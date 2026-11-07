"""Verify console assets from an installed wheel outside the source checkout."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = """
from pathlib import Path
import cardreport_server
from fastapi.testclient import TestClient
from cardreport_server.api import create_app
from cardreport_server.settings import Settings
config = Settings(_env_file=None, database_url='postgresql://u:p@localhost/test',
    s3_endpoint='http://localhost:8333', s3_access_key='test', s3_secret_key='test',
    s3_bucket='test', s3_prefix='test/')
client = TestClient(create_app(config))
assert 'site-packages' in str(Path(cardreport_server.__file__))
for name in ('', 'app.js', 'common.js', 'templates.js', 'submit.js', 'reports.js', 'console.css'):
    response = client.get('/ui/' + name)
    assert response.status_code == 200, name
    assert response.headers['cache-control'] == 'no-cache'
assert client.get('/docs').status_code == 200
print('Installed wheel console and Swagger passed outside source checkout')
"""


def main() -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("CARDREPORT_") and k != "PYTHONPATH"
    }
    with tempfile.TemporaryDirectory(prefix="cardreport-package-") as directory:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", directory],
            cwd=ROOT,
            env=env,
            check=True,
        )
        wheel = next(Path(directory).glob("*.whl"))
        subprocess.run(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--python",
                sys.executable,
                "--with",
                str(wheel),
                "--with",
                "httpx",
                "python",
                "-c",
                CHECK,
            ],
            cwd=directory,
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
