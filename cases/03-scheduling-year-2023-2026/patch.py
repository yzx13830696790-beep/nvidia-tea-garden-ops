# -*- coding: utf-8 -*-
"""案例 03：AI 任务调度系统——把所有日期里的 2023 改成 2026。

范围界定（这一步比替换本身重要）
--------------------------------
"把 AI 任务调度系统里所有 2023 改成 2026"听起来是个全局搜索替换。但在压缩产物里
全局替换 ``2023`` 会误伤三类东西：

    FarmlandMap-B8wwDWtu.js   属于 /monitoring-center/3d-map，根本不是 AI 调度系统
    index-IpV8ITOi.css        2 处是 SVG path 坐标（%20233.62）
    index-DAMuBsXX.js         3 处是随机数常量数组（2150032023）

所以换字面量：只替换 ``"2023-``（带引号带连字符），即 ISO 日期串的前缀。这样
SVG 坐标（``%20233.62``）和数字常量（``2150032023``）天然不受影响。

模块 chunk 全集怎么定
---------------------
用「顶层路由块边界法」：在入口文件里从 ``{path:"/task-scheduling"`` 扫到下一个顶层
路由，中间 import 的 chunk 就是 AI 调度系统的全部模块（7 个页面）：
TaskSchedulingLayout / PathPlanningEngine / PeriodicTaskArrangement /
EmergencyTaskQueue / MultiDeviceCollaboration / TaskProgressVisualization /
HistoryTrajectoryPlayback。再逐个 grep ``"2023-`` 确定实际命中的只有 2 个。

⚠️ 流水线顺序
--------------
必须施加在案例 02 的产物之上。PeriodicTaskArrangement 期望命中 17 处，其中 4 处
来自案例 02 新增的那条任务。若直接在原始文件上跑，会因命中数不足 17 而中止。

运行
----
    python patch.py --dir cases/02-periodic-picking-task/out
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tgpatch.patch import PatchEngine  # noqa: E402

HERE = Path(__file__).resolve().parent

# 文件 -> 期望命中次数（已逐个核验）
TARGETS = {
    "PeriodicTaskArrangement-_PTsgACL.js": 17,
    "EmergencyTaskQueue-CH4Fc2Rv.js": 3,
}

# 这些文件也在 assets 里含 "2023"，但明确不属于本次范围
EXCLUDED = {
    "FarmlandMap-B8wwDWtu.js": "/monitoring-center/3d-map，不属于 AI 调度系统",
    "index-IpV8ITOi.css": "SVG path 坐标 %20233.62，不是年份",
    "index-DAMuBsXX.js": "随机数常量数组 2150032023，不是年份",
}

OLD, NEW = '"2023-', '"2026-'


def build_engine(raw: bytes, filename: str, expect: int) -> PatchEngine:
    eng = PatchEngine(raw, label="年份 2023->2026 (%s)" % filename)
    eng.assert_before("裸 2023 数量与日期串数量一致（说明全是日期）",
                      lambda s: s.count(b"2023") == expect)
    eng.add("日期前缀 2023- -> 2026-", OLD, NEW, count=expect)
    eng.assert_after("已无 2023", lambda s: b"2023" not in s)
    eng.assert_after("未引入其它年份",
                     lambda s: all(('"%d-' % y).encode() not in s for y in (2024, 2025, 2027)))
    eng.assert_after("字符数不变（两个年份等长，走的是原地替换）",
                     lambda s: len(s) == len(raw))
    return eng


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[1]
                                         / "02-periodic-picking-task" / "out"),
                    help="输入目录（默认取案例 02 的产物）")
    ap.add_argument("-o", "--out", default=str(HERE / "out"))
    args = ap.parse_args()

    src_dir, out_dir = Path(args.dir), Path(args.out)
    print("输入目录: %s" % src_dir)
    print("已排除（经核验，非年份 / 不在范围内）:")
    for f, why in EXCLUDED.items():
        print("  %-34s %s" % (f, why))
    print()

    total = 0
    for name, expect in TARGETS.items():
        # 逐文件解析输入：优先取 --dir（案例 02 的产物），否则回落到本案例的
        # fixtures/。两个文件的改动来源本来就不同——PeriodicTaskArrangement 必须先
        # 经过案例 02，而 EmergencyTaskQueue 直接从线上原始版本起步。
        p = src_dir / name
        origin = "案例 02 产物"
        if not p.exists():
            p = HERE / "fixtures" / name
            origin = "本案例 fixtures（线上原始版本）"
        if not p.exists():
            raise SystemExit(
                "缺少输入文件 %s\n"
                "  - PeriodicTaskArrangement 需先跑案例 02；\n"
                "  - EmergencyTaskQueue 可用 `python -m tgpatch pull %s -o fixtures` 取回。"
                % (name, name))

        print("输入 %s <- %s" % (name, origin))
        result = build_engine(p.read_bytes(), name, expect).run()
        result.write(out_dir / name)
        total += expect
        print()

    print("合计替换 %d 处。输出目录: %s" % (total, out_dir))
    print("下一步：案例 05（启用开关默认关闭）请以本目录的 PeriodicTaskArrangement 为输入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
