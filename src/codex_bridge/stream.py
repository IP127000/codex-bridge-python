from __future__ import annotations

import json
import logging
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .session import SessionStore
from .translate import split_mcp_function_name
from .types import ChatMessage, ChatRequest, ChatStreamChunk, ChatUsage

logger = logging.getLogger("codex_bridge")


def sse_event(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")


@dataclass(slots=True)
class StreamArgs:
    client: httpx.AsyncClient
    url: str
    api_key: str
    chat_req: ChatRequest
    response_id: str
    sessions: SessionStore
    request_messages: list[ChatMessage]
    model: str


@dataclass(slots=True)
class ToolCallAccum:
    id: str = ""
    name: str = ""
    arguments: str = ""


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    event_name = ""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
            event_name = ""
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
    if data_lines:
        yield "\n".join(data_lines)
    _ = event_name


def summarize_stream_tool_call_names(tool_calls: "OrderedDict[int, ToolCallAccum]") -> str:
    if not tool_calls:
        return "(none)"
    return ", ".join(tool_call.name for tool_call in tool_calls.values())


async def translate_stream(args: StreamArgs) -> AsyncIterator[bytes]:
    msg_item_id = f"msg_{uuid.uuid4().hex}"
    yield sse_event(
        "response.created",
        {
            "type": "response.created",
            "response": {"id": args.response_id, "status": "in_progress", "model": args.model},
        },
    )

    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    try:
        async with args.client.stream("POST", args.url, headers=headers, json=args.chat_req.to_dict()) as response:
            if response.status_code >= 400:
                body = await response.aread()
                message = body.decode("utf-8", errors="replace")
                logger.error("upstream %s: %s", response.status_code, message)
                yield sse_event(
                    "response.failed",
                    {
                        "type": "response.failed",
                        "response": {
                            "id": args.response_id,
                            "status": "failed",
                            "error": {"code": str(response.status_code), "message": message},
                        },
                    },
                )
                return

            accumulated_text = ""
            accumulated_reasoning = ""
            tool_calls: OrderedDict[int, ToolCallAccum] = OrderedDict()
            emitted_message_item = False
            stream_done = False
            stream_usage: ChatUsage | None = None

            async for data in _iter_sse_data(response):
                if data.strip() == "[DONE]":
                    stream_done = True
                    break
                if not data:
                    continue
                try:
                    chunk = ChatStreamChunk.from_dict(json.loads(data))
                except Exception as exc:
                    logger.warning("chunk parse error: %s — data: %s", exc, data)
                    continue

                if chunk.usage is not None:
                    stream_usage = chunk.usage

                for choice in chunk.choices:
                    if choice.delta.reasoning_content:
                        accumulated_reasoning += choice.delta.reasoning_content

                    content = choice.delta.content or ""
                    if content:
                        if not emitted_message_item:
                            yield sse_event(
                                "response.output_item.added",
                                {
                                    "type": "response.output_item.added",
                                    "output_index": 0,
                                    "item": {
                                        "type": "message",
                                        "id": msg_item_id,
                                        "role": "assistant",
                                        "status": "in_progress",
                                        "content": [],
                                    },
                                },
                            )
                            emitted_message_item = True
                        accumulated_text += content
                        yield sse_event(
                            "response.output_text.delta",
                            {
                                "type": "response.output_text.delta",
                                "item_id": msg_item_id,
                                "output_index": 0,
                                "delta": content,
                            },
                        )

                    for tool_call in choice.delta.tool_calls or []:
                        entry = tool_calls.setdefault(tool_call.index, ToolCallAccum())
                        if tool_call.id:
                            entry.id = tool_call.id
                        if tool_call.function:
                            if tool_call.function.name:
                                entry.name += tool_call.function.name
                            if tool_call.function.arguments:
                                entry.arguments += tool_call.function.arguments

    except httpx.RequestError as exc:
        logger.error("upstream request failed: %s", exc)
        yield sse_event(
            "response.failed",
            {
                "type": "response.failed",
                "response": {
                    "id": args.response_id,
                    "status": "failed",
                    "error": {"code": "connection_error", "message": str(exc)},
                },
            },
        )
        return

    if emitted_message_item:
        yield sse_event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "message",
                    "id": msg_item_id,
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": accumulated_text}],
                },
            },
        )

    base_index = 1 if emitted_message_item else 0
    final_function_items: list[dict[str, Any]] = []
    logger.debug("← upstream stream function_calls=%s", summarize_stream_tool_call_names(tool_calls))
    for relative_index, tool_call in enumerate(tool_calls.values()):
        item_id = f"fc_{uuid.uuid4().hex}"
        output_index = base_index + relative_index
        namespace, name = split_mcp_function_name(tool_call.name)
        added_item = {
            "type": "function_call",
            "id": item_id,
            "call_id": tool_call.id,
            "name": name,
            "arguments": "",
            "status": "in_progress",
        }
        done_item = {
            "type": "function_call",
            "id": item_id,
            "call_id": tool_call.id,
            "name": name,
            "arguments": tool_call.arguments,
            "status": "completed",
        }
        if namespace is not None:
            added_item["namespace"] = namespace
            done_item["namespace"] = namespace

        yield sse_event(
            "response.output_item.added",
            {
                "type": "response.output_item.added",
                "output_index": output_index,
                "item": added_item,
            },
        )
        if tool_call.arguments:
            yield sse_event(
                "response.function_call_arguments.delta",
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": item_id,
                    "output_index": output_index,
                    "delta": tool_call.arguments,
                },
            )
        yield sse_event(
            "response.output_item.done",
            {
                "type": "response.output_item.done",
                "output_index": output_index,
                "item": done_item,
            },
        )
        final_function_items.append(done_item)

    if not stream_done:
        logger.warning("stream disconnected before [DONE] — discarding partial turn")
        yield sse_event(
            "response.failed",
            {
                "type": "response.failed",
                "response": {
                    "id": args.response_id,
                    "status": "failed",
                    "error": {
                        "code": "stream_incomplete",
                        "message": "stream disconnected before completion",
                    },
                },
            },
        )
        return

    for tool_call in tool_calls.values():
        if tool_call.id:
            args.sessions.store_reasoning(tool_call.id, accumulated_reasoning)

    assistant_tool_calls = None
    if tool_calls:
        assistant_tool_calls = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {"name": tool_call.name, "arguments": tool_call.arguments},
            }
            for tool_call in tool_calls.values()
        ]
    assistant_message = ChatMessage(
        role="assistant",
        content=accumulated_text if accumulated_text else None,
        reasoning_content=accumulated_reasoning or None,
        tool_calls=assistant_tool_calls,
    )
    if accumulated_reasoning:
        args.sessions.store_turn_reasoning(args.request_messages, assistant_message, accumulated_reasoning)

    messages = list(args.request_messages)
    messages.append(assistant_message)
    args.sessions.save_with_id(args.response_id, messages)

    output_items: list[dict[str, Any]] = []
    if emitted_message_item:
        output_items.append(
            {
                "type": "message",
                "id": msg_item_id,
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": accumulated_text}],
            }
        )
    output_items.extend(final_function_items)
    usage = stream_usage or ChatUsage()

    yield sse_event(
        "response.completed",
        {
            "type": "response.completed",
            "response": {
                "id": args.response_id,
                "status": "completed",
                "model": args.model,
                "output": output_items,
                "usage": {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "total_tokens": usage.total_tokens,
                },
            },
        },
    )
