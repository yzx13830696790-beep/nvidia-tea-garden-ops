# 源码级改法：新增「果园自动采摘任务」

对应字节级方案见同目录 `patch.py`。**9 处改动，跨 4 个文件。**

> 行号取自源码包 `smart-agriculture-skill-ai-h5`。该包为改造前基线，任务名用的是
> 「农田」而线上是「果园」，见 `docs/source-level.md` 第 4 节。

## 为什么是 9 处

"加一行任务"看起来是一处改动，实际要同时改 9 个地方。漏掉任何一个都会出问题：

| # | 位置 | 漏掉的后果 |
|---|---|---|
| 1 | 任务数组 | 没有数据 |
| 2-4 | 三处 `type → 中文` 映射 | 列表和详情页显示「未知类型」 |
| 5-6 | 两处「任务类型」下拉 | 新建任务时选不到「采摘任务」 |
| 7-8 | 两处设备池 | 选不到执行设备 |
| 9 | 分页 `total` | 列表底部显示"共 3 条"但实际 4 行 |

字节级方案用 `eng.expect_regions(9)` 强制核对差异区域数——只改了 8 处就直接报错。
源码级没有这层保护，所以更要按下面的清单逐条对。

---

## 文件 1/4：`src/views/TaskScheduling/PeriodicTaskArrangement.vue`

### 改动 1/9：追加第 4 条任务（L276-277）

在 `taskList` 数组末尾（第 3 条任务之后）追加：

```diff
     lastExecutedAt: '2023-07-20T12:30:00Z',
     nextExecutionTime: '2023-08-20T10:00:00Z'
+  },
+  {
+    id: '4',
+    name: '果园自动采摘任务',
+    description: '每天对果园进行自动采摘作业',
+    type: 'picking',
+    deviceIds: ['device-007'],
+    cycleType: 'daily',
+    cycleValue: 1,
+    startTime: '2023-07-15T07:00:00Z',
+    priority: 'low',
+    status: 'pending',
+    enabled: true,
+    createdAt: '2023-07-12T09:00:00Z',
+    updatedAt: '2023-07-12T09:00:00Z',
+    nextExecutionTime: '2023-07-16T07:00:00Z'
   }
 ]);
```

字段解释：

- `priority: 'low'` —— 需求是"优先级一颗星"。星级由 `getPriorityValue` 映射
  （L369-376），`low → 1`。
- `status: 'pending'` —— 需求"等待中"，`getStatusLabel` 映射（L336-345）。
- `cycleType: 'daily', cycleValue: 1` —— 需求"每天"。`getCycleLabel` 会渲染成「每天」
  （`cycleValue > 1` 时才带数字）。
- `deviceIds: ['device-007']` —— "设备数量 1"。这个 id 必须在第 7、8 步的设备池里存在，
  否则详情页显示不出设备名。
- 三个时间字段保持 `2023-07` 不动 —— 它们会被案例 03 统一改成 2026。

### 改动 2/9：类型映射（L316-323）

```diff
 const getTaskTypeLabel = (type: string) => {
   const map: Record<string, string> = {
     'patrol': '巡逻任务',
     'spray': '喷洒任务',
     'inspection': '检查任务',
+    'picking': '采摘任务',
     'other': '其他任务'
   };
   return map[type] || '未知类型';
 };
```

位置放在 `'other'` **之前**。顺序不影响功能，但和下拉框的排列保持一致更易读。

### 改动 3/9：分页计数（L291-295）

```diff
 const pagination = reactive({
   currentPage: 1,
   pageSize: PAGINATION_CONFIG.DEFAULT_PAGE_SIZE,
-  total: 3
+  total: 4
 });
```

---

## 文件 2/4：`src/views/TaskScheduling/components/TaskCreationWizard.vue`

这个文件被 `PeriodicTaskArrangement.vue` 导入，所以**编译进同一个 chunk**。
只改主文件、不改这里，就会出现"列表里有这条任务，但新建向导选不了采摘类型"。

### 改动 4/9：类型映射（L364-369）

```diff
     'patrol': '巡逻任务',
     'spray': '喷洒任务',
     'inspection': '检查任务',
+    'picking': '采摘任务',
     'other': '其他任务'
```

### 改动 5/9：任务类型下拉（L45-48）

```diff
 <el-option label="巡逻任务" value="patrol" />
 <el-option label="喷洒任务" value="spray" />
+<el-option label="采摘任务" value="picking" />
 <el-option label="检查任务" value="inspection" />
 <el-option label="其他任务" value="other" />
```

### 改动 6/9：设备池（L336-343）

```diff
 const devices = [
   { id: 'device-001', name: '机器狗 Alpha-X' },
   { id: 'device-002', name: '机器狗 Beta-Z' },
   { id: 'device-003', name: '无人机 Sky-7' },
   { id: 'device-004', name: '无人机 Aero-9' },
   { id: 'device-005', name: '捕虫灯 LT-200' },
-  { id: 'device-006', name: '超声波装置 US-50' }
+  { id: 'device-006', name: '超声波装置 US-50' },
+  { id: 'device-007', name: '采摘机器人01' }
 ];
```

---

## 文件 3/4：`src/views/TaskScheduling/components/TaskEditForm.vue`

### 改动 7/9：任务类型下拉（L38-41）

```diff
 <el-option label="巡逻任务" value="patrol" />
 <el-option label="喷洒任务" value="spray" />
+<el-option label="采摘任务" value="picking" />
 <el-option label="检查任务" value="inspection" />
 <el-option label="其他任务" value="other" />
```

### 改动 8/9：设备池（L263-270）

```diff
 const devices = [
   { id: 'device-001', name: '机器狗 Alpha-X' },
   ...
-  { id: 'device-006', name: '超声波装置 US-50' }
+  { id: 'device-006', name: '超声波装置 US-50' },
+  { id: 'device-007', name: '采摘机器人01' }
 ];
```

⚠️ 这里的 `devices` 数组与 `TaskCreationWizard.vue` 里的**逐字相同**。
复制粘贴很容易只改一处，所以两个文件都要单独确认。

---

## 文件 4/4：`src/views/TaskScheduling/components/TaskDetailView.vue`

### 改动 9/9：类型映射（L155-160）

```diff
     'patrol': '巡逻任务',
     'spray': '喷洒任务',
     'inspection': '检查任务',
+    'picking': '采摘任务',
     'other': '其他任务'
```

这是三处映射里最容易漏的一处——它在**详情页**，只有点进某条任务才看得到，
列表页不会暴露问题。

---

## 怎么确认没漏

三处映射的分母是一致的，可以直接数：

```bash
grep -rn "'其他任务'" src/views/TaskScheduling/
# 应该 5 行：3 处映射 + 2 处下拉
```

改完之后，源码里 `'采摘任务'` 应恰好出现 5 次（3 映射 + 2 下拉），
`'device-007'` 应恰好出现 3 次（任务数据 1 + 设备池 2），
`'picking'` 应恰好出现 4 次（1 任务数据 + 3 映射）。

**独立印证**：这个 chunk 由哪几个源文件编译而成，可以用 sourcemap 直接问：

```bash
python -m tgpatch chunkmap dist/assets --chunk PeriodicTaskArrangement
# PeriodicTaskArrangement-rL475vF1.js
#     src/views/TaskScheduling/components/TaskDetailView.vue
#     src/views/TaskScheduling/components/TaskEditForm.vue
#     src/views/TaskScheduling/components/TaskCreationWizard.vue
#     src/views/TaskScheduling/PeriodicTaskArrangement.vue
```

正好是上面这 4 个文件。当初字节级补丁是在压缩产物上盲改的，落到这 4 个文件里，
和这里逐处对应——两条独立路径互相印证。

---

## 验证

```bash
npm run dev
# 1. 任务列表应出现第 4 行：果园自动采摘任务 / 采摘任务 / 每天 / 1 / ★ / 等待中
# 2. 列表底部页码总数应为 4
# 3. 点「新建任务」→ 类型下拉里应有「采摘任务」→ 设备选择里应有「采摘机器人01」
# 4. 点开这条任务详情，类型应显示「采摘任务」而不是「未知类型」
```

注意本案例是**流水线第一步**：产出的文件还要依次过案例 03（年份改 2026）和案例 05
（启用开关默认关闭）。源码级下顺序无所谓（都是改同一批文件），但字节级必须 02 → 03 → 05。
