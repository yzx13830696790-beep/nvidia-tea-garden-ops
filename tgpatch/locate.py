# -*- coding: utf-8 -*-
"""入口识别与活跃 chunk 定位。

痛点
----
同一台机器上会残留历史构建的多份同名 chunk（例如 ``PickerVehicleData-<hash>.js``
有 3 个不同 hash 的副本）。它们的**文件名不同、内容可能不同**。如果改错了副本，
页面照常打开、HTTP 照常 200、但界面毫无变化——因为线上加载的是另一份。

更坑的是：本地工作目录里那份"上次拉下来的副本"往往是**旧版**。直接用它会静默回退
上一次的改动（我们确实踩过：把已经改好的「果园」退回成了「农田」）。所以每次动手前
都要重新 pull 并与线上 md5 比对。

本模块给出三个判据，按可靠性排序：

1. **引用链可达性**（最可靠）：从入口文件出发做 BFS，只有被链上某个文件显式 import
   的 chunk 才会被浏览器加载。
2. **``__vite__mapDeps`` 索引**：路由懒加载的 chunk 集合由入口里的索引数组决定。
3. **``index.html`` 引用**：确认当前真正生效的入口文件是哪一个。

注意 ``index.html`` 里**第一个** ``<script src>`` 通常是 ``/cesium/Cesium.js``（地图库），
不是 SPA 入口。必须按 ``index-`` 前缀筛，否则会对着 Cesium 文件分析半天。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CHUNK_RE = re.compile(r"([A-Za-z0-9_.$-]+)-([A-Za-z0-9_\-]{8})\.js")
MODULE_CHUNK_RE = re.compile(r"([A-Za-z][A-Za-z0-9_$]*)-([A-Za-z0-9_\-]{8,})\.js")


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def find_entry(index_html: str) -> str | None:
    """从 index.html 里找出 SPA 入口脚本的文件名。

    返回形如 ``index-DzrFuFTi.js``；找不到返回 None。
    """
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', index_html)
    for s in srcs:
        name = s.rsplit("/", 1)[-1]
        # 排除 /cesium/Cesium.js 之类的第三方库
        if name.startswith("index-") and name.endswith(".js"):
            return name
    for s in srcs:
        name = s.rsplit("/", 1)[-1]
        if name.endswith(".js") and "cesium" not in s.lower():
            return name
    return None


# --------------------------------------------------------------------------- #
# __vite__mapDeps
# --------------------------------------------------------------------------- #
def parse_map_deps(entry_src: str) -> list[str]:
    """解析入口文件里 ``__vite__mapDeps`` 的依赖数组。"""
    m = re.search(r'm\.f\s*=\s*(\[[^\]]*\])', entry_src)
    if not m:
        m = re.search(r'(\[\s*"assets/[^\]]+\])', entry_src)
    if not m:
        return []
    return re.findall(r'"assets/([^"]+)"', m.group(1))


def parse_routes(entry_src: str) -> list[tuple[str, list[str]]]:
    """解析 ``path:"..."`` 与紧随其后的 ``__vite__mapDeps([...])``。

    返回 ``[(路由, [该路由会加载的 chunk 文件名]), ...]``。
    实现上先定位所有 mapDeps 调用，再向前找最近的 ``path:"..."``——
    比「从 path 向后扫」稳，因为中间可能隔着多层括号和条件表达式。
    """
    names = parse_map_deps(entry_src)
    calls = list(re.finditer(r"__vite__mapDeps\(\[([0-9,\s]*)\]\)", entry_src))
    paths = [(m.start(), m.group(1)) for m in re.finditer(r'path:"([^"]+)"', entry_src)]

    out: list[tuple[str, list[str]]] = []
    for call in calls:
        before = [p for p in paths if p[0] < call.start()]
        if not before:
            continue
        _, route = before[-1]
        idx = [int(x) for x in call.group(1).split(",") if x.strip()]
        # 同一个 path 可能有多段 mapDeps（嵌套路由），合并
        chunks = [names[i] for i in idx if 0 <= i < len(names)]
        merged = False
        for i, (r, existing) in enumerate(out):
            if r == route:
                out[i] = (route, existing + [c for c in chunks if c not in existing])
                merged = True
                break
        if not merged:
            out.append((route, chunks))
    return out


def route_block(entry_src: str, path: str) -> str:
    """取出某个顶层路由在入口文件里的整段代码（到下一个顶层路由为止）。

    「顶层路由块边界法」：`{path:"/xxx"` 到下一个 `{path:"` 之间，就是这条路由的
    全部静态依赖，据此可以圈定模块 chunk 的候选全集，避免全局替换误伤别的模块。
    """
    starts = [m.start() for m in re.finditer(r'\{\s*path:"', entry_src)]
    labels = [m.group(1) for m in re.finditer(r'\{\s*path:"([^"]+)"', entry_src)]
    for i, label in enumerate(labels):
        if label == path:
            begin = starts[i]
            end = starts[i + 1] if i + 1 < len(starts) else min(len(entry_src), begin + 20000)
            return entry_src[begin:end]
    raise KeyError("入口里找不到路由 %r（现有: %s）" % (path, labels))


def chunks_of_route(entry_src: str, path: str) -> list[str]:
    """某条路由对应的 chunk 文件名集合（从路由块里的 import 语句提取）。"""
    block = route_block(entry_src, path)
    return sorted(set(re.findall(r'"\./([A-Za-z0-9_\-]+-[A-Za-z0-9_\-]{8,}\.js)"', block)))


# --------------------------------------------------------------------------- #
# 活跃版本判定
# --------------------------------------------------------------------------- #
def module_versions(filenames: list[str], module: str) -> list[str]:
    """从文件名列表里筛出 ``<module>-<hash>.js`` 的所有版本。"""
    return sorted(f for f in filenames if f.startswith(module + "-") and f.endswith(".js"))


def referenced_by(sources: dict[str, str], target: str) -> list[str]:
    """哪些文件引用了 ``target``（按字面量出现判断）。"""
    needle = target
    return sorted(f for f, s in sources.items() if f != target and needle in s)


def reachable_from_entry(sources: dict[str, str], entry: str) -> dict[str, int]:
    """从入口出发做 BFS，返回 ``{文件名: 距入口层数}``。

    能到达的 chunk 才是浏览器真正会加载的。同名多副本时，只有可达的那一份是活的。
    """
    import collections

    def refs(fname: str) -> set[str]:
        s = sources.get(fname, "")
        found = set(re.findall(r'"\./([A-Za-z0-9_\-\.]+\.js)"', s))
        found |= set(re.findall(r'\./([A-Za-z0-9_\-]+\.js)', s))
        return {f for f in found if f in sources}

    depth = {entry: 0}
    q = collections.deque([entry])
    seen = {entry}
    while q:
        cur = q.popleft()
        for r in refs(cur):
            if r not in seen:
                seen.add(r)
                depth[r] = depth[cur] + 1
                q.append(r)
    return depth


def pick_active(sources: dict[str, str], entry: str, module: str) -> dict:
    """综合判断某个模块的**活跃** chunk 是哪一个。

    返回 ``{"module", "versions", "active", "zombies", "reason"}``。
    活跃判定优先用引用链可达性；不可达时退化为「被引用次数最多」。
    """
    versions = module_versions(list(sources.keys()), module)
    if not versions:
        return {"module": module, "versions": [], "active": None, "zombies": [],
                "reason": "assets 里没有该模块的任何 chunk"}

    depth = reachable_from_entry(sources, entry)
    alive = [v for v in versions if v in depth]
    if len(alive) == 1:
        return {"module": module, "versions": versions, "active": alive[0],
                "zombies": [v for v in versions if v != alive[0]],
                "reason": "引用链从入口可达，且唯一（depth=%d）" % depth[alive[0]]}

    ref_counts = {v: len(referenced_by(sources, v)) for v in versions}
    if alive:
        best = max(alive, key=lambda v: (depth[v] == 0, -depth[v], ref_counts[v]))
        reason = "可达的有 %d 个副本，取引用链最近的（depth=%d）" % (len(alive), depth[best])
    else:
        best = max(versions, key=lambda v: ref_counts[v])
        reason = "入口不可达（可能被动态 import 字符串拼接隐藏），退化为取被引用最多者"

    return {"module": module, "versions": versions, "active": best,
            "zombies": [v for v in versions if v != best], "reason": reason}


# --------------------------------------------------------------------------- #
# 远端扫描
# --------------------------------------------------------------------------- #
SCAN_PY = r'''
import os, re, json, collections
D = %(assets)r
ENTRY = %(entry)r
MODULE = %(module)r

src = {}
for f in sorted(os.listdir(D)):
    if not f.endswith(".js"):
        continue
    try:
        src[f] = open(os.path.join(D, f), "rb").read().decode("utf-8", "replace")
    except Exception:
        pass

versions = sorted(f for f in src if f.startswith(MODULE + "-") and f.endswith(".js"))

def refs(f):
    s = src.get(f, "")
    out = set(re.findall(r'"\./([A-Za-z0-9_\-\.]+\.js)"', s))
    out |= set(re.findall(r"\./([A-Za-z0-9_\-]+\.js)", s))
    return set(out)

depth = {ENTRY: 0}
q = collections.deque([ENTRY]); seen = {ENTRY}
while q:
    cur = q.popleft()
    for r in refs(cur):
        if r in src and r not in seen:
            seen.add(r); depth[r] = depth[cur] + 1; q.append(r)

refcnt = {v: sum(1 for f, s in src.items() if f != v and v in s) for v in versions}

print(json.dumps({
    "entry": ENTRY,
    "entry_exists": ENTRY in src,
    "versions": [{"name": v, "bytes": len(src[v].encode("utf-8")),
                  "reachable": v in depth, "depth": depth.get(v),
                  "referenced_by": refcnt[v]} for v in versions],
    "js_total": len(src),
}, ensure_ascii=False))
'''


def scan_remote(remote, module: str, entry: str | None = None) -> dict:
    """在容器内扫描 assets，找出某个模块所有副本及其可达性。"""
    import json

    if entry is None:
        html = remote.container("cat /opt/tea-garden/web/dist/index.html 2>/dev/null")
        entry = find_entry(html) or ""
    out = remote.exec_python(SCAN_PY % {"assets": remote.target.assets,
                                        "entry": entry,
                                        "module": module})
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        raise RuntimeError("容器内扫描未返回 JSON：\n%s" % out[:800])
    data = json.loads(m.group(0))
    alive = [v for v in data["versions"] if v["reachable"]]
    data["active"] = alive[0]["name"] if len(alive) == 1 else None
    data["zombies"] = [v["name"] for v in data["versions"] if not v["reachable"]]
    if len(alive) > 1:
        data["active"] = max(alive, key=lambda v: v["referenced_by"])["name"]
        data["warning"] = "有 %d 个可达副本，存在歧义，请人工确认" % len(alive)
    return data


def load_sources_via_remote(remote, names: list[str], tmpdir) -> dict[str, str]:
    """把容器内若干 chunk 取回本地并读成文本（仅供分析用，不写回远端）。"""
    out = {}
    for n in names:
        p = remote.fetch(n, tmpdir)
        out[n] = p.read_bytes().decode("utf-8", "replace")
    return out
