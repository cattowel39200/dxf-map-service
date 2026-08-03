# 지적도 DXF 추출 서비스
#
# 의존성이 전부 순수 파이썬이거나 manylinux 휠이라 별도 시스템 패키지가
# 필요 없다. slim 이미지로 충분하다.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY web/ ./web/

# 산출물 위치. 호스팅에서 디스크를 붙이면 여기에 마운트한다.
RUN mkdir -p /app/output
ENV OUTPUT_DIR=/app/output

# Hugging Face Spaces 기본 포트. Render·Fly 등은 PORT 를 주입한다.
ENV PORT=7860
EXPOSE 7860

# 작업 상태를 메모리에 두므로 워커는 반드시 하나여야 한다.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
