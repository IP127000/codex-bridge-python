from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path
from typing import Any

from .types import ChatMessage

logger = logging.getLogger("codex_bridge")

DEFAULT_MAX_SESSIONS = 256
DEFAULT_MAX_SESSION_BYTES = 512 * 1024 * 1024
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _now() -> float:
    return time.time()


def _content_key(content: str) -> int:
    return int.from_bytes(blake2b(content.encode("utf-8"), digest_size=8).digest(), "big")


def _encode_key(key: str) -> str:
    out: list[str] = []
    for byte in key.encode("utf-8"):
        if (
            ord("a") <= byte <= ord("z")
            or ord("A") <= byte <= ord("Z")
            or ord("0") <= byte <= ord("9")
            or byte in {ord("_"), ord("-"), ord(".")}
        ):
            out.append(chr(byte))
        else:
            out.append(f"%{byte:02X}")
    return "".join(out)


def _value_bytes(value: Any) -> int:
    if value is None or isinstance(value, (bool, int, float)):
        return 8
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_value_bytes(item) for item in value)
    if isinstance(value, dict):
        return sum(len(str(key)) + _value_bytes(item) for key, item in value.items())
    return len(str(value))


def _message_bytes(message: ChatMessage) -> int:
    return (
        len(message.role)
        + _value_bytes(message.content)
        + len(message.reasoning_content or "")
        + sum(_value_bytes(call) for call in (message.tool_calls or []))
        + len(message.tool_call_id or "")
        + len(message.name or "")
    )


def _messages_bytes(messages: list[ChatMessage]) -> int:
    return sum(_message_bytes(message) for message in messages)


@dataclass(slots=True)
class SessionEntry:
    messages: list[ChatMessage] | None
    bytes: int
    last_used_at: float


@dataclass(slots=True)
class StoredString:
    value: str | None
    bytes: int
    last_used_at: float


class DiskStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.reasoning_dir.mkdir(parents=True, exist_ok=True)
        self.turns_dir.mkdir(parents=True, exist_ok=True)

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def reasoning_dir(self) -> Path:
        return self.root / "reasoning"

    @property
    def turns_dir(self) -> Path:
        return self.root / "turns"

    def session_path(self, response_id: str) -> Path:
        return self.sessions_dir / f"{_encode_key(response_id)}.json"

    def reasoning_path(self, key: str) -> Path:
        return self.reasoning_dir / f"{_encode_key(key)}.json"

    def turn_path(self, key: int) -> Path:
        return self.turns_dir / f"{key}.json"

    def write_session(
        self,
        response_id: str,
        created_at: float,
        last_used_at: float,
        size_bytes: int,
        messages: list[ChatMessage],
    ) -> None:
        self._write_json(
            self.session_path(response_id),
            {
                "schema_version": 1,
                "response_id": response_id,
                "created_at_unix_ms": int(created_at * 1000),
                "last_used_at_unix_ms": int(last_used_at * 1000),
                "bytes": size_bytes,
                "messages": [message.to_dict() for message in messages],
            },
        )

    def read_session(self, response_id: str) -> dict[str, Any] | None:
        return self._read_json(self.session_path(response_id))

    def write_reasoning(
        self,
        key: str,
        created_at: float,
        last_used_at: float,
        size_bytes: int,
        value: str,
    ) -> None:
        self._write_json(
            self.reasoning_path(key),
            {
                "schema_version": 1,
                "key": key,
                "created_at_unix_ms": int(created_at * 1000),
                "last_used_at_unix_ms": int(last_used_at * 1000),
                "bytes": size_bytes,
                "value": value,
            },
        )

    def read_reasoning(self, key: str) -> dict[str, Any] | None:
        return self._read_json(self.reasoning_path(key))

    def write_turn_reasoning(
        self,
        key: str,
        created_at: float,
        last_used_at: float,
        size_bytes: int,
        value: str,
    ) -> None:
        self._write_json(
            self.turn_path(int(key)),
            {
                "schema_version": 1,
                "key": key,
                "created_at_unix_ms": int(created_at * 1000),
                "last_used_at_unix_ms": int(last_used_at * 1000),
                "bytes": size_bytes,
                "value": value,
            },
        )

    def read_turn_reasoning(self, key: int) -> dict[str, Any] | None:
        return self._read_json(self.turn_path(key))

    def load_sessions(self) -> list[dict[str, Any]]:
        return self._load_records(self.sessions_dir)

    def load_reasoning(self) -> list[dict[str, Any]]:
        return self._load_records(self.reasoning_dir)

    def load_turn_reasoning(self) -> list[dict[str, Any]]:
        return self._load_records(self.turns_dir)

    def remove_session(self, response_id: str) -> None:
        self._remove_file(self.session_path(response_id))

    def remove_reasoning(self, key: str) -> None:
        self._remove_file(self.reasoning_path(key))

    def remove_turn_reasoning(self, key: int) -> None:
        self._remove_file(self.turn_path(key))

    def _load_records(self, directory: Path) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in directory.iterdir():
            record = self._read_json(path)
            if record is None:
                logger.warning("ignoring corrupt disk history record %s", path)
                continue
            records.append(record)
        return records

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        tmp = path.with_suffix(f"{path.suffix}.tmp-{uuid.uuid4().hex}")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _remove_file(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            logger.warning("failed to remove disk history record %s: %s", path, exc)


class SessionStore:
    def __init__(
        self,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
        max_stored_bytes: int = DEFAULT_MAX_SESSION_BYTES,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        disk_root: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.sessions: dict[str, SessionEntry] = {}
        self.session_order: deque[str] = deque()
        self.reasoning: dict[str, StoredString] = {}
        self.reasoning_order: deque[str] = deque()
        self.turn_reasoning: dict[int, StoredString] = {}
        self.turn_reasoning_order: deque[int] = deque()
        self.stored_bytes = 0
        self.max_sessions = max(max_sessions, 1)
        self.max_stored_bytes = max(max_stored_bytes, 1)
        self.ttl_seconds = max(ttl_seconds, 1)
        self.disk = DiskStore(disk_root) if disk_root is not None else None
        self._load_disk_index()
        self._enforce_limits()

    @classmethod
    def with_disk_limits_and_ttl(
        cls,
        root: Path,
        max_sessions: int,
        max_stored_bytes: int,
        ttl_seconds: int,
    ) -> "SessionStore":
        return cls(max_sessions, max_stored_bytes, ttl_seconds, root)

    def store_reasoning(self, call_id: str, reasoning: str) -> None:
        if not reasoning:
            return
        with self._lock:
            self._insert_reasoning(call_id, reasoning)
            self._enforce_limits()

    def get_reasoning(self, call_id: str) -> str | None:
        with self._lock:
            self._enforce_limits()
            value = self._load_reasoning_value(call_id)
            if value is not None:
                self._touch_reasoning(call_id)
            return value

    def store_turn_reasoning(
        self,
        prior: list[ChatMessage],
        assistant: ChatMessage,
        reasoning: str,
    ) -> None:
        del prior
        if not reasoning:
            return
        content = assistant.text_content()
        with self._lock:
            if content:
                self._insert_turn_reasoning(_content_key(content), reasoning)
            for tool_call in assistant.tool_calls or []:
                call_id = tool_call.get("id")
                if isinstance(call_id, str) and call_id:
                    self._insert_reasoning(call_id, reasoning)
            self._enforce_limits()

    def get_turn_reasoning(
        self,
        prior: list[ChatMessage],
        assistant: ChatMessage,
    ) -> str | None:
        del prior
        content = assistant.text_content()
        if not content:
            return None
        key = _content_key(content)
        with self._lock:
            self._enforce_limits()
            value = self._load_turn_reasoning_value(key)
            if value is not None:
                self._touch_turn_reasoning(key)
            return value

    def get_history(self, response_id: str) -> list[ChatMessage]:
        with self._lock:
            self._enforce_limits()
            messages = self._load_session_messages(response_id)
            if messages:
                self._touch_session(response_id)
            return messages

    def new_id(self) -> str:
        return f"resp_{uuid.uuid4().hex}"

    def save_with_id(self, response_id: str, messages: list[ChatMessage]) -> None:
        with self._lock:
            self._insert_session(response_id, messages)
            self._enforce_limits()

    def save(self, messages: list[ChatMessage]) -> str:
        response_id = self.new_id()
        self.save_with_id(response_id, messages)
        return response_id

    def cleanup(self) -> None:
        with self._lock:
            self._enforce_limits()

    def _load_disk_index(self) -> None:
        if self.disk is None:
            return

        sessions = sorted(self.disk.load_sessions(), key=lambda record: record.get("last_used_at_unix_ms", 0))
        for record in sessions:
            response_id = str(record.get("response_id", ""))
            if not response_id:
                continue
            last_used_at = float(record.get("last_used_at_unix_ms", 0)) / 1000
            size_bytes = int(record.get("bytes", 0) or 0)
            self.stored_bytes += size_bytes
            self.sessions[response_id] = SessionEntry(messages=None, bytes=size_bytes, last_used_at=last_used_at)
            self.session_order.append(response_id)

        reasoning = sorted(self.disk.load_reasoning(), key=lambda record: record.get("last_used_at_unix_ms", 0))
        for record in reasoning:
            key = str(record.get("key", ""))
            if not key:
                continue
            last_used_at = float(record.get("last_used_at_unix_ms", 0)) / 1000
            size_bytes = int(record.get("bytes", 0) or 0)
            self.stored_bytes += size_bytes
            self.reasoning[key] = StoredString(value=None, bytes=size_bytes, last_used_at=last_used_at)
            self.reasoning_order.append(key)

        turn_reasoning = sorted(
            self.disk.load_turn_reasoning(),
            key=lambda record: record.get("last_used_at_unix_ms", 0),
        )
        for record in turn_reasoning:
            try:
                key = int(record.get("key", ""))
            except (TypeError, ValueError):
                logger.warning("ignoring disk turn reasoning record with invalid key %s", record.get("key"))
                continue
            last_used_at = float(record.get("last_used_at_unix_ms", 0)) / 1000
            size_bytes = int(record.get("bytes", 0) or 0)
            self.stored_bytes += size_bytes
            self.turn_reasoning[key] = StoredString(value=None, bytes=size_bytes, last_used_at=last_used_at)
            self.turn_reasoning_order.append(key)

    def _insert_session(self, response_id: str, messages: list[ChatMessage]) -> None:
        size_bytes = _messages_bytes(messages)
        if size_bytes > self.max_stored_bytes:
            self._remove_session(response_id)
            logger.warning(
                "session %s is %s bytes, above %s byte retention limit; not caching history",
                response_id,
                size_bytes,
                self.max_stored_bytes,
            )
            return

        self._remove_session(response_id)
        now = _now()
        stored_messages: list[ChatMessage] | None = messages
        if self.disk is not None:
            try:
                self.disk.write_session(response_id, now, now, size_bytes, messages)
                stored_messages = None
            except OSError as exc:
                logger.warning("failed to persist session %s: %s", response_id, exc)

        self.stored_bytes += size_bytes
        self.sessions[response_id] = SessionEntry(messages=stored_messages, bytes=size_bytes, last_used_at=now)
        self.session_order.append(response_id)

    def _insert_reasoning(self, call_id: str, reasoning: str) -> None:
        old = self.reasoning.pop(call_id, None)
        if old is not None:
            self.stored_bytes -= old.bytes
        self.reasoning_order = deque(key for key in self.reasoning_order if key != call_id)

        size_bytes = len(call_id) + len(reasoning)
        now = _now()
        stored_value: str | None = reasoning
        if self.disk is not None:
            try:
                self.disk.write_reasoning(call_id, now, now, size_bytes, reasoning)
                stored_value = None
            except OSError as exc:
                logger.warning("failed to persist reasoning %s: %s", call_id, exc)

        self.stored_bytes += size_bytes
        self.reasoning[call_id] = StoredString(value=stored_value, bytes=size_bytes, last_used_at=now)
        self.reasoning_order.append(call_id)

    def _insert_turn_reasoning(self, key: int, reasoning: str) -> None:
        old = self.turn_reasoning.pop(key, None)
        if old is not None:
            self.stored_bytes -= old.bytes
        self.turn_reasoning_order = deque(item for item in self.turn_reasoning_order if item != key)

        size_bytes = 8 + len(reasoning)
        key_string = str(key)
        now = _now()
        stored_value: str | None = reasoning
        if self.disk is not None:
            try:
                self.disk.write_turn_reasoning(key_string, now, now, size_bytes, reasoning)
                stored_value = None
            except OSError as exc:
                logger.warning("failed to persist turn reasoning %s: %s", key, exc)

        self.stored_bytes += size_bytes
        self.turn_reasoning[key] = StoredString(value=stored_value, bytes=size_bytes, last_used_at=now)
        self.turn_reasoning_order.append(key)

    def _enforce_limits(self) -> None:
        self._remove_expired()
        while len(self.sessions) > self.max_sessions:
            self._remove_oldest_session()
        while self.stored_bytes > self.max_stored_bytes and len(self.sessions) > 1:
            self._remove_oldest_session()
        while self.stored_bytes > self.max_stored_bytes and self.reasoning_order:
            self._remove_oldest_reasoning()
        while self.stored_bytes > self.max_stored_bytes and self.turn_reasoning_order:
            self._remove_oldest_turn_reasoning()

    def _remove_expired(self) -> None:
        cutoff = _now() - self.ttl_seconds

        while self.session_order:
            response_id = self.session_order[0]
            entry = self.sessions.get(response_id)
            if entry is None or entry.last_used_at > cutoff:
                break
            self._remove_oldest_session()

        while self.reasoning_order:
            key = self.reasoning_order[0]
            entry = self.reasoning.get(key)
            if entry is None or entry.last_used_at > cutoff:
                break
            self._remove_oldest_reasoning()

        while self.turn_reasoning_order:
            key = self.turn_reasoning_order[0]
            entry = self.turn_reasoning.get(key)
            if entry is None or entry.last_used_at > cutoff:
                break
            self._remove_oldest_turn_reasoning()

    def _remove_oldest_session(self) -> None:
        if self.session_order:
            self._remove_session_entry(self.session_order.popleft())

    def _remove_session(self, response_id: str) -> None:
        self.session_order = deque(item for item in self.session_order if item != response_id)
        self._remove_session_entry(response_id)

    def _remove_session_entry(self, response_id: str) -> None:
        entry = self.sessions.pop(response_id, None)
        if entry is not None:
            self.stored_bytes -= entry.bytes
        if self.disk is not None:
            self.disk.remove_session(response_id)

    def _remove_oldest_reasoning(self) -> None:
        if not self.reasoning_order:
            return
        key = self.reasoning_order.popleft()
        entry = self.reasoning.pop(key, None)
        if entry is not None:
            self.stored_bytes -= entry.bytes
        if self.disk is not None:
            self.disk.remove_reasoning(key)

    def _remove_oldest_turn_reasoning(self) -> None:
        if not self.turn_reasoning_order:
            return
        key = self.turn_reasoning_order.popleft()
        entry = self.turn_reasoning.pop(key, None)
        if entry is not None:
            self.stored_bytes -= entry.bytes
        if self.disk is not None:
            self.disk.remove_turn_reasoning(key)

    def _touch_session(self, response_id: str) -> None:
        now = _now()
        entry = self.sessions.get(response_id)
        if entry is not None:
            entry.last_used_at = now
        if self.disk is not None:
            record = self.disk.read_session(response_id)
            if record is not None:
                record["last_used_at_unix_ms"] = int(now * 1000)
                try:
                    self.disk._write_json(self.disk.session_path(response_id), record)
                except OSError as exc:
                    logger.warning("failed to touch disk session %s: %s", response_id, exc)
        self.session_order = deque(item for item in self.session_order if item != response_id)
        self.session_order.append(response_id)

    def _touch_reasoning(self, call_id: str) -> None:
        now = _now()
        entry = self.reasoning.get(call_id)
        if entry is not None:
            entry.last_used_at = now
        if self.disk is not None:
            record = self.disk.read_reasoning(call_id)
            if record is not None:
                record["last_used_at_unix_ms"] = int(now * 1000)
                try:
                    self.disk._write_json(self.disk.reasoning_path(call_id), record)
                except OSError as exc:
                    logger.warning("failed to touch disk reasoning %s: %s", call_id, exc)
        self.reasoning_order = deque(item for item in self.reasoning_order if item != call_id)
        self.reasoning_order.append(call_id)

    def _touch_turn_reasoning(self, key: int) -> None:
        now = _now()
        entry = self.turn_reasoning.get(key)
        if entry is not None:
            entry.last_used_at = now
        if self.disk is not None:
            record = self.disk.read_turn_reasoning(key)
            if record is not None:
                record["last_used_at_unix_ms"] = int(now * 1000)
                try:
                    self.disk._write_json(self.disk.turn_path(key), record)
                except OSError as exc:
                    logger.warning("failed to touch disk turn reasoning %s: %s", key, exc)
        self.turn_reasoning_order = deque(item for item in self.turn_reasoning_order if item != key)
        self.turn_reasoning_order.append(key)

    def _load_session_messages(self, response_id: str) -> list[ChatMessage]:
        entry = self.sessions.get(response_id)
        if entry is None:
            return []
        if entry.messages is not None:
            return list(entry.messages)
        if self.disk is None:
            return []
        record = self.disk.read_session(response_id)
        if record is None:
            return []
        return [ChatMessage.from_dict(message) for message in record.get("messages") or []]

    def _load_reasoning_value(self, call_id: str) -> str | None:
        entry = self.reasoning.get(call_id)
        if entry is None:
            return None
        if entry.value is not None:
            return entry.value
        if self.disk is None:
            return None
        record = self.disk.read_reasoning(call_id)
        return None if record is None else record.get("value")

    def _load_turn_reasoning_value(self, key: int) -> str | None:
        entry = self.turn_reasoning.get(key)
        if entry is None:
            return None
        if entry.value is not None:
            return entry.value
        if self.disk is None:
            return None
        record = self.disk.read_turn_reasoning(key)
        return None if record is None else record.get("value")
