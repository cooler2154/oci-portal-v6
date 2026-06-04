# OCI Portal Dockerfile — pure Python, no Node.js
# Build:  docker build -t oci-portal .
# Run:    docker run -p 8000:8000 -v ~/.oci:/root/.oci:ro -e SECRET_KEY=xxx oci-portal

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c \
  "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/debug/health')"

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--access-log"]
