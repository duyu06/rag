# Task 4 报告：`.gitattributes` 落地 + 行尾四枚钉转绿 + no-op 双向证明

**时点**：2026-09-28。**形态**：工作树态、**零提交**、**零 git 写命令**（全程只跑 `git status` /
`git ls-files` / `git diff` / `git check-attr` 这四种读命令）。HEAD 仍 `7cc5efc`。
**本任务的里程碑**：16 枚门首次全绿 + 全量套件首次两格全绿。

产物只有一枚仓内文件：`.gitattributes`（LF，435 字节，sha256[:12] `c5d07b5dc438`）。
其余全部证据落在 gitignored 的 `.superpowers/sdd/ENTERPRISE_B0_PLAN/tmp/`（`git check-ignore`
命中 `.gitignore:25`，不进 SEC-A 扫描面）。

---

## 1. `.gitattributes` 的内容与行尾自查

逐字采用 brief Step 2 的代码块（**不是**规格 §7 的代码块，两者的差别见 §7 偏差项 D2）：

```gitattributes
# 归一化由仓库决定，不由每台机器的 core.autocrlf 决定。
* text=auto

# 进镜像/进 Linux 执行的文件必须是 LF：CRLF 的 .sh 在容器里直接跑不起来。
*.sh text eol=lf

# Windows 部署脚本按 Windows 形态签出。
*.ps1 text eol=crlf

# 真二进制。显式声明，不靠 git 猜。
*.png binary
*.jpg binary
*.jpeg binary
*.webp binary
*.ico binary
*.gif binary
*.woff binary
*.woff2 binary
```

字节自查（`open(...,'rb')` 直读，非 `file` 命令的推断）：

| 项 | 实测 |
| --- | --- |
| 总字节 | 435 |
| `CR` 字节数 | **0** |
| `LF` 字节数 | 18 |
| `CRLF` 字节数 | 0 |
| 以换行结尾 | 是 |
| sha256[:12] | `c5d07b5dc438` |
| 编码 | UTF-8（四行中文注释逐行 `repr` 核过，无 BOM、无 mojibake） |

三枚必需规则按行的 `repr` 逐字为 `b'* text=auto'` / `b'*.sh text eol=lf'` / `b'*.ps1 text eol=crlf'`
—— 单空格，正是门 13 用 `{line.strip()}` 集合比对的形状（`strip()` 只削行首尾，不折叠行内空格）。
八枚二进制声明全部以 `binary` 收尾，`rule.split()[0]` 得到的扩展名集合覆盖
`*.png *.jpg *.jpeg *.webp *.ico *.gif *.woff *.woff2`。

**三条刻意的"不做"照单执行**：没给 `*.py` / `*.md` / `*.yml` 加 `eol=`（会改动 120 枚 CRLF 工作树
文件的签出形态 = 被禁止的全量归一）；没加 `*.md text`（会把已封版的 `docs/MODEL_ROUTER_V23_DESIGN.md`
在 index 里改字节，也会把 `ALLOWED_NON_TEXT_INDEX_ENTRIES` 那枚钉死形状拖变形）；
`i/-text` 那三枚继续由形状钉看住，不靠归一化处理。落文件后 `i/-text` 仍是且仅是那三枚（见 §4）。

---

## 2. Step 1：no-op 对照基线（改文件之前取的三件）

取证脚本 `tmp/task4_eol_probe.py before`；同时**逐字**跑了 brief 里的配方做交叉核对，
两者聚合 sha 相等 ⇒ 我的脚本没自创配方。

```
[before] tracked=313 face=317 WORKTREE-AGGREGATE=53bb297dbc72 FACE-AGGREGATE=6625c6e4cbb5
         i/crlf=0 i/-text=3 checked=2 offenders=0
```

`git status --porcelain` 基线原文（7 行，与 Task 3 收工态一字不差）：

```
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

**两枚 identity 未提交改动不是我的**，收工复量仍是开工前的字节：
`backend/app/identity/README.md` → `3bc681bbc52c`、`__init__.py` → `2cfab9f18182`，
与 `task-1-report.md` 登记的基线值**逐字符相等**。

---

## 3. no-op 证明之一：静态半边（门 13/16 不是空判）

门 `test_eol_rules_are_a_no_op_for_the_current_tree` 的判据是"凡被 `eol=` 管着的文件，
工作树形态**已经**等于规则要求"，并在末尾 `assert checked` 防退化。我在探针里按**同一判据**独立重算了一遍：

```
checked=2
offenders=0
```

被数到的两枚（`git ls-files | grep -iE '\.(sh|ps1)$'` 的全部命中）：

| 文件 | 规则要求 | 工作树实测 | 结论 |
| --- | --- | --- | --- |
| `.superpowers/scripts/run_p0_failover_acceptance.sh` | `eol=lf` | 0 枚 CR | 已满足 ⇒ 规则零影响 |
| `scripts/deploy.ps1` | `eol=crlf` | LF 枚数 == CRLF 枚数（无裸 LF） | 已满足 ⇒ 规则零影响 |

`checked=2 ≠ 0` ⇒ 这枚门**不是空判**（`offenders=0` 是"真的核过两枚且都合规"，不是"什么都没核上"）。
与规格 §7 设计决定 3 的实测口径（`.sh` 仅 1 枚且已 LF、`.ps1` 仅 1 枚且已 CRLF）一致。

另取一枚正面证据，证明这文件是**活的**而不是写了好看：

```
$ git check-attr text eol -- scripts/deploy.ps1 .superpowers/scripts/run_p0_failover_acceptance.sh backend/app/main.py
scripts/deploy.ps1: text: set            scripts/deploy.ps1: eol: crlf
.superpowers/scripts/run_p0_failover_acceptance.sh: text: set   ...: eol: lf
backend/app/main.py: text: auto          backend/app/main.py: eol: unspecified
```

即：两条 `eol=` 规则确实挂到了那两枚文件上，`* text=auto` 确实挂到了 `.py` 上而**没有**给它定 `eol`
—— 这正是"归一化从机器属性变成仓库属性、但不改签出形态"的形状。

---

## 4. no-op 证明之二：动态半边（前后逐行 / 逐字节对照）

### 4.1 `git status --porcelain`

raw diff（brief 期望它为空，实测不可能为空，见偏差 D3）：

```
$ diff /tmp/b0-eol-before-status.txt /tmp/b0-eol-after-status.txt
3a4
> ?? .gitattributes
raw diff exit=1
```

**字面结论**：唯一差异是新增的那一行 `?? .gitattributes`（未跟踪 ⇒ 它不进 index，零提交纪律未被破坏）。
按 brief 的口径排除这一行后再比：

```
$ grep -v '^?? \.gitattributes$' <after> | diff <before> -
STATUS 逐行相同
```

排除的就是 `?? .gitattributes` 这一枚；除此之外**没有**为了对上数而改动任何东西。
收工再量一次（证伪实验 + 两格全量套件都跑完之后）：

```
$ diff before-status <(grep -v '^?? \.gitattributes$' closeout-status)
STATUS 仍逐行相同(排除新文件)
```

并且用 `cat -A` 逐行验过行首空格真实存在（`' M .github/workflows/ci.yml$'`），排除了我自己
探针里 `status.strip()` 吃掉首行行首空格造成的**显示**假象（见偏差 D7）。

### 4.2 聚合 sha（brief Step 1 的配方，跟踪件）

```
before: WORKTREE-AGGREGATE 53bb297dbc72
after : WORKTREE-AGGREGATE 53bb297dbc72
closeout: WORKTREE-AGGREGATE 53bb297dbc72
```

**逐字符相等**。机理要说清：`.gitattributes` 是未跟踪件，`git ls-files` 根本不数它，
所以这条 sha 的相等 = "既有 313 枚跟踪件的字节一枚都没变"的硬证物，不含任何"新文件把哈希冲掉了"的余地。

### 4.3 逐文件 sha 清单（把"除新文件外逐文件不变"钉到枚）

覆盖面换成 `git ls-files -c -o --exclude-standard`（跟踪 ∪ 未忽略的未跟踪 = SEC-A 扫描面同源），
逐枚取 sha256[:12]：

```
$ diff b0-eol-before-manifest.txt b0-eol-after-manifest.txt
0a1
> c5d07b5dc438  .gitattributes

$ diff b0-eol-before-manifest.txt b0-eol-closeout-manifest.txt
0a1
> c5d07b5dc438  .gitattributes

$ diff b0-eol-after-manifest.txt b0-eol-closeout-manifest.txt
IDENTICAL
```

- 覆盖面 317 → 318，**只多一枚名**，317 枚既有名的 sha **一行都没变**（`0a1` 是纯新增 hunk，
  无 `c`/`d` 行 ⇒ 无改写、无删除）。
- `after` 与 `closeout` 逐字节相同 ⇒ 中间的证伪实验和两格全量套件**没在树上留任何东西**。
- FACE-AGGREGATE 从 `6625c6e4cbb5`（317 枚）变 `1898e1960f7b`（318 枚），差异完全来自那枚新增名。
- 扫描面计数：Task 1 记 316 → Task 2 加门文件成 317 → 本任务加 `.gitattributes` 成 **318**，
  与任务书给的"surface was 317"吻合；SEC-A 整模块 46 绿、**未新增任何豁免行**（§5）。

### 4.4 `git diff`：补丁正文两态逐字相同

规格 B0-007 的判据是"与基线相同"而非"干净"，而 brief Step 1 的三件基线里**没有** `git diff` 的内容，
所以这一步不能靠 before/after 两次采样比出来。补做一次 A/B：把本次自己新建的 `.gitattributes`
临时挪出仓库（同盘的仓外目录）复现 before 态，取补丁后**按读到的原字节写回并 `cmp`**。

```
== git diff 补丁正文（stdout）两态对照 ==
有 .gitattributes：10107 字节  sha=dfa0fbde86b5
无 .gitattributes：10107 字节  sha=dfa0fbde86b5
补丁逐字相同: True

== git diff stderr 两态对照 ==
有：warning: ... 'backend/app/identity/README.md', LF will be replaced by CRLF the next time Git touches it
    warning: ... 'backend/app/identity/__init__.py', LF will be replaced by CRLF the next time Git touches it
无：（同上两行，一字不差）

== 还原校验 ==
cmp 仓外副本 vs 还原后文件：rc=0 输出=''
字节等值 (back == original): True   435 字节  sha=c5d07b5dc438
```

三条结论：
1. 补丁正文两态 **10107 字节 / sha `dfa0fbde86b5` 逐字相同** ⇒ `git diff` 不因这枚文件改变。
2. `git diff --stat` 的两态都是同一组既有改动：`.github/workflows/ci.yml`（Task 3 留下的）、
   `backend/app/identity/README.md`、`__init__.py`（飞书对接留下的）——**不是**本次造成的；
   本次没让任何既有跟踪文件新进出 diff。
3. 那两枚 `LF will be replaced by CRLF` 提示**两态一字不差 ⇒ 不是 `.gitattributes` 带来的**，
   它们是 `core.autocrlf=true`（实测本仓该值确为 `true`）在两枚 LF 工作树文件上本就有的噪声。
   这条纠正了一个很容易写错的归因：看到落文件后终端出现新提示就判"我改了 diff 语义"。

---

## 5. Step 3 / 门读数

四枚行尾钉（brief Step 3 原命令）：

```
$ python -m pytest backend/tests/test_ci_gate_contract.py -q -k "gitattributes or crlf or non_text or no_op"
4 passed, 12 deselected in 1.12s
```

门模块（本任务的核心里程碑）：

```
$ python -m pytest backend/tests/test_ci_gate_contract.py -q
16 passed in 31.91s      # 归档复跑：16 passed in 31.74s（tmp/task4-gate-module-final.txt）
```

**16 passed / 0 failed** —— 自 B0 开工以来首次全绿（Task 2/3 的终态一直是 `1 failed, 15 passed`，
唯一红就是 `test_gitattributes_carries_the_required_rules`，红因正是"`.gitattributes` 不存在"）。
另外三枚行尾钉的读数性质要说清：它们在 Task 2/3 期间**本来就是绿的**，本任务没有让它们变绿，
而是证明了它们**仍然是绿的**（即这枚文件没有把 index 形状拖变形）：`i/crlf` 计数 0、
`i/-text` 集合恰等于三枚钉死名、静态 no-op 的 `checked=2 / offenders=0`：

```
index_rows=313
i/crlf=0 []
i/-text=3
.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md
docs/MODEL_ROUTER_V23_DESIGN.md
frontend/public/yaoke-logo.webp
```

SEC-A 模块（含 `.gitattributes` 落进扫描面之后）：

```
$ python -m pytest backend/tests/test_secret_hygiene_contract.py -q
46 passed in 28.70s      # 归档复跑：46 passed in 28.08s（tmp/task4-seca-module-final.txt）
```

**46 passed**、零 skip、**没有新增任何豁免行**。`.gitattributes` 的内容（四行中文注释 + 规则行）
不含任何凭据形状，SEC-A 的门跟着整模块一起绿。

---

## 6. 全量套件两格（首次全绿）

| 格 | cwd | 命令 | 读数 | 用时 |
| --- | --- | --- | --- | --- |
| 1 | 仓库根 `E:/xiangmu/rag` | `python -m pytest backend/tests -q` | **1332 passed**, 36 warnings, 1133 subtests passed，rc=0，无 FAILED/ERROR 行 | 首跑 186.18s；归档复跑 **181.49s** |
| 2 | `E:/xiangmu/rag/backend` | `python -m pytest tests -q` | **1332 passed**, 36 warnings, 1133 subtests passed，rc=0，无 FAILED/ERROR 行 | 归档复跑 **179.40s**（首跑读数被 stderr 交错挡住，见偏差 D6） |

两格日志已归档：`tmp/task4-suite-cell1-rootcwd.txt`、`tmp/task4-suite-cell2-backendcwd.txt`，
每格都单独用 `grep -E '^(FAILED|ERROR)'` 扫过：**none**。

`36 warnings` 与 `1133 subtests` 在两格完全相等，`passed` 数与 `EXPECTED_COLLECTED = 1332` 一致。
两格 rc 均为 0。这 **是** B0 的第一次全绿读数，没有靠任何手段凑：没改门、没改 `EXPECTED_COLLECTED`、
没加豁免、没 skip 任何断言、没动 `backend/app/**`。

`python -m pytest --collect-only -q` 意义上的 1332 由 Task 3 标定（1316 + 16 枚门），本任务零新增用例，
所以收集数不变本身就是"我没往套件里塞东西"的旁证。

---

## 7. Step 5：证伪（B0-007 的可红性）

脚本 `tmp/task4_falsify_gate13.py`：预检 sha → 摘规则 → 跑门 → **`finally` 里按开头 `read_bytes()`
读到的原字节写回**（不从 git 取，git 里根本没有这枚未跟踪文件）→ `cmp` 三重校验 → 复跑同一门。

```
预检 sha=c5d07b5dc438 期望=c5d07b5dc438
已摘除 `*.sh text eol=lf` 一枚规则：435 → 419 字节
红相 pytest rc=1（非 0 = 门确实转红）
```

红相输出**字面**（全文存 `tmp/b0-eol-falsify-gate13-red.txt`；下面这份是从该 UTF-8 文件里以
UTF-8 解出来的，控制台按 cp936 直显会 mojibake，故此处给可读版，字节以归档文件为准）：

```
F                                                                       [100%]
================================== FAILURES ===================================
________________ test_gitattributes_carries_the_required_rules ________________

    def test_gitattributes_carries_the_required_rules():
        assert GITATTRIBUTES_FILE.is_file(), "没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定"
        rules = {line.strip() for line in GITATTRIBUTES_FILE.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.strip().startswith("#")}
        missing = [rule for rule in REQUIRED_GITATTRIBUTES_RULES if rule not in rules]
>       assert not missing, f".gitattributes 缺必需规则：{missing}"
E       AssertionError: .gitattributes 缺必需规则：['*.sh text eol=lf']
E       assert not ['*.sh text eol=lf']

backend\tests\test_ci_gate_contract.py:669: AssertionError
=========================== short test summary info ===========================
FAILED backend/tests/test_ci_gate_contract.py::test_gitattributes_carries_the_required_rules
1 failed, 15 deselected in 1.13s
```

**红了，且红在正确的那一枚门上**：点名到 `test_gitattributes_carries_the_required_rules`、
断言文本里逐字复现了被摘掉的那枚规则串 `['*.sh text eol=lf']`。这枚门不是"恒绿摆设"。

还原校验**字面**：

```
cmp 动手前副本 vs 还原后文件：rc=0 输出=''
字节等值 (back == original): True
还原后字节数 435（原 435）  sha256[:12]=c5d07b5dc438（期望 c5d07b5dc438）
CR 字节数 0  LF 字节数 18
三条必需规则回位: [True, True, True]
还原后重跑同一门：
1 passed, 15 deselected in 0.53s
```

**我确认做了还原并逐字节验到了**：还原依据是实验开头 `read_bytes()` 读到的原字节（另存一份
`tmp/task4_falsify_premark_gitattributes` 作 `cmp` 参照），不是 git；`cmp` rc=0 且
`back == original` 为 True。还原后 `git status --porcelain` 回到 8 行、聚合 sha 仍是 `53bb297dbc72`
（§4.2/4.3 的 closeout 两列）。实验中途若被打断，树上会留一枚缺规则的 `.gitattributes`（比不做更坏），
所以写回放在 `finally`，且脚本自带预检：sha 不是 `c5d07b5dc438` 就直接退出、不动文件。

---

## 8. brief 的配方与实况不符之处（逐条，都是实测出来的）

- **D1｜Step 1 说的"基线在 `task-1-report.md`"取不到。** 我把 `task-1-report.md` 全文正则扫了一遍：
  12 位 sha 只有 `4d7f974107dd`（`backend/.env`）、`3bc681bbc52c` / `2cfab9f18182`（两枚 identity）、
  `a62e3e228e5e`（探针脚本），**没有** `WORKTREE-AGGREGATE`；`task-1/2/3-report.md` 与 `progress.md`
  全文也搜不到该配方跑过的痕迹（`MISSING` 那行只在 brief 自己里出现）。
  ⇒ 基线 `53bb297dbc72` 由**本任务 Step 1 现场取**，并靠两枚 identity sha 与 Task 1 登记值相等、
  7 行 status 与 Task 3 收工态逐行相等这两条独立锚点确认"我确实是从已知基线起算的"。
- **D2｜规格 §7 的代码块与门 13 的比对方式冲突，brief 的版本才对。** §7 第 165 行写的是
  `*.sh␣␣text␣eol=lf`（**两枚**空格），而 `*.ps1 text eol=crlf` 是一枚。门 13 用
  `{line.strip()}` 集合比字符串，`strip()` 不折叠行内空格 ⇒ 照 §7 逐字落盘会当场红
  （缺 `['*.sh text eol=lf']`）。我按 brief/门（可执行契约）落单空格。
  规格 §7 那处是排版瑕疵，属"文档内部不一致"，留给后续勘误，**不改规格文件**（规格已封版）。
- **D3｜Step 4 期望"`git diff` 对既有跟踪文件为空"字面做不到。** 基线本来就不干净
  （ci.yml + 两枚 identity），规格 §4 B0-007 自己也说了判据是"与基线相同"。
  ⇒ 按 §4.4 的 A/B 实测：补丁正文 10107 字节 / `dfa0fbde86b5` 两态逐字相同。
- **D4｜Step 4 的字面命令 `diff a b && echo "STATUS 逐行相同"` 走不到 `echo` 那支。**
  raw diff exit=1（多一行），必须先 `grep -v` 再比。两版输出都按字面登记在 §4.1。
- **D5｜Step 5 末行 `git diff --exit-code .gitattributes && echo "还原一致"` 是不可靠判据。**
  `.gitattributes` **未跟踪**（本任务零提交），`git diff` 只看跟踪文件 ⇒ 它对这枚文件**恒**返回 0，
  哪怕内容被摘掉一枚规则也照样"还原一致"。这条如果照跑，得到的是一枚**假绿**。
  ⇒ 换成不依赖 git 的真字节校验：动手前副本 `cmp`（rc=0）+ `back == original`（True）+ sha 复量。
- **D6｜brief 用 `| tail -N` 取套件末行读数在 Windows 上会被 stderr 交错挡住。**
  格 2 首跑 `tail -4` 只捞到 `[credential-guard]` 噪声（stderr 不经缓冲、排在 stdout 汇总行之后）。
  ⇒ 改成 `> 日志 2>&1` 再按 `grep -E '\d+ (passed|failed)'` 取汇总行，两格各取到唯一一行。
- **D7｜我自己的探针有两处自造噪声，都当场治好并留了字面证据。**
  ① `write_text()` 在 Windows 上把清单写成 CRLF，导致 `grep -v '\.gitattributes$'` 锚不到行尾、
  误报"整份清单 317 行全变"；改为直接 `diff` 两份清单后得到正确的 `0a1` 纯新增 hunk，
  并 `file` + 字节计数确认清单确为 CRLF（318 枚）、status 取证文件为 LF（0 枚）。
  ② 证伪脚本用 `status.strip()` 打印，吃掉了首行行首那个空格，看着像 `M` 变基线首列；
  用 `cat -A` 复核真实行是 `' M .github/workflows/ci.yml$'`，属显示假象、树未变。
- **D8｜`os.replace` 跨卷被 Windows 拒（WinError 17）。** §4.4 把新文件挪到 `%TEMP%`（C: 盘）时报
  "系统无法将文件移到不同的磁盘驱动器"；失败点 `finally` 已把原字节写回并复量到
  `435 / c5d07b5dc438 / CR 0`，随后把 park 目录改到同盘的仓外 `E:\xiangmu\` 才跑通。
  这算一次"实验中途被打断"的实况演练：**任何一次失败都没有让树留在缺规则的坏态上**。
- **D9｜探针脚本的位置。** 我最初把取证脚本写进 `scripts/`，立即意识到它会进 SEC-A 扫描面
  （跟踪面 ∪ 未忽略未跟踪面），把 §4.3 的覆盖面从 318 再抬到 319、并可能在别人的门上制造红。
  已删除并改放 gitignored 的 plan `tmp/` 下，删后 `git status --porcelain` 复回开工前 7 行。
  任务书要求"只创建 `.gitattributes` + 工作区过程件"，这条算我自己加的约束。

---

## 9. 逐步判定汇总

| Step | 判据 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 三件基线在改文件前取齐 | status 7 行 / `WORKTREE-AGGREGATE 53bb297dbc72` / 清单 317 枚；brief 配方交叉核对同值 | GREEN |
| 2 | 内容与规则逐字一致、文件本身 LF | 435 字节、CR 0、LF 18、三枚必需规则单空格、八枚 `binary` | GREEN |
| 3 | 行尾四枚钉 4 passed | `4 passed, 12 deselected in 1.12s` | GREEN |
| 4a | status 逐行相同（除新增枚） | raw diff `3a4 > ?? .gitattributes`；排除后 `STATUS 逐行相同`；closeout 复验同 | GREEN |
| 4b | 聚合 sha 不变 | `53bb297dbc72` 三时点逐字符相等 | GREEN |
| 4c | 逐文件不变 | 清单 `0a1` 纯新增一枚；`after` vs `closeout` IDENTICAL | GREEN |
| 4d | `git diff` 与基线相同 | 两态 10107 字节 / `dfa0fbde86b5` 逐字相同；stderr 两行警告两态一字不差 | GREEN |
| 5 | 摘一枚必需规则 ⇒ 门红 ⇒ 逐字节还原 | rc=1、点名门 13、缺 `['*.sh text eol=lf']`；`cmp` rc=0 + 字节等值 + sha 复量 `c5d07b5dc438`；复跑 1 passed | GREEN |
| 6 | 静态 no-op 非空判 | `checked=2 / offenders=0`，两枚 `.sh`/`.ps1` 形状已合规 | GREEN |
| — | 门模块全绿 | **16 passed / 0 failed** | **GREEN（里程碑）** |
| — | 全量两格 | **1332 passed × 2**，36 warnings / 1133 subtests 两格相等，rc=0，无 FAILED/ERROR | **GREEN（首次）** |
| — | SEC-A 模块 | **46 passed**，扫描面 318 枚，未新增豁免行 | GREEN |
| — | 零 git 写命令 / 零提交 / identity 两枚不变 | HEAD 仍 `7cc5efc`；identity `3bc681bbc52c` / `2cfab9f18182` 复量同值 | GREEN |

**B0-006 / B0-007 双双闭合**：文件存在且含 §7 全部必需规则、`i/crlf=0`、`i/-text` 恰等于枚举三枚；
no-op 三判据（status 逐行、diff 正文、工作树字节）各自有独立测法与字面物证。

---

## 10. 证据清单（全部 gitignored，不进仓）

| 文件 | 内容 |
| --- | --- |
| `tmp/task4_eol_probe.py` | 五件取证（status / 聚合 sha / 逐文件清单 / index 形状 / no-op 计数），before、after、closeout 三时点 |
| `tmp/task4_diff_ab.py` | `git diff` 正文两态 A/B（同盘挪出 + `finally` 写回 + `cmp`） |
| `tmp/task4_falsify_gate13.py` | Step 5 证伪（预检 → 摘规则 → 跑门 → 写回 → `cmp` → 复跑） |
| `tmp/b0-eol-{before,after,closeout,endstate}-{status,agg,manifest,eol,eolrules}.txt` | 四时点原始读数（before = 未落文件；endstate = 全部收尾动作之后） |
| `tmp/b0-eol-diff-{with,without}.txt` | 两态 `git diff` 补丁正文（各 10107 字节） |
| `tmp/b0-eol-falsify-gate13-red.txt` | 红相原始输出 |
| `tmp/task4_falsify_premark_gitattributes` | 证伪动手前的字节副本（`cmp` 参照物） |
| `tmp/task4-gate-module-final.txt` / `tmp/task4-seca-module-final.txt` | 16 绿 / 46 绿的模块日志 |
| `tmp/task4-suite-cell{1,2}-*.txt` | 两格全量套件日志 |
| `snap-task4-post/gitattributes` | `.gitattributes` 终态快照（与源文件 `cmp` 逐字节相同） |

未做的事（按约束刻意不做）：任何 `git add` / `commit` / `push` / `stash` / `checkout` / `restore` /
`clean` / `config`；`git add --renormalize`；改 `ci.yml`、门文件、`backend/app/**`、
`backend/tests/**`、`requirements.txt`、`docker-compose.yml`、`scripts/**`、`frontend/**`；
放宽或跳过任何断言；给 SEC-A 加豁免行。

### 10.1 收工后的最后一次终态复核（写完本报告与台账、建完快照之后）

```
[endstate] tracked=313 face=318 WORKTREE-AGGREGATE=53bb297dbc72 FACE-AGGREGATE=1898e1960f7b
           i/crlf=0 i/-text=3 checked=2 offenders=0
$ diff b0-eol-closeout-manifest.txt b0-eol-endstate-manifest.txt
清单与收工态 IDENTICAL（台账/快照未动扫描面）
$ python -m pytest backend/tests/test_ci_gate_contract.py -q
16 passed in 36.30s
.gitattributes 终态 435 bytes sha c5d07b5dc438 CR 0
backend/app/identity/README.md   3bc681bbc52c
backend/app/identity/__init__.py 2cfab9f18182
$ git status --porcelain | cat -A        # 行首空格逐枚在场，8 行 = 7 行基线 + ?? .gitattributes
```

这一跑的用意是排除"报告/快照本身把状态搞漂"：台账与报告都落在 `.gitignore:25` 的 `.superpowers/` 里
（`git check-ignore -v` 命中，`git ls-files -c -o --exclude-standard` 不数它们），覆盖面仍 318 枚、
聚合 sha 仍 `53bb297dbc72`、逐文件清单与收工态逐字节相同。两格全量套件之后又跑过证伪和台账写入，
但清单 `IDENTICAL` 说明套件读到的东西一件没变，§6 的两格读数继续成立。

顺带把"我没碰不该碰的东西"也从清单里量出来（四个时点 `before / after / closeout / endstate` 逐枚相同）：

| 约束物 | 四时点 sha256[:12] | 说明 |
| --- | --- | --- |
| `.github/workflows/ci.yml` | `1c706e165b73` | 未动 Task 3 的成果 |
| `backend/tests/test_ci_gate_contract.py` | `4c98f1439494` | 与台账 R11 登记值相等 ⇒ 门文件一字未改、没摘任何断言 |
| `docs/MODEL_ROUTER_V23_DESIGN.md` | `e9c21dad395f` | 已封版 V2.3 工件字节未变 ⇒ "不加 `*.md text`"这条决定是真的起了作用 |

留给后事的提醒：**这枚文件至今未跟踪**。真要入库需要显式 `git add .gitattributes`，
而那一步会把它带进 index 归一化（它自身是 LF 且 `* text=auto` 判定为文本 ⇒ index 与工作树同形，
不产生 renormalization 副作用）；本任务无提交权限，**没做**，仅在此登记。

## Task 4 修复轮 1

**裁定出处**：规格 `docs/ENTERPRISE_B0_SPECIFICATION.md` §16 **卡 K**（第 425-436 行）+ §6.4 新增的
"解析覆盖度本身是判据"（第 155-157 行）。**轮次**：修复轮 1/5。**形态**：工作树态、**零提交**、
**零 git 写命令**（只跑 `git status` / `git diff` / `git ls-files` / `git check-ignore` / `cmp`），
HEAD 仍 `7cc5efc`。**本轮只动一枚文件**：`backend/tests/test_ci_gate_contract.py`。

### 1. 缺陷（照裁定的原话复述，再加本轮实测）

`_EOL_LINE` 用 `attr/\S*` 抽属性列。`.gitattributes` 在场前该列恒无空格 ⇒ 313 行全解析；
规则生效后 `*.sh text eol=lf` / `*.ps1 text eol=crlf` 两枚路径的列变成 `attr/text eol=lf` /
`attr/text eol=crlf`（**含空格**）⇒ 那两行整体不匹配、`_index_eol_rows()` 静默返回 311 枚，
丢的恰好是全仓对行尾最敏感的两枚文件。两枚消费门（`test_index_has_no_crlf_entries` /
`test_non_text_index_entries_are_exactly_the_enumerated_set`）在两枚 `i/lf` 上不违反任何不变式
⇒ **绿着变瞎**。本轮在真实 listing 上按旧式正则复量，字面读数：

```
旧式正则 attr/\S* 解析 311 行 / 313 条记录，未匹配 2 条：
    丢行 -> i/lf    w/lf    attr/text eol=lf       \t.superpowers/scripts/run_p0_failover_acceptance.sh
    丢行 -> i/lf    w/crlf  attr/text eol=crlf     \tscripts/deploy.ps1
```

### 2. 改了什么（三段，缺一不可）

**2.1 正则（形状修好，但它是次要的）**

```python
# 改前
_EOL_LINE = re.compile(r"^(i/\S+)\s+(w/\S+)\s+(attr/\S*)\s*\t(.+)$")
# 改后
_EOL_LINE = re.compile(r"^(i/\S+)\s+(w/\S+)\s+(attr/[^\t]*?)\s*\t(.+)$")
```

列的终点从"下一个空白"改成"记录里那枚制表符"。**tab 是查过的、不是假设的**：
`git ls-files --eol` 每条记录恰含 **1 枚字面 tab**（`sorted({r.count(b"\t") for r in records}) == [1]`，
实测样本 `b'i/lf    w/crlf  attr/text eol=crlf    \tscripts/deploy.ps1'`）。选 `[^\t]*?` 而不是 `.*?`
是为了把"绝不跨 tab 去吃路径"写进模式本身：属性列里空格合法、tab 不合法。

**2.2 主判据 = 解析覆盖度（卡 K 点名的那一条，落在 helper 里，不加门）**

`_index_eol_rows()` 现在先钉覆盖面再返回数据：解析出的**条数**必须等于 `git ls-files` 的跟踪条数，
且两侧**路径集合相等**，不等即红。它不假设属性列长什么样，所以任何未来的丢行（换 git 版本、
换列序、新字段带空格）都只会响亮地红。失败信息同时给三个数 + 未解析记录样本 + 缺/多两侧的路径。

判据取"逐条计数 + 路径集合"两道，理由都写在 helper 的 docstring 里，摘两句关键的：
- 计数按**记录条**（`parsed` 列表）而不是按字典条目算 ⇒ 合并冲突态一枚路径在两侧各出现多枚 stage 条目时
  不会假红（本仓库的账是"假红最贵"：假红 → 有人加豁免 → 真形状跟着漏）。
- 只加计数会漏"读到了但读歪了"（比如列跨了 tab、把路径前缀吃进列里），那时条数仍是 313；
  **集合相等**才抓得到这一族。B5 的实测就是两条同时咬。

**2.3 口径：两侧同用 `-z`（本轮选的是这条路，不是"归一化引号"）**

新增两枚接缝 `_index_eol_records()` / `_tracked_paths()`，都走同一枚 `_git_z_records()`，
即 `git ls-files --eol -z` 与 `git ls-files -z`，按 NUL 切记录、按原始字节解码。
**为什么不能一边明文一边 `-z`**（实测）：默认 `core.quotePath=true` 把非 ASCII 路径八进制转义并套双引号，
本仓实测 **20 枚**这样的路径。

```
明文面（会引号转义）非 ASCII 路径枚数 = 20
-z 面（关引号）里以引号开头的记录枚数 = 0
-z 面非 ASCII 路径枚数 = 20，例：['demo-data/01-差旅费用管理制度.md', 'demo-data/02-售后退款SOP.md']
明文面解析键中带引号者 = 20 枚 ⇒ 拿它与 -z 的 tracked 集合直接比会全差；两侧同用 -z 才同口径
明文面键集合 == -z 面键集合 ? False
```

**没有弱化任何判据**：`i/crlf` 仍须为 0、`i/-text` 仍须恰等于枚举三枚，两枚消费门的正文一字未改
（只各加一句 docstring 点名覆盖度钉）；**没有**给 `scripts/deploy.ps1` 或
`.superpowers/scripts/run_p0_failover_acceptance.sh` 加任何白名单/豁免。

### 3. 前后行数对照（本轮的里程碑数字）

| 量法 | 改前 | 改后 |
| --- | --- | --- |
| `_index_eol_rows()` 返回行数（真实 listing） | **311**（旧正则，实测复现） | **313** |
| `git ls-files` 跟踪面 | 313 | 313 |
| 覆盖度钉 | 不存在（⇒ 丢行无感） | 313 == 313 且集合相等 ⇒ GREEN |
| 找回的两枚路径 | — | `scripts/deploy.ps1`、`.superpowers/scripts/run_p0_failover_acceptance.sh`（两枚都 `i/lf`） |
| `i/crlf` 枚数 | 0（瞎着说绿） | **0（在 313 枚覆盖面上诉绿）** |
| `i/-text` 集合 | 三枚（同上） | 同样三枚，覆盖面完整 |

### 4. 反证台 A（落盘注入旧正则 ⇒ 门红；复原 ⇒ `cmp` 证明）

脚本 `%TEMP%\b0t4f1\probe_falsify_on_disk.py`：把门文件里那行 `_EOL_LINE` **按字节**换成旧式
`attr/\S*`（注入点唯一性用 `assert original.count(CURRENT) == 1` 预检），跑整枚门模块，
`finally` 里按原字节写回并 `cmp`。字面输出（关键行）：

```
备份 C:\Users\zhang\AppData\Local\Temp\b0t4f1\gate_before_falsification.py
  开工门文件 sha256(12)=73bede2def2e 字节=48603 CR=0 LF=810
注入后应掉的字节差 = 4
已注入旧式正则：sha256(12)=74e5b0cb39fe 字节=48599
===== 反证台 A：正则退回 attr/\S*（模拟卡 K）：rc=1 =====
E       AssertionError: 行尾门的解析覆盖度掉了（卡 K 的那一形）：`git ls-files --eol` 共 313 条记录、
        正则解析出 311 条（未解析 2 条），`git ls-files` 跟踪面 313 枚 ⇒ 两侧必须**逐条等量且路径集合相等**。
E         未解析记录样本（前 5 条）：['i/lf    w/lf    attr/text eol=lf      \t.superpowers/scripts/run_p0_failover_acceptance.sh',
                                     'i/lf    w/crlf  attr/text eol=crlf    \tscripts/deploy.ps1']
E         跟踪面有而解析面缺（前 10）：['.superpowers/scripts/run_p0_failover_acceptance.sh', 'scripts/deploy.ps1']
E         解析面有而跟踪面无（前 10）：[]
E       assert (311 == 313)
FAILED backend/tests/test_ci_gate_contract.py::test_index_has_no_crlf_entries
FAILED backend/tests/test_ci_gate_contract.py::test_non_text_index_entries_are_exactly_the_enumerated_set
2 failed, 14 passed in 36.36s
===== 复原 =====
  cmp C:\Users\zhang\AppData\Local\Temp\b0t4f1\gate_before_falsification.py vs 门文件  -> rc=0（0 = 逐字节相同）
  复原后 sha256(12)=73bede2def2e 字节=48603 CR=0 LF=810
  备份与门文件同 sha = True
===== 复原后复跑门模块（终态读数）：rc=0 =====
16 passed in 36.42s
```

⇒ **方向 (a) 成立**：属性列一含空格、解析一掉行，红落在两枚消费门上（经同一枚 helper 的覆盖度钉），
且红的话点名被丢的两枚路径。

### 5. 反证台 B（合成 listing 丢一行 ⇒ 覆盖度钉红；两个方向都量）

脚本 `%TEMP%\b0t4f1\probe_falsify_memory.py`：替换 `_index_eol_records` / `_tracked_paths` 两枚接缝
（它们是接缝、不是判据本体），直接调门函数。字面输出（关键行）：

```
开工基线：--eol 记录 313 条 / 跟踪面 313 枚 / 解析行 313 行
新正则  ：^(i/\S+)\s+(w/\S+)\s+(attr/[^\t]*?)\s*\t(.+)$
旧正则  ：^(i/\S+)\s+(w/\S+)\s+(attr/\S*)\s*\t(.+)$
--- B0 真实面（修后的正则，未注入） ---        GREEN ×2
--- B1 合成 listing 丢掉一行（scripts/deploy.ps1）；丢行后解析行数 = -1 ---
  RED   test_index_has_no_crlf_entries
        …共 312 条记录、正则解析出 312 条（未解析 0 条），`git ls-files` 跟踪面 313 枚 ⇒ 两侧必须逐条等量且路径集合相等。
  RED   test_non_text_index_entries_are_exactly_the_enumerated_set   （同一枚覆盖度钉）
--- B2 合成 listing 丢掉一行（.superpowers/scripts/run_p0_failover_acceptance.sh）--- 同上 RED ×2
--- B3 反方向：跟踪面多一枚幻影路径（钉不只认一个方向）---
  RED   test_index_has_no_crlf_entries   …解析出 313 条…跟踪面 314 枚
--- B4 全虚构 listing（3 条带空格属性列的记录 vs 真实跟踪面 313 枚）---
  新正则对虚构空格列的解析结果： [('attr/text eol=lf', 'foo/a.sh'), ('attr/text eol=crlf', 'foo/b.ps1'), ('attr/text=auto', 'foo/c.py')]
  RED    …共 3 条记录、正则解析出 3 条（未解析 0 条），`git ls-files` 跟踪面 313 枚
--- B5 只把正则换回旧式 attr/\S*（数据面一字不动）---
  旧式正则解析 311 行 / 313 条记录，未匹配 2 条：（两枚丢行原文见 §1）
  覆盖度 RED   …共 313 条记录、正则解析出 311 条（未解析 2 条）…
  RED ×2（两枚消费门）
--- 复原（finally 等价）---
  复原后解析行 = 313 / 记录 = 313
  GREEN test_index_has_no_crlf_entries
  GREEN test_non_text_index_entries_are_exactly_the_enumerated_set
  门文件字节 开工 48603 / 收工 48603 相同 = True
```

⇒ **方向 (b) 成立**（B1/B2/B4 = 丢行即红，B3 = 反方向也红，B5 = 只换正则即红）。
B4 还顺带答了"覆盖度钉会不会只是依赖真实 git 状态"：整面虚构时它照样红，而新正则对
**虚构的空格属性列**也解析正确（形状不靠真实数据兜）。

### 6. D5 假绿台的现场复证（为什么复原只用 `cmp`）

门文件**未被跟踪**，所以 `git diff --exit-code` 对它的任何改动恒返 0（Task 4 brief 九处偏差里的 D5）。
本轮当场复证（`%TEMP%\b0t4f1\probe_d5_gitdiff_trap.py`，注入一枚无意义空格再写回）：

```
注入后 字节 48603 -> 48604（真改动）
  git diff --exit-code rc=0 输出=''   ← 改动存在却被判『无差异』= D5 假绿
  git status --porcelain  rc=0 行='?? backend/tests/test_ci_gate_contract.py'   ← 仍是 ??，指针不指向内容
  git ls-files            rc=0 行=''   ← 空 = 未跟踪，git 根本没有它的旧版本可比
复原后 字节 48603，与原字节相同 = True
  cmp(备份, 门文件) rc=0   ← 本任务只认这一枚证明
```

两处 `finally` 复原都做了，且都用字节证明：A 台 `cmp` rc=0 + sha256[:12] 回到 `73bede2def2e`；
B 台全程未写盘（开工/收工字节相等 = True）。**没有**用 `git diff --exit-code` 当复原证据。

### 7. 约束自查

| 约束 | 实测 |
| --- | --- |
| 门数仍 16（不加门） | `def test_` 枚数 = **16**；`_OWN_TEST_NAMES` = 16；点名集合 == 定义集合（差集空） |
| `EXPECTED_COLLECTED` 仍 1332 | 行文本 `EXPECTED_COLLECTED = 1332`；且 `test_collected_count_matches_the_pinned_number` 绿 ⇒ 实收 1332 |
| 覆盖度钉位置 | 在 `_index_eol_rows()` 内（helper），两枚消费门自动继承；**未新增任何 `def test_`** |
| 门文件 LF-only / 标准库 / 无 `yaml` / 无 `app.*` | 48603 字节 / **CR 0** / LF 810；import 仅 `__future__ functools os re subprocess sys pathlib`；`import yaml`/`from app`/`import app` 均 False |
| 未动 `.gitattributes` | `cmp` vs `snap-task4-post/gitattributes` **rc=0**，sha `c5d07b5dc438` 不变 |
| 未动 `ci.yml` / `backend/app/**` / `requirements.txt` / SEC-A | `ci.yml` sha `1c706e165b73` 与 R12 登记值相等；`backend/.env` `4d7f974107dd` 不变；`test_secret_hygiene_contract.py` `git diff --exit-code` **rc=0**（sha `fd39d7d374f9`，零新增豁免行） |
| 探针/合成物全在仓外 | 三台前缀 `%TEMP%\b0t4f1\`（`C:\Users\zhang\AppData\Local\Temp\b0t4f1`），合成 listing 只在内存里；`git status --porcelain` 与开工那 8 行逐行相同（无新文件入树） |
| 零 git 写命令 / 零提交 | HEAD 仍 `7cc5efc`；全程只有读命令与 `cmp` |
| 两枚 identity 文件 | 未触碰；`git diff --stat` 仍 `README.md 13++-- / __init__.py 13+--` 两枚 |

### 8. 终态读数

| 面 | 读数 | 结论 |
| --- | --- | --- |
| 门模块（改后，首次） | `16 passed in 36.39s`（cwd=仓根，`backend/.env` 在场） | GREEN |
| 门模块（反证台 A 复原后） | `16 passed in 36.42s`，rc=0 | GREEN（复原证据） |
| SEC-A 模块 | `46 passed in 32.62s`，未新增豁免行（该文件 `git diff --exit-code` rc=0） | GREEN |
| 全量格 1 | cwd=`E:\xiangmu\rag`、`python -m pytest backend/tests -q`、`.env` 状态 = **`backend/.env` 在场**（1561 字节 / sha `4d7f974107dd`，未挪未删）→ collected **1332** / passed **1332** / failed **0** / errors **0** / subtests **1133** / warnings 36 / rc=0 / **214.58s** | GREEN |
| 全量格 2 | cwd=`E:\xiangmu\rag\backend`、`python -m pytest tests -q`、`.env` 状态 = 同一枚 `./.env` 在场（未挪未删）→ **1332 / 0 / 0 / 1133 subtests / 36 warnings** / rc=0 / **210.26s** | GREEN |

两格 `passed / warnings / subtests` 三项逐字相等，与 §6（Task 4 首轮）那两格同值 ⇒ 本轮改动
没有动收集面、也没有将就在跑的任何东西上换颜色。

### 9. 证据位置与未做的事

- 三台探针（只读 git、仓外）：`%TEMP%\b0t4f1\probe_explore.py`（口径与形状取证）、
  `probe_falsify_on_disk.py`（反证台 A + 复原）、`probe_falsify_memory.py`（反证台 B）、
  `probe_d5_gitdiff_trap.py`（D5 复证）；两格全量日志 `full_root.log` / `full_backend.log`；
  注入前字节副本 `gate_before_falsification.py`。本轮**刻意没有**把这些归档进
  `.superpowers/.../tmp/`——任务给的约束是"探针与合成物一律仓外"，仓外副本已足够复核。
- 快照：`snap-task4-fix1-post/test_ci_gate_contract.py`（与源文件 `cmp` 逐字节相同，见 §10）。
- 未做：任何 `git add`/`commit`/`push`/`stash`/`checkout`/`restore`/`clean`/`config`；
  改 `.gitattributes`/`ci.yml`/`backend/app/**`/`requirements.txt`/SEC-A 门；加门、摘门、加豁免、
  加白名单、`skip`/`xfail`；把两枚被丢路径写进任何枚举集合。
- **本轮不主张的事**：远端 CI 读数（`gh run view`）仍归 Task 5+ 的远端回合，本地两格之外没有第三格。

### 10. 快照与终态复核（写完报告与台账之后再量一次）

```
$ cmp backend/tests/test_ci_gate_contract.py snap-task4-fix1-post/test_ci_gate_contract.py  -> rc=0
门文件终态 48603 字节 / CR 0 / LF 810 / sha256[:12] 73bede2def2e（开工登记值 4c98f1439494，本轮改动所致）
$ python -m pytest backend/tests/test_ci_gate_contract.py backend/tests/test_secret_hygiene_contract.py -q
..............................................................           [100%]
62 passed in 66.42s (0:01:06)        ← 16（本门册）+ 46（SEC-A）同一次调用，两枚模块零红
                                       （本节文字全部写完之后再复跑一次的那一发；前一发 65.81s 同值）
$ git status --porcelain | wc -l                                     8 行（7 行基线 + ?? .gitattributes）
$ git ls-files | wc -l                                              313
```

这一跑的用意与 §10（Task 4 首轮）相同：排除"报告/台账/快照本身把状态搞漂"。本轮三处写入
（报告、台账、`snap-task4-fix1-post/`）全部落在 `git check-ignore -v` 命中的 `.gitignore:25`
（`.superpowers/`）里、且都不是跟踪文件 ⇒ 跟踪面仍 313 枚、SEC-A 扫描面（tracked + 未忽略的未跟踪
= 318）一枚未增，§8 那两格全量读数继续成立。`snap-task4-fix1-post/` 只放门文件本体
（本轮没动 `.gitattributes`，它的快照仍在 `snap-task4-post/gitattributes`，`cmp` rc=0 已在 §7 量过）。


