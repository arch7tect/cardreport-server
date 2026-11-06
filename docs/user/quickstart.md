# Generate a report from Python

Start the [local stack](local-development.md). Templates are registered separately
from generation. The request body is a standard CardReport dataset bundle, in JSON
or YAML; CSV conversion belongs to the caller or the CardReport library.

Run the complete streaming client:

```sh
uv run python examples/client.py
uv run python examples/client.py --output output/reference.html
uv run python examples/client.py --template examples/flow_template.json --data examples/flow_data.json --output output/flow.pdf
```

The [client](../../examples/client.py) shows registration, version pinning, a chunked
upload, bounded status polling and a streamed download. `generate()` can be imported
into another Python application (requires httpx). It deliberately does not retry
submission: after a lost response, the job may already exist. Retrying creates a
second report. Retain the returned job ID to resume polling.

The reference JSON/YAML fixtures are copied from CardReport 0.8.1's MIT-licensed
public examples at library commit `e5a5ae3a5b5bb9b1f012ed39b3230c8f02d00d14`.
The flow example is synthetic: 150 numbered rows demonstrate table pagination.

A `202` response confirms durable upload and queue commit. Dataset validation and
rendering happen asynchronously. HTML is a static semantic preview; only PDF runs
Chromium's page geometry checks. The server currently uses Chromium for PDF.

Open `/docs` for local Swagger and `/openapi.json` for the schema-derived contract.
No browser assets require a public CDN. The API has no authentication and belongs
only on a trusted internal network.
