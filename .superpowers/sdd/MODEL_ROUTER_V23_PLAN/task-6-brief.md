
Modify `app/rag.py`：`generate_answer` 的 143–176 双分支 → `llm.complete(profile(mode="rag"), LLMRequest(...), trace_id=None)`；`except LLMError/NoCapableModelError` 沿用现"LLM 不可用回退原文"文案（行为不变）；`current_model_name()` 改经 router 默认候选解析（无 key 时 ollama 模型名不变）；`LLM_ROUTER_ENABLED=false` 保留旧分支原样（if 包裹）；probe 引用改 provider。测试：既有 `test_branding/test_p16/test_typesafe_*` 全绿 + 新用例断言响应 model 字段=RoutePlan primary。

## Task 2 评审移交项

- **温度必须显式携带（I-4，硬义务）**：`RAG_LEGACY_TEMPERATURE = 0.1` 的**单一出处在 `app/llm/__init__.py`**（Task 2 已把常量从 `normalize.py` 挪到包级别，`app/llm/__init__.py` 的 docstring 里写明了这条义务）。provider/normalize 两层刻意不注入默认温度，`LLMRequest.temperature` 的默认值是 Task 1 冻结的 **0.2**，于是 rag 链迁移时必须写成：

  ```python
  from app.llm import RAG_LEGACY_TEMPERATURE, LLMRequest
  req = LLMRequest(messages=..., temperature=RAG_LEGACY_TEMPERATURE, ...)
  ```

  漏掉 = 把 rag 链的采样温度从现网 0.1 静默改成 0.2（行为变更，不是重构）。
- **新增断言：双路 payload 的 temperature 等价**（迁移门闸，Task 6 的测试类里必须落一条）：对同一次问答，legacy 分支实际发出的请求体与 router 分支经 `normalize.openai_payload` / `normalize.ollama_payload` 构造出的请求体，其 `temperature`（Ollama 侧是 `options.temperature`）**逐字相等且等于 `RAG_LEGACY_TEMPERATURE`**。两条链都要覆盖（OpenAI 兼容 + Ollama），且 `LLM_ROUTER_ENABLED` true/false 双路各跑一次——这是矩阵 #18「legacy 回退三链原行为」在报文面上的等价证明，只看响应文本抓不到温度漂移。



## Task 5 评审移交项（复审 N4 + 裁定 C 的 §6 第 4 条；本任务的强制义务）

- **给执行面结果对象加 `plan`（+ `context_dropped`）末位可加字段**：`app/llm/fallback.py` 的
  `FallbackResult`、`StreamSummary`、`AllCandidatesFailedError` 各加 `plan: RoutePlan | None = None`，
  `AllCandidatesFailedError` **同时**加 `context_dropped: int = 0`（与另两对象同名同语义），由
  `run_complete` 与 `StreamSession.finish()` / 抛异常前填上。**禁止**改 `complete()/stream()` 的返回
  对象、**禁止**加回调参数（评审 C 否决了那两条：前者动返回形状，后者要三条链各自闭包传参、形状更容易漂）。
  frozen dataclass 的**末位带默认值** ⇒ T4 的 12 处构造断言不破；这是「九键里 `context_dropped` 在
  D2 降级路上恒为 0（哑键）」的唯一修法——那条路恰恰最需要解释。
- **trace 接线形状固定**：`attach_model_route(trace, result.plan, result, profile=profile)`。
  `model_route` 只许由 `app.llm.usage.model_route_trace()` 产出（九键），挂载点只许是
  `app.agent_trace.attach_model_route()`；**不得**引用已删除的 `llm.model_route_payload`，**不得**
  自己拼那个 dict，**不得**往 `trace["model_route"]` merge 别的返回值。
- **矩阵 #17 的「集成」半段归本任务**：补一条走**真** `llm.complete()` 的用例，断言落盘 trace 里
  `model_route` 九键齐备（attempts 非空 + 无 prompt/reasoning 字节）。Task 5 的
  `AgentTraceModelRouteSeamTests` 只覆盖纯函数 + JSONL 往返，**不能替你交 #17**。
- **写账义务（§8.1 第 2 条）**：任何 `success=False` 的行**必须**带 `error_type=kind`（或
  `kind:status`）；两种哨兵 `client_aborted`/`unknown` 由账本产出，链上自写会被退回 `unknown`。
