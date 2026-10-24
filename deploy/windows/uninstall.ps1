# Отключает автозапуск бота и останавливает его.
. (Join-Path $PSScriptRoot 'common.ps1')

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ((Stop-Bot) -gt 0) { Write-Host '[OK] Бот остановлен' } else { Write-Host '[i] Бот не был запущен' }

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host '[OK] Автозапуск удалён'
} else {
    Write-Host '[i] Автозапуск не был установлен'
}
