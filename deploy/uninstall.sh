#!/bin/bash
# Отключает автозапуск бота.
LABEL="com.pandadownloader.bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "⏹ Бот остановлен" || echo "Бот не был запущен"
rm -f "$PLIST" && echo "🗑 Автозапуск удалён"
