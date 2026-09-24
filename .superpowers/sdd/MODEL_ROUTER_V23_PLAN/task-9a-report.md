# Task 9 段 A 报告 — 矩阵收口 + D6 单一出口静态扫描 + 既有扫描收紧 + cwd 收口

## 状态

**段 A 四件（A-1/A-2/A-3/A-4）全部交付，验收门 1–3 全绿。**

| 门 | 结果 |
| --- | --- |
| 门 1 定向 | `tests/test_llm_egress_guard.py` **29 passed / 84 subtests / 0 failed**；`tests/test_llm_usage_contract.py + tests/test_model_router_v23_contract.py + tests/test_llm_egress_guard.py` **500 passed / 477 subtests / 0 failed** |
| 门 2 两种 cwd | `cd backend && python -m pytest tests -q` ⇒ **918 passed / 0 failed / 973 subtests（121.48s）**；`cd /e/xiangmu/rag && python -m pytest backend/tests -q` ⇒ **918 passed / 0 failed / 973 subtests（80.24s）**。基线 889/889 → 只增不减（+29 例 / +84 subtests） |
| 门 3 变异 | 8 发（`task9a_mutations.py`，字节读写 + 发内还原 + sha1 核对）：**7 killed + 1 发刻意 GREEN**（M3a，见下）；冻结件 sha1 跑完全部 IDENTICAL |
| 真实库只读复核 | `llm_request_logs=0 / conversations=7 / messages=10`（与主 agent 的基线一致；全套件跑完仍 0） |

零 git 写；零真实外呼（探针一律假 host + `httpx.MockTransport`）；未新增依赖；**未改 `app/` 下任何产品代码**（变异台注入过的两个临时文件已删除并清 `__pycache__` 残骸）。

## 交付文件（改动面 = 本段窗口）

### A. 新建

1. `backend/tests/test_llm_egress_guard.py`（900 行，**纯 LF**，29 例 / 84 subtests）
   - `D6AstFaceTests`（6 例）：AST 面等式钉（`import httpx` 落点集、httpx 出口动词调用点、端点字符串常量、凭据属性读法、扫描面非空、厂牌字面量分支禁令）。
   - `D6FullTextFieldTests`（5 例）：全文字面量面（brief 点名的五枚模式 + 三枚配套）等式、**散文面**等式、以及第三层关系 `全文 == 代码 + 散文`（逐模式逐文件）；恒 0 模式显式留行。**【修复轮 · 评审 Minor 3/4】**这一组现在 8 例：代码面改成按行集**测量**（`code_hits()`）并与派生值同核、加分区自核、加与 AST 面的跨算法互验。
   - `ExemptionTableTests`（3 例）：命中文件 ⊆ 豁免表、**豁免表与命中集互等 + 无死行**（放大一档与少一档都红）、扫描面不整目录跳过（`identity/`、`tools/` 都在面上）。
   - `NoBareValueErrorOnTheChainTests`（7 例）：T3 移交的「业务入口不裸放 `ValueError`」。
   - `UnknownAttributionTests`（2 例）：`error_type='unknown'` 的 SQL 归零 + 零候选不产行。
   - `MatrixDocumentClosureTests`（5 例 + 1 例注册表前提）：文档↔套件耦合闸。**【修复轮 · 评审 Minor 3】**段 A 交付时它是**单向**闸（文档写了不存在的例⇒红；套件有例没挂表⇒永远绿），修复轮补 `test_every_guard_test_class_is_discoverable_from_the_document` 成双向 ⇒ 本组 6 例。
2. `docs/MODEL_ROUTER_V23_MATRIX.md`（87 行，纯 LF）：19+1 全表 + P0 + 4 枚云行 + 两枚口径 + 缺项核对 + **§5 cwd 收口终态**（供 B 段与终审复用）。
3. `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task9a_mutations.py`：变异台（不进产品树）。

### B. 修改（全部是测试侧；`app/` 零改动）

1. `backend/tests/test_llm_usage_contract.py`（A-3，T5 N2）：
   - `ROUTE_KEY_MOUNT_FILES` / `ROUTE_OBJECT_PRODUCER_FILES` 改存**相对路径**（`app/agent_trace.py` / `app/llm/usage.py`），比对键换成 `path.relative_to(BACKEND_DIR).as_posix()`（新增 `_relative_source_path`）。
   - 谓词换成 `SELECTED_INDEX_PATTERN` / `CONTEXT_DROPPED_PATTERN`（`re.search(r"[\"']…[\"']")`，两枚各 search 再 `and`，与 brief 同形）；键名那条同理（`KEY_NAME_PATTERN` + 保留 `MODEL_ROUTE_KEY`）。
   - docstring 补「本钉只挡源码字面量，运行时注入由 #17 集成用例兜」，并**反向闸**：两枚豁免集合必须是扫描面的子集（豁免表养闲条目即红）。
     **【修复轮 · 评审 I-2】**段 A 那两枚谓词之后仍有两形可绕：`dict(stage=…, selected_index=…, context_dropped=…)`
     的 **kwargs 形**（源码里没有引号）与 `{"selected_" "index": …}` 的**隐式拼接形**（CPython 合成单枚
     `ast.Constant` ⇒ 文本面零命中）。修复轮把谓词从两枚扩到四枚（两支新谓词 `or` 进去），并把 docstring
     那句自述改成实际覆盖面（「写在源码里的键名三形全挡；运行期拼键名才交给 #17」）。
   - 补 `import re`。
2. `backend/tests/test_model_router_v23_contract.py`（A-4）：`RouterSettingsTests::test_argless_settings_still_constructs_on_host_env` 例内 `os.chdir(BACKEND_DIR)` + `addCleanup(os.chdir, original)`（brief 的方案①；**未动 §12 冻结默认值、未放宽任何断言**）。
3. `backend/tests/test_feishu_identity_contract.py::WarmupGateTests`（A-4 外溢，**新增红**）：`setUp` 把 `settings.llm_registry_file` 指到绝对的出厂文件、`tearDown` 还原。原因见 §5。
4. `backend/tests/test_typesafe_judgments.py::TypeSafeJudgmentTests`（A-4 外溢）：`setUp` 显式 `patch.object(settings, "typesafe_enabled", True)` + `("typesafe_mode", "selective")`。原因见 §5。

## D6 扫描终态（**供 B 段与终审直接复用**）

三层关系：`全文面命中 == 代码面命中 + 散文面命中`（逐模式、逐文件）——注释与 docstring 是
**单列计数**的一层，不是被忽略的噪声；本文件不声称两层同数（Task 8 的 m-1/m-2 教训）。
AST 面是**另一条独立算法**的四张等式表（`import httpx` / 出口动词 / 端点字符串常量 / 凭据属性读法），
不参与上面那条加法式。
**【修复轮就地更正 · 评审 Minor 4】**这一段原来写作「`全文面命中 == 代码面 == AST 面 + 散文面`」，
那个等式是**错的**（把 AST 面写成了加法项，实际两者互不隶属）。而且当时那句「代码面」还只是
从「全文 − 散文」**推导**出来的（`code_line_numbers()` 定义了零使用 ⇒ 内圈加法对任何实现恒真）。
修复轮后：代码面由 `code_hits()` 按行集**独立测一遍**，第三层同时核「派生值 == 测量值 ==
`CODE_EXPECTED`」，再配 `test_the_measured_code_face_is_confirmed_by_the_ast_face`（与 AST 面跨算法
互验）与 `ScanningHelpersAreAllLiveTests`（扫描 helper 一枚都不许变死代码）。

### 全文面 / 散文面 / 代码面（相对路径：计数）

| 模式（正则本体） | 全文面 | 散文面 | 代码面 |
| --- | --- | --- | --- |
| `/api/chat` | agent 1、conversation_agent 1、llm/provider 2、rag 2 | conversation_agent 1、provider 1、rag 1 | agent 1、provider 1、rag 1 |
| `/v1/chat/completions` | **∅** | ∅ | ∅ |
| `"/chat/completions"` | provider 1、rag 1 | ∅ | provider 1、rag 1 |
| `OLLAMA_BASE_URL` | **∅**（registry 运行期拼装，T1 移交） | ∅ | ∅ |
| `_API_KEY` | provider 1（docstring 里的 `OLLAMA_API_KEY` 散文） | provider 1 | ∅ |
| `httpx\.(post\|stream)` | agent 4、conversation_agent 1、rag 4 | agent 3、conversation_agent 1、rag 2 | agent 1、rag 2 |
| `^import httpx` | agent 1、identity/feishu_client 1、provider 1、rag 1 | ∅ | 同全文面 |
| `(openai\|deepseek\|qwen\|ollama)_(api_key\|base_url)` | agent 2、config 7、knowledge_os 1、llm/health 2、main 1、main_agent 1、rag 7 | agent 1、health 1、rag 2 | agent 1、config 7、knowledge_os 1、health 1、main 1、main_agent 1、rag 5 |

### AST 面

| 判据 | 终态 |
| --- | --- |
| `import httpx` | agent 1、identity/feishu_client 1、llm/provider 1、rag 1 |
| httpx 出口动词调用点（post/get/stream/put/patch/delete/request/Client/AsyncClient） | agent 1、feishu_client 1、provider 1、rag 2 |
| 端点字符串常量（非 docstring） | agent {ollama_chat 1}、provider {ollama_chat 1, openai_path 1}、rag {ollama_chat 1, openai_path 1} |
| `settings.<凭据名>` 属性读法 | agent {ollama_base_url 1}、knowledge_os/health/main/main_agent {openai_api_key 1} each、rag {openai_api_key 3, openai_base_url 1, ollama_base_url 1} |

### 豁免表终态（`EXEMPTIONS`，10 档 = 命中集，互等钉住）

| 文件 | 理由 |
| --- | --- |
| `app/llm/provider.py` | 唯一合法出口（真 import httpx + 两侧端点字面量 + 凭据 env 名散文） |
| `app/rag.py` | legacy 应急腿（两条 `httpx.post` + 端点字面量 + 凭据读法）；§1 已判「下一稳定版删除」⇒ 删除时连本行与等式一起收掉 |
| `app/agent.py` | legacy 应急腿（`import httpx` + 一处 `httpx.post` + 端点字面量 1；§9.1 Task 8 补正） |
| `app/conversation_agent.py` | **0/0**：`native_stream.py` 已退役 ⇒ 命中只在退役说明的散文里。留行是让「内联回来」那条变异第一眼被读到 |
| `app/identity/feishu_client.py` | 飞书开放平台 httpx 客户端，**不是 LLM 出口**（T2 移交 M-5）；按文件级例外，不用整目录跳过 |
| `app/config.py` | §12 `*_api_key` / `*_base_url` **字段声明**（配置面 ≠ 出口面：AST 属性读法天然不计，全文面按等式计入） |
| `app/llm/health.py` | `settings.openai_api_key` 一枚（legacy RAG 选择语义）+ 头注释散文里的历史 `httpx.get`；探针不自己发请求 |
| `app/knowledge_os.py` / `app/main.py` / `app/main_agent.py` | 展示面的 `settings.openai_api_key` 读法（provider 标签），无 httpx、无端点字面量 |

`app/llm/{errors,normalize,health}.py` 的 "httpx" 只出现在散文/异常类名清单里 ⇒ **AST 面天然免疫**；`errors.py`、`normalize.py` 在全部三层面**零命中**，`health.py` 的命中只有上面那一枚凭据读法 + 一行散文，已进表。

## 矩阵 19+1 缺项核对与补齐情况

| 项 | 结论 |
| --- | --- |
| #9 完整 SSE 事件序 | **不缺**（brief 预计有误）：`SseRoutePayloadTests::test_the_success_event_order_is_unchanged` 逐位钉 `status/message/status/status/token/token/trace/sources/done` + 第二条出口的 `start` 前缀序。 |
| #16 providers healthy 形状 | **不缺**：`SystemStatusLlmBlockTests::test_llm_block_is_the_legacy_probe_face_plus_the_aggregate` 断言 `{"ollama": {"healthy": True}}` 整块等式；`ProviderHealthBudgetTests::test_an_open_breaker_never_leaks_into_the_healthy_face` 挡 D4 渗透。 |
| #17 trace 三链齐备性 | **形状齐、口径按 §9.1 分工**：RAG 测试内闭合（`ModelRouteIntegrationTests`）、SSE/Agent 真落盘九键（`SseTraceIntegrationTests` / `AgentModelRouteTraceTests`）。本表第 17 行按链逐枚列 node-id，齐备性由 `MatrixDocumentClosureTests` 机器化。 |
| `unknown` 归零 SQL | **确实缺 → 已补**：`UnknownAttributionTests` 两枚（三档 profile 真失败账写进自建临时库后 `WHERE error_type='unknown'` = 0 且 `rows ≥ 3`；零候选请求不产行）。 |
| 全 `app/` 的 D6 模式集扫描 | **确实缺 → 已补**：新文件三层面等式。 |
| 业务入口不裸放 `ValueError` | **确实缺 → 已补**：7 枚（链上等式、except 内裸放 = ∅、类型可接住性、理由码越界构造期响、`reason_codes` 不许裸 str 字面量、三链 except 落点等式、D2 的 500 形状禁令）。 |
| 矩阵文档与套件的耦合 | **确实缺 → 已补**：`docs/MODEL_ROUTER_V23_MATRIX.md` + `MatrixDocumentClosureTests`（改名/删例/把 PENDING 写成 PASS 都红）。 |

### `PENDING_EXTERNAL` 完整列表（供 Task 11 验收文档抄）

| 行 | 条目 | 说明 |
| --- | --- | --- |
| C1 | OpenAI（gpt-4.1-mini）实连 | 本轮无云 key；出厂 `enabled` 由 D1 动态判定为 False |
| C2 | DeepSeek（deepseek-chat）实连 | 同上，注册表 `enabled=false` 占位 |
| C3 | Qwen（qwen-plus）实连 | 同上 |
| C4 | 云条目 tool call / 流式的协议级差异 | key 到位后新增 `LIVE-CLOUD-*` 用例即可，不改架构 |

`BLOCKED`（非 PENDING_EXTERNAL，另计）：**P0 REAL-LLM-FAILOVER-001**（归 Task 10，需宿主起服务 + 真 Ollama 且 ornith 未加载态）；**#12b 多轮回放**（Task 9 段 B 交付物）。矩阵 §1 的注册表前提由 `test_shipped_registry_file_is_what_the_matrix_claims` 钉住：清空 OS env 下 `external ∧ enabled = ∅`、可路由面只剩 `ollama`。

## §5 cwd 收口终态（两种 cwd 同数 = 918/0/973）

| 落点 | 根因 | 手法 |
| --- | --- | --- |
| `RouterSettingsTests::test_argless_settings_still_constructs_on_host_env` | 该例刻意用真 `Settings()`，而 `llm_registry_file` 默认是相对 `config/llm_registry.json` | 例内 chdir 到 `BACKEND_DIR`（方案①，轻，不动冻结默认值） |
| `WarmupGateTests`（飞书，2 例） | **V2.3 外溢**：Task 5 把 `llm.warmup()` 挂上 lifespan ⇒ 「真跑 lifespan」的用例继承了上面那枚相对默认（`RegistryError: LLM 注册表文件不可用`） | `setUp` 把 `settings.llm_registry_file` 指到绝对的出厂文件、`tearDown` 还原（与本文件既有 `_set_rules` 同手法） |
| `TypeSafeJudgmentTests`（TSV2，6 例） | **既有 dotenv 耦合**：`SettingsConfigDict(env_file=".env")` 是相对路径 ⇒ 从仓库根起读不到 `.env` ⇒ `typesafe_enabled=False` / `effective_typesafe_mode="off"` 早退分支。不是 V2.3、也不是注册表 | `setUp` 显式打进两枚前提（`typesafe_enabled=True`、`typesafe_mode="selective"`）。**正解在产品侧**（`env_file` 绝对化）⇒ 留给主 agent 裁，段 A 不动产品代码 |

## 变异表（8 发，`task9a_mutations.py`）

| 发 | 打点 | 期望 | 结果 |
| --- | --- | --- | --- |
| M1 | 新建 `app/egress_probe_tmp.py`：`import httpx` + 一次 `httpx.post` | RED | **KILLED**（7 failed / 26 passed）——AST 面 + 全文面 + 豁免互等三处同时红 |
| M2 | 豁免表放大一档（多列 `app/store.py`） | RED | **KILLED**（2 failed / 2 passed）——死行 + 互等两红 |
| M3a | 把 A-3 谓词退回「只认双引号」，并注入 `app/llm/probe_single_quote.py`（单引号 `selected_index`+`context_dropped`） | GREEN | **GREEN（刻意存活）**：证明收紧前确有免检面；这一发的「存活」就是 A-3 的收益证据 |
| M3b | 同一枚注入文件 + 收紧后的谓词 | RED | **KILLED**（1 failed） |
| M4 | 拆掉 chdir 钉，从仓库根跑 argless 那一枚 | RED | **KILLED**（1 failed）；还原后同一命令 **1 passed** |
| M5 | 矩阵文档里把一枚承载 node-id 改成不存在的方法名 | RED | **KILLED**（1 failed / 5 passed） |
| M6 | 代码面计数放大一枚（`httpx_verb` rag 2→3，破坏 `全文 == 代码 + 散文`） | RED | **KILLED**（1 failed / 1 passed / 7 subtests） |
| M7 | 豁免表少一档（删掉 `app/llm/provider.py` 那行） | RED | **KILLED**（4 failed / 28 passed） |

收尾核对：`app/llm/{fallback,normalize,usage,__init__}.py`、`app/{rag,agent,conversation_agent,agent_routes,security}.py`、`config/llm_registry.json`、`tests/conftest.py` 全部 **IDENTICAL**；注入的两个临时文件与其 `__pycache__` 残骸已删；五枚测试/文档文件行尾仍纯 LF。

## 我没有做的事（以及为什么）

1. **`normalize.py::openai_payload` 的多轮回放映射 + `OpenAIMultiTurnReplayTests`**（矩阵 #12b）：段 B 义务，本段一行代码都没碰 `app/llm/normalize.py`（sha1 佐证）。
2. **`agent.py` 的 N-3**（降级腿「本轮失败 ⇒ 丢前轮在手证据」+ 那一枚必钉用例）：段 B 义务；且它需要改产品代码，段 A 的硬约束禁止。
3. **§12 `llm_registry_file` 出厂默认改包相对**（A-4 的方案②）：动冻结默认值需主 agent 批准，未走。
4. **`app/config.py` 的 `env_file` 绝对化**（§5 第三行的正解）：产品代码，段 A 不动；已把测试侧的临时收口与根因写清，等裁决。
5. **未新增 `unknown_rate` 观测键**（T5 终裁：与 `success_rate` 共线）；矩阵文档里那句「不设观测键」也做成了断言（`unknown_rate` 在文档中至多出现一次）。
6. **未削弱任何既有断言**；`conftest.py` 护栏一字未改（sha1 佐证）；真实库只读复核 0/7/10。
7. **未做 git 写**、未起宿主服务、未跑前端 build、未做云真连（Task 10/11 的面）。

## 移交段 B / 终审

- 豁免表与三层等式表已在本文件上方**逐枚列全**，段 B 若新增/删除 `app/` 出口，改的就是这三张表 + `EXEMPTIONS`；`test_exemption_table_has_no_dead_rows` 会双向挡（多一档、少一档都红）。
- `MatrixDocumentClosureTests` 会把文档里每一枚 node-id 与套件对齐：段 B 补 #12b 时，把矩阵的 `12b` 行状态从 `BLOCKED` 改成 `GREEN` 并填入真实 node-id，否则该行不产证据。
- `UnknownAttributionTests` 的自建库手法（`CONVERSATION_DB_PATH` 指绝对临时路径）是段 B 写「非零 ⇒ 某链漏写 kind」类用例的模板；直写保护集会被 `conftest.py` 逐例判红。
- 若终审决定把 §5 第三行的根因修在产品侧（`env_file` 绝对化），则 `TypeSafeJudgmentTests.setUp` 里那两枚 `patch.object` 可以退回（它们是**加**上去的前提，不是替代断言）。
