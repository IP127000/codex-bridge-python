# codex-bridge

[English](./README.md) | [简体中文](./README.zh-CN.md)

一个轻量级 Python 代理，用来把 Codex 使用的 OpenAI **Responses API**
实时转换成标准 **Chat Completions API**，从而让 Codex 可以接入
DashScope（Qwen）、DeepSeek、Kimi、OpenRouter、Groq、xAI 等
OpenAI 兼容上游。

## 用途

Codex 本身使用的是 OpenAI 的 Responses API，而很多非 OpenAI 提供商只
提供 Chat Completions API。`codex-bridge` 运行在 Codex 和上游模型
服务之间，负责双向转换协议，让你无需修改 Codex 的使用方式。

## 它能做什么

- 在本地接收 Codex 发出的 `POST /v1/responses`
- 转换成上游 `POST /v1/chat/completions`
- 把阻塞和流式 Chat Completions 返回值转回 Responses API 格式
- 保留 `previous_response_id` 对应的会话历史
- 代理 `/v1/models`，并规范化返回结构，兼容 Codex 客户端
- 通过 `--print-config` 生成可直接粘贴到 Codex 的配置片段和 model catalog JSON

## 安装

当前项目以源码仓库形式提供，可以直接在仓库目录安装：

```bash
python3 -m pip install .
```

如果你要本地开发并安装测试依赖：

```bash
python3 -m pip install -e ".[dev]"
```

安装后即可使用 `codex-bridge` 命令。

## 快速开始

### 最简启动方式

如果你想用一条命令直接启动：

```bash
codex-bridge https://api.deepseek.com/v1 "$DEEPSEEK_API_KEY" deepseek-v4-flash 262144
```

这个模式会：

- 在 `127.0.0.1:5057` 启动 `codex-bridge`
- 把 bridge 状态和 Codex 配置固定保存在 `~/.codex-bridge-python`
- 自动写入一个指向本地 bridge 的最小 `config.toml`
- 把第二个参数写入 `~/.codex-bridge-python/auth.json`，同时设置成
  `OPENAI_API_KEY`
- 把第三个参数作为写入 Codex 配置的模型名，同时作为 bridge 强制转发的上游模型
- 把可选的第四个参数作为 Codex 的上下文窗口大小
- 自动写入 `model_context_window`、`model_auto_compact_token_limit`，并开启请求压缩
- 默认以当前目录作为 Codex 工作区启动；但如果你是在 `~` 目录启动，它会自动切换到
  `~/.codex-bridge-python`，避免和 `~/.codex` 的项目级配置冲突

如果你后续再次运行 `codex-bridge`，即使位置参数没有给全，它也会尝试从
`~/.codex-bridge-python/config.toml` 和
`~/.codex-bridge-python/auth.json` 自动补齐；如果还是无法补齐，会明确提示缺少哪些值。

如果你没有传第 4 个上下文窗口参数，`codex-bridge` 会优先使用当前模型在
已保存配置中的值；否则按模型名估算；如果仍然没有合适值，就回退到 `128000`。

### 1. 启动 bridge

以 DashScope 为例：

```bash
CODEX_BRIDGE_UPSTREAM=https://dashscope.aliyuncs.com/compatible-mode/v1 \
CODEX_BRIDGE_API_KEY=$DASHSCOPE_API_KEY \
CODEX_BRIDGE_PORT=4448 \
codex-bridge
```

以 DeepSeek 为例：

```bash
CODEX_BRIDGE_UPSTREAM=https://api.deepseek.com/v1 \
CODEX_BRIDGE_API_KEY=$DEEPSEEK_API_KEY \
CODEX_BRIDGE_PORT=4446 \
codex-bridge
```

启动后，程序会拉取上游模型列表并输出简短日志，方便你确认上游是否连通、
模型 id 是否正确。

### 2. 生成 Codex 配置片段

```bash
codex-bridge --print-config \
  --port 4448 \
  --upstream https://dashscope.aliyuncs.com/compatible-mode/v1 \
  --api-key "$DASHSCOPE_API_KEY"
```

它会输出一段可放入 `~/.codex/config.toml` 的配置，包含：

- 指向本地 bridge 的 `base_url`，即 `http://127.0.0.1:<port>/v1`
- `wire_api = "responses"`
- `model_catalog_json` 配置项
- 与上游模型列表对应的 model catalog JSON 负载

### 3. 让 Codex 指向本地 bridge

你可以直接使用 `--print-config` 输出结果，也可以手工写配置。一个最小示例：

```toml
model = "qwen-plus"
model_provider = "dashscope"
model_catalog_json = "~/.codex/dashscope-model-catalog.json"

[model_providers.dashscope]
name = "dashscope"
base_url = "http://127.0.0.1:4448/v1"
wire_api = "responses"
env_key = "DASHSCOPE_API_KEY"
```

然后把对应的 model catalog JSON 保存到
`~/.codex/dashscope-model-catalog.json`。最推荐的来源就是
`codex-bridge --print-config` 输出的那段 JSON，因为 Codex 现在要求的 schema
比旧的 `model_properties` 更完整。

### 4. 正常使用 Codex

Codex 配置好以后，后续请求会透明地通过 `codex-bridge` 转发到上游。

### 5. 强制所有请求使用同一个上游模型

如果你希望把所有传入请求的模型名统一改写到同一个上游模型：

```bash
CODEX_BRIDGE_FORCE_DEFAULT_MODEL=true \
CODEX_BRIDGE_DEFAULT_MODEL=deepseek-v4-flash \
codex-bridge
```

如果没有设置 `CODEX_BRIDGE_DEFAULT_MODEL`，bridge 会回退到
`deepseek-v4-flash`。

极简启动模式会自动把这个强制路由接好，因此不需要额外再做模型映射配置。

## CLI 参数

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--port` | `CODEX_BRIDGE_PORT` | `4444` | 本地监听端口 |
| `--upstream` | `CODEX_BRIDGE_UPSTREAM` | `https://openrouter.ai/api/v1` | 上游 Chat Completions 基础地址 |
| `--api-key` | `CODEX_BRIDGE_API_KEY` | _(空)_ | 转发给上游的 API Key |
| `--print-config` | _(无)_ | — | 输出一段 Codex 配置并退出 |
| `--force-default-model` | `CODEX_BRIDGE_FORCE_DEFAULT_MODEL` | `false` | 开启后忽略请求里的原始模型名，统一转发到默认模型 |
| `--default-model` | `CODEX_BRIDGE_DEFAULT_MODEL` | `deepseek-v4-flash` | 强制模型开关开启时使用的目标模型 |
| `--max-sessions` | `CODEX_BRIDGE_MAX_SESSIONS` | `256` | 最多保留多少个已完成会话 |
| `--max-session-memory-mb` | `CODEX_BRIDGE_MAX_SESSION_MEMORY_MB` | `512` | 会话与 reasoning 状态的大致内存上限 |
| `--session-ttl-hours` | `CODEX_BRIDGE_SESSION_TTL_HOURS` | `168` | 空闲会话保留时长，单位小时 |
| `--history-store` | `CODEX_BRIDGE_HISTORY_STORE` | `memory` | 会话后端：`memory` 或 `disk` |
| `--history-dir` | `CODEX_BRIDGE_HISTORY_DIR` | `.codex-bridge-history` | 当 `history-store=disk` 时使用的目录 |

## 额外环境变量

这些变量当前实现支持，但没有单独暴露成 CLI 参数：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CODEX_BRIDGE_MODEL_MAP` | _(空)_ | 模型名映射，例如 `gpt-5.4:qwen-plus` |
| `CODEX_BRIDGE_TOOL_DENYLIST` | _(空)_ | 转发前要丢弃的工具名列表，逗号分隔 |
| `CODEX_BRIDGE_LOG` | `codex_bridge=info` | 日志级别提示，例如 `debug`、`info`、`warning`、`error` |

如果开启 `CODEX_BRIDGE_FORCE_DEFAULT_MODEL=true`，所有请求里的 `model`
都会被统一改写为 `CODEX_BRIDGE_DEFAULT_MODEL`。如果没有显式设置
`CODEX_BRIDGE_DEFAULT_MODEL`，则默认使用 `deepseek-v4-flash`。

## 支持的上游示例

只要上游足够兼容 OpenAI Chat Completions 接口，通常都可以接入。常见示例：

| 提供商 | Base URL | 建议端口 |
|---|---|---|
| DashScope (Qwen) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `4448` |
| DeepSeek | `https://api.deepseek.com/v1` | `4446` |
| Kimi (Moonshot) | `https://api.moonshot.cn/v1` | `4447` |
| Mistral | `https://api.mistral.ai/v1` | `4449` |
| Groq | `https://api.groq.com/openai/v1` | `4450` |
| xAI | `https://api.x.ai/v1` | `4451` |
| OpenRouter | `https://openrouter.ai/api/v1` | `4452` |

## 功能说明

- **阻塞式响应转换**：把标准 Chat Completions 返回值转换成 Responses API
  的 `output` 项
- **流式输出**：输出 Responses 风格的 SSE 事件，例如
  `response.created`、`response.output_text.delta`、
  `response.function_call_arguments.delta`、`response.completed`
- **工具调用支持**：把 Responses 风格工具定义改写成 Chat Completions
  工具 schema，并将上游函数调用结果回填为 Responses 输出
- **namespace 工具支持**：把 `namespace` 工具组展开成独立工具，同时保留可
  逆的命名格式
- **并行工具调用兼容**：连续函数调用会被合并成一个 assistant turn，以兼容
  上游 Chat Completions 约束
- **reasoning 内容保留**：尽可能在多轮工具调用中保留 provider 的
  reasoning 内容
- **会话续接**：为 `previous_response_id` 保留翻译后的消息历史
- **子任务隔离**：避免 `spawn_agent` 生成的子请求错误继承父会话历史
- **模型列表代理**：规范化 `/v1/models` 返回结构，便于 Codex 读取
- **默认模型强制路由**：可把所有传入请求统一改写到一个指定的上游模型
- **配置生成**：根据真实上游模型列表输出可直接用于 Codex 的
  `model_catalog_json` 配置和匹配的 model catalog JSON

## 会话存储

默认情况下，`codex-bridge` 会把会话和 reasoning 状态保存在内存里。

如果你希望使用磁盘后端：

```bash
CODEX_BRIDGE_HISTORY_STORE=disk \
CODEX_BRIDGE_HISTORY_DIR=.codex-bridge-history \
codex-bridge
```

磁盘目录结构如下：

```text
.codex-bridge-history/
  sessions/
  reasoning/
  turns/
```

请把这个目录当作敏感数据处理，因为里面可能包含提示词、工具输出和其他会
话内容。

## Python API

也可以从 Python 代码中启动 bridge：

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

## 测试

运行本地测试：

```bash
python3 -m pytest -q
```

当前测试覆盖：

- Responses 输入到 Chat Completions 消息的转换
- namespace 工具展开
- reasoning item 处理
- 图片输入结构转换
- 流式事件顺序
- 流式工具调用 round-trip
- 子任务请求隔离

## 调试

打开更详细的日志：

```bash
CODEX_BRIDGE_LOG=debug codex-bridge
```

重点可观察的信息包括：

- 上游模型发现结果
- 转发出去的工具名
- 上游返回的函数调用名
- 上游 HTTP 错误或解析错误

## 当前范围

`codex-bridge` 当前聚焦于 Codex 的 Responses 工作流，主要代理：

- `POST /v1/responses`
- `GET /v1/models`

它不是一个面向所有 OpenAI 兼容端点的通用反向代理。
