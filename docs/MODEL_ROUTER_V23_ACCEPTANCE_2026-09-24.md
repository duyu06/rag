# Model Router V2.3 验收报告 — Enterprise LLM Routing & Resilience Layer

日期：2026-09-24　范围：`rag/backend`（Model Router V2.3，Task 1–11）
规格：`docs/MODEL_ROUTER_V23_DESIGN.md`（含 §8.1、§9.1 两处回写）　计划：`docs/MODEL_ROUTER_V23_PLAN.md`
台账：`docs/MODEL_ROUTER_V23_MATRIX.md`　过程记录：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/progress.md`

## 1. 结论

**CONDITIONAL PASS。**

| 判据 | 结果 |
| --- | --- |
| P0（`REAL-LLM-FAILOVER-001`） | **GREEN**（真机跑通，见 §4） |
| 验收矩阵 19+1（台账实际 26 行，含 4 枚云行与 N-3 行） | **22 GREEN / 4 PENDING_EXTERNAL** |
| 全套件（release 门槛） | **961 passed / 0 failed / 992 subtests**（90.70s），`cd backend` 与仓库根两种 cwd 同数；真机 P0 用例默认**不被收集**，不计入这 961 |
| 冻结原则遵守 | 无一项 spec 被反向放宽；三处 spec 回写（§8.1、§9.1、Task 5 接口段）都是**在下一轮实现落地之前补规格**（时序上是"评审发现 → 回写规格 → 修复轮照规格实现"，不是规格先于代码） |
| 条件（为什么不是 PASS） | 4 枚云行本机无 key 不可测；legacy 应急路仍带 httpx 出口（下一稳定版必须删除）；已知限制 9 条见 §6 |
| **待你拍板一项** | **V2.3 出厂形态下 agent 工具链 100% 走 D2 fast-path**（注册表里没有任何一枚"带 `tools` 且可用"的条目：两枚本地条目 `tools=false`，三枚云条目无 key 被动态禁用）。要真正用工具轮只有两条路：给 `openai`/`deepseek`/`qwen` 配 key，或新增一条"官方支持 tools 且本机跑得动"的本地条目（`qwen2.5` / `llama3.1` 级）。**不建议翻 `tools` 旗标**（phi3 官方未针对 function calling 训练、`ornith-1.5:9b-text` 本机加载失败 ⇒ 翻旗标 = 注册表说谎，§5 的 `capability > preference` 会把工具流量发给编不出合法 JSON 的模型）。终审已复核该判断，见 `review-task-11-final.md` ⑤ |

## 2. 交付了什么

- `backend/app/llm/`：`models`（冻结 19 列的 `UsageRecord`）/ `registry`（声明式 JSON 注册表 + D1 凭据规则 + 动态 `enabled`）/ `errors`（三分类 + `model_unavailable` 窄超集正则）/ `normalize`（两协议载荷 + **多轮回放映射**）/ `provider`（**D6 唯一出口**）/ `health` / `classifier`（规则式画像，禁 LLM 判路由）/ `router`（**五级候选池过滤 + 一枚调用方 `context` 接缝**，`stage` 枚举六值，机器理由码）/ `fallback`（重试 / 熔断 / 共享 30s 预算 / 流式 commit 边界）/ `usage`（账本 + 聚合 + `model_route` 九键唯一生产者）。
- 三链路迁移完成：RAG（Task 6）、SSE 对话流（Task 7，`native_stream.py` 退役）、Agent 工具链（Task 8，D2 就地降级）。
- 观测面：`/api/system/status` 的 `llm` 块（逐枚白名单，熔断态与 probe 健康物理分离）、`llm_request_logs` 19 列、trace `model_route` 九键。
- 收口件：`tests/test_llm_egress_guard.py`（D6 三层扫描 + 不裸放 `ValueError` + `unknown` 归零 + 矩阵↔套件双向耦合闸）、`tests/test_real_llm_failover_gate.py`（P0 三枚反造假闸）、`.superpowers/scripts/run_p0_failover_acceptance.sh`。

## 3. 冻结裁决登记（本版的"法条"）

| 编号 | 裁决 | 出处 |
| --- | --- | --- |
| D1 | 云厂商凭据一律走 `{PROVIDER}_API_KEY/_BASE_URL/_MODEL_OVERRIDE`，注册表**零密钥** | spec §3 / §12 |
| D2 | `NoCapableModelError` ⇒ Agent 走本地 fast-path、RAG 走既有兜底文案；**不得 500/503** | spec §5 |
| D3 | 记账 fail-open：账本塌了不许拖垮生成 | spec §8 |
| D4 | `providers.*.healthy` 只来自 probe+60s 缓存，**不掺熔断态**；`fallback_rate` 从表聚合不另建计数器 | spec §8 |
| D5 | 流式只在**首内容块前**允许换模型；commit 后异常 ⇒ `error`+`done`+`stream_committed:true` | spec §7 |
| D6 | **单一出口**：只有 `app/llm/provider.py` 允许 httpx + 端点字面量；`app/llm/` 其余文件永久零命中 | spec §6 / 台账 #19 |
| §8.1 | `error_type` 值域 = provider 的 `kind`(+`:status`/`:no_fallback`) ＋ 两枚**账本侧哨兵** `client_aborted`/`unknown`；交付闸对「推断」与「链上自写」两个来源同样生效；`llm` 块允许 `aborted_rate`/`breaker`；`model_route` **九键**且唯一生产者/唯一挂载点 | Task 5 评审回写 |
| §9.1 | `LLM_ROUTER_ENABLED=false` **只回退非流式路径**：对话链流式腿因 `native_stream.py` 退役而无 legacy 形态（对照面改为「报文与退役模块逐字等价」）；agent 链两条腿都有 legacy 形态，但关旗标等于回到「无条件把 tools 发给不支持工具的本地模型」 | Task 7/8 评审回写 |
| 其它 | 优先级 0 分剔除维持 fail-closed；`unknown` **不设**观测键（与 `success_rate` 共线，归因走 SQL）；`model` 列口径 = 生效模型名（M2）；`client_aborted` 不计入 `success_rate` 但计入 `p95_latency_ms` | ledger Ruling 行 |

## 4. P0 真机十字（唯一 P0）

命令：`bash .superpowers/scripts/run_p0_failover_acceptance.sh --yes`；证据：
`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`。

| # | 断言 | 实测 |
| --- | --- | --- |
| 1 | primary 真被调用 | `ollama-ornith` → `ornith-1.5:9b-text`，请求体 1619 B，`ok=False` |
| 2 | 失败归类 | `model_unavailable`；服务端原文 `llama-server reported out-of-memory during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer of size 820943872` |
| 3 | fallback 被调 | 第二 attempt `ollama-phi3` = `success` |
| 4 | 真回答 | `phi3:mini` 请求 1610 B、`status=200`、中文答案过形状与语言门 |
| 5 | `selected_index`（路由侧） | = 1；账本 `fallback_index` 由第 ⑧ 枚核 |
| 6 | `trace_id` | 全链一致（临时 trace 1 行） |
| 7 | `model_route` | 九键齐、attempts = 2 |
| 8 | usage 落库 | 临时账本恰好 1 行、19 列，`model = phi3:mini` |
| 9 | 零 prompt 入库 | 临时账本该行 19 列 + 临时 trace 落盘件 × 5 枚 canary ⇒ 0 命中（扫描范围=临时库/临时 trace，不含仓库真库） |
| 10 | API 面 200 | **回放式**：生成腿复用本次真答案（零第二次外呼）、检索腿为替身，测的是"fallback 成功不塌成 5xx"；40.6 s。当时的 `model_used` 显示计划 primary `ornith-1.5:9b-text` 而真答出的是 `phi3:mini` —— 该劈叉已由 §6.7 的代码修复消掉 |

耗时：primary 41 596 ms → fallback 生成 20 033 ms，用例总 112 s。仓库真库 `backend/data/conversations.db` 全程 0 行；`config/llm_registry.json` 一字未动。

十枚里有 3 处事实重叠（③ 被 ① 蕴含一半、⑤ 与 ⑦ 共用 `selected_index`、⑤ 的第二条恒真），
**净独立门约 7 枚**；重叠是刻意冗余（同一事实双取），不影响"真失败 / 真成功 / 真落库"三件事各自有独立证据。
第 ② 枚引的那句服务端原文取自探针的 `probe_classification`；链上 `llm_error_message_verbatim` 是同一次
OOM 的**另一段**文案（`ggml_vulkan: Failed to allocate pinned memory …`），两形都命中 §6 的 `alloc` 特征。

**反造假闸**（台账 P0 行与证据互锁）：默认套件对该文件收集数 **0**（用 `del` 类而非 `@skipUnless`，
避免 `skipped` 被读成"跑过了"）；承载例源码面零 skip 令牌；`validate_evidence()` 自身被四枚变异
（模型序 / 错误体 / 行数 / 指纹）打。**这枚闸的效力是本次实测得到的**：主 agent 改矩阵状态单元格时
被它连判三次红（带 `**` 的 GREEN、单元格内裸竖线、状态非裸值），不是纸面设计。

## 5. 性能与预算（实测 vs 待测）

| 项 | 门禁 | 本版实测 | 状态 |
| --- | --- | --- | --- |
| Router 决策开销 | P95 ≤ 10 ms | 5 条目 chat **0.028 ms**；60 候选 rag 0.506 / chat 0.525 / agent 0.282 ms（Task 3 基准，口径为 min-of-3 的每轮 P95） | GREEN |
| Fallback 决策 | ≤ 20 ms | 熔断 gate + 计划内换候选均为进程内常数级；未见独立计时 | 未单列计时（defer） |
| 简单 RAG 全链路 TTFT | P50 ≤ 2 s / P95 ≤ 4 s | 本机 Ollama 冷加载即超预算，需云 LLM 复测 | **PENDING_EXTERNAL** |
| §12 全局预算 | 默认 30 s / 单模型 20 s | 真机 P0 需 900 s / 300 s 才装得下 2 GiB 冷加载 ⇒ 测试进程内 patch 绕过 Field 区间（产品默认与 `.env` 未动，证据里披露 `frozen_range_note`） | 已知限制，见 §6.1 |

## 6. 已知限制（必须随版本一起交付的话）

1. **§12 的 30 s / 20 s 预算装不下 2 GiB 模型的冷加载**。本版不加配置键、不改冻结区间；
   运维事实是：冷模型首次请求在默认预算下必然超时降级。**建议 V2.4** 落 `keep_alive` 预热策略
   或「真机验收专用预算档」（届时需正式 spec 修订，而不是继续在测试里 patch）。
2. **P0 的 primary 失败由本机内存压力诱发**（证据里 available 0.44 GiB / load 97%），不是
   `ornith-1.5:9b-text` 的固有缺陷。链条本身成立；但**换一台宽裕的机器重跑，十字前提会消失**。
   复现条件：在 `ornith-1.5:9b-text`（5.24 GiB）加载不上的环境下跑，或换真实失败源。
3. **runner 的内存门槛偏保守**（floor 3.2 GiB ≈ phi3 权重 × 1.6）：不带 `--yes` 时它拒绝执行，
   而实际靠 Ollama 的 mmap（干净文件页可换出）跑通。建议调成 ×1.2，否则会把能跑的真机验收挡在门外。
4. **云 4 行不可测**（C1 OpenAI / C2 DeepSeek / C3 Qwen / C4 云侧 tool-call 协议差异）：本机
   `OPENAI_API_KEY` 为空。注意 Task 8 曾推断"配一把 key 即可用 agent 工具轮"，该推断**已被推翻**：
   多轮回放的 `arguments` 需 JSON 字符串、工具回执需 `tool_call_id`，两处映射在 Task 9 段 B 才补齐，
   且只有静态形状钉、无真连证据。云 key 到位后须重跑 #12/#13 与全链路。
5. **`LLM_ROUTER_ENABLED=false` 不是全链止血开关**（§9.1）：对话链流式腿与 agent 工具轮在关旗标后
   仍走路由或仍走"未路由的旧行为"，运维不得把它当 SSE 侧模型故障的开关。legacy 路径按冻结约定
   **下一稳定版本必须删除**。
6. **两处刻意保留的不一致**（诚实登记，非缺陷）：① `DENIED` + 在手证据时文案说"无权访问"而
   `num_sources` 记在手的量（拒绝面优先，现状已钉死）；② `llm_calls` 在 pre-commit 静默换候选后
   仍记 1（对外语义不变），**不许**用它估外呼次数，看 `attempts` / 账本。
7. **`model_used` 曾报"计划 primary"而非"真答出的模型"**（终审 I-11-2）。`/api/query` 的该字段走
   `current_model_name()`，它只跑 `plan()` 取计划面 primary、docstring 自陈"不进 fallback"
   ⇒ 任何发生 fallback 的请求，响应体模型名与账本 `model` 列**必然劈叉**（P0 真机证据即活例：
   响应 `ornith-1.5:9b-text` vs 账本 `phi3:mini`）。这违反 DESIGN §9 的冻结句"响应 model 字段来自
   实际选中模型"⇒ **本版必修**，修法是用可变盒子把 `LLMResponse.model` 从生成腿带出（同 T8/T9 的
   `route_out`/`tool_time` 一族），零候选与 legacy 路回退 `current_model_name()`。修复与三口径实测见
   `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task-11-fix-report.md`。
8. **最坏故障形态在 status 页不可见**（终审 I-11-3）：D2（零候选走 fast-path）+ M3（零候选不产账行）
   + D4（providers 只报 probe 健康）三条**各自都**，合起来 ⇒ 所有 enabled 候选全灭时
   `requests_5m = 0`、四枚比率全 null、`providers` 仍绿、`breaker` 仍 closed ⇒ 运维读到的是"闲置且健康"，
   不是"全灭"（终审者已构造出该场景并给出读数）。本版只在文档里登记；**V2.4 必修**：`llm` 块补
   `no_capable_5m` 计数 + 前端不得把 null 渲染成"正常"（与 §7 的 m-7 degraded 键同批）。
9. **P0 证据的"事后修饰"面还剩 4 处**（终审 I-11-1）：`files_sha1` 键集不钉、账本数值不重读临时库文件、
   trace 不重读、⑩ 的 `status_code` 不在判据内（实测一发绕通）。因 P0 已跑完且证据已归档，本版不追改
   判据（改了会让已交卷的证据与判据脱钩）；V2.4 收口件时一并加固。

## 7. 延迟项登记（defer，含归属）

| 项 | 归属 |
| --- | --- |
| `env_file=".env"` 相对路径 ⇒ 从非 `backend/` 目录启动服务时读不到 `.env`（6 枚 `TypeSafeJudgmentTests` 靠测试侧前提绕过） | 产品侧绝对化，V2.4 |
| A-3 扫描的**混合形**可绕（一枚隐式拼接 + 一枚 kwargs） | T9 复审 N-1，V2.4 |
| 响应面缺 `degraded`/`fast_path` 布尔键（前端不读 trace 就分不出"这次没有工具轮"） | m-7，V2.4 / 模型控制台 V2.6 |
| `_classification_query`（agent）与 `llm._query_of` 两份实现 | m-9，V2.4 |
| `data/audit.jsonl` 不在测试护栏改道范围内 | 测试卫生，V2.4 |
| **云牌价未对过账单**：`config/llm_registry.json` 三枚云条目的 `pricing` 仍是出厂占位（0.40/1.60、0.27/1.10、0.40/1.20），本机零账单 | 云 key 到位后按真实账单重填；在那之前 **`llm_request_logs.estimated_cost` 只可看趋势、不得用于结算或报销口径** |
| 熔断器无 epoch token / 无槽位租约（迟到回执可能被算进新一轮） | `app/resilience.py:5-8,42` 文档字符串已自陈，V2.4 |
| 最坏故障形态在 status 页失明（`no_capable_5m` 计数 + null 渲染） | 终审 I-11-3，V2.4（本版仅 §6.8 登记） |
| P0 证据判据的 4 处"事后修饰"面 | 终审 I-11-1，V2.4（本版仅 §6.9 登记） |
| TypeSafe selective 跳过率跨轮漂移未定位 | **跨版本观测项**，出处 = `TYPESAFE_V2_ACCEPTANCE_2026-09-23`，非本版评审产物；V2.4 一并跟 |

## 8. 过程质量（为什么这份结论可信）

- 过程纪律（按磁盘产物如实分级，不说"全部走过四环"）：**T5–T9 走完整四环**（实现 → 独立评审 → 修复轮 →
  scoped 复审，各有 `re-review-task-N-round1.md`）；**T1–T4 为三环**（实现 + 评审 + 主 agent 复核，
  无独立复审件）；**T10 未单开评审 agent，由本次终审补审**（结论 ACCEPT-with-corrections）。
  五份评审文件的合计：**Critical 1 / Important 18 / Minor 49**
  （T5 `0/5/12`、T6 `0/2/8`、T7 `0/4/9`、**T8 `1/4/9`**、T9 `0/3/11`）。
  唯一那枚 Critical 是 Task 8 的「降级腿缺第二道 catch ⇒ 正常输入即可 503、trace 与审计一起丢」，
  已由修复轮封住并经复审者自建溢出输入复验。
- 变异自查：实现侧逐轮累计 **≥90 发**、评审与复审侧独立复现 **≥33 发**，存活发**全部如实标注**
  （T9 段 A 那发"刻意的 GREEN"是记录谓词自身被变异，评审判定为如实披露，并由此挖出两形可绕）。
- 三次真实事故被拦下并修好：测试污染生产库 `llm_request_logs`（23 行假账，已精确清理 + 会话级护栏）、
  截断 agent 留下 `IndentationError`（阻断收集）、变异脚本把 LF 文件翻成 CRLF（943 行假差异，会毒化 D6 扫描）。
- 两处被评审证伪的"主 agent 断言"已回写：任务书里"trace 要两行"（`model_route` 归一）、
  "矩阵 #9/#16/#17 预计缺"（实测不缺）。

## 9. 版本控制提醒

`rag/` 是 git 仓库，但 **HEAD 停在 `bc2085c`，工作树有 106 条 `git status` 条目**
（55 改 / 1 删 / 50 未跟踪；未跟踪目录按条目折叠计数，实际文件更多。父目录 `E:\xiangmu` 不是仓库）。
V2.3 的全部产物（`app/llm/`、三份测试收口件、四份文档、§8.1/§9.1 回写）都只存在于工作树里，
**没有任何回滚点**。是否提交、以什么粒度提交（建议至少按 `Model Router V2.3` 一个提交）由你决定；
本报告不替你动手。

## 10. 下一步（用户已确认的队列）

1. 云 key 到位后：填配置即可重跑 `PENDING_EXTERNAL` 四行 + 全链路 TTFT/成本口径。
2. Enterprise Acceptance Framework 子规格 A（安全速赢：口令哈希替换无盐 SHA-256 等）→ B（治理 + Golden Dataset）→ C（运维 + 多租户）。
3. Model Router V2.5–V2.7：隐私路由（`data_classification`）、模型控制台 UI、动态性能路由。

## 11. 封版基线与按能力维度的最终判定

### 11.1 Baseline（release evidence，2026-09-25 00:52）

```text
git HEAD                     bc2085c（工作树 106 条 git status 条目，未提交）
backend image                rag-backend:f5a2bc5e4651（含 I-11-2 修复后重建）
Docker engine                29.7.2
full suite                   961 passed / 0 failed / 992 subtests（两种 cwd 同数）
release doc revision         MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md（本文件即 revision 载体，自哈希不可自指；同批 docs 哈希见下三行）
matrix doc                   MODEL_ROUTER_V23_MATRIX.md sha1=0829f2052526（P0 单元格回读裸 GREEN）
design doc                   MODEL_ROUTER_V23_DESIGN.md sha1=49574e46f6f9（含 §8.1 / §9.1 / §9.2）
仓库真库                     backend/data/conversations.db sha1=39bca2c404e2（llm_request_logs 0 行，测试零污染）
容器冒烟                     startup complete + /api/health 200 + llm 块 8 键 + providers/breaker 互不渗透（D4）
```

### 11.2 按能力维度（此表是叙述性总结；机器闸只认矩阵里的三值词表）

| 能力 | V2.3 终态 |
| --- | --- |
| Registry（声明式、零密钥、动态 enabled） | PASS |
| Provider 抽象（两协议吸收差异） | PASS |
| Capability routing（按能力不按名字） | PASS |
| NoCapableModel → Agent fast path（D2） | PASS |
| Retry taxonomy（retryable / config / hard 三分类） | PASS |
| Fallback（链 + 预算 + 归因） | PASS |
| Circuit breaker（半开探针、槽位门） | PASS |
| Timeout budget（共享 30s，不按模型相加） | PASS |
| SSE pre-commit failover（换模型对用户无感） | PASS |
| SSE post-commit termination（不切模型 + `stream_committed`） | PASS |
| Tool normalization（`ToolCall(id,name,arguments)`） | PASS |
| Usage accounting（19 列冻结、fail-open、禁存项） | PASS |
| **实际 `model_used`（I-11-2）** | **PASS（本版内修复并复测：三口径 + 6 发变异全杀 + 新契约测试 1 枚有牙）** |
| Route trace（`model_route` 九键） | PASS |
| System status compatibility | PASS*（已确认的 observability 限制进 V2.4，见 L1） |
| Single LLM egress（D6） | PASS |
| Protocol-level mock（19 形矩阵） | PASS |
| REAL-LLM-FAILOVER-001 | PASS（真机，见 §4） |
| Cloud providers | PENDING_EXTERNAL（C1–C4，无 key） |
| Evidence hardening | V2.4（L2） |
| No-capable observability | V2.4（L1） |

### 11.3 已知限制（L1–L4，随版交付）

```text
L1  no-capable status blindness      零候选全灭时 requests_5m=0、四比率 null、provider 仍绿
L2  P0 evidence mutation weakness    status_code 等单字段可被事后修饰（多事实互锁归 V2.4）
L3  cloud live validation pending    4 枚云行需真实凭据复跑（含 §9.2 之外的 tool-call 多轮回放）
L4  estimated_cost 是观测估算非账单  云牌价仍是出厂占位，未对过账单 ⇒ 不得用于结算
```

### 11.4 Deferred（V2.4 backlog，本版不动实现）

```text
V2.4
  - 删除 LLM_ROUTER_ENABLED legacy 路径（连同 rag.py / agent.py 的 httpx 出口与 D6 豁免段一起消失）
  - no-capable 可观测性：no_capable_5m / route_failures_5m + 归因枚举
      NO_CAPABLE_MODEL | ALL_CIRCUITS_OPEN | ALL_MODELS_DISABLED | PROVIDER_UNAVAILABLE
  - P0 证据完整性：HTTP 结果 + trace + 账本 + route attempts + 响应体 多事实互锁，废单字段断言
  - 云侧对账：真实凭据下重跑 C1–C4，并按账单重填 pricing
  - env_file 绝对化 / m-7 响应面 degraded 键 / _classification_query 收口 / audit.jsonl 测试卫生
```

### 11.5 最终判定

```text
MODEL ROUTER V2.3
==============================
Architecture       PASS
Implementation     PASS
Protocol Contract  PASS
Real Failover      PASS
Observability      PASS*   (* 已登记的非阻断限制 L1/L2)
Regression         PASS    961 / 0 / 992
P0 Blockers        0

FINAL: ACCEPTED / RELEASE-CANDIDATE
==============================
```

封版线：本版此后**停止继续修改 V2.3**。任何"顺手修"都要新开一版并携带回归证据。
