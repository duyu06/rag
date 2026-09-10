<p align="center">
  <img src="frontend/public/yaoke-logo.webp" width="420" alt="yaoke logo" />
</p>

# yaoke · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank + Ornith Tool Calling** 的企业 RAG / Agent 演示项目。

当前版本：**P1.5 / v0.5.0**  
默认本地 LLM：**`ornith-1.5:9b`（Ollama）**。

## P1.5 重点

P1.5 在 P1.4 Agent 能力之上，把单轮问答收敛成可持续演示的企业会话体验：

- 持久化 Conversation：会话与消息写入 SQLite，可恢复、重命名、删除
- 多轮上下文：后续问题可带最近对话上下文，不把整个历史无限塞入模型
- **Local Fast Path**：本地企业问答直接走授权检索 + 一次 LLM 综合，避免额外 Tool Routing 调用
- 失败回答可原地 Retry：不新增第二条用户消息，不更换 assistant message id
- Retry 成功后覆盖失败状态，并重新写入 Citation 与 Agent Trace
- 检索阶段可观测：Vector / BM25 / Fusion / Rerank / Retrieval / LLM / Total timings
- BM25 按权限 scope 缓存，Hybrid 可并行执行 Vector + BM25
- 正式响应式 Conversation UI：桌面三栏，窄屏自动重排
- Agent Debugger 展示可公开执行事件与性能分解，不保存或展示 hidden reasoning / chain-of-thought
- 新增 `scripts/release_smoke.py`：默认做安全 preflight；`--agent` 才验证真实 Ornith → Qdrant → Citation → Trace

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
 │ enterprise_search → authorized retrieval → one LLM synthesis
 │
 └─ auto / web
     ↓
   ornith-1.5:9b native tools
     ↓
   Tool Registry
   ├─ enterprise_search
   └─ web_search
 ↓
Evidence + citation_index
 ↓
Final Answer
 ↓
SQLite Conversation + Citation + Audit + Agent Trace
```

## Agent 三种模式

| 模式 | 企业检索 | Web Search | 用途 |
|---|---|---|---|
| `本地 / local` | ✅ | ❌ | 内部制度、敏感企业问题；优先走 Local Fast Path |
| `自动 / auto` | ✅ | ✅ 由 Ornith 决定 | 默认 Agent 模式 |
| `联网 / web` | ✅ | ✅ | 最新公开新闻、行业趋势、外部资料 |

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

P1.5 发布前真实主链检查：

```bash
python scripts/release_smoke.py --agent
```

`--agent` 会要求本机 Ornith、Qdrant、已初始化 Demo 数据、Citation 与 Trace 均可用。Web Search 依赖当前网络和公共搜索服务；Web 失败不代表本地企业 RAG 已失效。

## Conversation 与 Agent API

```text
GET    /api/conversations
POST   /api/conversations
GET    /api/conversations/{conversation_id}
PATCH  /api/conversations/{conversation_id}
DELETE /api/conversations/{conversation_id}
POST   /api/conversations/{conversation_id}/messages
POST   /api/conversations/{conversation_id}/messages/{message_id}/retry

GET  /api/tools?mode=auto
POST /api/agent/query
POST /api/agent/query/stream
GET  /api/agent/traces/{trace_id}
```

Agent Stream 当前是服务端完成推理后分块输出，**不是模型原生 token-by-token streaming**。

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

## CI 验收

GitHub Actions 包括：

```text
python -m compileall -q backend/app scripts
python scripts/validate_demo_assets.py
python -m unittest discover -s backend/tests -p 'test_*.py' -v
npm install
npm run build
```

真实 Qdrant integration 额外验证：

- 20/20 Demo 文档索引
- API 与 Citation ACL
- Vector / BM25 / Hybrid / Rerank
- 30 题四路 Evaluation
- Agent `enterprise_search` → Qdrant → Citation
- SALES → HR 越权拒绝
- Conversation SQLite 持久化与 ownership
- 多轮上下文与 Local Fast Path
- Vector / BM25 / Fusion / Rerank / LLM timings
- failed assistant 原地 Retry，message id 与 message count 不变
- Retry 后 Citation / Trace 重写
- BM25 warm cache
- Next.js production build

CI 的模型边界使用确定性 stub，因此 **CI 绿灯不等于用户机器上的 `ornith-1.5:9b` 已被真实加载成功**；最终发布仍以 `release_smoke.py --agent` 为准。

## 5 分钟面试演示

推荐顺序：

1. Admin 展示 5 个知识域 / 20 份资料
2. 本地模式问企业问题，展示 Local Fast Path + Citation
3. 连续追问一次，展示多轮上下文
4. 打开 Agent Debugger，展示检索阶段 timings 与 Trace
5. SALES 问 HR 信息，展示 RBAC 拒绝
6. 故意演示失败回答后 Retry（如方便），说明同一 assistant turn 原地恢复
7. 四路 RAG Evaluation
8. 自动/联网模式演示 `web_search`（网络稳定时再做）

相关文档：

- [`docs/P1_5_CONVERSATIONS.md`](docs/P1_5_CONVERSATIONS.md)：P1.5 Conversation / Runtime 验收
- [`docs/AGENT_P1_4.md`](docs/AGENT_P1_4.md)：P1.4 Tool Calling 架构背景
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)：演示脚本
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

P1.5 的目标不是继续堆功能，而是把 **企业 Agent 的检索质量、权限边界、来源可追溯、会话可恢复、失败可重试和执行可观测** 做成稳定可演示主线。

## License

MIT。二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
