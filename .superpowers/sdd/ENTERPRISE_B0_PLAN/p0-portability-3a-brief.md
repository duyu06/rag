# V2.3-P0-EVIDENCE-PORTABILITY 简报 · 3A：从原始真源导出可移植证据包

**裁定来源**：用户 2026-09-28，台账 **R26** 第 ③ 条。**本步不改任何判据语义**，只做"载体"：
把一次真机运行的原始产物**机械导出**为最小、文本化、可跟踪、干净签出可重算的证据包。

## 为什么必须现在做

远端主门 113 条红里有 1 条是 P0 闸：它无条件重算 `files_sha1` 里的**绝对路径**，而那四枚目标中三枚
落在 gitignored 的 `.superpowers/` 下 ⇒ 任何干净签出必然 `missing` ⇒ 闸要求矩阵写 `BLOCKED`，
矩阵写的是 `GREEN` ⇒ 恒红。**不批准的解法**：把 `.db` + trace 原件整体入库（把运行态数据库、trace 工作文件、
本机 probe 变成仓库长期发布物，还会新增一枚 `i/-text` 撞上 B0 §6.4 的枚举钉）；
也不批准退回"验收 markdown 说 GREEN 就算 GREEN"（那会取消逐文件重算 hash 的反造假性）。

**已验证事实（控制器 2026-09-28 本机量得，非推测）**：四枚原始件此刻仍在、且 **sha1 全部 MATCH 记录值**：

| 原始件 | 大小 |
| --- | --- |
| `run/20260924-215206/conversations.db` | 16384 B |
| `run/20260924-215206/agent_traces.jsonl` | 845 B |
| `task10/ornith-primary-load-probe.json` | 3010 B |
| `backend/tests/test_real_llm_failover_acceptance.py` | 40517 B（已跟踪） |

⇒ 今天导出的包仍能对真源负责；再拖就只剩 JSON 自己说话。

## 交付物

```
docs/evidence/model-router-v23/real-llm-failover-001/
├── result.json            # 十枚断言本体（逐枚 name/pass/observed/elapsed_ms）
├── response.json          # answer.* 全量（含 text）+ provider_calls 摘要
├── ledger-row.json        # ledger.row 原样 + canary_hits/canary_needles/禁存列证明
├── trace-attempts.json    # trace.model_route_attempts + selected_index + trace_id + stage/keys
├── primary-probe.json     # 原始 probe 的**文本化投影**（不是原文件路径引用）
└── manifest.json          # 见下
```

全部 **JSON / UTF-8 / LF / 末尾换行 / `ensure_ascii=False` / 缩进 2**。不许引入 `.db`、`.jsonl`、
图片或任何二进制 ⇒ 不能新增 `i/-text`（B0 的行尾枚举钉会红，那是对的，说明你越界了）。

### `manifest.json` 必须固定这些字段

```
evidence_schema_version   整数，本轮 = 1
case_id                   REAL-LLM-FAILOVER-001
generated_at              导出时刻（ISO8601，带时区）
source_run_generated_at   原始证据自己的 generated_at（2026-09-24T13:52:06+00:00），**不得丢**
trace_id                  p0-failover-6146ff1417d7（来自 trace.trace_id，与 ledger.row.trace_id 同源）
source_tree_hash          导出时被测代码树指纹：对 `git rev-parse HEAD` 的**依赖式记录**（见下）
release_image             见"环境字段"节
exported_by               导出函数标识 + 它读的原始件绝对路径的 **basename 列表**（不是绝对路径）
portable_files            [{ path, sha256, bytes }]   ← 干净签出必须可重算：这是 P0 判定事实
raw_provenance            [{ name, sha1, bytes, role }] ← 原始件 hash 只作 provenance；本体继续 ignored
```

`raw_provenance` 的 role 取 `ledger_db / trace_jsonl / primary_probe / acceptance_module`。
**绝对路径一律不得出现在任何导出文件里**（那是单机耦合的病根）；只留 basename + hash。

### 环境字段（`release_image` 等）——不许编

原始 JSON 里 `environment` / `plan` / `config_overrides` 有值就用，**没有就写 `null` 并在报告里点名**：
`trace_id`、`release_image` 在 `answer`/`ledger` 层是 `None` 还是缺失，你必须先读原始件再决定，
**不得**为了填满 manifest 而造一个镜像名。若原始件确无该事实，manifest 里就写 `null`，
并把"这个字段当时没被记录"作为一条 finding 交回控制器（这属于证据面缺口，不是导出脚本该圆场的事）。

## 实现位置（保持单一真源）

- 导出逻辑放 `backend/tests/real_llm_failover_kit.py`：新增 `build_portable_bundle(...) -> dict[str, str]`
  与 `write_portable_bundle(...) -> dict`（返回 manifest），
  并让**真机 runner 在跑完一次验收后调用它**——否则 bundle 会随时间失去可再生性。
  现有一次性回导可以走同一函数（不必另写 CLI；若你判断需要一枚 `scripts/` 入口，先报告再动）。
- **不改 `validate_evidence()`、不改 P0 闸的判定语义**。那是 3B 的活。本步产物先要被**能重算**，
  不是要被采信。
- 不修改原始 JSON、原始 `.db`、`.jsonl`、probe 文件（只读）。

## 硬约束

- **不做 git 写操作**（不 add/commit/push/checkout/reset/stash）。提交与推送由控制器统一执行。
- 不动 `backend/app/**`、`.gitattributes`、`ci.yml`、两枚 tag、B0 的 16 枚门文件。
  若你新增测试导致收集数变化 ⇒ **停下报告**，不要自己动 `EXPECTED_COLLECTED`（当前 = 1335）。
- 不派子代理。**增量写报告**，别最后一次性补（长会话会被截断，本会话已有一次 150 回合上限的事故）。
- 新文件落在 `docs/` 下 ⇒ 会进入 **SECA-20 扫描面**（面数 318 起涨是允许的，但命中数必须仍 = 16 文件 / 31 处）。
  若 bundle 里某段文本被扫描门判成凭据形状：**不要加豁免行、不要改文案规避**，停下报告——
  那意味着真机响应文本里有不该公开的东西，属于必须让控制器和用户知道的事。
- 报告与台账里凡引用"原始件在"必须附**当场重算**的 sha1 输出，不许引用本简报的表。

## 验收（逐条取读数）

1. `python -c` 重算四枚原始件 sha1 == 原始 JSON 记录值（MATCH×4 原文）。
2. 导出的六枚文件存在、LF-only（`CRLF 0`）、可 `json.loads`、无绝对路径（`grep -c 'E:\\\\'` = 0）。
3. `portable_files` 里每条 sha256 用**独立**一行 python 重算并全部相等。
4. `trace_id` 在 `manifest` / `trace-attempts.json` / `ledger-row.json` 三处逐字符一致。
5. 十枚断言在 `result.json` 里条数 = 10、逐枚 `pass=true`、`observed` 非空。
6. SEC-A 的 `test_real_llm_failover_gate.py` 与 `test_secret_hygiene_contract.py` 复跑：
   本步**预期 P0 闸仍红**（判据未改），但**不得新增任何红**；`test_secret_hygiene_contract.py` 必须仍 46 passed。
7. 全量套件 `--collect-only` 读数不变（=1335）；若你加了测试，报告并停下。

## 交付文件

`.superpowers/sdd/ENTERPRISE_B0_PLAN/p0-portability-3a-report.md`（增量写），内容含：上述 7 条读数原文、
每个 bundle 文件的字段来源映射（`bundle 字段 ← 原始 JSON 路径`，逐条）、
以及一段"哪些字段原始件里没有、因此写成 null"的诚实清单。
