# yaoke 联网搜索

## 目标

yaoke 的联网能力不是让 LLM 无限制访问外网，而是增加一个受控的 Web Search evidence channel：

```text
User
  ↓
JWT / RBAC
  ↓
Enterprise Retrieval (Qdrant + BM25)
  ↓
[用户显式开启时] DDGS Web Search
  ↓
Enterprise evidence first + Web evidence second
  ↓
Ornith-1.5:9b
  ↓
Answer + numbered citations + Web URLs
```

## 使用

前端登录后，左下角有：

```text
🌐 联网搜索 · OFF / ON
```

默认 OFF。开启后只影响新的提问。

后端通过内部控制标记识别联网请求，Retrieval 在向量检索、BM25 和 Rerank 前会移除该标记，因此不会污染企业知识库召回 Query。

## 配置

```env
WEB_SEARCH_ENABLED=true
WEB_SEARCH_BACKEND=auto
WEB_SEARCH_REGION=cn-zh
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT_SECONDS=8
```

搜索使用 `ddgs`，默认不要求额外付费 API Key。`WEB_SEARCH_BACKEND=auto` 允许库选择可用搜索后端。

## 安全与隐私边界

- UI 默认关闭联网。
- 内部 KB 仍先执行 RBAC/ACL，联网不会扩大企业文档权限。
- 企业制度/金额/流程/产品参数以内部知识库为最高优先级，Web 只能补充外部事实。
- 当前 Web Search 只使用搜索结果标题、URL 和摘要，不提供任意 URL 抓取接口，避免把系统变成通用 SSRF fetcher。
- 互联网搜索摘要可能过时、不完整或被搜索引擎改写；回答会保留 URL 供人工核验。
- 对敏感内部问题，不应开启联网，因为 Query 会发送给外部搜索服务。

## 降级

Web Search 超时或搜索后端不可用时：

- 企业 RAG 继续工作；
- 系统不会把 Web Search 作为 `/api/health` 的硬依赖；
- 如果本地知识库也没有证据，会明确提示联网失败且无可靠依据。

## 后续 Agent 化

Ornith-1.5-9B 支持 tool calling。当前版本先使用显式联网开关，下一阶段可以把 `search_web` 注册为 Ornith 的 `web_search` Tool，由模型根据问题自动决定是否调用，同时保留 allowlist、审计、超时和敏感 Query 策略。
