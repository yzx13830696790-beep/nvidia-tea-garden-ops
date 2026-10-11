# 案例 02 · 周期性巡航任务编排：新增「果园自动采摘任务」

| 项 | 值 |
|---|---|
| 页面 | `/task-scheduling/periodic-tasks` |
| 模块 | `PeriodicTaskArrangement` |
| 改动点 | **9 处** |
| 输入 md5 | `b9569e5b15adddab923a11c6dbc9832b` |
| 产物 md5 | `0bc73a2a63d2091bc9fd4d3ee805345c` |
| 下游 | 案例 03 → 案例 05（必须按此顺序） |

## 需求

在任务列表里加一行：名称「果园自动采摘任务」、类型「采摘任务」、周期「每天」、
设备数量 1、优先级 1 星、状态「等待中」。

## 为什么是 9 处

「加一条任务」在压缩产物里要同时改 9 个地方：

| # | 位置 | 内容 |
|---|---|---|
| 1 | 任务数组 | 追加 `task-4` |
| 2 | 类型映射 · 详情页 | `picking:"采摘任务"` |
| 3 | 类型映射 · 向导复核 | 同上（变量名 `ee`） |
| 4 | 类型映射 · 列表渲染 | 同上（变量名 `e`） |
| 5 | 下拉 · 编辑表单 | 补「采摘任务」选项 |
| 6 | 下拉 · 创建向导 | 补「采摘任务」选项 |
| 7 | 设备池 · 编辑表单 | 补 `device-007` |
| 8 | 设备池 · 创建向导 | 补 `device-007` |
| 9 | 分页 | `total:3` → `total:4` |

漏掉任何一处的后果：

- 漏 2/3/4 → 列表里显示「未知类型」
- 漏 5/6 → 编辑时选不到「采摘任务」
- 漏 7/8 → 找不到采摘机器人这个设备
- 漏 9 → 分页少一条，翻页时数据错位

所以脚本里用了 `expect_regions(9)`：改动点是 9 处，差异区域就必须恰好是 9 个。

## ⚠️ 前置守卫：本地副本必须是新版

这个 chunk 在本机留过两份副本，其中一份是**旧版**（把「果园」写成了「农田」）。
误用旧副本会把之前改好的文案**静默回退**——补丁本身完全成功、断言全过，
只是把旧内容又推上线了。

因此前置断言里要求 `农田` 出现 0 次：

```python
eng.assert_before("本地副本是新版（无「农田」残留）", lambda s: s.count("农田".encode()) == 0)
```

## 运行

```bash
python -m tgpatch locate PeriodicTaskArrangement
python -m tgpatch pull PeriodicTaskArrangement-_PTsgACL.js -o fixtures/
python patch.py
python -m tgpatch esm out/PeriodicTaskArrangement-_PTsgACL.js --balance
python -m tgpatch deploy out PeriodicTaskArrangement-_PTsgACL.js --tag per
cd . && node e2e.js
```

## 命名不统一（如实说明）

同一台采摘机器人在不同页面命名不一致，本次**未统一**：

| 出现位置 | 名称 |
|---|---|
| 周期性任务页（本案例） | `采摘机器人01` |
| 多机协同页（案例 04） | `采摘机器人-01` |
| 数智孪生中台 | `采摘机器人-001` |

另外，设备详情 / 编辑表单里显示的是原始 `deviceId`（`device-007`）而不是设备名。
