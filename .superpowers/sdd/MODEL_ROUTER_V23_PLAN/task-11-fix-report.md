# Task 11 修复报告（终审 I-11-2 代码半段：`model_used` 报计划面 primary）

> 范围：`backend/app/rag.py`、`backend/app/main.py`、`backend/tests/test_model_router_v23_contract.py`
> 未动：`app/llm/*`、`app/conversation_agent.py`、`app/agent.py`、`app/security.py`、`config/*`、`docs/*`
> 容器 `rag-backend-1` 未重启/未重建；11434 未打；仓库零 git 写。

## 1. 病灶与修法

**病灶（终审已证，本报告的复现证据见 §3）**：`/api/query` 的 `model_used` 无条件读
`app/rag.py::current_model_name()`，而后者只跑 `plan()` 取**计划面 primary**（docstring 自陈
「不进 fallback」）。⇒ 任何发生 fallback 的请求，响应体模型名与账本
`llm_request_logs.model` 必然劈叉，违反 DESIGN §9 冻结句「响应 model 字段来自实际选中模型」。

**修法**（可变盒子，与 Task 8/9 的 `route_out` / `tool_time` 同一族）：

| # | 文件:位置 | 改动 |
| --- | --- | --- |
| 1 | `app/rag.py`（`_RAG_PROFILE` 之后） | 新增键名常量 `MODEL_USED_KEY = "model_used"`：写方（rag）与读方（main）共读一枚常量，杜绝「盒子写了、调用方查另一个词」的静默失配 |
| 2 | `app/rag.py::generate_answer` | 签名 → `generate_answer(question, rows, *, model_out: dict \| None = None)`（关键字 + 默认 None ⇒ 既有位置参调用点与既有测试逐字不破）；docstring 写明「只有 router 路真拿到响应才写键；零候选/全链失败/legacy **不写这个键**」 |
| 3 | `app/rag.py::_answer_via_router(messages, model_out=None)` | 成功返回前写 `model_out[MODEL_USED_KEY] = result.response.model`（M2 生效模型名，与 usage 落库的 `model` 列同源，见 `normalize.parse_*` 的 `str(data.get("model") or model)`）；空串**不写**；异常从 `llm.complete()` 抛出时根本到不了这一行 ⇒ 失败路天然不写键 |
| 4 | `app/main.py:41` | import 增 `MODEL_USED_KEY` |
| 5 | `app/main.py`（`/api/query`） | 盒子传入；`"model_used": model_out.get(MODEL_USED_KEY) or current_model_name()` |
| 6 | `app/main.py`（`/api/query/stream`） | 盒子传入；`done` 事件按「有执行面事实才挂键」，与既有 `timings` 同一姿势（见 §2 的契约影响声明） |
| 7 | `app/rag.py::current_model_name` | **保留**（仍是 `/api/health`、`/api/system/status`、`main_agent.legacy_rag_model` 的合法计划面读数）。只改 docstring 里那句已经不成立的断言（原文：「所以 `/api/query` 的 `model_used`、`/api/health` 与 `/api/system/status` 的 `llm_model` 指向真正会答这一行的那个名字」），改成「`/api/query` 只在没发生 fallback 时与它一致」。**代码路径零改动** |

## 2. 契约影响声明（唯一一处键集合变化）

- `/api/query`（非流式）：**键名与键集合一字未改**（`{answer, query, sources, num_sources, model_used}`，新测试里已钉），只有 `model_used` 的**取值口径**变得更真：fallback 时 = 实际答话的模型（= 账本 `model` 列），零候选/全链失败/legacy 时 = `current_model_name()`（与迁移前逐字相同）。
- `/api/query/stream`：`done` 事件**新增**一枚可选键 `model_used`（此前这条腿的响应里根本没有模型字段，所以今天没有任何「说谎的 model 字段」）。写法是「盒子有事实才挂键」：legacy 路与失败路 ⇒ 键不出现，不写空串、也不拿计划面名字冒充。
  - 备案理由：终审要求「两个调用点都传盒子」。若只传不读，那枚盒子在流式腿就是死代码；挂到 `done` 上是把它接进既有事实流。该键**非破坏性**（新增可选键），全仓测试与前端都无一处读 SSE `done` 的 `model_used`（`grep frontend/src` 只有 `lib/conversations.ts:39` 的会话消息 `model_used`，那是 `conversation_routes` 的响应面，与本次改动无关；`/api/query/stream` 在前端零调用）。如果主 agent 裁定「本版一个字都不许多」，删掉 §2 那三行（`answered_by = ...` 到 `done_payload[...] = ...`）
  即可，其余改动不受影响——**同时必须删掉 §3 表里那两枚 stream 用例**（它们钉的就是这枚新键），
  那样终态回到 958。当前选择是「键 + 测试 + 变异 M6 一起交」，因为无测试的响应面字段就是下一个劈叉。
- `app/llm/*` 零改动 ⇒ 生效模型名口径没有第二套：仍然是 `provider.effective_model_name` 一处。

## 3. 测试与红→绿

新增一枚测试类 `RagModelFaceTests(_RagMigrationFixture)`（`tests/test_model_router_v23_contract.py`，
插在 `# 3b. 模型面` 段、`RagLedgerTests` 之前，`:4600`）：10 枚用例 + 3 枚真 HTTP 面助手
（`authed_client` / `_search_leg_stubbed` / `http_query_body` / `http_stream_done_payload`）。
**先落测试、后改代码**（前 8 枚），所以有真红证据；后 2 枚流式腿用例是随 §2 那枚新键一起补的，
强度由 M6 变异证明。

| 用例 | 钉什么 | 改代码前 | 改代码后 |
| --- | --- | --- | --- |
| `test_the_box_carries_the_model_that_actually_answered` | primary 真 500、第二候选真成功 ⇒ 盒子 `{"model_used": "phi3:mini"}`，且不含计划面名 | RED（`TypeError: unexpected keyword 'model_out'`） | GREEN |
| `test_the_http_face_reports_the_fallback_model_not_the_planned_primary` | `/api/query` 响应体 `model_used == "phi3:mini"` **且 == 账本 `model` 列**；`assertNotEqual(RAG_LOCAL_MODEL, ...)`；响应键集合不变 | RED：`AssertionError: 'phi3:mini' != 'ornith-1.5:9b-text'`（**这就是 I-11-2 的可复现证据**） | GREEN |
| `test_a_non_fallback_answer_reports_the_same_name_as_before` | 对照组：无 fallback 时盒子值 == `current_model_name()`（证明不是把字段换成猜值） | RED | GREEN |
| `test_no_capable_model_writes_no_box_and_falls_back_to_the_plan_face` | 零候选 ⇒ **一个键都不许多写**（盒子预置脏值必须原样保留）+ 兜底文案（`LLM_UNAVAILABLE_COPY` / `模型连接错误：NoCapableModelError`）逐字不变 + HTTP 面 `model_used == current_model_name()` 且非空串 | RED | GREEN |
| `test_every_candidate_failing_writes_no_box` | 全链失败（`AllCandidatesFailedError`）⇒ 不写键 | RED | GREEN |
| `test_a_provider_echoing_an_empty_model_writes_no_box` | provider 回显空 + 本地 target 空 ⇒ **不写空串** | RED | GREEN |
| `test_matrix_18_legacy_model_used_is_the_pre_migration_name_verbatim` | legacy（有云 key）⇒ `model_used == settings.openai_model == _legacy_model_name()`，**不等于**注册表 primary；盒子不写；账本零行 | RED | GREEN |
| `test_matrix_18_legacy_model_used_without_a_cloud_key_is_the_local_name` | legacy（无云 key）⇒ `model_used == settings.ollama_model`，与迁移前逐字相同 | RED | GREEN |
| `test_the_stream_leg_reports_the_answered_model_in_the_done_event` | `/api/query/stream` 的 `done` 事件：fallback 时带 `model_used == "phi3:mini"`，其余键逐字不变（钉本次**新增**的可选键） | 未参与首轮红（写代码后补）⇒ 由 M6 变异证明其强度 | GREEN |
| `test_the_stream_leg_adds_no_key_when_nothing_answered` | 零候选 ⇒ `done` 回到迁移前键集合 `{"finish_reason"}`，不写空串不写计划面名 | 同上 | GREEN |

定向门闸：`python -m pytest tests/test_model_router_v23_contract.py tests/test_llm_usage_contract.py -q`
⇒ **492 passed / 0 failed / 393 subtests**（含新 10 枚）。

全套件：见 §5（终态数字）。

## 4. 变异台（6 发，字节安全 + 发内还原 + sha1 核对）

脚本：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t11_mutations.py`（每发只改 1 处、命中数必须 == 1，
跑完定向用例立刻从内存基线还原并核对 sha1）。**6/6 killed，存活 0 发。**

| 发 | 变异（文件 / 内容） | 定向用例 | 结果 |
| --- | --- | --- | --- |
| M1 | `rag.py`：删掉 `_answer_via_router` 里的盒子写入（成功路不再报实际名） | `test_the_box_carries_...`、`test_the_http_face_reports_the_fallback_model_...` | **KILLED**（2 failed / 2） |
| M2 | `rag.py`：让**失败路也写盒子**（`except (LLMError, AllCandidatesFailedError, NoCapableModelError)` 里写空串） | `test_no_capable_model_writes_no_box_...`、`test_every_candidate_failing_writes_no_box` | **KILLED**（2 failed / 2）——「零候选用例必须红」兑现 |
| M3 | `rag.py`：legacy（无云 key 那条 Ollama 分支）**写死「实际名」** `settings.ollama_model` | 两枚 `test_matrix_18_legacy_model_used_...` | **KILLED**（1 failed / 2）——红的是 legacy 用例；HTTP 面看不出来（同值），是盒子面的 `assertEqual({}, box)` 把它抓住的 |
| M4 | `main.py`：去掉 `or current_model_name()` 回退 | 零候选两枚 | **KILLED**（1 failed / 2）——`model_used` 变 None ⇒ 「兜底位不许是空串」那枚红 |
| M5 | `main.py`：调用方退回**原病灶**（无条件 `current_model_name()`） | fallback 两枚 | **KILLED**（1 failed / 2）——即 I-11-2 的劈叉被重新引入必被抓 |
| M6 | `main.py`：流式腿不挂 `done.model_used` | 两枚 stream 用例 | **KILLED**（1 failed / 2）——新增的响应键有测试钉着，不是裸契约 |

还原核对：`FINAL rag.py sha1=ccadbcc2...=BASE`、`FINAL main.py sha1=2db326f0...=BASE`，
CRLF 计数与 LF 计数相等（316/316、770/770）⇒ 行尾未翻。

## 5. 全套件（终态）

| 命令 | 结果 |
| --- | --- |
| `cd backend && python -m pytest tests -q`（终态，变异还原之后） | **960 passed / 0 failed / 992 subtests passed in 110.46s** |
| `python -m pytest tests/test_model_router_v23_contract.py tests/test_llm_usage_contract.py -q`（定向门闸，终态） | **492 passed / 0 failed / 393 subtests passed in 40.11s** |
| `RagModelFaceTests` 单类（10 枚） | 改代码前 **8 红**（真红证据见 §3），改代码后 **10 passed** |
| 仓库根 `python -m pytest backend/tests -q` | **958 passed / 0 failed / 992 subtests**（与 backend 目录跑同数；该次跑在插入 stream 两枚之前，插入后的 backend 目录跑即上行的 960） |

基线 950 ⇒ 终态 960 = 950 + 本次新增 10 枚，**净增不减**；`subtests` 992 与基线逐字相同（没动任何既有 subTest）。

> 日志留痕口径：`t11_fullsuite_root.log` = 仓库根同数验证快照（958，插入流式腿两枚用例**之前**那一轮）。
> **终态以本表首行 960 为准**（全部变异还原后、`cd backend` 跑的，输出直接打印未落盘；上面那行 110.46s 即其原文）。
> 定向 492 那一轮同理（打印为准，不另存日志）。

### `model_used` 三口径实测值（全部由上表用例断言并通过）

| 口径 | `/api/query` 的 `model_used` | 账本 `llm_request_logs.model` | 来源 |
| --- | --- | --- | --- |
| **fallback**（primary 500 → 第二候选真成功） | `phi3:mini` | `phi3:mini` | **同名**（修前是 `ornith-1.5:9b-text` vs `phi3:mini`，劈叉即 §3 那枚真红） |
| **零候选**（`NoCapableModelError`，provider 全不健康） | `ornith-1.5:9b-text` == `current_model_name()` == `_legacy_model_name()`，非空串 | 不产生新行（库里只有对照组的行） | 盒子不写键 ⇒ 回退展示面；兜底文案 `已完成检索，但当前 LLM 服务不可用…` + `模型连接错误：NoCapableModelError` 逐字不变 |
| **legacy**（`LLM_ROUTER_ENABLED=false`，有云 key） | `gpt-4.1-mini` == `settings.openai_model` == `_legacy_model_name()` | 零行（legacy 不经路由） | 与迁移前逐字一致；**注意**：注册表 primary 是 `ornith-1.5:9b-text`，两值刻意不同名，所以「legacy 路偷读路由面名字」一定红 |
| **legacy**（`LLM_ROUTER_ENABLED=false`，无云 key） | `ornith-1.5:9b-text` == `settings.ollama_model` | 零行 | 同上，另一支 |
| （附加）全链失败 / provider 空回显 | 回退 `current_model_name()` | 失败账一行 | 盒子**不写键**，含空串 |


## 6. 既有 `model_used` 断言清单（逐条核对：原来挡什么 → 现在挡什么）

**结论：本次没有改动、没有放宽任何一条既有断言**（`git diff` 面 = 只新增一个测试类 + 三处实现改动）。
逐条核对如下：

| 位置（**插入后的现行号**） | 原来挡什么 | 这次改动后挡什么（是否受影响） |
| --- | --- | --- |
| `tests/test_model_router_v23_contract.py:4593`（`RagFailureFaceTests::test_the_http_face_still_returns_200_when_no_candidate_is_capable`，`assertEqual(RAG_LOCAL_MODEL, body["model_used"])`） | 零候选时 `/api/query` 仍报展示面兜底名，且 HTTP 面不塌成 5xx | **不受影响、原样绿**：零候选 ⇒ 盒子不写键 ⇒ 仍走 `current_model_name()`。口径与新增的 `test_no_capable_model_...`（`:4698`）一致（同值同因），双保险 |
| `:4893-4975`（`RagDisplayedModelNameTests` 一族，直接调 `rag_module.current_model_name()`） | 展示面解析：计划 primary + D1 别名 + 三条硬约束（不出网 / 不抛异常 / 不进 fallback） | **完全不受影响**：该函数代码路径零改动（只改了 docstring） |
| `:5901-5915`、`:6311`、`:6883-6892`、`:7873`、`:7886`（SSE 会话腿与 agent 腿的 `model_used`） | 那两条链的 `model_used` == selected 生效名 == 账本 `model` 列（含 D1 别名）；legacy 腿回落 `settings.ollama_model` | **不受影响**：那两条腿各自读 `route_outcome.response.model` / 账本，不经 `rag.generate_answer`。它们正是 §9 那句话在另两条链上的同款实现——本项把 RAG 腿补齐成同一口径 |
| `tests/test_typesafe_api_runtime.py:91/119/148` | `/api/query` 响应**键集合**恰好 `{answer, query, sources, num_sources, model_used}`；`generate_answer` 与 `current_model_name` 都是替身 | **不受影响**：`generate_answer` 被 mock ⇒ 新关键字参无人调用 ⇒ 盒子恒空 ⇒ 回退 `current_model_name()` == "test-model"。键集合断言继续挡「顺手加键」。（新增的可选键只出现在 SSE `done`，与这条断言不同端点） |
| `tests/test_llm_usage_contract.py:1327`（`knowledge_os` 里 mock `current_model_name`） | `/api/system/status` 的 `llm_model` 读数 | **不受影响**：`current_model_name` 保留且未改语义 |
| `tests/test_real_llm_failover_acceptance.py:698`（`model_used_field` 只**记录**不**断言**） | P0 证据采集字段 | **不受影响**：该用例 mock `app.main.generate_answer` ⇒ 盒子恒空。注：P0 真机看到的「响应 `ornith-1.5:9b-text` 而账本 `phi3:mini`」在这版之后会**同名**（真机复验归主 agent，本任务不打 11434） |
| `:5406` `RagLegacyEgressInventoryTests`（`app/rag.py` 的 D6 豁免命中面静态扫描：httpx 3 处 / 端点路径字面量 2 处） | 「legacy 豁免清单不许悄悄变长」——本文件的出口数量是一枚钉 | **不受影响、原样绿**：本次在 `rag.py` 里只加了一个关键字参、一处盒子写入与注释，**没有新增任何 httpx 调用或端点字面量**；全套件绿即证明计数没漂（这也是我没往 `rag.py` 里写 `httpx.post` 相关新词的原因） |

## 7. 冻结件与行尾 sha1 前后表

**改动的只有三枚文件**（补丁脚本 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/t11_fix_patch.py` 与
`t11_insert_tests.py` 各自只 open 这三枚路径；变异台另有内存基线还原，见 §4 末行）：

| 文件 | sha1 改前 | sha1 改后 | 行尾（改前 → 改后） |
| --- | --- | --- | --- |
| `backend/app/rag.py` | `a5a638716947c462585be058affbd0f2b3c7836a` | `ccadbcc2c082f26d957d6ac7609917d8cbfca27f` | 全 CRLF：280 → **316**（`CR == LF` ⇒ 一行都没翻） |
| `backend/app/main.py` | `bc0281dcfc42f26bf95ce1f41776bfaa113df8bd` | `2db326f08fdd665747e1ff086b3218d12015b8d7` | 全 CRLF：757 → **770**（同上） |
| `backend/tests/test_model_router_v23_contract.py` | `5dcfca837e10733c133ed6c1a4d1250928b98830` | `d7e0554acbad9c920eb292868fc6322eff73a511` | 纯 LF：7791 → **8026**（`CR=0` 保持） |

**冻结件（本次零写入；sha1 为终态值，mtime 全部早于本会话，可作旁证）**：

| 文件 | sha1（终态） | 行尾 | mtime |
| --- | --- | --- | --- |
| `app/llm/__init__.py` | `c29e3c393f8767d6c88516a3b09da1d3f2527577` | 纯 LF 448 | 09-24 02:35 |
| `app/llm/provider.py` | `9d34721f89f04110540a0f6b2bf2931d8782e711` | 纯 LF 291 | 09-23 20:31 |
| `app/llm/normalize.py` | `41597af45085a6e2d5b7aa152b4d4e0e9ebe16b0` | 纯 LF 435 | 09-24 20:16 |
| `app/llm/fallback.py` | `008d8213bc055ddd4fbcbc7e8eae1c044790d8cc` | 纯 LF 943 | 09-24 08:25 |
| `app/llm/usage.py` | `8a8f5b0cff288d49dfd950d8e7505c1123876e9c` | 全 CRLF 1066 | 09-24 05:08 |
| `app/llm/router.py` | `2742871ed6eef48320918da7b5c1991a0cdd40fc` | 全 CRLF 313 | 09-23 22:21 |
| `app/llm/{classifier,errors,health,models,registry}.py` | `81d43043…` / `fca8d9da…` / `f529dc5f…` / `586dfe03…` / `60b70611…` | 纯 LF | 09-23 |
| `app/conversation_agent.py` | `0ffcc353eb59952ebc07c8474d5fc247d8efa5c0` | 全 CRLF 601 | 09-24 09:54 |
| `app/agent.py` | `bb3606778b63b111c42f0823340cdb4e5c4137e8` | 全 CRLF 1048 | 09-24 20:40 |
| `app/security.py` | `d36b387aac6ede8b40534aff73b11e0db3ed4ff4` | 纯 LF 287 | 09-24 02:38 |
| `config/llm_registry.json` | `3e652e9cf4963aa0ef6def92bcd63576215fc75c` | 纯 LF 60 | 09-23 18:46 |
| `tests/test_llm_usage_contract.py` | `7f3bd53166502320144781a83a7b5ad0c3e48ae6`（**与改前逐字相同**） | 纯 LF 2089 | 09-24 20:37 |
| `tests/test_typesafe_api_runtime.py` | `e2f58d84bde4c2832bea2c346b4d5c6db8177089`（未改） | 纯 LF 288 | 09-23 06:55 |
| `tests/conftest.py`（账本护栏） | `73d1060de465e020b376e8ccf68c612ab9b57213`（未改） | 纯 LF 404 | 09-24 10:18 |

> 备注：任务书写「`app/llm/*` 纯 LF」——实测 `app/llm/usage.py` 与 `app/llm/router.py` 是**全 CRLF**，
> 其余 `app/llm/*.py` 才是纯 LF。两者本次都没被写过，故只作现场更正记录。

## 8. 我没做的事

- 没动 `app/llm/*`（生效模型名口径仍是唯一一处）、没动 `conversation_agent.py` / `agent.py` / `security.py` / `config/*` / `docs/*`。
- 没改 `current_model_name()` 的行为（只改了 docstring 里那句因本次修复而失实的断言）。
- 没有重跑真机 P0、没有重启/重建容器、没有打 11434（新镜像里的 `model_used` 复验归主 agent）。
- 没有做 git 任何写操作（无 add/commit/stash/checkout）。
- 没有删除 legacy 应急路（D6 豁免段：那要等 legacy 一起删，归后续版本）。
- 没有新增响应键到 `/api/query`（非流式）；SSE `done` 的那枚可选键已在 §2 单独报备，可按裁定一键回退。
