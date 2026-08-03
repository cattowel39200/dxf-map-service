# =============================================================================
#  Cloudflare Tunnel 설정
#
#  이 PC에서 도는 서비스를 회사 도메인으로 인터넷에 공개한다.
#  포트포워딩도 공인IP도 필요 없고, HTTPS 인증서는 Cloudflare가 알아서 붙인다.
#
#      .\setup.ps1                     설정 (관리자 권한 필요)
#      .\setup.ps1 -Status             상태 확인
#      .\setup.ps1 -Remove             제거
#
#  미리 해 둘 것:  cloudflared tunnel login  으로 도메인 승인
# =============================================================================
param(
    [string]$Hostname = "map.kyoungsungeng.com",
    [string]$TunnelName = "dxf-map",
    [int]$Port = 8000,
    [switch]$Status,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$CF        = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$CfDir     = Join-Path $env:USERPROFILE ".cloudflared"
$ConfigPath= Join-Path $CfDir "config.yml"
$Project   = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$TaskName  = "DXF Map Service"

function Head($t) {
    Write-Host ""
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("  " + ("-" * 58)) -ForegroundColor DarkGray
}
function Ok($t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [주의] $t" -ForegroundColor Yellow }
function Bad($t)  { Write-Host "  [실패] $t" -ForegroundColor Red }

if (-not (Test-Path $CF)) {
    Bad "cloudflared가 없습니다. winget install Cloudflare.cloudflared"
    exit 1
}

# ----------------------------------------------------------------- 상태 확인
if ($Status) {
    Head "Cloudflare Tunnel 상태"

    if (Test-Path (Join-Path $CfDir "cert.pem")) { Ok "Cloudflare 인증됨" }
    else { Warn "인증 안 됨 - cloudflared tunnel login 필요" }

    $list = & $CF tunnel list 2>&1 | Out-String
    if ($list -match [regex]::Escape($TunnelName)) { Ok "터널 '$TunnelName' 있음" }
    else { Warn "터널 '$TunnelName' 없음" }

    if (Test-Path $ConfigPath) { Ok "설정 파일 $ConfigPath" }
    else { Warn "설정 파일 없음" }

    $svc = Get-Service cloudflared -ErrorAction SilentlyContinue
    if ($svc) { Ok "cloudflared 서비스: $($svc.Status)" }
    else { Warn "cloudflared 서비스 미등록" }

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) { Ok "API 서버 자동시작: $($task.State)" }
    else { Warn "API 서버 자동시작 미등록" }

    $local = try { (Invoke-WebRequest "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 8).StatusCode } catch { 0 }
    if ($local -eq 200) { Ok "로컬 서버 응답 정상 (127.0.0.1:$Port)" }
    else { Warn "로컬 서버 응답 없음 - 서버가 꺼져 있습니다" }

    Write-Host ""
    $pub = try { (Invoke-WebRequest "https://$Hostname/api/config" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { 0 }
    if ($pub -eq 200) { Ok "공개 주소 접속 정상  https://$Hostname" }
    else { Warn "공개 주소 응답 없음 (DNS 전파에 1~2분 걸릴 수 있음)" }
    Write-Host ""
    exit 0
}

# ----------------------------------------------------------------- 제거
if ($Remove) {
    Head "제거"
    try { & $CF service uninstall 2>&1 | Out-Null; Ok "cloudflared 서비스 제거" } catch { Warn "서비스 제거 실패" }
    try {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
        Ok "API 서버 자동시작 제거"
    } catch { Warn "자동시작 작업 없음" }
    Write-Host ""
    Write-Host "  터널 자체와 DNS 레코드는 남아 있습니다. 완전히 지우려면:"
    Write-Host "    cloudflared tunnel delete $TunnelName"
    Write-Host "    Cloudflare 대시보드에서 $Hostname CNAME 삭제"
    Write-Host ""
    exit 0
}

# ----------------------------------------------------------------- 설정
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Bad "관리자 권한으로 실행하세요. (PowerShell 우클릭 - 관리자 권한으로 실행)"
    exit 1
}

Head "Cloudflare Tunnel 설정"
Write-Host "  공개 주소   https://$Hostname"
Write-Host "  터널 이름   $TunnelName"
Write-Host "  연결 대상   http://127.0.0.1:$Port"
Write-Host "  프로젝트    $Project"

# 1. 인증 확인
Head "1. Cloudflare 인증"
if (-not (Test-Path (Join-Path $CfDir "cert.pem"))) {
    Bad "인증이 안 되어 있습니다."
    Write-Host ""
    Write-Host "    cloudflared tunnel login" -ForegroundColor White
    Write-Host ""
    Write-Host "  위 명령을 실행하고 브라우저에서 kyoungsungeng.com 을 승인한 뒤"
    Write-Host "  이 스크립트를 다시 실행하세요."
    exit 1
}
Ok "인증됨"

# 2. 터널 생성
Head "2. 터널"
$list = & $CF tunnel list 2>&1 | Out-String
if ($list -match [regex]::Escape($TunnelName)) {
    Ok "이미 있는 터널을 씁니다"
} else {
    & $CF tunnel create $TunnelName 2>&1 | Out-String | Write-Host
    if ($LASTEXITCODE -ne 0) { Bad "터널 생성 실패"; exit 1 }
    Ok "터널 생성됨"
}

$cred = Get-ChildItem $CfDir -Filter "*.json" |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $cred) { Bad "터널 자격증명 파일을 찾지 못했습니다"; exit 1 }
$TunnelId = $cred.BaseName
Ok "터널 ID $TunnelId"

# 3. DNS 연결
Head "3. DNS 레코드"
$dns = & $CF tunnel route dns --overwrite-dns $TunnelName $Hostname 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) { Ok "$Hostname -> 터널" }
else {
    if ($dns -match "already exists|record with that host") { Ok "이미 연결되어 있습니다" }
    else { Bad "DNS 설정 실패"; Write-Host $dns; exit 1 }
}

# 4. 설정 파일
Head "4. 설정 파일"
$yml = @"
# 지적도 DXF 서비스 터널 설정
tunnel: $TunnelId
credentials-file: $($cred.FullName)

# 접속을 로컬 서버로 넘긴다. 서버는 127.0.0.1 에만 열려 있어
# 이 터널을 통하지 않으면 외부에서 닿을 수 없다.
ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:$Port
    originRequest:
      # DXF 생성이 최대 3분 걸린다. 기본 30초로는 끊긴다.
      connectTimeout: 30s
      noHappyEyeballs: true
  - service: http_status:404
"@
[System.IO.File]::WriteAllText($ConfigPath, $yml,
    (New-Object System.Text.UTF8Encoding($false)))
Ok $ConfigPath

# 5. API 서버 자동 시작
Head "5. API 서버 자동 시작"
$py = Join-Path $Project ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Bad "가상환경이 없습니다: $py"; exit 1 }

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $py `
    -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1" `
    -WorkingDirectory $Project
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Hidden
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "지적도 DXF 추출 서비스 API" | Out-Null
Ok "로그온 시 자동 실행 등록"

# 이미 떠 있지 않으면 지금 띄운다
$alive = try { (Invoke-WebRequest "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }
if ($alive -ne 200) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 8
    $alive = try { (Invoke-WebRequest "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 8).StatusCode } catch { 0 }
}
if ($alive -eq 200) { Ok "로컬 서버 응답 정상" } else { Warn "로컬 서버가 아직 응답하지 않습니다" }

# 6. 터널 서비스 등록
Head "6. 터널 서비스"
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) {
    Stop-Service cloudflared -Force -ErrorAction SilentlyContinue
    & $CF service uninstall 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}
& $CF --config $ConfigPath service install 2>&1 | Out-String | Write-Host
Start-Sleep -Seconds 3
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne "Running") { Start-Service cloudflared; Start-Sleep -Seconds 4 }
    Set-Service cloudflared -StartupType Automatic
    Ok "서비스 등록 및 시작 ($((Get-Service cloudflared).Status))"
} else {
    Bad "서비스 등록 실패"
    exit 1
}

# 7. 확인
Head "7. 공개 주소 확인"
Write-Host "  DNS 전파를 기다리는 중..."
$pub = 0
for ($i = 1; $i -le 10; $i++) {
    Start-Sleep -Seconds 6
    $pub = try { (Invoke-WebRequest "https://$Hostname/api/config" -UseBasicParsing -TimeoutSec 15).StatusCode } catch { 0 }
    if ($pub -eq 200) { break }
    Write-Host "    ... $i"
}

Write-Host ""
Write-Host ("  " + ("=" * 58)) -ForegroundColor Cyan
if ($pub -eq 200) {
    Write-Host "   공개 완료   https://$Hostname" -ForegroundColor Green
} else {
    Write-Host "   설정은 끝났지만 아직 응답이 없습니다" -ForegroundColor Yellow
    Write-Host "   1~2분 뒤 .\setup.ps1 -Status 로 다시 확인하세요"
}
Write-Host ("  " + ("=" * 58)) -ForegroundColor Cyan

Write-Host ""
Write-Host "  ★ 남은 일 - V-World 인증키에 도메인 등록" -ForegroundColor Yellow
Write-Host "     vworld.kr - 마이페이지 - 인증키 관리 - 활용 URL 에"
Write-Host "     https://$Hostname  추가"
Write-Host "     그리고 .env 의 VWORLD_DOMAIN 을 $Hostname 으로 바꾸고"
Write-Host "     작업 스케줄러에서 'DXF Map Service' 를 다시 시작"
Write-Host ""
Write-Host "  상태 확인   .\setup.ps1 -Status"
Write-Host "  제거        .\setup.ps1 -Remove"
Write-Host ""
