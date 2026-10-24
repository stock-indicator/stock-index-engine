# syntax=docker/dockerfile:1.6
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Pick up Debian security fixes published after the base image was built.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Run as an unprivileged user. Pass the uid that owns the mounted output/ and
# resources/ directories on the host, e.g. --build-arg APP_UID="$(id -u)".
ARG APP_UID=10001
RUN groupadd --gid "${APP_UID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Code stays root-owned and read-only to the app; only the data and log
# directories are writable.
COPY . .
RUN mkdir -p logs output resources && chown app:app logs output resources

USER app

EXPOSE 8000
ENV REFRESH_CRON="0 6 * * *" \
    UVICORN_HOST=0.0.0.0 \
    UVICORN_PORT=8000

HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status != 200)"]

CMD ["uvicorn", "services.api:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
