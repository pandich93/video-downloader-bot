# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Tests for link normalization, editor options, FFmpeg plans, the slot queue and config parsing.
- CI on GitHub Actions: `ruff check` and `pytest` on Python 3.12 and 3.14.
- English README, Russian README moved to `README.ru.md`.
- MIT license, contributing guide, code of conduct, security policy, issue and PR templates.
- Variation strength in the editor settings: medium (default, as before), light (about half as strong)
  or off. Each variation records its `seed` in the log, so it can be reproduced.

### Changed
- **📦 All 3** picks the three variations together: every parameter falls into its own third of the
  range, so the files always differ from each other instead of occasionally coming out nearly identical.
- **Breaking:** the bot is private by default. An empty `ALLOWED_USER_IDS` now means "only the admin";
  to open the bot to everyone, set `PUBLIC_MODE=true`.
- `.idea/` is no longer tracked; `.dockerignore` keeps the MTProto session, cookies, the cache
  database and logs out of Docker images.
- `.env.example` no longer contains a real nickname.

### Fixed
- "As in the original" frame with variation: the zoom no longer shrinks the video (e.g. 1920×1080 → 1850×1040),
  so the hook, nickname and logo land where they were laid out.
- Windows autostart: the scheduled task now checks every 5 minutes and starts the bot again if its
  wrapper was killed; `run.ps1` exits when the bot is already running, so there is no second copy.
  Run `Запустить автозапуск.bat` again to update an existing task.

## [1.0.0] — planned first public release

### Added
- Download videos from YouTube, TikTok and Instagram by link; best quality that fits
  Telegram's 50 MB limit, chosen before downloading.
- TikTok via tikwm.com, with Telegram's servers fetching the file when the TikTok CDN is unreachable.
- Instant re-send of already delivered videos from a SQLite `file_id` cache.
- Video editor for TikTok, Reels and Shorts: 9:16 crop or blurred background, three styling levels,
  text hook, nickname, logo, progress bar, loudness normalization, metadata removal, random variation,
  Intel Quick Sync with CPU fallback.
- Files up to 2 GB through MTProto (Telethon).
- Public mode: user accounting, daily limits, bans, `/stats`, queue with position updates.
- Admin notifications about errors, daily yt-dlp auto-update, restart on `.env` change or `/restart`.
- Autostart on macOS (launchd) and Windows (Task Scheduler), Dockerfile.
