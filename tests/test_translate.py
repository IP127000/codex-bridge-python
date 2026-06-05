from __future__ import annotations

import json
import os
from pathlib import Path

from codex_bridge.session import SessionStore
from codex_bridge.translate import (
    convert_tools_with_denylist,
    from_chat_response,
    split_mcp_function_name,
    to_chat_request,
)
from codex_bridge.types import ChatMessage, ChatResponse, ResponsesRequest


FIXTURES = Path(__file__).parent / "fixtures" / "codex_0_128_0"


def fixture(name: str) -> ResponsesRequest:
    return ResponsesRequest.from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_namespace_tools_are_flattened() -> None:
    req = fixture("with_namespace_tool.json")
    chat = to_chat_request(req, [], SessionStore())
    assert len(chat.tools) == 3
    names = [tool["function"]["name"] for tool in chat.tools]
    assert names == [
        "exec_command",
        "mcp__codex_apps__github._add_comment_to_issue",
        "mcp__codex_apps__github._close_issue",
    ]


def test_reasoning_input_items_are_dropped() -> None:
    req = fixture("with_reasoning_item.json")
    chat = to_chat_request(req, [], SessionStore())
    assert [message.role for message in chat.messages] == ["system", "user", "user"]
    assert [message.text_content() for message in chat.messages] == ["system", "first turn", "second turn"]


def test_input_image_becomes_chat_completions_multimodal() -> None:
    req = fixture("with_image_input.json")
    chat = to_chat_request(req, [], SessionStore())
    assert len(chat.messages) == 2
    parts = chat.messages[1].content
    assert isinstance(parts, list)
    assert parts[0] == {"type": "text", "text": "What is in this image?"}
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_from_chat_response_splits_namespace_field() -> None:
    chat = ChatResponse.from_dict(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_status",
                                "type": "function",
                                "function": {
                                    "name": "mcp__node_repl.status",
                                    "arguments": "{}",
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    response, _ = from_chat_response("resp_1", "test-model", chat)
    assert response["output"][0]["namespace"] == "mcp__node_repl"
    assert response["output"][0]["name"] == "status"


def test_split_mcp_function_name_keeps_legacy_name() -> None:
    namespace, name = split_mcp_function_name("mcp__node_repljs")
    assert namespace is None
    assert name == "mcp__node_repljs"


def test_convert_tools_denylist_filters_flat_and_namespaced_tools() -> None:
    tools = [
        {"type": "function", "name": "spawn_agent"},
        {"type": "function", "name": "exec_command"},
        {
            "type": "namespace",
            "name": "mcp__server",
            "tools": [
                {"type": "function", "name": "blocked"},
                {"type": "function", "name": "allowed"},
            ],
        },
    ]
    converted = convert_tools_with_denylist(
        tools,
        {"spawn_agent", "mcp__server.blocked"},
    )
    names = [tool["function"]["name"] for tool in converted]
    assert names == ["exec_command", "mcp__server.allowed"]


def test_model_map_env_is_honored(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_BRIDGE_MODEL_MAP", "gpt-5.4:deepseek-v4-pro")
    req = ResponsesRequest.from_dict({"model": "gpt-5.4", "input": "hi"})
    chat = to_chat_request(req, [], SessionStore())
    assert chat.model == "deepseek-v4-pro"


def test_force_default_model_overrides_request_model() -> None:
    req = ResponsesRequest.from_dict({"model": "gpt-5.4", "input": "hi"})
    chat = to_chat_request(
        req,
        [],
        SessionStore(),
        force_default_model=True,
        default_model="deepseek-v4-flash",
    )
    assert chat.model == "deepseek-v4-flash"


def test_force_default_model_uses_fallback_when_default_is_empty() -> None:
    req = ResponsesRequest.from_dict({"model": "gpt-5.4", "input": "hi"})
    chat = to_chat_request(
        req,
        [],
        SessionStore(),
        force_default_model=True,
        default_model="",
    )
    assert chat.model == "deepseek-v4-flash"


def test_history_deduplicates_replayed_function_call_output() -> None:
    history = [
        ChatMessage(
            role="tool",
            content="result",
            tool_call_id="call_1",
        )
    ]
    req = ResponsesRequest.from_dict(
        {
            "model": "mock-model",
            "input": [{"type": "function_call_output", "call_id": "call_1", "output": "result"}],
        }
    )
    chat = to_chat_request(req, history, SessionStore())
    assert chat.messages == history
