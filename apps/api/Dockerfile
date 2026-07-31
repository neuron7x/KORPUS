FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-ukr poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir '/app/apps/api[postgres]'
COPY scripts /app/scripts
RUN useradd --create-home --uid 10001 korpus && mkdir -p /data/objects && chown -R korpus:korpus /data /app
USER 10001
ENV KORPUS_DATABASE_URL=sqlite:////data/korpus.db KORPUS_OBJECT_ROOT=/data/objects
EXPOSE 8000
CMD ["uvicorn", "korpus.main:app", "--host", "0.0.0.0", "--port", "8000"]
