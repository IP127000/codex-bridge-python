from __future__ import annotations

import json
import threading
from collections import deque
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from fastapi.testclient import TestClient

from codex_bridge.app import create_app
from codex_bridge.config import Settings


def sse_from_chunks(chunks: list[dict[str, Any]]) -> str:
    payload = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    return payload + "data: [DONE]\n\n"


def default_ok_sse() -> str:
    return sse_from_chunks(
        [
            {"choices": [{"delta": {"role": "assistant", "content": "OK"}}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}},
        ]
    )


@dataclass
class MockUpstreamState:
    bodies: list[dict[str, Any]] = field(default_factory=list)
    responses: deque[str] = field(default_factory=deque)


class MockUpstream:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.state = MockUpstreamState(responses=deque(responses or []))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._build_handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self) -> "MockUpstream":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _build_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args) -> None:
                return

            def do_GET(self) -> None:
                if self.path == "/v1/models":
                    body = json.dumps({"data": [{"id": "mock-model"}]}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
                outer.state.bodies.append(body)
                if self.path != "/v1/chat/completions":
                    self.send_error(404)
                    return

                payload = outer.state.responses.popleft() if outer.state.responses else default_ok_sse()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(payload.encode("utf-8"))

        return Handler


def make_settings(upstream: str) -> Settings:
    return Settings(
        port=4444,
        upstream=upstream,
        api_key="",
        print_config=False,
        force_default_model=False,
        default_model="deepseek-v4-flash",
        max_sessions=256,
        max_session_memory_mb=512,
        session_ttl_hours=168,
        history_store="memory",
        history_dir=None,
    )


def parse_sse_events(raw_lines: list[str]) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = ""
    for line in raw_lines:
        if not line:
            continue
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((event_name, json.loads(line.removeprefix("data: "))))
            event_name = ""
    return events


def test_streaming_completed_event_includes_usage() -> None:
    with MockUpstream() as upstream:
        app = create_app(make_settings(upstream.base_url))
        with TestClient(app) as client:
            with client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "instructions": "Answer briefly.",
                    "input": "Say OK.",
                    "tools": [],
                    "stream": True,
                },
            ) as response:
                assert response.status_code == 200
                events = parse_sse_events(list(response.iter_lines()))

        completed = next(data for name, data in events if name == "response.completed")
        assert completed["response"]["usage"] == {
            "input_tokens": 7,
            "output_tokens": 2,
            "total_tokens": 9,
        }
        assert upstream.state.bodies[0]["stream_options"] == {"include_usage": True}


def test_streaming_namespaced_tool_calls_emit_namespace_field() -> None:
    tool_sse = sse_from_chunks(
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_js",
                                    "function": {"name": "mcp__node_repl.js", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}},
        ]
    )
    with MockUpstream([tool_sse]) as upstream:
        app = create_app(make_settings(upstream.base_url))
        with TestClient(app) as client:
            with client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "input": "Use the JS REPL.",
                    "tools": [
                        {
                            "type": "namespace",
                            "name": "mcp__node_repl",
                            "tools": [
                                {"type": "function", "name": "js", "parameters": {"type": "object"}}
                            ],
                        }
                    ],
                    "stream": True,
                },
            ) as response:
                events = parse_sse_events(list(response.iter_lines()))

        completed = next(data for name, data in events if name == "response.completed")
        item = completed["response"]["output"][0]
        assert item["type"] == "function_call"
        assert item["namespace"] == "mcp__node_repl"
        assert item["name"] == "js"
        assert upstream.state.bodies[0]["tools"][0]["function"]["name"] == "mcp__node_repl.js"


def test_spawn_agent_child_context_does_not_replay_parent_history() -> None:
    child_task = "Please compute 2+2 and return only the numeric result."
    parent_prompt = "Ask a subagent to solve 2+2."
    spawn_agent_sse = sse_from_chunks(
        [
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_spawn_simple_math",
                                    "function": {
                                        "name": "spawn_agent",
                                        "arguments": json.dumps(
                                            {"task_name": "simple_math", "message": child_task}
                                        ),
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}},
        ]
    )
    with MockUpstream([spawn_agent_sse, default_ok_sse()]) as upstream:
        app = create_app(make_settings(upstream.base_url))
        with TestClient(app) as client:
            with client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "instructions": "You are the parent agent.",
                    "input": parent_prompt,
                    "tools": [{"type": "function", "name": "spawn_agent"}],
                    "stream": True,
                },
            ) as response:
                parent_events = parse_sse_events(list(response.iter_lines()))
            parent_completed = next(data for name, data in parent_events if name == "response.completed")
            response_id = parent_completed["response"]["id"]

            with client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "mock-model",
                    "instructions": "You are the spawned child agent.",
                    "previous_response_id": response_id,
                    "input": child_task,
                    "tools": [
                        {"type": "function", "name": "spawn_agent"},
                        {"type": "function", "name": "wait_agent"},
                    ],
                    "stream": True,
                },
            ) as response:
                assert response.status_code == 200
                list(response.iter_lines())

        child_messages = upstream.state.bodies[1]["messages"]
        assert not any(message.get("content") == parent_prompt for message in child_messages)
        assert not any(
            any(call["function"]["name"] == "spawn_agent" for call in message.get("tool_calls", []))
            for message in child_messages
        )
        assert [message["content"] for message in child_messages if message["role"] == "user"] == [child_task]


def test_force_default_model_routes_all_requests_to_default_model() -> None:
    with MockUpstream() as upstream:
        settings = make_settings(upstream.base_url)
        settings.force_default_model = True
        settings.default_model = "deepseek-v4-flash"
        app = create_app(settings)
        with TestClient(app) as client:
            with client.stream(
                "POST",
                "/v1/responses",
                json={
                    "model": "gpt-5.4",
                    "input": "Say OK.",
                    "tools": [],
                    "stream": True,
                },
            ) as response:
                assert response.status_code == 200
                list(response.iter_lines())

        assert upstream.state.bodies[0]["model"] == "deepseek-v4-flash"
