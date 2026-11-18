<#
.SYNOPSIS
    One-command deploy / operate for the Squad Radio KOOK bot on Windows.

.DESCRIPTION
    Deploys the bot as a background service in one go:
      1. locates (or creates) the local virtual environment
      2. verifies dependencies, installing them if missing
      3. resolves the KOOK token (env var, .env.token, or prompts once)
      4. stops any instance already running, so there is only one
      5. starts a hidden background process
      6. waits for the health endpoint, so "started" really means "online"

    Operational switches are included, so this single file is all you need:
      -Status / -Stop / -Restart / -Logs / -Foreground
      -InstallAutoStart / -UninstallAutoStart  (run at user logon)

.PARAMETER HealthPort
    Local health-check port. Default 18082. Use 0 to disable the probe.

.PARAMETER MaxLogMb
    Total size cap for the logs directory, in MB. Default 50.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Status
    .\deploy.ps1 -Restart
    .\deploy.ps1 -Logs
    .\deploy.ps1 -Stop
    .\deploy.ps1 -Foreground
    .\deploy.ps1 -InstallAutoStart

.NOTES
    If the execution policy blocks this script, run:
      powershell -ExecutionPolicy Bypass -File .\deploy.ps1
#>
[CmdletBinding()]
param(
    [switch] $Status,
    [switch] $Stop,
    [switch] $Restart,
    [switch] $Logs,
    [switch] $Foreground,
    [switch] $InstallAutoStart,
    [switch] $UninstallAutoStart,
    [int]    $HealthPort = 18082,
    [int]    $MaxLogMb  = 50
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$Root      = $PSScriptRoot
$Python    = Join-Path $Root ".venv\Scripts\python.exe"
$TokenFile = Join-Path $Root ".env.token"
$LogDir    = Join-Path $Root "logs"
$DataDir   = Join-Path $Root "data"
$TaskName  = "SquadRadio"
$HealthUrl = "http://127.0.0.1:$HealthPort/healthz"

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "OK  $text" -ForegroundColor Green }
function Write-Note($text) { Write-Host "!   $text" -ForegroundColor Yellow }

# Find bot processes by command line; this also catches the venv launcher pair.
function Get-BotProcesses {
    @(
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine -match 'squad_radio\.cli\s+kook-bot' }
    )
}

function Get-Health {
    try { return Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 2 } catch { return $null }
}

function Get-LatestLog {
    Get-ChildItem -LiteralPath $LogDir -Filter "squad-radio_*.log" -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
}

function Show-LogTail([int] $Lines = 30) {
    $file = Get-LatestLog
    if (-not $file) {
        Write-Note "No log file yet under $LogDir"
        return
    }
    Write-Host "--- $($file.Name) (last $Lines lines) ---"
    Get-Content -LiteralPath $file.FullName -Tail $Lines -Encoding UTF8
}

# Start-Process joins a string[] with spaces and does NOT quote the items, so a
# project path containing spaces (e.g. "Program Files (x86)") would be split
# into separate arguments. Quote anything that needs it before handing over.
function ConvertTo-ArgString([string[]] $items) {
    ($items | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join ' '
}

function Ensure-Python {
    if (Test-Path -LiteralPath $Python) { return }
    Write-Step "Virtual environment missing, creating .venv ..."
    $sys = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sys) { throw "Python was not found on PATH. Install Python 3.11+ first." }
    & $sys.Source -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
        throw "Failed to create .venv"
    }
    Write-Ok ".venv created"
}

function Ensure-Deps {
    Write-Step "Checking dependencies ..."
    & $Python -c "import squad_radio, websocket"
    if ($LASTEXITCODE -eq 0) { Write-Ok "dependencies ready"; return }

    Write-Step "Installing from requirements.txt ..."
    & $Python -m pip install -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    & $Python -c "import squad_radio, websocket"
    if ($LASTEXITCODE -ne 0) { throw "Dependencies still not importable after install" }
    Write-Ok "dependencies installed"
}

# The background process is given --token-file, so a file is always required.
function Ensure-TokenFile {
    if (Test-Path -LiteralPath $TokenFile) {
        $existing = (Get-Content -LiteralPath $TokenFile -Raw -Encoding UTF8).Trim()
        if ($existing) { return }
    }
    if ($env:KOOK_TOKEN) {
        [IO.File]::WriteAllText(
            $TokenFile,
            $env:KOOK_TOKEN.Trim(),
            (New-Object System.Text.UTF8Encoding($false))
        )
        Write-Ok "token taken from KOOK_TOKEN and saved to .env.token"
        return
    }

    Write-Note "No KOOK token found (.env.token missing, KOOK_TOKEN unset)."
    $secure = Read-Host -AsSecureString "Paste your KOOK bot token (input hidden)"
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if (-not $plain -or -not $plain.Trim()) { throw "Empty token, aborting." }

    [IO.File]::WriteAllText(
        $TokenFile,
        $plain.Trim(),
        (New-Object System.Text.UTF8Encoding($false))
    )
    try {
        icacls $TokenFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    } catch {
        Write-Note "Could not tighten file ACL, but the file is git-ignored."
    }
    Write-Ok "token saved to .env.token (git-ignored)"
}

function Stop-Bot {
    $procs = Get-BotProcesses
    if (-not $procs) { return 0 }
    Write-Step "Stopping $($procs.Count) running instance(s) ..."
    $procs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 700
    $left = Get-BotProcesses
    if ($left) { throw "Failed to stop PID $($left.ProcessId -join ', ')" }
    return $procs.Count
}

# ---------------------------------------------------------------- dispatch ---

if ($UninstallAutoStart) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok "logon auto-start removed (task '$TaskName')"
    return
}

if ($InstallAutoStart) {
    Ensure-Python
    Ensure-Deps
    Ensure-TokenFile
    $arg = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$PSCommandPath`" -HealthPort $HealthPort -MaxLogMb $MaxLogMb"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Description "Squad Radio KOOK bot (auto start at logon)" -Force | Out-Null
    Write-Ok "logon auto-start registered (task '$TaskName')"
    Write-Host "     The bot now starts by itself whenever you log in."
    return
}

if ($Logs) {
    Show-LogTail 40
    return
}

if ($Stop) {
    $count = Stop-Bot
    if ($count -eq 0) { Write-Note "bot is not running" } else { Write-Ok "bot stopped ($count process(es))" }
    return
}

if ($Status) {
    $procs = Get-BotProcesses
    if (-not $procs) {
        Write-Note "bot is NOT running"
        exit 1
    }
    Write-Host "Process : PID $($procs.ProcessId -join ', ')"
    $health = Get-Health
    if ($health) {
        Write-Host "Health  : $HealthUrl"
        Write-Host ("Status  : {0}  connected={1}  uptime={2}s  replies={3}  reconnects={4}" -f `
            $health.status, $health.connected, [int]$health.uptime_seconds, $health.replies_sent, $health.reconnects)
    } else {
        Write-Note "health endpoint not reachable on port $HealthPort"
    }
    $file = Get-LatestLog
    if ($file) {
        Write-Host ("Log     : {0} ({1} KB)" -f $file.Name, [math]::Round($file.Length / 1KB))
    }
    return
}

# ------------------------------------------------------- deploy / restart ---

Ensure-Python
Ensure-Deps
Ensure-TokenFile
New-Item -ItemType Directory -Force -Path $LogDir, $DataDir | Out-Null

# A fresh deploy and an explicit -Restart behave the same: stop, then start.
$null = Stop-Bot

$botArgs = @(
    "-m", "squad_radio.cli", "kook-bot",
    "--token-file", $TokenFile,
    "--password-cache", (Join-Path $DataDir "password_cache.json"),
    "--state-file", (Join-Path $DataDir "kook_bot_state.json"),
    "--log-dir", $LogDir,
    "--max-log-mb", "$MaxLogMb"
)
if ($HealthPort -gt 0) { $botArgs += @("--health-port", "$HealthPort") }

if ($Foreground) {
    Write-Step "Running in the foreground (Ctrl+C to stop) ..."
    $fgArgs = $botArgs + @("--log-console", "on")
    & $Python @fgArgs
    return
}

Write-Step "Starting bot in the background ..."
$bgArgs = $botArgs + @("--log-console", "off")
$argLine = ConvertTo-ArgString $bgArgs
# Note: no -RedirectStandard* here on purpose. On some machines the environment
# holds both HTTPS_PROXY and https_proxy, which makes PowerShell 5.1 throw a
# duplicate-key error while preparing the redirect. The bot writes its own log
# file anyway, so stdout/stderr capture is not needed.
$proc = Start-Process -FilePath $Python -ArgumentList $argLine -WorkingDirectory $Root `
    -WindowStyle Hidden -PassThru

if ($HealthPort -gt 0) {
    Write-Step "Waiting for the KOOK connection on port $HealthPort ..."
    $health = $null
    $sawEndpoint = $false
    $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 800
        $probe = Get-Health
        if ($probe) {
            $sawEndpoint = $true
            $health = $probe
            if ($probe.connected -eq $true) { break }
        }
        $exited = $false
        try { $exited = $proc.HasExited } catch { }
        if ($exited) { break }
    }

    if (-not ($health -and $health.connected -eq $true)) {
        if ($sawEndpoint) {
            Write-Note "health endpoint is up but KOOK is not connected yet (status=$($health.status))"
            Write-Note "the bot keeps retrying in the background - check '.\deploy.ps1 -Logs' in a minute"
        } else {
            Write-Note "bot did not come up within 40s"
            Show-LogTail 30
            Write-Note "If no new log file appeared, run '.\deploy.ps1 -Foreground' to read the error."
            exit 1
        }
    } else {
        Write-Ok "bot is online (launcher PID $($proc.Id))"
        Write-Host ("     status={0}  connected={1}  uptime={2}s" -f `
            $health.status, $health.connected, [int]$health.uptime_seconds)
    }
} else {
    Start-Sleep -Seconds 3
    $exited = $false
    try { $exited = $proc.HasExited } catch { }
    if ($exited) {
        Write-Note "bot exited right after start"
        Show-LogTail 30
        exit 1
    }
    Write-Ok "bot started (launcher PID $($proc.Id)), health probe disabled"
}

$logFile = Get-LatestLog
if ($logFile) { Write-Host "     log   : $($logFile.FullName)" }
Write-Host "`nManage it with: .\deploy.ps1 -Status | -Logs | -Stop | -Restart | -InstallAutoStart"
