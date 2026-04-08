# ─────────────────────────────────────────────────────────────
# Stage 1 — Dependency resolver (build cache layer)
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# 시스템 패키지 최소화
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# requirements만 먼저 복사 → pip 레이어 캐싱 극대화
COPY requirements.txt .

# wheel로 빌드해 다음 스테이지에서 재설치 없이 복사 가능하게
RUN pip install --upgrade pip --no-cache-dir \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt


# ─────────────────────────────────────────────────────────────
# Stage 2 — Runtime image (최종 경량 이미지)
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# 보안: root 아닌 전용 유저 사용
RUN groupadd -r appuser && useradd -r -g appuser appuser

# 실행 환경 최소 패키지
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# builder 스테이지에서 설치된 패키지만 복사
COPY --from=builder /install /usr/local

# 애플리케이션 소스 복사
COPY --chown=appuser:appuser main.py         ./main.py
COPY --chown=appuser:appuser variants.json   ./variants.json
COPY --chown=appuser:appuser templates/      ./templates/

# 환경 변수
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# 비-root 유저로 전환
USER appuser

EXPOSE 8000

# 헬스체크 — /health 엔드포인트 활용
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# 프로덕션 실행: workers=2 (PID 계열 조정 가능)
CMD ["python", "-m", "uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]
