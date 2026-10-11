# -*- coding: utf-8 -*-
"""让 ``python -m tgpatch`` 可用。

README 与 :mod:`tgpatch.cli` 的用法说明里通篇是 ``python -m tgpatch <子命令>``，
但包里一直没有 ``__main__.py``，于是这条命令只会得到
``No module named tgpatch.__main__``。这个文件补上这个缺口。

等价用法还有 ``python -m tgpatch.cli <子命令>`` 与安装后的 ``tgpatch <子命令>``。
"""
from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
