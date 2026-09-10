# P1.7 Real Streaming

P1.7 在 P1.6 Retrieval Quality 基线上增加真实的 Conversation 流式体验，不改变 Retrieval、RBAC、Citation 或 Tool Calling 的权限语义。

## 目标

P1.6 的 `/api/agent/query/stream` 会先完成整次推理，再按固定字符数切片输出。浏览器看起来像流式，但首 token 延迟没有改善，也无法证明模型使用原生 streaming。

P1.7 将 Local Fast Path 的最终 synthesis 改为 Ollama 原生 `stream: true`：

```text
User message
  ↓
JWT / Role / KB ACL
  ↓
enterprise_search
  ↓
Vector + BM25 + RRF / optional Rerank
  ↓
Authorized evidence
  ↓
Ollama final synthesis (stream: true, tools=[])
  ↓
SSE token events
  ↓
same assistant message id
  ↓
completed answer + Citation + Trace persisted to SQLite
```

## 为什么只在最终 synthesis 开启 native stream

Tool Routing turn 继续 buffered。这样可以保证：

- partial tool-call JSON 不会暴露给前端
- Tool name / arguments 仍在服务端完整解析后执行
- RBAC 仍由 backend tool layer 决定，不交给模型
- P1.6 Retrieval pipeline 完全复用，不因 streaming 分叉

Local Fast Path 本身没有额外 Tool Routing LLM call，因此最适合直接获得真实首 token 改善。

`auto` / `web` 当前继续沿用原有 Tool Calling 语义；Conversation SSE 对这两种模式提供兼容传输，但最终答案仍是 buffered 后一次送出。后续如果要让多轮 Tool Calling 的最终 synthesis 也 native-stream，应先把 Agent loop 重构为明确的 routing phase / synthesis phase，而不是在 tool-call stream 中猜测 JSON 边界。

## Conversation SSE

新增：

```text
POST /api/conversations/{conversation_id}/messages/stream
POST /api/conversations/{conversation_id}/messages/{message_id}/retry/stream
```

事件：

```text
message  -> 持久化 assistant message id，status=generating
token    -> Ollama native content chunk
trace    -> Agent Trace id
sources  -> 最终 Citation sources
done     -> completed message + conversation + timings
error    -> failed message 已原地持久化
```

## 持久化语义

新消息：

```text
persist user(completed)
  ↓
persist assistant(generating)
  ↓
stream tokens to browser
  ↓
replace same assistant id(completed, answer, sources, trace)
```

失败时不会创建第二条 assistant message，而是把同一个 id 原地改为 `failed`。Retry 同样复用原 failed assistant id。

这保证刷新页面后看到的是数据库真实状态，而不是仅存在于 React state 的临时回答。

## 前端行为

`ConversationChatPanel` 仍会先创建 optimistic user/assistant UI，以立即反馈发送动作；收到 token 后只追加到当前 generating assistant 内容。`done` 事件到达后，使用服务端返回的完整 Conversation 替换 optimistic state，因此最终 message id、Citation、Trace、latency 都以服务端为准。

若 SSE 连接在 `done` 前中断，前端会报错并重新读取该 Conversation；后端 worker 会继续负责将该持久化 assistant turn 收敛为 `completed` 或 `failed`。

## 安全边界

P1.7 不改变以下规则：

- ACL 在 Retrieval candidate generation 前生效
- SALES 无法通过请求参数扩大到 HR KB
- Web Search 不覆盖内部企业政策
- Citation 只能来自 backend 返回的 evidence
- Agent Trace 不保存 hidden reasoning / chain-of-thought
- native streaming 仅传 visible `message.content`

## 验收标准

CI contract 必须证明：

1. Ollama payload 包含 `stream: true`。
2. 使用 `httpx.stream` 读取 NDJSON，而不是对完整答案固定字符切块。
3. Local Fast Path 将每个 content chunk 立即送入 token sink。
4. Conversation send / retry 都存在 SSE endpoint。
5. assistant 在开始时为 `generating`，结束后原地 `completed` 或 `failed`。
6. 前端使用 `sendStream` / `retryStream` 并在 generating 状态显示已累计 token。
7. P1.6 real-BGE quality gate 继续通过，证明 streaming 改动没有破坏 Retrieval baseline。
8. Next.js production build 通过。

## 面试演示建议

使用 `local` 模式提问：

> X200 能在零下 20 度工作吗？

观察 AI 气泡在检索完成后立即逐步出字。回答结束后点击该 assistant 消息：

- 右侧 Citation 应出现产品说明书来源
- Agent Debugger 应能打开对应 Trace
- 刷新页面后完整回答仍存在

然后切 SALES 账号尝试访问 HR 知识，说明 streaming 只是传输体验升级，权限边界依旧由后端 Retrieval/Tool layer 控制。
