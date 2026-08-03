"""서비스 설정. 값은 .env 또는 환경변수로 덮어쓴다."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# vworld.kr 에서 무료 발급. 인증키 없이는 지적 레이어를 받을 수 없다.
VWORLD_KEY = os.getenv("VWORLD_KEY", "")

# Data API는 인증키와 함께 호출 도메인을 검사한다. 서버에서 부르면 Referer가 없어
# 이 값을 명시해야 하며, 인증키 신청 시 등록한 서비스 URL과 맞아야 한다.
VWORLD_DOMAIN = os.getenv("VWORLD_DOMAIN", "localhost")

# 1회 추출 면적 상한
MAX_AREA_KM2 = float(os.getenv("MAX_AREA_KM2", "1.0"))

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT / "output"))
OUTPUT_TTL_HOURS = float(os.getenv("OUTPUT_TTL_HOURS", "24"))

# V-World Data API — 연속지적도(부번). 1회 최대 1000건이라 페이징한다.
VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_PAGE_SIZE = 1000
VWORLD_MAX_PAGES = 40

# V-World WMTS 타일 (배경지도). 키를 노출하지 않도록 백엔드에서 중계한다.
VWORLD_TILE_URL = "https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{ext}"

# 국토지리정보원 수치표고모델을 넣어 두는 곳. 국토정보플랫폼에서 내려받은 파일을
# 여기 복사해 두면 해당 지역 요청에서 AWS 대신 자동으로 쓴다.
DEM_DIR = Path(os.getenv("DEM_DIR", ROOT / "dem"))

# 좌표계 정보가 없는 배포본용 기본값. 국토지리정보원 DEM은 보통 중부원점이다.
DEM_FALLBACK_CRS = os.getenv("DEM_FALLBACK_CRS", "EPSG:5186")

# AWS Terrain Tiles — 인증키 불필요, 전지구 커버리지, terrarium PNG 인코딩.
# 로컬 DEM이 없는 지역의 대비책이다. 실측 격자 15 m, 표고는 1 m 단위 양자화.
DEM_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DEM_ZOOM = 13

# Overpass 공용 인스턴스는 자주 붐벼 504를 낸다. 순서대로 시도한다.
OVERPASS_URLS = [u.strip() for u in os.getenv("OVERPASS_URL", "").split(",") if u.strip()] or [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

HTTP_TIMEOUT = 60.0
USER_AGENT = "dxf-map-service/1.0 (cadastral+terrain DXF extractor)"
