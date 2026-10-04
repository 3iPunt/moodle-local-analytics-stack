FROM python:3.12.15-slim

# HOME decides where DuckDB installs extensions; mysql_scanner is fetched here at build time
# because the runtime network (backend) has no internet access.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/opt/duck \
    DATA_DIR=/data

RUN groupadd --system --gid 10001 analytics \
    && useradd --system --uid 10001 --gid analytics --home-dir /opt/duck --no-create-home analytics \
    && mkdir -p /opt/duck /data \
    && chown analytics:analytics /data

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN python -c "import duckdb; duckdb.connect().execute('INSTALL mysql')" \
    && chmod -R a+rX /opt/duck

COPY pytest.ini views.sql examples.yaml ./
COPY app ./app
COPY tests ./tests

USER analytics

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

CMD ["uvicorn", "--factory", "app.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
