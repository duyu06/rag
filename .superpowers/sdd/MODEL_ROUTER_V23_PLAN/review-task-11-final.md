# Task 11 终审裁定（rev11b）

终审者：独立终审 agent（Task 11 评审半段）。范围按主 agent 指令收窄为五件：验收文档逐句对证、Task 10 补审、跨任务一致性、欠账清点、诚实性抽查。
硬约束遵守：未改 `backend/`、`docs/`、`frontend/` 任何文件；矩阵若被临时改动一律还原（见 §6 证明）；零 git 写；零真实外呼。

## ① Verdict

**ACCEPT-with-corrections。**（论证与清单见文末「① Verdict（终）」；本处只给结论以免占位期误读。）

## ② 验收文档需要改的句子（`docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md`）

逐句对证进行中。已核实为**准确**的项（不再列句子）：
- §1 矩阵行：台账状态单元格实测 26 枚 = `GREEN` 22 / `PENDING_EXTERNAL` 4，行号集合 `1..19 + 12b + N-3 + P0 + C1..C4` ⇒ §1「19+1（台账实际 26 行，含 4 枚云行与 N-3 行）/ 22 GREEN / 4 PENDING_EXTERNAL」**准确**。
- §4 耗时：`primary 41 596 ms`（证据 `provider_calls[0].elapsed_ms = 41596.4`）/ `fallback 20 033 ms`（`provider_calls[1].elapsed_ms = 20032.8`）/ `用例总 112 s`（`timings_ms.total = 111838.3`）——注意 attempt 级另有 `41597.5 / 20036.3`（含记账与包装），文档取的是 provider 口径，**可接受但建议标注口径**。
- §4 行 1/3/4 的请求体字节 1619 / 1610、`ok=False`、`http_status 200`、`model_unavailable` 均与证据 `provider_calls` 一致。
- §5 性能行 `0.028 / 0.506 / 0.525 / 0.282 ms` 出处为 `task-3-report.md:73-74`（`RouterBenchmarkTests` 2 方法 / 4 计量场景，预热 + 3 轮 × 200 次、每轮 P95、判 min-of-3 ≤ 10 ms；计量前先断言 `len(fallbacks)` 防"空跑很快"）⇒ **数字有出处**。
- §8 评审计数（主 agent 已自改）：`Critical 1 / Important 18 / Minor 49`，逐份 T5 `0/5/12`、T6 `0/2/8`、T7 `0/4/9`、T8 `1/4/9`、T9 `0/3/11` 求和 = **1 / 18 / 49** ⇒ **改后措辞准确**（5 份文件求和恰好闭合，且 Critical 归 T8）。

### 2.1 需要改的句子

| # | 位置 | 原句 | 磁盘事实 | 建议措辞 |
| --- | --- | --- | --- | --- |
| A1 | §4 行 10 | 「API 面 200 ｜ 真走 HTTP 面，40.6 s」 | 证据 `assertions[9].observed.caliber` 自述：「生成腿**回放**本次真答案（零第二次外呼），**检索腿替身**；测的是『fallback 成功不塌成 5xx』」；且 `model_used_field = ornith-1.5:9b-text`（与账本 `model=phi3:mini` 不同名） | 「API 面 200（**回放式**：生成腿复用同一次真答案、检索腿为替身，零第二次外呼），40.6 s」 |
| A2 | §4 行 9 | 「零 prompt 入库 ｜ canary **全列** 0 命中」 | 证据 `assertions[8]`：`columns_scanned=19`、`cells_scanned=19`、`needles=5`、`hits=0` ⇒ 扫描面是**临时账本那 1 行 × 19 列**，不是全库全表 | 「零 prompt 入库：临时账本该行 19 列 × 5 枚 canary 全 0 命中（范围=临时库，非仓库真库）」 |
| A3 | §9 | 「当前有 **105 个未提交文件**」 | `git status --porcelain` = **106 条**（55 改 / 1 删 / 50 未跟踪，且未跟踪**目录**折叠计数）；`HEAD = bc2085c` 一致 | 「HEAD 停在 `bc2085c`，工作树有 **106 条 `git status` 条目**（含折叠的未跟踪目录，实际文件更多）」 |
| A4 | §5 行 1 | 「5 条目 **0.028 ms**；60 候选 rag 0.506 / chat 0.525 / agent 0.282 ms」 | 出处文本为「5 条目 **chat** 0.028ms」——0.028 只是 chat 一形，非"5 条目"通值；且口径是 min-of-3 的每轮 P95 | 「5 条目 chat 0.028 ms（min-of-3、每轮 P95；Task 3 基准）」 |

| A5 | §2 交付段 | 「`router`（**7 级过滤**，机器理由码）」 | `plan()` 里清空候选池并抛带 stage 的异常只有 **5** 处（`enabled` / `capability` / `health` / `limits` / `priority`），第 6 枚 `context` 由 Task 4 的调用方接缝自写（`router.py:72-74` 明写"前五个由 plan() 产生"）；"7 级"在 DESIGN / PLAN / task-3-brief / task-3-report 全文**零命中** | 改「五级候选池过滤 + 一枚调用方 `context` 接缝（stage 枚举 6 值）」，或写明"7"的口径来源 |
| A6 | §7 表末两行 | 「`data/audit.jsonl` 不在测试护栏改道范围内」「TypeSafe selective 跳过率跨轮漂移未定位」 | 前 5 行逐条可追到磁盘：`env_file` ⇒ `task-1-report.md`/`review-task-1.md`；A-3 混合形 ⇒ `re-review-task-9-round1.md`；m-7/m-9 ⇒ `review-task-8-findings.md`；epoch/槽位租约 ⇒ `backend/app/resilience.py:5-8,42` 文档字符串（归属列写的是代码，不是 brief，措辞已自洽）。"TypeSafe selective 漂移"属 **TypeSafe V2** 观测项，本 V2.3 的 brief/report 里无对应条目 | selective 行加"（跨版本观测项，出处 = TYPESAFE_V2 验收，非本版评审）"，否则 §7 的"含归属"承诺对这一行不成立 |
| A7 | §8 首句 | 「11 个任务**全部**走『实现 → 独立评审 → 修复轮 → scoped 复审』」 | 磁盘只有 5 份 scoped 复审件（`re-review-task-5..9-round1.md`）；T1–T4 有评审件（`review-task-1..4.md`）但**无独立复审件**，其修复是否经复审只在 progress 行内自述；T10 明写未单开评审 | 改「T5–T9 走完整四环（各有 re-review 文件），T1–T4 为『评审 + 主 agent 复核』三环，T10 由本次终审补审」 |

（§9 的 105/§4 的行 10、行 9 见上表 A1–A3；其余句子对证结果：§1 结论表、§3 D1–D6 与 §8.1/§9.1 两行、§5 行 2/3/4、§6 六条、§7 前 5 行、§8 其余计数句 **与磁盘一致，无需改**。）

### 2.2 对 A2 的自我修正（读到断言体之后）

`test_real_llm_failover_acceptance.py:500-517` 的 ⑨ 实际扫面 = `scan_cells(ledger_rows, needles)` **+** `scan_cells([{"trace_file": json.dumps(on_disk)}], needles)`，
且 needles 是 5 枚（PROMPT_CANARY / 问题原文 / 证据正文前 24 字 / RAG 系统提示前 24 字 / "请依据以下证据回答问题"）⇒
**"全列"是名副其实的**（该 19 列不过滤地全扫），我上表 A2 的说法过重。收窄为：措辞补一句范围（临时账本 1 行 + 临时 trace 落盘件），不必改成"只扫 19 格"。A2 定级 Minor（范围可更精确），不是错误陈述。

## ③ 跨任务一致性（"各自对、合起来错"）

### 3.1 模型名口径四处（`rev11_probe5_model_faces.py` 复跑 + P0 真证据对照）

| 面 | mock 链实测 | P0 真机证据 | 判定 |
| --- | --- | --- | --- |
| 账本 `llm_request_logs.model` | `effective-name-B`（= 真答出这句话的生效名） | `phi3:mini` | 与 M2 口径一致 |
| trace `model_route.attempts[].model` | `['effective-name-A','effective-name-B']`，**零条目 id** | `['ornith-1.5:9b-text','phi3:mini']` | 一致 |
| trace `model_route.primary.model` | `effective-name-A` | `ornith-1.5:9b-text` | 一致 |
| 执行面 `FallbackResult.attempts[].model_id` | 条目 id（设计如此，M4） | `ollama-ornith/ollama-phi3` | 一致（口径不同属已裁事实） |
| `LLMResponse.model` | `effective-name-B` | `phi3:mini` | 一致 |
| **HTTP 响应体 `model_used`** | 探针未覆盖 | **`ornith-1.5:9b-text`**（账本同请求是 `phi3:mini`） | **劈叉，且是结构性的** |

根因（磁盘可查）：`backend/app/main.py:511` 的 `"model_used": current_model_name()`，
而 `app/rag.py:91-133` 的 `current_model_name()` **只跑 `plan()` 拿"计划面的 primary"**，docstring 自己写着
「**不进 fallback**」(107) 与「报的是『计划面的 primary』，不是『这次真会用的那个 primary』」(125)。
⇒ 任何发生 fallback 的请求，响应体名字与账本名字**必然不同**；⑩ 那条 `model_used_field` 不是回放瑕疵，是生产行为。
定级 **Important（I-11-2）**：M2 只把"生效名"口径钉在账本/trace/`LLMResponse.model` 三处，
验收文档 §3「`model` 列口径 = 生效模型名（M2）」容易被读成"四处统一"。
补 A8：§4 行 10 的实测列应写「`model_used` 显示的是计划 primary（`ornith-1.5:9b-text`），真答出的是 `phi3:mini`」。
修法判据一句话：`/api/query` 响应体的 `model_used` 改读本次 `LLMResponse.model`（或 §6 新增第 7 条如实登记这条劈叉）。

### 3.2 两枚哨兵的四处闭环（法条 → 实现 → 归因 → 归零闸）

| 处 | 磁盘事实 | 判定 |
| --- | --- | --- |
| 法条 | 验收文档 §3 §8.1 行 + DESIGN §8.1 第 1/2 条：值域 = provider kind(+`:status`/`:no_fallback`) + 两枚账本侧哨兵；交付闸对「推断」与「链上自写」同样生效 | 在位 |
| 实现 | `app/llm/usage.py:115/118` 两枚常量、`:157` 值域正则（含 §6 四值 + 两枚哨兵）、`:569-578` 交付闸、`:835` 分母只剔 `client_aborted` | 在位 |
| 归因 | 链上自写只产 `unknown`（`app/llm/fallback.py:279` `error.kind if error else "unknown"`）；`client_aborted` **全仓零个第二生产者**（grep `app/**.py`：只有 `usage.py` 写它） | 闭环 |
| 归零闸 | `tests/test_llm_egress_guard.py::UnknownAttributionTests`（`:731-`）：自建库里真跑三种 profile 的失败出口，再要求 `rows>0` **且** `unknown=0` 同时成立——不是读会话库空跑 | 闭环 |
| 行为级证明 | `rev11_probe3_status_green.py` 场景 C：链上自写 10 枚 `client_aborted` 但**零交付事实** ⇒ 落库分布 `[('client_aborted',20),('unknown',10)]`，即那 10 枚被闸改写成 `unknown` 并计入失败分母（`success_rate=0.0`） | **交付闸对"自写"这一路实测有效** |

⇒ 哨兵没有"合起来错"：法条、常量、生产者唯一性、值域正则、归零闸、跨槽行为六处互洽。

### 3.3 能不能构造一种真实故障让 status 页"看起来全绿"——能（一种，已构造）

**构造 A（真实可触发）：注册表能力旗标写坏 ⇒ 零候选全灭**
把 `ollama-ornith` 的 `capabilities.rag` 改成 `false`（`app/rag.py:116` 自己举的例子，无需改代码，改配置即可）。
`rev11_probe3_status_green.py` 实测读数：

```
requests_5m = 0     success_rate = null     fallback_rate = null
aborted_rate = null p95_latency_ms = null   providers = {}   breaker = {}
```

在生产容器里（`task-11-smoke.md` 的实测宿主形态）`providers = {'ollama': {'healthy': True}}`、
`breaker = {'ollama': {'state': 'closed'}}` ⇒ **`llm` 块五键全 null + provider 绿 + 熔断绿**，
而用户侧每一条 RAG 都在吃 D2 兜底文案（HTTP 全 200、账本 0 行、trace 无 `model_route`）。
三条款各自都对（D2「不得 500/503」、M3「零候选不产行」、D4「healthy 只来自 probe」），
**合起来 = 观测面对"最坏的一档故障"完全失明**：没有行就没有比率，没有比率就没有红。
唯一残留信号是一条 `logger.warning`（`rag.py:135`）与 audit 里的失败态，不进 status 聚合。

- 定级 **Important（I-11-3）**，归属 V2.4（与 §7 已 defer 的 `degraded` 键同一批）；
  一句话判据：`llm` 块加一枚 `no_capable_5m`（或 `zero_row_requests_5m`）计数，
  并且「`requests_5m == 0` 且服务在线」时前端不得渲染成"无数据 = 一切正常"。
  本版**不阻 GREEN**（§1 已是 CONDITIONAL PASS，且这条正是"legacy 应急路 + D2"已知限制的观测面投影）。
- 顺带核掉两个候选构造：**B（全 `client_aborted` 风暴）**不是全绿——`aborted_rate=1.0` 单独可见，
  只有 `success_rate=null` 这一处需要前端不把它渲染成 100%；**primary 全灭 + fallback 全成**也不是全绿，
  `fallback_rate` 会顶到 1.0（D4 明令不另建计数器，正是为了让这格可见）。

## ④ Critical / Important / Minor（跨任务与新发现）

**Critical：0。** 本轮没找到任何"正常输入即可 5xx / 账本被污染 / 出口被绕开"级别的新事实；
P0 的真失败-真降级链条有 16 枚点名判据 + 两发盘级互锁（§5.4）背书。

| 级别 | 编号 | 内容 | 证据 | 归属 |
| --- | --- | --- | --- | --- |
| Important | I-11-1 | 证据可**事后修饰**的面还剩 4 处：`files_sha1` 键集不钉、账本数值不重读临时库、trace 不重读、⑩ 的 `status_code` 不在判据里 | `rev11_probe2_mutations.py` 19 发（16 NAMED / 3 SILENT）+ `rev11b_t10_disk_shots.py` S3 GREEN 绕闸 | V2.4 收口件（P0 已跑，不追改证据）；修法 3 行见 §5.4 |
| Important | I-11-2 | `model_used`（HTTP 响应面）= **计划 primary**，账本 = 真答出的生效名；发生 fallback 的请求两处必劈叉。这条劈叉既没进 §3 的 M2 口径句，也没进 §6 的"两处刻意不一致" | `app/main.py:511` + `app/rag.py:91-133`（"不进 fallback"）+ P0 证据 `assertions[9].model_used_field='ornith-1.5:9b-text'` vs `ledger.row.model='phi3:mini'` | 文档本版可改（§3/§6 各一句）；代码侧改读 `LLMResponse.model` 归 V2.4 / 模型控制台 |
| Important | I-11-3 | 零候选全灭（D2 + M3 + D4 三条款合起来）⇒ `llm` 块五键全 null + provider 绿 + 熔断绿，**最坏故障形态在 status 页不可见** | `rev11_probe3_status_green.py` 场景 A 读数（§3.3） | V2.4：`llm` 块补 `no_capable_5m` 计数 + 前端不得把 null 渲染成"正常"（与 §7 m-7 同批） |
| Minor | M-11-1 | §4 行 5 名实不符：断言 `fallback_index_is_one` 打的是 `result.selected_index`，真 `fallback_index` 由 ⑧ 断 | 断言体 `test_real_llm_failover_acceptance.py:476-483` | 文档（A8） |
| Minor | M-11-2 | 十字里有 3 处重叠（③⊂①、⑤≡⑦ 的一半、⑤ 第二条 `context_dropped>=0` 恒真），"十条互不蕴含的门"这个呈现偏满 | §5.2 表 | 文档（A9：加一句"净独立门约 7 枚"） |
| Minor | M-11-3 | 闸内的"判据不退化"四枚变异打在**合成骨架** `_valid_looking_evidence()` 上，不是打在这份真证据上 | `test_real_llm_failover_gate.py:422-447` | 文档可注一句；改探针归 V2.4 |
| Minor | M-11-4 | §5 表未标 0.028 只是 chat 一形、也未标 min-of-3 P95 口径；§9 的 105 已漂到 106 | `task-3-report.md:73` / `git status --porcelain` | 文档（A3/A4） |

**主 agent 自改的那句核过了**：§8「Critical 1 / Important 18 / Minor 49（T5 `0/5/12`、T6 `0/2/8`、T7 `0/4/9`、T8 `1/4/9`、T9 `0/3/11`）」
求和 = 1/18/49，逐份相符，且那句 Critical 的归因（Task 8 降级腿缺第二道 catch）与 `review-task-8-findings.md`、
`re-review-task-8-round1.md` 一致 ⇒ **措辞准确，不必再改**；只有同段第一句"11 个任务全部走四环"需要收窄（A7）。

### 2.3 追加两行（同属 ②，接在 A1–A7 之后）

| # | 位置 | 原句 | 事实 | 建议措辞 |
| --- | --- | --- | --- | --- |
| A8 | §4 行 5 | 「`fallback_index` ｜ 1」 | 该枚断言名 `fallback_index_is_one`，断言体是 `assertEqual(1, result.selected_index)`；账本 `fallback_index=1` 由第 ⑧ 枚断言 | 「`selected_index`（路由侧）= 1；账本 `fallback_index` 由 ⑧ 核」 |
| A9 | §4 表头「P0 真机**十**字」 | 呈现为十条独立门 | ③ 被 ① 蕴含一半、⑤ 与 ⑦ 共用 `selected_index`、⑤ 第二条恒真 ⇒ 净独立门约 7 | 表下加一句："十枚里 ③/⑤ 与 ①/⑦ 有事实重叠，净独立门约 7 枚；重叠是刻意冗余（同事实双取），不影响真失败/真成功/真落库三件事各自有独立证据" |
| A10 | §1 冻结原则行 | 「无一项 spec 被反向放宽；三处 spec 回写都是**先补规格再落实现**」 | 三处回写（DESIGN §8.1、§9.1、PLAN Task 5 段）磁盘都在，且 §9.1 的温度半句已按 Task 7 裁定改过（DESIGN 里已搜不到"0.2→0.1"残留）⇒ 成立；但"先补规格再落实现"的时序只对**修复轮 1** 成立（回写发生在首轮实现与首轮评审之后），照字面读会以为规格先于代码 | 改成"每一处回写都在**下一轮实现落地之前**补规格" |
| A11 | §4 行 2 | 「服务端原文 `llama-server reported out-of-memory during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer of size 820943872`」 | 这句逐字在盘，但位置是 `assertions[1].observed.probe_classification.message`（**探针二次分类**）；链上真正带回执的那枚字段 `llm_error_message_verbatim` 与 `provider_calls[0].error_body_excerpt` 是同一次 OOM 的**另一段**文案（`ggml_vulkan: Failed to allocate pinned memory …`） | 引文后加注「（取自探针 `probe_classification`；链上 `llm_error_message_verbatim` 是同一次 OOM 的另一段服务端文案，两形都含 §6 的 `alloc` 特征）」 |

### 2.4 未改动自证（终审者的手不能脏）

`sha1(docs/MODEL_ROUTER_V23_MATRIX.md) = 0829f2052526b8e2f3a9516aab332d8e802a9a87`（P0 单元格回读裸 `GREEN`）、
`sha1(docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md) = a1291bc642bd78125c63d9456775bc…`（本文件通读 + 0 写）、
`sha1(task10/real-llm-failover-001.json) = f043d2c773d4169471fe80e1d3db24a6647a3efe`；
`backend/data/conversations.db` mtime 停在 `09-24 04:47`（早于本窗口）；零 git 写、零真实外呼（11434 未被打过一次）。
本轮只新增 `rev11b_t10_disk_shots.py` 与本裁定文件。

## ⑤ 仍欠一笔的裁决清单（欠账清点：progress.md 逐条判）

| 欠账（progress 行） | 判定 | 一句话判据 / 归属 |
| --- | --- | --- |
| T1 ⑦「云端 priority/stream/reasoning 旗标与 pricing 为牌价占位，**Task 11 前按账单校准**」 | **仍欠一笔** | `config/llm_registry.json` 三枚云条目仍是 0.40/1.60、0.27/1.10、0.40/1.20 的原样占位，本机零账单 ⇒ 归 T1/V2.4：云 key 到位后按账单重填，且 §7 需登记"未对过账单 ⇒ `estimated_cost` 不得用于结算"这一句（现在全文没提牌价未校准） |
| T2 minor「warmup 同一性无断言」 | **已消化** | 收口件里 `WarmupGateTests` / `ScanningHelpersAreAllLiveTests` 已把"warmup 走的是不是同一份注册表"变成行为断言（矩阵 §1 的闸清单里可点名），且容器冒烟的 startup complete 本身就是 fail-fast 通过的证据 |
| T2 minor「errors 头表格未提新正则」 | **已消化** | `app/llm/errors.py:12` 表格行已写"500 + body 含 `alloc`/`failed to load`/…" |
| T2 minor「报告三处旧指向」 | 已消化（历史文本） | 报告是过程件，不回改；终审不追 |
| T3 Ruling「priority 0 分剔除维持 fail-closed」「fast-path 常驻为 D2 设计前提」 | **已消化** | §3「其它」行第一条原话在案，且 §3.3 的构造 A 证明"fast-path 常驻"的代价已由 D2 语义吸收（不 5xx）；剩余可见性问题记在 I-11-3，不重开 T3 |
| T4 M1–M7 移交终审 triage | 逐条：**M1** 已消化（P0 账本行 `status_code=None` 正是流式/非流式口径的实况，§8.1 未把它当缺陷）；**M2** 已消化并被 3.1 复验（账本/trace/response 三名同口径），但**响应面 `model_used` 是 M2 的漏网之处 ⇒ 转 I-11-2**；**M3** 已消化（"零候选不产行"进 §6/D2），其观测面后果转 I-11-3；**M4**（Attempt 首字段是 `model_id` 不是 brief 的 `model`）已消化——§3 口径与 `rev11_probe5` 实测一致；**M5**（hard 回执措辞）已消化（ratify 后无消费者差异）；**M6**（半截 usage 记 0）仍欠一笔：见下行同批；**M7**（`over_soft` 无消费者）**仍欠一笔** ⇒ 归 V2.4 隐私路由（V2.5 `data_classification`）一并处理，判据：`over_soft` 落地当天必须有至少一枚行为断言，否则删字段 |
| T5 Ruling（§8.1 四点：哨兵值域 / aborted 判据收窄 / additive 两键 / `model_route` 扩三键） | **已消化** | 四处闭环逐点复验（§3.2 表），§3 D 表与 DESIGN §8.1 在案 |
| T5 Ruling（`model_route_payload` 删除，唯一生产者 = `usage.model_route_trace`） | **已消化** | 生产唯一性由 `ROUTE_OBJECT_PRODUCER_FILES = frozenset({"app/llm/usage.py"})` 钉（`task-9-fix-report.md:121`），容器内聚合 7 键读到的形状与 `task-11-smoke.md` 一致 |
| T6/T7/T8 各自的 Ruling（brief 自纠两处、§9.1 温度与两腿形态、agent 链补正段） | **已消化** | DESIGN 里"buffered 腿 0.2→0.1"那半句已不存在（本轮 grep 零命中）⇒ T7 交给 T11 的回写义务已履行 |
| **T8 待用户裁决 ①**「V2.3 出厂形态接受 agent 工具链 100% 走 D2 fast path 吗」 | **仍欠一笔（须用户拍板）** | 文档 §6.5 只说了"关旗标不等于工具轮可用"，没把"出厂即 100% fast path（今天没有任何一枚模型带 tools）"写成对用户可见的接受/拒绝项；判据：§1 条件列或 §10 队列里必须有一句"要 tools ⇒ 配云 key 或新增官方支持 tools 且本机跑得动的条目" |
| **T8 待用户裁决 ②**「`agent_local_fast_path=false` 时零候选该不该报错」 | **已消化（按 D2 无条件降级）** | 裁语在 progress:68 与 §3 D2 行；本版不再重开 |
| **T8 待用户裁决 ③**「`model_used` 改名/改口径是否登记 UI 文案表」 | **仍欠一笔** | 与 I-11-2 同源：UI 文案表（`docs/UI_COPY_GLOSSARY.md`）里没有"响应面 model_used ≠ 账本 model"这条，判据=加一行词条或改读真值 |
| T9 段 A M3a「刻意的 GREEN（变异打在记录谓词自身）」 | **已消化** | 评审判定如实披露（`review-task-9-findings.md`），且由此挖出的两形可绕已降级进 §7（A-3 混合形），文档 §8 那句话与磁盘一致 |
| T9 新增豁免档 `app/llm/fallback.py` | **已消化** | `tests/test_llm_egress_guard.py:414-422` 有指因（`fallback.py:520` 的 `config_failed` 判定是这两枚事实的定义方）+ 拆两档豁免 + 外圈等式不授九键构造权；终审复核：豁免表仍是"逐枚白名单 + 反向等式"形态，没有变成透传 |
| T9 复审 N-1「A-3 混合形可绕」 | **仍欠一笔（已登记 V2.4）** | §7 第二行在案 ⇒ 处置合规，不再是"待终审确认"状态 |
| T10 三条限定（内存诱发失败 / runner 门槛偏保守 / §12 预算装不下冷加载） | **已消化** | §6.2 / §6.3 / §6.1 逐条在案，且证据里 `frozen_range_note` + `memory_before.available_gib=0.44` 可复核 |
| `env_file` 绝对化 | **仍欠一笔（V2.4 产品侧）** | §7 第一行在案；判据：从非 `backend/` 目录起服务能读到 `.env`，且那 6 枚 `TypeSafeJudgmentTests` 的测试侧前提撤掉后仍绿 |
| m-7 响应面缺 `degraded`/`fast_path` 布尔键 | **仍欠一笔（V2.4）** | §7 第三行在案；I-11-3 是它的放大版（没有 degraded ⇒ 零行故障在页面上是"无数据"），建议两笔并成一笔做 |
| m-9 `_classification_query` 与 `llm._query_of` 两份实现 | **仍欠一笔（V2.4 重构）** | §7 第四行在案；判据：合并后两链的 query 归一断言仍绿 |
| `data/audit.jsonl` 不在测试护栏改道范围 | **仍欠一笔（测试卫生 V2.4）** | §7 第五行在案；本轮未新增污染（真库计数 0/7/10 与 P0 前一致，见 §5.4 还原核对） |
| 熔断器无 epoch token / 无槽位租约 | **已消化为"已知限制"** | 限制写在代码文档字符串（`app/resilience.py:5-8,42`）且 §7 第六行登记了归属；不是待确认项 |
| TypeSafe selective 跳过率跨轮漂移 | **仍欠一笔（跨版本观测项）** | §7 末行在案，但出处不属本版（见 A6）：建议标注版本归属，否则本版"含归属"的承诺对这行不成立 |

**净结论**：真"待终审确认"已全部清零（T5 的 §8.1 四点、T9 的 M3a/豁免档/N-1 都已裁定并落文）；
剩下的欠账全部有归属，其中**只有 T1 ⑦（云牌价）与 T8 ①③（fast-path 出厂形态 + UI 文案表）需要用户拍板**，
其余是 V2.4 工程欠账。

## ⑦ 我跑过的命令与 sha1 表

| 命令（全部在 `E:/xiangmu/rag/…`） | 目的 | 关键输出 |
| --- | --- | --- |
| `python -c`（矩阵状态单元格计数） | §1/§4 行计数 | 26 枚状态：GREEN 22 / PENDING_EXTERNAL 4；id 集 `1..19,12b,N-3,P0,C1..C4` |
| `git log --oneline -1` / `git status --porcelain \| wc -l` | §9 | `bc2085c` / **106**（55 M + 1 D + 50 ??） |
| `grep -rn "0\.028\|0\.506" *.md` | §5 出处 | `task-3-report.md:73-74` |
| `python rev11_probe2_mutations.py` | 5.1 | 基线 `[]`；19 发 = 16 NAMED / 3 SILENT（sha1 键集 / 账本数值 / trace 重读） |
| `python -m pytest tests/test_real_llm_failover_acceptance.py --collect-only -q` | 5.3 | **0 collected**（默认） |
| `REAL_LLM_ACCEPTANCE=1 … --collect-only -q` | 5.3 | **1 collected**（`RealLlmFailover001Tests::…_ten_assertions`） |
| `python rev11b_t10_disk_shots.py` | 5.4 / 2④ | S1 RED、S2 RED、S3 **GREEN（绕闸）**、S4 RED；`finally` 字节还原 |
| `python rev11_probe5_model_faces.py` | 3.1 | 五面同名一致、trace 零条目 id；`model_used` 不在其覆盖面 |
| `python rev11_probe3_status_green.py` | 3.3 | 场景 A：`requests_5m=0`、四比率全 null；场景 C：自写 `client_aborted` 10 枚被改写成 `unknown` |
| `python -c`（snap 对照 sha1） | 诚实性抽查 | 见下 |

**sha1 表（发靶前 = 还原后，逐字节相等）**

| 文件 | sha1 | 结果 |
| --- | --- | --- |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | `0829f2052526b8e2f3a9516aab332d8e802a9a87`（25340 B / 163 LF） | 打 S4 后还原，**回读一致**；P0 单元格回读为裸 `GREEN` |
| `task10/real-llm-failover-001.json` | `f043d2c773d4169471fe80e1d3db24a6647a3efe`（18289 B） | 打 S1/S2/S3 后还原，**回读一致**（另一次崩溃也由 `finally` 还原，已单独复核同值） |
| `backend/tests/test_agent_routing_contracts.py` | `0f9f293daefb…` | 与 `snap-task8/`、`snap-task8-r1/` 两份快照 **IDENTICAL** ⇒ T8 报告「一字未动」**为真** |
| 9 枚冻结件（`fallback/normalize/usage/__init__/rag/conversation_agent/agent_routes/security/registry`） | 逐个 | 相对 `snap-task9` **全部 IDENTICAL**；相对 `snap-task8` 只有 `normalize.py` 不同（T9 自己的授权改动 `41597af450…`，与 `task-9-fix-report.md:289` 自报值同前缀）⇒ T9「逐枚 IDENTICAL」**为真** |

### 5.5 诚实性抽查（三句最自夸的话，逐句去 diff 找反例）

| 句子 | 反例找到了吗 | 判定 |
| --- | --- | --- |
| T8 报告：「`test_agent_routing_contracts.py` **一字未动**（sha1 仍 `0f9f293daefb`）」 | 未找到：三份快照 + 现值同摘要 | **属实** |
| T5 报告：「净结论：T4 那一例本身**不降强度**」 | 报告自己就把反例写全了（旧版那枚 `assertEqual(1, len(rows))` + `route_mode` 在新版里没有主人），并交代了补回位置 ⇒ 我去磁盘验了补回例真实存在：`tests/test_llm_usage_contract.py:2058` | **属实（且是自曝式表述，不是掩盖）** |
| T9 修复报告：「`_degrade_to_local_fast_path` 的判据**一字未动**（DENIED 仍不吃门）」+「9 枚冻结件逐枚 IDENTICAL」 | 未找到：冻结件对 `snap-task9` 全等；`agent.py` 不在冻结集，但其降级腿判据面在 `re-review-task-8-round1` 已被逐字比对过 | **属实** |
| （加检一句）验收文档 §2「`native_stream.py` **退役**」 | 未找到反例：`git status` 有 `D backend/app/native_stream.py`，且有 `assertFalse(...exists())` 断言 | 属实 |

⇒ **抽查结论**：三份报告与验收文档的自夸句本轮全部经得住 diff/摘要复核；本轮新增的三枚 Important
（I-11-1/2/3）都是"没人说过假话、但也没人看过这一格"类型的组合洞，而不是陈述失实。

## ① Verdict（终）

**ACCEPT-with-corrections。**

950/0/992 的终态、P0 真机十字、四枚反造假闸与 D6 收口件都经得住独立复核（本轮亲跑 9 项、
盘级 4 发、内存级 19 发、快照 sha1 逐枚对照，Critical 0）；但**验收文档还带不走**：11 处措辞必须改
（A1–A11，其中 A1「真走 HTTP 面」与 A9「十条互不蕴含」是两处对读者会形成错误印象的 overstated 表述），
外加三枚 Important 要按 §5 的清单登记进 §6/§7（I-11-1 证据事后修饰、I-11-2 `model_used` 劈叉、
I-11-3 零行故障在 status 页失明）。两笔欠账要用户拍板（T1 云牌价未校准、T8 出厂 100% fast-path 形态），
其余欠账全部有归属、可随 V2.4 走。**不建议 REJECT**：没有一条判据是纸面的，也没有一处 spec 被反向放宽。

## ⑥ Task 10 补审结论（原编号 ⑤，为让"Critical/Important/Minor"与"欠账清单"排在前面而后移）

### 5.1 判据会不会被事后修饰——内存级 19 发实测（`rev11_probe2_mutations.py`，本轮复跑）

`validate_evidence(真证据) = []`（基线成立）。对**这份真证据**的深拷贝打 19 发，16 发点名、**3 发完全静默**：

| 静默变异 | 为什么静默 | 定级 |
| --- | --- | --- |
| 把 `files_sha1` 整表换成**别的真文件的真摘要**（探针件/矩阵/闸文件） | `kit.py:553-559` 只遍历表里给的 (path, digest) 逐枚重算，**不钉键集**、不要求键必须等于 `ledger.path` / `trace.path` / 用例源码 | **Important（新发现 I-11-1）** |
| 账本行数值整块编造（`input_tokens=99999`、`request_id=p0-req-forged`、`created_at=2020-…`） | 判据只查 `fallback_index / success / model / 禁存列` 四件事，**不重读临时库文件**——而 `task10/run/20260924-215206/conversations.db` 此刻仍在盘上，重读是免费的 | Important（同上，合并计一枚） |
| `trace.path` 换成探针件 + `lines=1` | 同上：trace 面不重读 | 同上 |

另两枚"半静默"值得登记：`⑩ 的 observed.status_code` 与 `⑨ 的 hits` 都不在判据里（改 500 / 改成非空 hits 都不会被 sha1 之外的规则拦下）——见 §5.4 盘级复验。

**判据在闸内的自证是"合成骨架"而不是真证据**：`test_real_llm_failover_gate.py:422-447` 的四枚变异打在
`_valid_looking_evidence()`（现场拼的骨架，`files_sha1` 里放探针件真摘要）上。⇒ 验收文档 §4「判据自身被四枚变异打」**字面成立**，
但它证明的是"函数没退化"，不是"这份证据改一个字就红"。补审因此自己补打盘级两发（§5.4）。

### 5.2 十枚断言的独立性（读断言体逐枚）

| 结论 | 依据 |
| --- | --- |
| **③ 被 ① 部分蕴含** | ① 的 observed 已含 `attempts[*].model_id/result`（两枚），③ 的 `assertEqual(FALLBACK_ENTRY_ID, attempts[1].model_id)` + `assertEqual("success", attempts[1].result)` 是同一份 `result.attempts` 的第二次读；③ 独有的只有 `len(self.provider_calls)==2` 与出口面 `call_fallback` 两枚 |
| **⑤ 与 ⑦ 重复且名实不符** | ⑤ 名叫 `fallback_index_is_one`，断言体却是 `assertEqual(1, result.selected_index)`；真正的 `fallback_index` 由 **⑧** 断（`ledger_row["fallback_index"]==1`）。⑤ 的第二条 `assertGreaterEqual(result.context_dropped, 0)` 是**恒真**（该字段是计数器，构造上非负）⇒ §4 行 5 的口径要改（A8） |
| **⑦ 内部第一条被第二条蕴含** | `assertEqual(2, len(attempts))` 之后 `assertEqual([PRIMARY,FALLBACK], [a.model for a in attempts])` 已蕴含长度=2；且 `selected_index==1` 与 ⑤ 同字段 |
| **⑥/⑧/⑨ 互补、不重复** | ⑥ 管同源（trace_id/request_id + trace 恰好 1 行）、⑧ 管形状与语义（19 列实测值 + 成功行不得带 error_type + total_tokens>0）、⑨ 管禁存面（全列 + trace 文件） |
| **④ 独立且是真门** | 长度下限 + CJK 下限 + 反兜底文案 + `response.model == phi3` 四条互不蕴含 |
| **⑩ 是最弱一枚（但不是恒真）** | `record(10, …, lambda: self._http_face_200(answer), lambda: [])` 的**判词列表为空**，pass 完全来自观察函数不抛异常；函数内确实 `assertEqual(200, response.status_code)` + 答案逐字相等 ⇒ 运行期有牙，但**证据面事后改 500 无人核**（§5.4 S3） |

⇒ 净独立门数约 **7** 枚（10 枚里有 3 处重叠：③⊃①、⑤≡⑦ 的一半、⑤ 第二条恒真）。这不推翻 P0（真失败/真成功/真落库三件事各自都有独立证据），但**验收文档 §4 把"十字"当成十条互不蕴含的门来呈现**，需要一句话交代重叠。

### 5.3 收集闸今天仍成立（亲跑）

`--collect-only` 于 `backend/` 下：**默认 0 枚 / `REAL_LLM_ACCEPTANCE=1` 恰好 1 枚**（原始输出见 §6 命令表）。

### 5.4 盘级"事后修饰"四发（`rev11b_t10_disk_shots.py`，真写盘 + 发内还原）

| 发 | 攻击 | 结果 | 点名判据 |
| --- | --- | --- | --- |
| S1 | 盘上证据的 `provider_calls[0].error_body_excerpt` 换成通用文案 | **RED** `1 failed, 20 passed, 48 subtests` | `'primary 的错误体不含 §6 的加载失败特征字面'` → `test_real_llm_failover_gate.py:411` |
| S2 | `ledger.rows` 1→2（"多写一行账本"） | **RED** 同上 | `'临时库行数 2 != 1'` |
| S3 | **`assertions[9].observed.status_code` 200→500** | **GREEN ⇒ 闸被绕过** | 无 —— `validate_evidence` 不看 ⑩ 的状态码，`pass` 字段仍是 true |
| S4 | 矩阵 P0 状态 GREEN→BLOCKED | **RED（互锁闸如期红）** | `'证据已经成立…矩阵还写着 BLOCKED'` → `test_real_llm_failover_gate.py:417` |

还原证明（脚本 `finally` 字节还原 + 事后独立复核，两条都过）：
`sha1(matrix) = 0829f2052526b8e2f3a9516aab332d8e802a9a87`（25340 B，P0 单元格回读为裸 `GREEN`）、
`sha1(evidence) = f043d2c773d4169471fe80e1d3db24a6647a3efe`（18289 B），均与打靶前初值逐字节相等。

**结论（Task 10 补审）**：闸不是纸面的——S1/S2 两发（正是主 agent 点名的两发）都点名到判据字面，S4 的互锁双向成立
（状态写 BLOCKED 而证据成立也红，见 `:417` 与 `:411` 两支）。但**盘级存在一枚真洞 I-11-1**：
⑩ 的 `status_code` 这类"只进 observed、不进判据"的字段可事后改，配合 §5.1 的三发静默（sha1 键集不钉 /
账本数值与 trace 不重读），共同构成一句话：**这份证据"改一个字就红"只在被点名的 16 个位上成立**。
最小修法（判据一句话可验）：`validate_evidence` 加三行 ——
`{str(ledger.path), str(trace.path)} ⊆ set(files_sha1)`、
`assertions[9].observed.status_code == 200`、
`sqlite3.connect(ledger.path)` 重读行数与该行的 `model/fallback_index/success/total_tokens` 并全列重扫 canary
（临时库仍在盘上，成本为零）。定级 **Important（不阻断 V2.3 GREEN，因 P0 十字的真事实已由 S1/S2 类位覆盖）**。
