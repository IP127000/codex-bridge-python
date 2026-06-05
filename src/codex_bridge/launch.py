from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .app import estimate_model_properties
from .config import validate_upstream
from .runner import _find_binary

SIMPLE_LAUNCH_PORT = 5057
TEMP_CODEX_HOME_NAME = ".codex-bridge-home"
LOCAL_PROVIDER_NAME = "codex-bridge"
LOCAL_BRIDGE_URL = f"http://127.0.0.1:{SIMPLE_LAUNCH_PORT}/v1"
BRIDGE_LOG_NAME = "codex-bridge.log"


def is_simple_launch_args(argv: list[str]) -> bool:
    return len(argv) == 3 and all(not arg.startswith("-") for arg in argv)


def _find_codex_binary() -> list[str]:
    script = shutil.which("codex")
    if script:
        return [script]
    raise FileNotFoundError("could not find `codex` in PATH")


def build_launcher_config(model: str, project_root: Path) -> str:
    props = estimate_model_properties(model)
    project_key = str(project_root.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    return "\n".join(
        [
            f'model = "{model}"',
            f'model_provider = "{LOCAL_PROVIDER_NAME}"',
            "",
            f'[model_providers."{LOCAL_PROVIDER_NAME}"]',
            f'name = "{LOCAL_PROVIDER_NAME}"',
            f'base_url = "{LOCAL_BRIDGE_URL}"',
            'wire_api = "responses"',
            'env_key = "OPENAI_API_KEY"',
            "",
            f'[model_properties."{model}"]',
            f"context_window = {props.context_window}",
            f"max_context_window = {props.max_context_window}",
            f"supports_parallel_tool_calls = {str(props.supports_parallel_tool_calls).lower()}",
            f"supports_reasoning_summaries = {str(props.supports_reasoning_summaries).lower()}",
            'input_modalities = ["text"]',
            "",
            f'[projects."{project_key}"]',
            'trust_level = "trusted"',
            "",
        ]
    )


def prepare_temp_codex_home(project_root: Path, model: str) -> Path:
    home_dir = project_root / TEMP_CODEX_HOME_NAME
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "config.toml").write_text(
        build_launcher_config(model, project_root),
        encoding="utf-8",
    )
    return home_dir


def _bridge_command(base_url: str) -> list[str]:
    return [
        *_find_binary(),
        "--port",
        str(SIMPLE_LAUNCH_PORT),
        "--upstream",
        base_url,
    ]


def start_bridge_for_codex(
    project_root: Path,
    base_url: str,
    api_key: str,
    model: str,
) -> tuple[subprocess.Popen[bytes], Path]:
    env = os.environ.copy()
    env["CODEX_BRIDGE_API_KEY"] = api_key
    env["CODEX_BRIDGE_FORCE_DEFAULT_MODEL"] = "true"
    env["CODEX_BRIDGE_DEFAULT_MODEL"] = model
    log_path = project_root / TEMP_CODEX_HOME_NAME / BRIDGE_LOG_NAME
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        _bridge_command(base_url),
        env=env,
        cwd=str(project_root),
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    log_file.close()
    return process, log_path


def _tail_log(log_path: Path, max_bytes: int = 4000) -> str:
    if not log_path.exists():
        return ""
    raw = log_path.read_bytes()
    return raw[-max_bytes:].decode("utf-8", errors="replace")


def wait_for_bridge_ready(process: subprocess.Popen[bytes], log_path: Path, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            details = _tail_log(log_path)
            raise RuntimeError(f"codex-bridge exited before becoming ready\n{details}".rstrip())
        try:
            response = httpx.get(f"{LOCAL_BRIDGE_URL}/models", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"status {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.25)
    details = _tail_log(log_path)
    raise RuntimeError(f"timed out waiting for codex-bridge ({last_error})\n{details}".rstrip())


def run_simple_launch(
    base_url: str,
    api_key: str,
    model: str,
    project_root: Path | None = None,
) -> int:
    project_root = (project_root or Path.cwd()).resolve()
    base_url = validate_upstream(base_url)
    home_dir = prepare_temp_codex_home(project_root, model)
    bridge_process, log_path = start_bridge_for_codex(project_root, base_url, api_key, model)
    try:
        wait_for_bridge_ready(bridge_process, log_path)
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home_dir)
        env["OPENAI_API_KEY"] = api_key
        cmd = _find_codex_binary()
        print(f"codex-bridge: upstream={base_url} local={LOCAL_BRIDGE_URL} model={model}", file=sys.stderr)
        print(f"codex-bridge: CODEX_HOME={home_dir}", file=sys.stderr)
        process = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(project_root),
        )
        return process.wait()
    finally:
        if bridge_process.poll() is None:
            bridge_process.terminate()
            try:
                bridge_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                bridge_process.kill()
                bridge_process.wait(timeout=5)
