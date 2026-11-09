FROM ghcr.io/astral-sh/uv:0.9.8@sha256:08f409e1d53e77dfb5b65c788491f8ca70fe1d2d459f41c89afa2fcbef998abe AS uv
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN apt-get update && apt-get install -y --no-install-recommends tini libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project && .venv/bin/python -m playwright install --with-deps chromium
COPY src ./src
RUN uv sync --locked --no-dev --no-editable
COPY alembic.ini ./
COPY migrations ./migrations
RUN useradd --uid 10001 --create-home app && mkdir /tmp/cardreport-worker && chown app:app /tmp/cardreport-worker
ARG BUILD_VERSION=development
ARG SOURCE_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/arch7tect/cardreport-server" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version=$BUILD_VERSION \
      org.opencontainers.image.revision=$SOURCE_REVISION
USER app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/.venv/bin/python", "-m", "cardreport_server", "api", "--host", "0.0.0.0"]
