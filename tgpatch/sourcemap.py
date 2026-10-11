# -*- coding: utf-8 -*-
"""sourcemap 反查：从构建产物回到源码。

为什么需要它
------------
字节级补丁是在**压缩后的产物**上做替换，有两个绕不过去的短板：

1. ``locate`` 判断"哪个 chunk 属于哪个页面"靠的是入口文件里的 ``__vite__mapDeps``
   索引和路由字符串——一旦构建配置变了（比如改成多个入口、或者路由被拆散），
   这套推断就会失效。
2. 改动位置是"压缩产物第 N 个字节"，无法回答"这段代码原本写在源码的哪一行"。
   评审时没人能确认你改的是不是该改的地方。

而 Vite 生产构建默认就会产出 ``.js.map``。只要它还在（并且带 ``sourcesContent``），
上面两个问题都有确定答案：产物里的每一段代码都能精确映射回 ``src/`` 下的源文件与行号。

本模块只用标准库解析 Source Map v3，不引入任何依赖。

用法
----
    from tgpatch import sourcemap

    sm = sourcemap.SourceMap.load("dist/assets/PickerVehicleData-C_olpgXX.js.map")
    sm.sources                      # ['../../src/views/DeviceManagement/PickerVehicleData.vue']
    sm.original_source(0)           # 该源文件的完整内容（来自 sourcesContent）

    # 产物里搜到一段代码，反查它原本在哪
    pos = sm.lookup_text("Math.max(85,Math.min(100,")
    pos.source, pos.line, pos.column

    # 批量：整个 assets 目录的 chunk -> 源文件
    sourcemap.scan_dir("dist/assets")
    sourcemap.reverse_index("dist/assets")   # 源文件 -> 哪些 chunk 由它编译而来

注意
----
``.js.map`` 属于构建产物，通常不会随部署上线（本例线上 assets 目录里就没有 map）。
它更像是**开发期的对照物**：有它在，就能拿源码的正确位置去印证字节级补丁改对了没有。
"""
from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = [
    "SourceMapError", "Position", "SourceMap",
    "decode_vlq", "decode_mappings", "scan_dir", "reverse_index",
    "strip_query", "utf16_len", "find_source",
]

# Source Map v3 的 VLQ 字母表（base64 变体）
_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_B64_INDEX = {c: i for i, c in enumerate(_B64)}


class SourceMapError(ValueError):
    """sourcemap 解析失败。"""


@dataclass
class Position:
    """源码中的位置（行列均为 1 起始，方便直接对着编辑器看）。"""

    source: str
    line: int
    column: int
    name: Optional[str] = None

    def __str__(self) -> str:
        tail = "  (原名 %s)" % self.name if self.name else ""
        return "%s:%d:%d%s" % (self.source, self.line, self.column, tail)


# --------------------------------------------------------------------------- #
# VLQ 与 mappings 解码
# --------------------------------------------------------------------------- #
def decode_vlq(segment: str) -> List[int]:
    """解码一个 base64 VLQ 段，返回有符号整数列表。

    每个数字用 5 位一组、最高位作续位标记，最低位作符号位——这是 Source Map
    规范里"用可打印字符存任意整数"的做法。
    """
    values: List[int] = []
    shift = 0
    acc = 0
    for ch in segment:
        digit = _B64_INDEX.get(ch)
        if digit is None:
            raise SourceMapError("mappings 里出现非法 base64 字符 %r" % ch)
        acc += (digit & 31) << shift          # 低 5 位是数据
        if digit & 32:                        # 最高位=1 表示还有下一组
            shift += 5
            continue
        negative = acc & 1                    # 最低位是符号
        acc >>= 1
        values.append(-acc if negative else acc)
        acc = 0
        shift = 0
    if shift:
        raise SourceMapError("mappings 段以续位标记结尾，数据不完整: %r" % segment)
    return values


def decode_mappings(mappings: str) -> List[List[Tuple[int, int, int, int, int]]]:
    """把 ``mappings`` 字符串解成 ``[生成行][段] -> (gen_col, src_idx, src_line, src_col, name_idx)``。

    规范里除第一个字段外全部是**相对前一个段**的增量，所以这里做前缀和还原成绝对值。
    后两个字段（源码行列）是相对上一个**有映射的**段的，跨行也不重置。
    """
    lines: List[List[Tuple[int, int, int, int, int]]] = []
    src_idx = src_line = src_col = name_idx = 0
    for raw_line in mappings.split(";"):
        gen_col = 0
        segs: List[Tuple[int, int, int, int, int]] = []
        if raw_line:
            for raw_seg in raw_line.split(","):
                if not raw_seg:
                    continue
                v = decode_vlq(raw_seg)
                if len(v) not in (1, 4, 5):
                    raise SourceMapError("mappings 段字段数为 %d，应为 1/4/5" % len(v))
                gen_col += v[0]
                if len(v) == 1:               # 只有生成列，无源码信息
                    segs.append((gen_col, -1, -1, -1, -1))
                    continue
                src_idx += v[1]
                src_line += v[2]
                src_col += v[3]
                if len(v) == 5:
                    name_idx += v[4]
                segs.append((gen_col, src_idx, src_line, src_col,
                             name_idx if len(v) == 5 else -1))
        lines.append(segs)
    return lines


def strip_query(src: str) -> str:
    """去掉 Vite 常加在源路径末尾的 ``?vue&type=script`` 之类查询串。"""
    return src.split("?", 1)[0]


def utf16_len(s: str) -> int:
    """字符串占多少个 UTF-16 码元。

    Source Map v3 规定**列号以 UTF-16 码元计**，而不是字节也不是码点。
    对 BMP 内的字符（汉字都在这里）码点数就等于码元数，但补充平面字符
    （emoji、部分生僻字）一个码点占两个码元，必须单独算。
    """
    return len(s.encode("utf-16-le")) // 2


# --------------------------------------------------------------------------- #
# SourceMap
# --------------------------------------------------------------------------- #
@dataclass
class SourceMap:
    """一个 ``.js.map`` 文件的解析结果。"""

    path: Optional[Path] = None
    file: str = ""
    sources: List[str] = field(default_factory=list)
    sources_content: List[Optional[str]] = field(default_factory=list)
    names: List[str] = field(default_factory=list)
    mappings: str = ""
    _segments: Optional[List[List[Tuple[int, int, int, int, int]]]] = None

    # -- 解析 ------------------------------------------------------------- #
    @classmethod
    def load(cls, path) -> "SourceMap":
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except OSError as e:
            raise SourceMapError("读不到 sourcemap %s: %s" % (p, e)) from e
        except json.JSONDecodeError as e:
            raise SourceMapError("sourcemap %s 不是合法 JSON: %s" % (p, e)) from e
        return cls.from_dict(data, path=p)

    @classmethod
    def from_dict(cls, data: dict, path=None) -> "SourceMap":
        if not isinstance(data, dict):
            raise SourceMapError("sourcemap 顶层应为对象")
        if data.get("version") != 3:
            raise SourceMapError("只支持 Source Map v3，实际 version=%r" % data.get("version"))
        sources = list(data.get("sources") or [])
        content = list(data.get("sourcesContent") or [])
        # sourcesContent 可能缺项，补齐到等长，避免下标错位
        if len(content) < len(sources):
            content += [None] * (len(sources) - len(content))
        return cls(
            path=Path(path) if path else None,
            file=str(data.get("file") or ""),
            sources=sources,
            sources_content=content,
            names=list(data.get("names") or []),
            mappings=str(data.get("mappings") or ""),
        )

    # -- 源文件 ----------------------------------------------------------- #
    def source_relpath(self, index: int) -> str:
        """仓库相对路径，例如 ``src/views/DeviceManagement/PickerVehicleData.vue``。

        Vite 写进 ``sources`` 的是相对 **map 文件所在目录** 的路径（``dist/assets``），
        所以前面会挂两个 ``../``。这里把它们剥掉，得到可以直接对着仓库根看的路径。
        """
        return _squeeze(self._raw_source(index))

    def source_path(self, index: int) -> str:
        """绝对/完整路径：拿 map 所在目录去解析 ``../``。

        无法解析时（map 不是从磁盘读的）退化成与 :meth:`source_relpath` 相同的结果。
        """
        raw = self._raw_source(index)
        if self.path is None:
            return _squeeze(raw)
        base = str(self.path.parent).replace("\\", "/")
        return posixpath.normpath(posixpath.join(base, raw))

    def _raw_source(self, index: int) -> str:
        if not 0 <= index < len(self.sources):
            raise SourceMapError("源文件下标越界: %d（共 %d 个）" % (index, len(self.sources)))
        return strip_query(self.sources[index]).replace("\\", "/")

    def original_source(self, index: int) -> Optional[str]:
        """源文件原文（来自 sourcesContent，可能为空）。"""
        if 0 <= index < len(self.sources_content):
            return self.sources_content[index]
        return None

    def has_content(self) -> bool:
        return any(c for c in self.sources_content)

    def unique_sources(self) -> List[str]:
        seen: Dict[str, None] = {}
        for i in range(len(self.sources)):
            seen.setdefault(self.source_relpath(i), None)
        return list(seen)

    # -- 位置反查 --------------------------------------------------------- #
    @property
    def segments(self) -> List[List[Tuple[int, int, int, int, int]]]:
        if self._segments is None:
            self._segments = decode_mappings(self.mappings)
        return self._segments

    def original_position(self, gen_line: int, gen_col: int) -> Optional[Position]:
        """产物中的 (行, 列) -> 源码中的位置。两者都是 **0 起始**。

        列号按 Source Map 规范以 **UTF-16 码元** 计（不是字节——压缩产物里
        混着中文时两者差异极大，会让结果整体偏移）。

        取该行中"生成列 <= 给定列"的最后一个段——这正是一般调试器做的事：
        压缩后一行里塞了很多段，落在某个段之后、下一个段之前，就归属该段。
        """
        if not 0 <= gen_line < len(self.segments):
            return None
        best: Optional[Tuple[int, int, int, int, int]] = None
        for seg in self.segments[gen_line]:
            if seg[0] > gen_col:
                break
            if seg[1] >= 0:                       # 只认真正带源码信息的段
                best = seg
        if best is None:
            return None
        _, src_idx, src_line, src_col, name_idx = best
        name = self.names[name_idx] if 0 <= name_idx < len(self.names) else None
        # 规范里是 0 起始，转成 1 起始便于阅读
        return Position(source=self.source_relpath(src_idx),
                        line=src_line + 1, column=src_col + 1, name=name)

    @property
    def code_path(self) -> Optional[Path]:
        """对应的产物文件（``.js.map`` 去掉 ``.map``）。"""
        if self.path is None:
            return None
        s = str(self.path)
        return Path(s[:-4]) if s.endswith(".map") else self.path

    def lookup_text(self, needle: str, *, code_path=None,
                    encoding: str = "utf-8") -> Optional[Position]:
        """在**产物文本**里搜一段字符串，返回它在源码里的位置。

        这是本模块最实用的入口：字节级补丁总是先定位到 "``Math.max(85,Math.min(100,``
        出现在产物的什么位置"，用这个方法立刻知道它对应源码的哪一行。

        两个必须注意的点：

        * 搜的是 ``.js`` 而不是 ``.map`` —— ``.map`` 里的 ``sourcesContent`` 是
          未压缩的源码，在它里面搜压缩形态的串永远搜不到。
        * 列号先按**字符**找到位置，再折算成 UTF-16 码元，**不能**直接用字节偏移。
          压缩产物里塞满中文字面量时，字节偏移会比真实列号大出几千，
          反查出来的源码行会整体漂移（这个 bug 在纯 ASCII 文件上不会暴露）。
        """
        code_file = Path(code_path) if code_path else self.code_path
        if code_file is None:
            raise SourceMapError("lookup_text 需要产物路径：给 SourceMap 带上 path，"
                                 "或用 code_path= 显式指定")
        text = Path(code_file).read_text(encoding=encoding, errors="replace")
        idx = text.find(needle)
        if idx < 0:
            return None
        before = text[:idx]
        gen_line = before.count("\n")
        line_prefix = before[before.rfind("\n") + 1:]
        gen_col = utf16_len(line_prefix)
        return self.original_position(gen_line, gen_col)

    # -- 输出 ------------------------------------------------------------- #
    def describe(self) -> str:
        lines = ["file      : %s" % (self.file or "(未声明)"),
                 "源文件数  : %d" % len(self.sources),
                 "含源内容  : %s" % ("是" if self.has_content() else "否"),
                 "映射段总数: %d" % sum(len(s) for s in self.segments)]
        return "\n".join(lines)


def _squeeze(raw: str) -> str:
    """``../../src/views/X.vue`` -> ``src/views/X.vue``。

    刻意用纯文本处理而不是 ``os.path.normpath``：在 Windows 上后者会把 ``/`` 换成
    ``\\``，而源路径是构建时由 POSIX 工具链写进去的，统一用 ``/`` 更稳定。
    ``..`` 只会出现在开头（Vite 指向 src 的路径），把它们剥掉即可。
    """
    parts: List[str] = []
    for seg in raw.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            continue                      # 开头的 .. 直接丢弃
        parts.append(seg)
    return "/".join(parts) if parts else raw


# --------------------------------------------------------------------------- #
# 目录级扫描
# --------------------------------------------------------------------------- #
def iter_maps(assets_dir) -> Iterable[Path]:
    """按文件名排序产出目录下所有 ``.js.map``（排除 ``.css.map``）。"""
    d = Path(assets_dir)
    return sorted(p for p in d.glob("*.js.map") if p.is_file())


def scan_dir(assets_dir) -> Dict[str, List[str]]:
    """扫描一个 assets 目录，返回 ``chunk 文件名 -> [源文件路径]``。

    chunk 名取 ``.map`` 里的 ``file`` 字段（没有就从文件名反推），保证与浏览器
    实际加载的文件名一致。
    """
    out: Dict[str, List[str]] = {}
    for mp in iter_maps(assets_dir):
        try:
            sm = SourceMap.load(mp)
        except SourceMapError:
            continue
        chunk = sm.file or mp.name[:-len(".map")]
        out[chunk] = sm.unique_sources()
    return out


def reverse_index(assets_dir) -> Dict[str, List[str]]:
    """反向索引：源文件 -> 由它编译出的 chunk 列表。

    用途：给定一个 ``.vue``，立刻知道改动会落到哪几个产物文件上——也就是
    部署时要同步替换哪几个 chunk。多入口构建下一个源文件可能出现在多个 chunk 里。
    """
    rev: Dict[str, List[str]] = {}
    for chunk, sources in scan_dir(assets_dir).items():
        for src in sources:
            rev.setdefault(src, []).append(chunk)
    for chunks in rev.values():
        chunks.sort()
    return rev


def find_source(assets_dir, needle: str) -> Dict[str, List[str]]:
    """按子串查源文件（例如 ``find_source(d, "TaskScheduling")``）。"""
    return {src: chunks for src, chunks in reverse_index(assets_dir).items()
            if needle.lower() in src.lower()}
