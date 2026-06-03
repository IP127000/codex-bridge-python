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
- 通过 `--print-config` 生成可直接粘贴到 Codex 的配置片段

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
- 根据上游模型列表生成的 `model_properties`

### 3. 让 Codex 指向本地 bridge

你可以直接使用 `--print-config` 输出结果，也可以手工写配置。一个最小示例：

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

### 4. 正常使用 Codex

Codex 配置好以后，后续请求会透明地通过 `codex-bridge` 转发到上游。

## CLI 参数

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--port` | `CODEX_BRIDGE_PORT` | `4444` | 本地监听端口 |
| `--upstream` | `CODEX_BRIDGE_UPSTREAM` | `https://openrouter.ai/api/v1` | 上游 Chat Completions 基础地址 |
| `--api-key` | `CODEX_BRIDGE_API_KEY` | _(空)_ | 转发给上游的 API Key |
| `--print-config` | _(无)_ | — | 输出一段 Codex 配置并退出 |
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
- **配置生成**：根据真实上游模型列表输出可直接用于 Codex 的
  `model_properties`

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
