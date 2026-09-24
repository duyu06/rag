# Model Router V2.3 — Task 6 修复轮 1 · scoped 复审裁定

复审者：Task 6 修复轮 1 scoped 复审（只读 + 定向跑 + 变异复验）
被评审对象：`backend/tests/conftest.py`（新建）、`backend/tests/test_model_router_v23_contract.py`
（新增 `ModelRouteIntegrationTests` / `LedgerIsolationGuardTests` + 改 `_FallbackFixture` 族）、
`backend/app/llm/usage.py`（docstring）、`task-6-report.md`「修复轮 1」段
输入：`review-task-6-findings.md` §3 I-1/I-2 + §4 Minor 1/2/4/5 + §6 移交表
复审日期：2026-09-24
复验工作区：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev6r1_mutation_lab/backend/`
（**backend 的一次性副本**；本轮全部变异只发生在副本里，真实 `backend/` 六个关键文件
sha1 跑前跑后逐字未变，见第 6 节）

---

## 1. Verdict

**PASS-with-minors** —— 放行 Task 7。

一句话理由：I-1 的六条骨架**逐条落地并且我独立复现了它有牙**（注释掉 `attach_model_route`
⇒ 红；把响应回显模型名改成与注册表不同 ⇒ 红；给九键多塞一枚 ⇒ 两例同时红；聚合异常不填
`context_dropped` ⇒ 降级例红；`_trace_stage` 不认负 index ⇒ stage 例红）；I-2 做成了
「夹具补漏 + 会话级护栏 + 三枚防回潮钉」三层，我实测**真实库全程零污染**
（`llm_request_logs` 0 行、`conversations.db` sha1 `39bca2c404e2` 未变），并且证明护栏
**没有悄悄削弱任何其他测试文件**（29 个文件加/去护栏的结果集逐字相同）。
新发现的问题全部是**护栏自身的边界与措辞**（读也按写归责、两枚钉是前缀检查、非 `backend/`
cwd 下护栏整体失效），定级 Minor，不阻断 T7，但**必须按第 5 节写进 T7/T9/T10 的口径**。

| 首轮项 | 本轮判定 |
| --- | --- |
| **I-1** 矩阵 #17「真调用」半段 | **ADDRESSED** |
| **I-2** 测试写真实库 | **ADDRESSED**（补漏 + 护栏，护栏本身另生 3 枚新 Minor） |
| Minor 1（同义反复的空表扫描） | **ADDRESSED** |
| Minor 2（展示面缺 httpx 闸） | **ADDRESSED**（我复现了它有牙） |
| Minor 4（`usage.py` 文档漂移） | **ADDRESSED**（代码零改动，AST 级核实） |
| 改动面纪律 | **PASS**（无越界） |
| 报告可信度（D6 表） | **PASS**（28 个数字逐枚对得上，可让 T9 直接抄） |

---

## 2. 必查 1–6 逐项判定

### 2.1 必查 1｜I-1 `ModelRouteIntegrationTests` 是否真按骨架交付 → **ADDRESSED**

对象：`tests/test_model_router_v23_contract.py:4811-4958`（+ `MODEL_ROUTE_NINE_KEYS` 常量 :4805）。

| 骨架要求 | 判定 | 证据 |
| --- | --- | --- |
| 九键**集合等式**，多一枚少一枚都红 | ✅ | `:4887` `assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route))` + `:4888` `assertEqual(9, len(route))`；九键清单逐枚对 DESIGN §8/§8.1 第 4 条（六键 + stage/selected_index/context_dropped）一致。**复验**：副本里给 `usage.model_route_trace` 的返回多塞一枚 `extra_key` ⇒ **两例同时红**（`Items in the second set but not the first: 'extra_key'`，1 failed→2 failed） |
| `attempts` 非空 | ✅ | `:4892` `assertTrue(route["attempts"], "attempts 非空：这是一条真跑过一次的链")` |
| `primary.model == result.response.model`（M2 同源，**不是自比**） | ✅ | `:4893`，另加 `:4894` 钉 `RAG_LOCAL_MODEL` 字面量、`:4895` 钉 `attempts[0]["model"]`。**独立反证（我这轮自己加的发）**：把 `serve()` 的回显体模型名改成 `"ghost-echoed-model"`（provider 侧 `normalize.py:106` 是 `data.get("model") or model` ⇒ `result.response.model` 来自**响应体**，而 `route["primary"]["model"]` 来自**注册表**，两条独立推导）⇒ `test_a_real_llm_complete_lands_a_nine_key_model_route` **红**：`'ghost-echoed-model' != 'ornith-1.5:9b-text'`。**这条等式有牙，不是同源自比**。 |
| 整份 trace 序列化后 canary / `SYSTEM_PROMPT[:24]` / 「请依据以下证据回答问题」0 命中 | ✅ | `:4856-4867` `assert_no_private_bytes`：`json.dumps(trace, ensure_ascii=False)` 上扫 5 枚（canary、`差旅住宿上限每天陆佰元`=答案正文、`报销制度.md`=证据文件名、`SYSTEM_PROMPT[:24]`、`请依据以下证据回答问题`），成功路 `:4907` 与降级路 `:4952` 各扫一次。**非空洞性我也复验了**：同一夹具、同一 `serve()` 下断言 canary **确实出现在出网的请求体里**（`self.requests[0].payload` 内含 canary）⇒ 1 passed。所以「trace 0 命中」不是「链上本来就没有这些字节」的同义反复 |
| **真写 JSONL 再读回**（内存对象不算） | ✅ | `:4908-4918`：`tempfile.TemporaryDirectory()` + `mock.patch.object(agent_trace_module, "TRACE_PATH", path)` → `save_trace(trace)` → 直接 `path.read_text()` 断言**恰好 1 行** → `json.loads(line)[MODEL_ROUTE_KEY] == route` → 再扫一遍禁存项 → `get_trace("t6-integration")` 与原 trace 全等。`TRACE_PATH` 是**调用时读模块属性**（`app/agent_trace.py:71-83`），patch 有效；`data/agent_traces.jsonl` mtime 仍停在 `09-23 15:58` ⇒ 真文件没被碰 |
| `AllCandidatesFailedError` 那支给出 `stage="none"` 且 `context_dropped` 有值 | ✅ | `:4920-4958`：真链（候选 A `limits.context_tokens=10` 被上下文收口剔掉、候选 B 真外呼吃 500）⇒ `:4943` `stage=="none"`、`:4944` `selected_index==-1`、`:4945-4946` `context_dropped == exc.context_dropped == 1`（**取的是 1，不是缺省 0**）、`:4947-4950` attempts 长度 1 / `result=="failed"` / `error_type=="model_unavailable"` / `model=="phi3:mini"`，另 `:4953-4958` 与**真账本行**对照（1 行、`success=0`、`model` 与 trace 同一个词）。**两发独立复验**：`fallback.py:542` 的 `context_dropped=self.context_dropped` 改 0 ⇒ 本例 + `PlanCarrier` 那枚同时红（`1 != 0`）；`usage._trace_stage` 不认 `selected_index<0` ⇒ 本例红（`'none' != 'fallback'`） |
| 验收命令 + 内存变异 | ✅ | 我在**真实** `backend/` 跑 `-k ModelRouteIntegration` ⇒ `2 passed, 283 deselected in 43.86s`；在副本里把 `:4882` 的 `attach_model_route(...)` 整行注释 ⇒ `1 failed, 1 passed`（`AssertionError: 'model_route' not found in {'trace_id': 't6-integration', 'events': []}`，报在 `:4885`） |

补充观察（不判缺陷）：`:4879` 断言 `"rag" == profile.mode`，而 `profile.mode` 是
`classify(question)` 恒写的常量 ⇒ 这一枚不构成「真实需求被识别」的证据；`requirements`
的 `complexity` 也没钉值（T6 报告口径是「complexity 不参与打分」）。真正撑起「画像真来自这条链」
的是 `:4871` 用 `serve()` 注入 MockTransport 后端到端跑通 + 账本里真有一行（`:4954` 那族）。
「不是测试另造一份画像」这一点靠 `:4836-4839` 的 classify spy 成立。

### 2.2 必查 2｜I-2 与「护栏本身是不是新风险」 → **ADDRESSED（护栏生 3 枚新 Minor，见第 4 节）**

**(a) 有没有测试原本依赖默认路径、改道后变成「测了个空临时库」仍绿？→ 没有。**

* 全 `tests/` 读 `database_path()` 的只有 2 枚：`test_llm_usage_contract.py:363-369`
  （`test_database_path_shares_the_conversation_store_source`）与 `:1930-1941`
  （`test_warmup_creates_a_table_a_fresh_deployment_does_not_have`）。两枚都在
  `mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": <临时绝对路径>})` 之内 ⇒
  `guarded()` 的 `_inside_repo_data` 判假 ⇒ **原样返回、不记一笔、期望逐字不变**。
  我复跑该文件（含在 413 例定向里）⇒ 绿。
* 依赖**默认**路径（env 未设 ⇒ `data/conversations.db`）的断言：全仓 **0 枚**。
* `ConversationStore(` 在测试里 5 处，4 处传显式路径（`test_conversation_store.py:18/56/75/83`、
  `test_typesafe_api_runtime.py:162`、`test_typesafe_security_contract.py:182`），
  唯一无参构造是 `test_llm_usage_contract.py:368`（在显式 patch 之内）。
  app 侧的模块级单例 `conversation_store = ConversationStore()`（`app/conversation_store.py:332`）
  在 **collection 期 import** 时就绑定了 `data/conversations.db`，**早于**会话 fixture 改 env ⇒
  护栏的 env 层动不了它（修复者自己在「仍存 minor 3」里写了这条边界，属实）。
  实测：副本上非契约测试跑两轮（含一轮无 conftest），`conversations` 恒 7 / `messages` 恒 10 ⇒
  **没有任何测试往会话面写真库**，所以这条边界目前不是破口，只是没被保护。
* **差分实测**（副本，`pytest tests --ignore=test_model_router_v23_contract.py`，
  有护栏 vs 把 `tests/conftest.py` 移走）：两臂都是
  `30 failed, 478 passed, 498 subtests`，FAILED/ERROR 清单 `diff` **逐字相同**。
  那 30 枚红是副本缺 `frontend/`、`README.md`、`requirements.txt`、`.env.example`
  等**同级文件**造成的路径伪影，与护栏无关。**结论：护栏没有让任何其他任务的测试变弱或变强。**

**(b) 是否「只在未被显式设置时改道」？与 `patch.dict(..., clear=True)` 会不会互相打架？→ 处理正确。**

* `conftest.py:117-119`：`previous_env is None` 才写 env；`finally:138-141` 收尾按原状还原
  （设过就还原、没设过就 pop）⇒ 显式设置者优先，且**不泄漏**到进程外。
* `_EgressFixture.setUp`（`:799-801`）的 `mock.patch.dict(os.environ, {}, clear=True)`
  会把第 1 层设的 env 清掉（fixture setup 顺序：session → function）⇒ 所以**必须有第 2 层**。
  这不是「打架」，而是修复者在 conftest 文档串里写清的取舍（`:16-20`）。
  我实测这条链路成立：副本探针里 `aggregate_status()` 在 `clear=True` 之下确实被第 2 层拦下
  （见 (d)）。**代价**：第 2 层把「读」也当成事故 —— 见第 4 节 N1。

**(c) 三枚钉可达吗（不是恒真）？→ ①②③ 都可 redis，我逐枚复现过。**

| 钉 | 复现方式（全部在副本，未碰真实 `backend/data/`） | 结果 |
| --- | --- | --- |
| ①`the_effective_ledger_path_is_not_the_repository_database` | `mv tests/conftest.py` ⇒ `guard_is_active()` 为假 ⇒ `assertTrue` 红；（该形态下契约测试文件整体 `import conftest` 失败，先变 collection ERROR，见第 4 节 N4） | 可红 |
| ②`no_test_in_this_session_tried_to_write_the_real_ledger` | 把 `:2826` 的 `self._isolate_usage_ledger()` 换成 `pass`（= 评审点名的「sink 指向真库」那一发，R3 同形） | **红**：`Lists differ: [] != [('data\\conversations.db', '<会话临时>')]`；同时**肇事那一例自己 ERROR**（`PlanCarrierTests::test_complete_passes_the_result_object_through_untouched`），终端打 `[ledger-guard] 1 次…` |
| ③`the_repository_ledger_table_is_still_empty` | 一枚绕过 `database_path` 的直写（探针文件排在契约文件之前 ⇒ 钉在它之后跑） | **红**：`AssertionError: 1 not found in (0, None)` |
| ③ 的反面（**边界**） | 同一枚直写，但探针文件排在契约文件**之后** | **三枚钉全绿**，而那 1 行**真的留在了副本的 `data/conversations.db` 里** ⇒ ②③ 是**前缀检查**，见第 4 节 N2 |

关键对照：R3 形态下（护栏在场）真实库**没有**被写（副本 `llm_request_logs` 恒 0），
所以 ③ 绿是**正确的**——它的角色是「护栏之外」的兜底，不是主闸。主闸是逐例归责那道。

**(d) 「真实库 0 行」这枚强口径要不要改成替换方案？→ 可以保留强口径，但必须补一句可诊断信息。**

现状：`conftest.py:76-92` 只读 URI 打开真库（自己不留痕，实测它没造 sidecar）；
`assertIn(rows, (0, None))` 同时接受 `None`（文件/表不在场）⇒
**CI / 新克隆（`backend/data/` 在 .gitignore 里，见 `.gitignore:7`）上这枚是真空通过**，
只在「跑过真 app 的开发机」上会变红。所以：
① 修复者自述的「强口径」**比实现更强**：实现已经允许 `None`，不是硬绑本机。
② 真正的缺陷是**归因措辞**：开发机上有真账时，它把既有真样本读成「测试写了 N 行账」。
③ 判定：**不要求退回快照等式**（快照等式丢掉「本仓库这份数据必须是干净的」这条承诺，
而这条承诺正是 I-2 的实质），但**要求**把它做成可诊断：会话 fixture 里存一份
`_SNAPSHOT = real_ledger_row_count()`，断言 `rows in (0, None)`，失败信息同时打
「会话开始时 = `_SNAPSHOT`」⇒ 一行改动、零强度损失、彻底消除误导。
另外：T10 若按 `task-10-brief.md` 的移交项落临时库，则不会撞上；若 T10 用真库做验收，
T11 的全套件会红 ⇒ **这条必须写进 T10 的执行前检查**（见第 5 节 M-T10-1）。

### 2.3 必查 3｜Minor 1 / Minor 2 → 双 **ADDRESSED**

* **Minor 1**（`test_the_zero_candidate_exit_writes_no_row_at_all`，`:4471-4502`）：
  现在**先落一行真成功账**作对照组（`:4484-4488` 断言 `len(control)==1` 且 `success==1`），
  再跑零候选那一支，断言三枚：行数不动（`:4495`）、那一行仍是成功账（`:4496`）、
  **非空表上**不存在 `success=0 ∧ error_type 空`（`:4497-4499`）。⇒ 不再是 `[]==[]` 的同义反复。
  同时强度只增不减（原两枚都还在）。
* **Minor 2**（`test_the_display_face_never_touches_the_network`，`:4639-4656`）：
  `for name in ("get","post","Client"): mock.patch.object(rag_module.httpx, name, forbidden)`
  ——三处**确实都上了闸**，叠加 `setUp` 的 `fail_on_any_probe()`（`:4057-4063`）与
  `self.requests == []`（MockTransport 零请求）⇒ 共三道。**有牙复现**：副本里在
  `rag.py::current_model_name()` 第一行塞 `httpx.get("http://127.0.0.1:1/...")` ⇒
  `RagDisplayedModelNameTests::test_the_display_face_never_touches_the_network` **红**
  （`AssertionError: 展示面 current_model_name() 不许出网`，报在测试文件 `:4651` 的 `forbidden`），
  其余 7 例仍绿。⇒ 「展示面零网络」从读代码证升级成测试证。（该 URL 指向 127.0.0.1:1 且
  `httpx.get` 已被替换成 `forbidden` ⇒ 本轮零真实外呼，本机 11434 未被打扰。）

### 2.4 必查 4｜`usage.py` 是否只有 docstring 变化 → **ADDRESSED（代码零改动，已 AST 级核实）**

* 逐文件 diff：`snap-task5/app/llm/usage.py` → 工作树 = **1 个 hunk、3 删 / 5 增、全在
  `:366-376` 的 `model_route_trace` docstring 里**（`diff -u | grep -c '^@@'` = 1）。
* 我另跑了一次**AST 级**核实：把两个文件的 module/class/function docstring 全部剥掉后
  `ast.dump` **完全相同**（`usage.py code (docstrings stripped) AST identical: True`）。
* 内容上也确实是评审 §4-4 指的那处漂移的正解：新文字说明 `context_dropped` **自 Task 6 起
  是异常带的字段**、`selected_index`/`stage` 仍按「没有事实」落，不再写「它没有这两枚字段」。
* 其余 9 个 `app/llm/` 模块（normalize/router/provider/registry/health/classifier/models/
  errors/`__init__`）对 `snap-task5` **零差异**；`app/agent_trace.py`、`app/main.py`、
  `app/security.py`、`app/knowledge_os.py`、`tests/test_llm_usage_contract.py` 全部逐字未变。

### 2.5 必查 5｜改动面纪律 → **PASS，无越界**

* `app/rag.py` 内容未变：sha1 `a5a638716947` == 首轮评审 §7 的 RESTORE 行 `a5a63871…`。
* `app/llm/fallback.py` 内容未变：sha1 `008d8213bc05` == RESTORE 行 `008d8213bc…`。
  （两者 mtime 都是 `05:08:51`，是变异-还原留下的时间戳 ⇒ **按内容判**，不按时间判。
  修复者在报告 §0 的「范围核对提示」里主动交代了这一点，措辞准确。）
* `tests/test_model_router_v23_contract.py`：对 `snap-task5` 用 `difflib.SequenceMatcher`
  复核 ⇒ **旧侧被删/改 0 行、新增 1098 行**，4 个 hunk 全是 `insert`。⇒ 「既有断言 0 改动」属实。
* 本轮触碰窗口（`find backend -newermt "2026-09-24 04:45"`，排除 pycache）只有
  `app/rag.py` / `app/llm/{fallback,usage}.py` / `tests/{conftest,test_model_router_v23_contract}.py`
  五个源文件 + `data/` 的三个 sidecar（见 2.6）。**`docs/`、`frontend/` 本轮零触碰**（同窗口 find 为空）。
* 允许的改动面之外**没有新文件**：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t6fix1_mutations.py`
  属评审包目录，合规。
* 我自己造成的副作用（如实报）：在真实 `backend/` 跑定向测试（`-k ModelRouteIntegration`、
  413 例定向）后，`backend/data/` 多出 `conversations.db-shm`(32 KB) 与 `conversations.db-wal`(0 B)
  两个 sidecar，`data/audit.jsonl` 由非 T6 用例追加（+~1.5 KB，canary 命中数 21→21 未增）。
  **主库 sha1 与行数未变**（`39bca2c404e2`、0/7/10）。⇒ 这恰好是 2.2(a) 那条边界的现场证据：
  测试进程**只是 import 应用代码**就会以 WAL 打开真库；护栏不管这一面。

### 2.6 必查 6｜修订后的 D6 命中表可信吗 → **PASS，可让 T9 逐枚照抄**

我按「非注释行」独立数过 `app/rag.py`（280 行），与报告 §5 的表**逐枚对得上**：

| 模式 | 报告 | 我的实测 | 判定 |
| --- | --- | --- | --- |
| `httpx` 代码命中 | 3（27/204/220） | 3（27/204/220） | ✅ |
| `httpx` 散文命中 | 7（9,10,13,18,20,22,246） | 同上 7 行 | ✅ |
| `httpx.post(` / `import httpx` | 2（204,220）/ 1（27） | 一致 | ✅ |
| `httpx.get` / `httpx.Client` | 0 / 0 | 0 / 0 | ✅ |
| `"/api/chat"` / `"/chat/completions"` | 各 1（221 / 203），散文 L11 各 1 | 一致（L11 一行同时提到两枚字面量） | ✅ |
| `settings.openai_base_url` / `ollama_base_url` | 1（203）/ 1（221） | 一致 | ✅ |
| `openai_api_key` 代码读法 | **3（142/202/206）** | 3（142/202/206） | ✅ |
| 同上的散文 | **2（L92/L109）** | 2（两处都在 `current_model_name` 的 docstring 内） | ✅ |
| `OLLAMA_BASE_URL` / `_API_KEY` 大写 | 0 / 0 | 0 / 0 | ✅ |
| `timeout=120` | 2（215,230） | 一致 | ✅ |
| `"temperature": 0.1` | 1（209） | 一致（255/257 的 `0.1` 在 docstring 内，报告口径写的是「代码里只剩一枚」⇒ 成立） | ✅ |
| `settings.ollama_model` / `openai_model` | 3（99,144,223）/ 2（143,208） | 一致 | ✅ |

一处**必须提醒 T9 的实现细节**（不是表的错）：`RagLegacyEgressInventoryTests`
（`:5004-5015`）的「代码」过滤是 `not line.lstrip().startswith("#")`，**只排注释行、不排
docstring**。对 `httpx` 恰好没事（散文中没有 `httpx` 出现在 docstring），但同一把尺子量
`openai_api_key` 会得到 **5** 而不是 3。⇒ T9 扫凭据类模式时**必须按上表的行号白名单**，
不要复用这个过滤器；否则会把 L92/L109 两句散文误判成两次凭据出口。
另：该测试只钉了 httpx/端点/get/Client 五枚等式，`openai_api_key=3`、`timeout=120=2`
**没有被钉**（报告 §5 的说法是「这组数字已被测试钉成等式（3 处 httpx / 2 处端点 / get+Client=0）」，
范围写得准，未越权声明）。⇒ 判 **可信、可直接抄**，附带上述一句使用限制。

---

## 3. 护栏的净效应结论（本轮最重要的判断）

**它保护了什么（真实收益，三条都是实测）：**
1. `app/llm/` 账本的**唯一落点解析函数**被包住（`usage._connect` 的 `database_path()`
   是读写共同的唯一收口，`usage.py:1012-1023`），所以「忘关 sink」「漏 `init_usage_db`」
   这类事故从「静默污染 §8 聚合的唯一数据源」变成「肇事那一例自己红 + 终端清单」。
   实测：拆掉夹具隔离 ⇒ 真库**没有**被写（0 行），而该例 ERROR + 钉 ② FAILED。
2. 第 2 层（路径层）**不受 env 被清空影响** ⇒ 挡住了 `patch.dict(..., clear=True)`
   这个 Task 1 就在用的手法造成的护栏旁路。
3. 隔离做在 `_FallbackFixture` **基类**（`:2826` 调用 / `:2828` 定义），罩住 9 个子类
   （含 `PlanCarrierTests`、`PackageEntryPointTests`）+ 未来新增子类 ⇒ 这是比评审要求的
   「补 `PlanCarrier` 一处」更宽的修法，且 `_RagMigrationFixture` 补了第三道 env 兜底
   （`:4078-4083`）。同类洞自查（全仓只有 `_log_usage → usage_sink()` 一条惰性解析路）成立。

**它可能让哪些既有测试变弱（实测答案：没有）：**
* 差分跑（29 个非契约测试文件、有护栏 vs 无护栏）结果集**逐字相同**（478 passed / 30 伪影 failed）。
* 全仓没有任何断言依赖「默认路径就是 `backend/data/conversations.db`」；两枚读
  `database_path()` 的测试都把 env 显式设到临时目录 ⇒ 护栏直通、期望不变。
* 唯一的**语义**变化是：今后任何测试若让账本解析落回仓库 `data/`，会从「静默污染」变成「红」。
  这不是变弱，是变严；但它带来下面三枚新风险。

**要不要补第三道闸？→ 要，但只补「会话面」那一道，且必须换收口点。**
1. **N1 的修法（把闸从「路径」挪到「写」）**：`guarded()` 里再判一次调用来源，或者
   另包 `usage._execute`（`usage.py:1025` 是**写路径唯一收口**）来记「写」这笔，
   `database_path` 层只做**静默改道 + 记一笔「读到真库」**（不判红，只在终端 summary 里列）。
   ——这样读用例不再被冤枉，写用例照样红。**这是本轮唯一建议的实现级改动，且只在 conftest 内。**
2. **第三道闸（会话面）**：conftest 再包一层 `ConversationStore.__init__`（未显式传 path 时
   改到会话临时库并记一笔）。可行性我已实测：在副本里把 `conversation_store.path` 临时换成
   临时文件后 `create()` 的写**落在临时库**、真库 `conversations` 恒 7（探针
   `PROBE-THIRDGATE repo conversations=7 probe-titled=0`，1 passed）。⇒ 一次 patch 就罩得住，
   **不需要**改 `conversation_store.py` 的读 env 姿势（那才是新增对外行为）。
   建议归 T7 顺手做（T7 是第一个大量用 `TestClient` 打会话流式面的任务）。
3. **不建议**给护栏加「快照等式替代 0 行」的降级（见 2.2(d)），改成补一句会话开始快照即可。

---

## 4. 新发现的破坏 / 矛盾（定级 + 修法）

> 全部落在**测试基础设施与文档措辞**层，没有一枚改变 shipped code 的对外行为，
> 也没有一枚让既有测试变弱 ⇒ 无一枚够 Important。N1/N2 我要求 T7 落地前修掉。

| # | 级别 | 发现 | 证据 | 修法（可执行） |
| --- | --- | --- | --- | --- |
| **N1** | **Minor（本轮最该修的一枚）** | **只读账本也会被护栏判成「写进了真实库」**：`_query`→`_connect(None)` 同样调 `database_path()`，所以纯读的 `aggregate_status()` 在 `clear=True` 之下会被记一笔并在收尾时把该例打成 ERROR，而失败信息一口咬定「测试把账本**写**进了真库」 | 副本探针：只调 `usage.aggregate_status(300)`（不写任何行）⇒ `PROBE-READ: redirects before=0 after=1 [('data\\conversations.db','<会话临时>/conversations.db')]` + `ERROR at teardown of ReadOnlyLedgerProbeTests` | 把「写」的判定挪到 `usage._execute`（写路径唯一收口），`database_path` 层只静默改道 + 终端汇总；或至少：`_REDIRECTS` 记 `(src,dst,kind)`，只有 `kind=="write"` 才逐例判红，读走 warning 行。**否则 T9 的 status 聚合用例（矩阵 #16）、T10/T11 的读面用例会成批踩坑并被误诊断** |
| **N2** | Minor | 钉 ②/③ 是**前缀检查**（会话级 `_REDIRECTS` 与「此刻真库行数」都在 `LedgerIsolationGuardTests` 的位置取值），其后的文件（字母序 `test_p16*`…`test_web_security`）里出的事它看不见；绕过 `database_path` 的直写更看不见 | 同一枚绕过护栏的直写：探针文件**排在前** ⇒ ③ 红（`1 not found in (0, None)`）；**排在后** ⇒ 三枚全绿且行留在副本 `data/conversations.db`（`SELECT` 实测到 `('rag','rev6r1-late',1)`） | ① 把 ②/③ 的 docstring 从「没有任何用例试图」改成「**截至本类开跑前**没有」，别给 T9/T11 虚假的全局感；② 真正的整会话闸放 `pytest_sessionfinish`：`_REDIRECTS` 非空 ⇒ `terminalreporter.write_sep("!", ...)` + 把 `session.exitstatus` 抬成非 0（`pytest_sessionfinish(session, exitstatus)` 里可直接改）。这条同时收掉 N2 与「计数解释」 |
| **N3** | Minor（本机相关，需写文档） | 护栏只认 `backend/data`。仓库根还有一份 `data/conversations.db`（40 KB，`.gitignore:8` 同样忽略），而默认值是**相对** `data/conversations.db` ⇒ **从非 `backend/` 目录跑套件时整层护栏失效**（实测：MUT-B + `cwd=rev6r1/` ⇒ 10 passed 全绿、`backend/data` 恒 0 行、行落在 `<cwd>/data/`）。同因：护栏**不保护** `<repo>/data` | 三行实测见上；`_inside_repo_data` 用 `path.resolve()`（相对 cwd） | ① 把 `_inside_repo_data` 改成候选集：`path` 若为相对，则同时按 `Path.cwd()/path`、`BACKEND_DIR/path`、`BACKEND_DIR.parent/path` 判；② 保护目录集合加 `BACKEND_DIR.parent/"data"`；③ T11 验收文档写明「全套件只在 `backend/` 下有效」（首轮 §6 第 11 条已提，这条现在多一个安全理由） |
| **N4** | Minor | `tests/test_model_router_v23_contract.py:100` 顶层 `import conftest as ledger_guard`：**删掉 conftest 会让整个契约文件 collection ERROR**（285 例一起没），而不是「三枚钉红」。这比修复者说的「整套件红」更糟：它把**被评审的 39+5 例证据**一起吞掉，且 `-k` 任意子集都跑不动 | `mv tests/conftest.py` 后跑 `-k PlanCarrier` ⇒ `ERROR tests/test_model_router_v23_contract.py` / `Interrupted: 1 error during collection` | 保留「不兜底」的立场（我同意：护栏文件被删应当响），但把兜底换成**可诊断**形态：`try: import conftest as ledger_guard; _GUARD_IMPORT_ERROR=None except ImportError as exc: ledger_guard=None; _GUARD_IMPORT_ERROR=exc`，并在 ① 那枚钉里 `failIf(_GUARD_IMPORT_ERROR)`。⇒ 少三枚钉时是**三枚红**，契约文件其余 282 例仍能跑 |
| **N5** | Minor（报告口径） | 报告 §2(c) 说「③ 用的是评审给的**首选**口径『跑完后真库必须仍是 0 行』」——评审原文（findings §3 I-2 验收方式）其实写的是「与跑前**相等**」。本轮实现比评审要求的更强，且**额外允许 `None`** ⇒ 既不是原文口径、也不像自述那么硬 | findings `:127-129` vs 报告 `:489-494` | 不要求改回弱口径（我判强口径更好），但报告要如实写成「**比评审要求的更强**（0 行 + 允许文件/表不在场），并已准备快照等式作为替换」。这不是撒谎，是引文不精确 |
| **N6** | 提示（不算缺陷） | `guard_legacy_egress_off` / 展示面三闸写的是 `mock.patch.object(rag_module.httpx, "get"/"post"/"Client")` —— `rag_module.httpx` **就是全局 httpx 模块**，所以这两处 patch 在生效期内是全进程级的（对 MockTransport 无影响，因为 provider 用 `Client(transport=...)` 的实例化路径……而 `Client` 也被换掉了）。今天无害（测试内不出网），但 T7 若在同作用域里想真起 client 会踩 | `:4127-4131`、`:4649-4652` | T7 若需要真 client，请 patch `app.llm.provider._client` 而不是全局 `httpx.Client`；否则沿用时注意作用域 |

**没有发现任何实现级破坏。** 特别地：`app/rag.py`、`app/llm/fallback.py` 本轮零内容改动，
`usage.py` 零代码改动 ⇒ shipped 行为与首轮判 PASS 的状态逐字一致。

---

## 5. 移交 T7 / T8 / T9 / T10 / T11 的强制口径（编号、可照做）

### → T7（SSE 链迁移）
* **M-T7-1**｜非流式那支的 #17 已由 T6 交（`:4811-4958`，2 例，我复验 5 发变异全红）。
  你只需交**流式那支**：`summary = session.finish()` 后
  `attach_model_route(trace, summary.plan, summary, profile=profile)`，
  并照 T6 的形状钉九键集合等式 + 真 JSONL 往返 + 禁存项扫描。**别**再去补非流式那半段。
* **M-T7-2**｜`StreamInterrupted` 仍不带 `plan`/`context_dropped`（`fallback.py:873-879`）。
  commit 后中断那一支的 route **只能**从 `finish()` 拿；自己拼 dict = 违反 §8.1 第 4 条唯一生产者。
* **M-T7-3（护栏相关，开工前必读）**｜`backend/tests/conftest.py` 会把落到 `backend/data/`
  的账本路径改道并**让肇事那一例红**。T6 的实测边界，你必须绕开：
  1. **只要读账本**（`aggregate_status` / `routing_health_view` / 任何走 `database_path()` 的路径）
     且 env 被 `clear=True` 清过，也会被记一笔并判红（新发现 N1）。⇒ 你的夹具**必须**
     照 `_RagMigrationFixture`（`:4065-4083`）：`init_usage_db(临时库)` + `set_usage_sink(None)`
     + `CONVERSATION_DB_PATH` 指临时目录，三道全上。
  2. **`TestClient` 打 `/api/conversations*` 会写真实库的 `conversations`/`messages`**，
     护栏管不到（单例 import 期绑定）。⇒ 每个真 HTTP 面用例请自带
     `mock.patch.object(conversation_store, "path", <临时文件>)`（可行性我已实测，见 §3 第 2 条），
     并**顺手把这条做成 conftest 的第三道闸**（`ConversationStore.__init__` 包一层），
     这是本轮交给 T7 的唯一新增基础设施义务。
* **M-T7-4**｜`normalize.ollama_payload` **恒发** `options` 与 `tools`（`normalize.py:53-63`）。
  矩阵 #18 报文面必须像 T6 那样**双向枚举键集合差**（`set(a)-set(b)` 与 `set(b)-set(a)` 都钉），
  漏发/多发就是行为变更，不许放宽断言。
* **M-T7-5**｜`stream_committed` 属 SSE payload，不进 `model_route`（九键是闭集，`:4887` 那枚
  等式会替你看住）。
* **M-T7-6**｜若你在 `current_model_name` 一类展示面复用「零网络」姿势：三道闸
  （`httpx.get`/`post`/`Client` + 探针上闸 + MockTransport 零请求），T6 已给模板（`:4639-4656`）。

### → T8（Agent 链迁移）
* **M-T8-1**｜`NoCapableModelError` **不带** `plan`/`context_dropped`；fast-path 要挂 trace 必须
  自己把 `plan` 传到 `attach_model_route`。
* **M-T8-2**｜#17 的 agent 半段请钉成**一对**：trace 里读得到 `stage`/`reason_codes`，
  账本里**读不到行**（零候选不产行是 T5 裁定）。
* **M-T8-3**｜`llm.complete(mode="agent")` 的温度默认 0.2（`app/llm/__init__.py:216`）。
  先查 `agent.py::_ollama_chat` 现网发的是多少再决定显式携带（T2 I-4 同类事故）。
* **M-T8-4**｜护栏口径同 M-T7-3（尤其「读也判红」与 agent 链的 trace 写盘：`TRACE_PATH`
  请 patch 到临时文件，别追加进 `data/agent_traces.jsonl`）。

### → T9（矩阵收口 + D6 静态扫描）
* **M-T9-1**｜**豁免表可以直接抄**报告 §5 那张表（我 28 项逐枚实测一致，见 2.6）。
  两个使用限制：
  1. 扫描凭据类模式时**不要**复用 `RagLegacyEgressInventoryTests` 的
     `not startswith("#")` 过滤器（它不排 docstring，会把 L92/L109 算成代码 ⇒ 得到 5 而不是 3）；
     按 `openai_api_key` 的 **行号白名单 142/202/206** 列豁免，L142/L202 标「读 bool 非出口」、
     L206 标「唯一凭据出口」，禁前缀放行。
  2. 模式集必须补 **`/chat/completions`（无 `/v1`）**——`rag.py:203` 用的是无 `/v1` 的字面量，
     现 brief 的 `/v1/chat/completions` 对这条腿不可见（`SingleEgressStructureTests`
     的 `FORBIDDEN_LITERALS` 早已含它，两份口径本就对齐）。
* **M-T9-2**｜#17 归属**现在可以结清**：台账/矩阵上写
  「#17 集成半段：非流式 = **T6 已交**（`ModelRouteIntegrationTests` 2 例）；流式 = T7；
  agent = T8」，别再让三方互等。
* **M-T9-3**｜收口时 `SELECT COUNT(*) FROM llm_request_logs WHERE error_type='unknown'`
  必须是 0（mock 全跑完后）；**读这条 SQL 请用临时库或只读 URI**，别把真库开成写模式。
* **M-T9-4**｜清库义务已完成（真实库 `llm_request_logs` 实测 **0 行**，删前快照
  `db-backup-before-test-row-cleanup.sqlite`）。收口时顺手确认 `conversations=7 / messages=10`
  未增（若增了 = 某个真 HTTP 面用例写真库，护栏看不见，见 M-T7-3.2）。
* **M-T9-5**｜若你要给护栏补第三道闸，N2 的 `pytest_sessionfinish` 改法与 N4 的
  「可诊断 import」改法请一并做，别新开一处 `import conftest`。

### → T10（REAL-LLM-FAILOVER-001）
* **M-T10-1**｜`task-10-brief.md` 已写「usage 落库必须落**你显式指定的**临时库」——**这条现在
  不只是建议而是硬约束**：真库 `llm_request_logs` 非 0 行会让 `LedgerIsolationGuardTests` ③
  在 T11 的全套件里红（本机口径）。执行前检查：
  `export CONVERSATION_DB_PATH=<临时绝对路径>`（宿主 uvicorn 与你断言用的 `database_path()`
  同一个 env 源，天然同源），**跑完确认 `backend/data/conversations.db` 的 sha1 未变**。
* **M-T10-2**｜临时库姿势**已写进 brief**（§「T6 评审移交项」，我核读过）；补两句：
  ① `CONVERSATION_DB_PATH` 必须是**绝对路径**（相对路径会随 uvicorn 的 cwd 漂到
  `<repo>/data/`，那里护栏不保护，见 N3）；② trace 侧请同时
  `CONVERSATION_DB_PATH` + patch `TRACE_PATH`，不然 `data/agent_traces.jsonl` 会被追加真内容。
* **M-T10-3**｜P0 十字里的「model_route 两 attempt」请直接用
  `attach_model_route(trace, exc.plan or result.plan, result, profile=profile)`，
  九键等式照 `:4887` 抄；`phi3:mini` 是**真** Ollama 调用（这是 P0 的目的），
  但除它以外别引入任何新出网。

### → T11（全量回归 + 验收文档）
* **M-T11-1**｜全套件数字基线：**793 passed / 878 subtests / 0 failed（`cd backend`）**。
  +5 例的解释成立（`ModelRouteIntegration` 2 + `LedgerIsolationGuard` 3），
  我独立复跑 6 文件定向 = **413 passed / 381 subtests / 0 failed**（首轮 408 + 5），与报告逐字同。
* **M-T11-2**｜验收文档必须写：① §9 的两条行为变更（Ollama 显式 `temperature=0.1`；
  `model_used`/`llm_model` 改注册表 authoritative）；② RAG 链 V2.3 **不产 trace**、
  真值只进 `llm_request_logs`（`trace_id` NULL）；③ **测试护栏的三条边界**：
  只保护 `usage.database_path` 解析到 `backend/data/` 的路径（N3 的 cwd 依赖、
  `<repo>/data` 不在保护集、会话面单例不在保护集）、只读账本也会被它判红（N1）、
  ②③ 两枚钉是前缀检查（N2）。缺 ③ 这份文档就会让下一个人把护栏当万能。
* **M-T11-3**｜运行目录：`backend/` 之外跑必红（`RouterSettingsTests::test_argless_settings…`
  是既有 cwd 耦合，T5 N3 未修），且**在 repo 根跑还会让账本护栏整体失效**（N3 实测）
  ⇒ 这条从「便利问题」升级为「护栏前置条件」，必须落文档或按 N3 的轻修法修掉。

---

## 6. 我实际执行的命令与关键输出

> 真实 `backend/` 只做了**只读检查 + pytest 定向跑**；所有变异/探针都在副本
> `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/rev6r1_mutation_lab/backend/`。
> 副本目录深度刻意与真实仓库一致（`<root>/backend/tests`），因为若干测试用
> `parents[2]` 反推仓库根。零 git 写、零真实外呼（本机 11434 未被打扰）。

```bash
# 0) 关键文件基线（真实 backend，只读）
python -c "hashlib.sha1(...)"
  app/rag.py a5a638716947 | app/llm/fallback.py 008d8213bc05 | app/llm/usage.py 8a8f5b0cff28
  tests/test_model_router_v23_contract.py 3f06baaa502e | tests/conftest.py 83cfa7ae3bcf
  data/conversations.db 39bca2c404e2  （0 / 7 / 10 行）
# rag.py 与 fallback.py 的 sha1 == 首轮评审 §7 RESTORE 行 ⇒ 内容逐字未变（不看 mtime）

# 1) 定向：I-1 验收 + 防回潮钉 + 6 文件包（真实 backend）
python -m pytest tests/test_model_router_v23_contract.py -k ModelRouteIntegration -q
  → 2 passed, 283 deselected in 43.86s
python -m pytest tests/test_model_router_v23_contract.py -k "LedgerIsolationGuard or PlanCarrier" -q
  → 10 passed, 2 subtests（跑后真库仍 39bca2c404e2 / 0 行）
python -m pytest <6 文件> -q
  → 413 passed, 14 warnings, 381 subtests passed in 53.03s        （0 failed；首轮 408 + 5）

# 2) 改动面 / 差异（只读）
for f in app/llm/{normalize,router,provider,registry,health,classifier,models,errors,__init__}.py:
  diff snap-task5 backend → 全部 same；usage.py → 1 hunk（3删5增，全在 :366-376 docstring）
python -c "AST dump with docstrings stripped, usage.py snap vs now" → identical: True
diff -q snap-task5/tests/test_llm_usage_contract.py backend/tests/… → SAME
difflib.SequenceMatcher(snap→now, 契约测试文件) → 旧侧删改 0 行 / 新增 1098 行，4 个 hunk 全 insert
find backend -type f -newermt "2026-09-24 04:45"（排 pycache）
  → app/rag.py app/llm/{fallback,usage}.py tests/{conftest,test_model_router_v23_contract}.py
    + data/{audit.jsonl, conversations.db-shm, conversations.db-wal}（后两枚是**我**跑测试造的）
find docs frontend -newermt 同窗口 → 空
grep -rn "attach_model_route" backend/tests → 契约文件 4882/4940（本轮新增）+ T5 那族
pytest tests/conftest.py --collect-only → no tests collected（166 行、零测试函数）

# 3) D6 命中表独立复核（app/rag.py，280 行）
python 扫描（非注释行 / 注释行分列）
  httpx code=[27,204,220](3) comment=[9,10,13,18,20,22,246](7) | httpx.post(=2 | import httpx=1
  httpx.get=0 httpx.Client=0 | "/api/chat"=1@221 | "/chat/completions"=1@203
  openai_api_key 全命中=[92,109,142,202,206]，其中 92/109 在 current_model_name 的 docstring 内
  （用 sed -n '88,112p' 逐行看过）⇒ 代码读法确为 142/202/206 三处
  timeout=120=[215,230] | "temperature": 0.1=[209]（255/257 在 docstring）
  ollama_base_url=221 openai_base_url=203 ollama_model=[99,144,223] openai_model=[143,208]

# 4) 变异复验（全部在副本；跑完逐发还原并核对 sha1，收尾三文件全 OK）
M-A  注释掉 `:4882` attach_model_route
  → 1 failed, 1 passed：AssertionError: 'model_route' not found in {'trace_id','events'}
M-B  usage.model_route_trace 多塞一枚 "extra_key"
  → 2 failed：Items in the second set but not the first: 'extra_key'      （九键等式有牙）
M-A2 把 serve 的回显体模型名改成 ghost-echoed-model（**我加的反证，评审未做**）
  → 1 failed：'ghost-echoed-model' != 'ornith-1.5:9b-text'   （M2 是真交叉，不是自比）
M-R2 fallback.py:542 聚合异常 context_dropped=self.context_dropped → 0
  → 2 failed：PlanCarrierTests::test_the_context_drop_count_reaches_the_aggregate_error
             ModelRouteIntegrationTests::test_the_aggregate_failure_branch_…（1 != 0）
M-R5 usage._trace_stage 不再认 selected_index<0
  → 1 failed：'none' != 'fallback'                              （stage 那枚有牙）
M-R6 rag.py::current_model_name() 首行塞 httpx.get(...)
  → 1 failed：RagDisplayedModelNameTests::test_the_display_face_never_touches_the_network
    （AssertionError 报在测试文件 :4651 的闸上）；其余 7 例绿      （Minor 2 的闸活了）
M-B  拆掉 `_FallbackFixture.setUp` 的 `_isolate_usage_ledger()`（= 评审点名的那一发）
  → ERROR at teardown of PlanCarrierTests::test_complete_passes_the_result_object_through_untouched
    FAILED LedgerIsolationGuardTests::test_no_test_in_this_session_tried_to_write_the_real_ledger
    终端：[ledger-guard] 1 次「往仓库 data/ 下的真实账本写账」被护栏拦下
         data\conversations.db ⇒ <会话临时>/conversations.db
    副本真库 llm_request_logs 仍 **0 行**（护栏兜住了，改道生效）
    同形态 + cwd=副本根（非 backend/）→ 10 passed **全绿**，行落在 <cwd>/data/  ⇒ 新发现 N3

# 5) 护栏可达性 / 边界探针（副本，用完即删）
只读 aggregate_status(300) 且在 patch.dict(clear=True) 内
  → PROBE-READ: redirects before=0 after=1 + ERROR at teardown      ⇒ 新发现 N1
绕过 database_path 的直写（探针文件排前 / 排后两种顺序）
  → 排前：③ FAILED(1 not found in (0,None))；排后：三枚全绿且行留在真库  ⇒ 新发现 N2
mv tests/conftest.py 后跑契约文件 → ERROR … 1 error during collection      ⇒ 新发现 N4
patch conversation_store.path 到临时文件后 create()
  → PROBE-THIRDGATE repo conversations=7 probe-titled=0 / 1 passed  ⇒ 第三道闸可行

# 6) 护栏净效应差分（副本，非契约测试 29 个文件）
有护栏：  30 failed, 478 passed, 498 subtests in 92.14s
无护栏：  30 failed, 478 passed, 498 subtests in 90.46s
diff <(FAILED 清单 有) <(FAILED 清单 无) → IDENTICAL failure sets
（那 30 枚是副本缺 frontend/README/.env.example 等同级文件的伪影，两臂同现 ⇒ 与护栏无关）

# 7) 收尾完整性核对
python -c "sha1(...)";  ALL PRISTINE: True
  backend/app/rag.py a5a638716947 / app/llm/fallback.py 008d8213bc05 / app/llm/usage.py 8a8f5b0cff28
  tests/test_model_router_v23_contract.py 3f06baaa502e / tests/conftest.py 83cfa7ae3bcf
  data/conversations.db 39bca2c404e2（llm_request_logs 0 / conversations 7 / messages 10）
data/audit.jsonl canary 命中数 21 → 21（本轮未增）；data/agent_traces.jsonl mtime 仍 09-23 15:58
```

---

## 7. 一句话给主 agent

两件 Important 都真修掉了、而且都我自己拿变异复现过有牙；护栏是值得留的，
但请把第 4 节 N1/N2/N3 当作它的**使用说明书**一起落——特别是「只读也算写」这条，
T7/T9/T10 一定撞；顺手把 M-T7-3.2 的会话面第三道闸做掉，`conversations`/`messages`
那两张表现在完全没人看着。
