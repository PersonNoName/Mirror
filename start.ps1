$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing required command: $Name"
    }
}

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') {
            return
        }
        $name, $value = $_ -split '=', 2
        [System.Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim())
    }
}

Require-Command "docker"
Require-Command "python"
Require-Command "uvicorn"

docker compose up -d | Out-Host

$opencodePort = if ($env:OPENCODE_PORT) { $env:OPENCODE_PORT } else { "4096" }
$appPort = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }
$opencodeProcess = $null

try {
    if (Get-Command "opencode" -ErrorAction SilentlyContinue) {
        $opencodeProcess = Start-Process -FilePath "opencode" -ArgumentList @("serve", "--port", $opencodePort) -PassThru
    }
    else {
        Write-Warning "'opencode' command not found; skipping local OpenCode startup."
    }

    uvicorn app.main:app --host 0.0.0.0 --port $appPort
}
finally {
    if ($null -ne $opencodeProcess -and -not $opencodeProcess.HasExited) {
        Stop-Process -Id $opencodeProcess.Id -Force
    }
}
