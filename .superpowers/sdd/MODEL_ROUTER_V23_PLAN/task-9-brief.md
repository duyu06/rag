
Create `tests/test_llm_egress_guard.py`（D6 扫描：`rg` 模式集 `/api/chat|/v1/chat/completions|OLLAMA_BASE_URL|_API_KEY|httpx.(post|stream)` 于 `app/`，豁免 provider.py+usage/probes 无调用例外清单以等式钉）；对照 spec §10 表逐项映射到已有测试，缺项补（预计：#9 完整 SSE、#16 providers healthy 形状、#17 trace 断言）。全套件绿。

## Task 2 评审移交项（M-5）

- 扫描豁免清单必须含 **`app/identity/feishu_client.py`**：它是飞书开放平台的 httpx 客户端（`import httpx` + `httpx.Client`，实测 4 处命中），**不是 LLM 出口**，D6 的「单一出口」只管模型调用，身份链路不得被卷进豁免争议——按文件级例外钉进清单，别用「整目录跳过」糊过去。
- 同一份清单还需记下这些已知命中，否则等式钉一上手就红：`app/agent.py`(2)、`app/native_stream.py`(2) 属 Task 7/8 迁移后消失的 legacy 出口；`app/llm/errors.py`、`app/llm/normalize.py`、`app/llm/health.py` 的 "httpx" 只出现在散文/异常类名清单里（三者的 AST 级「只有 provider.py import httpx」已由 `tests/test_model_router_v23_contract.py::SingleEgressStructureTests` 钉住，且 `app/llm/` 非 provider 文件对端点路径字面量已做到**全文零命中**，见 `test_endpoint_literals_are_absent_from_non_provider_files_in_full_text`），扫描要么按 `import httpx` 精确匹配、要么把这三条记进例外清单。



## Task 5 复审移交项（三件，都属静态扫描/回归口径族，正好与本任务同族）

- **N2｜防回潮源码级扫描的收紧**：`tests/test_llm_usage_contract.py::ModelRouteProducerUniquenessTests`
  的 `test_no_other_module_names_the_route_key_or_rebuilds_its_facts` 现在只认**双引号**字面量，且
  豁免按 `path.name` 比对（子目录里同名文件自动免检）。改法：谓词换成
  `re.search(r"[\"']selected_index[\"']", t) and re.search(r"[\"']context_dropped[\"']", t)`（键名那条同理），
  两个豁免集合存**相对路径**（`"app/agent_trace.py"` / `"app/llm/usage.py"`）与
  `path.relative_to(BACKEND_DIR).as_posix()` 比对；docstring 补一句「本钉只挡源码字面量，运行时注入
  由 #17 集成用例兜」。与本任务的 D6 扫描同族化（同一份文件枚举、同一份豁免结构）。
- **N3｜cwd 耦合的第二个形状**（不在 Task 5 改动面上）：
  `cd /e/xiangmu/rag && python -m pytest backend/tests/test_model_router_v23_contract.py -q`
  ⇒ `RouterSettingsTests::test_argless_settings_still_constructs_on_host_env` **1 failed**（Task 4 时代
  既有；该例故意用真 `Settings()`，而 `llm_registry_file` 默认是相对路径 `config/llm_registry.json`）。
  二选一：该例内 `monkeypatch.chdir(BACKEND_DIR)`（轻），或把出厂默认解析成**包相对**路径（会动 §12
  冻结默认值，需主 agent 裁定）。T9/T11 要么修掉，要么在验收文档里写明「全套件只在 `backend/` 下有效」。
- **`unknown` 的归因出口 = 库查询，不是 API 键**（V2.3 不加 `unknown_rate`，理由见 DESIGN §8.1 与
  复审意见：它与 `success_rate` 完全共线，信息增量 0，代价是第 14 枚白名单键 + 再一轮 §8.1 回写）。
  验收清单加一条：`SELECT count(*) FROM llm_request_logs WHERE error_type='unknown'` 在全部 mock 用例
  跑完后应为 **0**（有非零 = 某条链漏写 kind，属实现缺陷而非样本）。`aborted_rate`/`breaker` 两枚键
  与其余键同批钉「不许前缀放行」。

## Task 8 评审移交项（I-4：云 key 之后 agent 工具轮必然 400，修点在 llm 层，归 T9）

- **事实（T8 评审探针 P8，真 provider + 假 key + MockTransport）**：给 `openai` 条目配上 key 之后，agent 工具轮
  **第二轮**出口体是
  `{"role":"assistant","content":"","tool_calls":[{...,"function":{"name":"enterprise_search","arguments":{"query":"…"}}}]}`
  ⇒ ①`arguments` 是 **dict**，而 OpenAI chat-completions 要求 **JSON 字符串**；②工具回执是
  `{"role":"tool","tool_name":X}`（baseline 原码形状），**缺 `tool_call_id`**。真连必得 400（归类 hard/non-retryable）。
  Ollama 原生腿吃 dict，不受影响。
- **归属**：不是 agent.py 的实现错误——DESIGN §6 明写「Agent 只认内部模型（dict）」且「两侧差异全部在 provider 层吸收」；
  `app/llm/*` 在 T8 字节冻结。缺陷在 **请求侧映射**。
- **修法（T9 义务）**：`app/llm/normalize.py::openai_payload` 出口前把
  `messages[].tool_calls[].function.arguments` 的 dict `json.dumps(..., ensure_ascii=False)`；并把
  `{"role":"tool","tool_name":X}` 映射为 `{"role":"tool","tool_call_id":<对应 call id>}`。agent 侧消息回放形状不改。
- **验收**：矩阵 #12 现在只有单轮形状例，缺「**多轮回放**」半段 ⇒ 补一例断言第二轮出口的 `arguments` 是 `str`
  且工具回执带 `tool_call_id`（今天写出来会红，那正是它的价值）。
- **必须回给用户的一句话**：这推翻了「配一把 OPENAI_API_KEY 就能用 agent 工具轮」的短期替代方案——key 到位后
  工具轮在云侧仍会 400，直到 T9 这次映射修完。

## Task 8 修复轮复审移交项（N-3，与矩阵收口同族）

- **N-3｜降级腿的「本轮检索 FAILED」短路会丢弃前轮已到手证据**：`backend/app/agent.py:598-600` 在「前面工具轮
  已经拿到授权证据 + 本轮 `enterprise_search` 失败」时直接回「企业知识检索暂时失败…」，却同时报
  `num_sources=2` —— 与自家 `:601` 的理由（"证据已在手"）自相矛盾。今天 agent 工具链 100% 走 D2 fast path
  所以不显形；**一旦放开 `tools=true` 的模型（配 key 或新增条目），这就是常态路径**。
  判据要与权威实现对齐：`conversation_agent._local_fast_path` 那三支的条件是「本轮检索结果」还是「全链路在手证据」？
  对齐它，或在短路前加「`evidence` 非空则继续合成」的门。**必须补一例**钉「前轮有证据 + 本轮失败 ⇒ 不用失败文案
  糊掉在手证据（或至少 `num_sources` 与文案一致）」。
- **N-1 / N-2**（docstring 过强 / 报告行号 709→710）随终审 triage，不必单独修。
