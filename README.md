<p align="center">
  <img src="frontend/public/yaoke-logo.webp" width="420" alt="yaoke logo" />
</p>

# yaoke · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank + Ornith Tool Calling** 的企业 RAG / Agent 演示项目。

当前版本：**P1.4 / v0.4.0**  
默认本地 LLM：**`ornith-1.5:9b`（Ollama）**。

## P1.4 重点

- `ornith-1.5:9b` 使用 Ollama `/api/chat` 原生 `tools` 进行 Tool Calling
- Tool Registry：`enterprise_search` / `web_search`
- Agent Loop 最多 **3 轮 Tool Call**，超限后强制基于已有证据生成最终回答
- `enterprise_search` 每次执行重新做 **JWT Role → Knowledge Base ACL**，权限不是 Prompt 规则
- **本地 / 自动 / 联网** 三种模式；Local 模式不暴露 Web Tool，执行层还有二次拒绝
- Web Search 使用 DDGS；只接受公开 HTTP(S) 结果，拒绝 localhost / 私网 / metadata / `file://` / `ftp://`
- 企业与 Web 证据统一 Citation 编号
- Tool Call / Tool Result 写入审计，并生成 `trace_id`
- `/admin/agent` Agent Debugger 只展示可公开执行事件，**不展示 hidden reasoning / chain-of-thought**
- 保留原 P1.3 RAG API 作为 fallback

P1.2/P1.3 能力继续保留：5 个知识域、20 份 Demo 文档、30 道检索评测题、Vector/BM25/Hybrid/Rerank、Citation 原文查看、审计、真实 Dashboard 指标、Demo Seed 与 RBAC smoke tests。

## 当前架构

```text
User
 ↓
JWT / Role / selected KB scope
 ↓
Agent mode: local | auto | web
 ↓
ornith-1.5:9b
 ↓
Tool Registry
 ├─ enterprise_search
 │    ↓
 │  Role ACL → Qdrant Filter + Authorized BM25 → optional Rerank
 │
 └─ web_search
      ↓
    DDGS → public Web results
 ↓
Evidence + citation_index
 ↓
Ornith Final Answer
 ↓
Citation + Audit + Agent Trace
```

**核心原则：模型可以决定调用哪个 Tool，但模型不能决定自己拥有什么权限。**

## Agent 三种模式

| 模式 | 企业检索 | Web Search | 用途 |
|---|---|---|---|
| `本地 / local` | ✅ | ❌ | 内部制度、敏感企业问题 |
| `自动 / auto` | ✅ | ✅ 由 Ornith 决定 | 默认模式 |
| `联网 / web` | ✅ | ✅ | 最新公开新闻、行业趋势、外部资料 |

涉及内部客户、报价、员工、人事或未公开业务信息时，应使用 **本地模式**，避免 Query 发送到公共搜索服务。

## 企业权限边界

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
```

- SALES：公共 / 产品 / 销售 / 售后
- HR：公共 / HR
- ADMIN：全部

即使 Ornith 主动请求 `enterprise_search(knowledge_base_id="kb_hr")`，SALES 账号仍会在工具执行层收到 `DENIED`。如果用户在 UI 选择了单个知识库，模型也不能通过 Tool 参数扩大检索范围。

## 知识库与 Demo 数据

| 知识域 | 文档示例 | 数量 |
|---|---|---:|
| 公共制度 | 差旅、信息安全、会议接待、采购 | 4 |
| HR | 员工手册、考勤加班、休假、绩效调薪 | 4 |
| 产品 | X100、X200、产品 FAQ、安装部署 | 4 |
| 销售 | 折扣、客户分级、报价、合同审批 | 4 |
| 售后 | 退款、退换货、投诉、质保维修 | 4 |

管理员可一键将 `demo-data/` 中 20 份资料建立索引。

## 演示账号

| 角色 | 用户名 | 密码 | 可访问知识库 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 全部 |
| 销售 | `sales01` | `sales123` | 公共 / 产品 / 销售 / 售后 |
| HR | `hr01` | `hr123` | 公共 / HR |

> 仅供 Demo。生产环境应替换为 OIDC / SAML / 企业微信 / 飞书等企业身份源，并替换 `JWT_SECRET`。

## 最快启动

```bash
git clone https://github.com/duyu06/rag.git
cd rag
cp backend/.env.example backend/.env
ollama pull ornith-1.5:9b
docker compose up --build
```

如需先验证模型：

```bash
ollama run ornith-1.5:9b
```

访问：

- Web：`http://localhost:3000`
- Swagger：`http://localhost:8001/docs`
- Qdrant：`http://localhost:6333/dashboard`
- Agent Debugger：`http://localhost:3000/admin/agent`

如果不通过 Docker 手工启动 backend，请使用：

```bash
uvicorn app.main_agent:app --host 0.0.0.0 --port 8001
```

`app.main` 仍保留旧 RAG 路由，但不会挂载 P1.4 Agent API。

## 初始化与基础检查

```bash
python scripts/check_demo.py
python scripts/demo_smoke.py
```

管理员登录后点击 **Demo 工具 → 初始化 Demo**，或：

```bash
python scripts/init_demo.py
```

检索层权限严格检查：

```bash
python scripts/demo_smoke.py --retrieval
```

## P1.4 Agent 验收

先做不依赖真实模型路由的模式/Tool API 检查：

```bash
python scripts/agent_smoke.py
```

验证真实 Ornith Tool Calling、Local 禁网、Agent Trace 与 RBAC：

```bash
python scripts/agent_smoke.py --agent
```

同时要求 DDGS 外网搜索成功：

```bash
python scripts/agent_smoke.py --agent --web
```

最后一个命令依赖当前网络和公共搜索服务；它失败不等于本地企业 RAG 已失效。

## Tool API

```text
GET  /api/tools?mode=auto
POST /api/agent/query
POST /api/agent/query/stream
GET  /api/agent/traces/{trace_id}
```

示例：

```json
{
  "question": "今天 AI 行业有什么重要新闻？",
  "mode": "auto",
  "knowledge_base_id": null,
  "top_k": 5,
  "rerank": false
}
```

### Trace 只展示执行事件

```text
user
model_decision      # 只记录 Tool 名称
tool_start
tool_end
final
```

不会保存或展示 Ornith 的 hidden reasoning / thinking 内容。

## Web 安全边界

当前只有搜索工具，没有任意 URL `web_fetch`。

拒绝：

```text
localhost
127.0.0.1 / ::1
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.169.254
file://
ftp://
```

Web Tool 失败会作为 Tool Result 返回给 Agent，不会让整个 FastAPI / 企业知识库不可用。

## RAG Evaluation

内置 `backend/eval_dataset.json`，共 30 道题，对比：

```text
Vector
BM25
Hybrid
Hybrid + Rerank
```

实时输出 Hit@1 / Hit@3 / MRR / elapsed_ms，不写死指标。

## Citation 与审计

企业 Citation 可点击 **查看原文**，后端会再次做 KB ACL。

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

Demo 使用 `backend/data/audit.jsonl`；Agent Trace 使用 `backend/data/agent_traces.jsonl`。生产环境应替换为集中式日志/数据库/OpenTelemetry。

## 自动检查

GitHub Actions：

```text
python -m compileall -q backend/app scripts
python scripts/validate_demo_assets.py
python -m unittest discover -s backend/tests -p 'test_*.py' -v
npm install
npm run build
```

当前 contracts 覆盖：

- SALES → HR、HR → Sales/Product/Service 权限隔离
- Qdrant query/scroll KB Filter
- Authorized BM25 corpus
- Tool Registry 与 Agent API
- Local 模式禁止 Web Tool
- Agent 最大 Tool Round
- Tool Audit / Trace
- localhost / 私网 / metadata / file / ftp URL 拦截
- Demo corpus / evaluation assets 一致性

## 5 分钟演示

- [`docs/AGENT_P1_4.md`](docs/AGENT_P1_4.md)：P1.4 架构与验收标准
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)：面试演示脚本
- [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)：发布前验收清单

推荐 P1.4 演示顺序：

1. Admin 初始化 20 份资料
2. `自动` 模式问 X100 产品问题 → `enterprise_search`
3. `联网`/`自动` 模式问最新 AI 新闻 → `web_search`
4. 打开 Agent Trace 看 Tool → Result → Final
5. SALES 问 HR 调薪 → 证明无 HR Chunk
6. 四路 RAG Evaluation
7. 查看 TOOL_CALL / TOOL_RESULT / DENIED 审计

## 主要 API

```text
GET  /api/ready
GET  /api/health
POST /api/auth/login
GET  /api/auth/me
GET  /api/knowledge-bases

GET  /api/tools
POST /api/agent/query
POST /api/agent/query/stream
GET  /api/agent/traces/{trace_id}

GET  /api/demo/status
POST /api/demo/initialize
POST /api/demo/reset
GET  /api/stats
GET  /api/audit
GET  /api/documents
POST /api/ingest
DELETE /api/documents/{file_name}
GET  /api/source/{knowledge_base_id}/{file_name}

# Legacy / debugger / evaluation
POST /api/query
POST /api/query/stream
POST /api/retrieval/debug
POST /api/evaluation/run
```

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

P1.4 的目标是先把 **Ornith 能安全、自主地选择企业检索或公共 Web Search，并让 Tool Call 可授权、可审计、可追踪、可引用** 做稳定。

## License

MIT。二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
