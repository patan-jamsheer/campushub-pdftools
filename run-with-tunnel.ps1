# Starts the PDF Tools compression service and a public HTTPS tunnel, then prints the address to paste into the app.
#
#   powershell -ExecutionPolicy Bypass -File .\run-with-tunnel.ps1
#
# The tunnel is a free Cloudflare quick tunnel: no account, no signup. Its address changes every time this script is
# restarted, which is why the app has an editable "Compression server" address instead of a hardcoded one.
#
# Close this window (or press Ctrl+C) to stop everything.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host 'Python is not installed or not on PATH.' -ForegroundColor Red
    exit 1
}

$cloudflared = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $cloudflared) {
    foreach ($candidate in @(
            'C:\Program Files (x86)\cloudflared\cloudflared.exe',
            'C:\Program Files\cloudflared\cloudflared.exe')) {
        if (Test-Path $candidate) { $cloudflared = $candidate; break }
    }
}
if (-not $cloudflared) {
    Write-Host 'cloudflared is not installed. Install it with:' -ForegroundColor Red
    Write-Host '  winget install --id Cloudflare.cloudflared -e'
    exit 1
}

Write-Host 'Checking Python dependencies...' -ForegroundColor Cyan
python -c "import flask, pymupdf" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing requirements...'
    python -m pip install -r requirements.txt
}

Write-Host 'Starting the compression service on port 5000...' -ForegroundColor Cyan
$server = Start-Process -FilePath python -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot -PassThru -WindowStyle Minimized

try {
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod 'http://localhost:5000/api/health' -TimeoutSec 3 | Out-Null
            $ready = $true
            break
        } catch { }
    }
    if (-not $ready) {
        throw 'The service did not start. Run "python app.py" in this folder to see the error.'
    }
    Write-Host 'Service is up.' -ForegroundColor Green

    Write-Host 'Opening the public tunnel...' -ForegroundColor Cyan
    $log = Join-Path $env:TEMP 'pdftools-tunnel.log'
    if (Test-Path $log) { Remove-Item $log -Force }
    $tunnel = Start-Process -FilePath $cloudflared `
        -ArgumentList 'tunnel', '--url', 'http://localhost:5000', '--no-autoupdate' `
        -RedirectStandardError $log -RedirectStandardOutput (Join-Path $env:TEMP 'pdftools-tunnel-out.log') `
        -PassThru -WindowStyle Hidden

    $url = $null
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Path $log) {
            $found = Select-String -Path $log -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -AllMatches
            if ($found) { $url = $found.Matches[0].Value; break }
        }
    }
    if (-not $url) {
        throw "The tunnel did not report an address. Check $log"
    }

    Write-Host ''
    Write-Host 'Ready.' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Open PDF Tools -> Compress PDF -> Compression server -> Change' -ForegroundColor White
    Write-Host '  and paste this address:' -ForegroundColor White
    Write-Host ''
    Write-Host "    $url" -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'The app remembers it. If you restart this script the address changes,' -ForegroundColor DarkGray
    Write-Host 'so paste the new one (no APK rebuild needed).' -ForegroundColor DarkGray
    Write-Host ''
    Write-Host 'Press Ctrl+C to stop the service and the tunnel.' -ForegroundColor DarkGray

    while ($true) {
        Start-Sleep -Seconds 5
        if ($server.HasExited) { throw 'The compression service stopped.' }
        if ($tunnel.HasExited) { throw 'The tunnel stopped.' }
    }
}
finally {
    foreach ($p in @($server, $tunnel)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host 'Stopped.' -ForegroundColor DarkGray
}
