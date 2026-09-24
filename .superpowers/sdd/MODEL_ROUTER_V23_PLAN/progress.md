# SDD ledger — plan: E:\xiangmu\rag\docs\MODEL_ROUTER_V23_PLAN.md
规格：docs/MODEL_ROUTER_V23_DESIGN.md（D1–D6 与 19+1 矩阵冻结；实现冲突改实现不放宽 spec）。无 git 写；收尾门槛=定向绿+全套件 ≥407 passed/0 failed 只增不减。Agent 无 model 参数：继承会话模型。

## Pre-flight 冲突扫描
| 对 | 检查 | 结论/裁决 |
| --- | --- | --- |
| T1↔T5 | 两者都提到 warmup/status | Ruling: warmup 只归 T1（registry fail-fast）；T5 仅 status 聚合与 trace，不重复接线 |
| T3 自 | health 全灭抛 NoCapable 与 D2 降级链 | 一致：抛错→Agent fast-path/RAG 既有兜底文案；'全灭'定义为所有 enabled 候选 provider 均不健康或 OPEN |
| T4↔T6/7/8 | run_complete(profile,req,trace_id=None) / run_stream 形状 | 一致；SSE commit 语义只在 StreamSession 暴露，业务不改事件 |
| T7 自 | native_stream 删除前提=其余调用点为零 | 实测 grep: 仅 conversation_agent.py:16 引用 → 可删；若 T7 时发现新调用点，一并迁移并报告 |
| T8 自 | _ollama_chat 返回 dict 形状被 run_agent 循环消费 | 一致：provider 响应转回 message-dict，循环体零改；tool_calls 标准化在 llm 层完成后回填同形状 |
| T5↔D6 | status llm 块 providers.healthy 来自 probe 缓存 | 一致：probe 在 health.py（T2），T5 消费 provider_health_view |
| 矩阵#18 | legacy 双路契约 = T4(旗标)+T6/7/8 各留分支 | 一致 |

Task 1: complete (models+registry+§12 配置键；定向 37 passed/66 subtests/0 failed，全套件 444 passed/539 subtests/0 failed = 基线 407+37 只增不减；变异 14/14 killed；红证据两轴：删实现=collection error、删 §12 键=30 failed)。
Task 1: ruling(自定，需评审确认): ①`ProviderCredentials` 加第三字段 `model_override=""`（D1 的 `_MODEL_OVERRIDE` 在冻结双字段签名里无落点，带默认值向后兼容）；②`load_registry` 拒空 `models`（Task 3/4 测零候选可直用 `Registry(models=())`，不校验）；③动态 enabled 泛化为「external ∧ 无 key ⇒ False」（openai 是其中一例），ollama `external=false` 不受影响；④`OLLAMA_MODEL` 不参与 model 覆盖（否则 ornith/phi3 两条本地条目被折叠成同一模型，REAL-LLM-FAILOVER-001 的源→备对子消失）；⑤凭据查找序 Settings 字段→OS env（D1「不产生第二套配置」+ .env 里的 OPENAI key 必须继续生效）；⑥§12 实为 14 键（任务消息「12 个」按 brief 列表全实现）；⑦云端 priority/stream/reasoning 旗标与 pricing 为牌价占位，Task 11 前按账单校准。
Task 1: handoff → T2: `provider_credentials` 的 `RegistryError`（缺 base_url/凭据不全）翻译成 `LLMError(kind="config")`+`PROVIDER_CONFIG_FAILED`；§8 冻结 19 列**无** `estimated` 列，「usage 缺失记 0+estimated 旗标」只能留内存或另裁决加列。→ T5: `warmup()` 挂 lifespan（本任务按 pre-flight 只建函数）。→ T9: D6 扫描在 `app/llm/registry.py` 的命中仅 docstring 散文（代码里 env 名运行期拼装，无大写凭据键字面量），需文件级豁免或限非注释行；`app/config.py` 的 `*_api_key` 小写字段同理。→ T3/T4: `Registry.models[*].enabled` 已是生效值，enabled 过滤不必再判 key；reason 若需区分「JSON 意图 true 但无 key」需自行读凭据。

Task 1: complete (spec ✅; fix round 1/5 I-1/I-2+M-1..3 ADDRESSED, re-review PASS; 446 passed/0 failed; app/llm 对 D6 永久零命中无豁免)。
Task 1: handoff→T2: ProviderCredentials.model_override 必须被消费; RegistryError(缺base_url)→provider 层翻译 LLMError(kind=config)+PROVIDER_CONFIG_FAILED; estimated 旗标只活在内存/trace(§8 19列冻结, 持久化需用户裁决, T2 开工已确认按 (a) 案执行)。
Task 1: minor(deferred): config/ 目录未入 VCS(既有状况)→T11 验收记一行; 空 priority 合法口径记档。
Task 2: complete (spec ✅; fix round 1/5: I-1..4+M-5/6 ADDRESSED, re-review PASS 含 D-17 超集独立验证与 10 组对抗 body; 529 passed/0 failed)。
Task 2: minor(deferred): warmup 同一性无断言; errors 头表格未提新正则; 报告三处旧指向(历史文本) — 终审 triage。
Task 3 交接: health_view 由 provider_health_view(registry) 供给但 T3 测试用 stub dict; 未知provider启动校验已在 warmup; Router 消费 ModelDefinition.enabled 已含动态判定。

Task 3: complete (classifier+router 纯函数；定向 172 passed/302 subtests/0 failed（+50 例），全套件 579 passed/793 subtests/0 failed = 基线 529+50 只增不减；变异 4/4 killed：交换 caps↔health、cost 反向、全灭不抛、0 分不剔除；P95 实测 60 候选 chat 0.525ms/agent 0.282ms/rag 0.506ms、5 条目 0.028ms ≤10ms）。
Task 3: ruling(自定，需评审确认): ①签名取 plan brief 的 keyword-only `mode/needs_tools/needs_stream`（spec §4 旧位置参名弃用），complexity 为输出；②needs_reasoning 恒 False 但 router 仍消费该字段（双态钉）；③priority 缺失键=0 分⇒剔除 ⇒ 全 0 分抛 NoCapable(stage=priority) fail-closed；④候选级理由码口径（CAPABILITY_MATCH 人人有/HIGHER_PRIORITY=压住更低分/LOWER_COST=同分带压住更贵/LOCAL_PREFERRED=external false 入选/health 码只在真剔过该 provider 时出现，入选码在前剔除码在后）；⑤同分同价回落注册表声明序；⑥NoCapableModelError 非 LLMError 子类，带 stage/profile/reason_codes，NO_CAPABLE_MODEL 只随异常；⑦benchmark 双规模（任务消息 5 条目 + brief 60 候选）都跑；⑧classifier high 词表在任务书 8 枚之上加约 30 枚（不参与打分，V2.7 的成本旋钮）。
Task 3: handoff → T4: **接口缺口**——plan() 无请求体，§5 的 context 粗估改在 execute 前置：`sum(len(str(m)) for m in req.messages)/2 > context_tokens` 剔候选，收口后仍空则自抛 NoCapable(stage="context")；health_view 需 T4 合成 {healthy, circuit_open}（probe ∧ breaker.allow()），否则熔断过滤步不生效，与 Attempt(skipped_circuit) 是两道门；FALLBACK_AFTER_TIMEOUT/PROVIDER_CONFIG_FAILED 由 T4 产生。→ T8: 无 key 出厂注册表下 agent 模式必然 NoCapable（已用真注册表钉），fast-path 是常驻分支。→ T5: status 的 providers.healthy 不得掺熔断态（D4）。→ T9: classifier/router 对 D6 永久零命中，无需豁免。
Task 3: spec ✅ approved; 评审两 Important→(c)已回写 spec §5 修订+T4 义务入 brief;(d)①入口校验派修复轮1。Ruling: priority 0分剔除维持 fail-closed(评审独立复核出厂配置下与保留末位零行为差); fast-path 常驻为 D2 设计前提。
Task 3: spec ✅ approved + (c) §5 limits 修订已回写 spec、T4 义务已入 task-4-brief; Ruling: priority 0分剔除 fail-closed 维持(出厂配置下与保留末位零行为差, fail-closed 更安全); fast-path 常驻为 D2 设计前提; (d)①入口校验进修复轮1。
Task 3: complete (spec ✅; fix round 1/5 三项 ADDRESSED, re-review PASS; 583 passed/0 failed; T4 前置 stage=context+入口校验已具备)。
Task 3: handoff→T4: 只用模块常量构造异常(裸 str 会被入口校验转 ValueError, 非 NoCapable 子类, T4/T8 接不住); stage 无运行期闸门(静态 Literal 兜); →T9: 扫描业务入口不裸放 ValueError。
Task 4: spec ✅ Approved-with-fixes; I1(流式行 latency=预算常数)进修复轮1; Minor M1(status_code流式恒None)/M2(model 身份空间劈叉:非流=生效名,流=条目id→T5 聚合需归一)/M3(NoCapable 不产行+关页记失败→T5 聚合语义必须知情)/M4(Attempt 首字段=model_id 非 brief 的 model)/M5(hard 回执 ratify,措辞待改)/M6(半截 usage 记 0)/M7(over_soft 无消费者)→ 全部移交 T5/T7/终审 triage。
Task 4: complete (spec ✅; fix round 1/5: I1 三出口同口径+两跳和钉, re-review PASS 零新破坏; 648 passed/0 failed)。

Task 5: 接续轮（前一轮被会话截断：树里已有 usage.py/契约测试/status 块/lifespan，但 2 例红 + trace model_route 零落地 + 无报告）。主 agent 亲跑核实：接续轮定向 98 passed/0 failed，全套件 **746 passed/0 failed/852 subtests/84.82s**。
Task 5: review = **Approved-with-fixes**（Critical 0 / Important 5 / Minor 12，见 review-task-5-findings.md）。评审者独立复现 M1/M2/M3 三发变异全杀，另发现「_clean_codes 去重+上限」变异存活、两例聚合测试只在 cwd=backend 绿、以及报告改动面自述不实。
Task 5: Ruling(主 agent 裁，需终审确认): **spec §8 回写**（评审 I-4 + C 的授权口径）——①`error_type` 值域在 §0c T2「kind(+no_fallback/status)」之上加两枚**账本侧哨兵** `client_aborted`/`unknown`（T2 那句冻的是「provider 归类怎么落库」，不含「生产者漏填归类」与「用户 commit 后离开」两种无 provider 事实的行；把它们混为一谈或都算失败都会污染 success_rate）；②`client_aborted` 判据收窄为「success=False ∧ error_type 缺失 ∧ **有交付事实**（fallback_index>=0 ∧ tokens>0）」，其余落 `unknown` 且**计入**失败分母；③`llm` 块除 §8 五键外**允许** additive 的 `aborted_rate` 与 `breaker`（逐枚白名单，熔断态与 `providers.*.healthy` 物理分离，D4 不破）；④`model_route` 键清单扩三枚执行面事实 `stage`/`selected_index`/`context_dropped`——原 §8 六键与 §5/T3 移交（「trace 要带 stage + 被剔计数」）互相矛盾，且 19 列没有它们的位置，删掉执行面信息比补三键更坏。
Task 5: Ruling: `app/llm/model_route_payload` **删除**（零业务消费者、同一 attempt 给出与 trace/账本不同的模型名、且被 docstring 伪称「T4 交付已测」以豁免重审）。口径：**同一事实只有一处构造** = `usage.model_route_trace`，唯一挂载点 = `agent_trace.attach_model_route`。
Task 5: handoff→T6: 给 `FallbackResult`/`StreamSummary`/`AllCandidatesFailedError` 各加**末位可加**字段 `plan: RoutePlan|None = None`（不动 `complete()/stream()` 返回形状、不加回调），调用形状固定 `attach_model_route(trace, result.plan, result, profile=profile)`。→T6/T7/T8: 矩阵 #17 的「集成」半段归各任务，各补一条走真 `llm.complete/stream` 的用例钉 model_route 六+三键齐备；T8 另钉 `NO_CAPABLE_MODEL→fast_path`（零候选不产行后唯一的解释出口）。→T6/T7/T8: 写 `success=False` 的账**必须**带 `error_type=kind`，不得用「留空」表达「不知道」。→T11: 验收文档须写明「`requests_5m` 不含零候选请求」。

Task 5: re-review round 1 = **PASS-with-minors（放行 Task 6）**；I-1..I-5 全 ADDRESSED，FIX-5 五枚 Minor 名副其实，无新 Critical/Important。
Task 5: 主 agent 补刀 N1（交付闸扩到「链上自写」与成功行；新例 1 枚 + 变异复现）并回写 DESIGN §8.1 第 2 条 + PLAN Task 5 段（N5）。终裁：V2.3 **不加** `unknown_rate`（与 success_rate 共线），归因走 `error_type='unknown'` 库查询 → T9/T11 验收钉 0。
Task 5: complete (spec ✅ §8/§8.1; 修复轮 1/5, re-review PASS; 定向 101 passed/33 subtests（两个 cwd 同数）; 全套件 **749 passed/0 failed/876 subtests**; 变异：首轮存活那发已杀 + N1 复现杀; N2/N3→T9, N4→T6 已入 brief).

Task 6: complete (spec ✅ §9/#18; 定向 413 passed、双文件 386; 全套件 **793 passed/0 failed/878 subtests/113.64s**（基线 749 只增不减）; 变异 11+6 发全 RED 存活 0; 修复轮 1 re-review = **PASS-with-minors 放行 T7**，I-1/I-2 ADDRESSED，护栏净效应「没让任何既有测试变弱」由复审者 29 文件加/去护栏对照证明）。
Task 6: 事故与清理：Task 6 首轮用例每跑一次往**真实库** `backend/data/conversations.db` 的 `llm_request_logs` 写一行假账（累计 23 行，形状 `model='fb-a-model' ∧ trace_id IS NULL`）。主 agent 删前快照 → 精确 DELETE 归零（真实数据 conversations 7 / messages 10 未动，复审复核为 sha1 全程未变）。修复轮把它做成系统级护栏 `backend/tests/conftest.py`（会话级改道 `CONVERSATION_DB_PATH`）+ `LedgerIsolationGuardTests` 3 枚防回潮钉。
Task 6: Ruling(主 agent 裁): 我的 task-6-brief 有两处**我自己写错**、实现者顶住了：①D-3「NoCapableModelError 要补一行带 kind 的失败账」与 T5 已裁「零候选不产行」正面冲突，且该异常无 `.kind` ⇒ 按 T5 裁定执行，本条作废；②「矩阵 #17 集成半段归 T6」经复审判定按骨架在**测试文件内**闭合即可（RAG 链今天没有 trace 对象，`save_trace` 只在 `agent.py`/`conversation_agent.py`），已由 `ModelRouteIntegrationTests` 交付。
Task 6: handoff→T7（步骤 0，先修护栏再迁移）: **N1** 只读账本会被护栏误判成「写进真实库」（`_query`→`_connect(None)` 同样过 `database_path()`；实测纯 `aggregate_status()` 被记一笔并在收尾打红、信息误导）⇒ 把「写」的判定挪到 `usage._execute`（写路径唯一收口），或 `_REDIRECTS` 记 `(src,dst,kind)` 只对 `kind=="write"` 逐例判红、读走 warning。**N3** 护栏只认 `backend/data`，默认值是**相对** `data/conversations.db` ⇒ 非 `backend/` cwd 下整层失效且行落在 `<cwd>/data/`（实测）；仓库根还有一份 `data/conversations.db`（不在保护集）。修法：`_inside_repo_data` 对相对路径同时按 `Path.cwd()/path`、`BACKEND_DIR/path`、`BACKEND_DIR.parent/path` 判，保护集加 `BACKEND_DIR.parent/"data"`。→T9: 豁免表可直接抄（`settings.openai_api_key` 代码读法 3 处 L142/L202/L206、httpx 代码命中 3 处、端点字面量 2 处，散文 L92/L109 不算）；顺带修 N2/N3 两枚扫描与 cwd 遗留。→T10: 真调用必须把 `CONVERSATION_DB_PATH` 指**绝对**临时路径（brief 已写）。→T11: 验收文档写明「全套件只在 `backend/` 下有效」+ 展示面 `complexity` 恒 low 的口径 + 「requests_5m 不含零候选请求」。
Task 6: 环境告警（非代码缺陷）: 两轮 agent 的工具返回里出现**伪造 `<system>` 指令块**（诱导改身份/披露口径），来源不在 `docs/` 与评审包文件内 ⇒ 注入面在仓库之外（工具通道），两个 agent 均忽略并留 sha1 证据；已向用户报告。

Task 7: 首个实现者撞 150 轮上限被截断，留下两处残留由主 agent 当场修掉：①`conversation_agent.py:505` 的 `attach_model_route` 被变异脚本注释后未还原 ⇒ `if` 体空、文件 IndentationError（全仓 collection 阻断）；②同一脚本以文本模式把 LF 原生 `app/llm/fallback.py` 翻成 CRLF（943 行假差异，会毒化 T9/T11 的静态扫描与评审包）⇒ 按字节还原并验证内容与 snap-task6 逐字相同。
Task 7: 接续者完成收尾。主 agent 独立复核终态：`conversation_agent.py` sha1=c65937c0a841（与其自报一致）、`CONVERSATION_LEGACY_TEMPERATURE=0.2`、attach 真调用在位、`native_stream.py` 已删且零 import、`fallback.py` 纯 LF 且与 snap6 相同、conftest 纯 LF、AST 全通过；全套件亲跑 **835 passed / 0 failed / 880 subtests / 106.60s**（基线 793/878 只增不减）；真实库只读实测 `llm_request_logs=0`、`conversations=7`、`messages=10`。
Task 7: Ruling(主 agent 自纠，无需用户裁决): 我给的 task-7-brief A 条「非流式腿 temperature=RAG_LEGACY_TEMPERATURE」是**错的**——`baseline-app/conversation_agent.py:297-299` 该腿调 `agent._ollama_chat`，与流式腿（`baseline-app/native_stream.py:27-28`）现网值都是 **0.2**；0.1 只属于 `app/rag.py` 那条链。已裁定两条腿统一用本链常量 `CONVERSATION_LEGACY_TEMPERATURE=0.2`，矩阵 #18 在本链回到「报文逐字等价」而非「已声明偏差」；DESIGN §9 需据此删/改「buffered 腿 0.2→0.1」那半句（→T11 回写）。
Task 7: handoff→T8: `_ollama_chat` 迁移时**同一条**温度出处规则适用（agent 链现值 0.2，别套 0.1）。→T9: 执行器侧 D5 变异未在 T7 打（`fallback.py` 字节冻结），归 T9；D6 豁免表按 T6 复审那张抄。→T11: DESIGN §9 回写 + 「全套件只在 `backend/` 下有效」+ p17 的 `SOURCE` import 期读源码宜改方法内读。
Task 7: 环境告警升级（重要）: 本窗口出现**并发写入者**——接续者的首轮修复被整份还原过一次，来源=被截断 agent 残留的变异脚本仍在跑。⇒ 后续每个任务：①派新 agent 前确认前一个已终止；②收尾必须交 sha1 清单并由主 agent 独立复核（本轮已这样做）；③变异脚本一律字节读写 + 发内还原 + sha1 验证（已写进后续 brief 的通用约束）。

Task 7: review = **Approved-with-fixes**（Critical 0 / Important 4 / Minor 9）。评审者独立复跑定向 332/353/0、从仓库根跑护栏 10/0，自打 11 发变异 **9 killed / 2 survived**（M3b 流式腿删 temperature 参数、M5a ttft 换零点），并逐件 sha1 复核终态。
Task 7: Ruling(主 agent 裁 + 评审 §6 措辞已回写): **DESIGN 新增 §9.1**（对话链两条腿在 `LLM_ROUTER_ENABLED=false` 下不对称：非流式腿保留 `_ollama_chat` 原调用；**流式腿无 legacy 形态可留**（原实现即被退役的 `native_stream.py`，内联回业务文件违反 D6/#19），其 #18 对照面改为「报文与退役模块逐字等价」；旗标只是**非流式路径**的应急回退，V2.3 验收文档必须点名「不得当 SSE 止血开关」）+ §10 #18 行与 PLAN Global Constraints 同步加注。同处回写：**对话链两腿现网温度都是 0.2**，0.1 只属于 `rag.py` 链。
Task 7: 修复轮 1 落地：FIX-1 流式腿调用面 kwargs spy（M3b 由存活→被杀）+ 注释改口；FIX-2 ttft 两枚轴做成行为事实（注入 40ms 检索段，M5a→被杀）；FIX-3 **授权扩面** `app/agent_routes.py` 加 `except StreamInterrupted` 支（第二支 SSE 出口也落 D5 payload，与主对话 SSE 同形、事件词汇不变）+ 路由级用例；FIX-4 护栏第三道闸（`_connect(ensure_schema)` 判 write）+ 删 `native_stream.pyc` + `SOURCE` 改方法内读。共 7 发变异全 RED 存活 0。
Task 7: 主 agent 独立复核：全套件 **837 passed / 0 failed / 880 subtests**（我亲跑，等终态）；`conversation_agent.py` 与 snap-task7 的 diff = 17 行、**非注释改动 0 行**；`agent_routes.py` 混合行尾未被翻转（117 CRLF / 69 裸 LF，既有字节未动）；`native_stream` 字节码残骸已清；真库仍 `llm_request_logs=0 / conversations=7 / messages=10`。

Task 7: re-review round 1 = **PASS-with-minors，放行 T8**（复审者独立用自造锚点打 7 发变异全 RED 存活 0：`M3b`/`M5a` 确认被杀，另加「删支/顺序写反/认错类」三支全红；FIX-3 语义成立：支序在 generic 前、两支 `error` 键集合逐字同形、无新事件类型、哨兵仍只由账本产出、新例真走 `agent_query_stream`；抽两族 102 passed；backend 六枚 sha1 跑完全部复原、真库未动）。**Task 7 关闭**。
Task 7: Ruling(流程纪律，我自己的错): 复审者指出我把 `snap-task7/` **就地刷新**成修复后终态 ⇒ 首轮评审的四枚基线 sha1 消失，「既有断言 0 放宽」退化成语义核对。此后快照一律**只增不改名**：门禁快照 `snap-taskN/`（评审基线）与收尾快照 `snap-taskN-r1/`（修复后）分开存，绝不覆盖。

Task 8: 实现者交付（报告 task-8-report.md）。主 agent 独立复核：`agent.py` sha1=9760d3509ed5、871 行全 CRLF 未翻转、AST 通过、自有 `AGENT_LEGACY_TEMPERATURE=0.2`、`needs_tools=bool(tools)`、`attach_model_route` 已接；**冻结件逐字节未动**（fallback/rag/conversation_agent/agent_routes/security 对 snap-task7 全 IDENTICAL，`config/llm_registry.json=3e652e9cf496` 未改）；真库 0/7/10。全套件我亲跑中（其自报 881/0/881）。
Task 8: Ruling(接受实现者的 §9.1 补正): 我写的「`LLM_ROUTER_ENABLED=false` 不覆盖 agent 链工具轮」**不准确**——agent 链两条腿都有 legacy 形态（同一段含 `tools` 的 httpx 报文）。已按建议措辞回写 DESIGN §9.1 补正段：应急含义是「回到未路由的世界」，不是「让工具轮可用」。
Task 8: 待用户裁决（不阻断，终审一并复述）: ①**V2.3 出厂形态接受「agent 工具链 100% 走 D2 fast path」吗？** 实现者附证据建议**不要**翻 `tools` 旗标（phi3 官方未针对 function calling 训练、ornith 本机加载失败）；可行替代=给 `openai` 配 key，或新增一条指向官方支持 tools 且本机跑得动的模型的注册表条目。②`agent_local_fast_path=false` 时零候选该不该报错（现按 D2「不得 500/503」无条件降级）。③`model_used` 改为 selected 生效模型名是否登记 UI 文案表（字段名与类型未变）。
Task 8: 快照纪律已执行：新建 `snap-task8/`（含 `agent.py` + `agent_routes.py` + `conversation_stream_routes.py` + 6 份测试 + 报告），**未覆盖** `snap-task7/`。

Task 8: 主 agent 独立复跑全套件 = **882 passed / 0 failed / 881 subtests / 154.94s**（实现者报 881，差一枚 collected 计数：其门 2 跑在倒数第二个字节集上，评审者 m-3 已指出；方向只增不减）。冻结件 sha1 我逐枚复算全 IDENTICAL。
Task 8: review = **Changes-requested**（Critical 1 / Important 4 / Minor 9）。评审者独立复现 5 发变异（4 KILLED + **G2 存活**），探针实测出 C-1 的 503 与 I-2 的 llm_ms 虚高一整次检索。定向 386/0/353、回归子集 169/0。
Task 8: 评审裁定（进 ledger/T11）: **两套 fast-path 的口径** = `conversation_agent._local_fast_path` 是**唯一权威实现**，`agent.py` 就地降级是它的**变体**；brief 那句改读为「复用语义与机器件、不复用函数」，本版不重构，但 6 项等价清单必须逐项对齐（其中 I-3 三支短路、I-2 工具计时两项当前**不等价** ⇒ 进修复轮）。
Task 8: I-4（云 key 后 agent 工具轮第二轮回放不合 OpenAI 协议：`arguments` 需 JSON 字符串、工具回执需 `tool_call_id`）→ 修点在冻结的 `normalize.openai_payload`，已写进 `task-9-brief.md`；结论「配 key 即可用工具轮」被实测推翻，须回给用户。

Task 8: 修复轮 1 交付（`agent.py` 新 sha1=59d4cd3b3c3b、1000 行全 CRLF、AST 通过）。主 agent 独立复核：**冻结件 9 枚逐字节 IDENTICAL**（fallback/normalize/usage/__init__/rag/conversation_agent/agent_routes/security/registry）、I-3 三支短路（`fast_path_denied|failed|no_evidence`）与 `_synthesize_with_second_door` 三个落点在位、真库 0/7/10。实现者报定向 393/0/360、全套件 889/0/889、变异 7 发全 KILLED 存活 0（含评审 G2 由存活→被杀）；我自己的全套件复跑在跑，终态补在下条。

Task 8: re-review round 1 = **PASS-with-minors，放行 T9**（`re-review-task-8-round1.md`）。C-1 实测封住（自建溢出证据：不 503 / trace 恰 1 行 / 两枚注记 capability→context / 审计含 QUERY / 零外呼；删新 except 变异 KILLED）；I-3 三支与 `conversation_agent.py:317/319/321` 逐字同源且变异复现出旧症状；**A 项无误伤**（工具成功 2 条证据的降级形状仍走合成、账本 1 行、九键在位）；6 发变异全 KILLED、25 枚 sha1 与初值全等。
Task 8: complete (spec ✅ §9/§9.1/#12/#17/#18; 修复轮 1/5, re-review PASS; 定向 393/0/360; 全套件主 agent 亲跑 **889 passed/0 failed/889 subtests/182.80s**（基线 882/881 只增不减）; 变异合计 7+6 发全杀; 冻结件 9+ 枚逐字节 IDENTICAL)。
Task 8: 新发现 N-3 → 已写进 `task-9-brief.md`（降级腿在「前轮已有授权证据 + 本轮检索失败」时丢证据并回失败文案，`num_sources=2` 自相矛盾；T9/T10 放开 tools 模型后成常态路径）。另 N-1（docstring 过强）/ N-2（报告行号 709→710）随终审 triage。快照按纪律**另存** `snap-task8-r1/`，未覆盖 `snap-task8/`。

Task 9: 主 agent 独立复跑：A 段终态两种 cwd **918/0/973**（我亲跑仓库根那一次）；A+B 终态 **928 passed / 0 failed / 974 subtests / 193.28s**（我亲跑，与段 B 自报一致）。产品代码改动面 = 仅 `normalize.py`（→`6e8a345ff322`，纯 LF）与 `agent.py`（→`9dabebf801ed`，1044 行全 CRLF 零裸 LF）；其余 9 枚冻结件我逐枚复算 IDENTICAL（含 `conftest.py=73d1060de465`）。
Task 9: review = **Approved-with-fixes**（Critical 0 / Important 3 / Minor 11）。评审者实测结论：§0b-2 配对四组对抗输入三对一错（**I-1 跨槽**）；§0b-3 N-3 等价论证**成立**（权威单发无累加盒）、DENIED 不吃门、新增的是 `note`+`stage` 不违反 §5 冻结枚举 ⇒ 不需 spec 回写；§0b-4 矩阵 6 行 25 枚承载例逐枚跑绿、云行仍 PENDING、P0 仍 BLOCKED，但闸**单向**；D6 豁免互等双向真成立（删档/养档/新出口三发全红），第三层内圈**恒真**（代码面是推导而非独立测量）；§0b-1 那发 GREEN 判定为**如实披露**（变异的是谓词本身），但 A-3 仍余 2 形可绕（kwargs 形、隐式拼接形）⇒ I-2。

Task 9: 修复轮 1 交付（实现者自报，待主 agent 独立复核）。报告 `task-9-fix-report.md`。FIX-1=I-1：`normalize.py` 的可配对性判断从 `_matching_call` 入口移到 `_paired_tool_receipt` 选出槽之后（先 `consumed.add(index)` 占槽再判），跨槽错配消除；评审探针 P10 由 `['k2', None]` → `[None, 'k2']`（**注意**：brief 写的验收句 `[None, None]` 与评审自己给的「+占槽」修法互斥，实现按修法落地并在报告 §1.4 交代取舍）。新例 `OpenAIMultiTurnReplayTests::test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt`。FIX-2=I-2：A-3 谓词 2→4 枚（kwargs 形 + `ast.Constant` 整枚相等形），docstring 自述收窄；**新增裁决点**：kwargs 支命中冻结件 `app/llm/fallback.py`（它本就是这两枚事实的定义方），故拆两档豁免 + 两枚外圈等式证明买不到九键构造权。FIX-3=I-3：DENIED 例补 `assertEqual(2, num_sources)` + `assertIn("无权访问", answer)`；两段报告 + 矩阵 §4 就地改口（m-B1 那句「已被钉住」原为不实）。FIX-4=Minor 1/2/3/4：agent.py docstring ④ 补「手上没货」前提、会漂裸行号改函数名+分支指法、耦合闸补反向（类名清单，评审说 12 枚实测 6 枚）、第三层代码面改由 `code_hits()` 按行集**测量** + 分区自核 + 与 AST 面跨算法互验 + `ScanningHelpersAreAllLiveTests` 死代码闸。自报：定向 517/0/485；两种 cwd 全套件同数 **935/0/981**（基线 928/0/974，+7 例 +7 subtest、0 删 0 降级）；变异 13 发 = 11 killed + 1 期望存活（A6 运行期拼键名）+ 1 打点无效重跑；9 枚冻结件逐枚 IDENTICAL、真库 0/7/10、行尾未翻（`normalize.py` LF 435、`agent.py` CRLF 1048/1048）。

Task 9: 修复轮 1 交付 → scoped 复审 = **PASS（放行 T10）**。主 agent 亲跑 A+B 终态 **928/0/974**；修复者报修复后 **935/0/981 两种 cwd 同数**（复审者亦跑了两姿势）。冻结件 9 枚我逐枚 IDENTICAL；改动面 = `normalize.py`(+`agent.py` 注释) + 4 份测试 + 矩阵 + 三段就地更正的报告，行尾未翻（normalize 纯 LF / agent 全 CRLF）。
Task 9: Ruling(我裁 + 复审确认): I-1 修复后 P10 的正确期望是 **`[None,'k2']`**（次序语义：receipt↔同位 call，空 id 只是写不出、不许跨槽领后面的 id），首轮评审要求的 `[None,None]` **过严**且会让 call1 变孤儿——复审实测「删 `consumed.add` 即可翻转」不成立（那样基线退化成两枚回执重领同一 id）。跨槽错配在两种读法下都已杀死。
Task 9: 复审新发现 7 枚全 Minor，其中两枚必须先落：**N-1** 混合形（一枚隐式拼接 + 一枚 kwargs）仍可绕 A-3 谓词；**N-P0 承载闸可被 `skipUnless` 伪造**（复审最担心：闸只按 AST 核存在 ⇒ P0 转绿在真机上可以造假）⇒ 已写成 T10 步骤 0。

Task 10: 段 A 的实现 agent 撞 150 轮上限中止（最后一步才开始写报告），但它留下的产物经我逐项核验**是可用的**：`backend/tests/test_real_llm_failover_acceptance.py`（40KB，P0 十字逐条对应 §10）、`backend/tests/test_real_llm_failover_gate.py`（29KB，**反 skip 造假闸** 15 passed/11 subtests 我亲跑）、`.superpowers/scripts/run_p0_failover_acceptance.sh`（8.6KB，含内存前置判定 + 离线自检 + 证据落盘 + 「只有主 agent 有权把矩阵改 GREEN」）。默认套件对该文件的收集数 **0**（末段 `del` 掉类而不是 `skipUnless`——避免 skipped 被读成"跑过了"，这条设计我认可并保留）。缺的只有 `task-10a-report.md`。
Task 10: 全套件（含闸）我亲跑 = **950 passed / 0 failed / 992 subtests / 136.27s**（基线 935/981，+15 例全来自闸）。
Task 10: P0 前置的**真机 primary 探针**（runner 的离线自检段，一次有界真调用）实测原文：`llama-server reported out-of-memory during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer of size 820943872 / error loading model: unable to allocate Vulkan0 buffer`，耗时 22465ms；归类 `model_unavailable`、marker 命中 `alloc`、当前模型不重试；`rag` 画像计划 = primary `ollama-ornith` → fallback `ollama-phi3`，理由码 `CAPABILITY_MATCH/LOCAL_PREFERRED/HIGHER_PRIORITY`；出口体含 canary 278 字节；账本 19 列、禁存列零命中。诚实标注：这台机器上 ornith 的失败**由内存压力诱发**，不是模型自身固有缺陷——P0 要的是「primary 真失败 ⇒ 归类 ⇒ 真 fallback」这条链，成因写清即可。
Task 10: 环境处置（用户授权）：停 11 个闲置观测容器 + 修剪工作集 ⇒ **宿主层面无收益**（vmmemWSL 仍 2.03GB，实测可用从 2.10 掉到 1.78–2.0GB）；恢复清单 `container-stop-log.txt`。随后按用户「先使用本地已有的模型 / 继续」直接真跑 P0（结果见下条）。

Task 10: **P0 REAL-LLM-FAILOVER-001 真跑通过 = GREEN**（本机已有模型，未拉新模型、未打云、注册表一字未动）。10 枚断言全过，实测：primary `ornith-1.5:9b-text` 请求体 1619B / 41596ms / status=500 / `model_unavailable`（服务端原文 Vulkan 张量分配失败）→ fallback `phi3:mini` 1610B / 20033ms / status=200 真中文回答；`fallback_index=1`、trace_id 全链一致、`model_route` 九键两 attempt、临时账本恰好 1 行 19 列、canary 全列 0 命中、仓库真库 0 行。证据 `task10/real-llm-failover-001.json`；报告 `task-10-report.md`（段 A agent 中止未写，由主 agent 按证据补）。
Task 10: 反造假闸（T9 复审点名的洞）已落地并被我自己踩到两枚行为：默认收集数 0（`del` 类而非 `skipUnless`）、源码面零 skip 令牌、矩阵 P0 状态与证据 JSON 互锁、判据自身被四枚变异打。矩阵 P0 行已由我按 `green_permission()` 手写 **GREEN**（裸状态值；带 `**` 或说明文本会被 `MatrixDocumentClosureTests` 判红，单元格内不能有裸竖线）。
Task 10: Ruling(主 agent 裁，三条如实限定进 T11): ①**primary 的失败由内存压力诱发**（证据里 available 0.44 GiB / load 97%），链条成立但换台内存宽裕的机器十字前提会消失 ⇒ 复现条件写进验收文档；②runner 的内存门槛（floor 3.2 GiB ≈ phi3×1.6）判「不够」，实际靠 Ollama mmap 干净页跑通 ⇒ 门槛偏保守，建议 T11 之后调成 ×1.2，否则把能跑的真机验收挡在门外；③用例内 `config_overrides` 把 `llm_total_budget_ms` 打到 900000，**越出 §12 冻结区间 5000..120000**（测试进程内 patch，产品默认与 .env 未动，且证据里披露了 `frozen_range_note`）⇒ 本版不为此加配置键、不改 §12；但这暴露一条真实运维事实：**§12 的 30s/20s 预算装不下 2 GiB 模型冷加载**，T11 必须写成已知限制 + V2.4 建议（`keep_alive` 预热或真机验收专用预算档）。

Task 10: complete（P0 GREEN；全套件主 agent 亲跑 **950 passed / 0 failed / 992 subtests / 124.16s**，默认套件不收集真跑用例）。评审处置如实记：**未对 Task 10 单开评审 agent**，其闸的效力由我实测取得（我三次改矩阵状态单元格都被闸判红：带 `**` 的 GREEN、单元格内裸竖线、`***` 之外的说明文本），P0 证据链交 T11 终审一并复核（`review-task-11` 范围含 T10 产物）。
Task 11: 开工。范围=镜像重建 + compose 冒烟 + 前端构建复验 + 验收文档 `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md` + 终审（含 T10 产物）+ Rulings 汇总 + 未提交文件提醒。

Task 11: 容器层冒烟**通过**（证据 `task-11-smoke.md`）。镜像 `rag-backend:7b350b4d183d` 重建成功（前两次分别栽在 Debian 镜像 502 与 apt 卡死；期间我把 Docker 引擎拖挂了一次，已按你授权 `wsl --shutdown` + 重启恢复）。启动门：`Application startup complete` + `/api/health` 200 ⇒ `warmup_llm_router()` 的注册表 fail-fast 通过，并顺带证明 `COPY config ./config` 把 `llm_registry.json` 打进了镜像。观测面（容器内跑端点同一组合）：`router_enabled=True`、聚合 7 键 + `status`、白名单 13 枚、`providers={'ollama':{'healthy':True}}` 与 `breaker={'ollama':{'state':'closed'}}` **互不渗透（D4 成立）**、账本 0 行。`/api/system/status` 从宿主 curl = **401**（需 `system:operate`，鉴权未放宽）。

## Task 11 终局（V2.3 封版）

**Baseline**
- git HEAD `bc2085c`；工作树 106 条 `git status` 条目（未提交，用户决定）。
- 镜像 `rag-backend:f5a2bc5e4651`（I-11-2 修复后重建）；Docker engine `29.7.2`（引擎曾于 22:37 挂死，按用户授权 `wsl --shutdown` + 重启恢复；容器恢复矩阵见 `container-restore-log.md`，只恢复 rag 的 qdrant+backend，另两项目交回各自会话）。
- **release 全套件 = 961 passed / 0 failed / 992 subtests / 90.70s**（`cd backend` 与仓库根两种 cwd 同数；106 是 git 条目数，绝不进测试台账）。
- docs 哈希：MATRIX `0829f2052526`（P0 单元格裸 GREEN）、DESIGN `49574e46f6f9`（§8.1/§9.1/§9.2）、ACCEPTANCE `92d3ebbceafa`；仓库真库 `backend/data/conversations.db` `39bca2c404e2`（`llm_request_logs` 0 行，测试零污染）。

**P0 Evidence（`task10/real-llm-failover-001.json`，sha1 `f043d2c773d4`）**
- `REAL-LLM-FAILOVER-001` = GREEN：ornith 真失败（500 / `model_unavailable` / 41596 ms / 请求体 1619 B）→ phi3 真成功（200 / 20033 ms / 1610 B）。
- 实际模型一致性（I-11-2 修复后）：`response.model_used == LLMResponse.model == llm_request_logs.model == phi3:mini`；`RoutePlan.primary` 仍 = `ornith-1.5:9b-text`（计划事实不被覆盖）；trace 成功 attempt.model = `phi3:mini`。
- trace_id 全链一致；usage 落库一致性（1 行 × 19 列，canary 0）；`unknown` 归零 SQL 由矩阵闸核。

**Known limitations**
- L1 no-capable status blindness（零候选全灭 ⇒ `requests_5m=0`、四比率 null、provider 仍绿）。
- L2 P0 evidence mutation weakness（`status_code` 等单字段可事后修饰；终审盘级 S3 绕闸实测在案）。
- L3 cloud live validation pending external credentials（C1–C4 `PENDING_EXTERNAL`；`/api/query/stream` 的 `done.model_used` 契约作用域已写进 DESIGN §9.2——该腿是缓冲生成、无 commit 边界，post-commit 规则归对话链真流式腿）。
- L4 `estimated_cost` 是观测估算非账单事实（云牌价仍是出厂占位）。

**Deferred → V2.4**：删 legacy 路径（连带 rag/agent 的 httpx 出口与 D6 豁免段）；no-capable 可观测性 + 归因枚举 `NO_CAPABLE_MODEL|ALL_CIRCUITS_OPEN|ALL_MODELS_DISABLED|PROVIDER_UNAVAILABLE`；证据多事实互锁；云对账与牌价校准；`env_file` 绝对化；m-7 degraded 键；`_classification_query` 收口；`audit.jsonl` 测试卫生。

**Task 11 收口链执行记录**：修复 agent 返回（960/0/992，6 发变异全杀）→ 我独立复跑 960 → 我补 §9.2 第 4 条「不扩散」契约测试 1 枚（变异注入 token 帧 ⇒ 红，还原 sha1 `2db326f08fdd` 一致）→ release 全套件 **961/0/992** → 镜像重建 `f5a2bc5e4651` + 容器冒烟（startup complete、`/api/health` 200、`/api/system/status` 401 未放宽、llm 块 8 键、providers/breaker 分离）→ P0 证据 sha1 与互锁闸回读（50 passed）→ 矩阵/验收文档终值 → 快照。**最终判定 ACCEPTED / RELEASE-CANDIDATE，V2.3 就此封版，不再顺手修。**

## V2.3 封版提交（用户裁定 ①，2026-09-25）
- commit `21498bc`，tree `a1497c86aef66829a7a8014a902b18deaef293a7`，作者 `duyu06 <152303443+duyu06@users.noreply.github.com>`（= 本仓既有身份，我用 `-c` 临时传入，**没有写 git config**）。
- 范围审计结论：`git add -A` 前逐条核过 106 条 ⇒ 其中确有一批**属于已验收但从未提交的飞书桥 / UI 中文化 / TypeSafe V2** 文件（V2.3 直接依赖它们，且同一批文件被多个计划交替修改、无中间提交 ⇒ 无法诚实地按标签拆开）。处置=**单一原子提交 + 提交正文里显式写出 provenance**，不伪装成"纯 V2.3 diff"。
- 排除并说明：`.superpowers/` 默认忽略（`*.tsbuildinfo` 同），仅以 `-f` 精选入库 SDD ledger、各任务 brief/report、评审与复审 findings、P0 runner 脚本、容器对账日志；快照树、baseline 树、变异 scratch 脚本与日志保持不入库（报告内逐轮可复核）。仓库根散件 `task-10-brief.md`（我早期误路径产物）已并回 SDD 目录内同名 brief 并删除。
- 结果：`git status --porcelain` = **0 条（clean）**；未 push、未打 tag（按裁定保留 `model-router-v2.3-rc1` 给后续云侧 live test 之后再决定，与"正式 release"语义分开）。
- 已知瑕疵（如实记，不擅自 amend）：commit message 末尾那行 `Co-authored-by:` 因带括号说明文字而**不是合法 trailer**，GitHub 可能按异常 co-author 渲染。要修需 `--amend` 重写这条未推送提交，等你点头再做。
