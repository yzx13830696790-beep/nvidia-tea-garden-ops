# -*- coding: utf-8 -*-
"""SSH 执行器。

优先用 paramiko（进程内、无子进程开销）；若运行环境没装 paramiko，则回退到
``scripts/ssh_run.py``——后者只依赖 ``paramiko`` 一个包但以独立进程运行，两条路径
返回结构完全一致，调用方无需区分。

回退路径的存在是有原因的：早期在沙箱里跑批处理时，主解释器没有 paramiko，而另一个
解释器有，于是就用「子进程 + 指定解释器」的方式绕过。这里把它保留成显式降级分支。
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER_FALLBACK = ROOT / "scripts" / "ssh_run.py"


@dataclass
class Result:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def text(self) -> str:
        return self.stdout

    def tail(self, n: int = 5) -> str:
        lines = [l for l in self.stdout.splitlines() if l.strip()]
        return "\n".join(lines[-n:])


class SSHError(RuntimeError):
    pass


class SSHRunner:
    """对一台目标机的命令执行封装。"""

    def __init__(self, target, auto_add_host_key: bool = True):
        self.target = target
        self._cli = None
        self._mode = None
        self._auto_add = auto_add_host_key

    # -- 连接 -------------------------------------------------------------- #
    def _ensure_paramiko_client(self):
        if self._cli is not None:
            return self._cli
        try:
            import paramiko
        except ModuleNotFoundError:
            return None

        cli = paramiko.SSHClient()
        if self._auto_add:
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            cli.connect(
                self.target.host,
                port=self.target.ssh_port,
                username=self.target.ssh_user,
                password=self.target.ssh_password,
                timeout=15,
                banner_timeout=20,
                auth_timeout=20,
                look_for_keys=False,
                allow_agent=False,
            )
        except Exception as exc:  # noqa: BLE001 - 统一转成自己的异常类型
            raise SSHError(
                "连接 %s 失败: %s\n（确认 IP 可达、22 端口开放、口令正确；"
                "内网 IP 会随网络变化，用 `tgpatch probe` 核对身份）"
                % (self.target.describe(), exc)
            ) from exc
        self._cli = cli
        self._mode = "paramiko"
        return cli

    # -- 执行 -------------------------------------------------------------- #
    def run(self, cmd: str, timeout: int = 600) -> Result:
        cli = self._ensure_paramiko_client()
        if cli is not None:
            return self._run_paramiko(cli, cmd, timeout)
        return self._run_fallback(cmd, timeout)

    def _run_paramiko(self, cli, cmd: str, timeout: int) -> Result:
        stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return Result(rc, out, err)

    def _run_fallback(self, cmd: str, timeout: int) -> Result:
        if not RUNNER_FALLBACK.exists():
            raise SSHError(
                "既没有 paramiko，也找不到 %s。请先 `pip install paramiko`。" % RUNNER_FALLBACK
            )
        env = {
            **os.environ,
            "SSH_HOST": self.target.host,
            "SSH_PORT": str(self.target.ssh_port),
            "SSH_USER": self.target.ssh_user,
            "SSH_PASSWORD": self.target.ssh_password,
        }
        proc = subprocess.run(
            [sys.executable, str(RUNNER_FALLBACK)],
            input=cmd,
            capture_output=True,
            text=True,
            env=env,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return _parse_runner_output(proc.stdout)

    # -- 生命周期 ---------------------------------------------------------- #
    def close(self) -> None:
        if self._cli is not None:
            try:
                self._cli.close()
            finally:
                self._cli = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _parse_runner_output(raw: str) -> Result:
    """解析 scripts/ssh_run.py 的分节输出，还原出 rc / stdout / stderr。"""
    out, err, rc = "", "", 0
    marker_out = "===== STDOUT ====="
    marker_err = "===== STDERR ====="
    i = raw.find(marker_out)
    if i == -1:
        return Result(0, raw, "")
    body_start = raw.find("\n", i) + 1
    j = raw.find(marker_err, body_start)
    k = raw.find("===== EXIT:", body_start)
    end = min(x for x in (j, k, len(raw)) if x != -1)
    out = raw[body_start:end]
    if j != -1 and (k == -1 or j < k):
        err_start = raw.find("\n", j) + 1
        err = raw[err_start:k if k != -1 else len(raw)]
    if k != -1:
        tail = raw[k + len("===== EXIT:"):]
        digits = "".join(ch for ch in tail.split("=====")[0] if ch.isdigit())
        rc = int(digits) if digits else 0
    return Result(rc, out, err)
