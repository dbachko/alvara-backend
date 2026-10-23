FROM python:3.14.9-slim-bookworm@sha256:945c2676dc2b18e0c1f16879244122c57c0ffede60006bf3df159c507a31bcae

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALVARA_HOST=0.0.0.0 \
    ALVARA_PORT=8080 \
    ALVARA_PUBLIC_BASE_URL=http://127.0.0.1:8080

RUN groupadd --system --gid 10001 alvara \
    && useradd --system --uid 10001 --gid alvara --home-dir /app alvara

WORKDIR /app
COPY --chown=alvara:alvara pyproject.toml uv.lock ./
RUN python -m pip install --no-cache-dir uv==0.12.21 \
    && uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:${PATH}"

COPY --chown=alvara:alvara alvara_assets ./alvara_assets/
COPY --chown=alvara:alvara abi ./abi/
COPY --chown=alvara:alvara *.py README.md settings.json ./
RUN mkdir -p /app/artifacts && chown alvara:alvara /app/artifacts

USER alvara
EXPOSE 8080
ENTRYPOINT ["python", "async_server.py"]
