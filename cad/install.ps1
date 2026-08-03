# =============================================================================
#  CADMAP 설치 스크립트
#
#  AutoCAD가 켜질 때 CADMAP.lsp를 자동으로 불러오도록 등록한다.
#  ApplicationPlugins 폴더는 AutoCAD가 기본으로 신뢰하는 위치라
#  SECURELOAD 보안 설정에 걸리지 않는다.
#
#      .\install.ps1              설치
#      .\install.ps1 -Uninstall   제거
#      .\install.ps1 -List        설치 상태 확인
# =============================================================================
param(
    [switch]$Uninstall,
    [switch]$List
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BundleName = "CADMAP.bundle"
$PluginRoot = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins"
$Bundle     = Join-Path $PluginRoot $BundleName
$Contents   = Join-Path $Bundle "Contents"
$Installed  = Join-Path $Contents "CADMAP.lsp"
$Source     = Join-Path $PSScriptRoot "CADMAP.lsp"

function Write-Head($t) {
    Write-Host ""
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("  " + ("-" * 56)) -ForegroundColor DarkGray
}

# ----------------------------------------------------------------- 상태 확인
if ($List) {
    Write-Head "CADMAP 설치 상태"
    if (Test-Path $Installed) {
        $f = Get-Item $Installed
        Write-Host "  설치됨" -ForegroundColor Green
        Write-Host "    위치   : $Installed"
        Write-Host "    크기   : $($f.Length) bytes"
        Write-Host "    수정일 : $($f.LastWriteTime)"
        if (Test-Path $Source) {
            $s = Get-Item $Source
            if ($s.LastWriteTime -gt $f.LastWriteTime) {
                Write-Host "    원본이 더 최신입니다. 다시 설치하세요." -ForegroundColor Yellow
            }
        }
    } else {
        Write-Host "  설치되지 않았습니다." -ForegroundColor Yellow
        Write-Host "    .\install.ps1 을 실행하세요."
    }
    Write-Host ""
    exit 0
}

# ----------------------------------------------------------------- 제거
if ($Uninstall) {
    Write-Head "CADMAP 제거"
    if (Test-Path $Bundle) {
        Remove-Item $Bundle -Recurse -Force
        Write-Host "  제거했습니다: $Bundle" -ForegroundColor Green
        Write-Host "  AutoCAD를 다시 켜면 반영됩니다."
    } else {
        Write-Host "  설치되어 있지 않습니다." -ForegroundColor Yellow
    }
    Write-Host ""
    exit 0
}

# ----------------------------------------------------------------- 설치
Write-Head "CADMAP 설치"

if (-not (Test-Path $Source)) {
    Write-Host "  CADMAP.lsp를 찾을 수 없습니다: $Source" -ForegroundColor Red
    Write-Host "  이 스크립트는 CADMAP.lsp와 같은 폴더에서 실행해야 합니다."
    exit 1
}

New-Item -ItemType Directory -Force $Contents | Out-Null
Copy-Item $Source $Installed -Force

$xml = @'
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0"
                    AppVersion="1.0.0"
                    ProductType="Application"
                    Name="CADMAP"
                    Description="지적도 / 지형도 DXF 가져오기"
                    Author="dxf-map-service">
  <CompanyDetails Name="dxf-map-service" />
  <Components>
    <RuntimeRequirements OS="Win32|Win64" Platform="AutoCAD*" />
    <ComponentEntry AppName="CADMAP"
                    Version="1.0.0"
                    ModuleName="./Contents/CADMAP.lsp"
                    AppType="LISP"
                    LoadOnAutoCADStartup="True" />
  </Components>
</ApplicationPackage>
'@

# AutoCAD는 이 파일을 UTF-8로 읽는다. BOM 없이 저장한다.
[System.IO.File]::WriteAllText(
    (Join-Path $Bundle "PackageContents.xml"),
    $xml,
    (New-Object System.Text.UTF8Encoding($false)))

Write-Host "  설치 완료" -ForegroundColor Green
Write-Host "    $Installed"
Write-Host ""

$running = Get-Process acad -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "  AutoCAD가 실행 중입니다." -ForegroundColor Yellow
    Write-Host "  다시 켜면 자동으로 불러옵니다. 지금 바로 쓰려면 명령행에 붙여넣으세요:"
} else {
    Write-Host "  AutoCAD를 켜면 자동으로 불러옵니다."
    Write-Host "  이미 켜 둔 상태라면 명령행에 아래를 붙여넣으세요:"
}

$lispPath = $Installed -replace '\\', '/'
Write-Host ""
Write-Host "    (load `"$lispPath`")" -ForegroundColor White
Write-Host ""
Write-Host "  등록되는 명령어" -ForegroundColor Cyan
Write-Host "    지적도    영역을 지정해 지적도/지형도 가져오기"
Write-Host "    지도설정  좌표계 / 레이어 / 서버 주소 설정"
Write-Host "    좌표      클릭한 점의 좌표를 도면에 기입"
Write-Host ""
Write-Host "  서버가 켜져 있어야 합니다. 상위 폴더에서 run.ps1 실행."
Write-Host ""
