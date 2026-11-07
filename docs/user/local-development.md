# Local development

[README](../../README.md) · [Development checks](../development.md)

Use Docker Desktop (or a working Docker Engine with Compose) and Python 3.12+ with uv.
Ports bind to localhost. The default DB/S3 keys are development-only.

```sh
cp .env.example .env
uv sync --locked
docker compose up -d --wait postgres s3
uv run --env-file .env alembic upgrade head
uv run --env-file .env python -m cardreport_server init-storage
uv run --env-file .env python -m cardreport_server api
```

The native API listens on port 8000. Open this project in PyCharm, use
`.venv/bin/python`, run module `cardreport_server` with argument `api`, and keep the
project root as the working directory and explicitly load `.env` in the run configuration. Keep PostgreSQL and S3
in Compose. API startup refuses a mismatched database revision or unavailable storage.

Container setup uses the same application image intended for deployment:

```sh
docker compose --profile app build
docker compose --profile app run --rm migrate
docker compose --profile app up -d --wait api worker
```

The container API is on port 18000 (`API_PORT`). Use `/health/live` and `/health/ready`.
Run real PDF smokes for both Chromium and WeasyPrint without application/database configuration.
The container includes their Python and native dependencies; no host browser/Pango installation is needed.

```sh
docker run --rm cardreport-server:local /app/.venv/bin/python -m cardreport_server smoke
```

Stop using `docker compose --profile app stop`; restart with the commands above.
Named volumes retain developer data. Do not add `--volumes` to normal shutdown.
POSTGRES_PORT/S3_PORT/API_PORT can be changed in `.env` to avoid collisions; also
update native CARDREPORT_DATABASE_URL/CARDREPORT_S3_ENDPOINT accordingly.

The local S3 container is pinned SeaweedFS, not a production storage deployment.
Only its S3 port is published. Its bucket and credentials are initialized at startup;
`init-storage` verifies or creates the configured bucket for other endpoints.

Use [the Python quickstart](quickstart.md) to generate PDF and HTML.
Scale with `docker compose --profile app up -d --scale worker=2 worker`; each worker
has two slots by default (`WORKER_CONCURRENCY`). Native workers are not supported: detached browser cleanup
requires a container boundary. No local Kubernetes cluster is needed for daily work.

## Application settings in Compose

The `CARDREPORT_` tuning values in [`.env.example`](../../.env.example) also
configure the containers, including retries, polling, rendering and cleanup budgets.
The four native DB/S3 connection and credential values are exceptions: the local
stack keeps its bundled endpoints and credentials. See [applying configuration](operations.md#applying-configuration)
for an example, restart requirements and container termination grace.
