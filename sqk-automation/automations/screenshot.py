"""编号 2：抓取盒子当前屏幕，存到 screen_shot/。"""

import os

from adb_kit import adb, screen

number = 2
name = "screenshot"
title = "抓取盒子屏幕"
description = """连接盒子后执行 screencap，把 PNG 保存到 config/devices.json 里
screenshot_dir 指定的目录（默认 screen_shot/），文件名形如 2026-09-20_163012.png；
配置了多台设备时会自动加设备名前缀，避免同一秒的截图互相覆盖。

想连拍就多写几项，例如 run "[2, 2, 2]"。"""

default_params = {
    "reconnect": True,   # 每次先重新 adb connect；改成 False 则复用现有连接
    "show_info": False,  # 截图前打印一次设备型号/分辨率
    "open_after": False,  # 存盘后用系统默认图片程序打开
}


def run(ctx):
    settings, device = ctx.settings, ctx.device

    if ctx.param("reconnect"):
        ctx.ensure_connected()
    else:
        adb.check_adb(settings)
        if not adb.is_connected(settings, device):
            raise adb.AdbError(
                f"{device.serial} 不在已连接列表中；把 params.json 里 "
                f"{name} 的 reconnect 改回 true，或先跑 connect。"
            )
        ctx.log(f"复用现有连接：{device.name} ({device.serial})")

    if ctx.param("show_info"):
        for key, value in adb.device_info(settings, device).items():
            ctx.log(f"{key}：{value}")

    ctx.log("抓取屏幕中…")
    data = adb.capture(settings, device)
    saved = screen.save(settings, device, data, len(settings.devices))
    ctx.log(f"已保存：{saved}（{len(data) / 1024:.0f} KB）")

    if ctx.param("open_after"):
        os.startfile(str(saved))
