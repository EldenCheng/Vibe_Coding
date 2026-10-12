"""离线自检：不接真机，用假 adb 验证 framework/adb_kit/automations 的逻辑。

    py selftest.py

覆盖 adb 封装、截图落盘、操作注册表、编号台账、选择器语法、参数合并、
序列执行与汇总，最后跑一次端到端 run screenshot。
"""

import contextlib
import io
import json
import re
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from adb_kit import adb, screen
from adb_kit.config import Device, Settings
from framework import context, registry, runner, selector

import main as entry  # noqa: E402  放在 sys.path 修好之后

PNG = b"\x89PNG\r\n\x1a\n" + b"chunk" * 8 + b"IEND\xaeB`\x82"
DEV = Device(name="客厅盒子", host="192.168.1.100", port=5555)
OTHER = Device(name="书房盒子", host="192.168.1.101", port=5555)


def done(stdout=b"", stderr=b"", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


def fake_run(mode):
    """模拟不同设备的 adb 应答。"""

    def run(args, timeout=30):
        cmd = args[1:]
        if cmd[0] in ("start-server",):
            return done()
        if cmd[0] == "devices":
            return done(b"List of devices attached\n192.168.1.100:5555\tdevice\n")
        if cmd[0] == "connect":
            if mode == "refused":
                return done(b"", "cannot connect to 192.168.1.100:5555: 拒绝连接。".encode(), 1)
            return done(b"connected to 192.168.1.100:5555\n")
        if cmd[0] == "-s":
            tail = cmd[2:]
            if tail[0] == "shell":
                command = tail[1]
                # 读系统属性必须走 getprop；直接 shell ro.product.model 是不通的
                if command == "getprop ro.product.model":
                    return done(b"MagicBox X1\n")
                if command == "getprop ro.build.version.release":
                    return done(b"9\n")
                if command == "wm size":
                    return done(b"Physical size: 1920x1080\n")
                return done(b"")
            if tail[0] == "exec-out":
                if mode == "crlf":
                    return done(PNG.replace(b"\n", b"\r\n"))
                if mode in ("broken", "empty"):
                    return done(b"" if mode == "empty" else b"no-png-here")
                return done(PNG)
            if tail[0] == "pull":
                Path(tail[2]).write_bytes(PNG)
                return done(b"1 file pulled")
        raise AssertionError(f"未预期的 adb 调用：{cmd}")

    return run


def make_settings(screenshot_dir: Path, devices=(DEV,)) -> Settings:
    return Settings(
        adb_path="adb",
        default_device=devices[0].name,
        screenshot_dir=screenshot_dir,
        connect_timeout=5,
        devices=list(devices),
    )


def fake_op(number, name, defaults=None, body=None) -> registry.Operation:
    """构造一个操作，顺带走一遍注册表的校验逻辑。"""
    module = types.SimpleNamespace(
        __name__=f"automations.{name}",
        number=number,
        name=name,
        title=f"{name} 的说明",
        default_params=defaults or {},
        run=body or (lambda ctx: None),
    )
    return registry._operation_from(module)


CHECKS = []


def check(label, got, want):
    ok = got == want
    CHECKS.append((label, ok))
    mark = "通过" if ok else "不通过"
    print(f"  {mark}｜{label}")
    if not ok:
        print(f"        得到={got!r}\n        期望={want!r}")
    return ok


def expect_error(label, fn, keyword, error=Exception):
    """要求 fn 抛错，且错误信息里有 keyword。"""
    try:
        fn()
    except error as exc:
        check(label, keyword in str(exc), True)
    except Exception as exc:
        check(f"{label} ｜抛错类型不符", f"{type(exc).__name__}: {exc}", keyword)
    else:
        check(f"{label} ｜应当抛错", "没抛错", keyword)


# ---------------------------------------------------------------- adb 层


def test_adb_layer(settings):
    print("\n[1] adb 封装与截图落盘")
    adb.check_adb = lambda s: None

    adb._run = fake_run("ok")
    check("exec-out 截图字节数", len(adb.capture(settings, DEV)), len(PNG))
    check("连接成功文案", "connected" in adb.connect(settings, DEV), True)
    check(
        "设备信息可读（属性走 getprop）",
        adb.device_info(settings, DEV),
        {"型号": "MagicBox X1", "安卓版本": "9", "分辨率": "Physical size: 1920x1080"},
    )

    adb._run = fake_run("crlf")
    check("CRLF 还原后字节一致", adb.capture(settings, DEV), PNG)

    for mode in ("broken", "empty"):
        adb._run = fake_run(mode)
        check(f"{mode} 自动回退 pull", adb.capture(settings, DEV), PNG)

    adb._run = fake_run("refused")
    expect_error("拒绝连接时给出排查方向", lambda: adb.connect(settings, DEV),
                 "无线调试掉线", adb.AdbError)

    check("单设备命名", screen.build_filename(DEV, 1, datetime(2026, 9, 20, 16, 30, 12)),
          "2026-09-20_163012.png")
    check("多设备命名加前缀", screen.build_filename(DEV, 2, datetime(2026, 9, 20, 16, 30, 12)),
          "客厅盒子_2026-09-20_163012.png")


# ------------------------------------------------------------- registry


def test_registry(tmp: Path):
    print("\n[2] 操作注册表与编号台账")

    real = registry.discover()
    numbers = [o.number for o in real]
    check("自动发现全部操作", len(real) >= 2, True)
    check("返回顺序按编号升序", numbers, sorted(numbers))
    check("编号没有重复", len(numbers), len(set(numbers)))
    check("截图操作在册", sorted(o.name for o in real), ["connect", "screenshot"])

    expect_error("编号非正整数被拒", lambda: fake_op(0, "zero"), "正整数", registry.RegistryError)
    expect_error("名称含横线被拒", lambda: fake_op(90, "bad-name"), "不合法", registry.RegistryError)
    expect_error("参数键以下划线开头被拒",
                 lambda: fake_op(91, "badkey", {"_x": 1}), "键名非法", registry.RegistryError)

    ops = [fake_op(7, "alpha"), fake_op(8, "beta")]
    expect_error("编号重复被拒", lambda: registry._check_unique(ops + [fake_op(7, "gamma")]),
                 "同时使用", registry.RegistryError)
    expect_error("名称重复被拒", lambda: registry._check_unique(ops + [fake_op(9, "alpha")]),
                 "同时使用", registry.RegistryError)

    check("按编号查找", registry.find(ops, "8").name, "beta")
    check("按名称查找（大小写无关）", registry.find(ops, "ALPHA").number, 7)
    expect_error("找不到编号", lambda: registry.find(ops, 99), "没有编号为 99", registry.RegistryError)
    expect_error("找不到名称", lambda: registry.find(ops, "nope"), "没有名为", registry.RegistryError)

    ledger = tmp / "number_ledger.json"
    real_ledger = registry.LEDGER_PATH
    try:
        registry.LEDGER_PATH = ledger
        check("新编号自动登记", registry._sync_ledger(ops), ["7 → alpha", "8 → beta"])
        check("台账内容", json.loads(ledger.read_text(encoding="utf-8")),
              {"7": "alpha", "8": "beta"})
        check("已登记且名字一致则无新增", registry._sync_ledger(ops), [])
        expect_error("编号被改派给别的操作时报错",
                     lambda: registry._sync_ledger([fake_op(7, "renamed"), fake_op(8, "beta")]),
                     "永不复用", registry.RegistryError)
        check("操作下线后编号仍留在台账", json.loads(ledger.read_text(encoding="utf-8"))["7"], "alpha")
    finally:
        registry.LEDGER_PATH = real_ledger


# ------------------------------------------------------------- selector


def test_selector():
    print("\n[3] 选择器语法")
    ops = [fake_op(1, "one"), fake_op(2, "two"), fake_op(5, "five")]
    names = lambda *specs: [o.name for o in selector.parse(list(specs), ops)]
    both = (selector.SelectorError, registry.RegistryError)

    check("按名称", names("two"), ["two"])
    check("按编号", names("2"), ["two"])
    expect_error("编号不存在时报错", lambda: names("9"), "没有编号为 9", both)
    check("区间取已存在的", names("1-5"), ["one", "two", "five"])
    check("列表按书写顺序", names("[5, 1]"), ["five", "one"])
    check("列表可省略方括号", names("5,1"), ["five", "one"])
    check("列表可混用编号和名称", names("[one, 5]"), ["one", "five"])
    check("重复项按次数执行", names("2,2,2"), ["two", "two", "two"])
    check("空格分隔多个选择器", names("5", "1"), ["five", "one"])
    check("all 按编号升序", names("all"), ["one", "two", "five"])
    check("all 大小写无关", names("ALL"), ["one", "two", "five"])

    expect_error("区间反向报错", lambda: names("5-1"), "起点大于终点", both)
    expect_error("区间内无操作报错", lambda: names("3-4"), "没有任何操作", both)
    expect_error("列表里有未知项则整体报错", lambda: names("1,99"), "没有编号为 99", both)
    expect_error("括号不成对报错", lambda: names("[1, 2"), "方括号不成对", both)
    expect_error("all 不能出现在列表里", lambda: names("[all, 1]"), "只能整体使用", both)


# -------------------------------------------------------------- context


def test_context(tmp: Path):
    print("\n[4] 参数合并")
    op = fake_op(20, "paramtest", defaults={"flag": False, "count": 1})
    settings = make_settings(tmp)

    ctx = context.Context.build(op, settings, {})
    check("缺 params.json 时用默认值", (ctx.param("flag"), ctx.param("count")), (False, 1))

    ctx = context.Context.build(op, settings, {"paramtest": {"flag": True}})
    check("params.json 覆盖默认值", ctx.param("flag"), True)
    check("未覆盖的保持默认", ctx.param("count"), 1)

    expect_error("未声明的参数名报错", lambda: ctx.param("nope"), "没有声明参数", KeyError)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        context.Context.build(op, settings, {"paramtest": {"typo_key": 1}})
    check("拼错键名会警告", "typo_key" in buffer.getvalue(), True)

    expect_error("参数段不是对象时报错",
                 lambda: context.Context.build(op, settings, {"paramtest": 5}),
                 "必须是对象", context.ParamsError)


# --------------------------------------------------------------- runner


def test_runner(tmp: Path):
    print("\n[5] 序列执行与汇总")

    def ok_op(ctx):
        pass

    def bad_op(ctx):
        raise RuntimeError("故意失败")

    ops = [fake_op(30, "a", body=ok_op), fake_op(31, "b", body=bad_op), fake_op(32, "c", body=ok_op)]

    def factory(op):
        return context.Context.build(op, make_settings(tmp), {})

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        results = runner.run_sequence(ops, factory)
        code = runner.summarize(results, planned=len(ops))
    check("默认跑完全部操作", [r.ok for r in results], [True, False, True])
    check("有失败时退出码为 1", code, 1)
    check("失败原因被记录", "故意失败" in results[1].detail, True)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        results = runner.run_sequence(ops, factory, fail_fast=True)
        code = runner.summarize(results, planned=len(ops))
    check("fail-fast 只跑到失败那步", [r.ok for r in results], [True, False])
    check("fail-fast 退出码为 1", code, 1)
    check("fail-fast 提示未执行数", "未执行 1" in buffer.getvalue(), True)

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        good = [fake_op(33, "g", body=lambda ctx: None)]
        results = runner.run_sequence(good, factory)
        code = runner.summarize(results, planned=1)
    check("全成功退出码为 0", code, 0)


# ---------------------------------------------------------------- 端到端


def test_end_to_end(tmp: Path):
    print("\n[6] 端到端：main.py run screenshot（假 adb）")
    devices_file = tmp / "devices.json"
    devices_file.write_text(
        json.dumps(
            {
                "adb_path": "adb",
                "default_device": DEV.name,
                "screenshot_dir": str(tmp / "out"),
                "connect_timeout": 5,
                "devices": [{"name": DEV.name, "host": DEV.host, "port": DEV.port}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    adb._run = fake_run("ok")
    real_check = adb.check_adb
    adb.check_adb = lambda s: None
    try:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = entry.main(["run", "screenshot", "-c", str(devices_file)])
    finally:
        adb.check_adb = real_check

    out = tmp / "out"
    files = sorted(out.glob("*.png")) if out.exists() else []
    check("退出码 0", code, 0)
    check("生成一张截图", len(files), 1)
    check("截图内容是合法 PNG", files[0].read_bytes() if files else None, PNG)
    check("文件名形如 日期_时间.png",
          bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{6}\.png", files[0].name)) if files else False, True)


def main() -> int:
    import tempfile

    real_run = adb._run
    try:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            test_adb_layer(make_settings(tmp / "shots"))
            test_registry(tmp)
            test_selector()
            test_context(tmp)
            test_runner(tmp)
            test_end_to_end(tmp)
    finally:
        adb._run = real_run

    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"\n{passed}/{total} 项通过")
    for label, ok in CHECKS:
        if not ok:
            print(f"  未通过：{label}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
