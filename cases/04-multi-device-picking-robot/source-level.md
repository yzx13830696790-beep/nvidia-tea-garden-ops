# 源码级改法：多机协同新增「采摘机器人-01」

对应字节级方案见同目录 `patch.py`。**5 处改动，全在同一个文件里。**

文件：`src/views/TaskScheduling/MultiDeviceCollaboration.vue`

> 行号取自源码包 `smart-agriculture-skill-ai-h5`，见 `docs/source-level.md` 第 4 节。

## 为什么不是「加一台设备」那么简单

需求是加一台「采摘机器人-01」。但 `pickingRobot` 是一个**此前不存在的设备类型**，
所以要同时在五个地方登记。只加数据的话，设备确实会出现在列表里，但类型标签显示
「未知类型」、筛选器里根本选不到它。

| # | 位置 | 漏掉的后果 |
|---|---|---|
| 1 | `DeviceInfoType` 类型联合 | **构建直接失败**（见下） |
| 2 | 设备池数组 | 列表里没有这台设备 |
| 3 | 类型 → 中文 映射 | 类型标签显示「未知类型」 |
| 4 | 类型筛选逻辑 | 筛选器选「采摘机器人」筛不出东西 |
| 5 | 设备类型下拉 | 根本没有这个筛选项 |

字节级方案只改 2/3/4/5 四处——因为类型定义只存在于源码，编译后就被抹掉了。
**这是两条路径的第一个实质性差异**：源码级多一处、且这一处漏了会挡住构建。

---

## 改动 1/5：类型联合（L536-546）⚠️ 漏了会构建失败

```diff
 interface DeviceInfoType {
   id: string;
   name: string;
-  type: 'drone' | 'robotDog' | 'other';
+  type: 'drone' | 'robotDog' | 'other' | 'pickingRobot';
   status: 'online' | 'offline' | 'busy' | 'charging' | 'error';
   battery: number;
   position: DevicePosition;
   capabilities: string[];
   avatar?: string;
   errorMessage?: string;
 }
```

为什么不加这一行就编译不过：`npm run build` 的实际命令是

```
vue-tsc --build && vite build
```

`vue-tsc` 先跑类型检查。`availableDevices = ref<DeviceInfoType[]>([...])` 里塞进
`type: 'pickingRobot'`，就会报：

```
Type '"pickingRobot"' is not assignable to type '"drone" | "robotDog" | "other"'.
```

这是**好事**——字节级路径没有这道防线，改错了要等跑起来才发现。

---

## 改动 2/5：设备池数组（L691 后）

```diff
   {
     id: 'device-005',
     name: '履带机器人-01',
     type: 'other',
     status: 'online',
     battery: 78,
     avatar: '',
     position: { x: 180, y: 140, z: 0 },
     capabilities: ['spray', 'heavy-load']
+  },
+  {
+    id: 'device-006',
+    name: '采摘机器人-01',
+    type: 'pickingRobot',
+    status: 'online',
+    battery: 88,
+    avatar: '',
+    position: { x: 200, y: 120, z: 0 },
+    capabilities: ['picking', 'monitor']
   }
 ])
```

### `status: 'online'` 这一项不是随便选的

页面里有两个派生列表，都从这个数组筛出来：

```ts
const filteredDevices = computed(...)      // 「可用设备」面板，带搜索/类型筛选
const currentCollaborationDevices = ref([]) // 「参与设备」下拉
// L1100: availableDevices.value.filter(d => d.status === 'online' || d.status === 'charging')
```

只要 `status` 是 `online` 或 `charging`，这一条记录就会**同时出现在两个地方**——
所以只加一条数据，效果却是「可用设备多了一台」+「选参与设备时也能选到它」。
如果写成 `'offline'`，第二个下拉里就没有它。

---

## 改动 3/5：类型映射（L1127-1134）

```diff
 const getDeviceTypeName = (type: string) => {
   const typeMap: Record<string, string> = {
     'drone': '无人机',
     'robotDog': '机器狗',
-    'other': '履带机器人'
+    'other': '履带机器人',
+    'pickingRobot': '采摘机器人'
   }
   return typeMap[type] || '未知类型'
 }
```

---

## 改动 4/5：类型筛选逻辑（L834-841）

`filteredDevices` 里是一串 `else if` 链：

```diff
     let matchesType = true
     if (deviceTypeFilter.value) {
       if (deviceTypeFilter.value === 'drone' && device.type === 'drone') {
         matchesType = true
       } else if (deviceTypeFilter.value === 'robot-dog' && device.type === 'robotDog') {
         matchesType = true
       } else if (deviceTypeFilter.value === 'track-robot' && device.type === 'other') {
         matchesType = true
+      } else if (deviceTypeFilter.value === 'picking-robot' && device.type === 'pickingRobot') {
+        matchesType = true
       } else {
         matchesType = false
       }
     }
```

注意这里两个字符串**长得不一样**：筛选值是 `'picking-robot'`（连字符），
而数据类型是 `'pickingRobot'`（驼峰）。原有的三对也都是这个规律
（`'robot-dog'` vs `'robotDog'`、`'track-robot'` vs `'other'`）——下拉用 kebab-case、
数据用 camelCase。写成一样的就筛不出来了。

这段 `else if` 链其实可以简化成查表，但这里保持原结构，改动最小。

---

## 改动 5/5：设备类型下拉（L46-51）

```diff
 <el-select v-model="deviceTypeFilter" placeholder="设备类型" ...>
   <el-option label="全部类型" value="" />
   <el-option label="无人机" value="drone" />
   <el-option label="机器狗" value="robot-dog" />
   <el-option label="履带机器人" value="track-robot" />
+  <el-option label="采摘机器人" value="picking-robot" />
 </el-select>
```

`value` 必须和改动 4 里的判断值一致。

---

## 验证

```bash
npm run build     # 先过 vue-tsc；类型联合没改的话这里就会红
npm run dev
```

打开 `/task-scheduling/multi-device-collaboration`：

1. 「可用设备」面板里应出现第 6 台：**采摘机器人-01**，类型标签是**采摘机器人**（不是"未知类型"）
2. 类型筛选下拉应多出「采摘机器人」一项，选中后列表只剩这一台
3. 点「创建协同任务」→ 参与设备下拉里应能选到它

字节级方案里 `e2e.js` 对这三条都有断言，可以直接复用：

```bash
node cases/04-multi-device-picking-robot/e2e.js
```

---

## 顺带一提：命名不统一

这台设备在不同页面叫的名字不一样：

| 页面 | 名字 |
|---|---|
| 周期性巡航任务编排 | 采摘机器人01 |
| 多机协同工作模式 | 采摘机器人-01 |
| 数智孪生中台 | 采摘机器人-001 |

本次改动只动多机协同页，所以用的是 `采摘机器人-01`。三处不统一是既存问题，
两条路径都没处理。
