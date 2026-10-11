# -*- coding: utf-8 -*-
"""案例 05：周期性巡航任务编排——「启用」列开关的初始状态全部改为未启用。

需求
----
表格里 4 条任务的「启用」开关，初始状态全部为关闭（未启用）。

难点：怎么在不引入新变量的前提下，精确命中「任务行」的 enabled？
--------------------------------------------------------------
文件里 ``enabled:!0`` 一共 5 处：

    task-1 北区果园定时巡逻    priority:"medium",status:"pending",enabled:!0,createdAt:
    task-2 周末喷洒任务        priority:"high",status:"running",enabled:!0,createdAt:
    task-4 果园自动采摘任务    priority:"low",status:"pending",enabled:!0,createdAt:
    编辑表单默认值             priority:"medium",status:"pending",enabled:!0})
    创建向导默认值             priority:"medium",status:"pending",enabled:!0})
    (task-3 月度病虫害检查本来就是 enabled:!1)

裸 ``enabled:!0`` 无法区分任务行和表单默认值。解法是用**每行独有的 priority+status
组合**做前缀锚点：

    task-1 用 priority:"medium",status:"pending",enabled:!0,createdAt:
    task-2 用 priority:"high",status:"running",enabled:!0,createdAt:
    task-4 用 priority:"low",status:"pending",enabled:!0,createdAt:

后缀的 ``,createdAt:`` 是区分「表单默认值」的关键——表单默认值以 ``})`` 结尾。

⚠️ 两处表单默认值文本**完全相同**（编辑表单与创建向导的默认值对象一字不差）。
所以对它们**只能做整体计数断言（count==2）**，没法单独定位其中一处。这也是本案例
选择「只改列表 4 行的初始状态、不动新建弹窗默认值」的直接原因——需求说的就是列表。

⚠️ 流水线顺序
--------------
输入必须是案例 03 的产物（task-1 的 createdAt 此时已是 2026-…）。锚点本身不含年份，
所以理论上也能直接接在案例 02 之后，但为保证与线上最终状态一致，请按 02 -> 03 -> 05。

运行
----
    python patch.py --dir cases/03-scheduling-year-2023-2026/out
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tgpatch.patch import PatchEngine  # noqa: E402

HERE = Path(__file__).resolve().parent
CHUNK = "PeriodicTaskArrangement-_PTsgACL.js"

# (标签, 旧片段, 新片段, 期望次数) —— 用 priority+status 组合锁定任务行
PATCHES = [
    ("task-1 北区果园定时巡逻",
     'priority:"medium",status:"pending",enabled:!0,createdAt:',
     'priority:"medium",status:"pending",enabled:!1,createdAt:', 1),
    ("task-2 周末喷洒任务",
     'priority:"high",status:"running",enabled:!0,createdAt:',
     'priority:"high",status:"running",enabled:!1,createdAt:', 1),
    ("task-4 果园自动采摘任务",
     'priority:"low",status:"pending",enabled:!0,createdAt:',
     'priority:"low",status:"pending",enabled:!1,createdAt:', 1),
]

# 表单默认值：必须原样保留（它们决定新建/编辑弹窗里开关的默认值，不是列表初始状态）
FORM_DEFAULT = 'priority:"medium",status:"pending",enabled:!0})'

# 回归：这些字段的计数必须完全不变
REGRESSION_FIELDS = [
    'status:"pending"', 'status:"running"', 'status:"completed"', 'status:"paused"',
    'status:"failed"', 'priority:"medium"', 'priority:"high"', 'priority:"low"',
    'priority:"emergency"', 'type:"patrol"', 'type:"spray"', 'type:"inspection"',
    'type:"picking"', 'deviceIds:', 'nextExecutionTime:', 'createdAt:', 'updatedAt:',
    'startTime:',
]


def build_engine(raw: bytes) -> PatchEngine:
    eng = PatchEngine(raw, label="周期性任务：启用开关初始关闭")

    eng.assert_before("enabled:!0 共 5 处（2 表单默认 + 3 任务行）",
                      lambda s: s.count(b"enabled:!0") == 5)
    eng.assert_before("enabled:!1 共 1 处（task-3）",
                      lambda s: s.count(b"enabled:!1") == 1)
    eng.assert_before("两处表单默认值文本相同（只能整体计数 == 2）",
                      lambda s: s.count(FORM_DEFAULT.encode()) == 2)
    eng.assert_before("4 条任务名齐备",
                      lambda s: all(x.encode() in s for x in
                                    ["北区果园定时巡逻", "周末喷洒任务", "月度病虫害检查",
                                     "果园自动采摘任务"]))

    eng.add_many(PATCHES)

    eng.assert_after("enabled:!0 降为 2（仅表单默认）",
                     lambda s: s.count(b"enabled:!0") == 2)
    eng.assert_after("enabled:!1 升为 4（全部任务行）",
                     lambda s: s.count(b"enabled:!1") == 4)
    eng.assert_after("任务行的 enabled:!0 已归零",
                     lambda s: s.count(b"enabled:!0,createdAt:") == 0)
    eng.assert_after("表单默认值仍为 !0（未被误改）",
                     lambda s: s.count(FORM_DEFAULT.encode()) == 2)
    eng.assert_after("字符数 / 字节数不变（!0 与 !1 等长）",
                     lambda s: len(s) == len(raw))
    eng.assert_after("4 条任务名未变",
                     lambda s: all(s.count(x.encode()) == 1 for x in
                                   ["北区果园定时巡逻", "周末喷洒任务", "月度病虫害检查",
                                    "果园自动采摘任务"]))
    eng.assert_after("表格列定义未动（label:\"启用\"）",
                     lambda s: s.count('label:"启用",width:"80"'.encode()) == 1)
    for frag in REGRESSION_FIELDS:
        eng.assert_after("回归 %s 计数不变" % frag,
                         (lambda s, f=frag, r=raw: s.count(f.encode()) == r.count(f.encode())))

    eng.expect_regions(len(PATCHES))            # 恰好 3 个差异区域
    return eng


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[1]
                                         / "03-scheduling-year-2023-2026" / "out"),
                    help="输入目录（默认取案例 03 的产物）")
    ap.add_argument("--src", help="直接指定输入文件（优先于 --dir）")
    ap.add_argument("-o", "--out", default=str(HERE / "out"))
    args = ap.parse_args()

    src = Path(args.src) if args.src else Path(args.dir) / CHUNK
    if not src.exists():
        raise SystemExit("缺少输入文件 %s\n（按 02 -> 03 -> 05 顺序执行，或用 --src 指定）" % src)

    result = build_engine(src.read_bytes()).run()
    p = result.write(Path(args.out) / CHUNK)
    print("\n已写出 %s" % p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
