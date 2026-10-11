#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 SSH runner：从 stdin 读命令，在目标机执行，按分节格式输出。

这是 ``tgpatch.ssh`` 的降级路径——当运行环境没有安装 paramiko 时，SSHRunner 会
用子进程调用本脚本。输出格式固定为三段，便于调用方稳定解析：

    ===== STDOUT =====
    <stdout>
    ===== STDERR =====      # 仅当 stderr 非空
    <stderr>
    ===== EXIT: <rc> =====

配置全部来自环境变量（**没有任何内置口令**）：

    SSH_HOST       目标机地址（必填）
    SSH_PORT       默认 22
    SSH_USER       默认 deploy
    SSH_PASSWORD   SSH 口令（必填）
    SSH_TIMEOUT    连接超时秒数，默认 15

也可以把地址作为第一个命令行参数传入。
"""
import os
import sys


def main() -> int:
    try:
        import paramiko
    except ModuleNotFoundError:
        print("需要 paramiko：pip install paramiko", file=sys.stderr)
        return 64

    host = os.environ.get("SSH_HOST") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not host:
        print("未指定 SSH_HOST", file=sys.stderr)
        return 64

    user = os.environ.get("SSH_USER", "deploy")
    password = os.environ.get("SSH_PASSWORD", "")
    port = int(os.environ.get("SSH_PORT", "22"))
    timeout = int(os.environ.get("SSH_TIMEOUT", "15"))

    cmd = sys.stdin.read()

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(host, port=port, username=user, password=password,
                    timeout=timeout, banner_timeout=20, auth_timeout=20,
                    look_for_keys=False, allow_agent=False)
    except Exception as exc:  # noqa: BLE001
        print("连接 %s@%s:%d 失败: %s" % (user, host, port, exc), file=sys.stderr)
        return 65

    _, stdout, stderr = cli.exec_command(cmd, timeout=600)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    rc = stdout.channel.recv_exit_status()

    print("===== STDOUT =====")
    print(out)
    if err.strip():
        print("===== STDERR =====")
        print(err)
    print("===== EXIT:", rc, "=====")
    cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
