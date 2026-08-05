# Cloudflare 터널. 죽으면 5초 뒤 다시 잇는다.
$ErrorActionPreference = "Continue"
$exe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"

while ($true) {
    $up = Get-Process cloudflared -ErrorAction SilentlyContinue
    if (-not $up) {
        & $exe tunnel --config "$env:USERPROFILE/.cloudflared/config.yml" run
    }
    Start-Sleep -Seconds 5
}
