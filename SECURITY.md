# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository
([direct link](https://github.com/pandich93/video-downloader-bot/security/advisories/new)).

Include what an attacker can do, the steps to reproduce, and the version or commit you tested.
You should get a first reply within 7 days.

## Supported versions

Only the latest release and the `main` branch receive fixes.

## What counts

- Access control bypass: using the bot while not in `ALLOWED_USER_IDS`, getting around `/ban`
  or daily limits, running admin commands as a regular user.
- Leaks of `BOT_TOKEN`, `API_HASH`, the MTProto session, cookies or other users' data
  (logs, error messages, the cache database).
- Injection into FFmpeg or yt-dlp arguments, reading or writing files outside the download folder.

Out of scope: problems of yt-dlp, Telegram or the video sites themselves, and denial of service
by sending many large videos (use `DAILY_LIMIT` and `PUBLIC_MAX_FILE_MB`).

## Keeping your own bot safe

- `.env`, `mtproto.session` and `cookies*.txt` give full access to your bot and your accounts.
  They are in `.gitignore` and `.dockerignore` — keep it that way and never post them in issues.
- If a token leaked, revoke it in @BotFather (`/revoke`) and delete `mtproto.session`.
