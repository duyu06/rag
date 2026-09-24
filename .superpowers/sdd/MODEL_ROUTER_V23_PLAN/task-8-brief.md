
Modify `app/agent.py`：`_ollama_chat` → 内部改 `llm.complete(mode="agent", needs_tools=bool(tools))`（think/num_predict/keep_alive 经 LLMRequest 透传；返回形状转现行 `message dict` 以最小化循环体 diff）；tool_calls 用 `LLMResponse.tool_calls` 标准化替换 `message.get("tool_calls")` 手写路径（`_tool_arguments` 保留兼容或删除——grep 使用后定）；`NoCapableModelError`→捕获→走 `_local_fast_path` 等价降级（现 local 模式分支复用），trace 记 `NO_CAPABLE_MODEL→fast_path` 注记；legacy flag 分支保留。测试：`test_agent_contracts/test_agent_routing_contracts` 17 例适配不降强度（评审逐条）+ 新 D2 降级用例。


## Task 7 评审移交项（开工前必读）

- **温度出处规则（DESIGN §9.1 已回写）**：agent 链 `_ollama_chat` 的现网采样温度 = **0.2**，与对话链同值、与 `rag.py` 的 0.1 **无关**。迁移时给本链用自己的命名常量（照 `CONVERSATION_LEGACY_TEMPERATURE` 的手法），**两腿都要有「调用面 kwargs 等式」钉**——只钉报文值挡不住漏参（T7 的 M3b 变异就是因为 `llm.stream` 形参默认同为 0.2 而存活）。
- **快照纳管**：T7 评审指出 `snap-task6/7` 都没管 `app/conversation_stream_routes.py` 与 `app/agent_routes.py`，导致 routes 层 delta 只能靠 mtime+推理归因（本轮靠 `git diff HEAD` 才反证清）。T8 起快照必须纳入这两个文件 + 你要动的每个 routes 文件。
- **变异脚本一律字节安全**：本项目已出两次事故（一次注释未还原 ⇒ 语法破损阻断 collection；一次文本模式把 LF 原生 `fallback.py` 翻成 CRLF ⇒ 943 行假差异会毒化 T9 的 D6 扫描）。读 `bytes`/`bytes.replace`/写 `bytes`，发内还原并打印 sha1。
- **测试护栏**：`backend/tests/conftest.py` 已把 `CONVERSATION_DB_PATH` 兜底改道 + 「写判定收口到 `usage._execute`/`_connect(ensure_schema)`」+ 逐例判红；你新增夹具沿用即可，**不许**往 `backend/data/` 或仓库根 `data/` 写。
- **SSE 出口有两条**：`conversation_stream_routes.py` 与 `agent_routes.py:90` 都传 `token_sink`，D5 payload 现在两支都有（T7 修复轮补的第二支）——agent 链迁移别再造第三条出口分支。
- **`NoCapableModelError` → fast-path 注记**：`NO_CAPABLE_MODEL` 不产账行（零外呼，T5 裁定），所以 trace 上的 `NO_CAPABLE_MODEL→fast_path` 是那条路**唯一**的解释出口；同时 `llm_calls` 在 pre-commit 静默换候选后仍记 1（对外语义不变），不许拿来估外呼次数（`attempts`/账本才是）。
