# PandaDownloader

**English** · [Русский](README.ru.md)

[![CI](https://github.com/pandich93/video-downloader-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/pandich93/video-downloader-bot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![aiogram 3](https://img.shields.io/badge/aiogram-3-2CA5E0.svg)

A self-hosted Telegram bot that downloads videos from **YouTube, TikTok and Instagram** and turns them
into ready-to-post **9:16 clips for TikTok, Reels and Shorts** — with FFmpeg, on your own computer.

<!--
  Demo: record 15–20 seconds of the bot (send link → "Edit" → "TikTok" → result), e.g. with
  ScreenToGif (Windows) or Kap (macOS), export ≤ 5 MB, save as docs/demo.gif and uncomment:
  <p align="center"><img src="docs/demo.gif" width="320" alt="PandaDownloader demo"></p>
-->

> The bot interface is in Russian. Translations are welcome — see [Contributing](CONTRIBUTING.md).

## Features

- **Link → video.** Send a link and choose **📥 Original** or **✂️ Edit**.
- **Fits Telegram's limits.** yt-dlp checks format sizes first and downloads the best quality that fits
  into 50 MB (720p → 480p → 360p), H.264 preferred so videos play right in the chat.
- **Instant repeats.** Delivered videos are cached by Telegram `file_id`: the same video sent again
  (even as `youtu.be` vs `youtube.com`, or a short TikTok link) comes back immediately.
- **TikTok where tiktok.com is unreachable.** Metadata comes from tikwm.com, and Telegram's own servers
  fetch the file — no VPN on the host needed for videos up to 20 MB.
- **Video editor for short-form platforms:**
  - presets for TikTok (up to 10 min), Reels and Shorts (up to 3 min): 9:16 frame — crop for vertical
    sources, blurred background for horizontal ones, H.264 + AAC, loudness around −14 LUFS;
  - three styling levels: 🟢 clean · 🟡 styled (color look, logo, fade-in) · 🟣 authored (text hook for the
    first 3 seconds, your nickname, a progress bar in your brand color);
  - trimming (`0:05-0:40`), speed 1×/1.05×/1.1×, metadata removal, a slight random variation per export;
  - **📦 All 3** — one source, three files; hardware encoding on Intel Quick Sync with CPU fallback.
- **Files up to 2 GB** through MTProto (Telethon) instead of the Bot API's 20/50 MB.
- **Public or private.** Whitelist or open mode, daily limits, one job at a time, `/ban`, `/stats`,
  a queue that shows each user their position.
- **Runs unattended.** Daily yt-dlp updates, restart on `.env` change or `/restart`, errors are sent to the
  admin in Telegram. Autostart on Windows (Task Scheduler) and macOS (launchd), or Docker.

## Quick start (Docker)

1. Create a bot with [@BotFather](https://t.me/BotFather) and get your Telegram ID from
   [@userinfobot](https://t.me/userinfobot).
2. Run:

```bash
git clone https://github.com/pandich93/video-downloader-bot.git && cd video-downloader-bot
cp .env.example .env    # set BOT_TOKEN and ADMIN_ID
docker build -t video-bot . && docker run -d --name video-bot --restart unless-stopped --env-file .env video-bot
```

Send the bot a link. Logs: `docker logs -f video-bot`.

## Running without Docker

Requirements: Python 3.12+, [FFmpeg](https://ffmpeg.org/) (merging and editing) and
[Deno](https://deno.com/) (yt-dlp needs a JS runtime for YouTube).

| | Install system tools | Autostart |
|---|---|---|
| **Windows** | `winget install --id <ID> -e` for `Python.Python.3.12`, `Gyan.FFmpeg`, `DenoLand.Deno` | double-click `Запустить автозапуск.bat` |
| **macOS** | `brew install python@3.12 ffmpeg deno` | `./deploy/install.sh` |
| **Linux** | your package manager | Docker or a systemd unit |

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip ...
cp .env.example .env                               # set BOT_TOKEN and ADMIN_ID
.venv/bin/python main.py
```

Platform details (sleep settings, macOS folder permissions, Windows logs) are in the
[Russian README](README.ru.md#запуск-на-macos).

## Configuration

All settings live in `.env` (see [.env.example](.env.example)). Changing `.env` restarts the bot within ~30 s.

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | Token from @BotFather (required) |
| `ADMIN_ID` | first of `ALLOWED_USER_IDS` | Your Telegram ID: admin commands, notifications, no limits |
| `ALLOWED_USER_IDS` | empty = open to everyone | Comma-separated whitelist |
| `DAILY_LIMIT` | `20` | Jobs per user per day, `0` = unlimited |
| `PUBLIC_MAX_FILE_MB` | `500` | Max uploaded file for regular users (needs MTProto) |
| `BLOCKED_USER_IDS` | — | Comma-separated bans (also `/ban id`) |
| `COOKIES_FILE` | — | Netscape cookies for Instagram / YouTube "confirm you're not a bot" |
| `PROXY`, `PROXY_TYPE` | — | Proxy for all downloads, e.g. `socks5://127.0.0.1:1080` or `host:port:user:pass` |
| `API_ID`, `API_HASH` | — | From [my.telegram.org](https://my.telegram.org) — enables files up to 2 GB |
| `VIDEO_ENCODER` | `auto` | `auto` / `qsv` / `cpu` |
| `BRAND_COLOR`, `NICK` | `#FF4D00`, — | Progress bar color and nickname for the 🟣 level |
| `DOWNLOAD_DIR`, `MAX_FILE_MB` | `downloads`, `50` | Temp folder (**cleared on start**) and Bot API size limit |
| `AUTO_UPDATE`, `UPDATE_INTERVAL_HOURS` | `true`, `24` | yt-dlp self-update |
| `NOTIFY_ON_START`, `NOTIFY_NEW_USERS` | `true` | Admin notifications |

Your own logo: put a PNG into `assets/logo.png`. Your own font: `assets/font.ttf`.

**Admin commands:** `/stats` · `/ban <id>` · `/unban <id>` · `/restart`.

## How it works

```
Telegram ──► aiogram handlers ──► access & limits ──► download queue (2) ──► yt-dlp / tikwm
                    │                                        │
                    └──► editor sessions ──► encode queue (1) ──► FFmpeg + Pillow overlays
                                                             │
                     SQLite cache (file_id, users, jobs) ◄───┴──► Bot API (≤ 50 MB) or MTProto (≤ 2 GB)
```

## FAQ

**"Video is larger than 50 MB".** That is the Bot API limit. Add `API_ID`/`API_HASH` to send up to 2 GB.

**Instagram or YouTube asks to log in.** Export cookies from a browser where you are logged in
(`yt-dlp --cookies-from-browser firefox --cookies cookies.txt --skip-download "https://www.instagram.com/"`)
and set `COOKIES_FILE=cookies.txt`. The file is your session — keep it private.

**A site stopped working.** Update yt-dlp: `pip install -U "yt-dlp[default]"` (the bot also does it daily).

**Can I run it for other people?** Yes — leave `ALLOWED_USER_IDS` empty. Mind your home IP (YouTube may
rate-limit it), the queue on a laptop, and the legal note below.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

Tests need no network, FFmpeg or bot token. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Legal

PandaDownloader is a tool for **your own and licensed content**: converting your videos to platform
requirements and removing technical metadata. You are responsible for complying with copyright law and
the terms of service of YouTube, TikTok, Instagram and Telegram. The editor does not make someone else's
video "yours": Content ID and similar systems compare the content itself. This project is not affiliated
with any of these services and uses the third-party service tikwm.com, which may change or stop at any time.

## License

[MIT](LICENSE). The bundled Montserrat font is under the [SIL Open Font License](assets/fonts/OFL.txt).
