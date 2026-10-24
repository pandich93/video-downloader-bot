# Обёртка для автозапуска: держит бота запущенным (её запускает Планировщик задач).
# Код выхода 75 — бот сам попросил перезапуск (обновился yt-dlp, изменён .env, команда /restart).
# Любой другой код — сбой: ждём 15 секунд и запускаем снова.
$ErrorActionPreference = 'Continue'

$Dir    = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Py     = Join-Path $Dir '.venv\Scripts\python.exe'
$LogDir = Join-Path $Dir 'logs'
$RunLog = Join-Path $LogDir 'runner.log'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Без дублей: задача проверяет бота каждые 5 минут. Если он уже работает из этой папки
# (запущен вручную или второй обёрткой), второй экземпляр поймал бы конфликт в Telegram — выходим.
. (Join-Path $PSScriptRoot 'common.ps1')
if (@(Get-BotProcesses).Count -gt 0) { exit 0 }

$RESTART_EXIT_CODE = 75

$env:BOT_SUPERVISED   = '1'   # бот знает, что его перезапустит обёртка
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8       = '1'   # ошибки Python в stderr.log — в UTF-8, без кракозябр

function Write-RunLog([string]$Message) {
    # Лог обёртки не растёт бесконечно: больше 1 МБ — оставляем последние 500 строк
    if ((Test-Path $RunLog) -and (Get-Item $RunLog).Length -gt 1MB) {
        $tail = Get-Content -Path $RunLog -Tail 500 -Encoding UTF8
        Set-Content -Path $RunLog -Value $tail -Encoding UTF8
    }
    Add-Content -Path $RunLog -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message" -Encoding UTF8
}

while ($true) {
    # PATH перечитываем при каждом запуске: ffmpeg/deno могли установить уже после входа в систему
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')

    if (-not (Test-Path $Py)) {
        Write-RunLog "не найден $Py — создайте .venv (README → Windows). Повтор через 60 сек"
        Start-Sleep -Seconds 60
        continue
    }

    Write-RunLog 'старт бота'
    $p = Start-Process -FilePath $Py -ArgumentList 'main.py' -WorkingDirectory $Dir `
         -NoNewWindow -PassThru `
         -RedirectStandardOutput (Join-Path $LogDir 'stdout.log') `
         -RedirectStandardError  (Join-Path $LogDir 'stderr.log')
    $null = $p.Handle   # без этого PowerShell иногда теряет код выхода
    $p.WaitForExit()
    $code = $p.ExitCode

    if ($code -eq $RESTART_EXIT_CODE) {
        Write-RunLog 'перезапуск по запросу бота'
        Start-Sleep -Seconds 2
    } else {
        Write-RunLog "бот завершился с кодом $code — перезапуск через 15 сек (подробности в logs\stderr.log)"
        Start-Sleep -Seconds 15
    }
}
