# -*- coding: utf-8 -*-
"""案例 04：多机协同工作模式——「可用设备」新增「采摘机器人-01」。

需求
----
在 /task-scheduling/multi-device-collaboration 的「可用设备」列表里加一台
「采摘机器人-01」。

为什么是 4 处
-------------
新增一种**此前不存在的设备类型**（pickingRobot），要在四个地方同时登记：

    A. 设备池数组 Ze 追加 device-006，status=online
    B. 类型 -> 中文 映射 ha 补 pickingRobot:"采摘机器人"
    C. 类型筛选逻辑补 picking-robot 分支
    D. 设备类型下拉补「采摘机器人」选项

只做 A 的话，设备确实会出现在列表里，但类型标签显示「未知类型」、筛选器选不到它。

status 选 online 的关键作用
---------------------------
页面里有两个派生列表：

    na = Ze.value.filter(...)    -> 「可用设备」面板
    oa = Ze.value.filter(...)    -> 「参与设备」下拉（只取 online / charging）

只要 status=online，这一条记录就会同时出现在两个地方——所以只加一条数据，效果
却是「可用设备多了一台」+「选择参与设备时也能选到它」。

运行
----
    python -m tgpatch locate MultiDeviceCollaboration
    python -m tgpatch pull <活跃 chunk> -o cases/04-multi-device-picking-robot/fixtures
    python patch.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tgpatch.patch import PatchEngine  # noqa: E402

HERE = Path(__file__).resolve().parent

NEW_DEV = ('{id:"device-006",name:"采摘机器人-01",type:"pickingRobot",status:"online",'
           'battery:88,avatar:"",position:{x:200,y:120,z:0},capabilities:["picking","monitor"]}')

# 原有 5 台设备（完整对象）：必须逐字节保留且顺序不变。
#
# ⚠️ 必须用**完整对象**而不是截断前缀：`{id:"device-002",...,battery:65` 这种前缀在
#    文件里会出现 2 次——协同任务数据里也有一个 device-002（字段是 speed:3.2 而不是
#    avatar），只有带到 `capabilities:` 才能唯一定位设备池里那一份。
OLD_DEVICES = [
    '{id:"device-001",name:"无人机-01",type:"drone",status:"online",battery:85,'
    'avatar:"",position:{x:120,y:150,z:30},capabilities:["spray","monitor"]}',
    '{id:"device-002",name:"无人机-02",type:"drone",status:"busy",battery:65,'
    'avatar:"",position:{x:220,y:180,z:25},capabilities:["spray","monitor"]}',
    '{id:"device-003",name:"机器狗-01",type:"robotDog",status:"online",battery:92,'
    'avatar:"",position:{x:150,y:130,z:0},capabilities:["spray","patrol","sample"]}',
    '{id:"device-004",name:"机器狗-02",type:"robotDog",status:"charging",battery:40,'
    'avatar:"",position:{x:130,y:160,z:0},capabilities:["spray","patrol","sample"]}',
    '{id:"device-005",name:"履带机器人-01",type:"other",status:"online",battery:78,'
    'avatar:"",position:{x:180,y:140,z:0},capabilities:["spray","heavy-load"]}',
]

DEV_TYPE_OPTS = [
    '{label:"全部类型",value:""}',
    '{label:"无人机",value:"drone"}',
    '{label:"机器狗",value:"robot-dog"}',
    '{label:"履带机器人",value:"track-robot"}',
]

REPLACEMENTS = [
    # A. 设备池：device-005 之后插入
    ("A 设备池新增 device-006",
     'capabilities:["spray","heavy-load"]}]),ea=c([',
     'capabilities:["spray","heavy-load"]},' + NEW_DEV + ']),ea=c([',
     1),

    # B. 类型标签映射
    ("B 类型标签映射",
     'ha=e=>({drone:"无人机",robotDog:"机器狗",other:"履带机器人"}[e]||"未知类型")',
     'ha=e=>({drone:"无人机",robotDog:"机器狗",other:"履带机器人",pickingRobot:"采摘机器人"}[e]||"未知类型")',
     1),

    # C. 类型筛选分支
    ("C 类型筛选分支",
     '("robot-dog"===Be.value&&"robotDog"===e.type||"track-robot"===Be.value&&"other"===e.type)',
     '("robot-dog"===Be.value&&"robotDog"===e.type||"track-robot"===Be.value&&"other"===e.type'
     '||"picking-robot"===Be.value&&"pickingRobot"===e.type)',
     1),

    # D. 类型下拉选项
    ("D 类型下拉选项",
     'c[19]||(c[19]=k()),f(ua,{label:"履带机器人",value:"track-robot"})]),_:1},8,["modelValue"])',
     'c[19]||(c[19]=k()),f(ua,{label:"履带机器人",value:"track-robot"}),'
     'f(ua,{label:"采摘机器人",value:"picking-robot"})]),_:1},8,["modelValue"])',
     1),
]


def build_engine(raw: bytes) -> PatchEngine:
    eng = PatchEngine(raw, label="多机协同：新增采摘机器人-01")

    eng.assert_before("原文件不含 采摘 / pickingRobot / device-006（确认是改动前的版本）",
                      lambda s: s.count("采摘".encode()) == 0
                      and s.count(b"pickingRobot") == 0
                      and s.count(b"device-006") == 0)
    eng.assert_before("原 5 台设备各唯一",
                      lambda s: all(s.count(d.encode()) == 1 for d in OLD_DEVICES))
    eng.assert_before("类型下拉原有 4 项各唯一",
                      lambda s: all(s.count(x.encode()) == 1 for x in DEV_TYPE_OPTS))

    eng.add_many(REPLACEMENTS)

    # 原 5 台设备逐字节保留且顺序不变 —— 「插入」不能变成「重排」
    def order_ok(s: bytes) -> bool:
        pos = [s.find(d.encode()) for d in OLD_DEVICES]
        return all(p != -1 for p in pos) and pos == sorted(pos)

    eng.assert_after("新设备串恰好 1 次", lambda s: s.count(NEW_DEV.encode()) == 1)
    eng.assert_after("新设备 status=online（同时进可用设备与参与设备下拉）",
                     lambda s: 'id:"device-006",name:"采摘机器人-01",'
                               'type:"pickingRobot",status:"online"'.encode() in s)
    eng.assert_after("原 5 台设备仍在且顺序不变", order_ok)
    eng.assert_after("Ze 设备池内现共 6 台（数 `{id:\"device-00`）",
                     lambda s: _ze_slice(s).count(b'{id:"device-00') == 6)
    eng.assert_after("类型映射含 pickingRobot",
                     lambda s: '采摘机器人"}[e]||"未知类型")'.encode() in s)
    eng.assert_after("原 3 个类型标签未动",
                     lambda s: 'drone:"无人机",robotDog:"机器狗",other:"履带机器人"'.encode() in s)
    eng.assert_after("筛选含 picking-robot 分支",
                     lambda s: b'"picking-robot"===Be.value&&"pickingRobot"===e.type' in s)
    eng.assert_after("下拉含新选项",
                     lambda s: '{label:"采摘机器人",value:"picking-robot"}'.encode() in s)
    eng.assert_after("类型下拉现共 5 项",
                     lambda s: all(s.count(x.encode()) == 1 for x in DEV_TYPE_OPTS)
                     and s.count('{label:"采摘机器人",value:"picking-robot"}'.encode()) == 1)
    eng.assert_after("未误伤协同任务数据",
                     lambda s: s.count(b'id:"collab-001"') == 1
                     and s.count(b'id:"collab-h001"') == 1 and s.count(b'id:"collab-h002"') == 1)
    eng.assert_after("未动电量随机游走",
                     lambda s: s.count(b"e.battery=Math.max(0,Math.min(100,e.battery+") == 1)
    eng.assert_after("未动 30 秒定时器",
                     lambda s: s.count(b"window.setInterval(") == 1)
    eng.assert_after("字符数增量 == 4 处插入片段长度之和",
                     lambda s: len(s) - len(raw)
                     == sum(len(n.encode()) - len(o.encode()) for _, o, n, _ in REPLACEMENTS))

    eng.expect_regions(len(REPLACEMENTS))       # 恰好 4 个差异区域
    return eng


def _ze_slice(s: bytes) -> bytes:
    i = s.find(b"Ze=c([")
    j = s.find(b"]),ea=c([", i)
    return s[i:j] if i != -1 and j != -1 else b""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?")
    ap.add_argument("-o", "--out", default=str(HERE / "out"))
    ap.add_argument("--name", default=None)
    args = ap.parse_args()

    src = Path(args.src) if args.src else _default_fixture()
    result = build_engine(src.read_bytes()).run()
    p = result.write(Path(args.out) / (args.name or src.name))
    print("\n已写出 %s" % p)
    return 0


def _default_fixture() -> Path:
    fx = HERE / "fixtures"
    cands = sorted(fx.glob("MultiDeviceCollaboration-*.js")) if fx.exists() else []
    if not cands:
        raise SystemExit("找不到原始 chunk，请先 `python -m tgpatch pull <活跃 chunk> -o fixtures`")
    return cands[0]


if __name__ == "__main__":
    raise SystemExit(main())
