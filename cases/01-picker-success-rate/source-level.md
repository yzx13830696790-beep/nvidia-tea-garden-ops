# 源码级改法：成功率区间改为 78~95

对应字节级方案见同目录 `patch.py`。**5 处改动，全在同一个文件里。**

文件：`src/views/DeviceManagement/PickerVehicleData.vue`

> 行号取自源码包 `smart-agriculture-skill-ai-h5`（803 行的 `PeriodicTaskArrangement` 那一版
> 同批）。该包为改造前基线，与线上产物存在漂移，见 `docs/source-level.md` 第 4 节。

---

## 改动 1/5：初始数据落进新区间

**L153-156**

```diff
 // 采摘成功率数据
 const successRateData = ref({
-  current: 96.2,
-  history: [99.7, 98.5, 96.8, 95.9, 97.2, 94.8, 87.3, 96.2],
+  current: 91.4,
+  history: [88.5, 92.7, 86.3, 94.1, 83.6, 79.8, 87.2, 91.4],
   timestamps: Array(8).fill(0).map(...)
 });
```

原来的 `current: 96.2` 已经超过上界 95，且 `history` 里有 `99.7` —— 折线图开局就出界。
新值全部落在 `[78, 95]`，且 `current` 与 `history` 末点一致（保持"当前值就是最新采样点"
这个隐含约定，否则图表与数字对不上）。

`tiltData` / `loadForceData` 两块**不动**——它们是车身姿态和机械臂负载，各自有各自的量程。

---

## 改动 2/5：最高成功率改为固定 95

**L39**

```diff
-<span class="stat-value">{{ Math.max(...successRateData.history).toFixed(1) }}%</span>
+<span class="stat-value">{{ (95).toFixed(1) }}%</span>
```

需求是"最高成功率显示 95"。原本取值于 8 点窗口的极值，会随数据滚动变化——
窗口里未必恰好出现 95，显示就会飘。改成常量。

`(95).toFixed(1)` 里那对括号不能省——直接写 `95.toFixed(1)` 会被解析成数字字面量的
小数点。保留 `.toFixed(1)` 是为了沿用原来的渲染格式（`95.0%`）。

---

## 改动 3/5：最低成功率改为固定 78

**L43**

```diff
-<span class="stat-value">{{ Math.min(...successRateData.history).toFixed(1) }}%</span>
+<span class="stat-value">{{ (78).toFixed(1) }}%</span>
```

同上一处。两块一起改，否则会出现"最高 95 / 最低 87"这类自相矛盾的组合。

---

## 改动 4/5：手动刷新按钮的步进（L431-433）

`refreshData()` 是"刷新数据"按钮的处理函数。

```diff
 const refreshData = () => {
   // 模拟数据更新
-  successRateData.value.current = Math.max(87, Math.min(95, successRateData.value.current + (Math.random() * 4 - 2)));
+  successRateData.value.current = reflectBand(successRateData.value.current + (Math.random() * 10 - 5), 78, 95);
```

注意这里原值本来就是 `[87, 95]`——比自动更新那个更窄。要让它能在整个 78~95 区间跑，
步长也要放大（±2 → ±5），否则从 91.4 出发要很多次才可能摸到 78。

---

## 改动 5/5：定时器的步进（L457-459）

`onMounted` 里注册的自动更新定时器，**这一处才是"动态显示值"的真正来源**。

```diff
 dataUpdateInterval = window.setInterval(() => {
   // 小幅度随机波动数据
-  successRateData.value.current = Math.max(85, Math.min(100, successRateData.value.current + (Math.random() * 3 - 1.5)));
+  successRateData.value.current = reflectBand(successRateData.value.current + (Math.random() * 8 - 4), 78, 95);
```

原区间 `[85, 100]` 与需求的 `[78, 95]` 差得最远，是必改的一处。

---

## 为什么不用 `Math.max(78, Math.min(95, v))`

最直觉的写法是 clamp。实测它会**冻在边界**：

随机游走一旦贴上 78，接下来的若干次刷新可能连续停在 `78.0` 纹丝不动
（当初线上观察到连续 5 个采样点、25 秒不变），用户会以为页面卡死。

所以改用**触边回弹**（镜像反射）：越界后立刻朝反方向走，既不出界也不滞留。

```
v > 95  ->  190 - v        (以 95 为轴镜像)
v < 78  ->  156 - v        (以 78 为轴镜像)
```

在源码里直接写一个小工具函数即可——源码是给人读的，不必像字节级补丁那样
为了塞进压缩产物而写成 IIFE：

```ts
/** 把 v 约束在 [lo, hi] 内；越界时沿边界镜像回弹，而不是停在边界上。 */
const reflectBand = (v: number, lo: number, hi: number) =>
  v > hi ? 2 * hi - v : v < lo ? 2 * lo - v : v;
```

放在 `<script setup>` 顶部即可，三个量程（成功率 / 姿态 / 负载）都能复用。

---

## 验证

```bash
npm run dev      # 打开设备管理 → 采摘机器人车载运行数据流
# 观察：动态值在 78~95 之间来回走，不会长时间停在 78.0 或 95.0
#       最高成功率恒为 95.0%，最低恒为 78.0%
```

字节级方案里有一个 `simulate_walk` 蒙特卡洛自证（2 万步内不越界、不滞留）。
源码级可以照搬这条检查，也可以直接跑：

```bash
python cases/01-picker-success-rate/patch.py --preflight-only
```

它会打印回弹版与 clamp 对照组的"最长贴边连续步数"——回弹版 2 步，clamp 版 15 步。
这条断言钉在 `tests/test_engine.py` 里。

**未改**：折线图的 `visualMap.pieces` 阈值仍是 80%（`[80,100]` 绿 / `[0,80)` 红）。
所以 78~79.9 的点会渲染成红色——如果需要一并调整，改这个文件的图表配置。
