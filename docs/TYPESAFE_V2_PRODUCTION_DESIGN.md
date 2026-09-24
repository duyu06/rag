# TypeSafe V2 — 生产优化设计（检索判定层）

日期：2026-09-23 · 状态：待用户审阅 · 前置：`docs/TYPESAFE_ACCEPTANCE_2026-09-22.md`（V1 正确性验收，全部结论继承）
用户方案：TypeSafe Production Optimization（外部方案书 §4-15）；Model Router V2 另立 spec，本设计交付其复用件。

## 1. 目标与非目标

**目标**：把 TypeSafe 从"默认 Reranker"降为"高价值 Judge"。量化：TypeSafe calls/query P50≤4、P95≤8；input tokens/query 降 ≥30%；判定段 P50≤700ms / P95≤1800ms；59 题 accuracy 回归 ≤1%；故障（超时/宕机/熔断）全部确定性退本地序且 HTTP 200。

**非目标（本单不做）**：LLM 模型注册表/路由/控制台/隐私路由/成本预算（Model Router V2 单）；TypeSafe 批量接口（SDK 无批量能力，已证实）；判断结果持久化缓存（进程内 LRU 足够单 worker 部署）；用 LLM 判断复杂度（第一版纯规则）。

**TTFT 口径（用户已裁决）**：检索段为硬门禁；全链路 SSE TTFT 只对 V1 基线 6532ms 验 ≥30% 降幅；≤2.5s/4.5s 目标标注为"API LLM 部署下复测"项，本地 Ollama（首 token 实测 30s+）不设门禁。

## 2. 管道重构（retrieval.py 判定段）

`rerank && provider=typesafe` 时新顺序：

```
Hybrid/RRF
  → 本地 Cross-Encoder 精排（pool = retrieval_rerank_candidates，产出 rerank_score）
  → 语义去重（cosine ≥ typesafe_dedup_cosine 合并，保留高分块）
  → 动态 TopK（§4）
  → 置信度/风险路由 should_judge()（§3）
  → [触发且未被熔断] TypeSafe 判定（软/硬超时预算，§5）
      ├─ 成功且 mode 应用 → include/exclude/conflicting 路由（V1 active 逻辑逐字保留）
      └─ degraded/circuit_open/skip → 本地序（现有降级路径不变）
  → diversify_by_document → final rows
```

不变式：`provider=local` 或 `typesafe_enabled=false` 时整段与 V1 逐字一致（回归护栏）。`shadow` 的"只观测不应用"语义保持——用户可见顺序=本地序；但其观测对象是 V2 新管道（CE 前置+动态 TopK）下的候选，不再与 V1 shadow 的固定 6/12 输入逐字相等（评估 TypeSafe 质量时按 V2 管道口径解读）。RBAC 过滤永远先于判定（V1 结论 6 继承）。

## 3. 模式五档（用户方案 §12）

`typesafe_mode: off | shadow | selective | active | strict`（`typesafe_enabled=false` 恒等价 off；旧值 shadow/active 语义不变，向后兼容）。

| mode | 调用条件 | 应用路由 |
| --- | --- | --- |
| off | 从不调用 | 否 |
| shadow | 恒调用（观测） | 否 |
| selective | 仅 `should_judge()` 真 | 是 |
| active | 除"高置信 + 无风险 + 单一事实"外都调 | 是 |
| strict | 恒调用 | 是（=V1 active，验收用） |

`should_judge(query, rows)` 纯规则信号（任一为真即触发）：compound（现有 `is_compound_query`）；CE top1-top2 分差 < `typesafe_medium_margin`；top1 < `typesafe_confidence_floor`；query 含否定/数字/时间/参数特征（复用 `_QUERY_MARKERS` 扩展）；命中敏感词表（安全/合同/薪资等，常量表）；用户显式要求严格引用；no-answer 倾向（top1 低于 floor 且候选跨文档分散）。`active` 的跳过条件 = 分差 > `high_margin` 且无风险信号且非 compound。

## 4. 动态 TopK（替代固定 6/12）

```
compound → typesafe_compound_candidates(8)
margin > high_margin → 3（min_candidates）
margin > medium_margin → 4
否则 → 6（max_candidates）
top1 < confidence_floor → 12（low_confidence_candidates 上限）
```
全部可配置；判定输入为 CE 归一化分与去重后的有序行。

## 5. 执行护栏（复用件交付）

新文件 `app/resilience.py`（通用、无业务依赖，Model Router V2 将按 Provider 实例化复用）：

- `CircuitBreaker(window=20, failure_ratio=0.30, open_seconds=60, half_open_probes=3, clock=time.monotonic)`：`allow()->bool`、`record(ok: bool)`；CLOSED→OPEN→HALF_OPEN→CLOSED 状态机，锁保护；OPEN 期间 `allow()` False。
- `TimeoutBudget(hard_ms)`：`remaining_ms()`/`elapsed_ms()`/`is_over_soft()`。

判定服务接入：批次以 `typesafe_hard_timeout_ms` 包预算，超软线（`typesafe_soft_timeout_ms`）记 slow 计数，超硬线取消未完成任务 → `degraded=true, reason="timeout"` 退本地序；per-request client timeout = `min(remaining_ms, typesafe_timeout_seconds*1000)`；breaker=单例 `typesafe`，OPEN 时不发起判定、**不标 degraded**（主动避险），记 `typesafe_circuit_open=true` 与 skip 指标；并发 `typesafe_max_concurrency` 默认 4→6。

## 6. 判定缓存与语义去重

- 缓存（`typesafe_cache_enabled=true`）：进程内 LRU（`typesafe_cache_max_entries=2048`）+ TTL `typesafe_cache_ttl_seconds=86400`；键 `sha256(normalize(query) + "|" + chunk_id + "|" + sha256(content) + "|" + model + "|" + PROMPT_VERSION="v1")`；值=判定五字段（route/evidence/conflict/injection/confidence）；命中免请求记 `typesafe_cache_hit`；文档重建内容 hash 自然失效；锁保护，命中不写穿 breaker。
- 去重：候选行若载荷已含向量则就地 cosine 比较；否则以 `client.retrieve(with_vectors=True)` 对候选池（≤12 点）一次批量取向量再比较（进程内 Qdrant，单跳 <10ms，耗时记入 `dedup_ms`）；cosine ≥ `typesafe_dedup_cosine`(0.97) 合并保留高分块。不新增存储字段、不触发重索引。

## 7. 指标、白名单与前端

timings 新增：`typesafe_trigger(bool)/typesafe_skipped(str|None: off|circuit_open|budget_exhausted)/typesafe_cache_hit(int)/typesafe_slow(bool)/typesafe_circuit_open(bool)`（请求级）+ 进程内滚动聚合（模块级，不持久化）：trigger_rate/skip_rate/cache_hit_ratio/requests_per_query_p50·p95/input_tokens_per_query_p50/cost_per_query_p50/timeout_rate/degraded_rate/slow_rate/sample_count/latency_p50_ms·p95_ms（已有）/breaker_state。
`app/security.py::public_typesafe_metrics` 白名单同步扩展（只增白名单字段，不透传任意 key，脱敏边界不变）。
`/api/system/status`（admin）增"判定层"统计块；Trace 重排阶段增触发/缓存/熔断子事件；前端 `SystemView` 增中文卡片区（触发率/跳过率/缓存命中/熔断状态，文案按 `docs/UI_COPY_GLOSSARY.md`），`TraceView` 对应行中文化展示。

## 8. 配置键（config.py 追加，.env.example 同步）

```
TYPESAFE_MODE=selective|…五档   TYPESAFE_SOFT_TIMEOUT_MS=1200  TYPESAFE_HARD_TIMEOUT_MS=1800
TYPESAFE_MIN_CANDIDATES=3       TYPESAFE_MAX_CANDIDATES=6      TYPESAFE_COMPOUND_CANDIDATES=8
TYPESAFE_LOW_CONFIDENCE_CANDIDATES=12
TYPESAFE_HIGH_MARGIN=0.25       TYPESAFE_MEDIUM_MARGIN=0.10    TYPESAFE_CONFIDENCE_FLOOR=0.20
TYPESAFE_DEDUP_COSINE=0.97      TYPESAFE_CACHE_ENABLED=true    TYPESAFE_CACHE_TTL_SECONDS=86400
TYPESAFE_CACHE_MAX_ENTRIES=2048
TYPESAFE_BREAKER_ENABLED=true   TYPESAFE_BREAKER_WINDOW=20     TYPESAFE_BREAKER_FAILURE_RATIO=0.30
TYPESAFE_BREAKER_OPEN_SECONDS=60 TYPESAFE_BREAKER_HALF_OPEN_PROBES=3
TYPESAFE_MAX_CONCURRENCY=6（默认改）
```
margin/floor 默认值在首轮 59 题 strict 对照中标定，允许验收前调整并记录最终值。

### 标定结果（Task 8 真实验收回填，2026-09-23）

- **`typesafe_hard_timeout_ms`：1800 → 3000（已入码）**——`app/config.py` 类默认值 + `backend/.env.example` 同步，容器镜像复核 `Settings` 直读 `hard=3000 / soft=1200`。依据：段A 实测本 API 单请求 P95=1835ms 压在 1800 预算线之下（配置错配 ⇒ strict 轮 degraded=14）；段B 实测批次墙钟尾落 3.0-4.9s；段B2 复跑后非退化 51 批次墙钟 P50 938.74 / P95 1803.05 / max 2073.51ms ⇒ 3000 对「无停摆」批次余量约 45%。不再猜第三个值。
- **`typesafe_soft_timeout_ms`：1200（保持默认）**——慢线只驱动 `slow` 计数（实测 `slow_rate` 0.37-0.50），无门禁依赖。
- **`typesafe_high_margin / medium_margin / confidence_floor`：0.25 / 0.10 / 0.20 全部保持默认（未调）**——理由：① selective 的成本与 calls 门禁已 PASS（input tokens ↓44.88%、calls/query P50 0（仅判题 3）/ P95 8），无调参动机；② 唯一未过项是 §9.2 判定段延迟线，属**结构性问题**（路由器 100% 保留 6/8 多请求档 + 现网单请求物理量），调 margin/floor 只改变"判几题"、不改变"被保留题有多慢"，阈值不可解；③ 分布证据（段B2 strict 轮 `typesafe_reasons`，59/59 覆盖）：无信号 39 / risk 7 / margin 5 / param 3 / margin+risk 1 / risk+param 1 / margin+param 1 / compound 1 / compound+param 1，token 合计 risk 9 · margin 7 · param 6 · compound 2 · **floor 0 · dispersed 0**；且"无信号批次 = 39"与段B selective 实测 `router_skipped_cases=39` 逐数相同 ⇒ 免判集完全由该读数决定，默认阈值行为自洽。`floor`/`dispersed` 与 12 档动态 TopK 在本数据集**不可观测（0 命中）**，需扩题集后再标定。
- **§9.2 判定段延迟线（700/1800ms）实测 FAIL**：selective 逐题批次墙钟（仅 20 道真外呼题）P50 1102.02 / P95 2234.32ms。根因非阈值可解（strict 轮按档墙钟中位：3 档 938.7 / 4 档 912.7 / 6 档 1651.0 / 8 档 1268.8ms ⇒ 700ms 低于最便宜档的物理实测中位）。**提案（待用户批准，未批准前该门禁仍记 FAIL）**：改为 `P50≤1200ms / P95≤2500ms`（逐题批次墙钟、仅判题口径）；备选 (a) 批次并行化 (b) 6/8 档独立预算 (c) 以 selective 为生产验收档、700/1800 降为观测目标。全部门禁实测结论见 `docs/TYPESAFE_V2_ACCEPTANCE_2026-09-23.md`。

## 9. 验收（本轮交付门槛）

1. 单测/契约：resilience 状态机与预算、动态 TopK 边界、should_judge 信号矩阵、缓存命中/失效/TTL、去重合并、五档模式行为、`provider=local`+`enabled=false` 逐字回归（现有全量测试保持绿为底线）。
2. 真实复跑（用户已批准外呼，成本约 $0.016×2）：`strict` 一轮复现 V1 全部门禁（degraded=0/unauthorized=0/59 题 100% 不退化>1%）；`selective` 一轮验 calls/query P50≤4·P95≤8、input tokens ↓≥30%、Hit@1≥98%·Hit@3=100%、判定段 P50≤700·P95≤1800ms。`scripts/complex_accuracy.py` 门禁扩展接受新 mode 值并输出上述聚合。
3. 故障注入：无效地址→HTTP 200+degraded；连续失败→breaker OPEN→零外呼且仍 200；HALF_OPEN 恢复。
4. SSE 全链路 TTFT 对比 V1 基线降幅 ≥30%（本地 Ollama 在跑与否如实记录）；前端 `npm run build` PASS；密钥扫描 0 命中；`117+ 测试`基线只增不减。

## 10. 文件边界

新建：`app/resilience.py`；修改：`app/config.py`、`app/retrieval.py`、`app/typesafe_judgments.py`、`app/security.py`、`app/main.py`（status 块）、`scripts/complex_accuracy.py`、`backend/.env.example`、前端 `SystemView.tsx`/`TraceView.tsx`。缓存/路由逻辑内聚在 typesafe 模块，不再分包。

## 10.1 门禁标定决议（2026-09-23，用户批准）

判定段批次墙钟线由 §9 的 P50≤700ms/P95≤1800ms 正式调整为 **P50≤1200ms / P95≤2500ms**（依据：本 API 单次 P50 实测 883ms 已高于原线 + 路由器结构性保留最贵档；见验收报告段B2/终审）。原线数字保留作历史记录，验收以本决议线为准。生产 `TYPESAFE_MODE` 同步批准为 `selective`。
