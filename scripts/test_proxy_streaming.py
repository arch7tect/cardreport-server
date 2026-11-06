"""Prove an HTTP proxy forwards incomplete chunks to upload admission."""

import argparse
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18081")
    args = parser.parse_args()
    url = urlsplit(args.url)
    assert url.hostname == "127.0.0.1" and url.port is not None
    slug = "proxy-" + uuid4().hex
    sockets = []
    with httpx.Client(base_url=args.url, timeout=10) as client:
        response = client.post(
            f"/v1/templates/{slug}/versions",
            content=Path("examples/reference_template.json").read_bytes(),
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        try:
            for _ in range(4):
                sock = socket.create_connection((url.hostname, url.port))
                sock.sendall(
                    f"POST /v1/reports?template_id={slug} HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\n\r\n10000\r\n{'x' * 65536}\r\n".encode()
                )
                sockets.append(sock)
            # Let all four long requests reach the API before probing its capacity.
            time.sleep(1)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                response = client.post(
                    "/v1/reports",
                    params={"template_id": slug},
                    content=b"{}",
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 429:
                    break
                time.sleep(0.1)
            assert response.status_code == 429, response.text
            print("Incomplete chunked uploads reached all four API slots through nginx")
        finally:
            for sock in sockets:
                sock.close()


if __name__ == "__main__":
    main()
