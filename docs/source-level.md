# 源码级改造：当源码拿得到的时候

这个仓库最初只为一种局面准备：**线上跑着一份 Vite 构建产物，源码拿不到，但需求必须落地。**
于是有了「定位活跃 chunk → 字节级精确替换 → 三层验证」这条流水线。

后来拿到了同一系统的源码包（`smart-agriculture-skill-ai-h5`，与线上同源但为更早的基线）。
于是这个仓库补上第二条路径——**源码级改造**：改 `src/`、重新 build、部署新产物。

本文说明两条路径各自适用什么场景、怎么选、怎么互相印证。

---

## 1. 两条路径的取舍

| | 源码级（本文） | 字节级（`docs/methodology.md`） |
|---|---|---|
| 前提 | 拿得到 `src/`，且能跑通 `vite build` | 只有 `dist/`，或构建环境已不可复现 |
| 改动方式 | 改 `.vue` / `.ts` 源文件 | 在压缩产物上做字节替换 |
| 可读性 | 改的是原始可读代码 | 改的是 `Math.max(85,Math.min(100,w.value.current+…` |
| 影响面 | 无限制（可以重构、可以加组件） | 只能做**等价替换**，不能改结构 |
| 风险 | 构建产物可能与线上不一致（配置漂移） | 可能改错同名副本 / 改到僵尸 chunk |
| 回滚 | 重新构建上一版 | 备份文件直接还原（`tgpatch rollback`） |
| 验证成本 | 需要能跑起构建（依赖、node 版本） | 只要有 md5 就能验证 |

**判断顺序**：先问"源码在不在、且能不能构建出与线上一致的产物"。

- 能 → 走源码级，这是正解。
- 不能（源码缺失、依赖装不上、构建配置丢失、产物已手工改过）→ 走字节级。

现实里更常见的是**混合**：源码在，但线上那份产物比源码新（已经有人改过、或构建配置不同）。
这种情况下源码级改动**不能直接上线**——会顺带把别的新改动一起回滚掉。本仓库的五个案例
就属于这一类，见第 4 节。

---

## 2. 源码级改造流程

```bash
# 0. 装依赖（一次性）
npm ci

# 1. 改源码（见 cases/*/source-level.md 的逐处说明）
$EDITOR src/views/TaskScheduling/PeriodicTaskArrangement.vue

# 2. 本地起开发服务器，肉眼确认
npm run dev

# 3. 类型检查 + 构建
npm run build          # = vue-tsc --build && vite build

# 4. 把 dist/ 部署到容器
#    产物文件名带内容 hash，所以整目录替换比按文件名替换更稳妥
docker cp dist/. <容器>:/opt/webapp/web/dist/

# 5. 验证（与字节级路径共用同一套）
python -m tgpatch verify <入口>.js --entry-chain --routes /task-scheduling
node scripts/e2e_common.cjs <某个 case 的 e2e.js>
```

要点：

- **产物文件名会变。** 改一个 `.vue`，它的 chunk hash 会变（`PeriodicTaskArrangement-rL475vF1.js`
  → `PeriodicTaskArrangement-<新hash>.js`），入口文件 `index-*.js` 也会变。所以字节级那套
  "按名字替换单个文件" 的做法在这里不适用，要整目录同步——否则浏览器会拿着旧入口去要
  一个已经不存在的老 chunk，白屏。
- **`.js.map` 不要上线。** 它会把源码原文（`sourcesContent`）一起暴露出去。
  Vite 默认生产构建不产出 map；如果为了排查问题临时开了 `build.sourcemap`，部署前记得关掉。
- **验证仍然必要。** 源码级不代表不会出错：改错文件、改错分支、构建缓存都可能让改动没生效。
  第 5 步的三层验证一样要跑。

---

## 3. 用 sourcemap 把两条路径接起来

`tgpatch.sourcemap` 解析构建产物里的 `.js.map`，把 chunk 精确映射回源文件。
它解决两个问题。

### 3.1 确认"改哪个 chunk"不再靠猜

字节级路径判断 chunk 归属，一直是靠入口文件里的 `__vite__mapDeps` 索引数组和路由字符串
推断（`locate.chunks_of_route`）。一旦构建配置变了（多入口、路由拆分），这套推断就失效。

有了 map 就是精确答案：

```bash
$ python -m tgpatch chunkmap dist/assets --chunk PeriodicTaskArrangement
PeriodicTaskArrangement-rL475vF1.js
    src/views/TaskScheduling/components/TaskDetailView.vue
    src/views/TaskScheduling/components/TaskEditForm.vue
    src/views/TaskScheduling/components/TaskCreationWizard.vue
    src/views/TaskScheduling/PeriodicTaskArrangement.vue
```

反向也行——改一个 `.vue` 时，立刻知道要同步部署哪几个 chunk：

```bash
$ python -m tgpatch chunkmap dist/assets --source TaskScheduling/components
```

### 3.2 给字节级改动做"位置取证"

这是最有用的一条。字节级补丁改的是压缩后的位置，评审时没法确认改对了地方。
用 map 可以反查：**产物里这段代码，原本写在源码的第几行。**

```bash
$ python -m tgpatch chunkmap dist/assets --lookup "Math.max(85,Math.min(100,"
PickerVehicleData-C_olpgXX.js  ->  src/views/DeviceManagement/PickerVehicleData.vue:433:35  (原名 Math)
```

源码第 433 行确实是：

```ts
successRateData.value.current = Math.max(85, Math.min(100, successRateData.value.current + (Math.random() * 4 - 2)));
```

（`(原名 Math)` 是压缩前这个位置的标识符名——map 的 `names` 字段还原出来的。）

### 3.3 一个踩过的坑：列号是 UTF-16 码元，不是字节
第一版实现里，`lookup_text` 用**字节偏移**当列号喂给映射表。在纯 ASCII 的
`PickerVehicleData.js` 上结果正好正确，于是没被发现；换到中文密集的
`PeriodicTaskArrangement.js` 上，同样一段中文串反查出来的行号偏了 100 多行。

原因：Source Map v3 规定列号以 **UTF-16 码元**计。压缩产物里每个汉字占 3 个 UTF-8 字节
但只占 1 个码元，字节列号会随中文数量线性膨胀。

修法是先按字符定位、再折算成码元数（`sourcemap.utf16_len`）。修完之后：

| 产物中的串 | 反查结果 | 源码实际位置 |
|---|---|---|
| `北区农田定时巡逻` | `PeriodicTaskArrangement.vue:230` | ✓ 230 |
| `2023-07-15T08:00:00Z` | `PeriodicTaskArrangement.vue:236` | ✓ 236 |
| `履带机器人-01` | `MultiDeviceCollaboration.vue:684` | ✓ 684 |
| `2023-08-10T08:30:00Z` | `EmergencyTaskQueue.vue:373` | ✓ 373 |

---

## 4. 五个案例的两条路径对照

源码包 `smart-agriculture-skill-ai-h5` 是**改造前的基线**，五个案例的源文件都能对上。
下表把字节级补丁的每一处，对应到源码位置——后者由 `chunkmap --lookup` 逐条取证。

| 案例 | 源文件 | 源码位置 | 字节级 & 源码级是否等价 |
|---|---|---|---|
| 01 成功率区间 | `DeviceManagement/PickerVehicleData.vue` | L39 / L43 / L155-156 / L433 / L459 | 等价（5 处） |
| 02 加采摘任务 | `TaskScheduling/PeriodicTaskArrangement.vue` 等 **4 个文件** | 3 映射 + 2 下拉 + 2 设备池 + 任务数据 + total | 等价（9 处） |
| 03 年份 2023→2026 | `PeriodicTaskArrangement.vue` / `EmergencyTaskQueue.vue` | 13 + 3 处（加任务后 17 + 3） | 等价（20 处） |
| 04 加采摘机器人 | `TaskScheduling/MultiDeviceCollaboration.vue` | L50 / L684 / L835-837 / L1132 | 源码级**多 1 处**（类型联合） |
| 05 启用默认关 | `TaskScheduling/PeriodicTaskArrangement.vue` | L239 / L255 / 新增任务那处 | 等价（3 处） |

案例 02 的对应关系尤其值得看：字节级补丁说"映射 3 处 + 下拉 2 处 + 设备池 2 处，
落在 `PeriodicTaskArrangement` 那一个 chunk 里"。而 `chunkmap` 独立给出这个 chunk
**恰好由 4 个源文件编译而成**（`PeriodicTaskArrangement.vue` + `TaskCreationWizard.vue`
+ `TaskEditForm.vue` + `TaskDetailView.vue`），改动正好分布在这 4 个文件里。
两条独立证据互相印证。

案例 04 则相反——**源码级比字节级多一处**。`DeviceInfoType.type` 是个联合类型
`'drone' | 'robotDog' | 'other'`，不加上 `'pickingRobot'`，`vue-tsc` 会直接让构建失败。
这一处在编译后被抹掉了，所以字节级路径根本不存在这道防线。
（见 `cases/04-multi-device-picking-robot/source-level.md`）

两条路径不是简单的"哪个更好"：源码级有类型检查兜底、改起来可读；
字节级不依赖构建环境、能精确落在一份可能已经漂移的产物上。

### ⚠️ 一个必须知道的差异：源码比线上旧

本源码包里这份基线用的是 **「农田」**（`北区农田定时巡逻`、`南区农田`、`field-001`），
而线上部署版是 **「果园」**。也就是说这套源码**不是线上那份产物的直接来源**。

因此：

- `cases/*/source-level.md` 里的行号是**针对这个源码包**的，不是针对线上产物。
- 直接拿这套源码改完构建上线，会把线上已经发生的其它变更（比如"农田→果园"）一并回退。
- 正确做法是**把源码级改动当参考实现**，落到真正与线上同源的那份源码上；
  或者先确认线上产物就是从这套源码构建出来的，再走源码级路径。

这也正好说明字节级路径为什么仍然必要——它是"源码与线上不一致"时唯一能精确落地的办法。
