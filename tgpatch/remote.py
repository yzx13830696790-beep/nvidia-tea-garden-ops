# -*- coding: utf-8 -*-
"""远端操作：宿主命令、容器内执行、字节级取回、md5 校验部署。

分层是刻意的：宿主机 -> Docker 容器 -> 容器内文件系统。
所有需要 sudo 的操作统一走 ``target.sudo_prefix()``，避免口令散落在各脚本里。
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import tarfile
import time
from pathlib import Path

from .ssh import SSHRunner, SSHError


def md5_bytes(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def md5_file(p: Path | str) -> str:
    return md5_bytes(Path(p).read_bytes())


class Remote:
    """一台目标机上的远端操作集合。"""

    def __init__(self, target, runner: SSHRunner | None = None):
        self.target = target
        self.runner = runner or SSHRunner(target)

    # -- 基础 -------------------------------------------------------------- #
    def run(self, cmd: str, timeout: int = 600):
        """在宿主 shell 执行（不 sudo）。"""
        return self.runner.run(cmd, timeout=timeout)

    def _exec(self, cmd: str, timeout: int = 600) -> str:
        r = self.runner.run(cmd, timeout=timeout)
        return r.stdout

    def sudo(self, cmd: str, timeout: int = 600) -> str:
        """在宿主以 sudo 执行。"""
        return self._exec(self.target.sudo_prefix() + cmd, timeout=timeout)

    def container(self, cmd: str, timeout: int = 600) -> str:
        """在容器内以 root 执行一条 shell 命令。"""
        inner = "%s docker exec %s sh -c %s" % (
            self.target.sudo_prefix(), self.target.container, _sq(cmd))
        return self._exec(inner, timeout=timeout)

    def container_raw(self, cmd: str, timeout: int = 600) -> str:
        """同 :meth:`container`，但不用 sh -c 包一层（命令本身已是完整调用）。"""
        inner = "%s docker exec %s %s" % (self.target.sudo_prefix(), self.target.container, cmd)
        return self._exec(inner, timeout=timeout)

    def container_stdin(self, cmd: str, payload: str, timeout: int = 600) -> str:
        """把 payload 从 stdin 喂给容器内的命令（docker exec -i）。"""
        inner = "%s docker exec -i %s sh -c %s" % (
            self.target.sudo_prefix(), self.target.container, _sq(cmd))
        return self._exec(inner, timeout=timeout)

    def exec_python(self, code: str, timeout: int = 600) -> str:
        """把一段 Python 源码送进容器执行。

        用 base64 + 分块 append 的方式传，避免长命令触发 ARG_MAX 限制，也避免引号
        与中文在多层 shell 转义中被打碎。
        """
        b64 = base64.b64encode(code.encode("utf-8")).decode("ascii")
        chunks = [b64[i:i + 2000] for i in range(0, len(b64), 2000)]
        parts = ["rm -f /tmp/_x.b64"]
        parts += ["echo %s >> /tmp/_x.b64" % c for c in chunks]
        parts.append("base64 -d /tmp/_x.b64 > /tmp/_x.py && python3 /tmp/_x.py")
        return self.container("; ".join(parts), timeout=timeout)

    # -- 资产 -------------------------------------------------------------- #
    def list_assets(self, pattern: str = "") -> list[tuple[str, int]]:
        """列出容器 assets 目录下的文件与大小（按名字排序）。"""
        cmd = ("cd %s && for f in *; do [ -f \"$f\" ] && stat -c '%%s %%n' \"$f\"; done"
               % self.target.assets)
        out = self.container(cmd)
        rows: list[tuple[str, int]] = []
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                rows.append((parts[1], int(parts[0])))
        rows.sort()
        if pattern:
            rows = [r for r in rows if pattern in r[0]]
        return rows

    def md5_remote(self, names: list[str]) -> dict[str, str]:
        """取容器内若干文件的 md5。"""
        if not names:
            return {}
        cmd = "cd %s && md5sum %s" % (self.target.assets, " ".join(_sq(n) for n in names))
        out = self.container(cmd)
        got: dict[str, str] = {}
        for line in out.splitlines():
            parts = line.strip().split()
            if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{32}", parts[0]):
                got[parts[1]] = parts[0]
        return got

    def fetch(self, name: str, outdir: Path | str = ".", expect_md5: str | None = None) -> Path:
        """从容器按字节精确取回一个文件，并核对大小 / 可选 md5。"""
        b64 = self.container_raw("base64 -w0 %s/%s 2>/dev/null" % (self.target.assets, _sq(name)))
        data = base64.b64decode("".join(re.findall(r"[A-Za-z0-9+/=]", _strip_markers(b64))))
        size_raw = self.container_raw("stat -c '%%s' %s/%s 2>/dev/null" % (self.target.assets, _sq(name)))
        size = _first_int(size_raw)
        if size is not None and size != len(data):
            raise SSHError("取回 %s 大小不符：线上 %s / 本地 %d" % (name, size, len(data)))
        if expect_md5 and md5_bytes(data) != expect_md5:
            raise SSHError("取回 %s md5 不符：期望 %s / 实际 %s"
                           % (name, expect_md5, md5_bytes(data)))
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        p = outdir / name
        p.write_bytes(data)
        return p

    def deploy(self, srcdir: Path | str, names: list[str], tag: str = "dep",
               ts: str | None = None) -> dict[str, str]:
        """把本地文件部署进容器 assets，逐文件 md5 校验，并先备份原文件。

        流程：tar.gz 打包 -> base64 分块上传 -> 宿主解包 -> 容器内备份 -> docker cp
        -> 容器内 md5 比对。任一步失败都会抛异常，不会留下半成品。
        """
        srcdir = Path(srcdir)
        ts = ts or time.strftime("%Y%m%d%H%M%S")
        missing = [n for n in names if not (srcdir / n).exists()]
        if missing:
            raise FileNotFoundError("本地缺少待部署文件: %s" % missing)

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for n in names:
                tf.add(srcdir / n, arcname=n)
        blob = buf.getvalue()
        b64 = base64.b64encode(blob).decode("ascii")

        local_md5 = {n: md5_file(srcdir / n) for n in names}

        self.sudo("rm -f /tmp/%s.b64 /tmp/%s.tar.gz" % (tag, tag))
        for i in range(0, len(b64), 2500):
            self.run("echo %s >> /tmp/%s.b64" % (b64[i:i + 2500], tag))
        self.run("base64 -d /tmp/%s.b64 > /tmp/%s.tar.gz" % (tag, tag))
        self.run("rm -rf /tmp/%s && mkdir -p /tmp/%s && tar -xzf /tmp/%s.tar.gz -C /tmp/%s"
                 % (tag, tag, tag, tag))

        # 备份
        for n in names:
            self.container("cp %s/%s %s/%s.bak-%s" % (self.target.assets, n,
                                                      self.target.assets, n, ts))
        self.sudo("docker cp /tmp/%s/. %s:%s/" % (tag, self.target.container, self.target.assets))

        remote = self.md5_remote(names)
        bad = [n for n in names if remote.get(n) != local_md5[n]]
        self.sudo("rm -f /tmp/%s.b64 /tmp/%s.tar.gz; rm -rf /tmp/%s" % (tag, tag, tag))
        if bad:
            raise SSHError(
                "部署后 md5 不一致: %s\n请用备份后缀 .bak-%s 回滚。"
                % (bad, ts)
            )
        return {"ts": ts, "md5": local_md5}

    def backup_names(self, name: str, limit: int = 10) -> list[str]:
        """列出某文件的可用备份（倒序，最新在前）。"""
        out = self.container("ls -1 %s/%s.bak-* 2>/dev/null" % (self.target.assets, name))
        names = [os.path.basename(l.strip()) for l in out.splitlines() if l.strip()]
        return sorted(names, reverse=True)[:limit]

    def rollback(self, name: str, backup: str) -> str:
        """用指定备份还原一个文件。"""
        return self.container("cp %s/%s %s/%s && echo ROLLED-BACK"
                              % (self.target.assets, backup, self.target.assets, name))

    def identity(self) -> dict:
        """核对目标机身份——内网 IP 会变，改之前先确认连的是对的那台。"""
        out = self._exec("hostname; echo ---; uname -sr; echo ---; whoami; echo ---; hostname -I")
        parts = [p.strip() for p in out.split("---")]
        return {
            "hostname": parts[0] if len(parts) > 0 else "",
            "kernel": parts[1] if len(parts) > 1 else "",
            "user": parts[2] if len(parts) > 2 else "",
            "ips": parts[3].split() if len(parts) > 3 else [],
        }

    def containers(self) -> list[str]:
        out = self.sudo("docker ps --format '{{.Names}}\t{{.Status}}'")
        return [l.strip() for l in out.splitlines() if l.strip()]

    def close(self):
        self.runner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


# --------------------------------------------------------------------------- #
def _sq(s: str) -> str:
    """POSIX 单引号转义。"""
    return "'" + s.replace("'", "'\\''") + "'"


def _strip_markers(raw: str) -> str:
    """剥掉 ssh_run.py 回退路径留下的分节标记。"""
    i = raw.find("===== STDOUT =====")
    if i == -1:
        return raw
    i = raw.find("\n", i) + 1
    j = raw.find("===== EXIT:", i)
    if j == -1:
        j = raw.find("===== STDERR", i)
    return raw[i:j if j != -1 else len(raw)]


def _first_int(s: str) -> int | None:
    m = re.search(r"\d+", _strip_markers(s))
    return int(m.group(0)) if m else None
