# -*- coding: utf-8 -*-
"""统一命令行入口。

    python -m tgpatch probe                        核对目标机身份
    python -m tgpatch routes [--path /task-scheduling]   看路由 -> chunk 映射
    python -m tgpatch locate PickerVehicleData     找出活跃 chunk（含僵尸副本告警）
    python -m tgpatch chunkmap dist/assets         构建产物 -> 源文件映射（需 .js.map）
    python -m tgpatch chunkmap dist/assets --lookup "Math.max(85,Math.min(100,"
    python -m tgpatch pull PickerVehicleData-x.js -o work/   字节级取回
    python -m tgpatch esm work/*.js                本地 ESM 语法校验
    python -m tgpatch deploy work out.js --tag veh 部署 + md5 校验
    python -m tgpatch verify out.js --md5 <md5> --must a --mustnot b
    python -m tgpatch backups out.js               列出可回滚的备份
    python -m tgpatch rollback out.js out.js.bak-20261011120000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import sourcemap as smap
from .config import ConfigError, load_target
from .locate import find_entry, parse_map_deps, parse_routes, scan_remote
from .patch import balanced
from .remote import Remote, md5_file
from .validate import check_esm
from .verify import AssetCheck, check_entry_chain, check_routes, http_get


def _remote(args):
    target = load_target(host=getattr(args, "host", None) or None)
    if args.show_target:
        print("目标机: %s" % target.describe())
    return Remote(target)


# --------------------------------------------------------------------------- #
def cmd_probe(args) -> int:
    with _remote(args) as r:
        info = r.identity()
        print("=== 身份核对 ===")
        print("  hostname : %s" % info["hostname"])
        print("  kernel   : %s" % info["kernel"])
        print("  user     : %s" % info["user"])
        print("  IP       : %s" % ", ".join(info["ips"]))
        print("  SSH 可达 ✓")
        print()
        print("=== 容器 ===")
        for line in r.containers():
            print("  %s" % line)
        print()
        print("=== 目标容器 : %s ===" % r.target.container)
        out = r.container("ls -1 %s | wc -l" % r.target.assets)
        print("  assets 文件数: %s" % "".join(c for c in out if c.isdigit()) or "?")
        print()
        html = r.container("cat /opt/webapp/web/dist/index.html 2>/dev/null")
        entry = find_entry(html)
        print("  index.html 入口: %s" % entry)
        if entry:
            src = r.container("cat %s/%s" % (r.target.assets, entry))
            deps = parse_map_deps(src)
            print("  __vite__mapDeps 长度: %d" % len(deps))
            print("  路由数: %d" % len(parse_routes(src)))
        base = r.target.base_url
        rr = http_get(base + "/index.html")
        print("  前端 %s -> HTTP %d" % (base, rr.status))
    return 0


def cmd_ls(args) -> int:
    with _remote(args) as r:
        rows = r.list_assets(args.pattern or "")
        for name, size in rows:
            print("  %-60s %10d" % (name, size))
        print("  共 %d 个文件" % len(rows))
    return 0


def cmd_routes(args) -> int:
    with _remote(args) as r:
        if not args.path:
            html = r.container("cat /opt/webapp/web/dist/index.html 2>/dev/null")
            entry = find_entry(html)
            print("入口: %s" % entry)
        else:
            entry = args.entry
        src = r.container("cat %s/%s" % (r.target.assets, entry))
        names = parse_map_deps(src)
        print("__vite__mapDeps 长度: %d" % len(names))
        print()
        for path, chunks in parse_routes(src):
            if args.path and args.path not in path:
                continue
            print("%-34s -> %s" % (path, chunks[:6]))
    return 0


def cmd_locate(args) -> int:
    with _remote(args) as r:
        data = scan_remote(r, args.module, entry=args.entry)
        print("入口: %s (存在=%s)" % (data["entry"], data["entry_exists"]))
        print("assets 内 .js 文件数: %d" % data["js_total"])
        print()
        print("=== %s 的所有副本 ===" % args.module)
        for v in data["versions"]:
            print("  %-56s %8d bytes  reachable=%-5s depth=%-4s refs=%d"
                  % (v["name"], v["bytes"], v["reachable"], v["depth"], v["referenced_by"]))
        print()
        print("活跃 chunk : %s" % data["active"])
        if data["zombies"]:
            print("僵尸副本   : %s" % ", ".join(data["zombies"]))
            print("            （改这些没用，浏览器不会加载它们）")
        if data.get("warning"):
            print("⚠ %s" % data["warning"])
    return 0


def cmd_chunkmap(args) -> int:
    assets = Path(args.assets_dir)
    if not assets.is_dir():
        print("目录不存在: %s" % assets, file=sys.stderr)
        return 2

    # -- 模式一：拿一段产物代码，反查它来自源码哪一行 --
    if args.lookup:
        hits = 0
        for mp in smap.iter_maps(assets):
            if args.chunk and args.chunk not in mp.name:
                continue
            try:
                sm = smap.SourceMap.load(mp)
            except smap.SourceMapError:
                continue
            pos = sm.lookup_text(args.lookup)
            if pos:
                hits += 1
                print("%-44s -> %s" % (sm.file or mp.name[:-4], pos))
        if not hits:
            print("没有 chunk 含这段文本: %r" % args.lookup)
            return 1
        return 0

    # -- 模式二：反查某个源文件被编译进了哪些 chunk --
    if args.source:
        rev = smap.reverse_index(assets)
        rows = [(s, c) for s, c in sorted(rev.items())
                if args.source.lower() in s.lower()]
        if not rows:
            print("没有源文件匹配: %r" % args.source)
            return 1
        for src, chunks in rows:
            print("%-64s %s" % (src, ", ".join(chunks)))
        print("\n共 %d 个源文件" % len(rows))
        return 0

    # -- 模式三：默认列出 chunk -> 源文件 --
    table = smap.scan_dir(assets)
    if args.chunk:
        table = {k: v for k, v in table.items() if args.chunk in k}
    js_total = len(list(assets.glob("*.js")))
    print("assets 目录 : %s" % assets)
    print("带 map 的 chunk: %d 个（目录内 .js 共 %d 个）" % (len(table), js_total))
    if len(table) < js_total:
        print("              （没列出的 chunk 说明构建时未产出 sourcemap）")
    print()
    for chunk, srcs in table.items():
        print(chunk)
        for s in srcs:
            print("    %s" % s)
    print("\n共 %d 个 chunk" % len(table))

    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps(
            {"chunks": table, "reverse": smap.reverse_index(assets)},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("映射表已写出: %s" % out)
    return 0


def cmd_pull(args) -> int:
    with _remote(args) as r:
        for name in args.names:
            p = r.fetch(name, args.out)
            print("%-56s %8d bytes  md5=%s" % (name, p.stat().st_size, md5_file(p)))
    return 0


def cmd_esm(args) -> int:
    ok, out = check_esm(args.files)
    print(out.rstrip())
    if args.balance:
        for f in args.files:
            b = balanced(Path(f).read_bytes())
            bad = [k for k, v in b.items() if not v]
            print("  %-56s 配平 %s" % (Path(f).name, "OK" if not bad else "**%s**" % bad))
            ok &= not bad
    return 0 if ok else 1


def cmd_deploy(args) -> int:
    names = [n for n in args.files.split(",") if n.strip()]
    with _remote(args) as r:
        info = r.deploy(args.srcdir, names, tag=args.tag)
        print("部署成功 ✓  备份后缀 .bak-%s" % info["ts"])
        for n in names:
            print("  %-56s md5=%s" % (n, info["md5"][n]))
        if args.verify_base:
            print()
            return 0 if check_entry_chain(r.target.base_url, names[0]) else 1
    return 0


def cmd_verify(args) -> int:
    target = load_target(require_password=False, host=args.host or None)
    base = args.base or target.base_url
    chk = AssetCheck(name=args.name, expect_md5=args.md5,
                     must=args.must or [], mustnot=args.mustnot or [],
                     title=args.name)
    ok = chk.run(base)
    if args.entry_chain:
        ok &= check_entry_chain(base, args.name)
    if args.routes:
        ok &= check_routes(base, args.routes)
    print()
    print("=== 结果: %s ===" % ("全部通过 ✓" if ok else "存在问题 ✗"))
    return 0 if ok else 1


def cmd_backups(args) -> int:
    with _remote(args) as r:
        for b in r.backup_names(args.name):
            print("  %s" % b)
    return 0


def cmd_rollback(args) -> int:
    with _remote(args) as r:
        out = r.rollback(args.name, args.backup)
        print("回滚 %s <- %s : %s" % (args.name, args.backup, out.strip()))
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tgpatch", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", help="目标机 IP（默认取 TG_HOST）")
    p.add_argument("-q", "--quiet", action="store_true")
    p.set_defaults(show_target=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(func=fn)
        return s

    s = add("probe", cmd_probe, "核对目标机身份 / 容器 / 入口")

    s = add("ls", cmd_ls, "列出容器 assets 目录")
    s.add_argument("pattern", nargs="?", help="文件名包含的子串")

    s = add("routes", cmd_routes, "打印路由 -> chunk 映射")
    s.add_argument("--path", help="只看包含该子串的路由")
    s.add_argument("--entry", default="", help="指定入口文件名")

    s = add("locate", cmd_locate, "定位模块的活跃 chunk（并列出僵尸副本）")
    s.add_argument("module")
    s.add_argument("--entry", default=None, help="入口文件名（默认自动探测）")

    s = add("chunkmap", cmd_chunkmap,
            "用 .js.map 建立 产物 chunk <-> 源文件 的映射（本地目录，不连远端）")
    s.add_argument("assets_dir", help="含 .js 与 .js.map 的构建产出目录，如 dist/assets")
    s.add_argument("--chunk", help="只看文件名含该子串的 chunk")
    s.add_argument("--source", help="反向模式：查源文件（子串）被编译进哪些 chunk")
    s.add_argument("--lookup", help="反查模式：给出产物里的一段文本，返回它来自源码哪一行")
    s.add_argument("--json", help="把完整映射表写成 JSON")

    s = add("pull", cmd_pull, "从容器字节级取回文件")
    s.add_argument("names", nargs="+")
    s.add_argument("-o", "--out", default=".", help="输出目录")

    s = add("esm", cmd_esm, "ESM 语法校验（可附加括号配平检查）")
    s.add_argument("files", nargs="+")
    s.add_argument("--balance", action="store_true", help="同时做括号配平检查")

    s = add("deploy", cmd_deploy, "部署并做 md5 校验（自动备份原文件）")
    s.add_argument("srcdir")
    s.add_argument("files", help="逗号分隔的文件名")
    s.add_argument("--tag", default="dep", help="远端临时文件前缀")
    s.add_argument("--verify-base", action="store_true", help="部署后顺带查入口链路")

    s = add("verify", cmd_verify, "HTTP 层校验")
    s.add_argument("name")
    s.add_argument("--base", help="前端地址（默认 http://<host>:<port>）")
    s.add_argument("--md5", help="期望 md5")
    s.add_argument("--must", action="append", help="应出现的文本（可重复）")
    s.add_argument("--mustnot", action="append", help="应消失的文本（可重复）")
    s.add_argument("--entry-chain", action="store_true", help="同时校验入口引用链")
    s.add_argument("--routes", action="append", help="同时校验这些路由返回 200")

    s = add("backups", cmd_backups, "列出某文件的备份")
    s.add_argument("name")

    s = add("rollback", cmd_rollback, "用备份还原某文件")
    s.add_argument("name")
    s.add_argument("backup")

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print("配置错误:\n%s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
