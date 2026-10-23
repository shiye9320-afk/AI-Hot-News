# trends-mailer

抓取 **X（Twitter）实时热搜** 和 **YouTube 趋势视频**，生成 HTML 报告并用邮件发送。
全部走公开镜像，**不需要任何 API Key、不需要登录账号**。

## 数据源

| 数据 | 来源 | 说明 |
|---|---|---|
| X 热搜 | `getdaytrends.com`（主）+ `trends24.in`（备） | 两个独立镜像交叉验证，同时出现的话题会在报告里标注 |
| YouTube 全站热门 | **Piped 镜像** `/trending?region=US`（主） | 默认。实测 `api.piped.private.coffee` 可用，返回 15 条真实热门 |
| ↳ 备用链路 | yt-dlp 抓 `/feed/trending` | ⚠️ **该页面已被 YouTube 官方下架**，现在会 302 到首页，仅作兼容保留 |
| ↳ 再备用 | Invidious 镜像 `/api/v1/trending?region=US` | 生态萎缩严重，全球仅剩极少数实例 |
| YouTube 音乐趋势 | RSSHub `/youtube/charts/TrendingVideos/:country` | 备选，`--yt-source charts` 时启用 |

> **关于 `/feed/trending`**：这个页面在 2025 年被 YouTube 移除，yt-dlp 会报
> `The channel/playlist does not exist and the URL redirected to youtube.com home page`。
> 这不是代码问题，所以脚本改成了 Piped/Invidious 镜像兜底。
>
> 想要**零故障的官方数据**，可以申请 YouTube Data API v3 的 key，用
> `videos?part=snippet&chart=mostPopular&regionCode=US`（免费额度 10000 units/天，1 次调用 1 unit），
> 这条路最稳，但需要 Google Cloud 项目。

⚠️ **这些镜像在境外**。大陆裸网访问会被墙，所以推荐直接丢给 GitHub Actions 跑（runner 天然可访问）。

## 快速开始

```bash
pip install -r requirements.txt

# 美国区 + YouTube 全站热门（默认）
python fetch_trends.py

# 本机挂了代理（YouTube 必开）
python fetch_trends.py --proxy http://127.0.0.1:7890

# 换 X 地区 / 条数
python fetch_trends.py --region japan --limit 30

# 想要音乐榜而不是全站热门
python fetch_trends.py --yt-source charts --yt-country jp

# 离线复现（用已有快照，不走网络）
python fetch_trends.py --from-json reports/2026-10-23.raw.json --limit 30
```

产物在 `reports/`：
- `YYYY-MM-DD.html` —— 邮件正文，也是可直接浏览器打开的成品页
- `YYYY-MM-DD.md` —— Markdown 版，作邮件附件

`--region` 可选 `united-states` / `japan` / `worldwide` 等（对应 getdaytrends 的地区路径）。

## 发邮件

```bash
export SMTP_HOST=smtp.qq.com
export SMTP_PORT=465
export SMTP_USER=你的邮箱@qq.com
export SMTP_PASS=授权码        # 不是登录密码
export MAIL_TO=收件邮箱@qq.com

python send_mail.py --html reports/2026-10-23.html --md reports/2026-10-23.md
```

**各服务商配置对照**（代码不用改，只换环境变量）：

| 邮箱 | SMTP_HOST | SMTP_PORT | 授权码获取位置 |
|---|---|---|---|
| QQ 邮箱 | `smtp.qq.com` | `465` | 设置 → 账户 → 开启「IMAP/SMTP 服务」 |
| 网易 163 | `smtp.163.com` | `465` | 设置 → POP3/SMTP/IMAP → 开启 SMTP 服务 |
| 网易 126 | `smtp.126.com` | `465` | 同上 |
| 网易 yeah.net | `smtp.yeah.net` | `465` | 同上 |
| 网易企业邮 | `smtp.qiye.163.com` | `465` | 管理员后台开启 |
| Gmail | `smtp.gmail.com` | `465` | 用「应用专用密码」 |

⚠️ **网易邮箱的坑**：163/126 反垃圾策略比 QQ 严，报告里有 30 个 YouTube 链接，
容易被判垃圾邮件甚至拒信（返回 `554 DT:SPM`）。如果遇到，把 `--limit` 降到 10~15，
或改用 QQ 邮箱发送。另外 163 要求发件地址必须与登录账号一致（本脚本已满足）。

## 部署到 GitHub Actions（推荐）

本机在大陆直连 X / YouTube 会超时，交给 GitHub 的 runner 跑最省心：

1. 新建仓库，把本项目推上去
2. 仓库 Settings → Secrets and variables → Actions，添加：

| Secret | 示例值 |
|---|---|
| `SMTP_HOST` | `smtp.qq.com` |
| `SMTP_PORT` | `465` |
| `SMTP_USER` | `xxx@qq.com` |
| `SMTP_PASS` | 授权码 |
| `MAIL_TO` | 收件邮箱，多个用逗号分隔 |

3. 默认每天北京时间 08:00 自动发（`cron: "0 0 * * *"`，UTC）
4. 也可以到 Actions 页面手动 `Run workflow`，临时指定地区和条数

## 文件结构

```
fetch_trends.py                    抓取 + 渲染（MD / HTML）
send_mail.py                       SMTP 发信
requirements.txt
.github/workflows/daily-trends.yml 定时任务
reports/                           产物与数据快照
```

## 已知限制

- **X 热搜来自第三方镜像**，不是官方 API。榜单有几分钟延迟，且镜像偶尔会挂——所以做了双源备份。
- 想要**零延迟的官方数据**，得用 X 官方 API v1.1 的 `trends/place.json`（付费），
  或用 `twscrape` 拿自己账号的 cookie 直连（免官方 Key，但需登录态）。见项目 README 末节的备注。
- YouTube 走的是公共 RSSHub 实例，被限流时脚本会自动切换实例，全挂则报告中标记抓取失败。
