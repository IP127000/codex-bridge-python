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

1. Update `pyproject.toml` and `CHANGELOG.md`.
2. Commit the release changes.
3. Create and push an annotated tag:

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

4. The `Release` GitHub Actions workflow builds, checks, and publishes the package to PyPI.

The current workflow publishes with the GitHub Actions secret `PYPI_API_TOKEN`.
If PyPI Trusted Publishing is configured later for repository
`IP127000/codex-bridge-python`, workflow `.github/workflows/release.yml`,
environment `pypi`, and project `codex-bridge-python`, remove the explicit
`password: ${{ secrets.PYPI_API_TOKEN }}` setting from the publish step.

See `AGENTS.md` for the full automation-agent release checklist, including
GitHub Release creation and release note guidance.
