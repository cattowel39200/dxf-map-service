# 개발 서버 실행. 최초 1회는 .venv를 만들고 의존성을 설치한다.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "가상환경을 만드는 중..." -ForegroundColor Cyan
    python -m venv .venv
    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env를 만들었습니다. VWORLD_KEY를 채운 뒤 다시 실행하세요." -ForegroundColor Yellow
}

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
