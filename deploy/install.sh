#!/bin/bash
# Автозапуск бота через launchd: стартует при входе в систему и поднимается после падения.
set -euo pipefail

LABEL="com.pandadownloader.bot"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$DIR/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

[ -x "$PY" ] || { echo "❌ Не найден $PY — сначала создайте .venv и установите зависимости (см. README)"; exit 1; }
[ -f "$DIR/.env" ] || { echo "❌ Нет файла .env в $DIR"; exit 1; }

case "$DIR" in
  "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
    echo "⚠️  Проект лежит в $DIR"
    echo "   macOS не даёт фоновым программам доступ к Рабочему столу, Документам и Загрузкам."
    echo "   Если бот не запустится (в logs/launchd.log будет 'Operation not permitted'), см. README → «Автозапуск»."
    ;;
esac

mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PY</string>
        <string>main.py</string>
    </array>
    <key>WorkingDirectory</key><string>$DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>15</integer>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>PYTHONUNBUFFERED</key><string>1</string>
    </dict>
    <key>StandardOutPath</key><string>$DIR/logs/launchd.log</string>
    <key>StandardErrorPath</key><string>$DIR/logs/launchd.log</string>
</dict>
</plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"

echo "✅ Автозапуск установлен. Проверяю через 5 секунд…"
sleep 5
if launchctl print "$DOMAIN/$LABEL" | grep -q "state = running"; then
  echo "✅ Бот работает. Лог: tail -f \"$DIR/logs/bot.log\""
else
  echo "❌ Бот не запустился. Последние строки logs/launchd.log:"
  tail -n 20 "$DIR/logs/launchd.log" 2>/dev/null || true
fi
