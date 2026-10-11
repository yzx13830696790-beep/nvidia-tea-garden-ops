# -*- coding: utf-8 -*-
"""端到端回归测试：把五个案例按 02 -> 03 -> 05 的流水线跑一遍，
逐环节比对 md5。

夹具（线上真实 chunk）不入库，所以 fixtures/ 不存在时整体跳过。

为什么要拿 md5 卡这么死
-----------------------
这五个案例的产物当初都真部署上线过、并通过了 HTTP + 浏览器验证。也就是说这些 md5
对应的字节就是**线上跑着的那个版本**。改写工具箱时如果不做这个比对，很容易在
「把脚本整理得更漂亮」的过程中悄悄改变替换行为——而静态断言、语法校验、HTTP 校验
**都发现不了**这种偏移。只有 md5 能。

运行：
    python tests/test_pipeline.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "cases"
PY = sys.executable

# 线上已验证的 md5（部署过并通过三层验证的版本）
CHAIN = [
    # (案例目录, 输入文件, 输入 md5, 输出文件, 输出 md5)
    ("01-picker-success-rate", "PickerVehicleData-BWUD9G8B.js",
     "ffc009140d153f4d89e34b785753b5e4", "PickerVehicleData-BWUD9G8B.js",
     "2493ad757eb4ad4410ccd6a7a9d1c0e8"),
    ("02-periodic-picking-task", "PeriodicTaskArrangement-_PTsgACL.js",
     "b9569e5b15adddab923a11c6dbc9832b", "PeriodicTaskArrangement-_PTsgACL.js",
     "0bc73a2a63d2091bc9fd4d3ee805345c"),
    ("03-scheduling-year-2023-2026", "EmergencyTaskQueue-CH4Fc2Rv.js",
     "0e7aa822f8c305faabb39582ad25a943", "EmergencyTaskQueue-CH4Fc2Rv.js",
     "d008272e8c15fbb2b9b0d383401601c5"),
    ("04-multi-device-picking-robot", "MultiDeviceCollaboration-xV5LwVm2.js",
     "7370090f1957518baabf79df968deb65", "MultiDeviceCollaboration-xV5LwVm2.js",
     "c27579d70ed986a7a4d2368ce889fe53"),
]

# 跨案例链条：PeriodicTaskArrangement 走 02 -> 03 -> 05
PERIODIC_CHAIN = [
    ("02-periodic-picking-task", "b9569e5b15adddab923a11c6dbc9832b",
     "0bc73a2a63d2091bc9fd4d3ee805345c"),
    ("03-scheduling-year-2023-2026", "0bc73a2a63d2091bc9fd4d3ee805345c",
     "662660a2e603c34a7c6f5c62e9895815"),
    ("05-periodic-enable-default-off", "662660a2e603c34a7c6f5c62e9895815",
     "682cc5bf76780ae97e544d74878a034f"),
]
PERIODIC = "PeriodicTaskArrangement-_PTsgACL.js"

results: list[tuple[bool, str]] = []


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def run_case(case: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    d = CASES / case
    return subprocess.run([PY, "patch.py", *(extra or [])], cwd=str(d),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)


def ck(ok: bool, desc: str, detail: str = "") -> None:
    results.append((ok, desc))
    print("  [%s] %s%s" % ("OK" if ok else "FAIL", desc, ("   " + detail) if detail else ""))


def main() -> int:
    fixtures_found = any((CASES / c / "fixtures").exists() for c, *_ in CHAIN)
    if not fixtures_found:
        print("跳过：cases/*/fixtures 不存在。")
        print("夹具是线上真实 chunk，不入库。取回方式：")
        print("  python -m tgpatch locate <模块名>")
        print("  python -m tgpatch pull <活跃 chunk> -o cases/<案例>/fixtures")
        return 0

    print("=" * 72)
    print("A) 独立案例（输入 -> 输出 的 md5 必须与线上已验证版本一致）")
    print("=" * 72)
    for case, src_name, src_md5, out_name, out_md5 in CHAIN:
        src = CASES / case / "fixtures" / src_name
        if not src.exists():
            print("  [SKIP] %s（缺夹具 %s）" % (case, src_name))
            continue
        ck(md5(src) == src_md5, "%s 夹具 md5 正确" % case, md5(src)[:12])

        extra = ["--dir", str(CASES / "02-periodic-picking-task" / "out")] \
            if case.startswith("03-") else []
        proc = run_case(case, extra)
        out = CASES / case / "out" / out_name
        if proc.returncode != 0 or not out.exists():
            ck(False, "%s 生成补丁" % case, (proc.stdout or "")[-300:] + (proc.stderr or "")[-300:])
            continue
        got = md5(out)
        ck(got == out_md5, "%s 输出 md5 == 线上已验证版本" % case, "%s" % got[:12])

    print()
    print("=" * 72)
    print("B) 跨案例链条：PeriodicTaskArrangement 02 -> 03 -> 05")
    print("=" * 72)
    prev = CASES / "02-periodic-picking-task" / "fixtures" / PERIODIC
    if prev.exists():
        ck(md5(prev) == PERIODIC_CHAIN[0][1], "链条起点 md5 正确", md5(prev)[:12])
    for case, expect_in, expect_out in PERIODIC_CHAIN:
        if case.startswith("03-"):
            src = CASES / "02-periodic-picking-task" / "out" / PERIODIC
        elif case.startswith("05-"):
            src = CASES / "03-scheduling-year-2023-2026" / "out" / PERIODIC
        else:
            src = CASES / case / "fixtures" / PERIODIC
        if not src.exists():
            ck(False, "%s 输入存在" % case, str(src))
            continue
        ck(md5(src) == expect_in, "%s 输入 md5 符合链条预期" % case, md5(src)[:12])

        extra = ["--dir", str(src.parent)] if case.startswith("03-") else \
                (["--dir", str(src.parent)] if case.startswith("05-") else [])
        proc = run_case(case, extra)
        out = CASES / case / "out" / PERIODIC
        if proc.returncode != 0 or not out.exists():
            ck(False, "%s 生成补丁" % case, (proc.stdout or "")[-300:] + (proc.stderr or "")[-300:])
            continue
        ck(md5(out) == expect_out, "%s 输出 md5 == 链条预期" % case, md5(out)[:12])

    print()
    ok = all(r[0] for r in results)
    print("=" * 72)
    print("结果: %s（%d/%d 通过）"
          % ("全部通过 ✓" if ok else "存在失败 ✗",
             sum(1 for r in results if r[0]), len(results)))
    print("=" * 72)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
