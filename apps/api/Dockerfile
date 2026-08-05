ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/apps/api/src \
    TMPDIR=/tmp/korpus

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates \
       poppler-utils \
       tesseract-ocr \
       tesseract-ocr-eng \
       tesseract-ocr-ukr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/api/requirements.runtime.lock /tmp/requirements.runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes --requirement /tmp/requirements.runtime.lock \
    && python -m pip check

COPY apps/api/src /app/apps/api/src
COPY apps/api/migrations /app/apps/api/migrations
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY scripts /app/scripts
COPY apps/api/docker-entrypoint.sh /usr/local/bin/korpus-entrypoint

RUN groupadd --gid 10001 korpus \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin korpus \
    && mkdir -p /data/objects /audit /tmp/korpus \
    && chown -R 10001:10001 /data /audit /tmp/korpus \
    && chmod 0555 /app /app/apps /app/apps/api /app/apps/api/src /app/scripts \
    && chmod 0555 /usr/local/bin/korpus-entrypoint

USER 10001:10001
WORKDIR /app
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
ENTRYPOINT ["/usr/local/bin/korpus-entrypoint"]
CMD ["python", "-m", "uvicorn", "korpus.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-keep-alive", "10"]
