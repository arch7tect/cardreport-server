# CardReport Server

Manage versioned report templates and generate static PDF/HTML through an internal
HTTP API, using [CardReport](https://github.com/arch7tect/cardreport).

Templates and data are separate. Register a JSON/YAML template once, then submit
its ID/version and a streamed bundle of named datasets. PostgreSQL holds metadata
and the queue; S3 holds inputs/results. Replaceable workers run bounded concurrent
attempts and scale independently from the FastAPI application.

PDF and HTML support `renderer=chromium` (default) and `renderer=weasyprint`.
Both engines are included in the worker image. Chromium supports dashboard and
flow; the experimental SVG/WeasyPrint engine supports dashboard only and requires
no browser or JavaScript for rendering. Unsupported features fail explicitly.
HTML is a preview; PDF is the authoritative checked output. See
[renderer selection](docs/user/api.md#renderer-selection) for details.

**Development version; no package release yet.** The service, examples and local deployment checks are implemented; see [implementation progress](docs/implementation-plan.md) and the
[verification record](docs/reviews/2026-11-06-verification.md). There is no built-in
authentication: deploy only on a trusted internal network.

## Start locally

Install Docker with Compose and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync --locked
cp .env.example .env  # First setup only; preserve any existing .env.
docker compose --profile app build
docker compose up -d --wait postgres s3
docker compose --profile app run --rm migrate
docker compose --profile app up -d --wait api worker
uv run python examples/client.py
```

Configure worker slots, retries and timeouts in `.env`; see
[configuration and budgets](docs/user/operations.md#configuration-and-budgets).

The example saves `output/reference.pdf`. Open [local Swagger](http://127.0.0.1:18000/docs)
for the API. Everything needed for rendering and Swagger is in the app image;
no external browser assets are fetched. Stop with `docker compose --profile app stop`;
named volumes retain local data.

## Use from Python

The [complete client](examples/client.py) registers the template, streams input,
polls status and downloads the output. For embedding from this checkout:

```python
from pathlib import Path
from examples.client import generate

generate(
    "http://127.0.0.1:18000",
    template=Path("examples/reference_template.json"),
    data=Path("examples/reference_data.json"),
    destination=Path("output/reference.pdf"),
    template_id="collections",
    renderer="chromium",  # Or "weasyprint" for dashboard reports.
)
```

For production integrations, register templates separately and pin their version
when submitting `POST /v1/reports`. HTTP 202 confirms durable acceptance, not data
validation or successful rendering. Do not automatically repeat an upload after an
uncertain response: it can create a duplicate job.

## Documentation

- [Python quickstart and JSON/YAML examples](docs/user/quickstart.md)
- [HTTP API, status and error contract](docs/user/api.md)
- [Local Compose and PyCharm setup](docs/user/local-development.md)
- [Configuration, recovery, retention and upgrades](docs/user/operations.md)
- [Internal Kubernetes and kind acceptance](docs/user/kubernetes.md)
- [Development checks](docs/development.md)

The library's dataset limits remain in force. Upload streaming bounds API
memory; worker decoding and rendering still materialize data. There is no arbitrary
code execution, SQL connector, URL data fetcher, broker, or separate scheduler.

## Project documents

[Design](docs/design.md) · [Implementation plan](docs/implementation-plan.md) ·
[Design review](docs/reviews/2026-11-06-design.md) · [Plan review](docs/reviews/2026-11-06-implementation-plan.md) ·
[Renderer review and checks](docs/reviews/2026-11-07-renderers.md)

## License

[MIT](LICENSE).
