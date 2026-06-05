from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from .app import create_app, log_upstream_models, print_codex_config
from .config import Settings, configure_logging, parse_args, provider_name_from_upstream
from .launch import is_simple_launch_args, run_simple_launch


async def async_main(settings: Settings) -> int:
    if settings.print_config:
        await print_codex_config(
            upstream=settings.upstream,
            api_key=settings.api_key,
            provider_name=provider_name_from_upstream(settings.upstream),
            port=settings.port,
        )
        return 0

    app = create_app(settings)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=settings.port,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)

    async def _log_models() -> None:
        try:
            await log_upstream_models(settings.upstream, settings.api_key)
        except Exception:
            logging.getLogger("codex_bridge").exception("failed to log upstream models")

    asyncio.create_task(_log_models())
    await server.serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    configure_logging()
    if is_simple_launch_args(argv):
        try:
            return run_simple_launch(argv)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 2
    try:
        settings = parse_args(argv)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return asyncio.run(async_main(settings))


if __name__ == "__main__":
    raise SystemExit(main())
