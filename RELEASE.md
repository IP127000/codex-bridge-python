# Release

This project publishes to PyPI as `codex-bridge-python`.

## Versioning

- Use Semantic Versioning: `MAJOR.MINOR.PATCH`.
- Keep the version in `pyproject.toml` as the single release source.
- Tag releases as `vX.Y.Z`, matching the project version exactly.
- Do not upload date-based or future-dated versions.

## Local checks

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest -q
rm -rf build dist src/*.egg-info
python3 -m build
python3 -m twine check dist/*
```

## PyPI release

1. Update the release version in `pyproject.toml`.
2. Add the matching release entry to `CHANGELOG.md`.
3. Run local checks:

```bash
python3 -m pytest -q
rm -rf /tmp/codex-bridge-python-dist-X.Y.Z
python3 -m build --sdist --wheel --outdir /tmp/codex-bridge-python-dist-X.Y.Z
python3 -m twine check /tmp/codex-bridge-python-dist-X.Y.Z/*
```

4. Commit and push the release changes:

```bash
git add pyproject.toml CHANGELOG.md README.md README.zh-CN.md src tests
git commit -m "Release vX.Y.Z"
git push origin main
```

Adjust the staged paths to match the actual change.

5. Create and push the matching annotated tag:

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```

6. Watch the GitHub Actions release workflow:

```bash
gh run list --repo IP127000/codex-bridge-python --workflow Release --limit 1
gh run watch <run-id> --repo IP127000/codex-bridge-python --exit-status
```

The `Release` GitHub Actions workflow verifies that the tag matches
`pyproject.toml`, runs tests, builds the package, checks metadata, and publishes
the package to PyPI.

7. Create the GitHub Release and release notes after PyPI publish succeeds:

```bash
gh release create vX.Y.Z \
  /tmp/codex-bridge-python-dist-X.Y.Z/codex_bridge_python-X.Y.Z-py3-none-any.whl \
  /tmp/codex-bridge-python-dist-X.Y.Z/codex_bridge_python-X.Y.Z.tar.gz \
  --repo IP127000/codex-bridge-python \
  --title "vX.Y.Z" \
  --notes "## Changed

- Summarize the user-facing release changes."
```

8. Verify the published package and GitHub Release:

```bash
python3 -m pip index versions codex-bridge-python --no-cache-dir
gh release view vX.Y.Z --repo IP127000/codex-bridge-python --json url,tagName,assets,publishedAt
```

Use the PyPI JSON API if the browser page or `pip index` lags behind a
successful upload.

The current workflow publishes with the GitHub Actions secret `PYPI_API_TOKEN`.
If PyPI Trusted Publishing is configured later for repository
`IP127000/codex-bridge-python`, workflow `.github/workflows/release.yml`,
environment `pypi`, and project `codex-bridge-python`, remove the explicit
`password: ${{ secrets.PYPI_API_TOKEN }}` setting from the publish step.

See `AGENTS.md` for the full automation-agent release checklist, including
GitHub Release creation and release note guidance.
