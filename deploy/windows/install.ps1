# Включает автозапуск бота через Планировщик задач Windows:
# старт при входе в систему, без окна, перезапуск после падения,
# проверка каждые 5 минут — если бот не работает, задача запускает его снова.
# Перед этим останавливает бота, запущенного вручную из этой папки.
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $VenvPy)) {
    Write-Host "[X] Не найден $VenvPy"
    Write-Host '    Сначала создайте .venv и установите зависимости (README -> «Запуск на Windows»).'
    exit 1
}
if (-not (Test-Path (Join-Path $Dir '.env'))) {
    Write-Host "[X] Нет файла .env в $Dir"
    exit 1
}

& $VenvPy -c 'import aiogram, yt_dlp, dotenv' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '[X] В .venv не установлены зависимости. Выполните в папке проекта:'
    Write-Host '    .venv\Scripts\python -m pip install -r requirements.txt'
    exit 1
}

Update-PathFromRegistry
foreach ($tool in 'ffmpeg', 'deno') {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "[!] Не найден $tool — без него часть видео не скачается (README -> «Запуск на Windows»)."
    }
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ((Stop-Bot) -gt 0) {
    Write-Host '[i] Остановлен уже запущенный бот'
    Start-Sleep -Seconds 2
}

$user      = "$env:USERDOMAIN\$env:USERNAME"
$action    = New-ScheduledTaskAction -Execute 'powershell.exe' `
             -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Runner`"" `
             -WorkingDirectory $Dir
# Второй триггер — каждые 5 минут: поднимает бота, если обёртку run.ps1 убили снаружи
# (RestartCount на это не срабатывает). Пока бот работает, IgnoreNew не даёт запустить дубль.
$trigger   = @(
    New-ScheduledTaskTrigger -AtLogOn -User $user
    New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
)
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -StartWhenAvailable -MultipleInstances IgnoreNew `
             -ExecutionTimeLimit ([TimeSpan]::Zero) `
             -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop `
        -Description 'PandaDownloader: Telegram-бот, автозапуск при входе в систему и проверка каждые 5 минут' | Out-Null
} catch {
    Write-Host "[X] Не удалось создать задачу: $($_.Exception.Message)"
    Write-Host '    Запустите «Запустить автозапуск.bat» правой кнопкой -> «Запуск от имени администратора».'
    exit 1
}

Start-ScheduledTask -TaskName $TaskName
Write-Host '[OK] Автозапуск установлен. Проверяю через 10 секунд...'
Start-Sleep -Seconds 10

$bots = @(Get-BotProcesses | Where-Object { $_.Name -like 'python*' })
if ($bots.Count -gt 0) {
    Write-Host "[OK] Бот работает (PID $($bots[0].ProcessId))."
    Write-Host '     Лог в реальном времени: Get-Content logs\bot.log -Wait -Tail 20 -Encoding UTF8'
} else {
    Write-Host '[X] Бот не запустился. Последние строки логов:'
    Show-LogTail 'stderr.log' 20
    Show-LogTail 'runner.log' 5
}
