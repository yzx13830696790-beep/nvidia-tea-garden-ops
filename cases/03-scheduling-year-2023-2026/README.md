# 案例 03 · AI 任务调度系统：2023 → 2026

| 项 | 值 |
|---|---|
| 模块 | `PeriodicTaskArrangement`、`EmergencyTaskQueue` |
| 改动点 | **2 个文件共 20 处**（17 + 3） |
| 输入 md5 | `0bc73a2a…`（案例 02 产物）、`0e7aa822…`（线上原始） |
| 产物 md5 | `662660a2e603c34a7c6f5c62e9895815`、`d008272e8c15fbb2b9b0d383401601c5` |
| 上游 | **必须施加在案例 02 的产物之上** |

## 需求

把 AI 任务调度系统里所有关于时间的 2023 改成 2026。

## 范围界定比替换本身重要

「全局把 2023 换成 2026」会误伤三类东西：

| 误伤对象 | 实际是什么 |
|---|---|
| `FarmlandMap-B8wwDWtu.js` | 属于 `/monitoring-center/3d-map`，根本不是调度系统 |
| `index-IpV8ITOi.css` | SVG path 坐标 `%20233.62` |
| `index-DAMuBsXX.js` | 随机数常量数组 `2150032023` |

### 第一步：圈定模块 chunk 全集

用「顶层路由块边界法」——在入口文件里从 `{path:"/task-scheduling"` 扫到下一个顶层路由，
中间 import 的 chunk 就是 AI 调度系统的全部页面：

```
TaskSchedulingLayout        PathPlanningEngine        PeriodicTaskArrangement
EmergencyTaskQueue          MultiDeviceCollaboration  TaskProgressVisualization
HistoryTrajectoryPlayback
```

再逐个 grep，确定实际含 `"2023-` 的只有 2 个。

### 第二步：换更精确的字面量

只替换 `"2023-`（**带引号带连字符**），即 ISO 日期串前缀。这样：

- SVG 坐标 `%20233.62` → 没有引号，不受影响
- 数字常量 `2150032023` → 没有 `"2023-`，不受影响

## ⚠️ 为什么必须接在案例 02 之后

期望命中数是 **17**，其中 4 处来自案例 02 新增的那条任务（`startTime` / `createdAt` /
`updatedAt` / `nextExecutionTime`）。直接在原始文件上跑会因命中数不足而中止——

**这是设计好的护栏，不是 bug。** 它保证了你不会在"以为已经加了任务"的前提下漏改。

## 运行

```bash
# 先跑案例 02；EmergencyTaskQueue 从线上取原始版本
python patch.py --dir ../02-periodic-picking-task/out
python -m tgpatch esm out/*.js --balance
python -m tgpatch deploy out PeriodicTaskArrangement-_PTsgACL.js,EmergencyTaskQueue-CH4Fc2Rv.js --tag t26
cd . && node e2e.js
```

## 已知未处理项（如实说明）

若干「下次执行时间」跟着年份一起变成了 2026-07 / 2026-08，落在当前时间之前。
本次需求只要求改年份，未调整月日。
