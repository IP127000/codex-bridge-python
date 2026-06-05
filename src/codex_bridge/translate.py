from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from .config import env_value
from .session import SessionStore
from .types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatStreamOptions,
    ChatUsage,
    ResponsesInput,
    ResponsesRequest,
)


def to_chat_request(
    req: ResponsesRequest,
    history: list[ChatMessage],
    sessions: SessionStore,
    *,
    force_default_model: bool = False,
    default_model: str = "deepseek-v4-flash",
) -> ChatRequest:
    messages = list(history)

    system_text = req.instructions or req.system
    if system_text:
        system_message = ChatMessage(role="system", content=system_text)
        if not messages or messages[0].role != "system":
            messages.insert(0, system_message)

    if req.input.kind == "text":
        messages.append(ChatMessage(role="user", content=req.input.value))
    else:
        items = list(req.input.value)
        existing_call_ids = {
            call_id
            for message in messages
            for call_id in _message_call_ids(message)
        }
        existing_tool_responses = {
            message.tool_call_id
            for message in messages
            if message.tool_call_id
        }

        index = 0
        while index < len(items):
            item = items[index]
            item_type = item.get("type", "")

            if item_type == "function_call":
                call_id = item.get("call_id", "")
                if call_id in existing_call_ids:
                    index += 1
                    continue

                grouped: list[dict[str, Any]] = []
                reasoning_content: str | None = None

                while index < len(items) and items[index].get("type", "") == "function_call":
                    current = items[index]
                    current_call_id = current.get("call_id", "")
                    if current_call_id in existing_call_ids:
                        index += 1
                        continue
                    name = response_function_name_for_chat(current)
                    arguments = current.get("arguments", "{}")
                    if reasoning_content is None and current_call_id:
                        reasoning_content = sessions.get_reasoning(current_call_id)
                    grouped.append(
                        {
                            "id": current_call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    )
                    index += 1

                message = ChatMessage(
                    role="assistant",
                    content=None,
                    reasoning_content=reasoning_content,
                    tool_calls=grouped,
                )
                if message.reasoning_content is None:
                    message.reasoning_content = sessions.get_turn_reasoning(messages, message)
                messages.append(message)
                continue

            if item_type == "function_call_output":
                call_id = item.get("call_id", "")
                if call_id in existing_tool_responses:
                    index += 1
                    continue
                output = item.get("output", "")
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=output,
                        tool_call_id=call_id,
                    )
                )
            elif item_type == "reasoning":
                pass
            else:
                role = item.get("role", "user")
                if role == "developer":
                    role = "system"
                message = ChatMessage(
                    role=role,
                    content=value_to_chat_content(item.get("content")),
                )
                if message.role == "assistant":
                    message.reasoning_content = sessions.get_turn_reasoning(messages, message)
                if message.role == "system":
                    if messages and messages[0].role == "system":
                        messages[0] = message
                    else:
                        messages.insert(0, message)
                else:
                    messages.append(message)
            index += 1

    return ChatRequest(
        model=map_model_name(
            req.model,
            force_default_model=force_default_model,
            default_model=default_model,
        ),
        messages=messages,
        tools=convert_tools(req.tools),
        temperature=req.temperature,
        max_tokens=req.max_output_tokens,
        stream_options=ChatStreamOptions(include_usage=True) if req.stream else None,
        stream=req.stream,
    )


def map_model_name(
    name: str,
    *,
    force_default_model: bool = False,
    default_model: str = "deepseek-v4-flash",
) -> str:
    effective_default_model = default_model.strip() or "deepseek-v4-flash"
    if force_default_model:
        return effective_default_model
    mapping = env_value("CODEX_BRIDGE_MODEL_MAP", default="")
    for pair in mapping.split(","):
        if ":" not in pair:
            continue
        source, target = pair.split(":", 1)
        if name == source.strip():
            return target.strip()
    return name


def convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    denied = {
        name.strip()
        for name in env_value("CODEX_BRIDGE_TOOL_DENYLIST", default="").split(",")
        if name.strip()
    }
    return convert_tools_with_denylist(tools, denied)


def convert_tools_with_denylist(
    tools: list[dict[str, Any]],
    denied: set[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for tool in tools:
        tool_type = tool.get("type")
        if tool_type == "function":
            if not tool_is_denied(tool, None, denied):
                output.append(convert_tool(tool))
        elif tool_type == "namespace":
            namespace = tool.get("name", "")
            for child in tool.get("tools") or []:
                if child.get("type") != "function":
                    continue
                name = chat_function_name_for_namespace_tool(namespace, child.get("name", ""))
                if not tool_is_denied(child, name, denied):
                    output.append(convert_tool_with_name(child, name))
    return output


def tool_is_denied(tool: dict[str, Any], override_name: str | None, denied: set[str]) -> bool:
    if not denied:
        return False
    name = override_name
    if not name:
        function = tool.get("function")
        if isinstance(function, dict):
            name = function.get("name")
    if not name:
        name = tool.get("name")
    return isinstance(name, str) and name in denied


def convert_tool(tool: dict[str, Any]) -> dict[str, Any]:
    return convert_tool_with_name(tool, None)


def convert_tool_with_name(tool: dict[str, Any], override_name: str | None) -> dict[str, Any]:
    if not isinstance(tool, dict):
        return tool
    if "function" in tool:
        result = json.loads(json.dumps(tool))
        if override_name and isinstance(result.get("function"), dict):
            result["function"]["name"] = override_name
        return result
    if tool.get("type") == "function":
        function: dict[str, Any] = {}
        if override_name:
            function["name"] = override_name
        elif "name" in tool:
            function["name"] = tool["name"]
        for field in ("description", "parameters", "strict"):
            if field in tool:
                function[field] = tool[field]
        return {"type": "function", "function": function}
    return json.loads(json.dumps(tool))


def response_function_name_for_chat(item: dict[str, Any]) -> str:
    name = item.get("name", "")
    namespace = item.get("namespace", "")
    if namespace:
        return chat_function_name_for_namespace_tool(namespace, name)
    return str(name)


def chat_function_name_for_namespace_tool(namespace: str, name: str) -> str:
    return f"{namespace}.{name}"


def from_chat_response(
    response_id: str,
    model: str,
    chat: ChatResponse,
) -> tuple[dict[str, Any], list[ChatMessage]]:
    choice = chat.choices[0] if chat.choices else None
    message = choice.message if choice else ChatMessage(role="assistant", content="")
    usage = chat.usage or ChatUsage()
    output: list[dict[str, Any]] = []

    text = message.text_content()
    if text or message.tool_calls is None:
        output.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        )

    for tool_call in message.tool_calls or []:
        function = tool_call.get("function") or {}
        raw_name = function.get("name", "")
        namespace, name = split_mcp_function_name(raw_name)
        arguments = function.get("arguments", "{}")
        item = {
            "type": "function_call",
            "id": f"fc_{uuid.uuid4().hex}",
            "call_id": tool_call.get("id", ""),
            "name": name,
            "arguments": arguments,
            "status": "completed",
        }
        if namespace is not None:
            item["namespace"] = namespace
        output.append(item)

    response = {
        "id": response_id,
        "object": "response",
        "model": model,
        "output": output,
        "usage": {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        },
    }
    return response, [message]


def split_mcp_function_name(name: str) -> tuple[str | None, str]:
    if "." in name:
        namespace, child = name.split(".", 1)
        if namespace and child:
            return namespace, child
    if not name.startswith("mcp__"):
        return None, name
    rest = name.removeprefix("mcp__")
    server_end = rest.find("__")
    if server_end < 0:
        return None, name
    split_at = len("mcp__") + server_end + len("__")
    if split_at >= len(name):
        return None, name
    return name[:split_at], name[split_at:]


def value_to_chat_content(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        has_non_text = any(
            (part.get("type", "") not in {"input_text", "text", "output_text"})
            for part in value
            if isinstance(part, dict)
        )
        if not has_non_text:
            return "".join(
                part.get("text", "")
                for part in value
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            )
        return [map_content_part(part) for part in value]
    return json.dumps(value, ensure_ascii=False)


def map_content_part(part: Any) -> Any:
    if not isinstance(part, dict):
        return part
    kind = part.get("type", "")
    if kind in {"input_text", "text", "output_text"}:
        return {"type": "text", "text": part.get("text", "")}
    if kind == "input_image":
        return {"type": "image_url", "image_url": {"url": part.get("image_url", "")}}
    if kind == "image_url":
        inner = part.get("image_url")
        if isinstance(inner, dict):
            normalized = inner
        elif isinstance(inner, str):
            normalized = {"url": inner}
        else:
            normalized = {"url": ""}
        return {"type": "image_url", "image_url": normalized}
    return json.loads(json.dumps(part))


def _message_call_ids(message: ChatMessage) -> Iterable[str]:
    ids: list[str] = []
    for tool_call in message.tool_calls or []:
        call_id = tool_call.get("id")
        if isinstance(call_id, str):
            ids.append(call_id)
    if message.tool_call_id:
        ids.append(message.tool_call_id)
    return ids
