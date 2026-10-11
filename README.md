# nvidia-tea-garden-ops

![regression](https://github.com/yzx13830696790-beep/nvidia-tea-garden-ops/actions/workflows/regression.yml/badge.svg)

果安云平台（tea-garden）前端的**可验证改造工具箱**——支持源码级与字节级两条路径。

线上是一套 Vite + Vue3 打包出来的 SPA：模块被切成带内容 hash 的 chunk，import 关系由入口
文件里的 `__vite__mapDeps` 索引数组决定。需求（改数值、加一条记录、换年份、加一个设备类型）
必须落到线上，而这个仓库提供两条路：

| 路径 | 前提 | 流程 |
|---|---|---|
| **源码级**（首选） | 拿得到 `src/` 且能跑通 `vite build` | 改 `.vue` → 构建 → 部署新产物 |
| **字节级**（兜底） | 只有 `dist/`，或构建环境已不可复现 | 定位活跃 chunk → 字节级精确替换 → 部署 |

```
字节级：定位活跃 chunk  →  字节级精确替换（带命中数断言）  →  ESM 语法校验
          →  部署进容器（md5 校验 + 自动备份）  →  HTTP 校验  →  浏览器端到端验证

源码级：改 src/*.vue  →  vue-tsc + vite build  →  整目录部署  →  同一套三层验证
```

一句话原则：**改之前先证明只有一个地方要改；改之后先证明没有别的地方被改到。**

两条路径不是"哪个更好"，而是对应两种现实：源码级有类型检查兜底、改动可读；
字节级不依赖构建环境、能精确落在一份**可能已经漂移**的产物上。真实项目里最常见的
恰恰是后者——源码在，但线上那份产物比源码新。详见 [docs/source-level.md](docs/source-level.md)。

---

## 为什么不能"直接改一下就好"

压缩产物里，一个看起来很小的需求往往要同时改很多处，而且**改错了不一定报错**：

| 需求 | 实际改动点 | 漏改的后果 |
|---|---|---|
| 成功率区间改成 78~95 | 5 处 | 数值越界、或冻在边界像卡死 |
| 列表加一条任务 | **9 处** | 数据显示"未知类型"、下拉选不到 |
| 新增一种设备类型 | **4 处** | 设备出现了，但标签是"未知类型" |
| 所有 2023 改成 2026 | 2 个文件 20 处 | 误伤 SVG 坐标和随机数常量 |

更麻烦的是**同名僵尸副本**：`PickerVehicleData-<hash>.js` 在 assets 里有多个不同 hash 的
版本。改错副本时，页面照常打开、HTTP 照常 200、界面毫无变化——因为浏览器加载的是另一份。

而"本地那份上次拉下来的副本"往往还是**旧版**。用旧版当基线会把上一次的改动静默回退掉
（真实踩过：已经改好的"果园"被退回成了"农田"）。

---

## 目录结构

```
tgpatch/                 核心库
├── config.py            目标机 / 容器 / 凭据（全部走环境变量，代码内无明文口令）
├── ssh.py               SSH 执行器（paramiko，缺失时回退到 scripts/ssh_run.py）
├── remote.py            宿主命令 / 容器内执行 / 字节级取回 / md5 校验部署 / 回滚
├── locate.py            入口识别、路由→chunk 映射、活跃副本判定、僵尸检测
├── sourcemap.py         用 .js.map 把 chunk 精确映射回 src/（含位置反查）
├── patch.py             字节级补丁引擎（替换表 + 前置/后置断言 + 可逆性自证 + 差异聚类）
├── validate.py          ESM 语法校验与沙箱求值
├── verify.py            HTTP 校验、浏览器端到端、随机游走蒙特卡洛
└── cli.py               统一命令行入口

cases/                   五个真实改造案例（均已在线上验证过）
├── 01-picker-success-rate/          车载数据流成功率区间改为 78~95（5 处）
├── 02-periodic-picking-task/        周期性任务列表新增"果园自动采摘任务"（9 处）
├── 03-scheduling-year-2023-2026/    调度系统 2023 → 2026（2 文件 20 处）
├── 04-multi-device-picking-robot/   多机协同新增"采摘机器人-01"（源码级 5 处 / 字节级 4 处）
└── 05-periodic-enable-default-off/  任务列表"启用"开关初始全部关闭（3 处）
    每个案例目录下：
      patch.py           字节级方案（声明式替换表 + 断言）
      source-level.md    源码级方案（精确到文件与行号）
      e2e.js             浏览器端到端断言
      README.md          需求、为什么是这么多处、验证方法

scripts/
├── esm_check.cjs        ESM 语法校验器（Node vm.SourceTextModule）
├── e2e_common.cjs       端到端公共层（登录、选页面、等渲染）
└── ssh_run.py           独立 SSH runner（tgpatch.ssh 的降级路径）

tests/
├── test_engine.py       引擎自检：合成字节，不依赖专有夹具（CI 实际执行的就是它）
└── test_pipeline.py     端到端回归：按 02→03→05 跑完并逐环节比对 md5（需夹具）

.github/workflows/regression.yml   CI：引擎自检 + md5 回归
docs/
├── methodology.md       字节级方法论与踩坑集
├── source-level.md      源码级路径：什么时候用、怎么和字节级互相印证
└── troubleshooting.md   故障排查
```

---

## 快速开始

```bash
git clone <this-repo> && cd nvidia-tea-garden-ops
pip install -r requirements.txt

cp .env.example .env
$EDITOR .env          # 填 TG_HOST / TG_SSH_PASSWORD，并把容器名与路径换成实际值
```

### 1. 先核对身份

内网 IP 会随网络环境变化，动手前务必确认连的是对的那台机器：

```bash
python -m tgpatch probe
```

输出目标机 hostname / 内核 / IP、容器列表、assets 文件数、入口文件名、mapDeps 长度、
路由数、前端 HTTP 状态。

### 2. 找到**活跃**的 chunk

```bash
python -m tgpatch locate PickerVehicleData
```

```
=== PickerVehicleData 的所有副本 ===
  PickerVehicleData-BWUD9G8B.js   11390 bytes  reachable=True  depth=2  refs=1
  PickerVehicleData-XXXX.js       11421 bytes  reachable=False depth=None refs=0

活跃 chunk : PickerVehicleData-BWUD9G8B.js
僵尸副本   : PickerVehicleData-XXXX.js
            （改这些没用，浏览器不会加载它们）
```

### 3. 取回 → 打补丁 → 校验

```bash
python -m tgpatch pull PickerVehicleData-BWUD9G8B.js -o cases/01-picker-success-rate/fixtures
cd cases/01-picker-success-rate && python patch.py
python -m tgpatch esm out/PickerVehicleData-BWUD9G8B.js --balance
```

补丁脚本会在**命中数不符**或**断言不通过**时中止，且**不写任何文件**。

### 4. 部署 → 三层验证

```bash
python -m tgpatch deploy cases/01-picker-success-rate/out PickerVehicleData-BWUD9G8B.js --tag veh
python -m tgpatch verify PickerVehicleData-BWUD9G8B.js --entry-chain \
    --must '(_v=>_v>95?190-_v:_v<78?156-_v:_v)' --mustnot 'Math.min(100,'
cd cases/01-picker-success-rate && node e2e.js
```

部署前会自动备份原文件（`.bak-<时间戳>`），可随时回滚：

```bash
python -m tgpatch backups PickerVehicleData-BWUD9G8B.js
python -m tgpatch rollback PickerVehicleData-BWUD9G8B.js PickerVehicleData-BWUD9G8B.js.bak-20261011120000
```

---

## 用 sourcemap 把产物对回源码

构建产物里的 `.js.map` 能让"改哪个 chunk""改的是源码哪一行"从推断变成确定答案。
本地目录即可用，不连远端：

```bash
# chunk -> 源文件（哪些 .vue 编译进了这个 chunk）
python -m tgpatch chunkmap dist/assets --chunk PeriodicTaskArrangement

# 源文件 -> chunk（改一个 .vue 要同步部署哪几个产物）
python -m tgpatch chunkmap dist/assets --source TaskScheduling/components

# 产物里的一段代码，反查它来自源码哪一行
python -m tgpatch chunkmap dist/assets --lookup "Math.max(85,Math.min(100,"
#   PickerVehicleData-C_olpgXX.js -> src/views/DeviceManagement/PickerVehicleData.vue:433:35

# 导出完整映射表
python -m tgpatch chunkmap dist/assets --json chunk-map.json
```

它给字节级路径补上了最关键的一块：**改动位置可被评审**。原来只能说"我改了产物里第
25349 个字节处"，现在能指到"源码第 433 行"。

一个真实的印证：字节级补丁说案例 02 的 9 处改动落在 `PeriodicTaskArrangement` 这一个
chunk 里；`chunkmap` 独立给出这个 chunk 恰好由 4 个源文件编译而成，9 处正好分布其中。

> 实现上有个坑值得记住：Source Map v3 的列号按 **UTF-16 码元**计，不是字节。
> 第一版按字节算，在纯 ASCII 的 chunk 上结果正好正确，换到中文密集的 chunk 上
> 行号偏了 100 多行。这条已经钉进 `tests/test_engine.py`。

---

## 补丁引擎的三条硬规则

```python
from tgpatch.patch import PatchEngine

eng = PatchEngine(raw, label="成功率区间 78~95")
eng.assert_before("旧 clamp 恰好 2 处", lambda s: s.count(b"Math.max(85,Math.min(100,") == 2)
eng.add("上界", b"Math.max(85,Math.min(100,", b"REFLECT(", count=2)
eng.assert_after("旧写法已绝迹", lambda s: b"Math.min(100," not in s)
eng.expect_regions(5)
result = eng.run()
result.write("out/chunk.js")
```

1. **命中数必须显式声明。** 压缩产物里同一片段出现多次是常态。声明 `count=2` 却只命中 1 次
   → 立刻中止。不声明命中数就等于不知道自己在改什么。
2. **可逆性自证。** 补丁跑完后对新内容施加逆替换，必须逐字节还原出原文件。这证明两个文件
   之间的差异**只有**声明的那几处——比"我改了 5 处"强得多。
3. **括号配平。** 括号数量必须守恒，否则几乎可以肯定是片段切错了。

另外两条默认开启：**差异区域聚类**（差异按间隔合并成区域，区域数应等于需求改动点个数）与
**原子写**（先写临时文件再替换，中途失败不留半个 chunk）。

---

## 自检与 CI

```bash
python tests/test_engine.py      # 不需要夹具、不需要凭据，克隆下来即可跑
```

夹具是线上真实构建产物、不入库，所以 `test_pipeline.py` 对任何克隆者都是空转的（只打印
一行「跳过」）。`test_engine.py` 用**合成字节**把引擎的每条硬规则都钉了一遍（97 项）：
入口识别绕开 Cesium、路由块边界、僵尸副本判定、命中数 / 可逆性 / 配平 / 区域数 / 原子写、
sourcemap 的 VLQ 往返与 UTF-16 列号语义，以及
**「反射式回弹 vs clamp 冻结在边界」**——把当初那个真实 bug 变成了一条会红的断言：

```
[OK] 最长贴边连续点数显著优于 clamp（这就是当初那个 bug）   reflect=2  clamp=15
[OK] 反射式回弹不会长时间滞留在边界   max_edge_run=2
```

CI（`.github/workflows/regression.yml`）每次 push 都跑它，并设 `TG_REQUIRE_NODE=1`：
缺 Node 时 ESM 校验**判失败**而不是静默跳过——否则那一道关会无声消失。整个工作流不连内网、
不需要任何凭据。

---

## ⚠️ 流水线顺序（重要）

`PeriodicTaskArrangement` 这个 chunk 被三个案例先后改动，**必须按顺序施加**：

```
案例 02 (加任务, 9 处)  →  案例 03 (2023→2026, 17 处)  →  案例 05 (开关默认关, 3 处)
    b9569e5b            →     0bc73a2a              →     662660a2            →    682cc5bf
```

- 案例 03 期望在 `PeriodicTaskArrangement` 命中 **17** 处，其中 4 处来自案例 02 新增的那条任务。
  直接在原始文件上跑会因命中数不足而中止——这是设计好的护栏，不是 bug。
- 案例 05 用 `priority:"low",status:"pending",enabled:!0,createdAt:` 锁定案例 02 新增的那一行。

```bash
python tests/test_pipeline.py   # 自动按顺序跑完并比对每一步的 md5
```

回归测试会把每个环节的输出 md5 与**当初部署上线并验证过的版本**逐一比对。这一步很关键：
把脚本"整理得更漂亮"的过程中很容易悄悄改变替换行为，而静态断言、语法校验、HTTP 校验
**都发现不了**这种偏移——只有 md5 能。

---

## 三层验证，各管一段

| 层级 | 能发现 | 发现不了 |
|---|---|---|
| 静态 | 替换文本在不在、命中数对不对、语法能否解析、括号是否配平 | 文件根本没被部署；部署到了僵尸副本 |
| HTTP | 部署是否生效、md5 是否一致、入口是否真的引用这个 chunk、路由是否 200 | 页面渲染出来到底是什么 |
| 浏览器 | 页面真的显示成什么样、点击/定时器行为、同页其它面板有没有被误伤 | 部署到了别的环境 |

**只做前两层就宣布成功的下场是：静态全绿、HTTP 全绿、打开页面毫无变化。**
详见 [docs/methodology.md](docs/methodology.md)。

---

## 安全约定

- **代码里没有任何明文口令。** 目标机地址、SSH / sudo 口令全部从 `.env` 或环境变量读取；
  缺失时直接报错，而不是用一个兜底默认值连上去。
- **示例值一律是占位符。** `.env.example`、`config.example.toml` 以及代码里的默认值
  （`deploy` / `webapp` / `/opt/webapp/web/dist/assets` / `8080`）都是编出来的，不对应
  任何真实环境；真实值只存在于你本机那个被忽略的 `.env` 里。
- `.env`、`config.toml`、`cases/*/fixtures/`（线上真实构建产物）、`cases/*/out/` 全部
  `.gitignore` 排除。
- 部署前自动备份，`rollback` 子命令可一键还原。
- 目标机 IP 会变。改之前先 `probe` 核对身份，别对着另一台机器改半天。

---

## 环境要求

- Python ≥ 3.11（用到 `tomllib`）；`pip install -r requirements.txt`
- Node.js ≥ 18（ESM 校验与端到端脚本）
- 端到端验证需要本机有 Chrome 或 Edge（无头模式即可）
- 被改造的环境需提供 SSH 访问 + Docker（容器内跑应用）

## 许可

MIT，见 [LICENSE](LICENSE)。
