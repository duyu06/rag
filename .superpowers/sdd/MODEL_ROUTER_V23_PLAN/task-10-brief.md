
起宿主后端（backend/，env：LLM_ROUTER_ENABLED=true、registry 默认、qdrant 容器在、Ollama 在且 ornith-9b-text 保持未加载态）；跑 1 次真实 `/api/query/stream`：断言 spec §10 P0 十字（primary 404/500 真实发生、kind=model_unavailable、phi3 真实生成中文答案、fallback_index=1、usage 行、API 200、trace model_route attempts=2、prompt 零入库）；数字与日志证据存 task-10 报告段。若 ornith 意外可加载：`docker stop ollama`? 不允许——改用 registry 临时条目 model 改为不存在的 `ornith-1.5:9b-missing`（等效加载失败）并在报告注明等价性。


## T6 评审移交项（护栏兼容性，开工前必读）

- `backend/tests/conftest.py` 现在会在 `CONVERSATION_DB_PATH` 未设时兜底改道到会话临时目录，且
  `LedgerIsolationGuardTests` 钉「**仓库真实库** `backend/data/conversations.db` 的 `llm_request_logs`
  必须 0 行」。REAL-LLM-FAILOVER-001 是**真调用**（本机 Ollama：`ornith-1.5:9b-text` 真实加载失败 →
  `phi3:mini` 兜底），它的 usage 落库义务（10 断言里的「usage 落库」）必须落到**你显式指定的临时库**：
  跑之前 `export CONVERSATION_DB_PATH=<临时路径>` 或按 T5/T6 的姿势 `mock.patch.dict(os.environ, ...)`，
  断言读同一份 env。**不要**为了"看起来像生产"往 `backend/data/conversations.db` 写真账——那会让
  防回潮钉红，并把验收证据和测试数据混在一张表里。

## Task 9 复审移交项（T10 开工前必读，事后补记：本段的执行结果见 task-10-report.md）

- **步骤 0｜P0 承载闸反造假**（复审 §0b：`MatrixDocumentClosureTests` 只按 AST 核「例存在」，带
  `@unittest.skipUnless / skipIf / expectedFailure` 的例也算存在 ⇒ P0 转绿可被机器伪造）。
  要求：①给 P0 承载例（`REAL-LLM-FAILOVER-001`）加一枚**装饰器体检**断言（`getattr(fn, "__wrapped__", fn)` +
  源面扫 `skip`/`expectedFailure` ⇒ 存在即红）；②矩阵里 P0 行改 GREEN 的**唯一**许可 = 真跑通并留下
  执行证据（真请求字节数、真模型名、真耗时、落库行），**不许**靠 skip 让套件"绿"。
- **环境前置**：本机 Ollama 在跑（`ornith-1.5:9b-text` 5.63GB / `ornith-1.5:9b` / `phi3:mini` 2.18GB 三个
  条目都在），但**先探针再写用例**：若可用内存不足以真加载 phi3:mini，P0 结论是**环境 BLOCKED**，
  如实标 `BLOCKED`（不许标 PASS，也不许降标准改成 mock 冒充真调用）。
- **临时库姿势**：`conftest.py` 会在 `CONVERSATION_DB_PATH` 未设时兜底改道到会话临时目录；真调用落的
  usage 行必须落在**你显式指定的绝对路径临时库**里（DESIGN §8 的 19 列、`model_route` 九键、
  零 prompt 入库三条都要在那张表上核）。**不许**往 `backend/data/conversations.db` 写。
