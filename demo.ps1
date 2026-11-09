# demo.ps1 - Jalankan Pilgan Checker untuk demo lokal.
# Pemakaian:
#   .\demo.ps1
#   .\demo.ps1 -NoBrowser   (tanpa membuka browser otomatis)

param(
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Get-PythonPath {
    if (Test-Path -LiteralPath ".venv\Scripts\python.exe") {
        return (Resolve-Path -LiteralPath ".venv\Scripts\python.exe").Path
    }
    if (Test-Path -LiteralPath "venv\Scripts\python.exe") {
        return (Resolve-Path -LiteralPath "venv\Scripts\python.exe").Path
    }
    return "python"
}

function Test-PortOpen {
    param([int]$Port)

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect("127.0.0.1", $Port)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Find-FreePort {
    for ($port = 5000; $port -le 5010; $port++) {
        if (-not (Test-PortOpen -Port $port)) {
            return $port
        }
    }
    throw "Tidak ada port kosong di rentang 5000-5010."
}

$python = Get-PythonPath
$port = Find-FreePort
$url = "http://127.0.0.1:$port"

Write-Host ""
Write-Host "  Pilgan Checker - Demo Lokal" -ForegroundColor Magenta
Write-Host "  ===========================" -ForegroundColor DarkMagenta
Write-Host "  Python : $python"
Write-Host "  URL    : $url" -ForegroundColor Green
if ($env:APP_USERNAME -and $env:APP_PASSWORD) {
    Write-Host "  Login  : basic auth aktif ($env:APP_USERNAME)" -ForegroundColor Yellow
}
Write-Host "  Stop   : Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

$openJob = $null
if (-not $NoBrowser) {
    # Tunggu server benar-benar siap, lalu buka browser.
    $openJob = Start-Job -ScriptBlock {
        param($targetUrl)

        for ($i = 0; $i -lt 60; $i++) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $targetUrl -TimeoutSec 2
                if ($response.StatusCode -eq 200) {
                    Start-Process $targetUrl
                    return
                }
            }
            catch {
                Start-Sleep -Milliseconds 500
            }
        }
    } -ArgumentList $url
}

try {
    & $python -m flask --app app run --host 127.0.0.1 --port $port --no-reload
}
finally {
    if ($openJob) {
        Stop-Job -Job $openJob -ErrorAction SilentlyContinue
        Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue
    }
}
