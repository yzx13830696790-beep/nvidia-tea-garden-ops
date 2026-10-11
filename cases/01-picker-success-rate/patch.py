# -*- coding: utf-8 -*-
"""案例 01：采摘机器人车载运行数据流——成功率区间改为 78~95。

需求
----
「最高成功率」显示 95、「最低成功率」显示 78，动态值在 78~95 之间跳动。

改动点（5 处）
-------------
1. 初始数据 current/history —— 8 点窗口全部落进 [78,95]，且 current 与末点一致
2. 最高成功率渲染     -> 固定 95.0
3. 最低成功率渲染     -> 固定 78.0
4. 手动「刷新数据」按钮的步进 -> 区间 78~95 + 触边回弹
5. 5 秒定时器的步进         -> 区间 78~95 + 触边回弹

为什么不用 clamp
----------------
最直觉的写法是 ``Math.max(78, Math.min(95, v))``。实测下来它会「冻在边界」：
随机游走一旦贴上 78，接下来的几十次刷新可能连续停在 78.0 不动（我们观察到连续
5 个采样点、25 秒纹丝不动），用户会以为页面卡死。

所以改用**触边回弹**（镜像反射）：

    v > 95  ->  190 - v        (以 95 为轴镜像)
    v < 78  ->  156 - v        (以 78 为轴镜像)

越界后立刻朝反方向走，既不出界，也不滞留。形式上写成 IIFE 避免引入新变量名，
毕竟要插入的是压缩产物：

    (_v=>_v>95?190-_v:_v<78?156-_v:_v)(v + d)

运行
----
    # 1. 先定位活跃 chunk（同名副本可能有好几个）
    python -m tgpatch locate PickerVehicleData

    # 2. 取回当前线上版本
    python -m tgpatch pull PickerVehicleData-<hash>.js -o fixtures/

    # 3. 生成补丁（默认读 fixtures/，写到 out/）
    python patch.py

    # 4. 语法校验
    python -m tgpatch esm out/PickerVehicleData-<hash>.js --balance

    # 5. 部署
    python -m tgpatch deploy out PickerVehicleData-<hash>.js --tag veh
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tgpatch.patch import PatchEngine  # noqa: E402
from tgpatch.verify import simulate_walk  # noqa: E402

HERE = Path(__file__).resolve().parent
LO, HI = 78.0, 95.0
REFLECT = "(_v=>_v>95?190-_v:_v<78?156-_v:_v)"

REPLACEMENTS = [
    # 1. 初始数据：8 点窗口全部落在 78~95，current 与末点一致（保持原有数据结构）
    ("初始数据 current/history",
     "current:96.2,history:[99.7,98.5,96.8,95.9,97.2,94.8,87.3,96.2]",
     "current:91.4,history:[88.5,92.7,86.3,94.1,83.6,79.8,87.2,91.4]",
     1),

    # 2/3. 最高 / 最低成功率 -> 固定值
    ("最高成功率显示",
     "y(Math.max(...w.value.history).toFixed(1))",
     "y((95).toFixed(1))",
     1),
    ("最低成功率显示",
     "y(Math.min(...w.value.history).toFixed(1))",
     "y((78).toFixed(1))",
     1),

    # 4. 手动刷新：步长 ±2 -> ±5，触边回弹
    ("手动刷新 动态值",
     "w.value.current=Math.max(85,Math.min(100,w.value.current+(4*Math.random()-2)))",
     "w.value.current=%s(w.value.current+(10*Math.random()-5))" % REFLECT,
     1),

    # 5. 5 秒定时器：步长 ±1.5 -> ±4，触边回弹
    ("定时器 动态值",
     "w.value.current=Math.max(85,Math.min(100,w.value.current+(3*Math.random()-1.5)))",
     "w.value.current=%s(w.value.current+(8*Math.random()-4))" % REFLECT,
     1),
]

# 另外两块仪表盘必须原样保留（同页面回归）
UNTOUCHED = [
    ("车身姿态 clamp 未动", "Math.max(0,Math.min(25,", 2),
    ("机械臂负载 clamp 未动", "Math.max(10,Math.min(90,", 2),
    ("平均成功率逻辑未动", "w.value.history.reduce(", 1),
    # 注意：`min:0,max:100` 在页面上出现 2 次（成功率图 + 另一张图），
    # 所以这里的锚点必须带上 name 才唯一 —— 只数 `min:0,max:100` 会误判成 1。
    ("成功率图 yAxis 仍为 0..100", 'min:0,max:100,name:"成功率(%)"', 1),
]


def build_engine(raw: bytes, chunk_name: str) -> PatchEngine:
    eng = PatchEngine(raw, label="%s 成功率区间 %g~%g" % (chunk_name, LO, HI))

    # 前置：确认这是「没改过」的原始版本，且目标片段都还在
    eng.assert_before("可识别的原始版本（旧 clamp 恰好 2 处）",
                      lambda s: s.count(b"Math.max(85,Math.min(100,") == 2)
    eng.assert_before("旧初始值存在",
                      lambda s: b"current:96.2" in s)

    eng.add_many(REPLACEMENTS)

    # 后置：新写法到位、旧写法绝迹、同页其它逻辑未被误伤
    eng.assert_after("旧 clamp 已绝迹",
                     lambda s: b"Math.max(85,Math.min(100," not in s and b"Math.min(100," not in s)
    eng.assert_after("回弹表达式恰好 2 处",
                     lambda s: s.count(REFLECT.encode()) == 2)
    eng.assert_after("上/下界镜像系数各 2 处",
                     lambda s: s.count(b"190-_v") == 2 and s.count(b"156-_v") == 2)
    eng.assert_after("最高/最低不再是动态极值",
                     lambda s: b"Math.max(...w.value.history)" not in s
                     and b"Math.min(...w.value.history)" not in s)
    eng.assert_after("固定值渲染各 1 处",
                     lambda s: s.count(b'y((95).toFixed(1))+"%"') == 1
                     and s.count(b'y((78).toFixed(1))+"%"') == 1)
    for desc, needle, n in UNTOUCHED:
        eng.assert_after(desc, (lambda s, nd=needle, c=n: s.count(nd.encode()) == c))

    eng.expect_regions(len(REPLACEMENTS))       # 恰好 5 个差异区域
    return eng


def preflight() -> None:
    """上线前先用蒙特卡洛自证：永不越界、不冻边界、覆盖整个区间。"""
    print("=== 触边回弹行为预演（上线前自证）===")
    for label, scale in (("手动刷新 ±5", 5.0), ("定时器 ±4", 4.0)):
        st = simulate_walk(start=91.4, step_scale=scale, lo=LO, hi=HI, steps=20000, seed=7)
        first = ", ".join("%.1f" % v for v in st["values"][:12])
        print("  %-12s 2 万步 min=%.2f max=%.2f span=%.2f 最长贴边连续=%d 步"
              % (label, st["min"], st["max"], st["span"], st["max_edge_run"]))
        print("               前 12 步: %s" % first)
        assert st["min"] >= LO - 1e-9 and st["max"] <= HI + 1e-9, "越界了"
        assert st["span"] >= 16, "覆盖不到整个区间"
        assert st["max_edge_run"] < 8, "会长时间冻结在边界（这正是 clamp 的问题）"
    print("  ✓ 永不越界、覆盖全区间、不滞留边界\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", nargs="?", default=None, help="原始 chunk（默认 fixtures/ 下第一个）")
    ap.add_argument("-o", "--out", default=str(HERE / "out"), help="输出目录")
    ap.add_argument("--name", default=None, help="输出文件名（默认与源同名）")
    ap.add_argument("--preflight-only", action="store_true", help="只跑行为预演，不生成补丁")
    args = ap.parse_args()

    preflight()
    if args.preflight_only:
        return 0

    src = Path(args.src) if args.src else _default_fixture()
    raw = src.read_bytes()
    eng = build_engine(raw, src.name)
    result = eng.run()

    out = Path(args.out)
    name = args.name or src.name
    p = result.write(out / name)
    print("\n已写出 %s" % p)
    return 0


def _default_fixture() -> Path:
    cands = sorted((HERE / "fixtures").glob("PickerVehicleData-*.js")) if (HERE / "fixtures").exists() else []
    if not cands:
        raise SystemExit(
            "找不到原始 chunk。请先取回线上版本：\n"
            "  python -m tgpatch locate PickerVehicleData\n"
            "  python -m tgpatch pull <活跃 chunk> -o cases/01-picker-success-rate/fixtures"
        )
    return cands[0]


if __name__ == "__main__":
    raise SystemExit(main())
