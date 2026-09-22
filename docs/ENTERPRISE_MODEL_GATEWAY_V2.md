# Enterprise Multi-Model Gateway V2

## 目标

生成层不再只是“切换模型”，而是一个受策略控制的企业 AI Gateway：

```text
RBAC / Scope
  -> Retrieval
  -> TypeSafe evidence judge
  -> Data sensitivity policy
  -> Model Router
  -> Provider failover
  -> Circuit Breaker
  -> Metrics / Trace / Audit
  -> SSE
```

## 数据分级

知识库具有四级敏感度：

| Level | 云模型 |
|---|---|
| public | 允许 |
| internal | 默认允许，可配置关闭 |
| confidential | 默认禁止，可配置开启 |
| restricted | 永远禁止 |

当前 Demo 映射：

- `kb_public`: public
- `kb_product`: internal
- `kb_service`: internal
- `kb_sales`: confidential
- `kb_hr`: restricted

RAG 使用**实际检索证据**的最高敏感级别决定模型路由。HR/restricted 证据不能发送到 DeepSeek、Qwen、OpenAI 或任何 OpenAI-compatible 外部 API。

## Provider Secret Isolation

Primary 使用 `LLM_*`。

Fallback 使用独立 Secret：

- `DEEPSEEK_API_KEY`
- `QWEN_API_KEY`
- `OPENAI_API_KEY`

Router 不会把一个 Provider 的 Key 借给另一个 Provider。

## Failover

默认：

```text
primary -> qwen -> ollama
```

只对可重试故障执行 fallback：

- timeout
- 408 / 409 / 425 / 429
- 500 / 502 / 503 / 504
- transport errors

以下错误不会被 fallback 隐藏：

- 400 request contract error
- 401/403 credential/permission error
- unsupported model/config error

## Streaming

流式请求只允许在**首个可见 token 之前**进行 Provider fallback。

一旦已经把 token 发给用户，后续 Provider 失败将直接结束该 stream，而不会切到另一模型造成重复或自相矛盾的回答。

## Circuit Breaker

每个 Provider 独立维护滑动失败窗口。

默认：

```dotenv
LLM_ROUTER_FAILURE_WINDOW=20
LLM_ROUTER_FAILURE_THRESHOLD=0.30
LLM_ROUTER_COOLDOWN_SECONDS=60
```

失败率达到阈值后 Provider 进入 OPEN；冷却后仅允许 half-open probe，成功恢复 CLOSED。

## 管理接口

仅 ADMIN：

- `GET /api/admin/llm/router`
- `GET /api/admin/llm/providers/health`
- `POST /api/admin/llm/circuit-breakers/reset`
- `POST /api/admin/llm/metrics/reset`

输出只包含 Provider、Model、能力、连接状态、失败率、延迟、token 统计等安全元数据。

## Trace

Agent Trace 会增加 `model_route` 事件，包括：

- selected provider/model
- fallback_index
- sensitivity
- external_allowed
- attempted_providers

禁止持久化：

- API Key
- Authorization header
- hidden reasoning
- 完整敏感 Prompt

## 生产门禁

必须满足：

1. restricted KB external requests = 0
2. unauthorized chunks = 0
3. API key leak = 0
4. primary 429/503/timeout -> fallback
5. primary 401/400 -> fail fast
6. circuit breaker OPEN 时跳过 Provider
7. streaming fallback 只发生在 first-token 之前
8. SSE / SQLite / History 一致性保持不变
9. TypeSafe degraded fallback 保持不变
10. Real-BGE retrieval quality 不回归
