# Task 2 报告 — errors + normalize + provider（唯一出口成型）+ health probe 收编

状态：**完成（DONE_WITH_CONCERNS；疑虑全为移交项与 spec 字面带来的边角，见「需上层确认」）**

门槛达成：定向 `tests/test_model_router_v23_contract.py` = **114 passed / 149 subtests / 0 failed**
（Task 1 的 39 例 + 本任务新增 **75 例**，brief 要求 ≥18）；全套件
**521 passed, 13 warnings, 634 subtests passed, 0 failed**（基线 446/549 → 只增不减，+75/+85）。
无 git 写。`app/native_stream.py` 本任务**未动**（Task 7 迁移后再删）。

## 交付文件

| 文件 | 内容 |
| --- | --- |
| `backend/app/llm/errors.py`（新） | `LLMError(kind, status_code, message, *, no_fallback, provider)` + `retryable/fallback_allowed/is_config` 三个派生属性；`classify(status, body_text) -> LLMError\|None`（§6 三张表 + body 特征两组 + 未列码兜底）；`from_response()`（总有返回值版，供 200-with-error-body）；`from_exception()`（超时/连接 → retryable，HTTPStatusError → classify，ValueError → hard，LLMError 透传）；表常量 `RETRYABLE_STATUSES/CONFIG_STATUSES/HARD_RETRYABLE_STATUSES/MODEL_UNAVAILABLE_MARKERS/NO_FALLBACK_MARKERS` 全部公开可测 |
| `backend/app/llm/normalize.py`（新） | `ollama_payload` / `openai_payload`（+ 关键字 `stream=False`）、`parse_ollama_response` / `parse_openai_response`、`parse_openai_tool_calls`（两侧共用）、`ollama_stream_lines` / `openai_stream_lines`（增量 UTF-8 解码 + 行缓冲）、`RAG_LEGACY_TEMPERATURE=0.1`。**零 I/O、不 import httpx** |
| `backend/app/llm/provider.py`（新） | 全仓唯一 httpx 出口：`PROVIDERS` 分发表（ollama 原生 + openai/deepseek/qwen 兼容层，deepseek/qwen 共用一个 `OpenAICompat` 实例）、`complete(model, req, timeout)`、`stream(model, req, timeout)`、`probe(provider, timeout) -> ProbeResult`（健康端点的 URL 构造也在这里）、`effective_model_name()`、`_client()`（含 `_transport` 测试接缝）、`_Adapter.headers()`（openai 侧 Bearer，ollama 侧恒不发） |
| `backend/app/llm/health.py`（新） | probe 收编：`probe_ollama/probe_llm`（签名与 `(bool, str)` 返回形状不变）+ `_ollama_model_installed`（逐字平移）+ `provider_health_view(registry)`（60s 缓存，`{provider: {"healthy": bool}}`）+ `reset_health_cache()` + 可 patch 的 `_now()` |
| `backend/app/llm/registry.py`（改，仅新增） | 把 D1 解析体抽成 `credentials_for_provider(provider, *, label="")`，`provider_credentials(model)` 改为委托（消息文案不变）。见偏离 D-1 |
| `backend/app/llm/models.py`（改，仅新增字段） | `LLMResponse.usage_estimated: bool = False`（内存旗标，§8 的 19 列与 `UsageRecord` 一字未动）；`LLMRequest` docstring 补「温度由调用方携带」 |
| `backend/app/llm/__init__.py`（改） | 再导出 `LLMError / probe_llm / probe_ollama / provider_health_view`；**刻意不再导出** `provider.complete/stream`（Task 4 的 `llm.complete` 是业务唯一入口，包级别摆同名 provider 函数等于给业务递一条绕过路由的后门） |
| `backend/app/rag.py`（改） | 删 `probe_ollama / probe_llm / _ollama_model_installed`（迁走），`import httpx` 仍保留给 legacy `generate_answer`（Task 6 处理），并注明迁移去向 |
| `backend/app/main.py`、`app/main_agent.py`、`app/knowledge_os.py`（改 import） | `probe_llm/probe_ollama` 改从 `app.llm.health` 导入；路由函数体一字未改 |
| `backend/tests/test_runtime_metadata_contract.py`、`tests/test_runtime_usability_contract.py`（改） | 三条文本钉随迁到新文件 + 加了两条反向钉（rag.py 不再留第二份定义、health.py 不 import httpx）。见偏离 D-13 |
| `backend/tests/test_model_router_v23_contract.py`（追加） | 11 个测试类 / 75 例（Task 2 段），MockTransport 报文级 |

## 红 → 绿证据（5 处变异，全部被杀；改完还原后复跑全绿）

| # | 变异 | 结果 |
| --- | --- | --- |
| 1 | `CONFIG_STATUSES = frozenset()`（401/403 不再归 config） | **4 failed**（`test_auth_statuses_are_config_not_retryable` 两 subtest + `test_http_error_statuses_surface_as_classified_llmerror` 的 401/403 两个 subtest） |
| 2 | `effective_model_name()` 恒返回 `model.model`（override 失效） | **2 failed**（`test_model_override_replaces_the_requested_model`、`test_provider_response_without_model_echoes_the_effective_model`） |
| 3 | 删掉两条「未收到终止帧」的 `raise`（Ollama `done=true` / OpenAI `[DONE]`） | **2 failed**（`test_ollama_stream_without_done_is_an_error`、`test_openai_stream_without_done_marker_is_classified_not_silently_truncated`） |
| 4 | `ollama_payload` 改成「空 tools 省键」 | **2 failed**（`test_empty_tools_still_emits_the_tools_key_like_production`、`test_ollama_complete_request_line_is_single_egress`） |
| 5 | `OpenAICompat.headers()` 返回 `{}`（不发 Bearer） | **1 failed**（`test_openai_complete_sends_bearer_and_reads_usage`）——写实现时这条变异**先由测试抓到一次真实 bug**：初版 `OpenAICompat` 漏了 `headers()` 覆写，云端链会裸奔无鉴权头 |

还原后定向复跑 `114 passed / 149 subtests`；全套件复跑 `521 passed / 634 subtests / 0 failed`（75.85s）。
另一条独立红证据：迁移过程中 `test_runtime_metadata_contract` 与 `test_runtime_usability_contract`
先红（文本钉指向旧文件）→ 随迁后绿，说明「probe 真的搬家了」而不是复制了一份。
密钥扫描：新增/改动的 `app/llm/*` 与本测试文件对真 key 形态（`sk-`+16、长 Bearer）**0 命中**；
测试里只有 `sk-test-only-in-egress` / `should-be-ignored` 这类明显的假值。

## 测试构成（75 例 / 11 类）

- **错误分类**（`ErrorClassificationTests` 14）：retryable 六码逐码 + `RETRYABLE_STATUSES` 集合等式、
  401/403 ⇒ config 且 `fallback_allowed=True`（凭据独立的下一 provider 仍可用）、
  400/404/422 ⇒ hard 且**不重试当前**、四个 `model_unavailable` 特征（并钉
  `retryable=False`＝Task 4「不重试当前模型」的冻结项）、五个 NO_FALLBACK 特征、
  `model_unavailable` 优先于 `unsupported` 的 precedence、未列码两档（5xx retryable / 4xx hard）、
  2xx/3xx ⇒ None、`from_response(200,...)` 总有值、七种 httpx 超时/连接异常、
  HTTPStatusError 走表、malformed JSON ⇒ hard（矩阵 #8）、LLMError 透传、未知异常收敛、
  错误消息摘要截断且去换行（D3 日志面）。
- **Ollama 报文形状**（`OllamaPayloadShapeTests` 5）：与 `agent.py::_ollama_chat` **逐字段 + 逐键序**
  等式（`model/stream/think/keep_alive/messages/tools/options{temperature,num_predict}`）、
  `tools=[]` 仍发空数组（现网同形）、`think/keep_alive=None` ⇒ 整键省略（同时平移得动 rag 的形状）、
  `num_predict` 强制 int、构造报文不改写出入对象。
- **OpenAI 报文形状**（`OpenAIPayloadShapeTests` 3）：温度只从 `LLMRequest` 透传（0.1/0.2 两例）+
  `RAG_LEGACY_TEMPERATURE` 常量钉、空 tools 省键 / 有 tools 发送 / `num_predict→max_tokens`、
  流式带 `stream_options.include_usage`。
- **响应解析**（`ResponseParsingTests` 6 + `ToolCallStandardisationTests` 3）：usage 提取（含
  provider 回显 model 名优先）、Ollama `message/done_reason/prompt_eval_count`、
  两侧 usage 缺失 ⇒ 0 + `usage_estimated=True` 且**断言 `UsageRecord` 没有 estimated 字段**、
  非整数 token 视为缺失、`reasoning/reasoning_content` 不被读（D3）、缺 choices/message ⇒
  `LLMError(hard)` 且 Ollama 文案与现网 `RuntimeError` 一致、
  OpenAI 字符串 arguments → dict、Ollama 对象 arguments + 无 id ⇒ `""`、七种坏参数退化成 `{}`。
- **流式解析**（`StreamParsingTests` 9）：SSE delta 序 + `[DONE]` + 末尾 usage 块（含
  `include_usage` 的空 choices 帧）、注释/心跳/`event:` 行跳过、缺 `[DONE]` ⇒ retryable、
  Ollama NDJSON + done 行 eval_count、缺 `done=true` ⇒ 报错（与 `native_stream.py` 同语义）、
  200 里的 `{"error":"failed to load model"}` ⇒ `model_unavailable`、坏 JSON 行 ⇒ hard、
  **中文 UTF-8 跨包拆片**（按 1/2/3/7 字节与「正好切在汉字中间」四种喂法都不丢字）、
  半行 JSON 不进解析器。
- **provider 非流式**（`ProviderCompleteTests` 13，MockTransport）：Ollama 端到端请求行
  （URL/方法/无 Authorization/payload 全等式 + 响应解析）、OpenAI 端到端（URL + Bearer +
  content-type + usage）、`OLLAMA_API_KEY` 被误设也不外带、`model_override` 替换请求模型名、
  无回显时响应 model=替换后名字、未知 provider ⇒ hard + `no_fallback` 且**零请求**、
  缺 base_url ⇒ config 且零请求、openai 空 key ⇒ config 且**不发注定 401 的往返**、
  六个状态码经 `complete()` 的归类、500+alloc ⇒ `model_unavailable`（REAL-LLM-FAILOVER-001 前提）、
  连接失败 ⇒ retryable 且不泄漏 httpx 异常类型、timeout 透传、200-非 JSON ⇒ hard。
- **provider 流式**（`ProviderStreamTests` 5）：NDJSON 端到端 + `stream:true` 报文、
  MockTransport 每 3 字节切片的中文 SSE 端到端（证明拆包处理在真链路上成立）、
  **惰性边界**（分发/凭据错误在调用 `stream()` 时就抛、HTTP 错误在第一次 `next()` 才抛）、
  503 在第一次迭代时归类、流内 error 帧归类。
- **health**（`HealthProbeTests` 8 + `ProviderHealthViewTests` 7）：`probe_ollama` 三态
  （命中/未安装/连接失败摘要含 `ConnectError:` 类名）、无冒号 tag 匹配、
  `probe_llm` 两分支与 openai `/models` + Bearer、默认 timeout=2.5 的签名钉、
  **`/api/health` 两个入口的消费形状等式**（`main.health()` 七键逐字等式 + `yaoke_health()`
  的 llm_*/agent_llm_*/legacy_rag_* 语义）、health view 的 `{provider:{"healthy":bool}}` 形状、
  provider 粒度而非模型粒度、只探 enabled 条目的 provider、
  **缓存命中不外呼（1 次请求）**、TTL 到点重探（patch `_now`，不睡 60s）、
  `reset_health_cache()` 强制刷新、不可达 ⇒ `{"healthy": False}` 而不抛。
- **D6 结构护栏**（`SingleEgressStructureTests` 2）：AST 级——`app/llm/` 内只有 `provider.py`
  import httpx；非 docstring 的字符串常量与属性名里，endpoint 路径（`/api/chat`
  `/chat/completions` `/api/tags` `/models`）与 `ollama_base_url/openai_base_url`
  只允许出现在 `provider.py`（这是 Task 9 全文扫描的前置内部版，且**不会因写文档而变红**）。

## 偏离与自裁决（brief 之外）

- **D-1（改了 Task 1 的文件，纯新增）**：`registry.py` 加公开函数
  `credentials_for_provider(provider, *, label="")`，`provider_credentials(model)` 委托它。
  原因：provider/health 只有 provider 名（probe 没有注册表条目），而
  `ModelDefinition.model` 是 `min_length=1` ——「伪造一条载体条目」直接过不了校验，
  硬造只会往 provider.py 里塞假数据。Task 1 的 8 个凭据用例与 base_url 错误文案**逐字未动**（全套件已证）。
- **D-2**：`errors.py` 不 import httpx，`from_exception` 按 **MRO 类名**识别 httpx 异常族
  （`_TIMEOUT_CLASS_NAMES` / `_TRANSPORT_CLASS_NAMES`）。任务要求「app/llm 内仅 provider.py 出现
  httpx」，而 brief 又要求 `from_exception` 认 httpx 超时/连接 ⇒ 只能用名字识别。
  代价：理论上非 httpx 的同名异常会走同一分支（都是 retryable，影响面可忽略）。
- **D-3**：两个 `*_stream_lines` 的入参是「bytes 分片可迭代对象，或任何带 `iter_bytes()` 的响应」
  （参数名 `source`，brief 写的是 `resp`）。provider 直接传 `httpx.Response`；测试传
  `[b"...", b"..."]`。这是 D-2 的另一面：把 httpx 类型从 normalize 的签名里赶出去。
- **D-4**：`LLMResponse.usage_estimated: bool=False`。§8 的 19 列冻结 ⇒ 旗标只能在内存；
  命名避开 `estimated_cost`（那是牌价成本，两个 concept 混词迟早出 accounting bug）。
  流式侧同义信息在 `LLMChunk.usage["estimated"]`。
- **D-5**：未知 provider ⇒ `LLMError(kind="hard", no_fallback=True)`（brief 的 hard_terminal）。
  后果需 Task 4 知晓：**一个拼错的 provider 名会终止整条链**（而不是静默套协议），
  所以业务层必须把它落到既有兜底文案，不得 500（D2 那条线）。
  同时 deepseek/qwen 出厂即登记为 OpenAI 兼容，不然它们一上路就撞这条终止。
- **D-6**：`openai_payload` 的 `num_predict→max_tokens`、流式的 `stream_options.include_usage`
  都是 brief 未列的**归一化加法**（不加就拿不到末尾 usage 帧，§8 记账会静默失效）。
  个别兼容网关若不认 `stream_options` 需在其条目上关；本版无该旗标位（Task 10 云厂商实测再裁决）。
- **D-7**：`think/keep_alive is None` ⇒ **整键省略**，而不是恒发 `false`/默认值。
  这样一个函数同时平移 `agent.py`（恒发两键）与 `rag.py` legacy（两键都不发）两种现网形状。
- **D-8**：温度对齐 rag 现值 0.1 的落点是**调用方携带**（本层不注入默认，`LLMRequest` 默认仍是
  Task 1 冻结的 0.2）。`normalize.RAG_LEGACY_TEMPERATURE = 0.1` 只是把「对齐现值」这件事留一个出处，
  Task 6 迁移时必须 `LLMRequest(temperature=0.1)`；否则 rag 链的采样温度会被悄悄改成 0.2。
- **D-9**：probe 的 detail 文本只有一处分支变了：「200 但 body 不是 JSON 对象」
  （legacy 会吐 `AttributeError: 'list' object has no attribute 'get'` 这种摘要）。
  连接失败 / 非 2xx / 未安装模型三类文案逐字不变，且都被 `assertEqual`/`startswith` 钉住。
- **D-10**：`provider_health_view` 的 `healthy` = **端点可达**（不是「模型已装」），
  且只覆盖 `enabled=True` 条目的 provider。D4 的熔断粒度就是 provider，
  模型加载失败由 §6 `model_unavailable` + Task 4 降级承接；探未启用 provider 是白打网络。
- **D-11**：`classify` 的未列码兜底（5xx retryable / 4xx hard）与 `from_response` 这层
  「总有返回值」的包装是 brief 没写的**完备性补齐**：不补就会有一批状态码归到 None ⇒
  被当成「没有错误」而把坏响应喂给解析器。
- **D-12**：brief 只点名 `rag.py` 与 `knowledge_os.py` 改 import，实际还改了 `main.py` 与
  `main_agent.py`（它们本来就从 `app.rag` 拿 probe）。我**没有**在 rag.py 留
  再导出：那会让「两条 import 路径指向同一个 probe」成为长期口径债。
- **D-13**：两条既有静态文本钉（`def probe_ollama`、`def _ollama_model_installed` 等）从
  rag.py 改指 health.py，并新增反向钉（rag.py 不得再留定义、health.py 不得 import httpx）。
  强度只增不减；`assertNotIn("import httpx", health)` 用「import」而不是「httpx」，
  因为 health.py 的 docstring 里要说明 legacy 违例长什么样。
- **D-14**：`stream()` 的惰性边界是**契约**不是实现细节（分发/凭据错误早抛、HTTP 错误在第一次
  `next()` 抛）——否则矩阵 #10 的「pre-commit 静默换模型」做不到。已在 docstring + 两条用例钉住。
- **D-15**：`parse_openai_tool_calls` 被两侧共用（brief 只列了这个名字）：两个协议的
  `tool_calls` 数组形状一致，差异只在 arguments 是字符串（OpenAI）还是对象（Ollama 新版），
  `_arguments()` 两边都吃。Ollama 不回 id ⇒ `ToolCall.id=""`（Task 8 不得假设唯一 id）。

## 移交下一任务（handoff）

- **→ Task 3（classifier + router）**：`health.provider_health_view(registry)` 就是 §5 health 段的
  输入；`RoutePlan` 用的 `ModelDefinition` 与 provider 层同源，`enabled` 已是生效值。
- **→ Task 4（fallback）**：三个可依赖的事实。
  (1) `LLMError.kind/no_fallback/retryable/fallback_allowed/is_config` 已把「重试当前 /
  换候选 / 跳同 provider / 终止」四档判定做完，`model_unavailable.retryable is False`
  就是「不重试当前」的冻结项；
  (2) `stream()` 的惰性边界（D-14）决定 commit 前失败的可见性；
  (3) `provider._transport` 是唯一的 MockTransport 注入点，别在测试里 monkeypatch httpx 本身。
  预算/超时是 `complete(model, req, timeout)` 的第三个位置参数（**秒**）。
- **→ Task 5（usage/观测）**：`LLMResponse.usage_estimated` 与 `LLMChunk.usage["estimated"]`
  是内存旗标，§8 无对应列（要落库须用户裁决）；`health.reset_health_cache()` 供 status 用例复位。
- **→ Task 6（RAG 迁移）**：`LLMRequest` 必须显式带 `temperature=0.1`
  （`normalize.RAG_LEGACY_TEMPERATURE`），Ollama 侧 `think/keep_alive/num_predict` 留 None 才能
  保持 legacy 报文形状（provider 层不会替你补）。
- **→ Task 8（Agent 迁移）**：`ollama_payload(req, model, stream=False)` 与现网
  `agent.py::_ollama_chat` 的报文**等式已被测试钉住**，迁移时把 settings 的
  think/keep_alive/num_predict 灌进 `LLMRequest` 即可；回填 message-dict 时注意
  Ollama 的 `ToolCall.id` 是空串。
- **→ Task 9（单一出口扫描）**：`app/llm/` 内部的两条结构护栏已在
  `SingleEgressStructureTests`，扩展到 `app/` 全目录时可直接复用 `_docstring_nodes()`
  （把散文与出口代码分开，避免「改文档就变红」）。`rag.py::generate_answer` 里
  legacy 的 `/api/chat` 与 `settings.openai_api_key` 仍在（Task 6 消除），届时需要
  legacy 豁免清单还是「Task 6 先落地」请上层定顺序。
- **→ Task 10（真实 failover）**：`MODEL_UNAVAILABLE_MARKERS` 是 spec 字面四枚
  （`alloc` / `failed to load` / `model not found` / `no such model`）。Ollama 真实的
  404 文案是 `model "x" not found`（模型名带引号夹在中间），**不会**命中
  `model not found` ⇒ 会归成 404=hard（仍可 fallback，结果正确，只是 kind 不是
  `model_unavailable`）。实测后若要把 404 也归成 model_unavailable，需要加特征而不是改表。

## 需上层确认（不阻断，均按 spec 字面实现）

1. **`classify` 的 body 特征 precedence**：我判 `model_unavailable` 组优先于 NO_FALLBACK 组
   （理由：Ollama 加载失败文案里常混 `unsupported` 字样，那是「换模型」不是「请求不合法」）。
   spec §6 只列了两组特征，没写谁先。若评审认为硬终态应压过一切，我改一行 + 改一条用例。
2. **`alloc` 这枚特征过宽**（`allocation` 之类会误命中 `model_unavailable`）。spec 冻结了
   特征集合，我按字面实现并加了 precedence 说明；是否收紧成 `cannot alloc|failed to alloc`
   需要裁决（改 spec 而不是改实现）。
3. **未知 provider ⇒ NO_FALLBACK** 的行为后果（D-5）：注册表里一个拼错的 provider 名会让整条
   请求终止而不是降级到别的候选。我按 brief 字面实现并显式登记了 deepseek/qwen。
   若希望「未登记 provider 一律按 OpenAI 兼容试一次」，那是 spec 变更。
4. **每 attempt 新建 `httpx.Client`**（不共享连接池）：`_client()` 的注释说明了取舍
   （timeout/headers 随 attempt 变 vs 连接复用收益）。Task 10/11 若量到 TLS 握手开销，
   再决定是否上「按 provider 缓存 Client」。
5. `from_exception` 对**未知异常**给 `hard`（可 fallback）：好处是执行器只会收到 `LLMError`、
   §10 的 error_type 归因不失真；代价是代码 bug 会被降级而不是崩出来。消息里保留了
   `{异常类名}` 以便定位。是否接受，请评审点头。

## Fix round 1

状态：**评审 4 Important + 3 Minor 全部处理**（I-1/I-2/I-3/I-4/M-5/M-6 落地并有用例；M-7 按裁决
「不修、记移交」写进 task-5-brief.md）。门槛达成：定向
`tests/test_model_router_v23_contract.py` = **122 passed / 164 subtests / 0 failed**
（修前 114/149，新增 8 例全部逐条对应修复项）；全套件
**529 passed / 649 subtests / 0 failed**（基线 521 只增不减，+8）。无 git 写、无子代理。
定向 122 高于门槛 118±：多出的 1 例是 M-5 的全文扫描结构护栏（下面 D-16），刻意保留。

### 逐项

| 项 | 落点 | 改动 | 新用例 |
| --- | --- | --- | --- |
| **I-1** | `app/llm/errors.py:classify` | `CONFIG_STATUSES`（401/403）判定**前置**到两组 body 特征之前（原第 3 步的 `if status in CONFIG_STATUSES` 删除），`classify` docstring 的判定顺序重写为 5 步并把矩阵 #7 的理由写在第 1 条 | `test_config_status_is_decided_before_any_body_marker`（401/403 × 三枚 body：`The region is unsupported...` / `no such model for this key` / `cannot alloc ...`，钉 kind=config、`no_fallback=False`、`fallback_allowed=True`、消息仍含原文摘要） |
| **I-2** | `app/llm/errors.py` | 新增 `MODEL_UNAVAILABLE_PATTERNS`（窄正则，`__all__` 公开）+ `_first_pattern_hit()`；**冻结四枚字面 `MODEL_UNAVAILABLE_MARKERS` 一字未动**（用例里用元组等式钉住）；正则命中片段经 `_excerpt(…, 80)` 压平后才进消息（D3） | `test_quoted_model_name_not_found_is_model_unavailable`（`model 'x' not found` / `model "x" not found` / JSON 转义体 / 跨行片段 × 404 与 500 全归 model_unavailable，且 `retryable=False`）＋ `test_quoted_model_regex_leaves_other_not_found_shapes_alone`（`Invalid parameter: 'tool_choice' not found in schema` 400 仍 hard 可 fallback；`404 page not found` 仍 non-retryable-hard）＋ `test_real_ollama_404_model_not_found_body_is_model_unavailable`（经 `complete()` 的端到端面） |
| **I-3** | `app/llm/provider.py` + `app/llm/registry.py` | provider 公开 `SUPPORTED_PROVIDERS = frozenset(PROVIDERS)`（键集投影，`__all__` + 模块 docstring 已登记）；registry 新增公开 `validate_registry(registry, *, supported_providers=…)`，违规抛 `RegistryError` 且消息含「条目 id→provider 名 + 可用分发面」；`warmup()` 在 `get_registry()` 之后**函数体内** `from app.llm import provider` 再校验（`provider→registry` 是编译期依赖，反向只在运行期取一次常量 ⇒ 无环；也因此校验不能落进 `load_registry`）。`app/llm/__init__.py` 的 `warmup` 是同一对象（用例断言 `registry_module.warmup is llm.warmup` 的等价面：包级 `__doc__` 写明「只再导出、不包一层」，两条路径强度相同） | `test_warmup_rejects_enabled_entry_with_unregistered_provider`（`deepseek_chat` 这种 schema 合法却没登记的名字由校验拦下；评审字面的 `deepseek-chat` 带连字符先死在模型层模式，warmup 同样抛 ⇒ 两条路都不放行）＋ `test_warmup_accepts_every_registered_provider_name`（ollama/openai/qwen/deepseek 四条真 enabled 全过 + 出厂 5 条目全过）＋ `test_validate_registry_is_the_public_seam_and_skips_disabled_entries`（注入面、enabled=False 跳过、空键集全违规、`SUPPORTED_PROVIDERS == frozenset(PROVIDERS)`） |
| **I-4** | `app/llm/__init__.py`（单一出处）← `normalize.py`（删除） | `RAG_LEGACY_TEMPERATURE = 0.1` 从 normalize 挪到包级别并入 `__all__`；包 docstring 新段写明「**Task 6 必须以该常量构造 LLMRequest**（`LLMRequest(temperature=RAG_LEGACY_TEMPERATURE)`），漏掉=把 rag 链温度从 0.1 静默改成 0.2」；normalize 只留指向包级常量的散文说明。「双路 payload temperature 等价」义务已**追加进 `task-6-brief.md` 末尾新增的「## Task 2 评审移交项」节**（含写法与 OpenAI+Ollama 两侧、flag 双路各跑一次的口径） | 改造 `test_payload_carries_temperature_from_the_request_not_a_layer_default`：`llm.RAG_LEGACY_TEMPERATURE==0.1` + 在 `__all__` + 在包 `__doc__`、`hasattr(normalize, …)` 必须为 False（防第二出处复活）、两侧 payload 温度透传（Ollama 侧 `options.temperature` 也补了一针） |
| **M-5** | `app/llm/normalize.py` docstring ×2 + 结构用例 + `task-9-brief.md` | `ollama_payload` / `openai_payload` 的 docstring 去掉字面 `/api/chat`、`/chat/completions`（改「Ollama 聊天端点 / OpenAI 兼容聊天端点」，并注明「路径字面量只在 provider.py」的原因）；`app/llm/` 非 provider 文件对 6 枚 forbidden literal **全文零命中**（实测扫描输出为空）。task-9-brief.md 末尾追加「## Task 2 评审移交项（M-5）」两行：豁免清单必须含 `app/identity/feishu_client.py`（httpx 非 LLM 出口，实测 4 命中），并记全 `app/agent.py`(2)/`app/native_stream.py`(2)/`errors.py`/`normalize.py`/`health.py` 的散文类命中口径 | 新增 D-16 用例（见下行） |
| **M-6** | `app/llm/normalize.py:openai_stream_lines` | docstring 补一段：「流式工具增量（`delta.tool_calls`）暂不解析，`LLMChunk` 也不带 tool_calls 字段——Task 7 之前不得出现 tools+stream 的组合」 | —（口径说明，无可断言行为） |
| **M-7** | 不改代码 | 按裁决记移交：`task-5-brief.md` 末尾新增「## Task 2 评审移交项」——`error_type` 只存 `kind`（可带 `:no_fallback`）与 `status_code`，**不存 `str(LLMError)`**（消息含 provider 回显摘要，属 D3/§8 禁存面且会随文案漂移），并给出 canary 反测试写法 | — |

### 变异证据（本轮 3 发，全被杀；跑完逐一还原并复跑全绿）

| # | 变异 | 结果 |
| --- | --- | --- |
| 6 | I-1 **前置撤销**：`CONFIG_STATUSES` 判断挪回 body 特征之后（即修复前的顺序） | **1 例红（6 subtest 全红）**：`test_config_status_is_decided_before_any_body_marker`（401/403 × 3 body 全部落到 `hard(no_fallback)`/`model_unavailable`）。既有 `test_auth_statuses_are_config_not_retryable`（body=`invalid api key`，无特征）**保持绿** ⇒ 只有新用例能杀这个变异，正是 §10 矩阵 #7 要钉的那一格 |
| 7 | I-2 **正则撤销**：`MODEL_UNAVAILABLE_PATTERNS = ()`（等于不增补） | **9 红**：`test_quoted_model_name_not_found_is_model_unavailable` 8 个 subtest（四形态 × 404/500）+ 端到端 `test_real_ollama_404_model_not_found_body_is_model_unavailable`。两枚反向钉（`test_quoted_model_regex_leaves_other_not_found_shapes_alone`）保持绿 ⇒ 证明它们钉的是「不吃进」而非「吃进」 |
| 8 | I-3 附加变异：`warmup()` 里注释掉 `validate_registry(...)` | **1 红**：`test_warmup_rejects_enabled_entry_with_unregistered_provider`（`RegistryError not raised`），另两例（正例/注入面）保持绿 |

还原后复跑：定向 **122 passed / 164 subtests / 0 failed**，全套件 **529 passed / 649 subtests / 0 failed**（74s）。
D6 扫描复扫：`app/llm/` 非 `provider.py` 文件对 `/api/chat|/chat/completions|/api/tags|/models|ollama_base_url|openai_base_url` **全文 0 命中**（含 docstring/注释）。

### 新增偏离与自裁决（本轮）

- **D-16（测试补强，非 brief 要求）**：`SingleEgressStructureTests` 增
  `test_endpoint_literals_are_absent_from_non_provider_files_in_full_text`——原有那条按 AST
  跳过 docstring（改文档不该变红），但 **Task 9 的扫描是全文 rg**，两条口径不同。新用例把
  「`app/llm/` 非 provider 文件全文零命中」钉死，正是 M-5 的验收面；顺带
  `assertGreater(scanned, 4)` 防空跑。定向门槛 118± 因此落在 122。
- **D-17（I-2 的正则比评审给的字面多一个 `\\?`）**：评审给的
  `r"model\s+['\"][^'\"]{1,128}['\"]\s+not found"` 对**真机 HTTP body 打不中**——Ollama 回的是
  JSON，引号在字节流里是 `\"`，而 `classify` 收到的是原始响应文本（反斜杠在引号前面）。
  故实装为 `r"""model\s+\\?['"][^'"]{1,128}\\?['"]\s+not found"""`（引号前允许一个可选反斜杠），
  命中集是给定字面的**超集**，且两枚反向钉（`'tool_choice' not found in schema`、
  `404 page not found`）实测不命中。不加这三个字符，「真机 404 归 model_unavailable」只在对
  未转义字符串单测时成立，Task 10 的真链路上仍然不成立。
- **D-18（I-3 的两个后果需 Task 4/5 知晓）**：①`validate_registry` 只看 `enabled=True` 条目
  ——`external=True` 且无 key 的条目在解析层已被收成 False，其写错的 provider 名不触发启动失败
  （运行期也永远不会被选中，后果为零）；②校验发生在 `get_registry()` 之后，所以抛错时
  `_registry` **已装配**（与 load 失败「不留半份单例」不同），但 `warmup` 不 catch ⇒ 进程照旧起不来。
  用例按实际行为钉（`assertIsNotNone`）而不是粉饰成 None。
- **D-19（评审字面 `deepseek-chat` 的归类）**：该名带连字符，`ModelDefinition.provider` 的
  `^[a-z0-9_]+$` 在 load 阶段就拒（Task 1 冻结），所以它到不了 `validate_registry`。
  用例两种都钉（warmup 都抛），但**真正证明 I-3 生效的是** schema 合法却没登记的
  `deepseek_chat` / `moonshot`。注册表里的**条目 id** 确实叫 `deepseek-chat`（合法，id 无模式约束），
  它的 provider 是 `deepseek` ⇒ 出厂配置在新增校验下照过（已作为用例第二段钉住）。
- **历史文本**：本报告上文的 `normalize.RAG_LEGACY_TEMPERATURE`（交付文件表、D-8、→Task 6 段）
  自本轮起为**过时指向**，现行出处是 `app.llm.RAG_LEGACY_TEMPERATURE`；不改写历史，以本节为准。

### 修正后的移交（覆盖上文对应段落）

- **→ Task 6**：温度写法固定为 `LLMRequest(temperature=RAG_LEGACY_TEMPERATURE)`（从 `app.llm` 取，
  不再从 `normalize` 取）；「双路 payload temperature 等价」断言已进 `task-6-brief.md`。
- **→ Task 5**：`warmup()` 现在做「加载 + provider 分发面校验」两件事，lifespan 接线时不要
  再自己补一次校验；`error_type` 口径见 `task-5-brief.md`（M-7）。
- **→ Task 9**：豁免清单两行已进 `task-9-brief.md`（`app/identity/feishu_client.py` + 其余已知命中）。
- **→ Task 10**：上文「Ollama 真实 404 不会命中 `model not found`」的移交项**已闭合**——
  真机 404 形态现在归 `model_unavailable`（`retryable=False`、可 fallback），
  REAL-LLM-FAILOVER-001 若遇到的是「模型名写错」而不是「加载失败」，Task 4 拿到的仍是换候选信号。
- **→ Task 7**：`openai_stream_lines` 不解析 `delta.tool_calls`（M-6），SSE 迁移若要带工具的增量
  出参，必须先扩 `LLMChunk` 再放开 tools+stream 组合。
