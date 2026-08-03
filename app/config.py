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
#
# 쉼표로 여러 개를 적으면 순서대로 시도한다. 배포 도메인을 vworld.kr에 등록하기
# 전에도 localhost로 계속 동작하고, 등록한 뒤에는 첫 값이 바로 통과한다.
VWORLD_DOMAINS = [d.strip() for d in
                  os.getenv("VWORLD_DOMAIN", "localhost").split(",") if d.strip()]
VWORLD_DOMAIN = VWORLD_DOMAINS[0] if VWORLD_DOMAINS else "localhost"

# 1회 추출 면적 상한
MAX_AREA_KM2 = float(os.getenv("MAX_AREA_KM2", "1.0"))

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", ROOT / "output"))
OUTPUT_TTL_HOURS = float(os.getenv("OUTPUT_TTL_HOURS", "24"))

# 워커가 하나이고 작업 상태를 메모리에 두므로 동시 처리량을 제한한다.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))

# V-World Data API — 연속지적도(부번). 1회 최대 1000건이라 페이징한다.
VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_PAGE_SIZE = 1000
VWORLD_MAX_PAGES = 40

# V-World WMTS 타일 (배경지도). 키를 노출하지 않도록 백엔드에서 중계한다.
VWORLD_TILE_URL = "https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{ext}"



HTTP_TIMEOUT = 60.0
USER_AGENT = "dxf-map-service/1.0 (cadastral DXF extractor)"
