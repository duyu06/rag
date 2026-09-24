# Task 10 段 A 报告：P0 的前置件、反造假闸与证据采集器（**未执行 phi3 那一半**）

日期：2026-09-24 · 承载：`REAL-LLM-FAILOVER-001`（DESIGN §10 P0 行，十字）
分工边界：段 A 做完「闸 + 采集器 + 用例正文 + runner」，**phi3:mini 的真实加载等用户放行**。
本机实测可用内存一直在 0.52 ↔ 3.46 GiB 之间跳（phi3:mini 权重 2.03 GiB），
所以下面每一次真调用都刻意只花了一次（A-2 的 ornith 探针），其余全部离线。

---

## 1. 改动面（零 git 写 / 零 `app/` 产品代码改动 / 零 `config/` 改动）

| 文件 | 动作 | 角色 |
| --- | --- | --- |
| `backend/tests/real_llm_failover_kit.py` | 新建 | 共享件：收集开关、A-2 有界探针、环境/内存前置、证据 schema 与 `validate_evidence()`、`green_permission()`、离线自检 `selfcheck_primary_leg()` |
| `backend/tests/test_real_llm_failover_acceptance.py` | 新建（纯 LF） | A-3：P0 十枚断言正文 + 临时库/临时 trace + 证据落盘。**默认不被收集** |
| `backend/tests/test_real_llm_failover_gate.py` | 新建 | A-1：三枚反造假闸 + 闸自身完整性（15 枚例，默认可收集） |
| `.superpowers/scripts/run_p0_failover_acceptance.sh` | 新建 | A-4：一键 runner，带 `--dry-run` / `--probe` / `--yes` |
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10_mutations.py` | 新建 | 变异台（M0–M4），byte-safe：改前记 sha1、发完还原、还原后核对 |
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10_rehearsal.py` | 新建 | 十枚断言的**离线彩排**（MockTransport + A-2 真错误体） |
| `docs/MODEL_ROUTER_V23_MATRIX.md` | 改文案（**状态字段一字未动**） | §4.5 新增三枚闸的口径；P0 行的「承载测试」补上真机半段与闸的 node-id（`| BLOCKED |` 保持原样） |
| `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/` | 新建目录 | 现场件：`ornith-primary-load-probe.json`、`preflight.json`、`rehearsal/`（真跑后才有 `run/<stamp>/`） |

产品侧 `app/llm/*`、`app/main.py`、`config/llm_registry.json` 全部零字节改动（§5 的 cwd 问题、
§12 预算问题都以**测试侧 patch** 绕过，见 §7 的待裁清单）。

---

## 2. A-1 反造假闸：三问各自钉什么

复审点名的洞是真的：`MatrixDocumentClosureTests::test_every_row_carries_a_real_test_or_an_honest_status`
只做 AST 存在性核对（`_test_index()`），所以「P0 例挂 `@skipUnless` + 矩阵写 GREEN」
在过去同时骗得过套件与文档。闸 `test_real_llm_failover_gate.py` 补三问：

**① 源码面 + 运行面（`P0CarrierHasNoSkipBranchTests`，5 枚）**
- 承载例先被**确定身份**：恰好一枚「类名含 Failover ∧ 继承 TestCase」的 `test_*` 方法
  （`test_the_carrier_exists_and_is_exactly_one`）——否则「零 skip」可以靠删例成立；
- 令牌集 `SKIP_NAME_RE` / `SKIP_STRING_RE` 扫 AST 的四个面：装饰器/名字/属性/关键字参数、
  **非 docstring 的字符串常量**（大小写不敏感**子串**，所以 `getattr(unittest, "ski"+"pIf")`
  里 `"ski"`/`"pIf"` 任一段都命中不了、但 `"skipIf"` 这类整词命中；子串规则是为了
  不让「把令牌写进字符串再 getattr」成为后门）、裸 `exec/eval/compile/__import__/vars`
  调用、`getattr(obj, "<skip 名>")` 的**字面量第二参**；
- 运行面逐枚探 `__unittest_skip__` / `__unittest_expecting_failure__` /
  `__expected_failure__` / `__test__ is False`；
- `getattr(fn, "__wrapped__", fn)` 的**整条链逐跳**重扫 + 三枚同源校验
  （每跳 `co_filename` 必须是承载例那个文件、`__qualname__` 尾段必须能在该文件 AST 里找到）
  ——`functools.wraps` 会把 `__qualname__` 冒充成原方法（M4 实测），所以只看名字会被骗，
  `co_filename` 骗不过；
- 采集器 `real_llm_failover_kit.py` 本身也在①射程内（它能定义「什么算证据成立」）。
- docstring **有意**放行：模块 docstring 必须能写「不许用 skipUnless 冒充」这句话，
  否则闸连自己的判据都写不清楚。放行范围是 Module/Class/Function 三层的首表达式，
  别的字符串常量一律算命中。

**② 收集面（`P0CollectionGateTests`，4 枚）**
- 结构：收集门必须是模块**末尾唯一**一枚 `if not kit.acceptance_enabled():`（一元、
  无 `else`、无额外参数），且 body 只有一件事——`del` 掉那枚承载类；
- `kit.acceptance_enabled()` 的源码里**只许读一枚 env 名**（正则实测 = `["ENV_SWITCH"]`），
  且 `ENV_SWITCH == "REAL_LLM_ACCEPTANCE"`、`SWITCH_ON == "1"`（改名要先过这枚）；
- **双向**子进程判据（真跑 pytest 收集器，不在进程内模拟）：
  关 ⇒ `--collect-only` 收集数**恰好 0** 且输出里**不许出现 `skipped`**
  （「既不红也不冒充绿」这件事本身是断言）；开 ⇒ **恰好 1**、退出码 0；
- 再加一枚便宜的仓级钉：全仓 `tests/test_*.py` 里除承载例外，**任何**文件都不许出现
  「顶层条件性 `del 类`」——换文件名给自己开后门、或把同一招用在别的用例上，当场红。
  （刻意不跑全仓 `--collect-only`：实测那一句要 26–30 秒，而它抓的东西 AST 就能抓住。）

**③ 文档面（`P0MatrixStatusLockedToEvidenceTests`，3 枚）**
- 合法取值**写死在闸里**：`P0_STATUS_WITHOUT_EVIDENCE="BLOCKED"` /
  `P0_STATUS_WITH_EVIDENCE="GREEN"`，并有一枚元断言钉这两枚常量的值 + 矩阵文档里
  「状态值域只有 `GREEN / PENDING_EXTERNAL / BLOCKED`」那句原文；
- 状态从 `docs/MODEL_ROUTER_V23_MATRIX.md` **现读**（`kit.matrix_p0_status()` 复用
  `MatrixDocumentClosureTests.parse_matrix_rows`，不复制第二份解析），证据从
  `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json` 现读，
  判据是 `validate_evidence()`：**证据不成立 ⇒ 那一行只许 BLOCKED；证据成立 ⇒ 只许 GREEN**，
  两边不对称都红，失败信息直接点名「改状态之前先跑 runner」；
- `test_the_evidence_judgment_does_not_degrade` 拿四枚变异打判据自己
  （模型序 / 错误体不含加载特征 / 账本行数≠1 / sha1 对不上），每缺一枚必须**点名**该项。

**④ 闸自己（`P0GateSelfIntegrityTests`，3 枚）**：本文件零 skip 令牌（字符串面换成
`getattr(…, "<字面量>")` 精确规则，否则令牌清单会自我命中）、四枚类逐枚挂在矩阵上（反向耦合，
口径同 §前言第 ④ 条）、闸自己在默认套件里必须被收集到 ≥8 枚且三枚核心判据在清单里。

### 变异证据（`task10_mutations.py` 实测，byte-safe + 还原核对）

改前基线：`MODEL_ROUTER_V23_MATRIX.md` sha1 `9fcb5277…5f263`、
`test_real_llm_failover_acceptance.py` sha1 `f2c57aec…309f`。
（注：`红的判据` 清单要连 `SUBFAILED(...)` 一起解析，只认 `FAILED ` 会让
「红在 subTest 里」的判据从清单上消失——第一版就踩过这个坑。）

| 变异 | 内容 | pytest 结果 | 红掉的判据 |
| --- | --- | --- | --- |
| M0 | 不改（对照） | 15 passed / 11 subtests | 无 |
| **M1** | **P0 例挂 `@unittest.skipIf(True)` + 矩阵改 GREEN**（复审点名的那一发） | **5 failed / 12 passed** | `test_carrier_source_has_zero_skip_family_tokens`、`test_carrier_class_and_method_carry_no_runtime_skip_marks`、`test_unwrapped_call_chain_is_clean_hop_by_hop`、`test_p0_row_status_matches_the_evidence` |
| M2 | 只把矩阵 P0 行改成 GREEN | 1 failed | `test_p0_row_status_matches_the_evidence` |
| M3 | 收集门长出第二枚 env 条件（`and os.environ.get('M3_EXTRA')`） | 4 failed | `test_the_gate_is_exactly_one_env_switch`、`test_collected_zero_when_off_and_one_when_on`、①的运行面两枚（类被摘掉 ⇒ 拿不到承载例） |
| M4 | `@getattr(unittest, "ski"+"pIf")(True, …)`（源码面故意看不见） | 2 failed | `test_carrier_class_and_method_carry_no_runtime_skip_marks`、`test_unwrapped_call_chain_is_clean_hop_by_hop`（靠 `co_filename` 抓住 `functools.wraps` 的冒充） |

**我自己试的三招与结论**
1. **挂 `@unittest.skipIf(True)` 并把矩阵写 GREEN** ⇒ 红四枚（M1）。被封。
2. **把令牌拆成字符串片段再 getattr**（绕①源码面） ⇒ 源码面确实看不见，
   但①的运行面（`__unittest_skip__` 已贴在方法上）与 `__wrapped__` 链的 `co_filename`
   双双红（M4）。被封。
3. **用假传输跑一遍再交一份漂亮 JSON**（`_transport = httpx.MockTransport(...)`）
   ⇒ 证据里带着 `provider_transport="MockTransport"`，`validate_evidence()` 有一条专门
   判据拒收；连 P0 用例自己都会**只红这一枚**（彩排的既定终态，见 §5）。所以假跑不出 GREEN。
4. （附）门长出第二个条件 ⇒ ②红（M3）；只改文档文案 ⇒ ③红（M2）。

**诚实边界（残留风险，别把闸读成密码学保证）**：证据 JSON 本质是**自述**。闸能确定性地
拒掉「结构造假」（缺项、模型序、无服务端原文、sha1 对不上、挂了 mock 传输），
但挡不住一个能同时伪造 phi3 中文答案 + 临时库文件 + sha1 的人。真正的不可伪造点是
「phi3 的那句中文只能真生成出来」+「`files_sha1` 里钉着 P0 用例源码（改过代码 ⇒ 证据过期）」。
建议 T11 验收文档把 `answer.text` 原文与 trace 行一并贴出来，让人眼做最后一道判据。

---

## 3. A-2 真探针：**原始输出逐字**

一次真实加载尝试（`POST http://localhost:11434/api/chat`，`num_predict=1`、
`keep_alive="0"`、超时 120 s、失败即停；没碰 phi3、没碰云）。
现场文件：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/ornith-primary-load-probe.json`。

请求（211 字节，形状 = `normalize.ollama_payload` 的现网同形）：

```json
{"model": "ornith-1.5:9b-text", "stream": false, "keep_alive": "0",
 "messages": [{"role": "user", "content": "Reply with exactly one word: pong"}],
 "tools": [], "options": {"temperature": 0.2, "num_predict": 1}}
```

**状态码 / 耗时 / 原始错误体（一字未改，含 JSON 转义）：**

```
status_code : 500
elapsed_ms  : 22465.5      （22.47 秒）
raw_error_body_chars : 191
raw_error_body :
{"error":"llama-server reported out-of-memory during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer of size 820943872\nerror loading model: unable to allocate Vulkan0 buffer"}
```

**过一遍 T2 的真归类（`app.llm.errors.classify(500, 上面原文)`）：**

```
kind          : model_unavailable
no_fallback   : False            （⇒ 允许换候选，正是 P0 要的）
retryable     : False            （⇒ 不重试当前模型，同模型再发只是白等）
message       : 模型不可用（alloc）：{"error":"llama-server reported out-of-memory during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer of size 820943872\nerror loading model: unable to allocate Vulkan0 buffer"}
marker 命中   : "alloc"（§6 冻结四枚字面之一，不是新增正则那条收窄分支）
```

前置/后置事实：`/api/ps` 前后都是**空**（`loaded: []`，`keep_alive=0` 生效，ornith 没常驻）；
`/api/tags` 三条目都在（5.24 / 6.1 / 2.03 GiB）。
**结论：T2 的 `500 + alloc/failed to load` 那一族归类今天仍然命中**，且 P0 的
「primary 真失败」有了可复核的现场证据（含真实服务端文案与真实 22 秒耗时）。

**顺带一条对验收有用的量化**：一次加载失败就要 22.5 秒。§12 出厂
`llm_model_timeout_seconds=20` **小于**这个数字 ⇒ 真机上 primary 腿会以「超时」而不是
「model_unavailable」收场（归类会漂成 `retryable`，还会多吃一次重试）。这就是 §7 第 1 条待裁项。

---

## 4. A-3 P0 用例正文：十枚断言各自怎么验

文件 `backend/tests/test_real_llm_failover_acceptance.py`，
唯一用例 `RealLlmFailover001Tests::test_real_llm_failover_001_ten_assertions`。
真走 `llm.complete(messages, mode="rag", temperature=0.2, num_predict=256,
keep_alive="0", trace_id=…, request_id=…)`——**不 mock 传输层**，classifier → plan →
run_complete → provider → usage 一条全链。观测只加一层「记录并原样透传」的
`provider.complete` 包（异常照样 `raise` 原对象），为的是留下出口面事实：
真错误体原文、请求字节数、逐次耗时。

| # | §10 P0 十字 | 实测判据（全部同时进证据） |
| --- | --- | --- |
| 1 | primary 真被调用 | `result.attempts[0].model_id == "ollama-ornith"` 且 `result == "failed"`；出口面 `calls[0].model == "ornith-1.5:9b-text"`、`request_bytes > 0`、`ok is False`。刻意注：拿到「意外成功」也判红（前提不成立时不许读成通过） |
| 2 | 失败归类 model_unavailable | 执行面 `attempts[0].error_type == "model_unavailable"` + 出口面 `error_kind` 同名 + `http_status == 500` + 错误体摘要 ≥20 字**且**含 `MODEL_UNAVAILABLE_MARKERS/PATTERNS` 之一（拿 §3 的真原文对齐；证据里同时贴 A-2 探针的 classification 做交叉核对） |
| 3 | fallback 被调 | `len(attempts) >= 2`、`attempts[1].model_id == "ollama-phi3"`、`result == "success"`、出口面 `calls[1].model == "phi3:mini"` 且 `ok is True`、**真外呼次数恰好 2**（多走一步也算红） |
| 4 | phi3 有效中文回答 | 非空、`strip() ≥ 8` 字、CJK 字符 `≥ 4`、不等于四枚「未找到依据」类兜底文案、`response.model == "phi3:mini"`（响应的模型名必须是真答出这句话的那枚）。下限刻意保守——phi3:mini 是真会只回一句 |
| 5 | fallback_index==1 | `result.selected_index == 1`（证据另记 `reason_codes` 与 `context_dropped`） |
| 6 | trace_id 全链一致 | 入口常量 == 落盘 trace 行的 `trace_id` == 临时库行 `trace_id`（`request_id` 一并核）；trace 文件**恰好一条** |
| 7 | model_route 两枚 attempt | `attach_model_route` 挂载后九键集合等式（§8.1 第 4 条）+ `route["attempts"]` **两枚**、模型名序 `ornith → phi3`、`attempts[0].error_type == "model_unavailable"`、`stage == "fallback"`、`selected_index == 1` |
| 8 | usage 落库一行 | 临时库 `llm_request_logs` **恰好 1 行**；该行 `model == phi3:mini`、`fallback_index == 1`、`success == 1`、`route_mode == "rag"`、`error_type ∈ (None, "")`（成功行不许带哨兵）、`total_tokens > 0`（零 token = 这次生成其实没发生） |
| 9 | 零 prompt 入库 | **全列**扫：五枚 canary（含 `PROMPT_CANARY`、问题原文、证据块、系统提示词前 24 字、"请依据以下证据回答问题"）扫 1 行 × 19 列 + 整份 trace JSONL 文本，命中必须 `== []`；证据里记 `columns_scanned` 与 `cells_scanned` |
| 10 | API 面 200 语义 | `TestClient` 真打 `POST /api/query`（真登录 admin → Bearer），检索腿用替身、**生成腿回放本次已捕获的真答案**（零第二次外呼），断言 `status_code == 200` 且 `answer ==` 真答案。口径写在证据的 `caliber` 字段里，不假装它是端到端 |

收尾两件事：`08_assemble_evidence` 把账本行/trace 行**从盘上重读**后组装证据
（`provider_calls` / `ledger` / `trace` / `chain` / `files_sha1`），然后跑
`validate_evidence()` 自校验（十枚全过 + 证据自洽才落 `completed=true`），最后打印
每步耗时、sha1 表、以及 `green_permission()` 的结论。

**隔离姿势（不污染 `backend/data/`）**
- 账本：`setUp` 里 `mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": <绝对临时路径>})`
  + `usage.init_usage_db(<同一路径>)`，`addCleanup` 还原 + `reset_usage_state()`；
  `llm.set_usage_sink(None)` 走**默认 sink**（P0 要的就是真落库，不是假 sink）。
- trace：`mock.patch.object(app.agent_trace, "TRACE_PATH", <临时绝对路径>)` 之后
  `save_trace()` 真落 JSONL 一行。
- 目录：`task10/run/<时间戳>/{conversations.db, agent_traces.jsonl}`，
  彩排件另落 `task10/rehearsal/run/<时间戳>/`，两边互不冒充。
- 证据里带 `protected_repo_ledgers` = `conftest.real_ledger_row_counts()`，
  跑完顺手证明仓库真实库仍是 0 行（与 `LedgerIsolationGuardTests` 同口径）。
- 超时与耗时：预算给到 `llm_total_budget_ms=900000` / `llm_model_timeout_seconds=300`
  （见 §7 待裁 1），`timed()` 给每一步打毫秒，`record()` 给每枚断言打毫秒。

**已证明的可收集性**（不加载 phi3）：
- 默认：`pytest tests --collect-only -q` ⇒ **950 tests collected**（基线 935 + 闸 15 枚；
  P0 文件贡献 **0**，`grep real_llm_failover_acceptance` = 0 命中）；
- 开开关：`REAL_LLM_ACCEPTANCE=1 pytest tests/test_real_llm_failover_acceptance.py --collect-only -q`
  ⇒ 恰好 1 枚 `RealLlmFailover001Tests::test_real_llm_failover_001_ten_assertions`。

**离线自检（不加载 phi3 也验掉的部分）**：`kit.selfcheck_primary_leg()` 四段——
① 用 A-2 的**真错误体**过 `errors.classify` ⇒ `model_unavailable`（`no_fallback=False`、
`retryable=False`）；② 出厂注册表 `mode=rag` 的计划 ⇒
`primary=ollama-ornith, fallbacks=[ollama-phi3], reasons=CAPABILITY_MATCH+LOCAL_PREFERRED+HIGHER_PRIORITY`；
③ ornith 条目的生效模型名 ⇒ `ornith-1.5:9b-text`；④ 出口报文含 canary（278 字节）
且 §8 的 19 列里没有任何能装 prompt 的列名。四段全过（runner 的 `[1/4]` 每次都会跑）。

再往上一层是**十枚断言的接线彩排**（`task10_rehearsal.py`，MockTransport + A-2 真错误体 +
phi3 形状假应答）：结果 **10/10 断言全过**（含 #10 的 TestClient 200、#8 的一行账、
#9 的零 canary），且用例**自己恰好红一枚**在「证据自校验」——因为证据记着
`provider_transport="MockTransport"` 被判据拒收。这正是设计意图：**同一份代码在真机上
不会有这枚红**，而任何人想用假传输交 GREEN 证据都会撞上它。
彩排一次性抓出三处「真机跑 5 分钟才会发现」的接线错：注册表相对路径（cwd）、
`LLMResponse` 没有 `.usage` 属性（真字段是 `input_tokens/output_tokens/usage_estimated`）、
mock 必须接住 §5 健康视图的 `GET /api/tags`（否则 `plan()` 在 `stage=health` 直接零候选）。

---

## 5. A-4 runner 用法（`bash .superpowers/scripts/run_p0_failover_acceptance.sh`）

```
--dry-run   只查环境 + 跑离线自检 + 打印将要执行的命令，零模型调用（实测退出码 0）
--probe     在 dry-run 的骨架上追加一次 A-2 有界探针（覆盖探针件）
（无参数）   真跑：前置 → 自检 → REAL_LLM_ACCEPTANCE=1 pytest → 回打证据 → 打印许可判定
--yes       显式越权内存门槛（当前这台机器不满足，必须带它才会真跑）
```

四步：`[0/4]` 环境前置（`/api/tags`+`/api/ps`+**三次**内存采样取 `min`，
低于 3.2 GiB 判「不够」；已加载模型非空也判前置不满足）→ `[1/4]` primary 腿离线自检 →
`[2/4]` 打印要执行的命令与证据路径 → `[3/4]` 真跑 → `[4/4]` 十枚断言实测值、两次真外呼的
模型名/字节数/耗时/状态码、临时库路径与行数、仓库真实库行数、sha1 表、
以及 `green_permission()` 的三枚许可条件。
退出码：0 成功 / 1 用例红 / 2 参数错 / 3 内存门槛未过（未给 `--yes`）/ 4 前置不满足。
**它不改矩阵文件**：只打印判定，`docs/MODEL_ROUTER_V23_MATRIX.md` 那一行留给主 agent 落笔。
（`--dry-run` 下内存判定只报告不拦截；实测本机 `最低可用 2.52 GiB < 3.2`。）

---

## 6. 定向绿的确切数字

```
cd backend
python -m pytest tests/test_real_llm_failover_gate.py tests/test_llm_egress_guard.py \
                 tests/test_real_llm_failover_acceptance.py tests/test_llm_usage_contract.py \
                 -q -p no:cacheprovider
  → 151 passed, 136 subtests passed in 50.90s（0 failed）

python -m pytest tests -q -k "Matrix or P0 or RealFailover or Failover or failover or ledger or Ledger"
  → 74 passed, 876 deselected, 61 subtests passed in 34.71s

python -m pytest tests --collect-only -q        → 950 tests collected（默认套件不含 P0 例）
bash …/run_p0_failover_acceptance.sh --dry-run   → 退出码 0（零模型调用）
python …/task10_rehearsal.py                     → 总体 PASS（10 过 + 1 枚设计性红）
python …/task10_mutations.py                     → M0 全绿、M1–M4 全部「预期判据全部红」，
                                                   还原核对 OK（两文件 sha1 回到基线）
```
全套件没重跑（按分工留给主 agent）；`935 → 950` 的差是闸的 15 枚，P0 例贡献 0。

---

## 7. 需要主 agent 裁的六件（我没有改任何产品代码）

1. **§12 预算装不下真机冷加载（P0 的硬阻塞）**。出厂 `llm_total_budget_ms=30000`、
   `llm_model_timeout_seconds=20`，而 A-2 实测**一次加载失败就花 22.5 秒**；
   phi3:mini 冷加载另需数十秒。用例现在在**测试进程内** patch 成 900000/300，
   这越过了 §12 写明的 `5000..120000` 区间（`Field(ge/le)` 被 `patch.object` 绕过）。
   三条路请裁：①接受「验收态用测试侧 patch」并在 T11 文档点名；
   ②新增一枚验收专用配置键（如 `llm_acceptance_budget_ms`，产品默认不变）；
   ③把 §12 的上界写宽。我倾向 ②（可审计、不改出厂默认、不动 spec 冻结值）。
2. **`/api/query` 的 `model_used` 与被选中的模型不同源**。`rag.current_model_name()`
   给的是 `RoutePlan.primary` 的生效名（代码里自述如此），所以 fallback 答出来的这一行
   在 API 面上仍显示 `ornith-1.5:9b-text`。DESIGN §9 那句「响应 model 字段来自实际选中模型」
   与之有张力。断言 #10 只把该字段**如实记进证据**、没有断言它等于 phi3，
   请裁是否算缺陷。
3. **`app/agent_trace.TRACE_PATH = Path("data/agent_traces.jsonl")` 是相对模块全局**
   （`save_trace` 直读它）。P0 靠 patch 该全局避开 `backend/data/`；但产品侧从非 `backend/`
   起服务时 trace 会落在 `<cwd>/data/`。与 §5 的 `env_file` 同根（相对路径），未改。
4. **注册表默认值是相对路径**（`config/llm_registry.json`）：彩排第一次就在仓库根起跑
   撞上 `RegistryError`。用例已按矩阵 §5 的先例（`WarmupGateTests.setUp`）
   在 setUp 里指绝对出厂文件。正解仍在产品侧，等裁。
5. **证据可伪造性的上限**（§2 末尾）：闸能确定性地杀掉结构造假与 mock 传输，
   杀不死「手工编一份 JSON + 造临时库文件」。是否要在 T11 加一枚更强的锚
   （例如把 `answer.text` 与 phi3 的 `prompt_eval_count` 写进验收文档，由人眼复核）。
6. **矩阵 §5 的 `935 passed / 981 subtests` 文案现在过期**（默认收集 950）。
   我没有去改那组数字——那是全套件终态，归 Task 11 实测后回写。

---

## 8. 等用户放行后要跑的那一条命令

```bash
# 仓库根 E:\xiangmu\rag
bash .superpowers/scripts/run_p0_failover_acceptance.sh --yes
```

等价的手工式（自己确认过内存才敲）：

```bash
cd backend && REAL_LLM_ACCEPTANCE=1 python -m pytest tests/test_real_llm_failover_acceptance.py -q -s -p no:cacheprovider
```

跑完请核三件事：①终端 `[4/4]` 十枚全 PASS 且 `green_permitted_by_evidence = True`；
②`task10/run/<stamp>/` 里的临时库只有 1 行账、仓库 `backend/data/conversations.db` 仍 0 行；
③`task10/real-llm-failover-001.json` 的 `provider_transport` 必须是 `null`。
三件齐了才由主 agent 把 `docs/MODEL_ROUTER_V23_MATRIX.md` 的 P0 行改成 `GREEN`（闸会反查：
改了矩阵但证据不成立 ⇒ 红；证据成立但矩阵还写 BLOCKED ⇒ 也红）。
