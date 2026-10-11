# -*- coding: utf-8 -*-
"""目标机 / 容器 / 凭据配置。

**代码里没有任何明文口令。** 取值优先级（后者覆盖前者）：

    1. 内置默认（只含非敏感项：端口、容器名、assets 路径）
    2. ``config.toml``        —— 项目根目录，已 gitignore
    3. ``.env``               —— 项目根目录，已 gitignore
    4. 进程环境变量 ``TG_*``   —— 最高优先级

必须提供的项只有 ``host`` 与 ``ssh_password``；缺失时直接报错并给出设置方法，
不会静默使用任何兜底口令。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ENV_PREFIX = "TG_"


class ConfigError(RuntimeError):
    """配置缺失或非法。"""


# --------------------------------------------------------------------------- #
# .env / config.toml 解析
# --------------------------------------------------------------------------- #
def _parse_dotenv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def _parse_toml(path: Path) -> dict:
    try:
        import tomllib  # Python >= 3.11
    except ModuleNotFoundError:  # pragma: no cover
        return {}
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return data.get("target", data)


def _collect_file_config() -> dict[str, str]:
    """读取 .env 与 config.toml，合并成扁平的 TG_* 键值。"""
    values: dict[str, str] = {}

    env_file = ROOT / ".env"
    if env_file.exists():
        values.update(_parse_dotenv(env_file.read_text(encoding="utf-8")))

    toml_file = ROOT / "config.toml"
    if not toml_file.exists():
        toml_file = ROOT / "config" / "config.toml"
    if toml_file.exists():
        for k, v in _parse_toml(toml_file).items():
            values.setdefault(k, v)

    # 统一成 TG_XXX 形式
    norm: dict[str, str] = {}
    for k, v in values.items():
        key = k.upper()
        if not key.startswith(_ENV_PREFIX):
            key = _ENV_PREFIX + key
        norm[key] = str(v)
    return norm


# --------------------------------------------------------------------------- #
# Target
# --------------------------------------------------------------------------- #
@dataclass
class Target:
    """一台被改造的目标机 + 它上面运行的容器。"""

    host: str
    ssh_user: str = "deploy"
    ssh_password: str = ""
    ssh_port: int = 22
    sudo_password: str = ""          # 留空表示不需要 sudo 口令
    # 下面三项都是**占位示例值**，不是任何真实环境的默认值。
    # 请按自己的部署实情在 .env / config.toml 里覆盖。
    container: str = "webapp"
    assets: str = "/opt/webapp/web/dist/assets"
    http_port: int = 8080

    @property
    def base_url(self) -> str:
        return "http://%s:%d" % (self.host, self.http_port)

    @property
    def effective_sudo_password(self) -> str:
        """未单独配置 sudo 口令时，沿用 SSH 口令（本机常见做法）。"""
        return self.sudo_password or self.ssh_password

    def sudo_prefix(self) -> str:
        """返回可拼在命令前的 sudo 前缀；无需口令时返回空串。"""
        pwd = self.effective_sudo_password
        if not pwd:
            return ""
        # -S 从 stdin 读口令，-p '' 抑制提示串（否则提示串会混进 stdout）
        return "echo %s | sudo -S -p '' " % _shquote(pwd)

    def redacted(self) -> dict:
        d = asdict(self)
        for k in ("ssh_password", "sudo_password"):
            d[k] = "***" if d[k] else ""
        return d

    def describe(self) -> str:
        return "%s@%s:%d  container=%s" % (self.ssh_user, self.host, self.ssh_port, self.container)


def _shquote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------- #
# 组装
# --------------------------------------------------------------------------- #
_DEFAULTS: dict[str, str] = {
    "TG_SSH_USER": "deploy",
    "TG_SSH_PORT": "22",
    "TG_CONTAINER": "webapp",
    "TG_ASSETS": "/opt/webapp/web/dist/assets",
    "TG_HTTP_PORT": "8080",
}

_MISSING_HINT = """\
未找到目标机地址。请任选一种方式配置：

  A) 复制模板并填写（推荐，文件已被 gitignore，不会误提交）
       cp .env.example .env
  B) 直接给环境变量
       export TG_HOST=192.168.x.x
       export TG_SSH_PASSWORD=你的SSH口令
  C) 在 config.toml 里写
       [target]
       host = "192.168.x.x"
       ssh_password = "..."

必须提供的只有 host 与 ssh_password（若目标机 sudo 需要口令，再补 TG_SUDO_PASSWORD；
不填则沿用 SSH 口令）。若该机本来免密 sudo，把 TG_SUDO_PASSWORD 显式设为空字符串即可。
"""


def load_target(require_password: bool = True, **overrides) -> Target:
    """装载目标机配置。

    Parameters
    ----------
    require_password
        为 True 时，缺少 SSH 口令会直接抛 ConfigError。离线场景（只跑本地补丁
        引擎、不连远端）可以传 False。
    **overrides
        显式覆盖，优先级最高；键名用小写字段名（host=..., container=...）。
    """
    raw = dict(_DEFAULTS)
    raw.update(_collect_file_config())
    for k, v in os.environ.items():
        if k.startswith(_ENV_PREFIX):
            raw[k] = v

    def get(key: str, default: str = "") -> str:
        return raw.get(_ENV_PREFIX + key, default)

    host = overrides.get("host") or get("HOST")
    if not host:
        raise ConfigError(_MISSING_HINT)

    ssh_password = overrides.get("ssh_password")
    if ssh_password is None:
        ssh_password = get("SSH_PASSWORD")
    if require_password and not ssh_password:
        raise ConfigError(
            "未找到 SSH 口令（TG_SSH_PASSWORD）。\n"
            "本工具箱不会使用任何内置兜底口令——明文的默认口令正是这类脚本最危险的地方。\n\n"
            + _MISSING_HINT
        )

    def _int(key: str, default: int) -> int:
        v = overrides.get(key)
        if v is None:
            v = get(key.upper(), str(default))
        try:
            return int(v)
        except (TypeError, ValueError):
            raise ConfigError("配置项 %s 不是合法整数: %r" % (key, v))

    return Target(
        host=host,
        ssh_user=overrides.get("ssh_user") or get("SSH_USER", "deploy"),
        ssh_password=ssh_password or "",
        ssh_port=_int("ssh_port", 22),
        sudo_password=overrides.get("sudo_password") if overrides.get("sudo_password") is not None
        else get("SUDO_PASSWORD"),
        # 以下三项的默认值是**占位示例**；真实值请写进 .env / config.toml
        container=overrides.get("container") or get("CONTAINER", "webapp"),
        assets=overrides.get("assets") or get("ASSETS", "/opt/webapp/web/dist/assets"),
        http_port=_int("http_port", 8080),
    )
