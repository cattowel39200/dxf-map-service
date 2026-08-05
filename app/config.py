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

# 사용 기록 데이터베이스. 산출물과 달리 오래 남긴다.
USAGE_DB = Path(os.getenv("USAGE_DB", ROOT / "data" / "usage.db"))

# 관리자 대시보드(/admin) 접근 암호. 비워 두면 대시보드가 열리지 않는다.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# 메일 발송. 지메일은 앱 비밀번호를 써야 한다(계정 비밀번호로는 거부된다).
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "지적도 DXF 추출")

# 정품 안내에 표시할 입금 계좌
BANK_INFO = os.getenv("BANK_INFO", "")
# 데모 사용 기간(일). 첫 사용 시점부터 센다.
DEMO_DAYS = int(os.getenv("DEMO_DAYS", "3"))

SITE_URL = os.getenv("SITE_URL", "https://ks-down-map.com")

# 워커가 하나이고 작업 상태를 메모리에 두므로 동시 처리량을 제한한다.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "3"))

# V-World Data API — 연속지적도(부번). 1회 최대 1000건이라 페이징한다.
VWORLD_DATA_URL = "https://api.vworld.kr/req/data"
VWORLD_PAGE_SIZE = 1000
VWORLD_MAX_PAGES = 40

# V-World WMTS 타일 (배경지도).
VWORLD_TILE_URL = "https://api.vworld.kr/req/wmts/1.0.0/{key}/{layer}/{z}/{y}/{x}.{ext}"

# 배경지도를 브라우저가 V-World에서 직접 받게 할지 여부.
#   1 (기본) 브라우저 → V-World 직결. 타일 장당 약 17 ms. 대신 인증키가
#            프론트엔드에 노출된다. 키는 도메인에 묶여 있어 다른 사이트에서는
#            배경지도가 뜨지 않는다.
#   0        서버가 중계. 키는 감춰지지만 Cloudflare를 한 번 더 거쳐 약 57 ms.
# 어느 쪽이든 지적 데이터 조회(Data API)는 항상 서버가 대신 한다.
TILE_DIRECT = os.getenv("TILE_DIRECT", "1") == "1"



HTTP_TIMEOUT = 60.0
USER_AGENT = "dxf-map-service/1.0 (cadastral DXF extractor)"
