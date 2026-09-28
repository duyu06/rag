# Task 3 报告：`ci.yml` 形态改造（让四枚 ci.yml 门转绿，其余三个 job 一字未动）

执行日期：2026-09-28。改动文件：**只有** `.github/workflows/ci.yml`（+ 本目录下的过程件，`.gitignore:25` 的 `.superpowers/` 规则挡在 git 之外）。
零 git 写命令；HEAD 仍 `7cc5efc0460abb01171c20cee61ef01bf5282a3d`。

---

## 一、动手前的红相（Step 1 / 基线复测，逐枚）

`python -m pytest backend/tests/test_ci_gate_contract.py -q`（改文件**之前**）：

```
5 failed, 10 passed in 28.98s
```

| # | 用例 | 改前 | 改前 offender（原文可判部分） |
|---|------|------|------------------------------|
| 1 | `test_collected_count_matches_the_pinned_number` | 绿 | — |
| 2 | `test_the_gate_module_itself_is_collected` | 绿 | — |
| 3 | `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` | 绿 | — |
| 4 | `test_collection_measurement_counts_node_ids_not_the_summary_line` | 绿 | — |
| 5 | `test_backend_contracts_has_no_unittest_discover_step` | **红** | `F1 复活：unittest 收集 1 处`，红在 `- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v` |
| 6 | `test_backend_contracts_runs_the_pytest_suite` | **红** | `主门不跑全量套件`（当时目录级 pytest 步不存在，`suite_wide` 为空；SECA-20 单文件步被 `(?!/)` 正确排除） |
| 7 | `test_step_ordering_still_explains_itself` | 绿 | 主门缺席刻意不重复归因（`mandatory=False`），故改前即绿 |
| 8 | `test_install_face_uses_requirements_txt_as_the_source` | **红** | `assert False where False = any(...)` —— 安装面没有 `-r backend/requirements.txt` |
| 9 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | **红** | `1 枚安装步不是 run: | 字面块 … 第一段正文：['- name: Install SECA-20 secret-scan dependencies\n        run: >-\n          python -m pip install --disable-pip-version-check\n          pytest\n          "fastapi']` |
| 10 | `test_install_face_pip_source_values_are_pinned` | 绿 | 折叠标量下 `(选项,值)` 收到空表 ⇒ 空判即绿（改后才真开始工作） |
| 11 | `test_every_exemption_row_states_why` | 绿 | — |
| 12 | `test_gitattributes_carries_the_required_rules` | **红** | `没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定`（`WindowsPath('E:/xiangmu/rag/.gitattributes').is_file() == False`）——**Task 4 的活，本任务不许碰** |
| 13 | `test_index_has_no_crlf_entries` | 绿 | — |
| 14 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | 绿 | — |
| 15 | `test_eol_rules_are_a_no_op_for_the_current_tree` | 绿 | — |

改前五枚红 = 四枚 ci.yml 形（#5/#6/#8/#9）+ 一枚 `.gitattributes`（#12），与交接说明逐字吻合。

---

## 二、步骤序列对照（**按 step 名，不按行号**——§20.4 的规矩）

### 改前 `backend-contracts`（9 步，快照 `snap-task3-pre/ci.yml`）

1. `actions/checkout@v4`（uses，无名）
2. `actions/setup-python@v5`（uses，无名）
3. `Install SECA-20 secret-scan dependencies` ← **本任务整枚删除**（13 包手写清单 + `run: >-`）
4. `Run SECA-20 delivery-surface secret scan`
5. `python -m compileall -q backend/app scripts`（裸 `- run:`，无名）
6. `python scripts/validate_demo_assets.py`（裸 `- run:`，无名）
7. `python -m unittest discover -s backend/tests -p 'test_*.py' -v`（裸 `- run:`，无名）← **本任务删除**
8. `Validate Docker Compose configuration`
9. `Validate Windows deployment script syntax`

### 改后 `backend-contracts`（10 步，= 规格 §5.1 目标序列的 10 行）

1. `actions/checkout@v4`
2. `actions/setup-python@v5`
3. **`Cache pip wheels`**（新增：`actions/cache@v4`，`key: b0-${{ runner.os }}-py3.12-${{ hashFiles('backend/requirements.txt') }}`）
4. **`Install backend dependencies (same source as requirements.txt)`**（新增：`run: |` 三行，torch CPU 发行源 / `-r backend/requirements.txt` / `pytest`）
5. `Run SECA-20 delivery-surface secret scan`（**命令字节未动**，见下）
6. `python -m compileall -q backend/app scripts`
7. `python scripts/validate_demo_assets.py`
8. **`Run backend contract suite (single runner: pytest)`**（新增主门：`python -m pytest backend/tests -q`，无旗标）
9. `Validate Docker Compose configuration`
10. `Validate Windows deployment script syntax`

新增的顺序注释（§5.2 两条理由 + "原既有步已删除"那句）留在主门步**之前**，按 `_job_steps` 的口径归进前一枚步（`validate_demo_assets` 段），因此对命令匹配不可见 —— 这正是 Task 2 修复轮 1 预演的形状。

### 其余三个 job：语义零改动（机器证明，不只是"diff 没显示"）

```
backend-contracts CHANGED
backend-integration IDENTICAL
backend-quality IDENTICAL
frontend-build IDENTICAL
```

（口径：`yaml.safe_load` 前后两棵树，逐 job 深比较。）

### SECA-20 扫描步的 `-k` 表达式：字节相同

```
scan -k byte-identical: True
```

（口径：在 pre/post 两段字节里各取 `-k "tracked_files` 起 120 字节比对，相等。）

---

## 三、行尾计数（Step 1 与 Step 5，字面读数）

```
PRE  CRLF 134 bareLF 0 bytes 5043 endswith_crlf True
POST CRLF 139 bareLF 0 bytes 6040 lines 139        （两枚块替换后）
POST-FIX CRLF 139 bareLF 0 bytes 6042              （第五节的名字引号修复后，终态）
FINAL CRLF 139 bareLF 0 bytes 6042
```

**bareLF 两次都是 0**，CRLF 134 → 139（净 +5 行：安装块 −14+13，主门块 −1+6）。
改法本身是**字节级 Python 操作**：`read_bytes()` → 断言 `count(b'\n')==count(b'\r\n')` → `split(b"\r\n")` 按行切 → 只在锚点处splice → `b"\r\n".join(...) + b"\r\n"` 写回；脚本 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/task3_edit_ci_yml.py`。
本文件仍属仓库 24 枚 mixed/待归一文件之一，**没有顺手"修好"它的行尾**（那是 Task 4 + `.gitattributes` 的账）。

---

## 四、Step 4 定向门 + 全量门册（终态）

Step 4 原命令：

```
$ python -m pytest backend/tests/test_ci_gate_contract.py -q -k "contracts or ordering or requirements_txt or exemption or states_why"
6 passed, 9 deselected in 0.58s
```

整模块 15 枚（终态，**1 红 / 14 绿**，与交接要求的期望终态一致）：

```
backend/tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number PASSED [  6%]
backend/tests/test_ci_gate_contract.py::test_the_gate_module_itself_is_collected PASSED [ 13%]
backend/tests/test_ci_gate_contract.py::test_the_gate_module_itself_carries_no_skip_or_xfail_decorator PASSED [ 20%]
backend/tests/test_ci_gate_contract.py::test_collection_measurement_counts_node_ids_not_the_summary_line PASSED [ 26%]
backend/tests/test_ci_gate_contract.py::test_backend_contracts_has_no_unittest_discover_step PASSED [ 33%]
backend/tests/test_ci_gate_contract.py::test_backend_contracts_runs_the_pytest_suite PASSED [ 40%]
backend/tests/test_ci_gate_contract.py::test_step_ordering_still_explains_itself PASSED [ 46%]
backend/tests/test_ci_gate_contract.py::test_install_face_uses_requirements_txt_as_the_source PASSED [ 53%]
backend/tests/test_ci_gate_contract.py::test_extra_pip_arguments_are_exactly_the_exemption_table PASSED [ 60%]
backend/tests/test_ci_gate_contract.py::test_install_face_pip_source_values_are_pinned PASSED [ 66%]
backend/tests/test_ci_gate_contract.py::test_every_exemption_row_states_why PASSED [ 73%]
backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules FAILED [ 80%]
backend/tests/test_ci_gate_contract.py::test_index_has_no_crlf_entries PASSED [ 86%]
backend/tests/test_ci_gate_contract.py::test_non_text_index_entries_are_exactly_the_enumerated_set PASSED [ 93%]
backend/tests/test_ci_gate_contract.py::test_eol_rules_are_a_no_op_for_the_current_tree PASSED [100%]

1 failed, 14 passed in 29.32s
```

唯一的红及其 offender 原文：

```
E       AssertionError: 没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定
E       assert False
E        +  where False = is_file()
E        +    where False = is_file = WindowsPath('E:/xiangmu/rag/.gitattributes').is_file
```

⇒ **红在 Task 4 的缺口上，与本任务无关，未削弱、未注释、未删任何断言。**

转绿的形状要点（逐枚复核，不是"我看它绿了"）：

* 门 5：全 job 的 `_step_script()`（剥 `#` 行）里再无 `unittest discover`。留下的两枚含该字面串的东西**全是注释**（改前既有的 17–22 行、本轮新增的 §5.2 注释），验证了 Task 2 预留的"注释不假红"设计确实生效。
* 门 6：`_SUITE_WIDE_PYTEST` 命中 `python -m pytest backend/tests -q`（`(?!/)` 把 SECA-20 的单文件步正确排除在外）；`_main_gate_filter_flags` 收到空表 —— 主门无 `-k/-m/-x/--lf/--ignore/--deselect/--maxfail/--collect-only` 任何一枚。
* 门 8/9/10：安装面 tokenize 出 `['torch', 'pytest']`，与 `PIP_INSTALL_EXEMPTIONS` 的 1+1 处数逐一对齐、无死行；`(选项,值)` 收到 `('--index-url','https://download.pytorch.org/whl/cpu')` 与 `('-r','backend/requirements.txt')`，两枚都落在 `ALLOWED_PIP_SOURCE_VALUES` 内。
* 门 7：段索引严格全序成立 —— SECA-20 扫描 < 主门 < compose < pwsh。

### 收集数钉（门 1）没有被人凑

`EXPECTED_COLLECTED = 1331` **一字未动**（门文件本轮零改动）。本轮没加也没删任何用例，1331 与改造前同一个数，绿是"实收 == 常数"而不是"常数跟着实收走"。

---

## 五、brief 的 YAML 原样落地时**没有**得到的东西：文件是非法 YAML

这是本任务唯一一处"brief 原文不可直接执行"，必须原样上报：

Step 3 的主门步名按 brief 字面写是

```yaml
      - name: Run backend contract suite (single runner: pytest)
```

plain scalar 里出现 `: `（冒号+空格）在 YAML 1.1/1.2 都是非法的。`yaml.safe_load` 的字面报错：

```
PRE OK
POST FAIL ScannerError mapping values are not allowed here
  in "<unicode string>", line 47, column 56:
     ... nd contract suite (single runner: pytest)
                                     ^
```

（对照：改前的 `ci.yml` 同一次脚本里读作 `PRE OK` ⇒ 非法形态是本轮引入的，不是我接手时的旧账。）

**处置**：把 step 名整体加双引号，**字面文本一字不改**（GitHub 上显示的步名、以及 §20.4"按 step 名引用"的对照物都保持 brief 的原样）：

```yaml
      - name: "Run backend contract suite (single runner: pytest)"
```

修完 `yaml.safe_load` 通过，10 枚步名逐个打印正常，字节数 6040 → 6042（只多两枚 `"`），行尾计数不变（`POST-FIX CRLF 139 bareLF 0`）。

**为什么这件事值得记账（交给 Task 5/6 与规格复核人）**：
`test_ci_gate_contract.py` 的 ci.yml 门**全部是正则 + 行切片**，不用 YAML 解析器。所以"把 `ci.yml` 写成非法 YAML"在这 15 枚门里**可以是全绿的**——门 5/6/7/8/9/10 会照常认下这枚纸门，远端则在 actions 解析 workflow 时才炸（`Invalid workflow file`），而那时本地已收工。本轮是我自己补跑 `safe_load` 才抓到的，不是门抓到的。
建议（**本任务不做**，因为不许改门文件）：给门册加一枚"`ci.yml` 必须能被 YAML 解析器加载"的存在性钉；或至少在主门步名里禁用 `: `。登记为规格 §14 自指盲区之外新增的一格。

---

## 六、Step 6：无 `.env` 全量本地等价（规格 §8 / B0-008）

`backend/.env` 用 `mktemp -d` **挪出仓库**，树内不留任何副本（R6：`.gitignore:6` 是精确路径 `backend/.env`，树内 `.env.bak` 会以 untracked 身份落进 SEC-A 扫描面、红两枚无关门）。单条命令完成 park → 跑 → restore：

```
HOLD=/tmp/tmp.hwxe29B3lJ
ls: cannot access 'backend/.env': No such file or directory   ← park 成功（cwd=仓库根、无 .env 的形态）
...
1 failed, 1330 passed, 36 warnings, 1133 subtests passed in 168.97s (0:02:48)
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
RESTORED
4d7f974107dd                                                   ← .env sha256 前 12 位，与要求值一致
```

`1331 = 1330 passed + 1 failed`，而失败的那一枚**只可能是** `.gitattributes`（Task 4）⇒ **主门命令 `python -m pytest backend/tests -q` 在无 `.env`、cwd=仓库根的形态下把 1331 枚全部实际执行了**，这正是本轮改造的目的：CI 从此真的跑到那 ~40 枚裸 `pytest` 函数。
完整输出留档 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/full-suite-task3-noenv.txt`。

### 恢复核验：`git status --porcelain` 逐行 = 基线 + 本轮 ci.yml

本轮动手前记录的基线（Task 2 收工态）与 Step 6 恢复后读数**完全相同**，只多 `.github/workflows/ci.yml` 这一枚本轮自己的改动：

```
 M .github/workflows/ci.yml                        ← 本任务唯一产物
 M backend/app/identity/README.md                  ← 接手时已存在，未动
 M backend/app/identity/__init__.py                ← 接手时已存在，未动
?? backend/tests/test_ci_gate_contract.py          ← Task 2 产物，本轮零改动
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

`.env` 恢复核验：`sha256sum backend/.env | cut -c1-12` = **`4d7f974107dd`**（与要求的钉值一致），且 `.env` 不进 porcelain（被 `.gitignore:6` 精确忽略）。

identity 两枚基线 sha 对照（progress.md:48 记录的 Task 1 冻结值 `3bc681bbc52c` / `2cfab9f18182`）：

```
backend/app/identity/README.md      3bc681bbc52c   （同）
backend/app/identity/__init__.py    2cfab9f18182   （同）
```

`git diff --stat -- backend/app` 里出现的仍是这两枚、且 **numstat 与接手时逐值相同**（本轮没有向 `backend/app/**` 写过任何一个字节）：

```
8	5	backend/app/identity/README.md
10	3	backend/app/identity/__init__.py
```

（另附 git 自己的两行 `LF will be replaced by CRLF` warning——这是 `core.autocrlf=true` + 无 `.gitattributes` 的既有症状，正是规格 §6.4 那枚门要消灭的东西，本轮不处理。）

---

## 七、diff 形态核验（不是整文件翻转）

```
$ git diff --stat .github/workflows/ci.yml
 .github/workflows/ci.yml | 35 ++++++++++++++++++++---------------
 1 file changed, 20 insertions(+), 15 deletions(-)

$ git diff --numstat .github/workflows/ci.yml
20	15	.github/workflows/ci.yml

$ git diff -U0 .github/workflows/ci.yml | grep '^@@'
@@ -23,14 +23,13 @@ jobs:
@@ -43 +42,7 @@ jobs:
```

**20 增 / 15 删、两个 hunk 都落在 `backend-contracts` 内**，与编辑量成正比；没有出现 `134/134` 那种"每行行尾都被重写"的形态 ⇒ CRLF 字节保持不变，`git diff` 未被污染。
全仓 `git diff --stat` 终态：

```
 .github/workflows/ci.yml         | 35 ++++++++++++++++++++---------------
 backend/app/identity/README.md   | 13 ++++++++-----
 backend/app/identity/__init__.py | 13 ++++++++++---
 3 files changed, 38 insertions(+), 23 deletions(-)
```

后两枚是接手时的既有项，本轮零改动。

---

## 八、SEC-A 密钥卫生门复跑（`ci.yml` 在它的扫描面上）

```
$ python -m pytest backend/tests/test_secret_hygiene_contract.py -q
46 passed in 25.35s
```

整模块 46 枚全绿，**没有新增任何豁免行**（本轮 YAML 里新增的都是发行源 URL 与包名，不含凭据形态）。

---

## 九、刻意没做的事（越界清单）

* 不建 `.gitattributes`（Task 4）⇒ 门 12 保持红。
* 不改 `test_ci_gate_contract.py`（含 `EXPECTED_COLLECTED=1331`）、不改 `backend/app/**`、`backend/tests/**`、`requirements.txt`、`docker-compose.yml`、`scripts/**`、`frontend/**`。
* 不动 `backend-integration` / `backend-quality` / `frontend-build`（第六节的 YAML 深比较为证）。
* 不给主门加 `--collect-only` 或任何旗标（交接约束：远端"N tests collected"读数归后续任务）。
* 不本地跑 `docker compose config` / `pwsh` 那两步（GitHub-runner-only，延到 Task 7 远端腿）。
* 不做任何 git 写命令；`git add`/`commit`/`push`/`stash`/`checkout`/`restore`/`clean`/`config` 一枚未跑。
* 不把 `ci.yml` 的行尾"顺手改成 LF"（它是 24 枚 mixed 之一，归 Task 4）。

## 十、快照

* `snap-task3-pre/ci.yml`：动手前字节（5043 字节 / CRLF 134 / bareLF 0 / sha 前 12 位 `244915837490`）。
  **与 `git cat-file -p HEAD:.github/workflows/ci.yml` 不是同一串字节**，而且这个差本身要写清楚（我一度把它当成"快照不可信"，复核后是本规格 §6.4 的正面证据）：
  HEAD/index blob 是 **134 枚裸 LF、0 枚 CRLF**（4909 字节），工作树那份是 **134 枚 CRLF、0 枚裸 LF**（5043 字节），
  `pre.replace(b'\r\n', b'\n') == head_bytes → True`。即 `core.autocrlf=true` 在 index 侧存 LF、签出侧发 CRLF，
  内容与 HEAD 逐字符相同（本轮动手前 `git status` 里 ci.yml 不在改动位上即为证）。⇒ 快照可信，且它顺手把"行尾归一化仍由每台机器的 `core.autocrlf` 决定"这句话量成了字节。
* `snap-task3-post/ci.yml`：终态字节，`cmp` 与工作树文件**逐字节相同**；sha256 前 12 位 `2d4d33d8fd44`、6042 字节、CRLF 139 / bareLF 0。
* 编辑脚本 `tmp/task3_edit_ci_yml.py`、无 `.env` 全量日志 `tmp/full-suite-task3-noenv.txt`。

---

## 收工自检（把上文"我说是"变成机器说的）

```
$ python -m pytest backend/tests/test_ci_gate_contract.py backend/tests/test_secret_hygiene_contract.py -q
1 failed, 60 passed in 52.88s          ← 60 = 门册 14 绿 + SEC-A 46；唯一 FAILED 仍是 .gitattributes

$ python -c "…字节级…"
CRLF 139 bareLF 0 bytes 6042
unittest-discover as COMMAND: False     ← 全文件里 `unittest discover` 只存在于 `#` 注释行，
                                          任何非注释行都不含它 ⇒ 单 runner 钉是真的绿，不是被注释糊绿

$ git status --porcelain
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

台账已追加：`.superpowers/sdd/ENTERPRISE_B0_PLAN/progress.md`（该文件保持纯 LF，CRLF 0）。

---

## Task 3 修复轮 1

本轮要求 = `progress.md` 的 **R9**（控制器裁定，绑定的需求原文）。一句话复述判据：
**给门册加第 16 枚门**，钉住刚刚真咬过 Task 3 的那一形——`.github/workflows/ci.yml` 里任何
plain scalar 值（`- name: …`、`key: …`）只要含 `: ` 就必须整体加引号，否则 YAML 把冒号读成
映射分隔符、整份 workflow `ScannerError`。三条硬约束照办：**不引 YAML 解析器 / 不引 PyYAML**、
**门哑即红（地板）**、**不许在今天真文件上假红**。本轮唯一改动文件 = `backend/tests/test_ci_gate_contract.py`；
`ci.yml` / `.gitattributes` / `backend/app/**` / `requirements.txt` / SEC-A 门 **零改动**（第九节的 git 读数）。

### 一、动了哪几处（`git diff` 的口径：门文件 untracked，所以看字节）

| 处 | 内容 | 性质 |
| --- | --- | --- |
| 模块 docstring | 追加一段"第 16 枚门不属于上面四族，它守的是这份 workflow 打得开" | 只增不改 |
| 新增 4 枚正则 + 2 个纯函数 + 1 枚 test | `_STRUCTURAL_SCALAR_LINE` / `_BLOCK_SCALAR_INDICATOR` / `_FLOW_STYLE_VALUE` / `_INLINE_COMMENT`、`_fully_quoted()` / `_workflow_scalar_entries()` / `_unquoted_colon_bearing_scalars()`、`test_workflow_plain_scalars_bearing_a_colon_space_are_quoted` | 全新 |
| `EXPECTED_COLLECTED` | 1331 → **1332**（先加门→实测→回写，见第四节） | 实测回写 |
| `_OWN_TEST_NAMES` | 15 → 16 枚，新增名排在 `test_every_exemption_row_states_why` 之后（与文件内定义顺序一致） | 同步扩名 |
| 两处 docstring 里的过期计数 | "本文件 15 枚全绿"→16、"那 1331 枚…15 枚门照样全绿"→1332/16 | 措辞对齐，**判据一字未动** |

既有 15 枚门的**任何一条断言都没被削弱、注释或删除**；`test_secret_hygiene_contract.py` 的
EXEMPTIONS 表**未加任何豁免行**（第八节：SEC-A 整模块 46 枚仍绿）。

### 二、第 16 枚门的代码与逐支口径

```python
def _unquoted_colon_bearing_scalars(text: str) -> "list[tuple[int, str, str]]":
    """条目里"值含 `: ` 却没整体加引号"的那几枚 —— R9 ① 咬过我们的原形。

    邻形登记（**刻意不钉**，要扩得控制器点头）：值以冒号**结尾**（`- name: Note:`）同样让
    PyYAML 报 `ScannerError: mapping values are not allowed here`，可 R9 ② 的字面范围是
    "值里含 `: `"。本枚按字面走，邻形只留这一句注释 + 报告里的实测证据。
    """
    offenders: "list[tuple[int, str, str]]" = []
    for lineno, key, value, dashed in _workflow_scalar_entries(text):
        if _FLOW_STYLE_VALUE.match(value):
            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
        if _fully_quoted(value):
            continue
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
        if ": " in body:
            offenders.append((lineno, ("- " if dashed else "") + key, body))
    return offenders
```

（配套的正则、`_fully_quoted()` 与 `_workflow_scalar_entries()` 的逐行走查在源码
`backend/tests/test_ci_gate_contract.py:498-571`，门函数本体在 `:574-598`。）
判据分支逐支说明它钉什么：

| 分支 | 代码位置 | 钉住的东西 / 为什么不放宽 |
| --- | --- | --- |
| 整行注释、空行 → 跳过 | `_workflow_scalar_entries` 的 `stripped.startswith("#")` | `ci.yml:22` 那句 `# … ModuleNotFoundError: httpx，本地却绿）。` 含 `: `，但它是散文不是标量。这是与既有门同一口径：命令匹配走 `_step_script()` 剥注释，本门同理 |
| 块标量正文 → 整段跳过 | `if block_indent is not None: if indent > block_indent: continue` | **本轮划下的那条界线**（第五节有实测）。`run: \|` 里的 python/shell 代码写 `print("failed: x")` 完全合法、YAML 根本不看那枚冒号；把它判红就是一枚会自己咬人的假红门。界线只有一条"缩进比开块行深 ⇒ 正文"，不是解析器 |
| 键名限定 ASCII 单词字符 | `[A-Za-z0-9][A-Za-z0-9_.\-]*` | 中文散文行、`- 6333:6333` 序列项都不进判据面。代价写死在注释里：只钉咬过我们的形，不重造 YAML |
| 冒号后必须是空格才算 | 正则里的 `[ \t]*:[ \t]+` + 检查 `": " in body` | 于是 `qdrant/qdrant:v1.19.1`、`'[scriptblock]::Create(...)'`、`https://download.pytorch.org/whl/cpu` 这些"冒号不跟空格"天然绿——YAML 也正是这么定的 |
| 值是 `|` / `>-` 指示符 → 开块，不查值 | `_BLOCK_SCALAR_INDICATOR` | `run: \|` 本身没有可查标量；同时登记缩进起点，正文从此处开始豁免 |
| flow 值（`[` / `{` 开头）→ 跳过 | `_FLOW_STYLE_VALUE` | `branches: [main]`、`ports: [...]` 里的冒号是 YAML 自己的语法分隔符，不是 plain scalar |
| 整体同种引号包住 → 跳过 | `_fully_quoted()` | 这正是 Task 3 的修法：`- name: "… (single runner: pytest)"` ⇒ 绿。**部分**加引号（`"foo: bar" baz`）不算，仍红 |
| 内联注释先切掉再查 | `_INLINE_COMMENT.split(value, 1)[0]` | `key: v  # note: x` 的 `: ` 在注释里 ⇒ 绿。YAML 对 plain scalar 也是同一条"空格+井号起即注释"规则 |
| **地板**：扫不到任何 `- name:` 结构行 ⇒ 当场红 | `assert named, …` | 与 `test_extra_pip_arguments_are_exactly_the_exemption_table` 的"非空 tokenize 地板"同族：一枚什么都扫不到的门不能读成"CI 干净"。今天真文件读到 15 枚 `- name:`（第三节 A 段） |
| 判据本体 | `assert not offenders, …` | 报出**行号 + 键 + 值原文**，并写明修法是加引号而不是删掉带冒号的半句（R9 ① 的修法，也是 Task 3 实际做的） |

本门与既有 ci.yml 门的两处**刻意不同**，都写进了注释：

* 它扫**整份文件**，不切成 `backend-contracts` 一块。理由：一枚坏标量落在哪个 job 都会让
  GitHub 打不开整份 workflow，把范围限在一个 job 等于放行另外三个。
* 它不走 `_step_script()`，而是自带"整行注释 / 块标量正文"两支跳过逻辑。理由：`_step_script()`
  是"剥掉 `#` 行"，对本门的宾语（结构行）够用但不完整——它不知道 `run: |` 的正文该整段豁免。
  两支口径的**方向**与既有门一致（注释不是命令、正文不是标量），所以不出现"同一形状两枚门一个绿一个红"。

刻意留在范围外的（写在函数 docstring 里，不假装已解决）：多行 plain scalar 的续行、
锚点/别名（`&x` / `*x`）、`?` 复杂键。它们都不是咬过我们的那一形；再往下钉就等于造第二套
YAML 真相——R9 ② 明令禁止的那件事。

**本轮顺手量出的一枚邻形（登记，未扩判据）**：值以冒号**结尾**、后面没有空格
（`- name: Note:`）也会让 YAML 当场 `ScannerError`，而 R9 ② 的字面范围是"值里含 `: `"。
我用宿主 PyYAML 把几种形状的合法性各打一枪（只当口径校准，不当判据）：

```
inline run with ': ' inside double quotes  → ScannerError: mapping values are not allowed here
same value fully single-quoted             → PARSES OK
colon not followed by space                → PARSES OK
trailing colon no space                    → ScannerError: mapping values are not allowed here
unquoted name with colon space             → ScannerError: mapping values are not allowed here
```

三条结论：① "值里含 `: ` 且没整体加引号"确实非法 ⇒ 本门的靶子是实的；
② 部分加引号（`python -c "print('x: y')"` 这种把带冒号的串写在**未加引号**的值中间）也非法
⇒ 本门"只有整体同种引号包住才算安全"的口径是对的，不是过严；
③ `qdrant/qdrant:v1.19.1` 这类"冒号不跟空格"合法 ⇒ 本门放得对，没有过拟合。
第 ④ 条是登记项：`- name: build:`（值以冒号收尾）同样炸，但它越出 R9 ② 的字面，
本枚**没钉**，只在 `_unquoted_colon_bearing_scalars()` 的 docstring 里留了这一句 + 本节的实测。
要不要扩，交控制器 / Task 5 终审判。

### 三、反证台：门必须是红的当且仅当形状回来了（字面输出）

台子 = `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/b0_t3f1_falsify.py`。手法比 Task 2 那台更进一步：
**不 patch `_ci_text`，而是把合成 workflow 写成真文件、落在仓库之外的临时目录**（`tempfile.mkdtemp()` → `%TEMP%`），
再把门模块的 `CI_FILE` 指过去、调用**真门函数**（门照原样 `_ci_text() → CI_FILE.read_text()`）。
仓库树里一枚合成文件都不落——R6 / §16 卡 F 已证：往树里丢一枚未忽略的 untracked 文件，
SEC-A 的两枚扫描门当场双红，反证台自己就会把现场弄脏。收尾 `shutil.rmtree`，末行自证目录已消失。

```
$ PYTHONIOENCODING=utf-8 python .superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/b0_t3f1_falsify.py
合成文件目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f1_ox7cnx64
==============================================================================
A. 今天的真 ci.yml（Task 3 已把唯一那枚危险步名加了引号）必须绿
==============================================================================
[REAL-quoted] → GREEN   (结构行 59 枚 / `- name:` 15 枚)

==============================================================================
B. R9 ① 的原形：计划正文那枚**未加引号**的步名 ⇒ 第 16 枚门必须红
==============================================================================
[PLAN-LITERAL-unquoted] → RED   (结构行 59 枚 / `- name:` 15 枚)
        门的断言原文 → 1 枚 plain scalar 的值里含 `: ` 却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符，整份 workflow 直接 `ScannerError`：第 47 行 `- name: Run backend contract suite (single runner: pytest)` ⏎ 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
  同一次运行里其余 6 枚 ci.yml 门的读数（R9 ② 说的盲区：14 绿可以带着非法 YAML）：
[PLAN-LITERAL × 门4 no_unittest_discover] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门5 runs_the_pytest_suite] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门6 step_ordering] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门7 requirements_txt_source] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门8 exemption_table] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门I source_values] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[PLAN-LITERAL × 门16 新·quoted_scalar] → RED   (结构行 59 枚 / `- name:` 15 枚)
        门的断言原文 → （同上，逐字相同）

C. 加引号 / 不含冒号 的对照：门不许假红
[quoted-double] → GREEN   (结构行 2 枚 / `- name:` 1 枚)
[quoted-single] → GREEN   (结构行 2 枚 / `- name:` 1 枚)
[colon-free-unquoted] → GREEN   (结构行 2 枚 / `- name:` 1 枚)

D. 同一条 `: ` 出现在块标量正文里 ⇒ 绿（这就是本轮划下的界线）
[block-scalar-body] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[only-block-bodies] → GREEN   (结构行 2 枚 / `- name:` 2 枚)
[structural-key-pair] → RED   (结构行 3 枚 / `- name:` 1 枚)
        门的断言原文 → 1 枚 plain scalar 的值里含 `: ` 却没整体加引号 —— …：第 4 行 `key: cache: primary` ⏎ 修法=…

E. 地板（fail-closed）：扫不到任何 `- name:` ⇒ 门哑，当场红
[no-name-steps] → RED   (结构行 2 枚 / `- name:` 0 枚)
        门的断言原文 → workflow 里一枚 `- name:` 结构行都没扫到（结构行共 2 枚）：这不能读成『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）
[empty-file] → RED   (结构行 0 枚 / `- name:` 0 枚)
        门的断言原文 → workflow 里一枚 `- name:` 结构行都没扫到（结构行共 0 枚）：…

F. 真文件在全部 7 枚 ci.yml 门下的终态读数（应与门册一致）
[REAL × 门4 no_unittest_discover] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门5 runs_the_pytest_suite] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门6 step_ordering] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门7 requirements_txt_source] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门8 exemption_table] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门I source_values] → GREEN   (结构行 59 枚 / `- name:` 15 枚)
[REAL × 门16 新·quoted_scalar] → GREEN   (结构行 59 枚 / `- name:` 15 枚)

临时目录已清理：C:\Users\zhang\AppData\Local\Temp\b0_t3f1_ox7cnx64 存在 → False
```

（A / F 两段与 B 段的判定行是逐字粘的；B 段里第二发 RED 的断言原文与第一发**逐字相同**，我用"（同上，逐字相同）"折叠，
C、D、E 三段则只折叠了重复的 `====` 表头行。每条 `[case] → verdict`、结构行枚数与断言原文都是字面读数，
完整原始日志在 `tmp/falsify-t3f1.txt`。）

三件事各自被证成了：

1. **门会红**：把 Task 3 修好的那两枚 `"` 摘掉（= 计划原稿的字节，其余一字不改），第 16 枚门当场红，
   并精确点名"第 47 行 `- name: Run backend contract suite (single runner: pytest)`"。
2. **盲区是真的**：同一份非法 YAML 喂给其余 6 枚 ci.yml 门，**6 枚全绿**。
   加上不碰 YAML 的另外 9 枚（收集数/自我存续/SEC-A 无关），旧门册在这份打不开的文件上就是
   R9 ② 说的"14 绿 + 到远端才炸"。这一发是本门存在理由的机器证明，不是修辞。
3. **门不假红**：双引号、单引号、不含冒号三种步名全绿；`: ` 只出现在 `run: |` / `run: >-` 正文里的
   两种形状（D-1 塞进真文件、D-2 整份只剩块标量）也全绿；真文件（A、F 两段）绿。
   地板另侧也红：`- name:` 一枚都扫不到（步名全删 / 空文件）⇒ 红在"门哑了"，不绿在"没发现问题"。

顺带把 R9 ① 那句话复核成字节（`tmp/b0_t3f1_yamlshape.py` 第三节，**门之外**的反向核对，用宿主机上恰好装着的
PyYAML 6.0.3；这枚 import 只出现在工作区脚本里，没进门文件、没进 `requirements.txt`）：

```
  safe_load(真文件) OK ⇒ jobs=['backend-contracts', 'backend-integration', 'backend-quality', 'frontend-build'] / backend-contracts steps=10
  主门那一步的 name 读成字符串：'Run backend contract suite (single runner: pytest)'
  计划原稿那枚未加引号的步名：ScannerError → mapping values are not allowed here / in "<unicode string>", line 47, column 56: / ... nd contract suite (single runner: pytest) / ^
  ⇒ 第 16 枚门钉的就是这一形
```

### 四、`ci.yml` 全文的 `: ` 分类账：还有没有别的未加引号冒号本该被抓到

台子 = `tmp/b0_t3f1_yamlshape.py`（第一、二节）。它用**门自己的**正则与那条缩进规则给每一枚含
`: ` 的行归类，不另起一套判断。

```
一、`: ` 分类账：`ci.yml` 里每一枚含 `: ` 的行落在哪一支
  第  22 行 [整行注释（散文，不是标量）]  # 只装 pydantic+argon2 的第一版在 CI 收集阶段就 ModuleNotFoundError: httpx，本地却绿）。
  第  29 行 [结构行 · 块标量开块行（值就是 `|` / `>-` 指示符，没有可查的标量）]  run: |
  第  37 行 [结构行 · 块标量开块行（…）]  run: >-
  第  47 行 [结构行 · 值里含 `: ` 且已整体加引号 ⇒ 合法]  - name: "Run backend contract suite (single runner: pytest)"
  第  50 行 [结构行 · 块标量开块行（…）]  run: |
  第  70 行 [结构行 · 块标量开块行（…）]  run: >-
  第 114 行 [结构行 · 块标量开块行（…）]  run: |
  —— 分类合计：
      58 × 结构行 · 那枚 `: ` 就是键分隔符本身（值侧没有第二枚）⇒ 无风险
       5 × 结构行 · 块标量开块行（值就是 `|` / `>-` 指示符，没有可查的标量）
       1 × 整行注释（散文，不是标量）
       1 × 结构行 · 值里含 `: ` 且已整体加引号 ⇒ 合法
  值侧真含 `: ` 的结构行：[47] ⇒ 未加引号的：[]（空 = 门绿）
```

**结论（这就是要上报的那句话）**：今天的 `ci.yml` 里，值侧真含 `: ` 的结构行**只有第 47 行一枚**，
而它已被 Task 3 加了引号 ⇒ 本门在真文件上绿，且**没有任何一条别的行是"本该被抓到而没抓到"**。
其余 64 枚含 `: ` 的行分三类，各自为什么不危险：

* 58 枚是 `键: 值` 本身的那枚分隔符（`- name: Cache pip wheels`、`uses: actions/checkout@v4`、
  `key: b0-${{ … }}`、`image: qdrant/qdrant:v1.19.1`…）——值侧没有第二枚 `: `，YAML 读得毫无歧义。
* 5 枚是 `run: |` / `run: >-` 的**开块行**：值是块指示符，不是标量；门在这里登记缩进起点。
* 1 枚是整行注释（`:22`）：散文，与命令匹配那批门走 `_step_script()` 剥注释是同一条口径。

**界线怎么划的（不是"为了少报一条而划线"）**：宾语不同。本门的宾语是 **YAML 自己要吃的那枚标量**——
step 名、`key:`、`uses:` 这类 plain scalar，写坏了整份文件打不开。块标量正文（`run: |` 下面那 20 行
python / shell / pwsh）不是 YAML 的标量，它是**字符串本体**，里面的冒号没有任何歧义；
把它算进来，门就会在一次完全合法的改动（比如给 compose 校验步加一句 `echo "compose: failed"`）上假红，
而假红门的下场是被后人加豁免、连真形一起放过。同一道理我把 flow 集合（`[main]`）、内联注释、
"冒号后不跟空格"（`::Create`、`v1.19.1`、`https://…`）三族排除，每一条都在源码注释里写明了理由。
反证台 D 段是这条界线的两侧各打一枪：同一份文本，冒号写在正文里 ⇒ GREEN、写在结构行上 ⇒ RED。

标准库还能顺手确认的（第二节的 C1–C9，**只登记不进门**，因为它们不是咬过我们的形）：
缩进无制表符、缩进全为 2 的倍数、结构行引号成对、无行尾空白、5 枚块标量开块行都有正文、
四枚 job 都找得到（step 段数 10 / 8 / 5 / 4）、步名无重复、字节形状 **CRLF 139 / bareLF 0**
（与 Task 3 记的终态逐字相同 ⇒ 本轮没有碰过 `ci.yml`）。

### 五、常数回写：门 15 → 16，`EXPECTED_COLLECTED` 先加门、再实测、才回写

顺序本身就是判据的一部分——**加完门立刻重量**，红相读数先落进日志，再改常数：

```
$ python scripts/b0_collection_probe.py
TOTAL 1332
   16  backend/tests/test_agent_contracts.py
    …
$ python scripts/b0_collection_probe.py --node-ids | grep test_ci_gate_contract | wc -l
16
```

算术（两侧都是实测量，不是凑）：Task 1 冻结的基线 **1316** + 本文件现在的 **16** 枚 = **1332**；
探针总数 1332 − 本模块 16 = 1316 ⇒ 与基线逐枚对齐。预测值（R9 ② 写的"预期 1332"）与实测**相等**，
本轮**没有偏差要上报**。

红相证据（加门后、改常数前，`tmp/gate-module-t3f1-redphase.txt`）——门 1 当场红，且红得能归因：

```
E       AssertionError: 收集数 1332 ≠ 钉住的 1331。
E       新增 16 枚：['backend/tests/test_ci_gate_contract.py::…', …]
…
FAILED backend/tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
2 failed, 14 passed in 29.62s
```

（"新增 16 枚"是相对 Task 1 那份 1316 行的 `baseline/collected-node-ids.txt` 的差集，不是相对 1331；
明细基线只用于把失败信息写得能看，判据仍是"实收 == 常数"那一条——R7 ② 的口径未动。）

回写常数后复跑：

```
$ PYTHONIOENCODING=utf-8 python -m pytest backend/tests/test_ci_gate_contract.py -q -rf
1 failed, 15 passed in 29.14s          ← 唯一红：test_gitattributes_carries_the_required_rules（Task 4 的活）
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
```

### 六、门册终态（16 枚逐枚点名，`-v` 的字面读数）

`tmp/gate-module-t3f1-verbose.txt`：`1 failed, 15 passed in 35.06s`。

| # | 门 | 本轮读数 |
| --- | --- | --- |
| 1 | `test_collected_count_matches_the_pinned_number` | PASSED（常数 1332 = 实测） |
| 2 | `test_the_gate_module_itself_is_collected` | PASSED（实收 16 == `_OWN_TEST_NAMES` 16，逐名相等） |
| 3 | `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` | PASSED（新门没被挂哑） |
| 4 | `test_collection_measurement_counts_node_ids_not_the_summary_line` | PASSED |
| 5 | `test_backend_contracts_has_no_unittest_discover_step` | PASSED |
| 6 | `test_backend_contracts_runs_the_pytest_suite` | PASSED |
| 7 | `test_step_ordering_still_explains_itself` | PASSED |
| 8 | `test_install_face_uses_requirements_txt_as_the_source` | PASSED |
| 9 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | PASSED |
| 10 | `test_install_face_pip_source_values_are_pinned` | PASSED |
| 11 | `test_every_exemption_row_states_why` | PASSED |
| **12** | **`test_workflow_plain_scalars_bearing_a_colon_space_are_quoted`（本轮新增）** | **PASSED（真文件绿 = 不假红）** |
| 13 | `test_gitattributes_carries_the_required_rules` | **FAILED**（没有 `.gitattributes`，Task 4 的活） |
| 14 | `test_index_has_no_crlf_entries` | PASSED |
| 15 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | PASSED |
| 16 | `test_eol_rules_are_a_no_op_for_the_current_tree` | PASSED |

**门册合计 15 绿 / 1 红**，红的那枚与 Task 3 轮完全同一枚、同一理由 ⇒ 本轮零附带伤害。
定向选择也复跑了一次（新门本身 0.64s、无子进程）：

```
$ python -m pytest backend/tests/test_ci_gate_contract.py -q -v -k "quoted"
collected 16 items / 15 deselected / 1 selected → 1 passed, 15 deselected in 0.64s
$ python -m pytest backend/tests/test_ci_gate_contract.py -q -k "quoted or ordering or requirements_txt or exemption or states_why or unittest"
6 passed, 10 deselected in 0.57s
```

### 七、两把全量读数（`tmp/t3f1_full_suite.sh`，字面输出）

台子里带 `trap … EXIT INT TERM` 兜底，`.env` 一律**挪出仓库**（R6：不在树里留 `.env.bak`），
收尾断言 sha 与 `git status` 都复原：

```
=== ① 原地全量（backend/.env 在场 = 日常本地形态） ===
rc=1
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
1 failed, 1331 passed, 36 warnings, 1133 subtests passed in 174.19s (0:02:54)
=== ② 无 .env 全量（CI 形态，可比 Task 3 台账那枚 1330/1） ===
parked: backend/.env 已挪出仓库到 /tmp/tmp.dspmk6dW7m
rc=1
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
1 failed, 1331 passed, 36 warnings, 1133 subtests passed in 179.73s (0:02:59)
=== 复原校验 ===
.env sha 前 12 位：before=4d7f974107dd after=4d7f974107dd
无 .env.bak 残留
git status 与开工前逐行相同（7 行）
```

两把**同值**：**1331 passed / 1 failed**，FAILED 逐名只有 `.gitattributes` 那枚（Task 4 的活），
无附带伤害。`1331 + 1 = 1332` ⇒ 主门 `python -m pytest backend/tests -q` 在两种形态下都把
钉住的 1332 枚**实际执行**了。与本轮开头预测的形状（"门册 1 红 / 15 绿；全量 1331/1"）**逐字相符**，
没有需要上报的偏差；两处 `.env` 维度中性这件事也和 Task 1 的四格读数一致。

### 八、SEC-A 密钥卫生门复跑（改过的门文件在它的扫描面上）

```
$ python -m pytest backend/tests/test_secret_hygiene_contract.py -q
46 passed in 25.25s
```

整模块 46 枚全绿：新门的中文注释、步名样例、`https://…` 之类都不是凭据形态，
**没有加任何豁免行**、没有动 `test_secret_hygiene_contract.py` 一个字节。

### 九、本轮文件的字节形状（终态）

```
bytes 39045 | LF 707 | CRLF 0 | bareLF 707 | sha256[:12] fd3aa56eff49
imports: ['from __future__ import annotations', 'import functools', 'import os',
          'import re', 'import subprocess', 'import sys', 'from pathlib import Path']
third-party/app imports: []        ← 无 `app.*`、无 PyYAML、无第三方（`yaml import present: False`）
def test_ count: 16
roster == defs (one-for-one): True | 枚数: 16
EXPECTED_COLLECTED: 1332
```

改动前（= Task 2 修复轮 1 的终态，`snap-task2-fix1-post/` 逐字节相同）：31379 字节 / 588 LF / 0 CRLF /
sha `19d335a1c15a` / 15 枚。本轮 +7666 字节、+119 行、+1 枚门。

### 十、刻意没做的事（越界清单）

* 不改 `.github/workflows/ci.yml`（它已经是对的）—— 收尾 `cmp snap-task3-post/ci.yml .github/workflows/ci.yml`
  = **IDENTICAL**，且第四节量到 CRLF 139 / bareLF 0 与 Task 3 记的终态相同。
* 不建 `.gitattributes`（Task 4）⇒ 门 13 保持红，本轮**未削弱、未注释、未删除**任何断言。
* 不引 YAML 解析器、不给门加第三方 import（R9 ② 的第一约束）；`yaml.safe_load` 只出现在**仓库外的
  反证台脚本**里当口径校准，门文件与 `requirements.txt` 都干净。
* 不改 `backend/requirements.txt`、`docker-compose.yml`、`scripts/**`（`b0_collection_probe.py` 只**调用**）、
  `frontend/**`、`backend/app/**`、`backend/tests/test_secret_hygiene_contract.py`。
* 不给 SEC-A 的 EXEMPTIONS 表加豁免行。
* 不做任何 git 写命令：`add` / `commit` / `push` / `stash` / `checkout` / `restore` / `clean` / `config`
  一枚未跑；只用了 `git status` / `rev-parse` / `hash-object` / `rev-parse HEAD:<path>` / `ls-files`（门自己的
  `ls-files --eol` 也算）。HEAD 仍 `7cc5efc`；identity 两枚工作树文件的 sha256 前 12 位
  **`3bc681bbc52c` / `2cfab9f18182`** 与 progress:48 的冻结值逐字相同。
* 不扩判据到 R9 ② 字面之外的邻形（值以冒号结尾那一形只在第二节登记 + 注释里留一句）。

### 十一、快照与产物

* `snap-task3-fix1-post/test_ci_gate_contract.py`：门文件终态 39045 字节，`cmp` 与工作树**逐字节相同**，sha 前 12 位 `fd3aa56eff49`。
* 反证台：`tmp/b0_t3f1_falsify.py`（合成 workflow 落 `%TEMP%`，跑完 `rmtree`，末行自证目录已消失）、
  `tmp/b0_t3f1_yamlshape.py`（`: ` 分类账 + C1–C9 + 门之外的 PyYAML 反核）。
* 日志：`tmp/falsify-t3f1.txt`、`tmp/yamlshape-t3f1.txt`、`tmp/gate-module-t3f1-redphase.txt`（2 红）、
  `tmp/gate-module-t3f1-final.txt`、`tmp/gate-module-t3f1-verbose.txt`、
  `tmp/full-suite-t3f1-inplace.txt`、`tmp/full-suite-t3f1-noenv.txt`、`tmp/full-suite-t3f1-summary.txt`、
  `tmp/t3f1_full_suite.sh`、`tmp/status-before.txt` / `status-after.txt`。
* 台账追加：见 `progress.md` 末尾的"R9 ② 修复轮 1 回执"一行（该文件保持纯 LF、CRLF 0）。

### 收工自检（把上文"我说是"变成机器说的）

```
$ python -m pytest backend/tests/test_ci_gate_contract.py -q -rf
1 failed, 15 passed in 29.32s           ← 唯一红 = .gitattributes（Task 4）
$ python -m pytest backend/tests/test_secret_hygiene_contract.py -q
46 passed in 25.25s                     ← 未加豁免行
$ python scripts/b0_collection_probe.py | head -1
TOTAL 1332                              ← = EXPECTED_COLLECTED
$ cmp .github/workflows/ci.yml snap-task3-post/ci.yml
（无输出 = 逐字节相同 ⇒ 本轮没碰 ci.yml）
$ git status --porcelain
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
                                        ← 与开工前 7 行逐行相同；合成文件一枚不入树
```

## Task 3 修复轮 2

（2026-09-28，Task 3 的修复轮 2/5；工作树态、**零提交**、HEAD 仍 `7cc5efc`。裁定 = `progress.md` 的 **R10**。）

### 一、本轮动的与不动的

| 项 | 位置 | 性质 |
| --- | --- | --- |
| I-3 + Minor 5 | `backend/tests/test_ci_gate_contract.py` 门 16 的 `_unquoted_colon_bearing_scalars()` | 判定顺序纠正 + 邻形扩**一个子句**（不加门） |
| I-1 + Minor 4 | `ci.yml` 块 A（原第 17-22 行 → 现 17-24） | 现在时改成现状，历史括注明确标成历史 |
| I-2 | `ci.yml` 块 B 抬头（原第 42 行 → 现 44-51） | 断言按**实验**重写 |
| Minor 6 | `ci.yml` 第 29 行 cache key | 补 `cpu-torch` 判别位 |

**未动**：`backend-integration` / `backend-quality` / `frontend-build`（机器证明见§六）、SECA-20 扫描步
四行（与 HEAD 逐字节相同）、`EXPECTED_COLLECTED`（仍 **1332**）、`_OWN_TEST_NAMES`（仍 16 枚）、
`test_secret_hygiene_contract.py` 与其豁免表、任何既有断言（一枚都没削、没删）。
**没建** `.gitattributes`（Task 4 的活）⇒ 它那枚红仍是唯一红，这是正确的终态。

改法是**字节级 Python splice**（`read_bytes` → 断言 `count(LF)==count(CRLF)` → 按 `\r\n` 切行 →
`\r\n.join` 写回 → 复核），三枚脚本各只碰 ci.yml 这一枚文件：`tmp/task3f2_edit_ci_blockA.py`、
`tmp/task3f2_edit_ci_cachekey.py`、`tmp/task3f2_edit_ci_blockB.py`。**没有**顺手归一化本文件的行尾
（它仍属 24 枚 mixed 之一，归 Task 4）。

### 二、I-3 + Minor 5：门 16 的判定顺序（先复现、再修、再验）

**复现（改之前）**——合成 workflow 写成**真文件**落在仓库之外的 `%TEMP%`，只把门模块的 `CI_FILE`
指过去、调用**真门函数**（脚本 `tmp/b0_t3f2_i3_repro.py`，字面输出）：

```text
合成文件目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f2_i3_9b1vdf7k
--- I-3：合法写法（整体加引号 + 行内注释）在修复前的判定 ---
[RED] quoted_plus_trailing_comment
        门原文：1 枚 plain scalar 的值里含 `: ` 却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符，整份 workflow 直接 `ScannerError`：第 10 行 `- name: "Run suite (single runner: pytest)"` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
结论：假红成立（计划要求修的缺陷）

--- 同一形状的字节细节：门看到的 value 长什么样 ---
第 10 行 dashed=True value(原文)='"Run suite (single runner: pytest)"  # keep quoting'
    _fully_quoted(原始值) = False
    剥行内注释后 = '"Run suite (single runner: pytest)"'  _fully_quoted(剥后) = True
    含 ': ' = True  endswith(':') = False

--- 邻形（Minor 5）：值以冒号结尾，YAML 读成嵌套映射 opener ---
[GREEN] trailing_colon_plain
[GREEN] trailing_colon_quoted
    PyYAML: quoted_plus_comment ⇒ 合法
    PyYAML: trailing_colon_plain ⇒ ScannerError mapping values are not allowed here
    PyYAML: trailing_colon_quoted ⇒ 合法
```

红因量得很直白：`_fully_quoted()` 跑在**原始值**上，而原始值的末字符是注释散文的 `g`，那对引号
于是"配不成"；剥注释发生在**之后**，晚了一步。同一发宿主 PyYAML 判合法 ⇒ 这是**假红**，不是严。
同一次复现顺带把 Minor 5 也量了：尾冒号那一形旧门**漏**（GREEN），宿主 PyYAML 报的是同一个
`ScannerError`。

**修法**：只调顺序 + 加一个子句。不引 YAML 解析器（标准库没有、PyYAML 被依赖面禁、R9 ② 不许造
第二份真相），也**不做** tab / 缩进 / 引号配对三件套（R10 判为 YAGNI，那三件留在临时脚本当证据）。

```python
# 改前
        if _FLOW_STYLE_VALUE.match(value):
            continue
        if _fully_quoted(value):            # ← 跑在原始值上：注释尾巴把引号对拆开了
            continue
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
        if ": " in body:
            offenders.append(...)
# 改后
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()   # 先剥行内注释
        if _FLOW_STYLE_VALUE.match(body):
            continue
        if _fully_quoted(body):             # 再判引号
            continue
        if ": " in body or body.endswith(":"):               # Minor 5：尾冒号邻形，同一事故家族
            offenders.append(...)
```

同门三处文字随判据一起校准（`_unquoted_colon_bearing_scalars` 的 docstring 里"刻意不钉、要扩得
控制器点头"那句登记按 R10 撤销、门 16 的 docstring 补两条、断言原文补"或以 `:` 结尾"、模块头第
16 枚门那一段改写）。**门名与门数一字未改**（R10 明令不加门）⇒ `EXPECTED_COLLECTED` 无需回写，
实测仍是 1332（见§六）。

**改后反证台**（`tmp/b0_t3f2_falsify_gate16.py`，12 发全落在仓库外；字面输出）：

```text
合成文件目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f2_battery_ri3pd6ux

[GREEN] 期望[GREEN] ✓ A 合法：整体加引号 + 行尾内联注释
        PyYAML 认合法；I-3 之前它被假红｜PyYAML 合法
[GREEN] 期望[GREEN] ✓ B 合法：单引号 + 行尾内联注释
        同一对引号即可，不必双引号｜PyYAML 合法
[RED] 期望[RED] ✓ C 非法：未加引号且含 `: `（R9 ① 原形）
        ScannerError：mapping values are not allowed here｜PyYAML ScannerError
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 10 行 `- name: Run suite (single runner: pytest)` 修法=给值整体加双引号…
[RED] 期望[RED] ✓ D 非法：未加引号含 `: ` + 行尾注释（不许因剥注释转绿）
        注释不是护身符｜PyYAML ScannerError
        门原文：… 第 10 行 `- name: Run suite (single runner: pytest)` …
[RED] 期望[RED] ✓ E 非法：尾冒号邻形（Minor 5）
        尾冒号 = 嵌套映射 opener，同样 ScannerError｜PyYAML ScannerError
        门原文：… 第 10 行 `- name: Note:` …
[RED] 期望[RED] ✓ F 非法：尾冒号 + 行尾注释
        剥完注释仍以 `:` 结尾｜PyYAML ScannerError
        门原文：… 第 10 行 `- name: Note:` …
[GREEN] 期望[GREEN] ✓ G 合法：尾冒号但整体加引号
        引号内的冒号是值的一部分｜PyYAML 合法
[GREEN] 期望[GREEN] ✓ H 合法：` : ` 只出现在 run: | 正文里
        块标量正文整段跳过（不是结构行）｜PyYAML 合法
[GREEN] 期望[GREEN] ✓ I 合法：冒号不跟空格（镜像 tag / 端口）
        `qdrant/qdrant:v1.19.1` 与 `- 6333:6333` 都无歧义｜PyYAML 合法
[RED] 期望[RED] ✓ J 地板：整份文件一枚 `- name:` 都没有
        卡 I (2) 同族 fail-closed：门哑了当场红｜PyYAML 合法
        门原文：workflow 里一枚 `- name:` 结构行都没扫到（结构行共 3 枚）：这不能读成『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）
[RED] 期望[RED] ✓ K 地板：空文件
        同上，红在『门哑了』而不是『CI 干净』｜PyYAML 合法
        门原文：workflow 里一枚 `- name:` 结构行都没扫到（结构行共 0 枚）：…
[GREEN] 期望[GREEN] ✓ L 真 ci.yml（本轮改造后的树面）
        不假红是本枚的硬要求｜PyYAML 合法

结论：12 发，与期望不符 0 发
清理：C:\Users\zhang\AppData\Local\Temp\b0_t3f2_battery_ri3pd6ux 已删除 = True
```

D 与 E/F 是这轮特意加的两发**反证的反证**：剥注释只能把合法放行、不许把非法洗绿；
J/K 两枚地板证明"改顺序"没把 fail-closed 那一半弄哑。
**回归**：修复轮 1 的反证台 `tmp/b0_t3f1_falsify.py` 原样复跑（日志
`tmp/b0_t3f1_falsify-rerun-t3f2.txt`），五发结论一字未变（计划原稿那枚未加引号的步名仍 RED 并
点名行号、双引号/单引号/无冒号仍 GREEN、`run: |` 正文里的 `: ` 仍 GREEN 而同一冒号写在结构行上
仍 RED、地板仍 RED、真文件 × 7 枚 ci.yml 门全 GREEN）。

### 三、I-1 + Minor 4：块 A 的改写（字面 before/after）

旧块六行里坐着两枚缺陷：第 20-22 行用**现在时**宣称"依赖刻意取最小集、与 `backend-integration`
同源"（Task 3 之后为假；同一枚 job 里终态第 30 行的新步名 `Install backend dependencies
(same source as requirements.txt)` 与终态第 36 行的 `-r backend/requirements.txt` 就是它的反证——**过期那枚正坐在删掉该反模式的那一步上面一行**，下一个人读它就会往 YAML 里
加包名，红门 9、复刻 `f6c67b5`）；第 17 行"下面那枚既有步"的指涉对象已被本任务删除，句子悬空，
还和块 B 的"原步已删除"那句重复（改写时在第 47-48 行，本轮终态第 54-55 行）。

```text
改前（原 17-22 行）
'      # SECA-20（SEC-A 验收矩阵第 20 行）的执行位置。两步都必须在下面那枚既有步之前：'
'      # GitHub 的步骤一旦失败，同一 job 后续步骤不再执行——放在 `unittest discover` 之后'
'      # 等于这道门永远不跑（终审实测该既有步在 main HEAD 上就是红的，且早于 SEC-A）。'
'      # 依赖刻意取"能 import `app.*` 的最小集"，与 backend-integration 那套轻量安装同源'
'      # （conftest 会话夹具会 module-level import `sec_a_seed` → `app.llm.*` → httpx；'
'      # 只装 pydantic+argon2 的第一版在 CI 收集阶段就 ModuleNotFoundError: httpx，本地却绿）。'

改后（现 17-24 行）
'      # SECA-20（SEC-A 验收矩阵第 20 行）的执行位置：这一步必须排在主门之前——GitHub 的步骤'
'      # 一旦失败，同一 job 后续步骤不再执行 ⇒ 排在主门之后，它在主门红的那次运行里永远轮不到。'
'      # 依赖现状：本 job 装**整份** backend/requirements.txt（下面那枚安装步就是唯一真源）；'
'      # backend-integration 仍是它自己那套手写轻量清单。两枚 job 跑法不同——这里用 pytest 收'
'      # 整个 backend/tests、经 conftest；那边只跑 scripts/*.py——依赖来源随之分家，别互相抄：'
'      # 往这里加包名会红在豁免表钉上（f6c67b5 那版正是手写清单，远端当场 ModuleNotFoundError: httpx）。'
'      # 历史（已作废，只当事故记录读）：B0 之前本 job 刻意取"能 import `app.*` 的最小集"、与'
'      # backend-integration 同源；只装 pydantic+argon2 的第一版在 CI 收集阶段就红、本地却绿。'
```

三段口径现在各自对得上事实：位置（现在时，宾语换成**仍存在的主门**，悬空指涉消失）、
依赖现状（本 job 整份 `requirements.txt`、`backend-integration` 保持手写清单，两枚来源不同且
说明了**为什么**不同：pytest 全目录经 conftest vs 只跑 `scripts/*.py`）、
历史（第 23-24 行明确标"已作废，只当事故记录读"，httpx 那趟往返留在里面而不是装作现行规则）。
脚本自检的字面读数：

```text
改后字节：CRLF 141 bareLF 0 bytes 6367
自检：悬空指涉已消、过期现在时声明已消；块内 'unittest' 字面出现次数 = 1 （块 A 不再供这枚 token，交门 7 实验判定）
（说清楚口径：脚本那枚计数跑在**整份文件**上，值为 1 = 块 B 的"原既有步"那句；块 A 自己
已不含这枚 token，这一点由下面§四的 E7/E10 两发从门的判据侧独立证实）
```

最后那半句是**给§四用的前置事实**：改写顺手把旧 runner 的字面名字从块 A 拿掉了（它只在块 B 的
"原既有步已删除"那一句里出现），所以门 7 的文字半边从此只系在一处。这不是为了操控门而做的选择
——块 A 谈的是"扫描步为什么要在主门之前"，旧 runner 的历史归块 B 那枚"已删除"说明管，重复一次
反而是 Minor 4 点名的毛病；但它**确实**改变了实验结果，所以§四把两件事都跑了一遍并逐条记下。

### 四、I-2：先实验、再按实验写注释

旧抬头（原第 42 行）断言"删掉任何一条（顺序理由）都会让 `test_step_ordering_still_explains_itself` 红"。
评审证伪的那条根因（deferred minor ⑦ 被 brief 原样搬进 CI 文件）本轮**用实验重测**：
`tmp/b0_t3f2_i2_experiment.py` 把 ci.yml 的**副本**（整块删注释 / 只删一行 / 组合删 / 只挪 step）
写到 `%TEMP%`（仓库外），只把门模块的 `CI_FILE` 指过去，调用**真门函数**。块与行按**内容**定位，
所以改写前后各跑一次、同一台子复跑不串位。

**实验表（终态：块 A 已改写 + 块 B 已按实测重写之后，日志 `tmp/b0_t3f2_i2-experiment.txt`）**：

| # | 这一发做了什么 | 门 7 `test_step_ordering_still_explains_itself` | 其余 6 枚 ci.yml 门 |
| --- | --- | --- | --- |
| E0 | 真 ci.yml 原样（终态基线） | **GREEN** | 全绿 |
| E1 | 删整块 A（8 行：SECA-20 位置 + 依赖现状 + 历史） | **GREEN** | 全绿 |
| E2 | 删安装步内部注释（§5.1 同源 + torch 发行源，3 行） | **GREEN** | 全绿 |
| E3 | 删整块 B（主门前 12 行注释） | **RED**（"解释扫描步为何排在主门之前的注释被删了"） | 全绿 |
| E4 | 只删块 B 的抬头/分界那 8 行（(1)(2) 与原步两句留下） | **GREEN** | 全绿 |
| E5 | **只删理由 (1) 那行** | **GREEN** ← 旧抬头的断言在这一发上为**假** | 全绿 |
| E6 | **只删理由 (2) 那行** | **GREEN** ← 同上，为**假** | 全绿 |
| E7 | 只删"原既有步 … 已删除"那两行 | **RED** ← 这一句才是文字半边唯一的系点 | 全绿 |
| E8 | 删块 A **并且**删理由 (1)（注释里两处编号全摘） | **GREEN** ← 扫描步的**步名**自己带着那枚编号 | 全绿 |
| E9 | (1)(2) 同时删 | **GREEN** | 全绿 |
| E10 | 块 A + 原步两句一起删（两枚 token 的注释供给点全摘） | **RED** | 全绿 |
| E11 | **对照弹**：注释一字不动，把扫描步挪到主门之后 | **RED**（"step 顺序被改动…要求严格递增：扫描 < 主门 < compose < pwsh"） | 全绿 |

词元落点（解释 E5-E10 为什么这样红/绿）：

```text
  `SECA-20` 在 ci.yml 第 [17, 38, 52] 行；job 块内命中 = True
  `unittest` 在 ci.yml 第 [54] 行；job 块内命中 = True
```

⇒ 机器真正钉住的是两件事：**(a) step 相对顺序严格递增**（E11 红，注释一个字没动），
**(b) `SECA-20` 与 `unittest` 两个 token 还在 job 块里**。而 (b) 里 `SECA-20` 由第 38 行那枚扫描步
的**步名**自己供着（E8 证明删不掉），`unittest` 只由"原既有步已删除"那一句供着（E7/E10 才红）。
两条顺序理由 (1)(2) 各自单独删**都不红**（E5/E6）⇒ 那两句是给人读的，由人审与规格担保。

**按这份实验重写的块 B 抬头**（原 1 行 → 现 8 行；(1)(2) 与"原既有步已删除"两句按规格逐字未动）：

```text
改前（原第 42 行，1 行）
'      # B0 §5.2 两条顺序理由，删掉任何一条都会让 test_step_ordering_still_explains_itself 红：'

改后（现 44-51 行，8 行）
'      # B0 §5.2 的两条顺序理由在下面 (1)(2)。旧抬头那句『删掉任何一条都会让门红』经修复轮 2'
'      # 实测证伪、已按实测重写（逐块删注释跑 test_step_ordering_still_explains_itself，'
'      # 实验表在 task-3-report.md《Task 3 修复轮 2》）。机器的与人审的分界是：'
'      #   机器钉：step 相对顺序严格递增（扫描 < 主门 < compose < pwsh）——把扫描步挪到主门'
'      #   之后当场红；文字半边只 grep 两枚 token 还在不在 job 块里：扫描步的编号由那枚 step'
'      #   的**名字**自己供着（删注释删不掉它），旧 runner 的名字仅系在下面“原既有步已删除”'
'      #   那一句上 ⇒ 删那一句才红，删 (1) 或删 (2) 任何一条门都照绿。'
'      #   所以这两条理由的取舍与措辞由**人审**担保（规格要求它们逐字留在树上），别以为门拦得住。'
```

新块**刻意不复述那两枚 token 的字面**（写的是"扫描步的编号""旧 runner 的名字"）：一旦本块自己
把 `SECA-20` / `unittest` 拼出来，E7 那一发就会翻成 GREEN，"删那一句才红"立刻被我这行注释弄成
假话。这是**改完之后重跑实验**才发现的自指陷阱，不是先验的讲究——所以脚本里带了自检：

```text
自检：新块是否自带两枚 token（必须都为 0，否则本块的声明会被自己弄假）
  新块内含 `SECA-20` = False
  新块内含 `unittest` = False
自检：(1)(2) 与原步两句仍逐字在树上 = True True
```

改写后台子原地重跑（E0-E11 全部与上表一致），所以注释里那句分界**是**实验读数，不是希望。

### 五、Minor 6：cache key 补判别位

```text
第 29 行（1-based）改后："          key: b0-${{ runner.os }}-py3.12-cpu-torch-${{ hashFiles('backend/requirements.txt') }}"
改后字节：CRLF 141 bareLF 0 bytes 6377
```

缺 `cpu-torch` 时，"torch 换发行源 / 换 CPU 版本"这类改动只要 `requirements.txt` 哈希不动就会
命中旧缓存，装出与 YAML 不一致的环境。`py3.12` 仍是字面量（R10 已登记为已知耦合）：GitHub 没有
内建 python 版本变量，而它就写在上一行 `python-version: '3.12'` 旁边；不为此造第二份真相。

### 六、终态读数（全部字面粘贴）

**门册**（`python -m pytest backend/tests/test_ci_gate_contract.py -q`；`-v` 全量日志
`tmp/gate-module-t3f2-final.txt`）：

```text
======================== 1 failed, 15 passed in 29.37s ========================
```

`-v` 逐枚（唯一红仍是 `.gitattributes`，Task 4 的活；本轮改过的门 16 与门 7 都在绿的那一侧）：

```text
test_collected_count_matches_the_pinned_number PASSED [  6%]
test_the_gate_module_itself_is_collected PASSED [ 12%]
test_the_gate_module_itself_carries_no_skip_or_xfail_decorator PASSED [ 18%]
test_collection_measurement_counts_node_ids_not_the_summary_line PASSED [ 25%]
test_backend_contracts_has_no_unittest_discover_step PASSED [ 31%]
test_backend_contracts_runs_the_pytest_suite PASSED [ 37%]
test_step_ordering_still_explains_itself PASSED [ 43%]
test_install_face_uses_requirements_txt_as_the_source PASSED [ 50%]
test_extra_pip_arguments_are_exactly_the_exemption_table PASSED [ 56%]
test_install_face_pip_source_values_are_pinned PASSED [ 62%]
test_every_exemption_row_states_why PASSED [ 68%]
test_workflow_plain_scalars_bearing_a_colon_space_are_quoted PASSED [ 75%]
test_gitattributes_carries_the_required_rules FAILED [ 81%]
test_index_has_no_crlf_entries PASSED [ 87%]
test_non_text_index_entries_are_exactly_the_enumerated_set PASSED [ 93%]
test_eol_rules_are_a_no_op_for_the_current_tree PASSED [100%]
```

**全量两把**（脚本 `tmp/t3f2_full_suite.sh`；无 `.env` 那一把把 `backend/.env` 用 `mktemp -d`
**挪出仓库**、树内零副本，R6）：

```text
原地（tmp/full-suite-t3f2-inplace.txt）：
1 failed, 1331 passed, 36 warnings, 1133 subtests passed in 169.40s (0:02:49)
无 .env（tmp/full-suite-t3f2-noenv.txt）：
1 failed, 1331 passed, 36 warnings, 1133 subtests passed in 173.76s (0:02:53)
两把的 FAILED 逐名都只有：
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules

挪出后的核验（tmp/noenv-tree-check.txt，该子进程按控制台默认 cp936 写日志，解码后原文）：
树内 backend/.env 存在 = False
恢复核验（tmp/env-sha-after-t3f2.txt）：
.env 恢复后 sha256 前 12 位 = 4d7f974107dd 字节 1561
```

`1331 + 1 = 1332 = EXPECTED_COLLECTED` ⇒ 主门命令在"无 `.env`、cwd=仓库根"的 CI 形态下把 1332 枚
**全部实际执行**（本轮没动收集面，两把与修复轮 1 的 `1331 passed / 1 failed` 同值）。

**SEC-A 密钥卫生整模块**（`ci.yml` 与本轮新写的注释都在它的扫描面上，`tmp/secA-t3f2.txt`）：

```text
46 passed in 25.21s
```

**未新增任何豁免行**，`test_secret_hygiene_contract.py` 本轮一字未动；本轮新增的脚本与日志全在
`.superpowers/`（`.gitignore:25` 实测 `git check-ignore` 命中）⇒ 不在
`git ls-files --cached --others --exclude-standard` 的扫描面上；**合成 workflow 副本一枚都不入树**
（三处临时目录都在 `%TEMP%`，各自打印"已删除 = True"）。

**其余三个 job 零改动 + 文件仍然打得开**（机器证明，不只是"diff 没显示"）：

```text
safe_load 当前树面：OK, top keys = ['name', True, 'jobs']
safe_load HEAD：OK
  backend-integration: 与 HEAD 深比较 IDENTICAL
  backend-quality: 与 HEAD 深比较 IDENTICAL
  frontend-build: 与 HEAD 深比较 IDENTICAL
SECA-20 扫描步四行与 HEAD 逐字节相同 = True
当前形态：
    '      - name: Run SECA-20 delivery-surface secret scan'
    '        run: >-'
    '          python -m pytest backend/tests/test_secret_hygiene_contract.py -q'
    '          -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"'
```

`backend-contracts` 的 step 序列（10 枚，`yaml.safe_load` 语义序、按 step 名不按行号；
`(无名 uses)`/`(无名 run)` 是脚本对无 `name:` 键的 step 的打印，四枚裸动作 = checkout、
setup-python、compileall、validate_demo_assets）：

```text
   - (无名 uses)
   - (无名 uses)
   - Cache pip wheels
   - Install backend dependencies (same source as requirements.txt)
   - Run SECA-20 delivery-surface secret scan
   - (无名 run)
   - (无名 run)
   - Run backend contract suite (single runner: pytest)
   - Validate Docker Compose configuration
   - Validate Windows deployment script syntax
```

### 七、字节形状与 diff 形态（行尾是本轮的高危项）

```text
=== numstat（本轮唯一改动面）===
35      21      .github/workflows/ci.yml
=== 全仓 numstat（另两枚是开工前就在的 identity 既有改动，不是本轮的）===
warning: in the working copy of 'backend/app/identity/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/identity/__init__.py', LF will be replaced by CRLF the next time Git touches it
35      21      .github/workflows/ci.yml
8       5       backend/app/identity/README.md
10      3       backend/app/identity/__init__.py
=== 两枚 hunk 的落点 ===
HEAD：backend-contracts 第 10–51 行（全文 134 行）
hunk：旧 17-36 → 新 17-37   全在 backend-contracts 内 = True
hunk：旧 43-43 → 新 44-57   全在 backend-contracts 内 = True
结论： 两枚 hunk 都在 backend-contracts 内（其余三个 job 零改动）

ci.yml bytes 7206 CRLF 148 bareLF 0 sha256-12 4dd5f48c44ca
HEAD: CRLF 0 bareLF 134        ← index 侧全 LF；Task 4 落 * text=auto 时别把这 148 枚 CRLF 提交进 index
```

计数演进（每一步 bareLF 都是 0）：`134`（HEAD/index 形态是 134 枚裸 LF）→ `139`（Task 3 原始轮）
→ `141`（块 A 6→8 行）→ `141`（cache key 同行改写，行数不变）→ `148`（块 B 抬头 1→8 行）。
三枚写入脚本都带同一枚地板断言：`read_bytes` 后先 `assert count(LF)==count(CRLF)`，
`join` 之后再 `assert out.count("\n")==out.count("\r\n")` 才肯 `write_bytes`——
"工具把文件写成 LF ⇒ `git diff` 整份翻转"这条路从源头堵着，本轮 diff 只有 2 枚 hunk、35/21 行。

门文件本轮的字节形状与约束（**没有**被编辑器顺手翻成 CRLF）：

```text
门文件字节 40751 LF 721 CRLF 0 bareLF 721 sha256-12 c337e5363e5c
EXPECTED_COLLECTED = 1332
import 行： ['from __future__ import annotations', 'import functools', 'import os', 'import re',
             'import subprocess', 'import sys', 'from pathlib import Path']
有无 yaml / app. 进口 = False False
def test_ = 16 | 钉住 = 16 | 逐名同序 = True
```

`git status --porcelain`（终态，`tmp/status-after-t3f2.txt`，与开工前 7 行逐行相同）：

```text
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

### 八、刻意没做的事（越界清单）

* **不引 YAML 解析器**、不 import PyYAML（标准库没有、`requirements.txt` 不许动、门只许标准库；
  PyYAML 只在临时脚本里当"这形到底合不合法"的独立证人）。
* **不做** tab / 缩进 / 引号配对三件套（R10 判为 YAGNI）。
* 不加门、不削/删任何既有断言、不动 `EXPECTED_COLLECTED`（仍 1332）、不动豁免表、
  不碰 `test_secret_hygiene_contract.py`。
* 不碰 `backend-integration` / `backend-quality` / `frontend-build`；不碰 SECA-20 扫描步的 `-k` 表达式。
* **不建** `.gitattributes`（Task 4 的活；它那枚红是正确终态）；不归一化 `ci.yml` 行尾；
  不"顺手清理"缩进、空行或注释风格。
* 零 git 写命令（只用了 `diff` / `status` / `show` / `cat-file` / `check-ignore` / `rev-parse`），
  HEAD 仍 `7cc5efc`、提交数仍 0。
* 没把 `py3.12` 变量化（GitHub 无内建 python 版本变量，R10 已登记为已知耦合，不造第二份真相）。

### 九、快照与产物

* `snap-task3-fix2-post/ci.yml`、`snap-task3-fix2-post/test_ci_gate_contract.py`（与源文件 `cmp` 逐字节相同）
* 复现台 / 反证台 / 实验台：`tmp/b0_t3f2_i3_repro.py`、`tmp/b0_t3f2_falsify_gate16.py`
  （日志 `tmp/b0_t3f2_falsify-gate16.txt`）、`tmp/b0_t3f2_i2_experiment.py`
  （日志 `tmp/b0_t3f2_i2-experiment.txt`）、修复轮 1 反证台的复跑日志
  `tmp/b0_t3f1_falsify-rerun-t3f2.txt`
* 写入脚本：`tmp/task3f2_edit_ci_blockA.py` / `tmp/task3f2_edit_ci_cachekey.py` / `tmp/task3f2_edit_ci_blockB.py`
* 终态日志：`tmp/gate-module-t3f2-final.txt`、`tmp/secA-t3f2.txt`、`tmp/full-suite-t3f2-inplace.txt`、
  `tmp/full-suite-t3f2-noenv.txt`、`tmp/status-after-t3f2.txt`、`tmp/env-sha-after-t3f2.txt`

### 收工自检（把上文"我说是"变成机器说的）

| 声称 | 机器证据 |
| --- | --- |
| 门 16 不再假红合法写法 | `b0_t3f2_falsify_gate16.py` 的 A/B/G/H/I/L 六发 GREEN（L=真 ci.yml） |
| 门 16 没被"修绿"修哑 | 同台 C/D/E/F 四发 RED 且点名行号；J/K 地板 RED；12 发 0 偏差 |
| 修复轮 1 划下的界线没被本轮弄坏 | `b0_t3f1_falsify.py` 原样复跑，五段结论一字未变（含"同一份非法 YAML 喂给其余 6 枚 ci.yml 门全绿"） |
| 块 A 的现在时都是真的 | §三 before/after 全文 + 脚本自检"悬空指涉已消、过期现在时声明已消" + 其余三枚 job IDENTICAL |
| 块 B 那句分界=实验而非希望 | §四 E0-E11：E5/E6 GREEN 直接反证旧抬头；E7/E10/E11 RED 定住三条系点；改后原地复跑逐发红绿读数与改前一致 |
| 没加门、没凑常数 | 门册 16 枚逐名点名、`EXPECTED_COLLECTED=1332` 未动、全量 `1331 passed + 1 failed = 1332` |
| 行尾没被污染 | 每一步 bareLF=0；`CRLF 139→141→148`；门文件 `CRLF 0`；两枚 hunk 全在 `backend-contracts` |
| 其余三个 job 零改动 | `yaml.safe_load` 深比较三枚 IDENTICAL + SECA-20 四行与 HEAD 逐字节相同 |
| 合成文件一枚不入树 | `git status --porcelain` 终态 7 行 = 开工前；三处临时目录 `已删除 = True` |
| 零提交 | HEAD 仍 `7cc5efc`；本轮只跑读类 git 命令 |

**交回控制器的两句话**：① I-2 的诚实版本已写进注释——顺序半边机器钉、两条理由的取舍人审担保，
实验表在上面；② 本轮顺手让块 A 不再复述旧 runner 的字面名（Minor 4 要求的"折叠悬空句"就是这个
折叠），这**改变**了门 7 文字半边的供给点分布（原来两处、现在一处），所以注释里的"删那一句才红"
只有在块 A 保持不复述的前提下成立——这一点已写进注释本身，下一位改注释时看得见。

### 十、本轮自己的事故留档（两条，都不影响终态字节）

1. **报告的一段被追加了两次**：`### 三/四/五`（块 A 与块 B 的 before/after + 实验表）先被单独
   append 过一次，之后又与 `### 六~九` 一起再 append 一遍 ⇒ 报告里出现两份 §三~§五。
   `tmp/report_t3f2_dedupe.py` 检出并删掉 5060 字节的重复段（保留**改过行号口径**的那一份）。
2. **引文不是字面**：块 B"改后"清单里 ci.yml 第 49 行用的是**全角引号** `“原既有步已删除”`，
   我第一遍写成半角 `"…"` ⇒ 号称"字面粘贴"的那一行其实对不上字节。同一枚脚本换回真实字节。

修完的自证（同一枚脚本的输出）：

```text
删掉重复段： 5060 字节（保留的是改过行号口径的那一份）
引文字符已换成 ci.yml 的真实字节（全角引号）
修后字节 75256 CRLF 0 bareLF 1165
小节序： 一、本轮动的与… / 二、I-3 + Mi… / 三、I-1 + Mi… / 四、I-2：先实… / 五、Minor 6：… /
          六、终态读数（全… / 七、字节形状与 … / 八、刻意没做的事… / 九、快照与产物 / 收工自检（把上文…
标题枚数 = 10 去重后 = 10
报告引用的注释行 = 23 | ci.yml 里找不到 = 7
```

那 7 枚"找不到"是**故意**的——它们是§三/§四的**改前**引文（旧块 A 六行 + 旧块 B 抬头一行），
本来就不该在终态文件里；16 枚"改后"引文逐行在 `ci.yml` 命中。
另外：%TEMP% 里留过一枚没删净的副本目录（写实验台的第一次运行在 `apply_edits` 类型判断上崩了，
`b0_t3f2_i2v2_1jsg_zzo`）+ 一枚我手工备份的开工前 ci.yml（`b0_t3f2_ci_before.yml`），
都在**仓库之外**、都不在扫描面上，收工前已 `rm -rf` 清干净（`ls | grep b0_t3f2` 空）。



## Task 3 修复轮 3

（2026-09-28，Task 3 的修复轮 3/5；工作树态、**零提交**、HEAD 仍 `7cc5efc`、全程未跑任何 git 写命令。
裁定来源 = 上一轮的**scoped re-review**（R10 修复轮 2 回执之后的再评审），两处改动都是评审已经量过、
本轮照单落地并复验，不是重新设计。）

### 一、本轮动的与不动的

| 项 | 位置 | 性质 |
| --- | --- | --- |
| Fix 1 | `backend/tests/test_ci_gate_contract.py` 门 16 `_unquoted_colon_bearing_scalars()` | 引号判定补成**两读并判**（`or _fully_quoted(value)`），修掉轮 2 留下的**镜像假红** |
| Fix 1 附带 | 同文件**四处**文字：模块头第 16 枚门那段、`_INLINE_COMMENT` 的 `#:` 注释、`_unquoted_colon_bearing_scalars()` 与门 16 的 docstring | 把"顺序就是判据"这句按新判据改写，并把两读各自的**代价**如实登记（含治不好的残留） |
| Fix 2 | `.github/workflows/ci.yml` 块 B 抬头（原 44-51 共 8 行 → 现 44-50 共 7 行） | 删死链路径指涉 + 删修复轮考古，只留"哪半边机器钉 / 哪半边人审 / 为什么人审省不掉"的持久陈述 |

**未动**（全部有机器证明，见§六）：`backend-integration` / `backend-quality` / `frontend-build`
（`yaml.safe_load` 深比较 IDENTICAL）、SECA-20 扫描步四行（按行内容与 HEAD 相同）、
`EXPECTED_COLLECTED`（实测仍 **1332**）、`_OWN_TEST_NAMES`（实测仍 **16 枚**）、块 A、cache key、
`test_secret_hygiene_contract.py` 与其豁免表、任何既有断言（一枚都没削、没删、没加）。
**没建** `.gitattributes`（Task 4 的活）⇒ 它那枚红仍是唯一红。**没造** `.gitattributes` 以外的东西。
本轮**不新增测试**（R10 明令不加门 ⇒ 门数与 `EXPECTED_COLLECTED` 无需回写）。

### 二、Fix 1：门 16 的引号判定补成两读并判

**缺陷**（评审实测）：轮 2 把判定挪到"只看剥完行内注释的值"，修好了 `- name: "…"  # 说明`，
但 `_INLINE_COMMENT` 是 **quote-blind** 的——`- name: "Run: everything #1"` 里引号内那枚 `#`
先把值劈成 `"Run: everything`，收尾引号随之消失，`_fully_quoted()` 认不出那对引号 ⇒ 一枚**完全合法**
的 YAML 被判红。轮 2 的假红与它的镜像假红同族同价：本仓库的失效史就是"假红 → 有人加豁免 →
真形状跟着漏"。

**改前 / 改后（判据本体，逐字节）**

```python
# 改前（轮 2 定稿）
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
        if _FLOW_STYLE_VALUE.match(body):
            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
        if _fully_quoted(body):
            continue                           # 整体被同一对引号包住 ⇒ 冒号是值的一部分
        if ": " in body or body.endswith(":"):
            offenders.append((lineno, ("- " if dashed else "") + key, body))

# 改后（轮 3 定稿）—— 只多一枚 `or`，其余一字未动
        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
        if _FLOW_STYLE_VALUE.match(body):
            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
        if _fully_quoted(value) or _fully_quoted(body):
            continue                           # 任一读法整体被同一对引号包住 ⇒ 冒号是值的一部分
        if ": " in body or body.endswith(":"):
            offenders.append((lineno, ("- " if dashed else "") + key, body))
```

**谓词台（`tmp/b0_t3f3_predicate_table.py`）**——同一发同时算"改前判据 / 改后判据 / 宿主 PyYAML
语义"三列（脚本按两条规则各自跑真判据，所以一次读数就是 before/after 对照）：

```text
形状                                                   value(原文)              body(剥后)               改前       改后       PyYAML
- name: "Run: everything #1"                         '"Run: everything #1"' '"Run: everything'     RED      GREEN    合法
- name: "Run suite (single runner: pytest)"  # kee   '"Run suite (single ru '"Run suite (single ru GREEN    GREEN    合法
- name: "Note:"                                      '"Note:"'              '"Note:"'              GREEN    GREEN    合法
- name: Note:                                        'Note:'                'Note:'                RED      RED      ScannerError
- name: Note:  # note                                'Note:  # note'        'Note:'                RED      RED      ScannerError
- name: "Run: a" baz                                 '"Run: a" baz'         '"Run: a" baz'         RED      RED      ParserError
- name: qdrant/qdrant:v1.19.1                        'qdrant/qdrant:v1.19.1 'qdrant/qdrant:v1.19.1 GREEN    GREEN    合法
- name: 'Run: everything #1'                         "'Run: everything #1'" "'Run: everything"     RED      GREEN    合法
- name: "Run: everything #1"  # keep                 '"Run: everything #1"  '"Run: everything'     RED      RED      合法
- name: "a: b" and "c"                               '"a: b" and "c"'       '"a: b" and "c"'       GREEN    GREEN    ParserError
- name: "a: b #c" d"                                 '"a: b #c" d"'         '"a: b'                RED      GREEN    ParserError
- name: Run suite (single runner: pytest)  # note    'Run suite (single run 'Run suite (single run RED      RED      ScannerError
```

改前 → 改后翻绿的只有两发，都是**宿主 PyYAML 判合法**的那一族（双引号 + 单引号镜像），
四发"必须仍红"的形状一行读数没变。

**反证台**（`tmp/b0_t3f3_gate16_battery.py`：合成 workflow 写成**真文件**落在仓库之外，
把门的 `CI_FILE` 指过去、调用**真门函数**，每发再让宿主 PyYAML 独立复验）。
16 发 = 评审点名的 9 类形状 + 我补的 4 发（H 单引号镜像、I 残留、J 反证的反证、O 既有边界）
+ 上两轮台子里沿用的 G2/L/M。

改**前**跑（同一台子的 15 发版：归档件 `tmp/b0_t3f3_battery-before.txt`，**整段原样粘贴、一字未删**；比改后那台少
O 那一发，故 15 发）。跑的是**当时树面上真实的门模块**，没有任何副本技巧：

```text
合成文件目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f3\syn_before
目录在仓库之外 = True
[RED] 期望[GREEN] ✗ 与期望不符 A 修复目标：完全加引号、引号内含 `#`（PyYAML 合法）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: "Run: everything` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：不一致
[GREEN] 期望[GREEN] ✓ B 上一轮修的形状：加引号 + 行内注释（不得回退）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致
[GREEN] 期望[GREEN] ✓ C 尾冒号但整体加引号
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致
[RED] 期望[RED] ✓ D 尾冒号 plain（Minor 5）
        PyYAML ScannerError: mapping values are not allowed here   in "<unicode string>",｜语义期望[RED] 实际[RED]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: Note:` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：一致
[RED] 期望[RED] ✓ E 尾冒号 plain + 行内注释
        PyYAML ScannerError: mapping values are not allowed here   in "<unicode string>",｜语义期望[RED] 实际[RED]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: Note:` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：一致
[RED] 期望[RED] ✓ F 部分加引号（引号外还有散文）
        PyYAML ParserError: while parsing a block mapping   in "<unicode string>", line ｜语义期望[RED] 实际[RED]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: "Run: a" baz` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：一致
[GREEN] 期望[GREEN] ✓ G 冒号不跟空格（镜像 tag / 端口序列项）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致
[RED] 期望[GREEN] ✗ 与期望不符 H 单引号 + 引号内含 `#`（同一族，只是引号种类不同）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: 'Run: everything` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：不一致
[RED] 期望[RED] ✓ I 引号内含 `#` 且后面还挂真注释（旧新两版都红，见报告）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: "Run: everything` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：不一致
[RED] 期望[RED] ✓ J 未加引号含 `: ` + 行内注释（剥注释不许洗绿）
        PyYAML ScannerError: mapping values are not allowed here   in "<unicode string>",｜语义期望[RED] 实际[RED]
        门原文：1 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`：第 12 行 `- name: Run suite (single runner: pytest)` 修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），不是把带冒号的那半句删掉
        门 vs 语义：一致
[GREEN] 期望[GREEN] ✓ K 正常未加引号步名（无冒号）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致
[GREEN] 期望[GREEN] ✓ G2 冒号不跟空格写在 services 里（ci.yml 真实形状）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致
[RED] 期望[RED] ✓ L 地板：整份文件一枚 `- name:` 都没有
        PyYAML 合法｜语义期望[FLOOR] 实际[GREEN]
        门原文：workflow 里一枚 `- name:` 结构行都没扫到（结构行共 6 枚）：这不能读成『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）
        门 vs 语义：不一致  ← 门/语义偏差
[RED] 期望[RED] ✓ M 地板：空文件
        PyYAML 合法｜语义期望[FLOOR] 实际[GREEN]
        门原文：workflow 里一枚 `- name:` 结构行都没扫到（结构行共 0 枚）：这不能读成『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）
        门 vs 语义：不一致  ← 门/语义偏差
[GREEN] 期望[GREEN] ✓ N 真 ci.yml（树面）
        PyYAML 合法｜语义期望[GREEN] 实际[GREEN]
        门 vs 语义：一致

结论：15 发，与期望不符 2 发；语义（PyYAML）侧偏差 2 发
不符清单：A 修复目标：完全加引号、引号内含 `#`（PyYAML 合法） | H 单引号 + 引号内含 `#`（同一族，只是引号种类不同）
语义偏差清单：L 地板：整份文件一枚 `- name:` 都没有 | M 地板：空文件
清理：C:\Users\zhang\AppData\Local\Temp\b0_t3f3\syn_before 已删除 = True
```

⇒ **假红复现成立**，用的是 Fix 1 落地**之前**的仓库真门文件（那一跑在 05:01，`or` 还没写进去），
不是事后复原：评审报的 A 当场 RED，顺带量出同族还有单引号那一发（H 也 RED、宿主 PyYAML 判合法）。
两发的门原文都被劈成 `- name: "Run: everything` / `- name: 'Run: everything` ——
引号里的 `#` 先被 `_INLINE_COMMENT` 当注释起点切掉，收尾引号随之消失，`_fully_quoted()` 认不出。
下面"改后跑"那台是加了 O 之后的 16 发版（多那一发只为把"既有边界不是本轮换来"这件事钉成读数），
两台的同名发读数逐条可比：15 发里 A/H 两发由 RED 翻 GREEN，**其余 13 发读数一字不变**
（改后台子只多了 O 那一发）。

改**后**跑（`tmp/b0_t3f3_battery-final.txt`，终态树面 + 终态门文件，字面）：

```text
合成文件目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f3\syn_final
目录在仓库之外 = True
[GREEN] 期望[GREEN] ✓ A 修复目标：完全加引号、引号内含 `#`（PyYAML 合法）
[GREEN] 期望[GREEN] ✓ B 上一轮修的形状：加引号 + 行内注释（不得回退）
[GREEN] 期望[GREEN] ✓ C 尾冒号但整体加引号
[RED] 期望[RED] ✓ D 尾冒号 plain（Minor 5）
[RED] 期望[RED] ✓ E 尾冒号 plain + 行内注释
[RED] 期望[RED] ✓ F 部分加引号（引号外还有散文）
[GREEN] 期望[GREEN] ✓ G 冒号不跟空格（镜像 tag / 端口序列项）
[GREEN] 期望[GREEN] ✓ H 单引号 + 引号内含 `#`（同一族，只是引号种类不同）
[RED] 期望[RED] ✓ I 引号内含 `#` 且后面还挂真注释（旧新两版都红，见报告）
[RED] 期望[RED] ✓ J 未加引号含 `: ` + 行内注释（剥注释不许洗绿）
[GREEN] 期望[GREEN] ✓ K 正常未加引号步名（无冒号）
[GREEN] 期望[GREEN] ✓ O 既有边界台：两截引号、首尾同字符（谓词台实测改前改后同 GREEN，非本轮换来）
[GREEN] 期望[GREEN] ✓ G2 冒号不跟空格写在 services 里（ci.yml 真实形状）
[RED] 期望[RED] ✓ L 地板：整份文件一枚 `- name:` 都没有
[RED] 期望[RED] ✓ M 地板：空文件
[GREEN] 期望[GREEN] ✓ N 真 ci.yml（树面）
结论：16 发，与期望不符 0 发；语义（PyYAML）侧偏差 2 发
语义偏差清单：L 地板：整份文件一枚 `- name:` 都没有 | M 地板：空文件
清理：C:\Users\zhang\AppData\Local\Temp\b0_t3f3\syn_final 已删除 = True
```

**逐形对照评审点名的清单**（全部 ✓，无一例外）：

| 评审点名的形状 | 要求 | 实测 | 判据 |
| --- | --- | --- | --- |
| `- name: "Run: everything #1"` | GREEN（本轮修的就是它） | **GREEN**（改前 RED） | A |
| `- name: "Run suite (single runner: pytest)"  # keep quoting` | GREEN（不得回退） | **GREEN** | B |
| `- name: "Note:"` | GREEN | **GREEN** | C |
| `- name: Note:` | RED | **RED**（点名第 12 行） | D |
| `- name: Note:  # note` | RED | **RED**（点名第 12 行） | E |
| `- name: "Run: a" baz`（部分引号） | RED | **RED**（PyYAML 同一形 ParserError） | F |
| `qdrant/qdrant:v1.19.1` | GREEN | **GREEN**（另加 services 真实写法一发 G2 也 GREEN） | G / G2 |
| 没有 `- name:` | 地板 RED | **RED**（"只能读成这枚门哑了"），空文件同 | L / M |
| 真 `ci.yml` | GREEN | **GREEN** | N |

L/M 两发"门 RED 而 PyYAML 合法"是**设计**（fail-closed：门哑了不能读成 CI 干净），不是偏差，
台子把它们单列成 `FLOOR` 期望；台子那行"语义偏差 2 发"就是这两枚，逐发点名可查。

**两读各自的代价（登记，不藏）**：

* `"a: b" and "c"`（引号外有散文、整串首尾同字符）GREEN —— 但 `_fully_quoted()` 比的是**首尾字符**
  而非引号配对，谓词台实测这形**改前改后同 GREEN**，是既有边界，不是本轮换来的。
* `"a: b #c" d"`（要引号内含 `#`、引号外还有散文、散文末尾再补一枚同类引号才踩得到）
  改前 RED → 改后 GREEN，是 `or` **新开**的那一窄面。登记为已知边界。
* `- name: "Run: everything #1"  # keep`（引号内含 `#` **且**后面还挂真注释）改前改后**同 RED**，
  宿主 PyYAML 判合法 ⇒ 这枚假红**本轮没治好**：quote-blind 的第一刀落在引号里面，两读都凑不出
  完整引号对。要消它只能真去解析 YAML（R9 ② 禁止、PyYAML 被依赖面禁），故登记而不是修。
  三条都写进了 `_unquoted_colon_bearing_scalars()` 的 docstring，门文件自己带着这份边界表。

**回归**：轮 2 的 12 发台子 `tmp/b0_t3f2_falsify_gate16.py` 原地复跑 ⇒
`结论：12 发，与期望不符 0 发`；轮 1 的 `tmp/b0_t3f1_falsify.py` 原地复跑 ⇒ 与轮 2 留档
（`tmp/b0_t3f1_falsify-rerun-t3f2.txt`）48 行逐行比，**只有 2 行不同、且都是同一处行号 56→55**
（Fix 2 把注释块缩了一行，门点名行号随之平移），五段结论一字未变。

### 三、Fix 2：块 B 抬头去死链、去考古

**两个缺陷**：(a) 旧块第 3 行把读者指去 `task-3-report.md《Task 3 修复轮 2》`，而那文件在
`.superpowers/` 下（`.gitignore:25` 实测命中）⇒ `ci.yml` 一旦提交，这枚指涉在 GitHub 上指向**不存在**
的东西；(b) 同一块在**交付物**里逐轮叙事（"旧抬头那句…经修复轮 2 实测证伪、已按实测重写"），
那份记录本来就在 SDD 账本里，写进 YAML 只是让下一个人多读八行考古。

```text
改前（现 44-51 行，8 行）
'      # B0 §5.2 的两条顺序理由在下面 (1)(2)。旧抬头那句『删掉任何一条都会让门红』经修复轮 2'
'      # 实测证伪、已按实测重写（逐块删注释跑 test_step_ordering_still_explains_itself，'
'      # 实验表在 task-3-report.md《Task 3 修复轮 2》）。机器的与人审的分界是：'
'      #   机器钉：step 相对顺序严格递增（扫描 < 主门 < compose < pwsh）——把扫描步挪到主门'
'      #   之后当场红；文字半边只 grep 两枚 token 还在不在 job 块里：扫描步的编号由那枚 step'
'      #   的**名字**自己供着（删注释删不掉它），旧 runner 的名字仅系在下面“原既有步已删除”'
'      #   那一句上 ⇒ 删那一句才红，删 (1) 或删 (2) 任何一条门都照绿。'
'      #   所以这两条理由的取舍与措辞由**人审**担保（规格要求它们逐字留在树上），别以为门拦得住。'

改后（现 44-50 行，7 行）
'      # B0 §5.2 的两条顺序理由在下面 (1)(2)。这枚契约分两半，别把两半混成一半：'
'      #   机器钉（test_step_ordering_still_explains_itself）的是 step 相对顺序严格递增'
'      #   （扫描 < 主门 < compose < pwsh）——把扫描步挪到主门之后当场红；文字那半边只 grep'
'      #   两枚 token 还在不在 job 块里。两枚 token 的供给点不对称，人审因此省不掉：扫描步'
'      #   那枚由 step 的**名字**自己供着（删注释删不掉它），旧 runner 那枚在 job 块里只出现'
'      #   一次、就系在下面“原既有步已删除”那一句上 ⇒ 删那一句才红，删 (1) 或删 (2) 门都照绿。'
'      #   所以 (1)(2) 的取舍与措辞由**人审**担保（规格要求它们逐字留在树上），别以为门拦得住。'
```

留下的每一句都是**持久且当前为真**的陈述：哪半边机器钉（顺序严格递增）、哪半边人审（(1)(2) 的取舍
与措辞）、以及让人审**成为必需**的那枚耦合（旧 runner 的 token 在 job 块里**只出现一次**，系在
"原既有步已删除"那一句上 ⇒ 删那一句才红）。删掉的只有死链与轮次叙事。
下面 (1)(2) 两句与"原既有步已删除"两句**逐字未动**（规格要求）。

**写入脚本自检**（`tmp/task3f3_edit_ci_blockB.py`，字节级 splice，`read_bytes` 后先断言
`LF==CRLF`、`join` 后再断言才肯 `write_bytes`；块按**内容**定位，字面读数）：

```text
改前字节：7206  CRLF 148  bareLF 0  行数 149
块落点（1-based）：44-51，共 8 行 → 新块 7 行
改后字节：7106  CRLF 147  bareLF 0
自检：新块内含 `SECA-20` = False ／ 内含 `unittest` = False
自检：job 块内 `SECA-20` 次数 = 3 ／ `unittest` 次数 = 1
自检：`unittest` 所在行 = ["# 原既有步 `python -m unittest discover -s backend/tests -p 'tes"]
自检：全文仍含 'task-3-report' = False
自检：全文仍含 '修复轮' = False
自检：全文仍含 '证伪' = False
自检：全文仍含 '实验表' = False
sha256-12 改前 4dd5f48c44ca → 改后 1c706e165b73
```

新块**刻意不复述**那两枚 token 的字面（写的是"扫描步""旧 runner 那枚"）：一旦本块自己把
`SECA-20` / `unittest` 拼出来，下面那发 E7 就会翻绿、"删那一句才红"立刻被这行注释弄成假话。
这是轮 2 发现的自指陷阱，本轮把它当作**写入约束**而不是考古内容。

**新块抬头那句话是读数不是愿望**（`tmp/b0_t3f3_i2_recheck.py`，ci.yml 副本落仓库外、
只把门的 `CI_FILE` 指过去、调用**真门函数**；字面）：

```text
副本目录（仓库外）：C:\Users\zhang\AppData\Local\Temp\b0_t3f3_e_z065as32  在树内 = False
词元落点（新抬头自带检查）
  新块 7 行内含 `unittest` = False ／ 内含 `SECA-20` = False
  `unittest` 在 ci.yml 全文出现的行 = [53]
  `SECA-20`  在 ci.yml 全文出现的行 = [17, 38, 51]
  job 块内 unittest 计数 = 1 ／ SECA-20 计数 = 3
读数（每条都是对**真门**的调用）
E0 树面原样                            门7 = GREEN ｜ 同时红的其余 ci.yml 门：无
E5 只删理由 (1) 那行                     门7 = GREEN ｜ 同时红的其余 ci.yml 门：无
E6 只删理由 (2) 那行                     门7 = GREEN ｜ 同时红的其余 ci.yml 门：无
E7 只删“原既有步已删除”两句                   门7 = RED   ｜ 同时红的其余 ci.yml 门：无
E12 删整块新抬头 7 行                     门7 = GREEN ｜ 同时红的其余 ci.yml 门：无
E13 删 (1)+(2) 两句                   门7 = GREEN ｜ 同时红的其余 ci.yml 门：无
E11 对照弹：扫描步挪到主门之后                  门7 = RED   ｜ 同时红的其余 ci.yml 门：无
清理：C:\Users\zhang\AppData\Local\Temp\b0_t3f3_e_z065as32 已删除 = True
```

⇒ 注释里三句断言逐句对上：**"删那一句才红"** = E7 是唯一红在文字半边的发；
**"删 (1) 或删 (2) 门都照绿"** = E5/E6/E13；**"扫描步那枚由 step 的名字自己供着（删注释删不掉它）"**
= E12/E13 仍 GREEN（`SECA-20` 在第 38 行那枚步名里）；**"机器钉顺序"** = E11。
本轮**没有**重跑轮 2 那张 12 发全表（E1-E4/E8-E10 的结论由这几发放言的同一枚耦合决定），
但新块里写的每一句都在上面这七发里被独立复验过。

**归档卫生（说清楚，别让下一个人在 tmp 里找不到东西）**：`tmp/b0_t3f3_*` 现有 11 份日志 + 5 枚脚本。
其中 `b0_t3f3_battery-before.txt` 是**从本节那段逐字粘贴还原出来的**——%TEMP% 工作目录在收工时被清掉了，
所以这枚文件是"报告引文的等长副本"，不是原始 stdout 文件本身（原文里那 61 行确实一字未删，
`head`/`tail` 都对得上，但把还原件说成原始件就是造假）。
另有一枚 `b0_t3f3_battery-before2.txt` 是**同一台 16 发台子**跑在"把 `or` 摘掉的树外门模块副本"上的
交叉复验（正文没引它，因为它与谓词台说的是同一件事，多贴一遍只是噪声）；留着是因为它是独立第二法源。

### 四、终态读数（全部字面粘贴）

**门册**（`python -m pytest backend/tests/test_ci_gate_contract.py -q`，33.45s；`-v` 见
`tmp/b0_t3f3_gate-module-final.txt`）：

```text
=========================== short test summary info ===========================
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
1 failed, 15 passed in 33.45s
```

`-v` 逐枚（`tmp/b0_t3f3_gate-module-verbose-final.txt`，35.49s，跑在终态字节上；唯一红仍是 `.gitattributes`，本轮**没建** ⇒ 正确终态）：

```text
test_collected_count_matches_the_pinned_number PASSED [  6%]
test_the_gate_module_itself_is_collected PASSED [ 12%]
test_the_gate_module_itself_carries_no_skip_or_xfail_decorator PASSED [ 18%]
test_collection_measurement_counts_node_ids_not_the_summary_line PASSED [ 25%]
test_backend_contracts_has_no_unittest_discover_step PASSED [ 31%]
test_backend_contracts_runs_the_pytest_suite PASSED [ 37%]
test_step_ordering_still_explains_itself PASSED [ 43%]
test_install_face_uses_requirements_txt_as_the_source PASSED [ 50%]
test_extra_pip_arguments_are_exactly_the_exemption_table PASSED [ 56%]
test_install_face_pip_source_values_are_pinned PASSED [ 62%]
test_every_exemption_row_states_why PASSED [ 68%]
test_workflow_plain_scalars_bearing_a_colon_space_are_quoted PASSED [ 75%]
test_gitattributes_carries_the_required_rules FAILED [ 81%]
test_index_has_no_crlf_entries PASSED [ 87%]
test_non_text_index_entries_are_exactly_the_enumerated_set PASSED [ 93%]
test_eol_rules_are_a_no_op_for_the_current_tree PASSED [100%]
======================== 1 failed, 15 passed in 35.49s ========================
```

16 枚逐名点名：门 16（本轮 Fix 1 改的，第 12 名）与门 7（本轮 Fix 2 涉及的，第 7 名）都在绿的
这一侧；唯一红仍是第 13 名 `.gitattributes`。

**常数实测**（把"没回写"变成机器读数，而不是我的断言）：

```text
EXPECTED_COLLECTED = 1332
len(_OWN_TEST_NAMES) = 16
```

**SEC-A 密钥卫生整模块**（`ci.yml` 的注释与本轮改过的门文件都在它的扫描面上；`tmp/b0_t3f3_secA-final.txt`，30.81s）：

```text
..............................................                           [100%]
46 passed in 30.81s
```

**未新增任何豁免行**，`test_secret_hygiene_contract.py` 一字未动。

**收工前在同一份终态字节上又各复跑一次**（`1 failed, 15 passed in 32.96s` ／ `46 passed in 30.23s`），
上面那些读数不是单次巧合。

**全量套件本轮没跑** —— 按任务给的许可跳过（≈170s），所以这里**不声称**它是绿的：
本轮改动面 = 门 16 内部判据 + 一枚 YAML 注释块，两者都落在门册 16 枚与 SEC-A 46 枚的覆盖面内，
且这两把本轮都实测过。**交下一轮或收工时补跑**。

### 五、字节形状与改动面（机器证明）

```text
.github/workflows/ci.yml                   bytes   7106  LF  147  CRLF  147  bareLF 0  sha12 1c706e165b73
backend/tests/test_ci_gate_contract.py     bytes  43268  LF  743  CRLF    0  bareLF 743  sha12 4c98f1439494
```

`ci.yml` 全程 CRLF、**改前改后 bareLF 都是 0**；门文件保持 **LF-only / 仅标准库 / 无 `app.*` /
无 `yaml` 进口**（imports 实测 `['__future__','functools','os','pathlib','re','subprocess','sys']`）。

`tmp/b0_t3f3_ci_shape_proof.py`（HEAD 用只读 `git show` 取、副本落仓库外；上一版按 `"\n"` 切行
比较被行尾差异污染、读数无效，已改成 `splitlines()` 后重跑）：

```text
行数：HEAD 134 ／ 树面 147
safe_load HEAD = OK ／ 树面 OK top keys = ['name', True, 'jobs']
  backend-integration: 与 HEAD 深比较 IDENTICAL
  backend-quality: 与 HEAD 深比较 IDENTICAL
  frontend-build: 与 HEAD 深比较 IDENTICAL
SECA-20 扫描步四行与 HEAD 相同（按行内容）= True
    '      - name: Run SECA-20 delivery-surface secret scan'
    '        run: >-'
    '          python -m pytest backend/tests/test_secret_hygiene_contract.py -q'
    '          -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"'
backend-contracts step 有序序列与 HEAD 相同 = False（各 9 / 10 枚）   ← Task 3 本来的改造，不是本轮
相对 snap-task3-fix2-post（上一轮终态）的改动：
  @@ -44,8 +44,7 @@
改动行数 = 15（8 删 7 加）
```

⇒ 本轮相对上一轮终态**只有一枚 hunk、只在块 B 抬头**，其余三枚 job 与 HEAD 深比较 IDENTICAL。
`git diff --numstat` 侧读数是 `34 21 .github/workflows/ci.yml`（相对 HEAD，含 Task 3 全部改造）。

**工作树与探针卫生**：

```text
$ git status --porcelain
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

七行与开工前**逐行相同**（identity 两枚是既有改动，sha 实测仍 `3bc681bbc52c` / `2cfab9f18182`，
本轮没碰）。本轮**五枚脚本**（`b0_t3f3_predicate_table.py`、`b0_t3f3_gate16_battery.py`、
`b0_t3f3_i2_recheck.py`、`b0_t3f3_ci_shape_proof.py`、`task3f3_edit_ci_blockB.py`）**执行时的工作目录
与全部合成 workflow 都在仓库之外**：`%TEMP%/b0_t3f3*`，`在树内 = False` 逐台打印，
跑完各自 `已删除 = True`。事后只把**脚本本体与日志**归档进
`.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/b0_t3f3_*`（11 份日志 + 5 枚脚本），那目录被
`.gitignore:25` 的 `.superpowers/` 覆盖 —— 实测 `git check-ignore -v` 命中该行、
`git status --porcelain` 仍是开工前那 7 行，**没有多出一枚文件**，所以不在
`git ls-files --cached --others --exclude-standard` 的 SEC-A 扫描面上。零 git 写命令，HEAD 仍 `7cc5efc`。

### 六、刻意没做的事

* 没引 YAML 解析器、没把 PyYAML 塞进任何清单（R9 ② / 依赖面禁）；门仍是"钉形状"。
* 没做 tab / 缩进 / 引号配对三件套（R10 判 YAGNI，本轮照旧）。
* 没为 `"a: b #c" d"` 与 `"…#1"  # 注释` 这两枚边界加特判或解析逻辑 —— 加特判就是把"假红 → 加豁免"
  那条路换个方向再走一遍；登记 + 写在门文件 docstring 里，而不是悄悄放宽。
* 没动块 A、cache key、(1)(2) 两句、"原既有步已删除"两句、SECA-20 扫描步、其余三枚 job。
* 没建 `.gitattributes`（Task 4 的活，它那枚红仍是对的）；没顺手归一化任何文件行尾。
* 没新增测试、没削任何断言。

### 七、快照与交 Task 4

快照 `snap-task3-fix3-post/{ci.yml,test_ci_gate_contract.py}`，两枚都与源文件 `cmp` 逐字节相同：

```text
快照 ci.yml 与源 cmp 逐字节相同 = True 7106
快照 test_ci_gate_contract.py 与源 cmp 逐字节相同 = True 43268
```

**交 Task 4 的数值更新（覆盖 R10 ③ 末尾那行）**：`ci.yml` 工作树现有 **147** 枚 CRLF
（改前 148，本轮块 B 抬头 8→7 行；index 侧仍是 134 枚裸 LF）。落 `* text=auto` 前后要按 147
重跑门 13/14/15 并复核 no-op 覆盖面。
