# NexusKB · 企业 AI 知识中台

一个用于面试和企业 AI 场景演示的 RAG 知识库项目，基于 `Exalt24/enterprise-rag-knowledge-base` 的架构思路二次开发并针对中文企业资料做了收敛。

## P0 已实现

- 企业 SaaS 中文工作台
- PDF / DOCX / TXT / Markdown 上传与解析
- Qdrant 向量索引
- BGE 中文 Embedding
- BM25 关键词检索
- Vector + BM25 Hybrid Search
- 可选 Cross-Encoder Rerank
- AI 问答 + 来源 Citation
- SSE 流式展示
- 检索调试器：Vector / BM25 / Hybrid / Rerank 分数可视化
- 文档列表、删除、索引统计、系统健康检查
- 4 份企业演示资料
- Docker Compose 一键启动

## 架构

```text
员工 / 管理员
      │
      ▼
Next.js 16 Web
      │
      ▼
FastAPI
 ├─ 文档解析 / Chunk
 ├─ BGE Embedding
 ├─ Qdrant Vector Search
 ├─ BM25 Keyword Search
 ├─ Hybrid Fusion
 ├─ Optional Reranker
 └─ RAG Generation
      │
      ├─ Ollama（默认）
      └─ OpenAI-compatible API（可选）
```

## 快速启动

### 1. 准备环境变量

```bash
cp backend/.env.example backend/.env
```

### 2. 默认使用 Ollama

```bash
ollama pull qwen2.5:7b
```

### 3. 启动

```bash
docker compose up --build
```

访问：

- Web：http://localhost:3000
- FastAPI Docs：http://localhost:8001/docs
- Qdrant Dashboard：http://localhost:6333/dashboard

> 第一次执行向量化会下载 `BAAI/bge-small-zh-v1.5`，可选 Rerank 第一次启用时会下载 `BAAI/bge-reranker-base`。

## OpenAI-compatible 模型

如果不使用 Ollama，可在 `backend/.env` 配置：

```env
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4.1-mini
```

设置 `OPENAI_API_KEY` 后优先使用 OpenAI-compatible provider。

## 演示流程

1. 打开「知识库」，上传 `demo-data/` 下 4 份 Markdown。
2. 打开「AI 助手」，依次提问：
   - 广州普通员工出差住宿标准是多少？
   - 退款超过 500 元需要谁审批？
   - X100 产品保修期多久？
   - 销售折扣超过多少需要主管审批？
3. 打开「检索测试」，输入相同问题。
4. 切换 Vector / BM25 / Hybrid，并开启 Rerank，对比排序和分数。
5. 展示回答下方 Citation，说明答案可追溯到企业原文。

## 面试项目表达

可以这样介绍：

> 我把企业内部制度、SOP 和产品文档做成 RAG 知识中台。检索层不是单纯向量检索，而是同时使用 BGE Embedding 和 BM25，通过 Hybrid Fusion 兼顾自然语言语义查询与 SOP 编号、产品型号、金额等精确词检索，并支持 Cross-Encoder 二次重排。生成层要求关键事实附带 Citation，检索调试器可以直接观察 Vector、BM25、Hybrid 与 Rerank 分数，便于定位召回和排序问题。

## 当前边界

P0 暂不实现多租户、RBAC、多知识库、Agent、ERP/CRM 等能力，先保证知识库链路最小可验证。后续 P1 再加入多知识库 + RBAC + RAG Evaluation。

## Upstream & License

架构和实现参考：`https://github.com/Exalt24/enterprise-rag-knowledge-base`

上游项目采用 MIT License。原版权声明保留在本仓库 `LICENSE`。
