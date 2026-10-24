# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Tests for link normalization, editor options, FFmpeg plans, the slot queue and config parsing.
- CI on GitHub Actions: `ruff check` and `pytest` on Python 3.12 and 3.14.
- English README, Russian README moved to `README.ru.md`.
- MIT license, contributing guide, code of conduct, security policy, issue and PR templates.

### Changed
- `.idea/` is no longer tracked; `.dockerignore` keeps the MTProto session, cookies, the cache
  database and logs out of Docker images.
- `.env.example` no longer contains a real nickname.

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
