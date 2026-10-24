# Общие настройки и функции для скриптов автозапуска на Windows.
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$TaskName = 'PandaDownloaderBot'
$Dir      = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$VenvPy   = Join-Path $Dir '.venv\Scripts\python.exe'
$Runner   = Join-Path $PSScriptRoot 'run.ps1'
$LogDir   = Join-Path $Dir 'logs'

function Update-PathFromRegistry {
    # PATH из реестра: ffmpeg/deno могли установить после открытия окна
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Get-BotProcesses {
    # Обёртка run.ps1 из этой папки и python main.py, запущенный из .venv этой папки
    $prefix = $Dir + '\'
    Get-CimInstance Win32_Process | Where-Object {
        $_.ProcessId -ne $PID -and $_.CommandLine -and (
            ($_.Name -match '^(powershell|pwsh)\.exe$' -and
             $_.CommandLine.IndexOf($Runner, [StringComparison]::OrdinalIgnoreCase) -ge 0) -or
            ($_.Name -match '^pythonw?\.exe$' -and $_.CommandLine -match 'main\.py' -and
             $_.ExecutablePath -and $_.ExecutablePath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase))
        )
    }
}

function Stop-Bot {
    # Останавливает бота вместе с дочерними процессами
    # (python из .venv запускает основной интерпретатор дочерним процессом).
    $all   = @(Get-CimInstance Win32_Process)
    $roots = @(Get-BotProcesses)
    $ids   = New-Object 'System.Collections.Generic.HashSet[int]'
    $queue = New-Object 'System.Collections.Generic.Queue[int]'
    foreach ($r in $roots) {
        if ($ids.Add([int]$r.ProcessId)) { $queue.Enqueue([int]$r.ProcessId) }
    }
    while ($queue.Count -gt 0) {
        $id = $queue.Dequeue()
        foreach ($c in ($all | Where-Object { $_.ParentProcessId -eq $id })) {
            if ($ids.Add([int]$c.ProcessId)) { $queue.Enqueue([int]$c.ProcessId) }
        }
    }
    foreach ($id in $ids) {
        if ($id -ne $PID) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
    }
    return $roots.Count
}

function Show-LogTail([string]$Name, [int]$Lines = 15) {
    $path = Join-Path $LogDir $Name
    if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) {
        Write-Host "--- logs\$Name ---"
        Get-Content -Path $path -Tail $Lines -Encoding UTF8
    }
}
