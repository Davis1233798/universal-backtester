FROM python:3.12-slim
WORKDIR /app
# Optional JavaScript JSON-lines plugins need the Node runtime.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app/
COPY unibacktest /app/unibacktest
COPY examples /app/examples
RUN pip install --no-cache-dir -e '.[all]'
RUN mkdir -p /app/data
ENV UBT_DB=/app/data/backtests.sqlite3
EXPOSE 8000
CMD ["uvicorn","unibacktest.api:app","--host","0.0.0.0","--port","8000"]
