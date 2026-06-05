# codex-bridge

[English](./README.md) | [简体中文](./README.zh-CN.md)

A lightweight Python proxy that translates the OpenAI **Responses API** used by
Codex into the standard **Chat Completions API**, so Codex can work with
OpenAI-compatible providers such as DashScope (Qwen), DeepSeek, Kimi,
OpenRouter, Groq, xAI, and others.

## Why

Codex speaks the OpenAI Responses API. Many non-OpenAI providers expose only
the Chat Completions API. `codex-bridge` sits between Codex and your upstream
provider, translating requests and responses on the fly so you can keep using
Codex normally.

## What It Does

- Accepts Codex `POST /v1/responses` requests locally
- Translates them into upstream `POST /v1/chat/completions`
- Converts blocking and streaming Chat Completions responses back into
  Responses API format
- Preserves session history for `previous_response_id`
- Proxies `/v1/models` and normalizes the response shape for Codex clients
- Generates a Codex config snippet with model metadata via `--print-config`

## Install

`codex-bridge` currently lives in this repository. Install it from the checkout:

```bash
python3 -m pip install .
```

For editable local development:

```bash
python3 -m pip install -e ".[dev]"
```

After installation, the `codex-bridge` command is available on your `PATH`.

## Quick Start

### Simplest launch

If you want a one-command workflow, run:

```bash
codex-bridge https://api.deepseek.com/v1 "$DEEPSEEK_API_KEY" deepseek-v4-flash
```

This mode:

- starts `codex-bridge` on `127.0.0.1:5057`
- creates a temporary `CODEX_HOME` at `./.codex-bridge-home`
- writes a minimal `config.toml` that points Codex at the local bridge
- exports your second argument as `OPENAI_API_KEY`
- uses your third argument as the model written into Codex config and the
  bridge's forced upstream model
- starts the `codex` CLI as a child process in the current directory

### 1. Start the bridge

Example with DashScope:

```bash
CODEX_BRIDGE_UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1 \
CODEX_BRIDGE_API_KEY=$DASHSCOPE_API_KEY \
CODEX_BRIDGE_PORT=4448 \
codex-bridge
```

Example with DeepSeek:

```bash
CODEX_BRIDGE_UPSTREAM=https://api.deepseek.com/v1 \
CODEX_BRIDGE_API_KEY=$DEEPSEEK_API_KEY \
CODEX_BRIDGE_PORT=4446 \
codex-bridge
```

On startup, the bridge fetches upstream models and logs a short summary so you
can confirm connectivity and available model ids.

### 2. Generate a Codex config snippet

```bash
codex-bridge --print-config \
  --port 4448 \
  --upstream https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --api-key "$DASHSCOPE_API_KEY"
```

This prints a `~/.codex/config.toml` snippet containing:

- a local `base_url` pointing at `http://127.0.0.1:<port>/v1`
- `wire_api = "responses"`
- one `model_properties` block per upstream model

### 3. Point Codex at the bridge

You can use the printed snippet directly, or configure it manually. A minimal
manual example looks like this:

```toml
model = "qwen-plus"
model_provider = "dashscope"

[model_providers.dashscope]
name = "dashscope"
base_url = "http://127.0.0.1:4448/v1"
wire_api = "responses"
env_key = "DASHSCOPE_API_KEY"

[model_properties."qwen-plus"]
context_window = 131072
max_context_window = 131072
supports_parallel_tool_calls = true
supports_reasoning_summaries = false
input_modalities = ["text"]
```

### 4. Use Codex normally

Once Codex is configured to use the local bridge, requests go through
`codex-bridge` transparently.

### 5. Force all requests to one upstream model

If you want every incoming request model to be rewritten to a single upstream
model:

```bash
CODEX_BRIDGE_FORCE_DEFAULT_MODEL=true \
CODEX_BRIDGE_DEFAULT_MODEL=deepseek-v4-flash \
codex-bridge
```

When `CODEX_BRIDGE_DEFAULT_MODEL` is unset, the bridge falls back to
`deepseek-v4-flash`.

The simple three-argument launch mode wires this forced routing automatically,
so Codex can start without extra model mapping steps.

## CLI Reference

| Flag | Env var | Default | Description |
|---|---|---|---|
| `--port` | `CODEX_BRIDGE_PORT` | `4444` | Local listen port |
| `--upstream` | `CODEX_BRIDGE_UPSTREAM` | `https://openrouter.ai/api/v1` | Upstream Chat Completions base URL |
| `--api-key` | `CODEX_BRIDGE_API_KEY` | _(empty)_ | API key forwarded to upstream |
| `--print-config` | _(none)_ | — | Print a Codex config snippet and exit |
| `--force-default-model` | `CODEX_BRIDGE_FORCE_DEFAULT_MODEL` | `false` | Ignore the incoming request model and always forward the default model |
| `--default-model` | `CODEX_BRIDGE_DEFAULT_MODEL` | `deepseek-v4-flash` | Target model used when forced default model routing is enabled |
| `--max-sessions` | `CODEX_BRIDGE_MAX_SESSIONS` | `256` | Maximum retained completed sessions |
| `--max-session-memory-mb` | `CODEX_BRIDGE_MAX_SESSION_MEMORY_MB` | `512` | Approximate memory budget for retained session and reasoning state |
| `--session-ttl-hours` | `CODEX_BRIDGE_SESSION_TTL_HOURS` | `168` | Idle session retention window in hours |
| `--history-store` | `CODEX_BRIDGE_HISTORY_STORE` | `memory` | Session backend: `memory` or `disk` |
| `--history-dir` | `CODEX_BRIDGE_HISTORY_DIR` | `.codex-bridge-history` | Disk history directory when `history-store=disk` |

## Extra Environment Variables

These are supported by the implementation even though they are not exposed as
CLI flags:

| Variable | Default | Description |
|---|---|---|
| `CODEX_BRIDGE_MODEL_MAP` | _(empty)_ | Comma-separated model remaps such as `gpt-5.4:qwen-plus` |
| `CODEX_BRIDGE_TOOL_DENYLIST` | _(empty)_ | Comma-separated tool names to drop before forwarding upstream |
| `CODEX_BRIDGE_LOG` | `codex_bridge=info` | Logging level hint, for example `debug`, `info`, `warning`, `error` |

If `CODEX_BRIDGE_FORCE_DEFAULT_MODEL=true`, every incoming request model is
rewritten to `CODEX_BRIDGE_DEFAULT_MODEL`. When
`CODEX_BRIDGE_DEFAULT_MODEL` is unset, it defaults to `deepseek-v4-flash`.

## Supported Providers

Any reasonably OpenAI-compatible Chat Completions endpoint should work. Common
examples:

| Provider | Base URL | Suggested Port |
|---|---|---|
| DashScope (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `4448` |
| DeepSeek | `https://api.deepseek.com/v1` | `4446` |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `4447` |
| Mistral | `https://api.mistral.ai/v1` | `4449` |
| Groq | `https://api.groq.com/openai/v1` | `4450` |
| xAI | `https://api.x.ai/v1` | `4451` |
| OpenRouter | `https://openrouter.ai/api/v1` | `4452` |

## Features

- **Blocking responses**: Converts standard Chat Completions responses into
  Responses API `output` items
- **Streaming**: Emits Responses-style SSE events such as
  `response.created`, `response.output_text.delta`,
  `response.function_call_arguments.delta`, and `response.completed`
- **Tool calls**: Flattens Responses-style tools into Chat Completions tool
  schemas and round-trips returned function calls
- **Namespace tools**: Expands `namespace` tool groups into individually
  callable upstream tools while preserving reversible naming
- **Parallel tool calls**: Consecutive function calls are grouped into a
  single assistant turn for upstream compatibility
- **Reasoning content retention**: Retains provider reasoning content across
  tool-call turns where possible
- **Session continuation**: Stores translated history for
  `previous_response_id`
- **Spawned child isolation**: Prevents spawned subagent prompts from
  accidentally replaying parent history
- **Model catalog proxying**: Normalizes `/v1/models` so Codex clients can
  consume upstream model lists consistently
- **Forced default model routing**: Can rewrite every incoming request model to
  a single configured upstream model
- **Config generation**: Prints Codex-ready `model_properties` blocks from
  real upstream models

## Session Storage

By default, `codex-bridge` keeps retained session and reasoning state in
memory.

To use disk-backed retention:

```bash
CODEX_BRIDGE_HISTORY_STORE=disk \
CODEX_BRIDGE_HISTORY_DIR=.codex-bridge-history \
codex-bridge
```

The disk backend writes JSON files under:

```text
.codex-bridge-history/
  sessions/
  reasoning/
  turns/
```

Treat this directory as sensitive. It can contain prompts, tool outputs, and
other conversation data.

## Python API

You can also launch the bridge from Python:

```python
from codex_bridge import start

proc = start(
    port=4448,
    upstream="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key="sk-...",
)

# ... use Codex ...

proc.terminate()
```

## Testing

Run the local test suite:

```bash
python3 -m pytest -q
```

The current tests cover:

- translation of Responses input into Chat Completions messages
- namespace tool flattening
- reasoning item handling
- image input reshaping
- streaming event sequencing
- tool-call streaming round-trip
- spawned child request isolation

## Debugging

For more verbose bridge logs:

```bash
CODEX_BRIDGE_LOG=debug codex-bridge
```

Useful things to look for in logs:

- upstream model discovery
- forwarded tool names
- returned function call names
- upstream HTTP failures or parse failures

## Known Scope

`codex-bridge` is focused on Codex's Responses workflow and currently proxies:

- `POST /v1/responses`
- `GET /v1/models`

It is not trying to be a full generic OpenAI-compatible reverse proxy for every
endpoint.
