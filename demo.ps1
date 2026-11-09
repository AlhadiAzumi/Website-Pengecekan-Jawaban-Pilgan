# demo.ps1 - Jalankan Pilgan Checker untuk demo lokal atau dari HP (LAN).
# Pemakaian:
#   .\demo.ps1                      (laptop saja, localhost)
#   .\demo.ps1 -NoBrowser           (tanpa membuka browser otomatis)
#   .\demo.ps1 -Lan                 (bisa dibuka dari HP di Wi-Fi yang sama)
#   .\demo.ps1 -Lan -OpenFirewall   (buat aturan firewall, butuh admin)

param(
    [switch]$NoBrowser,
    [switch]$Lan,
    [switch]$OpenFirewall
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

function Test-PortAvailable {
    param([int]$Port)

    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Port)
    try {
        $listener.Start()
        return $true
    }
    catch {
        return $false
    }
    finally {
        try { $listener.Stop() } catch { }
    }
}

function Find-FreePort {
    for ($port = 5000; $port -le 5010; $port++) {
        if (Test-PortAvailable -Port $port) {
            return $port
        }
    }
    throw "Tidak ada port kosong di rentang 5000-5010."
}

function Get-LanTargets {
    # Utamakan adapter fisik yang punya gateway default (Wi-Fi/Ethernet),
    # supaya IP virtual (Hyper-V/WSL/VirtualBox) tidak membingungkan.
    $virtualPattern = "VirtualBox|VMware|Hyper-V|vEthernet|WSL|Loopback|Bluetooth|Tailscale|ZeroTier|TAP-|Tunnel"
    $targets = @()
    $fallback = @()

    foreach ($cfg in (Get-NetIPConfiguration -ErrorAction SilentlyContinue)) {
        if (-not $cfg.IPv4Address) { continue }
        $status = $null
        if ($cfg.NetAdapter) { $status = $cfg.NetAdapter.Status }
        if ($status -and $status -ne "Up") { continue }

        $isVirtual = ($cfg.InterfaceDescription -match $virtualPattern) -or ($cfg.InterfaceAlias -match $virtualPattern)
        $hasGateway = [bool]$cfg.IPv4DefaultGateway
        foreach ($ip in $cfg.IPv4Address.IPAddress) {
            if ($ip -match "^(127\.|169\.254\.)" -or $ip -eq "0.0.0.0") { continue }
            $item = [pscustomobject]@{
                IP         = $ip
                Alias      = $cfg.InterfaceAlias
                HasGateway = $hasGateway
            }
            if ($isVirtual) { $fallback += $item } else { $targets += $item }
        }
    }

    if (-not $targets) { $targets = $fallback }

    if (-not $targets) {
        foreach ($ip in (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress) {
            if ($ip -match "^(127\.|169\.254\.)" -or $ip -eq "0.0.0.0") { continue }
            $targets += [pscustomobject]@{ IP = $ip; Alias = "Network"; HasGateway = $false }
        }
    }

    return @($targets | Sort-Object -Property @{ Expression = { if ($_.HasGateway) { 0 } else { 1 } } }, Alias)
}

$python = Get-PythonPath
$port = Find-FreePort
$localUrl = "http://127.0.0.1:$port"
$bindHost = if ($Lan) { "0.0.0.0" } else { "127.0.0.1" }
$mode = if ($Lan) { "Demo LAN - bisa dibuka dari HP" } else { "Demo Lokal" }

if ($Lan -and $OpenFirewall) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "  Firewall: -OpenFirewall butuh PowerShell sebagai Administrator." -ForegroundColor Yellow
    }
    else {
        Get-NetFirewallRule -DisplayName "Pilgan Checker Demo*" -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction SilentlyContinue
        New-NetFirewallRule -DisplayName "Pilgan Checker Demo (port $port)" `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port `
            -Profile Any | Out-Null
        Write-Host "  Firewall: aturan inbound port $port dibuat (semua profil jaringan)." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "  Pilgan Checker - $mode" -ForegroundColor Magenta
Write-Host "  ===============================================" -ForegroundColor DarkMagenta
Write-Host "  Python : $python"
Write-Host "  Laptop : $localUrl" -ForegroundColor Green

if ($Lan) {
    $lanTargets = @(Get-LanTargets)
    if ($lanTargets.Count -eq 0) {
        Write-Host "  HP     : IP LAN tidak terdeteksi" -ForegroundColor Yellow
        Write-Host "           Pastikan laptop terhubung ke Wi-Fi/LAN." -ForegroundColor DarkGray
    }
    else {
        $primary = $lanTargets[0]
        Write-Host "  HP     : http://$($primary.IP):$port  ($($primary.Alias))" -ForegroundColor Green
        foreach ($extra in @($lanTargets | Select-Object -Skip 1)) {
            Write-Host "           http://$($extra.IP):$port  ($($extra.Alias))" -ForegroundColor DarkGray
        }
        if (-not $primary.HasGateway) {
            Write-Host "           IP utama tanpa gateway default; coba alamat lain di atas." -ForegroundColor DarkGray
        }
    }

    if (-not $OpenFirewall) {
        Write-Host "  Firewall: jika HP tidak bisa connect, jalankan .\demo.ps1 -Lan -OpenFirewall sebagai Admin." -ForegroundColor DarkGray
    }
}

Write-Host "  Login  : aktif - buat akun admin saat halaman pertama kali dibuka." -ForegroundColor Yellow
if ($Lan) {
    Write-Host "           Siapa pun di Wi-Fi yang sama akan diminta login." -ForegroundColor DarkGray
}

Write-Host "  Stop   : Ctrl+C" -ForegroundColor DarkGray
Write-Host ""

$openJob = $null
if (-not $NoBrowser) {
    # Tunggu server benar-benar siap, lalu buka browser di laptop.
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
    } -ArgumentList $localUrl
}

try {
    & $python -m flask --app app run --host $bindHost --port $port --no-reload
}
finally {
    if ($openJob) {
        Stop-Job -Job $openJob -ErrorAction SilentlyContinue
        Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue
    }
}
