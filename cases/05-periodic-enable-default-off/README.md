# 案例 05 · 周期性巡航任务编排：「启用」开关初始状态全部关闭

> **两种改法**：[`patch.py`](patch.py) 是**字节级**方案（只有构建产物时用）；
> [`source-level.md`](source-level.md) 是**源码级**方案，并说明字节级在这里
> 为什么无法单独定位"新建任务弹窗的默认值"。

| 项 | 值 |
|---|---|
| 页面 | `/task-scheduling/periodic-tasks` |
| 模块 | `PeriodicTaskArrangement` |
| 改动点 | **3 处** |
| 输入 md5 | `662660a2e603c34a7c6f5c62e9895815`（案例 03 产物） |
| 产物 md5 | `682cc5bf76780ae97e544d74878a034f` |
| 上游 | 案例 02 → 案例 03 |

## 需求

表格里 4 条任务的「启用」开关，初始状态全部为关闭（未启用）。

## 难点：怎么在不引入新变量的前提下精确命中「任务行」的 enabled

文件里 `enabled:!0` 一共 **5 处**：

| 位置 | 上下文 | 处理 |
|---|---|---|
| task-1 北区果园定时巡逻 | `priority:"medium",status:"pending",enabled:!0,createdAt:` | 改成 `!1` |
| task-2 周末喷洒任务 | `priority:"high",status:"running",enabled:!0,createdAt:` | 改成 `!1` |
| task-4 果园自动采摘任务 | `priority:"low",status:"pending",enabled:!0,createdAt:` | 改成 `!1` |
| 编辑表单默认值 | `priority:"medium",status:"pending",enabled:!0})` | **不动** |
| 创建向导默认值 | `priority:"medium",status:"pending",enabled:!0})` | **不动** |

（task-3 月度病虫害检查本来就是 `enabled:!1`）

裸 `enabled:!0` 无法区分任务行和表单默认值。解法是用**每行独有的 priority + status 组合**
做前缀锚点，再用后缀 `,createdAt:` 把「任务行」和「表单默认值」分开——后者以 `})` 结尾。

## ⚠️ 两处表单默认值文本完全相同

编辑表单与创建向导的默认值对象**一字不差**，因此**只能做整体计数断言**（`count == 2`），
没法单独定位其中一处。

这也正是本案例选择「只改列表 4 行的初始状态、不动新建弹窗默认值」的直接原因——
需求说的就是列表。e2e 里会把"弹窗默认值仍是启用"如实断言出来，作为已知状态记录。

## 无附带改动的强证据

- `!0` 与 `!1` **等长**，所以字符数 / 字节数必须**完全不变**
- 「反向还原 == 原文件」——把 3 处替换逆过来必须逐字节等于原文
- 18 个字段的计数必须与原文完全一致（`status:*`、`priority:*`、`type:*`、
  `deviceIds:`、`nextExecutionTime:`、`createdAt:`、`updatedAt:`、`startTime:` 等）

## 运行

```bash
python -m tgpatch pull PeriodicTaskArrangement-_PTsgACL.js -o fixtures/
# 注意：需要接在案例 02 → 03 的链条之后
python patch.py --dir ../03-scheduling-year-2023-2026/out
python -m tgpatch esm out/PeriodicTaskArrangement-_PTsgACL.js --balance
python -m tgpatch deploy out PeriodicTaskArrangement-_PTsgACL.js --tag en
cd . && node e2e.js
```

## e2e 读取 el-switch 状态的两个坑

1. **`aria-checked` 不在 `.el-switch` 上**，而在内部的 `.el-switch__input` 上。
2. **`active-text` / `inactive-text` 两个 span 始终都在 DOM 里**，靠"哪个可见"判断
   需要用内层的 `aria-hidden="false"`。所以一律读 `aria-checked`。

脚本还会验证开关**仍可点击**（只是初始状态变了，不是被禁用），翻转后立刻翻回来，
避免把线上的初始展示状态改脏。
