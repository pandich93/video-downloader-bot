#!/bin/bash
# Статус бота и последние строки лога.
LABEL="com.pandadownloader.bot"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
if launchctl print "gui/$(id -u)/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit code"; then :; else
  echo "Автозапуск не установлен (запустите deploy/install.sh)"; fi
echo "--- logs/bot.log ---"
tail -n 15 "$DIR/logs/bot.log" 2>/dev/null || echo "лога пока нет"
