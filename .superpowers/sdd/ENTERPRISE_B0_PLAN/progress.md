# SDD ledger — plan: docs/ENTERPRISE_B0_PLAN.md

工作区：`.superpowers/sdd/ENTERPRISE_B0_PLAN/`（由 `sdd-workspace` 解析；计划正文里写的
`.superpowers/sdd/ENTERPRISE_B0/` 是同一处的旧称，以本目录为准 —— 见 R0）。
规格权威：`docs/ENTERPRISE_B0_SPECIFICATION.md`。基线 commit `7cc5efc` = tag `security-a-rc1`。

## 执行环境裁定

- **R0 工作目录名**：计划正文 `.superpowers/sdd/ENTERPRISE_B0/` → 实际 `ENTERPRISE_B0_PLAN/`。
  理由：`sdd-workspace` 以 plan basename 建目录，且与 `SECURITY_A_PLAN/` 同族。代价：错则路径分裂成两处台账。
- **R1 `scripts/**` 禁令的边界**：Global Constraints 原写"不动 `scripts/**`"，与 Task 1 新建
  `scripts/b0_collection_probe.py` 直接冲突。裁定：**禁改既有交付脚本**（`deploy.ps1`、`scripts/*_integration.py`），
  **允许新增 B0 自有探针**。依据 SEC-A 先例（`sec_a_fresh_boot_probe.py`、`sec_a_smoke_http.py` 入库）。
  已回写计划正文。代价：若理解成"完全禁止"，Task 1 无法产出量法唯一实现，门会各写一套解析。
- **R2 不在 worktree、不提交**：本仓库既有规矩 = 主工作树 + 全程零提交（SEC-A 即如此），且 B0 的行尾钉读的是**真 index**
  （`git ls-files --eol`），另开 worktree 会让门量到另一棵树。用户 standing rule 优先于技能的 worktree 默认。
  代价：并发会话共享此树；缓解 = 每任务快照 + 聚合 sha。
- **R3 B0-12 判据重写**：`git status --porcelain -- backend/app` 基线**非空**（identity 两枚未提交项）。
  原判据"三条全空"会红在别人的改动上，并诱发"顺手提交它们"这种越界。改为 **基线 sha 对照**（Task 1 记，Task 5 校）。
- **R4 `test_backend_contracts_runs_the_pytest_suite` 的假绿**：原子串判据会被 SECA-20 那步
  （`python -m pytest backend/tests/test_secret_hygiene_contract.py`）命中 ⇒ 门在改造前就绿，
  而它要防的"主门被删"永远抓不到。改为 `python -m pytest backend/tests(?!/)` ⇒ 目录级调用才算。
  连带修正 Task 2 Step 7 的红/绿预期（红 5 / 绿 8，逐枚点名）。

## 派发前冲突扫描表

| 对 | 一方产出 vs 另一方消费 | 发现 | 处置 |
| --- | --- | --- | --- |
| T2 顺序钉 × T3 ci.yml | 钉要求 block 内含 `SECA-20` 与 `unittest` 两串；T3 删掉安装步名并新写注释 | T3 的新注释确实含这两串（"SECA-20 扫描步排在主门之前" / "原既有步 `python -m unittest discover…` 已删除"）⇒ 钉绿，但**靠字面巧合**。评审会当"只断言文字存在"的弱门 | 留给任务评审；已在 brief 里要求实现者额外断言"扫描步索引 < 主门索引"（若评审仍判弱，进修复轮） |
| T2 行尾三枚守卫 × 基线树 | 钉断言无 `i/crlf`、`i/-text` == 那三枚、`.sh`/`.ps1` 形态合规 | 三枚在**改造前就绿**（它们防回归不防迁移）⇒ Task 2 Step 7 原预期"四枚行尾钉红"错 | R4 连带修正：红 5 / 绿 8 逐枚点名 |
| T1 常数 1316 × T2 常数 1329 | T2 写 `EXPECTED_COLLECTED`，基线是 T1 的 1316 + 本文件 13 枚 | 一致（13 枚 = 计划里实际 `def test_` 枚数，已机器核过：定义 13 / 点名 13 / 幽灵 0） | 已在 spec 自审阶段修掉"14 枚含 1 枚幽灵"的错 |
| T3 Step 4 的 `-k` × T2 节点名 | `-k "…requirements_txt…"` 需命中 `test_install_face_uses_requirements_txt_as_the_source` | 命中（子串在节点名内）✓；`contracts/ordering/exemption/states_why` 亦各自命中 | 无需处置 |
| T4 Step 3 的 `-k` × 行尾钉 | `gitattributes or crlf or non_text or no_op` | 恰选 4 枚行尾钉 ✓ | 无 |
| T6 N3 × 两枚依赖钉 | N3 把 `-r backend/requirements.txt` 换成手写串 | 会同时杀 `…requirements_txt_as_the_source` 与豁免表钉（`pytest-fastapi-pydantic` 成未豁免包）⇒ 一发双杀 | 属预期，报告里注明双杀 |
| 各任务 × Global Constraints | 白名单 = ci.yml/.gitattributes/新门文件/新探针/docs/工作区 | 唯一冲突是 R1（`scripts/**`），已裁定并回写 | 已修 |

## 进度

- **R5 Task 1 Step 3 的四格矩阵实际只覆盖三格**：第一版那段 shell 里 `cd backend` 后又 `(cd .. && pytest backend/tests)`，
  测的是"仓库根 + 无 `.env`"（格 2 重复），而"backend + 无 `.env`"这一格从没测；且 `cd backend` 会让后续格串味。
  裁定：全部改成 `(cd backend && …)` 子 shell 形式，四格各自独立，并在 Expected 里要求"四格是四个不同的命令组合"。
  已回写计划正文。代价：不修则 B0-04 的"四格全绿"是三格，且 `.env` × cwd 的交互维度缺一个观测点。

- **Task 1：进行中（R6 修复轮 1 已完成，待独立评审）**。四格**收集轴与通过轴现已全等**：
  格 1/2/3/4 均 `1316 passed / 0 failed / rc=0`（格 2、4 用"挪出仓库"的正确手法重跑）。
  首轮的 `2 failed` 读数已被**标为 superseded 但保留**在报告里当证据；本行此前写作"通过轴不等"是旧判语，已按 R6 更正。
  证据：`task-1-report.md`（含《修复轮 1》与《门的敏感性证据》）、快照 `snap-task1-post/`、基线明细 `baseline/collected-node-ids.txt`、
  identity 两枚基线 sha `3bc681bbc52c` / `2cfab9f18182`（Task 5 Step 4 的对照源）。
- **R6 Step 3 的"仓库内改名 `.env` → `.env.bak`"会把 SEC-A 的门拖红（Task 1 实测发现）**：
  `.gitignore:6` 是精确路径 `backend/.env`，不匹配 `.env.bak` ⇒ 后者作为"未忽略的 untracked"
  进入 `test_secret_hygiene_contract.py:595 _delivery_surface_names()`（`git ls-files --cached --others --exclude-standard`）
  的扫描面，命中 2 处凭据形态字面量 ⇒ `test_repository_tracked_files_hold_no_credential_material`
  与 `test_the_exemption_table_matches_the_hit_set` 双双红。
  **归因已闭环**：把 `.env` 挪出仓库（不留树内副本）复量，cwd=根 与 cwd=backend 两格都 `1316 passed / rc=0`，
  与在场版同值 ⇒ `.env` 维度对结果中性，两枚红纯由测量残留造成。
  后果：brief Task 1 Step 3 的 Expected"四格 `failed=0`"按其现写法**不可能成立**；且 CI 里 `backend/.env`
  从来不存在（gitignored），真实 CI 形态 = 挪出仓库那格。
  待裁定（Task 2/3 之前）：B0 若还要复量 env 缺席，改名目标必须落在交付面之外；
  门的 `.env` 相关写法不应在仓库内留 `.env.bak`。本任务**未改测试、未改门、未放宽判据**，只如实报红。
- **R6 裁定（控制器，2026-09-28）**：实现者归因正确，我独立复核 `.gitignore:6` 确为精确路径 `backend/.env`。
  判据 **B0-04 不变**（"四格 failed=0"仍成立且可达——实现者的两格对照读数已证 `.env` 维度中性、红纯由残留），
  错的是我写的**流程**：计划里三处 `mv → .env.bak` 全部改为"挪出仓库到 `mktemp -d`，还原后断言
  `git status --porcelain` 与基线逐行相同"，并升格为 Global Constraints 的一条（约束 Task 1/3/5 全部 env 复量）。
  附带采入：这次"树里多一枚文件 ⇒ 扫描门当场红"是 B0-09 门敏感性的免费证据，Task 5 直接引用本条。
  代价：若判反（以为中性其实不中性），B0 的 CI 形态格会带着一个从未观察过的变量进封版。
  处置：Task 1 进修复轮 1/5，重跑格 2 与格 4 并更正报告 provenance。
- **R6 修复轮 1 回执（2026-09-28，已完成）**：按改写后的 Step 3 原文（`HOLD="$(mktemp -d)"` 挪出仓库 → 跑 → 放回 → `rmdir`）
  重跑格 2（cwd=仓库根、`.env` 缺席）与格 4（cwd=backend、`.env` 缺席），两格末行均为
  `1316 passed, 36 warnings, 1133 subtests passed … rc=0` ⇒ **四格通过轴齐平（1316 / 0 failed / rc=0）**，
  B0-04 判据原文不改即达成。复原校验：`git status --porcelain` 与基线**逐行相同**（5 行，diff 无输出）、
  `backend/.env` sha256 前 12 位 `4d7f974107dd` 前后一致、`.env.bak`/park 目录/探针文件均无残留。
  顺带按裁定采入的那条，做了最小化敏感性复验：只落一枚未跟踪未忽略文件 `B0_SENSOR_PROBE.env`
  ⇒ `test_repository_tracked_files_hold_no_credential_material` 与 `test_the_exemption_table_matches_the_hit_set`
  当场双红（门原文报 `B0_SENSOR_PROBE.env ×1 未豁免` / 命中集多出 `{'B0_SENSOR_PROBE.env': 1}`），`rm` 掉即复绿；
  **未改任何测试/门/判据**。上面"Task 1 complete"那行里的"通过轴不等"限定语就此解除，其历史读数保留在报告里不删。

- **Task 1：独立评审 = 规格 ✅ / 任务质量 Approved with findings**（评审独立复算了 39 行逐模块计数、
  1316 行基线明细、两枚 identity sha 与 mtime、探针与快照 `cmp` 逐字节相同；面文件数 316、残留为零、HEAD 仍 `7cc5efc`）。
  三条 Important 的归属与处置：
  - **I-1 台账旧判语** → 控制器文档缺陷，已就地更正（本文件上方那行）。
  - **I-2 敏感性植入用裸 `rm` 收尾、无 trap 兜底** → 残留实测为零、证据真实，但一次中断就会把两枚红门交给下一个任务。
    已升格为计划 Task 5 Step 1 的硬要求（`trap … EXIT INT TERM` + 结尾断言面数复原）。
  - **I-3 规格两处自我矛盾** → 我的文档缺陷两条：§8.1 亲自规定"就地改名 `env.bak`"（就是 R6 那枚坑的源头，
    实现者只归因到 brief 没指到规格行）；§11 B0-12"并集为空"与 §4 B0-007"基线本就不干净"打架。
    已按项目自己的勘误机制走 **§16 卡 F / 卡 G**，判据未降（卡 G 实际是收紧：原写法不可满足因而等于失效）。
  - 评审另纠正我一处杜撰：卡 F 初稿里我把两枚门的名字写岔，现按评审复核到的真名为准。
- **Task 1 deferred minors（7 条，交终审分诊）**：M-1 缺席格的 `.env` 状态只在 capture 之外echo，四份 capture 内容不可分辨；
  M-2 `errors=0`/无 skip 是从 `-q` 尾行缺 token 推得，应标为推断；无 `.env` 两格的收集数按 `passed+failed` 推得而非实测；
  M-3 残留检查 `ls -d /tmp/tmp.??` 匹配不到真 mktemp 后缀（评审已代验：结论成立）；
  M-4 原始证据只在 `%TEMP%`，未落工作区 `evidence/`（已并入 Task 5 要求）；
  M-5 报告一处用词 `FAIL`，越出 GREEN/PENDING_EXTERNAL/BLOCKED 三态；
  M-6 计划里"两 cwd 各 170–171s"与实测 98.14–195.89s 不符（已改计划，并把"墙钟不作判据"写明）；
  M-7 格 4 的 cwd 证明是转述而非字面 shape。
- **Task 1: complete（无提交，工作树态；规格 ✅，findings 已全部裁定或登记）**。基线常数 **1316** 与
  identity 两枚 sha 已冻结可用，Task 2 可开。
- **Task 2：独立评审 = 规格 ✅ / 质量 Approved with findings**（0 Critical / 5 Important / 9 Minor）。
  评审独立复算全部成立：`TOTAL 1329`、`comm` 差集 +13/−0、`5 failed / 8 passed`、全套 `1324 passed, 5 failed`
  且 skipped=0、门文件与 brief 六个代码块逐行一致（278/278）、无 `app.*` import、LF、
  `REAL_LLM_ACCEPTANCE` 剥离经"开着跑仍绿"反证有效、收集错误 rc=2/rc=5 一律 fail-closed、
  两枚 identity sha 未变、ci.yml/requirements/compose/scripts 零改动。**无假绿**（除自报的门 8）。
- **R8（我对 5 条 Important 的裁定，全部进修复轮 1）**：
  - **I-1 成立，且是地雷 → 改门，不改注释。** `test_backend_contracts_has_no_unittest_discover_step` 扫的是
    step 原文、不剥注释，而 `_job_steps` 会把两 step **之间**的注释归进前一个 step ⇒ 计划亲手要求的
    "原既有步 `python -m unittest discover` 已删除"那句注释会让门 4 永远红，且红在 `validate_demo_assets` 那一步上。
    裁定：给所有 ci.yml 类的门统一加 `_step_script()`（剥 `#` 行）后再匹配；**注释一字不删**（§5.2 + 门 6 存在的理由
    就是把那两条顺序理由留在树上）。评审用内存重建的 post-Task-3 YAML 已证：不修则 Task 3 Step 4"除 .gitattributes 外全绿"
    **按现写法不可能成立**。
  - **I-2 成立 → 走规格 §16 卡 H**：`--collect-only` 对 `skip`/`skipif`/`unittest.skip` 照打 node id，
    所以"自我存续钉抓得到哑掉的门"这半句是规格越界。裁定：口径拆两条 + 新增"本文件字节内不得出现 skip/xfail"的机器判据。
    代价：不修则一枚 `@pytest.mark.skip` 就能让 13 枚门全绿而其中任意几枚永不执行——正是 F6。
  - **I-3 成立 → 走规格 §16 卡 I**：实现把"其它 pip **参数**"缩成"其它**包名**"，评审量出三个假绿
    （恶意 `--index-url` / 第二份 `-r requirements-dev.txt` / 折叠 YAML 后续行整体消失）。
    裁定：加"tokenize 非空"地板 + 钉住 `--index-url`/`-r` 的**值** + 安装步必须 `run: |`。
  - **I-4 成立 → 门 6 从"词汇存在"改成"顺序为真"**：`_job_steps` 已给有序段，直接断言
    SECA-20 段索引 < 主门段索引 < compose/pwsh 段索引。原写法把扫描步挪到主门之后仍绿。
  - **I-5 成立 → 主门段必须不含过滤旗标**（`-k` / `--ignore` / `--deselect` / `-x` / `--lf` / `--kf` / `-m`），
    并把"远端该步自报 `N tests collected` == 常数"写进 Task 7 的判据（B0-03 一直要这个数，却没有任何地方断言它）。
    理由：否则 13 枚门可以在一枚"只跑过滤子集"的 CI 步骤下全绿——正是 B0 要杀的 F1/F6。
  - **连带**：新增 2 枚门（卡 H 的 skip 判据、卡 I 的 index-url 值钉）⇒ 门文件 13 → **15 枚**，
    `EXPECTED_COLLECTED` 必须由实现者**重新实测回写**（预期 1331），并保持 `_OWN_TEST_NAMES` 同步。
    修完预期形状：门模块 **红 5 / 绿 10**，套件 `1326 passed / 5 failed`。
  - **9 条 Minor 全部 deferred**，交终审分诊；其中 3 条一行的（`TESTS_DIR` 未用、313 个文件先 read 后判后缀、
    `.ps1` 混合行尾判据不严）随本轮顺手带上，因为改动同文件、成本近零。
  - 评审越界提示：它指出门文件 docstring 指向 `scripts/b0_collection_probe.py` 而 §10.2 禁 `scripts/**` ——
    那是 **R1 已裁定**的白名单例外（新增允许、既有禁改），不是缺陷，不改。
- **Task 2：修复轮 1/5（7 addressed, 0 open；工作树态，无提交）**。定向复评逐条判 ADDRESSED，且
  **0 新 Critical/Major**：`_step_script()` 剥注释已贯穿全部 8 处 ci.yml 匹配；卡 H 的哑化装饰器判据实测覆盖
  `skip/skipif/xfail/@ pytest/断裂写法`（`parametrize`、`lru_cache`、`fixture` 不误伤）；卡 I 三枚钉
  （`run: |` 形状 / 非空 tokenize 地板 / `-r`·`--index-url` 值钉）逐个用合成形状证红；门 6 改成严格有序锚点；
  I-5 过滤旗标无过拟合（`-q`/`--tb=short`/`-rf`/`-p no:cacheprovider` 全绿）也无漏拟合（`-m` 前缀剥离后仍抓到第二个 `-m`）。
  **I-1 地雷由评审独立重建 post-Task-3 YAML 证伪**：6 枚 ci.yml 门全绿；未剥注释的匹配器会在第 6 步
  `validate_demo_assets` 上假红 —— 即 Task 3 若按原样落地必然踩雷，现已排除。
  门数 15 枚、`EXPECTED_COLLECTED=1331` 经评审自跑证为**活测量**（门 1 绿）；模块 `5 failed / 10 passed`、
  套件 `1326 passed / 5 failed`；文件 588 LF / 0 CRLF / 仅标准库；`_OWN_TEST_NAMES` 与 15 枚 `def test_` 逐名相等。
- **Task 2 deferred minors（复评新增 6 条 + 原 9 条，交终审分诊）**：
  ①报告里 skip 夹具用"改名副本"证 (a)/(b) 分野无效（`OWN_MODULE` 是硬编码，副本不参与枚数钉）——结论经评审
  换路证真，但**记录方式不成立**，Task 6 的 skip 变异必须用真原地形态；
  ②门 6 锚点会匹配 step 的 `- name:` 散文（计划用名不冲突、fail-closed）；
  ③卡 H 判据扫全文含注释，将来写一行"例如 @pytest.mark.skip"的说明会自撞（已刻意避开）；
  ④`--co`/`--collect-only` 在过滤旗标名单里，R8 承诺的"远端自报收集数"必须放**独立步骤**；
  ⑤非来源类旗标（`--no-deps`）三枚钉都不可见，`--trusted-host` 只是被误当包名顺带抓到、归因错——
  与卡 I 字面范围一致，登记不重开；⑥`_pip_source_option_values` 不剥尾随 `;`/`,`（fail-closed）。
  ⑦**须随 Task 3 更正的措辞缺陷**：门 6 的"文字存在"半边被 ci.yml **旧**注释（`:17-19` 已含 `SECA-20` 与
  `unittest discover`）满足 ⇒ 删掉新写的 §5.2 理由注释仍判 GREEN。断言本身未变，但门 6 docstring 与
  计划 Task 3 Step 3 注释都声称"删了会红"，是**越界措辞**，Task 3 会继承。
- **Task 2: complete（工作树态；规格 ✅，7 项 findings 全部 ADDRESSED，15 条 minor 已登记）**。
  Task 3 可开；其预期形状 = 门模块 **红 1（`.gitattributes` 那枚）/ 绿 14**。
- **Task 3 落地读数（实现者，待评审复核）**：只改 `ci.yml`（字节级 CRLF 拼接），
  `CRLF 134/bareLF 0 → CRLF 139/bareLF 0`，`git diff --numstat 20/15`、两个 hunk 全在 `backend-contracts` 内、
  其余三个 job 逐字节相同；门模块 `1 failed / 14 passed`（唯一红 = `.gitattributes` 那枚，符合预期）；
  无 `.env` 全量 `1330 passed / 1 failed`（=1331 收全）、SEC-A 模块 46 绿。
- **R9（Task 3 实现者撞出的两件事，控制器裁定）**：
  ① **计划里的 YAML 本身是错的**：`- name: … (single runner: pytest)` 未加引号 ⇒ `ScannerError`（plain scalar
     里的 `: ` 被当映射分隔符）。实现者按"只加引号、文本不改"修好（+2 字节）。我已把计划正文改为带引号形态，
     并把"为什么必须带引号"写在旁边。这是**只有真去做才会暴露**的那类缺陷，写在这里而不是悄悄改掉。
  ② 它顺带指出一个真缺口：15 枚门都不解析 YAML（PyYAML 既不在 `requirements.txt` 也不许进 `backend/app` 依赖面，
     而门必须只用标准库），所以**一份语法就错的 workflow 可以拿 14 绿**。裁定：加**第 16 枚门**——
     不做 YAML 解析器（那是给自己造第二份真相），只钉住"刚刚真咬过我们的那一形"：
     任何 `- name:` / `key:` 之类的 plain scalar 值里若含 `: `，该值必须整体加引号。
     连带：门数 15→16 ⇒ `EXPECTED_COLLECTED` 必须重新实测回写（预期 1332），`_OWN_TEST_NAMES` 同步扩名。
     代价：不加则 B0 的全部价值可以被一枚打不开门的 workflow 绕过；乱加则要么引入 YAML 依赖要么造出第二套解析器。
  ③ 授权说明：第 16 枚门改的是 Task 2 的宿主文件，随 Task 3 的修复轮一起做（同一评审面、同一批读数），
     因为这枚门的存在理由就是 Task 3 踩到的坑。Task 3 的评审范围因此含 `ci.yml` + 门文件两处。
- **R7（Task 2 派发前修掉的计划缺陷两处）**：
  ① 计划里门文件的 `BASELINE_NODE_IDS` 指向 `.superpowers/sdd/ENTERPRISE_B0/…`，与 R0 定的工作区名不符
     ⇒ 门会去读一枚不存在的路径。已按 R0 改为 `ENTERPRISE_B0_PLAN`；计划正文其余同类旧称以本条为准。
  ② 更要紧的一条：`.superpowers/` **是 gitignored**，所以那枚 node-id 明细基线在 **CI 里根本不存在**，
     而计划原稿在失败分支里无条件 `read_text()`。判据本身不依赖它（`实收 == 常数` 一条独立成立），
     但失败信息会在远端炸成 `FileNotFoundError` 而不是"差集是什么"。已改为 `is_file()` 防御式读取 +
     一条注释写明"明细只用于可读性，绝不允许进判据"。代价：错则 B0-01 在远端变成一条无法归因的红。

- **Task 2 complete：13 枚门落地，红相 5 枚红 / 8 枚绿（与 brief Step 7 预测逐枚吻合，清单见 `task-2-report.md`），`EXPECTED_COLLECTED=1329` 双写完成（实测 1316+13=1329，非凑数）**。
  全量末行 `5 failed, 1324 passed … in 171.08s`，5 行 FAILED 逐名都是本文件自己的红门、无附带伤害；
  SEC-A 密钥卫生门整模块 `46 passed`（新文件确在扫描面上、命中 0 处，**未加豁免行**）；快照 `snap-task2-post/`，源文件 sha256 前 12 位 `69f74974c2e1`，LF、仅标准库、不 import `app.*`。
  **交 Task 3 的一条形态约束（report 有实测证据）**：`_pip_package_tokens` 按物理行扫，`run: >-` 折叠标量的续行包名
  tokenize 不到（实测 `folded(>-) → []`、`run: | 同行 → ['pytest','torch']`）⇒ 改造后的安装步必须把 `pytest` / `torch`
  与 `pip install` 写在同一物理行，否则豁免表钉会红在"死行"这个错误理由上。判据未改，约束归 ci.yml。

- **R8 修复轮 1 回执（2026-09-28，已完成；本报告《修复轮 1》一节为全量证据）**：五枚 Important 全部按 R8 落地，
  三条随手 Minor 一并带上。**上方"Task 2 complete"那行的 13 枚 / 1329 / 红 5 绿 8 是红相轮的历史读数，
  已被本轮回执取代**：门 **15 枚**、`EXPECTED_COLLECTED=1331`（1316+15，先加门→重量→回写，
  并用 monkeypatch 把常数按回 1329 证明门 1 当场红）、门模块 `5 failed, 10 passed`、全量 `1326 passed / 5 failed`
  ⇒ **与 R8 预测的"红 5 / 绿 10 + 1326/5"逐字相符，无偏差需上报**。
  落地形状：① `_step_script()` 剥 `#` 行，所有 ci.yml 命令匹配走它（注释一字未删，门 6 的文字半边刻意看原文）；
  ② 卡 H 口径拆两条 + 新增 `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator`
  （真路径复现：给一枚门挂 skip ⇒ 新钉红、枚数钉仍绿）；③ 卡 I 三条钉齐（`run: |` 形状 + 非空 tokenize 地板 +
  `ALLOWED_PIP_SOURCE_VALUES` 值钉，评审的三枚假绿枚枚转红）；④ 门 6 改为段索引严格全序（挪扫描步到主门之后即红）；
  ⑤ 主门过滤旗标钉（`-k`/`-x`/`--lf`/`--deselect`/`--ignore`/`-m` 任一枚即红，`python -m` 前缀已剥离）。
  反证台另照出我自己的一枚假红：`python -m` 剥离正则首版要求 `-` 与 `m` 之间有空格 ⇒ 正确的 Task 3 会让门 5
  红在 `['-m']` 上；已修（`\s+-\s*m\s+`）并复量 post-Task-3 六枚 ci.yml 门全绿。
  留待复核的一格：门 6 对"主门缺席"不重复归因（R8 严格字面读法会多出第 6 枚红、与门 5 同根因），见报告第七节。
  **交 Task 3 的约束因此升级**：安装步必须 `run: |` 且每条 `pip install` 参数各占一物理行（已从口头约定变成机器钉），
  `--index-url` 只能是 `https://download.pytorch.org/whl/cpu`、`-r` 只能引用 `backend/requirements.txt`，
  主门 `python -m pytest backend/tests -q` 不得带旗标。零 git 写命令、HEAD 仍 `7cc5efc`、identity 两枚 sha 不变、
  快照 `snap-task2-fix1-post/`（与源文件 `cmp` 相同），源文件终态 31379 字节 / sha 前 12 位 `19d335a1c15a` / LF / 仅标准库。



- **Task 3 complete：`ci.yml` 的 `backend-contracts` 落到规格 §5.1 的 10 步形状 ⇒ 门册 1 红 / 14 绿**（唯一红 `test_gitattributes_carries_the_required_rules`，Task 4 的活；本任务未削弱/未注释/未删任何断言）。定向 Step 4：`-k "contracts or ordering or requirements_txt or exemption or states_why"` = `6 passed, 9 deselected in 0.58s`。
  形状（按 step 名，不按行号）：删 `Install SECA-20 secret-scan dependencies`（13 包手写清单 + `run: >-`）→ 换 `Cache pip wheels` + `Install backend dependencies (same source as requirements.txt)`（`run: |` 三枚物理行：torch CPU 发行源 / `-r backend/requirements.txt` / `pytest`）；删 `- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v` → 换 `Run backend contract suite (single runner: pytest)`（`python -m pytest backend/tests -q`，零过滤旗标）；§5.2 两条顺序理由与"原步已删除"那句注释**逐字留在树上**。其余三个 job 用 `yaml.safe_load` 前后深比较证明 **IDENTICAL**；SECA-20 扫描步的 `-k` 表达式**字节未动**。门文件与 `EXPECTED_COLLECTED=1331` 本轮**零改动**。
  字节/形态：改法是**字节级 Python splice**（`read_bytes` → 断言 `count(\n)==count(\r\n)` → 按 `\r\n` 切 → `\r\n`.join 写回）。**CRLF 134→139、bareLF 两次都是 0**（终态 6042 字节）；`git diff --numstat` = **20/15**、两枚 hunk 全落在 `backend-contracts` 内，**不是 134/134** ⇒ 没污染 diff。没顺手改本文件行尾（它仍属 24 枚 mixed 之一，归 Task 4）。
  Step 6 无 `.env` 全量（`mktemp -d` 挪出仓库、树内零副本，R6）：**`1 failed, 1330 passed, 36 warnings, 1133 subtests passed in 168.97s`**，FAILED 逐名只有 `.gitattributes` 那枚 ⇒ `1330 + 1 = 1331`：主门命令在无 `.env`、cwd=仓库根的形态下**把 1331 枚全部实际执行**（本轮改造的目的——CI 从此看得见那 ~40 枚裸 `pytest` 函数）。`.env` 恢复后 sha 前 12 位 **`4d7f974107dd`**（=要求钉值），`git status --porcelain` = Task 2 基线 + 仅 `M .github/workflows/ci.yml`；identity 两枚 sha **`3bc681bbc52c` / `2cfab9f18182`** 与本报告 progress:48 的冻结值逐字相同。SEC-A 密钥卫生整模块 **46 passed**（`ci.yml` 在其扫描面上，**未新增豁免行**）。
  **上报一枚 brief 缺陷 + 一门册盲区（本任务不许改门文件，故只登记不修）**：Step 3 原文 `- name: Run backend contract suite (single runner: pytest)` 里的 `: ` 让 plain scalar **非法** —— `yaml.safe_load` 字面报 `ScannerError: mapping values are not allowed here … line 47, column 56`，同一次脚本里改前那份读作 `PRE OK`（证明非法形态由本轮引入）。处置=给步名整体加双引号、**文本一字不改**（只多两枚 `"`）。盲区要说清：15 枚门全是正则 + 行切片、**从不加载 YAML**，所以"把 `ci.yml` 写成非法 YAML"可以让 14 枚照绿、到远端才炸 `Invalid workflow file`；本轮是 implementer 自补 `safe_load` 抓到的，**不是门抓到的** ⇒ 建议 Task 5/终审给门册加一枚"workflow 必须可被 YAML 解析器加载"的存在性钉。附带一份正面证据：`snap-task3-pre/ci.yml`（134 枚 CRLF）与 `git cat-file -p HEAD:.github/workflows/ci.yml`（**134 枚裸 LF / 0 枚 CRLF**）在 `\r\n→\n` 之后**逐字节相同** ⇒ §6.4"行尾归一化仍由每台机器的 `core.autocrlf` 决定"被量成了字节；Task 4 落 `* text=auto` 时**别把这 139 枚 CRLF 提交进 index**（门 13 `test_index_has_no_crlf_entries` 会红）。
  零 git 写命令、HEAD 仍 `7cc5efc`；快照 `snap-task3-pre/ci.yml` + `snap-task3-post/ci.yml`（后者与源文件 `cmp` 相同，sha 前 12 位 `2d4d33d8fd44`）、编辑脚本 `tmp/task3_edit_ci_yml.py`、日志 `tmp/full-suite-task3-noenv.txt`、全量证据 `task-3-report.md`。**交 Task 4 的一件事**：`ci.yml` 工作树现有 139 枚 CRLF、index 侧全 LF，加规则前后要重跑门 13/14/15，并复核 `test_eol_rules_are_a_no_op_for_the_current_tree` 只覆盖 `.sh`/`.ps1`（不含 `.yml`）。

- **R9 ② 修复轮 1 回执（2026-09-28，Task 3 的修复轮 1/5；工作树态、零提交；证据全在 `task-3-report.md` 的《Task 3 修复轮 1》一节）**：第 16 枚门
  `test_workflow_plain_scalars_bearing_a_colon_space_are_quoted` 按裁定落地——**不解析 YAML、不引 PyYAML**，
  只钉"含 `: ` 的 plain scalar 必须整体加引号"这一形：`_workflow_scalar_entries()` 把行切成
  `(行号, 键, 值, 是否 - 前缀)`，四条豁免各有理由（整行注释、块标量正文按缩进整段跳过、flow 值 `[`/`{`、
  内联 ` #` 之后的散文），判据本体是"值里含 `: ` 且没被同一对引号整体包住 ⇒ 红"。
  **反证台**（`tmp/b0_t3f1_falsify.py`，合成 workflow 写成真文件落在 `%TEMP%` 即**仓库之外**，只把门的 `CI_FILE` 指过去、
  调真门函数，跑完 `rmtree` 自证无残留）五发齐：计划原稿那枚未加引号的步名 ⇒ **RED 并点名"第 47 行"**；
  双引号 / 单引号 / 不含冒号三种步名 ⇒ GREEN；真 `ci.yml` ⇒ GREEN（**不假红**）；`: ` 只出现在 `run: |` / `run: >-`
  正文里（含塞进真文件的那一发）⇒ GREEN，而同一冒号写在结构行上 ⇒ RED（界线两侧各打一枪）；
  地板按卡 I (2) 同族 fail-closed——`- name:` 一枚都扫不到（步名全删 / 空文件）当场红，红在"门哑了"。
  **R9 ② 那句"14 绿可以带着非法 YAML"被量成事实**：同一份非法 YAML 喂给其余 6 枚 ci.yml 门 **6 枚全绿**。
  连带：`EXPECTED_COLLECTED` **1331 → 1332** 是"先加门 → 实测 → 才回写"（探针 `TOTAL 1332`、本模块 `--node-ids` 实收 16 ⇒
  1316 + 16 = 1332，两侧都是实测量、与预测值相等**无偏差**）；改常数前门 1 当场红并打出"收集数 1332 ≠ 钉住的 1331"（红相留档），
  回写后 `2 failed → 1 failed`。`_OWN_TEST_NAMES` 16 枚与 16 枚 `def test_` 逐名相等。
  终态读数：门册 **15 绿 / 1 红**（唯一红仍是 `.gitattributes` 那枚，Task 4 的活）、全量两把同值
  **`1331 passed / 1 failed`（174.19s 原地 / 179.73s 无 `.env`，`.env` 挪出仓库、sha `4d7f974107dd` 前后一致、
  `git status` 7 行逐行复原）**、SEC-A 整模块 **46 passed 且未加豁免行**、门文件 39045 字节 / 707 LF / 0 CRLF /
  sha `fd3aa56eff49` / 仅标准库 / 无 `app.*`；`ci.yml` 与 `snap-task3-post/ci.yml` **cmp 逐字节相同**（本轮没碰它）、
  identity 两枚 sha `3bc681bbc52c` / `2cfab9f18182` 不变、HEAD 仍 `7cc5efc`。
  **交控制器的一条判断**：量口径时另发现一枚**邻形**也炸——值以冒号**结尾**（`- name: Note:`）同样 `ScannerError`
  （宿主 PyYAML 实测），但 R9 ② 的字面是"值里含 `: `"，故本枚**没扩**、只在函数 docstring 与报告里留了实测与登记；
  要不要扩请终审判。顺带把三件事校准成字面读数：`qdrant/qdrant:v1.19.1` 这类"冒号不跟空格"合法（门放得对）、
  部分加引号 `python -c "print('x: y')"` 非法（门"整体加引号才算安全"的口径不是过严）、真 `ci.yml` 值侧含 `: ` 的
  结构行**只有第 47 行一枚**且已加引号 ⇒ 没有"本该抓到而漏掉"的第二条。快照 `snap-task3-fix1-post/test_ci_gate_contract.py`（与源文件 `cmp` 相同）。
- **Task 3：独立评审 = 规格 ✅ / 质量 Approved with findings**（0 Critical / 3 Important / 5 Minor）。
  评审独立复算并证真的部分：其余三个 job 与 HEAD **逐字节相同**、`CRLF 139/bareLF 0`、diff `20/15` 两 hunk 全在
  `backend-contracts` 内、步骤序列 10 枚与 §5.1 逐行对得上（它自己 `yaml.safe_load` 读的）、门 16 无标量时地板确实红、
  `_OWN_TEST_NAMES` 与 16 枚 `def test_` 逐名同序、`EXPECTED_COLLECTED=1332` 是活读数（它自跑门 1 绿）、
  门文件 707 LF / 0 CRLF / 仅标准库、identity 两枚 sha 未变。**无假绿**，唯一红仍是 `.gitattributes`。
- **R10（Task 3 修复轮 2 的裁定）**：
  - **I-1 成立且位置最坏** → `ci.yml:20-22` 仍用现在时说"依赖刻意取能 import `app.*` 的最小集、与
    `backend-integration` 同源"，而本任务之后该 job 装的是整份 `requirements.txt`，`backend-integration` 仍是手写清单
    ⇒ 同一文件里现在有两枚互相矛盾的依赖声明（`:20` vs `:30` 与新步名）。**这正是 ENTER-B0-003 的反模式留在校验它的
    那一步正上方一行**：下一个人读 `:20` 会认为"该手写"，于是往 YAML 里加包名，红门 9、复刻 `f6c67b5`。
    裁定：改写 `:17-22` 为"过去时 + 现状"两段，历史括注保留但明确标为历史；与 Minor 4 合并处理（`:17-19` 的
    "下面那枚既有步"指涉对象已被本任务删除，句子悬空且与新块重复）。
  - **I-2 成立** → `ci.yml:42` 断言"删掉任何一条理由注释就会让门红"，评审实测**为假**（旧注释同样供 `SECA-20`+`unittest`
    两个 token）。根因就是我登记过的 deferred minor ⑦，brief 原样搬进了 CI 文件。裁定：I-1 的改写删掉旧块后，
    这半句**有机会变成真话**——但必须**实验确定**：逐块删注释、记录门 7 的红/绿，再按实验结果写注释，
    而不是按我希望它成立来写。顺序半边（严格递增锚点）是真的，不受影响。
  - **I-3 成立** → 门 16 在 `_fully_quoted()` 判定**之前**没剥行内注释，于是
    `- name: "…(single runner: pytest)"  # 说明` 这种**完全合法**的写法被假红（评审用树外合成文件复现，
    `yaml.safe_load` 认为合法）。本仓库自己的失效史就是"假红 → 有人加豁免 → 真形状跟着漏"，所以必须修判定顺序。
  - **Minor 5 的尾冒号邻形一并扩**（`body.endswith(":")`）：同一事故家族、一个子句、不引入解析器。
    评审判定"钉单一形状而不是自己写 YAML 解析器"是**站得住的**（标准库无 YAML 解析器、PyYAML 被依赖面禁、
    R9 ② 明令不许造第二份真相），故维持形状钉路线；但它建议的 tab/缩进/引号配对三件套**不做**（YAGNI，
    那三个检查留在实现者的临时脚本里当证据即可）。
  - **Minor 6 cache key 偏离规格 §5.1** → 规格才是权威：计划正文已补 `cpu-torch` 判别位（我改），`ci.yml` 随本轮跟上。
    `py3.12` 仍为字面量：GitHub 无内建 python 版本变量，且它就写在上一行 `python-version: '3.12'` 旁边；
    不为此造第二份真相，登记为已知耦合。
  - 不改变门数量（I-3/Minor 5 都在门 16 内部）⇒ `EXPECTED_COLLECTED` 仍 **1332**；终态预期
    门模块 **1 红（`.gitattributes`）/ 15 绿**。

- **R10 ③ 修复轮 2 回执（2026-09-28，Task 3 的修复轮 2/5；工作树态、零提交；证据全在 `task-3-report.md` 的《Task 3 修复轮 2》一节）**：四条裁定全部落地。
  **I-3 + Minor 5（门 16）**：`_unquoted_colon_bearing_scalars()` 改成**先剥行内注释、再判引号**，并把"剥完的值以 `:` 结尾"并入同一子句（一个事故家族、不引解析器）。
  改前用**仓库外**合成文件复现假红：`- name: "Run suite (single runner: pytest)"  # keep quoting` ⇒ 门 RED、宿主 PyYAML 判合法；改后 12 发反证台 0 偏差
  （合法 A/B/G/H/I + 真 ci.yml 的 L 共六发 GREEN，非法 C/D/E/F 四发 RED 且点名行号，地板 J/K 两发仍 RED），修复轮 1 的 `b0_t3f1_falsify.py` 原地复跑五段结论一字未变。
  **不引 YAML 解析器**（标准库没有、PyYAML 被依赖面禁）、**不做** tab/缩进/引号配对三件套（R10 判 YAGNI）。
  **I-1 + Minor 4（`ci.yml:17-24`）**：过期现在时依赖声明拆成三段——位置（现在时，宾语换成仍存在的主门，"下面那枚既有步"的悬空指涉消失）、
  依赖现状（本 job 装整份 `requirements.txt`，`backend-integration` 仍是手写清单，并写明两枚 job 跑法不同 ⇒ 来源分家、别互相抄）、
  历史（明确标"已作废，只当事故记录读"，`ModuleNotFoundError: httpx` 那趟往返留在这一段）。
  **I-2（先实验、再按实验写注释）**：`tmp/b0_t3f2_i2_experiment.py`（ci.yml 副本落 %TEMP%、块与行**按内容**定位、只把门的 `CI_FILE` 指过去）12 发读数：
  只删理由 (1) ⇒ **GREEN**、只删理由 (2) ⇒ **GREEN**（旧抬头"删掉任何一条都会让门 7 红"当场证伪）、只删"原既有步已删除"那句 ⇒ **RED**、
  注释一字不动只把扫描步挪到主门之后 ⇒ **RED**。根因：门 7 文字半边的 `SECA-20` 由那枚扫描步的**步名**自己供（删注释删不掉），
  `unittest` 只系在"原步已删除"那一句上 ⇒ 新抬头按"**顺序半边机器钉、两条理由的取舍由人审担保**"写，
  并且**刻意不复述那两枚 token 的字面**（否则这行注释自己会把 E7 弄成假话）；改完原地复跑 E0-E11，逐发红绿读数与改前一致。
  **Minor 6**：cache key 补成 `b0-${{ runner.os }}-py3.12-cpu-torch-${{ hashFiles('backend/requirements.txt') }}`（`py3.12` 仍字面量，登记为已知耦合）。
  终态读数：门册 **15 绿 / 1 红**（唯一红仍是 `.gitattributes`，本轮**没建** ⇒ 正确终态；16 枚逐名点名、`EXPECTED_COLLECTED` 仍 **1332** 未回写）、
  全量两把同值 **`1331 passed / 1 failed`**（原地 169.40s / 无 `.env` 173.76s，`.env` 挪出仓库再复原、sha **`4d7f974107dd`** 前后一致、
  `git status --porcelain` 7 行逐行复原）、SEC-A 整模块 **46 passed 且未新增豁免行**；
  字节/形态：`ci.yml` **CRLF 139→141→148、每一步 bareLF 0**、7206 字节、`git diff --numstat` = **35/21**、两枚 hunk（旧 17-36、旧 43-43）
  **全在 `backend-contracts` 内**，其余三枚 job 与 HEAD 做 `yaml.safe_load` 深比较 **IDENTICAL**、SECA-20 扫描步四行与 HEAD **逐字节相同**；
  门文件 40751 字节 / 721 LF / **0 CRLF** / sha `c337e5363e5c`、仅标准库、`yaml` 与 `app.*` 进口均无；identity 两枚 sha **`3bc681bbc52c` / `2cfab9f18182`** 不变；
  HEAD 仍 `7cc5efc`、零 git 写命令、合成文件一枚不入树（三处 %TEMP% 目录各自"已删除 = True"）。快照 `snap-task3-fix2-post/{ci.yml,test_ci_gate_contract.py}`（与源文件 `cmp` 逐字节相同）。
  **交 Task 4 的一件事（数值更新）**：`ci.yml` 工作树现有 **148** 枚 CRLF（index 侧仍是 134 枚裸 LF），落 `* text=auto` 前后要重跑门 13/14/15 并复核 no-op 覆盖面。

- **R11（Task 3 修复轮 3 回执，2026-09-28，修复轮 3/5；工作树态、零提交、HEAD 仍 `7cc5efc`；证据全在 `task-3-report.md` 的《Task 3 修复轮 3》一节）**：scoped re-review 的两处照单落地，未重新设计。**Fix 1（门 16 的引号判定补成两读并判）**：轮 2 把判定挪到“只看剥完行内注释的值”，而 `_INLINE_COMMENT` 是 quote-blind 的 ⇒ 引号内含 `#` 的**完全加引号**标量被**镜像假红**（`- name: "Run: everything #1"` 门 RED、宿主 PyYAML 判合法），定稿 `_fully_quoted(value) or _fully_quoted(body)`、只多一枚 `or`；反证台改前那台 15 发跑的是**当时树上真实的门文件**（A 与单引号镜像那发当场 RED），改后台子 16 发**与期望不符 0 发**、评审点名的 9 类形状逐发 ✓（`"Run: a" baz` 部分引号仍 RED、`Note:` 与 `Note:  # note` 仍 RED、`qdrant:v1.19.1` 仍 GREEN、地板仍 RED、真 ci.yml GREEN），其余 13 发读数一字不变；谓词台把两读各自的代价也量清并写进门文件 docstring 而不是悄悄放宽：`"a: b" and "c"` 改前改后同 GREEN（`_fully_quoted` 比首尾字符不比配对的既有边界、非本轮换来）、`"a: b #c" d"` 是 `or` 新开的一窄面、`"…#1"  # 注释` 这枚假红**本轮没治好**（quote-blind 第一刀落在引号内，两读都凑不出引号对，要消只能引解析器 = R9 ② 禁止）。轮 2 的 12 发台与轮 1 的 5 段台原地复跑无回归（唯一差是注释块缩一行导致的点名行号 56→55）。**Fix 2（`ci.yml` 块 B 抬头 8→7 行）**：删掉指向 gitignored `.superpowers/`（`.gitignore:25`）的 `task-3-report.md《Task 3 修复轮 2》` 死链与逐轮考古，只留持久陈述——顺序半边由门 7 机器钉（挪一步当场红）、文字半边只 grep 两枚 token、而 (1)(2) 的取舍与措辞由**人审**担保，人审省不掉的原因是旧 runner 那枚 token 在 job 块里**只出现一次**、系在“原既有步已删除”那一句上 ⇒ 删那一句才红；新块刻意不自带那两枚 token（否则会把自家断言弄假），七发复验（E0/E5/E6/E7/E12/E13/E11）逐句对上注释里的每个断言。**终态**：门册 **15 绿 / 1 红**（唯一红仍是 `.gitattributes`，本轮没建 ⇒ 正确终态；16 枚逐名点名）、`EXPECTED_COLLECTED` 实测 **1332**、`_OWN_TEST_NAMES` 实测 **16**、SEC-A 整模块 **46 passed 且未新增豁免行**；字节/形态：`ci.yml` **CRLF 148→147、bareLF 改前改后都是 0**、7106 字节、相对轮 2 终态快照**只一枚 hunk（8 删 7 加）**、其余三枚 job 与 HEAD 做 `yaml.safe_load` 深比较 **IDENTICAL**、SECA-20 扫描步四行按行内容与 HEAD 相同、块 A / cache key / (1)(2) 两句 / “原既有步已删除”两句一字未动；门文件 43268 字节 / 743 LF / **0 CRLF** / sha `4c98f1439494`、仅标准库、`yaml` 与 `app.*` 进口均无；identity 两枚 sha **`3bc681bbc52c` / `2cfab9f18182`** 不变、零 git 写命令、五枚探针脚本的执行目录与全部合成 workflow 都在 %TEMP%（`在树内 = False` 逐台打印、各自“已删除 = True”），事后只把脚本与日志归档进 gitignored 的 `tmp/b0_t3f3_*`（`git check-ignore -v` 命中 `.gitignore:25`、`git status --porcelain` 仍是开工前那 7 行）。**全量套件本轮按任务给的许可跳过（≈170s），因此对它不作任何主张**，收工前须补跑。快照 `snap-task3-fix3-post/{ci.yml,test_ci_gate_contract.py}`（与源文件 `cmp` 逐字节相同）。**交 Task 4 的数值更新（覆盖 R10 ③ 末行）**：`ci.yml` 工作树现有 **147** 枚 CRLF（index 侧仍 134 枚裸 LF），落 `* text=auto` 前后按 147 重跑门 13/14/15 并复核 no-op 覆盖面。

- **Task 3: complete（工作树态，3 轮修复；规格 ✅，全部 findings 关闭，无新破坏）**。终态：门 16 枚 /
  `EXPECTED_COLLECTED=1332` / 模块 `1 failed, 15 passed`（唯一红 = `.gitattributes`，属 Task 4 的正确终态）；
  `ci.yml` 147 CRLF / 0 bare LF、其余三个 job 与 HEAD 逐字节相同；SEC-A 46 绿、零新增豁免。
  三轮共关闭 3 Important + 1 Minor + 2 枚轮次衍生项：注释剥序假红、`#` 在引号内的镜像假红、
  `ci.yml` 里指向 gitignored `.superpowers/` 的死路径与逐轮考古文字。
- **Task 3 deferred minor（复评登记）**：`"Run: a #1"  # 注释` 这枚"引号内 # 加行尾注释"复形仍假红
  （PyYAML 判合法）。已同时登记在门文件 docstring 与本台账，树内零出现，后果是对一枚生造步名响亮假红、
  不是静默放过 ⇒ 延后。
- **复评的一处字面纠正**：门文件里"要消只能真去解析 YAML"略说过头——约 5 行的引号感知剥注释就能消掉
  未转义那一类，真正需要解析器的是 `\"` 与 `''` 转义族。裁定：不改代码（决策不受影响），只纠正措辞归属。
- **R12（Task 4 回执，2026-09-28；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据全在 `task-4-report.md`）**：`.gitattributes` 落地（435 字节 / **CR 0** / LF 18 / sha `c5d07b5dc438`，三枚必需规则按门 13 的 `line.strip()` 集合取**单空格**、八枚声明以 `binary` 收尾），三条"不做"照单执行（不给 `*.py`/`*.md`/`*.yml` 加 `eol=`、不加 `*.md text`、`i/-text` 三枚仍由形状钉管）。**门册首次 16 绿 / 0 红**（`4 passed` 行尾钉 + 模块 31.91s）、**全量套件首次两格全绿**（cwd=仓根 **1332 passed / 186.18s**、归档复跑 181.49s；cwd=backend **1332 passed / 179.40s**；两格 36 warnings / 1133 subtests 相等、rc=0、无 FAILED/ERROR），SEC-A **46 绿且未加豁免行**（扫描面 316→317→**318**）。**no-op 双向闭合**：静态 `checked=2 / offenders=0`（`.sh` 已 LF、`.ps1` 无裸 LF，非空判）+ `git check-attr` 证明规则是活的；动态 status raw diff 只多 `?? .gitattributes` 一枚、`WORKTREE-AGGREGATE` 三时点 **`53bb297dbc72` 逐字符相等**、逐文件清单 `0a1` 纯新增（317 枚既有 sha 零改写）、`git diff` 正文两态 **10107 字节 / `dfa0fbde86b5` 逐字相同**。两枚 identity 复量仍 `3bc681bbc52c` / `2cfab9f18182` 一字未动。**证伪**：摘 `*.sh text eol=lf` 当场 `1 failed`（门点名 13、断言复现缺串），`finally` 按 read_bytes 原字节写回 + `cmp` rc=0 + sha 复量，复跑 `1 passed`。**brief 配方九处与实况不符已逐条登记**，其中两处是判据级的：D5 `git diff --exit-code .gitattributes` 对**未跟踪**文件恒返 0 = 假绿（换真字节 `cmp`）；D2 规格 §7 的 `*.sh␣␣text eol=lf` 双空格会当场红（以门为准，规格不改）。另 D1 `task-1-report.md` 里并无 `WORKTREE-AGGREGATE` 基线，故基线由本任务 Step 1 现场取并以 identity/7 行 status 双锚确认。快照 `snap-task4-post/gitattributes`（与源文件 `cmp` 相同）。**这枚文件仍未跟踪**——入库需显式 `git add .gitattributes`，本任务无提交权限，未做。
- **R13（Task 4 修复轮 1 回执，2026-09-28；修复轮 1/5；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据全在 `task-4-report.md` 的《Task 4 修复轮 1》一节）**：照规格 §16 **卡 K** 落地，本轮只动 `backend/tests/test_ci_gate_contract.py` 一枚文件。**主判据 = 解析覆盖度**：`_index_eol_rows()` 内新增"『`git ls-files --eol` 解析条数 == `git ls-files` 跟踪条数，且两侧路径集合相等，不等即红』"，不假设属性列形状 ⇒ 任何未来的丢行都只会响亮地红；两枚消费门（`i/crlf=0`、`i/-text` 恰三枚）正文一字未改、判据未弱化、**没有**给被丢路径加白名单。**正则**由 `attr/\S*` 改成 `attr/[^\t]*?`（列终点从"下一个空白"改成"记录里那枚字面 tab"；tab 是实测而非假设：每条记录恰 1 枚）。**口径选择 = 两侧同用 `-z`**（`ls-files --eol -z` vs `ls-files -z`，按 NUL 切记录）：默认 `core.quotePath` 会把本仓 **20 枚**非 ASCII 路径八进制转义并套双引号，明文面键与 `-z` 面键互不相等 ⇒ 混用必假红（这也顺手把卡 K 的第二族失效"读到了但读歪了"堵在集合相等那一半）。**行数 311 → 313**，找回 `scripts/deploy.ps1` 与 `.superpowers/scripts/run_p0_failover_acceptance.sh`（两枚都 `i/lf`）。**反证双向**：台 A 把门文件里的正则按字节落盘退回旧式 ⇒ `2 failed, 14 passed`，FAILED 恰点名那两枚消费门、断言含 `assert (311 == 313)` 与两枚被丢路径；`finally` 原字节写回 + `cmp` rc=0 + sha 回到 `73bede2def2e` ⇒ 复跑 `16 passed`。台 B 在内存里换 `_index_eol_records` / `_tracked_paths` 两枚接缝：合成 listing 丢一行 ⇒ 红（B1 `deploy.ps1`、B2 `run_p0_failover_acceptance.sh`）；跟踪面多一枚幻影路径 ⇒ 红（B3，反向）；3 枚全虚构记录 vs 真实 313 ⇒ 红（B4，钉不依赖真实 git 态）；只换旧式正则 ⇒ 红（B5）。**D5 假绿现场复证**：门文件未跟踪，注入真改动（48603→48604 字节）后 `git diff --exit-code` 仍 rc=0、`git status` 仍 `??`、`git ls-files` 空 ⇒ 本任务复原证明一律用字节 `cmp`。**终态**：门册 **16 绿 / 0 红**（`EXPECTED_COLLECTED` 仍 **1332**、`def test_` 与 `_OWN_TEST_NAMES` 均 16、差集空、覆盖度钉落在 helper 里**没有加门**）、SEC-A **46 绿且零新增豁免行**（`git diff --exit-code` rc=0、sha `fd39d7d374f9`）、全量两格 **1332 passed / 0 failed / 0 errors / 1133 subtests / 36 warnings / rc=0**（cwd=`E:\xiangmu\rag` 214.58s、cwd=`E:\xiangmu\rag\backend` 210.26s；两格 `.env` 状态同为"`backend/.env` 在场、未挪未删、sha `4d7f974107dd`"）；门文件 48603 字节 / **CR 0** / LF 810 / sha `73bede2def2e`、仅标准库、无 `yaml` 无 `app.*`；`.gitattributes` `cmp` vs `snap-task4-post/gitattributes` rc=0（`c5d07b5dc438` 不变）、`ci.yml` `1c706e165b73` 不变、两枚 identity 未触碰、`git status --porcelain` 仍开工那 8 行；三台探针与全部合成面都在仓外 `%TEMP%\b0t4f1\`（本轮按约束刻意不归档进 `tmp/`）。快照 `snap-task4-fix1-post/test_ci_gate_contract.py`（与源文件 `cmp` 逐字节相同）。**远端 CI 读数本轮不主张**，归后续回合。

- **Task 4：独立评审 = 规格 ✅ / 质量 Approved**（0 Critical / 1 Medium M1 / 4 Low）。评审把我的
  "首次全绿"这句话**证得比我说得更狠**：`.gitattributes` 一落地，`_EOL_LINE` 的 `attr/\S*` 就抽不动含空格的
  属性列 ⇒ 解析行数 313→311，被丢的恰好是 `scripts/deploy.ps1` 与 `.superpowers/scripts/run_p0_failover_acceptance.sh`
  ——仓库里对行尾最敏感的两枚文件，两枚行尾门当场变盲而**照样绿**（两行今天都是 `i/lf`，不违反任何不变式）。
  这是 B0 自己的交付物触发的 §3 F1/F6，属"门自己骗自己"的教科书样本。
- **R13**：按卡 K 修复（覆盖度钉为主判据 + 正则 `attr/[^	]*?`），门数与常数不动。修复轮 1 复评六点全过：
  行数 313/313 且两枚找回路径点名、覆盖度钉 fail-closed（git 非零 rc / 空面 / 幻影记录三向复红）、
  两侧统一 `-z` 规避 20 枚非 ASCII 路径的八进制引号口径差、无白名单、`cmp` 复原 rc=0。
  终态：**门 16 passed / 0 failed**，全量两格 `1332 passed`，SEC-A 46 绿、零新增豁免。
- **Task 4 待观察项（登记，不阻塞）**：覆盖度钉自身没有"tracked 非空"地板，0==0 时会放；
  现由 `i/-text` 枚举集合钉兜住（评审实测该角落仍红）。Task 6 的变异台应有一发专打这个角落，
  否则这层依赖是隐式的。
- **Task 4: complete（工作树态；规格 ✅，M1 已闭环）**。**B0 至此第一次全绿**：1332 passed / 0 failed 两 cwd 同值。
- **R14（Task 5 回执，2026-09-28；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据全在 `task-5-report.md`
  + 36 枚裸档 `evidence/`（含四枚可复跑取证脚本），快照 `snap-task5-post/` 逐枚 `cmp` rc=0）**：验收证据任务，**未产任何生产代码**。
  **B0-09 漂移复量 GREEN**：`5 passed, 41 deselected`；`surface files 318 hit files 16 occurrences 31`
  ⇒ 命中/处数与 SEC-A 封版**一字未动**；面数 316→317→318 三时点算术自洽（313 tracked + 5 枚 B0 自产 untracked，
  逐枚点名：规格/计划/探针/门模块/`.gitattributes`），tracked 侧由 `git ls-tree -r HEAD | wc -l` = 313 证明 B0 中性；
  SEC-A 的 258 → 313 那 55 枚**不是 B0 的账**，是 `f6c67b5` 用 `git add -f` 入库的 `.superpowers/` 过程件（实测 `git ls-tree` 逐 commit 对照）。
  **敏感性复验按两条硬要求落地**：`trap 'rm -f "$PROBE"; unset PROBE' EXIT INT TERM` + 结尾断言面数回到植入前
  （318 → 319 → 318，植入态 `17 命中 / 32 处` 且归因串逐字点名探针，删除后 `5 passed`、status 回开工 8 行）；
  **trap 的兜底性被现场证了一次**——第一版脚本 `cd` 层数算错、主体跑空、非零退出，探针仍被 trap 删净。
  **四格（§8.1，改造后终态版）GREEN**：仓根/.env 在场 `1332 passed, 36 warnings, 1133 subtests in 211.46s`、
  backend/在场 `209.89s`、仓根/移开 `204.31s`、backend/移开 `209.84s`，四格 rc=0 且 `FAILED/ERROR` 计数 0；
  `.env` 用 `mktemp -d` 挪出仓库、树内 `.env` 形状自检 `(none)`、park 期间面数仍 318、还原 sha `4d7f974107dd…` 逐字节一致；
  归一化签名 1↔3、2↔4 相同（`.env` 轴逐行等，cwd 轴差 24 行**全是** `backend/tests/…` vs `tests/…` 路径前缀）；
  Step 3 的 CI 形态格与 Step 2 的 root 格**逐位相同**（1332/36/1133/0/0/rc0），无需 §10.3 归因。
  **B0-15 容器格取到读数（不是 BLOCKED）**：镜像 = 发布镜像 `rag-backend:security-a-rc1`，实测 `Python 3.12.14`
  + 15 条 requirements 全在场，补 `pytest 9.1.1`（与宿主同版）与 `git 2.47.3`；树按交付面 tar 进容器自身文件系统
  （**刻意不 bind mount**：Windows 挂载会把容器内写实打到宿主），`.env` 因被 gitignore 挡在面外而天然不在场 ⇒ CI 形态。
  读数 **`3 failed, 1329 passed, 2 warnings, 1133 subtests passed in 107.52s`（rc=1）**、`1332 tests collected in 11.44s`。
  **三枚红全部落 §10.3 第 1/2 类，没有第 3 类（app 语义零触及）**：① ②`test_password_lifecycle_contract` 两枚覆盖面门
  对 starlette 对象形状敏感——宿主 `fastapi 0.135.3/starlette 1.0.0` 的 `app.routes` 类型集是 `['APIRoute','Route']`，
  容器 `0.141.1/1.7.0` 多出一类 `_IncludedRouter`（×4），而 requirements 写的是开区间 `fastapi>=0.115,<1`
  ⇒ **远端 CI 极可能同样红，且与 B0 无关**；③ `test_real_llm_failover_gate` 读的
  `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json` 被 `.gitignore:25` 挡掉（`git check-ignore -v` 实测），
  干净 checkout 里证据 `missing` ⇒ 门要求矩阵写 `BLOCKED` 而 tracked 矩阵写 `GREEN` ⇒ **远端必红**；
  这条是主门第一次真跑 1332 枚的直接暴露，容器格是唯一已取到的本地证据。两枚门模块（`test_ci_gate_contract`、
  `test_secret_hygiene_contract`）在 Linux + `.gitattributes` 生效的树上**零红**。**B0-12 按卡 J 三子句 GREEN**：
  ① 减两枚 identity 后 residue=0、② `--cached` 0、③ sha `3bc681bbc52c` / `2cfab9f18182` 与 progress:48 冻结值逐字符相同
  （identity 两枚逐枚点名"不是我改的"，未提交未动）；辅助：app 下 untracked 0 枚。
  **B0-07/B0-08 复核 GREEN**：`git diff` 正文 `10107` 字节 / `dfa0fbde86b5` = Task 4 钉值逐字符相同（`.gitattributes` 仍 no-op）、
  解析 `313` 行 == tracked `313`（**卡 K 的 311 那族丢行未复发**）、`i/crlf` 0 枚、`i/-text` 恰 3 枚逐名点验。
  **耗时读数（B0-13 的本地半）**：全量 204–211s（宿主四格）/ **107.52s**（容器 3.12 Linux）；
  `--collect-only` 宿主 26.28 / 27.61s、容器 **11.44s**；门模块 34.88s 里**那枚 spawn 收集子进程的门 `call 33.43s`（占模块 96%、
  占全量 15.8%；按容器换算到 CI 形态约 11s ≈ 10%）** ⇒ "为 CI 删掉它"的动机在 CI 侧远小于本地；pip cache 的取舍本地测不出
  （宿主依赖早已装好）⇒ 那半枚归远端。**§11 计数：GREEN 9 / PENDING_EXTERNAL 6 / BLOCKED 0**
  （远端专有的 B0-02、B0-03、B0-10、B0-13 半枚 + 归 Task 6/7 的 B0-11、B0-14 逐行点名，未有一行"顺手当过"；
  B0-14 现状实测为 `G20` 在 gap 文档**零命中**、`G0` 行仍旧措辞）。B0-10 另取两枚**本地强化读数**（非判据替代品）：
  `docker compose config rc=0`、`pwsh rc=0`（pwsh 7.6.6 在场）。字节锚点终检全 MATCH：`.env`/两枚 identity/
  `.gitattributes c5d07b5dc438`/`ci.yml 1c706e165b73`/门模块 `73bede2def2e`，探针与 park 目录与容器**零残留**，
  status 仍开工 8 行。**自登一处取证瑕疵**：两次带套件的 park 周期 wrapper 输出未 tee（套件本体已裸档），
  另跑一枚不含套件的同构 park 补了机械动作裸档，不主张任何读数。
- **Task 5: complete（工作树态；规格 ✅，零 BLOCKED）**。改造后终态四格齐平 `1332 passed / 0 failed`、
  B0-09 漂移为零（16/31 一字未动）、B0-12 三子句全绿、容器格取到读数并**照出两族"本地绿/远端红"**
  （starlette 开区间解析 + gitignored 证据件）——**这两条是 Task 7 远端往返前必须由 controller 处置的头号项**，
  本任务按 §10.3 只诊断不修（未编辑任何测试、未动 requirements）。B0 至此仍未入库的三枚
  （`.gitattributes` / 门模块 / `ci.yml`）需要在远端往返前取得用户提交授权。

- **Task 5 交付**：四格逐位等读（`1332 passed / 36 warnings / 1133 subtests`，rc=0，`FAILED|ERROR` 计数 0），
  `.env` 还原逐字节相同；B0-09 漂移 = 面 316→318（5 枚 untracked 逐枚归因）、**命中 16 文件 / 31 处与 SEC-A 封版一字未动**；
  trap 守卫的植入-看红-删除复验通过；§11 = GREEN 9 / PENDING_EXTERNAL 6 / BLOCKED 0；
  36 枚裸档入 `evidence/`。零残留、零提交。
- **R15（Task 5 的容器格 + 用户裁定）**：B0-15 那一格取到读数，且**格内 3 枚红**，是本计划目前最值钱的发现：
  ① 两枚 SEC-A 覆盖门对 `app.routes` 的库内部形状敏感。同一条 `fastapi>=0.115,<1` 在宿主解出
     `fastapi 0.135.3`、在容器解出 `fastapi 0.141.1`；**多出顶层 `_IncludedRouter` 条目是 FastAPI
     `routing.py` 的行为，不是 Starlette 的**（评审在镜像里逐文件核过：该符号只出现在
     `fastapi/routing.py`，starlette 1.7.0 全包零命中）。⇒ 顶层枚举漏 5 条腿。
     CI 会在它自己那天重解析，所以这两枚**远端很可能同样红**，与 B0 改造无关。
     （原始报告与 R14 把它归给 Starlette，归因对象错、结论不变；修复者按本条为准，别再翻错包。）
  ② `test_p0_row_status_matches_the_evidence` 读一枚被 `.gitignore:25` 整目录挡掉的过程件；本机有 ⇒ 绿，
     干净 checkout 无 ⇒ 矩阵写 `GREEN` 而门判 `BLOCKED`，当场红。B0 之后主门第一次真跑全 1332 枚，
     这条是第一次被暴露，**容器格是它唯一的本地证据**。
  ③ 用户裁定（本条为裁定记录）：**在 B0 内修，按"只改 `backend/tests/**`"的口径**，`requirements.txt` 不动、
     `backend/app` 不动。关键约束由控制器补：**红 1/2 的修法必须是递归展开 `_IncludedRouter`，不是过滤掉它**——
     过滤等于继续假装"顶层枚举 = 全部服务面"这个已经假的前提，属放宽；递归后覆盖面只增不减。
     红 3 的修法须让门自己识别"证据件不在交付面"这一形态，而不是把过程件塞进 git 或改矩阵文字。

- **Task 5：独立评审 = 规格 ✅ / 质量 Approved**（0 Critical / 2 Medium / 8 Low）。评审把我全部关键读数
  **独立重算且逐位复现**：四格 `1332/36/1133` rc=0（它用"进度点数 == 1332"直读 0 failed/0 errors/0 skipped，
  比我引 `grep -c FAILED` 更硬）、`.env` 复原 `4d7f974107dd`、park 确在仓外、
  `318 / 16 / 31` 且扫描模块与 HEAD 逐字节相同（⇒ 豁免表零漂移是被证明的，不是被声称的）、
  trap 周期 318→319→318 零残留、卡 J 三子句 + 两枚 identity sha、六枚字节锚全部复现。
  容器那格的机理它两侧都独立验了（宿主包内零命中该符号；`git check-ignore -v` 命中 `.gitignore:25`），
  并判定"CI 很可能同样红"**成立而非夸大**（红 1/2 是"很可能"，红 3 是演绎必然，措辞强度分级正确）。
- **R16（评审两条 Medium 的处置）**：
  - M-1 归因错库 → 已在本台账与上方 R15 就地改正（Starlette → FastAPI），报告侧由修复轮一并订正。
  - M-2 **"B0 修不了"这句是错的**：§10.1 白名单把 `backend/tests/**`（既有）明列为 B0 靶区，
    §10.3 第 2 类正是"断言写死本机形态 ⇒ 允许改测试"。正确措辞是"**本任务**修不了（约束=不编辑其他测试）"。
    这条错框会把红 1/2 挂到 §10.3 第 1 类（依赖形态，最不可操作的一格），从而在后续被当成"B0 之外的事"绕开。
  - 8 条 Low 全部 deferred（含"容器那格 EOL 证据其实来自 tar 而非 `git checkout`，故只证门代码 OS 可移植、
    不证 CI checkout 满足行尾不变式"——这条重要，Task 7 远端读数才是那一维的权威）。
  - 评审另指出 B0-07 的字面子句"`git diff` 空"在带 `M ci.yml` + 两枚 identity 的树上不可能成立，
    实现按"diff 正文跨 `.gitattributes` 状态不变"重解释并复量 `10107/dfa0fbde86b5`。读数正确，
    但**缺一张修订卡**：Task 7 封版前补（与卡 G/J 同族：字面判据不可满足 ⇒ 等价改写）。

- **R17（Task 5 修复轮落账 · R15 裁定的执行结果与本批新增判断）**：
  - **修 1 已按裁定落地**：`test_password_lifecycle_contract.py` 的枚举改**递归展开**（`_child_nodes` /
    `_walk_surfaces` / `_route_index`），**没有**过滤 `_IncludedRouter`、**没有**把它进白名单；
    派发侧（`_resolve_dispatch`）与绊线侧（`_route_dependants`，include 生效形状下一条端点有**两枚**
    dependant，只打一枚 = 桩打空）同步递归。"为什么递归"的理由记在 helper 头上（`:159-164`），
    不留给下一个人猜（本项目有过一条裸 `isinstance` 过滤被"顺手简化"回去的历史）。
    **宿主形态零变化**（同一进程里 HEAD 副本 vs 工作树副本同场对照：42 == 42、差集双向为空、
    `两侧完全相同 = True`）；容器格两枚红转绿，递归清单在 0.135.3 与 0.141.1 两侧给出**同一张表**
    （48 条全量腿 / 42 条已认证 / 免门 2 条）⇒ 枚举不再随库内部对象形状漂，这才是这条修复的判据本体。
  - **规模按"加重"订正 R15 的"漏 5 条"**：0.141.1 下顶层枚举只看见 21/48 条腿、已认证面 15/42 条 ⇒
    真实盲区是 **27 条腿**（4 枚 `_IncludedRouter` 背后 4+7+2+14）。Task 5 记的 5 条只是
    `MUST_BE_COVERED` 那 8 枚点名腿里被探针抓到的部分。点名 5 条 = `POST /api/conversations/{cid}/messages/stream`、
    `POST /api/agent/query`、`POST /api/agent/query/stream`、`PATCH /api/conversations/{cid}`、`GET /api/auth/users`；
    另 22 条（`/api/evaluation/*`、`/api/feedback`、`/api/search`、`/api/chunks`、`/api/tools` …）
    在旧走法下**既不过门也没人扫**。**白名单一条都不需要新增**（R15 要求"要新增就停下"——未触发）。
  - **修 2 按裁定收窄为"只改文案"**：期望值、判定分支、`return` 全部原样，无 skip / xfail / "不在场即过"；
    证据件缺席时新增那段诊断点名路径 + 现算的 `.gitignore:25` 命中行 + "干净 checkout 不可判 ≠ 已通过" +
    出路是 Task 7 的 `git add -f`（**不是**改矩阵）。**本批回退了一枚在飞做法**：上一轮把证据源改绑到
    已跟踪的验收文档 `docs/MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md §4`（它能让干净 checkout 那格变绿，
    但换掉的正是"证据必须在场"这条正确判据，且舍去 `validate_evidence` 里最硬的逐枚重算 sha1），
    与被替换的那份一起留在 `tmp/t5fix-superseded-doc-anchor_test_real_llm_failover_gate.py` 供复看，**不在交付面上**。
  - **修 3 已落**：报告里两处 "Starlette" 归因 + 一句 "B0 修不了" 全部**就地订正、原读保留**
    （`~~原文~~ + 加粗订正 + 【订正 R16/M-2】批注块`），另把同节抬头 "§10.3 第 1 类" 的可操作类别改判为**第 2 类**。
  - **"登记不修"那项已判定，结论与评审的怀疑相反**：容器 2 枚 vs 宿主 36 枚的差额**整族**是
    PyJWT `InsecureKeyLengthWarning`（14 encode + 20 decode = 34），自变量是 `settings.jwt_secret` 的
    **字节长**——这台宿主 shell 里真有一枚 31 字节 `JWT_SECRET`（`backend/.env` 的 44 个键名里根本没有它），
    容器/CI 未设 ⇒ 落回 `config.py:164` 的 45 字节出厂默认。决定性一步：同一枚容器、同一份 PyJWT 2.15.0，
    注入合成 31 字节 secret ⇒ 该文件 6 枚警告（与宿主同数），注入 45 字节 ⇒ 0 枚。
    ⇒ `PyJWT 2.12.1 ↔ 2.15.0` 的区间漂移**真实存在**（仍归 §10.2 那张依赖账，B0 不动 requirements），
    但它**不是**警告数掉档的原因。**副作用要记账**：警告数不是跨格可比的量，Task 7 远端格几乎必然读到
    个位数警告 ⇒ 远端判据要么**格内自比**，要么在 job 里显式声明 secret 长度档再钉数，否则会被误判成回归。
  - **读数与纪律**：宿主两 cwd `1332 passed / 36 warnings / 1133 subtests` rc=0；
    干净 checkout 模拟（过程件挪到仓外）`1331 passed / 1 failed`，且该枚在两个 cwd 下同形红
    （`kit.EVIDENCE_FILE` 由 `__file__` 锚死）；容器格两枚模块 `1 failed（预期那枚 P0）/ 91 passed`、
    收集仍 **1332**。门模块 16 绿、SEC-A 46 绿、豁免表零新增，四枚字节锚 MATCH
    （`.gitattributes c5d07b5dc438` / `ci.yml 1c706e165b73` / 门模块 `73bede2def2e` / requirements `beea80c42159` 与 HEAD 同字节），
    `git diff --cached` 空、**零提交**、app 面减去两枚 identity 后为空。
  - **自登一处取证瑕疵**：模拟格的 wrapper 里 `trap` 用了相对路径而后半段 `cd backend` ⇒ 退出时未命中、
    过程件一度停在 `.r15parked`；收工自证当场抓到并手工还原（sha `2ec6460041da…` 逐位相同、树内零残留）。
    规矩入档：**带 `cd` 的取证脚本 trap 一律用绝对路径**（§16 卡 F 同族）。
  - **交给 controller / Task 7**：`real-llm-failover-001.json` 上交付面那一步**仍待用户显式授权**；
    在它落地之前，CI 首跑必红这一枚——现在是**可诊断的红**（说的就是那枚件没入库），不是假绿、也不是误导性的红。

- **R18（R15 修复轮的复核 = 由用户本人执行，取代本会话的定向复评席位）**：判定
  `ACCEPTED-WITH-ONE-DELIVERY-BLOCKER`。逐项：FastAPI 路由枚举 / 跨版本覆盖面 / must-change 覆盖门 /
  白名单完整性 / P0 门语义 / 代码范围纪律 / 测试放宽=0 / git 写=0 ⇒ **GREEN**；
  **唯一 BLOCKED = P0 evidence 的交付面缺件**（本机有效且在场、干净 checkout 缺失，两 cwd 均复现 ⇒ 非路径偶然）。
  规模订正被采纳：**旧问题不是"漏 5 条端点"，而是"顶层枚举在新版 FastAPI 下漏 27/48 条服务腿"**，
  `MUST_BE_COVERED` 点名的 5 条只是它恰好能抓到的子集。
  修 2 的处置被确认为正确：**不为消红把证据锚改绑验收文档自述**，只增强失败诊断；判据保持
  "缺失 ⇒ 仍红、不 skip、不 xfail、不用 markdown 代替原始 evidence"。
  **下一动作 = Task 7 staging 精选 `git add -f` 纳入该 evidence 件，并在真干净 checkout / CI 面复验 1332/0**；
  那条格也绿之后 Task 5 这条链才算闭合。
- **R18 派生的两条后续项，按用户指示不塞回 Task 5**：
  ① **warning 数不得建跨环境绝对值门**（宿主 `JWT_SECRET` 31B 触发 34 枚 `InsecureKeyLengthWarning`，
     容器默认 45B 不触发 ⇒ 36 vs 2）。将来只允许两形态：同 job 内 before/after **差值**，
     或先钉死 `JWT_SECRET` 长度与类别再取绝对数。已写进规格 §14 L9。
  ② **FastAPI / PyJWT 开区间仍是真债**：本轮修的是症状（枚举改递归），没修依赖解析可复现性。
     归 B1 依赖策略（锁文件 / 上界 / 安装面与运行面同源）。已写进规格 §14 L8 与 §15 的 B1 交接项，
     并要求封版文档不得把"症状修了"写成"漂移解决了"。
- **取证纪律留档（不擦）**：本轮报告主动登记了一次自身瑕疵 —— `trap` 因 `cd backend` 后改用相对路径，
  令一枚过程件一度未还原；最终由锚点检查抓出、手工恢复并核 SHA。按用户判定，这类瑕疵**必须留在台账里**，
  它比"无痕完成"更有价值。Task 6 的 `--check` 字节还原核就是为这类事故准备的。
- **R19（Task 6 回执 = B0-11 变异台六发，2026-09-28；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据 `task-6-report.md` + `mutation-bench.txt`）**：十六枚门**首次被观测到红过**。台子 `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py`（SEC-A 字节安全四条一字不落：读字节 → `bytes.replace(old,new,1)` → 定向 pytest → `finally` 写回**读到的原字节**（不从 git 取）→ sha1 核对，不过即 `SystemExit(3)` 中止整轮；锚点必须恰好命中一次，0 次 `TARGET-NOT-FOUND` / >1 次 `ANCHOR-NOT-UNIQUE` 都不动树；import 期重钉 UTF-8；`REPO = parents[4]`），另加四处本台特有的：目标跨到仓库根（`ci.yml` / `.gitattributes`）、needle 按磁盘字节形态写、还原除 sha1 外另核一次外部 `cmp`、定向跑**整枚 16 门模块**而非计划表里点名的单枚函数（否则"一发杀两枚"会漏读第二枚，N3 正是这种；每发 19—34s、严格串行）。**六发 6/6 KILLED**：N1 `conftest.py` 插一行 `collect_ignore=["test_web_security.py"]`（"日常最容易的藏"，不改名不加 skip）⇒ 收集数钉红、`1329 ≠ 1332` 且失败信息逐枚点名消失的 3 枚 node id；N2 加**真 step**（不是注释——门先过 `_step_script()` 剥注释，树上那句"已删除"的注释杀不掉它）⇒ 单 runner 钉红；N3 `-r backend/requirements.txt` → 手写六包清单 ⇒ **双杀**（同源钉 + 豁免表钉）；N4 追加未豁免包 `bandit` ⇒ 只红豁免表钉、同源钉**正确地不红**（"装什么"漂了"从哪儿装"没漂，两枚门的分工互为反向对照）；N5 删 `*.sh text eol=lf` ⇒ 行尾规则钉红，而覆盖度钉 `313==313` 绿、`i/crlf` 绿、no-op 证明绿（`attr/` 列退回 `attr/text` 照样被 `attr/[^\t]*?` 吃下）⇒ **"规则被删"这一格只有门 13 一枚在守，本发证明它守住了**。**N6 = KILLED，但结论要说平白**：两侧同时收空（`records=[]` + `tracked=[]`，只收 tracked 一侧是 `313==0` 响亮地红、表达不出评审那一格）后，**覆盖度钉确实在 `0 == 0` 上放行、`i/crlf` 消费门跟着变空判绿**（Task 4 评审登记的"无非空地板"被证实存在），拦下来的是 `i/-text` 枚举集合钉（`set() ≠ 那三枚具名`）⇒ 兜底链生效、**不回 Task 2 修门**，但这是"这一族组合有牙"而非"覆盖度钉单独有牙"；**建议 controller 裁**：给 `_index_eol_rows()` 补 `assert records and tracked`（与卡 I (2) tokenize 非空、门 16 扫不到 `- name:` 即红同族），本轮按纪律**未动任何判据**。自我存续两枚钉（卡 H）在 N1/N6 下**都没跟着红，是设计使然不是漏判**：被藏的是别家模块、N6 不增删 `def test_`。**歧义 4 处全按磁盘原文消解、判据一字未改**：`_GUARDED = False` 命中 2 次（模块级 :157 + 夹具 finally :774 的后缀）⇒ 补 `_SESSION_GUARD` 行；三枚 ci.yml needle 用 `\n` 拼 ⇒ **0 命中**（磁盘实测 147 CRLF / 0 裸 LF，`read_text()` 的 universal newlines 会伪装成匹配）⇒ 改 `LC()` 且唯一性检查走 `read_bytes().decode`；`-r backend/requirements.txt` 与 `hashFiles('backend/requirements.txt')` 核对不构成第二次命中；N6 两枚锚避开门 16 里那枚 `tracked = subprocess.run(...)` 同前缀形状。**零残留**：每发 `sha1 同 + cmp rc=0`，六发后四枚目标字节锚全部回到台账值（`.gitattributes c5d07b5dc438`/435B/CR0、`ci.yml 1c706e165b73`/7106B/CR147、门模块 `73bede2def2e`/48603B、`conftest.py 2ff38f8a68a1`/56751B），跟踪面聚合 sha **before == after**（task-4 同配方：`WORKTREE-AGGREGATE d30366c6a440`/313 枚 + 剔掉两枚既有 identity 的 `EX-ID 2685edde76fe`/311 枚，两口径逐字符相等；两枚 identity 保留在聚合内当"别的跟踪件也没动"的旁证、**不去"修"**它们，另算 EX-ID 口径免被稀释），`git status --porcelain` 十行逐字相同（相对 R12 的 7 行多出的 2 枚 `M` 是 Task 5 修复轮既有改动、before/after 同值），聚合值相对 Task 4 的 `53bb297dbc72` 漂移即由那两枚解释、**比较基准取本轮自己的 before**。`--check` 不注入不跑任何东西：**10/10**（6 发锚点 + 4 枚字节），sha1 常数是开工前钉进脚本、不是跑完回填。收工全量套件复跑 **1332 passed / 0 failed / 36 warnings / 1133 subtests / 121.26s / rc=0**（与 R15/R17 宿主读数同量），`FAILED/ERROR` 行 0 枚。产物三件 + 过程件全在 gitignored 的 `.superpowers/` 下 ⇒ SEC-A 扫描面**零新增豁免**；快照 `snap-task6-post/`（台子/表格/报告/progress，与源件 `cmp` rc=0）。**与任务书一处偏差照登**：路径写的是 `ENTERPRISE_B0/`，仓库里那一级实为 `ENTERPRISE_B0_PLAN/`（Task 1—5 同）。远端 CI 那一格仍无读数，归 Task 7。
- **R20（Task 6 修复轮 1 回执 = R19 交给 controller 的那枚地板落地，2026-09-28；修复轮 1/5；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据 `task-6-report.md`《Task 6 修复轮 1》F1—F7 + `tmp/task6fix1-*`）**：controller 裁定"现在补"，理由是补它本身就是 B0 的论点（不许有静默的空判绿）。**只动 `backend/tests/test_ci_gate_contract.py` 一枚文件、+25/−3 行、不加门、既有判据一字未弱化**（`assert len(parsed) == len(tracked) and not missing and not extra` 连同失败信息整体保留）。判据从"两道"成"两道地板 + 逐条计数 + 路径集合"：`_index_eol_rows()` 里 `assert tracked`（行 714）与 `assert parsed`（行 729）挂在等量之前，红的话术对齐同文件 `assert checked` 与卡 I (2)——说**钉哑了**、绝不说仓库干净。**N6 单发在台子上按 id 改前/改后各复跑一次（台子一字未改，`main(argv)` 本就支持选发；注入总数 3 = 两发注入 + 一次 `--check`，每发 `sha1 同 + cmp rc=0`）**：改前 `1 failed`（只红兜底 `test_non_text_index_entries_are_exactly_the_enumerated_set`、`:750`、`test_index_has_no_crlf_entries` **空判绿**），改后 **`2 failed, 14 passed`**（`test_index_has_no_crlf_entries` 与兜底**都红在 `:714` 那枚 `assert tracked`** ⇒ 击杀者是覆盖度钉自己，兜底不再是唯一守门人；`450484c09592→5c8ec7fb9839` vs `a0b9f37f32bb→eb4a49aa6d75`，两枚 needle 仍 `[1, 1]`）。反证台 `tmp/task6fix1_floor_jig.py` 把两枚接缝喂合成面四格：A 真实面改前/改后**都放行**（本轮不造假红）、B N6 形改前放行→改后红（跟踪面地板）、C 只收记录一侧与 D 记录 313 条但一枚都解析不了（tab→空格 = 卡 K 原形）改前就红、改后红在解析面地板且带未解析样本。**计数 vs 集合查到的结论是不必重构**：既有断言早含路径集合**双向**差（`missing`/`extra`），实测"同基数换集合"那一形**改前就红**（`313 vs 313` 仍红）⇒ 本轮没复制任何逻辑；分工要说清——计数按记录条、集合按去重路径，中间 `rows = dict(parsed)` 会折叠重复，另登记一条**本轮不修**的既有边界：集合比的是路径而不是 `(路径, index 列)` 二元组。**终态**：门册 **16 绿 / 0 红**（23.42s；`def test_` 与 `_OWN_TEST_NAMES` 均 16、`EXPECTED_COLLECTED` 仍 **1332** 未改也未凑，`scripts/b0_collection_probe.py` 实测 `TOTAL 1332` 且本模块 16 枚）、自我存续两枚钉同格绿（新字节里哑门装饰器 0 命中）、全量套件 **1332 passed / 0 failed / 0 errors / 36 warnings / 1133 subtests / 129.53s / rc=0**（`^FAILED|^ERROR` 0 枚，与 R19 的 121.26s 同量）。`--check` **9/10 rc=1**：锚点 6 发全 `ANCHOR-OK`（含 `N6 counts=[1, 1]`）、`.gitattributes`/`ci.yml`/`conftest.py` 三条 `RESTORED-OK` 回到常数，唯一 `RESTORED-MISMATCH` 是本轮**有意**改动的门模块（常数钉在禁改的台子里、本轮不回填，新字节锚 `sha1 a0b9f37f32bb` / `sha256[:12] 699b0dfa8d9e` / 50994B / **CR 0** / LF 832；注入态 `eb4a49aa6d75` ≠ 树上值 ⇒ 差异是改动不是残留）。**零残留**：跟踪面聚合 sha 三时点回到台账值 `WORKTREE-AGGREGATE d30366c6a440`/313 枚 + `EX-ID 2685edde76fe`/311 枚（门模块与 `.gitattributes` 都是 `??` 未跟踪件、不进这一面，聚合相等读的是"没动任何跟踪件"），`git status --porcelain` 仍那 **10 行**、两枚 identity `3bc681bbc52c` / `2cfab9f18182` 一字未碰也不去"修"。diff 的信任根：改前字节由 `tmp/task6fix1_make_diff.py` 逐字反演、核到 `sha1 450484c09592` **等于**台账常数（不等即自我作废），因为门模块未跟踪、`git diff` 对它恒返 0（D5 那一族）。产物全在 gitignored 的 `.superpowers/` ⇒ SEC-A 扫描面**零新增豁免**；快照 `snap-task6-fix1-post/{test_ci_gate_contract.py,ent_b0_mutations.py,task-6-report.md,progress.md}`（与源件 `cmp` rc=0）。**交 controller 两项**：①门模块新字节常数待下一轮有授权时替换进 `BASELINE_SHA1`（否则 `--check` 长期报这一条）；②`(路径, index 列)` 那枚边界仍属"没有第二份真相可比"，与 §14 L6 同登记口径。远端 CI 那一格本轮仍无读数，归 Task 7。
- **R21（Task 6 修复轮 2 回执 = 变异台自身的归因仪表 + 常数重锚 + 两发补量，2026-09-28；修复轮 2/5；工作树态、零提交、零 git 写命令、HEAD 仍 `7cc5efc`；证据 `task-6-report.md`《Task 6 修复轮 2》G1—G10 + `tmp/task6fix2-*` + `mutation-bench.txt`）**：**只动台子 `mutations/ent_b0_mutations.py` 与诊断件 `baseline/collected-node-ids.txt`，`backend/tests/test_ci_gate_contract.py` 一字未改**（收工 sha1 `a0b9f37f32bbab9580023b230a79a206ad1e0cbf`、与 `snap-task6-fix1-post/` 那份 `cmp` rc=0、`def test_` 仍 16、`EXPECTED_COLLECTED` 仍 1332）。**I-2（仪表不归因）**：`"KILLED" if rc != 0` 只对"整枚 16 门模块"说话，`spec["node"]` 被收集却**从未打印、从未参与判定**，于是修复轮 1 的 N6 报 KILLED 而它计划钉住的门当时正空判绿——改法 = 新增 `decide(rc, red, assigned)` 四态（`KILLED-ASSIGNED` 计划门**全部**在实测红面里 / `KILLED-INCIDENTAL` 别的门红而计划门绿 ⇒ **这一发失败**、整轮 rc 非 0 / `COLLECTION-BROKEN` rc≠0 而 `FAILED/ERROR` 一枚读不到 ⇒ 命令没跑到断言层 / `SURVIVED` rc=0），`MUTATIONS[i]["node"]` 扩成 `["nodes"]`，逐发打印 `计划钉住 / 实测红面 / 判决`，表格加四列；顺手自食一枚教训——`gate_roster()` 首版按"去 `def `、去末字符"取门名把括号留在名字里，八发全 ASSIGNED 而溯源表整列 NEVER，改 `^def (test_\w+)` 现读。**整轮重跑（终态台子字节产出正式件）N1—N8 = `8/8 KILLED-ASSIGNED`、`KILLED-INCIDENTAL` 0 枚、台子 rc=0，每发 `sha1 同 + cmp rc=0`**（N1 b0c5eee33ccd→5fa40bed5e3f、N2 931846cba857→bded7c6c802d、N3 →9985973a1dd5 双杀、N4 →7bbab2f31091、N5 5738e2743ea7→90885abbf68d、N6 a0b9f37f32bb→eb4a49aa6d75 **两枚计划门全红在 :714 的 assert tracked**、N7 →0ca2edd50e16、N8 →582bca1b201e）。**I-1（`BASELINE_SHA1` 陈旧、`--check` 从此恒 rc=1）**：重锚**不取磁盘现值**、取 `snap-task6-fix1-post/test_ci_gate_contract.py` 并与树双证（sha1 逐字符相同 + `cmp` rc=0），**旧→新 = `450484c09592ef3e89f8798c65737c563e4ca217` → `a0b9f37f32bbab9580023b230a79a206ad1e0cbf`**（`sha256[:12] 699b0dfa8d9e`/50994B/CR0），其余三枚常数一字未动（本轮没合法改过它们）；`--check` 在"重锚后、加发前"那一格实测 **10/10 rc=0**（取法诚实：台子原文先存 `tmp/task6fix2-harness-with-n7n8.py`，切成临时六发版 `ast.parse` 复验后跑，再整枚拷回 `cmp` rc=0），M-1 落地后终态 **12/12 rc=0**（锚点 8 发 + 字节 4 枚）——不变式是"每条都过、rc=0"，条目数随发数长。**M-1（16 枚里 4 枚从无红读数）**：补 **N7 = 改门模块里一枚 `def test_` 的函数名**（宾语 `test_backend_contracts_runs_the_pytest_suite` ⇒ `n7_renamed_away_from_test_prefix`，仓库无 pytest 配置文件 ⇒ `python_functions` 默认 `test*` 确实脱离收集），实测 **`2 failed, 13 passed`**：总数钉 `1331 ≠ 1332` 且"消失 1 枚"点名的就是被改名那枚，**卡 H 自我存续钉 `本文件应有 16 枚，实收 15 枚`（:130）第一次真红**——这正是 Task 2 那次 skip 注入实验欠的 Proof（枚数钉对哑门无感已证，改名/摘走这一形此前无人量过）；补 **N8 = 把 `PIP_INSTALL_EXEMPTIONS["pytest"]` 的『为什么』砍到 `占位`**（4 字 < 12 地板、`count` 未动）⇒ 只红 `test_every_exemption_row_states_why`（:500），与 N4"装什么漂了/为什么允许漂了"互为反向对照。**溯源表（本轮 9 枚红由台子 `print_provenance()` 现算，跨 Task 2—6 累计 14/16 有真红读数）**：补完 N7/N8 后仍无红读数的是**门 4 `test_collection_measurement_counts_node_ids_not_the_summary_line`**（helper 自测：宾语是写死在函数体里的四行样本，只有 `_NODE_ID` 被改坏才可能红，而 T2 A 组已用同一枚真实门函数证过接缝接得上；为它造变异等于把单元测试包装成门）与**门 16 `test_eol_rules_are_a_no_op_for_the_current_tree`**（回归守卫：树上合规时它**必须**绿，非空性由 `checked=2 / offenders=0` + 它自己的 `assert checked` 地板独立量过；要让它红得往树里真写一枚 CRLF `.sh`，那是禁改面且属 Task 4 §7 判据本身）——两条**明写进报告 G5，不悄悄略过**。规格 §9 第一行的"文件级改名"本轮**没有**逐字落（会把另一枚跟踪测试文件的重命名带上树），N1 落"整枚模块脱离收集"、N7 落"改名"但宾语降到函数级，按偏差照登。**M-3**：`run_node(node, code)` 按**变异代号**取 key（改前八发宾语都是同一枚门模块 ⇒ 盖进同一份、只剩最后一份，修复轮 1 为此重跑过 N1）；本轮八份 611—3515 字节互不覆盖，全复制进 `tmp/task6fix2-red-N{1..8}.txt`。**M-4**：`baseline/collected-node-ids.txt` 仍是 Task 1 的 **1316** 行面 ⇒ 门 1 的失败信息打印幽灵"新增 16 枚"（T3 §五 红相件里就实录并解释过这一句），用 `python scripts/b0_collection_probe.py --node-ids --out …` 重生成到 **1332** 行面（sha1 `7d414d853c6d…` → `953f80ffbf3e…`、CR 0/LF 1332、**纯超集**：丢 0 枚补 16 枚且 16 枚全是门模块自己），"判据不读它"这一 claim 由两枚实测兑现：①重生成后复跑整枚门模块 **`16 passed in 21.86s`**；②本轮红相 N1/N7 两份存档件的失败信息都是 `新增 0 枚：[]`。**登记为开放边界（不实现，归 controller）**：评审原话逐字入报告 G8——R20 的地板仍能被**自洽的小假面**哑掉一枚形状（记录一枚、路径同时是唯一的跟踪面条目 ⇒ 地板 + 等量 + 集合三关全过，只有硬编码 `i/-text` 枚举集合钉红），proper 闭法是把 `len(tracked)` 钉到一份独立第二真相（如 `git ls-tree -r HEAD` 的计数），与 §14 L6 / R20 F3"集合只比路径不比 `(路径, index 列)`"同族 ⇒ **不当已解决、也不当已修**，实现它要动判据。**终态与零残留**：注入总数 **32 = 四个完整八发周期**（每发各一次注入 + `finally` 写回原字节 + `sha1 同 + cmp rc=0`，32 次全过、0 次 `RESTORE-FAILED`/`SystemExit(3)`；**只有第四周期是正式件**，前三周期各被仪器自身一处缺陷作废——`gate_roster()` 把 `()` 留在门名里 ⇒ 溯源表整列 NEVER、溯源 footer 的分母写死 `16`、footer 的发数写死八发；三次的**判决本身逐字相同**、八发 sha 迁移在四个周期里逐字符相同 ⇒ 被推翻的一直是表格文案，不是任何一发读数；另加四次 `--check`，不注入）；跟踪面聚合 sha before/after 回到台账 `WORKTREE-AGGREGATE d30366c6a440`/313 枚 + `EX-ID 2685edde76fe`/311 枚，四枚目标字节锚全部回到常数（`.gitattributes c5d07b5dc438`/435B/CR0、`ci.yml 1c706e165b73`/7106B/CR147、`conftest.py 2ff38f8a68a1`/56751B/CR0、门模块 `699b0dfa8d9e`/50994B/CR0），`git status --porcelain` 仍那 **10 行**、两枚 identity `3bc681bbc52c`/`2cfab9f18182` 一字未碰也不去"修"；全量套件两次（第一份收在第二周期后、终态那份收在正式八发与快照之前）**1332 passed / 0 failed / 0 errors / 36 warnings / 1133 subtests / 144.22s / rc=0**（前一份 202.66s 同量、同样 0 枚红；`^FAILED|^ERROR` 0 枚 ⇒ **32 次注入之后收集数仍是 1332**，这才是零残留的终局判据）。产物全在 gitignored 的 `.superpowers/` ⇒ SEC-A 扫描面**零新增豁免**；快照 `snap-task6-fix2-post/{ent_b0_mutations.py,collected-node-ids.txt,mutation-bench.txt,task-6-report.md,progress.md}`（与源件 `cmp` rc=0）。**交 controller 一项**：G8 那枚"自洽小假面"边界。远端 CI 那一格本轮仍无读数，归 Task 7。

- **Task 6: complete（工作树态，2 轮修复；规格 ✅）**。终态 = 八发 **8/8 `KILLED-ASSIGNED`**、
  0 `KILLED-INCIDENTAL`、0 `COLLECTION-BROKEN`；`--check` 终态 **12/12 rc=0**，`BASELINE_SHA1`
  由 `snap-task6-fix1-post/` 重锚（`450484c09592 → a0b9f37f32bb`，与树 `cmp` rc=0）；
  聚合面三时点回台账（`d30366c6a440`@313 / `2685edde76fe`@311），`git status` 仍 10 行，
  全量 `1332 passed / 0 failed`，零 git 写、零提交。16 门"被观测到红过"溯源表 = **14/16**，
  另两枚为 helper 自测 / 回归守卫，已如实点名而非默默略过。
- **R22（Task 7 派单前的关键未知量预检，实测）**：P0 证据件
  `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`（18289 B）
  若被 `git add -f` 纳入跟踪，**仍然不进 SECA-20 扫描面** —— `_in_scan_scope()` 按
  `_UNSCANNED_PREFIXES = (".superpowers/",)` 的**路径前缀**排除，与 tracked 状态无关；
  用门自己的 face 手工量得 **0 处命中**，`_BINARY_SUFFIXES` 也不跳它。
  ⇒ 结论与措辞纪律：Task 7 可以安全入库、且入库后面数仍 318（今天它被 `--exclude-standard` 挡在 untracked 外），
  但验收文档**不得**写"该证据件已通过密钥扫描门"；只能写"门按前缀不覆盖此路径，本会话以同一组 face
  手工量得 0 命中"。若将来要真覆盖它，那是改 `_UNSCANNED_PREFIXES` 的安全面决策，归 B1 / §18，不属 B0。

- **R23（远端往返 run 36436145777 @ `9482f44`）**：`backend-contracts` 步骤级 =
  Cache / 同源 Install / SECA-20 扫描 / compileall / demo-assets **全 success**，
  主门 **failure**（`99 failed, 1219 passed, 20 errors / 84.23s`），compose 与 pwsh 两步 **skipped**
  （主门一红即中止 —— §5.2 那条机制当场自证）。
  逐条归因：113 条红/错里 **111 条**同一句 `AttributeError: 'UserIdentity' object has no attribute 'get'`、
  **1 条** P0 证据闸、**1 条** 冷启动登录 500（前者的下游）。
  ⇒ **B0 的改造本身在远端是成立的**（收集、依赖、扫描、顺序全部按规格跑通）；
  红来自两条**早已在已提交代码里**的缺陷，B0 只是第一次把它们跑到门禁上。
- **R24（否证上一封版结论，控制器独立复现）**：在 `%TEMP%` 干净克隆到 `7cc5efc`（= `security-a-rc1`）
  复跑 `test_rbac_contract` 的 login-payload 一枚 ⇒ **同一句失败**；该树 `identity/__init__.py:63`
  即 `record.get(...)`。⇒ **SEC-A 报告的"两 cwd 各 1316 passed"是带着未提交的 identity 修复量出来的**，
  `security-a-rc1` 的树本身不绿。这不是本轮引入的，但它使上一张验收文档的该结论作废，需用户裁如何更正。
- **R25（P0 闸的单机耦合，入库 evidence 不足以解）**：`kit.validate_evidence()` 无条件重算
  `files_sha1` 的**绝对路径**四枚，其中三枚（`run/<ts>/conversations.db`、`agent_traces.jsonl`、
  `ornith-primary-load-probe.json`）落在 gitignored 的 `.superpowers/` 下且未被跟踪 ⇒
  干净 checkout 必然 missing ⇒ 闸要求 `BLOCKED` 而矩阵写 `GREEN` ⇒ 恒红。
  彻底解需入库一次真机运行的 sqlite + trace 原文（`.db` 还会新增一枚 `i/-text`，撞 §6.4 枚举钉），
  或改该闸语义 ⇒ **两条都在 B0 白名单之外**，已停手交用户裁。

- **R26（用户 2026-09-28 三条裁定，B0 停止扩面）**：
  - **① `UserIdentity.get()` 另开 `SEC-A-CORR-01`，不归 B0**。不得把两份未提交的飞书文件整体带进去，
    也不得让 B0 越权改 `backend/app/**`。修正面 = `backend/app/identity/__init__.py` + 直接需要的测试/文档；
    patch 必须**从已提交树重新生成最小形**（工作树 `__init__.py` 的 diff 恰为 `Any` 导入 + 签名 +
    docstring + 一处 `getattr`，即最小面；README 那堆 diff 属飞书未完成工作，**不带**）。
    须加结构钉：`resolve_for_user(UserIdentity(...))` 不得调用 `Mapping.get`（AST 级，不是只跑 happy path）。
    `security-a-rc1` = immutable / known-invalid；`security-a-rc2` 只在 ③ 也闭合且远端主门真绿后签发。
  - **② errata 两层同时做**：原验收文档顶部追加醒目 ERRATA（**保留**原"1316 passed"读数，
    改成"原测量 + 为什么它描述的不是那棵树"），另立 `docs/SECURITY_A_RC1_ERRATA_2026-09-28.md`。
    不 amend、不移 tag、明确 superseded。项目状态与 Obsidian 把 `security-a-rc1 = CONDITIONAL PASS`
    改为 `ERRATA ISSUED / SUPERSEDED / NOT SHIPPABLE`（不是删历史）。
  - **③ P0 证据改"载体"不改"含义"**：不批准把 `.db` + trace 原件整体入库（除撞 `i/-text` 枚举钉外，
    更因它把运行态库/trace/本机 probe 变成仓库长期发布物）；也不批准退回"验收 markdown 说 GREEN 就算 GREEN"
    （那会取消逐文件重算 hash 的反造假性，Task 5 已正确回退过一次）。
    裁定 = 建立 **Portable P0 Evidence Bundle**：真机仍产原始 db/trace/probe，验收 runner 从**原始真源自动导出**
    最小文本化可跟踪包（`docs/evidence/model-router-v23/real-llm-failover-001/` 下
    result/response/ledger-row/trace-attempts/primary-probe/manifest，全 JSON/JSONL）。
    manifest 固定 `evidence_schema_version / trace_id / source_tree_hash / release_image / generated_at /
    portable_files(path+sha256) / raw_provenance(name+sha256)`；
    **portable_files 的 sha256 是 P0 判定事实**（干净签出必须可重算），raw 件 hash 只作 provenance、本体继续 ignored。
    闸在 CI 验七条 interlock（bundle 齐 / manifest hash 全配 / response.model_used == ledger.model ==
    成功 trace attempt.model == phi3:mini / planned primary == ornith-1.5:9b-text / probe == 文档化的
    retryable|model-unavailable 失败 / trace_id 跨文件一致 / 矩阵 P0 行 == GREEN）。
    语义边界：`raw provenance 不在 ⇒ 不影响 portable validation`；`portable 缺失/畸形/hash 不配 ⇒ BLOCKED`。
    **改表示层，不改验收事实层。** 必须配独立八发变异（逐枚改 model_used / ledger.model / trace 成功枚 /
    planned primary / probe result / 删一枚 portable 件 / 改文件不更 manifest hash / 矩阵 GREEN→BLOCKED 全须红）。
    因涉 P0 闸语义代码，**实现后必须独立评审，不得自写自裁**。
- **执行序（用户指定，B0 不参与扩面）**：1 errata → 2 CORR-01 → 3 P0 portability amendment →
  4 两项各自动回归 → 5 全量两 cwd → 6 干净签出 → 7 push → 8 远端 backend-contracts GREEN →
  9 compose/pwsh 首次真执行 → 10 独立终审 → 11 `security-a-rc2`。两枚既有 tag 均不碰。

- **R27（3B 独立评审 = spec ❌ 部分 / 质量 findings；评审为用户裁定的强制席位，非自写自裁）**：
  干净签出转绿这条**已由评审与控制器各自独立复现**（评审自建克隆：`15 passed`、`portable 层 0 问题`、
  `raw_state=json-only`；负控：删 bundle 目录 ⇒ 2 红点名 `[I1]`。控制器自跑副本同样 15 passed）。
  `validate_evidence()` 本体确认未被弱化（§6 内唯一改动是 4 枚标记字面量提成 `MODEL_UNAVAILABLE_MARKERS`，
  逐字节等价）；矩阵 P0 行**逐字节等同 HEAD**、状态字未动；SEC-A 扫描文件 `git diff` 空、零新增豁免。
  **但四条点名条款不成立，全部要修**：
  - **H1** `rehearsal` / `completed` 两条判据在分层时**静默丢失**：往已跟踪的 evidence JSON 注入
    `"rehearsal": true` 或 `"completed": false` ⇒ 仍 `15 passed`（而 `assertions[0].pass=false` 会红，
    说明不是比较器坏了，是这两枚字段没人比）。简报原本写"必须保留"。且它不在 §5 映射表里 ⇒ 属于未申报的放宽。
  - **H2** 唯一的"非彩排正面凭据" `provider_transport` 在**源端退化成"读不到就算过"**：
    `evidence.get(...)` 让"键不存在"与"显式 null"不可区分；删键 + bundle 写 null ⇒ 15 passed。
  - **M1** raw 层是全有或全无：`agent_traces.jsonl` 被篡改 **且** `conversations.db` 被删 ⇒ `15 passed` 静默；
    四枚都在场时同样篡改则红。违反用户钉的"raw 在场但对不上 ⇒ 红"。一行修：`json-only` 分支也要调
    `raw_layer_problems(resolved)`，顺带让 `acceptance_module` 这枚 sha1 在 CI 里第一次获得真重算腿。
  - **M2** interlock 6 可被"字段缺失"满足（`set(...) - {None}` 的写法放过 None）。
  **另有两条一并修（同为加强，成本一行级）**：L6 `green_permission()` 仍只看 `validate_evidence()`
  而 runner 以它退出 ⇒ 3B 重新制造了"闸与 runner 两个口径"，而那正是共享 kit 注释当初要防的事；
  L1 变异台的 anchor 唯一性互锁**是死的**（`shot()` 从不传 needle ⇒ `check()` 恒 None ⇒
  "锚点全 ANCHOR-OK" 是同义反复，与 B0 那枚 `spec["node"]` 同类病）。
  **登记不修的两条**：M3 manifest 外部锚"对同一 diff 内改三处"不设防 —— 评审判为
  "对抗意义上更弱、可用意义上不更弱（3B 前 CI 根本产不出 GREEN，恒红的判据吓不住任何人）"，
  接受但**必须记成残余信任根**，同 diff 不可变锚（CI 变量 / 双独立钉）列 B1 义务；
  L5 报告里"第一轮 9×INCIDENTAL 的原文保留在…"不实（bench 产物与 final 逐字节相同，那轮没留档）——
  披露本身可信（docstring 记了两处仪表缺陷），但这句话要改。
- **提交切分裁定（回 L10）**：本工作树同时带着 CORR-01（identity 面）与 3B（P0 载体面）两批改动，
  评审在零提交会话里无法归因。故**分两枚窄提交**：`fix(sec-a-corr-01)` = `identity/__init__.py` +
  飞书契约钉 + errata 两文件；`fix(v2.3-p0)` = kit + 闸 + bundle + runner + 矩阵说明。
  `backend/app/identity/README.md` **两枚都不带**（飞书未完成文档）。

- **R28（3B 修复轮 1 的控制器独立复测，不采信返回摘要）**：
  - 我**先错两次、都是自己探针的错**，都记下来免得下次再犯：① 第一次"干净签出 1 failed"是因为
    我只拷文件没建 git 仓库，而 M1 新加的 git-blob 腿需要 `git rev-parse`；② 注入轮失败是因为副本里
    `git add -A` 尊重 `.gitignore`，那枚 evidence JSON 压根没被跟踪 ⇒ 注入无对象。修正为
    `git init` + `git add -f -A`（406 枚跟踪、evidence 已跟踪）后重打。
  - **带 git 的真副本实测（raw 不在场 = CI 形态）**：baseline **15 passed**；
    注入 `rehearsal:true` ⇒ **1 failed**；注入 `completed:false` ⇒ **1 failed**；
    删 `provider_transport` 键 ⇒ **1 failed**。⇒ R27 的 **H1 / H2 已修好且是我自己复现的**，不是转述。
  - 锚与载体：`PORTABLE_MANIFEST_SHA256` == 盘上 manifest sha256（`c39a09f83b6a…` 全串等）；
    五枚 portable 件的 sha256+bytes **全部重算相符**；kit 与闸文件语法完好、本地闸 15 passed（34 subtests，
    比修复前 26 多 8 枚 = 新增的退化探针）。
  - **仍未由我复现、不得当作已验**：M1（篡改 jsonl + 删 db ⇒ 红）需要 raw 在场，我不在真证据上动手；
    M2（interlock 6 指针置 null ⇒ 红）；以及九发变异在**anchor 互锁已接通**后的重跑。
    这三项挂在待办，谁主张谁取证。
  - **流程事实**：最近四次派单里三次撞 150 回合上限（活干了、摘要没写回），一次刚开始就死。
    后续这类"改代码 + 跑全套 + 写长报告"的活我自己按小步做，不再整单外包。

- **R29（我自己的一枚坏提交，如实登记）**：`64ec762` 的 `git add` 里放了一个指向 `mutations/` 下
  文件的错误 pathspec ⇒ git 整条 add 静默中止（我又把 stderr 丢了），那枚提交**只含台账与证据文件、
  代码文件数 = 0**，而它的 message 描述的是代码。发现方式：提交后照常看 `git status`，
  见 kit/闸/bundle/矩阵仍是 ` M`。处置：不 amend、不改历史，追加 `71cc5e1` 真提交并在 message 里
  点名 `64ec762` 名实不符；两枚合起来才是它所声称的内容。
- **R30（同一条病的第二次发作，形式不同）**：我随后把"python 追加台账 && git commit && git push"
  串成一条命令，两个 heredoc 嵌套，shell 把整段 Python 当成了 `git commit -F -` 的输入 ⇒
  生出一枚 **message 是乱码、内容正确**（只改 `EXPECTED_COLLECTED` 一行）的提交，
  而台账追加与 push 都没执行。处置：`git reset --soft HEAD~1` 退回重做 message ——
  目标是**我自己在 30 秒前造的、从未推送**的一枚提交，内容经 `--soft` 完整保留在 index，
  与"不 amend 他人历史 / 两枚 tag 不动"是两回事；这条区别本身要记在这里，免得下次拿它当借口。
  **纪律回写（两条）**：① `git add` 多路径必须逐条验、不吞 stderr，提交后用
  `git show --stat` 核对"message 说的东西在不在里面"（与 B0 的 presence pins ≠ effect pins 同病）；
  ② **一条 Bash 只做一件事**，含 heredoc 的命令绝不与 `&&` 链式拼接。
- **B0 侧收口**：`EXPECTED_COLLECTED` 已按实测 1332→**1335** 重锚（CORR-01 新增 3 枚结构钉所致，
  属"加测试"的合法变化），基线明细同步 1335 行；两枚变异台的字节锚各自重钉（B0 台 `4bba148e804d`）。
  全量两 cwd 各 **1335 passed / 0 failed**（182.78s / 183.95s，1159 subtests）。
- **R31（B0 侧文档闭合 + 我自己撞出来的两枚真源问题，2026-09-29）**：
  - **落档**：`83edc17 docs(b0)` 提交并推送 —— `G20` 新开 + `G0` 勘误（B0-14）、B0-02/03/10/13 用
    run `36472389872` @ `b825112` 的 step 级读数闭合，新增 §10.3（11 步全 success、
    `1335 passed / 2 warnings / 1159 subtests in 54.59s`、compose 与 pwsh 首次真跑即绿、
    剩余 run 级 red 逐条归因为 `argon2` / `typesafe_sdk` 两枚 job 的依赖漂移——规格 §1 明令 B0 不得触碰）。
    §11 补 §11.1：**锚点算法此前没标**（同一串 12 位在台账里既有 sha256[:12] 又有 git blob sha1，
    `c5d07b5dc438` vs `1b64d6e47305` 就是这么错开的），现明确为「对原始字节取 sha256 前 12 位」；
    交付面 313→447 的 134 枚逐枚归因（+121 `.superpowers/**` / +10 `docs/` / `.gitattributes` /
    新门文件 / probe 脚本），而命中仍 16 文件 31 处、`EXEMPTIONS` 字节相同 ⇒ 这条比 B0-09 原读数强。
    提交 message 里我把 `a0b9f37f32bb` 误打成 `a0b937f32bb`——文档表格是对的，不改历史，错在这儿记一笔。
  - **我做的坏事（如实）**：把十四发台放后台跑，看到"闸文件常数在变"就误判为异常，**中途 kill** ⇒
    M5 的注入字节残留在三枚已跟踪文件里（`manifest.json` / `primary-probe.json` / 闸文件的 pin）。
    台子本来就设计成"改 manifest 必须同时按 pin"（台头 ③），所以那三处漂移是**正常注入**，
    不正常的是我打断它。处置：`git cat-file blob HEAD:<path>` 逐枚写回原始字节 +
    与 blob 逐字节 `==` 校验 + sha256 复量回 `c39a09f8…`；`git restore` 那一步**不能单独用**
    （见下一条），最后 `git status` 只剩用户自己的 `identity/README.md`。
  - **新发现（真源缺陷，非仪器病）：P0 闸的 `[I2]` 外部锚依赖 checkout 的行尾形态。**
    Windows 干净 clone 实测：六枚 bundle JSON 全部被 smudge 成 **CRLF**，manifest 工作树 sha256
    = `91b0dff6…` ≠ 钉住的 `c39a09f8…`（后者是 **blob/CI** 形态）。⇒ 同一枚 commit
    在 Linux CI 绿、在 Windows 签出必红。`core.autocrlf=true` + `.gitattributes` 的 `* text=auto`
    对没有显式 `eol=` 规则的 `.json` 生效，`docs/evidence/**` 是 B0 §7 四条"不做"里没覆盖的新区块。
    这**不是** B0 的行尾门能抓的（那些钉量的是 index 侧 `i/…`，index 里一直是 LF，无违规可言），
    也不影响远端主门（Linux），但它让"可移植载体"这句话在 Windows 上不打折地成立不起来。
    两条候选，都还没做，**待用户/独立评审裁**：A `.gitattributes` 加 `docs/evidence/** text eol=lf`
    （结构性确定，判据一字不动，代价是改一枚有锚的交付面文件并同步 §11）；
    B kit 哈希前先做 CRLF→LF 规范化（只动载体，但把"逐字节"这句话改弱了）。
    我倾向 A，因为它把决定权放在 git 而不是放在判据代码里。
- **R32（3B 读数由我复现 + 一枚隔离出来的真源缺陷，2026-09-29）**：
  - **复现**（台子与 HEAD 未动，工作树逐字节 == blob 先验过）：`--check` 基线六枚 RESTORED-OK ×6 +
    外部锚在场且唯一 + 序列化可逆；`--anchor-selftest` 两枚错 needle 都响；**整轮十四发
    M1..M9 + N1..N5 = `KILLED-ASSIGNED-RESTORED-OK` ×14，rc=0，计划外附带红 `[]` ×14，
    park 已删**。原始输出 `evidence/p0-3b-bench-controller-repro-2026-09-29.txt`（未入库）。
    ⇒ 简报读数 3 与 3B 报告 F5 从"implementer 声称"升格为"控制器复现"；**读数 4/5 同步复现**：
    SEC-A 扫描门单跑 **46 passed** 且那枚文件 `git diff` 为空（零新增豁免可证）、
    B0 门 **16 passed**、收集探针 **TOTAL 1335**、四枚被触碰模块合跑 **183 passed / 243 subtests**；
    **读数 2** 本机 verdict 三层全清（`raw_state='full'`、portable/truth/raw problems 皆 `[]`、
    两枚运行件 sha1 == manifest 声明）。
  - **残留核对三层**：三枚被注入件 `git cat-file blob HEAD:<path>` == 工作树逐字节、
    pin == manifest 工作树 sha256（`c39a09f8…`）、raw 两枚 sha1 == `raw_provenance` 声明值。
  - **读数 1 的层级必须改写**（不许再说"干净签出绿"就完了）：**Linux/CI 形态**绿（远端 run
    `36472389872` 里这枚闸在 1335 中通过）；**Windows 干净 clone 红**——同一 clone 只把行尾当
    唯一变量：六枚 CRLF ⇒ `3 failed / 14 passed`（`[I2] sha256 不配`，portable 层 17 条问题，
    两枚退化探针**拒绝在坏基线上跑**并明说原因）；改回 LF ⇒ `15 passed / 0 failed / 34 subtests`。
    机制是 git 自己报的：`text: auto` + `eol: unspecified` ⇒ 检出跟 `core.autocrlf` 走。
    ⇒ 待裁两条：A `.gitattributes` 加 `docs/evidence/** text eol=lf`（我倾向这条：git 决定、判据不动，
    但要实测门 13 不会因为多一条规则而红，并同步 `.gitattributes` 的交付面锚）；
    B kit 哈希前规范化 CRLF（改弱"逐字节"，且让判据代码替 git 做决定）。**本轮一条都没动。**
  - 文档落档：`83edc17` 已推送（G20/G0 + B0 §10.3/§11.1）；SEC-A 项目记忆与索引已改写为
    rc1 = ERRATA ISSUED / SUPERSEDED / NOT SHIPPABLE。剩余按用户裁定：独立终审 → rc2（两枚 tag 不碰）。
- **R33（L10 修法 A 落地 + 一次 push 竞态，2026-09-29）**：
  - **改动两处、判据零放宽**：`.gitattributes` 加 `docs/evidence/** text eol=lf`（+ 四行说明，
    435 B/18 LF ⇒ 846 B/23 LF，锚 `c5d07b5dc438` → **`b85430dbe6d1`**）；门 15 的
    `REQUIRED_GITATTRIBUTES_RULES` 由三枚并成四枚（锚 `893d59b4d74b` → **`5ac7220e6c55`**，839 LF）。
    **刻意不新增测试**：并入既有门 ⇒ `EXPECTED_COLLECTED` 仍 1335，实测 `TOTAL 1335`。
    规则只写在 `.gitattributes` 里不够——没钉住的话任何人删掉它就静默退回那台单机耦合的闸。
  - **证伪（这枚钉有牙）**：摘掉 `docs/evidence/** text eol=lf` 那一行 ⇒
    `test_gitattributes_carries_the_required_rules` 当场 `1 failed`，文案点名
    `['docs/evidence/** text eol=lf']`；`finally` 按原字节写回，sha256 复量 + 外部 `cmp` rc=0。
  - **复跑（本机）**：B0 16 + SEC-A 46 = **62 passed**（新 `-f` 入库的那枚 evidence txt 进了扫描面，
    仍**零新增豁免**、`i/-text` 仍恰三枚、`i/crlf` 仍 0）、P0 闸 **15 passed / 34 subtests**。
  - **Windows clone 复核（这是本单的存在理由）**：clone `c29ce8a` 后六枚 bundle JSON 检出为 **LF**，
    manifest 工作树 sha256 回到钉住的 `c39a09f8…`；同一 clone 内 P0 闸 **15 passed / 0 failed**、
    B0 门 **16 passed**。对照 R32 那发隔离实验（CRLF ⇒ 3 failed）——两侧都对上了。
  - **远端**：run **`36533335735`** @ `c29ce8a` ⇒ `backend-contracts` **success、0 枚非成功步骤**，
    `1335 passed / 2 warnings / 1159 subtests in 53.39s`；SECA-20 子集 `5 passed, 41 deselected`。
    Linux 本来就绿，这一格证明的是**修法没把 CI 改坏**。整 run 仍 red 于 `argon2` / `typesafe_sdk` 两枚 job。
  - **push 竞态，如实登记**：`git push` 报 `cannot lock ref 'refs/heads/main': is at c29ce8a but
    expected 83edc17`。取真值而不是猜：`git ls-remote` + `gh api .../commits/c29ce8a` 证明远端那枚
    与我本地这枚**同一 sha、同一 message、同六枚文件**，用户自己的 `identity/README.md` 未被推送。
    最可能原因是压缩前那枚名为 "Commit B0 re-anchor and push all" 的后台任务（因输出超 5GB 被强停）
    的 push 步在我 commit 之后并发执行。**纪律回写两条**：① 跨回合**不留会写 git 的后台任务**，
    派单里的 git 写命令必须是我这一轮唯一 writer；② push 报错后先 `ls-remote` 取真值再决定，
    不盲目重推、更不动 force。
  - **顺带一枚自指事实（登记，不做第二轮扩张）**：`.gitattributes` 自己没有 `eol=` 规则，
    所以 `git add` 它时 git 提示"LF will be replaced by CRLF"——**它管住了别人没管住自己**。
    功能上无害（属性表按空白分隔，与行尾无关），但如果以后要给它自己一条规则，
    得先想清楚这是不是又一条"必需规则"要钉。
- **R34（独立终审回席 + 我逐条复验，含一枚否定我自己的结论，2026-09-29）**：
  - 终审席位：`general-purpose` 只读评审，范围 `7cc5efc..047a0d4`，明令不许动 git 状态、不许跑会改跟踪文件的
    变异台、把用户的 `identity/README.md` 划在范围外。**判决：No — 先修**（Critical 1 条 / Important 6 条 / Minor 6 条）。
  - **我复验为真的六条**（不转述，给读数）：
    1. `git diff --name-only c29ce8a..047a0d4` = 只有 `progress.md` + 一枚验收 md ⇒ 两枚相邻 commit
       **零代码差**，而 `backend-contracts` 读数是 `1335 passed` ↔ `1 failed, 1334 passed`。
       非确定性不是我推的，是这两枚 commit 的关系直接证出来的。
    2. 红腿 `test_typesafe_v2_pipeline.py:1306`（`assertGreater(timings["rerank_ms"], 0.0)`）与产出端
       `retrieval.py:671`（`"rerank_ms": round(rerank_ms, 2)`）在 `7cc5efc..047a0d4` **一次都没被碰过**；
       断言出自 `5ba5f20`（= 已封存的 `model-router-v2.3-rc1`），取整出自 `df9aebf`。⇒ 本轮无责，但本轮把它撞见了。
    3. **换效果钉不是放宽，是向本仓既有冻结裁定收敛**：`docs/SECURITY_A_SPECIFICATION.md:245`
       「latency 分布只作为证据采集，不作为 GREEN/BLOCKED 的输入……毫秒阈值门在共享开发机上必然 flaky，
       而 flaky 的安全门会被下一轮人直接 `skip` 掉，那比没有门更糟」；SECA-13（`:523`）与 §20.8 第 8 行（`:711`）
       已经把替代 oracle 写死成**调用面 spy / 结构事实**。`:1306` 违背的是既有规格，不是我的口味。
    4. 同族还有两枚潜在雷（终审点名，我验实在）：`test_typesafe_v2_core.py:1341`
       `typesafe_latency_p50_ms > 0.0`、`:1572` `latency_p50_ms > 0.0`，产出端
       `main.py:971` 与 `typesafe_judgments.py:517` 同样是 `round(..., 2)`。已红的这枚是**第一枚落地**，不是唯一一枚。
    5. **我写进 §11.1 的那句话是错的，必须改**：我写过「新增的 217 枚 `.superpowers` 过程件里零命中，
       是被门禁跑出来的，不是我扫出来再抄进来的」。实情是 `test_secret_hygiene_contract.py:433`
       `_UNSCANNED_PREFIXES = (".superpowers/",)` + `:575 _in_scan_scope()` ⇒ **整目录免内容扫描**
       （实测面 `448` 枚、进内容扫描 `230` 枚、被跳过 `218` 枚）。所以"零命中"从来不是对那 218 枚的断言，
       命中 16 文件 / 31 处只对 230 枚成立。这是我把"进了面"错读成"被扫了"——**B0-09 的强度被我写高了一格**。
    6. 锚点口径确实混用（终审自己复算出来的）：`ci.yml` 的 `1c706e165b73` 是**工作树**读数，
       `git cat-file blob HEAD:` 是 `e0ff7a206cd3`；`test_ci_gate_contract.py` / `manifest.json` 今天
       工作树 == blob 才侥幸对上，Windows 新 clone 会把它们 smudge 成 CRLF 而对不上。⇒ §11/§11.1 的锚
       应统一改成 **git blob id** 口径（kit 里 `git_blob_of_head()` 已造好），并把「锚是 blob 不是工作树」写进 §7/§11。
  - **另外两条我同样验实**：B0-12 第一子句（`git diff --name-only HEAD -- backend/app` 减去两枚 identity）
    今天只剩 `identity/README.md` 一枚 ⇒ 这条判据已退化成"只看守 README"，需要改成**区间**判据
    （`security-a-rc1..HEAD -- backend/app` 恰等 `9bed85a` 那一枚）；以及 047a0d4 那轮 compose/pwsh
    **又回到 skipped** ⇒ B0-10「首次真跑」是**每轮可能失效的读数**，不能写成历史事件。
  - 仪表侧三条（终审提，我读码确认）：`p0_3b_mutations.py:367` 的 `token in raw` 里 `raw` 是**整轮**输出 ⇒
    哨兵可能来自别的红节点；`:472` `restored_ok and (not path.exists() or True)` 是**恒真死条件**
    （这是本仓自己登记过的第四枚同类仪表病）；B0 台 `ent_b0_mutations.py:338-357` 纯 node-id 归因、
    没有 reason token ⇒「YAML 改坏导致 15 枚全红」也会被记成 `KILLED-ASSIGNED`。
  - **现场保持原样**：按用户裁定，未改那枚断言、未重跑掉这枚红、`047a0d4` 的红灯证据保持可追溯；
    修不修、归到 `TEST-HYGIENE` / 当前 corrective / 单开窄 amendment，由用户裁（任务 #130）。
    RC2 前置已改成硬链（#128 → #130 → #131 → #129）：**要打 tag 的那枚 commit 自己必须绿**，
    "前一枚绿过"不再算数；另需给 `security-a-rc1` 之外的**第二枚封存 tag** `model-router-v2.3-rc1`
    是否补记同一条脆弱腿做决定（它带病在库里，且这枚 tag 用户明令不许动）。
- **R35（终审后的三条裁定落地 + 窄单 `TEST-HYGIENE-01`，2026-09-30）**：
  - **用户三条裁定**：① flaky leg **单开窄单**（不并 corrective、不同族一起扫）；② 过程件**继续发布**，
    把"公开但免于内容扫描"登记成已知限制；③ 给 **V2.3 验收面补记**（tag 仍不许动）。
  - **窄单 `TEST-HYGIENE-01` 已做**：`test_typesafe_v2_pipeline.py:1306` 的
    `assertGreater(timings["rerank_ms"], 0.0)` 换成**两枚效果钉 + 一枚合法性钉**：
    `service._reranker.pools == [["a", "b", "c"]]`（调用面，恰好一次、池内容确定）、
    `[row["rerank_score"] for row in rows] == [1.0, 0.5, 0.0]`（min-max 归一化后的确定值，
    与隔壁 `rerank=False` 用例钉 `[None, None, None]` 成对）、`assertGreaterEqual(rerank_ms, 0.0)`。
    **产品代码一字未动**；依据是本仓**既有**冻结裁定（`SECURITY_A_SPECIFICATION.md:245` + SECA-13
    用调用面 spy 替代毫秒阈值），所以这是向规格收敛而不是放宽——终审独立席位也判"收紧"。
  - **确定性证据**：定向重复 **5/5 passed**（48.97 / 49.65 / 39.22 / 30.79 / 35.08s）；
    整模块 `47 passed / 30 subtests`；`InvariantPathTests` 5 枚全过；SEC-A 46 + B0 16 = **62 passed**；
    全量两 cwd 各 **1335 passed / 0 failed / 36 warnings / 1159 subtests**（297.74s / 272.80s）——
    收集数未动（没加测试，只换判据形态）。
  - **我自己那句错话已就地更正**（终审 Important 5，我复验为真）：§11.1 曾写"新增的 217 枚
    `.superpowers` 过程件里零命中是被门禁跑出来的"。实情 `_UNSCANNED_PREFIXES = (".superpowers/",)`
    让整目录**免内容扫描**：面 448 / 进扫描 230 / 跳过 218 ⇒ 命中 16 文件 31 处只对那 230 枚成立。
    **B0-09 判据本身没坏，是我替它加的那句强度声明是假的**（把"进了面"读成"被扫了"）。
  - **本轮文档动作**：新增 **§14 L11**（过程件公开且按设计免扫，三条后果 + 裁定继续发布的理由 +
    为什么前缀不能随手收窄：那目录里躺着故意写下的 canary）；矩阵 B0-01/04/09/10/15 五行加**读数出处**
    限定语（1332 是重锚前、面 448 是当前、B0-10 是**每轮读数**——`047a0d4` 那轮 compose/pwsh 又回 skipped）；
    `MODEL_ROUTER_V23_ACCEPTANCE` §6 追加第 **10**（本版自带一枚会翻色的腿，含 047a0d4 红的读数）与
    第 **11**（P0 的 CI 侧 GREEN 含义限定）；`MODEL_ROUTER_V23_MATRIX` P0 行补同一条限定语。
  - **仍开的（本轮明确不做）**：同族两枚潜在腿 `test_typesafe_v2_core.py:1341` / `:1572` → B1；
    终审 Important 2（B0-12 第一子句退化成只看守 README，需改**区间**判据）、
    Important 3（§11 锚与 `ent_b0_mutations.BASELINE_SHA1` 应统一改 **git blob** 口径；
    `ci.yml` 的 `1c706e165b73` 是工作树读数、blob 是 `e0ff7a206cd3`）、
    Important 4（`decide()` 的哨兵该绑到 assigned 节点自己的失败块；`:472` 恒真死条件；B0 台缺 reason token）、
    Important 6 的残余信任根移远端变量 / 双人签 ⇒ 都待用户排期，我不擅自动手。
- **R36（RC2 候选 commit 自身的主门读数，2026-09-30）**：
  - `git push` 落地 `047a0d4..2e4fccf` 两枚（`41e7c5f` 窄单 + `2e4fccf` 文档），CI 只对 push 的 **tip**
    起一轮 ⇒ 被读的就是将要打 tag 的那枚 commit 本身，不是"前一枚绿过"。
  - run **`36684075268` @ `2e4fccf`**：`backend-contracts` **success**，**非成功步骤数 = 0**；
    主门 `1335 passed, 2 warnings, 1159 subtests passed in 52.70s`；
    `Run SECA-20 delivery-surface secret scan` = `5 passed, 41 deselected in 1.11s`；
    **`Validate Docker Compose configuration` 与 `Validate Windows deployment script syntax` 两步本轮均 success**
    （B0-10 那条"每轮读数"在这一轮是绿的，读数按轮记，不改写成既成事实）。
  - 整 run 仍 failure：`backend-integration` / `backend-quality`（`argon2` / `typesafe_sdk` 依赖清单漂移），
    与 R33/R35 同一条债，规格 §1 明令不得触碰 ⇒ rc2 的 tag note 里必须写"tag 级 CI 仍非全绿"。
  - **还差一口气的那件事**：终审建议把 B0-02/03/10 的判据读成"主门确定化后**连续两枚** commit 的
    job 级 success"。目前的序列是 `c29ce8a` success → `047a0d4` failure → `2e4fccf` success ⇒
    **连续计数是 1/2**。窄单的修复让那枚腿**不再依赖时序**（效果钉本身是确定的），但"按构造确定"
    与"实测连续绿"是两件事，我不拿前者冒充后者。补齐 2/2 有两条路：对同一枚 commit `gh run rerun`
    （同码不同 runner，其实是对"非确定性"更直接的证伪），或等下一枚自然 commit。**待用户选**。
- **R37（第 17 枚门：B0-12 区间化 + 连续绿 2/2 达成，2026-09-30）**：
  - **连续绿先记账**：`2e4fccf` = run **`36684075268`**（`backend-contracts` success、
    `1335 passed / 2 warnings / 1159 subtests in 52.70s`）；`d1bab29` = run **`36685239481`**
    （success、**非成功步骤数 0**、`1335 passed / 1159 subtests in 45.17s`，compose 与 pwsh 两步均 success）
    ⇒ 主门确定化之后**连续两枚 commit 绿**，2/2 达成。
    两枚都是**零代码差**的读数（一枚 docs、一枚台账）⇒ 它们证的是"同码不同 runner 不翻色"，
    下面这枚带代码差的 commit 才是第三格。
  - **Important 2 落地**（用户挑的这一条）：新门
    `test_the_app_surface_delta_since_the_sealed_base_is_exactly_the_registered_exception`
    要求 `7cc5efc0460a…(= tag security-a-rc1)..HEAD` 的 `backend/app/**` 差集**恰等于**
    `{backend/app/identity/__init__.py}`，双向红。基线取 **sha 常数不取 tag 名**——把失败模式
    收敛成"历史没取全"一种。实测 `git diff --name-only security-a-rc1..HEAD -- backend/app`
    恰为此一枚（终审的说法我复验为真）。
  - **`ci.yml` 加 `fetch-depth: 0` 是被判据逼出来的**：浅签出没历史 ⇒ 新门必须**哑红不绿**。
    P1 在 `--depth 1` clone 里真跑：`1 failed` + 文案点名「…绝不能读成『app 面没有改动』… 需要
    fetch-depth: 0」；P2（clone 里改 `backend/app/config.py` 并提交）报
    `未登记的改动 ['backend/app/config.py']；被摘掉的例外 []`；P3（把 CORR-01 文件还原成基线）报
    `未登记的改动 []；被摘掉的例外 ['backend/app/identity/__init__.py']`。三发都在临时 clone、跑完即删，
    **主仓一次都没被写过**。
  - **读数**：门模块 **17 passed**；`EXPECTED_COLLECTED 1335 → 1336`，探针 `TOTAL 1336`，
    明细基线重生成 1336 行 `398913ffba87`；全量套件（仓根 cwd）**1336 passed / 36 warnings /
    1159 subtests in 252.82s，rc=0**（含 SEC-A 46 ⇒ `ci.yml` 新注释没有把扫描面弄红）；
    `ci.yml` 147 → 152 CRLF / **0 bare LF**，锚 `1c706e165b73` → `b84cb8bcaa10`（工作树口径）；
    门文件锚 `5ac7220e6c55` → `5ef3cc91a117`。顺手补终审 Minor 8（常数上方注释原来只推到 1332）。
  - **文档**：验收新增 **§11.2**（含三发证伪原文与新锚）、B0-12 行加"判据已加强"限定、
    交付面那行标"2026-09-30 起 17 枚"、G20 行加同一条日期化说明。原读数一律保留不删。
  - **仍未做（等裁）**：终审 Important 3（锚与 bench 基线改 **git blob** 口径——本轮又出现一次混用：
    `ci.yml` 工作树 `b84cb8bcaa10` vs blob `e0ff7a206cd3`）、Important 4（仪表三处）、
    同族两枚潜在腿 → B1。
- **R38（第 17 枚门在 CI 落地，连续绿 3 枚，2026-09-30）**：
  - run **`36689505511` @ `fe65f08`**：`backend-contracts` **success、非成功步骤数 0**，
    `1336 passed / 2 warnings / 1159 subtests in 55.02s`，SECA-20 子集 `5 passed, 41 deselected in 1.25s`；
    整 run 仍 failure 于 `backend-integration` / `backend-quality`（`argon2` / `typesafe_sdk`，规格 §1 不许碰）。
  - **两件事由这一格同时证成**：① `fetch-depth: 0` **确实在起作用**——新门在 CI 通过这件事本身要求基线
    commit 可解析，没有历史它必然哑红（P1 实测过那个红相）；② 重锚到 1336 后 **B0-03 的逐位相同仍成立**
    （本地两 cwd 1336/1159 与远端同数）。
  - 连续绿：**`2e4fccf` → `d1bab29` → `fe65f08`** 三枚 job 级 success，前两枚是零代码差的读数、
    第三枚带代码差 ⇒ 终审要求的"主门确定化后连续两枚"已满足，且多一枚。
  - 文档同步：验收 §11.2 补"远端确认"段；三处"现行常数 1335"的限定语改为 **1336**（链条
    1332→1335→1336 全部指向 §11.1/§11.2），原读数照旧不删。
  - 仍待用户裁的两件事：终审 Important 3（锚与 bench `BASELINE_SHA1`/needle 统一改 **git blob** 口径——
    本轮又新增一次混用：`ci.yml` 工作树 `b84cb8bcaa10` vs blob `e0ff7a206cd3`）与
    Important 4（变异台三处仪表：哨兵绑到 assigned 节点失败块、`:472` 恒真死条件、B0 台缺 reason token）；
    同族两枚潜在腿 `test_typesafe_v2_core.py:1341`/`:1572` 归 B1。**rc2 的授权仍在这些之后**（终审原话：
    先修 1306、拿一枚真绿的代码 commit、把 Important 2/3/4/5/7 的文档与判据缺口对齐再签）。
- **R39（Important 3 落地：锚与变异台改 git blob / 行尾无关口径，2026-09-30）**：
  - **锚的规范口径改成 git blob**：`git rev-parse HEAD:<path>` == `git hash-object -- <path>`
    （后者过 clean filter ⇒ CRLF 工作树也得到同一枚 blob）。验收新增 **§11.3**，11 枚件的 blob 身份成表；
    §11/§11.1/§11.2 的旧 sha256 锚**全部保留不删**（它们是各时点的工作树读数，是历史）。
    `manifest.json` 那枚**不换**——P0 闸的 `PORTABLE_MANIFEST_SHA256` 是判据而不是记账锚，
    它的工作树依赖已被 §7 L10 的 `eol=lf` 消掉；改它等于动判据。
  - **B0 台换口径**：`BASELINE_SHA1` → `BASELINE_BLOB`（四枚取自已提交树，比对函数 `blob_id()`）；
    `LC(...)` 与 `L(...)` 同形（needle 一律 LF），匹配与注入由 `edits_for()` 按目标文件行尾适配。
  - **双形态实测**：同一枚 needle 在 LF 与 CRLF 两种检出形态下的命中数，N1–N8 全部 `BOTH-FORM-OK`
    （N6 两枚编辑对都是 `[1,1]`）；blob 身份四枚全等（含 `ci.yml` 这种工作树 CRLF 的件）。
  - **台子自己抓到我的 bug（留案）**：第一轮重跑 `--check` 报 12/12，真跑却 N2/N3/N4 逐发
    `TARGET-NOT-FOUND`、rc=1 —— 我只改了注入路径，漏改主循环的命中预检 ⇒ **同一判据两份实现必然漂**。
    修法不是补那行，而是收敛成唯一实现 `anchor_counts(spec, text=None)`，两个入口同走。
  - **重跑读数**：`--check` 12/12；整轮 **8/8 `KILLED-ASSIGNED`、`BENCH_RC=0`**；还原四枚锚定件
    `hash-object == HEAD blob` 全等；台后门 17 + SEC-A 46 = **63 passed**。
    溯源表本轮 17 枚里红 9 枚，`NEVER` 是真读数（第 17 枚新门不在 B0 八发射程内，它的三发证伪在 §11.2）。
  - **我自己打错的一枚锚，当场改**：§11.3 表里 manifest 的 blob 我先写成 `af6db0a0c41f`（按截断显示
    猜的次序），真值是 `af6db0a0c641`（`git rev-parse` 与 `git hash-object` 双读一致）。已改。
    ⇒ 教训：**锚必须整串读出来再截，不能从被截断的显示里回填**。
  - **没做的事（登记为待办，不写进结论）**：真在 Linux 上跑一遍这台台子。**本地做不到**：
    `python:3.12-slim`/`python:3.13-slim` 无 git、`rag-backend:latest` 无 git 且无 pytest，
    我不擅自装系统依赖或拉新镜像。所以"跨机可复现"目前只有**构造性证据**（双形态锚点 + blob 与
    检出行尾无关 + `--check` 走 clean filter），不是"另一台机器实测过"。
  - 终审 Important 3 到此关闭；剩下 Important 4（仪表三处）与同族两枚潜在腿仍开着，rc2 在后。
- **R40（Important 3 的远端读数，连续绿第 5 枚，2026-09-30）**：
  - run **`36696050157` @ `eb921c6`**：`backend-contracts` **success、非成功步骤数 0**，
    主门 `1336 passed / 2 warnings / 1159 subtests in 55.52s`，SECA-20 子集 `5 passed, 41 deselected in 1.16s`。
    整 run 仍红于 `backend-integration` / `backend-quality`（`argon2` / `typesafe_sdk`，规格 §1 不许碰）。
  - 主门确定化后的连续 job 级 success：**`2e4fccf` → `d1bab29` → `fe65f08` → `a458eb2` → `eb921c6`** = 5 枚，
    其中带代码差的有 `fe65f08`（新门 + `fetch-depth: 0`）与 `eb921c6`（台子与锚换口径）两枚。
  - 工作树只剩：用户自己的 `identity/README.md`，以及 `test_real_llm_failover_gate.py` 的 stat-dirty
    （`git diff` 为空、内容 == HEAD blob）。

- **R41（Important 4 落地：两台北方仪表改成"按节点归因"，2026-09-30）**：
  - **终审要的那三处**：① 红因哨兵必须落在**这一发点名的那枚节点自己的失败块**里，不能拿整轮
    输出当证据；② P0 台 `:500` 那行旧代码是 `(not path.exists() or True)`——**恒真**，删除件是否
    真没了从来没核过；③ B0 台八发压根没有 reason 哨兵，"杀了"只等于"那枚红了"。
  - **B0 台**：新增 `failed_reasons()`（`ent_b0_mutations.py:417`，从 `=== FAILURES ====` 切到
    `=== short test summary info ====`，按块头建 `节点 → 它那块全文`）+ `reason_excerpt()`；
    `decide()` 改三元组 `(verdict, unexpected, unmatched)`，多一枚 `KILLED-WRONG-REASON`；八发每发
    补 `"reasons"` 哨兵表。哨兵里的计数不写死：`expand_count_tokens()` 支持 `{EC}`/`{EC-3}`/`{EC-1}`，
    真值由 `expected_collected()` 现读门模块 ⇒ 加测试不会把哨兵漂成假红。门册也改成现读
    `re.findall(r"^def (test_\w+)")`，不再另抄一份清单。
  - **P0 台**：同形 `failure_blocks()`（`p0_3b_mutations.py:361`），`decide()` 绑 `ASSIGNED` 那枚
    的块；块拿不到判 `KILLED-NO-BLOCK`，块里没有哨兵判 `KILLED-WRONG-REASON`；恒真那行改成
    `restored_ok = restored_ok and (not path.exists())`；台账分组键改成 `verdict.split("-RESTORED")[0]`
    （旧写法把 `KILLED-WRONG-REASON-RESTORED-OK` 归进各自的新类，"14 发全杀"那行会失真）。
  - **我在这一轮里自己造的四枚 bug，全部是台子/复算抓出来的，留案**：
    1. 拼接时删掉了 `SUCCESS_VERDICT`、又删掉 `gate_name()` ⇒ 两枚 `NameError`。跑一遍就炸，没逃掉。
    2. heredoc 里的 `\n` 被吞 ⇒ f-string 未终结，语法错。同形错两次；结论同前：**改这类文件用
       显式重写整段，不做行内 splice**。
    3. 块头正则我第一版写 `^_{3,}\s*(.+?)\s*_{3,}$` ⇒ P0 十四发**全判 `KILLED-NO-BLOCK`**。原因是
       pytest 对长节点名只补 1 个下划线。仪表在这里**拒绝认证而不是放过**，是对的形状。
    4. 放宽成 `^_+\s*(.+?)\s*_+\s*$` 之后，pytest 的 `_ _ _ _` 分隔线自己成了块头，切在 E 行之前
       ⇒ 块里没有断言行。终版：块头必须含 `\btest_\w+` 才算。
  - **N6 的哨兵是我猜错的，被台子当场驳回**：我按"index 面"的印象写了 token，实测那一发的真红因是
    `git ls-files` 跟踪面为空 ⇒ `KILLED-WRONG-REASON`。回去读这发的规格抬头（§6.4 覆盖度钉的**空判
    地板**），把两枚节点的哨兵都改成 `跟踪面一枚都没有`。**这正是这台子存在的理由：它抓的不是产品，
    是我的归因。**
  - **离线复算先行**：正则两处改完，先拿**已存盘的旧 dump**重放，不花正式轮——P0 14/14 全部落进
    自己节点的块、N6 那块捞出地板消息；确认解析器之后才跑真台。
  - **正式轮读数（两份全文在 `tmp/`）**：
    - B0 八发 `tmp/b0-bench-official-2026-09-30.txt`：**8/8 `KILLED-ASSIGNED`、`B0_RC=0`**；
      逐发的红因都落在自己块里（N1 `收集数 1333 ≠ 钉住的 1336`、N6 两枚都是地板那句、N7 双红）；
      N3 按计划外附带红 `test_extra_pip_arguments_are_exactly_the_exemption_table` 记为允许；
      还原八发全 `sha1 与注入前相同 + cmp rc=0`。溯源表 17 枚门本轮观测红 9 枚，`NEVER` 是真读数。
    - P0 十四发 `tmp/p0-bench-official-2026-09-30.txt`：**14/14 `KILLED-ASSIGNED-RESTORED-OK`、
      `P0_RC=0`**，park 目录已删；M1–M5 逐枚哨兵（`phi3:mini-M1…`、`ornith-M4:latest`、
      "不含 §6 那族加载失败特征"）、M6–M9 `[I1]/[I2]/[I6]/[I7]`、N1–N4 `[T-彩排]/[T-收尾]/[T-传输层]`
      全部命中各自块。
  - **台后零残留与门禁读数**：`--check` **12/12**（8 发锚点 + 4 枚 git blob 身份全等）；
    `git diff --name-only` 只剩两台北方脚本 + 用户自己的 `identity/README.md`
    （`test_real_llm_failover_gate.py` 是 stat-dirty，diff 为空）；
    门 17 + SEC-A 46 = **63 passed**；全量两 cwd **1336 passed / 36 warnings / 1159 subtests**
    （backend cwd 255.98s、仓库根 cwd 248.24s）。
  - **仍未做（不写进结论）**：Linux 上重跑这两台子（本地无带 git 的镜像，不擅自装系统依赖）；
    同族两枚潜在腿 `test_typesafe_v2_core.py:1341`/`:1572` 仍归 B1；
    `backend-integration`/`backend-quality` 的 `argon2`/`typesafe_sdk` 依赖漂移 B0 无权收。
  - 终审 Important 2/3/4 至此全部关闭。rc2 的前置只剩 #131（候选 commit 自身远端 GREEN 的链条）
    与**用户的明确授权**。

- **R42（Important 4 的远端读数 + 同族墙钟腿分诊，2026-09-30）**：
  - run **`36706771490` @ `dbd75c3`**：`backend-contracts` **success，15 步全 success、非成功步骤 0**；
    主门 `1336 passed / 2 warnings / 1159 subtests in 56.62s`；SECA-20 `5 passed, 41 deselected in 1.18s`。
    ⇒ 本地两 cwd `1336/1159` ↔ 远端 `1336/1159` **逐位相同**在 Important 4 这枚 commit 自身上重新成立。
    整 run 仍红于 `backend-integration` / `backend-quality`（`argon2` / `typesafe_sdk`，B0 无权收）。
  - 主门确定化后的 job 级连续 success：`2e4fccf → d1bab29 → fe65f08 → a458eb2 → eb921c6 → 0281ab8 →
    dbd75c3` = **7 枚**，其中带代码差的 4 枚（`fe65f08` 新门 + fetch-depth、`eb921c6` 锚口径、
    `dbd75c3` 仪表归因；`c29ce8a`/`41e7c5f` 在链条起点之前）。**#131 的"候选 commit 自身 GREEN"
    到这里有读数为证**；#129 只差用户授权。
  - **同族腿分诊（把"运气绿"和"构造出来的地板"分开）**：真同族 = 对实测延迟做 `> 0.0` 且生产侧
    `round(...,2)` —— `test_typesafe_v2_core.py:1341`（`app/typesafe_judgments.py:869`）与 `:1572`
    （`:517`）。**定向 20 连跑 20/20 绿** ⇒ 今天的红不在它们身上，但机制与 `047a0d4` 那次一字不差，
    归 **B1**（用户裁定本轮不动）。不是同族的：`test_typesafe_v2_pipeline.py:598`（每次 sleep 5ms 的
    假 CE 把地板顶出来，是构造不是运气）、`test_typesafe_v2_core.py:357`/`:1675`、`pipeline:526`
    （钉 `budget.remaining_ms` 逻辑量，不测执行耗时）。
  - 台账落点：验收新增 **§11.4**（Important 4 全案 + 两台正式轮读数 + 远端确认 + 这次分诊），
    B0-11 行加"判据已加强"，B0-03 行标明它取的是 `b825112` 那一格、并指向 §11.3/§11.4 的三格重证。
