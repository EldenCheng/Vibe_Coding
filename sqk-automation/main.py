"""sqk-automation 统一入口。

    py main.py list                 列出所有自动化操作
    py main.py info 2               查看某个操作的说明和可用参数
    py main.py run screenshot       按名称执行一个操作
    py main.py run 2                按编号执行一个操作
    py main.py run 1-5              执行编号落在 1..5 的操作
    py main.py run "[1, 3, 5]"      执行指定的一组操作（顺序按你写的）
    py main.py run 1 3 5            同上，空格写法
    py main.py run all              全部操作，按编号升序

操作自己的参数不在这里传，写在 config/params.json 里，每个操作读自己那一段。
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from adb_kit.config import ConfigError, load_settings
from framework import context, registry, runner, selector

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="命令")

    def with_global(sp):
        sp.add_argument("-d", "--device", help="devices.json 里的设备名，默认用 default_device")
        sp.add_argument("-c", "--config", help="改用指定的 devices.json 路径")
        return sp

    with_global(sub.add_parser("list", help="列出所有操作"))
    info = with_global(sub.add_parser("info", help="查看单个操作的详细说明与参数"))
    info.add_argument("target", help="编号或名称")
    run = with_global(sub.add_parser("run", help="执行一个或一串操作"))
    run.add_argument("targets", nargs="+", help="编号 / 名称 / 区间 1-5 / 列表 [1,3,5] / all")
    run.add_argument("--fail-fast", action="store_true", help="某步失败立即停止（默认跑完再汇总）")
    return parser


def print_list(ops) -> int:
    print(f"{'编号':<6}{'名称':<16}说明")
    print("─" * 56)
    for op in ops:
        print(f"{op.number:<7}{op.name:<17}{op.title}")
    print(
        f"\n共 {len(ops)} 个操作。"
        f"执行：py main.py run <编号|名称|1-5|[1,3,5]>；详情：py main.py info <编号|名称>"
    )
    return EXIT_OK


def print_info(ops, target, params_file) -> int:
    op = registry.find(ops, target)
    print(f"({op.number}) {op.name} — {op.title}")
    print("─" * 56)
    print(op.description)

    section = params_file.get(op.name) or {}
    print(f"\n可用参数（写在 config/params.json 的 {op.name!r} 段里）：")
    if not op.default_params:
        print("  这个操作没有参数。")
    for key, default in sorted(op.default_params.items()):
        if key in section:
            print(f"  {key} = {section[key]!r}（params.json 当前值）")
        else:
            print(f"  {key} = {default!r}（默认值）")
    return EXIT_OK


def do_run(ops, args) -> int:
    try:
        plan = selector.parse(args.targets, ops)
    except (selector.SelectorError, registry.RegistryError) as exc:
        print(f"[选择器错误] {exc}")
        print_list(ops)
        return EXIT_USAGE

    try:
        settings = load_settings(Path(args.config)) if args.config else load_settings()
        device = settings.pick(args.device)
        params_file = context.load_params()
    except (ConfigError, context.ParamsError) as exc:
        print(f"[配置错误] {exc}")
        return EXIT_USAGE

    print(f"执行计划：{' → '.join(f'{o.number}:{o.name}' for o in plan)}")
    print(f"目标设备：{device.name} ({device.serial})")

    def make_context(op):
        ctx = context.Context.build(op, settings, params_file)
        ctx.attach_device(device)
        return ctx

    results = runner.run_sequence(plan, make_context, fail_fast=args.fail_fast)
    return runner.summarize(results, planned=len(plan))


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    def announce(added):
        print(f"[编号台账] 新登记编号：{'、'.join(added)}（已写入 config/number_ledger.json）")

    try:
        ops = registry.discover(on_new=announce)
    except registry.RegistryError as exc:
        print(f"[操作定义错误] {exc}")
        return EXIT_USAGE

    if args.command == "run":
        return do_run(ops, args)
    if args.command == "info":
        try:
            return print_info(ops, args.target, context.load_params())
        except (registry.RegistryError, context.ParamsError) as exc:
            print(f"[错误] {exc}")
            return EXIT_USAGE
    if args.command is None:
        print("未指定命令，先看看有哪些操作：\n")
    return print_list(ops)


if __name__ == "__main__":
    raise SystemExit(main())
