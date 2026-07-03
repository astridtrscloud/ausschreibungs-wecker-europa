FROM python:3.11-slim

WORKDIR /app

# System-Abhaengigkeiten (gcc fuer native Extensions, curl fuer Healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python-Abhaengigkeiten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium-Browser installieren (optional, fuer simap.ch JS-Rendering)
RUN playwright install chromium 2>/dev/null || true

# Anwendungscode
COPY app/ ./app/
COPY tests/ ./tests/
COPY pytest.ini .

# Daten-Verzeichnis fuer SQLite
RUN mkdir -p data

# Port fuer FastAPI
EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Start via uvicorn
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
