#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StarTrace · 命令行版（GUI 版见同目录的 StarTrace.exe / gui.py）

用法：
  python send_trending.py                      # 抓取并发送邮件（供定时任务调用）
  python send_trending.py --dry-run            # 只预览今日榜单，不发邮件
  python send_trending.py --install-task       # 注册每日定时任务（时间取 config 的 send_time）
  python send_trending.py --install-task --time 08:30
  python send_trending.py --uninstall-task     # 删除定时任务
"""

import argparse
import datetime
import sys

import mailer_core as core


def main():
    parser = argparse.ArgumentParser(description=f"{core.APP_NAME} {core.APP_VERSION}（{core.APP_AUTHOR}）")
    parser.add_argument("--dry-run", action="store_true", help="只预览榜单，不发邮件")
    parser.add_argument("--install-task", action="store_true", help="注册每日定时任务")
    parser.add_argument("--time", default=None, help="定时任务时间 HH:MM（默认取 config.json 的 send_time）")
    parser.add_argument("--uninstall-task", action="store_true", help="删除定时任务")
    args = parser.parse_args()

    try:
        if args.uninstall_task:
            core.unregister_task()
            print("[OK] 已删除定时任务", core.TASK_NAME)
            return
        cfg = core.read_config()
        if args.install_task:
            core.register_task(args.time or cfg.get("send_time", "09:00"))
            print(f"[OK] 已注册每日任务 {core.TASK_NAME}，每天 {args.time or cfg.get('send_time', '09:00')} 自动运行")
            return
        core.validate_config(cfg)

        lang = str(cfg.get("language", "all")).strip().lower()
        lang_label = lang if lang != "all" else "全部语言"
        top_n = int(cfg.get("top_n", 25))

        print("[1/3] 正在抓取 GitHub Trending ...")
        repos = core.fetch_trending(lang, top_n)
        date_str = datetime.date.today().strftime("%Y-%m-%d")
        print(f"数据来源：{core.source_label(repos)}")
        print(f"[2/3] 获取到 {len(repos)} 个项目：")
        for i, r in enumerate(repos, 1):
            print(f"{i:>2}. ⭐{r['stars']:>6} [{r['lang']}] {r['name']}  {r['desc'][:56]}")
        if args.dry_run:
            print("\n[dry-run] 未发送邮件。正式发送请运行：python send_trending.py")
            return
        print("[3/3] 正在发送邮件 ...")
        date, n, to = core.send_today_mail(cfg)
        print(f"[OK] {date} 共 {n} 个项目，邮件已发送到：{to}")
    except (ValueError, RuntimeError) as e:
        print(f"[错误] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[错误] 发生异常：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
