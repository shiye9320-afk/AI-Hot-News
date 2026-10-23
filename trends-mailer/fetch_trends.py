#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取 X（Twitter）与 YouTube 热点，生成 Markdown + HTML 报告。

数据来源（全部免 API key / 免登录）：
  X 热点     : getdaytrends.com（主源）、trends24.in（备源，用于交叉校验）
  YouTube    : RSSHub 公共实例的 /youtube/charts/TrendingVideos/:country

用法：
  python fetch_trends.py                      # 默认美国区，输出到 reports/
  python fetch_trends.py --region japan --yt-country jp
  python fetch_trends.py --limit 15 --out-dir ./reports
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
TIMEOUT = 25

# RSSHub 公共实例，按顺序容错
RSSHUB_INSTANCES = [
    "https://rsshub.rssforever.com",
    "https://rsshub.app",
    "https://rsshub.pseudoyu.com",
    "https://rss.shab.fun",
]


@dataclass
class Trend:
    name: str
    url: str = ""
    volume: str = ""


@dataclass
class Video:
    title: str
    channel: str = ""
    url: str = ""
    published: str = ""


@dataclass
class Report:
    x_region: str = "united-states"
    x_trends: list[Trend] = field(default_factory=list)
    x_source: str = ""
    x_confirm: list[str] = field(default_factory=list)
    yt_country: str = "us"
    yt_videos: list[Video] = field(default_factory=list)
    yt_source: str = ""
    errors: list[str] = field(default_factory=list)


def _get(url: str, tries: int = 2) -> requests.Response | None:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            if r.status_code == 200 and r.text.strip():
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if i + 1 < tries:
            time.sleep(2)
    print(f"  [warn] {url} -> {last}", file=sys.stderr, flush=True)
    return None


# --------------------------------------------------------------------------- X

def fetch_x_getdaytrends(region: str) -> list[Trend]:
    """getdaytrends.com：<a href="/{region}/trend/xxx/">话题</a>"""
    r = _get(f"https://getdaytrends.com/{region}/")
    if r is None:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[Trend] = []
    seen: set[str] = set()
    for a in soup.select(f'a[href*="/{region}/trend/"]'):
        name = a.get_text(" ", strip=True)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        href = a.get("href", "")
        out.append(Trend(name=name, url=f"https://getdaytrends.com{href}" if href.startswith("/") else href))
    return out


def fetch_x_trends24(region: str) -> list[Trend]:
    """trends24.in：.trend-card__list li a"""
    r = _get(f"https://trends24.in/{region}/")
    if r is None:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[Trend] = []
    seen: set[str] = set()
    for a in soup.select(".trend-card__list li a"):
        name = a.get_text(" ", strip=True)
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(Trend(name=name, url=a.get("href", "")))
    return out


def merge_x(primary: list[Trend], backup: list[Trend], limit: int) -> tuple[list[Trend], list[str]]:
    """主源排序为准，返回 (榜单, 两个源都出现的话题)"""
    if not primary:
        return backup[:limit], []
    if not backup:
        return primary[:limit], []
    bset = {t.name.lower() for t in backup}
    confirm = [t.name for t in primary if t.name.lower() in bset]
    return primary[:limit], confirm


# ----------------------------------------------------------------------- YouTube

def fetch_youtube_trending(limit: int, proxy: str = "") -> tuple[list[Video], str]:
    """YouTube 全站热门（youtube.com/feed/trending），走 yt-dlp，需要能访问 YouTube。"""
    try:
        import yt_dlp  # 延迟导入：不抓 YouTube 时无需安装
    except ImportError:
        print("  [warn] 未安装 yt-dlp，跳过 YouTube（pip install yt-dlp）", file=sys.stderr, flush=True)
        return [], ""

    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": limit,
    }
    if proxy:
        opts["proxy"] = proxy

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://www.youtube.com/feed/trending", download=False)
    except Exception as e:  # noqa: BLE001
        msg = str(e).splitlines()[0][:120] if str(e) else type(e).__name__
        print(f"  [warn] YouTube 全站热门抓取失败：{msg}", file=sys.stderr, flush=True)
        return [], ""

    videos: list[Video] = []
    for e in (info.get("entries") or []):
        if len(videos) >= limit:
            break
        title = (e.get("title") or "").strip()
        vid = e.get("id") or ""
        if not title or not vid:
            continue
        videos.append(
            Video(
                title=title,
                channel=(e.get("channel") or e.get("uploader") or "").strip(),
                url=f"https://www.youtube.com/watch?v={vid}",
            )
        )
    return videos, "youtube.com/feed/trending"


def fetch_youtube_charts(country: str, limit: int) -> tuple[list[Video], str]:
    """YouTube 音乐趋势榜（RSSHub，免 key 但需要能访问 RSSHub 实例）"""
    for base in RSSHUB_INSTANCES:
        url = f"{base}/youtube/charts/TrendingVideos/{country}"
        r = _get(url, tries=1)
        if r is None:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            continue
        videos: list[Video] = []
        for item in root.iter("item"):
            title_raw = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if not title_raw:
                continue
            # RSSHub 的标题格式为「视频名 - 频道名」
            if " - " in title_raw:
                title, channel = title_raw.rsplit(" - ", 1)
            else:
                title, channel = title_raw, ""
            videos.append(Video(title=title.strip(), channel=channel.strip(), url=link, published=pub))
            if len(videos) >= limit:
                break
        if videos:
            return videos, base
    return [], ""


def fetch_youtube(limit: int, source: str = "trending", country: str = "us", proxy: str = "") -> tuple[list[Video], str]:
    if source == "charts":
        return fetch_youtube_charts(country, limit)
    return fetch_youtube_trending(limit, proxy)


# ----------------------------------------------------------------------- render

def md_escape(s: str) -> str:
    return re.sub(r"([\[\]*_`])", r"\\\1", s)


def yt_label(rep: Report) -> str:
    """给 YouTube 区块用的人话标签：全站热门 / 某地区音乐榜"""
    if "feed/trending" in rep.yt_source:
        return "全站热门"
    if rep.yt_country:
        return f"音乐趋势榜 · {rep.yt_country}"
    return "趋势"


def render_markdown(rep: Report, now: datetime) -> str:
    lines = [
        f"# 今日热点速览 · {now:%Y-%m-%d %H:%M} (UTC+8)",
        "",
        f"- X 热门（{rep.x_region}）：{len(rep.x_trends)} 条"
        + (f"，来源 {rep.x_source}" if rep.x_source else "，抓取失败"),
        f"- YouTube {yt_label(rep)}：{len(rep.yt_videos)} 条"
        + ("" if rep.yt_source else "，抓取失败"),
        "",
        "## X（Twitter）实时热搜",
        "",
    ]
    if rep.x_trends:
        lines += ["| # | 话题 |", "|---|---|"]
        for i, t in enumerate(rep.x_trends, 1):
            lines.append(f"| {i} | {md_escape(t.name)} |")
        if rep.x_confirm:
            lines += ["", f"> 双源交叉验证：{len(rep.x_confirm)} 个话题在两个独立镜像同时出现。"]
    else:
        lines.append("_抓取失败，请检查网络或稍后重试。_")

    lines += ["", "## YouTube 趋势视频", ""]
    if rep.yt_videos:
        lines += ["| # | 视频 | 频道 |", "|---|---|---|"]
        for i, v in enumerate(rep.yt_videos, 1):
            lines.append(f"| {i} | [{md_escape(v.title)}]({v.url}) | {md_escape(v.channel)} |")
    else:
        lines.append("_抓取失败，请检查网络或稍后重试。_")

    if rep.errors:
        lines += ["", "## 抓取日志", ""] + [f"- {e}" for e in rep.errors]

    lines += ["", "---", "_由 trends-mailer 自动生成_"]
    return "\n".join(lines)


def render_html(rep: Report, now: datetime) -> str:
    def x_rows() -> str:
        if not rep.x_trends:
            return '<tr><td style="padding:16px;color:#8a8f98;">抓取失败</td></tr>'
        rows = []
        for i, t in enumerate(rep.x_trends, 1):
            rows.append(
                f'<tr>'
                f'<td style="padding:9px 12px;color:#9aa0aa;font-size:13px;width:38px;">{i}</td>'
                f'<td style="padding:9px 12px;font-size:15px;color:#1d1d1f;'
                f'border-top:1px solid #f0f0f2;">{t.name}</td>'
                f"</tr>"
            )
        return "".join(rows)

    def yt_rows() -> str:
        if not rep.yt_videos:
            return '<tr><td style="padding:16px;color:#8a8f98;">抓取失败</td></tr>'
        rows = []
        for i, v in enumerate(rep.yt_videos, 1):
            rows.append(
                f'<tr>'
                f'<td style="padding:10px 12px;color:#9aa0aa;font-size:13px;width:38px;">{i}</td>'
                f'<td style="padding:10px 12px;border-top:1px solid #f0f0f2;">'
                f'<a href="{v.url}" style="color:#0a66c2;text-decoration:none;font-size:15px;'
                f'line-height:1.45;">{v.title}</a>'
                f'<div style="color:#8a8f98;font-size:12px;margin-top:3px;">{v.channel}</div>'
                f"</td></tr>"
            )
        return "".join(rows)

    confirm = ""
    if rep.x_confirm:
        confirm = (
            f'<div style="margin:10px 0 0;font-size:12px;color:#7a828e;">'
            f"双源交叉验证：{len(rep.x_confirm)} 个话题在两个独立镜像同时出现</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f7;">
<div style="max-width:640px;margin:0 auto;padding:32px 16px;
font-family:-apple-system,BlinkMacSystemFont,'SF Pro SC','PingFang SC','Segoe UI',sans-serif;">
  <div style="background:#fff;border-radius:18px;overflow:hidden;
  box-shadow:0 1px 3px rgba(0,0,0,.06),0 8px 28px rgba(0,0,0,.05);">
    <div style="padding:28px 26px 22px;background:linear-gradient(135deg,#1d1d1f 0%,#3a3a3c 100%);">
      <div style="color:#fff;font-size:21px;font-weight:600;letter-spacing:.3px;">今日热点速览</div>
      <div style="color:rgba(255,255,255,.62);font-size:13px;margin-top:6px;">{now:%Y 年 %m 月 %d 日 %H:%M} · UTC+8</div>
    </div>

    <div style="padding:22px 26px 6px;">
      <div style="font-size:13px;color:#86868b;letter-spacing:.8px;font-weight:600;
      text-transform:uppercase;">X · Twitter 热搜</div>
      <div style="font-size:12px;color:#a1a1a6;margin-top:4px;">地区 {rep.x_region}　{len(rep.x_trends)} 条</div>
    </div>
    <table style="width:100%;border-collapse:collapse;">{x_rows()}</table>
    <div style="padding:0 26px 22px;">{confirm}</div>

    <div style="height:1px;background:#f0f0f2;margin:0 26px;"></div>

    <div style="padding:22px 26px 6px;">
      <div style="font-size:13px;color:#86868b;letter-spacing:.8px;font-weight:600;
      text-transform:uppercase;">YouTube 趋势</div>
      <div style="font-size:12px;color:#a1a1a6;margin-top:4px;">{yt_label(rep)}　{len(rep.yt_videos)} 条</div>
    </div>
    <table style="width:100%;border-collapse:collapse;">{yt_rows()}</table>
    <div style="padding:0 26px 26px;"></div>
  </div>
  <div style="text-align:center;color:#a1a1a6;font-size:11px;padding:18px 0 8px;">
    由 trends-mailer 自动生成 · 数据来自公开镜像
  </div>
</div>
</body></html>"""


# ------------------------------------------------------------------------- main

def build_report(region: str, yt_country: str, limit: int, yt_source: str = "trending", proxy: str = "") -> Report:
    rep = Report(x_region=region, yt_country=yt_country)

    print("[1/2] 抓取 X 热搜 ...")
    primary = fetch_x_getdaytrends(region)
    backup = fetch_x_trends24(region)
    if primary:
        rep.x_source = "getdaytrends.com"
    elif backup:
        rep.x_source = "trends24.in"
    rep.x_trends, rep.x_confirm = merge_x(primary, backup, limit)
    print(f"      -> {len(rep.x_trends)} 条（主源 {len(primary)} / 备源 {len(backup)}）")
    if not primary and not backup:
        rep.errors.append("X 热搜：两个镜像均抓取失败")

    print(f"[2/2] 抓取 YouTube（{yt_source}）...")
    rep.yt_videos, rep.yt_source = fetch_youtube(limit, yt_source, yt_country, proxy)
    print(f"      -> {len(rep.yt_videos)} 条（{rep.yt_source or '失败'}）")
    if not rep.yt_videos:
        rep.errors.append(
            "YouTube：抓取失败。全站热门需要能访问 youtube.com（本机被墙时请挂代理或改用 GitHub Actions）"
        )

    return rep


def report_from_json(path: Path) -> Report:
    """从本地快照 JSON 构建报告（离线 / 复现用）"""
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    rep = Report(
        x_region=data.get("x_region", ""),
        x_source=data.get("x_source", ""),
        yt_country=data.get("yt_country", ""),
        yt_source=data.get("yt_source", ""),
        errors=data.get("errors", []),
    )
    rep.x_trends = [Trend(name=n) if isinstance(n, str) else Trend(**n) for n in data.get("x_trends", [])]
    rep.x_confirm = data.get("x_confirm", [])
    rep.yt_videos = [Video(**v) for v in data.get("yt_videos", [])]
    return rep


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取 X / YouTube 热点并生成报告")
    ap.add_argument("--region", default="united-states", help="X 地区，如 united-states / japan / worldwide")
    ap.add_argument("--yt-country", default="us", help="YouTube 国家码（仅 --yt-source charts 时生效）")
    ap.add_argument("--yt-source", default="trending", choices=["trending", "charts"],
                    help="trending=全站热门（默认），charts=音乐趋势榜")
    ap.add_argument("--limit", type=int, default=30, help="每类最多条数")
    ap.add_argument("--out-dir", default="reports", help="输出目录")
    ap.add_argument("--proxy", default=os.environ.get("YT_PROXY", ""),
                    help="抓 YouTube 用的代理，如 http://127.0.0.1:7890（也可设 YT_PROXY）")
    ap.add_argument("--from-json", default="", help="从本地快照 JSON 生成，不走网络")
    args = ap.parse_args()

    now = datetime.now(timezone(timedelta(hours=8)))
    if args.from_json:
        rep = report_from_json(Path(args.from_json))
        rep.x_trends = rep.x_trends[: args.limit]
        rep.yt_videos = rep.yt_videos[: args.limit]
        # 截断后重新核对交叉验证结果，避免计数与实际榜单不符
        kept = {t.name.lower() for t in rep.x_trends}
        rep.x_confirm = [n for n in rep.x_confirm if n.lower() in kept]
        print(f"[offline] 从快照构建：{args.from_json}")
    else:
        rep = build_report(args.region, args.yt_country, args.limit, args.yt_source, args.proxy)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{now:%Y-%m-%d}"
    md_path = out / f"{stamp}.md"
    html_path = out / f"{stamp}.html"
    md_path.write_text(render_markdown(rep, now), encoding="utf-8")
    html_path.write_text(render_html(rep, now), encoding="utf-8")

    print(f"\n[ok] {md_path}")
    print(f"[ok] {html_path}")

    # 供 GitHub Actions 判断是否需要告警
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"x_count={len(rep.x_trends)}\nyt_count={len(rep.yt_videos)}\n")
            f.write(f"md_path={md_path.as_posix()}\nhtml_path={html_path.as_posix()}\n")

    return 0 if (rep.x_trends or rep.yt_videos) else 1


if __name__ == "__main__":
    sys.exit(main())
