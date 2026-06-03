from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


JSON = dict[str, Any] | list[Any] | str | int | float | bool | None


@dataclass(slots=True)
class ResponsesInput:
    kind: str
    value: str | list[dict[str, Any]]

    @classmethod
    def from_raw(cls, raw: Any) -> "ResponsesInput":
        if isinstance(raw, str):
            return cls(kind="text", value=raw)
        if isinstance(raw, list):
            return cls(kind="messages", value=raw)
        raise ValueError("input must be a string or array")


@dataclass(slots=True)
class ResponsesRequest:
    model: str
    input: ResponsesInput
    previous_response_id: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    stream: bool = False
    temperature: float | None = None
    max_output_tokens: int | None = None
    system: str | None = None
    instructions: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResponsesRequest":
        return cls(
            model=str(payload["model"]),
            input=ResponsesInput.from_raw(payload["input"]),
            previous_response_id=payload.get("previous_response_id"),
            tools=list(payload.get("tools") or []),
            stream=bool(payload.get("stream", False)),
            temperature=payload.get("temperature"),
            max_output_tokens=payload.get("max_output_tokens"),
            system=payload.get("system"),
            instructions=payload.get("instructions"),
        )


@dataclass(slots=True)
class ChatStreamOptions:
    include_usage: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"include_usage": self.include_usage}


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: Any = None
    reasoning_content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def text_content(self) -> str:
        return self.content if isinstance(self.content, str) else ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.reasoning_content is not None:
            payload["reasoning_content"] = self.reasoning_content
        if self.tool_calls is not None:
            payload["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        return cls(
            role=payload["role"],
            content=payload.get("content"),
            reasoning_content=payload.get("reasoning_content"),
            tool_calls=payload.get("tool_calls"),
            tool_call_id=payload.get("tool_call_id"),
            name=payload.get("name"),
        )


@dataclass(slots=True)
class ChatRequest:
    model: str
    messages: list[ChatMessage]
    tools: list[dict[str, Any]]
    temperature: float | None
    max_tokens: int | None
    stream_options: ChatStreamOptions | None
    stream: bool

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_dict() for message in self.messages],
            "stream": self.stream,
        }
        if self.tools:
            payload["tools"] = self.tools
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if self.stream_options is not None:
            payload["stream_options"] = self.stream_options.to_dict()
        return payload


@dataclass(slots=True)
class ChatUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ChatUsage":
        payload = payload or {}
        return cls(
            prompt_tokens=int(payload.get("prompt_tokens", 0) or 0),
            completion_tokens=int(payload.get("completion_tokens", 0) or 0),
            total_tokens=int(payload.get("total_tokens", 0) or 0),
        )


@dataclass(slots=True)
class ChatChoice:
    message: ChatMessage

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatChoice":
        return cls(message=ChatMessage.from_dict(payload.get("message") or {}))


@dataclass(slots=True)
class ChatResponse:
    choices: list[ChatChoice]
    usage: ChatUsage | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatResponse":
        return cls(
            choices=[ChatChoice.from_dict(choice) for choice in payload.get("choices") or []],
            usage=ChatUsage.from_dict(payload.get("usage")) if payload.get("usage") is not None else None,
        )


@dataclass(slots=True)
class ChatDeltaFunction:
    name: str | None = None
    arguments: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ChatDeltaFunction":
        payload = payload or {}
        return cls(name=payload.get("name"), arguments=payload.get("arguments"))


@dataclass(slots=True)
class DeltaToolCall:
    index: int
    id: str | None = None
    function: ChatDeltaFunction | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DeltaToolCall":
        return cls(
            index=int(payload.get("index", 0)),
            id=payload.get("id"),
            function=ChatDeltaFunction.from_dict(payload.get("function")),
        )


@dataclass(slots=True)
class ChatDelta:
    role: str | None = None
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[DeltaToolCall] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ChatDelta":
        payload = payload or {}
        tool_calls = payload.get("tool_calls")
        return cls(
            role=payload.get("role"),
            content=payload.get("content"),
            reasoning_content=payload.get("reasoning_content"),
            tool_calls=[DeltaToolCall.from_dict(item) for item in tool_calls] if tool_calls else None,
        )


@dataclass(slots=True)
class ChatStreamChoice:
    delta: ChatDelta
    finish_reason: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatStreamChoice":
        return cls(
            delta=ChatDelta.from_dict(payload.get("delta")),
            finish_reason=payload.get("finish_reason"),
        )


@dataclass(slots=True)
class ChatStreamChunk:
    choices: list[ChatStreamChoice]
    usage: ChatUsage | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatStreamChunk":
        return cls(
            choices=[ChatStreamChoice.from_dict(choice) for choice in payload.get("choices") or []],
            usage=ChatUsage.from_dict(payload.get("usage")) if payload.get("usage") is not None else None,
        )
