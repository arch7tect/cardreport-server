"""Release decisions must fail closed and preserve published version identities."""

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "release_script", ROOT / "scripts/release.py"
)
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize(
    "version,tag_sha,published,tags,expected",
    [
        ("0.1.0", None, False, [], True),
        ("0.1.0.dev0", None, False, [], False),
        ("0.1.0", "old", True, ["v0.1.0"], False),
        ("0.1.0", "head", False, ["v0.1.0"], True),
        ("0.2.0", None, False, ["v0.1.0"], True),
    ],
)
def test_release_decision(
    version: str, tag_sha: str | None, published: bool, tags: list[str], expected: bool
) -> None:
    assert release.should_release(version, "head", tag_sha, published, tags) is expected


@pytest.mark.parametrize(
    "version,tag_sha,published,tags",
    [
        ("0.1.0", "other", False, ["v0.1.0"]),
        ("0.1.0", None, True, []),
        ("0.1.0", None, False, ["v0.2.0"]),
        ("0.1.0", "old", True, ["v0.1.0", "v0.2.0"]),
        ("0.1.0rc1", None, False, []),
        ("0.1.0; bad", None, False, []),
    ],
)
def test_release_conflicts(
    version: str, tag_sha: str | None, published: bool, tags: list[str]
) -> None:
    with pytest.raises(ValueError):
        release.should_release(version, "head", tag_sha, published, tags)


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_github_failures(status: int) -> None:
    result = subprocess.CompletedProcess([], 1, "", f"gh: failure (HTTP {status})")
    with patch.object(release.subprocess, "run", return_value=result):
        if status == 404:
            assert release.api("repos/owner/repo/releases/tags/v0.1.0") is None
        else:
            with pytest.raises(RuntimeError):
                release.api("repos/owner/repo/releases/tags/v0.1.0")
        # Writes never turn a failure into an absent resource.
        with pytest.raises(RuntimeError):
            release.api("repos/owner/repo/git/refs", "-f", "sha=head")


@pytest.mark.parametrize(
    "error", ["denied", "unauthorized", "connection refused", "500"]
)
def test_registry_errors_are_not_missing_tags(error: str) -> None:
    result = subprocess.CompletedProcess([], 1, "", error)
    with patch.object(release.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError):
            release.manifest("ghcr.io/owner/repo:0.1.0")


def test_missing_registry_tag() -> None:
    result = subprocess.CompletedProcess([], 1, "", "manifest unknown")
    with patch.object(release.subprocess, "run", return_value=result):
        assert release.manifest("ghcr.io/owner/repo:0.1.0") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("Architecture", "arm64"),
        ("Os", "windows"),
        ("revision", "other"),
        ("version", "0.2.0"),
    ],
)
def test_image_identity(field: str, value: str) -> None:
    image: dict[str, Any] = {
        "Os": "linux",
        "Architecture": "amd64",
        "Config": {
            "Labels": {
                "org.opencontainers.image.version": "0.1.0",
                "org.opencontainers.image.revision": "head",
            }
        },
    }
    with patch.object(release, "run", return_value=json.dumps([image])):
        release.verify_image("tested", "amd64", "0.1.0", "head")
    if field in {"revision", "version"}:
        image["Config"]["Labels"][f"org.opencontainers.image.{field}"] = value
    else:
        image[field] = value
    with patch.object(release, "run", return_value=json.dumps([image])):
        with pytest.raises(ValueError, match="identity mismatch"):
            release.verify_image("tested", "amd64", "0.1.0", "head")


def test_lock_and_changelog(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.0"\n')
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname="cardreport-server"\nversion="0.0.1"\n'
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## 0.1.0\n\nNew service.\n\n## 0.0.1\nOld.\n"
    )
    with patch.object(release, "ROOT", tmp_path):
        assert release.release_notes("0.1.0") == "New service."
        with pytest.raises(ValueError, match="Missing changelog"):
            release.release_notes("0.2.0")
        with pytest.raises(ValueError, match="versions disagree"):
            release.plan()


def test_stale_main_cannot_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SHA", "old")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    with (
        patch.object(release, "run") as command,
        patch.object(release, "plan", return_value=("0.1.0", True)),
        patch.object(release, "api", return_value={"object": {"sha": "new"}}),
    ):
        with pytest.raises(ValueError, match="Main advanced"):
            release.publish()
        command.assert_called_once_with("git", "fetch", "origin", "main", "--tags")


def test_pr_cannot_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SHA", "head")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/1/merge")
    with patch.object(release, "run") as command:
        with pytest.raises(ValueError, match="restricted to main"):
            release.publish()
        command.assert_not_called()


def test_draft_retry_finishes_without_duplicate(tmp_path: Path) -> None:
    draft = {"isDraft": True, "targetCommitish": "head"}
    with (
        patch.object(release, "github_release", return_value=draft),
        patch.object(release, "run") as command,
    ):
        release.finish_release("v0.1.0", "head", tmp_path)
        assert [call.args[:3] for call in command.call_args_list] == [
            ("gh", "release", "upload"),
            ("gh", "release", "edit"),
        ]
        assert "--draft=false" in command.call_args_list[-1].args
    with (
        patch.object(release, "github_release", return_value=draft),
        patch.object(release, "run") as command,
    ):
        with pytest.raises(ValueError, match="another commit"):
            release.finish_release("v0.1.0", "other", tmp_path)
        command.assert_not_called()


def test_upload_failure_keeps_draft(tmp_path: Path) -> None:
    def fail_upload(*args: str) -> str:
        if args[2] == "upload":
            raise subprocess.CalledProcessError(1, args)
        return ""

    with (
        patch.object(release, "github_release", return_value=None),
        patch.object(release, "run", side_effect=fail_upload) as command,
    ):
        with pytest.raises(subprocess.CalledProcessError):
            release.finish_release("v0.1.0", "head", tmp_path)
        assert [call.args[2] for call in command.call_args_list] == ["create", "upload"]


@pytest.mark.parametrize("message", ["HTTP 403", "HTTP 404", "connection refused"])
def test_release_view_failures(message: str) -> None:
    result = subprocess.CompletedProcess([], 1, "", message)
    with patch.object(release.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError):
            release.github_release("v0.1.0")


def test_existing_version_conflict_never_retags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SHA", "head")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    index = {
        "manifests": [
            {
                "platform": {"os": "linux", "architecture": arch},
                "digest": "sha256:" + arch,
            }
            for arch in ["amd64", "arm64"]
        ]
    }

    def command(*args: str) -> str:
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([{"RepoDigests": ["ghcr.io/owner/repo@sha256:staging"]}])
        return ""

    def verify(reference: str, *_: str) -> None:
        if "@" in reference:
            raise ValueError("Image identity mismatch")

    with (
        patch.object(release, "run", side_effect=command) as calls,
        patch.object(release, "plan", return_value=("0.1.0", True)),
        patch.object(release, "api", return_value={"object": {"sha": "head"}}),
        patch.object(release, "github_release", return_value=None),
        patch.object(release, "manifest", return_value=index),
        patch.object(release, "verify_image", side_effect=verify),
    ):
        with pytest.raises(ValueError, match="identity mismatch"):
            release.publish()
        assert not any(
            "create" in call.args or "latest" in str(call.args)
            for call in calls.call_args_list
        )
