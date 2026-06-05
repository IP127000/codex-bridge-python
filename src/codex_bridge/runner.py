from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_binary() -> list[str]:
    script = shutil.which("codex-bridge-python")
    if script:
        return [script]
    local = Path(__file__).resolve().parents[2] / "bin" / "codex-bridge-python"
    if local.exists():
        return [str(local)]
    return [sys.executable, "-m", "codex_bridge"]


def start(
    port: int = 4444,
    upstream: str = "https://openrouter.ai/api/v1",
    api_key: str = "",
) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    if api_key:
        env["CODEX_BRIDGE_API_KEY"] = api_key

    cmd = [*_find_binary(), "--port", str(port), "--upstream", upstream]
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
