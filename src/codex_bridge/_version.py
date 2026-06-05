from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

DISTRIBUTION_NAME = "codex-bridge-python"
FALLBACK_VERSION = "0.1.0"

try:
    __version__ = version(DISTRIBUTION_NAME)
except PackageNotFoundError:
    __version__ = FALLBACK_VERSION
