#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

cleanup() {
  rm -rf src/codex_bridge_python.egg-info
}
trap cleanup EXIT

VERSION="$(python3 - <<'PY'
import tomllib
from pathlib import Path

print(tomllib.loads(Path("pyproject.toml").read_text())["project"]["version"])
PY
)"

DIST_DIR="${DIST_DIR:-/tmp/codex-bridge-python-dist-${VERSION}}"

if ! python3 -c 'import build, twine' >/dev/null 2>&1
then
  printf 'Installing missing development dependencies...\n'
  python3 -m pip install -e ".[dev]"
fi

python3 -m pytest -q
rm -rf "$DIST_DIR"
python3 -m build --sdist --wheel --outdir "$DIST_DIR"
python3 -m twine check "$DIST_DIR"/*

printf 'Validation passed for codex-bridge-python %s\n' "$VERSION"
printf 'Artifacts: %s\n' "$DIST_DIR"
