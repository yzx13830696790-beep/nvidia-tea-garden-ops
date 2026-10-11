# -*- coding: utf-8 -*-
"""ESM 语法校验 + 沙箱求值。

浏览器加载一个语法损坏的 chunk 会整页白屏，而 HTTP 层完全正常（200、大小对、
Content-Type 对）。所以字节级替换之后**必须先过语法关**再谈部署。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ESM_CHECK = ROOT / "scripts" / "esm_check.cjs"


class ValidateError(RuntimeError):
    pass


def find_node() -> str:
    node = shutil.which("node")
    if not node:
        raise ValidateError("找不到 node。ESM 校验与端到端验证都需要 Node.js 18+。")
    return node


def check_esm(files, node: str | None = None, timeout: int = 180) -> tuple[bool, str]:
    """校验若干文件能否被解析为 ES Module。

    返回 ``(是否全部通过, 原始输出)``。
    """
    files = [Path(f) for f in files]
    for f in files:
        if not f.exists():
            raise FileNotFoundError(f)
    proc = subprocess.run(
        [node or find_node(), "--experimental-vm-modules", str(ESM_CHECK), *[str(f) for f in files]],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def eval_expr(expr: str, expect: str | None = None, node: str | None = None) -> tuple[bool, str]:
    """在沙箱里对一段表达式真求值，用来验证文本比对看不出的东西。

    典型用途：确认 ``__vite__mapDeps`` 的长度、确认某个常量数组的元素个数。
    """
    argv = [node or find_node(), "--experimental-vm-modules", str(ESM_CHECK), "--eval", expr]
    if expect is not None:
        argv.append(expect)
    proc = subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def map_deps_length(entry_src: str) -> int | None:
    """求值入口文件里的 ``__vite__mapDeps`` 数组长度（等价于模块 chunk 总数）。"""
    import re
    m = re.search(r'm\.f\s*=\s*(\[[^\]]*\])', entry_src)
    if not m:
        m = re.search(r'(\[\s*"assets/[^\]]+\])', entry_src)
    if not m:
        return None
    ok, out = eval_expr("JSON.parse(%s)" % json.dumps(m.group(1)) + ".length")
    if not ok:
        # 数组里可能有非 JSON 字面量，退回按字符串数量粗算
        return m.group(1).count('"assets/')
    return int(out.split("->")[-1].strip().split()[0])
