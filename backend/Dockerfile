FROM ghcr.io/astral-sh/uv:python3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io docker-compose \
    && rm -rf /var/lib/apt/lists/*
