"""Service process entry points."""

import argparse
import sys

import uvicorn
from pydantic import ValidationError


def main() -> None:
    parser = argparse.ArgumentParser(prog="cardreport-server")
    parser.add_argument(
        "command", choices=["api", "worker", "worker-health", "init-storage", "smoke"]
    )
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        if args.command == "api":
            uvicorn.run(
                "cardreport_server.api:create_app",
                factory=True,
                host=args.host,
                port=8000,
                log_level="info",
            )
        elif args.command == "worker":
            from .settings import Settings
            from .worker import Worker

            raise SystemExit(Worker(Settings()).run())
        elif args.command == "worker-health":
            from .worker import health

            raise SystemExit(0 if health() else 1)
        elif args.command == "init-storage":
            from botocore.exceptions import ClientError

            from .settings import Settings
            from .storage import Storage

            storage = Storage(Settings())
            try:
                storage.check()
            except ClientError as error:
                if error.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                    raise
                storage.client.create_bucket(Bucket=storage.bucket)
            storage.check()
            print("Storage ready")
        else:
            from cardreport import (
                KPI,
                Card,
                ChromiumRenderer,
                Report,
                WeasyPrintRenderer,
            )

            report = Report("Renderer startup check")
            report.row(Card(KPI("Total", 34)), height_mm=50)
            for renderer in (ChromiumRenderer(), WeasyPrintRenderer()):
                assert report.to_pdf(timeout=30, renderer=renderer).startswith(b"%PDF-")
                print(f"{type(renderer).__name__} PDF smoke passed")
    except ValidationError:
        print(
            "Invalid service configuration; check documented settings", file=sys.stderr
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
