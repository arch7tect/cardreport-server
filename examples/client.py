"""Register, stream, poll and download using the public HTTP API."""

import argparse
import time
from collections.abc import Iterator
from pathlib import Path

import httpx


def chunks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            yield chunk


def generate(
    base_url: str,
    template: Path,
    data: Path,
    destination: Path,
    template_id: str = "example",
    output: str = "pdf",
) -> dict[str, object]:
    with httpx.Client(base_url=base_url, timeout=150) as client:

        def media(path: Path) -> str:
            return (
                "application/yaml"
                if path.suffix in {".yaml", ".yml"}
                else "application/json"
            )

        registered = client.post(
            f"/v1/templates/{template_id}/versions",
            content=template.read_bytes(),
            headers={"Content-Type": media(template)},
        )
        registered.raise_for_status()
        submitted = client.post(
            "/v1/reports",
            params={
                "template_id": template_id,
                "template_version": registered.json()["version"],
                "output": output,
            },
            content=chunks(data),
            headers={"Content-Type": media(data)},
        )
        submitted.raise_for_status()
        job = submitted.json()
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            response = client.get(job["status_url"])
            response.raise_for_status()
            status = response.json()
            if status["state"] == "succeeded":
                destination.parent.mkdir(parents=True, exist_ok=True)
                with client.stream("GET", job["content_url"]) as content:
                    content.raise_for_status()
                    with destination.open("wb") as result:
                        for chunk in content.iter_bytes():
                            result.write(chunk)
                return dict(status)
            if status["state"] in {"failed", "expired"}:
                raise RuntimeError(status["error"] or "Result expired")
            time.sleep(0.5)
        raise TimeoutError(
            f"Polling deadline reached; inspect {job['status_url']} before resubmitting"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18000")
    parser.add_argument(
        "--template", type=Path, default=Path("examples/reference_template.json")
    )
    parser.add_argument(
        "--data", type=Path, default=Path("examples/reference_data.json")
    )
    parser.add_argument("--output", type=Path, default=Path("output/reference.pdf"))
    args = parser.parse_args()
    result = generate(
        args.url,
        args.template,
        args.data,
        args.output,
        output="html" if args.output.suffix == ".html" else "pdf",
    )
    print(f"Saved {args.output}; job {result['id']}")
