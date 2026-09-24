# Task 5 修复轮 1 — scoped 复审裁定（Model Router V2.3）

复审者：Task 5 修复轮 1 独立复审（只读 / 只跑测试 / 只写本文件）。裁定时间：2026-09-24T03:25+08:00。
被复审对象 = 工作树（`backend/app/llm/usage.py` 1056 行 / `app/llm/__init__.py` 448 行 /
`app/agent_trace.py` 92 行 / `app/security.py` / `tests/test_llm_usage_contract.py` 1975 行 /
`tests/test_model_router_v23_contract.py`）+ `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task-5-report.md`。
本复审**未修改 `backend/` 或 `frontend/` 任何文件、未做任何 git 写、未发起任何真实外呼**。
临时脚本两处（只在内存里 monkeypatch，绝不落盘改源码）：
`rev5r1_probes.py`、`rev5r1_mutations.py`（+ 其静音日志 `rev5r1_mutation_silence.log`）。
不重开首轮已裁的分层问题：§5-C / §8.1 第 4 条的九键口径按**最终口径**验收，只验收「有没有照做」。

---

## 1. Verdict

**PASS-with-minors —— 可放行 Task 6。**

五条 Important **全部 ADDRESSED**，且不是「改文本糊过去」：我独立复核了语义等价性（把首轮
被删的 `model_route_payload` 原码从评审包 `review-task-5.md:160-194` 里挖出来逐值对）、
独立跑了 9 枚新增测试、独立打了 8 发内存变异并全部杀死。FIX-5 五枚 Minor 全部名副其实。
新增破坏 = **0 Critical / 0 Important / 5 Minor**（见 §4），其中 4 枚不阻断 T6，1 枚（N3）
根本不属本任务。放行的同时要求：N1/N2 进 T9 或终审 triage，N4 并入 T6 的 `plan` 字段改动。

---

## 2. 五条 Important 的判定表

| 项 | 判定 | 证据（文件:行） | 我独立核出来的关键事实 |
| --- | --- | --- | --- |
| **I-1** 报告三段按任务窗口重写 + T4 那例的强度交代 + security 标准措辞 | **ADDRESSED** | `task-5-report.md:5-8`（口径声明为「整个 Task 5 任务窗口」）、`:18-29`（**8 行**改动面表，含此前漏报的 `tests/test_model_router_v23_contract.py:3786-3812` / `knowledge_os.py` / `main.py` / `__init__.py`）、`:31-48`（旧钉为何失效 + 三面逐面核对 + **明确承认掉下来那一枚**）、`:28` 与 `:63`（security 改成「round 2 变异注入并原样还原：mtime 变化、内容净零改动」标准措辞，并说明本轮才有真实内容改动）、`:220-234`（诚实清单按全窗口，`:224` 自认「第 5 轮那句『没有动 `__init__.py`』是假的」） | 报告说「补回那一枚」**不是空话**：`tests/test_llm_usage_contract.py:1944-1971` 真在树里，且真做了那件事——关探针 + 桩 `provider.complete` ⇒ 走**真** `llm.complete()` ⇒ `assertEqual(1, len(rows))` + `(trace_id, route_mode, model) == ("t-lazy","chat","usage-fixture-model")` + `success=1`（即「账交付给了惰性 sink」+ M2 口径 + 键值三钉）。我按 node-id 单跑 = 绿。旧钉 `assertIsNone(llm.usage_sink())` 的失效因由可查（真模块已存在），三面版另加两枚（显式 sink 优先 / `set_usage_sink` 返回值）⇒ **不降强度**成立 |
| **I-2 + I-3** 九键单一产地 + 假 provenance 改净 + 防回潮钉 + Minor 7 并一份 | **ADDRESSED** | 九键产地唯一：`usage.py:330-395`（末三枚 `:392-394`）+ `_trace_stage():398-406`；`grep -rn "model_route_payload\|_route_stage\|_route_error_code" backend/app backend/tests` ⇒ **无实现体、无导出**（`__init__.py` 的 `__all__:150-194` 只剩 `effective_model_name_for_entry:176`；余下 5 处命中全是 docstring/测试注释的历史叙述，与主 agent 自述一致）；provenance：`grep -rn "T4 交付" backend/app backend/tests docs` ⇒ **0 命中**（命令 exit 1），`usage.py:344-350` 与 `__init__.py:42-43` 改为 §8.1 依据 + 「曾另算一遍、已按 C 删除」；防回潮：`tests:1670-1729` 两例；Minor 7：`__init__.py:327-349` 一份实现 + `:352-366` 与 `usage.py:720-729` 两个一行外壳，`usage.py:69` 复用包级件（不再 `import provider.*`，`usage.py:729`） | **等价性我是查了原码而不是查了自述**：被删的 `_route_stage`（`review-task-5.md:180-183`）与新 `_trace_stage` 逐字同逻辑（`<0 ⇒ "none"` / `==0 ⇒ primary` / 否则 fallback），**不是 `0`/`""` 占位**；`selected_index` 从 `int(...)` 换成 `_int_or(...,-1)`（坏值不再抛，退回 -1，严格更好）；`context_dropped` 从 `int(...)` 换成 `_non_negative_int(...)`（负数收 0，见 §4 的 N4 附注）。`stage="none"` 的触发条件与 `AllCandidatesFailedError` 这条路：`:377` 类型闸门收这三型，该异常无 `selected_index`/`context_dropped` 字段 ⇒ `:384` 默认 -1 ⇒ `:404-405` 落 `none`，由 `tests:1395-1410` 用**真**异常对象钉住 `("none", -1, 0)`；`:1550-1565` 另钉同一条路的 attempts/码。防回潮两例的强度我实测过：V8（把 `model_route_payload` 原样挂回 `app.llm`）⇒ **被杀**；B1（在别的源文件里放一个双引号九键的第二生产者）⇒ 扫描谓词**抓到**。假 provenance 三处（`usage.py:347`、`__init__.py:332`、`tests:32/1377/1674`）全是历史叙述且都明说「不得复活」，不构成口径授权 |
| **I-4** `client_aborted` 判据收窄 + 顺序 + 测试 + docstring | **ADDRESSED（逐字一致）** | `usage.py:563-577`（`_clean_error_type(raw,*,success,delivered)`：有 `raw` 走 `_error_type_value`；`success` ⇒ None；否则 `delivered ⇒ client_aborted : unknown`）与 §8.1 第 2 条的 `success is False ∧ error_type 缺失 ∧ fallback_index>=0 ∧ tokens>0` 一一对上；`_has_delivery():580-587`；**先收口再判定**：`_prepare_record:511-546`（`:523-525` 先算 `input/output/fallback_index`，`:544-546` 才判归类，`:511-513` 把「顺序不能换」写进 docstring）；`scored_rows:824-831` 只剔 `client_aborted` 并解释「`unknown` 不剔」；模块 docstring 第三条 `:27-39` 已按 §8.1 改写（含「从缺席反推是编事实」那句理由）；常量注释 `:113-118` | 顺序这件事我**独立复现过绕过姿势**：`input_tokens="n/a", output_tokens="n/a", fallback_index=0, success=False, error_type=None` ⇒ 库里 `unknown`（探针 A1）。若先判归类，`"n/a"` 会让 `delivered` 抛错或把字符串当有值 ⇒ 这条坏账就会被叫成关页。新增那例（`tests:566-607`）**不是只断言列值**：三种无交付形状逐个 subTest ⇒ `["unknown"]*3` + `aggregate_status` 的 `requests_5m=3`、`success_rate=0.0`（**进分母**）、`aborted_rate=0.0`（不受影响），再补一条有交付事实的行反证 `aborted_rate=0.25` 且 `success_rate` 仍 0.0。内存变异 V1（`_has_delivery` 恒真）、V2（判据退回「只看 error_type 缺失」）**双双被杀**，红的正是这一例 |
| **I-5** 注册表变成夹具责任（两个 cwd 都绿） | **ADDRESSED（针对本任务文件）** | `tests:265-273`（`_UsageFixture.setUp` 末尾统一 `self.use_registry(entry_of(id="usage-fixture-entry", provider="ollama", model="usage-fixture-model"))`，注释里写清「条目故意不与账本行同名，否则会凭空匹上牌价、把红 1 那族的第 ② 支测不到」= 等价注入而非照抄）；`use_registry:295-301` 同时打 `usage`/`llm` 两处 `get_registry`；`tests:988`（`test_broken_registry_still_reports_the_rates`）仍显式换成抛错 ⇒ 「注册表坏 ⇒ 名字面塌空」那半段没丢 | 我按评审的验收姿势真跑了两边：`cd backend` 与 `cd 仓库根` 各跑 `AggregateMathTests::test_window_rates_and_p95_on_ten_seeded_rows` + `FailOpenTests::test_aggregate_degrades_to_an_empty_block_when_the_read_fails`（+ 那例 broken_registry）⇒ **全绿**（5 passed / 3 passed）。全套件 748/0 与定向 100/0（两个 cwd）由主 agent 独立核实，与本树文件面不矛盾。**但**：跨目录跑**另一个**文件红了 1 例，见 §4 的 N3（属 Task 4 时代既有耦合，不是本轮引入） |

---

## 3. FIX-5 五枚 Minor 的判定表

| Minor | 判定 | 实现证据 | 测试证据 + 我打的变异 |
| --- | --- | --- | --- |
| **1** provider 名正则兑现注释承诺 | **ADDRESSED** | `security.py:147` = `^[a-z0-9_]{1,64}$`；`:140-146` 的注释改成实话（点名「曾经放过 `api.openai.com` 与 `127.0.0.1:11434`」）并与 `models.py` 的 `ModelDefinition.provider` 同源 | `tests:1221-1242` 三枚必须被拒 + 两条不外泄；我的探针 C1 实测：`ollama/openai/deepseek/qwen/zhipu_ai` **全通过**，`api.openai.com`/`127.0.0.1:11434`/`Ollama`/`glm-4` 全拒；**出厂注册表 4 枚 provider 名（deepseek/ollama/openai/qwen）0 枚被误杀**（直读 `config/llm_registry.json`）。变异 V5（退回宽字符集）⇒ **1 红** |
| **2** `_clean_codes` 去重 + 上限有测试、上限不再与 9 枚枚举矛盾 | **ADDRESSED** | `usage.py:133` `ROUTE_REASON_MAX_ITEMS = len(REASON_CODES)`（探针 C2：`9 == 9`），`:130-132` 说明「曾经是硬编码 12 而死码」；`:619-627` 去重 + 截顶同源 | `tests:385-415`：6 枚含重含越界 ⇒ 恰好 3 枚（去重被钉）+ 「上限=枚举基数」等式 + 用 `mock.patch` 把 `_REASON_CODES` 临时放宽 2 倍来证明截断那一支是**活代码**（去掉 `[:N]` 就红）。变异 V3（去 dedupe + 去上限，即首轮那发**存活**的变异）⇒ **1 红**。附一句实话：因为先过枚举再去重，生产路径上这个上限**由构造不可达**，它只剩「枚举自己扩了也不失控」的纵深意义——测试注释 `:392-394` 已经自己写明，不算吹牛 |
| **3** `_ERROR_TYPE_PATTERN` 与 `_status_code` 边界对齐 | **ADDRESSED** | `:156-158` 形状放宽到 `:\d{1,4}`，`:603-616` `_error_type_shape_ok` 再做**取值域**判定，`:676-683` `_status_in_range()`（`_STATUS_CODE_MIN/MAX = 0/1000`）被 `error_type` 后缀与 `status_code` 列**共用**；`:590-600` `_error_type_value()` 把 trace 位与账本位并成同一个净化函数 | `tests:486-514` 五点（999/1000/1001/99999/`no_fallback`）逐个断言「列值 + 后缀」成对，并额外断言 `_trace_error_code` 同一枚码出同一个词。我的探针 A5/A7：`retryable:1000` 两侧都收、`1001` 两侧都拒、trace 侧同判。变异 V6（只判位数不判取值域）⇒ **1 红** |
| **4** `_trace_requirements` 不再 `bool("false")` | **ADDRESSED** | `:415-424` 逐枚 `_trace_flag(...)`；`:428` `_TRUTHY_FLAGS={"1","true","yes"}`；`:431-442` `bool` 原样、其余只看显式真值字符串 | `tests:1412-1438` 12 种写法逐值 + 出门必须是 `bool`。变异 V4（退回 `bool`）⇒ **2 红（同一例两个 subTest）**，与报告 M-R5 的自述一致 |
| **12** breaker 两例 `no_probes()` | **ADDRESSED** | 夹具 `no_probes():303-310`（打 `usage.provider_health_view`，返回按名字合成的视图） | `tests:892-896`、`:909-910` 两例首行都是 `self.no_probes()`，注释点名「隔离靠 `ollama.test` 解析失败 = 环境运气，不是测试自己的决定」；breaker 断言原样保留（`{"ollama":{"state":"open"},"openai":{...}}` + 「观测不创建熔断器」）⇒ 隔离现在是**声明式**的 |

**新增 9 例是不是水例？** 我逐枚读了：8 枚带值断言（三种形状 / 五点位域 / 12 种旗标写法 / 四值 `stage` / D2 三键 / 端到端一行账 / 去重截顶 / 三枚必须被拒），唯一「按形状」的 `test_the_object_is_exactly_the_nine_frozen_keys:1344-1359` 是 §8.1 冻结面本身该有的等式钉（键序 + `len==9` + 键集合三钉，多一枚少一枚都红），且报告 `:302-305` 自己承认「M-R4 一发杀 10 例 = 形状钉偏密，替代不了语义钉」——这个自我认知是对的，我也实测到 `V7`（`_trace_stage` 恒返回 `primary`，形状全对）确实被 `test_the_three_execution_face_facts_come_from_the_result` 杀掉。**没有只测形状不测语义的水例。**

---

## 4. 新发现的破坏或自相矛盾

**没有 Critical、没有 Important。** 五枚 Minor，其中 N3 不在本任务窗口内：

| # | 级别 | 事实 | 修法 |
| --- | --- | --- | --- |
| **N1** | Minor | **`client_aborted` 的交付闸只管「推断」那一支，不管「生产者自己写上来」那一支**。探针 A4：`success=False, error_type="client_aborted", fallback_index=-1, tokens 全 0` ⇒ 库里照样落成 `client_aborted`（`_clean_error_type:573-574` 见到非空 `raw` 就直接走 `_error_type_value`，而 `client_aborted` 是 `_ERROR_TYPE_PATTERN` 的合法值）。今天不可利用：`client_aborted` **不在** provider 的 kind 词表里（T2 只有四值），没有任何生产者会写它；但 §8.1 第 2 条要防的那个误读（「一次故障读成 1.0 关页 + 零失败样本」）在 T7 手写这个词时**仍可复现**，而 `unknown` 那一侧的闸是关的、这一侧是开的，两半不对称 | 在 `_clean_error_type` 里把显式值也过一道闸：`if _error_type_value(raw) == ERROR_TYPE_CLIENT_ABORTED and not delivered: return ERROR_TYPE_UNKNOWN`。真关页行（tokens>0 ∧ 选中过）不受影响，因此不推翻 §8.1，只是把「从缺席反推」的漏洞补成「从任何来源反推都不许」。归 T9 triage 或终审；若终审判 defer，请把它写进 §6 第 7 条的 T7 义务（「链不许自写 `client_aborted`，只能留空让账本判」）——**两者择一，不能都不做** |
| **N2** | Minor | 防回潮那例的**源码级字面量扫描有三个可绕形状**，而它的 docstring 说的是「换个名字再拼一遍也挡得住」这种全称口气：① 谓词只认**双引号**（探针 B1 `True` / B2 单引号 `False` / B3 `dict(stage=..., selected_index=...)` kwargs 形式 `False`）；② 豁免用 `path.name`（`:1719`、`:1722`）而不是相对路径 ⇒ 任何子目录里叫 `usage.py` 的文件都自动免检（探针 B4 `True`）；③ 运行时注入（V9：我往 `app.llm` 上挂了个换名的九键函数）**测不到**——这是源码扫描的固有边界，不算它的错，但报告与 docstring 的口气应该收在「挡得住**写进源码的字面量**」这个尺度上 | 三行改：谓词换成 `re.search(r"[\"']selected_index[\"']", t) and re.search(r"[\"']context_dropped[\"']", t)`；两个豁免集合改成存**相对路径**（`"app/agent_trace.py"` / `"app/llm/usage.py"`）与 `path.relative_to(BACKEND_DIR).as_posix()` 比对；docstring 补一句「本钉只挡源码里的字面量，运行时注入由 #17 集成用例兜」。归 T9（它本来就要跑 D6 静态扫描，顺手同族化） |
| **N3** | Minor（**超出本任务**，如实报） | `cd /e/xiangmu/rag && python -m pytest backend/tests/test_model_router_v23_contract.py -q` ⇒ **1 failed, 240 passed, 346 subtests**。红的是 `RouterSettingsTests::test_argless_settings_still_constructs_on_host_env`（`:713-718`）：它**故意**用真 `Settings()`，而 `llm_registry_file` 的默认值是相对路径 `config/llm_registry.json` ⇒ 不在 `backend/` 下时 `load_registry` 抛 `RegistryError`。**与 I-5 同根不同层**（I-5 是夹具漏注入，这一例是配置项本身相对）。归属核对：该例在 `snap-task4/test_model_router_v23_contract.py` 里**已存在**（`grep -c` = 1），且从 `backend/` 单跑 = 1 passed ⇒ **不是本轮引入的回归**，本轮也没写这个文件（mtime 00:22 = round 1，与 `snap-task5` 逐字节相同） | 归 T9/T11（矩阵收口 / 回归终审）：要么在该例内 `monkeypatch.chdir(BACKEND_DIR)`，要么把出厂默认解析成**包相对**路径（后者会动 §12 的冻结默认值，需裁定）。**不建议**塞回 Task 5 —— 它不在 Task 5 的改动面上 |
| **N4** | Minor | `stage="none"` 那条 D2 路上 **`context_dropped` 恒为 0**：`AllCandidatesFailedError`（`fallback.py:201-228`）只有 `attempts/reason_codes/budget_exhausted/chain_size`，**没有** `context_dropped`，所以 `usage.py:394` 的 `getattr(...,0)` 永远落到默认值。后果：「候选被上下文收口吃掉几条」这个 §5 要的解释，恰好在**最需要解释的那条降级路径**上读不出来（实现侧写「不猜」是对的，测试 `tests:1395-1410` 也诚实钉了 0 = 没有事实，缺的是**生产者那一侧**） | 不必改 Task 5。§6 第 4 条已经要求 **T6** 给 `AllCandidatesFailedError` 加 `plan` 属性——**同一次改动顺手加末位可加字段 `context_dropped: int = 0`**（与 `FallbackResult:167` / `StreamSummary:198` 同名同语义），`run_complete` 抛异常前填上。请把这一句补进 T6 的义务清单，否则九键里的一枚在 D2 路上是永久哑键 |
| **N5** | Minor（**主 agent 侧文本**，非实现） | 评审 I-4 第 1 步要求回写**两处**：DESIGN §8 与 `docs/MODEL_ROUTER_V23_PLAN.md:75`。DESIGN §8.1 四条已回写（权威依据齐备）；`MODEL_ROUTER_V23_PLAN.md` 的 Task 5 Interfaces 段仍是旧口径（`:75` 只列 `requests_5m/success_rate/fallback_rate/p95_latency_ms/providers` 五键，无 `aborted_rate`/`breaker`，也无 `error_type` 值域），读者按 PLAN 核对会以为实现多写了键 | 在 PLAN 的 Task 5 段加一行「接口口径以 DESIGN §8.1（2026-09-24 回写）为准」并同步那五键为七键。纯文档，主 agent 自己写，不需实现轮 |

**顺带核过、判为无问题的三点**：① `usage.py:69` 的 `from app.llm import effective_model_name_for_entry` 不构成循环 import（`python -c "import app.llm.usage"` 通过，包出口面不在模块级 import usage，惰性 sink 解析保持不变）；② 夹具默认注入注册表**没有**吃掉「注册表不可读」那一族用例（`tests:988`、`:1131`、`:1567` 三处仍显式打抛错的 `get_registry`）；③ `_providers_block:880-904` 仍只读 `provider_health_view`/缓存，熔断走 `_breaker_block`，D4 的 healthy 纯度未被本轮改动污染。

---

## 5. defer 清单确认 + 「`unknown` 要不要自己的观测出口」的技术意见

**defer 六枚我逐条核过「确实没偷偷做」**（不是只看报告自述）：
Minor 5（`_cost_for:785` 那句「空币种仍是唯一标记」原样在，措辞未改）、Minor 6（免费路币种/`>0` 判据未动，`:778-786` 三分支形状同首轮）、Minor 8（`agent_trace.py` mtime **01:35** = round 2，本轮零写入 ⇒ 没有再叠加行尾规整）、Minor 9（`_registry_or_none:990-996` 仍每次 warning，无节流状态）、Minor 10（`attempts` 仍 §8 三字段、`TRACE_LIST_MAX_ITEMS=16` 的截断仍静默，`:382-383`）、Minor 11（零候选不产行的结论未变，`tests:628` 那例仍在钉「不产行且不进分母」）。
**结论：defer 清单与树一致，没有一项被「顺手实现」，也没有一项被悄悄放宽。**

**关于 `unknown` 的观测出口——我同意主 agent 的倾向：V2.3 不加新键。** 理由（技术侧，不是站队）：

1. **`unknown` 今天并不是隐形的**。§8.1 第 1、2 条把它留在 `success_rate` 分母里，所以它在观测面上的**效应**已经存在：漏填归类越多，成功率越低。新加 `unknown_rate` 与 `success_rate` **完全共线**（同一批行、互补分母），信息增量是 0，代价是第 14 枚白名单键 + 再一次 §8.1 式回写 + `test_field_set_is_exactly_the_whitelist`（`tests:1174`）跟着改口径。
2. **真正缺的不是比率，是归因**，而归因那一侧已经有更便宜的出口：`error_type='unknown'` 是**账本里可查询的一列**。把「`unknown` 占比」做成 T9/T11 验收里的一条 **SQL 断言 / 运维阈值**（`SELECT count(*) ... WHERE error_type='unknown'`）比把它抬进 `/api/system/status` 的响应面更对症——前者不改 API 契约、不过白名单这道闸，后者每次扩键都要重走一轮裁定（这正是首轮 I-4 花掉一整条 Important 的原因）。
3. **现在加键的时机也错**：T6/T7/T8 会新增三条写账路径（§6 第 7 条），`unknown` 的绝对量在 T8 收口前根本没有稳定基线，此刻定的阈值或比率出口大概率要重定。
4. **但请给一个便宜的补偿**（不需要裁定、不动 §8）：把「生产者不许自写 `client_aborted`」（N1）与「`unknown` 计数走查询而非 API 键」（本条）两句话一起写进 T9 的验收清单，并在 §6 第 7 条末尾加一句「链只能写 kind，两种哨兵由账本产出」。**观测出口留给 V2.6 模型控制台是正确的落点**——那里要的是 per-provider / per-mode 的 breakdown，一枚全局 `unknown_rate` 到时候仍然不够用，现在加等于加半枚。

若终审否决我这条：那至少要求 `unknown_rate` 与 `aborted_rate` 同批过白名单、同批钉「不许前缀放行」，并接受 §8.1 第 3 条要再写一次。

---

## 6. 我实际跑过的命令与关键输出

```
# 定向：九枚新增测试按 node-id 单跑（证明它们真在树里、真的绿，不是报告自述）
cd backend && python -m pytest <9 个 node-id> -q
  → 10 passed, 24 subtests passed in 25.46s        # ModelRouteProducerUniquenessTests 整组=2 例

# 抽三处首轮 PASS 门禁复跑（本轮有没有把它们跑坏）
cd backend && python -m pytest tests/test_llm_usage_contract.py -q \
  -k "nineteen_columns or never_leaks_into_the_healthy_face or long_chinese_prompt \
      or window_rates_and_p95 or degrades_to_an_empty_block"
  → 5 passed, 95 deselected                         # 19 列等式 / D4 healthy 纯度 / 禁存项全列 0 命中
cd backend && python -m pytest ... -q -k "canary or single_byte or fail_open or open_breaker \
  or routers_own_vocabulary or cost_survives_even"
  → 6 passed, 94 deselected

# I-5 的验收姿势（两个 cwd）
cd backend  && python -m pytest tests/test_llm_usage_contract.py -q -k "window_rates_and_p95 or never_leaks…"  → 5 passed
cd /e/xiangmu/rag && python -m pytest backend/tests/test_llm_usage_contract.py -q \
  -k "window_rates_and_p95 or degrades_to_an_empty_block or broken_registry_still_reports"                      → 3 passed

# I-5 附加：跨目录跑「另一个文件」（首轮报过 cwd 依赖的那个）
cd /e/xiangmu/rag && python -m pytest backend/tests/test_model_router_v23_contract.py -q
  → 1 failed, 240 passed, 346 subtests in 30.68s
    FAILED RouterSettingsTests::test_argless_settings_still_constructs_on_host_env
      app.llm.registry.RegistryError: config\llm_registry.json FileNotFoundError
cd backend && python -m pytest "…::test_argless_settings_still_constructs_on_host_env" -q  → 1 passed
grep -c test_argless_settings… snap-task4/test_model_router_v23_contract.py                → 1  ⇒ 非本轮引入（见 N3）

# 口径归零核对
grep -rn "model_route_payload\|_route_stage\|_route_error_code" backend/app backend/tests   → 只有 docstring/注释 + 防回潮钉本体，无实现、无导出
grep -rn "T4 交付\|T4 已交付" backend/app backend/tests docs                                → 0 命中（exit 1）
grep -n "class AllCandidatesFailedError" -A 30 backend/app/llm/fallback.py                  → 该对象无 selected_index/context_dropped（N4）
wc -l backend/app/llm/__init__.py = 448 / usage.py = 1056 / 与报告自述一致（503 → 448）
python -c "from app.security import PUBLIC_LLM_STATUS_KEYS" → 13 枚，本轮未扩

# 改动面 / 快照核对（只读，不用 git）
diff -q snap-task5/{app/agent_trace,app/security,app/knowledge_os,app/main,tests/test_llm_usage_contract,tests/test_model_router_v23_contract}.py 工作树  → 全部 identical
diff -q snap-task5/app/llm/{__init__,usage,fallback,models,provider,registry,router}.py 工作树                                                    → 全部 identical
  ⇒ 门禁快照 = 工作树，本轮没有「快照之外还改了文件」；且 fallback/rag/agent/config 与 snap-task4 同尺寸

# 内存变异（rev5r1_mutations.py：monkeypatch + with 退出即还原，未改任何源码文件）
V1 _has_delivery 恒真                    基线绿 → 变异红  被杀
V2 client_aborted 判据退回「只看缺失」    绿 → 红  被杀
V3 _clean_codes 去 dedupe + 去上限        绿 → 红  被杀      # 首轮那发存活的变异，现已可杀
V4 _trace_flag 退回 bool(...)             绿 → 红  被杀
V5 provider 名正则退回宽字符集            绿 → 红  被杀
V6 后缀只判位数不判取值域                绿 → 红  被杀
V7 _trace_stage 恒返回 "primary"（形状对、语义漂）  绿 → 红  被杀
V8 把 model_route_payload 挂回 app.llm    绿 → 红  被杀
V9 换名九键生产者**运行时**挂进 app.llm    绿 → 绿  存活      # 见 N2：源码扫描天然看不见运行时注入，
                                                             # 有意义的边界是下面 B1/B2/B3，不是这一发
# 语义探针（rev5r1_probes.py，纯内存 + 临时对象）
A1 token="n/a" + fallback_index=0 + 失败 ⇒ unknown      # 「先收口再判定」的顺序真的生效（I-4）
A2 真交付(0,10/5) ⇒ client_aborted / A3 fallback_index=-1+tokens ⇒ unknown
A4 显式 error_type="client_aborted" + 零交付 ⇒ client_aborted  ← 绕过交付闸 = N1
A5 retryable:1000 + status 1000 ⇒ ('retryable:1000', 1000)（两侧同收）
A7 trace 侧 _trace_error_code("retryable:1001") ⇒ unknown（两侧同拒）
B1 双引号九键第二生产者被扫描抓到 ⇒ True / B2 单引号 ⇒ False / B3 kwargs 构造 ⇒ False   ← N2
B4 豁免按 path.name 比对 ⇒ 子目录同名 usage.py 会漏                                     ← N2
C1 真 provider 名通过新正则：ollama/openai/deepseek/qwen/zhipu_ai=True；api.openai.com/127.0.0.1:11434/Ollama/glm-4=False
   另：出厂注册表 config/llm_registry.json 的 provider 名 = [deepseek, ollama, openai, qwen]，0 枚被误杀
C2 ROUTE_REASON_MAX_ITEMS == len(REASON_CODES) == 9（与 §5 的九枚枚举不再矛盾）

# 副作用自查：本复审只写了 .superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev5r1_*.{py,log,md}；
#   find backend/app backend/tests -newermt "2026-09-24 03:00"  → 空（我会话期间源码零写入；
#     usage.py 的 02:55 mtime 是修复者自己最后一次写入，sha1 与 snap-task5 逐字节相同 f22c01f1…）
#   backend/data/audit.jsonl mtime = 02:59:24、agent_traces.jsonl = 09-23 15:58 ⇒ 我跑的定向/跨目录
#     测试没有向真实数据文件追加一行（首轮评审曾出现过一次 status 审计追加，本轮未复现）
#   未跑全套件（主 agent 已核 748/0）；未跑任何真实 LLM/Ollama 外呼（变异与探针均 monkeypatch）。
```
