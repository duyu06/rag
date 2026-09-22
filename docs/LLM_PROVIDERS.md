# LLM Provider 接入说明

yaoke 的生成层支持本地 Ollama，以及通过 OpenAI-compatible Chat Completions API 接入的云模型。

## 支持方式

- `ollama`：默认，本地 Ornith/Ollama。
- `deepseek`：使用 DeepSeek 官方 OpenAI-compatible API。
- `openai`：OpenAI 官方 API。
- `qwen`：阿里云百炼 OpenAI-compatible API。
- `openai-compatible`：Moonshot、SiliconFlow、OpenRouter、企业网关或其他兼容服务，通过自定义 Base URL / Model 接入。
- `auto`：默认。若配置了新的 `LLM_*` 参数则使用 OpenAI-compatible；否则兼容旧 `OPENAI_*`；都未配置时使用 Ollama。

## DeepSeek

```dotenv
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-flash
LLM_BASE_URL=
```

`LLM_BASE_URL` 留空时自动使用 `https://api.deepseek.com`。

## OpenAI

```dotenv
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4.1-mini
LLM_BASE_URL=
```

## Qwen

```dotenv
LLM_PROVIDER=qwen
LLM_API_KEY=sk-...
LLM_MODEL=qwen-plus
LLM_BASE_URL=
```

## 其他 OpenAI-compatible 服务

```dotenv
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=...
LLM_MODEL=provider-model-name
```

Provider 适配层调用 `/chat/completions`，流式输出使用 SSE，同时保留 Ollama 原生 NDJSON 流式协议。

## 兼容性

旧配置仍然有效：

```dotenv
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
```

优先级：

1. 新的 `LLM_*` 配置
2. 旧的 `OPENAI_*` 配置
3. Ollama

因此现有部署不设置 `LLM_*` 时不会改变原来的 Ornith/Ollama 行为。

## Agent Tool Calling

统一 Provider 层不仅用于基础 RAG，也用于 Agent 路由和最终答案生成。OpenAI-compatible 模型返回的 `tool_calls[].id` 会被保留，并在对应 `tool` 消息中作为 `tool_call_id` 回传。

这保证企业检索、Web Search 等 Tool Calling 能在兼容模型上继续工作，而不是只让基础问答支持云 API。

### DeepSeek Thinking 与 Tool Calling

DeepSeek V4 默认开启 Thinking。当前适配器在 **携带 tools 的 DeepSeek 路由轮** 显式发送：

```json
{"thinking":{"type":"disabled"}}
```

原因是 DeepSeek 的 Thinking + Tool Calling 协议要求后续携带 tools 的轮次完整回传历史 `reasoning_content`。当前 yaoke Agent 不保存隐藏推理，因此先使用非思考 Tool Calling，避免多轮工具调用出现 400，同时保持 Trace 不记录隐藏 reasoning。

最终证据综合轮仍由项目现有 `agent_think_synthesis=false` 策略控制，优先低延迟。

## 流式输出

Conversation 的 SSE 对外契约不变：

```text
message
token
trace
sources
done
```

内部：

- Ollama：`/api/chat` + NDJSON
- DeepSeek / OpenAI-compatible：`/chat/completions` + SSE

前端无需针对 DeepSeek 增加另一套流式解析逻辑。

## 安全

- `LLM_API_KEY` 使用 Pydantic `SecretStr`。
- API Key 只能放在 `backend/.env` 或生产 Secret Store。
- Health、SSE、Trace、Audit 不返回 API Key。
- 不要把真实 Key 写入 `.env.example`、README、测试夹具或 Git 历史。

## 健康检查

`GET /api/health` 会动态返回：

```json
{
  "llm_connected": true,
  "llm_provider": "deepseek",
  "llm_model": "deepseek-flash"
}
```

OpenAI-compatible Provider 通过 `GET /models` 做连通性探测；Ollama 继续通过 `/api/tags` 检查目标模型是否安装。

## 建议验收

1. 未配置 `LLM_*` 时，Ollama/Ornith 原有问答、Agent、SSE 均正常。
2. DeepSeek 配置后，`/api/health` 显示 `llm_provider=deepseek`。
3. `/api/query` 能返回带 Citation 的答案。
4. Local Conversation 能收到真实 token SSE，而不是完成后切片。
5. Auto/Web Agent 能完成至少一次 Tool Calling → Tool Result → Final Answer。
6. DeepSeek Key 不出现在 API、Trace、Audit、SQLite、前端 Bundle 和 Git 历史中。
7. DeepSeek 故障时返回明确的 LLM 服务不可用信息，不影响检索/RBAC 本身。
