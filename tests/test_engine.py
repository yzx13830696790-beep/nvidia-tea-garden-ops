# -*- coding: utf-8 -*-
"""引擎自检：**不依赖任何专有产物**。

为什么不直接用 test_pipeline.py
------------------------------
`tests/test_pipeline.py` 的夹具是线上真实 chunk，属于第三方构建产物、不入库。所以任何
克隆本仓库的人（以及 CI）跑它只会看到一行「跳过」——等于没有测试。

本文件用**合成字节**把引擎的每条硬规则都钉一遍。它才是 CI 实际执行的内容，也是判断
「这次改动有没有把护栏拆掉」的第一道关。

覆盖范围
--------
1. 入口识别：`index.html` 里第一个 `<script>` 往往是 `/cesium/Cesium.js`，必须跳过
2. `__vite__mapDeps` / 路由 / 路由块边界法解析
3. 活跃副本判定：同名多副本 + 僵尸副本识别
4. 补丁引擎五条硬规则：命中数、可逆性、配平、区域数、原子写
5. 反射式回弹 vs clamp：把「冻在边界」这个真实 bug 变成一条可回归的断言
6. sourcemap 反查：VLQ 往返、mappings 增量解码、源路径归一、位置反查
   （含「列号按 UTF-16 码元而非字节」这条曾经踩过的坑）
7. 全仓库 Python 语法 + ESM 语法

运行：
    python tests/test_engine.py

CI 里设 `TG_REQUIRE_NODE=1`，此时缺 Node 会判失败而不是静默跳过。
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tgpatch import locate, patch, sourcemap, validate, verify  # noqa: E402
from tgpatch.patch import PatchEngine, PatchError  # noqa: E402

# CI 上把「环境缺失」当失败，避免测试静默空转
REQUIRE_NODE = os.environ.get("TG_REQUIRE_NODE") == "1"

results: list[tuple[bool, str]] = []


def ck(ok: bool, desc: str, detail: str = "") -> None:
    results.append((bool(ok), desc))
    print("  [%s] %s%s" % ("OK" if ok else "FAIL", desc, ("   " + detail) if detail else ""))


def section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def raises(fn, exc) -> tuple[bool, str]:
    """执行 fn，期望抛出 exc。返回 (是否符合预期, 说明)。"""
    try:
        fn()
    except exc as e:
        return True, type(e).__name__
    except Exception as e:  # noqa: BLE001
        return False, "抛了 %s 而非 %s" % (type(e).__name__, exc.__name__)
    return False, "没有抛异常"


# --------------------------------------------------------------------------- #
# 1. 入口识别
# --------------------------------------------------------------------------- #
def t_entry() -> None:
    section("1) 入口识别 —— index.html 里第一个 <script> 是 Cesium，必须跳过")

    html_both = ('<script src="/cesium/Cesium.js"></script>'
                 '<script src="/assets/index-DzrFuFTi.js"></script>')
    ck(locate.find_entry(html_both) == "index-DzrFuFTi.js",
       "有 Cesium 时仍取到 index-*.js", str(locate.find_entry(html_both)))

    ck(locate.find_entry('<script src="/cesium/Cesium.js"></script>') is None,
       "只有 Cesium 时返回 None（而不是把 Cesium 当入口）")

    ck(locate.find_entry('<script src="/cesium/Cesium.js"></script>'
                         '<script src="/assets/main-abc.js"></script>') == "main-abc.js",
       "无 index-* 时退化为第一个非 cesium 脚本")

    ck(locate.find_entry('<script src="/assets/index-DzrFuFTi.js"></script>')
       == "index-DzrFuFTi.js",
       "绝对/相对路径都能抠出文件名")


# --------------------------------------------------------------------------- #
# 2. 路由解析
# --------------------------------------------------------------------------- #
ENTRY_SRC = (
    'var m={};m.f=["assets/Home-11111111.js","assets/Home-a-22222222.js",'
    '"assets/Task-33333333.js"];'
    'const R=[{path:"/home",component:()=>import("./Home-11111111.js")},'
    '{path:"/task",component:__vite__mapDeps([2])}];'
)


def t_routes() -> None:
    section("2) 路由 / mapDeps 解析")

    ck(locate.parse_map_deps(ENTRY_SRC) ==
       ["Home-11111111.js", "Home-a-22222222.js", "Task-33333333.js"],
       "mapDeps 数组按序解析", str(locate.parse_map_deps(ENTRY_SRC)))

    # 只有带 mapDeps 调用的路由才会被列出——静态 import 的路由不在此列
    ck(locate.parse_routes(ENTRY_SRC) == [("/task", ["Task-33333333.js"])],
       "路由 -> chunk 映射（只取懒加载路由）", str(locate.parse_routes(ENTRY_SRC)))

    ck(locate.chunks_of_route(ENTRY_SRC, "/home") == ["Home-11111111.js"],
       "路由块边界法：/home 块内的静态 import 被提取")
    ck(locate.chunks_of_route(ENTRY_SRC, "/task") == [],
       "/task 块内无静态 import，返回空（不会把下一个路由的串进来）")

    ck(raises(lambda: locate.route_block(ENTRY_SRC, "/nope"), KeyError)[0],
       "未知路由抛 KeyError 而不是静默返回空块")

    # 顶层路由块必须在下一条路由处截断，否则会把整份入口当成该路由的依赖
    blk = locate.route_block(ENTRY_SRC, "/home")
    ck("/task" not in blk, "块在下一条路由处正确截断", "%d bytes" % len(blk))


# --------------------------------------------------------------------------- #
# 3. 活跃副本判定
# --------------------------------------------------------------------------- #
def t_versions() -> None:
    section("3) 活跃副本判定 —— 同名多副本时，只有引用链可达的那份是活的")

    sources = {
        "index-aaaaaaaa.js": 'import "./PickerVehicleData-BBBBBBBB.js";',
        "PickerVehicleData-BBBBBBBB.js": "const x=1;",
        "PickerVehicleData-CCCCCCCC.js": "const y=2;",
        "PickerVehicleData-DDDDDDDD.js": "const z=3;",
    }
    r = locate.pick_active(sources, "index-aaaaaaaa.js", "PickerVehicleData")
    ck(len(r["versions"]) == 3, "三个副本都被识别", str(len(r["versions"])))
    ck(r["active"] == "PickerVehicleData-BBBBBBBB.js",
       "活跃副本 = 引用链可达的那份", str(r["active"]))
    ck(sorted(r["zombies"]) == ["PickerVehicleData-CCCCCCCC.js",
                                "PickerVehicleData-DDDDDDDD.js"],
       "另外两份判为僵尸副本", str(r["zombies"]))
    ck("depth=1" in r["reason"], "给出判定依据（depth）", r["reason"])

    ck(locate.pick_active(sources, "index-aaaaaaaa.js", "NoSuchModule")["active"] is None,
       "模块不存在时 active 为 None，不抛异常")

    # 入口不可达（例如动态 import 拼接了字符串）时退化为「被引用最多者」，
    # 必须给出 warning 级别的说明，而不是假装确定
    orphan = {"index-aaaaaaaa.js": "var a=1;", "M-11111111.js": "x", "M-22222222.js": "y"}
    o = locate.pick_active(orphan, "index-aaaaaaaa.js", "M")
    ck(o["active"] is not None and len(o["zombies"]) == 1 and "退化" in o["reason"],
       "不可达时退化为引用计数并显式说明", o["reason"])


# --------------------------------------------------------------------------- #
# 4. 补丁引擎五条硬规则
# --------------------------------------------------------------------------- #
PAD = b"x" * 200
TWO_HITS = b"var a=f(1);" + PAD + b"var b=f(2);" + PAD + b"var c=g(3);"
TMP = Path(tempfile.mkdtemp(prefix="tgpatch-selftest-"))


def t_engine() -> None:
    section("4) 补丁引擎 —— 五条硬规则")

    # 4.1 正常路径
    eng = PatchEngine(TWO_HITS, label="selftest")
    eng.assert_before("旧片段恰好 2 处", lambda s: s.count(b"f(") == 2)
    eng.add("f -> h", b"f(", b"h(", count=2)
    eng.assert_after("新片段出现 2 次", lambda s: s.count(b"h(") == 2)
    eng.expect_regions(2)
    res = eng.run(verbose=False)
    ck(res.changed and res.bytes_delta == 0, "等长替换：内容变了、长度不变",
       "delta=%d" % res.bytes_delta)
    ck(res.regions == 2, "区域数 == 声明的 2 处改动", "regions=%d" % res.regions)
    ck(res.new_bytes.count(b"h(") == 2 and b"f(" not in res.new_bytes, "替换结果正确")

    # 4.2 命中数不符 -> 中止，且不落盘
    out = TMP / "should_not_exist.js"
    eng2 = PatchEngine(TWO_HITS, label="count-mismatch")
    eng2.add("声明 1 处，实际 2 处", b"f(", b"h(", count=1)
    ok, why = raises(lambda: eng2.run(verbose=False).write(out), PatchError)
    ck(ok, "命中数与声明不符时中止（不看成败、只看声明）", why)
    ck(not out.exists(), "中止时不写出任何文件")

    # 4.3 可逆性自证 -> 抓住「新片段在别处也存在」的误伤
    over = PatchEngine(b"A() ; Z() ;", label="over-broad")
    over.add("A() -> Z()", b"A()", b"Z()", count=1)
    ok, why = raises(lambda: over.run(verbose=False), PatchError)
    ck(ok, "逆替换无法还原原文件时中止（差异不只来自声明的替换）", why)

    # 4.4 括号配平
    unbal = PatchEngine(b"f(1)", label="unbalanced")
    unbal.add("吃掉一个右括号", b"f(1)", b"g(1", count=1)
    ok, why = raises(lambda: unbal.run(verbose=False), PatchError)
    ck(ok, "括号不配平时中止（几乎一定是片段切错了）", why)

    # 4.5 区域数与声明不符
    reg = PatchEngine(b"var a=f(1);", label="regions")
    reg.add("f -> h", b"f(", b"h(", count=1)
    reg.expect_regions(7)
    ok, why = raises(lambda: reg.run(verbose=False), PatchError)
    ck(ok, "区域数 != 声明时中止", why)

    # 4.6 前置 / 后置断言
    pre = PatchEngine(b"xxx", label="pre")
    pre.assert_before("这句一定为假", lambda s: b"yyy" in s)
    pre.add("t", b"x", b"y", count=3)
    ck(raises(lambda: pre.run(verbose=False), PatchError)[0], "前置断言不过 -> 中止")

    post = PatchEngine(b"xxx", label="post")
    post.add("t", b"x", b"y", count=3)
    post.assert_after("这句一定为假", lambda s: False)
    ck(raises(lambda: post.run(verbose=False), PatchError)[0], "后置断言不过 -> 中止")

    # 4.7 原子写：内容正确 + 不留临时文件
    dst = TMP / "atomic.js"
    res.write(dst)
    ck(dst.read_bytes() == res.new_bytes, "原子写：落盘内容与结果一致")
    ck(not [p for p in TMP.iterdir() if p.name.startswith(".tgpatch-")],
       "原子写：不留 .tgpatch-*.tmp 残骸")

    # 4.8 add() 拒绝新旧相同（这种替换等于什么都没做）
    ck(raises(lambda: PatchEngine(b"x").add("noop", b"a", b"a"), ValueError)[0],
       "add() 拒绝旧新片段相同的替换")

    # 4.9 非 ASCII：默认放行（UTF-8 直接嵌入），require_ascii 时拒绝
    raw_cn = "名字:采摘".encode("utf-8")
    eng_cn = PatchEngine(raw_cn)
    eng_cn.add("中文替换", "采摘".encode("utf-8"), "收割".encode("utf-8"), count=1)
    r_cn = eng_cn.run(verbose=False)
    ck(r_cn.new_bytes == "名字:收割".encode("utf-8"), "非 ASCII 字面量按 bytes 安全替换")

    strict = PatchEngine(raw_cn)
    strict.require_ascii()
    strict.add("中文替换", "采摘".encode("utf-8"), "收割".encode("utf-8"), count=1)
    ck(raises(lambda: strict.run(verbose=False), PatchError)[0],
       "require_ascii 开启后拒绝非 ASCII 片段")

    # 4.10 工具函数
    ck(patch.count(TWO_HITS, b"f(") == 2, "patch.count 计数正确")

    # 注意：balanced() 返回的是 dict，`all(dict)` 遍历的是**键**（非空字符串恒为真），
    # 所以必须 all(d.values())——这里刻意把两者都钉住，免得以后自己踩回去。
    bal_ok = patch.balanced(b"a(b[c{d}])")
    ck(bal_ok == {"()": True, "[]": True, "{}": True} and all(bal_ok.values()),
       "patch.balanced：配平返回全 True", str(bal_ok))
    bal_bad = patch.balanced(b"a(b[c{d}]")
    ck(bal_bad["()"] is False and bal_bad["[]"] and bal_bad["{}"],
       "patch.balanced：能定位到具体是哪一对不配平", str(bal_bad))
    ck(all(bal_bad) is True and all(bal_bad.values()) is False,
       "all(字典) 遍历键 —— 调用方要用 all(...values())", "陷阱已记录")

    # 4.11 区域聚类：间隔小于 gap 的差异会被合并
    near_old, near_new = b"aaaa" + b"x" * 10 + b"bbbb", b"aaaa" + b"x" * 10 + b"cccc"
    ck(len(patch.diff_regions(near_old, near_new, gap=50)[0]) == 1,
       "相邻差异合并为 1 个区域")
    ck(len(patch.diff_regions(TWO_HITS, res.new_bytes, gap=50)[0]) == 2,
       "相距 200+ 字节的差异算 2 个区域")


# --------------------------------------------------------------------------- #
# 5. 反射式回弹 vs clamp
# --------------------------------------------------------------------------- #
def clamp_walk(start: float, step: float, lo: float, hi: float,
               steps: int, seed: int) -> int:
    """对照组：直接 clamp 到边界（真实 bug 的写法），返回最长「贴边」连续点数。"""
    rng = random.Random(seed)
    v, run, mx = start, 0, 0
    for _ in range(steps):
        v = max(lo, min(hi, v + (rng.random() * 2 - 1) * step))
        if v > hi - 0.05 or v < lo + 0.05:
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    return mx


def t_walk() -> None:
    section("5) 反射式回弹 —— 把「冻在边界像死机」变成可回归的断言")

    ck(verify.reflect(96, 78, 95) == 94, "越上界回弹：96 -> 94")
    ck(verify.reflect(77, 78, 95) == 79, "越下界回弹：77 -> 79")
    ck(verify.reflect(90, 78, 95) == 90, "界内不动")

    lo, hi, step, steps, seed = 78, 95, 5.0, 20000, 7
    st = verify.simulate_walk(91.4, step, lo, hi, steps, seed)
    ck(st["min"] >= lo - 1e-9 and st["max"] <= hi + 1e-9,
       "永不越界", "min=%.4f max=%.4f" % (st["min"], st["max"]))
    ck(st["span"] > 0.9 * (hi - lo), "取值铺满整个区间（没退化成小范围抖动）",
       "span=%.2f / %.2f" % (st["span"], hi - lo))
    ck(st["distinct_rounded"] > 100, "保留一位小数后取值足够多样",
       "distinct=%d" % st["distinct_rounded"])

    cmx = clamp_walk(91.4, step, lo, hi, steps, seed)
    ck(st["max_edge_run"] < cmx,
       "最长贴边连续点数显著优于 clamp（这就是当初那个 bug）",
       "reflect=%d  clamp=%d" % (st["max_edge_run"], cmx))
    ck(st["max_edge_run"] <= 5, "反射式回弹不会长时间滞留在边界",
       "max_edge_run=%d" % st["max_edge_run"])

    # 端到端阈值不能靠猜：先算失败概率再定阈值，否则 CI 上会随机红灯
    p = verify.failure_probability(step, lo, hi, 0.5, 3, trials=300, seed=1)
    ck(isinstance(p, float) and 0.0 <= p <= 1.0, "failure_probability 返回合法概率",
       "p=%.4f" % p)


# --------------------------------------------------------------------------- #
# 6. sourcemap 反查（产物 -> 源码）
# --------------------------------------------------------------------------- #
def _vlq_encode(values) -> str:
    """把整数列表编成 base64 VLQ——测试里用来自造 mappings 字符串。

    有了它才能对 `decode_vlq` 做往返断言，而不是只对比几个硬编码的期望值。
    """
    out = ""
    for v in values:
        x = (abs(v) << 1) | (1 if v < 0 else 0)
        while True:
            digit = x & 31
            x >>= 5
            if x:
                digit |= 32
            out += sourcemap._B64[digit]
            if not x:
                break
    return out


def _make_map(tmp: Path, stem: str, sources, contents, mappings, file=None) -> Path:
    import json as _json
    code = tmp / (stem + ".js")
    if not code.exists():
        code.write_text("/* placeholder */\n", encoding="utf-8")
    mp = tmp / (stem + ".js.map")
    mp.write_text(_json.dumps({
        "version": 3,
        "file": file or (stem + ".js"),
        "sources": list(sources),
        "sourcesContent": list(contents),
        "names": [],
        "mappings": mappings,
    }, ensure_ascii=False), encoding="utf-8")
    return mp


def t_sourcemap() -> None:
    section("6) sourcemap 反查 —— 产物位置如何映射回源码")

    # 6.1 VLQ 编解码往返
    ck(sourcemap.decode_vlq("AAAA") == [0, 0, 0, 0], "decode_vlq('AAAA') == 4 个 0")
    ck(sourcemap.decode_vlq("gB") == [16], "decode_vlq('gB') == 16（跨字节）")
    for vals in ([0], [1], [-1], [16], [-16], [31], [-1000], [4, 0, 1, 0], [0, 0, 0, 0, 0]):
        enc = _vlq_encode(vals)
        ck(sourcemap.decode_vlq(enc) == vals, "VLQ 往返 %s" % (vals,), enc)
    ok, name = raises(lambda: sourcemap.decode_vlq("A!"), sourcemap.SourceMapError)
    ck(ok, "VLQ 遇到非法字符报错", name)
    ok, name = raises(lambda: sourcemap.decode_vlq("g"), sourcemap.SourceMapError)
    ck(ok, "VLQ 以续位结尾报错（数据不完整）", name)

    # 6.2 mappings 解码：除首字段外都是相对前一段的增量
    segs = sourcemap.decode_mappings("AAAA;AACA")
    ck(len(segs) == 2, "mappings 按 ; 切成 2 个生成行")
    ck(segs[0] == [(0, 0, 0, 0, -1)], "第 0 行 1 个段，指向源码 0:0")
    ck(segs[1] == [(0, 0, 1, 0, -1)], "第 1 行 src_line 递增到 1")

    # 只有生成列的单字段段不改变源码状态（规范如此，最容易写错的一条）
    segs2 = sourcemap.decode_mappings("AAAA," + _vlq_encode([4]) + "," + _vlq_encode([4, 0, 1, 0]))
    ck([s[0] for s in segs2[0]] == [0, 4, 8], "单字段段只推进生成列")
    ck(segs2[0][1][1] == -1 and segs2[0][2][2] == 1, "单字段段不污染 src_idx/src_line")

    ok, name = raises(lambda: sourcemap.SourceMap.from_dict({"version": 2}),
                      sourcemap.SourceMapError)
    ck(ok, "非 v3 的 sourcemap 报错", name)

    # 6.3 源路径归一
    ck(sourcemap.strip_query("X.vue?vue&type=script") == "X.vue", "strip_query 去掉查询串")
    ck(sourcemap.utf16_len("中文") == 2, "utf16_len 汉字各占 1 个码元")
    ck(sourcemap.utf16_len("\U0001d11e") == 2, "utf16_len 补充平面字符占 2 个码元")

    tmp = Path(tempfile.mkdtemp(prefix="tgsm-"))
    try:
        # 6.4 位置反查：列号必须按 UTF-16 码元算
        #
        # 造一行 `中文字符NEEDLE`：NEEDLE 在第 4 个字符处（UTF-16 列 4），
        # 但字节偏移是 12（汉字 3 字节 × 4）。mappings 里放三个段
        # （列 0 -> 源码行 0、列 4 -> 行 1、列 8 -> 行 2），于是：
        #   按码元算列 -> 命中第 2 段 -> 源码行 2（1 起始）
        #   按字节算列 -> 命中第 3 段 -> 源码行 3（错）
        gen = "中文字符NEEDLE"
        code_file = tmp / "utf16.js"
        code_file.write_text(gen + "\n", encoding="utf-8")
        mappings = ",".join([
            _vlq_encode([0, 0, 0, 0]),          # 列 0  -> 源码 0:0
            _vlq_encode([4, 0, 1, 0]),          # 列 4  -> 源码 1:0
            _vlq_encode([4, 0, 1, 0]),          # 列 8  -> 源码 2:0
        ])
        mp = _make_map(tmp, "utf16", ["../../src/A.vue"], ["l1\nl2\nl3\n"], mappings)
        sm = sourcemap.SourceMap.load(mp)
        ck(sm.source_relpath(0) == "src/A.vue", "source_relpath 剥掉 ../", sm.source_relpath(0))
        ck(sm.original_source(0) == "l1\nl2\nl3\n", "original_source 取回源内容")
        ck(sm.has_content(), "has_content 识别 sourcesContent 存在")
        p = sm.lookup_text("NEEDLE")
        ck(p is not None and p.line == 2,
           "中文行：列号按 UTF-16 码元而非字节", str(p))
        ck(p is not None and p.source == "src/A.vue" and p.column == 1,
           "反查带回源文件与列号", str(p))
        ck(sm.lookup_text("不存在的片段") is None, "搜不到时返回 None")
        ck(sm.original_position(99, 0) is None, "生成行越界返回 None")
        ck(sm.original_position(0, 0) is not None, "列 0 有映射")

        # 纯 ASCII 行上字节列与码元列一致（当初这个 bug 就是在这里被漏掉的）
        code_file.write_text("abcdefNEEDLE\n", encoding="utf-8")
        mp2 = _make_map(tmp, "utf16", ["../../src/A.vue"], ["l1\nl2\nl3\n"], mappings)
        ck(sourcemap.SourceMap.load(mp2).lookup_text("NEEDLE").line == 2,
           "ASCII 行同样命中源码行 2")

        # 6.5 目录级扫描与反向索引（放到独立子目录，避免被上面的 utf16.js 干扰）
        sub = tmp / "scan"
        sub.mkdir()
        _make_map(sub, "c1", ["../../src/a.vue", "../../src/b.vue"], ["a", "b"], "")
        _make_map(sub, "c2", ["../../src/b.vue"], ["b"], "")
        table = sourcemap.scan_dir(sub)
        ck(set(table) == {"c1.js", "c2.js"}, "scan_dir 扫到两个 chunk", str(sorted(table)))
        ck(table["c1.js"] == ["src/a.vue", "src/b.vue"],
           "scan_dir: chunk -> 多个源文件", str(table.get("c1.js")))
        ck(table.get("c2.js") == ["src/b.vue"], "scan_dir: 单源文件 chunk")
        rev = sourcemap.reverse_index(sub)
        ck(rev.get("src/b.vue") == ["c1.js", "c2.js"],
           "reverse_index: 一个源文件出现在两个 chunk 里", str(rev.get("src/b.vue")))
        ck(sourcemap.find_source(sub, "A.VUE") == {"src/a.vue": ["c1.js"]},
           "find_source 大小写不敏感", str(sourcemap.find_source(sub, "A.VUE")))
        ck(sourcemap.find_source(sub, "b.vue") == {"src/b.vue": ["c1.js", "c2.js"]},
           "find_source 能列出多个 chunk", str(sourcemap.find_source(sub, "b.vue")))
        ck(sourcemap.SourceMap.load(mp2).code_path == tmp / "utf16.js",
           "code_path 由 .js.map 推出 .js")

        # 6.6 sourcesContent 缺失不应崩
        import json as _json
        p3 = tmp / "nocontentA.js.map"
        p3.write_text(_json.dumps({
            "version": 3, "file": "nocontentA.js",
            "sources": ["../../src/a.vue"], "names": [], "mappings": "",
        }), encoding="utf-8")
        sm3 = sourcemap.SourceMap.load(p3)
        ck(sm3.original_source(0) is None and not sm3.has_content(),
           "缺 sourcesContent 时返回 None 而不抛异常")
        ck(sm3.unique_sources() == ["src/a.vue"], "缺内容时源路径仍可用")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 7. 语法自检
# --------------------------------------------------------------------------- #
def t_syntax() -> None:
    section("7) 语法自检")

    # 6.1 全仓库 Python
    bad, n = [], 0
    skip = {"__pycache__", ".venv", "venv", "out", "fixtures", ".git"}
    for p in sorted(ROOT.rglob("*.py")):
        if skip & set(p.parts):
            continue
        n += 1
        try:
            compile(p.read_text(encoding="utf-8"), str(p), "exec")
        except SyntaxError as e:  # noqa: PERF203
            bad.append("%s: %s" % (p.relative_to(ROOT), e))
    ck(not bad, "全仓库 %d 个 .py 文件可编译" % n, "; ".join(bad[:3]))

    # 6.2 ESM / CJS（需要 Node）
    targets = sorted(ROOT.glob("cases/*/e2e.js")) + \
        sorted(ROOT.glob("scripts/*.cjs"))
    if not shutil.which("node"):
        ck(not REQUIRE_NODE, "缺 node —— 跳过 ESM 校验",
           "（TG_REQUIRE_NODE=1 时此项判失败）")
        return
    try:
        ok, out = validate.check_esm(targets)
    except Exception as e:  # noqa: BLE001
        ok, out = False, "%s: %s" % (type(e).__name__, e)
    ck(ok, "%d 个浏览器脚本可解析" % len(targets),
       "" if ok else out[-400:])


# --------------------------------------------------------------------------- #
# 7. 包导入
# --------------------------------------------------------------------------- #
def t_package() -> None:
    section("8) 包导入（paramiko 缺失也应可用）")

    import tgpatch
    ck(bool(tgpatch.__version__), "tgpatch 可导入", "version=%s" % tgpatch.__version__)
    for name in ("Target", "load_target", "SSHRunner", "Remote",
                 "Edit", "PatchEngine", "diff_regions", "balanced"):
        ck(hasattr(tgpatch, name), "导出 %s" % name)


def main() -> int:
    print("tgpatch 引擎自检（不依赖线上真实 chunk）")
    print("仓库根目录: %s" % ROOT)
    for fn in (t_entry, t_routes, t_versions, t_engine, t_walk, t_sourcemap,
               t_syntax, t_package):
        fn()

    ok = all(r[0] for r in results)
    print()
    print("=" * 78)
    print("结果: %s（%d/%d 通过）"
          % ("全部通过 ✓" if ok else "存在失败 ✗",
             sum(1 for r in results if r[0]), len(results)))
    if not ok:
        print("失败项:")
        for good, desc in results:
            if not good:
                print("  - %s" % desc)
    print("=" * 78)

    shutil.rmtree(TMP, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
