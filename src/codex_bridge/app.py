from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from .config import Settings
from .session import SessionStore
from .stream import StreamArgs, translate_stream
from .translate import from_chat_response, to_chat_request
from .types import ChatMessage, ChatResponse, ResponsesInput, ResponsesRequest

logger = logging.getLogger("codex_bridge")
DEBUG_NAME_LIMIT = 80


@dataclass(slots=True)
class ModelProps:
    context_window: int
    max_context_window: int
    supports_parallel_tool_calls: bool
    supports_reasoning_summaries: bool


@dataclass(slots=True)
class AppState:
    sessions: SessionStore
    client: httpx.AsyncClient
    upstream: str
    api_key: str


def join_base(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


async def fetch_upstream_models(
    upstream: str,
    api_key: str,
    timeout: float = 5.0,
) -> list[str]:
    url = f"{join_base(upstream)}models"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        body = response.json()
    entries = body.get("data") or body.get("models") or []
    if not isinstance(entries, list):
        return []
    return [
        model.get("id")
        for model in entries
        if isinstance(model, dict) and isinstance(model.get("id"), str)
    ]


async def log_upstream_models(upstream: str, api_key: str) -> None:
    try:
        models = await fetch_upstream_models(upstream, api_key)
    except httpx.HTTPStatusError as exc:
        logger.warning("upstream models: status %s (check credentials?)", exc.response.status_code)
        return
    except httpx.RequestError as exc:
        logger.warning("upstream models: request error: %s", exc)
        return
    except asyncio.TimeoutError:
        logger.warning("upstream models: request timed out (upstream unreachable?)")
        return

    if models:
        logger.info("upstream models: %s", ", ".join(models))
        logger.info(
            "To configure Codex with model metadata, run: codex-bridge --print-config --upstream %s %s",
            upstream,
            "" if not api_key else "--api-key ...",
        )


async def print_codex_config(
    upstream: str,
    api_key: str,
    provider_name: str,
    port: int,
) -> None:
    try:
        models = await fetch_upstream_models(upstream, api_key)
    except Exception as exc:
        print(f"// Failed to fetch upstream models: {exc}")
        print("// Falling back to a generic snippet. Replace <YOUR_MODEL> below.")
        models = ["<YOUR_MODEL>"]

    print(f"# -- Codex config snippet for {urlparse(upstream).hostname or 'custom'} --")
    print("# Copy the lines below into ~/.codex/config.toml")
    print()
    print(f'model_provider = "{provider_name}"')
    if models and not models[0].startswith("<"):
        print(f'model = "{models[0]}"')
    else:
        print('model = "<CHOOSE_A_MODEL>"')
    print()
    print(f"[model_providers.{provider_name}]")
    print(f'name = "{provider_name}"')
    print(f'base_url = "http://127.0.0.1:{port}/v1"')
    print('wire_api = "responses"')
    print(f'env_key = "{provider_name.upper().replace("-", "_").replace(".", "_")}_API_KEY"')
    print()
    for model in models:
        props = estimate_model_properties(model)
        print(f'[model_properties."{model}"]')
        print(f"context_window = {props.context_window}")
        print(f"max_context_window = {props.max_context_window}")
        print(f"supports_parallel_tool_calls = {str(props.supports_parallel_tool_calls).lower()}")
        print(f"supports_reasoning_summaries = {str(props.supports_reasoning_summaries).lower()}")
        print('input_modalities = ["text"]')
        print()


def estimate_model_properties(model_id: str) -> ModelProps:
    lower = model_id.lower()
    has_reasoning = any(token in lower for token in ("reasoner", "r1", "k2", "o1", "thinking", "deepseek-v4"))
    if "gpt-5" in lower:
        ctx, max_ctx = 272_000, 1_000_000
    elif "gpt-4.5" in lower or "gpt-4o" in lower:
        ctx, max_ctx = 128_000, 128_000
    elif "claude" in lower:
        ctx, max_ctx = 200_000, 200_000
    elif "gemini" in lower:
        ctx, max_ctx = 1_000_000, 2_000_000
    elif "deepseek" in lower:
        ctx, max_ctx = 262_144, 1_048_576
    elif "qwen" in lower:
        ctx, max_ctx = 131_072, 131_072
    elif any(token in lower for token in ("kimi", "moonshot", "mistral", "llama", "codestral")):
        ctx, max_ctx = 128_000, 128_000
    else:
        ctx, max_ctx = 128_000, 128_000
    return ModelProps(
        context_window=ctx,
        max_context_window=max_ctx,
        supports_parallel_tool_calls=True,
        supports_reasoning_summaries=has_reasoning,
    )


def summarize_debug_names(names: list[str]) -> str:
    if not names:
        return "(none)"
    shown = ", ".join(names[:DEBUG_NAME_LIMIT])
    if len(names) > DEBUG_NAME_LIMIT:
        shown += f", ... (+{len(names) - DEBUG_NAME_LIMIT} more)"
    return shown


def response_tool_debug_names(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        tool_type = tool.get("type")
        if tool_type == "function":
            name = tool.get("name")
            if not name and isinstance(tool.get("function"), dict):
                name = tool["function"].get("name")
            if isinstance(name, str):
                names.append(name)
        elif tool_type == "namespace":
            namespace = tool.get("name", "")
            for child in tool.get("tools") or []:
                if child.get("type") == "function" and isinstance(child.get("name"), str):
                    names.append(f"{namespace}.{child['name']}")
        elif isinstance(tool_type, str):
            names.append(f"<{tool_type}>")
    return names


def chat_tool_debug_names(tools: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for tool in tools:
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            names.append(function["name"])
        elif isinstance(tool.get("name"), str):
            names.append(tool["name"])
    return names


def chat_response_tool_call_debug_names(chat_resp: ChatResponse) -> list[str]:
    names: list[str] = []
    for choice in chat_resp.choices:
        for tool_call in choice.message.tool_calls or []:
            function = tool_call.get("function") or {}
            name = function.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def isolated_user_text(input_value: ResponsesInput) -> str | None:
    if input_value.kind == "text":
        return str(input_value.value)
    items = input_value.value
    if len(items) != 1:
        return None
    item = items[0]
    if item.get("type") != "message" or item.get("role") != "user":
        return None
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list) and len(content) == 1 and isinstance(content[0], dict):
        text = content[0].get("text")
        return text if isinstance(text, str) else None
    return None


def spawn_agent_message(call: dict[str, Any]) -> str | None:
    function = call.get("function")
    if not isinstance(function, dict) or function.get("name") != "spawn_agent":
        return None
    arguments = function.get("arguments")
    if not isinstance(arguments, str):
        return None
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    message = payload.get("message")
    return message if isinstance(message, str) else None


def should_isolate_spawn_child_request(req: ResponsesRequest, history: list[ChatMessage]) -> bool:
    input_text = isolated_user_text(req.input)
    if input_text is None:
        return False
    completed_tool_calls = {
        message.tool_call_id
        for message in history
        if message.tool_call_id
    }
    for message in history:
        for call in message.tool_calls or []:
            call_id = call.get("id")
            if isinstance(call_id, str) and call_id in completed_tool_calls:
                continue
            if spawn_agent_message(call) == input_text:
                return True
    return False


def create_app(settings: Settings) -> FastAPI:
    if settings.history_store == "memory":
        sessions = SessionStore(
            max_sessions=settings.max_sessions,
            max_stored_bytes=settings.max_session_bytes,
            ttl_seconds=settings.session_ttl_seconds,
        )
    elif settings.history_store == "disk":
        sessions = SessionStore.with_disk_limits_and_ttl(
            settings.history_dir,
            settings.max_sessions,
            settings.max_session_bytes,
            settings.session_ttl_seconds,
        )
    else:
        raise ValueError(f"history store must be 'memory' or 'disk', got: {settings.history_store}")

    state = AppState(
        sessions=sessions,
        client=httpx.AsyncClient(timeout=None),
        upstream=settings.upstream,
        api_key=settings.api_key,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.bridge = state
        cleanup_task = asyncio.create_task(_cleanup_sessions(state.sessions))
        logger.info(
            "session retention: store=%s dir=%s ttl=%sh max_sessions=%s max_session_memory=%s MiB",
            settings.history_store,
            settings.history_dir,
            settings.session_ttl_hours,
            settings.max_sessions,
            settings.max_session_memory_mb,
        )
        logger.info("codex-bridge listening on 127.0.0.1:%s -> %s", settings.port, settings.upstream)
        try:
            yield
        finally:
            cleanup_task.cancel()
            await state.client.aclose()

    app = FastAPI(lifespan=lifespan)

    @app.get("/v1/models")
    async def handle_models() -> Response:
        logger.info("GET /v1/models")
        url = f"{join_base(state.upstream)}models"
        headers = {}
        if state.api_key:
            headers["Authorization"] = f"Bearer {state.api_key}"
        upstream_body: dict[str, Any] | None = None
        try:
            response = await state.client.get(url, headers=headers)
            if response.is_success:
                upstream_body = response.json()
            else:
                logger.warning("upstream models: status %s", response.status_code)
        except Exception as exc:
            logger.warning("upstream models: request error: %s", exc)

        models = []
        if isinstance(upstream_body, dict):
            candidate = upstream_body.get("data") or upstream_body.get("models") or []
            if isinstance(candidate, list):
                models = candidate
        return JSONResponse({"object": "list", "data": models, "models": models})

    @app.post("/v1/responses")
    async def handle_responses(request: Request) -> Response:
        body = await request.body()
        try:
            payload = json.loads(body)
            req = ResponsesRequest.from_dict(payload)
        except Exception as exc:
            logger.error("JSON parse error: %s", exc)
            logger.error("body prefix: %s", body[:200].decode("utf-8", errors="replace"))
            return PlainTextResponse(str(exc), status_code=422)

        logger.debug(
            "-> model=%s stream=%s input_items=%s tools=%s prev_resp=%s",
            req.model,
            req.stream,
            len(req.input.value) if req.input.kind == "messages" else 1,
            len(req.tools),
            req.previous_response_id,
        )
        logger.debug("-> response tools=%s", summarize_debug_names(response_tool_debug_names(req.tools)))
        return await handle_responses_inner(state, req)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def handle_fallback(path: str, request: Request) -> Response:
        del path
        logger.warning("unhandled %s %s", request.method, request.url.path)
        return PlainTextResponse("not found", status_code=404)

    return app


async def _cleanup_sessions(sessions: SessionStore) -> None:
    while True:
        await asyncio.sleep(60 * 60)
        sessions.cleanup()


async def handle_responses_inner(state: AppState, req: ResponsesRequest) -> Response:
    history = state.sessions.get_history(req.previous_response_id) if req.previous_response_id else []
    if should_isolate_spawn_child_request(req, history):
        logger.debug("isolating spawned child request from parent response history")
        history = []

    model = req.model
    chat_req = to_chat_request(req, history, state.sessions)
    logger.debug("-> upstream tools=%s", summarize_debug_names(chat_tool_debug_names(chat_req.tools)))
    url = f"{join_base(state.upstream)}chat/completions"

    if req.stream:
        response_id = state.sessions.new_id()
        chat_req.stream = True
        request_messages = list(chat_req.messages)
        return StreamingResponse(
            translate_stream(
                StreamArgs(
                    client=state.client,
                    url=url,
                    api_key=state.api_key,
                    chat_req=chat_req,
                    response_id=response_id,
                    sessions=state.sessions,
                    request_messages=request_messages,
                    model=model,
                )
            ),
            media_type="text/event-stream",
        )
    chat_req.stream = False
    return await handle_blocking(state, chat_req, url, model)


async def handle_blocking(
    state: AppState,
    chat_req,
    url: str,
    model: str,
) -> Response:
    headers = {"Content-Type": "application/json"}
    if state.api_key:
        headers["Authorization"] = f"Bearer {state.api_key}"
    try:
        response = await state.client.post(url, headers=headers, json=chat_req.to_dict())
    except httpx.RequestError as exc:
        logger.error("upstream error: %s", exc)
        return PlainTextResponse(str(exc), status_code=502)

    if response.status_code >= 400:
        body = response.text
        logger.error("upstream %s: %s", response.status_code, body)
        return PlainTextResponse(body, status_code=response.status_code)

    try:
        chat_resp = ChatResponse.from_dict(response.json())
    except Exception as exc:
        logger.error("parse error: %s", exc)
        return PlainTextResponse(str(exc), status_code=500)

    logger.debug(
        "<- upstream function_calls=%s",
        summarize_debug_names(chat_response_tool_call_debug_names(chat_resp)),
    )
    assistant_msg = chat_resp.choices[0].message if chat_resp.choices else ChatMessage(role="assistant", content="")
    full_history = list(chat_req.messages)
    full_history.append(assistant_msg)
    response_id = state.sessions.save(full_history)
    resp, _ = from_chat_response(response_id, model, chat_resp)
    return JSONResponse(resp)
