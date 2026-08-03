# 지적도·지형도 DXF 추출 서비스

지도에서 영역을 드래그하고 좌표계를 고르면 지적도와 지형도를 DXF로 내려받는 웹서비스.

## 빠른 시작

```powershell
.\run.ps1
```

최초 실행 시 `.venv`를 만들고 의존성을 설치한 뒤 `.env`를 생성한다.
`.env`의 `VWORLD_KEY`를 채우고 다시 실행한 다음 <http://localhost:8000> 을 연다.

인증키는 [vworld.kr](https://www.vworld.kr) → 오픈API에서 무료로 발급하며,
발급 시 **활용 URL에 `http://localhost:8000`을 등록**해야 배경지도 타일이 나온다.

`.env`에는 값이 두 개 필요하다.

```
VWORLD_KEY=발급받은키
VWORLD_DOMAIN=localhost
```

`VWORLD_DOMAIN`을 빼먹으면 배경지도는 나오지만 지적 레이어만 `인증키 정보가
올바르지 않습니다`로 거부된다. Data API가 인증키와 함께 호출 도메인을 검사하는데,
브라우저가 아니라 서버에서 부르면 Referer가 없어 이 값을 명시해야 하기 때문이다.
배포 후에는 인증키에 등록한 실제 도메인으로 바꾼다.

## 인터넷에 공개하기

무료로 올릴 수 있다. Hugging Face Spaces 는 토큰만 있으면 한 줄로 끝난다.

```powershell
.\.venv\Scripts\python.exe deploy\deploy_hf.py --token hf_토큰
```

Render 를 쓰려면 대시보드에서 **New → Blueprint** 로 이 저장소를 고르면
[render.yaml](render.yaml) 대로 만들어진다. 자세한 절차와 두 방식의 차이는
[deploy/README.md](deploy/README.md).

배포 후에는 **vworld.kr 인증키의 활용 URL 에 배포 주소를 추가**해야 한다.
등록하지 않으면 배경지도와 지적 레이어가 나오지 않는다.

## 데이터 출처

| 레이어 | 출처 | 인증키 |
|---|---|---|
| 필지 경계, 지번·지목 | V-World 연속지적도 `LP_PA_CBND_BUBUN` | 필요 |
| 등고선 (우선) | **국토지리정보원 수치표고모델** — `dem/` 폴더의 파일 | 불필요 |
| 등고선 (대비책) | AWS Terrain Tiles(terrarium) → 마칭스퀘어 | 불필요 |
| 건물, 도로, 하천 | OpenStreetMap Overpass | 불필요 |
| 배경지도 | V-World WMTS(일반/위성/백지도) | 필요 |

### 등고선 자료를 국토지리정보원 것으로 바꾸려면

국토정보플랫폼은 **오픈API를 제공하지 않는다.** 로그인 후 도엽 단위로 내려받는 방식뿐이고
(IMG 형식, 무료, 이용허락 제한 없음), V-World의 355개 레이어에도 등고선은 없다.
그래서 한 번 받아 둔 파일을 자동으로 인식해 쓰도록 만들었다.

<https://map.ngii.go.kr> → 국토정보map → 자료받기 → 영역 지정 → **수치표고모델(DEM)**
을 받아 압축을 풀고 `.img` 파일을 `dem/` 폴더에 넣으면 끝이다. 서버를 켜 둔 채라면
`POST /api/dem/rescan`으로 다시 훑는다. 자세한 절차는 [dem/README.md](dem/README.md).

파일이 있는 지역은 그것을, 없는 지역은 전지구 자료를 쓰고, **어느 쪽을 썼는지 추출 결과
화면과 작업 응답에 격자 간격·표고 단위까지 표시한다.** GDAL이 읽는 래스터는 모두 지원한다
(`.img` `.tif` `.asc` `.adf` `.bil` `.vrt`).

**등고선 정밀도 — 전지구 자료를 쓸 때**: 실측 결과 위도 37도 z13에서 격자 간격은
**15.2 m × 15.0 m**이고 표고값은 **1 m 단위로 양자화**되어 있다(고유값 전부 정수).
국내 주요 봉우리와 대조하면 암반 정상에서 13~25 m 깎인다(백운대 -23.5, 자운봉 -25.5,
연주대 -13.2). 완만한 수목지는 잘 맞는다(남산 +1.1).

축척으로 치면 1:25,000 수준이라 1:5,000 수치지형도를 대체하지 못한다. 이 상태에서
1 m·2 m 간격을 고르면 지형이 아니라 격자 계단이 그려지므로, 요청한 간격이 자료의
표고 분해능보다 촘촘하면 작업 응답에 경고를 실어 보낸다.

`dem/` 폴더에 국토지리정보원 5 m DEM을 넣으면 표고가 연속값이 되어 1~2 m 간격 등고선이
의미를 갖는다. 같은 영역을 비교하면 5 m DEM은 33개의 긴 연속선(정점 4,259개)을 그리는
반면, 전지구 자료는 양자화 탓에 74개로 조각난 선(정점 2,972개)이 된다.

## 좌표계

| 좌표계 | EPSG |
|---|---|
| 중부 / 서부 / 동부 / 동해원점 (세계측지계) | 5186 / 5185 / 5187 / 5188 |
| UTM-K 단일원점 | 5179 |
| 중부원점 구 지적 (Bessel) | 5174 |
| UTM Zone 52N | 32652 |
| WGS84 경위도 | 4326 |

변환은 pyproj가 EPSG 등록 정의를 그대로 쓴다. 브라우저 상태바의 실시간 좌표는
proj4js로 즉시 계산한 근사값이고, 선택 영역 모서리처럼 확정값으로 보여 주는 숫자는
`/api/project`로 서버에 물어 파일과 동일한 변환을 거친다. 구 지적(5174)은
두 정의가 1 m 안팎 어긋날 수 있어 나눈 것이다.

## DXF 레이어

| 레이어 | 내용 | ACI |
|---|---|---|
| `D-PARCEL` | 필지 경계 (폐합 폴리라인) | 1 |
| `D-PNU-TEXT` | 지번·지목 (필지 중심 TEXT) | 7 |
| `T-CONTOUR` | 등고선 주곡선 | 33 |
| `T-CONTOUR-INDEX` | 등고선 계곡선 (간격의 5배) | 32 |
| `T-BLDG` | 건물 | 8 |
| `T-ROAD` | 도로 경계 | 2 |
| `T-WATER` | 하천·수계 | 5 |
| `A-REF` | 기준점 십자·방위표 | 4 |

한글 지번은 `HANGUL` 문자 스타일(맑은 고딕)로 쓴다. DXF는 글꼴 파일명만 저장하므로
맑은 고딕이 없는 환경에서 열면 CAD가 대체 글꼴로 표시한다.

출력 설정: DXF 버전(R12~2018), 도면 단위(m/mm), 지번 문자 높이, 등고선 간격,
등고선 Z값 부여, 좌하단 (0,0) 이동, 기준점·방위표 삽입.

## AutoCAD에서 바로 쓰기

브라우저를 거치지 않고 AutoCAD 안에서 영역을 지정해 받을 수 있다.
아래를 한 번 실행하면 AutoCAD를 켤 때마다 자동으로 불러온다.

```powershell
cd cad
.\install.ps1
```

`%APPDATA%\Autodesk\ApplicationPlugins`에 번들로 등록하는 방식이라 최근 버전의
SECURELOAD 보안 설정에 걸리지 않는다. `-List`로 상태 확인, `-Uninstall`로 제거한다.
그때그때 쓰려면 `APPLOAD`로 [cad/CADMAP.lsp](cad/CADMAP.lsp)를 불러도 된다.

등록되는 명령은 셋이다.

| 명령 | 하는 일 |
|---|---|
| `지적도` (DXFMAP) | 두 점으로 영역 지정 → 서버 요청 → 현재 도면에 삽입 |
| `지도설정` (MAPCFG) | 좌표계 · 레이어 · 등고선간격 · 서버 주소 |
| `좌표` (PTLABEL) | 클릭한 점에 X·Y 좌표 기입 |

받은 도면은 실제 좌표에 놓이므로 기존 도면과 바로 겹쳐 쓸 수 있다.
자세한 사용법과 문제 해결은 [cad/README.md](cad/README.md).

리습은 도면 좌표(TM)를 그대로 보내므로 `POST /api/jobs`가 `bbox_crs`를 받는다.
이 값이 있으면 bbox를 경위도가 아니라 해당 좌표계의 평면 좌표로 해석한다.

## 구조

```
app/
  main.py       FastAPI 라우트 · V-World 타일 중계
  jobs.py       작업 큐 (진행률 폴링)
  crs.py        좌표계 정의와 변환
  geom.py       면적 계산 · 폴리곤/폴리라인 클리핑
  contour.py    표고 격자 → 등고선
  dxfgen.py     ezdxf 조립
  sources/      vworld.py · local_dem.py · dem.py · osm.py
web/            OpenLayers 프론트엔드
cad/            AutoCAD 리습 (CADMAP.lsp)
dem/            국토지리정보원 수치표고모델을 넣는 곳
```

인증키는 브라우저로 나가지 않는다. 배경지도 타일과 필지 조회를 모두 서버가 중계한다.

## API

| 엔드포인트 | 용도 |
|---|---|
| `GET /api/config` | 좌표계 목록·한도·인증키 유무 |
| `GET /api/tiles/{layer}/{z}/{y}/{x}` | V-World WMTS 중계 |
| `GET /api/parcels?bbox=` | 지도 미리보기용 필지 GeoJSON |
| `GET /api/project?lon=&lat=&crs=` | 단일 점 확정 좌표 |
| `POST /api/jobs` | 추출 작업 생성 (202). `bbox_crs`로 도면 좌표 입력 가능 |
| `POST /api/dem/rescan` | `dem/` 폴더 다시 훑기 |
| `GET /api/jobs/{id}` | 진행 상태 |
| `GET /api/jobs/{id}/download` | DXF 내려받기 |

## 점검

```powershell
.\.venv\Scripts\python.exe selftest.py --live
```

좌표계 변환을 국토지리정보원 공표 성과(서울시청·부산시청)와 대조하고,
클리핑·DXF 생성(3개 버전 × 3개 좌표계)·표고 조회·OSM 조회를 확인한다.

서버를 띄운 상태에서 실제 작업 한 건을 끝까지 돌리려면:

```powershell
.\.venv\Scripts\python.exe e2e.py 8000
```

생성된 DXF를 눈으로 확인하려면 `python preview.py e2e_download.dxf preview.svg`.

## 알려진 제약

- **속도**: 0.7 km² 기준 약 70초. 대부분 Overpass 공용 서버 대기 시간이다. 건물·도로를
  끄면 20초 안쪽으로 떨어진다. 운영에서는 OSM 데이터를 자체 PostGIS에 적재하는 편이 낫다.
- **Overpass 불안정**: 공용 인스턴스가 붐비면 504를 낸다. 미러 3곳을 순서대로 시도하고,
  모두 실패해도 지적·등고선은 정상 출력한 뒤 결과 화면에 누락을 알린다.
- **작업 저장소가 메모리**: 단일 프로세스 전용이다. 워커를 늘리려면 Redis + RQ로 교체한다.
- **1회 추출 한도 1 km²**: `.env`의 `MAX_AREA_KM2`로 조정한다.
- **필지가 많은 도심**: 0.7 km² 시가지에서 필지 1,300여 개, 지번 텍스트까지 합쳐
  약 2 MB가 나온다. 지번을 끄면 절반으로 줄어든다.

## 법적 고지

연속지적도는 참고용 도면으로 **법적 측량 성과가 아니다**. 경계 확정에는
지적측량(LX 한국국토정보공사)이 필요하다. V-World 데이터 재배포는 이용약관을 확인할 것.
