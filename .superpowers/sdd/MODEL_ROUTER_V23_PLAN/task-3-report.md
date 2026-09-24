# Task 3 报告 — classifier + router（纯函数决策层）

状态：**DONE / 绿**。定向 `tests/test_model_router_v23_contract.py` **172 passed / 0 failed**
（本任务前 122 → +50 例，302 subtests）；全套件 `python -m pytest tests -q`
**579 passed / 0 failed / 793 subtests**（基线 529 → 只增不减，+50 全为本任务用例）。
Router P95（矩阵 #14）实测见下。

## 交付文件

| 文件 | 行数 | 内容 |
| --- | --- | --- |
| `backend/app/llm/classifier.py` | 124 | `classify(query, *, mode, needs_tools=False, needs_stream=False) -> RequestProfile`、`complexity_of`、三张模块级常量词表 + 长度门槛 + 子句分隔符；零 IO、零 import 外部模块 |
| `backend/app/llm/router.py` | 292 | `plan(profile, registry, health_view) -> RoutePlan`（§5 七步冻结顺序）、`NoCapableModelError`、`REASON_CODES` 冻结枚举、`CAPABILITY_BY_MODE` / `PRIORITY_KEY_BY_MODE` |
| `backend/app/llm/__init__.py` | +12 | 再导出 `classify` / `plan` / `NoCapableModelError` / `REASON_CODES`（同一对象，包内不留第二份定义）；docstring 补 Task 3 段 |
| `backend/tests/test_model_router_v23_contract.py` | +740 | 测试类③：`ClassifierTests`(12) / `RouterPipelineTests`(30) / `ShippedRegistryRoutingTests`(6) / `RouterBenchmarkTests`(2 方法 = 4 计量场景) |

`native_stream.py`、`rag.py`、`agent.py`、`conversation_agent.py` 本任务未触碰。

## 红 → 绿证据

1. **红（无实现）**：`ModuleNotFoundError: No module named 'app.llm.classifier'` → 整个契约文件
   collection error（1 error，0 test 可跑）。测试先写、先红，再落实现。
2. **红（首轮实现后）3 例**，全部是**测试自身**的口径错误（不是实现放宽）：
   `blocker/blocking` 变量名笔误；`cloud-dear` 误挂在被判不健康的 `openai` 上；
   `capability_runs_before_health` 的 keeper 漏了 `priority.tools`（正好证明「缺失键=0 分剔除」在生效）。
   三处按预期语义改测试后 → 172 passed。
3. **变异自查（4 发，全部被杀；逐发还原后复跑 48 例全绿）**

| 变异 | 结果 | 被哪条杀死 |
| --- | --- | --- |
| M-1 capability 与 health 两步交换顺序 | **4 failed** | `test_capability_runs_before_health_so_dead_provider_stays_silent`（不健康码越权出现在被能力剔掉的 provider 上）、`test_all_candidates_unhealthy_raises_no_capable_model`（stage 从 health 退化成 capability）、`test_reason_code_set_equality…`、`test_health_runs_before_limits…` |
| M-2 同分 cost tie-break 反向（贵的先） | **3 failed** | `test_tie_on_priority_is_broken_by_lower_total_unit_price`（两个声明序都红）、`test_reason_code_set_equality…`、`test_every_emitted_reason_code…` |
| M-3 健康全灭不抛（降级为「忽略 health 硬选」） | **5 failed** | `test_all_candidates_unhealthy_raises_no_capable_model`、`test_circuit_open_only_wipeout_also_raises`、`test_health_runs_before_limits_so_the_health_wipeout_owns_the_stage`、`test_unhealthy_ollama_routes_rag_traffic…`、`test_context_estimation…`（异常对象漏网即红） |
| M-4 `score > 0` 改成 `>= 0`（0 分不再剔除） | **2 failed** | `test_priority_step_is_the_last_filter_before_ordering`、`test_missing_or_zero_priority_key_eliminates_the_candidate` |

顺序类变异被「理由码归属」而不是「最终 id」抓住：能力不符的候选进不了 health 步，所以它的
provider 坏了也不该在 `reason_codes` 里留痕——单看 `primary.id` 交换顺序是等价的，这条测试
把等价性打破了。`test_health_runs_before_limits…` 用 stage 归属钉住 health↔limits 的相对序。

## 测试构成（50 例）

- **ClassifierTests 12**：签名（`query` 位置、其余 keyword-only、`mode` 无默认、缺 mode ⇒ TypeError）；
  `needs_reasoning` 恒 False（5 问句 × 3 mode 矩阵）；needs_tools/needs_stream 双态 + 真值归一
  （None/1 ⇒ False/True）；mode 白名单（含 `None`/`""`/`"agent "`）；长度门槛 60 的三向边界
  （59 low / 60 high / 200 high / 首尾空白不计入）；**high 词表逐词**参数化（并钉住任务书点名的
  对比/为什么/方案/风险/优缺点/多条件/同时/分别 8 枚必须在表里、每枚 ≥2 字）；**medium 词表逐词**
  参数化 + 与 high 表互不为子串（否则一条规则吃掉另一条）；子句数判 medium（`。`/`；`/换行三形态）
  与「顿号逗号不算子句」反钉；low 默认（7 条短问句含英文/空串）；优先级 high>medium>low 的叠加；
  确定性 + AST 纯度（import 白名单 `{__future__, typing, app.llm.models}`、禁 env/时钟/随机/文件）；
  不 import typesafe 路由层（§4「独立实现不成环」）。
- **RouterPipelineTests 30**：签名与返回形状、`NoCapableModelError.__bases__ == (Exception,)`
  且**不是** `LLMError` 子类；七步各钉：enabled（1000 分也剔 + 全禁的 stage="enabled"）、
  capability（priority=100 的能力不符仍剔 ⇒ capability>preference；**chat 恒需**反钉 rag/tools 全 True
  但 chat=False 的条目在三个 mode 下都不入选；mode→caps/priority 双映射；needs_tools 双态；
  needs_stream 双态；needs_reasoning 双态）、external 透传（贵而高优先级的云条目照当 primary，
  `LOCAL_PREFERRED` 只标 local）、health（不健康剔 + 码、circuit_open 剔 + 码、两信号独立、
  缺 provider 默认健康的 5 形态含 `None`/`{}`）、**全灭抛异常**（stage、reason_codes 逐字、
  `error.profile is profile`、异常文本含五字段定长摘要、长度 <400）、limits（`model_construct`
  绕过 `ge=1` 的零上限条目 + 全灭 stage="limits"）、priority（缺失键=0 剔除、tools=0 在 agent
  剔除、全 0 分 stage="priority"）、排序（100/80/50/10 阶梯 + score 逐位）、cost tie-break
  （声明序两个方向都测 + `LOWER_COST` 只挂赢家）、同分同价回落声明序、
  **理由码集合等式**（一个计划同时覆盖四种入选码 + 一种剔除码，逐候选核集合与合并序、去重）、
  冻结枚举等式 + 跨 18 组合扫描「无越界码 & 成功计划不含 NO_CAPABLE_MODEL」、
  跨步顺序两钉、纯度（AST + 禁 `api_key`/`base_url`/`app.config`/`app.llm.provider` 等字面）、
  不写脏 registry/health_view/画像、包级再导出同一对象。
- **ShippedRegistryRoutingTests 6**：出厂 5 条目走真 `load_registry`（D1 enabled 折叠）后的路由形状：
  无 key 时 chat ⇒ `ornith→phi3` 且理由码集合等式；rag+stream 仍成立；agent 无 key ⇒
  **pre-flight `NoCapableModelError`（stage=capability，D2 的 Agent fast-path 前提）**；
  给 key 后 agent 取 `priority.tools=100` 且 fallbacks 为空；ollama 不健康 ⇒ rag 流量落云条目；
  全灭再抛一次（不降级）。
- **RouterBenchmarkTests 2 方法 / 4 计量场景**：`measure()` = 预热 + **3 轮 × 200 次**独立计时，
  每轮取 P95，判 min-of-3 ≤10ms（断言消息带最差轮数字，失败时能区分抖动与回归）。
  实测（本机，非 CI）：5 条目 chat **0.028ms**；60 候选 chat **0.525ms**（最差轮 0.630）、
  agent+tools+stream **0.282ms**、rag **0.506ms** —— 预算 10ms 的 1/19～1/350。
  计量前先断言 `len(fallbacks)` 等于该规模应有的值（44 / 29 / 44 / 4），防止「空跑很快」。

## 偏离与自裁决（brief 之外，均已在代码注释里落文）

1. **签名以 plan brief 为准**：spec §4 写的是 `classify(query, call_site_mode, has_tool_schema,
   wants_stream)`（位置参、旧命名），brief 冻结为 `classify(query, *, mode, needs_tools, needs_stream)`。
   取后者（任务书「接口冻结」段），语义等价（mode 由调用点声明、两个需求旗标）。
   `complexity` 是**输出**不是入参。
2. **`needs_reasoning` 恒 False，但 router 照样消费它**：classifier 无需求方可置真（V2.3 冻结），
   而 §5 的能力过滤若不等这个字段接上再实现，V2.5 一置真就会静默选到不支持推理的模型。
   因此两侧都钉（classifier 侧矩阵 + router 侧双态）。
3. **limits 步退化成形式校验（→ 接口缺口移交 T4，本任务头号移交项）**：`plan(profile, …)` 的
   冻结入参只有画像，**没有请求体**，所以 §5 的「context 粗估」不可能在此发生。本步只保留
   「上限必须为正」的越界防御；上下文裁决由 **Task 4 在 execute 前置**，建议口径
   `sum(len(str(m)) for m in req.messages) / 2 > model.limits.context_tokens ⇒ 剔该候选`
   （中文按 ≈2 字符/token 粗估，与 §8 的 token 记账同源但不必精确——它只做「装不装得下」的裁决）。
   该缺口由 `test_context_estimation_is_deferred_to_task_4_and_documented` 三向钉住：
   签名参数名逐字、router 源码里不出现 `messages`（防止将来偷偷塞进去）、源码含「Task 4」与
   「上下文」的书面移交。
4. **priority 缺失键=0 分 ⇒ 剔除**（brief 字面），于是「全候选在该 mode 都是 0 分」会抛
   `NoCapableModelError(stage="priority")` 而不是退回声明序硬选一个。这是 fail-closed 的
   有意选择：一份没给某条链打过分数的注册表属于配置事故，静默服务它等于把 D2 的降级链
   换成「随机挑一个模型」。出厂注册表已在测试里核过（chat/rag 两档全为正数，agent 档只有
   tools=true 的三条有分数）。
5. **理由码的候选级语义是本任务给出的可测口径**（spec 只冻结枚举词，未定义谁挂哪个）：
   `CAPABILITY_MATCH`=通过第 2 步（人人有，读 trace 能确认不是撞上的）；
   `HIGHER_PRIORITY`=计划内至少有一个更低分候选（压住了别人）；
   `LOWER_COST`=同分带内至少有一个更贵候选（赢下那次 tie-break）；
   `LOCAL_PREFERRED`=该候选 `external=false` 且入选；
   `PRIMARY_UNHEALTHY`/`CIRCUIT_OPEN`=health 步**真的**剔过该 provider，两信号独立，
   合并序为「入选理由在前、剔除理由在后」。`NO_CAPABLE_MODEL` 只随异常且必随异常。
6. **`circuit_open` 是 health_view 的可选键**：任务书要求「healthy false **或** circuit_open true
   视为不健康」，而 T2 的 `provider_health_view()` 目前只输出 `{healthy}`。router 按
   `entry.get("healthy", True)` / `entry.get("circuit_open", False)` 读，缺键不改变今天的形状
   （向后兼容 T2 的视图），T4 把熔断态并进去即可生效 ⇒ **移交项**（见下）。
7. **最终 tie-break 用注册表声明序**（同分同价），把确定性从「依赖 dict 迭代序」里救出来；
   两向声明都测。
8. **benchmark 双规模**：任务消息给 5 条目、brief 给 60 候选，两者都跑（超集，不择一）。
9. `NoCapableModelError` 刻意不是 `LLMError` 子类并带 `stage`/`profile`/`reason_codes`/
   `profile_summary` 四个属性：Task 4 的 `except LLMError` 处理的是「一次 provider 往返的失败
   归类」，把「零候选」混进去会被当成可重试错误白烧预算；异常文本只含画像摘要，不含请求内容（D3）。

## 移交下一任务（handoff）

- **→ T4（头号）**：`plan()` 不做上下文粗估（签名里没有请求体）。T4 在 `execute` 前置
  `sum(len(str(m)) for m in req.messages)/2 > context_tokens` 的候选剔除，并把被剔原因并进 trace；
  若要保留 `RoutePlan` 的完整性，建议 T4 在 `plan()` 之后做一次「按请求体的二次收口」，
  收口后仍为空 ⇒ 自己抛 `NoCapableModelError(profile=…, stage="context")`（该类支持自定义 stage）。
- **→ T4**：`health_view` 需由 T4 合成为 `{provider: {"healthy": bool, "circuit_open": bool}}`
  （probe 视图 ∧ `CircuitBreaker.allow()`），否则 §5 的熔断过滤步只在未来 T4 注入后才生效；
  plan 阶段剔除与 `Attempt(result="skipped_circuit")` 是**两道门**（D4），不冲突。
- **→ T4/T5**：`FALLBACK_AFTER_TIMEOUT` / `PROVIDER_CONFIG_FAILED` 两码由执行期产生，
  router 永不输出（`REASON_CODES` 里列出是为了让「拼错码」在测试期就响）。T5 落库
  `usage.route_reason` 时把 `plan.reason_codes` 与执行期码 concat 后即可，顺序已保证入选在前。
- **→ T8**：D2 的 Agent 捕获点用 `except NoCapableModelError`（不是 `except LLMError`）；
  无 key 的出厂注册表下 agent 模式**必然**走这条路（本任务已用真注册表钉住），
  所以 `agent_local_fast_path` 不是罕见分支，回归用例必须常驻。
- **→ T5**：`/api/system/status` 的 `providers:{name:{healthy}}` 与 router 共用
  `provider_health_view`（60s 缓存），D4 要求 OPEN 时记 `CIRCUIT_OPEN` 但**不标 degraded**，
  因此 status 的 `healthy` 字段不得掺熔断态——与 health_view 的 `circuit_open` 键是两个面，别合并。
- **→ T9**：`app/llm/{classifier,router}.py` 对 D6 全文扫描永久零命中（无 httpx、无端点字面量、
  无凭据字面量、连 `settings` 都不 import），无需豁免清单；本任务已在
  `SingleEgressStructureTests` 的既有扫描下复跑通过。

## 需上层确认（不阻断，按 spec 字面实现）

1. 偏离 4 的「0 分剔除 ⇒ 可能抛 NoCapable」若评审认为应改成「0 分保留为末位候选」，
   改动面只有 `plan()` 第 6 步一行 + 两条测试；我按 brief 字面实现的是 fail-closed 版。
2. 偏离 5 的候选级理由码口径若与前端 TraceView 的预期文案不一致，请指定；枚举词本身未动，
   重贴语义不影响 D3/机器码面。
3. `classify` 的 high 词表在任务书 8 枚之上加了「架构/设计/评估/分析/排查/根因/复盘/规划」等
   约 30 枚（含 5 枚英文）。词表越宽 high 越多，但 V2.3 的 complexity **不参与打分**，
   今天只影响 trace 可读性；V2.7「按难度选档」接上时这条词表就是成本旋钮，届时按账单收窄。

## Fix round 1（评审 I-1 一行级 + 2 条测试钉 + 1 处空操作断言；2026-09-23）

改动面严格限定在 `backend/app/llm/router.py`（297 → 313 行）与
`backend/tests/test_model_router_v23_contract.py`（2549 → 2636 行，+4 例、1 例改断言）。
其余文件零触碰；未做任何 git 写操作。

### 1. I-1：`NoCapableModelError` 入口校验理由码 ⊆ `REASON_CODES`（`router.py:95-110`）

`reason_codes` 是**机器码**，Task 4/5 原样落 `usage.route_reason` 与 trace。此前只有「`plan()`
用模块常量传码」这一条隐式保证，Task 4 手工传码拼错一个字母（`CIRCUIT_OPENN`）会安静地流到
前端才被发现。现在构造时即 `raise ValueError`，并把越界码逐字写进异常文本。

**用 ValueError 而不是 assert**：`python -O` 会删掉 assert，那样这里就只剩一条静默的越界通道。
校验在补 `NO_CAPABLE_MODEL` **之前**执行，因此「合法码 + 一个脏码」的混合输入同样被拒。

同时 `_Stage`（`router.py:72-75`）补 `"context"` 成员：Task 4 的 execute 前置收口
（`sum(len(str(m)) for m in req.messages)/2 > context_tokens` 把候选剔空后）要抛
`stage="context"`，那是本模块唯一「今天没有产生者」的 stage，先钉接缝、不留给 T4 回头改 T3。
`plan()` 的过滤顺序与它实际产生的 stage 集合**未变**（仍是 enabled/capability/health/limits/priority）。

新用例两支：`test_no_capable_model_error_rejects_codes_outside_the_frozen_enum`
（4 形态越界码 × 「单独传」与「混在合法码里传」都拒；合法侧不误伤：枚举内任意组合都收、
`NO_CAPABLE_MODEL` 必随且只随一次；并核 `plan()` 的真实抛点仍然走得通）与
`test_stage_literal_carries_the_context_stage_task_4_raises`
（`typing.get_args(_Stage)` 集合等式 + 六个 stage 逐个构造，含 `stage="context"` 的
`.stage/.profile/.reason_codes/异常文本` 四项）。

### 2. 评审 M 残留：两条顺序钉

- `test_enabled_runs_before_capability_so_a_disabled_mismatch_stops_at_enabled`：
  一条**既禁用又能力不符**（agent 要 tools）的条目必须停在 `stage="enabled"`；随后用
  `model_copy(update={"enabled": True})` 把它打开、同一画像 ⇒ 落到 `stage="capability"`。
  第二跳是必要的：没有它就分不清「enabled 先手」与「两步都报 enabled」。既有的
  `test_disabled_entries_leave_no_trace…` 用的是能力相符条目，对 1↔2 交换是盲的。
- `test_limits_never_outranks_the_steps_around_it`：两侧各钉一次，都用「单条候选双重违规」。
  2↔5：能力不符 + limits 违规 ⇒ `stage="capability"`；5↔6：limits 违规 + priority 缺该档键
  （=0 分）⇒ `stage="limits"`。**现实现就是 capability < limits < priority，两条断言都按 spec
  顺序成立，无需按实现改写**（该口径已在用例注释里落文）。只测一侧时它与另一个邻居交换仍绿，
  所以 5↔6 那一跳在还原测试前是唯一杀手（见下表）。

### 3. 空操作断言行（`test_context_estimation_is_deferred_to_task_4_and_documented`，原 `:2199`）

`assertNotIn("messages", ROUTER_SOURCE.replace("Task 4", ""))` 的 `replace` 与「源码里有没有
`messages`」没有任何关系（删掉「Task 4」字样不影响任何子串搜索），它只是让读者以为存在某种
豁免关系。改为直接 `assertNotIn("messages", ROUTER_SOURCE)`（实测 router.py 该字面量 0 命中），
并注释说明字面量 **"Task 4" 允许且应该出现在源码里**——它就是书面移交，其下
`assertIn("Task 4", ROUTER_SOURCE)` 的正向断言照旧。断言意图（签名里没有消息体 / 移交已落文）不变。

### 4. 门槛与变异实测

| 项 | 结果 |
| --- | --- |
| 定向 `tests/test_model_router_v23_contract.py` | **176 passed / 0 failed**，312 subtests（172 → +4；门槛 ≥175 ✅） |
| 全套件 `python -m pytest tests -q` | **583 passed / 0 failed / 803 subtests**（基线 579 → +4；门槛 ≥582 ✅） |
| 变异 1↔2（enabled 与 capability 交换） | **2 failed**：新钉 `test_enabled_runs_before_capability…`（拿到 capability 而不是 enabled）+ 既有 `test_agent_plan_is_a_pre_flight_no_capable_without_a_cloud_key`（拿到 enabled 而不是 capability）⇒ **新钉确实红了** ✅ |
| 变异 2↔5（capability 与 limits 交换） | **2 failed**：新钉 `test_limits_never_outranks…` + 既有 `test_capability_runs_before_health…` |
| 变异 5↔6（limits 与 priority 交换） | **1 failed**：只有新钉 `test_limits_never_outranks_the_steps_around_it` ⇒ 这发交换此前无人能杀 |
| 变异 删掉入口校验 | **4 subfailed**（逐枚越界码）：新钉 `test_no_capable_model_error_rejects_codes_outside_the_frozen_enum` |
| 变异 从 `_Stage` 摘掉 `"context"` | **1 failed**：新钉 `test_stage_literal_carries_the_context_stage_task_4_raises` |

每发变异都是「改文件 → 跑定向 → 还原 → `diff` 确认零残留」；终态源码即上表全绿所测版本。

### 5. 回写 Task 4 的移交

`task-4-brief.md`「Task 3 评审移交」第 1、2 条的前置现在已具备：`stage="context"` 可构造、
非法 reason code 在入口即 `ValueError`。Task 4 若给 context 收口带自定义码，只能复用
`REASON_CODES` 里的词；要新增词请先改冻结枚举 + `test_every_emitted_reason_code_is_in_the_frozen_enum`，
不要就地放宽入口校验。
