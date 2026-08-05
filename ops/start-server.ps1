# 운영 서버. 재부팅 후 로그온하면 예약 작업이 이것을 돌린다.
# 이미 떠 있으면 그대로 두고, 죽으면 5초 뒤 다시 띄운다.
$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

while ($true) {
    $up = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
    if (-not $up) {
        & "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app `
            --host 127.0.0.1 --port 8001 --workers 1
        # 여기 왔다는 것은 서버가 죽었다는 뜻이다
    }
    Start-Sleep -Seconds 5
}
