# 源码级改法：调度系统 2023 → 2026

对应字节级方案见同目录 `patch.py`。**2 个文件，共 20 处日期。**

> 行号取自源码包 `smart-agriculture-skill-ai-h5`，见 `docs/source-level.md` 第 4 节。

## 先划范围，再替换

"把 AI 任务调度系统里所有 2023 改成 2026" 听起来是个全局替换。但**范围界定比替换本身重要**——
在压缩产物里全局替换 `2023` 会误伤三类东西：

| 不该动的 | 为什么 |
|---|---|
| `FarmlandMap-*.js` | 它属于 `/monitoring-center/3d-map`，根本不是 AI 调度系统 |
| `index-*.css` | 里面 2 处是 SVG path 坐标（`%2033.62` 这类） |
| `index-*.js` | 里面 3 处是随机数常量数组（`2150032023`） |

源码级下范围界定反而更轻松：**AI 调度系统的目录边界就是 `src/views/TaskScheduling/`**，
不用去猜 chunk 归属。直接在这个目录里搜就完了。

```bash
grep -rn "2023" src/views/TaskScheduling/
```

结果只有两个文件命中，与字节级路径"逐个 grep 确定只有 2 个 chunk 真正命中"的结论一致：

```
src/views/TaskScheduling/PeriodicTaskArrangement.vue:13 处
src/views/TaskScheduling/EmergencyTaskQueue.vue:3 处
```

---

## 文件 1/2：`src/views/TaskScheduling/PeriodicTaskArrangement.vue`

**13 处**（施加案例 02 后变 **17 处**），全部是 `taskList` 里的 ISO 日期串：

| 行 | 字段 | 内容 |
|---|---|---|
| L236 | `startTime` | `'2023-07-15T08:00:00Z'` |
| L240 | `createdAt` | `'2023-07-10T10:30:00Z'` |
| L241 | `updatedAt` | `'2023-07-10T10:30:00Z'` |
| L242 | `nextExecutionTime` | `'2023-07-16T08:00:00Z'` |
| L252 | `startTime` | `'2023-07-15T09:00:00Z'` |
| L256 | `createdAt` | `'2023-07-11T14:20:00Z'` |
| L257 | `updatedAt` | `'2023-07-11T14:20:00Z'` |
| L258 | `nextExecutionTime` | `'2023-07-22T09:00:00Z'` |
| L268 | `startTime` | `'2023-07-20T10:00:00Z'` |
| L272 | `createdAt` | `'2023-07-05T09:15:00Z'` |
| L273 | `updatedAt` | `'2023-07-20T15:45:00Z'` |
| L274 | `lastExecutedAt` | `'2023-07-20T12:30:00Z'` |
| L275 | `nextExecutionTime` | `'2023-08-20T10:00:00Z'` |

改法就是把每处的年份部分 `2023-` 换成 `2026-`，月份日份不动：

```diff
-    startTime: '2023-07-15T08:00:00Z',
+    startTime: '2026-07-15T08:00:00Z',
```

批量替换时**务必带上连字符**（替换 `'2023-` 而不是 `2023`）——万一以后有别的数字
里含 `2023`，带连字符能天然避开，与字节级方案用的同一个技巧。

---

## 文件 2/2：`src/views/TaskScheduling/EmergencyTaskQueue.vue`

**3 处**：

| 行 | 字段 | 内容 |
|---|---|---|
| L373 | `createdAt` | `'2023-08-10T08:30:00Z'` |
| L374 | `startedAt` | `'2023-08-10T08:35:00Z'` |
| L393 | `createdAt` | `'2023-08-10T09:15:00Z'` |

---

## 关于「17 处」这个数字

字节级方案里 `PeriodicTaskArrangement` 期望命中 **17** 处，而不是源码里的 13 处。
差的 4 处来自**案例 02 新增的那条任务**：

```
startTime           '2023-07-15T07:00:00Z'
createdAt           '2023-07-12T09:00:00Z'
updatedAt           '2023-07-12T09:00:00Z'
nextExecutionTime   '2023-07-16T07:00:00Z'
```

这也解释了字节级方案为什么必须按 **02 → 03 → 05** 的顺序施加：直接在原始产物上跑案例 03，
命中数只有 13，不足 17，补丁引擎会直接中止（这正是期望命中数断言的价值）。

源码级下不存在这个顺序问题——三处改动改的是同一批文件，先做哪个都行。

---

## 验证

```bash
npm run dev
# 打开 AI 任务调度系统 → 周期性巡航任务编排 / 应急任务队列
# 列表与详情里的日期年份应全部为 2026
```

另外确认**没改到不该改的**：

```bash
# 这三个地方应该还有 2023（它们不是日期）
grep -rn "2023" src/views/MonitoringCenter/FarmlandMap/ | head
```

---

## 一个遗留问题（两条路径都没解决）

年份改成 2026 后，`nextExecutionTime` 这类"下次执行时间"变成了 `2026-07-16`、`2026-08-20`，
相对于当前时间**落在过去**。界面上会显示成"已过期"。原始数据是 2023 年写的，
本意是"相对于当时的将来"。

真正合理的做法不是机械换年份，而是把这些时间字段改成**基于当前时间动态计算**
（比如 `dayjs().add(1, 'day')`）。这里保持与字节级方案一致，只做年份替换——
因为需求明确是"把 2023 改成 2026"。若要一并修，改 `PeriodicTaskArrangement.vue`
的 `taskList` 初值即可。
