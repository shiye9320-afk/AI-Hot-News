#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 fetch_trends.py 生成的 HTML 报告通过 SMTP 发到邮箱。

环境变量（GitHub Secrets 同名）：
  SMTP_HOST   smtp.qq.com / smtp.163.com / smtp.gmail.com
  SMTP_PORT   465（SSL）或 587（STARTTLS），默认 465
  SMTP_USER   登录账号，如 xxx@qq.com
  SMTP_PASS   授权码（不是登录密码！QQ 邮箱在「设置-账户」里生成）
  MAIL_TO     收件地址，多个用逗号分隔
  MAIL_FROM_NAME  可选，发件人显示名，默认「热点速览」

用法：
  python send_mail.py --html reports/2026-10-23.html --md reports/2026-10-23.md
"""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path


def env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="HTML 报告路径")
    ap.add_argument("--md", default="", help="Markdown 报告路径（作为附件）")
    args = ap.parse_args()

    host = env("SMTP_HOST", "smtp.qq.com")
    port = int(env("SMTP_PORT", "465"))
    user = env("SMTP_USER")
    password = env("SMTP_PASS")
    to_raw = env("MAIL_TO")
    from_name = env("MAIL_FROM_NAME", "热点速览")

    missing = [k for k, v in {"SMTP_USER": user, "SMTP_PASS": password, "MAIL_TO": to_raw}.items() if not v]
    if missing:
        print(f"[error] 缺少环境变量：{', '.join(missing)}", file=sys.stderr)
        return 2

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"[error] 找不到报告：{html_path}", file=sys.stderr)
        return 2

    recipients = [x.strip() for x in to_raw.replace(";", ",").split(",") if x.strip()]
    now = datetime.now(timezone(timedelta(hours=8)))

    msg = EmailMessage()
    msg["Subject"] = f"今日热点速览 · {now:%Y-%m-%d}"
    msg["From"] = formataddr((from_name, user))
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    msg.set_content(
        f"今日热点速览（{now:%Y-%m-%d %H:%M} UTC+8）\n\n"
        "你的邮件客户端不支持 HTML 时看到的这条纯文本提示。\n"
        "请用支持 HTML 的客户端查看，或直接打开附件中的 Markdown。\n"
    )
    msg.add_alternative(html_path.read_text(encoding="utf-8"), subtype="html")

    if args.md and Path(args.md).exists():
        msg.add_attachment(
            Path(args.md).read_bytes(),
            maintype="text",
            subtype="markdown",
            filename=Path(args.md).name,
        )

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg, from_addr=user, to_addrs=recipients)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, password)
                s.send_message(msg, from_addr=user, to_addrs=recipients)
    except Exception as e:  # noqa: BLE001
        print(f"[error] 发送失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"[ok] 已发送至 {', '.join(recipients)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
