# yaoke · P1.6 Retrieval Release

P1.6 的目标不是继续增加 Agent 数量，而是在 P1.5 已有的 Conversation / Local Fast Path / Retry / Trace 基础上，把企业知识检索的 **召回质量、结构化 Chunk、短追问语义保持和回归门禁** 做成稳定基线。

## 本阶段核心改动

### 1. Markdown heading hierarchy

Markdown 入库时保留父子标题层级，子段落会携带完整 heading path，例如：

```text
差旅费用管理制度 > 4. 国内住宿标准 > 4.1 一线城市
```

同时避免生成只有标题、没有正文的 heading-only chunk，减少检索到“空证据”的概率。

### 2. Hybrid Retrieval 边界修复

BM25 候选不再因为原始或归一化分数为 0 / 负数就被直接丢弃。只要候选与 Query 存在真实词法重叠，小语料库或同质语料库仍可进入融合排序。

### 3. Multi-turn retrieval query enrichment

短追问会继承必要的上一轮实体上下文，但只在相同 identifier family 内进行替换。例如：

```text
上一轮：X100 支持 IP65 吗？
追问：那 IP67 呢？
```

检索上下文仍保留 `X100`，只更新 IP 规格，不会错误变成“IP67 支持 IP67 吗”。

### 4. Retrieval schema v2

当前检索 schema：

```text
p16-metadata-rrf-v2
```

Demo 初始化会使用新的 Chunk 层级重新索引，避免旧索引继续保留 P1.6 修复前的数据结构。

## Real-BGE quality gate

CI 使用真实 `BAAI/bge-small-zh-v1.5` + Qdrant 对 P1.5 baseline 与 P1.6 做 A/B。

最近稳定门禁结果：

| Pipeline | Hit@1 | Hit@3 | MRR |
|---|---:|---:|---:|
| P1.5 Vector | 0.8667 | 1.0000 | 0.9333 |
| P1.5 BM25 | 0.7667 | 0.9667 | 0.8667 |
| P1.5 Hybrid | 0.8333 | 1.0000 | 0.9167 |
| P1.6 Vector | 0.9000 | 1.0000 | 0.9500 |
| P1.6 BM25 | 0.8667 | 1.0000 | 0.9278 |
| **P1.6 Hybrid** | **0.9000** | **1.0000** | **0.9500** |

质量门禁要求 P1.6 在 30 道 Demo 评测题上保持 Hybrid Top-3 recall，不允许因为结构化 Chunk 或查询增强导致明显召回回退。

## CI gate

P1.6 的合并门禁包含：

```text
backend-contracts
backend-integration
backend-quality (real BGE)
frontend-build
```

其中：

- `backend-contracts`：compileall、Demo asset 校验、unittest、Compose 配置、Windows 脚本语法
- `backend-integration`：真实 Qdrant、RBAC、Citation、Conversation、Local Fast Path、BM25 cache、P1.6 policy
- `backend-quality`：真实 BGE + Qdrant 30 题 A/B
- `frontend-build`：Next.js production build

P1.6 合并后的 `main` 也必须再次通过 push CI，不能只依赖 PR merge ref 的结果。

## 已知非阻塞诊断

`X100的防护等级是什么？` 在纯 Vector 路径中，P1.6 的正确 X100 文档可能从 Rank 1 变成 Rank 2，因为 FAQ Chunk 也高度相关；正确答案仍保持 Top-3，Hybrid 主路径保持 30/30 Top-3 recall。

这个现象当前不通过人为权重继续“调榜”，避免为了单题损害整体检索泛化。

## 面试时怎么解释 P1.6

推荐一句话：

> P1.5 我解决的是企业 Agent 的会话、权限和执行链路；P1.6 我没有继续堆功能，而是针对真实检索做了结构化 Chunk、Hybrid 边界、多轮查询增强和 real-BGE 回归门禁，让企业知识问答从“能跑”变成“有质量基线、可持续回归”。

如果面试官继续追问，可以展示：

1. Markdown 父子 heading path；
2. Vector / BM25 / Hybrid / Rerank 的差异；
3. 30 题评测的 Hit@1 / Hit@3 / MRR；
4. CI 中真实 BGE quality gate；
5. SALES → HR 越权仍然在候选生成前被拒绝。

## Freeze rule

P1.6 后进入面试稳定期：

- 允许：阻塞 Bug、检索回归、文案、演示脚本、可复现性、UI 明显缺陷；
- 暂不增加：ERP/CRM 写操作、MCP、Multi-Agent、GraphRAG、复杂 Workflow、多租户 SaaS、Kubernetes。

原因：这个项目当前的面试价值在于 **完整且可解释的企业 RAG / Agent 主链**，而不是功能数量。
