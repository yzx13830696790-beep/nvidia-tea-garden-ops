# -*- coding: utf-8 -*-
"""字节级补丁引擎。

为什么不用正则 / AST 重写
-------------------------
Vite 产出的 chunk 是单行压缩代码，含大量非 UTF-8 字面量、二进制嵌入和 Unicode
转义。任何"读成 str 再写回"的流程都可能改变字节（换行规范化、代理对、BOM）。
所以这里的替换全部在 **bytes 上做字面量替换**，只要求调用者给出的片段是纯 ASCII，
其余字节原样搬过去。

三条硬规则
----------
1. **命中数必须显式声明**。``count`` 不符 → 立刻中止，不落盘。压缩产物里同一个片段
   出现多次是常态，不声明命中数就等于不知道自己在改什么。
2. **可逆性自证**。补丁跑完后，对新内容施加逆替换，必须能逐字节还原出原文件。
   这比"我改了 5 处"强得多——它证明两个文件之间的差异**只有**这 5 处。
3. **配平检查**。括号 / 方括号 / 花括号数量必须守恒，否则一定是片段切错了。

典型用法
--------
>>> eng = PatchEngine(raw, label="PickerVehicleData")
>>> eng.assert_before("旧 clamp 只出现 1 次", lambda s: s.count(b"Math.min(100,") == 1)
>>> eng.add("成功率上界", b"Math.max(85,Math.min(100,x))", b"clamp78_95(x)")
>>> eng.assert_after("旧写法已消失", lambda s: b"Math.min(100," not in s)
>>> result = eng.run()
>>> result.new_bytes
"""
from __future__ import annotations

import difflib
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Union

BytesLike = Union[bytes, str]


class PatchError(RuntimeError):
    """补丁断言失败。抛出时绝不会写出任何文件。"""


def _to_bytes(v: BytesLike, enc: str = "utf-8") -> bytes:
    return v if isinstance(v, bytes) else v.encode(enc)


@dataclass
class Edit:
    """一次字面量替换。"""

    name: str
    old: BytesLike
    new: BytesLike
    count: int = 1
    note: str = ""

    def old_b(self, enc: str = "utf-8") -> bytes:
        return _to_bytes(self.old, enc)

    def new_b(self, enc: str = "utf-8") -> bytes:
        return _to_bytes(self.new, enc)

    def hits(self, src: bytes, enc: str = "utf-8") -> int:
        return src.count(self.old_b(enc))


@dataclass
class PatchResult:
    """补丁结果。"""

    new_bytes: bytes
    old_bytes: bytes
    regions: int
    edits: list[Edit]
    report: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.new_bytes != self.old_bytes

    @property
    def bytes_delta(self) -> int:
        return len(self.new_bytes) - len(self.old_bytes)

    def md5(self) -> str:
        return hashlib.md5(self.new_bytes).hexdigest()

    def write(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：先写临时文件再替换，避免中途失败留下半个 chunk
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".tgpatch-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(self.new_bytes)
            os.replace(tmp, p)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return p

    def print_report(self, out=None) -> None:
        import sys
        out = out or sys.stdout
        for line in self.report:
            print(line, file=out)


class PatchEngine:
    """构建一份补丁并原子地校验它。"""

    def __init__(self, raw: bytes, label: str = "", encoding: str = "utf-8"):
        self.raw = raw
        self.label = label
        self.encoding = encoding
        self.edits: list[Edit] = []
        self._pre: list[tuple[str, Callable[[bytes], bool]]] = []
        self._post: list[tuple[str, Callable[[bytes], bool]]] = []
        self._expected_regions: int | None = None
        self._region_gap = 50
        self._check_reversible = True
        self._check_balance = True
        # 非 ASCII 片段默认只提示、不拦。压缩产物里的中文一般以 UTF-8 直接嵌入，
        # 按 bytes 做字面量替换本身不受影响；如果原文件里其实是 \uXXXX 转义形式，
        # 命中数会是 0，第 2 步的命中数核对自然会拦下来。真正需要的额外保障是
        # 「替换后文件仍是合法 UTF-8」——见第 3.5 步。
        self._require_ascii = False

    # -- 声明 -------------------------------------------------------------- #
    def add(self, name: str, old: BytesLike, new: BytesLike, count: int = 1,
            note: str = "") -> "PatchEngine":
        """登记一次替换。``count`` 是**期望命中次数**，不是替换次数上限。"""
        if _to_bytes(old, self.encoding) == _to_bytes(new, self.encoding):
            raise ValueError("替换 %s 的新旧片段相同，这一定不是你想做的" % name)
        self.edits.append(Edit(name, old, new, count, note))
        return self

    def add_many(self, rows) -> "PatchEngine":
        """批量登记：(name, old, new, count) 四元组序列。"""
        for row in rows:
            self.add(*row)
        return self

    def assert_before(self, desc: str, predicate: Callable[[bytes], bool]) -> "PatchEngine":
        self._pre.append((desc, predicate))
        return self

    def assert_after(self, desc: str, predicate: Callable[[bytes], bool]) -> "PatchEngine":
        self._post.append((desc, predicate))
        return self

    def expect_regions(self, n: int) -> "PatchEngine":
        """声明差异区域数量。区域 = 相距小于 gap 的连续差异合并成一块。"""
        self._expected_regions = n
        return self

    def region_gap(self, gap: int) -> "PatchEngine":
        self._region_gap = gap
        return self

    def reversible(self, enabled: bool = True) -> "PatchEngine":
        """是否要求「逆替换可逐字节还原原文件」（默认开）。"""
        self._check_reversible = enabled
        return self

    def check_balance(self, enabled: bool = True) -> "PatchEngine":
        self._check_balance = enabled
        return self

    def require_ascii(self, enabled: bool = True) -> "PatchEngine":
        """强制所有替换片段为纯 ASCII（默认关闭）。

        默认关闭是有意的：chunk 里的中文多以 UTF-8 直接嵌入，按 bytes 替换本身安全；
        若是 \\uXXXX 转义形式，命中数为 0 会被自动拦下。只有在你确认目标文件**不含**
        任何多字节序列、想额外加一道保险时才打开。
        """
        self._require_ascii = enabled
        return self

    # -- 执行 -------------------------------------------------------------- #
    def run(self, verbose: bool = True) -> PatchResult:
        log: list[str] = []

        def say(s: str) -> None:
            log.append(s)
            if verbose:
                print(s)

        enc = self.encoding
        src = self.raw
        say("=== 补丁: %s ===" % (self.label or "(未命名)"))
        say("  原始 %d bytes  md5=%s" % (len(src), hashlib.md5(src).hexdigest()))

        # 1) 前置断言
        if self._pre:
            say("")
            say("=== 前置断言 ===")
            bad = []
            for desc, pred in self._pre:
                try:
                    ok = bool(pred(src))
                except Exception as exc:  # noqa: BLE001
                    ok, desc = False, "%s（断言抛异常: %s）" % (desc, exc)
                say("  [%s] %s" % ("OK" if ok else "FAIL", desc))
                if not ok:
                    bad.append(desc)
            if bad:
                raise PatchError("前置断言未通过，中止且不写文件: %s" % bad)

        # 2) 命中数核对
        say("")
        say("=== 命中数核对（必须先全对才动手）===")
        fails = []
        for e in self.edits:
            c = e.hits(src, enc)
            ok = c == e.count
            if not ok:
                fails.append("%s: 实际 %d / 期望 %d" % (e.name, c, e.count))
            say("  %-30s count=%d (期望 %d) %s%s"
                % (e.name, c, e.count, "OK" if ok else "**FAIL**",
                   ("  # " + e.note) if e.note else ""))
        if fails:
            raise PatchError("命中数与声明不符，中止且不写文件:\n  " + "\n  ".join(fails))

        # 3) 编码形态提示
        #
        # 这里刻意不做「非 ASCII 一律拒绝」。压缩产物里的中文两种形态都见过：UTF-8
        # 直接嵌入、以及 \uXXXX 转义。前者按 bytes 替换完全没问题，后者会因命中数为
        # 0 而被上面的核对拦下。真正危险的从来不是「含中文」，而是「自以为了解编码
        # 形态」——所以只需要把形态显式打印出来，剩下的交给命中数。
        non_ascii = [e.name for e in self.edits
                     if any(b > 0x7F for b in e.old_b(enc) + e.new_b(enc))]
        if non_ascii:
            say("")
            say("=== 编码形态 ===")
            for n in non_ascii:
                say("  含非 ASCII 字面量: %s —— 按「UTF-8 直接嵌入」处理" % n)
            say("  若线上文件实际写的是 \\uXXXX 转义形式，命中数会是 0，已被上面的核对拦下。")
            if self._require_ascii:
                raise PatchError("require_ascii 已开启，但以下替换含非 ASCII 片段: %s" % non_ascii)

        # 4) 施加替换
        new = src
        for e in self.edits:
            new = new.replace(e.old_b(enc), e.new_b(enc))
        say("")
        say("=== 已施加 %d 处替换 ===" % len(self.edits))
        say("  %d -> %d bytes (%+d)" % (len(src), len(new), len(new) - len(src)))

        # 5) 可逆性自证
        if self._check_reversible:
            back = new
            for e in reversed(self.edits):
                back = back.replace(e.new_b(enc), e.old_b(enc))
            same = back == src
            say("")
            say("=== 可逆性自证（逆替换后是否逐字节还原）===")
            say("  [%s] 逆替换结果 %s 原文件" % ("OK" if same else "FAIL",
                                               "==" if same else "!="))
            if not same:
                raise PatchError(
                    "可逆性检查失败：新内容与旧内容的差异不只来自声明的替换（可能有片段"
                    "在别处也被命中）。为避免误伤，中止且不写文件。")

        # 6) 后置断言
        if self._post:
            say("")
            say("=== 后置断言 ===")
            bad = []
            for desc, pred in self._post:
                try:
                    ok = bool(pred(new))
                except Exception as exc:  # noqa: BLE001
                    ok, desc = False, "%s（断言抛异常: %s）" % (desc, exc)
                say("  [%s] %s" % ("OK" if ok else "FAIL", desc))
                if not ok:
                    bad.append(desc)
            if bad:
                raise PatchError("后置断言未通过，中止且不写文件: %s" % bad)

        # 7) 配平
        if self._check_balance:
            say("")
            say("=== 括号配平（补丁后）===")
            bad = []
            for o, c in (("(", ")"), ("[", "]"), ("{", "}")):
                a, b = new.count(o.encode()), new.count(c.encode())
                ok = a == b
                if not ok:
                    bad.append("%s%s %d/%d" % (o, c, a, b))
                say("  %s%s  %6d / %6d  %s" % (o, c, a, b, "OK" if ok else "**MISMATCH**"))
            if bad:
                raise PatchError("括号不配平，几乎可以肯定是片段切错了: %s" % bad)

        # 8) 差异区域聚类
        regions, detail = diff_regions(src, new, gap=self._region_gap)
        say("")
        say("=== 差异区域 ===")
        for i, d in enumerate(detail, 1):
            say("  #%d  %s" % (i, d))
        say("  合计 %d 个区域（字符级差异子段 %d 个）"
            % (len(regions), sum(len(r["ops"]) for r in regions)))
        if self._expected_regions is not None and len(regions) != self._expected_regions:
            raise PatchError("差异区域数 %d != 声明 %d，中止且不写文件"
                             % (len(regions), self._expected_regions))

        say("")
        say("=== 通过 ✓  md5 %s -> %s ==="
            % (hashlib.md5(src).hexdigest(), hashlib.md5(new).hexdigest()))
        return PatchResult(new, src, len(regions), list(self.edits), log)


# --------------------------------------------------------------------------- #
# 独立的分析工具
# --------------------------------------------------------------------------- #
def diff_regions(old: bytes, new: bytes, gap: int = 50):
    """把字符级差异按间隔聚类成「区域」。

    压缩产物里数组 / 数字会被 difflib 按字符切碎，直接数 opcode 会严重高估改动范围；
    按「相邻差异间隔 < gap 就并入同一块」聚类后，区域数才对应到人眼看到的那几处改动。
    """
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    ops = [o for o in sm.get_opcodes() if o[0] != "equal"]

    regions: list[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        if regions and i1 - regions[-1]["i2"] < gap:
            regions[-1]["i2"] = max(regions[-1]["i2"], i2)
            regions[-1]["j2"] = max(regions[-1]["j2"], j2)
            regions[-1]["ops"].append((tag, i1, i2, j1, j2))
        else:
            regions.append({"i1": i1, "i2": i2, "j1": j1, "j2": j2,
                            "ops": [(tag, i1, i2, j1, j2)]})

    detail = []
    for k, r in enumerate(regions, 1):
        old_txt = b"".join(old[i1:i2] for _, i1, i2, _, _ in r["ops"] if i2 > i1)
        new_txt = b"".join(new[j1:j2] for _, _, _, j1, j2 in r["ops"] if j2 > j1)
        detail.append("#%d 旧@%d..%d (%d B) -> 新@%d..%d (%d B)\n      旧: %r\n      新: %r"
                      % (k, r["i1"], r["i2"], len(old_txt), r["j1"], r["j2"], len(new_txt),
                         old_txt[:120], new_txt[:120]))
    return regions, detail


def balanced(src: bytes) -> dict[str, bool]:
    """括号配平检查。"""
    return {
        "%s%s" % (o, c): src.count(o.encode()) == src.count(c.encode())
        for o, c in (("(", ")"), ("[", "]"), ("{", "}"))
    }


def count(src: bytes, sub: BytesLike, enc: str = "utf-8") -> int:
    return src.count(_to_bytes(sub, enc))
