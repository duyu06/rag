# V2.3-P0-EVIDENCE-PORTABILITY 简报 · 3B：把 P0 闸改为校验可移植证据包

**裁定**：用户 2026-09-28，台账 **R26** 第 ③ 条。**改的是证据表示层，不是验收事实层。**
3A 已产出 bundle（`docs/evidence/model-router-v23/real-llm-failover-001/`）并由控制器独立复核：
kit **481 增 0 删**、六枚文件 LF-only、零绝对路径、manifest 的 `source_run_dir` / `source_tree_hash`
/ `raw_provenance(4)` 字段齐备。

## 这一单要解决什么

现在这枚闸 `backend/tests/test_real_llm_failover_gate.py::P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence`
经由 `real_llm_failover_kit.validate_evidence()` **无条件重算 `files_sha1` 里的绝对路径**，
其中三枚目标位于 gitignored 的 `.superpowers/` ⇒ 干净签出必然 missing ⇒ 要求矩阵 `BLOCKED`
而矩阵写 `GREEN` ⇒ 远端恒红。远端实测：run `36436145777` 的 113 条红里这一枚独立成立。

**两个都不许走的出路**（用户在 R26 里写死）：
- 把 `.db` + trace 原件 `git add -f` 进仓库（运行态数据库/trace 工作文件变成长期发布物；
  还会新增一枚 `i/-text`，撞 B0 的 `test_non_text_index_entries_are_exactly_the_enumerated_set`）；
- 退回"验收 markdown 写 GREEN 就算 GREEN"（取消逐文件重算 hash 的反造假性；
  Task 5 已经有人这么改过并被正确回退，见 `task-5-report.md`）。

## 语义边界（判据，逐条钉死）

```
raw provenance 不在场        ⇒ 不影响 portable bundle 的校验（干净签出的正常形态）
portable 缺失 / 畸形 / hash 不配 ⇒ BLOCKED（闸要求矩阵写 BLOCKED）
portable 全通过 + 七条 interlock 成立 ⇒ 允许 GREEN
```

## 七条 interlock（CI 侧必须全部成立）

1. bundle 五枚 portable 件**全部存在**（`manifest.portable_files[].path`，相对**仓根**解析，
   不得相对 cwd——3A 报告明确记过：按 cwd 解析会假 DIFFER）。
2. 每条 `portable_files[].sha256` 与 `bytes` 当场重算相符；**manifest 自己也要被校验**
   （否则改 bundle 不改 manifest 就是 R26 里那条"改文件不更 hash"的漏洞）。
   ⇒ 用一枚独立于 manifest 之外的锚：**仓根 `docs/evidence/.../manifest.json` 的 sha256 钉进闸文件常量**，
   或在 `docs/ENTERPRISE_B0_*`/规格里落一枚外部锚。**二者取一并说明为什么。**
3. `response.model_used == ledger.row.model == 成功那枚 trace attempt.model == phi3:mini`
   （三处同源，字段路径 3A 已核：`answer.model`、`ledger.row.model`、
   `trace.model_route_attempts[1]` 且 `model_route_selected_index == 1`）。
4. 计划主模型 == `ornith-1.5:9b-text`（`attempts[0]`；`kit.PRIMARY_MODEL` 是既有常量，复用常量不复抄字面量）。
5. `primary-probe.json` 命中的是**文档化的 retryable / model-unavailable 失败**族
   （`validate_evidence` 已有的 `alloc` / `failed to load` / `model ... not found` 原文要求，一字不松）。
6. `trace_id` 在 `manifest` / `trace-attempts.json` / `ledger-row.json` 三处逐字符一致
   （真值 `p0-failover-6146ff1417d7`；顶层 `trace_id` 键在原始件里**不存在**，别再读它）。
7. 矩阵 P0 行状态 == 由 1–6 推出来的那个值（沿用现有"写死合法取值"的做法，不读 env、不读文档自述）。

## 反彩排件（这一条是本单最容易出事的地方）

控制器 2026-09-29 实测：`task10/rehearsal/run/20260924-214030/` 下有同名 `conversations.db`（**16384B**）
与 `agent_traces.jsonl`（**845B**），与真机那两份 **字节大小完全相同、sha1 不同**（`d981c1676e`/`d3cfc8b56c`
对真机 `b93ce392a1`/`356826f73d`），时间只差 12 分钟。仓库里另有 4 枚同名 db/jsonl（`data/`、
`rev6r1_mutation_lab/` 两处）。⇒

- **禁止按 basename 或大小定位原始件**；需要原始件时只能走 `manifest.source_run_dir` + `raw_provenance[].sha1` 双条件。
- 原始 JSON 的 `rehearsal` 真值判定（`validate_evidence` 已有"彩排件不许撑起 GREEN"这枚判据）**必须保留**，
  并额外要求 portable bundle 里带得出一个**非彩排**的正面凭据（例如 `provider_transport is None` 的事实被
  文本化进 `result.json` 或 `manifest`，而不是靠"读不到就算过"）。
- 必须有一发变异证明：把 bundle 的来源指向彩排 run dir ⇒ 闸红。

## 十枚断言与既有判据

`validate_evidence()` 的十枚断言、错误体 ≥20 字、canary 零命中、禁存列、
`completed is True`、`provider_transport is None` 等**一条都不许弱化或删除**。
可以把它拆成"portable 层"与"raw 层（在场才校验）"两个函数，但拆开后的合计判定强度必须 ≥ 现状，
并**逐条说明**哪条从"必须"变成"在场才必须"——这张映射表是独立评审要看的东西，别留给读者推。

## 八发变异（R26 指定，逐发必须红，且必须是**它该红的那枚门**红）

```
改 response.model_used              → 红
改 ledger.row.model                 → 红
改成功那枚 trace attempt 的 model    → 红
改 planned primary                  → 红
改 probe result（换成非文档化失败）   → 红
删掉一枚 portable 件                 → 红
改 portable 件但不更 manifest hash   → 红
矩阵 GREEN → BLOCKED                → 红
（+ 反彩排那一发：bundle 来源指向 rehearsal run dir → 红）
```

沿用 B0/SEC-A 的字节安全台纪律：anchor 恰好命中一次、`finally` 用读到的原字节还原、
sha + 外部 `cmp` 双核、判决必须**归因到指名节点**（`KILLED-ASSIGNED` / `KILLED-INCIDENTAL` /
`COLLECTION-BROKEN` 三态），不许再用"整模块 rc≠0 就算杀"。

## 硬约束

- **不做任何 git 写操作**。不 add / commit / push / checkout / reset / stash / config。
- 不动 `backend/app/**`、`.gitattributes`、`ci.yml`、两枚 tag、B0 的 `test_ci_gate_contract.py`
  （矩阵 `EXPECTED_COLLECTED` 当前 = **1335**；你若新增测试会改变收集数 ⇒ **停下报告**，别自己动常数）。
- 不弱化、不删、不 skip 任何既有断言。不得为了变绿而改 `docs/MODEL_ROUTER_V23_MATRIX.md` 的状态字。
- 不派子代理。**增量写报告**（本会话已有一次 150 回合上限事故与一次 `sed` 毁文件事故，都靠快照/`git show` 救回；
  别把证据只留在你脑子里）。
- 需要临时改 bundle 做证伪时：改前记 sha，`finally` 还原，还原后 `cmp` + sha 双核并在报告里贴原文。
  **绝不**在 `docs/evidence/` 留下改动后的文件。
- cp936 控制台：打印中文前先 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
- 全量套件 ~250s、`--collect-only` ~25–35s，定向模块 ~20–90s；给 Bash 足够 timeout（≤600000ms），
  不要让它超时后重跑。

## 验收读数（逐条取，不许引用本简报或前序报告）

1. 干净签出（`%TEMP%` 克隆 + `git checkout HEAD`）里 P0 闸**从红转绿**——这是本单的存在理由。
   注意：克隆必须包含 `docs/evidence/`；`git clone` 只带已跟踪文件，正好模拟 CI 形态。
2. 本机（raw 在场）同一条也绿，且 raw 层的校验确实执行了（打印它走了哪条分支）。
3. 八（九）发变异逐发 `KILLED-ASSIGNED` + 还原 `RESTORED-OK`。
4. `test_real_llm_failover_gate.py` 整模块绿；SEC-A 扫描门 46 passed 且**零新增豁免行**
   （`git diff` 那枚文件必须为空）。
5. 收集数 1335 不变（或如实报告变化）；B0 的 16 枚门仍 16 passed。
6. 全量套件两 cwd 各一次，逐格标 cwd 与 `.env` 状态。

## 交付物

`.superpowers/sdd/ENTERPRISE_B0_PLAN/p0-portability-3b-report.md`（增量写），含：
新闸代码、`validate_evidence` 拆分的**逐条映射表**（哪条从必须变成在场才校验，以及为什么这不算放宽）、
六条验收读数原文、九发变异台账、以及"独立评审必须重点看什么"的一段自我交底（不许写"应该没问题"）。

**完成后由控制器派独立评审**——本单涉及 P0 闸语义，按用户裁定不得自写自裁。
