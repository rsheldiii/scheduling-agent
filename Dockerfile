FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.8 /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev --no-editable

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

EXPOSE 2255

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:2255/health')"

USER appuser

CMD ["uv", "run", "python", "main.py"]
