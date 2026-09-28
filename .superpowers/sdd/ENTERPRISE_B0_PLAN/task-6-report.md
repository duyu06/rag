# Task 6 报告：B0 变异台六发（B0-11「每枚门都必须被观测到红过一次」）

日期 2026-09-28。工作树态、**零提交**、**零 git 写命令**（只用 `git ls-files` / `git status` 读命令）、
HEAD 仍 `7cc5efc`。规格行 = `docs/ENTERPRISE_B0_SPECIFICATION.md` §6.1—§6.4 四族门 + §16 卡 K
那一格覆盖度地板；任务书 `.superpowers/sdd/ENTERPRISE_B0_PLAN/task-6-brief.md`（Step 1—4）。

**一句话结论**：六发 **6/6 KILLED**，四枚目标文件逐枚 `cmp` rc=0 + sha1 与注入前相同，
跟踪面聚合 sha `d30366c6a440`（313 枚）与剔掉两枚 identity 后的 `2685edde76fe`（311 枚）
**before/after 逐字符相等**，`git status --porcelain` 十个字节的行序一字未动 ⇒ **树上零残留**。
N6 那一格的答案是 **KILLED，但杀掉它的不是覆盖度钉本身**——覆盖度钉在 `0 == 0` 上确实放行了，
`i/crlf` 那枚消费门跟着变成空判绿，最后站在路上的是 `i/-text` 枚举集合钉（详 §3.6）。

---

## 1. 开工基线（改任何字节之前取的三件）

取证脚本 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/task6_tree_probe.py before`（配方逐字照
`task-4-brief.md` Step 1：`sha256 over sorted(path NUL bytes NUL)` 的跟踪件面，取前 12 位；
`tmp/task4_eol_probe.py:aggregate()` 同一实现）。

```
[before] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
```

四枚变异目标的字节锚（sha256[:12] / 字节数 / CR 字节数）——**三枚与台账登记值一字不差**，
这是"我改的确实是交付面上那一份"的锚：

| 目标 | sha256[:12] | 字节 | CR | LF | 台账出处 |
| --- | --- | --- | --- | --- | --- |
| `.github/workflows/ci.yml` | `1c706e165b73` | 7106 | **147** | 147 | R14/R15 四枚字节锚之一 |
| `.gitattributes` | `c5d07b5dc438` | 435 | **0** | 18 | R12 |
| `backend/tests/test_ci_gate_contract.py` | `73bede2def2e` | 48603 | 0 | 810 | R13 |
| `backend/tests/conftest.py` | `2ff38f8a68a1` | 56751 | 0 | 955 | 本轮首量（历史上无字节锚） |

**两枚 identity 的处置**：`backend/app/identity/README.md` `3bc681bbc52c`、
`__init__.py` `2cfab9f18182` 与 R12 登记的基线逐字符相等，本轮**一枚字节都没碰**（六发的目标里
没有它们）。它们**保留在**跟踪面聚合 sha 里——因为聚合是"前后同一批 313 枚"的自比，留着它们
反而更强：它们跟着一起证明"这轮没改动任何别的跟踪件"。同时另算一枚 **EX-ID**（311 枚、把它们
剔掉）口径，让"零残留"这条判据不被别人家的未提交改动稀释。**两个方向都不去"修"它们**。

`git status --porcelain` 基线 10 行（开工即此态、收工仍此态）：

```
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
 M backend/tests/test_password_lifecycle_contract.py
 M backend/tests/test_real_llm_failover_gate.py
?? .gitattributes
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

相对 R12 的七行基线，多出的两枚 `M`（`test_password_lifecycle_contract.py` /
`test_real_llm_failover_gate.py`）是 **Task 5 修复轮留下的既有改动**，不是本轮的（本轮对它们的
sha 也在 before/after 两次采样里逐字符相等）。

聚合基线值本身从 Task 4 的 `53bb297dbc72` 漂到了 `d30366c6a440`，原因同上（那两枚跟踪件被
Task 5 改过），**本轮的比较对象是本轮自己的 before**，不拿跨任务的常数说事。

---

## 2. 锚点歧义与消解（逐条，判据一字未改）

台子的规矩：anchor 必须**恰好命中一次**，0 次 `TARGET-NOT-FOUND`、>1 次 `ANCHOR-NOT-UNIQUE`，
两者都不动树。下面是落盘前实撞到的四处，全部按磁盘原文补上下文解决。

### 2.1 N1 的 `_GUARDED = False` 命中 2 次 ⇒ ANCHOR-NOT-UNIQUE

`backend/tests/conftest.py` 里 `_GUARDED = False` 有两枚：模块级 `:157`，和会话夹具 `finally`
里的 `:774`（缩进 8 空格，但 `"_GUARDED = False\n"` 是它的一枚**后缀**，`count` 照样加一）。
`replace(...,1)` 打哪一枚取决于行序 ⇒ 靠运气归因。补下一行原文钉死模块级那一枚：

```
needle = "_GUARDED = False\n_SESSION_GUARD: \"LedgerGuard | None\" = None\n"   → 命中 1
```

（`:774` 那枚的下一行是 `_CREDENTIAL_GUARD = None`，因此不构成第二次命中。）

### 2.2 三枚 ci.yml needle 用 `\n` 拼 ⇒ TARGET-NOT-FOUND（0 命中）

第一次探针我用文本模式读 ci.yml 拼 `\n`，结果 `- name: "Run backend contract suite …"` 那枚
needle **命中 0 次**——`Path.read_text()` 的 universal newlines 把 CRLF 折成 LF，看着"匹配"，
而字节面根本不匹配。实测 ci.yml 磁盘形态：**147 枚 CRLF、0 枚裸 LF**（`CR=147`，与台账
`gate-module` 的 LF-only 形态分家）。修法是把 needle 的换行显式写成 `\r\n`（台子里 `LC(...)`），
并把 needle 唯一性检查改成 `read_bytes().decode("utf-8")`（**不做** newline 翻译）。
判据、注入形状一个字都没改，改的是 needle 的字节形态——这正是任务书点明的"按磁盘字节形态写"。

### 2.3 N3 的 `-r backend/requirements.txt`：核对过它确实唯一

同文件里 `hashFiles('backend/requirements.txt')`（缓存 key，第 29 行）看着像第二枚，但它 `backend`
前面是引号、不是 `-r `，**不构成命中**；实测 `count == 1`。为免把替换体读成人手抄的半行，
needle 取整行 + CRLF（含 10 空格缩进），仍命中 1 次。

### 2.4 N6 的两枚锚：`_index_eol_rows()` 的两侧调用点

`    records = _index_eol_records()` 与 `    tracked = _tracked_paths()` 各命中 1 次。
第二枚核过同文件里另一个 `tracked = ` 起点（门 16
`test_eol_rules_are_a_no_op_for_the_current_tree` 里是 `tracked = subprocess.run([...])`），
形状不同串 ⇒ 不误伤。

### 2.5 为什么 N6 是**两枚**编辑而不是一枚（对计划文字的必要订正）

计划写"把 tracked 侧强制成空集合，令 `0 == 0` 通过覆盖度钉"。只收 `tracked` 一侧得到的是
`len(parsed)=313 == len(tracked)=0` ⇒ 覆盖度钉**当场响亮地红**，那压根不是 Task 4 评审登记的那一格。
评审登记的是"**缺非空地板**"：两侧同时收空才会 `0 == 0`、`missing`/`extra` 皆空、`rows={}`。
所以本发按两枚编辑表达同一形（台子支持一发多处编辑，与 SEC-A 的 M10/M16 同一手法），
判据与结论格一字未改。这一条属于"needle 与磁盘实况对齐"，不属于"改判据"。

**歧义总账**：`--check` 就是这张表（§5），六发 7 枚 needle 全部 `counts=[1]` / `[1, 1]`。

---

## 3. 六发红相逐行

定向节点：**整枚 `tests/test_ci_gate_contract.py`（16 枚全跑）**，而不是计划 Step 2 表里点名的
那枚函数。理由与 SEC-A 那条"不带 `-x`"同源：台的职责是回答"**哪几枚门**杀掉了这一发"，
单枚节点在一发杀两枚时会把第二枚漏掉（N3 正是这种）。代价每发约 20—34s（16 枚里有两枚要起
`--collect-only` 子进程），六发串行约 3 分钟，仍远够不到"全量套件"那一档。计划点名的判据节点
逐枚写在台子的 `MUTATIONS[i]["node"]` 与本报告的 §3 里；`mutation-bench.txt` 表格中"红掉的门"
那一列给的是**实测**红点——六发里有五发与计划点名的同名，N3 多出一枚（双杀），N6 少一枚
（计划点名的两枚消费门里 `i/crlf` 那枚恰是本轮要量的空判角落，见 §3.6）。没有任何一发做过
替代性放宽。

`gitattributes` 与门模块都是**未跟踪件**，所以本台的复原证明**一律不沾 git**（R13 登记的 D5
假绿：`git diff --exit-code` 对未跟踪文件恒返 0）：`finally` 写回读到的原字节 → sha1 与注入前
比对 → 再用外部 `cmp` 把"读到的原件"（写到 `%TEMP%`，不进仓库）与树上的现字节逐字节比一次。

### 3.1 N1 §6.1 收集数钉 —— **KILLED**

注入 `collect_ignore = ["test_web_security.py"]`（`_GUARDED = False` 之后一行）：不改名、不加
skip/xfail，就是"日常最容易发生的那种藏"。

```
1 failed, 15 passed in 20.02s          ← 存档件的这一次（正式一轮是 19.11s，见 §9 的注入次数说明）
FAILED tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
AssertionError: 收集数 1329 ≠ 钉住的 1332。
消失 3 枚：['backend/tests/test_web_security.py::WebSecurityTest::test_local_and_private_targets_rejected',
 '…test_public_https_allowed', '…test_userinfo_and_local_suffix_rejected']
```

红信息直接点出被藏的三枚 node id（失败路径读 `.superpowers/…/baseline/collected-node-ids.txt`
做差集，本地在场；CI 里那枚文件是 gitignored ⇒ 红照样红，只是少一份差集，这一点门文件里已钉）。
**自我存续那两枚钉（卡 H）没跟着红，是设计使然、不是漏判**：被藏的是别家模块，本门文件自己
仍贡献 16 枚，枚数与哑门装饰器两面都无感——这正是 §6.1 总数钉存在的理由。全文存档
`tmp/task6-red-N1.txt`。

### 3.2 N2 §6.2 单 runner 钉 —— **KILLED**

注的是一枚**真 step**（不是注释；门的所有命令匹配都先过 `_step_script()` 剥整行 `#` 注释，
树上本来就有一句"原既有步 unittest discover 已删除"的注释，那一句杀不掉这枚门——I-1 那颗地雷的
另一面）：

```
      - run: python -m unittest discover -s backend/tests -p 'test_*.py' -v
```

```
1 failed, 15 passed in 20.03s
RED test_backend_contracts_has_no_unittest_discover_step
```

顺带量到两枚**不该红而确实没红**的邻近钉：新 step 落在主门之前，`test_step_ordering_still_explains_itself`
的四枚锚点相对次序仍是严格递增（扫描 < 主门 < compose < pwsh）；`test_workflow_plain_scalars_…`
（门 16）也不红——那行的值里没有 `: `。

### 3.3 N3 §6.3 依赖同源钉 —— **KILLED（一发杀两枚）**

`-r backend/requirements.txt` → 手写六包清单（`"fastapi>=0.115,<1" "pydantic>=2.8,<3"
"python-multipart>=0.0.9" "qdrant-client>=1.12,<2" "httpx>=0.27,<1" "PyJWT>=2.9,<3"`，
即 f6c67b5 那一版的形状）。

```
2 failed, 14 passed in 33.82s
RED test_install_face_uses_requirements_txt_as_the_source
RED test_extra_pip_arguments_are_exactly_the_exemption_table
```

同源钉红在"引用真源消失了"；豁免表钉**同时**红在"多出来没豁免的包"。两枚门各守一维、
互相不替代，这一发是全场唯一的双杀，值得记一笔。

### 3.4 N4 §6.3 豁免表形状钉 —— **KILLED**

安装步尾部追加一行 `python -m pip install --disable-pip-version-check bandit`（未豁免参数）。

```
1 failed, 15 passed in 20.16s
RED test_extra_pip_arguments_are_exactly_the_exemption_table
```

同源钉（门 8）保持绿是**正确的**：`-r backend/requirements.txt` 那行一字未动，"装什么"漂了、
"从哪儿装"没漂。两枚门的分工在这一发上和 N3 互为反向对照。

### 3.5 N5 §6.4 行尾规则钉 —— **KILLED**

删 `*.sh text eol=lf` 整行（含换行；`.gitattributes` 是 LF、CR 字节 0）。

```
1 failed, 15 passed in 19.12s
RED test_gitattributes_carries_the_required_rules
```

**同一发里三枚邻近钉没红，都是设计使然而非漏判**（值得单独记账，因为它们是"行尾族"最容易
被误当成冗余的地方）：`_index_eol_rows()` 的 `attr/` 列从 `attr/text eol=lf` 退回 `attr/text`
（`* text=auto` 仍给着 text 属性），正则 `attr/[^\t]*?` 照样吃得下 ⇒ 覆盖度钉 `313 == 313` 绿、
`i/crlf=0` 绿；`test_eol_rules_are_a_no_op_for_the_current_tree` 读的是工作树字节而非规则表，
`.sh` 里没有 CR ⇒ 绿。也就是说：**"规则被删"这一格只有门 13 一枚在守**，本发证明它守住了。

### 3.6 N6 §6.4 覆盖度钉的空判地板 —— **KILLED**（但结论要说平白）

两枚编辑把 `_index_eol_rows()` 的**两侧**都收空（`records = []` + `tracked = []`）。

```
1 failed, 15 passed in 19.12s
RED test_non_text_index_entries_are_exactly_the_enumerated_set
AssertionError: 非文本形态漂移：多出来 []，少了 ['.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md',
 'docs/MODEL_ROUTER_V23_DESIGN.md', 'frontend/public/yaoke-logo.webp']
```

平白的两句话：

1. **覆盖度钉自己放行了这一发**——`len(parsed) == len(tracked)` 在 `0 == 0` 上成立、两侧集合
   皆空，`rows={}` 被当成"面面俱到地解析完了"。Task 4 评审登记的那一格**确实存在**：这条钉
   没有非空地板。
2. **同一枚 `rows={}` 喂给下游时漏不下去**：`test_index_has_no_crlf_entries` 跟着变成空判绿
   （offenders 恒空，这正是评审担心的"绿着变瞎"），而 `i/-text` 枚举集合钉断的是
   `found == 那三枚具名文件` ⇒ 空集合不等于三枚 ⇒ 当场红。

所以按任务书与计划的判定口径（"必须仍被 `i/-text` 枚举集合钉抓红；若两枚都绿则判 SURVIVED"）：
**结果是 KILLED，兜底链按预期生效，不需要回 Task 2 修门。** 但要说清它证明的是**这一族的组合**
有牙、不是覆盖度钉单独有牙：如果哪天那三枚 `i/-text` 白名单被清成空集（例如有人把两枚 markdown
强转成文本），这一形就只剩总数钉以外无人拦。**建议 controller 裁的后续项**（本任务不动判据）：
给 `_index_eol_rows()` 补一枚地板 `assert records and tracked`（与卡 I (2) 的"tokenize 非空"、
门 16 的"扫不到 `- name:` 即红"同族手法），一句话改动、不需要新门。

### 3.7 逐发还原核对

六发全部 `sha1(还原后) == sha1(注入前)` 且 `cmp rc=0`，任何一枚不过就 `SystemExit(3)` 中止整轮
（本轮未触发）。每发的 sha1 迁移都在 `mutation-bench.txt` 的 `[Nx] 注入 … <before> -> <after>` 行上，
例如 ci.yml 三发每次都从 `931846cba857` 出发、跑完回到 `931846cba857`。

---

## 4. 零残留：聚合 sha before / after

同一枚探针、同一配方（`tmp/task6_tree_probe.py`，只读 git 命令）：

```
[before] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[after ] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
```

**两枚口径都逐字符相等**。机理说清，别把这条读成"新文件把哈希冲掉了"：

- `WORKTREE-AGGREGATE` 数的是 `git ls-files` 的 313 枚**跟踪件**。本轮注入过的四枚目标里
  `ci.yml` 与 `conftest.py` 在里面（`.gitattributes` 与门模块未跟踪、根本不进这一面），
  所以它的相等 = "313 枚跟踪件的字节一枚都没变"，含那两枚 identity（未碰，值见 §1）。
- `EX-ID`（311 枚）是把两枚 identity 剔掉的那一枚，用来让"零残留"不被别人家的未提交改动稀释。
  两枚口径同时相等，才是这一条的完整形状。
- 未跟踪的两枚目标另按**逐枚 sha256 + `cmp`** 各核一次：`.gitattributes` 收工仍是
  `c5d07b5dc438` / 435 字节 / **CR 0**，门模块仍是 `73bede2def2e` / 48603 字节 / CR 0
  ——两枚都回到 R12/R13 登记的字节锚上。
- `git status --porcelain` before/after **十行逐字相同**（含行首那枚空格，`cat` 原文见
  `tmp/task6-tree-before.txt` / `task6-tree-after.txt`）。

本轮**新增的文件**只有三枚，全部在 gitignored 的 `.superpowers/` 底下，因此既不进跟踪面、
也不进 SEC-A 扫描面（无需新增任何豁免行）：`mutations/ent_b0_mutations.py`、
`mutation-bench.txt`、`task-6-report.md`，另加两枚过程件 `tmp/task6_tree_probe.py` 与
`tmp/task6-red-N1.txt` / `tmp/task6-red-N6.txt`。

---

## 5. `--check` 模式输出（不注入、不跑任何东西）

`--check` 核两件事：**七枚 needle 仍各命中一次**（若哪枚针卡在树上，锚点计数就会变），以及
**四枚目标的 sha1 与开工基线常数逐枚相等**（字节还原的独立复证，不依赖上一次跑的记忆）。

```
== --check（不注入、不跑测试）==
ANCHOR-OK	N1	counts=[1]	backend/tests/conftest.py
ANCHOR-OK	N2	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	N3	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	N5	counts=[1]	.gitattributes
ANCHOR-OK	N6	counts=[1, 1]	backend/tests/test_ci_gate_contract.py

RESTORED-OK	.gitattributes	5738e2743ea7 == 5738e2743ea7
RESTORED-OK	.github/workflows/ci.yml	931846cba857 == 931846cba857
RESTORED-OK	backend/tests/conftest.py	b0c5eee33ccd == b0c5eee33ccd
RESTORED-OK	backend/tests/test_ci_gate_contract.py	450484c09592 == 450484c09592

10/10 项通过（锚点 6 发 + 字节 4 枚）      rc=0
```

（原件 `tmp/task6-check.txt`；上面 N4 那一行的代号在 tee 的制表符里被我抄丢了，以存档件为准。）

sha1 常数是**开工前实测后钉进脚本**的（`BASELINE_SHA1`），不是跑完回填的——回填就等于让
"还原"这道证明自证自。代价也说清：那四枚目标将来被合法改动时 `--check` 会红，需要重新标定，
这是特性不是缺陷（红得比"忘了改针"响亮）。

---

## 6. 全量套件复跑（"没留东西"的终局证明）

变异台只跑定向节点，理论上碰不到别的用例；但**"理论上"不是判据**——这一族的历史（SEC-A 的
M16、V2.3 之前那一轮）就是被"理论上"骗过的。所以收工前跑一次全量：

```
cwd = E:\xiangmu\rag        python -m pytest backend/tests -q
1332 passed, 36 warnings, 1133 subtests passed in 121.26s (0:02:01)
FAILED/ERROR 行数 = 0
```

与 R15/R17 登记的宿主读数**同量**（1332 / 36 / 1133），收集数没被 N1 那一发的 `collect_ignore`
留痕改动。原件 `tmp/task6-suite-after-bench.txt`。

## 7. 纪律核对

| 项 | 实测 |
| --- | --- |
| git 写命令 | **0 枚**。用到的 git 命令只有 `ls-files`（含 `--eol -z`，由门自己起）与 `status --porcelain`，全是读；零提交，HEAD 仍 `7cc5efc`，`git diff --cached` 空 |
| 串行 | 六发在一次进程里 `for` 循环串行；`--check` 与全量套件都**不**与任何注入并发（全量套件跑时树上无变异） |
| 每发还原 | `finally` 写回**读到的原字节**（不从 git 取）→ sha1 与注入前比对 → 外部 `cmp` 逐字节比对；不过则 `SystemExit(3)` 中止整轮。六发全部 `sha1 同 + cmp rc=0` |
| 判据 | 十六枚门的断言、常数（`EXPECTED_COLLECTED = 1332`、`PIP_INSTALL_EXEMPTIONS`、`ALLOWED_*`）一字未改；N6 尤其**没有**顺手补地板（那是 controller 的裁定，见 §3.6 末） |
| 未碰的面 | `backend/app/**`（含两枚 identity，收工 sha 仍是 `3bc681bbc52c` / `2cfab9f18182`）、`backend/requirements.txt`、`test_secret_hygiene_contract.py` 与其豁免表（SEC-A 扫描面里本轮零新增文件，`.superpowers/` 是 gitignored） |
| stdout 编码 | import 期即 `reconfigure(encoding="utf-8", errors="replace")`：宿主 cp936 下中文断言会先炸打印，而那时文件已还原 ⇒ 留下的是一份半截证据表，价值等于零 |
| 过程件落点 | pytest 全文与 `cmp` 参照件都在 `%TEMP%`（SEC-A 同形：一枚节点一个文件，跑单发即可再生该发的全文，本轮已把 N1/N6 两枚存档进 `tmp/`）；不进仓库 |

**与任务书/计划的两处偏差（都已就地说明，不是放宽）**：
① 产物路径写的是 `.superpowers/sdd/ENTERPRISE_B0/mutations/`，仓库里那一级实际叫
`ENTERPRISE_B0_PLAN/`（Task 1—5 全部如此），按实况落盘。
② 定向节点从"计划点名的那一枚函数"扩成"整枚 16 门模块"，理由与取证精度见 §3 开头。

## 8. 交付面

- `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py` — 六发台子（字节安全四条
  + 本台多出的四处，全部写在模块 docstring 里；`REPO = Path(__file__).resolve().parents[4]`
  与 SEC-A 同深度）
- `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutation-bench.txt` — 台子自己的表格输出（逐发红信息 +
  锚点命中 + 还原证明 + `6/6 KILLED`）
- `.superpowers/sdd/ENTERPRISE_B0_PLAN/task-6-report.md` — 本件
- `tmp/task6_tree_probe.py` / `tmp/task6-tree-{before,after}.txt` / `tmp/task6-check.txt` /
  `tmp/task6-red-N1.txt` / `tmp/task6-red-N6.txt` / `tmp/task6-suite-after-bench.txt` — 过程件
- `snap-task6-post/` — 台子与两份产物的字节快照（与源文件 `cmp` rc=0）
- `progress.md` 追加 **R19** 一行

**交给 controller 的三项**：
1. §3.6 那枚地板（`_index_eol_rows()` 缺非空断言）本轮**证实存在**但**被邻近钉兜住**，
   要不要在 Task 7 之前补，归裁定；补法一句话、不加门。
2. B0-11 到此有读数了，但**远端 CI 那一格仍未跑过**（本轮一切读数都是宿主工作树态）。
   规格 §14 登记的"交付面缺件"（P0 evidence）还在，远端首跑必红那一枚。
3. `.gitattributes` 与门模块**还是未跟踪件**（`??`），入库需要显式 `git add`，本任务无提交权限。

---

## 9. 收工三时点复量（同一探针、同一配方）

```
[before  ] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[after   ] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[closeout] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
```

`closeout` 是在**报告写完、台账 R19 落笔、`snap-task6-post/` 快照之后**又取的一次：写作过程本身
只动 gitignored 的 `.superpowers/`，所以三时点必须同值，而它同值了。逐枚字节锚（closeout，
与 §1 的 before 逐字符相等）：

```
2ff38f8a68a1  bytes=56751 CR=0    backend/tests/conftest.py
1c706e165b73  bytes=7106  CR=147  .github/workflows/ci.yml
c5d07b5dc438  bytes=435   CR=0    .gitattributes
73bede2def2e  bytes=48603 CR=0    backend/tests/test_ci_gate_contract.py
3bc681bbc52c  bytes=16587 CR=0    backend/app/identity/README.md      （既有改动，未碰）
2cfab9f18182  bytes=3344  CR=0    backend/app/identity/__init__.py    （既有改动，未碰）
```

`--check` 在 closeout 再跑一次仍 `10/10`、rc=0（`tmp/task6-check-closeout.txt`）；
`git rev-parse --short HEAD` = `7cc5efc`、`git diff --cached` 空、`git status --porcelain` 仍 10 行。

**注入总次数 = 7**：六发一轮（`mutation-bench.txt`）+ N1 单独复跑一次，只为把它那一发的 pytest
全文存档到 `tmp/task6-red-N1.txt`（台子按节点名落一枚临时文件，六发共用一枚、后发会盖前发，与
SEC-A 同形）。复跑同形（同一 sha1 迁移、同一枚门红、还原同样 `sha1 同 + cmp rc=0`），
`mutation-bench.txt` 里那一份才是本轮的正式读数。N6 的全文是首轮就跑完顺手抢下来存档的。

> 补记：§3 的两处措辞订正之后又取了第四时点 `final`，两枚口径仍
> `WORKTREE-AGGREGATE=d30366c6a440` / `EX-ID(311)=2685edde76fe`、`--check` 仍 `10/10` rc=0、
> `git status --porcelain` 仍那十行（`tmp/task6-tree-final.txt`）。

---

## Task 6 修复轮 1

日期 2026-09-28。工作树态、**零提交**、**零 git 写命令**（只用 `git ls-files` / `git status` /
`git rev-parse` 这类读命令），HEAD 仍 `7cc5efc`。本轮只动一枚文件：
`backend/tests/test_ci_gate_contract.py`。

**裁定的落点**：§3.6 交给 controller 的那一格（覆盖度钉缺非空地板）被裁定为**现在补**，理由是
补它本身就是 B0 的论点——不许有静默的空判绿。一句话改动、**不加门**、**不动任何既有判据**。

**一句话结论**：地板落地后 N6 的击杀者从"只有兜底的 `i/-text` 枚举集合钉"变成
**"覆盖度钉自己（两枚消费门都红在 `test_ci_gate_contract.py:714` 那枚 `assert tracked` 上）+
兜底仍在"**；门数仍 **16**、`EXPECTED_COLLECTED` 仍 **1332**、`python scripts/b0_collection_probe.py`
仍 `TOTAL 1332` 且本模块仍贡献 16 枚；跟踪面聚合 sha 两枚口径回到台账值
（`WORKTREE-AGGREGATE=d30366c6a440` / `EX-ID(311)=2685edde76fe`）；`--check` **9/10**，
唯一那一条不匹配正是本轮**有意**改动的那枚门模块字节（见 §F4，常数在被禁改的台子里）。

### F1. 地板的 diff（`tmp/task6fix1-floor.diff`）

改前那份字节不是从 git 取的（门模块是 `??` 未跟踪件，树里没有可比版本），而是由
`tmp/task6fix1_make_diff.py` 把本轮三处替换**逐字反演**出来，再核一枚硬证据：
反演结果 `sha1 = 450484c09592…` **==** 台账登记的改前值（也是本轮 N6 注入前的出发值）。
等 ⇒ 下面这份 diff 就是本轮的全部真实改动；不等脚本自己作废。

```diff
--- a/backend/tests/test_ci_gate_contract.py（改前，sha1 450484c09592）
+++ b/backend/tests/test_ci_gate_contract.py（改后，sha1 a0b9f37f32bb）
@@ -16,6 +16,8 @@
    `autocrlf=false` 的机器（Linux 默认）可以把 CRLF 字节写进 index。这一族还有第三枚钉：**解析
    覆盖度**（§16 卡 K）——`git ls-files --eol` 的每一行都必须被读到，"解析出的条数 == `git ls-files`
    的跟踪条数"，不等即红；它不假设属性列长什么样，所以任何未来的丢行都只会响亮地红、不会静默瞎。
+   同一枚覆盖度钉还有**非空地板**（Task 6 修复轮 1，变异台 N6 实测换来的那一格）：两侧都必须收得到
+   东西才轮到等量判据说话 —— 否则 `0 == 0` 会让钉自己放行，而下游 `i/crlf` 消费门跟着变成空判绿。

@@ -693,15 +695,28 @@  （`_index_eol_rows()` 的 docstring：判据从"两道"改成"两道地板 + 逐条计数 + 路径集合"）
-    判据取"逐条计数 + 路径集合"两道，缺一都不完整：
+    判据取"两道地板 + 逐条计数 + 路径集合"，缺一都不完整：
+      * **非空地板**（N6 实测换来的，Task 6 修复轮 1）：跟踪面与解析面**都必须有东西**。
+        等量判据两侧同空时成立在 `0 == 0` 上——那不是"面面俱到地一致"，那是这枚钉不再检查
+        任何东西。变异台 N6 那一发的读数是：覆盖度钉放行、`test_index_has_no_crlf_entries`
+        **空判绿**，只有 `i/-text` 枚举集合钉拦住（兜底链生效，但那证明的是"这一族的组合有牙"）。
+        地板的红要说清是**钉哑了**，不能读成"仓库干净"——与 `test_eol_rules_are_a_no_op_for_the_current_tree`
+        的 `assert checked`、卡 I (2) 的"tokenize 非空"、门 16 的"扫不到 `- name:` 即红"同族手法。
       * **逐条计数**（`len(parsed) == len(tracked)`）：…（原样未动）
-      * **路径集合相等**：抓"读到了但读歪了"…
+      * **路径集合相等**（`missing` / `extra` 双向）：…等量+集合两条是**并判**的：
+        只比条数会放走"条数相等但集合不同"那一形。
     """
     records = _index_eol_records()
     tracked = _tracked_paths()
+    assert tracked, (
+        "`git ls-files` 跟踪面一枚都没有 ⇒ 这枚解析覆盖度钉退化成了空判：它的绿不能读成"
+        "『index 面与跟踪面一致』，只能读成『钉不再检查任何东西』（卡 K 的地板，N6 实测那一形）。"
+        f"\n同一时刻的 `--eol` 记录面 {len(records)} 条；消费这份面的 "
+        "`test_index_has_no_crlf_entries` 与 `test_non_text_index_entries_are_exactly_the_enumerated_set`"
+        "也跟着失去覆盖面 —— 先弄清跟踪面是怎么收空的，再谈行尾干不干净")
     parsed: "list[tuple[str, str]]" = []

@@ -711,6 +726,13 @@
     rows: "dict[str, str]" = dict(parsed)
+    assert parsed, (
+        f"解析面一枚都没有 ⇒ 这枚解析覆盖度钉退化成了空判：红在『钉哑了』，不是红在『仓库干净』"
+        f"（卡 K 的地板）。`git ls-files --eol` 记录面 {len(records)} 条、未解析 {len(unparsed)} 条、"
+        f"跟踪面 {len(tracked)} 枚"
+        f"\n未解析记录样本（前 5 条）：{[u[:120] for u in unparsed[:5]]}"
+        f"\n最可能的那一形 = `_EOL_LINE` 的某一列认不了当前 git 的输出"
+        f"（属性列跨空格/制表符、列序变了、新字段带空格）——它丢的恰好是行尾最敏感的那几枚文件")
     missing = sorted(set(tracked) - set(rows))
     extra = sorted(set(rows) - set(tracked))
     assert len(parsed) == len(tracked) and not missing and not extra, (   ← **一字未动**
```

+25 行 / -3 行（-3 是那三行 docstring 被改写）。要钉住的三点：

1. **既有等量+集合判据一字未动**（`assert len(parsed) == len(tracked) and not missing and not extra`
   连同它的失败信息整体保留）——本轮只做加法，没有任何一枚断言被放宽。
2. **两枚接缝行仍是原文**（`    records = _index_eol_records()` / `    tracked = _tracked_paths()`
   各命中 1 次），所以 N6 那两枚 needle 一字未改，`--check` 的 `ANCHOR-OK N6 counts=[1, 1]` 就是这条。
3. **地板不新增门、不改门名**：`def test_` 仍 16 枚、`_OWN_TEST_NAMES` 一字未动、
   `EXPECTED_COLLECTED = 1332` 一字未动。地板挂在 helper 里，红通过**三枚既有消费面**表达
   （`test_index_has_no_crlf_entries` / `test_non_text_index_entries_are_exactly_the_enumerated_set`
   两枚调用它），这正是任务书要的"不加门"形状。

措辞对齐的是同文件里那枚 `assert checked`（"…一枚都不在面上：这条 no-op 证明退化成了空判"）与
卡 I (2) 的"这不能读成『…』，只能读成这枚门哑了"——红永远说**钉哑了**，绝不说**仓库干净**。

### F2. N6 单发复跑：击杀者从"只有兜底"变成"覆盖度钉自己"

台子一字未改（`main(argv)` 本来就支持按 id 选发：`python …/ent_b0_mutations.py N6`），
只在**改前**与**改后**各跑一次同一发，两次都是"全 16 枚模块、不带 `-x`"，所以读得到"哪几枚杀了它"。

| | 改前（`tmp/task6fix1-n6-before.txt`） | 改后（`tmp/task6fix1-n6-after.txt`） |
| --- | --- | --- |
| 注入 sha1 迁移 | `450484c09592 -> 5c8ec7fb9839` | `a0b9f37f32bb -> eb4a49aa6d75` |
| 锚点命中 | `[1, 1]` | `[1, 1]`（本轮改动**没碰**两枚 needle） |
| pytest 读数 | 1 failed, 15 passed in 28.00s | **2 failed, 14 passed** in 25.87s |
| 红掉的门 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | **`test_index_has_no_crlf_entries`** + 同一枚 `i/-text` 枚举集合钉 |
| 红在哪一行 | `:750` 的 `found == 那三枚具名`（兜底） | **`:714` 的 `assert tracked`** ——两枚都红在覆盖度钉的地板上 |
| 还原 | sha1 同 + `cmp` rc=0 | sha1 同 + `cmp` rc=0 |

`tmp/task6fix1-n6-after-pytest.txt` 的原文（两枚红都是同一句，行号 `:714`）：

```
E   AssertionError: `git ls-files` 跟踪面一枚都没有 ⇒ 这枚解析覆盖度钉退化成了空判：它的绿不能读成
    『index 面与跟踪面一致』，只能读成『钉不再检查任何东西』（卡 K 的地板，N6 实测那一形）。
FAILED tests/test_ci_gate_contract.py::test_index_has_no_crlf_entries
FAILED tests/test_ci_gate_contract.py::test_non_text_index_entries_are_exactly_the_enumerated_set
2 failed, 14 passed in 25.87s
```

这一格才是本轮的论点：**改前那枚 `test_index_has_no_crlf_entries` 是空判绿**（`rows={}` ⇒
offenders 恒空），也就是"覆盖度钉放行了、消费门跟着瞎"；改后它自己红在地板上，红的话术是
"钉哑了"而不是"行尾干净"。兜底那枚仍在红，但**不再是唯一的守门人**。

改前那一份的失败信息（`tmp/task6fix1-n6-before-pytest.txt`）留档对照，只有一枚红、且红在枚举集合：

```
E   AssertionError: 非文本形态漂移：多出来 []，少了 ['.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md',
    'docs/MODEL_ROUTER_V23_DESIGN.md', 'frontend/public/yaoke-logo.webp']
1 failed, 15 passed in 28.00s
```

**地板不只对 N6 那一形有牙**（`tmp/task6fix1_floor_jig.py`，喂合成面进那两枚刻意留下的接缝，
四格表 + 逐字重实现的"改前判据"同表对照，读数见 `tmp/task6fix1-floor-jig.txt`）：

| 格 | 合成面 | 改前 | 改后 |
| --- | --- | --- | --- |
| A | 真实面（记录 313 / 跟踪 313） | 放行 | **放行**（面 313 枚）⇒ 本轮不制造假红 |
| B | N6 形：两侧同时收空 | **放行（覆盖度钉不响）** | **红（跟踪面地板）** |
| C | 只收记录一侧 | 红（`0 vs 313`，等量） | 红（解析面地板，早一步且给样本） |
| D | 记录面 313 条但**一枚都解析不了**（把 tab 换成空格 ⇒ `_EOL_LINE` 从此认不了，正是卡 K 原形） | 红（`0 vs 313`） | 红（解析面地板 + 未解析样本 5 条） |

B 就是"静默空判"那一格，只有它改前放行；C / D 改前就红，但改后把"为什么红"从两个数变成了
**带未解析样本的诊断**，归因更准。

### F3. 等量 vs 集合：查到的结论是"并判已在，不重复实现"

任务书第 2 条问的是"等量判据是不是只比条数、能不能被'条数相等但集合不同'换掉"。实测：

- **既有断言早就是并判的**：`assert len(parsed) == len(tracked) and not missing and not extra`，
  其中 `missing = sorted(set(tracked) - set(rows))`、`extra = sorted(set(rows) - set(tracked))`
  是**路径集合的双向差**。所以"等量但换集"那一形**改前就红**，不需要补第三道判据。
  jig 最后一栏实测：把跟踪面换成"313 枚、但其中一枚不在 index 面上"的同基数异集合 ⇒
  改前 `红（等量/集合：313 vs 313）`、改后 `红（既有等量/集合判据）`，**两版都拦**。
- **本轮没有复制这份逻辑**：地板只做"非空"这一件事，等量与集合那两条一字未动，
  `missing` / `extra` 的计算与失败信息原样保留（diff 里那行 `← 一字未动`）。
- **两条的分工本来就不重合，别读成冗余**：计数按**记录条**（`len(parsed)`），集合按**去重后的路径**。
  中间那一层 `rows = dict(parsed)` 会折叠重复路径 ⇒ 单看集合会放走"两枚 stage 条目被折叠成一枚"
  这种形状，而单看计数又指不出是哪枚路径。地板挂在计数与集合**之前**，因为它要拦的是
  "两侧一起空到让两条都失去宾语"，那一格恰好是两条都判不出来的。
- 顺带登记一枚**本轮不修**的边界（不是本轮换来的、也不是空判那一族）：集合比的是**路径**，
  不是 `(路径, index 列)` 二元组——若有人把 `i/` 列整体换成一个自洽的假值，等量与集合都会绿，
  只有 `i/crlf` / `i/-text` 两条形状判据可能察觉。它属于"没有第二份真相可比"的那一族，
  与 §14 L6 同登记口径，不当已解决。

### F4. `--check`（不注入、不跑测试）

`tmp/task6fix1-check.txt`，rc=1：

```
ANCHOR-OK	N1 counts=[1]  backend/tests/conftest.py
ANCHOR-OK	N2 counts=[1]  .github/workflows/ci.yml
ANCHOR-OK	N3 counts=[1]  .github/workflows/ci.yml
ANCHOR-OK	N4 counts=[1]  .github/workflows/ci.yml
ANCHOR-OK	N5 counts=[1]  .gitattributes
ANCHOR-OK	N6 counts=[1, 1]  backend/tests/test_ci_gate_contract.py     ← 本轮改动没碰两枚 needle

RESTORED-OK	.gitattributes                    5738e2743ea7 == 5738e2743ea7
RESTORED-OK	.github/workflows/ci.yml          931846cba857 == 931846cba857
RESTORED-OK	backend/tests/conftest.py         b0c5eee33ccd == b0c5eee33ccd
RESTORED-MISMATCH	backend/tests/test_ci_gate_contract.py  a0b9f37f32bb != 450484c09592

9/10 项通过（锚点 6 发 + 字节 4 枚）
```

**这一条不匹配是本轮的改动本身，不是残留**，要说平白：`--check` 的字节基准是钉在台子
`BASELINE_SHA1` 里的那枚**开工前常数**（`450484c09592` = 改前门模块），而台子文件在本轮的
禁改范围内（约束只放行"台子自己的逐发输出件"），所以本轮**不回填常数**、把这条差异原样登记。
它和残留的区分有两枚硬证据：注入态是 `eb4a49aa6d75`、树上是 `a0b9f37f32bb`，两者不同；
且本轮的还原证明走的是**运行时**的 `sha1(注入前) == sha1(还原后)` + 外部 `cmp`（F2 那两行 OK），
不依赖这枚常数。**要请 controller 处置的一件事**：门模块的新字节锚是
`sha1 a0b9f37f32bb` / `sha256[:12] 699b0dfa8d9e` / 50994 字节 / **CR 0**（LF 832），
下一轮动台子时把常数一起换掉，否则 `--check` 会一直报这一条。

### F5. 门模块与收集常数

- 门模块（`tmp/task6fix1-gate-module.txt`）：**`16 passed in 23.42s`**，0 failed、0 error、0 skipped
  ⇒ 地板在真实面上不红（A 格），本轮不是假红。
- 自我存续两枚钉同格绿：`test_the_gate_module_itself_is_collected` 认"本文件贡献 16 枚"，
  `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 扫本轮新字节仍 0 命中
  （地板里没有装饰器，失败信息里的 `skip` 字样只出现在散文里、`@` 前缀一枚没有）。
- `python scripts/b0_collection_probe.py`（`tmp/task6fix1-probe.txt`）：**`TOTAL 1332`**，
  逐模块表里 `16  backend/tests/test_ci_gate_contract.py` ⇒ `EXPECTED_COLLECTED = 1332` 未改、
  也未"被凑"，两侧都是实测量。
- 全量套件一次（`tmp/task6fix1-suite-raw.txt`）：**`1332 passed, 36 warnings, 1133 subtests passed
  in 129.53s`、rc=0**，`^FAILED` / `^ERROR` 行 **0 枚**。与 R19 收工读数
  （1332 / 36 / 1133 / 121.26s）同量，差的那 8s 是宿主并发。

### F6. 零残留与聚合 sha 回到台账

同一枚只读探针 `tmp/task6_tree_probe.py`（`git ls-files` / `git status` / `git rev-parse`，
**零 git 写命令**），三时点：

```
[before-fix1] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[after-fix1 ] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[closeout-fix1] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
```

**两枚口径逐字符回到台账值**（R19 登记的就是这两枚）。机理沿用 §4 那条：本轮唯一改的
`backend/tests/test_ci_gate_contract.py` 与 `.gitattributes` 同属**未跟踪件**（`??`），
根本不进这 313 枚跟踪面 ⇒ 聚合相等读的是"本轮没动任何跟踪件"，而本轮的字节改动本身由
门模块的 sha1/sha256 逐枚钉住。其余核对：

- 四枚变异目标里本轮**没注入过**的三枚，`--check` 三条 `RESTORED-OK`（F4）。
- `git status --porcelain` 仍那 **10 行**（逐字见 `tmp/task6fix1-tree-after.txt`），
  `backend/app/identity/README.md` `3bc681bbc52c` / `__init__.py` `2cfab9f18182` 两枚既有改动
  **一字未碰、也没去"修"**；`HEAD` 仍 `7cc5efc`、零提交。
- 门模块字节：`sha1 a0b9f37f32bb`、`sha256[:12] 699b0dfa8d9e`、50994 字节、**CR 0** / LF 832
  ⇒ 与整份仓库的 LF 口径一致，本轮没往门文件里写进一枚 CRLF。
- **台子与六发的正式读数一字未动**：`cmp mutations/ent_b0_mutations.py snap-task6-post/ent_b0_mutations.py`
  rc=0、`cmp mutation-bench.txt snap-task6-post/mutation-bench.txt` rc=0 ⇒ 本轮没有重写台子
  （按 id 选发是它本来就有的能力），也没有覆盖 R19 那份 `6/6 KILLED` 正式表；两次 N6 的读数是
  另落 `tmp/task6fix1-n6-{before,after}.txt` 两份过程件。
- **注入总次数 = 3**：改前 N6 一发 + 改后 N6 一发（各一次注入、各一次 `finally` 还原、
  各一次 `sha1 同 + cmp rc=0`），加一次 `--check`（不注入）。树上无变异残留。

### F7. 产物

- `backend/tests/test_ci_gate_contract.py` —— 唯一被改的交付面文件（+25 / -3）
- `tmp/task6fix1-gate-pre.py` —— 逐字符反演出的改前字节（sha1 与台账常数相等，是 diff 的信任根）
- `tmp/task6fix1_make_diff.py` / `tmp/task6fix1-floor.diff` —— 反演脚本（不过即自我作废）与 diff
- `tmp/task6fix1_floor_jig.py` / `tmp/task6fix1-floor-jig.txt` —— 地板四格反证台与读数
- `tmp/task6fix1-n6-before.txt` / `-after.txt` / `-before-pytest.txt` / `-after-pytest.txt` —— 两次 N6
- `tmp/task6fix1-check.txt` / `task6fix1-gate-module.txt` / `task6fix1-probe.txt` /
  `task6fix1-suite-raw.txt` / `task6fix1-tree-before.txt` / `task6fix1-tree-after.txt` /
  `task6fix1-tree-closeout.txt`
- `snap-task6-fix1-post/` —— 门模块 + 台子 + 本报告 + `progress.md` 的字节快照（与源件 `cmp` rc=0）
- `progress.md` 追加 **R20** 一行

**交给 controller 的两项**：①F4 那枚 `BASELINE_SHA1` 常数需要下一轮有授权时替换（本轮禁改台子）；
②§14 L6 / F3 末尾登记的"集合只比路径不比 `(路径, index 列)`"仍是已知边界，不当已解决。
远端 CI 那一格本轮仍无读数（一切读数都是宿主工作树态），归 Task 7。

---

## Task 6 修复轮 2

日期 2026-09-28。工作树态、**零提交**、**零 git 写命令**（只用 `git ls-files` / `git status` /
`git rev-parse` 这类读命令），HEAD 仍 `7cc5efc`。本轮只动**台子自己**（
`.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py`）与**一枚诊断用的基线件**
（`baseline/collected-node-ids.txt`）；`backend/tests/test_ci_gate_contract.py` **一字未改**
（收工 `cmp` 与 `snap-task6-fix1-post/` 那份逐字节相同，见 G9）。

**一句话结论**：I-2 的归因仪表落地后整轮八发重跑，**N1—N8 全部 `KILLED-ASSIGNED`、
`KILLED-INCIDENTAL` 0 枚、`COLLECTION-BROKEN` 0 枚**，台子 rc=0；I-1 的常数从
`snap-task6-fix1-post/` 那一份重锚（`450484c09592` → `a0b9f37f32bb`），`--check` 在"重锚后、
加发前"那一格实测 **10/10 rc=0**，八发齐了之后是 **12/12 rc=0**（锚点 8 发 + 字节 4 枚）；
M-1 补的 N7/N8 把最后两枚"从未被观测到红"的**有牙判据**（自我存续钉、豁免行理由地板）第一次真红了；
M-4 把 `baseline/collected-node-ids.txt` 从 Task 1 的 1316 行面重生成到当前 1332 行面，
红信息里的幽灵"新增 16 枚"变成"新增 0 枚"，而**判据一字未变**（重生成后复跑门模块 `16 passed`）；
跟踪面聚合 sha 两枚口径回到台账值（`d30366c6a440` @313 / `2685edde76fe` @311）、全量套件
**1332 passed / 0 failed / 144.22s / rc=0**（32 次注入之后收集数仍是 1332）⇒ 零残留。评审还剩两枚从未红过，
本轮**明写**它们是 helper 自测 / 回归守卫并给出为什么可以（G5），不是悄悄略过。

### G1. I-2：判决必须归到"计划点名的那枚门"上

改前那枚仪表的缺陷是可复现的：`"KILLED" if rc != 0` 只对"整枚 16 门模块红了"说话，
`spec["node"]` **被收集但从未打印、从未参与判定**（`main()` 里那一格填的是占位 `"OK"`，
表格里连"计划门"这一列都没有）。于是修复轮 1 的 N6 报 `KILLED` 而它计划钉住的门当时正**空判绿**——
读数没错，含义是错的；一次偶然红、甚至收集整个炸掉，在表上长得一模一样。

台子新增 `decide(rc, red, assigned)`（`MUTATIONS[i]["node"]` 扩成 `["nodes"]` 列表，八发全部点名）：

| 态 | 触发条件 | 后果 |
| --- | --- | --- |
| `KILLED-ASSIGNED` | rc≠0 **且** 计划门**全部**在实测红面里 | 这一发做成了（唯一算数的态） |
| `KILLED-INCIDENTAL` | rc≠0、别的门红了、计划门绿 | **这一发的失败**，整轮 rc 非 0；绝不许"顺手把期望改成红的那枚" |
| `COLLECTION-BROKEN` | rc≠0 而 `FAILED/ERROR` 行**一枚都读不到** | 命令没跑到断言层（解释器/参数/收集期炸），不是 KILLED |
| `SURVIVED` | rc=0 | 这发在树上没杀掉任何门 ⇒ 那枚门是纸门 |

`main()` 现在逐发打印三行硬事实（`计划钉住 […]` / `实测红面 […]` / `判决 …`），表格也加了
"计划钉住的门 / 实测红面 / 判决（归因）/ 备注"四列。附带修好一处本轮首跑撞上的自伤：
`gate_roster()` 原先按"去 `def ` 前缀、去末字符"取门名，把括号留进了名字里
（`test_x()`），于是八发全 `KILLED-ASSIGNED` 而溯源表整列 `NEVER`——改成 `^def (test_\w+)`
正则现读（台子自己也吃了一次"名字对不上就一切免谈"的教训，写进函数 docstring）。

### G2. 整轮八发的新表（`mutation-bench.txt`，台子 rc=0）

| 变异 | 规格判据 | 目标文件 | 锚点命中 | 计划钉住的门 | 实测红面 | 判决（归因） | 备注 | 还原 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| N1 | §6.1 收集数钉 | backend/tests/conftest.py | 1 次/编辑 | `test_collected_count_matches_the_pinned_number` | 同计划 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N2 | §6.2 单 runner 钉 | .github/workflows/ci.yml | 1 次/编辑 | `test_backend_contracts_has_no_unittest_discover_step` | 同计划 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N3 | §6.3 依赖同源钉 | .github/workflows/ci.yml | 1 次/编辑 | `test_install_face_uses_requirements_txt_as_the_source` | 计划 + `test_extra_pip_arguments_are_exactly_the_exemption_table`（双杀） | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N4 | §6.3 豁免表形状钉 | .github/workflows/ci.yml | 1 次/编辑 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | 同计划 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N5 | §6.4 行尾规则钉 | .gitattributes | 1 次/编辑 | `test_gitattributes_carries_the_required_rules` | 同计划 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N6 | §6.4 覆盖度钉的空判地板 | backend/tests/test_ci_gate_contract.py | 1 次/编辑 | `test_index_has_no_crlf_entries` + `test_non_text_index_entries_are_exactly_the_enumerated_set` | **两枚计划门全红**（R20 的地板之后才有的读数） | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N7 | §6.1 总数钉 + 卡 H 自我存续钉（改名门自己） | backend/tests/test_ci_gate_contract.py | 1 次/编辑 | `test_collected_count_matches_the_pinned_number` + `test_the_gate_module_itself_is_collected` | 两枚计划门全红 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |
| N8 | §6.3 豁免行的『为什么』地板 | backend/tests/test_ci_gate_contract.py | 1 次/编辑 | `test_every_exemption_row_states_why` | 同计划 | **KILLED-ASSIGNED** | - | OK（sha1 同 + cmp rc=0） |

**`8/8 KILLED-ASSIGNED`；`KILLED-INCIDENTAL` 0 枚**——本轮没有一发靠"偶然红"充数。
逐发 sha1 迁移（`mutation-bench.txt` 原文）：`b0c5eee33ccd→5fa40bed5e3f`（N1）、
`931846cba857→bded7c6c802d`（N2）、`931846cba857→9985973a1dd5`（N3）、`→7bbab2f31091`（N4）、
`5738e2743ea7→90885abbf68d`（N5）、`a0b9f37f32bb→eb4a49aa6d75`（N6）、
`a0b9f37f32bb→0ca2edd50e16`（N7）、`a0b9f37f32bb→582bca1b201e`（N8）；八发都从台账常数出发、
跑完回到它。**这八枚 sha 在四个完整周期里逐字符相同**（注入是确定性的），所以"换台子字节重跑"
没有把任何一发跑到别的形状上。pytest 摘要逐发 `1 failed, 15 passed` / N3、N6、N7 `2 failed`
（N7 是 `2 failed, 13 passed`——被改名的那枚不再被收集，16 枚里只剩 15 枚参与），
耗时 **20.13—23.30s/发**、整轮 177s。

**N6 的归因变化就是 I-2 的论点本身**：修复轮 1 之前它 `KILLED` 却把计划门读成空判绿；
现在两枚计划门**同时**红在 `:714` 的 `assert tracked` 上（R20 的地板），仪表才配得上那个 `KILLED`。
**四份完整周期都跑过、都 `8/8`**：正式件 `mutation-bench.txt` 由**终态台子字节**产出，
被推翻的前三周期分别另存 `tmp/task6fix2-bench-raw.txt`（第 1 周期，撞上 `gate_roster()` 把
`()` 留在门名里 ⇒ 溯源表整列 NEVER）、`tmp/task6fix2-bench-cycle2.txt`（第 2 周期，撞上溯源表
footer 的分母写死 `16`）、`tmp/task6fix2-bench-cycle3.txt`（第 3 周期，footer 又把发数写死成
"八发"）。三次都是这台仪器**自己撞自己的判据**（"常数落后于事实"），每次都重跑整轮而不是
只改那一行——八发的 sha 迁移在四周期里逐字符相同，所以推翻的只是表格文案，不是任何一发判决。

### G3. I-1：`BASELINE_SHA1` 从快照重锚（旧→新入台账）

旧常数 `450484c09592ef3e89f8798c65737c563e4ca217` 是修复轮 1 **之前**的门模块字节，被 R20 的地板
作废 ⇒ `--check` 从此恒 rc=1。一枚永远红的自检会被读成"预期噪音"，正是本仓库写过两张卡的
"假红→忽略"那一族。**重锚不取"磁盘现值"**，取 `snap-task6-fix1-post/test_ci_gate_contract.py`
（R20 自己落的字节快照），再与树核对：

```
sha1sum  snap-task6-fix1-post/test_ci_gate_contract.py  = a0b9f37f32bbab9580023b230a79a206ad1e0cbf
sha1sum  backend/tests/test_ci_gate_contract.py         = a0b9f37f32bbab9580023b230a79a206ad1e0cbf
cmp backend/tests/test_ci_gate_contract.py snap-task6-fix1-post/test_ci_gate_contract.py  -> rc=0
```

新常数 `a0b9f37f32bb…`（`sha256[:12] 699b0dfa8d9e` / 50994 字节 / CR 0 / LF 832）写进
`BASELINE_SHA1`，`450484c09592 → a0b9f37f32bb` 这一对已在台账 **R21** 登记。其余三枚常数
（`conftest.py b0c5eee33ccd` / `ci.yml 931846cba857` / `.gitattributes 5738e2743ea7`）**一字未动**——
本轮没有合法改动过它们，动它们就等于把证明改成随树漂。

**`--check` 读数（`tmp/task6fix2-check-10of10.txt`，重锚后、加发前的那一格）**：

```
ANCHOR-OK	N1	counts=[1]	backend/tests/conftest.py
ANCHOR-OK	N2	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	N3	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	N4	counts=[1]	.github/workflows/ci.yml
ANCHOR-OK	N5	counts=[1]	.gitattributes
ANCHOR-OK	N6	counts=[1, 1]	backend/tests/test_ci_gate_contract.py

RESTORED-OK	.gitattributes	5738e2743ea7 == 5738e2743ea7
RESTORED-OK	.github/workflows/ci.yml	931846cba857 == 931846cba857
RESTORED-OK	backend/tests/conftest.py	b0c5eee33ccd == b0c5eee33ccd
RESTORED-OK	backend/tests/test_ci_gate_contract.py	a0b9f37f32bb == a0b9f37f32bb

10/10 项通过（锚点 6 发 + 字节 4 枚）      rc=0
```

任务书要的 10/10 就是这一格（6 发锚点 + 4 枚字节）。**取法要说明白**：这一份读数用的是
"重锚完成、M-1 那两发还没落地"的台子——为了不退回去伪造，我把当时的台子原文存到
`tmp/task6fix2-harness-with-n7n8.py`，按 `# §6.1 + 卡 H` 与列表闭合符切出临时六发版（切完 `ast.parse`
复验、`"code"` 计数 6），跑完 `--check` 再整枚拷回并 `cmp` rc=0 ⇒ 10/10 是**真读数**，
不是把 N7/N8 藏起来口头报数。M-1 落地后同一模式的终态是 **12/12 rc=0**
（`tmp/task6fix2-check-final.txt`：锚点 8 发 + 字节 4 枚），这才是这一轮的不变式
——"每一条都过、rc=0"，条目数随发数长。

### G4. M-1：N7 与 N8（把两枚"从未红过"的有牙判据真红一次）

- **N7 —— 改门模块里一枚 `def test_…` 的函数名**（宾语 `test_backend_contracts_runs_the_pytest_suite`，
  改成 `n7_renamed_away_from_test_prefix`；改函数名，不改文件名）。它必须**同时**红两枚：

  ```
  E   AssertionError: 收集数 1331 ≠ 钉住的 1332。
      消失 1 枚：['backend/tests/test_ci_gate_contract.py::test_backend_contracts_runs_the_pytest_suite']
      新增 0 枚：[]
  E   AssertionError: 门自己被摘了或哑了：本文件应有 16 枚，实收 15 枚          （:130）
  FAILED tests/test_ci_gate_contract.py::test_collected_count_matches_the_pinned_number
  FAILED tests/test_ci_gate_contract.py::test_the_gate_module_itself_is_collected
  2 failed, 13 passed in 22.44s
  ```

  这正是 Task 2 那次 skip 注入实验欠下的那一格：挂上哑门装饰器时**枚数钉绿、只有装饰器钉红**，
  所以"总数钉单独抓不到摘门"已被证过；本轮补的是**改名/摘走**这一形——总数钉与自我存续钉
  **都红**，`test_the_gate_module_itself_is_collected`（卡 H 的 (a) 半边、B0 整篇的论点）
  第一次有真红读数。宾语选门 6 是因为它不被任何别的门引用，改名不会牵连第二枚判据；
  `def test_…():` 整行在文件里唯一（`_OWN_TEST_NAMES` 里那枚是带引号字符串，无 `def ` 前缀），
  仓库没有任何 pytest 配置文件 ⇒ `python_functions` 取默认 `test*`，前缀匹配 ⇒ 改名确实脱离收集。

- **N8 —— 把 `PIP_INSTALL_EXEMPTIONS["pytest"]` 的"为什么"砍到 `占位`**（4 字 < 12 地板，
  `count` 一字未动）：

  ```
  E   AssertionError: 豁免行 `pytest` 的『为什么』短到不像是理由，像是占位       （:500）
  FAILED tests/test_ci_gate_contract.py::test_every_exemption_row_states_why
  1 failed, 15 passed in 21.23s
  ```

  与 N4 互为反向对照：N4 漂的是"装什么"（形状钉红、同源钉绿），N8 漂的是"为什么允许"
  （理由地板红、形状钉绿）。豁免表是安装面唯一允许出现裸包名的地方，一条没理由的豁免
  = 一条没人负责的口子，这一枚门此前从未被观测到红过。

**N7 的还原是本轮最高风险的一格**（任务书明令：改名若没逐字节还原就是重大事故）。实测：
台子 `finally` 写回原字节后 `sha1 a0b9f37f32bb == 注入前` + `cmp rc=0`；收工再独立核一次
`cmp backend/tests/test_ci_gate_contract.py snap-task6-fix1-post/test_ci_gate_contract.py` **rc=0**、
`grep -c "^def test_"` = **16**、`grep n7_renamed` = **0 枚** ⇒ 改名没留任何痕迹。

### G5. 十六枚门 × 观测到红的溯源（封版用）

"红"分三档来源，**不混为一谈**：`真树红相`=改交付面之前/之中那枚门在真实文件上红；
`变异台`=本台把真文件注入坏形状（Task 4 反证台 A 也属这一档，它改的是门模块自己的字节）；
`合成面反证台`=不动磁盘、把合成输入喂给**真实门函数**（Task 2 V/B/C/D/E 段、Task 3 门 16 反证台）。

| # | 门 | 本轮（Task 6 修复轮 2） | 此前最早的真红读数 | 归档 |
| --- | --- | --- | --- | --- |
| 1 | `test_collected_count_matches_the_pinned_number` | **N1、N7** | T2 修复轮 1 V 段（常数 monkeypatch 回 1329 ⇒ RED）；T3 红相 `1332 ≠ 1331` FAILED | 红过 |
| 2 | `test_the_gate_module_itself_is_collected` | **N7（首次）** | 无（此前从未红过） | **本轮补上** |
| 3 | `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` | — | T2 修复轮 1 §五 真路径反证：给一枚真门挂 `@pytest.mark.skip` ⇒ `1 failed`，红话术"收集面枚数对它们无感" | 红过 |
| 4 | `test_collection_measurement_counts_node_ids_not_the_summary_line` | — | 无 | **helper 自测（见下）** |
| 5 | `test_backend_contracts_has_no_unittest_discover_step` | **N2** | T2 真树红相（ci.yml:43 那枚 `unittest discover` 步） | 红过 |
| 6 | `test_backend_contracts_runs_the_pytest_suite` | — （本轮宾语，未被击杀） | T2 真树红相 `suite_wide == []`；T2 D 组 `-k` 缩子集 ⇒ RED | 红过 |
| 7 | `test_step_ordering_still_explains_itself` | — | T2 修复轮 1 B 组：扫描步挪到主门之后 ⇒ RED；必需锚点被删 ⇒ RED | 红过 |
| 8 | `test_install_face_uses_requirements_txt_as_the_source` | **N3** | T2 真树红相（YAML 仍是手写清单）；C 组"第二份 `-r`" ⇒ RED | 红过 |
| 9 | `test_extra_pip_arguments_are_exactly_the_exemption_table` | **N3、N4** | T2 真树红相（两条死行）；C 组折叠面 / 未豁免包 ⇒ RED | 红过 |
| 10 | `test_install_face_pip_source_values_are_pinned` | — | T2 修复轮 1 C 组四枚敌意形状（`--index-url` / `--extra-index-url=` / `-i` / 第二份 `-r`）**枚枚 RED** | 红过 |
| 11 | `test_every_exemption_row_states_why` | **N8（首次）** | 无（此前从未红过） | **本轮补上** |
| 12 | `test_workflow_plain_scalars_bearing_a_colon_space_are_quoted` | — | T3 修复轮 3 反证台：C/D/E/F 四发 RED 且点名行号，J/K 两枚地板 RED（A/B/G/H/I/L 六发 GREEN） | 红过 |
| 13 | `test_gitattributes_carries_the_required_rules` | **N5** | T2/T3 真树红相（仓库根本没有 `.gitattributes`，Task 4 的活） | 红过 |
| 14 | `test_index_has_no_crlf_entries` | **N6** | T4 反证台 A（真文件把正则退回 `attr/\S*` ⇒ 2 failed）+ B1/B2/B3/B5 合成面 ⇒ RED | 红过 |
| 15 | `test_non_text_index_entries_are_exactly_the_enumerated_set` | **N6** | 同上（与 14 同一枚覆盖度钉，两轮都成对红） | 红过 |
| 16 | `test_eol_rules_are_a_no_op_for_the_current_tree` | — | 无 | **回归守卫（见下）** |

**计数要说平白**：本轮八发观测到红 **9 枚**（溯源表由台子 `print_provenance()` 现算，不是手抄）；
跨 Task 2—6 累计**14/16 有真红读数**。修复轮 1 之前是 12/16，N7/N8 把其中两枚补成 14/16，
**恰好是评审给的那两枚有意义的**（第 2、11 行）。

**剩下两枚为什么可以不是"漏掉的洞"**（任务书要求明写，不许悄悄略过）：

- **门 4 = helper 自测**：它的宾语是**写死在函数体里的四行样本**（两枚 node id + 一空行 +
  `2 tests collected in 0.01s`），断言"解析器认出 2 枚而不是 4 枚"。它红只有一种可能——
  `_NODE_ID` 被改坏。那一形在 T2 修复轮 1 的 A 组已经用**同一枚真实门函数 + 合成输入**证过分野
  （不剥注释时门 4 会红在 `validate_demo_assets` 那一步上），也就是"针确实接得上"；
  它属于**解析器自己的单元测试**，不是交付面上的判据，没有"真实交付面漂移"能把它推红。
  为它造一发变异，等于把一条单元测试包装成门。
- **门 16 = 回归守卫（no-op 证明）**：它的判据是"凡被 `eol=` 管着的文件，工作树形态**已经**等于
  规则要求"，树上合规时它**必须**绿。T4 §1 实测 `checked=2 / offenders=0` 并留了
  `assert checked` 地板，正是"不许把它自己变成空判"的那一枚——**非空性已被独立量过**，
  只是没被观测到红。要让门 16 红，得往树里真写一枚 CRLF 的 `.sh`（改跟踪件字节，本轮禁改面，
  而且那属于 Task 4 §7 的 no-op 判据本身，不属于变异台）。登记为**已知缺口**、不当已解决。

> 规格 §9 的第一行写的是"改名成不以 `test_` 开头，例如 `test_web_security.py` →
> `web_security_hidden.py`"。**本轮的落法与该行的关系要写清**：R19 的 N1 落的是"整枚模块脱离收集"
> 这一机制（`collect_ignore`，日常最容易发生的那种藏），N7 落的是**改名**这一机制——但是门模块
> 自己的**函数名**。文件级改名会把另一枚跟踪测试文件的重命名带上树（本轮禁改面 + 会动收集面常数），
> 所以机制同、宾语降一级。这一条按"与任务书/计划的偏差照登"处理，不宣称逐字对齐 §9 那一行。

### G6. M-3：逐发落盘按代号取 key

`run_node(node, code)` 把 pytest 全文落成 `ent_b0_mutation_<代号>.txt`。八发各一枚、互不覆盖
（本轮实测文件大小 2885 / 946 / 1841 / 611 / 602 / 2149 / 3515 / 654 字节，八份都在），
八份都从临时目录复制进 `tmp/task6fix2-red-N{1..8}.txt` 存档。改前的形态就是修复轮 1 事故本身：
按节点名取 key，而八发的宾语都是同一枚门模块 ⇒ 八份读数盖进同一份、只剩最后一份，
那轮为了找回 N1 的全文把 N1 **重跑了一遍**——重跑不是取证，落盘的必须是当场那份。
现在按代号取 key，并且 §G4 里 N7/N8 的引用行直接从各自存档件里抄。

### G7. M-4：`baseline/collected-node-ids.txt` 重生成（判据一字未变）

| | 改前 | 改后 |
| --- | --- | --- |
| 行数 | **1316**（Task 1 那一份面） | **1332**（当前面） |
| sha1 | `7d414d853c6df0f6999a3fde767aa01f6cd43196` | `953f80ffbf3e8819ac434c7caa2cc0da4c2d6dc0` |
| 字节形态 | LF | LF（CR 字节 **0** / LF 1332） |
| 与当前面的差 | 幽灵"新增 16 枚"、"消失 0 枚" | 新增 0 / 消失 0（**纯超集**：丢了 0 枚、补了 16 枚） |

补进去的 16 枚**全部**是 `backend/tests/test_ci_gate_contract.py::…`（门模块自己在 Task 2 之后才长出来的），
所以这次重生成不可能改变任何判据的输入集合方向。命令就是任务书点名的那条：

```
python scripts/b0_collection_probe.py --node-ids --out .superpowers/sdd/ENTERPRISE_B0_PLAN/baseline/collected-node-ids.txt
→ wrote …baseline\collected-node-ids.txt (1332 node ids)
```

**"这文件只是诊断用、判据不读它"这句 claim 由两枚实测兑现**：
①重生成后立刻复跑整枚门模块 ⇒ **`16 passed in 21.86s`**（0 failed / 0 error / 0 skipped）；
②本轮红相里门 1 的失败信息现在打印 `新增 0 枚：[]`（N1 与 N7 两份存档件都是这一句），
而改前那份幽灵是 `新增 16 枚` ——T3 §五 红相件里就实录过这一句并当场解释过它（"是相对
Task 1 那份 1316 行的差集，不是相对 1331"），本轮把它从"解释掉"变成"不存在"。
判据本体仍是那一条 `len(ids) == EXPECTED_COLLECTED`（门 1 源码一字未动，`EXPECTED_COLLECTED` 仍 1332）。

### G8. 登记为**开放边界**（不实现，归 controller）

评审原话照登（本轮**未实现**，实现它等于改一枚门的判据，越出修复轮授权）：

> The reviewer showed the new floor is still muteable one shape over: a self-consistent tiny fake
> face (one record whose name is also the sole tracked path) passes floor + count + set, so only
> the hardcoded `i/-text` enumeration reddens. Closing it properly means tying `len(tracked)` to an
> independent count such as `git ls-tree -r HEAD`. **Do not implement that** — it changes a gate's
> judgement and belongs to the controller's ruling.

中文口径：R20 那两枚地板只拦"两侧一起空"，拦不住"**自洽的小假面**"——记录一枚、
路径与跟踪面那一枚同名 ⇒ 地板过、等量过、集合等，只有硬编码的 `i/-text` 枚举集合钉会红。
 proper 的闭法是给 `len(tracked)` 找一份**独立第二真相**（例如 `git ls-tree -r HEAD` 的计数），
 与 §14 L6 / R20 F3 末尾那条"集合只比路径不比 `(路径, index 列)`"同族：都属于"没有第二份真相可比"
 的那一族，**登记为已知边界，不当已解决、也不当已修**。

### G9. 零残留 / 纪律 / 注入次数

同一枚只读探针 `tmp/task6_tree_probe.py`（`git ls-files` / `git status` / `git rev-parse`，
**零 git 写命令**）：

```
[before-fix2] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[after-fix2 ] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
[closeout-fix2] tracked=313 WORKTREE-AGGREGATE=d30366c6a440 WORKTREE-AGGREGATE-EX-ID(311)=2685edde76fe
```

（第三时点 `closeout-fix2` 取在快照与全量套件**之后**，三枚口径逐字符同上 ⇒ "写完产物、跑完全量"
也没把树改动一丝一毫。）

- **两枚口径逐字符回到台账值**（R19/R20 登记的就是这两枚）。四枚目标收工字节锚全部回到常数：
  `.gitattributes c5d07b5dc438`/435B/CR0、`ci.yml 1c706e165b73`/7106B/CR147、
  `conftest.py 2ff38f8a68a1`/56751B/CR0、门模块 `699b0dfa8d9e`/50994B/CR0（=R20 的锚）。
- `git status --porcelain` 仍那 **10 行**、行序一字未动；两枚 identity
  `3bc681bbc52c` / `2cfab9f18182` **一字未碰、也没去"修"**。
- **门模块一字未改**（本轮禁改）：`sha1 a0b9f37f32bb…`、与 `snap-task6-fix1-post/` 那份 `cmp` rc=0、
  `def test_` 16 枚、`_OWN_TEST_NAMES` 与 `EXPECTED_COLLECTED = 1332` 均未动 ⇒ 本轮没有"为了让
  N7 好看"去动判据。
- **串行**：八发在一次进程里 `for` 循环，一台同时只有一枚变异在树上；`--check` 与全量套件跑时
  树上无变异。
- **注入总次数 = 32 = 四个完整八发周期**（每一发各一次注入、一次 `finally` 还原、一次
  `sha1 同 + cmp rc=0`，32 次全部通过，无一发触发 `RESTORE-FAILED` / `SystemExit(3)`）。
  四个周期的分工与作废理由逐条写在 G2 末尾：**只有第四周期是正式件**，前三个周期分别被
  仪器自身的三处文案/常数缺陷作废（判决本身每次都相同 ⇒ 作废的从来不是读数含义）。
  另加 4 次 `--check`（不注入、不改树）。
- **全量套件两次**（第一次收在第二周期之后，第二次收在**正式八发 + 快照之前**的终态，任务书那句
  "run it once at the very end"落到终态那一份）：**`1332 passed, 36 warnings, 1133 subtests passed
  in 144.22s (0:02:24)`、rc=0**，`^FAILED` / `^ERROR` 行 **0 枚**（存档件
  `tmp/task6fix2-suite-raw.txt` = 终态那一份；前一份 202.66s 同量、同样 0 枚红）。
  与 R19（121.26s）/ R20（129.53s）同量，差的是宿主并发；收集数没被 N1 的 `collect_ignore`
  或 N7 的改名留痕——**32 次注入之后仍是 1332**，这才是"零残留"的终局判据。
- 本轮**新增/改动文件全部在 gitignored 的 `.superpowers/` 下**（台子、正式表、基线件、报告、台账、
  过程件、快照）⇒ SEC-A 扫描面**零新增豁免**，未碰 `ci.yml` / `.gitattributes` / `backend/app/**` /
  `backend/requirements.txt` / 任何测试文件。

### G10. 产物

- `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py` —— 八发台子（归因仪表 +
  `explain()` + `print_provenance()` + 代号取 key + 重锚常数；docstring 从"多四处"改成"多六处"）
- `.superpowers/sdd/ENTERPRISE_B0_PLAN/mutation-bench.txt` —— 本轮正式表（八发逐行 +
  `8/8 KILLED-ASSIGNED` + 门 × 击杀者溯源）；R19 那份 `6/6 KILLED` 仍逐字节躺在
  `snap-task6-post/mutation-bench.txt`（覆盖前 `cmp` 核过 rc=0）
- `.superpowers/sdd/ENTERPRISE_B0_PLAN/baseline/collected-node-ids.txt` —— 重生成到 1332 行面
- `tmp/task6fix2-check-10of10.txt` / `task6fix2-check-final.txt` —— `--check` 两格读数（后者由终态台子）
- `tmp/task6fix2-red-N1.txt` … `task6fix2-red-N8.txt` —— 八发各自的 pytest 全文（M-3 的直接证据，
  第四周期 = 正式周期的存档）
- `tmp/task6fix2-bench-raw.txt` / `task6fix2-bench-cycle2.txt` / `task6fix2-bench-cycle3.txt` ——
  被作废的前三个完整周期原文（作废理由逐条见 G2 末，判决本身四次都一样）
- `tmp/task6fix2-harness-with-n7n8.py` / `task6fix2-baseline-1316-before.txt` /
  `task6fix2-suite-raw.txt` / `task6-tree-before-fix2.txt` / `task6-tree-after-fix2.txt` /
  `task6-tree-closeout-fix2.txt`
- `snap-task6-fix2-post/` —— 台子 + 重生成后的基线件 + 本报告 + `progress.md` 的字节快照（与源件 `cmp` rc=0）
- `progress.md` 追加 **R21** 一行

**交 controller 的一项**：G8 那枚"自洽小假面"边界（要动判据才能闭，本轮按纪律不动）。
远端 CI 那一格本轮仍无读数（一切读数都是宿主工作树态），归 Task 7。


