from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .session import (
    DEFAULT_MAX_SESSIONS,
    DEFAULT_MAX_SESSION_BYTES,
    DEFAULT_SESSION_TTL_SECONDS,
)


def env_value(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def env_int(*names: str, default: int) -> int:
    raw = env_value(*names, default=str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def env_bool(*names: str, default: bool) -> bool:
    raw = env_value(*names, default="true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    port: int
    upstream: str
    api_key: str
    print_config: bool
    force_default_model: bool
    default_model: str
    max_sessions: int
    max_session_memory_mb: int
    session_ttl_hours: int
    history_store: str
    history_dir: Path

    @property
    def max_session_bytes(self) -> int:
        return max(self.max_session_memory_mb, 1) * 1024 * 1024

    @property
    def session_ttl_seconds(self) -> int:
        return max(self.session_ttl_hours, 1) * 60 * 60


def validate_upstream(raw: str) -> str:
    upstream = raw.rstrip("/")
    parsed = urlparse(upstream)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"upstream URL scheme must be http or https, got: {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("upstream URL must have a host")
    return upstream


def provider_name_from_upstream(upstream: str) -> str:
    host = urlparse(upstream).hostname or "custom"
    host = host.removeprefix("api.").removeprefix("www.")
    for suffix in (".com", ".cn", ".ai", ".org", ".io"):
        if host.endswith(suffix):
            host = host[: -len(suffix)]
    return host or "custom"


def configure_logging() -> None:
    raw = env_value("CODEX_BRIDGE_LOG", "RUST_LOG", default="codex_bridge=info")
    level = logging.INFO
    lowered = raw.lower()
    if "debug" in lowered:
        level = logging.DEBUG
    elif "warn" in lowered or "warning" in lowered:
        level = logging.WARNING
    elif "error" in lowered:
        level = logging.ERROR

    logging.basicConfig(level=level, format="%(levelname)s %(message)s")


def parse_args(argv: list[str] | None = None) -> Settings:
    parser = argparse.ArgumentParser(
        prog="codex-bridge-python",
        description="Responses API ↔ Chat Completions bridge",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=env_int("CODEX_BRIDGE_PORT", default=4444),
    )
    parser.add_argument(
        "--upstream",
        default=env_value(
            "CODEX_BRIDGE_UPSTREAM",
            default="https://openrouter.ai/api/v1",
        ),
    )
    parser.add_argument(
        "--api-key",
        default=env_value("CODEX_BRIDGE_API_KEY", default=""),
    )
    parser.add_argument("--print-config", action="store_true")
    parser.add_argument(
        "--force-default-model",
        action="store_true",
        default=env_bool("CODEX_BRIDGE_FORCE_DEFAULT_MODEL", default=False),
    )
    parser.add_argument(
        "--default-model",
        default=env_value("CODEX_BRIDGE_DEFAULT_MODEL", default="deepseek-v4-flash"),
    )
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=env_int(
            "CODEX_BRIDGE_MAX_SESSIONS",
            default=DEFAULT_MAX_SESSIONS,
        ),
    )
    parser.add_argument(
        "--max-session-memory-mb",
        type=int,
        default=env_int(
            "CODEX_BRIDGE_MAX_SESSION_MEMORY_MB",
            default=DEFAULT_MAX_SESSION_BYTES // 1024 // 1024,
        ),
    )
    parser.add_argument(
        "--session-ttl-hours",
        type=int,
        default=env_int(
            "CODEX_BRIDGE_SESSION_TTL_HOURS",
            default=DEFAULT_SESSION_TTL_SECONDS // 60 // 60,
        ),
    )
    parser.add_argument(
        "--history-store",
        default=env_value(
            "CODEX_BRIDGE_HISTORY_STORE",
            default="memory",
        ),
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=Path(
            env_value(
                "CODEX_BRIDGE_HISTORY_DIR",
                default=".codex-bridge-python-history",
            )
        ),
    )
    args = parser.parse_args(argv)
    return Settings(
        port=args.port,
        upstream=validate_upstream(args.upstream),
        api_key=args.api_key,
        print_config=args.print_config,
        force_default_model=args.force_default_model,
        default_model=args.default_model.strip() or "deepseek-v4-flash",
        max_sessions=max(args.max_sessions, 1),
        max_session_memory_mb=max(args.max_session_memory_mb, 1),
        session_ttl_hours=max(args.session_ttl_hours, 1),
        history_store=args.history_store,
        history_dir=args.history_dir,
    )
