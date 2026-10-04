# Video Downloader Bot

Приватный Telegram-бот: присылаете ссылку на YouTube / TikTok / Instagram — получаете видео в чат.

## Структура

```
telegram_bot/
├── main.py            # точка входа
├── bot/
│   ├── config.py      # настройки из .env
│   ├── downloader.py  # yt-dlp + понижение качества 720p → 480p → 360p
│   ├── tiktok.py      # TikTok через tikwm.com (обход блокировки)
│   ├── handlers.py    # приём ссылок, скачивание оригинала, статусы
│   ├── callbacks.py   # нажатия на кнопки
│   ├── keyboards.py   # инлайн-кнопки
│   ├── link_store.py  # временное хранение ссылок (30 минут)
│   ├── access.py      # белый список пользователей
│   ├── cache.py       # кэш отправленных видео (SQLite, cache.db)
│   ├── notify.py      # уведомления администратору об ошибках
│   ├── updater.py     # автообновление yt-dlp
│   └── watcher.py     # перезапуск при изменении .env / restart.flag
├── deploy/            # install.sh / uninstall.sh / status.sh — автозапуск на Mac
├── logs/              # bot.log (ротация 5 МБ × 3), launchd.log
├── requirements.txt
├── .env.example
└── Dockerfile
```

## Как пользоваться

Отправьте ссылку — бот спросит «Что делаем с видео?» и покажет кнопки
**📥 Оригинал** и **✂️ Редактировать** (обработка видео — в разработке).
Кнопки действуют 30 минут, потом ссылку нужно прислать заново.

## Запуск на macOS

1. **Создайте бота.** В Telegram откройте @BotFather → `/newbot` → скопируйте токен.
2. **Узнайте свой ID.** Напишите @userinfobot — он пришлёт число (ваш user_id).
3. **Установите зависимости системы** (нужен [Homebrew](https://brew.sh)):
   ```bash
   brew install python@3.12 ffmpeg deno
   ```
   `ffmpeg` склеивает видео и звук, `deno` нужен yt-dlp для работы с YouTube.
4. **Установите Python-пакеты:**
   ```bash
   cd ~/Desktop/projects/telegram_bot
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
5. **Настройте .env:**
   ```bash
   cp .env.example .env
   open -e .env   # впишите BOT_TOKEN и ALLOWED_USER_IDS
   ```
6. **Запустите:**
   ```bash
   python main.py
   ```
   Отправьте боту ссылку. Остановка — `Ctrl+C`.

## Автозапуск на Mac (launchd)

Бот стартует сам при входе в систему и перезапускается, если упал.

```bash
cd ~/Desktop/projects/telegram_bot
./deploy/install.sh     # включить (ручной python main.py перед этим остановите — Ctrl+C)
./deploy/status.sh      # статус и последние строки лога
./deploy/uninstall.sh   # выключить
tail -f logs/bot.log    # смотреть лог в реальном времени
```

После изменения `.env` или кода перезапустите: `./deploy/install.sh` ещё раз.

**Если бот не стартует и в `logs/launchd.log` есть `Operation not permitted`** — macOS не пускает
фоновые программы в папки «Рабочий стол», «Документы», «Загрузки». Два варианта:
1. *(рекомендуется)* перенести проект, например в `~/bots/telegram_bot`, и пересоздать `.venv`
   (виртуальное окружение привязано к пути):
   ```bash
   ./deploy/uninstall.sh
   mkdir -p ~/bots && mv ~/Desktop/projects/telegram_bot ~/bots/
   cd ~/bots/telegram_bot && rm -rf .venv && python3.12 -m venv .venv
   source .venv/bin/activate && pip install -r requirements.txt
   ./deploy/install.sh
   ```
2. Дать Python «Полный доступ к диску»: Системные настройки → Конфиденциальность и безопасность →
   Полный доступ к диску → «+» → `Cmd+Shift+G` → путь из команды `realpath .venv/bin/python`.

**Сон Mac.** Когда Mac спит, бот не работает. Чтобы он не засыпал от зарядки:
Системные настройки → Аккумулятор → Параметры → включить «Предотвращать автоматический переход
в режим сна при подключении к сети, когда дисплей выключен». Закрытая крышка (без внешнего
монитора) всё равно усыпляет Mac.

## Перезапуск без доступа к Mac

- **Изменили `.env`** — бот сам перезапустится в течение ~30 секунд и применит настройки.
- **Файл `restart.flag`** в папке бота — перезапуск в течение ~30 секунд (файл удаляется сам).
- **Команда `/restart`** в Telegram — только для администратора (ADMIN_ID).

Во всех случаях бот сначала дожидается окончания текущих загрузок.

## Уведомления, кэш, автообновление

- **Уведомления:** любая ошибка уровня ERROR приходит администратору в Telegram
  (одинаковые — не чаще раза в 10 минут). Также бот сообщает о запуске и об обновлении yt-dlp.
- **Кэш:** отправленные видео запоминаются в `cache.db` — повторная ссылка (в том числе другая
  форма: youtu.be ↔ youtube.com, короткая ↔ полная TikTok) отправляется мгновенно.
- **Размер:** yt-dlp сначала узнаёт размер форматов и качает сразу лучшее качество, которое влезает в 50 МБ.
- **Автообновление:** раз в сутки бот обновляет yt-dlp и, если вышла новая версия, перезапускается
  (дождавшись окончания текущих загрузок). Отключить: `AUTO_UPDATE=false`.

## Cookies (Instagram и «подтвердите, что вы не бот» на YouTube)

Instagram часто отдаёт видео только авторизованным пользователям. Выгрузите cookies
из браузера, где вы залогинены:

```bash
yt-dlp --cookies-from-browser chrome --cookies cookies.txt --skip-download "https://www.instagram.com/"
```

и укажите в `.env`: `COOKIES_FILE=cookies.txt`. Файл содержит вашу сессию — никому его не передавайте.

## TikTok и другие заблокированные сайты

В Узбекистане TikTok заблокирован, поэтому с домашнего интернета yt-dlp получает
ошибку `SSL: UNEXPECTED_EOF_WHILE_READING`.

**По умолчанию бот качает TikTok через сервис tikwm.com** (`bot/tiktok.py`): он сам
забирает видео с TikTok и отдаёт его со своего домена, без водяного знака — VPN не нужен.
Если tikwm недоступен, бот пробует yt-dlp (с PROXY, если он задан). Другие варианты:

1. **VPN на весь Mac** (системный режим / TUN) — код менять не нужно.
2. **Прокси только для бота.** Многие VPN-клиенты (Hiddify, v2rayN, Clash, Outline и др.)
   поднимают локальный прокси. Посмотрите адрес в настройках клиента и впишите в `.env`:
   `PROXY=socks5://127.0.0.1:1080`. Через прокси пойдут все загрузки бота.
3. **VPS за границей** (см. Docker ниже) — прокси не нужен.

## Обновление yt-dlp

Сайты регулярно меняются, и старый yt-dlp перестаёт работать. Если бот начал падать на
ссылках, которые раньше работали, — первым делом обновите:

```bash
pip install -U "yt-dlp[default]"
```

## Запуск на VPS через Docker

```bash
docker build -t video-bot .
docker run -d --name video-bot --restart unless-stopped --env-file .env video-bot
```

Для cookies: `-v $(pwd)/cookies.txt:/app/cookies.txt` и `COOKIES_FILE=/app/cookies.txt`.
Обновление yt-dlp в Docker = пересборка образа (`docker build --no-cache ...`).
YouTube чаще блокирует IP дата-центров — на VPS cookies для YouTube почти обязательны.

## Ограничения

- Обычный Bot API принимает файлы до **50 МБ**. Бот пробует 720p → 480p → 360p; если не влезает — сообщает.
- Из карусели Instagram скачивается первое видео.
- Бот для личного использования: скачивайте контент, на который у вас есть права.
# video-downloader-bot
