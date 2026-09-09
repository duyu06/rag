# NexusKB · P1.4 五分钟面试演示脚本

目标：用 5 分钟证明 NexusKB 不只是“知识库聊天”，而是一个具备 **Hybrid Retrieval、RBAC、Ornith Tool Calling、联网检索、Citation、Audit 和 Agent Trace** 的企业 AI 知识中台。

## 演示前检查（不计入正式时间）

```bash
python scripts/check_demo.py
python scripts/demo_smoke.py
python scripts/agent_smoke.py
```

严格验证 Ornith Agent：

```bash
python scripts/agent_smoke.py --agent
```

网络稳定时再跑：

```bash
python scripts/agent_smoke.py --agent --web
```

管理员登录后确认 Demo 工具显示 `20/20 ready`。建议提前让 `ornith-1.5:9b` 和 Reranker 各运行一次，避免首次加载影响演示节奏。

---

## 00:00–00:35｜工作台：一句话定位

登录：

```text
admin / admin123
```

讲：

> NexusKB 是我做的企业 RAG / Agent 演示系统。它先用 JWT 和 RBAC 确定数据边界，再由 Ornith-1.5:9b 决定调用企业检索还是 Web Search。模型可以选 Tool，但不能决定权限；企业检索仍然在 Qdrant 和 BM25 候选生成前做 ACL。

快速指一下：5 个知识域、20 份资料、Chunks、运行指标。

---

## 00:35–01:35｜Auto：Ornith 自主选择企业检索

左下角选择：

```text
自动
```

提问：

```text
X100 的标准整机质保多久？
```

预期：

```text
Ornith
→ enterprise_search
→ 产品知识库
→ Answer + Citation
```

展示右侧来源，然后点击管理员快捷入口 **Agent Trace**。

在 Trace 中指出：

```text
User
→ Model Decision: enterprise_search
→ Tool Start
→ Tool Result: N chunks / latency
→ Final Answer
```

讲：

> 这里展示的是可审计的执行轨迹，不是模型的隐藏思维链。Tool Call、耗时和结果数量可以看，但 reasoning 不落盘。

---

## 01:35–02:20｜Web：最新信息调用联网 Tool

切换：

```text
联网
```

提问：

```text
今天 AI 行业有什么重要新闻？
```

预期：

```text
Ornith
→ web_search
→ DDGS public results
→ Web Citation
```

展示来源中的网页标题、域名和 URL，再打开最新 Agent Trace 指出 `web_search`。

讲：

> Web Search 是工具，不是让模型裸联网。Local 模式甚至不会把这个 Tool 暴露给模型，执行层还有第二道 DENIED 检查。

如果现场外网不稳定，直接跳过这一幕，不影响后面的企业 RAG 演示。

---

## 02:20–03:15｜RBAC：SALES 不能通过 Agent 绕过 HR 权限

切换：

```text
sales01 / sales123
```

模式选择：

```text
本地
```

问：

```text
公司年度调薪通常安排在几月？
```

讲：

> 即使模型尝试调用 enterprise_search，它拿到的不是全库权限。Backend 会根据当前 SALES JWT 重新解析 Allowed KB IDs，所以 HR Chunk 不可能进入 Tool Result。

如果需要进一步证明，打开“检索测试”跑同样 Query，指出返回候选里没有 `kb_hr`。

关键话术：

> 前端隐藏 HR 只是 UX；真正安全边界在 Tool 执行层和 Retrieval 层。

---

## 03:15–04:10｜为什么还要 Hybrid + Evaluation

切回管理员，进入 **检索测试**。

Query：

```text
设备本地管理页面默认端口是多少？
```

快速解释：

- Vector：自然语言语义相似
- BM25：型号、金额、端口、SOP 编号等精确词
- Hybrid：融合两类候选
- Rerank：Query-Chunk 二次相关性排序

然后打开 **四路评测**，展示 30 题实时：

```text
Hit@1
Hit@3
MRR
elapsed_ms
```

讲：

> 所以 Agent 上层不是替代 RAG，而是把经过评测和权限控制的 Retrieval 封装成 Tool。

---

## 04:10–05:00｜Audit + 收尾

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

> 我这个项目重点不是堆 Agent 数量，而是先把企业 AI 最关键的四层做实：检索质量、权限边界、证据引用和可观测性。Ornith 负责判断应该调用什么工具，Backend 负责真正执行权限和数据访问。下一步如果接 ERP 或 CRM，我也会沿用同一原则：读操作可以自动化，写操作和高风险动作必须增加确认与审计，而不是让模型直接拥有业务权限。

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
| Web | Ornith 最近有什么公开更新？ |
| Web | 最近一周有哪些值得关注的大模型发布？ |

## 现场止损规则

- **Ollama 不可用**：展示 Retrieval Debugger + Citation + RBAC，不硬演 Agent。
- **Web Search 不可用**：切回“本地”，企业知识库仍可正常演示。
- **Ornith 未调用预期 Tool**：不要现场反复 Prompt；展示上一条已成功 Trace，再用 `/api/tools` 解释工具策略。
- **Reranker 首次加载慢**：关闭 Rerank，演 Vector/BM25/Hybrid。
- **Evaluation 太慢**：展示已经完成的模式，不等待全部结束。
- **账号切换 UI 缓存异常**：刷新页面，不现场排查样式问题。
