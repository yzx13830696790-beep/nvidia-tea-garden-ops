# 案例 04 · 多机协同工作模式：新增「采摘机器人-01」

> **两种改法**：[`patch.py`](patch.py) 是**字节级**方案（4 处）；
> [`source-level.md`](source-level.md) 是**源码级**方案（**5 处**——多出的一处是
> TypeScript 类型联合，不补上 `vue-tsc` 会直接让构建失败）。

| 项 | 值 |
|---|---|
| 页面 | `/task-scheduling/multi-device-collaboration` |
| 模块 | `MultiDeviceCollaboration` |
| 改动点 | **4 处** |
| 输入 md5 | `7370090f1957518baabf79df968deb65` |
| 产物 md5 | `c27579d70ed986a7a4d2368ce889fe53` |

## 需求

在「可用设备」列表里加一台名为「采摘机器人-01」的设备。

## 为什么是 4 处

新增一种**此前不存在的设备类型**（`pickingRobot`），要在四个地方同时登记：

| # | 位置 | 内容 |
|---|---|---|
| A | 设备池 `Ze=c([...])` | 追加 `device-006`，`status:"online"` |
| B | 类型标签映射 `ha` | `pickingRobot:"采摘机器人"` |
| C | 类型筛选逻辑 | `"picking-robot"===Be.value&&"pickingRobot"===e.type` |
| D | 类型下拉 | `{label:"采摘机器人",value:"picking-robot"}` |

只做 A 的话，设备确实会出现在列表里，但**类型标签显示「未知类型」**、**筛选器选不到它**、
**下拉里没有这个类型**。

## status 选 online 的连锁效果

页面里有两个派生列表：

- `na = Ze.value.filter(...)` → 「可用设备」面板
- `oa = Ze.value.filter(...)` → 「参与设备」下拉（只取 `online` / `charging`）

所以只要 `status:"online"`，**一条数据会同时出现在两个地方**。这是"只加一条记录，
效果却是可用设备多了一台 + 选择参与设备时也能选到它"的原因。

## ⚠️ 断言必须用完整对象，不能用截断前缀

`{id:"device-002",...,battery:65` 这种前缀在文件里会出现 **2 次**：

- 一次是设备池里的无人机-02
- 一次是协同任务数据里的同名引用（字段是 `speed:3.2` 而不是 `avatar:""`）

带上前缀的 `,avatar:""` 或完整的 `capabilities:[...]}` 才能唯一定位设备池里那一份。

## 运行

```bash
python -m tgpatch locate MultiDeviceCollaboration
python -m tgpatch pull MultiDeviceCollaboration-xV5LwVm2.js -o fixtures/
python patch.py
python -m tgpatch esm out/MultiDeviceCollaboration-xV5LwVm2.js --balance
python -m tgpatch deploy out MultiDeviceCollaboration-xV5LwVm2.js --tag multi
cd . && node e2e.js
```

## 同页回归（必须不动）

- 原 5 台设备逐字节保留，且**顺序不变**（「插入」不能变成「重排」）
- 原 3 个类型标签：`drone` / `robotDog` / `other`
- 原 4 个下拉项：全部类型 / 无人机 / 机器狗 / 履带机器人
- 电量随机游走 `e.battery=Math.max(0,Math.min(100,e.battery+` ×1
- 30 秒定时器 `window.setInterval(` ×1
- 协同任务数据 `collab-001` / `collab-h001` / `collab-h002` 各 1 次

## 命名不统一（如实说明）

同一台采摘机器人不同页面名称不同：`采摘机器人-01`（本页）/ `采摘机器人01`（周期任务页）/
`采摘机器人-001`（数智孪生中台）。
