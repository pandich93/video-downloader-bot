# Contributing

Thanks for your interest! Bug reports, fixes, translations and new editor presets are all welcome.

## Before you start

- For anything bigger than a small fix, open an issue first so we agree on the approach.
- Out of scope: bypassing DRM or paywalls, downloading private content without the owner's
  permission, removing other people's watermarks. Such pull requests will be closed.

## Development setup

You need Python 3.12+ and, to try the editor, `ffmpeg` and `ffprobe` in `PATH`.

```bash
git clone https://github.com/pandich93/video-downloader-bot.git
cd video-downloader-bot
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # set BOT_TOKEN and ADMIN_ID of a test bot
python main.py
```

Use a separate test bot from @BotFather, not your production one.

## Checks

```bash
ruff check .
pytest
```

Both run in CI on every pull request. Tests do not need FFmpeg, network access or a bot token —
please keep it that way: test pure functions (link parsing, plans, queues) and leave network calls out.

## Code style

- Follow the style of the surrounding code: small functions, type hints, `logging` instead of `print`.
- Existing comments and user-facing texts are in Russian. Comments in English are fine in new code;
  bot messages stay in Russian until the project gets translations.
- Errors shown to users are separate exception types (`DownloadFailed`, `EditFailed`, `LimitError`)
  with a ready-to-show message. Unexpected errors are logged with `log.exception` — the admin
  gets them in Telegram.
- Never log tokens, cookies or full proxy URLs (see `mask_proxy`).

## Pull requests

- One topic per pull request, with a short description of what and why.
- Update `README.md`, `README.ru.md` and `.env.example` when you add a setting.
- Add a line to `CHANGELOG.md` under **Unreleased**.
