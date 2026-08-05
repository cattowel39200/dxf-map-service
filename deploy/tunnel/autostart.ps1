# =============================================================================
#  ks-down-map.com 자동 시작 등록
#
#  로그온할 때 두 가지를 띄운다.
#    KS Map API     127.0.0.1:8001 에서 도는 지적도 추출 서버
#    KS Map Tunnel  그 서버를 ks-down-map.com 으로 잇는 Cloudflare 터널
#
#  둘 다 죽으면 1분 뒤 최대 3번까지 다시 띄운다.
#
#      .\autostart.ps1            등록
#      .\autostart.ps1 -Status    상태 확인
#      .\autostart.ps1 -Remove    제거
# =============================================================================
param([switch]$Status, [switch]$Remove)

$ErrorActionPreference = "Stop"

$Project  = "C:\Users\vip\OneDrive\Music\dxf-map-service"
$Python   = Join-Path $Project ".venv\Scripts\python.exe"
$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$Config   = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
$Port     = 8001
$Site     = "https://ks-down-map.com"

$Tasks = @(
    @{
        Name = "KS Map API"
        Exec = $Python
        Args = "-m uvicorn app.main:app --host 127.0.0.1 --port $Port --workers 1"
        Work = $Project
        Desc = "지적도 DXF 추출 API 서버"
    },
    @{
        Name = "KS Map Tunnel"
        Exec = $Cloudflared
        Args = 'tunnel --config "' + $Config + '" run'
        Work = $env:USERPROFILE
        Desc = "ks-down-map.com Cloudflare 터널"
    }
)

function Line($t) { Write-Host "  $t" }

if ($Status) {
    Write-Host ""
    Write-Host "  ks-down-map.com 상태" -ForegroundColor Cyan
    Write-Host ("  " + ("-" * 52)) -ForegroundColor DarkGray
    foreach ($t in $Tasks) {
        $task = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($task) {
            $info = Get-ScheduledTaskInfo -TaskName $t.Name
            Line ("{0,-16} {1}  (마지막 실행 {2})" -f $t.Name, $task.State, $info.LastRunTime)
        } else {
            Line ("{0,-16} 미등록" -f $t.Name)
        }
    }
    Write-Host ""
    $local = try { (Invoke-WebRequest "http://127.0.0.1:$Port/api/config" -UseBasicParsing -TimeoutSec 8).StatusCode } catch { 0 }
    Line ("로컬 서버       " + $(if ($local -eq 200) { "정상" } else { "응답 없음" }))
    $pub = try { (Invoke-WebRequest "$Site/api/config" -UseBasicParsing -TimeoutSec 25).StatusCode } catch { 0 }
    Line ("공개 주소       " + $(if ($pub -eq 200) { "정상  $Site" } else { "응답 없음 (HTTP $pub)" }))
    Write-Host ""
    exit 0
}

if ($Remove) {
    Write-Host ""
    foreach ($t in $Tasks) {
        try {
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction Stop
            Line ("제거: " + $t.Name)
        } catch { Line ($t.Name + " 없음") }
    }
    Write-Host ""
    Write-Host "  터널과 DNS 레코드는 남아 있습니다. 완전히 지우려면:"
    Write-Host "    cloudflared tunnel delete ks-map"
    Write-Host ""
    exit 0
}

# ----------------------------------------------------------------- 등록
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "  관리자 권한으로 실행하세요." -ForegroundColor Red
    exit 1
}

foreach ($p in @($Python, $Cloudflared, $Config)) {
    if (-not (Test-Path $p)) {
        Write-Host "  찾을 수 없음: $p" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "  자동 시작 등록" -ForegroundColor Cyan
Write-Host ("  " + ("-" * 52)) -ForegroundColor DarkGray

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -Hidden
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

foreach ($t in $Tasks) {
    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $t.Exec -Argument $t.Args -WorkingDirectory $t.Work
    Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger `
        -Settings $settings -Description $t.Desc | Out-Null
    Line ("등록: {0,-16} {1}" -f $t.Name, $t.Desc)
}

Write-Host ""
foreach ($t in $Tasks) {
    Line ("{0,-16} {1}" -f $t.Name, (Get-ScheduledTask -TaskName $t.Name).State)
}

Write-Host ""
Write-Host "  이제 이 계정으로 로그온하면 자동으로 뜹니다."
Write-Host "  상태 확인  .\autostart.ps1 -Status"
Write-Host "  제거       .\autostart.ps1 -Remove"
Write-Host ""
