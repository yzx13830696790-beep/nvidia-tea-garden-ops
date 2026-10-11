# 源码级改法：任务列表「启用」开关初始全部关闭

对应字节级方案见同目录 `patch.py`。**3 处改动，全在一个文件里**（若不含案例 02 新增的那条）。

文件：`src/views/TaskScheduling/PeriodicTaskArrangement.vue`

> 行号取自源码包 `smart-agriculture-skill-ai-h5`，见 `docs/source-level.md` 第 4 节。

## 需求边界：只改"列表 4 行的初始状态"

需求是表格里任务的「启用」开关初始状态全部为关闭。这句话有两种理解：

| 理解 | 改动范围 |
|---|---|
| **A（本方案）** 列表里现有任务的初始状态 | `taskList` 数组的 `enabled` 字段 |
| B 连同"新建任务"弹窗的默认值一起 | 还要改 `TaskCreationWizard` / `TaskEditForm` 的表单默认值 |

字节级方案只能做 A —— 因为压缩产物里两处表单默认值的文本**一字不差完全相同**
（都是 `priority:"medium",status:"pending",enabled:!0})`），没有任何办法只定位其中一处。
（详见 `patch.py` 文档串里的说明。）

**源码级没有这个限制**：两个默认值在两个不同的文件里，可以精确地只改一个、或都改。
本方案仍按 A 执行（需求说的是列表），但把 B 的位置也列在下面，需要时自行决定。

---

## 改动 1/3：task-1 北区农田定时巡逻（L239）

```diff
     priority: 'medium',
     status: 'pending',
-    enabled: true,
+    enabled: false,
     createdAt: '2023-07-10T10:30:00Z',
```

## 改动 2/3：task-2 周末喷洒任务（L255）

```diff
     priority: 'high',
     status: 'running',
-    enabled: true,
+    enabled: false,
     createdAt: '2023-07-11T14:20:00Z',
```

## 改动 3/3：task-4 果园自动采摘任务

这是**案例 02 新增**的那条任务（`enabled: true`）。如果你按 02 → 05 的顺序做，
这时它已经在文件里了，一并改掉：

```diff
     startTime: '2026-07-15T07:00:00Z',
     priority: 'low',
     status: 'pending',
-    enabled: true,
+    enabled: false,
     createdAt: '2026-07-12T09:00:00Z',
```

⚠️ **顺序耦合**：如果先做案例 05、再做案例 02，那么在案例 02 新增任务时就该直接写
`enabled: false`。否则新加的那条会是唯一一个默认开启的任务。

---

## task-3 不用动

`task-3 月度病虫害检查`（L271）本来就是 `enabled: false`。改完之后文件里
应该**一处 `enabled: true` 都不剩**（在 `taskList` 范围内）。

自查：

```bash
sed -n '227,300p' src/views/TaskScheduling/PeriodicTaskArrangement.vue | grep -c "enabled: true"
# 期望输出 0
```

---

## 可选：改动 B —— 新建/编辑弹窗的默认值

如果需求也包含"以后新建的任务默认不启用"，改这两处：

| 文件 | 行 | 内容 |
|---|---|---|
| `components/TaskCreationWizard.vue` | L296 | 表单初始值 `enabled: true` |
| `components/TaskEditForm.vue` | L216 | 表单初始值 `enabled: true` |

这两个默认值出现在**两个不同文件**里，源码级下可以分别定位，字节级下不行——
这是两条路径的第二个实质性差异。

**未纳入本方案**，因为需求原文是"周期性巡航任务编排中全部启用按钮初始状态改为未启用状态"，
指的是列表。

---

## 关于「全部启用按钮」

界面上有两个批量按钮（L124-125）：

```vue
<el-button :disabled="!hasSelection" @click="batchEnable(true)">批量启用</el-button>
<el-button :disabled="!hasSelection" @click="batchEnable(false)">批量禁用</el-button>
```

它们**不需要改**——`batchEnable` 只作用于用户勾选的行，与初始状态无关。
需求里的"全部启用按钮"指的是表格每行的启用开关（`row.enabled`），不是这个批量按钮。

---

## 验证

```bash
npm run dev
# 打开 AI 任务调度系统 → 周期性巡航任务编排
# 4 行的「启用」开关初始应全部为关闭状态
```

字节级方案的 `e2e.js` 里有个容易踩的坑值得复用：Element Plus 的 `.el-switch` 上
`aria-checked` 并不在根元素上，而在内层 `.el-switch__input`；而且 `active-text` 与
`inactive-text` 两个标签**都可见**（靠 CSS 显隐），不能用"可见性"判断开关状态。
读权威值应该用内层元素的 `aria-checked`：

```js
await page.locator('.el-table__row .el-switch__input').first().getAttribute('aria-checked')
```

另外 `.el-button-group` 并非只属于批量按钮——行内操作按钮也用，所以要按文本前缀过滤，
不能只按 class 取。
