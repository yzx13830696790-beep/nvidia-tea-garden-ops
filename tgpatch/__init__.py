# -*- coding: utf-8 -*-
"""tgpatch —— 果安云平台（tea-garden）前端构建产物的字节级改造工具箱。

设计目标
--------
线上 SPA 是 Vite 打包产物：模块被切成带内容 hash 的 chunk，import 关系由入口文件里的
``__vite__mapDeps`` 索引数组决定。源码不可得，但需求（改数值 / 加一条记录 / 换年份 /
加一个设备类型）必须落到线上。本工具箱为此提供一条可复现、可验证的流水线：

    定位活跃 chunk  ->  字节级精确替换（带命中数断言）  ->  ESM 语法校验
      ->  部署到容器（md5 校验）  ->  HTTP 校验  ->  浏览器端到端验证

核心原则：**改之前先证明只有一个地方要改，改之后先证明没有别的地方被改到。**
所有替换都要求显式声明期望命中次数，命中数不符就中止、不落盘。

模块
----
config    目标机 / 容器 / 凭据配置（全部走环境变量，代码内无明文口令）
ssh       SSH 执行器（paramiko，缺失时回退到 scripts/ssh_run.py）
remote    远端操作：宿主命令、容器内执行、字节级取回、md5 校验部署
locate    入口识别与活跃 chunk 定位
patch     字节级补丁引擎（替换表 + 前置/后置断言 + 差异聚类 + 配平检查）
validate  ESM 语法校验（Node vm.SourceTextModule）
verify    HTTP 层校验与 playwright 端到端辅助
cli       统一命令行入口
"""

__version__ = "1.0.0"

from .config import Target, load_target          # noqa: F401
from .ssh import SSHRunner                        # noqa: F401
from .remote import Remote                        # noqa: F401
from .patch import Edit, PatchEngine, diff_regions, balanced  # noqa: F401

__all__ = [
    "Target", "load_target",
    "SSHRunner", "Remote",
    "Edit", "PatchEngine", "diff_regions", "balanced",
]
