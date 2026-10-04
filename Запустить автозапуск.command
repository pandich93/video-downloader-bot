#!/bin/bash
# Двойной клик в Finder: останавливает бота, запущенного вручную, и включает автозапуск через launchd.
cd "$(dirname "$0")"
HERE="$(pwd -P)"
# Останавливаем только python main.py, запущенный именно из этой папки
for pid in $(pgrep -f "main.py"); do
  cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')"
  if [ "$cwd" = "$HERE" ]; then
    kill "$pid" && echo "⏹ Остановлен бот, запущенный вручную (pid $pid)"
    sleep 2
  fi
done
./deploy/install.sh
echo
echo "Окно можно закрыть."
