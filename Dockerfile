FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIANXI_DATA=/app/data PIANXI_COOKIE_DIR=/app/data/cookies \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
WORKDIR /app
COPY requirements-platform-lock.txt ./
RUN pip install --no-cache-dir -r requirements-platform-lock.txt \
    && python -m playwright install --with-deps chromium \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home pianxi \
    && mkdir -p /app/data/cookies && chown -R pianxi:pianxi /app/data /opt/playwright
COPY backend/ ./backend/
COPY scripts/*.py ./scripts/
COPY --from=frontend /build/dist ./frontend/dist/
COPY deploy/entrypoint.sh /usr/local/bin/pianxi-entrypoint
RUN sed -i 's/\r$//' /usr/local/bin/pianxi-entrypoint && chmod +x /usr/local/bin/pianxi-entrypoint
USER pianxi
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8765/').status == 200"
ENTRYPOINT ["pianxi-entrypoint"]
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
