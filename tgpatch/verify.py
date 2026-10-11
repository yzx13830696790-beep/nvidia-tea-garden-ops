# -*- coding: utf-8 -*-
"""验证层：HTTP 校验 + 浏览器端到端。

三层验证的必要性
----------------
字节级补丁"看起来对了"和"线上真的对了"是两件事：

======  ==========================  ==========================================
层级    能发现什么                  发现不了什么
======  ==========================  ==========================================
静态    替换文本在不在、命中数对不  文件根本没被部署；部署到了僵尸副本
        对、语法能不能解析
HTTP    部署是否生效、md5 是否一致、 页面渲染出来的到底是什么（Vue 可能因数据
        入口是否真的引用这个 chunk   结构不匹配而不渲染）
浏览器  页面上真的显示成什么样、交   部署到别的机器 / 别的环境
        互（点击/刷新/定时器）行为
======  ==========================  ==========================================

只做前两层就宣布成功的下场是：静态全绿、HTTP 全绿、打开页面毫无变化。

实测中 HTTP 层还要注意：入口文件的引用检查必须真的去读 ``index.html`` 里那个
``index-*.js``（而不是 Cesium），否则"入口引用该 chunk"这条会永远是 False。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

UA = "Mozilla/5.0 (tgpatch verify)"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
@dataclass
class HttpResult:
    url: str
    status: int
    body: bytes
    headers: dict

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    @property
    def md5(self) -> str:
        return hashlib.md5(self.body).hexdigest()


def http_get(url: str, timeout: int = 15, no_cache: bool = True) -> HttpResult:
    headers = {"User-Agent": UA}
    if no_cache:
        headers["Cache-Control"] = "no-cache"
        headers["Pragma"] = "no-cache"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return HttpResult(url, r.status, r.read(), dict(r.headers))
    except urllib.error.HTTPError as e:
        return HttpResult(url, e.code, e.read() or b"", dict(e.headers))


# --------------------------------------------------------------------------- #
# 资产校验
# --------------------------------------------------------------------------- #
@dataclass
class AssetCheck:
    """对一个 chunk 的线上校验：md5 + 必须存在 + 必须不存在。"""

    name: str
    expect_md5: str | None = None
    must: list[str] = field(default_factory=list)
    mustnot: list[str] = field(default_factory=list)
    title: str = ""

    def run(self, base_url: str, verbose: bool = True) -> bool:
        r = http_get("%s/assets/%s" % (base_url.rstrip("/"), self.name))
        ok = r.status == 200
        say = print if verbose else (lambda *a, **k: None)

        say("=== %s ===" % (self.title or self.name))
        say("  HTTP %d | %d bytes | md5 %s%s"
            % (r.status, len(r.body), r.md5,
               ("  " + ("MATCH" if r.md5 == self.expect_md5 else "**MISMATCH**"))
               if self.expect_md5 else ""))
        if self.expect_md5:
            ok &= r.md5 == self.expect_md5
        for k in ("Content-Type", "Last-Modified", "Cache-Control", "ETag"):
            if k in r.headers:
                say("  %-14s %s" % (k + ":", r.headers[k]))

        t = r.text
        if self.must:
            say("  应存在:")
            for k in self.must:
                hit = k in t
                ok &= hit
                say("    [%s] %s" % ("OK" if hit else "FAIL", k))
        if self.mustnot:
            say("  应不存在:")
            for k in self.mustnot:
                gone = k not in t
                ok &= gone
                say("    [%s] %s" % ("OK" if gone else "FAIL", k))
        return ok


def check_entry_chain(base_url: str, chunk: str, verbose: bool = True) -> bool:
    """确认 index.html -> 入口 -> 该 chunk 的引用链真的成立。"""
    say = print if verbose else (lambda *a, **k: None)
    from .locate import find_entry

    idx = http_get("%s/index.html" % base_url.rstrip("/"))
    entry = find_entry(idx.text)
    say("=== 入口链路 ===")
    say("  index.html HTTP %d，识别到的入口: %s" % (idx.status, entry))
    if not entry:
        say("  [FAIL] index.html 里找不到 index-*.js 入口")
        return False
    e = http_get("%s/assets/%s" % (base_url.rstrip("/"), entry))
    hit = chunk in e.text
    say("  入口 HTTP %d | 引用 %s: %s" % (e.status, chunk, hit))
    return e.status == 200 and hit


def check_routes(base_url: str, paths: list[str], verbose: bool = True) -> bool:
    """确认若干前端路由返回 200（SPA 的 history 回退没配好时这里会 404）。"""
    say = print if verbose else (lambda *a, **k: None)
    say("=== 页面可达性 ===")
    ok = True
    for p in paths:
        r = http_get(base_url.rstrip("/") + p, timeout=10)
        good = r.status == 200
        ok &= good
        say("  %-52s HTTP %d %s" % (p, r.status, "" if good else "**FAIL**"))
    return ok


# --------------------------------------------------------------------------- #
# 浏览器端到端
# --------------------------------------------------------------------------- #
CHROME_CANDIDATES = [
    os.environ.get("TG_CHROME"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


class ChromeNotFound(RuntimeError):
    pass


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    raise ChromeNotFound(
        "找不到 Chrome/Edge。端到端验证需要真实浏览器渲染（无头即可）。\n"
        "请安装 Chrome，或用环境变量 TG_CHROME 指定可执行文件路径。")


def run_e2e(script: Path | str, base_url: str | None = None,
            timeout: int = 900, env_extra: dict | None = None,
            echo: bool = True) -> tuple[bool, str]:
    """跑一个 playwright-core 端到端脚本。

    脚本约定：通过 ``TG_BASE_URL`` 取地址，通过 ``TG_CHROME`` 取浏览器路径，
    退出码 0 = 通过。这样脚本本身与具体机器解耦。
    """
    script = Path(script)
    if not script.exists():
        raise FileNotFoundError(script)
    env = {**os.environ}
    try:
        env["TG_CHROME"] = find_chrome()
    except ChromeNotFound:
        pass
    if base_url:
        env.setdefault("TG_BASE_URL", base_url)
    if env_extra:
        env.update(env_extra)

    proc = subprocess.run(["node", str(script)], cwd=str(script.parent),
                          capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace", timeout=timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    if echo:
        print(out)
    return proc.returncode == 0, out


# --------------------------------------------------------------------------- #
# 随机游走
# --------------------------------------------------------------------------- #
def reflect(v: float, lo: float, hi: float) -> float:
    """触边回弹：越界后按边界镜像折回，而不是夹在边界上。

    直接 clamp 的后果是「连续多点冻在边界」——我们实测过：成功率卡在 78.0 整整
    25 秒不动，看起来像死机。镜像回弹既不出界，又不会滞留在边界。
    """
    if v > hi:
        return 2 * hi - v
    if v < lo:
        return 2 * lo - v
    return v


def simulate_walk(start: float, step_scale: float, lo: float, hi: float,
                  steps: int = 20000, seed: int | None = None) -> dict:
    """模拟「随机步长 + 触边回弹」的取值序列，返回统计量。

    用来在改动上线前先证明两件事：永不越界、且不会长时间冻结在边界。
    """
    rng = random.Random(seed)
    v = start
    vals = []
    max_run = run = 0
    for _ in range(steps):
        v = reflect(v + (rng.random() * 2 - 1) * step_scale, lo, hi)
        vals.append(v)
        # 「贴边」定义：距任一边界 < 0.05
        if v > hi - 0.05 or v < lo + 0.05:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return {
        "min": min(vals), "max": max(vals),
        "span": max(vals) - min(vals),
        "max_edge_run": max_run,
        "distinct_rounded": len({round(x, 1) for x in vals}),
        "values": vals,
    }


def failure_probability(step_scale: float, lo: float, hi: float,
                        margin: float, steps: int, trials: int = 2000,
                        seed: int = 0) -> float:
    """估算「n 步内取值越过 margin 之外」的概率。

    给端到端验证定阈值用：如果不先算一下，很容易写出一个「理论上会偶发失败」的
    断言阈值，然后在 CI 上随机红灯。
    """
    rng = random.Random(seed)
    bad = 0
    span = hi - lo
    for _ in range(trials):
        v = (lo + hi) / 2
        for _ in range(steps):
            v = reflect(v + (rng.random() * 2 - 1) * step_scale, lo, hi)
            if v < lo + margin or v > hi - margin:
                bad += 1
                break
    return bad / trials
