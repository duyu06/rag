# Task 2 报告 —— 四枚门（红相）

产物：`backend/tests/test_ci_gate_contract.py`（新建，未提交）。
判据来源：`task-2-brief.md`（13 枚测试与 helper 逐字照抄，未改任何断言、未改任何期望值）。
基线 commit `7cc5efc` / tag `security-a-rc1`，HEAD 未动，全程零 git 写命令。

## Step 1–4：模块头、收集面 helper、ci.yml 解析 helper、依赖同源钉（静态自检）

写完后机器核过的四条（字面输出）：

```
CRLF bytes: 0 | lone CR: 0 | LF: 352
test defs: 13
imports:
    from __future__
    import functools
    import os
    import re
    import subprocess
    import sys
    from pathlib
app. mentions: []
defined==listed: True 13 13
ghost in list: [] | unlisted def: []
```

- **只 import 标准库**（`functools/os/re/subprocess/sys/pathlib`），且**没连 pytest 都不需要** ——
  本文件不 `import pytest`。全文件无 `app.` 出现。这是 B0 的立身之本：门一旦拖进 `app.main`
  就继承那 10 枚在 CI 里收不动的重依赖模块的病，Reviewer 复查点即在此。
- 行尾 LF 达成（0 枚 CRLF、0 枚游离 CR），与本仓其他工具写的测试文件同形。
- `_OWN_TEST_NAMES` 与实定义 13 枚**逐枚同名同序**，幽灵 0、漏名 0（与台账里"定义 13 / 点名 13 / 幽灵 0"的机器核对一致）。

## Step 5：收集数实测与常数回写

命令（brief 原文）：`python scripts/b0_collection_probe.py | head -1`

字面读数：

```
TOTAL 1329
```

本文件自己的逐模块计数行（同一份探针输出，第 7 行）：

```
   13  backend/tests/test_ci_gate_contract.py
```

探针 rc=0，stderr 空。墙钟 `real 0m29.014s`（比 Task 1 记的 40–62s 快；台账 M-6 已裁定"墙钟不作判据"，此处只作成本读数为 Task 5 留档）。

**算术**：基线 1316 + 本文件贡献 13 = **1329** = 实测值 ⇒ 无模块被 import 失败拖住。

**写进文件的常数**：`EXPECTED_COLLECTED = 1329`。

关于"凑数"的一条自证：brief 预估 1329 与文件里落笔的 1329 **是同一枚数字**，所以必须说清次序 ——
我先按 brief 原文写了 1329，随后独立跑探针复量得到 1329，两者相等 ⇒ **本次没有发生"改常数去凑实测"
的动作**（既没上调也没下调，判据没被任何人手调过）。这条留在这里，是为了 Task 5 复核 B0-01 时
能分辨"常数被钉住"和"常数被人凑"。

## Step 6：`_OWN_TEST_NAMES` 点名

按 brief 放在 helper 区之后（文件末尾）。它是自我存续钉的**第二个源**，与装饰器故意重复 ——
判据不靠遍历本模块，因为"遍历自己"对本文件被摘走东西无感。

## Step 7：逐枚红/绿点名（13 枚全列）

命令（brief 原文）：`python -m pytest backend/tests/test_ci_gate_contract.py -q`
字面末行：`5 failed, 8 passed in 30.70s`（rc=1）
进度行：`...FF.FF.F...`

| # | 测试 | 实收 | brief 预测 | 红/绿的**那一条**理由 |
| --- | --- | --- | --- | --- |
| 1 | `test_collected_count_matches_the_pinned_number` | 绿 | 绿 | 子进程实收 1329 == `EXPECTED_COLLECTED` 1329 |
| 2 | `test_the_gate_module_itself_is_collected` | 绿 | 绿（未逐枚点名，属"三枚收集钉"） | 本文件实收 13 枚，与 `_OWN_TEST_NAMES` 逐名相等 |
| 3 | `test_collection_measurement_counts_node_ids_not_the_summary_line` | 绿 | 绿（同上） | 解析器把 `2 tests collected in 0.01s` 判成 0 枚、两枚 node id 判成 2 枚 |
| 4 | `test_backend_contracts_has_no_unittest_discover_step` | **红** | **红** | 抓到 1 处：`- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v`（ci.yml:43） |
| 5 | `test_backend_contracts_runs_the_pytest_suite` | **红** | **红** | `suite_wide == []`：全 job 没有目录级 `python -m pytest backend/tests(?!/)`；SECA-20 那步因 `(?!/)` 不算数 |
| 6 | `test_step_ordering_still_explains_itself` | 绿 | 绿 | job block 内 `SECA-20`（ci.yml:17）与 `unittest`（:18/:43）两串都在 |
| 7 | `test_install_face_uses_requirements_txt_as_the_source` | **红** | **红** | 1 枚安装步里无 `-r backend/requirements.txt`：YAML 仍是手写清单 |
| 8 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | **红** | **红** | 两条**死行**：`豁免表死行：\`pytest\` 当前 0 处；豁免表死行：\`torch\` 当前 0 处`（`seen == {}`，见下方敏感性那条） |
| 9 | `test_every_exemption_row_states_why` | 绿 | 绿 | 两行处数均 ≥1、"为什么"长度 30/44 ≥ 12 |
| 10 | `test_gitattributes_carries_the_required_rules` | **红** | **红** | `is_file()` 为假：仓库根本没有 `.gitattributes`（Task 4 的产物） |
| 11 | `test_index_has_no_crlf_entries` | 绿 | 绿（回归守卫） | `_index_eol_rows()` 解出 313 行，`i/crlf` 0 枚 |
| 12 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | 绿 | 绿（回归守卫） | 实收 `i/-text` 恰等于封面的三枚（SEC-A task-10d 报告 / MODEL_ROUTER_V23_DESIGN / yaoke-logo.webp） |
| 13 | `test_eol_rules_are_a_no_op_for_the_current_tree` | 绿 | 绿（回归守卫） | `checked > 0`（非空判）且 `.sh` 无 CR、`.ps1` 有 CRLF ⇒ offenders 空 |

**与预测的对账：13/13 完全吻合，红 5 / 绿 8，红名单与 brief 逐枚同名，没有一枚偏差。**

两条"不是假绿/假红"的反证（brief Step 7 要求必查的那条）：

```
job block chars: 1772 | steps: 9 | run-steps: 7 | install-steps: 1
tokens from current YAML: []
folded(>-) tokens: []
block(|)   tokens: ['pytest', 'torch']
index rows: 313 | i/-text: ['.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md',
 'docs/MODEL_ROUTER_V23_DESIGN.md', 'frontend/public/yaoke-logo.webp']
```

- 解析 helper **确实找到了** job 块与 9 枚 step ⇒ 第 6、9 两枚绿不是"找不到所以空判通过"；
  找不到时 `_job_steps` 抛的是 `AssertionError`（源码可查），不会静默返回空。
- 第 11–13 枚绿的守卫都建立在**实数**上（313 行 index、3 枚 -text、`checked > 0`）。

### 给 Task 3 的一条敏感性发现（未据此改任何判据）

`_pip_package_tokens` 按**物理行**扫：只 tokenize 含 `pip install` 的那一行余下的 token。
实测（上面 `folded` / `block` 两行）：

- `run: >-` 折叠标量把包名续写到第二行 ⇒ 该函数得到 `[]` ⇒ 豁免表两枚**永远死行** ⇒ 第 8 枚门
  在改造后仍会红，而且红的理由是"死行"而不是"漂移"；
- `run: |` 且包名与 `pip install` **同物理行**（如
  `python -m pip install --disable-pip-version-check -r backend/requirements.txt pytest`
  加一行 `python -m pip install torch --index-url …`）⇒ 得到 `['pytest', 'torch']`，正好对上豁免表的 1/1 处数。

今天 ci.yml 的 SECA-20 安装步用的正是 `>-` 折叠形态，所以那 11 个手写包名**一个都没被 tokenize 到** ——
这也解释了为什么第 8 枚门的红只有两条死行、没有"未豁免的包"。台账冲突扫描表里 T6 N3"换成手写串 ⇒
`pytest-fastapi-pydantic` 成未豁免包"那条预判，同样以"包名与 pip install 同行"为前提。
**处置：不动判据（brief 的函数照抄），把这条写成 Task 3 落地 ci.yml 时的形态约束。**

## Step 8：全量套件

命令（brief 原文）：`python -m pytest backend/tests -q`

字面末行：

```
5 failed, 1324 passed, 36 warnings, 1133 subtests passed in 171.08s (0:02:51)
```

- **计数轴 1329 复现**：`5 failed + 1324 passed = 1329`，与 Step 5 的探针独立读数一致；
  两条来自两个量法（探针数 node id / pytest 数结果），互不遮蔽。
- **收集面形状（顺手钉死一条，免得后人误判）**：磁盘上 41 个 `test_*.py`，收集面只有 40 枚模块 ——
  差的那一枚是 `backend/tests/test_real_llm_failover_acceptance.py`，它在 `REAL_LLM_ACCEPTANCE`
  关着时贡献 **0** 枚。这正是量法要剥掉那枚开关的原因 ⇒ **1329 这个常数是"验收门关着"那一格的形状**，
  与 CI 默认形态同源，不是一个含验收面的数。
- **红只可能是我的红**：`FAILED` 五行 = Step 7 那 5 枚，逐名相同；收集面上除本文件外的 **39 枚模块**
  **无一被本文件带红**。日志里 11 处大小写不敏感的 `error` 命中全部来自本文件这 5 枚的
  `AssertionError` 文本与消息里的 `ModuleNotFoundError` 字样（逐行核过），
  末行无 `errors` / `skipped` / `deselected` ⇒ **收集期 0 error、0 skip**。
- **在测试里跑的那个收集子进程工作正常**：`test_collected_count_matches_the_pinned_number` 与
  `test_the_gate_module_itself_is_collected` 在全量套件语境下同样绿 ——
  即子进程在"父进程已经是 pytest"时仍能从仓库根收出同一批 1329 枚，`lru_cache` 让 13 枚只付一次收集。
- **常驻成本读数（交 Task 5 复核）**：本文件单独跑 `30.70s`，其中约 `29.01s` 就是那次
  `--collect-only`（同量法探针独立计时 `real 0m29.014s`）⇒ 净门逻辑 ≈ 1.7s。
  全量 `171.08s` 已含这 29s ⇒ 无本文件时约 142s，**本任务把后端契约 job 抬高约 20%**。
  按 §10.3 这是"有意引入的常驻成本"，如实报上、不换进程内量法；Task 5 若判不可接受，
  出路是 §6.1 的读数合并（一次收集供多枚门），不是把量法退回 unittest loader。
- **与 Step 8 Expected 字面不符的一处**（不是失败，是 brief 的措辞）：brief 写 `Expected: 1329 + 0 failed`，
  而红相的 5 枚红门**就是本任务的交付物** ⇒ "0 failed"在 Task 2 结束时**不可能成立**。
  我按判据的本意执行"计数 1329 且**除本文件的 5 枚红外无别的失败**"，未为了让末行好看而弱化任何断言。
  Task 3/4 之后这行才应当变成 `1329 + 0 failed`。
- 墙钟不作判据（台账 M-6）：171.08s 落在 Task 1 实测的 98.14–195.89s 带内。

## SEC-A 密钥卫生门：落地后仍绿，以及怎么验的

命令：`python -m pytest backend/tests/test_secret_hygiene_contract.py -q` ⇒ **`46 passed in 26.00s`，rc=0**（整模块，不只 CI 那 `-k` 子集）。

再补一层直接对账（证明"绿"不是"没扫到我的文件"）：

```
on delivery surface: True | surface files: 317
faces applied: ['\n    ["\']?\n    (?:api[_-', 'sk-[A-Za-z0-9_\\-]{16,}|g']
hit files: 16 | my file hits: 0
unexplained vs EXEMPTIONS: {} | dead rows: {}
```

- 我的文件**确实在扫描面上**（`git ls-files --cached --others --exclude-standard` 从 Task 1 的 316 枚变 317 枚，
  多的正是它），扫它的是代码档两枚面（`_LITERAL_FACE` + `_MATERIAL_FACE`；`.py` 不上 env 面）。
- 命中 **0 处**，全表面命中文件数仍是 16 枚且逐名仍在豁免表内（`unexplained == {}`）、豁免表无死行
  （`dead rows == {}`）⇒ `test_repository_tracked_files_hold_no_credential_material`
  与 `test_the_exemption_table_matches_the_hit_set` 都真绿。
- **没有加任何豁免行、没有动那张表**（brief 的约束）。写法上的预防只有一条：本文件通篇不出现
  ≥16 字符的凭据形态字面量，`pip install` 的包名/参数都以散文字面提及、不写成 `token = "长值"` 形态。
- 同批还核过 `test_real_llm_failover_gate.py` 等未被本文件触动（全量 1324 passed 已覆盖）。

## brief 的代码哪一处没照写就走不通

**13 枚测试与全部 helper 逐字照抄，无一处需要改写才能跑。** 记两条"跑通了但值得上层知道"的：

1. Step 8 的 `Expected: 1329 + 0 failed` 在红相不可满足 —— 见上面 Step 8 那节。
   处置：**未**为凑 0 failed 弱化任何断言，按"除本文件 5 枚红外无失败"判并如实报末行。
2. `_pip_package_tokens` 的物理行扫法与 `run: >-` 折叠标量不兼容（今天 YAML 就是这个形态），
   实测 `folded(>-) tokens: []` vs `block(|) tokens: ['pytest', 'torch']`。
   今天它让第 8 枚门红在"两条死行"上 —— 理由正确；但 Task 3 若沿用 `>-` 续行写法，
   这枚门会**改造后仍红在同一个错误理由上**。处置：判据原文不动，把形态约束写进上面那节交给 Task 3。

（另记一条与本任务无关的树态：`git status --porcelain` 除 identity 两枚既存改动与三枚 B0 未跟踪文档
（`docs/ENTERPRISE_B0_PLAN.md`、`docs/ENTERPRISE_B0_SPECIFICATION.md`、`scripts/b0_collection_probe.py`）
外，只多了本文件。未跑任何 git 写命令。）

## 交付面自查（只读 git，零写命令）

```
=== git status (read-only) ===
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
=== HEAD ===
7cc5efc
=== ci.yml untouched? ===
(no diff output above = untouched)
```

- HEAD 仍 `7cc5efc` ⇒ 全程零提交（`add/commit/push/stash/checkout/restore/clean/config` 一枚都没跑）。
- identity 两枚 `M` 是 Task 1 登记的既存基线改动，未动、未提交。
- `git diff --stat` 对 `.github/workflows/ci.yml` / `backend/requirements.txt` / `docker-compose.yml` / `scripts/`
  **无输出** ⇒ 三枚 Task 3/4 的靶子文件本任务一片没碰。5 枚红门里有 4 枚正是"红在 ci.yml 现在的形状上"，
  按派发约束**留红不改 YAML**。
- 新建：`backend/tests/test_ci_gate_contract.py`（17032 字节，sha256 前 12 位 `69f74974c2e1`）
  + 工作区产物（本报告、台账一行、`snap-task2-post/`）。快照与源文件 `cmp` 逐字节相同。

## 结论

红相达成：**红 5 / 绿 8**，且逐枚红/绿的理由与 brief Step 7 的点名清单一字不差。
本文件的 8 枚绿不是空判（解析面 1772 字符 / 9 枚 step / 313 行 index / `checked > 0` 都实测过）。
交 Task 3 的形态约束一条（`>-` 与 `|`），交 Task 5 的成本读数一条（常驻 +29s，约占 job 20%）。

---

## 修复轮 1

范围：**只改 `backend/tests/test_ci_gate_contract.py`** 一枚文件（外加 `.superpowers/` 下的工作区取证件）。
`.github/workflows/ci.yml` 一字未动、`.gitattributes` 未创建、`backend/app/**` / `backend/requirements.txt` /
`docker-compose.yml` / `frontend/**` / `test_secret_hygiene_contract.py` 一片没碰；全程零 git 写命令（见文末自查）。
裁定来源：`progress.md` R8 的 I-1…I-5 五枚 Important + 三枚随手带上的 Minor；权威措辞取规格 §16 卡 H、卡 I。

> **上面第一至第三节（红相那一轮）的以下数字已被本节取代**：13 枚门 → **15 枚**；`EXPECTED_COLLECTED`
> 1329 → **1331**；`5 failed, 8 passed` → **`5 failed, 10 passed`**；全量 `1324 passed` → **`1326 passed`**；
> 门文件字节 17032 / `69f74974c2e1` → **31379 / `19d335a1c15a`**；"交 Task 3 的 `>-` 形态约束"从口头
> 约定升级为机器钉（门 8 的 `run: |` + 非空地板）。红相那两节保留原文不改，因为"当时量到什么"
> 本身就是台账；本节把改动与复量逐条写清。

### 一、这一轮改了什么（逐条对 R8）

**I-1 注释剥离（新增 helper `_step_script()`，brief 的 `Produces` 里本来就有这个名字、上一轮漏写了）。**
整行 `#` 注释在匹配之前剥掉，所有对**命令**的 ci.yml 门都改跑在它上面：`_test_runs()`（`run:` marker 也从
`"run:" in step` 收紧成 `^\s*(?:-\s+)?run:` 的行首形态，`- run: …` 这种一步写法照样认）、
门 4（unittest 面）、门 5（主门 + 旗标）、`_install_steps()`、门 7、`_pip_package_tokens()`、
新增的 `_pip_source_option_values()`、门 6 的锚点识别。**唯一例外**是门 6 的"文字存在"半边：它的宾语正是
注释本身，剥了注释就等于把 §5.2 那两条顺序理由的钉子自己拆了 —— 那半边继续看 `_job_block` 原文，
并在 docstring 里写明这是刻意的。计划亲手要求保留的那句 `python -m unittest discover …` 注释**一字未删、
一字未改**。

**I-2（卡 H）口径拆两条 + 新增机器判据。** 模块 docstring 末段与 `test_the_gate_module_itself_is_collected`
的 docstring 里，"被 skip / 被 marker 摘空 / 常数被人凑"这一句混称被拆开：枚数钉只守 (a) 改名 / 摘枚 / 凑数，
`--collect-only` 对 skip 类标记照打 node id 所以它天生看不见"哑掉"；(b) 由新增的
`test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 守——对本文件自己的字节扫哑门装饰器。
正则刻意用 `[ \t]` 而不是 `\s`（跨行不认，否则一枚正常装饰器的下一行只要以 `skip_next =` 开头就被误判），
且拼成 `"@" r"[ \t]*(?:…)"` 的字面量相邻形态，使这枚门**不会匹配到自己的源码行**（实测自扫命中 `[]`）。

**I-3（卡 I）判据拆三条 + 地板 + 值钉。** 门 8 前面加了两枚地板：安装步必须是 `run: |` 字面块
（`_LITERAL_BLOCK_RUN`），且 `_pip_package_tokens()` 的结果必须**非空**——"tokenize 到 0 枚"从"没有额外参数"
改成"这枚门哑了"。新增 `test_install_face_pip_source_values_are_pinned`，把 `-r` / `--requirement` /
`--index-url` / `--extra-index-url` / `-i` 的**值**钉进显式集合
`ALLOWED_PIP_SOURCE_VALUES = ("https://download.pytorch.org/whl/cpu", "backend/requirements.txt")`，
`--opt value` 与 `--opt=value` 两种写法都认。

**I-4 门 6 从"词汇存在"改成"顺序为真"。** `_job_steps` 给的是有序段，现在断言四枚锚点
（SECA-20 扫描 / 主门 / compose / pwsh）的段索引严格递增，并要求 compose、pwsh、扫描这三枚**必需锚点**
缺席即红（"门不能对找不到保持沉默"）。文字存在那半边保留。锚点谓词全部跑在剥了注释的正文上——
注释里若出现 `deploy.ps1` / `docker compose` 这类串（今天的两句恰好没有），不剥就会凭空多造出一枚锚点、
把索引基准挪歪，而这正是 I-1 已经量过的同一颗地雷的第二种炸法。
唯一有裁量空间的一点（主门缺席时不重复归因）单列在下面的"裁决点"一节。

**I-5 主门保真度。** 门 5 在"命中目录级调用"之后再加一道：主门 step 正文（剥注释）里不许出现任何过滤/短路
旗标。`MAIN_GATE_FILTER_FLAGS` 收 R8 点名的 `-k` `--ignore` `--deselect` `-x` `--lf` `--kf` `-m`，
外加同族的长名与近亲（`--exitfirst` `--ignore-glob` `--last-failed` `--new-first` `--failed-first`
`--co` `--collect-only` `--maxfail` `--sw` `--stepwise`）。`-q` 不算旗标（它不改收集面）。
**先剥 `python -m` 前缀再 tokenize**，否则 `python -m pytest` 自带的那枚 `-m` 会让门一落地就假红——
这一条不是纸面推演，是本轮反证台真金白银逮到并修掉的（第六节）。

**三枚随手带上的 Minor。** ① 删掉未使用的 `TESTS_DIR`；② `test_eol_rules_are_a_no_op_for_the_current_tree`
把后缀判定挪到 `read_bytes()` **之前**（原先为 313 枚 tracked 文件、含二进制，全部读进内存再判后缀）；
③ `.ps1` 那半边从"有 CRLF 即绿"收紧成 `body.count(b"\n") == body.count(b"\r\n")`（混合行尾的 `.ps1`
会被 `eol=crlf` 改写，旧判据放它绿）。

### 二、重新实测的常数：`EXPECTED_COLLECTED = 1331`

命令：`python scripts/b0_collection_probe.py | head -8`

字面读数（前 8 行，含本文件那一行）：

```
TOTAL 1331
   16  backend/tests/test_agent_contracts.py
    7  backend/tests/test_agent_routing_contracts.py
   68  backend/tests/test_authentication_leg_contract.py
    2  backend/tests/test_branding_contract.py
    1  backend/tests/test_chat_persistence_contract.py
   15  backend/tests/test_ci_gate_contract.py
    1  backend/tests/test_citation_ui_contract.py

real	0m28.785s
```

**算术**：Task 1 基线 1316 + 本文件贡献 **15** 枚 = **1331** = 探针实测 ⇒ 无模块被 import 失败拖住。
R8 的预测值 1331 命中，且**次序是先加两枚门、再重量、再回写**（不是先写数字再凑）：探针跑之前文件里的
常数仍是上一轮的 1329，实测出来后一步才改成 1331。为了把"常数落后就会红"这条性质也量出来（而不是只在
文案里声称），下面反证台 V 段用 monkeypatch 把常数按回 1329 跑了一次真门：它红在
`收集数 1331 ≠ 钉住的 1329`。墙钟 28.785s（台账 M-6：不作判据，只作 Task 5 的成本读数）。

### 三、修复后的红/绿点名：15 枚 = **红 5 / 绿 10**（与 R8 的预测形状一致）

命令：`python -m pytest backend/tests/test_ci_gate_contract.py -q`（对**终态字节**跑，sha 前 12 位 `19d335a1c15a`）
进度行：`....FF.FF..F...`（15 枚，按定义顺序）
字面末行：`5 failed, 10 passed in 30.03s`（rc=1，留档 `tmp/gate-module-round1-final.txt`）

> 本轮同一条门文件还留下三次读数，名单完全一致（`....FF.FF..F...`、`5 failed / 10 passed`）：
> 29.96s（I-5 的 `-m` 缺陷修复之前）、29.50s（之后、`_ORDER_ANCHORS` 注释改写之前）、
> 30.03s（终态）。第三次的差异只发生在注释行上，不改任何判据。

下表编号沿用 brief / R8 的**原 13 枚编号**（门 1…门 13），本轮新增的两枚记作 **新-H**（卡 H）与
**新-I**（卡 I），与 V 段反证台的标签一一对应。

| # | 测试 | 红/绿 | 红的那一条 / 绿的依据（offender 原文） |
| --- | --- | --- | --- |
| 门 1 | `test_collected_count_matches_the_pinned_number` | 绿 | 子进程实收 1331 == `EXPECTED_COLLECTED` 1331 |
| 门 2 | `test_the_gate_module_itself_is_collected` | 绿 | 本文件实收 15 枚，与 `_OWN_TEST_NAMES`（15 名）逐名相等 |
| **新-H** | `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` **（本轮新增）** | 绿 | 对本文件字节自扫：命中 `[]`；V 段 E 组证明注入装饰器即红 |
| 门 3 | `test_collection_measurement_counts_node_ids_not_the_summary_line` | 绿 | 尾行文句判 0 枚、两枚 node id 判 2 枚 |
| 门 4 | `test_backend_contracts_has_no_unittest_discover_step` | **红** | `F1 复活：…（1 处）` + `offending step 正文（已剥注释）：["- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v"]` ⇒ offender 是**真正的命令行**（ci.yml:43），不再可能是那句注释 |
| 门 5 | `test_backend_contracts_runs_the_pytest_suite` | **红** | `主门不跑全量套件：…注意 SECA-20 那枚单文件子集不算——它只跑 5 枚` + `assert []`（`suite_wide` 空） |
| 门 6 | `test_step_ordering_still_explains_itself` | 绿 | 文字半边：`SECA-20`、`unittest` 仍在块里；顺序半边：锚点 `扫描#3 → compose#7 → pwsh#8` 严格递增，主门缺席由门 5 归因（见"裁决点"） |
| 门 7 | `test_install_face_uses_requirements_txt_as_the_source` | **红** | `依赖又变成 YAML 里的手写清单：f6c67b5 的远端 ModuleNotFoundError 就是这么来的` + `assert False` |
| 门 8 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | **红** | 红因从上一轮的"两条死行"变成地板先响：`1 枚安装步不是 run: \| 字面块：…第一段正文：['- name: Install SECA-20 secret-scan dependencies\n        run: >-\n          python -m pip install --disable-pip-version-check\n          pytest\n          "fastapi']` |
| **新-I** | `test_install_face_pip_source_values_are_pinned` **（本轮新增）** | 绿 | 今天安装面里根本没有 `-r` / `--index-url` ⇒ 收到的 `(选项, 值) == []`。这一枚的"绿"是**真空绿**，但套件层面放不走东西：门 7 独立要求 `-r backend/requirements.txt` 在场，"一个源都没写"不可能整片绿；四枚敌意形状见 V 段 C 组，枚枚红 |
| 门 9 | `test_every_exemption_row_states_why` | 绿 | 两行处数 ≥1、"为什么"长度 ≥12 |
| 门 10 | `test_gitattributes_carries_the_required_rules` | **红** | `没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定`（`is_file()` False） |
| 门 11 | `test_index_has_no_crlf_entries` | 绿 | 313 行 index，`i/crlf` 0 枚 |
| 门 12 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | 绿 | `i/-text` 恰等于封面那三枚 |
| 门 13 | `test_eol_rules_are_a_no_op_for_the_current_tree` | 绿 | 先看后缀再读字节；`checked` = 2（`.sh` 1 + `.ps1` 1）；`.ps1` 新判据 `LF 256 == CRLF 256` ⇒ `scripts/deploy.ps1` 是纯 CRLF、不混合 |

**对账**：红名单 5 枚与上一轮**逐名相同**，只是门 8 的红因从"死行"升级成"地板/形状"（更准，不更松）；
新增两枚（新-H、新-I）都是绿，且都各自演示过能红（V 段）。15 枚 = 上一轮 13 枚 + 卡 H 一枚 + 卡 I 一枚。

### 四、合成反证台：每一枚新门 / 收紧的门都演示过"它能红"

台子：`.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/b0_t2_falsify.py`（工作区取证件，不在交付面上）。
做法与评审一致——**不动磁盘上的 ci.yml**，把模块的 `_ci_text()` 换成合成 YAML 后**直接调用真实门函数**，
记录 GREEN / RED 与 offender 首行。命令：

```
PYTHONIOENCODING=utf-8 python .superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/b0_t2_falsify.py
```

完整输出留档 `tmp/falsify-round1.txt`。下面按裁定编号摘录字面结果。

**A 组（I-1 的正面命题：一次正确的 Task 3 必须全绿，那句 unittest 注释不许把门拖红）**
合成输入 = 计划 Task 3 Step 2/3 的目标步骤序列（含 `run: |` 三行安装面与那段顺序注释）。字面：

```
[post-Task-3] 门4 no_unittest_discover: GREEN
[post-Task-3] 门5 runs_the_pytest_suite: GREEN
[post-Task-3] 门6 step_ordering: GREEN
[post-Task-3] 门7 requirements_txt_source: GREEN
[post-Task-3] 门8 exemption_table: GREEN
[post-Task-3] 门I 新·source_values: GREEN
  不剥注释时 `unittest discover` 命中的 step 段索引：[6]（['- run: python scripts/validate_demo_assets.py']）
  剥注释后命中的 step 段索引：[]
  主门（全目录 pytest）命中的段索引（剥注释）：[7]
```

后两行就是 I-1 那颗地雷的实量复现：**不剥注释时门 4 会红在 `validate_demo_assets` 那一步上**（索引 6，
它根本没跑 unittest），剥完之后主门正确落在索引 7、unittest 命中 0 处。

**B 组（I-4：顺序为真）**

```
[reorder] 门6 step_ordering: RED
        offender → step 顺序被改动，§5.2 的两条理由不再成立：SECA-20 扫描步#7 → 主门（pytest 跑全目录）#6
                   → compose 校验步#8 → pwsh 语法校验步#9（要求严格递增：扫描 < 主门 < compose < pwsh；缺席锚点 []）
[compose 锚点被删] 门6 step_ordering: RED
        offender → 顺序钉的必需锚点 `compose 校验步` 在 ci.yml 里找不到：位置判据不能对『找不到』保持沉默
[主门缺席（门5 负责归因）] 门6 step_ordering: GREEN
```

R8 点名的那颗变异（把扫描步挪到主门之后、原写法仍绿）现在红；必需锚点被删也红。

**C 组（I-3 / 卡 I 的三个假绿 + 地板）**

```
[evil --index-url] 门I 新·source_values: RED
        offender → 安装面出现了没钉过的依赖真源/发行源：`--index-url https://evil.example.com/simple` 不在钉住的来源集合内
[--extra-index-url=] 门I 新·source_values: RED
        offender → …：`--extra-index-url https://attacker.invalid/simple` 不在钉住的来源集合内
[短选项 -i] 门I 新·source_values: RED
        offender → …：`-i https://mirror.internal/simple` 不在钉住的来源集合内
[第二份 -r requirements-dev] 门I 新·source_values: RED
        offender → …：`-r backend/requirements-dev.txt` 不在钉住的来源集合内
[第二份 -r requirements-dev] 门7 requirements_txt_source: RED
        offender → 依赖又变成 YAML 里的手写清单：`f6c67b5` 的远端 ModuleNotFoundError 就是这么来的
[折叠 >- 安装面] 门8 exemption_table: RED
        offender → 1 枚安装步不是 `run: |` 字面块：…第一段正文：['- name: Install backend dependencies (folded)\n        run: >-\n          python -m pip install …']
  折叠安装面 tokenize 结果：[]（地板据此判红，而不是当成『没有额外参数』）
  字面块安装面 tokenize 结果：['torch', 'pytest']
  字面块收到的 (选项, 值)：[('--index-url', 'https://download.pytorch.org/whl/cpu'), ('-r', 'backend/requirements.txt')]
[未豁免包] 门8 exemption_table: RED
        offender → 安装面漂移：未豁免的包 `sentinel-package` ×1
```

评审量的三枚假绿（敌意 index-url / 第二份 `-r` / 折叠 YAML 续行整体消失）现在**枚枚有门红**。
折叠那一支要诚实记下分工：折叠面里续行上的 `-r backend/requirements-dev.txt` 值钉按物理行看不到
（实测 `[折叠敌意面] 门I 新·source_values: GREEN`），真正兜住它的是门 8 的 `run: |` 形状钉
（实测 `[折叠敌意面] 门8 exemption_table: RED`）⇒ 形状钉不是装饰，它是 tokenize 与值钉的前提。

**D 组（I-5：主门过滤旗标）**

```
[main gate -k] 门5 runs_the_pytest_suite: RED
        offender → 主门被过滤/短路旗标缩成了子集，收集数钉不再由这一步实际执行： ⏎ ['-k'] ← … run: python -m pytest backend/tests -q -k "not slow"
  旗标提取（含 `python -m` 前缀必须不被误判）：
    正常主门 → []
    run: python -m pytest backend/tests -q --lf                        → ['--lf']
    run: python -m pytest backend/tests --ignore=backend/tests/t.py    → ['--ignore']
    run: pytest backend/tests -k "slow"                                → ['-k']
    run: python -m pytest backend/tests -q -m "not slow"               → ['-m']
    run: python -m pytest backend/tests --deselect=…                   → ['--deselect']
    run: python -m pytest backend/tests -q --maxfail=1                 → ['--maxfail']
```

第 5 行是这枚门的全部难度：`python -m pytest … -m "not slow"` 里前缀那枚 `-m` 必须剥掉、
第二枚必须留下——实测得到 `['-m']`（只剩一枚）才算正确。

**E 组（I-2 / 卡 H：本文件字节的哑门装饰器判据）**

```
  本文件实字节命中：[]（门当前绿）
  合成行 '@pytest.mark.skip'                                       → ['@pytest.mark.skip']
  合成行 "@pytest.mark.skipif(sys.platform=='win32', reason='x')"   → ['@pytest.mark.skipif']
  合成行 "@unittest.skip('why')"                                   → ['@unittest.skip']
  合成行 '@pytest.mark.xfail(strict=False)'                         → ['@pytest.mark.xfail']
  合成行 '@functools.lru_cache(maxsize=1)'                          → []
```

最后一行是必要的反例：本文件真实存在的那枚装饰器不许被误判（否则门一落地就假红）。

**V 段（门 1 的敏感性：常数落后就必须红）**
把 `EXPECTED_COLLECTED` monkeypatch 回上一轮的 1329、调用真实门函数：

```
V. 常数落后 1329 → RED： 收集数 1331 ≠ 钉住的 1329。
   常数已复原： 1331
```

### 五、真路径反证：一枚 skip 挂上门之后，枚数钉仍然绿、新钉红

E 组只证明正则识别得到形状；这组证明**跑起来的 pytest 里两枚钉的实际分野**（卡 H 的核心声称）。
做法：把本文件复制成 `backend/tests/test_b0_h_probe_tmp.py`，在 `import functools` 后补一枚
`import pytest`，再给 `test_collection_measurement_counts_node_ids_not_the_summary_line`
挂上 `@pytest.mark.skip(reason="fix-round-1 falsification jig")`，只跑那两枚门：

```
命令：PYTHONIOENCODING=utf-8 python -m pytest backend/tests/test_b0_h_probe_tmp.py -q \
      -k "carries_no_skip_or_xfail or gate_module_itself_is_collected"
E       AssertionError: 本门文件里出现 1 枚哑门装饰器：['@pytest.mark.skip']。收集面枚数对它们无感，job 可以是绿的而门不再执行
E       assert not ['@pytest.mark.skip']
1 failed, 1 passed, 13 deselected in 29.03s
```

`1 failed`（新-H 红）+ `1 passed`（同一份被哑掉的拷贝里枚数钉**照样绿**）＝ 卡 H 那句
"自我存续子钉抓不到哑掉的门"在**本仓真树**上复现，不是引用评审的夹具。
取证件用完即删：`rm` 后 `git status --porcelain` 与基线逐行相同（文末自查），`backend/tests/` 无残留。

### 六、反证台逮到了我自己写的一处假红（必须记的一条）

I-5 的第一版把 `python -m` 前缀的剥离正则写成了 `\bpython[3]?(?:\.exe)?[ \t]+-[ \t]+m[ \t]+`
——`-` 与 `m` 之间要求至少一枚空格，而实际写法是连字符 `-m`。后果：**一次完全正确的 Task 3 会让门 5
假红在 `['-m']` 上**（正是 I-1 那一类"门红在正确的树上"的形状）。当前树上门 5 先红在
`assert suite_wide == []`，所以这道缺陷**不可能靠跑定向套件发现**，只有 A 组那条
"post-Task-3 必须全绿"的反证能照出来：

```
（修复前）[post-Task-3] 门5 runs_the_pytest_suite: RED
        offender → 主门被过滤/短路旗标缩成了子集…： ⏎ ['-m'] ← - name: Run backend contract suite … run: python -m pytest backend/tests -q
（修复后）[post-Task-3] 门5 runs_the_pytest_suite: GREEN
```

正则改成 `\bpython[3]?(?:\.exe)?\s+-\s*m\s+` 后，D 组的 6 行形状逐枚复量得到期望值。

### 七、一处裁决点：门 6 对"主门缺席"不重复归因（请复核这一格）

R8 的措辞是"直接断言 SECA-20 段索引 < 主门段索引 < compose/pwsh 段索引"。字面实现有两条路：

* **严格读法**：四枚锚点都必须存在，主门缺席 ⇒ 门 6 也红。今天会多出**第 6 枚红**，
  而且它的根因与门 5 完全同一条（主门那一步不存在），套件会变成 `1325 passed / 6 failed`。
* **本轮采用的读法**：`扫描 / compose / pwsh` 三枚**必需**锚点缺席即红（不对"找不到"保持沉默），
  主门作为**第四枚可选锚点**参与全序——在场就必须严格落在扫描与 compose 之间；缺席时由门 5 归因。
  实测：`[reorder] 红`、`[compose 锚点被删] 红`、`[主门缺席] 绿`、`[REAL ci.yml] 绿`。

选后者的理由：R8 对 I-4 的病症描述是"把扫描步挪到主门之后仍绿"，两读法都能治；而"主门被删"这一维
门 5 已经用一条更具体的信息红着，两条红同一个根因会把红相名单变脏、并让 Task 3 Step 4 的
"除 .gitattributes 外全绿"少对一枚。**没有**因此放宽任何断言：三枚必需锚点 + 严格递增 + 文字存在
那半边都在。若上层判"应取严格读法"，改动是把 `_ORDER_ANCHORS` 里主门那枚的 `False` 改成 `True`
一行，代价是门 6 与门 5 双红同源。

### 八、全量套件：1326 passed / 5 failed（与 R8 预测逐字相符）

命令：`python -m pytest backend/tests -q`（对**终态字节** `19d335a1c15a` 跑；留档
`tmp/full-suite-round1-final.txt`，中途还有一次同形状读数 174.83s 对应 `c04e73b82c15`——
两次之间只改了注释行）
字面末行：

```
5 failed, 1326 passed, 36 warnings, 1133 subtests passed in 172.68s (0:02:52)
```

- **计数轴复现**：`5 + 1326 = 1331` = Step 二的探针读数，两条量法（探针数 node id / pytest 数结果）同源互证。
- **红只可能是我的红**：`FAILED` 恰 5 行（`grep -c "^FAILED"` = 5）、`^ERROR` 0 行，逐名 = 第三节红名单；
  末行无 `errors` / `skipped` / `deselected` ⇒ 收集期 0 error、0 skip，除本文件外的 39 枚模块无一被带红。
- **常驻成本读数（交 Task 5）**：门模块单跑 30.03s，其中约 29s 是那次 `--collect-only` 子进程；
  全量 172.68s（上一轮 171.08s ⇒ 两枚新增门的净成本约 +1.6s 量级，落在墙钟噪声带内）。
  墙钟不作判据（台账 M-6）：172.68s 仍在 Task 1 实测的 98.14–195.89s 带内。
- 本轮**没有**新的"brief 措辞与判据冲突"：上一轮记的那条 `1329 + 0 failed` 在红相不可满足，
  本轮的期望形状（5 红 / 1326 绿）本身就是红相交付物的定义，已按实测逐字对上。

### 九、SEC-A 密钥卫生门：仍然整模块绿，且没有加豁免行

```
命令：python -m pytest backend/tests/test_secret_hygiene_contract.py -q
字面末行：46 passed in 25.35s      （对终态字节 `19d335a1c15a` 跑；I-5 修复后那次同名单 25.69s）
```

直接对账（证明绿不是"没扫到我"）：

```
on delivery surface: True | surface files: 317
faces applied: ['     ["\']?     (?:api[_-]?key|secret', 'sk-[A-Za-z0-9_\\-]{16,}|gh[pousr]_[A-']
hits on my file: 0 []
my file in SEC-A EXEMPTIONS: False | exemption rows: 16
```

- 交付面枚数与上一轮同为 317（本轮只改文件内容、不增删文件），扫我的是代码档两枚面（`_CODE_FACES`）。
- 命中 **0 处**、**没进豁免表**、表仍 16 行 ⇒ 未加豁免行（R8 / 派发约束）。
- 写法上的两条预防：① 新增字符串全是散文字面量（`https://download.pytorch.org/whl/cpu`、
  `backend/requirements.txt`、`--index-url`），没有 `token = "长值"` 那种"关键字 + 冒号 + 引号 16 字符"
  的形状；② 反证台的敌意 URL 只存在于 `.superpowers/` 下的取证件里，那里既在
  `_UNSCANNED_PREFIXES` 内、也不在交付面上。

### 十、文件终态与交付面自查（只读 git，零写命令）

`backend/tests/test_ci_gate_contract.py` 的终态字节形状（字面读数）：

```
bytes 31379 | sha256-12 19d335a1c15a        （上一轮 17032 / 69f74974c2e1）
LF 588 | CRLF 0 | bareLF 588 | loneCR 0     ⇒ 全文件 LF，无游离 CR
test defs: 15
imports: ['__future__', 'functools', 'os', 'pathlib', 're', 'subprocess', 'sys']
app. mentions: []                            ⇒ 仅标准库、不 import pytest、不连 app.*
defined==listed: True 15 15 | ghost: [] | unlisted: []
mute-decorator self-scan: []                  ⇒ 新-H 对自己的源码不假红
EXPECTED_COLLECTED = 1331
TESTS_DIR residue: False                      ⇒ Minor ① 已落地
```

```
=== git status --porcelain ===
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
=== HEAD ===
7cc5efc
```

- 与上一轮**逐行相同**：identity 两枚是既存基线改动（未动、未提交），三枚 B0 文档/探针是既存未跟踪件；
  本轮只在 `test_ci_gate_contract.py` 上改写内容，未新增任何被跟踪路径。
  反证用过的 `backend/tests/test_b0_h_probe_tmp.py` 已删除并复量确认不在名单上。
- **identity 两枚的 sha 对照（卡 G 的新口径，实测）**：
  `backend/app/identity/README.md` = `3bc681bbc52c`、`backend/app/identity/__init__.py` = `2cfab9f18182`
  —— 与 B0-T1 记录、评审复核的基线值逐字符相同 ⇒ 本轮确实一片没碰。
- HEAD 未动，全程零 git 写命令（`add/commit/push/stash/checkout/restore/clean/config` 一枚都没跑）。
- `git diff --stat` 对 `.github/workflows/ci.yml` / `.gitattributes` / `backend/requirements.txt` /
  `docker-compose.yml` / `frontend/**` / `backend/tests/test_secret_hygiene_contract.py` **无输出**：
  前四是 Task 3/4 的靶子、按派发约束留红；最后一枚是 SEC-A 的封版面。
- 工作区取证件（`.superpowers/` 下，gitignored）：`tmp/b0_t2_falsify.py`、`tmp/falsify-round1.txt`、
  `tmp/gate-module-round1.txt`、`tmp/full-suite-round1.txt`、`tmp/h-gate-jig.txt`、
  `tmp/secA-and-constant-lag.txt`、快照 `snap-task2-fix1-post/`。

### 十一、交 Task 3 / Task 4 的约束（本轮更新过的部分）

1. **安装步必须 `run: |`**，且每条 `pip install` 的参数**各占一个物理行**（门 8 的形状钉现在机器化了
   上一轮那条口头约束；`>-` 会直接红）。豁免表仍是 `pytest` ×1 + `torch` ×1。
2. `--index-url` 只能是 `https://download.pytorch.org/whl/cpu`，`-r` 只能是 `backend/requirements.txt`
   （新-I 机器钉值；`--extra-index-url` / `-i` 也在面内，写了就必须落在同一集合）。
3. 主门那一步**不许带任何过滤/短路旗标**：`python -m pytest backend/tests -q` 这一形是绿的，
   加 `-k` / `-x` / `--lf` / `--deselect` / `--ignore` / `-m` 任一枚即红（门 5，D 组实测）。
4. 顺序注释**继续留在树上**（门 6 的文字存在半边看原文），且扫描步必须在主门之前、
   compose/pwsh 必须在主门之后（门 6 的顺序半边，B 组实测）。
5. `EXPECTED_COLLECTED = 1331` 已按 15 枚门实测回写；Task 3/4 不新增门文件用例就不必再动它，
   新增用例必须同步 `_OWN_TEST_NAMES` 并重新实测——门 1 与门 2 会当场把不一致挑出来（V 段实测）。

### 修复轮 1 结论

五枚 Important 全部按 R8 落地，三条随手 Minor 一并带上；门 13 → 15，`EXPECTED_COLLECTED` 1329 → **1331**
（1316 + 15，先实测后回写）。形状与 R8 预测**逐字相符**：门模块 `5 failed, 10 passed`、
全量 `5 failed, 1326 passed`。每一枚新增/收紧的门都用合成反证演示过"能红"（A–E + V 六组），
新-H 另在真路径上跑过"挂 skip ⇒ 新钉红、枚数钉仍绿"的分野；反证台还照出我自己写进 I-5 的一枚
假红（第六节），修后才确认 post-Task-3 正确形状下 6 枚 ci.yml 门全绿。
唯一留待上层复核的判断是第七节那一格（门 6 对主门缺席不重复归因）。



