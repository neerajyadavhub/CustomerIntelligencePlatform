FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as an unprivileged user. /app must be writable for the demo SQLite file.
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.getenv('PORT', '8000'))"

# See docker-entrypoint.sh for when demo data is loaded.
ENTRYPOINT ["./docker-entrypoint.sh"]
