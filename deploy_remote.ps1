<#
.SYNOPSIS
    One-click deploy of squad-radio from Windows to the remote node.

.DESCRIPTION
    Thin wrapper around scripts/deploy_node.sh with safe defaults for this setup:

      * KEEP_TOKEN=1 by default. The local .env.token is the TEST bot ("jiliangguan"),
        while the remote node runs a DIFFERENT bot. Use -WithToken only when you
        deliberately want to replace the remote token.

      * SSH_PROXY defaults to socks5h://127.0.0.1:14455. The direct route to the
        node drops packets; the local mixed proxy is the working path.

    Actions: deploy (default), status, logs, restart.

.PARAMETER Action
    deploy | status | logs | restart

.PARAMETER WithToken
    Overwrite the remote token with the local .env.token (off by default).

.PARAMETER Proxy
    Override SSH_PROXY, e.g. socks5h://127.0.0.1:7890

.PARAMETER NoProxy
    Connect directly, ignore SSH_PROXY.

.PARAMETER BashPath
    Explicit path to bash.exe if auto-detection fails.

.EXAMPLE
    .\deploy_remote.ps1                  # deploy, keep remote token, via proxy
    .\deploy_remote.ps1 -Action status
    .\deploy_remote.ps1 -Action logs
    .\deploy_remote.ps1 -WithToken       # deliberately replace remote bot token

.NOTES
    Double-click deploy_remote.cmd for the same effect without typing commands.
    Run git push first if you want the remote to use the latest GitHub code.
#>
[CmdletBinding()]
param(
    [ValidateSet('deploy', 'status', 'logs', 'restart')]
    [string] $Action = 'deploy',
    [switch] $WithToken,
    [string] $Proxy,
    [switch] $NoProxy,
    [string] $BashPath
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Say($m)  { Write-Host "[remote] $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[remote] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[remote] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[remote] $m" -ForegroundColor Red; exit 1 }

# ---- 1. Locate Git Bash (deploy_node.sh is a bash script) ----
# Explicit Git-for-Windows locations FIRST: Get-Command may return the WSL shim
# at ...\WindowsApps\bash.exe, which is NOT Git Bash and cannot run this script.
if (-not $BashPath) {
    $explicit = @(
        "$env:ProgramFiles\Git\bin\bash.exe",
        "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
        "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe",
        "$env:ProgramFiles\Git\usr\bin\bash.exe"
    )
    $BashPath = $explicit | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $BashPath) {
    $found = Get-Command bash.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -and $_.Source -notmatch 'WindowsApps' }
    if ($found) { $BashPath = $found.Source }
}
if (-not $BashPath -or -not (Test-Path -LiteralPath $BashPath)) {
    Fail "Git Bash not found. Install Git for Windows, or pass -BashPath 'C:\path\to\bash.exe'."
}
$script = Join-Path $PSScriptRoot 'scripts\deploy_node.sh'
if (-not (Test-Path -LiteralPath $script)) { Fail "missing scripts/deploy_node.sh" }
Ok "Git Bash: $BashPath"

# ---- 2. Proxy (direct route to the node is unreliable) ----
$proxyUrl = if ($Proxy) { $Proxy } else { 'socks5h://127.0.0.1:14455' }
if ($NoProxy) {
    $env:SSH_PROXY = ''
    Warn 'SSH_PROXY disabled - connecting directly'
} else {
    $env:SSH_PROXY = $proxyUrl
    $m = [regex]::Match($proxyUrl, '://(?:[^@/]+@)?([^:/]+):(\d+)')
    if ($m.Success) {
        $ph = $m.Groups[1].Value
        $pp = [int]$m.Groups[2].Value
        $client = New-Object Net.Sockets.TcpClient
        $reachable = $false
        try {
            $iar = $client.BeginConnect($ph, $pp, $null, $null)
            $reachable = $iar.AsyncWaitHandle.WaitOne(1500)
            if ($reachable) { $client.EndConnect($iar) }
        } catch { } finally { $client.Close() }
        if (-not $reachable) {
            Fail "proxy $ph`:$pp unreachable. Start your local proxy, pass -Proxy <url>, or use -NoProxy."
        }
        Ok "proxy reachable: $ph`:$pp"
    }
}

# ---- 3. Token safety ----
if ($WithToken) {
    $env:KEEP_TOKEN = '0'
    Warn 'WithToken set: local .env.token WILL overwrite the remote bot token.'
} else {
    $env:KEEP_TOKEN = '1'
    Ok 'KEEP_TOKEN=1: remote bot token will be preserved.'
}

# ---- 4. Run deploy_node.sh inside Git Bash ----
# deploy_node.sh spawns the SSH proxy via `command -v python3`, but in a bare
# Git Bash launched from PowerShell that resolves to the WindowsApps shim
# (a WSL stub) and the proxy dies silently -> "SSH unreachable". Pin PY_BIN to
# the project venv python, expressed as a Git-Bash-style path.
$venvPyWin = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPyWin) {
    $env:PY_BIN = ($venvPyWin -replace '\\', '/') -replace '^([A-Za-z]):', '/$1'
} else {
    Warn '.venv python not found; deploy_node.sh will fall back to PATH python.'
}

$dir = $PSScriptRoot -replace '\\', '/'
$cmdLine = "cd '$dir' && bash scripts/deploy_node.sh $Action"
Say "running: $Action"
& $BashPath --noprofile --norc -c $cmdLine
$code = $LASTEXITCODE
if ($code -ne 0) { Fail "deploy_node.sh exited with code $code" }
Ok "done: $Action"
