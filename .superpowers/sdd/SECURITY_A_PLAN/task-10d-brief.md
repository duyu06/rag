# Task 10d — deferred minor 全量分诊（零结论即未完成）

Task 1–9 的评审与修复轮把当时不阻塞的次要项逐条登记进了台账：
`E:\xiangmu\rag\.superpowers\sdd\SECURITY_A_PLAN\progress.md`，标记是 **`minor (deferred)`**，
出现在这些行附近（用 grep 取全文，别照抄本简报的摘述）：**41, 56, 65, 80, 86, 91, 113, 128, 142, 189, 199**。
另有两条是复评移交、只存在于简报里的：**T10-9**（`docs/SECURITY_A_PLAN.md` 之后的
`task-10-brief.md` 末尾两格：管理员重置腿对不存在账号的 404 不写审计、canary 字面量不得抄进 `docs/**`）。

## 规矩：先量当前树，再给结论

**台账是历史，不是现状。** 本项目已经两次把"其实后续任务顺带闭合了的旧账"当成待办交下去
（`.env.example` 七枚键、写腿 `action="PASSWORD"` 都是这样）。所以每条的顺序必须是：

1. 读当前代码/测试，判这条**今天是否仍然成立**（成立 / 已被后续顺带闭合 / 描述已失真）；
2. 仍成立的，三选一并给证据：
   - **闭合**：改代码 + 补钉（或补一枚反向钉证明它抓得住退化），焦点门自跑；
   - **已知限制**：写进验收文档 L 系列的候选（给出一句话措辞 + 为什么不是缺陷 + 触发条件）；
   - **转 §18 后续登记**：给出一句话措辞（SEC-A 不做的事，谁做，为什么本轮不做）；
3. 已被顺带闭合的，给 `file:line` 证据并说明是哪一轮闭合的（不要重开修复）。

**判"闭合还是登记"的那条线**：会改变认证/口令/审计**语义或形状**的 → 不在本轮动（规格已冻结，动它
要用户裁定）；纯死代码、命名、重复片段、缺钉、注释失真 → 可以本轮闭合。凡是你认为"规格该改"的，
一律走 **NEEDS_CONTEXT** 报回来，不要自己动 `docs/SECURITY_A_*`。

## 建议优先处理的高价值项（其余按台账顺序）

- `configured_throttle()` 死代码（Task 8）；`auth.py` 按值绑 `pre_hash_throttle` ⇒ 打
  `login_throttle.pre_hash_throttle` 的测试会静默空转（这条是"未来会骗人"的那类，优先）。
- `_last_sweep` 用真实 monotonic 播种而 `allow(now=)` 接受注入时钟（注释记录了没拆雷 ⇒ 现在拆）。
- `_LEGACY_HEX` 拒大写却仍 `.lower()`（死代码）；新 AST 护栏漏收 `from app import config` 形态
  与 I1 扫描的两段链窄化（这两条都是**门的覆盖面**，优先级等同 Task 9 那发 Important）。
- 每个认证请求读两遍同一凭据行（Task 6 ①）：判它是"该并的性能形状"还是"该保留的两次独立判定"，
  给结论和理由，不要默默改。
- T10-9 第一格：管理员重置腿对不存在账号的 404 不写审计。判它是否属 §9.1 契约面；要补就只能补
  枚举 token + 用例，**不得**新增中文自由文本 detail。
- `LedgerGuard` 改名（Task 3）：调用点已经长大了，判"改名收益 vs 一次性 churn"，可以给"不改"的结论。
- `adoption_pct=0.0` 与 `OperationsView.tsx:132` 的 `2/0`（Task 4）：属前端展示层，SEC-A 不动前端
  ⇒ 预期结论是 §18 登记，但若你要动，先报 NEEDS_CONTEXT。

## 边界（硬性）

- 允许改：`backend/app/**`（除下列禁地）、`backend/tests/**`。
- **禁地**：`backend/app/llm/`、`backend/app/rag.py`、`backend/app/conversation_agent.py`、
  `backend/tests/test_real_llm_failover_acceptance.py`、egress 守卫的 D6 豁免计数、
  `docs/SECURITY_A_SPECIFICATION.md`、`docs/SECURITY_A_PLAN.md`、`frontend/**`。
- 无 git 写命令；不碰 `model-router-v2.3-rc1`；不写 `backend/data/`（真实库里现在是收敛完的 5 枚
  argon2id 行，是验收证据，别去"清理"它）；输出/报告/新增文件里不得出现明文口令或那 5 枚 legacy
  digest 字面量（closure 测试里那 5 枚**已有**的常量是唯一例外，别再加第二份）。
- 行尾按**每个文件现状**保持（`app/main.py`、`backend/.env.example` 是 CRLF；`app/cli.py` 等是 LF）。
  一次写操作只改一个文件。
- 每改一处就跑对应焦点门；**全部改完**再跑一次这五枚的合集（约 270 passed 是改动前的参照）：
  `tests/test_credentials_contract.py tests/test_authentication_leg_contract.py tests/test_password_lifecycle_contract.py tests/test_user_directory_contract.py tests/test_secret_hygiene_contract.py`。
  全套件（两 cwd 各 ~5 分钟）**不要跑**，另有安排。
- **不得为了变绿而放宽断言**、不得删测试、不得把门换成豁免表。测试数只增不减是本轮的自检线
  （若某条确实该消失，说明理由并等控制器裁，而不是删掉）。
- 扫描门是活的：新增/改动的交付文件若带出新的 `KEY="value"` 形状，`test_secret_hygiene_contract.py`
  会红。正确反应是**改掉那个形状**，不是往 `EXEMPTIONS` 里加行；真要加，必须在报告里写清"这一处
  为什么不是凭据材料"，并预期被复评挑战。
- **报告优先**：150 回合硬顶，撞上去过三次。第 30 回合前先建
  `E:\xiangmu\rag\.superpowers\sdd\SECURITY_A_PLAN\task-10d-report.md`（`PARTIAL` 头）并持续追加。

## 报告格式

一张分诊表，一行一条：`台账行 → 今天是否成立 → 结论（闭合/已知限制/§18/已顺带闭合）→ 证据或 file:line → 若闭合：红→绿的焦点命令与计数`。
最后：改动文件清单、每文件的行尾与 sha1 前后、测试计数变化（含归因）、你拒绝做的诱惑（看到但决定不动的东西，写出来）。

回报不超过 15 行：Status、表里各结论的数量（如 闭合 6 / 已知限制 3 / §18 4 / 已闭合 2）、一行测试摘要、
疑虑、报告路径。
