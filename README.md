# NexusKB · 企业 AI 知识中台

基于 **Next.js + FastAPI + Qdrant + BGE Embedding + BM25 + Hybrid Search + Cross-Encoder Rerank** 的企业 RAG 演示项目。

当前版本：**P1 / v0.2.0**

## P1 新增

- 多知识库：公共 / HR / 产品 / 销售 / 售后
- JWT 登录与 RBAC
- Qdrant 检索前 ACL 过滤
- BM25 语料同样按权限过滤
- 不同角色只能看到授权知识库与文档
- 管理员文档上传 / 删除
- RAG 离线评测入口：Hit@1 / Hit@3 / MRR
- 登录页、权限矩阵、知识域筛选器
- 5 份中文企业 Demo 文档

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

**权限不是在 Prompt 层处理。**

NexusKB 会先根据 JWT Role 得到允许访问的 Knowledge Base IDs，并在 Qdrant 查询与 BM25 corpus 构建阶段过滤无权限 Chunk。无权限资料不会进入候选集，也不会进入 LLM Context。

## 演示账号

| 角色 | 用户名 | 密码 | 可访问知识库 |
|---|---|---|---|
| 管理员 | `admin` | `admin123` | 全部 |
| 销售 | `sales01` | `sales123` | 公共 / 产品 / 销售 / 售后 |
| HR | `hr01` | `hr123` | 公共 / HR |

> 这些账号仅用于 Demo。生产环境请将 `backend/app/auth.py` 替换为企业 OIDC / SAML / 企业微信 / 飞书等身份源，并修改 `JWT_SECRET`。

## Demo 数据映射

启动后使用管理员账号上传：

| 文件 | 目标知识库 |
|---|---|
| `demo-data/01-差旅费用管理制度.md` | 公共制度 |
| `demo-data/02-售后退款SOP.md` | 售后知识库 |
| `demo-data/03-X100产品说明书.md` | 产品知识库 |
| `demo-data/04-销售折扣管理办法.md` | 销售知识库 |
| `demo-data/05-HR员工手册.md` | HR 知识库 |

然后切换销售和 HR 账号验证权限隔离。

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

## 推荐演示路径

1. 管理员登录
2. 将 5 份 Demo 文档分别上传到对应知识库
3. 在「检索测试」展示 Vector / BM25 / Hybrid / Rerank
4. 在「AI 知识助手」展示 Citation
5. 退出并切换 `sales01`
6. 验证销售看不到 HR 知识库
7. 切换 `hr01`
8. 验证 HR 看不到销售 / 产品 / 售后资料
9. 管理员进入「RAG 评测」，实际运行 Hit@K / MRR

## RAG 评测

确保 Demo 文档已经入库后：

```bash
cd backend
python eval_retrieval.py
```

或者管理员直接在前端「RAG 评测」页面点击 **运行评测**。

当前内置 QA 集位于：

```text
backend/eval_dataset.json
```

不要把评测数字写死在 UI 中，结果由当前向量库实时计算。

## 主要 API

```text
POST /api/auth/login
GET  /api/auth/me
GET  /api/knowledge-bases

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

这是一个 **企业 RAG / 企业知识中台的面试演示项目**，重点展示：

- 企业文档处理
- Hybrid Retrieval
- Reranking
- Citation
- 多知识库
- RBAC / ACL
- Retrieval Evaluation
- 可观测的检索调试界面

P1 暂不加入多租户、Agent、MCP、ERP / CRM、复杂工作流，保持项目可快速演示、可解释、可继续二开。

## License

MIT。项目二开基础来源于 `Exalt24/enterprise-rag-knowledge-base`，保留原项目 MIT License。
