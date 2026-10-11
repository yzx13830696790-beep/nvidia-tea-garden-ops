# 案例 01 · 采摘机器人车载运行数据流：成功率区间改为 78~95

| 项 | 值 |
|---|---|
| 页面 | `/device-management/picker-vehicle-data` |
| 模块 | `PickerVehicleData` |
| 改动点 | **5 处** |
| 夹具 md5（原始） | `ffc009140d153f4d89e34b785753b5e4` |
| 产物 md5 | `2493ad757eb4ad4410ccd6a7a9d1c0e8` |

## 需求

「最高成功率」显示 95、「最低成功率」显示 78，动态显示的当前成功率在 78~95 之间跳动。

## 5 处改动

1. 初始数据 `current` / `history` —— 8 点窗口全部落进 `[78,95]`，`current` 与末点一致
2. 最高成功率渲染 → 固定 `95.0`
3. 最低成功率渲染 → 固定 `78.0`
4. 手动「刷新数据」按钮的步进 → 区间 78~95 + 触边回弹
5. 5 秒定时器的步进 → 区间 78~95 + 触边回弹

## 关键点：为什么不用 clamp

最直觉的写法 `Math.max(78, Math.min(95, v))` 会**冻在边界**。随机游走一旦贴上 78，
接下来可能连续多次输出完全相同的 `78.0`——实测连续 5 个采样点、25 秒纹丝不动，
用户会认为页面卡死。

改用**触边回弹**（以边界为轴镜像）：

```js
(_v => _v > 95 ? 190 - _v : _v < 78 ? 156 - _v : _v)(v + d)
//                 ↑ 2*95              ↑ 2*78
```

越界后立刻反向，既不出界也不滞留。写成 IIFE 是为了不引入新顶层标识符——
插入的是压缩产物，多一个短名就可能与既有变量冲突。

上线前的自证（`preflight()`）：

```
手动刷新 ±5   2 万步 min=78.00 max=95.00 span=17.00 最长贴边连续=2 步
定时器 ±4     2 万步 min=78.00 max=95.00 span=17.00 最长贴边连续=1 步
✓ 永不越界、覆盖全区间、不滞留边界
```

## 同页回归（必须不动）

- 车身姿态监测：`Math.max(0,Math.min(25,` ×2
- 机械臂作业负载：`Math.max(10,Math.min(90,` ×2
- 平均成功率逻辑：`w.value.history.reduce(` ×1
- 成功率图 yAxis：`min:0,max:100,name:"成功率(%)"`

> ⚠️ 断言 yAxis 时别只写 `min:0,max:100`——它在页面上出现 **2 次**（两张图），
> `count==1` 会误判。必须带上 `,name:"成功率(%)"`。

## 运行

```bash
python -m tgpatch locate PickerVehicleData
python -m tgpatch pull PickerVehicleData-BWUD9G8B.js -o fixtures/
python patch.py
python -m tgpatch esm out/PickerVehicleData-BWUD9G8B.js --balance
python -m tgpatch deploy out PickerVehicleData-BWUD9G8B.js --tag veh
cd . && node e2e.js
```

## 已知未处理项（如实说明）

- 折线图 `visualMap.pieces` 的阈值仍是 80%，所以 78~79.9 的点会渲染成红色
  （属于图表配置，与本次需求无关）
