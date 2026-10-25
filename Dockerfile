# Build a fully local React/CSS/chart bundle. No third-party script CDN.
FROM node:22-alpine AS frontend-builder
WORKDIR /app
COPY frontend /app/frontend
COPY unibacktest /app/unibacktest
RUN cd /app/frontend && npm install --no-audit --no-fund && npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app/
COPY unibacktest /app/unibacktest
COPY --from=frontend-builder /app/unibacktest/static/app /app/unibacktest/static/app
COPY examples /app/examples
RUN pip install --no-cache-dir -e '.[all]'
RUN mkdir -p /app/data
ENV UBT_DB=/app/data/backtests.sqlite3
EXPOSE 8000
CMD ["uvicorn","unibacktest.api:app","--host","0.0.0.0","--port","8000"]
