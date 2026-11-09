# Releases

[README](../README.md) · [Changelog](../CHANGELOG.md) · [Operations](user/operations.md)

## Install a released image

GitHub Releases contain the versioned source, release notes and `images.json` with
the source commit, multi-platform digest and individual platform digests. GHCR
contains `ghcr.io/arch7tect/cardreport-server`, supporting Linux amd64 and arm64.
Both Chromium and WeasyPrint are included. No PyPI publication is part of this
service's release process.

For a **fresh local installation**, clone the matching tag and use its Compose file:

```sh
git clone --branch v0.1.0 https://github.com/arch7tect/cardreport-server.git
cd cardreport-server
cp .env.example .env  # First setup only; preserve an existing .env.
export CARDREPORT_SERVER_IMAGE=ghcr.io/arch7tect/cardreport-server:0.1.0
export CARDREPORT_IMAGE_ID="$CARDREPORT_SERVER_IMAGE"
docker compose --profile app pull migrate api worker
docker compose up -d --wait postgres s3
docker compose --profile app run --rm --no-build migrate
docker compose --profile app up -d --no-build --wait api worker
```

Open `http://127.0.0.1:18000/ui/`. You can persist both image settings in `.env`.
Use the same selected image for migrations, API and workers. `pull` downloads the
published image; `--no-build` prevents a missing image being replaced by a local
build under a release name. Stop if `pull` reports a warning or failure. For source development, leave `CARDREPORT_SERVER_IMAGE`
unset and follow the [development setup](user/local-development.md).

For production, pin `ghcr.io/arch7tect/cardreport-server@sha256:...` from the
release's `images.json` and use that identity for `CARDREPORT_IMAGE_ID` too.
`latest` is a convenience tag, not an upgrade policy. An existing installation
must follow [the coordinated upgrade procedure](user/operations.md#upgrade-and-rollback),
including admission stop, worker drain and migration. Do not apply the fresh-install
commands as a live rolling upgrade. Kubernetes uses the same image/digest.

## Cut a release

1. Update `[project].version` in `pyproject.toml` to a new stable `X.Y.Z`.
2. Run `uv lock` to synchronize the local package version. Do not hand-edit the lock.
3. Add a `## X.Y.Z` section to `CHANGELOG.md`; update any affected user docs.
4. Run the [development checks](development.md), review the diff and push to `main`.
5. Follow the `checks` workflow through both architecture lanes and publication.
6. Verify the GitHub release, anonymous GHCR pull and both-engine smoke below.

Versions ending in `.devN` run checks without publishing. Ordinary main commits
keeping an already released version also run checks without a new release. Stable
versions must not go backwards. PRs and manual runs on other branches never publish.
`workflow_dispatch` on main can retry a release; it does not bypass verification.

The workflow runs native amd64 and arm64 test lanes: lint, types, documentation,
unit tests, installed-wheel checks, PostgreSQL/S3 integration, container recovery,
browser workflows and both renderer startup smokes. Only after both lanes succeed
does it publish the saved **tested images**, without rebuilding them. Before upload,
the installed package version must match the version selected from `pyproject.toml`.
OCI labels bind each image to the source revision and version.

The publishing job alone receives `contents: write` and `packages: write` through
`GITHUB_TOKEN`. No personal publishing token or PyPI secret is required. Publishing
is serialized and checks the current main commit. The script checks identity on
retry and never overwrites an existing version manifest; a conflicting revision
stops publication. Staging tags `sha-<commit>-amd64` and `sha-<commit>-arm64` are
implementation artifacts, not releases. `X.Y.Z` and `latest` select both platforms.
The GitHub release uses tag `vX.Y.Z`; its digest attachment is uploaded while the
release is a draft, before making it public.

## Retry and initial registry setup

GitHub and GHCR cannot be updated atomically. A failed run can leave staging tags,
a versioned image, or a draft release. Use **Re-run failed jobs** on the same run
while it is still the main commit; saved tested images are retained for three days.
The publisher validates and reuses an existing version image instead of replacing
it, and finishes the draft release. If artifacts expire, rerun all jobs on that
same commit. If main advanced, stop and inspect the partial publication; never
move a published version tag or silently reuse its version for different code.
The safe recovery is a new patch version and changelog entry. Removing an abandoned
unreleased image/draft requires an explicit administrator decision; never delete
an already published release to reuse its version. `latest` may already point to a
partial release, so deployments must pin their chosen digest. A full rerun may
rebuild and update staging tags; `images.json` describes the preserved version
manifest, not those staging tags.

GHCR initially creates a private package even for a public repository. After the
first push, an administrator must open the package settings, change visibility to
**Public**, and verify an anonymous pull. Repository linkage comes from the OCI
source label. This is a one-time setup for the package, not a step on every release.
See [GitHub's registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

After publication, pull the digest from `images.json` on each supported platform
and run:

```sh
# Replace this placeholder with the multi-platform digest from images.json.
release_image=ghcr.io/arch7tect/cardreport-server@sha256:REPLACE_WITH_RELEASE_DIGEST
release_docker_config=$(mktemp -d)
docker --config "$release_docker_config" pull "$release_image"
docker --config "$release_docker_config" run --rm "$release_image" \
  /app/.venv/bin/python -m cardreport_server smoke
```

Use an empty Docker credential configuration or a clean host to check public access.
The smoke renders a PDF with each engine; it does not connect to a database or S3.
Source publication does not deploy or migrate any existing installation.
