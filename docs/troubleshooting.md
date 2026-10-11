# 踩坑集

按"现象 → 原因 → 对策"记。每一条都是真实踩过的。

---

## 连通与身份

### 内网 IP 变了，连不上

**现象**：`paramiko` 报 `ConnectionRefusedError` 或连接超时；也可能 IP 能 ping 通但 22/80
端口全部拒绝（那是另一台机器占用了同一个 IP）。
**原因**：内网 IP 由 DHCP 分配，换网段后会变。
**对策**：

```bash
python -m tgpatch probe          # 核对 hostname / IP / 容器，确认连的是对的那台
```

`probe` 会打印 `hostname -I` 的结果。如果 IP 能 ping 通但端口全拒，说明连到了别的设备——
换 IP，不要怀疑口令。

### `github.com:443` 不通但 `api.github.com` 通

**现象**：`gh auth login` 走到最后一步报
`Post "https://github.com/login/oauth/access_token": ... connection attempt failed`；
`git push` 报 `Failed to connect to github.com:443`。但 `curl https://api.github.com` 正常。
**原因**：`api.github.com` 与 `github.com` 走不同解析/线路，前者可达不代表后者可达。
**对策**：走代理。若本机有 Clash 类代理（常见端口 7890 / 7897）：

```bash
export HTTPS_PROXY=http://127.0.0.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
gh auth login --web --git-protocol https --skip-ssh-key
git -c http.proxy=http://127.0.0.1:7897 push -u origin main
```

备选：`ssh.github.com:443` 是 GitHub 的 SSH-over-443 入口，直连通常可达，可写入
`~/.ssh/config`：

```
Host github.com
  HostName ssh.github.com
  Port 443
  User git
```

### 部署成功了但页面没变化

**原因**：改到了僵尸副本。
**对策**：`python -m tgpatch locate <模块名>` 看 `reachable` 一列。`reachable=False` 的那些
改多少遍都不会生效。

### 入口分析怎么都不对

**原因**：取到的是 `/cesium/Cesium.js` 而不是 SPA 入口。
**现象**：解析 `__vite__mapDeps` 得到 0 个依赖；`path:"..."` 一个都搜不到。
**对策**：`index.html` 里**第一个** `<script src>` 常常是 Cesium。必须按 `index-` 前缀筛。
`tgpatch.locate.find_entry()` 已内置这个规则。

---

## 补丁本身

### 命中数 0：片段明明复制过来了

**原因**：编码形态不同。中文在 chunk 里可能是 UTF-8 直接嵌入，也可能是 `\uXXXX` 转义；
引号可能是 ASCII `"` 也可能是全角。
**对策**：先把目标片段在文件里 `grep -o` 一次，确认实际形态。例如：

```bash
grep -o '.\{0,40\}果园自动采摘任务.\{0,20\}' chunk.js
```

### 命中数比预期多

**原因**：片段在别处也出现，且语义不同。
**实例**：`{id:"device-002",...,battery:65` 在文件里出现 2 次——一次是设备池里的无人机-02，
一次是协同任务数据里的同名引用（字段是 `speed:3.2` 而非 `avatar:""`）。
**对策**：把片段延长到唯一定位，例如补上 `,avatar:""` 或完整的 `capabilities:[...]}`。

另一个实例：`min:0,max:100` 在页面上出现 2 次（两张图），断言写 `count==1` 会误判。
加上 `,name:"成功率(%)"` 才唯一。

### 括号不配平

**现象**：`PatchError: 括号不配平，几乎可以肯定是片段切错了: ['() 2/4']`
**原因**：替换片段切在了括号中间。例如把 `Math.max(85,Math.min(100,` 换成 `R(`，
括号数从 4/4 变成 2/4。
**对策**：让替换片段的括号自成一片，或把整个表达式一起替换。确实需要改变括号总数时
（罕见）可显式关闭：`eng.check_balance(False)`。

### 可逆性检查失败

**现象**：`可逆性检查失败：新内容与旧内容的差异不只来自声明的替换`
**原因**：新片段与文件里既有内容撞车，逆替换会把那些内容也改回去。
**对策**：给新片段加上不会撞车的特征（比如 `__tgStreamSeq` 这类带前缀的标识符），
或把 `count` 调准并确认影响范围。

### 断言都过了，但两个地方长得一模一样

**实例**：编辑表单与创建向导的默认值对象**文本完全相同**，没法单独定位其中一处。
**对策**：对这类片段只能做**整体计数断言**（`count == 2`）。需求如果只涉及其中一处，就
不要改它们——本仓库的案例 05 就是这个处理方式：只改列表 4 行的初始状态，不动新建弹窗的
默认值。

---

## 部署

### 长命令被截断 / 中文被转义打碎

**原因**：多层 shell（本地 → SSH → `sudo` → `docker exec sh -c`）叠加后引号转义极易出错；
命令太长还会撞 `ARG_MAX`。
**对策**：不要拼长命令行。用 base64 + 分块传：

```python
remote.exec_python(code)        # 源码 base64 后分块 append，再 decode 执行
```

部署文件同理：`tar.gz` → base64 分块 → 远端 decode。

### `%%{http_code}` 输出成了字面量

**原因**：`curl -w '%{http_code}'` 经过 Python `%` 格式化时被吃掉了。
**对策**：命令里不经过 `%` 格式化时用单个 `%`；经过时写 `%%`。

### sudo 提示串混进了 stdout

**原因**：`sudo -S` 会把 `[sudo] password for xxx:` 提示写到 stderr，但某些环境下会混入输出。
**对策**：加 `-p ''` 抑制提示串。`tgpatch.remote` 已统一处理。

---

## 前端渲染

### 页面白屏，HTTP 却是 200

**原因**：补丁把 JS 语法改坏了。
**对策**：部署前必跑 ESM 语法校验：

```bash
python -m tgpatch esm out/chunk.js
# 或直接调用：node --experimental-vm-modules scripts/esm_check.cjs out/chunk.js
```

### 静态全绿、HTTP 全绿，页面却空白

**原因**：Vue 数据结构与模板不匹配会**静默不渲染**，不报错。
**对策**：必须跑浏览器端到端。`cases/*/e2e.js` 会读真实 DOM 断言。

### `aria-checked` 读不到 el-switch 的状态

**原因**：Element Plus 的 `.el-switch` 只是一个包装 div，真正的 `input` 在内部
`.el-switch__input` 上。
**对策**：`el.querySelector('.el-switch__input').getAttribute('aria-checked')`。

### 开关文案判断错

**原因**：el-switch 的 `active-text` 与 `inactive-text` 两个 span **始终都在 DOM 里**，
靠"哪个可见"判断需要用内层的 `aria-hidden="false"`。
**对策**：读 `aria-hidden`，不要用 `isVisible()`。

### el-rate 数星星数多了

**原因**：`el-rate` 里有 decimal 占位元素，按 `.el-rate__item` 数会多算。
**对策**：读 `aria-valuenow`，那是权威值。

### 按钮按文本定位，结果匹配到一批

**原因**：`.el-button-group` 这个 class 行内按钮也在用。
**对策**：按文本前缀过滤，而不是只按容器 class。

### 表格列索引写死，取到了错误的列

**原因**：不同表格首列不同（例如应急任务表首列是"紧急标识"而不是"任务名称"）。
**对策**：用 `columns.indexOf('创建时间')` 动态定位，别写死下标。

---

## 测试

### 端到端测试偶发失败

**原因**：断言阈值是拍脑袋定的。
**对策**：先用蒙特卡洛算失败概率，确认接近 0 再写死阈值：

```python
from tgpatch.verify import failure_probability
failure_probability(step_scale=5.0, lo=78, hi=95, margin=0, steps=20)
```

### 本地副本是旧版，把改动回退了

**现象**：补丁成功、断言全过、部署成功，但界面回到了老样子。
**原因**：拿旧副本当基线，把旧内容又推上去了。真实事故：把已改好的"果园"退回成了"农田"。
**对策**：每次动手前重新 `pull` 并与线上 md5 比对；案例脚本里加"新鲜度"前置断言。

---

## 环境

### `ModuleNotFoundError: paramiko`

**对策**：`pip install -r requirements.txt`。或者不管——`tgpatch.ssh` 会自动回退到
`scripts/ssh_run.py`（但那个脚本本身也需要 paramiko；两者都没有时会明确报错）。

### 找不到 Chrome

**现象**：`ChromeNotFound: 找不到 Chrome/Edge。`
**对策**：安装 Chrome/Edge，或用 `TG_CHROME` 指定路径：

```bash
export TG_CHROME="C:/Program Files/Google/Chrome/Application/chrome.exe"
```
