# -*- coding: utf-8 -*-
"""
StarTrace · 程序入口
作者 Guozhengkun · v1.0.0

  StarTrace.exe          # 启动图形界面
  StarTrace.exe --send   # 静默模式：抓取并发送邮件（供每日定时任务调用）
"""

import datetime
import sys
from pathlib import Path

import mailer_core as core


def _set_runtime_base():
    """打包为 exe 时，将配置 / 日志放在 exe 所在目录；脚本运行时放在源码目录。"""
    if getattr(sys, "frozen", False):
        core.set_base_dir(Path(sys.executable).resolve().parent)
    else:
        core.set_base_dir(Path(__file__).resolve().parent)


def run_headless():
    """定时任务调用：抓取今日榜单并发送邮件，结果写入日志。"""
    try:
        cfg = core.read_config()
        core.validate_config(cfg)
        core.logging.info("== 定时任务触发：开始抓取并发送 ==")
        date_str, n, to = core.send_today_mail(cfg)
        core.logging.info("== 完成：%s 共 %d 个项目，已发送至 %s ==", date_str, n, to)
        print(f"[OK] {date_str} 共 {n} 个项目，邮件已发送到：{to}")
        return 0
    except Exception as e:
        core.logging.error("== 发送失败：%s ==", e)
        print(f"[错误] {e}")
        return 1


def main():
    _set_runtime_base()
    if "--send" in sys.argv:
        sys.exit(run_headless())
    from gui import run
    run()


if __name__ == "__main__":
    main()
