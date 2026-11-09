# CardReport Server

[![Latest release](https://img.shields.io/github/v/release/arch7tect/cardreport-server)](https://github.com/arch7tect/cardreport-server/releases/latest)

Manage versioned report templates and generate static PDF/HTML through an internal
HTTP API, using [CardReport](https://github.com/arch7tect/cardreport).

Templates and data are separate. Register a JSON/YAML template once, then submit
its ID/version and named datasets as JSON, YAML or CSV files. PostgreSQL holds metadata
and the queue; S3 holds inputs/results. Replaceable workers run bounded concurrent
attempts and scale independently from the FastAPI application.

PDF and HTML support `renderer=chromium` (default) and `renderer=weasyprint`.
Both engines are included in the worker image. Chromium supports dashboard and
flow; the experimental SVG/WeasyPrint engine supports dashboard only and requires
no browser or JavaScript for rendering. Unsupported features fail explicitly.
HTML is a preview; PDF is the authoritative checked output. See
[renderer selection](docs/user/api.md#renderer-selection) for details.

Available as a [versioned Docker image and GitHub release](docs/releases.md) for
Linux amd64 and arm64. See [what is new](CHANGELOG.md). There is no built-in
authentication: deploy only on a trusted internal network.

## Run a released image

Use `ghcr.io/arch7tect/cardreport-server:0.3.0` for API, workers and migrations.
The [installation guide](docs/releases.md#install-a-released-image) starts the full
stack from the published image, without building it locally. For existing services,
follow the coordinated upgrade procedure before changing images.

## Develop locally

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
for the API, or the [web console](http://127.0.0.1:18000/ui/) to manage templates, generate reports and browse results. Everything needed for rendering and Swagger is in the app image;
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

## Submit data files

CSV filenames name the datasets: `summary.csv` supplies `summary`. Register the
[reference template](examples/reference_template.json) as `collections` first,
then send the [reference CSV files](examples/reference_csv):

```sh
curl --fail-with-body \
  'http://127.0.0.1:18000/v1/reports?template_id=collections&output=pdf' \
  -F 'files=@examples/reference_csv/summary.csv' \
  -F 'files=@examples/reference_csv/funnel.csv' \
  -F 'files=@examples/reference_csv/attempts.csv' \
  -F 'files=@examples/reference_csv/outcomes.csv' \
  -F 'files=@examples/reference_csv/payments.csv'
```

The response contains status and download URLs. In **New report**, **Add files**
accepts JSON, YAML and CSV together, in one selection or several. Remove any file
with its × button before submitting. CSV types come from the stored template;
JSON/YAML bundles contain their own dataset names. Names must not overlap.
After generation, **Show data** displays the datasets used for that report;
**Download data JSON** saves their immutable typed snapshot.
**Show input files** lists original uploads, including failed reports; download an
individual file or an investigation ZIP with the pinned template and diagnostics.
Set **Report retention** on the template to control how long future runs keep
originals, normalized data and output. See
[CSV API options](docs/user/api.md#csv-input) and the
[Python multipart example](docs/user/quickstart.md#csv-from-python).

## Documentation

- [Python quickstart and JSON/YAML/CSV examples](docs/user/quickstart.md)
- [Web console](docs/user/web-console.md)
- [HTTP API, status and error contract](docs/user/api.md)
- [Local Compose and PyCharm setup](docs/user/local-development.md)
- [Configuration, recovery, retention and upgrades](docs/user/operations.md)
- [Internal Kubernetes and kind acceptance](docs/user/kubernetes.md)
- [Development checks](docs/development.md)
- [Releases, image installation and publication](docs/releases.md)
- [Changelog](CHANGELOG.md)

The library's dataset limits remain in force. Upload streaming bounds API
memory; worker decoding and rendering still materialize data. There is no arbitrary
code execution, SQL connector, URL data fetcher, broker, or separate scheduler.

## Project documents

[Implemented architecture and worker lifecycle](docs/architecture.md) ·
[Design](docs/design.md) · [Implementation plan](docs/implementation-plan.md) ·
[Web console design](docs/ui-design.md) · [Web console implementation plan](docs/ui-implementation-plan.md) ·
[Design review](docs/reviews/2026-11-06-design.md) · [Plan review](docs/reviews/2026-11-06-implementation-plan.md) ·
[Renderer review and checks](docs/reviews/2026-11-07-renderers.md)

## License

[MIT](LICENSE).
