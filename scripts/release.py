"""Publish verified container artifacts; pyproject.toml owns the release version."""

import argparse
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STABLE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
ARCHITECTURES = ("amd64", "arm64")


def run(*command: str) -> str:
    return subprocess.check_output(command, text=True).strip()


def api(path: str, *args: str) -> Any:
    result = subprocess.run(
        ["gh", "api", path, *args], capture_output=True, text=True, check=False
    )
    if result.returncode:
        if not args and "(HTTP 404)" in result.stderr:
            return None
        raise RuntimeError(f"GitHub API failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def github_release(tag: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft,targetCommitish"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        if result.stderr.strip() == "release not found":
            return None
        raise RuntimeError(f"Release lookup failed: {result.stderr.strip()}")
    return dict(json.loads(result.stdout))


def check_draft(info: dict[str, Any] | None, sha: str) -> None:
    if info is not None and (not info["isDraft"] or info["targetCommitish"] != sha):
        raise ValueError("Release is published or its draft belongs to another commit")


def finish_release(tag: str, sha: str, folder: Path) -> None:
    info = github_release(tag)
    check_draft(info, sha)
    if info is None:
        run(
            "gh",
            "release",
            "create",
            tag,
            "--target",
            sha,
            "--draft",
            "--title",
            tag,
            "--notes-file",
            str(folder / "notes.md"),
        )
    run("gh", "release", "upload", tag, str(folder / "images.json"), "--clobber")
    run(
        "gh",
        "release",
        "edit",
        tag,
        "--draft=false",
        "--latest",
        "--notes-file",
        str(folder / "notes.md"),
    )


def release_notes(version: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    heading = f"## {version}\n"
    if heading not in changelog:
        raise ValueError(f"Missing changelog section: {version}")
    return changelog.split(heading, 1)[1].split("\n## ", 1)[0].strip()


def should_release(
    version: str, head: str, tag_sha: str | None, published: bool, tags: list[str]
) -> bool:
    if not STABLE.fullmatch(version):
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+\.dev[0-9]+", version):
            return False
        raise ValueError("Use X.Y.Z for releases or X.Y.Z.devN for development")
    current = tuple(map(int, version.split(".")))
    if any(
        tuple(map(int, tag[1:].split("."))) > current
        for tag in tags
        if tag.startswith("v") and STABLE.fullmatch(tag[1:])
    ):
        raise ValueError("Release version is older than an existing version tag")
    if published:
        if tag_sha is None:
            raise ValueError("Published release is missing its source tag")
        return False
    if tag_sha is not None and tag_sha != head:
        raise ValueError("Unfinished release belongs to a different commit")
    return True


def plan() -> tuple[str, bool]:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    locked = tomllib.loads((ROOT / "uv.lock").read_text())
    if (
        next(
            p["version"] for p in locked["package"] if p["name"] == "cardreport-server"
        )
        != version
    ):
        raise ValueError("pyproject.toml and uv.lock versions disagree; run uv lock")
    repository = os.environ["GITHUB_REPOSITORY"]
    tag = f"v{version}"
    tags = run("git", "tag", "--list").splitlines()
    tag_sha = run("git", "rev-list", "-n", "1", tag) if tag in tags else None
    release = api(f"repos/{repository}/releases/tags/{tag}")
    ready = should_release(
        version,
        os.environ["GITHUB_SHA"],
        tag_sha,
        release is not None and not release["draft"],
        tags,
    )
    if ready:
        release_notes(version)
    return version, ready


def manifest(reference: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["docker", "manifest", "inspect", reference],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        if "manifest unknown" in result.stderr or "no such manifest" in result.stderr:
            return None
        raise RuntimeError(f"Registry read failed: {result.stderr.strip()}")
    return dict(json.loads(result.stdout))


def verify_image(reference: str, architecture: str, version: str, sha: str) -> None:
    image = json.loads(run("docker", "image", "inspect", reference))[0]
    labels = image["Config"]["Labels"]
    if (
        image["Os"] != "linux"
        or image["Architecture"] != architecture
        or labels.get("org.opencontainers.image.version") != version
        or labels.get("org.opencontainers.image.revision") != sha
    ):
        raise ValueError(f"Image identity mismatch: {reference}")


def publish() -> None:
    repository, sha = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if os.environ["GITHUB_REF"] != "refs/heads/main":
        raise ValueError("Publishing is restricted to main")
    run("git", "fetch", "origin", "main", "--tags")
    version, ready = plan()
    if not ready:
        print("Version already published or development version; nothing to publish")
        return
    if api(f"repos/{repository}/git/ref/heads/main")["object"]["sha"] != sha:
        raise ValueError("Main advanced; publish from its current checked commit")
    tag, image = f"v{version}", f"ghcr.io/{repository.lower()}"
    check_draft(github_release(tag), sha)
    reference = f"{image}:{version}"
    sources = []
    for arch in ARCHITECTURES:
        run("docker", "load", "--input", f"local/release-images/{arch}.tar.gz")
        local = f"cardreport-server:release-{arch}"
        verify_image(local, arch, version, sha)
        target = f"{image}:sha-{sha}-{arch}"
        run("docker", "tag", local, target)
        run("docker", "push", target)
        # Freeze each source by registry digest, not a mutable staging tag or image ID.
        digests = json.loads(run("docker", "image", "inspect", target))[0][
            "RepoDigests"
        ]
        sources.append(next(d for d in digests if d.startswith(image + "@")))
    # The first architecture push creates the GHCR package before checking its version tag.
    if manifest(reference) is None:
        run("docker", "buildx", "imagetools", "create", "--tag", reference, *sources)
    index = manifest(reference)
    assert index is not None
    platforms = {m["platform"]["architecture"]: m for m in index.get("manifests", [])}
    if set(platforms) != set(ARCHITECTURES):
        raise ValueError("Release must contain exactly amd64 and arm64")
    # Also validate an existing version on retry, without replacing its bytes.
    for arch, item in platforms.items():
        pinned = f"{image}@{item['digest']}"
        run("docker", "pull", "--platform", f"linux/{arch}", pinned)
        verify_image(pinned, arch, version, sha)
    run(
        "docker",
        "run",
        "--rm",
        f"{image}@{platforms['amd64']['digest']}",
        "/app/.venv/bin/python",
        "-m",
        "cardreport_server",
        "smoke",
    )
    digest = run(
        "docker",
        "buildx",
        "imagetools",
        "inspect",
        reference,
        "--format",
        "{{json .Manifest}}",
    ).strip()
    identity = json.loads(digest)["digest"]
    run(
        "docker",
        "buildx",
        "imagetools",
        "create",
        "--tag",
        f"{image}:latest",
        f"{image}@{identity}",
    )
    folder = ROOT / "local" / "release"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "images.json").write_text(
        json.dumps(
            {
                "version": version,
                "commit": sha,
                "image": reference,
                "digest": identity,
                "platforms": {a: m["digest"] for a, m in platforms.items()},
            },
            indent=2,
        )
        + "\n"
    )
    notes = (
        release_notes(version)
        + f"\n\nContainer: `{reference}`\n\nPinned image: `{image}@{identity}`\n"
    )
    (folder / "notes.md").write_text(notes)
    # A draft survives asset-upload failure; publish only after its digest record exists.
    finish_release(tag, sha, folder)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "publish"))
    args = parser.parse_args()
    if args.command == "publish":
        publish()
    else:
        version, ready = plan()
        output = f"version={version}\nrelease={str(ready).lower()}\n"
        print(output, end="")
        if path := os.environ.get("GITHUB_OUTPUT"):
            with Path(path).open("a") as stream:
                stream.write(output)


if __name__ == "__main__":
    main()
