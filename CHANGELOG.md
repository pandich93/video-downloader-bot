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
- The original title and description go into the video caption — for downloads and for edited videos
  (above the "Изменено: …" line). Text longer than the 1024-character caption is shortened with "…"
  and sent in full as the next message (once per **📦 All 3** batch). The description is also kept in
  the `file_id` cache; `cache.db` from earlier versions is migrated in place, no records are lost.
- ✍️ AI texts in the editor (optional, `OPENROUTER_API_KEY`): its own title, description and hashtags for
  TikTok, Reels and Shorts from the original text, different for each platform and within its limits.
  Free OpenRouter models only (`OPENROUTER_MODELS`, tried in order; models without `:free` are skipped;
  if none answers, up to 5 current free models come from the public catalog); one request per run, even for
  **📦 All 3**. On any failure — the original text and a warning in the log. In public mode AI texts are
  for the admin and `ALLOWED_USER_IDS` unless `LLM_PUBLIC=true`.
- AI texts are written by an SEO master prompt (SEO analyst + targeting specialist + SMM editor): the main
  search query goes first in the title and in the first 125 characters, hashtags are broad + niche + topic
  (no empty tags like #fyp), a call to action fits the video, and nothing is added that the original does
  not say — a question without an answer stays a teaser. Hashtags are no longer repeated inside the
  description. Reasoning models get 8000 tokens and 180 s, so their answers are no longer cut off;
  the default free models are the ones that actually answered in testing.

### Changed
- **📦 All 3** picks the three variations together: every parameter falls into its own third of the
  range, so the files always differ from each other instead of occasionally coming out nearly identical.
- **Breaking:** the bot is private by default. An empty `ALLOWED_USER_IDS` now means "only the admin";
  to open the bot to everyone, set `PUBLIC_MODE=true`.
- `.idea/` is no longer tracked; `.dockerignore` keeps the MTProto session, cookies, the cache
  database and logs out of Docker images.
- `.env.example` no longer contains a real nickname.

### Fixed
- A connection reset by the provider (`ConnectionResetError`, WinError 10054) is now treated as a blocked
  site: the user gets the "enable VPN or PROXY" hint and the admin no longer gets an error notification.
- Captions of files sent through MTProto are no longer parsed as Markdown, so `**` and `__` from the
  original text stay as they are.
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
