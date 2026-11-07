"""Run real service dependencies under a fresh, isolated Compose project."""

import argparse
import json
import os
import socket
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def port() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep", action="store_true", help="Keep this test stack for debugging"
    )
    parser.add_argument(
        "--containers",
        action="store_true",
        help="Build and test API/worker containers, including recovery",
    )
    parser.add_argument(
        "--ui", action="store_true", help="Run browser checks after container checks"
    )
    args, extra = parser.parse_known_args()
    if args.ui and not args.containers:
        parser.error("--ui requires --containers")
    run_id = uuid.uuid4().hex[:10]
    project = "cardreport-test-" + run_id
    folder = ROOT / "local" / project
    folder.mkdir(parents=True)
    pg_port, s3_port = port(), port()
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CARDREPORT_")
        and k
        not in {"WORKER_CONCURRENCY", "CONTAINER_STOP_GRACE", "WORKER_START_PERIOD"}
    } | {
        "COMPOSE_PROJECT_NAME": project,
        "COMPOSE_ENV_FILES": "/dev/null",
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "POSTGRES_DB": "cardreport_test",
        "POSTGRES_PORT": pg_port,
        "S3_PORT": s3_port,
        "API_PORT": port(),
        "S3_BUCKET": "cardreport-test",
        "S3_PREFIX": "test/" + run_id + "/",
        "CARDREPORT_TEST_RUN": "1",
        "CARDREPORT_TEST_ARTIFACTS": str(folder),
        "CARDREPORT_DATABASE_URL": f"postgresql://cardreport:local-db-only@127.0.0.1:{pg_port}/cardreport_test",
        "CARDREPORT_S3_ENDPOINT": f"http://127.0.0.1:{s3_port}",
        "CARDREPORT_S3_ACCESS_KEY": "cardreport-local",
        "CARDREPORT_S3_SECRET_KEY": "local-storage-only",
        "CARDREPORT_S3_BUCKET": "cardreport-test",
        "CARDREPORT_S3_PREFIX": "test/" + run_id + "/",
    }
    # Store only this run's non-production configuration, never the inherited environment.
    (folder / "test-env.json").write_text(
        json.dumps(
            {
                k: v
                for k, v in env.items()
                if k.startswith("CARDREPORT_")
                or k
                in {
                    "COMPOSE_PROJECT_NAME",
                    "POSTGRES_DB",
                    "POSTGRES_PORT",
                    "S3_PORT",
                    "S3_BUCKET",
                    "S3_PREFIX",
                    "API_PORT",
                }
            },
            indent=2,
        )
    )

    def run(*command: str) -> None:
        subprocess.run(command, cwd=ROOT, env=env, check=True)

    succeeded = False
    try:
        run("docker", "info", "--format", "{{.Architecture}}")
        run("docker", "compose", "up", "-d", "--wait", "postgres", "s3")
        run("uv", "run", "alembic", "upgrade", "head")
        run("uv", "run", "alembic", "upgrade", "head")
        run("uv", "run", "python", "-m", "cardreport_server", "init-storage")
        run("uv", "run", "pytest", "tests/integration", "-q", *extra)
        if args.containers:
            run("docker", "compose", "build", "api")
            run(
                "docker",
                "compose",
                "--profile",
                "app",
                "up",
                "-d",
                "--wait",
                "api",
                "worker",
            )
            run("uv", "run", "pytest", "tests/container", "-q")
            if args.ui:
                run(
                    "docker",
                    "compose",
                    "--profile",
                    "app",
                    "up",
                    "-d",
                    "--wait",
                    "api",
                    "worker",
                )
                run("uv", "run", "pytest", "tests/ui", "-q")
        succeeded = True
    finally:
        with (folder / "compose.log").open("w") as log:
            subprocess.run(
                ["docker", "compose", "--profile", "app", "logs", "--no-color"],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if succeeded and not args.keep:
            # Only resources created above in this unique test project are removed.
            run("docker", "compose", "--profile", "app", "down", "--volumes")
        else:
            print(f"Preserved test stack {project}; configuration and logs in {folder}")


if __name__ == "__main__":
    main()
