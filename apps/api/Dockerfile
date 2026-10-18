ARG PYTHON_IMAGE=python:3.12.13-alpine3.23@sha256:601d3d3797e90e2534782e69c85fafb7971b43f24c7b1b079b7e48dd435e458d
FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/apps/api/src \
    TMPDIR=/tmp/korpus

# База закріплена за дайджестом, але security-fixes в Alpine виходять після збирання
# бази. `upgrade` мусить стояти перед install у тому самому шарі: вимір 19.10.2026
# закрив 10 виправлених HIGH і дав 0 HIGH/CRITICAL без ignore-unfixed.
RUN mkdir -p "$TMPDIR" \
    && apk upgrade --no-cache \
    && apk add --no-cache \
       ca-certificates \
       poppler-utils \
       tesseract-ocr \
       tesseract-ocr-data-eng \
       tesseract-ocr-data-ukr

WORKDIR /app
COPY apps/api/requirements.runtime.lock /tmp/requirements.runtime.lock
RUN python -m pip install --no-cache-dir --no-deps --require-hashes --requirement /tmp/requirements.runtime.lock \
    && python -m pip check

COPY apps/api/src /app/apps/api/src
COPY apps/api/migrations /app/apps/api/migrations
COPY apps/api/alembic.ini /app/apps/api/alembic.ini
COPY scripts /app/scripts
COPY apps/api/docker-entrypoint.sh /usr/local/bin/korpus-entrypoint

RUN addgroup -g 10001 -S korpus \
    && adduser -u 10001 -S -D -H -G korpus -s /sbin/nologin korpus \
    && mkdir -p /data/objects /audit /tmp/korpus \
    && chown -R 10001:10001 /data /audit /tmp/korpus \
    && chmod 0555 /app /app/apps /app/apps/api /app/apps/api/src /app/scripts \
    && chmod 0555 /usr/local/bin/korpus-entrypoint \
    # COPY keeps the host's file modes. This tree's working files are 0660, the runtime
    # user is 10001, and every capability is dropped — so not even root inside the
    # container may read a file it does not own, because DAC_OVERRIDE is dropped with
    # the rest. Executed 2026-08-06: alembic answered "No 'script_location' key found in
    # configuration" because it could not open alembic.ini, and the migrate job had
    # never once run. Directories keep 0555 above; this makes their contents readable
    # and nothing writable.
    && chmod -R a+rX /app/apps/api/src /app/apps/api/migrations /app/scripts \
    && chmod a+r /app/apps/api/alembic.ini

USER 10001:10001
WORKDIR /app
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=4 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
ENTRYPOINT ["/usr/local/bin/korpus-entrypoint"]
CMD ["python", "-m", "uvicorn", "korpus.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--timeout-keep-alive", "10"]
