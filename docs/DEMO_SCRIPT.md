# NexusKB · 5 分钟面试演示脚本

目标：用 5 分钟证明这不是“套壳聊天机器人”，而是一套有检索工程、权限边界、引用溯源和评测能力的企业 RAG。

## 演示前 2 分钟检查（不计入正式演示）

```bash
python scripts/check_demo.py
python scripts/demo_smoke.py
```

管理员登录后打开右下角 **Demo 工具**，确认 `20/20 ready`。如果不是，点击 **初始化 Demo**。

推荐预先运行一次 Reranker，让模型完成首次下载，避免现场等待。

---

## 00:00–00:40｜工作台：项目定位

打开 `http://localhost:3000`，使用：

```text
admin / admin123
```

讲：

> 这是 NexusKB 企业知识中台。现在内置 5 个知识域、20 份企业资料。核心链路不是单纯向量搜索，而是 JWT/RBAC 先确定数据范围，再做 Vector + BM25 Hybrid Retrieval，可选 Cross-Encoder Rerank，最后让 LLM 只基于授权证据回答并给出 Citation。

指一下工作台：

- 知识库数量
- 文档 / Chunk
- **今日查询、平均延迟、拒绝访问**（真实审计数据）

---

## 00:40–01:40｜AI 助手：回答 + Citation

问题：

```text
广州普通员工出差住宿标准是多少？
```

展示：

1. 流式回答
2. Citation 来源卡片
3. 点击 **查看原文**

讲：

> Citation 不是模型自己写一个文件名。来源来自 Retrieval 返回的 Chunk metadata，查看原文接口会再次执行知识库 ACL 校验。

再快速问一个容易区分精确词检索的问题：

```text
X200 的防护等级是什么？
```

---

## 01:40–02:40｜检索测试：为什么 Hybrid

进入 **检索测试**，Query：

```text
设备本地管理页面默认端口是多少？
```

依次展示：

- Vector
- BM25
- Hybrid
- Hybrid + Rerank（如现场机器性能允许）

讲：

> Vector 解决自然语言语义近似；BM25 对型号、金额、端口、SOP 编号等精确词更可靠。Hybrid 做候选融合，Reranker 再直接对 Query-Chunk 对进行相关性评分。

打开右下角 Demo 工具，运行 30 道题四路评测，展示 Hit@1 / Hit@3 / MRR。

---

## 02:40–03:50｜RBAC：销售看不到 HR

退出管理员，切换：

```text
sales01 / sales123
```

先让面试官看到顶部知识域中没有 HR。

如果对方问“前端隐藏有什么意义”，直接回答：

> 前端隐藏只是 UX。真正安全边界在 Retrieval 层。

问：

```text
公司年度调薪通常安排在几月？
```

进入检索测试，再运行同样问题。指出返回候选里没有 `kb_hr`。

讲：

> Role 会解析为 Allowed Knowledge Base IDs，这组 ID 同时进入 Qdrant query filter 和 BM25 corpus 构建。未授权 HR Chunk 在召回前就被排除了，不会进入候选集，更不会发给 LLM。

---

## 03:50–04:30｜反向验证：HR 看不到销售

切换：

```text
hr01 / hr123
```

问题：

```text
合同金额超过100万需要谁审批？
```

说明 HR 只能访问公共 + HR，销售合同资料不会进入 Retrieval。

---

## 04:30–05:00｜审计与收尾

切回管理员，打开 **Demo 工具**。

展示最近审计：

- QUERY
- ACCESS / DENIED
- RETRIEVAL_DEBUG
- SOURCE_VIEW
- EVALUATION

收尾话术：

> 这个 Demo 我重点做的不是功能数量，而是企业 RAG 最容易被忽略的四件事：检索质量、数据权限、来源可追溯和效果可评测。生产环境下一步会把 Demo JWT 换成企业 IdP，把 JSONL 审计换成数据库或 OpenTelemetry 日志管道，再根据业务需要接 Agent Tools。

---

## 备用问题

| 场景 | 问题 |
|---|---|
| 公共制度 | 公司密码多久必须更换一次？ |
| 公共制度 | 采购 3500 元办公用品需要谁审批？ |
| HR | 周末加班是否需要提前审批？ |
| HR | 绩效等级有哪些？ |
| 产品 | X200 标准整机质保几年？ |
| 产品 | X200 断网后最多缓存多久数据？ |
| 销售 | 普通报价单默认有效期多少天？ |
| 销售 | A 类客户至少多久跟进一次？ |
| 售后 | P1 客户投诉多久必须首次响应？ |
| 售后 | 保内非人为损坏维修是否收费？ |

## 现场止损规则

- Ollama 不可用：展示 Retrieval Debugger + Citation 原文，不硬演 LLM。
- Reranker 首次加载慢：先关闭 Rerank，演 Vector/BM25/Hybrid。
- 评测未跑完：用已经完成的前三路结果，不等待。
- 切换账号后页面缓存异常：直接刷新，不现场排查 UI。
