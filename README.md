<p align="center">
  <img src="frontend/public/yaoke-logo.webp" width="420" alt="yaoke logo" />
</p>

# yaoke · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank + Ornith Tool Calling** 的企业 RAG / Agent 演示项目。

当前版本：**P1.8 / v0.8.0**  
默认本地 LLM：**`ornith-1.5:9b`（Ollama）**。

## P1.8 重点

P1.8 在 P1.7 原生 Conversation Streaming 基础上增加 **Interview Readiness / Demo Observability**，目标是让演示环境是否可用在一屏内可判断：

- 管理员工作台新增 Interview Readiness 面板，实时聚合 API、Qdrant、Ornith、Demo Corpus 与 Tool Registry
- readiness 总状态只有全部关键检查通过时才显示 `READY`，否则显示 `DEGRADED`
- Demo Corpus 必须达到完整 ready 状态（内置数据为 20/20）
- Local Tool Policy 必须严格只有 `enterprise_search`
- Auto Tool Policy 必须严格为 `enterprise_search + web_search`
- Backend health 明确暴露 `P1.8 / v0.8.0 / native_streaming=true`，前端不靠写死文案判断流式能力
- readiness 同屏展示文档、Chunks、今日问答、平均耗时和拒绝访问次数
- 面板提供“系统状态 / RAG 评测 / 开始演示”直达入口
- P1.7 `release_smoke.py --stream` 继续作为本机真实 Ornith SSE/TTFT/持久化验收，不用浏览器状态面板替代真实模型 smoke

## P1.7 重点

P1.7 在 P1.6 Retrieval Quality 基线上升级 **真实 Conversation Streaming**，不改变原有 Retrieval / RBAC / Citation 权限语义：

- Local Fast Path 最终 synthesis 使用 Ollama 原生 `stream: true`
- 使用 `httpx.stream` 直接消费 Ollama NDJSON `message.content`，不再对完整答案固定字符切块
- Tool Routing / Tool arguments 继续 buffered，避免 partial tool-call JSON 暴露给客户端
- 新增 Conversation SSE send / retry endpoint
- assistant turn 先以 `generating` 持久化，流结束后在**同一 message id** 原地写入 completed answer + Citation + Trace
- Retry 同样复用原 failed assistant message id，并支持增量出字
- Conversation UI 使用 `sendStream` / `retryStream`，收到一个 token chunk 就立即追加到当前 AI 气泡
- `auto` / `web` 保留现有 Tool Calling 语义，通过 SSE 兼容传输最终 buffered answer；`local` + Local Fast Path 才是本轮 native token streaming 主链
- P1.6 real-BGE 质量门禁继续作为 Retrieval regression gate

## P1.6 Retrieval 基线

P1.6 在 P1.5 Conversation / Local Fast Path / Retry / Trace 基础上，重点收敛 **检索质量与可回归性**：

- Markdown Chunk 保留父子 heading hierarchy，避免相邻标题生成 heading-only 空证据
- 短追问 Query Enrichment 按 identifier family 更新实体，避免 `X100 + IP65 → IP67` 时丢掉产品实体
- BM25 小语料 / 同质语料中，即使原始或归一化分数非正，也保留真实词法匹配候选
- Hybrid 使用结构化 Chunk metadata + RRF 融合，继续保留可选 Rerank
- 检索 schema 为 `p16-metadata-rrf-v2`，Demo 会按新结构重新索引
- CI 使用真实 `BAAI/bge-small-zh-v1.5` + Qdrant quality gate，不只依赖 stub
- 30 道 Demo 评测题的稳定基线：**P1.6 Hybrid Hit@1 = 0.9000 / Hit@3 = 1.0000 / MRR = 0.9500**

P1.5 的会话能力继续保留：

- 持久化 Conversation：会话与消息写入 SQLite，可恢复、重命名、删除
- 多轮上下文：后续问题只带有限长度上下文，不把整个历史无限塞入模型
- **Local Fast Path**：本地企业问答直接走授权检索 + 一次 LLM 综合，避免额外 Tool Routing 调用
- 失败回答可原地 Retry：不新增第二条用户消息，不更换 assistant message id
- Retry 成功后覆盖失败状态，并重新写入 Citation 与 Agent Trace
- 检索阶段可观测：Vector / BM25 / Fusion / Rerank / Retrieval / LLM / Total timings
- BM25 按权限 scope 缓存，Hybrid 可并行执行 Vector + BM25
- 响应式 Conversation UI：桌面三栏，窄屏自动重排
- Agent Debugger 展示可公开执行事件与性能分解，不保存或展示 hidden reasoning / chain-of-thought
- `scripts/release_smoke.py`：默认做安全 preflight；`--agent` 才验证真实 Ornith → Qdrant → Citation → Trace

P1.4 的 Tool Calling 继续保留：`enterprise_search` / `web_search`、本地/自动/联网三种模式、RBAC 二次校验、统一 Citation、Tool Audit 与 Agent Trace。

## 核心原则

> **模型可以决定调用哪个 Tool，但模型不能决定自己拥有什么权限。**

企业检索权限链路：

```text
JWT
 ↓
Role
 ↓
Allowed Knowledge Base IDs
 ↓
enterprise_search()
 ↓
Qdrant metadata filter + Authorized BM25 corpus
 ↓
Hybrid / optional Rerank
 ↓
Evidence
 ↓
Ornith Final Answer + Citation
```

无权限 Chunk 在候选集阶段就被排除，而不是“先搜全库，再靠 Prompt 要求模型别说”。

## 当前架构

```text
User
 ↓
JWT / Role / selected KB scope
 ↓
Conversation
 ↓
Agent mode: local | auto | web
 ├─ local
 │   ↓
 │ Local Fast Path
 │   ↓
 │ enterprise_search → authorized retrieval
 │   ↓
 │ Ollama final synthesis (stream: true, tools=[])
 │   ↓
 │ Conversation SSE → incremental AI bubble
 │
 └─ auto / web
     ↓
   ornith-1.5:9b native tools
     ↓
   Tool Registry
   ├─ enterprise_search
   └─ web_search
     ↓
   buffered final answer over SSE compatibility path
 ↓
Evidence + citation_index
 ↓
SQLite Conversation + Citation + Audit + Agent Trace
```

## Agent 三种模式

| 模式 | 企业检索 | Web Search | 输出方式 | 用途 |
|---|---|---|---|---|
| `本地 / local` | ✅ | ❌ | Local Fast Path 原生 token streaming | 内部制度、敏感企业问题 |
| `自动 / auto` | ✅ | ✅ 由 Ornith 决定 | Tool Calling buffered + SSE compatibility | 默认 Agent 模式 |
| `联网 / web` | ✅ | ✅ | Tool Calling buffered + SSE compatibility | 最新公开新闻、行业趋势、外部资料 |

涉及内部客户、报价、员工、人事或未公开业务信息时，应使用 **本地模式**，避免 Query 发送到公共搜索服务。

## 企业权限边界

- `ADMIN`：全部 5 个知识域
- `SALES`：公共 / 产品 / 销售 / 售后
- `HR`：公共 / HR

即使模型主动请求 `enterprise_search(knowledge_base_id="kb_hr")`，SALES 账号仍会在工具执行层收到 `DENIED`。用户在 UI 选择单个知识库后，模型也不能通过 Tool 参数扩大检索范围。

## 知识库与 Demo 数据

| 知识域 | 文档示例 | 数量 |
|---|---|---:|
| 公共制度 | 差旅、信息安全、会议接待、采购 | 4 |
| HR | 员工手册、考勤加班、休假、绩效调薪 | 4 |
| 产品 | X100、X200、产品 FAQ、安装部署 | 4 |
| 销售 | 折扣、客户分级、报价、合同审批 | 4 |
| 售后 | 退款、退换货、投诉、质保维修 | 4 |

共 **20 份 Demo 文档**，并内置 **30 道四路检索评测题**。

## 演示账号

| 角色 | 用户名 | 密码 | 可访问知识库 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 全部 |
| 销售 | `sales01` | `sales123` | 公共 / 产品 / 销售 / 售后 |
| HR | `hr01` | `hr123` | 公共 / HR |

> 仅供 Demo。生产环境应替换为 OIDC / SAML / 企业微信 / 飞书等企业身份源，并替换 Demo 密码与 `JWT_SECRET`。

## 最快启动

推荐 Docker Compose：

```bash
git clone https://github.com/duyu06/rag.git
cd rag
cp backend/.env.example backend/.env
ollama pull ornith-1.5:9b
docker compose up --build
```

`backend/.env.example` 面向宿主机直跑，默认 `OLLAMA_BASE_URL=http://localhost:11434`。Docker Compose 会为 backend 容器覆盖为 `http://host.docker.internal:11434`。

先单独验证本机模型：

```bash
ollama run ornith-1.5:9b
```

访问：

- Web：`http://localhost:3000`
- Swagger：`http://localhost:8001/docs`
- Qdrant：`http://localhost:6333/dashboard`
- Agent Debugger：`http://localhost:3000/admin/agent`

宿主机手工启动 backend：

```bash
cd backend
uvicorn app.main_agent:app --host 0.0.0.0 --port 8001
```

此模式要求宿主机已有 Qdrant（默认 `localhost:6333`）与 Ollama（默认 `localhost:11434`）。

## 初始化与验证

启动后先做不触发完整 Agent 推理的检查：

```bash
python scripts/check_demo.py
python scripts/demo_smoke.py
python scripts/release_smoke.py
```

初始化 20 份 Demo 资料：

```bash
python scripts/init_demo.py
```

检索层权限检查：

```bash
python scripts/demo_smoke.py --retrieval
```

Agent Tool Registry / mode 检查：

```bash
python scripts/agent_smoke.py
```

真实 Ornith Tool Calling：

```bash
python scripts/agent_smoke.py --agent
```

同时验证 Web Search：

```bash
python scripts/agent_smoke.py --agent --web
```

P1.8 发布前真实主链检查：

```bash
python scripts/release_smoke.py --agent
python scripts/release_smoke.py --stream
```

`--agent` 验证真实 Ornith → Qdrant → Citation → Trace；`--stream` 进一步验证 Conversation SSE、多个 token 事件、同一 message id 持久化、Citation/Trace 刷新后仍可恢复。面试机如需设首 token SLA，可使用 `python scripts/release_smoke.py --stream --max-ttft 8`。Web Search 依赖当前网络和公共搜索服务；Web 失败不代表本地企业 RAG 已失效。

## Conversation 与 Agent API

```text
GET    /api/conversations
POST   /api/conversations
GET    /api/conversations/{conversation_id}
PATCH  /api/conversations/{conversation_id}
DELETE /api/conversations/{conversation_id}
POST   /api/conversations/{conversation_id}/messages
POST   /api/conversations/{conversation_id}/messages/stream
POST   /api/conversations/{conversation_id}/messages/{message_id}/retry
POST   /api/conversations/{conversation_id}/messages/{message_id}/retry/stream

GET  /api/tools?mode=auto
POST /api/agent/query
POST /api/agent/query/stream
GET  /api/agent/traces/{trace_id}
```

P1.7 的 `local` + Local Fast Path 使用 Ollama 原生 token streaming。Conversation SSE 会先持久化 `generating` assistant turn，再逐 chunk 推送可见文本，结束后原地写入完整 Answer、Citation、Trace 与 timings。`auto` / `web` 为保护 Tool Calling JSON 边界，当前仍先完成 Tool loop，再通过 SSE compatibility path 输出最终答案。

## Citation、Audit 与 Trace

企业 Citation 来自 Retrieval Chunk metadata，并通过受保护的来源接口打开原文；打开时后端再次执行 KB ACL。

审计包含：

```text
LOGIN
QUERY
ACCESS / DENIED
INGEST / DELETE
SOURCE_VIEW
RETRIEVAL_DEBUG
EVALUATION
DEMO_INIT / DEMO_RESET
TOOL_CALL
TOOL_RESULT
```

Agent Trace 只记录可观察执行事件，例如 Tool 名称、Tool 结果数量、耗时、最终输出，不记录模型 hidden reasoning。

Demo 持久化：

```text
backend/data/audit.jsonl
backend/data/agent_traces.jsonl
backend/data/conversations.db
```

生产环境应替换为数据库、集中式日志与 OpenTelemetry 等持久化/可观测方案。

## RAG Evaluation

内置 `backend/eval_dataset.json`，30 道题实时比较：

```text
Vector
BM25
Hybrid
Hybrid + Rerank
```

输出 Hit@1 / Hit@3 / MRR / elapsed_ms，不写死指标。

P1.6 CI 使用真实 `BAAI/bge-small-zh-v1.5` 做 P1.5 / P1.6 A/B；P1.7 继续复用同一质量门禁作为 Retrieval regression gate。当前稳定结果：

| Pipeline | Hit@1 | Hit@3 | MRR |
|---|---:|---:|---:|
| P1.5 Hybrid | 0.8333 | 1.0000 | 0.9167 |
| **P1.6 Hybrid** | **0.9000** | **1.0000** | **0.9500** |

这些指标属于 P1.6 Retrieval baseline，不代表 streaming 本身提升了检索精度。

## CI 验收

GitHub Actions 当前包括四路门禁：

```text
backend-contracts
backend-integration
backend-quality
frontend-build
```

主要覆盖：

- Python compileall / Demo assets / unittest
- Docker Compose 与 Windows 部署脚本语法
- 真实 Qdrant integration
- 20/20 Demo 文档索引
- API 与 Citation ACL
- Vector / BM25 / Hybrid / Rerank
- 30 题四路 Evaluation
- Agent `enterprise_search` → Qdrant → Citation
- SALES → HR 越权拒绝
- Conversation SQLite 持久化与 ownership
- 多轮上下文与 Local Fast Path
- failed assistant 原地 Retry，message id 与 message count 不变
- Retry 后 Citation / Trace 重写
- BM25 warm cache
- P1.6 heading hierarchy / BM25 边界 / query enrichment 回归
- P1.7 native Ollama streaming / Conversation SSE / same-message persistence contract
- P1.8 Interview Readiness live health / Demo / Tool Policy contract
- 真实 BGE recall quality gate
- Next.js production build

CI 的 Agent 模型边界仍可使用确定性 stub，因此 **CI 绿灯不等于用户机器上的 `ornith-1.5:9b` 已被真实加载成功**；最终发布仍以 `release_smoke.py --agent` 为准。P1.7 native token 行为还应在本机 Ollama 环境实际观察一次首 token 输出。

## 5 分钟面试演示

推荐顺序：

1. Admin 打开工作台 Interview Readiness，先展示 API / Qdrant / Ornith / 20/20 / Tool Policy / Native Streaming 全部 PASS
2. 展示 5 个知识域 / 20 份资料
3. 切到本地模式问 `X200 能在零下 20 度工作吗？`，展示 Local Fast Path **真实逐步出字** + Citation
4. 连续追问，展示多轮上下文与 P1.6 Query Enrichment
5. 刷新页面，证明完整回答已持久化；失败回答可在同一 message id 原地 Retry
6. SALES 问 HR 信息，展示候选生成前的 RBAC 拒绝
7. 四路 RAG Evaluation + real-BGE Retrieval baseline
8. 打开 Agent Debugger，展示检索 timings 与 Trace
9. 自动/联网模式演示 `web_search`（网络稳定时再做），最后用 Audit 收尾

相关文档：

- [`docs/P1_8_READINESS.md`](docs/P1_8_READINESS.md)：P1.8 Interview Readiness / Demo Observability
- [`docs/P1_7_STREAMING.md`](docs/P1_7_STREAMING.md)：P1.7 原生 Streaming / SSE / 持久化语义
- [`docs/P1_6_RELEASE.md`](docs/P1_6_RELEASE.md)：P1.6 Retrieval / real-BGE 质量基线
- [`docs/P1_5_CONVERSATIONS.md`](docs/P1_5_CONVERSATIONS.md)：P1.5 Conversation / Runtime 验收
- [`docs/AGENT_P1_4.md`](docs/AGENT_P1_4.md)：P1.4 Tool Calling 架构背景
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)：五分钟面试演示脚本
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)：发布前检查

## 当前明确不做

```text
ERP / CRM 写操作
自动发邮件
任意 URL web_fetch
Multi-Agent
MCP
GraphRAG
复杂 Workflow
多租户 SaaS
Kubernetes
```

P1.8 的目标不是继续堆功能，而是把 **P1.6 Retrieval quality + P1.7 real streaming** 变成一套面试现场可快速验收、可解释、可恢复的稳定演示系统；Readiness 负责环境可见性，真实 Ornith streaming 仍由本机 release smoke 最终验收。

## License

MIT。二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
