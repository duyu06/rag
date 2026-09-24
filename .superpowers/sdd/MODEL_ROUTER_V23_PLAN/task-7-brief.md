
Modify `app/conversation_agent.py`：`token_sink is None` 分支→`llm.complete(mode="rag")`；流式分支→`run_stream`（ttft 记录点=首 chunk；`redact_text` 逐 chunk 保留；commit 由 StreamSession 提供；`StreamInterrupted`→现 error/done 事件 + payload `stream_committed:true`）；删除 `from app.native_stream import ollama_chat_stream` 并删除 `app/native_stream.py`（先 grep 全仓零其余引用）；`llm_ms/llm_calls/model_used` 语义不变（model 来自 selected）；legacy flag 分支保留原调用。测试：既有 SSE/stream 契约（`test_p17_streaming_contract` 等）不降强度 + commit 前/后两用例。


## Task 5 评审移交项（裁定 C 的 §6 第 5/7 条）

- **trace 接线**：流式路的 `model_route` 由 `attach_model_route(trace, summary.plan, summary, profile=profile)`
  产出（`summary = session.finish()`，`plan` 字段由 Task 6 加为末位可加字段）。九键唯一生产者
  `usage.model_route_trace()`；`StreamInterrupted` 那条路**也要挂**（它是最需要解释的一次离开）。
- **`stream_committed` 属 SSE payload**（D5），不属 trace 的 route 解释——别把它塞进 `model_route`。
- **写账义务**：commit 之后 provider 断流 ⇒ 账上的 `error_type` **仍是原始 kind**，不得留空
  （留空 + 有交付事实才会被认作 `client_aborted`）。补一条用例钉「provider 侧真实归类活过 commit」。
- **矩阵 #17 集成半段**归本任务：真 `llm.stream()` 跑通后断言 trace 九键齐备。
- **`StreamInterrupted` 不带 `plan`/`context_dropped`**（T6 评审 Minor 7）：commit 后中断那条路只有 `finish()` 能拿到执行面事实。若你的分支需要在 `except StreamInterrupted` 里挂 trace，**用 `finish()` 的结果**，不许自己拼 dict（九键唯一生产者 = `usage.model_route_trace`）；确实需要异常上带事实就先加末位可加字段，别复制构造。
- **测试隔离护栏已就位**（T6 修复轮）：`backend/tests/conftest.py` 会把 `CONVERSATION_DB_PATH` 兜底改道到会话临时目录，并有 `LedgerIsolationGuardTests` 钉「真实库 `llm_request_logs` 必须 0 行」。你新增夹具时**沿用**它，别在测试里往 `backend/data/` 写；`data/audit.jsonl` 目前仍会被别的任务追加（T6 只隔离了自己那一笔），若你触发审计写入就自行改道并报告。

## Task 6 复审移交项（**步骤 0：先修护栏，再做 SSE 迁移**）

- **N1**：`backend/tests/conftest.py` 现在把**只读**账本访问也判成「测试写进了真实库」
  （`usage._query → _connect(None)` 同样调 `database_path()`，实测纯 `aggregate_status()` 会被记一笔
  并在 teardown 打红，失败信息还一口咬定是「写」）。修法二选一：把「写」的判定挪到 `usage._execute`
  （写路径的唯一收口），或 `_REDIRECTS` 记 `(src, dst, kind)`、只有 `kind=="write"` 才逐例判红、读只出 warning。
  不修则你新增的 status/聚合用例会成批被误诊断。
- **N3**：护栏只认 `backend/data`，而默认值是**相对** `data/conversations.db` ⇒ 从非 `backend/` 目录跑时
  整层护栏失效、行落在 `<cwd>/data/`（实测），且仓库根那份历史 `data/conversations.db` 不在保护集。
  修法：相对路径同时按 `Path.cwd()/path`、`BACKEND_DIR/path`、`BACKEND_DIR.parent/path` 三候选判定，
  保护集加 `BACKEND_DIR.parent/"data"`。
