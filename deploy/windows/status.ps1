# Статус бота и последние строки логов.
. (Join-Path $PSScriptRoot 'common.ps1')

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Автозапуск:        установлен (задача $TaskName, состояние: $($task.State))"
    Write-Host "Последний запуск:  $($info.LastRunTime)"
} else {
    Write-Host 'Автозапуск:        не установлен (запустите «Запустить автозапуск.bat»)'
}

$bots = @(Get-BotProcesses | Where-Object { $_.Name -like 'python*' })
if ($bots.Count -gt 0) {
    Write-Host "Бот:               работает (PID $(($bots | ForEach-Object { $_.ProcessId }) -join ', '))"
} else {
    Write-Host 'Бот:               не запущен'
}

Write-Host ''
Show-LogTail 'bot.log' 15
Show-LogTail 'stderr.log' 10
Show-LogTail 'runner.log' 5
