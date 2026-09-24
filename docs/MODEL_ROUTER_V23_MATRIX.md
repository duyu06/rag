# Model Router V2.3 —— §10 验收矩阵逐项映射表（Task 9 段 A 收口 + 段 B 两件产品修复）

日期：2026-09-24 · 规格：`MODEL_ROUTER_V23_DESIGN.md` §10（19+1 冻结）· 计划：`MODEL_ROUTER_V23_PLAN.md` `### Task 9`
段 A = D6 扫描 + 本表 + cwd 收口；**段 B** = I-4 的 `openai_payload` 多轮回放映射（`#12b` 由 `BLOCKED` 转 `GREEN`）
+ N-3 的降级腿在手证据门（新增 `N-3` 行）。
本表是**文档与测试套件的耦合件**（双向闸）：`backend/tests/test_llm_egress_guard.py::MatrixDocumentClosureTests`
会在每次跑套件时逐行核四件事——① 行号 1–19 齐全（19+1 里的「+1」= `P0` 行）；② `GREEN` 行必须给出
至少一枚 node-id，且该 node-id 指向的**文件/类/方法真实存在**（按 AST 现算，不起 pytest）；③ 状态值域只有
`GREEN / PENDING_EXTERNAL / BLOCKED` 三枚；④ **反向**：`test_llm_egress_guard.py` 的每一枚测试类
（`D6AstFaceTests` / `D6FullTextFieldTests` / `ExemptionTableTests` / `NoBareValueErrorOnTheChainTests` /
`UnknownAttributionTests` / `MatrixDocumentClosureTests` / `ScanningHelpersAreAllLiveTests`）都必须被本表
点名至少一次——只有正向闸时「套件里新增一枚不挂表的例」永远绿（Task 9 评审 Minor 3）。
改名、删例、把无 key 环境下的云端项写成 PASS，都会让那一枚用例红。

诚实口径（本项目冻结）：**没有云 key 的环境里，云端实连项只能是 `PENDING_EXTERNAL`**——既不是 PASS 也不是 FAIL。
`BLOCKED` 只用于「今天做不了、但障碍在代码之外」的行（真机 P0）。段 A 时代唯一的那枚代码内缺陷
（`#12b` 多轮回放）已由段 B 修掉，本表不再有任何 `BLOCKED` 的协议缺陷行。

## 1. 19+1 全表

| # | 用例 | 方法 | 预期 | 承载测试 | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | OpenAI-compat 成功 | httpx MockTransport（假 host） | PASS | `test_model_router_v23_contract.py::ProviderCompleteTests::test_openai_complete_sends_bearer_and_reads_usage`、`test_model_router_v23_contract.py::OpenAIPayloadShapeTests::test_stream_payload_asks_for_the_final_usage_block` | GREEN |
| 2 | Ollama 成功 | 同上 | PASS | `test_model_router_v23_contract.py::ProviderCompleteTests::test_ollama_complete_request_line_is_single_egress`、`test_model_router_v23_contract.py::ResponseParsingTests::test_ollama_complete_response_reads_message_and_eval_counts` | GREEN |
| 3 | 429 → retry | 同上 | 重试后成功 | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_3_429_retries_the_same_model_then_succeeds`、`test_model_router_v23_contract.py::RetryBudgetTests::test_retry_count_follows_the_setting_exactly` | GREEN |
| 4 | 500 → fallback | 同上 | 第二候选成功，`fallback_index=1` | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_4_500_model_load_failure_falls_back_to_second_candidate` | GREEN |
| 5 | timeout → fallback | 同上 | 同上且 reason 含 `FALLBACK_AFTER_TIMEOUT` | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_5_timeout_falls_back_and_marks_fallback_after_timeout`、`test_model_router_v23_contract.py::RetryBudgetTests::test_retries_share_the_budget_and_each_gets_a_smaller_timeout` | GREEN |
| 6 | 400 | 同上 | 不重试当前；允许 fallback | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_6_400_does_not_retry_current_but_allows_fallback` | GREEN |
| 7 | 401 | 同上 | 不重试当前 provider；标 `PROVIDER_CONFIG_FAILED` | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_7_401_marks_provider_config_failed_and_skips_same_provider` | GREEN |
| 8 | malformed JSON | 同上 | 归类正确（非 retryable 崩溃） | `test_model_router_v23_contract.py::FallbackTransportMatrixTests::test_matrix_8_malformed_json_is_classified_not_crashing`、`test_model_router_v23_contract.py::ErrorClassificationTests::test_malformed_json_is_hard_not_a_crash` | GREEN |
| 9 | stream 成功 | 同上 | **SSE 序完整** | `test_model_router_v23_contract.py::SseStreamContractTests::test_the_stream_leg_forwards_every_content_chunk_in_order`、`test_model_router_v23_contract.py::SseRoutePayloadTests::test_the_success_event_order_is_unchanged`、`test_model_router_v23_contract.py::SseRoutePayloadTests::test_the_second_sse_egress_lands_the_same_d5_face_and_keeps_its_success_order` | GREEN |
| 10 | pre-token 流失败 | 同上 | 静默换模型，用户无感 | `test_model_router_v23_contract.py::StreamCommitTests::test_matrix_10_pre_commit_failure_switches_model_invisibly`、`test_model_router_v23_contract.py::SseCommitMatrixTests::test_matrix_10_pre_commit_failure_switches_model_and_the_user_sees_one_answer` | GREEN |
| 11 | post-token 流失败 | 同上 | 不切模型，`error`+`done`+`stream_committed` | `test_model_router_v23_contract.py::StreamCommitTests::test_matrix_11_post_commit_failure_never_switches_model`、`test_model_router_v23_contract.py::SseRoutePayloadTests::test_post_commit_interruption_emits_error_then_done_with_two_new_payload_keys`、`test_model_router_v23_contract.py::SseRoutePayloadTests::test_a_real_truncated_upstream_lands_error_plus_done_on_the_wire` | GREEN |
| 12 | tool call OpenAI | 同上 | `ToolCall` 标准化 | `test_model_router_v23_contract.py::ToolCallStandardisationTests::test_openai_string_arguments_are_parsed_into_dict`、`test_model_router_v23_contract.py::AgentToolCallStandardisationTests::test_message_from_response_reads_only_the_standardised_tool_calls` | GREEN |
| 12b | tool call OpenAI：**多轮回放**（第二轮把 `assistant.tool_calls[].function.arguments` 发成 JSON 字符串、工具回执带 `tool_call_id`） | MockTransport 逐字节看第二轮出口体（真 `run_agent` 工具轮 + 云条目 + 假 key） | 第二轮出口合规（段 B 已落地：映射坐在 `openai_payload` 出口前，`agent.py` 与 `ToolCall` 一字不动） | `test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_the_second_round_sends_function_arguments_as_a_json_string`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_the_second_round_tool_receipt_carries_the_matching_tool_call_id`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_two_calls_with_different_names_in_one_round_pair_by_name`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_two_calls_with_the_same_name_in_one_round_pair_in_order`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_the_mapping_prefers_the_matching_tool_name_over_position`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_a_call_without_an_id_is_never_paired`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_the_egress_mapping_is_idempotent_and_never_mutates_the_request` | GREEN |
| 13 | tool call Ollama | 同上 | `ToolCall` 标准化；**且 #12b 的映射不许牵连这条腿** | `test_model_router_v23_contract.py::ToolCallStandardisationTests::test_ollama_object_arguments_and_absent_id_are_normalised`、`test_model_router_v23_contract.py::AgentToolCallStandardisationTests::test_string_arguments_reach_the_tool_as_a_dict`、`test_model_router_v23_contract.py::OpenAIMultiTurnReplayTests::test_the_ollama_leg_still_replays_the_dict_arguments` | GREEN |
| N-3 | （Task 8 修复轮复审移交项，非 §10 冻结行）agent 降级腿：前轮已有授权证据 + 本轮 `enterprise_search` 失败 ⇒ 不许用失败文案糊掉在手证据，`num_sources` 与文案必须同源；`DENIED` 支仍是零外呼 + 硬文案 | `_AgentMigrationFixture` + 工具替身（前轮成功 / 本轮抛 `ToolExecutionError`） | 证据在手即继续合成，并把失败事实留在 trace 上 | `test_model_router_v23_contract.py::AgentNoCapableFastPathTests::test_a_failed_current_round_answers_from_the_evidence_already_in_hand`、`test_model_router_v23_contract.py::AgentNoCapableFastPathTests::test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand` | GREEN |
| 14 | Router 延迟 | 本地 benchmark | P95 ≤ 10ms | `test_model_router_v23_contract.py::RouterBenchmarkTests::test_p95_under_budget_on_a_sixty_candidate_registry`、`test_model_router_v23_contract.py::RouterBenchmarkTests::test_p95_under_budget_on_the_shipped_five_entry_registry` | GREEN |
| 15 | usage 落库 | SQLite 断言 | 19 列全、无禁存项、失败行必带 kind | `test_llm_usage_contract.py::UsageSchemaTests::test_table_has_the_frozen_nineteen_columns_in_order`、`test_llm_usage_contract.py::ForbiddenContentTests::test_long_chinese_prompt_never_survives_any_column`、`test_llm_egress_guard.py::UnknownAttributionTests::test_three_profile_failure_exits_land_zero_unknown_rows` | GREEN |
| 16 | status 聚合 | API 测试（TestClient） | `llm` 块形状 + `providers:{name:{healthy}}` | `test_llm_usage_contract.py::SystemStatusLlmBlockTests::test_llm_block_is_the_legacy_probe_face_plus_the_aggregate`、`test_llm_usage_contract.py::LlmStatusWhitelistTests::test_field_set_is_exactly_the_whitelist`、`test_llm_usage_contract.py::ProviderHealthBudgetTests::test_an_open_breaker_never_leaks_into_the_healthy_face`、`test_model_router_v23_contract.py::ProviderHealthViewTests::test_view_shape_is_provider_keyed_healthy_flag` | GREEN |
| 17 | trace route 解释 | 集成（三链各一枚） | `model_route` 九键完整 | RAG（测试内闭合）：`test_model_router_v23_contract.py::ModelRouteIntegrationTests::test_a_real_llm_complete_lands_a_nine_key_model_route`；SSE（真落盘九键）：`test_model_router_v23_contract.py::SseTraceIntegrationTests::test_a_real_streamed_answer_lands_a_nine_key_model_route_on_disk`；Agent（真落盘九键）：`test_model_router_v23_contract.py::AgentModelRouteTraceTests::test_the_route_lands_nine_keys_before_save_trace` | GREEN |
| 18 | legacy 回退 | `LLM_ROUTER_ENABLED=false` | 三链原行为；**对话链仅非流式腿有 legacy 形态，流式腿以「报文与退役模块逐字等价」为准（§9.1）** | `test_model_router_v23_contract.py::RagRouterMigrationTests::test_the_rag_chain_goes_through_the_router_exactly_once`、`test_model_router_v23_contract.py::SseBufferedAndLegacyTests::test_matrix_18_the_legacy_branch_still_calls_agent_ollama_chat`、`test_model_router_v23_contract.py::SseBufferedAndLegacyTests::test_the_stream_leg_has_no_legacy_form_left_to_preserve`、`test_model_router_v23_contract.py::AgentLegacyBranchTests::test_matrix_18_the_legacy_payload_is_untouched_byte_for_byte` | GREEN |
| 19 | 单一出口静态扫描 | 契约测试（本文件） | provider.py 外零命中（等式钉） | `test_llm_egress_guard.py::D6AstFaceTests::test_httpx_import_sites_are_exactly_the_equalled_four`、`test_llm_egress_guard.py::D6AstFaceTests::test_httpx_egress_calls_are_the_provider_plus_two_legacy_legs_plus_feishu`、`test_llm_egress_guard.py::D6FullTextFieldTests::test_fulltext_hits_are_equalled_per_pattern`、`test_llm_egress_guard.py::D6FullTextFieldTests::test_fulltext_face_equals_code_face_plus_prose`、`test_llm_egress_guard.py::ExemptionTableTests::test_exemption_table_has_no_dead_rows`、`test_model_router_v23_contract.py::SingleEgressStructureTests::test_endpoint_literals_are_absent_from_non_provider_files_in_full_text` | GREEN |
| P0 | **REAL-LLM-FAILOVER-001**：primary=ornith-1.5:9b-text 真实加载失败 → fallback=phi3:mini 真实成功 | 本机 Ollama（宿主起服务，非 mock） | §10 十字全绿 | 今天的半段（假传输等价物）：`test_model_router_v23_contract.py::ProviderCompleteTests::test_load_failure_500_is_model_unavailable_for_the_real_failover_case`、`test_model_router_v23_contract.py::ErrorClassificationTests::test_model_unavailable_body_markers`、`test_model_router_v23_contract.py::ShippedRegistryRoutingTests::test_chat_plan_prefers_the_local_primary_and_keeps_phi3_as_fallback`；**真机半段（Task 10 段 A 落地，默认不被收集，见 §4.5）**：`test_real_llm_failover_acceptance.py::RealLlmFailover001Tests::test_real_llm_failover_001_ten_assertions`；**反造假闸（默认可收集）**：`test_real_llm_failover_gate.py::P0CarrierHasNoSkipBranchTests::test_carrier_source_has_zero_skip_family_tokens`；**2026-09-24 真机证据**：`task10/real-llm-failover-001.json`（primary `ornith-1.5:9b-text` 真失败 status=500＋`model_unavailable`＋41596ms → fallback `phi3:mini` 真成功 status=200＋20033ms；临时账本 1 行零 canary、仓库真库 0 行、trace 1 行） | GREEN |
| C1 | OpenAI（gpt-4.1-mini）实连 | 真 key + 真 HTTPS | 待定 | 无（本轮无云 key） | PENDING_EXTERNAL |
| C2 | DeepSeek（deepseek-chat）实连 | 真 key + 真 HTTPS | 待定 | 无（本轮无云 key；出厂 `enabled=false` 占位） | PENDING_EXTERNAL |
| C3 | Qwen（qwen-plus）实连 | 真 key + 真 HTTPS | 待定 | 无（本轮无云 key；出厂 `enabled=false` 占位） | PENDING_EXTERNAL |
| C4 | 云条目 tool call / 流式的协议级差异 | 真 key 后新增 `LIVE-CLOUD-*` 用例 | 不改架构 | 无 | PENDING_EXTERNAL |

## 2. 两枚必须被读到的口径（各有承载用例，不许只写在文档里）

1. **`requests_5m` 不含零候选请求**（Task 5 裁定：零候选不产行）。承载：
   `test_llm_egress_guard.py::UnknownAttributionTests::test_a_zero_candidate_request_writes_no_row_at_all`
   与 `test_llm_usage_contract.py::ClientAbortTests::test_no_capable_model_writes_no_row_and_stays_out_of_the_denominator`、
   `test_model_router_v23_contract.py::SseCommitMatrixTests::test_a_zero_candidate_plan_writes_no_row_at_all`。
2. **`unknown` 的归因出口 = 库查询，不设观测键**：V2.3 **不加** `unknown_rate`（它与 `success_rate` 完全共线，
   信息增量 0，代价是第 14 枚白名单键 + 再一轮 §8.1 回写）。验收 SQL 是
   `SELECT count(*) FROM llm_request_logs WHERE error_type='unknown'`，在全部 mock 用例跑完后**应为 0**；
   非 0 ⇒ 某条链漏写 `kind`，属**实现缺陷**而非样本。承载：
   `test_llm_egress_guard.py::UnknownAttributionTests`（三档 profile 各写真失败账之后仍归零）。
   为什么不是「直接读会话库」：`backend/tests/conftest.py` 的护栏会把**任何**写进保护集的行逐例判红，
   所以整套件的正常终态是「会话库恒 0 行」——读它等于空跑（虚假的绿），故本用例自建临时库。

## 3. 段 A 的缺项核对（brief 预计缺三枚，实测结论如下）

| 预计缺项 | 实测结论 |
| --- | --- |
| #9 完整 SSE 事件序 | **不缺**：`SseRoutePayloadTests::test_the_success_event_order_is_unchanged` 逐位钉 `status/message/status/status/token/token/trace/sources/done`，另一枚钉第二条出口的 `start` 前缀序。 |
| #16 providers healthy 形状 | **不缺**：`SystemStatusLlmBlockTests::test_llm_block_is_the_legacy_probe_face_plus_the_aggregate` 断言 `{"ollama": {"healthy": True}}` 整块等式，且 `ProviderHealthBudgetTests::test_an_open_breaker_never_leaks_into_the_healthy_face` 挡住 D4 渗透。 |
| #17 trace 断言的三链齐备性 | **形状齐、口径不齐**：RAG 在测试内闭合（`ModelRouteIntegrationTests`，本链无 trace 对象），SSE 与 Agent **真落盘**九键（`SseTraceIntegrationTests` / `AgentModelRouteTraceTests`）——这正是 §9.1 与 Task 6 裁定要求的分工，本表第 17 行按链逐枚列 node-id 即为「齐备性」的机器化。 |
| #15/#17 的 `unknown` 归零 SQL | **确实缺** ⇒ 段 A 新增 `UnknownAttributionTests` 两枚。 |
| #19 的全 `app/` 模式集扫描 | **确实缺**（既有件只覆盖 `app/llm/` 内部与业务文件的「无第二出口」）⇒ 段 A 新增 `test_llm_egress_guard.py`（AST 面 + 全文面 + 散文面 + 代码面四张表）。**修复轮改口**：那句「三层等式」里代码面当初是从「全文 − 散文」**推导**的（`code_line_numbers()` 零使用 ⇒ 内圈加法对任何实现恒真，评审 Minor 4）。现在代码面由 `code_hits()` 按行集**独立测一遍**，并与散文面做分区自核、与 AST 面做跨算法互验（`ScanningHelpersAreAllLiveTests` 再挡「helper 变死代码」这一种回潮）。 |
| 业务入口不裸放 `ValueError`（T3 移交） | **确实缺** ⇒ 段 A 新增 `NoBareValueErrorOnTheChainTests`（7 枚）。 |

## 4. 段 B 已交付的两件 + 仍在表外的三件

**段 B（Task 9）交付的两处产品代码修复**（改动面只有 `app/llm/normalize.py` 与 `app/agent.py`）：

- **#12b 多轮回放映射（I-4）——已 GREEN**：`app/llm/normalize.py::openai_payload` 出口前过一次
  `_replay_messages()`：`assistant.tool_calls[].function.arguments` 的 dict ⇒
  `json.dumps(..., ensure_ascii=False)`；`{"role":"tool","tool_name":X}` ⇒ 带 `tool_call_id`
  的协议回执（配对规则：同名优先、同名按出现次序消费、自带 id 优先并占槽、空 id 的调用
  **照样按次序占槽但写不出** `tool_call_id` 且**不许跨槽**去领后面调用的 id（Task 9 复审 I-1）、
  配不上就**不造假 id**）。授权依据 = DESIGN §6「两侧差异全部在 provider 层吸收」+「Agent 只认
  内部模型」，所以 `app/agent.py` 的回放形状与 `LLMResponse/ToolCall` 一字未动；Ollama 腿仍吃
  dict（#13 追加的那枚承载用例就是这条边界的闸）。
  **口径更新**：这一段落地之后，「配一把 `OPENAI_API_KEY` 就能用 agent 工具轮」才成立——
  段 A 时代那句话（key 到位后云侧工具轮仍会 400）已经不再是事实。真正的云侧行为仍归 C1–C4。
- **N-3 降级腿在手证据——已 GREEN**：判据查实结论 = 权威实现
  `app/conversation_agent.py:307-321` 那三支看的是「**本轮检索结果**」（`status` 与 `evidence`
  都只来自它自己那一次 `tool_registry.execute`，且它只有 round 0、没有工具回路 ⇒ 对权威而言
  「本轮 == 全链路」）。降级腿的 `evidence` 是 `run_agent` 的累加盒，照抄判据会丢已授权证据，
  故取 brief 的方案 ②：`status != "SUCCESS"` 且**手上没货**才用失败文案；有货 ⇒ 用在手证据继续
  合成（`AUTHORIZED_ENTERPRISE_EVIDENCE=` 的 dump 同步改成累加盒，并补一枚
  `NO_CAPABLE_MODEL→fast_path_failed_with_evidence` 注记）。`DENIED` 支**不吃**这枚门。
  **现状已钉住**（Task 9 修复轮 I-3）：`DENIED` + 在手证据时「文案说无权访问、`num_sources`
  报在手的 2」这枚**刻意保留**的不同源，由
  `test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand` 末尾两枚断言
  （`assertEqual(2, result["num_sources"])` + `assertIn("无权访问", result["answer"])`）钉成事实；
  是否统一口径待终审裁（要统一必须**同时**改文案与来源面，改一侧就让那两枚里的一枚红）。

仍在表外、不属于段 B 义务的三件：

- **P0 真机十字**：归 Task 10（需宿主起服务 + 真 Ollama 且 ornith 保持未加载态）。
- **`env_file=".env"` 的产品侧绝对化**（§5 第三行的根因）：主 agent 已裁「本版不改」，
  测试侧显式前提维持，记进终审待办。
- **§12 `llm_registry_file` 出厂默认改包相对**（§5 第一行的方案②）：动冻结默认值需裁决，未走。

## 4.5 Task 10 段 A：P0 的三枚反造假闸（`backend/tests/test_real_llm_failover_gate.py`）

本表原本只有一枚耦合闸：`MatrixDocumentClosureTests` 按 **AST 核存在**——文档写一枚
node-id，闸只回答「这个文件里有这个类和方法吗」。于是「给 P0 例挂 `@unittest.skipUnless`
+ 把本行状态写成 GREEN」这条路今天**能同时骗过套件与文档**（Task 9 复审点名的洞）。
段 A 补三枚闸，取值口径写死在闸里、不写在本表里：

- **① `P0CarrierHasNoSkipBranchTests`**：P0 承载例（
  `test_real_llm_failover_acceptance.py::RealLlmFailover001Tests`）的**代码面**零 skip 家族
  令牌——装饰器、属性、调用、**以及字符串常量**（`getattr(fn, "skipIf")` / `exec(...)` 两条
  后门死在这里），并逐跳重扫 `getattr(fn, "__wrapped__", fn)` 的整条链；运行面同时要求
  `__unittest_skip__` / `__unittest_expecting_failure__` / `__test__ is False` 三枚为假。
  证据采集器 `tests/real_llm_failover_kit.py` 本身也在射程内（它能定义「什么算证据成立」）。
- **② `P0CollectionGateTests`**：那枚例的门**只有一枚**显式 env 开关
  `REAL_LLM_ACCEPTANCE=1`（收集门必须是模块末尾唯一的一元 `if`，`acceptance_enabled()`
  只读一枚 env 名），且**双向**：关 ⇒ 子进程 `--collect-only` 收集数恰好 **0**
  （默认套件里「既不红也不冒充绿」本身是断言，且输出不许出现 `skipped`）；
  开 ⇒ 恰好 **1**。另有一枚全仓默认收集面的兜底钉（换文件名/换目录混进来也红）。
- **③ `P0MatrixStatusLockedToEvidenceTests`**：本表 P0 行的状态字段与执行证据互锁——
  **没有**成立的证据 JSON（`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`）
  ⇒ 只许 `BLOCKED`；证据成立 ⇒ 只许 `GREEN`。判据是 `real_llm_failover_kit.validate_evidence()`：
  十枚断言各带实测值、两次真外呼的模型名/请求字节数/耗时、primary 错误体里的**服务端原文**、
  临时库恰好一行且零 canary 命中、以及**逐枚重算的 sha1**。本表文案自己不算数；
  `test_the_evidence_judgment_does_not_degrade` 再拿四枚变异（模型序 / 错误体 / 行数 / 指纹）
  打这枚判据自己，防它退化成「数一数有没有 10 条」。
- **`P0GateSelfIntegrityTests`**：闸自己也在判据内——本文件零 skip 令牌、四枚类逐枚挂在本表上
  （反向耦合，口径同 §前言第 ④ 条），且闸自己在默认套件里**必须**被收集到 ≥8 枚
  （否则「把闸藏起来」也是一种通关方式）。

**改判 GREEN 的动作仍归主 agent**：闸只给判据，runner 只打印「许可条件是否全部满足」，
两者都不写本表。段 A 新增的闸与 P0 例会让 §5 的 `935 passed / 981 subtests` 上行
（P0 例默认不收集，只贡献闸那一枚文件的量），终态数字归 Task 11 重测。
A-2 的现场探针（真 ornith 加载失败原文 / 状态码 / 耗时）落在
`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/ornith-primary-load-probe.json`，
是 §10「primary 真失败」这一枚的前置证据，也是 T11 验收文档的输入。

## 5. cwd 收口终态（Task 9 段 A / T5 N3 / T6 N3）

全套件现在**两种 cwd 同数**：`cd backend && pytest tests -q` 与 `cd <仓库根> && pytest backend/tests -q`
Task 11 封版终态：**961 passed / 0 failed / 992 subtests**（两种 cwd 同数；真机 P0 用例默认不收集）。上一行的过程值：（P0 反造假闸 15 例入库；真跑用例默认不收集）。下面记录的是段 A/段 B 收口时的过程值。

段 A/段 B 收口时两种 cwd 同数：**935 passed / 0 failed / 981 subtests**（段 A 收口时 918/973；段 B 新增 10 例 =
`OpenAIMultiTurnReplayTests` 8 枚 + `AgentNoCapableFastPathTests` 的 N-3 两枚，那枚多出来的
subtest 是 `MatrixDocumentClosureTests` 对本表新增 `N-3` 行的逐行核对；**修复轮**再加 7 例 =
`OpenAIMultiTurnReplayTests` 的 I-1 一枚 + `test_llm_egress_guard.py` 六枚（代码面测量三枚 +
反向耦合闸一枚 + `ScanningHelpersAreAllLiveTests` 两枚），7 枚新 subtest 全部来自反向闸对
7 张类表的逐枚核对；基线 889/889 只增不减）。
段 A 落地的三个 cwd 钉都是**测试侧**、都不动 §12 冻结默认值：

| 落点 | 手法 | 为什么不是别的样子 |
| --- | --- | --- |
| `test_model_router_v23_contract.py::RouterSettingsTests::test_argless_settings_still_constructs_on_host_env` | 例内 `os.chdir(BACKEND_DIR)` + `addCleanup` 还原（brief 的方案①） | 方案②（把 `llm_registry_file` 解析成包相对路径）动 §12 冻结默认值，未获主 agent 批准 ⇒ 不走。 |
| `test_feishu_identity_contract.py::WarmupGateTests.setUp` | 把 `settings.llm_registry_file` 指到**绝对**出厂文件（与本文件既有的 `_set_rules` 同手法），`tearDown` 还原 | 这一类的红是 V2.3 自己的：Task 5 把 `llm.warmup()` 挂上了 lifespan，于是「真跑 lifespan」的用例继承了相对默认值。 |
| `test_typesafe_judgments.py::TypeSafeJudgmentTests.setUp` | 显式 `patch.object(settings, "typesafe_enabled"/"typesafe_mode")` | 根因不是注册表而是 `SettingsConfigDict(env_file=".env")` 的**相对** dotenv：从仓库根起读不到 `.env` ⇒ `effective_typesafe_mode="off"` 早退，6 例红。这是 TSV2 期既有耦合，段 A 只做「把隐性前提写成显性前提」，不放宽断言；**正解在产品侧**（`env_file` 绝对化），需主 agent 裁。 |

