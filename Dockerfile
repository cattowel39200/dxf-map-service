# 지적도·지형도 DXF 추출 서비스
#
# rasterio / pyproj 는 manylinux 휠에 GDAL·PROJ 바이너리가 들어 있어
# 별도 시스템 패키지를 깔 필요가 없다. slim 이미지로 충분하다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/
COPY dem/README.md ./dem/README.md

# 산출물과 표고자료 위치. 호스팅에서 디스크를 붙이면 여기에 마운트한다.
RUN mkdir -p /app/output /app/dem
ENV OUTPUT_DIR=/app/output \
    DEM_DIR=/app/dem

# Hugging Face Spaces 기본 포트. Render·Fly 등은 PORT 를 주입한다.
ENV PORT=7860
EXPOSE 7860

# 작업 상태를 메모리에 두므로 워커는 반드시 하나여야 한다.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
