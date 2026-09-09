# NexusKB · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank** 的企业 RAG 演示项目。

当前版本：**P1.2 / v0.3.0**

## P1.2 重点

- Demo Corpus 从 5 份扩展到 **20 份企业资料**，每个知识域 4 份文档
- Retrieval Evaluation 从 10 道扩展到 **30 道题**
- 四路对比：Vector / BM25 / Hybrid / Hybrid + Rerank
- Citation 增加 **查看原文**；文件返回前再次执行 KB ACL
- 新增审计日志：登录、问答、拒绝访问、入库、删除、来源查看、检索调试、评测、Demo 初始化/重置
- `/api/stats` 返回真实 **今日查询 / 平均查询耗时 / 拒绝访问次数**
- 工作台运行指标实时刷新；管理员 Demo 工具显示最近审计
- 新增 `scripts/demo_smoke.py` 运行时 RBAC 检查
- 新增 `docs/DEMO_SCRIPT.md` 5 分钟面试演示脚本

## 企业检索链路

```text
User
 ↓
JWT
 ↓
Role → Allowed Knowledge Base IDs
 ↓
Qdrant Metadata Filter + Authorized BM25 Corpus
 ↓
Vector + BM25
 ↓
Hybrid
 ↓
Cross-Encoder Rerank (optional)
 ↓
Top-K Authorized Context
 ↓
LLM + Citation
 ↓
Audit Trail
```

**权限不是 Prompt 规则。** 无权限 Chunk 在召回前被排除，不进入候选集，也不会进入 LLM Context。

## 知识库与演示数据

| 知识域 | 文档示例 | 数量 |
|---|---|---:|
| 公共制度 | 差旅、信息安全、会议接待、采购 | 4 |
| HR | 员工手册、考勤加班、休假、绩效调薪 | 4 |
| 产品 | X100、X200、产品 FAQ、安装部署 | 4 |
| 销售 | 折扣、客户分级、报价、合同审批 | 4 |
| 售后 | 退款、退换货、投诉、质保维修 | 4 |

管理员一键初始化时，会把 `demo-data/` 里的 20 份资料自动写到对应知识库并建立索引；已完成索引的同版本资料会跳过。

## 演示账号

| 角色 | 用户名 | 密码 | 可访问知识库 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 全部 |
| 销售 | `sales01` | `sales123` | 公共 / 产品 / 销售 / 售后 |
| HR | `hr01` | `hr123` | 公共 / HR |

> Demo 用户仅用于面试演示。生产环境应替换为 OIDC / SAML / 企业微信 / 飞书等身份源，并替换 `JWT_SECRET`。

## 最快启动

```bash
git clone https://github.com/duyu06/rag.git
cd rag
cp backend/.env.example backend/.env
ollama pull qwen2.5:7b
docker compose up --build
```

访问：

- Web：`http://localhost:3000`
- FastAPI Swagger：`http://localhost:8001/docs`
- Qdrant Dashboard：`http://localhost:6333/dashboard`

检查运行环境：

```bash
python scripts/check_demo.py
```

初始化 Demo：登录 `admin` 后点击右下角 **Demo 工具 → 初始化 Demo**，或：

```bash
python scripts/init_demo.py
```

运行 RBAC smoke：

```bash
python scripts/demo_smoke.py
```

如果 Demo 已完成 Embedding 并希望额外验证检索层不泄漏：

```bash
python scripts/demo_smoke.py --retrieval
```

## RAG Evaluation

内置评测集：`backend/eval_dataset.json`，共 30 道题。

管理员可在 Demo 工具中直接运行：

```text
Vector
BM25
Hybrid
Hybrid + Rerank
```

输出：

- Hit@1
- Hit@3
- MRR
- elapsed_ms

所有结果由当前 Qdrant 数据实时计算，不写死指标。

## Citation 与来源查看

回答中的 Citation 来自 Retrieval Chunk metadata。点击 **查看原文** 时，前端携带 JWT 请求：

```text
GET /api/source/{knowledge_base_id}/{file_name}
```

后端会重新执行 Knowledge Base ACL；因此 Citation 展示与文件访问使用同一权限边界。

## 审计

Demo 使用 `backend/data/audit.jsonl` 持久化以下事件：

```text
LOGIN
QUERY
ACCESS / DENIED
INGEST
DELETE
SOURCE_VIEW
RETRIEVAL_DEBUG
EVALUATION
DEMO_INIT / DEMO_RESET
```

管理员接口：

```text
GET /api/audit?limit=50
```

`/api/stats` 同时输出 `today_queries`、`avg_query_latency_ms`、`denied_access` 和 `events_today`。

> JSONL 是为了让面试 Demo 保持零额外数据库依赖。生产环境应替换为 PostgreSQL / ClickHouse / OpenTelemetry + 日志平台，并根据多实例部署处理统一 trace_id。

## 自动检查

GitHub Actions：

```text
python -m compileall -q backend/app scripts
python -m unittest discover -s backend/tests -p 'test_*.py' -v
npm install
npm run build
```

RBAC contract tests 防止以下回归：

- SALES 访问 HR
- HR 访问销售 / 产品 / 售后
- Qdrant query/scroll 丢失 KB Filter
- BM25 corpus 误用全量 Chunk

## 5 分钟演示

完整脚本：[`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)

推荐顺序：

1. Admin 一键初始化 20 份资料
2. AI 助手：回答 + Citation + 查看原文
3. 检索测试：Vector/BM25/Hybrid/Rerank
4. 30 题四路 Evaluation
5. Sales 问 HR 问题，证明 Retrieval 层无 HR Chunk
6. HR 问销售合同问题，反向验证
7. Admin 查看 ACCESS/DENIED 与 QUERY 审计

## 主要 API

```text
GET  /api/ready
GET  /api/health
POST /api/auth/login
GET  /api/auth/me
GET  /api/knowledge-bases

GET  /api/demo/status
POST /api/demo/initialize
POST /api/demo/reset

GET  /api/stats
GET  /api/audit
GET  /api/documents
POST /api/ingest
DELETE /api/documents/{file_name}
GET  /api/source/{knowledge_base_id}/{file_name}

POST /api/query
POST /api/query/stream
POST /api/retrieval/debug
POST /api/evaluation/run
```

## 当前边界

目前仍刻意冻结：

```text
Multi-Agent
MCP
GraphRAG
多租户 SaaS
Kubernetes
ERP / CRM Action Tools
复杂长流程 Workflow
```

先把企业 RAG 的 **检索质量、权限、引用、评测、审计、可演示性** 做实，再扩 Agent。

## License

MIT。二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
