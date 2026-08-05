# 발급키·구매 신청이 든 usage.db 를 날마다 복사해 둔다. 14벌을 넘으면 지운다.
$root = Split-Path $PSScriptRoot -Parent
$src = Join-Path $root "data\usage.db"
$dir = Join-Path $root "data\backup"
if (-not (Test-Path $src)) { exit }
New-Item -ItemType Directory -Force $dir | Out-Null
Copy-Item $src (Join-Path $dir ("usage-{0}.db" -f (Get-Date -Format "yyyyMMdd"))) -Force
Get-ChildItem $dir -Filter "usage-*.db" | Sort-Object Name -Descending |
    Select-Object -Skip 14 | Remove-Item -Force
