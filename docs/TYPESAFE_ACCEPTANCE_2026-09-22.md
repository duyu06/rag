# TypeSafe RAG 接入与验收记录（2026-09-22）

## 接入结论

TypeSafe System One 已作为可选服务端判定层接入 Hybrid Retrieval：

1. 后端先完成 RBAC / Scope 过滤，未授权 Chunk 不会进入 TypeSafe。
2. 普通问题判定前 6 个候选；显式多问题判定前 12 个候选。
3. 每个候选只发起一次 `system_one` 请求，并在同一请求中判断相关性、答案证据、错误前提冲突、Prompt Injection；组合问题还会按子问题增加 Noul。
4. `shadow` 只记录指标，不改变原顺序；`active` 才应用 include / conflicting evidence / exclude 路由。
5. 任一超时、异常或部分结果都会令整批 `typesafe_degraded=true`，并确定性退回原 Hybrid/RRF 顺序，不让业务接口直接变成 5xx。
6. `TYPESAFE_ENABLED=false` 时保留原本地 Cross-Encoder 行为与 API 契约。

## 配置

密钥只能写入 `backend/.env` 或生产 Secret Store：

```dotenv
RERANK_PROVIDER=typesafe
TYPESAFE_ENABLED=true
TYPESAFE_MODE=shadow
TYPESAFE_API_KEY=
TYPESAFE_MODEL=jev-latest
TYPESAFE_CANDIDATES=6
TYPESAFE_COMPOUND_CANDIDATES=12
```

先跑 `shadow`，确认中文题集、成本和延迟后，再把 `TYPESAFE_MODE` 切到 `active`。请求本身还必须开启 Rerank。

## 严格验收命令

59 题复杂集、Compound、RBAC / Scope：

```powershell
python scripts/complex_accuracy.py `
  --require-typesafe `
  --expect-typesafe-mode active `
  --max-typesafe-degraded 0 `
  --min-typesafe-requests 414 `
  --json-output output/typesafe-active-complex.json
```

4 个多轮 Citation 回合与 2 个无答案边界：

```powershell
python scripts/complex_accuracy.py `
  --llm-only `
  --rerank-llm-boundaries `
  --require-typesafe `
  --expect-typesafe-mode active `
  --max-typesafe-degraded 0 `
  --min-typesafe-requests 36 `
  --json-output output/typesafe-active-llm.json
```

严格门禁会逐阶段检查：指标样本是否完整、真实请求数、响应模型、运行模式、degraded、errors，以及越权候选数；不能用另一个阶段的成功数据掩盖当前阶段未调用 TypeSafe。

## 本次真实结果

| 验收项 | 结果 |
|---|---:|
| 30 题 Real-BGE 基线 | Vector 90% / 100% / 0.95；BM25 93.33% / 100% / 0.9667；Hybrid 90% / 100% / 0.95（Hit@1 / Hit@3 / MRR） |
| 59 题 Vector | Hit@1 96.61%、Hit@3 100%、MRR 0.983 |
| 59 题 BM25 / Hybrid / Hybrid+TypeSafe | Hit@1、Hit@3、MRR 均 100% |
| Compound | 5/5 |
| RBAC / Scope | 7/7 |
| 多轮 Citation + 无答案 | 6/6 |
| TypeSafe（59 题检索） | 366 requests；P50 882.9 ms；P95 2108.4 ms；315,591 input tokens；32,118 output tokens；$0.013255；total 82,393.1 ms |
| TypeSafe（Compound） | 60 requests；P50 354.2 ms；P95 1418.4 ms；61,027 input tokens；7,620 output tokens；$0.002563；total 9273.6 ms |
| TypeSafe（检索合计） | 426 requests；376,618 input tokens；39,738 output tokens；$0.015818；degraded 0；unauthorized 0 |
| TypeSafe（LLM 边界） | 36 requests；P50 945.4 ms；P95 1900.6 ms；30,932 input tokens；$0.001299；degraded 0；unauthorized 0 |
| SSE 实测 | HTTP 200；70 token events；`trace → sources → done`；TTFT 6532.15 ms |
| SSE / SQLite 一致性 | stream = done = history = SQLite；sources 1 = 1；SQLite status `completed` |
| 故障注入 | TypeSafe 无效地址时 Debug 与 `/api/query` 均 HTTP 200；degraded=true；两次结果一致且等于未重排 fallback |
| 自动化测试 | `117 passed, 9 subtests passed` |
| 前端生产构建 | `npm run build` PASS |

成本按当前官方单价 `$0.042 / 1M input tokens` 估算；TypeSafe output token 当前不计费，但仍记录以便观测。

## 密钥与可观测性边界

- 配置使用 `SecretStr`；前端没有 TypeSafe Key 字段。
- API、SSE、Trace 只允许显式白名单中的 TypeSafe 指标，不允许任意 `typesafe_*` 字段透传。
- API、SSE、SQLite、Trace、审计日志统一脱敏 TypeSafe key 与 Bearer token 形态。
- `backend/.env`、根目录 `data/`、`output/`、`.playwright-cli/` 均不会进入 Git。
- 本次扫描：工作区（排除 `backend/.env`）、前端、运行时 Trace/审计/报告、333 个 Git revision 中，TypeSafe key 形态命中均为 0。

机器可读的本次结果位于 `output/typesafe-active-complex.json` 和 `output/typesafe-active-llm.json`；`output/` 已被忽略，不作为提交物。
