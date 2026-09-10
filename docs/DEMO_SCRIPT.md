# yaoke · P1.6 五分钟面试演示脚本

目标：用 5 分钟证明 yaoke 不只是“知识库聊天”，而是一个具备 **Hybrid Retrieval、真实评测基线、RBAC、Conversation、Local Fast Path、Ornith Tool Calling、联网检索、Citation、Audit 和 Agent Trace** 的企业 AI 知识中台。

## 演示前检查（不计入正式时间）

```bash
python scripts/check_demo.py
python scripts/demo_smoke.py
python scripts/agent_smoke.py
```

严格验证真实 Ornith 主链：

```bash
python scripts/release_smoke.py --agent
```

网络稳定时再跑：

```bash
python scripts/agent_smoke.py --agent --web
```

管理员登录后确认 Demo 工具显示 `20/20 ready`。建议提前让 `ornith-1.5:9b` 和 Reranker 各运行一次，避免首次加载影响演示节奏。

P1.6 当前检索 schema：

```text
p16-metadata-rrf-v2
```

面试前不要临时重调检索权重。当前 real-BGE 稳定基线为：

```text
P1.6 Hybrid
Hit@1 = 0.9000
Hit@3 = 1.0000
MRR   = 0.9500
```

---

## 00:00–00:35｜工作台：一句话定位

登录：

```text
admin / admin123
```

讲：

> yaoke 是我做的企业 RAG / Agent 演示系统。它不是把文档直接丢给模型，而是先由 JWT 和 RBAC 确定数据边界，再经过 Vector、BM25、Hybrid 和可选 Rerank 找证据；Ornith-1.5:9b 负责决定调用企业检索还是 Web Search。模型可以选 Tool，但不能决定自己有什么权限。

快速指一下：5 个知识域、20 份资料、Chunks、运行指标。

如果面试官问版本差异：

> P1.5 我主要做会话、失败重试和执行链路；P1.6 我重点做检索质量，包括 Markdown 层级 Chunk、Hybrid 边界、多轮短追问查询增强和 real-BGE 回归门禁。

---

## 00:35–01:35｜本地模式：最快企业问答 + Citation

左下角选择：

```text
本地
```

提问：

```text
X100 的标准整机质保多久？
```

预期：

```text
Local Fast Path
→ enterprise_search
→ authorized Hybrid Retrieval
→ Answer + Citation
```

展示右侧来源，然后打开管理员快捷入口 **Agent Trace**。

讲：

> 本地企业问答不需要先让模型做一轮 Tool Routing，所以这里走 Local Fast Path：授权检索后只做一次 LLM 综合。这样延迟更稳定，而且敏感内部 Query 不会发送到公共搜索服务。

在 Trace 中指出：

```text
Retrieval
Vector / BM25 / Fusion / Rerank timing
LLM timing
Total timing
Citation
```

补一句：

> Trace 只保留可审计执行事件，不保存模型 hidden reasoning。

---

## 01:35–02:15｜多轮追问：证明不是单轮 Demo

在同一个 Conversation 继续问：

```text
那它支持 IP67 吗？
```

讲：

> 这里会带有限长度的会话上下文，但不会把整个历史无限塞给模型。P1.6 还专门修了短追问检索增强：如果上一轮同时出现 X100 和 IP65，下一轮问“那 IP67 呢”，系统会保留 X100，只更新 IP 规格，不会把产品实体丢掉。

如果时间允许，再快速展示左侧 Conversation 可以恢复、重命名和删除。

---

## 02:15–03:00｜RBAC：SALES 不能通过 Agent 绕过 HR 权限

切换账号：

```text
sales01 / sales123
```

模式：

```text
本地
```

问：

```text
公司年度调薪通常安排在几月？
```

讲：

> 前端不显示 HR 只是 UX。真正的安全边界在 Backend：根据 SALES 的 JWT 重新计算 Allowed KB IDs，并在 Qdrant metadata filter 和授权 BM25 corpus 阶段就排除 HR 数据。模型即使主动请求 kb_hr，也拿不到对应 Chunk。

关键话术：

> 我把模型当成决策组件，不把模型当成授权组件。

---

## 03:00–04:05｜P1.6 检索质量：Hybrid + Evaluation

切回管理员，进入 **检索测试 / 四路评测**。

推荐 Query：

```text
设备本地管理页面默认端口是多少？
```

快速解释：

- Vector：处理自然语言语义相似；
- BM25：处理型号、端口、金额、SOP 编号等精确词；
- Hybrid：融合两路候选，降低单一路径失误；
- Rerank：对 Query-Chunk 做二次相关性排序。

然后展示 30 题实时评测：

```text
Hit@1
Hit@3
MRR
elapsed_ms
```

讲：

> 我没有只看“感觉回答对不对”，而是把 30 道固定问题放进 CI，用真实 BAAI/bge-small-zh-v1.5 和 Qdrant 做 P1.5 / P1.6 A/B。当前 P1.6 Hybrid 的 Hit@1 是 0.90，Hit@3 是 1.00，MRR 是 0.95。

如果面试官追问为什么 Chunk 很重要：

> Markdown 入库会保留父子标题路径，例如“差旅费用管理制度 > 国内住宿标准 > 一线城市”，同时避免只包含标题没有正文的空证据 Chunk。这样检索命中父主题时仍能带回实际答案内容。

---

## 04:05–04:40｜Auto / Web Tool Calling

如果现场网络稳定，切换：

```text
自动 或 联网
```

提问：

```text
今天 AI 行业有什么重要新闻？
```

预期：

```text
Ornith
→ web_search
→ public results
→ Web Citation
```

讲：

> Web Search 是受控 Tool，不是让模型任意抓 URL。Local 模式不会暴露 Web Tool；即使 Web Search 故障，本地企业 RAG 仍然可以独立工作。

如果外网不稳定，直接跳过，不影响主线评分。

---

## 04:40–05:00｜Audit + 收尾

打开 **审计日志**，展示：

```text
QUERY
TOOL_CALL
TOOL_RESULT
ACCESS / DENIED
SOURCE_VIEW
EVALUATION
```

收尾话术：

> 这个项目我刻意没有堆 Multi-Agent 或复杂 Workflow。我优先把企业 AI 真正难的几层做完整：检索质量、权限边界、会话连续性、来源追溯和执行可观测。下一步如果接 ERP 或 CRM，我也会沿用这个边界：读操作可以自动化，写操作和高风险动作必须增加确认、权限和审计，而不是直接把业务权限交给模型。

---

## 面试官高频追问

### 为什么不用纯 Vector？

> 企业知识里有很多型号、端口、金额、制度编号。纯语义向量有时会把“意思接近”放在“精确匹配”前面，所以我保留 BM25，并通过 Hybrid / RRF 融合两路候选。

### 为什么不用更大的模型解决检索问题？

> 模型再大也不能补回没有检索到的证据，而且企业权限不能靠 Prompt。先提高 Retrieval recall 和 ACL 边界，比单纯换更大模型更可控。

### 为什么 Local Fast Path 不让模型决定 Tool？

> 本地模式的目标已经明确是企业知识问答，再做一轮 Tool Routing 只增加延迟和不确定性；Auto/Web 才保留 Ornith 的 Tool Calling。

### CI 为什么还需要真实 BGE？

> stub 适合验证调用契约，但不能证明 embedding / Chunk / Hybrid 的真实检索质量，所以我单独加了 real-BGE quality job。

### 你知道当前系统还有什么不足？

> Agent Stream 目前是服务端完成推理后再分块输出，不是真正 token-by-token streaming；Demo 数据和 SQLite 适合面试演示，生产环境会换企业身份源、正式数据库和集中式可观测系统。

---

## 备用问题

| 场景 | 问题 |
|---|---|
| 企业 / 产品 | X200 标准整机质保几年？ |
| 企业 / 产品 | X200 断网后最多缓存多久数据？ |
| 企业 / 公共 | 公司密码多久必须更换一次？ |
| 企业 / HR | 周末加班是否需要提前审批？ |
| 企业 / 销售 | A 类客户至少多久跟进一次？ |
| 企业 / 售后 | P1 客户投诉多久必须首次响应？ |
| 多轮 | X100 支持 IP65 吗？→ 那 IP67 呢？ |
| Web | 最近一周有哪些值得关注的大模型发布？ |

## 现场止损规则

- **Ollama 不可用**：展示 Retrieval Debugger + Citation + RBAC + real-BGE CI，不硬演 Agent。
- **Web Search 不可用**：切回“本地”，企业知识库仍正常演示。
- **Ornith 未调用预期 Tool**：不要现场反复 Prompt；展示上一条成功 Trace，再用 `/api/tools` 解释策略。
- **Reranker 首次加载慢**：关闭 Rerank，演 Vector / BM25 / Hybrid。
- **Evaluation 太慢**：展示已经完成的指标或 CI quality gate，不现场等待。
- **账号切换 UI 缓存异常**：刷新页面，不现场排查样式问题。
- **某一道纯 Vector 排名波动**：回到整体 Hit@3 / MRR，不为单题现场调权重。
