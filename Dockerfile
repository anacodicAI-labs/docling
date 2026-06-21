FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir -e ".[platform]"

ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/app/.cache/huggingface
ENV STORAGE_ROOT=/data/storage
ENV DATABASE_URL=sqlite:////data/paper_extract.db

RUN mkdir -p /data/storage /data /app/.cache/huggingface

EXPOSE 8000

CMD ["paper-extract-api"]
