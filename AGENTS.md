# AGENTS.md

This file is the operating guide for automation agents working on this
repository.

## Project

- PyPI distribution name: `codex-bridge-python`
- Python import package: `codex_bridge`
- CLI command: `codex-bridge-python`
- Release version source: `pyproject.toml`
- Changelog: `CHANGELOG.md`
- Release workflow: `.github/workflows/release.yml`
- GitHub repository: `IP127000/codex-bridge-python`

## Working Rules

- Keep the working tree cleanly understood before editing:

```bash
git status --short --branch
```

- Use Semantic Versioning for releases: `MAJOR.MINOR.PATCH`.
- Never publish date-based or future-dated versions.
- The Git tag must exactly match the package version with a leading `v`.
  For example, `version = "0.1.4"` requires tag `v0.1.4`.
- Do not print, commit, or store PyPI tokens in files. The current workflow
  publishes with the GitHub Actions secret `PYPI_API_TOKEN`.
- The PyPI web page and `pip index` can lag behind successful uploads. Verify
  publication with GitHub Actions logs and the PyPI JSON API when needed.

## Feature Change And Release Flow

Use this flow when changing functionality, public behavior, README content that
should appear on PyPI, packaging metadata, or release-visible documentation.

1. Inspect the current project state.

```bash
git status --short --branch
python3 -m pytest -q
```

2. Make the code or documentation change.

- Keep edits scoped to the requested behavior.
- Update tests when behavior changes.
- Update `README.md` and `README.zh-CN.md` when user-facing usage changes.
- Update `pyproject.toml` with the next release version.
- Add a new entry at the top of `CHANGELOG.md`.

3. Run local validation.

```bash
scripts/check.sh
```

Or run the commands manually:

```bash
python3 -m pytest -q
rm -rf /tmp/codex-bridge-python-dist-X.Y.Z
python3 -m build --sdist --wheel --outdir /tmp/codex-bridge-python-dist-X.Y.Z
python3 -m twine check /tmp/codex-bridge-python-dist-X.Y.Z/*
```

If `build` or `twine` is not installed locally, install the dev extra or use a
temporary virtual environment:

```bash
python3 -m pip install -e ".[dev]"
```

4. Clean build leftovers before committing.

```bash
rm -rf src/codex_bridge_python.egg-info
git status --short
```

5. Commit and push `main`.

```bash
git add README.md README.zh-CN.md pyproject.toml CHANGELOG.md src tests
git commit -m "Short release-oriented summary"
git push origin main
```

Adjust the staged paths to match the actual change. Do not use `git add -A`
when unrelated files are present.

6. Create and push the matching annotated tag.

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

Pushing the tag triggers `.github/workflows/release.yml`. The workflow verifies
that `vX.Y.Z` matches `pyproject.toml`, runs tests, builds the package, checks
metadata, and publishes to PyPI.

7. Watch the release workflow.

```bash
gh run list --repo IP127000/codex-bridge-python --workflow Release --limit 1
gh run watch <run-id> --repo IP127000/codex-bridge-python --exit-status
```

If the workflow fails, inspect logs before retrying:

```bash
gh run view <run-id> --repo IP127000/codex-bridge-python --log
```

8. Create the GitHub Release and release notes after the workflow succeeds.

```bash
gh release create vX.Y.Z \
  /tmp/codex-bridge-python-dist-X.Y.Z/codex_bridge_python-X.Y.Z-py3-none-any.whl \
  /tmp/codex-bridge-python-dist-X.Y.Z/codex_bridge_python-X.Y.Z.tar.gz \
  --repo IP127000/codex-bridge-python \
  --title "vX.Y.Z" \
  --notes "## Changed

- Summarize the user-facing change.
- Mention packaging, CLI, README, or behavior changes that users need to know."
```

Prefer concise release notes with sections such as `Added`, `Changed`, `Fixed`,
or `Removed`. Keep them aligned with the `CHANGELOG.md` entry.

9. Verify PyPI and GitHub.

```bash
python3 -m pip index versions codex-bridge-python --no-cache-dir
python3 - <<'PY'
import json
import ssl
import urllib.request

ctx = ssl._create_unverified_context()
with urllib.request.urlopen("https://pypi.org/pypi/codex-bridge-python/json", context=ctx, timeout=20) as r:
    data = json.load(r)
print(data["info"]["version"])
PY
gh release view vX.Y.Z --repo IP127000/codex-bridge-python --json url,tagName,assets,publishedAt
```

For README-only PyPI changes, verify the PyPI JSON description contains the new
phrasing. The browser page may take longer to refresh.

## Testing Guide

Always run the complete test suite before committing behavior changes:

```bash
python3 -m pytest -q
```

For release readiness, prefer the project check script:

```bash
scripts/check.sh
```

The script reads the version from `pyproject.toml`, runs tests, builds sdist and
wheel into `/tmp/codex-bridge-python-dist-X.Y.Z`, and runs `twine check` on the
artifacts. It installs the dev extra if `build` or `twine` is missing, cleans
the generated `src/codex_bridge_python.egg-info`, and does not publish anything.

Current test areas:

- `tests/test_translate.py`: Responses-to-Chat-Completions translation,
  namespace tool flattening, reasoning item handling, image input conversion,
  model mapping, forced default model routing, denylisted tools, and history
  deduplication.
- `tests/test_app.py`: FastAPI bridge behavior against a mock upstream,
  streaming SSE conversion, usage propagation, namespace tool-call round trip,
  spawned child isolation, forced model routing, and config/model catalog
  output.
- `tests/test_launch.py`: simplified launcher argument detection, persisted
  launcher config, auth JSON, model catalog merging, context window defaults,
  auto-compaction settings, request compression settings, and launch workdir
  handling.

When changing a code path, add or update tests in the matching area:

- Translation or request/response schema changes: update `tests/test_translate.py`
  and add fixtures under `tests/fixtures/` when real Codex payload shape matters.
- Streaming behavior or HTTP proxy behavior: update `tests/test_app.py` with
  mock upstream SSE chunks and assert both downstream Responses events and
  upstream Chat Completions request bodies.
- Simple launcher, context size, Codex config, auth, or model catalog changes:
  update `tests/test_launch.py`.
- Session retention, disk history, reasoning carry-over, or cleanup changes:
  add focused tests for `SessionStore` behavior. If no suitable file exists,
  create a new `tests/test_session.py`.
- CLI parsing or environment variable behavior: add focused tests for
  `parse_args` or the affected helper.

Before releasing, make sure tests cover both the user-visible outcome and the
internal upstream request shape when the bridge transforms data.

## Documentation-Only Repository Changes

If a change is only for repository automation or agent instructions, such as
editing this `AGENTS.md`, do not publish a PyPI release unless the user asks for
one. Commit and push the repository change normally:

```bash
git add AGENTS.md
git commit -m "Document release workflow"
git push origin main
```

## Token And Publishing Notes

- The repository currently uses `secrets.PYPI_API_TOKEN` in the release
  workflow.
- If the token is rotated in PyPI, update the GitHub secret:

```bash
gh secret set PYPI_API_TOKEN --repo IP127000/codex-bridge-python
```

- Prefer PyPI Trusted Publishing in the future. If it is configured on PyPI,
  remove the explicit `password: ${{ secrets.PYPI_API_TOKEN }}` line from the
  publish step and validate the next release carefully.

## Common Pitfalls

- Forgetting to bump `pyproject.toml` before tagging.
- Tagging `vX.Y.Z` when `pyproject.toml` still says another version.
- Trusting `pip index` immediately after upload; it can lag behind PyPI JSON.
- Creating a GitHub Release before the package upload succeeds.
- Leaving `src/codex_bridge_python.egg-info` in the working tree after a local
  build.
- Using old wheel filenames in release assets after bumping the version.
