# -*- coding: utf-8 -*-
"""案例 02：周期性巡航任务编排——新增一行「果园自动采摘任务」。

需求
----
在任务列表里加一条：名称「果园自动采摘任务」、类型「采摘任务」、周期「每天」、
设备数量 1、优先级 1 星（low）、状态「等待中」（pending）。

为什么是 9 处而不是 1 处
------------------------
压缩产物里，「加一条任务」要同时改 9 个地方——数据、3 个类型映射、2 个下拉、2 个
设备池、1 个分页计数：

    1. 任务数组末尾追加 task-4
    2-4. 三处 type -> 中文 映射（详情页 / 创建向导复核步骤 / 列表列渲染）
    5-6. 两处「任务类型」下拉补选项
    7-8. 两处设备池补 device-007
    9.   分页 total 3 -> 4

漏掉任何一个都会出现「数据有但显示未知类型」「下拉能选但列表不认」这类问题。
所以这里用 expect_regions(9) 强制核对差异区域数——如果只改了 8 处，立刻报错。

⚠️ 前置守卫：本地副本必须已经是「新版」
------------------------------------------
这个 chunk 在本机留过两份副本，其中一份是旧的（把「果园」写成了「农田」）。
如果误用旧副本，会把之前已经改好的文案静默回退。所以前置断言里显式要求
``农田`` 出现 0 次——这是「我正在改的是正确的那一份」的硬证据。

⚠️ 流水线顺序
--------------
本案例产出的文件是案例 03（2023->2026）与案例 05（启用开关默认关闭）的**输入**。
三个案例必须按 02 -> 03 -> 05 的顺序在同一个文件上依次施加。

运行
----
    python -m tgpatch locate PeriodicTaskArrangement
    python -m tgpatch pull <活跃 chunk> -o cases/02-periodic-picking-task/fixtures
    python patch.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tgpatch.patch import PatchEngine  # noqa: E402

HERE = Path(__file__).resolve().parent

NEW_TASK = (
    '{id:"4",name:"果园自动采摘任务",description:"每天对果园进行自动采摘作业",'
    'type:"picking",deviceIds:["device-007"],cycleType:"daily",cycleValue:1,'
    'startTime:"2023-07-15T07:00:00Z",priority:"low",status:"pending",enabled:!0,'
    'createdAt:"2023-07-12T09:00:00Z",updatedAt:"2023-07-12T09:00:00Z",'
    'nextExecutionTime:"2023-07-16T07:00:00Z"}'
)

REPLACEMENTS = [
    # 1. 数据：在 task-3 之后追加 task-4
    ("追加第4条任务",
     'nextExecutionTime:"2023-08-20T10:00:00Z"}]',
     'nextExecutionTime:"2023-08-20T10:00:00Z"},' + NEW_TASK + ']',
     1),

    # 2-4. 三处类型映射。三处的变量名不同（f / ee / e），所以是三段不同的字面量
    ("类型映射 详情页",
     'other:"其他任务"}[f]||"未知类型"',
     'picking:"采摘任务",other:"其他任务"}[f]||"未知类型"', 1),
    ("类型映射 向导复核",
     'other:"其他任务"}[ee]||"未知类型"',
     'picking:"采摘任务",other:"其他任务"}[ee]||"未知类型"', 1),
    ("类型映射 列表",
     'other:"其他任务"}[e]||"未知类型"',
     'picking:"采摘任务",other:"其他任务"}[e]||"未知类型"', 1),

    # 5-6. 两处下拉：插在「喷洒任务」之后
    ("下拉 编辑表单",
     'V(D,{label:"喷洒任务",value:"spray"}),l[19]||(l[19]=w()),V(D,{label:"检查任务",value:"inspection"})',
     'V(D,{label:"喷洒任务",value:"spray"}),V(D,{label:"采摘任务",value:"picking"}),'
     'l[19]||(l[19]=w()),V(D,{label:"检查任务",value:"inspection"})', 1),
    ("下拉 创建向导",
     'V(Y,{label:"喷洒任务",value:"spray"}),l[21]||(l[21]=w()),V(Y,{label:"检查任务",value:"inspection"})',
     'V(Y,{label:"喷洒任务",value:"spray"}),V(Y,{label:"采摘任务",value:"picking"}),'
     'l[21]||(l[21]=w()),V(Y,{label:"检查任务",value:"inspection"})', 1),

    # 7-8. 两处设备池：追加 device-007。两个变量名 g / E 不同
    ("设备池 编辑表单",
     '{id:"device-006",name:"超声波装置 US-50"}],g=D(()=>{if(!f.value',
     '{id:"device-006",name:"超声波装置 US-50"},{id:"device-007",name:"采摘机器人01"}],'
     'g=D(()=>{if(!f.value', 1),
    ("设备池 创建向导",
     '{id:"device-006",name:"超声波装置 US-50"}],E=D(()=>{if(!y.value',
     '{id:"device-006",name:"超声波装置 US-50"},{id:"device-007",name:"采摘机器人01"}],'
     'E=D(()=>{if(!y.value', 1),

    # 9. 分页计数
    ("分页 total", "pageSize:m.DEFAULT_PAGE_SIZE,total:3}",
     "pageSize:m.DEFAULT_PAGE_SIZE,total:4}", 1),
]

# 已有内容必须原样保留
KEEP = [
    ("原 3 条任务仍在", '{id:"1",name:', 1),
    ("原巡逻类型 3 处", 'type:"patrol"', 3),
    ("原喷洒任务 1 处", 'type:"spray"', 1),
    ("原检查任务 1 处", 'type:"inspection"', 1),
    ("未知类型兜底仍 3 处", '||"未知类型"', 3),
    ("标题未动", 'title:"周期性巡航任务编排"', 1),
]


def build_engine(raw: bytes, chunk_name: str = "PeriodicTaskArrangement") -> PatchEngine:
    eng = PatchEngine(raw, label="周期性任务编排：新增果园自动采摘任务")

    # 守卫 1：这是「已经改过文案」的正确版本，不是那份把果园写成农田的旧副本
    eng.assert_before("本地副本是新版（无「农田」残留在 0 处）",
                      lambda s: s.count("农田".encode()) == 0)
    # 守卫 2：已经有 3 条任务，且尚未插入第 4 条
    eng.assert_before("恰好 3 条任务（task-4 尚未插入）",
                      lambda s: all(s.count(('{id:"%s",name:' % i).encode()) == 1
                                    for i in ("1", "2", "3")))
    eng.assert_before("旧分页 total:3 存在",
                      lambda s: b"pageSize:m.DEFAULT_PAGE_SIZE,total:3}" in s)
    eng.assert_before("尚未存在 picking 相关片段",
                      lambda s: b"picking" not in s and b"device-007" not in s)

    eng.add_many(REPLACEMENTS)

    for desc, needle, n in KEEP:
        eng.assert_after(desc, (lambda s, nd=needle, c=n: s.count(nd.encode()) == c))

    eng.assert_after("新任务名恰好 1 处",
                     lambda s: s.count('name:"果园自动采摘任务"'.encode()) == 1)
    eng.assert_after("新任务四个字段连写正确",
                     lambda s: b'type:"picking",deviceIds:["device-007"],cycleType:"daily",cycleValue:1' in s)
    eng.assert_after("picking 映射 3 处",
                     lambda s: s.count('picking:"采摘任务"'.encode()) == 3)
    eng.assert_after("下拉 2 处",
                     lambda s: s.count('value:"picking"'.encode()) == 2)
    eng.assert_after("设备池 2 处",
                     lambda s: s.count('name:"采摘机器人01"'.encode()) == 2)
    eng.assert_after("分页已 +1",
                     lambda s: b"pageSize:m.DEFAULT_PAGE_SIZE,total:4}" in s
                     and b"pageSize:m.DEFAULT_PAGE_SIZE,total:3}" not in s)

    eng.expect_regions(len(REPLACEMENTS))       # 恰好 9 个差异区域
    return eng


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?", help="原始 chunk")
    ap.add_argument("-o", "--out", default=str(HERE / "out"))
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    src = Path(args.src) if args.src else _default_fixture()
    result = build_engine(src.read_bytes()).run()
    p = result.write(Path(args.out) / (args.name or src.name))
    print("\n已写出 %s" % p)
    print("下一步：案例 03（2023->2026）请以本文件为输入。")
    return 0


def _default_fixture() -> Path:
    fx = HERE / "fixtures"
    cands = sorted(fx.glob("PeriodicTaskArrangement-*.js")) if fx.exists() else []
    if not cands:
        raise SystemExit("找不到原始 chunk，请先 `python -m tgpatch pull <活跃 chunk> -o fixtures`")
    return cands[0]


if __name__ == "__main__":
    raise SystemExit(main())
