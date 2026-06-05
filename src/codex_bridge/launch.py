from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .app import estimate_model_properties
from .config import validate_upstream
from .model_catalog import DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT
from .model_catalog import build_model_catalog_entry, build_model_catalog_payload
from .runner import _find_binary

SIMPLE_LAUNCH_PORT = 5057
CODEX_BRIDGE_HOME_NAME = ".codex-bridge-python"
LOCAL_PROVIDER_NAME = "codex-bridge"
LOCAL_BRIDGE_URL = f"http://127.0.0.1:{SIMPLE_LAUNCH_PORT}/v1"
BRIDGE_LOG_NAME = "codex-bridge.log"
LAUNCHER_SECTION_NAME = "codex_bridge_launcher"
DEFAULT_CONTEXT_WINDOW = 128_000
MODEL_CATALOG_NAME = "model-catalog.local.json"


def is_simple_launch_args(argv: list[str]) -> bool:
    return len(argv) <= 4 and all(not arg.startswith("-") for arg in argv)


def _find_codex_binary() -> list[str]:
    script = shutil.which("codex")
    if script:
        return [script]
    raise FileNotFoundError("could not find `codex` in PATH")


def codex_bridge_home_dir() -> Path:
    return Path.home() / CODEX_BRIDGE_HOME_NAME


def codex_launch_workdir(project_root: Path) -> Path:
    return codex_bridge_home_dir() if project_root.resolve() == Path.home().resolve() else project_root.resolve()


def normalize_context_window(value: int | str | None) -> int:
    if value is None:
        return DEFAULT_CONTEXT_WINDOW
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONTEXT_WINDOW
    return normalized if normalized > 0 else DEFAULT_CONTEXT_WINDOW


def context_window_for_model(model: str) -> int:
    props = estimate_model_properties(model)
    return props.context_window if props.context_window > 0 else DEFAULT_CONTEXT_WINDOW


def auto_compact_token_limit(context_window: int) -> int:
    return max(context_window // 2, 1)


def _codex_config_overrides(model: str, context_window: int, model_catalog_path: Path) -> list[str]:
    compact_limit = auto_compact_token_limit(context_window)
    return [
        "-c",
        f'model="{model}"',
        "-c",
        'model_reasoning_effort="high"',
        "-c",
        f"model_context_window={context_window}",
        "-c",
        f"model_auto_compact_token_limit={compact_limit}",
        "-c",
        "enable_request_compression=true",
        "-c",
        f'model_catalog_json="{model_catalog_path}"',
        "-c",
        f'model_provider="{LOCAL_PROVIDER_NAME}"',
        "-c",
        f'model_providers."{LOCAL_PROVIDER_NAME}".name="{LOCAL_PROVIDER_NAME}"',
        "-c",
        f'model_providers."{LOCAL_PROVIDER_NAME}".base_url="{LOCAL_BRIDGE_URL}"',
        "-c",
        f'model_providers."{LOCAL_PROVIDER_NAME}".wire_api="responses"',
        "-c",
        f'model_providers."{LOCAL_PROVIDER_NAME}".env_key="OPENAI_API_KEY"',
    ]


def model_catalog_path(home_dir: Path) -> Path:
    return home_dir / MODEL_CATALOG_NAME


def build_model_catalog(
    base_url: str,
    model: str,
    context_window: int,
) -> dict[str, list[dict[str, object]]]:
    provider_url = validate_upstream(base_url)
    props = estimate_model_properties(model)
    description = f"Custom model via codex-bridge upstream: {provider_url} -> {model}"
    return build_model_catalog_payload(
        [
            build_model_catalog_entry(
                model=model,
                description=description,
                context_window=context_window,
                max_context_window=props.max_context_window,
                supports_parallel_tool_calls=props.supports_parallel_tool_calls,
                supports_reasoning_summaries=props.supports_reasoning_summaries,
                input_modalities=["text"],
            )
        ]
    )


def load_model_catalog_entries(home_dir: Path) -> list[dict[str, object]]:
    path = model_catalog_path(home_dir)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    entries = payload.get("models")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("slug"), str)]


def merge_model_catalog_entries(
    existing_entries: list[dict[str, object]],
    base_url: str,
    model: str,
    context_window: int,
) -> dict[str, list[dict[str, object]]]:
    current_entry = next((entry for entry in existing_entries if entry.get("slug") == model), None)
    if not current_entry or current_entry.get("context_window") != context_window:
        current_entry = build_model_catalog(base_url, model, context_window)["models"][0]
    merged_entries: list[dict[str, object]] = []
    replaced = False
    for entry in existing_entries:
        if entry.get("slug") == model:
            merged_entries.append(current_entry)
            replaced = True
        else:
            merged_entries.append(entry)
    if not replaced:
        merged_entries.append(current_entry)
    return build_model_catalog_payload(merged_entries)


def write_model_catalog(
    home_dir: Path,
    base_url: str,
    model: str,
    context_window: int,
    existing_entries: list[dict[str, object]] | None = None,
) -> Path:
    path = model_catalog_path(home_dir)
    payload = merge_model_catalog_entries(existing_entries or [], base_url, model, context_window)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def build_launcher_config(
    home_dir: Path,
    base_url: str,
    model: str,
    launch_workdir: Path,
    context_window: int,
) -> str:
    compact_limit = auto_compact_token_limit(context_window)
    project_key = str(launch_workdir.resolve()).replace("\\", "\\\\").replace('"', '\\"')
    catalog_path = model_catalog_path(home_dir)
    return "\n".join(
        [
            f'model = "{model}"',
            'model_reasoning_effort = "high"',
            f"model_context_window = {context_window}",
            f"model_auto_compact_token_limit = {compact_limit}",
            "enable_request_compression = true",
            f'model_catalog_json = "{catalog_path}"',
            f'model_provider = "{LOCAL_PROVIDER_NAME}"',
            "",
            f'[model_providers."{LOCAL_PROVIDER_NAME}"]',
            f'name = "{LOCAL_PROVIDER_NAME}"',
            f'base_url = "{LOCAL_BRIDGE_URL}"',
            'wire_api = "responses"',
            'env_key = "OPENAI_API_KEY"',
            "",
            f"[{LAUNCHER_SECTION_NAME}]",
            f'upstream = "{base_url}"',
            f'model = "{model}"',
            f"context_window = {context_window}",
            f"port = {SIMPLE_LAUNCH_PORT}",
            "",
            f'[projects."{project_key}"]',
            'trust_level = "trusted"',
            "",
        ]
    )


def write_auth_json(home_dir: Path, api_key: str) -> None:
    payload = {
        "auth_mode": "apikey",
        "OPENAI_API_KEY": api_key,
    }
    (home_dir / "auth.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_temp_codex_home(
    home_dir: Path,
    base_url: str,
    api_key: str,
    model: str,
    launch_workdir: Path,
    context_window: int,
    available_models: list[str] | None = None,
    *,
    reset: bool,
) -> Path:
    existing_entries = load_model_catalog_entries(home_dir)
    if reset and home_dir.exists():
        shutil.rmtree(home_dir)
    home_dir.mkdir(parents=True, exist_ok=True)
    write_model_catalog(home_dir, base_url, model, context_window, existing_entries)
    (home_dir / "config.toml").write_text(
        build_launcher_config(home_dir, base_url, model, launch_workdir, context_window),
        encoding="utf-8",
    )
    write_auth_json(home_dir, api_key)
    return home_dir


def _parse_string_value(raw: str) -> str | None:
    match = re.fullmatch(r'"((?:[^"\\]|\\.)*)"', raw.strip())
    if not match:
        return None
    return bytes(match.group(1), "utf-8").decode("unicode_escape")


def _parse_scalar_value(raw: str) -> str | int | None:
    parsed_string = _parse_string_value(raw)
    if parsed_string is not None:
        return parsed_string
    try:
        return int(raw.strip())
    except ValueError:
        return None


def load_saved_launcher_config(home_dir: Path) -> dict[str, str | int]:
    config_path = home_dir / "config.toml"
    if not config_path.exists():
        return {}
    current_section = ""
    values: dict[str, str | int] = {}
    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current_section = stripped[1:-1].strip().strip('"')
            continue
        if current_section != LAUNCHER_SECTION_NAME or "=" not in stripped:
            continue
        key, raw_value = stripped.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        parsed = _parse_scalar_value(raw_value)
        if parsed is not None:
            values[key] = parsed
    return values


def load_saved_api_key(home_dir: Path) -> str | None:
    auth_path = home_dir / "auth.json"
    if not auth_path.exists():
        return None
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    api_key = payload.get("OPENAI_API_KEY")
    return api_key if isinstance(api_key, str) and api_key else None


def resolve_simple_launch_args(
    argv: list[str],
    home_dir: Path,
) -> tuple[str, str, str, int, bool]:
    saved = load_saved_launcher_config(home_dir)
    saved_upstream = saved.get("upstream") if isinstance(saved.get("upstream"), str) else None
    saved_model = saved.get("model") if isinstance(saved.get("model"), str) else None
    saved_api_key = load_saved_api_key(home_dir)
    provided_base_url = argv[0] if len(argv) >= 1 else None
    provided_api_key = argv[1] if len(argv) >= 2 else None
    provided_model = argv[2] if len(argv) >= 3 else None
    provided_context_window = argv[3] if len(argv) >= 4 else None

    base_url = provided_base_url or saved_upstream
    api_key = provided_api_key or saved_api_key

    model: str | None = None
    if provided_model:
        model = provided_model
    elif saved_upstream and base_url == saved_upstream:
        model = saved_model

    missing: list[str] = []
    if not isinstance(base_url, str) or not base_url:
        missing.append("base_url")
    if not isinstance(api_key, str) or not api_key:
        missing.append("api_key")
    if not isinstance(model, str) or not model:
        missing.append("model")
    if missing:
        raise ValueError(
            "missing required launch values: "
            + ", ".join(missing)
            + f". Provide them as positional args or populate {home_dir}."
        )

    saved_context_window = None
    if saved_upstream == base_url and saved_model == model:
        saved_context_window = saved.get("context_window")
    context_window = normalize_context_window(
        provided_context_window
        or saved_context_window
        or context_window_for_model(model)
    )
    has_explicit_changes = any(
        [
            provided_base_url not in (None, saved_upstream),
            provided_api_key not in (None, saved_api_key),
            provided_model not in (None, saved_model),
            provided_context_window is not None
            and normalize_context_window(provided_context_window) != normalize_context_window(saved_context_window),
        ]
    )
    return base_url, api_key, model, context_window, len(argv) >= 3 or has_explicit_changes


def _bridge_command(base_url: str) -> list[str]:
    return [
        *_find_binary(),
        "--port",
        str(SIMPLE_LAUNCH_PORT),
        "--upstream",
        base_url,
    ]


def start_bridge_for_codex(
    bridge_cwd: Path,
    home_dir: Path,
    base_url: str,
    api_key: str,
    model: str,
) -> tuple[subprocess.Popen[bytes], Path]:
    env = os.environ.copy()
    env["CODEX_BRIDGE_API_KEY"] = api_key
    env["CODEX_BRIDGE_FORCE_DEFAULT_MODEL"] = "true"
    env["CODEX_BRIDGE_DEFAULT_MODEL"] = model
    log_path = home_dir / BRIDGE_LOG_NAME
    log_file = log_path.open("ab")
    process = subprocess.Popen(
        _bridge_command(base_url),
        env=env,
        cwd=str(bridge_cwd),
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
    argv: list[str],
    project_root: Path | None = None,
) -> int:
    project_root = (project_root or Path.cwd()).resolve()
    home_dir = codex_bridge_home_dir()
    launch_workdir = codex_launch_workdir(project_root)
    base_url, api_key, model, context_window, reset_home = resolve_simple_launch_args(argv, home_dir)
    base_url = validate_upstream(base_url)
    home_dir = prepare_temp_codex_home(
        home_dir,
        base_url,
        api_key,
        model,
        launch_workdir,
        context_window,
        reset=reset_home,
    )
    bridge_process, log_path = start_bridge_for_codex(launch_workdir, home_dir, base_url, api_key, model)
    try:
        wait_for_bridge_ready(bridge_process, log_path)
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home_dir)
        env["OPENAI_API_KEY"] = api_key
        cmd = [*_find_codex_binary(), *_codex_config_overrides(model, context_window, model_catalog_path(home_dir))]
        print(f"codex-bridge: upstream={base_url} local={LOCAL_BRIDGE_URL} model={model}", file=sys.stderr)
        print(f"codex-bridge: CODEX_HOME={home_dir}", file=sys.stderr)
        print(f"codex-bridge: workdir={launch_workdir} context_window={context_window}", file=sys.stderr)
        process = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(launch_workdir),
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
