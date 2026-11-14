# CardReport Server

[![Latest release](https://img.shields.io/github/v/release/arch7tect/cardreport-server)](https://github.com/arch7tect/cardreport-server/releases/latest)

Manage versioned report templates and generate static PDF/HTML through a built-in
web console or an internal HTTP API, using
[CardReport](https://github.com/arch7tect/cardreport). The console lets you manage
templates, upload data and inspect reports in a browser; applications can use the
same API from Python or any HTTP client.

Templates and data are separate. Register a JSON/YAML template once, then submit
its ID/version and named datasets as JSON, YAML or CSV files. PostgreSQL holds metadata
and the queue; S3 holds inputs/results. Replaceable workers run bounded concurrent
attempts and scale independently from the FastAPI application. Workers coordinate
retention cleanup through PostgreSQL; no separate cleanup service is needed. See
[cleanup coordination](docs/user/operations.md#cleanup-coordination) for connection
budgeting and deployment requirements.

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

Use `ghcr.io/arch7tect/cardreport-server:0.5.0` for API, workers and migrations.
The [installation guide](docs/releases.md#install-a-released-image) starts the full
stack from the published image, without building it locally. For existing services,
follow the coordinated upgrade procedure before changing images.

## Use the web console

After starting the service, open [the web console](http://127.0.0.1:18000/ui/)
at `/ui/` on your server. It is included in the same image; no separate frontend
installation or terminal commands are needed to create reports.

1. In **Templates**, choose **Create template** to import or paste a JSON/YAML
   template and give it an ID.
2. In **New report**, select a template/version, renderer and PDF or HTML output.
   Use **Add files** to select JSON, YAML and CSV files, together or in several
   selections. Remove unwanted files with **×**, then choose **Generate report**.
3. Open the report to follow its status and view or download the result.
   **Show data** displays the normalized datasets for a successful report;
   **Download data JSON** saves that snapshot. **Show input files** provides the
   original uploads and an investigation ZIP, including for failed reports.

For a first report, import the [reference template](examples/reference_template.json)
and add the [reference CSV files](examples/reference_csv).

On a template's detail page, **Report retention** controls how long future reports
keep their inputs and output. Enter days (fractions are allowed), or leave empty
to inherit the server default. See the [web console guide](docs/user/web-console.md)
for file formats, search, pagination and all controls.

## Use from Python

The [complete client](examples/client.py) registers the template, streams input,
polls status and downloads the output. With the service running, install
[uv](https://docs.astral.sh/uv/) and run `uv sync --locked` from the repository root.
Use the following in your script, then run `uv run python your_script.py` from that
same directory so `examples.client` and the relative paths resolve:

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

This example helper creates a new template version on every call.
For production integrations, register templates separately and pin their version
when submitting `POST /v1/reports`. HTTP 202 confirms durable acceptance, not data
validation or successful rendering. Do not automatically repeat an upload after an
uncertain response: it can create a duplicate job.

Daily headings can use `{{ datasets.summary.report_date }}` in stored templates.
The library formats typed dates and numbers using report settings; the same template
works with JSON, YAML or CSV uploads. See the [daily report recipe](docs/user/api.md#daily-report-text)
and [web console instructions](docs/user/web-console.md#daily-report-text).

## Submit data files with curl

With the service running, execute these commands from the repository root.
First register the [reference template](examples/reference_template.json) as
`collections` through the API:

```sh
curl --fail-with-body -H 'Content-Type: application/json' \
  --data-binary @examples/reference_template.json \
  http://127.0.0.1:18000/v1/templates/collections/versions
```

Then submit the [reference CSV files](examples/reference_csv). This example uses
the latest template version; add `template_version=N` to pin a particular version.

```sh
curl --fail-with-body \
  'http://127.0.0.1:18000/v1/reports?template_id=collections&output=pdf' \
  -F 'files=@examples/reference_csv/summary.csv' \
  -F 'files=@examples/reference_csv/funnel.csv' \
  -F 'files=@examples/reference_csv/attempts.csv' \
  -F 'files=@examples/reference_csv/outcomes.csv' \
  -F 'files=@examples/reference_csv/payments.csv'
```

HTTP 202 means the upload and job were accepted. The response's `status_url` and
`content_url` are paths relative to the server address. Replace `REPORT_ID` below
with the returned `id`, and repeat the status request until `state` is `succeeded`,
`failed` or `expired`:

```sh
curl --fail-with-body 'http://127.0.0.1:18000/v1/reports/REPORT_ID'
```

Only after `state` becomes `succeeded`, download the PDF:

```sh
curl --fail-with-body --create-dirs --output output/reference.pdf \
  'http://127.0.0.1:18000/v1/reports/REPORT_ID/content'
```

CSV filenames name datasets (`summary.csv` supplies `summary`); column types come
from the stored template. JSON/YAML bundles carry their own dataset names and can
be included in the same multipart request. Dataset names must not overlap.
See [CSV API options](docs/user/api.md#csv-input) and the
[Python multipart example](docs/user/quickstart.md#csv-from-python).

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

The example saves `output/reference.pdf`. Open [local Swagger](http://127.0.0.1:18000/docs)
to explore the API, or the [web console](http://127.0.0.1:18000/ui/) for browser access.
Configure worker slots, retries and timeouts in `.env`; see
[configuration and budgets](docs/user/operations.md#configuration-and-budgets).
Everything needed for rendering and Swagger is in the app image; no external
browser assets are fetched. Stop with `docker compose --profile app stop`;
named volumes retain local data.

Layout failures can include the component path, page and measured overflow in
millimetres. See [layout error details](docs/user/api.md#layout-failure-details)
and [the console guide](docs/user/web-console.md#understanding-layout-failures).

## Documentation

- [Python quickstart and JSON/YAML/CSV examples](docs/user/quickstart.md)
- [Web console](docs/user/web-console.md)
- [HTTP API, history filters, status and error contract](docs/user/api.md)
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
