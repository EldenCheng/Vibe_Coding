"""编号 1：连接盒子并检查状态。"""

from adb_kit import adb

number = 1
name = "connect"
title = "连接盒子并检查状态"
description = """建立无线 adb 连接，等设备进入可命令状态，
然后读一下型号、安卓版本、分辨率，用来确认连上的是不是预期的那台盒子。
一次都没连通过、或者怀疑掉线时先跑这个。"""

default_params = {
    "show_info": True,  # 是否打印型号/安卓版本/分辨率
}


def run(ctx):
    ctx.ensure_connected()

    if ctx.param("show_info"):
        for key, value in adb.device_info(ctx.settings, ctx.device).items():
            ctx.log(f"{key}：{value}")

    ctx.log("连接正常。")
