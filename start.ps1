<#
.SYNOPSIS
    Quick start the Squad Radio KOOK listener.

.DESCRIPTION
    Locates the local virtual environment, loads the KOOK bot token from
    .env.token (git-ignored) or the KOOK_TOKEN environment variable, then
    starts the always-on "today's password" listener.

    Use -CheckOnly to verify the environment without starting the bot.

.EXAMPLE
    .\start.ps1
    .\start.ps1 -CheckOnly
    powershell -ExecutionPolicy Bypass -File .\start.ps1
#>
[CmdletBinding()]
param(
    [string] $PasswordCache = "",
    [string] $StateFile = "",
    [switch] $CheckOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

# --- Locate Python ---
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment not found at $python. Create it with: python -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}

# --- Load token (never hardcode it) ---
$tokenFile = Join-Path $PSScriptRoot ".env.token"
if (-not $env:KOOK_TOKEN -and (Test-Path -LiteralPath $tokenFile)) {
    $env:KOOK_TOKEN = (Get-Content -LiteralPath $tokenFile -Raw -Encoding UTF8).Trim()
}
if (-not $env:KOOK_TOKEN) {
    throw "No KOOK token found. Put your token in .env.token (git-ignored) or set KOOK_TOKEN before running."
}

# --- Resolve runtime paths ---
if (-not $PasswordCache) { $PasswordCache = Join-Path $PSScriptRoot "data\password_cache.json" }
if (-not $StateFile) { $StateFile = Join-Path $PSScriptRoot "data\kook_bot_state.json" }

if ($CheckOnly) {
    Write-Host "OK: virtual environment and token found." -ForegroundColor Green
    Write-Host "Python : $python"
    Write-Host "Cache  : $PasswordCache"
    Write-Host "State  : $StateFile"
    return
}

Write-Host "Starting Squad Radio KOOK listener..." -ForegroundColor Green
& $python -m squad_radio.cli kook-bot `
    --password-cache $PasswordCache `
    --state-file $StateFile
