
`python -m pytest tests -q` 终态、`npm run build`、`docker compose build backend && up -d`（含新 config COPY 已有）、健康冒烟（登录/问答/SSE/status llm 块/TraceView model_route 浏览器走查）、密钥扫描；写 `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-23.md`（DoD 19 项逐项 + 矩阵 20 行 + PENDING_EXTERNAL 三行 + 与 TypeSafe V2 交接的复用件清单）。终审包+台账收口。

---

## 验收线（冻结，摘自 spec）

DoD 19 项全 PASS；矩阵 19 mock/单测 + REAL-LLM-FAILOVER-001 PASS；`P0 Regression=0`；Prompt/Reasoning 存储=0；Router P95≤10ms；407→只增。云条目 `PENDING_EXTERNAL`。
