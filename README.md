# NexusKB · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank** 的企业 RAG 演示项目。

当前版本：**P1.1 / v0.2.1**

## P1.1 演示加固

- 管理员 **一键初始化 Demo**：自动把 5 份资料写入对应知识库并建立向量索引
- 初始化幂等：资料与索引已存在时跳过，避免重复 Embedding
- **重置 Demo**：只重建内置 5 份资料，不删除额外上传的企业文档
- Docker Compose 增加 Qdrant / Backend / Frontend healthcheck 与依赖顺序
- `/api/ready` 用于容器 readiness；`/api/health` 会真实探测 Qdrant 与 LLM/Ollama
- 新增 `scripts/check_demo.py` 本地演示前置检查
- 新增 `scripts/init_demo.py` 命令行初始化兜底
- RBAC/ACL 自动回归测试加入 CI
- RAG Evaluation 扩展到 **Vector / BM25 / Hybrid / Hybrid + Rerank**
- 四路评测输出 Hit@1 / Hit@3 / MRR / 耗时
- 管理员登录后右下角提供独立 **Demo 工具** 浮层

## 核心能力

- 多知识库：公共 / HR / 产品 / 销售 / 售后
- JWT 登录与 RBAC
- Qdrant 检索前 ACL 过滤
- BM25 语料同样按权限过滤
- 管理员文档上传 / 删除
- Hybrid Search + Cross-Encoder Rerank
- Citation 来源引用
- Retrieval Debugger
- 实时 Retrieval Evaluation

## 技术链路

```text
User
 ↓
JWT
 ↓
Role → Allowed Knowledge Base IDs
 ↓
Qdrant Metadata Filter
 ↓
┌───────────────┬──────────────┐
│ Vector Search │ BM25 Search  │
└───────┬───────┴──────┬───────┘
        └──── Hybrid ───┘
               ↓
          Cross-Encoder
               ↓
          Top-K Context
               ↓
          LLM + Citation
```

**权限不是在 Prompt 层处理。** 无权限资料不会进入 Vector 候选、BM25 corpus 或 LLM Context。

## 演示账号

| 角色 | 用户名 | 密码 | 可访问知识库 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 全部 |
| 销售 | `sales01` | `sales123` | 公共 / 产品 / 销售 / 售后 |
| HR | `hr01` | `hr123` | 公共 / HR |

> 账号仅用于 Demo。生产环境应接 OIDC / SAML / 企业微信 / 飞书等身份源，并替换 `JWT_SECRET`。

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

启动后可以先执行：

```bash
python scripts/check_demo.py
```

期望看到：

```text
[OK] Qdrant
[OK] Backend
[OK] Frontend
[OK] LLM

Demo preflight: PASS
```

## 一键初始化 Demo

推荐方式：使用 `admin` 登录 Web，点击右下角 **Demo 工具 → 初始化 Demo**。

系统自动映射：

| 文件 | 目标知识库 |
|---|---|
| `01-差旅费用管理制度.md` | 公共制度 |
| `02-售后退款SOP.md` | 售后知识库 |
| `03-X100产品说明书.md` | 产品知识库 |
| `04-销售折扣管理办法.md` | 销售知识库 |
| `05-HR员工手册.md` | HR 知识库 |

命令行兜底：

```bash
python scripts/init_demo.py
```

首次初始化会加载/下载 BGE Embedding 模型，因此第一次可能明显慢于后续运行。

## RBAC 自动测试

CI 执行：

```bash
python -m unittest discover -s backend/tests -p 'test_*.py' -v
```

当前覆盖：

- ADMIN 可访问 5 个知识库
- SALES 不可访问 HR
- HR 不可访问销售 / 产品 / 售后
- `all` scope 必须收敛为角色 ACL
- Qdrant vector query / scroll 必须注入 KB Filter
- BM25 corpus 必须来自授权 Chunk

这里的 CI 测试负责快速防回归；真正的模型/Qdrant 运行时联调仍通过本地 Demo 与检索调试器验证。

## RAG 评测

管理员可以：

1. 先一键初始化 Demo
2. 打开右下角 **Demo 工具**
3. 点击 **运行四路 RAG 评测**

实时比较：

```text
Vector
BM25
Hybrid
Hybrid + Rerank
```

指标：

- Hit@1
- Hit@3
- MRR
- elapsed_ms

评测集：`backend/eval_dataset.json`，结果由当前 Qdrant 数据实时计算，不在 UI 写死。

## 推荐 5 分钟演示路径

1. `admin` 登录 → Demo 工具 → 初始化 Demo
2. 工作台确认 5 个知识库和文档已就绪
3. AI 助手提问“广州普通员工出差住宿标准是多少？”展示 Citation
4. 检索测试切换 Vector / BM25 / Hybrid / Rerank
5. Demo 工具运行四路评测
6. 退出切换 `sales01`，验证 HR 知识库不可见
7. 切换 `hr01`，验证销售/产品/售后资料不可见

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
GET  /api/documents
POST /api/ingest
DELETE /api/documents/{file_name}

POST /api/query
POST /api/query/stream
POST /api/retrieval/debug
POST /api/evaluation/run
```

## 项目定位

这是一个 **企业 RAG / 企业知识中台的面试演示项目**。重点不是堆 Agent，而是把检索、权限、引用、评测和可演示性做清楚。

当前仍冻结：多租户、Multi-Agent、MCP、GraphRAG、Kubernetes、ERP/CRM 和复杂工作流。

## License

MIT。项目二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
