# 1분마다 예약 작업이 이 파일을 돌린다. 점검하고 곧바로 끝난다.
# 오래 도는 감시 프로세스는 저도 모르게 죽을 수 있음이 드러나(2026-08-06),
# 매번 새로 뜨는 방식으로 바꿨다. 이 파일이 안 돌면 예약 작업 문제다.
$root = Split-Path $PSScriptRoot -Parent

# 1) 서버
$up = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if (-not $up) {
    Start-Process -FilePath "$root\.venv\Scripts\python.exe" `
        -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8001","--workers","1" `
        -WorkingDirectory $root -WindowStyle Hidden
}

# 2) 터널
if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "C:\Program Files (x86)\cloudflared\cloudflared.exe" `
        -ArgumentList "tunnel","--config","$env:USERPROFILE/.cloudflared/config.yml","run" `
        -WindowStyle Hidden
}
