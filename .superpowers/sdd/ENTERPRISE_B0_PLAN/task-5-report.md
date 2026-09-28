# B0 Task 5 报告 —— 全量回归 + SECA-20 漂移复量 + 耗时读数（验收证据）

- 任务：`docs/ENTERPRISE_B0_PLAN.md` / `task-5-brief.md` 的 Task 5（7 枚任务里的第 5 枚）。
- 性质：**本任务不产生产代码**，交付物是证据。全部读数逐格附「命令 / 字面读数 / 状态词」三件，
  状态词只用 `GREEN / PENDING_EXTERNAL / BLOCKED`（规格 §11 / §12）。
- 执行环境：Windows（win32）+ Git Bash，宿主解释器 `Python 3.13.7`，`pytest 9.1.1`。
- 开工基线（Step 0 现场取，落 `evidence/t5-head.txt` / `t5-status-pre.txt`）：
  - `git rev-parse HEAD` = **`7cc5efc0460abb01171c20cee61ef01bf5282a3d`**（= `security-a-rc1` peel 出来的就是它）
  - `git status --porcelain` = **8 行**（sha256 前 12 位 `d550e9739816`）：
    `M .github/workflows/ci.yml` / `M backend/app/identity/README.md` / `M backend/app/identity/__init__.py`
    / `?? .gitattributes` / `?? backend/tests/test_ci_gate_contract.py` / `?? docs/ENTERPRISE_B0_PLAN.md`
    / `?? docs/ENTERPRISE_B0_SPECIFICATION.md` / `?? scripts/b0_collection_probe.py`
  - `backend/.env` sha256 前 12 位 **`4d7f974107dd`**（= progress.md 要求钉值，逐字相符）
- 原始证据目录：`.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/`（本任务所有裸输出都落这里，
  不只留 `%TEMP%`——brief Step 1 硬要求 2，B0-03 会话截断后要能重新导出）。
  该目录在 `.superpowers/` 下：`.gitignore:25` 挡掉 ⇒ 不在 SECA-20 交付面上（且在面的扫描口径里
  也属 `_UNSCANNED_PREFIXES`），本任务写证据这件事本身不会污染 B0-09 的读数。
- 零 git 写命令、零提交；未触碰 `backend/app/**`、`ci.yml`、`.gitattributes`、`backend/tests/**`、
  `requirements.txt`、`docker-compose.yml`、`scripts/**`、`frontend/**`（改动只落在报告 / evidence / 台账）。

---

## Step 1 —— SECA-20 扫描门漂移复量（B0-09）

### 1.1 brief 点名的五枚门

命令（与 `ci.yml` SECA-20 步逐字同形）：

```bash
python -m pytest backend/tests/test_secret_hygiene_contract.py -q \
  -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"
```

字面读数（`evidence/t5-step1-seca-gates.txt`）：

```
.....                                                                    [100%]
5 passed, 41 deselected in 1.46s
real	0m4.113s
```

Expected `5 passed` ⇒ **GREEN**。

### 1.2 面 / 命中 / 处数读数

命令：

```bash
python -c "
import sys;sys.path.insert(0,'backend/tests')
import test_secret_hygiene_contract as m
names=m._delivery_surface_names();hits=m._hit_counts(names)
print('surface files',len(names),'hit files',len(hits),'occurrences',sum(hits.values()))"
```

字面读数（`evidence/t5-step1-surface-reading.txt`）：

```
surface files 318 hit files 16 occurrences 31
```

判读（brief 写死的规则：**命中 16 枚 / 处数 31 不许变，面文件数只许增、增量逐枚归因**）：

- `hit files 16` / `occurrences 31` = SEC-A 封版值**一字未动** ⇒ 豁免表零漂移 ⇒ **GREEN**。
- 命中集 16 枚逐名（`evidence/t5-step1-surface-attribution.txt`）全部是 SEC-A 时代就在表里的那些文件；
  B0 新增的 5 枚面文件**一枚都不在命中集里**（纯 CI/门/规格文件，不含凭据形状）。

### 1.3 面文件数 318 的构成与逐枚归因

命令：

```bash
git ls-files --cached | wc -l                    # 313
git ls-files --others --exclude-standard         # 5 枚，逐名列在 evidence 里
```

字面读数（`evidence/t5-step1-surface-attribution.txt`）：`cached(tracked): 313` + `others: 5` = **318**。

5 枚未被忽略的 untracked（B0 唯一能加的那一维，逐枚点名）：

| 面文件 | 由谁产生 | 在命中集？ |
| --- | --- | --- |
| `docs/ENTERPRISE_B0_SPECIFICATION.md` | B0 规格（Task 0/评审回合入库前） | 否 |
| `docs/ENTERPRISE_B0_PLAN.md` | B0 计划 | 否 |
| `scripts/b0_collection_probe.py` | **Task 1** 收集数探针 | 否 |
| `backend/tests/test_ci_gate_contract.py` | **Task 2** 门模块（Task 3/4 修） | 否 |
| `.gitattributes` | **Task 4** 行尾规则 | 否 |

算术自洽性（同一枚扫描面定义下的三时点，逐格可对账）：

```
Task 1 开工 316 = 313 tracked + 3 untracked（规格 + 计划 + 探针）
Task 2 落门文件 317 = 316 + backend/tests/test_ci_gate_contract.py
Task 4 落 .gitattributes 318 = 317 + .gitattributes
```

tracked 那一半**不可能**被 B0 改动：B0 零提交、HEAD 仍是 `7cc5efc`，且
`git ls-tree -r --name-only HEAD | wc -l` = **313** = `git ls-files --cached` 的数 ⇒ 索引与 HEAD 一致，
没有文件从交付面消失（面数变少才会红的那个方向，实测为零）。

**258 → 318 这一段必须说清，否则会把前人的动作算到 B0 头上**。分两层，实测与推算分开写：

- **实测层**（`git ls-tree -r --name-only <c> \| wc -l` 逐 commit 取，裸档 `evidence/t5-step1-surface-history.txt`）：
  `bc43ca3`（SEC-A 之前）= **236**（`.superpowers/` 下 41 枚）、
  `f6c67b5`（SEC-A finalize）= **313**、HEAD `7cc5efc` = **313**；
  `f6c67b5` 的 `--name-only` 列表里 **55 枚**落在 `.superpowers/` 下，该前缀在 313 里共 **96 枚**。
  ⇒ tracked 那一半的 +77（236→313）发生在 B0 开工之前，且方向是**增**。
- **推算层**（SEC-A 没有归档它那枚 258 的面构成，所以这一句是**算术推断、不是读数**）：
  若 258 取自 `bc43ca3` 形态，则 = 236 tracked + 22 枚当时未被忽略的 untracked；
  `.superpowers/` 在 `.gitignore:25` 里 ⇒ 那 55 枚过程件**未跟踪时不在面上、`git add -f` 之后才在面上**，
  这正好解释"同一条 `-c -o --exclude-standard` 定义、前后差 55~60 枚"。
- **不依赖推算的结论**：B0 对 tracked 侧净零（HEAD 未动、`git ls-tree` 与 `git ls-files --cached` 同数 313），
  B0 对面量的净贡献是 **+2**（门模块、`.gitattributes`，逐枚已归因如上，见 §1.3 的三时点算术）；
  没有任何文件从面上消失（"变少即红"那一方向实测为零）。

### 1.4 敏感性复验（植入 → 看红 → 删除 → 复绿），带 trap 兜底

这一小节是 brief Step 1 硬要求 1 的落地：Task 1 首轮那一次是用裸 `rm` 收尾的，本次改成
`trap 'rm -f "$PROBE"; unset PROBE' EXIT INT TERM` + **结尾断言面文件数回到植入前**。
脚本本体：`evidence/t5-step1-plant-probe.sh`（探针落仓库根未跟踪 `.py`，`.gitignore` 不匹配；
脚本先当场跑 `git check-ignore` 证伪"探针被忽略 ⇒ 实验是空的"这一卡 F 型失效）。

命令：

```bash
bash .superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/t5-step1-plant-probe.sh
```

字面读数（`evidence/t5-step1-plant-probe-raw.txt`，节选）：

```
surface files BEFORE plant : 318
planted: /e/xiangmu/rag/b0_t5_drift_probe.py
probe ignore check: NOT ignored (rc=1) => on the delivery surface
surface files AFTER  plant : 319  (expected BEFORE+1)
--- gate run with probe on the surface (expected RED) ---
E         Right contains 1 more item:
E         {'b0_t5_drift_probe.py': 1}
FAILED backend/tests/test_secret_hygiene_contract.py::test_repository_tracked_files_hold_no_credential_material
FAILED backend/tests/test_secret_hygiene_contract.py::test_the_exemption_table_matches_the_hit_set
2 failed, 3 passed, 41 deselected in 2.37s
gate rc(PIPESTATUS)=1
--- full-module hit/occurrence reading with probe on the surface ---
surface files 319 hit files 17 occurrences 32
probe hits 1
surface files AFTER  remove: 318
ASSERTION OK: surface files returned to 318
--- gate run after removal (expected GREEN again) ---
5 passed, 41 deselected in 1.35s
--- probe residue check ---
ls: cannot access '/e/xiangmu/rag/b0_t5_drift_probe.py': No such file or directory
STATUS IDENTICAL to pre-experiment
[trap] probe removed
```

判读（四件都取到了）：

1. 门**真的会红**，且红在正确的两枚上（材料形状 + 豁免表对账），归因字符串逐字点名探针文件、处数 1；
2. 植入态读数 `17 命中 / 32 处` = 封版值 + 探针那一枚，**没有其他文件被顺带拖进来** ⇒ 面定义无串扰；
3. 删除后 `5 passed` 复绿，面文件数**断言回到 318**，`git status --porcelain` 与开工 8 行**逐行相同**（无残留）；
4. **trap 的兜底性是被实测过的**，不是被写的：本任务第一版脚本把 `cd` 的相对层数算错
   （`dirname $0/../..` 落在 `.superpowers/sdd/`），脚本主体整个跑空、以非零码中断，
   `trap` 照样把那枚错位的探针删干净了（输出末行 `[trap] probe removed` + `ls` 报 no such file）。
   这正是卡 F 说的"一次中断就会把两枚红门交给下一个任务"的反例被拦住的现场。

**B0-09 判定：GREEN**（命中 16 / 处数 31 零漂移；面数 316 → 318 只增不减且逐枚归因；敏感性复验带 trap 通过）。

---

## Step 2 / Step 3 —— 四格全量套件复量（改造后终态版，含耗时）

四格 = `{cwd = 仓库根, cwd = backend}` × `{backend/.env 在场, 移开}`。
每格都按规格 §12 的要求**同时标注 cwd 与 `.env` 状态**（本项目已证明不带这两项的读数字格不可跨会话复用）。

brief 的配方是 `> /tmp/b0-full-root.txt` 再复制；本任务把裸输出**直接写进 `evidence/`**
（Step 1 硬要求 2：原始证据不许只留在 `%TEMP%`），命令其余部分逐字未变。

| 格 | 命令 | cwd | `.env` 状态 | 字面读数 | rc | 原始输出 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `python -m pytest backend/tests -q` | `E:\xiangmu\rag`（仓库根） | **在场**（未挪，sha `4d7f974107dd`） | `1332 passed, 36 warnings, 1133 subtests passed in 211.46s (0:03:31)`；`real 3m38.890s` | 0 | `evidence/t5-step2-cell1-root-withenv.txt` |
| 2 | `python -m pytest tests -q` | `E:\xiangmu\rag\backend` | **在场**（未挪，sha `4d7f974107dd`） | `1332 passed, 36 warnings, 1133 subtests passed in 209.89s (0:03:29)`；`real 3m37.298s` | 0 | `evidence/t5-step2-cell2-backend-withenv.txt` |
| 3 | `python -m pytest backend/tests -q` | `E:\xiangmu\rag`（仓库根） | **移开**（`mktemp -d` 挪出仓库；跑完还原） | `1332 passed, 36 warnings, 1133 subtests passed in 204.31s (0:03:24)`；`real 3m31.577s` | 0 | `evidence/t5-step3-cell3-root-noenv.txt` |
| 4 | `python -m pytest tests -q` | `E:\xiangmu\rag\backend` | **移开**（同上） | `1332 passed, 36 warnings, 1133 subtests passed in 209.84s (0:03:29)`；`real 3m37.256s` | 0 | `evidence/t5-step3-cell4-backend-noenv.txt` |

`failed` / `errors` 四格皆 **0**（`grep -c "FAILED\|ERROR"` 在每格裸输出上取到 **0**；`-q` 形态下 0 即不印）。
收集轴另取两格 `--collect-only` 直读（见 Step 5 的 B0-01 行）。

### `.env` 移开的手法（卡 F 落地，逐条可查）

脚本：`evidence/t5-step3-noenv-cell.sh`（两格各跑一次，`root` / `backend` 参数）。
**登记一处取证瑕疵（不作隐瞒）**：那两次带套件的运行只把 **pytest 本体**逐字 tee 进了
`evidence/t5-step3-cell3-root-noenv.txt` / `t5-step3-cell4-backend-noenv.txt`（含 rc 文件
`t5-step3-{root,backend}-noenv-rc.txt` 与还原后的 `t5-step3-status-after.txt`），
wrapper 那几行断言输出当时只留在终端、**没有裸档**。为把 park/restore 的机械动作也留成裸档，
另跑了一枚**不含套件**的同构周期（`evidence/t5-step3-park-cycle-mechanics.sh` →
`-mechanics-raw.txt`，同一 `mktemp -d` 手法、同一 trap 形状，几秒钟）：它**不主张任何套件读数**，
只证 park 期间交付面始终是 318（没有树内副本落上面）、`.env` 逐字节还原、status 回到开工 8 行。
下面引用的是当时终端里的 wrapper 原文（root 那格）：

```
cell              : root
.env sha256 BEFORE: 4d7f974107dd9db2becbea672af5d92d916579c15f27d366c492ba78682dba8e  (bytes 1561)
hold dir          : /tmp/tmp.N7HFDvrdiQ (outside the repo)
backend/.env present after park? no
untracked-not-ignored files matching 'env':
  (none)
suite rc          : 0
[restore] backend/.env moved back from /tmp/tmp.N7HFDvrdiQ
hold dir removed? gone
.env sha256 AFTER : 4d7f974107dd9db2becbea672af5d92d916579c15f27d366c492ba78682dba8e  (bytes 1561)
ASSERTION OK: backend/.env restored byte-for-byte (sha256 equal, size equal)
ASSERTION OK: git status --porcelain identical to pre-experiment 8 lines
```

- **零 in-tree 副本**：`mv` 到 `mktemp -d`（`/tmp/tmp.*` 在仓库外），树内 `.env` 形状文件的自检行
  打印 `(none)`；`git ls-files --others --exclude-standard | grep -i env` 为空 ⇒
  卡 F 那两枚被拖红的门（材料形状 + 豁免表对账）在本任务全程没有被惊动（Step 1 的 5 passed 复绿即证）。
- **trap 兜底是被实测过的**：`backend` 那格第一版脚本在 `cd backend` 之后还写相对证据路径，
  重定向失败、脚本非零退出 —— `trap` 照样把 `.env` 放回原位（`[restore] ... moved back`），
  事后 `ls -la backend/.env` = 1561 字节、mtime 仍是 `Sep 23 15:06`、sha 仍是 `4d7f974107dd`。
  这一格随后按修正版重跑取到有效读数；**失败的那次没有留下任何 park 状态**（`t5-hold-dir.txt` 守卫已清）。

### 四格互等性的机器比对（不只"数字看着一样"）

`evidence/t5-step23-four-cell-normalized-compare.txt`：把 tmp 目录名、`pytest-<N>` 计数、
`llm-ledger-isolation<N>` 与耗时归一后对四格正文取 sha256 前 12 位：

```
cell1 cwd=repo-root  .env=present :: 1332 passed, 36 warnings, 1133 subtests passed in Xs   normalized-sha12 2b20124cc22b
cell2 cwd=backend    .env=present :: 1332 passed, 36 warnings, 1133 subtests passed in Xs   normalized-sha12 145ab80e8ea6
cell3 cwd=repo-root  .env=parked  :: 1332 passed, 36 warnings, 1133 subtests passed in Xs   normalized-sha12 2b20124cc22b
cell4 cwd=backend    .env=parked  :: 1332 passed, 36 warnings, 1133 subtests passed in Xs   normalized-sha12 145ab80e8ea6
```

判读：**`.env` 这一轴是逐行相等的**（1↔3、2↔4 各自同一签名），不只是同数；
cwd 那一轴的签名不同，差异逐行核对过**只有告警摘要里的路径前缀**
（`backend/tests/...` vs `tests/...`，归一化后 24 行 diff = 12 处成对差异，全是这一类，枚数与测试名集合无差）——
这是 pytest 打印相对路径的固有行为，不是形态差异。⇒ **B0-04 GREEN**（四格全绿、还原逐字节一致、
且"`.env` 中性"从巧合升级为被声明的条件）。

### Step 3 专述：CI 形态那一格 vs Step 2 的 root 格

brief 要求"与 Step 2 的 root 格读数**逐位相同**；不同则 §10.3 归因"：

```
格 1（.env 在场，cwd=仓库根） 1332 passed, 36 warnings, 1133 subtests passed | rc=0
格 3（.env 移开，cwd=仓库根） 1332 passed, 36 warnings, 1133 subtests passed | rc=0
```

**逐位相同**（1332 / 36 / 1133 / 0 failed / 0 errors / rc 0 全等），只有墙钟耗时不同
（211.46s vs 204.31s，属负载噪声，不是判据项）⇒ 无需 §10.3 归因。

---

## Step 3.5 —— 容器内 3.12 那一格（规格 §8.2 / B0-15）：**取到读数，格内有 3 枚红**

### 量测环境（不是猜的，逐枚实测）

- 镜像：**`rag-backend:security-a-rc1`**（发布镜像，本地在场，`docker images` 实测）
  ⇒ `python -V` = **`Python 3.12.14`**（与规格 §8.2 点名的 SEC-A 容器基准同一枚），
  `requirements.txt` 的 15 条包**全部在场**（`fastapi 0.141.1 / starlette 1.7.0 / torch 2.14.0+cpu /
  sentence-transformers 5.7.0 / argon2-cffi 25.1.0 / typesafe-sdk 0.7.1 …`，逐名点验过）。
  ⇒ 不必在容器里重装整份依赖（省掉 torch 的几百 MB），只补 CI 用到的两枚工具：
  `pip install pytest` ⇒ **`pytest 9.1.1`**（与宿主同版）、`apt-get install git` ⇒ `git version 2.47.3`
  （ubuntu-latest runner 本来就有 git，这一步是让容器更贴 CI，不是放宽）。
- 树：**不用 bind mount**。Windows 挂载会把容器内的写实打实落到宿主工作树，而这一格必须
  `没有 backend/.env`（在宿主上删它 = 动交付面外的东西）。做法：把
  `git ls-files --cached --others --exclude-standard` 那 318 枚面文件 + `.git`（4 MB）
  打成 tar、`docker cp` 进容器自己的文件系统解压到 `/w`。
  `.env` 被 `.gitignore` 挡在面外 ⇒ **天然不在场**，与 CI checkout 同构（脚本 `evidence/t5-step35-container-prepare.sh`）。
- 形态自检（容器内打印）：`backend/.env present? no`、`git rev-parse HEAD` = `7cc5efc0460...`、
  `tracked=313 untracked=5`（与宿主交付面逐项同数）、`/w` 总 12 MB。
- 取证存档的边界（写清以免被当成"全部裸档"）：套件本体在 `evidence/t5-step35-container-cell.txt`（134 行，
  `docker cp` 出来的），`--collect-only` 那行在 `evidence/t5-b001-collect-container.txt`，
  准备段在 `evidence/t5-step35-prepare-raw.txt`（末尾停在一次 MSYS 把 `docker exec -w /w` 折成 `W:/`
  的失败，之后几步改为 `bash -lc 'cd /w && …'` 手工完成）；`b0-t5-cell` 那枚容器已按清理要求 `docker rm -f`，
  它内部的 wrapper 行（apt 装 git、形态自检）只在本节正文引用。**镜像级环境事实已复档可重跑**：
  `evidence/t5-step35-container-env-facts.txt`（`Python 3.12.14` + 15 条包逐名 OK + `pip install pytest`
  ⇒ `pytest 9.1.1` = 宿主同版）。
- 与 CI 的一处**刻意差异**并写清：GitHub checkout 只会拿到 **已提交**的树，而 B0 无提交权限，
  `.gitattributes` / `test_ci_gate_contract.py` / `ci.yml` 改动此刻是未跟踪/未提交状态。
  本格按"这些文件入库后的形状"打包（含那 5 枚未跟踪文件），因此它证的是
  **"3.12 + Linux + 无 `.env` 这套环境本身会不会红"**，不是"B0 的产物能否被提交"（后者归 B0-02 远端格）。

### 读数

命令：`docker exec b0-t5-cell bash -lc 'cd /w && python -m pytest backend/tests -q'`
（宿主观测墙钟 `real 1m54.345s`；容器内计时见 pytest 自身那行）

```
3 failed, 1329 passed, 2 warnings, 1133 subtests passed in 107.52s (0:01:47)
inner rc=1
1332 tests collected in 11.44s          ← 同一枚收集钉，在 3.12/Linux 上也还是 1332
```

FAILED 逐名（原文在 `evidence/t5-step35-container-cell.txt`，134 行裸输出已 `docker cp` 回工作区）：

```
FAILED backend/tests/test_password_lifecycle_contract.py::MustChangeGateCoverageTests::test_every_authenticated_route_is_gated_or_whitelisted
FAILED backend/tests/test_password_lifecycle_contract.py::MustChangeGateCoverageTests::test_the_enumeration_sees_every_service_surface
FAILED backend/tests/test_real_llm_failover_gate.py::P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence
```

收集数 1332、subtests 1133 与宿主四格**全等**；两枚 B0 门模块（`test_ci_gate_contract`、
`test_secret_hygiene_contract`）在 Linux + `.gitattributes` 生效的树上**没有一枚进 FAILED**
⇒ §6.4 的行尾钉与 SECA-20 的扫描面定义在 CI 的同族 OS 上成立（这是宿主 Windows 给不了的覆盖面）。

### §10.3 归因（三枚红，逐枚；**都不是 app 语义缺陷**）

**红 1 + 红 2 —— 依赖解析版本差（原文归 §10.3 第 1 类：依赖形态）**

> 【订正 R16 / M-2 · 修复轮 B0-T5-fix】这一小节的两处归因**都被后续裁定改判**，原文一字不删、就地标注：
> ① `_IncludedRouter` 属于 **FastAPI**（`fastapi/routing.py` 的私有符号），**不是 Starlette 的行为**；
> ② 由此它的可操作类别不是 §10.3 第 1 类（依赖形态，最不可操作的一格），而是
> **§10.3 第 2 类**（"断言写死了本机形态"）——§10.1 白名单把 `backend/tests/**`（既有）明列为 B0 靶区。
> 两枚红已在 B0 内以"只改测试"的口径修掉，见 `task-5-fix-report.md`。

- 实测两侧的同源不同解：宿主 `fastapi 0.135.3 / starlette 1.0.0`，容器（发布镜像按
  `requirements.txt` 的 `fastapi>=0.115,<1` 区间在另一天解析）`fastapi 0.141.1 / starlette 1.7.0`。
- 机理逐枚取证（两侧重跑同一段只读探针）：
  - 宿主 `sorted({type(r).__name__ for r in app.routes})` = `['APIRoute', 'Route']`
  - 容器同一句 = `['APIRoute', 'Route', '_IncludedRouter']`
  ⇒ ~~新版 Starlette~~ **新版 FastAPI**（`fastapi/routing.py` 的 `_IncludedRouter`）
  在顶层 `app.routes` 里多挂了 `_IncludedRouter` 条目，
  于是红 2 的"非 `APIRoute` 条目不许带服务面"断言拿到 `['_IncludedRouter'] × 4`，
  红 1 的 `MUST_BE_COVERED <= authenticated` 跟着漏腿（5 条端点没被顶层枚举看见）。
  （修复轮量测订正 · **规模是加重不是笔误**：那"5 条"只是 `MUST_BE_COVERED` 8 枚点名腿里被探针抓到的部分，
  旧走法在这格实际只枚举到 21/48 条服务面腿、15/42 条已认证腿 ⇒ 真实盲区 **27 条腿**。
  逐条清单与两枚模块的转绿读数见 `task-5-fix-report.md` §1.1 / §1.5。）
  （归因订正：评审在镜像里逐文件核过该符号**只出现在 `fastapi/routing.py`**、starlette 1.7.0 全包零命中；
  本修复轮又在宿主两侧复核 `hasattr(fastapi.routing, '_IncludedRouter')` 与
  `hasattr(starlette.routing, '_IncludedRouter')` **同为 False**（宿主 0.135.3/1.0.0 尚无此符号），
  与"这是 fastapi 版本差"一致。修复者按 FastAPI 找包，别再翻 starlette。）
- 性质：这两枚红是**测试对库内部路由对象形状敏感**，遇上未上界的区间依赖 ⇒ 依赖解析一变就红。
  ~~B0 修不了~~ **本任务修不了**（约束 = 不编辑其他测试；原文写"B0 修不了"是错的——
  §10.1 把 `backend/tests/**`（既有）明列为 B0 靶区，§10.3 第 2 类点的正是"断言写死本机形态"这一族，
  错框会把这两枚挂到第 1 类、后续被当成"B0 之外的事"绕开）。
  `backend/requirements.txt` 依旧是禁止触碰的真源（§10.2），修的那一侧是测试：按 §10.3 第 2 类
  改枚举并留"为什么这样钉"的说明，**本任务的约束是不编辑其他测试**，故当时只登记。
- **对远端的直接含义**（写在这里，因为它决定 B0-02 会不会红）：CI 的 `ubuntu-latest` 装的是
  同一份区间约束、在 CI 那天重新解析 ⇒ 这两枚门在远端**很可能同样红**，且与 B0 的改造无关。
  这是本次复量最值钱的发现之一，属于"本地绿/远端红"的那一族，正是 B0 要照出来的东西。

**红 3 —— 测试依赖一枚 gitignored 证据件（§10.3 第 2 类：测试自身的 `.env`/本机形态依赖）**

- 机理：`test_p0_row_status_matches_the_evidence` 先读矩阵文档（`docs/MODEL_ROUTER_V23_MATRIX.md`，
  已跟踪，状态写着 `GREEN`），再读 `backend/tests/real_llm_failover_kit.py:79` 定义的
  `EVIDENCE_FILE = .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`。
  该 JSON 在本机**存在**（宿主读数：`exists True`、`read_evidence()[1] = None`、状态 `GREEN` ⇒ 本地绿），
  但它被 `.gitignore:25` 的 `.superpowers/` 整目录挡掉（`git check-ignore -v` 实测命中，`git ls-files` 为空），
  ⇒ 任何**干净 checkout**（容器 / CI）里它是 `missing`，测试按规则要求矩阵必须写 `BLOCKED`，
  而矩阵写着 `GREEN` ⇒ `AssertionError: 'BLOCKED' != 'GREEN'`。
- 性质：**不是 app 语义缺陷**（app 代码一行没被这条触及），也不是 B0 引入的
  （该文件在 B0 开工前就是这样）；是一条"**只在有本机过程件的树上才绿**"的判据。
  B0 之后主门第一次真跑全部 1332 枚（旧 runner 收不到模块级函数、且整步本就红），
  所以这条会在远端第一次真起跑时暴露 —— 本格是它的**唯一本地证据**。
- 出路登记（不由本任务决定）：要么把该证据件按 SEC-A 先例 `git add -f` 精选入库，
  要么让该枚门自己识别"证据件不在面内"这一形态。两条都动 B0 白名单外的东西或需评审改判据 ⇒ **只报告**。

> 【修复轮补记 B0-T5-fix · R15 裁定】两条出路里裁定走**第一条**：证据件由 controller 写进 Task 7 的
> staging 段，等用户显式授权后 `git add -f` 上交付面；**不改矩阵、不放宽判据**。
> 第二条（让门自己识别"不在面内"）被裁定为**不许**——那等于把"证据必须在场"这条正确判据换掉。
> 本批在测试侧只把失败做成**可诊断**（原来那句 `'BLOCKED' != 'GREEN'` 指着矩阵，真正缺的是那枚没入库的件），
> 判据一分不松：不在场 ⇒ 照旧红。读数与新文案见 `task-5-fix-report.md` §2。

### 本格结论

- **B0-15 判据本体（"§8.2 那一格有读数"）：GREEN** —— 镜像、解释器版本、装包、收集、执行五件事都取到了。
- **格内结果不作 GREEN 主张**：`3 failed / rc=1`，逐枚归因如上，全落 §10.3 的第 1/2 类，**没有第 3 类**
  （app 面零改动，见 Step 4）。⇒ 交给 controller 决定是否成为修复派发；本任务不编辑那三枚测试。
- 清理：`docker rm -f b0-t5-cell` 已执行，`docker ps -a` 里 `b0-t5` 计数为 0；宿主工作树未受本格影响
  （Step 1/Step 3 的 `git status --porcelain` 8 行逐行相同断言在本格之后仍然成立）。

---

## Step 4 —— B0 没碰 app 面（B0-12，按规格 §11 / §16 卡 J 的**三子句**形态执行）

判据不是"列表为空"：`security-a-rc1` peel 出来就是 HEAD（`7cc5efc`），那两枚 `backend/app/identity/`
未提交改动**本来就出现在 diff 里**。裸档：`evidence/t5-step4-app-surface-audit.txt`。

### 子句 ①：`git diff --name-only HEAD -- backend/app` 减去两枚 identity 后为空

```
$ git diff --name-only HEAD -- backend/app
backend/app/identity/README.md
backend/app/identity/__init__.py
$ <同一条> | grep -vE '^backend/app/identity/(README\.md|__init__\.py)$'
clause1-residue-count=0                ← 减去那两枚之后为空 ⇒ 子句 ① 成立
```

### 子句 ②：`git diff --cached --name-only -- backend/app` 为空

```
clause2-count=0                        ← 已暂存侧零枚
```

辅助读数（不属判据、由白名单保证的那一维，仍然实测了）：
`git ls-files --others --exclude-standard -- backend/app` → `aux-untracked-count=0`（B0 没在 app 下新建任何文件）。

### 子句 ③：两枚 identity 的 sha256 == B0-T1 冻结基线，逐字符相同

```
backend/app/identity/README.md   3bc681bbc52c     （progress.md:48 冻结值 3bc681bbc52c）
backend/app/identity/__init__.py 2cfab9f18182     （progress.md:48 冻结值 2cfab9f18182）
```

mtime 佐证（未被本任务改写）：`README.md Sep 26 00:23`、`__init__.py Sep 26 00:15`（均在 B0 开工之前）。
`git diff --stat HEAD -- backend/app` = `2 files changed, 18 insertions(+), 8 deletions(-)`——
差量只有那两枚，**逐枚点名"不是我改的"**：它们是 SEC-A 收尾时留下的身份声明层注释/文档改动，
本任务未提交、未改动、未顺手调整（三子句全绿 ⇒ **B0-12 GREEN**）。

### 附带发现（登记，非判据、非本任务处置）

`.gitattributes` 生效后，`git diff` 在 stderr 上多出两行：

```
warning: in the working copy of 'backend/app/identity/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/identity/__init__.py', LF will be replaced by CRLF the next time Git touches it
```

成因实测：本机 `core.autocrlf=true`（`git config --get core.autocrlf` 返回 `true`）+ `* text=auto`
⇒ git 会预告"下次签出给 CRLF"。**索引侧没有被改写**（`git ls-files --eol -- backend/app/identity/` 六枚全 `i/lf`），
diff **正文**字节不变（见下表 B0-07 的 `10107 / dfa0fbde86b5`），所以它只是 stderr 噪声、不影响任何一枚门的判定。
登记的原因是：任何人若把"stderr 干净"当成某种 no-op 证据，会在 `.gitattributes` 落地后误判——
**no-op 证据必须落在正文与索引上**，这正是 Task 4 用 `cmp`/sha 而不是用 `git diff --exit-code` 的原因（D5 那枚假绿）。

---

## Step 5 —— 规格 §11 判据矩阵逐行（B0-01 … B0-15）

状态词只用 `GREEN / PENDING_EXTERNAL / BLOCKED`；**没有读数就没有 GREEN**。
最后一列专管"这一行只能在本地以外结算的那半枚"，防止把本地绿当整行绿。

| ID | 本任务的命令 | 字面读数（裸档位置） | 状态词 | 远端 / 他任务那半枚 |
| --- | --- | --- | --- | --- |
| **B0-01** 收集数 == 钉住常数 | `python -m pytest backend/tests -q --collect-only`（仓根）；`cd backend && python -m pytest tests -q --collect-only`；门 `test_collected_count_matches_the_pinned_number` | `1332 tests collected in 26.28s`（real 33.495s，`evidence/t5-b001-collect-root.txt`）；`1332 tests collected in 27.61s`（real 34.720s，`...-backend.txt`）；`EXPECTED_COLLECTED = 1332`、门 **PASSED**（`t5-step5-gate-literals.txt` / `t5-step5-gate-module-verbose.txt`）；容器格另取 `1332 tests collected in 11.44s`（`t5-b001-collect-container.txt`） | **GREEN**（本地两 cwd + 容器三处同数） | **PENDING_EXTERNAL**：远端 step 读数比对归 B0-03 / Task 7 |
| **B0-02** 远端 `backend-contracts` 整 job success | `gh run view <id> --json jobs,name,url` + `--log` | **未取**——本任务零 git 写、不推送、不触发远端，因而没有 run id 可引 | **PENDING_EXTERNAL** | 整行待 Task 7（且必须按 Step 3.5 的两条风险预判：见下"关注点"） |
| **B0-03** 同 commit 本地/远端收集数逐位相同 | 本地侧：上面 B0-01 的两枚 `--collect-only` 读数 + 原始 node-id 导出 | 本地侧 `1332`（三处）；原始证据已落工作区 `evidence/`（不再只留 `%TEMP%`），会话截断后可重新导出 | **PENDING_EXTERNAL** | 远端那半枚未取 |
| **B0-04** §8.1 四格全绿 + `.env` 还原逐字节一致 | `t5-step2/step3` 四格命令（见 Step 2 表） | 四格全等 `1332 passed, 36 warnings, 1133 subtests passed`、rc=0、`FAILED/ERROR` 计数 0；`.env` sha `4d7f974107dd…` 前后逐字节相同、`git status` 回到开工 8 行；归一化签名 1↔3、2↔4 相同（`t5-step23-four-cell-normalized-compare.txt`） | **GREEN** | — |
| **B0-05** 单 runner 钉绿 | 门 5/6：`test_backend_contracts_has_no_unittest_discover_step`、`test_backend_contracts_runs_the_pytest_suite` | 两枚 **PASSED**（`t5-step5-gate-module-verbose.txt`，模块 `16 passed in 34.88s`） | **GREEN**（本地） | **PENDING_EXTERNAL**：门自身被远端收集那一半随 B0-01/B0-03 一起结 |
| **B0-06** 依赖同源钉绿（含豁免表形状） | 门 8/9/10/11（`_install_face`、包名集合、发行源值、逐行理由） | 四枚 **PASSED**；模块 `16 passed`；SEC-A 那侧"未加豁免行"由 Step 1 的 `5 passed` + 命中 16/处数 31 复证 | **GREEN**（本地） | **PENDING_EXTERNAL**（远端收集半枚，同上） |
| **B0-07** `.gitattributes` 的 no-op 性 | `git diff \| wc -c`、`git diff` 正文 sha256、`git status --porcelain`、`git ls-files --eol` 索引侧 | 正文 **`10107` 字节 / `dfa0fbde86b5`** —— 与 Task 4 R12 的钉值**逐字符相同**（`.gitattributes` 落地前后同值）；`.gitattributes` 本体 `435` 字节 / `c5d07b5dc438` 不变；status 仍开工那 8 行（`d550e9739816`）；索引侧 `i/crlf` 零枚 ⇒ 无字节改写（`t5-step5-byte-anchors.txt`、`t5-step5-gate-literals.txt`） | **GREEN** | — |
| **B0-08** 行尾钉绿 | 门 14/15 + 卡 K 的解析覆盖度钉（`_index_eol_rows()`） | `parsed eol rows = 313`、`tracked (git ls-files -z) = 313`（**两侧等值 ⇒ 没有 311 那族丢行**，卡 K 的失效未复发）；`i/crlf entries = 0 []`；`i/-text entries = 3`，逐名 `.superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md`、`docs/MODEL_ROUTER_V23_DESIGN.md`、`frontend/public/yaoke-logo.webp` | **GREEN** | — |
| **B0-09** SECA-20 扫描门豁免表零漂移 | Step 1 的三条命令 | `5 passed, 41 deselected`；`surface files 318 hit files 16 occurrences 31`；植入态 `319 / 17 / 32` → 删除态 `318` + `5 passed` + trap 兜底实测 | **GREEN** | — |
| **B0-10** compose / pwsh 两道**首次真起跑** | 行定义在远端：`docker compose config >/dev/null` 与 pwsh `[scriptblock]::Create(...)` | 远端未取 ⇒ 本行不作主张。**本地强化读数**（同形命令，非判据替代品）：`compose config rc=0`；`pwsh rc=0`（pwsh 7 在场，`/c/Program Files/PowerShell/7/pwsh`），裸档 `t5-step5-b010-local-probe.txt` | **PENDING_EXTERNAL** | 整行待 Task 7 的 step 级读数 |
| **B0-11** §9 五发变异逐发红 + `--check` 还原一致 | 变异台归 **Task 6**（计划 §13：`\| §9 五发变异 \| Task 6 \|`） | 本任务不复跑。已有反例留档可续用：Task 2 `tmp/b0_t2_falsify.py` + `tmp/falsify-round1.txt`（含"把扫描步挪到主门之后仍绿"那发、`@pytest.mark.skip` 那发）、Task 3 门 5 `F1 复活：unittest 收集 1 处` 红、Task 4 R12 摘 `*.sh text eol=lf` 当场 `1 failed` + `finally` 原字节写回 `cmp rc=0` | **PENDING_EXTERNAL**（他任务结算，非本地远端义） | Task 6 |
| **B0-12** `backend/app/**` 未被 B0 改动（三子句） | Step 4 三条命令 | ① 减两枚 identity 后 `clause1-residue-count=0`；② `clause2-count=0`；③ `3bc681bbc52c` / `2cfab9f18182` 与 progress.md:48 冻结值逐字符相同；辅助：app 下 untracked `0` 枚 | **GREEN** | — |
| **B0-13** 全量 pytest 的 CI 耗时读数入档、pip cache 取舍有证据 | 本地：四格 + 门模块 `--durations` + 容器格；远端：step 级耗时（未取） | 本地读数全集：全量四格 `211.46 / 209.89 / 204.31 / 209.84 s`（宿主人 3m31.6s–3m38.9s）；容器 3.12/Linux **`107.52s`**；`--collect-only` 宿主 `26.28 / 27.61s`、容器 **`11.44s`**；门模块 `34.88s`，其中**那枚 spawn 收集子进程的门 `call 33.43s`（占模块 96%、占全量 15.8%；按容器实测换算到 CI 形态约 11s ≈ 全量的 10%）**。pip cache 的收益/代价本地**测不出来**（宿主依赖早已装好、无 runner 安装步） | **PENDING_EXTERNAL** | 远端安装步耗时与 cache 命中读数归 Task 7；"子进程收集值不值"的本地依据已给足（见上） |
| **B0-14** `G20` 新开 + `G0` 勘误卡落档 | `grep -c "G20" docs/ENTERPRISE_ACCEPTANCE_GAP_ANALYSIS.md`；`grep -n '^&#124; G0 ' 同文件`；`git status --porcelain -- 该文件` | **`G20` 命中 0 次**（`grep -c` = 0，rc=1）；`G0` 行仍是原措辞（第 7 行：`&#124; G0 工程 &#124; 部分 &#124; .github/workflows/ci.yml 已有 build/测试/真BGE门禁/前端构建；缺 lint、typecheck、依赖扫描(pip-audit)、工具化 secret 扫描(gitleaks)、OpenAPI 契约测试`），文档标题仍为「企业级验收框架 **G0–G19** 差距盘点（2026-09-23）」；该文件在 `git status` 里**零出现** ⇒ 从未被 B0 改动。裸档 `t5-step5-b014-doc-probe.txt` | **PENDING_EXTERNAL**（他任务结算，非远端义） | 归 **Task 7**（计划 §13 / §16 卡 D 的落档动作） |
| **B0-15** §8.2 容器内 3.12 那一格有读数 | `docker run` 前置 + `docker exec b0-t5-cell bash -lc 'cd /w && python -m pytest backend/tests -q'` | `Python 3.12.14`、`pytest 9.1.1`、`git 2.47.3`、`backend/.env present? no`、`tracked=313 untracked=5`、**`3 failed, 1329 passed, 2 warnings, 1133 subtests passed in 107.52s`**（rc=1）、`1332 tests collected in 11.44s`；三枚 FAILED 逐名 + §10.3 归因见 Step 3.5 | **GREEN**（判据本体"有读数"已满足） | 格内 3 枚红的处置归 controller；**本格不主张"容器全绿"** |

### 计数小结

按**行**计（15 行）：

- **GREEN：9 枚** —— B0-01 / B0-04 / B0-05 / B0-06 / B0-07 / B0-08 / B0-09 / B0-12 / B0-15；
  九行全部带本任务当场取到的字面读数。其中 B0-01 / B0-05 / B0-06 的 **GREEN 只覆盖本地那一半**，
  远端收集那半枚在最后一列单列为 PENDING_EXTERNAL，不并进本行的绿。
- **PENDING_EXTERNAL：6 枚** —— B0-02 / B0-03 / B0-10 / B0-11 / B0-13 / B0-14；
  其中 B0-02 / B0-03 / B0-10 / B0-13 是**只能在远端结**（Task 7），
  B0-11 / B0-14 是**由 Task 6 / Task 7 结**（"外部"指他任务，不是远端），已逐行注明，没有一行被"顺手当过"。
- **BLOCKED：0 枚**。

---

## 关注点（交给 controller，本任务不动手）

1. **远端 B0-02 有两个具体的红点等着，且都不是 B0 造成的**：
   - `test_password_lifecycle_contract.py` 两枚覆盖面门对 ~~starlette 的对象形状~~
     **fastapi 路由对象形状**（`_IncludedRouter`，归因订正见上方 §10.3 归因那节的批注）敏感，
     而 `requirements.txt` 写的是 `fastapi>=0.115,<1` 这种**开区间**
     ⇒ CI 那天解析到 0.141.x 就会红。B0 不许动 requirements（§10.2），
     当年也不该在本任务动测试——**这一枚已在 B0 的修复轮里按 §10.3 第 2 类改掉**（只改测试）。
   - `test_real_llm_failover_gate.py` 的 P0 那枚门读的 `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`
     被 `.gitignore:25` 挡掉 ⇒ 干净 checkout 里证据 `missing`，而 tracked 的矩阵文档写着 `GREEN`，
     门按规则要求 `BLOCKED` ⇒ **远端必红**。这条是 B0 之后"主门第一次真跑全部 1332 枚"的直接暴露，
     容器格是唯一已取到它的本地证据。
2. **`.gitattributes` / 门模块 / `ci.yml` 至今全是未跟踪/未提交态**，B0 无提交权限（项目零提交规矩）。
   任何远端往返之前需要用户显式授权把这三枚入库，否则 CI 拿到的是没有 `.gitattributes` 的树，
   行尾钉与 no-op 那两枚判据在远端的形状会和本地不一样（这正是 §16 卡 K 那一族）。
3. **耗时与 pip cache**：子进程收集那枚门在 Windows 宿主上 `33.43s`，同形态在 Linux/3.12 只需约 `11s`
   ⇒ "为 CI 省掉它"的动机在 CI 那侧比在本地小得多；真正的大头是 pip 安装（本地测不到）。
   建议 cache 取舍等 Task 7 的远端 step 读数一起判，本行已把两半的实测数都留在档上。
4. **取证瑕疵自登**：两次带套件的 park 周期 wrapper 输出未 tee（详见 Step 3 那节），
   已用不含套件的同构 park 裸档补齐机械动作；后续任务的取证脚本一律 `| tee evidence/…`。
5. 本任务**没有**弱化任何断言、**没有**加豁免行、**没有** skip：
   SEC-A 扫描模块的 46 枚（`5 passed + 41 deselected = 46`）在四格全量里被完整跑到且 `0 failed`，
   `EXEMPTIONS` 一字未加（Step 1 的 16/31 零漂移就是它的对账证据）；
   B0 门模块 16 枚、`_OWN_TEST_NAMES = 16`、`EXPECTED_COLLECTED = 1332` 未动（门模块 sha `73bede2def2e` 不变）。

## 交付面自证（本任务改了什么）

- 新建：`.superpowers/sdd/ENTERPRISE_B0_PLAN/task-5-report.md`（本文件）、
  `.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/`（36 枚裸档，含四枚可复跑的取证脚本
  `t5-step1-plant-probe.sh`、`t5-step3-noenv-cell.sh`、`t5-step3-park-cycle-mechanics.sh`、
  `t5-step35-container-prepare.sh`）、
  `snap-task5-post/`（快照）。
- 台账：`progress.md` 追加 R14 一行。
- **未改**：`backend/app/**`（三子句为证）、`backend/tests/**`（门模块 sha `73bede2def2e` 不变、
  SEC-A 模块命中 16/31 不变）、`.github/workflows/ci.yml`（`1c706e165b73` 不变）、
  `.gitattributes`（`c5d07b5dc438` 不变）、`backend/requirements.txt`、`docker-compose.yml`、
  `scripts/**`、`frontend/**`。
- git：零命令写、零提交；HEAD 仍 `7cc5efc0460abb01171c20cee61ef01bf5282a3d`。

---

## 终检（收工前现场取的，裸档 `evidence/t5-final-integrity.txt`）

```
HEAD: 7cc5efc0460abb01171c20cee61ef01bf5282a3d
STATUS IDENTICAL (8 lines)
backend/.env                             4d7f974107dd  expected 4d7f974107dd  MATCH
backend/app/identity/README.md           3bc681bbc52c  expected 3bc681bbc52c  MATCH
backend/app/identity/__init__.py         2cfab9f18182  expected 2cfab9f18182  MATCH
.gitattributes                            c5d07b5dc438  expected c5d07b5dc438  MATCH
.github/workflows/ci.yml                  1c706e165b73  expected 1c706e165b73  MATCH
backend/tests/test_ci_gate_contract.py    73bede2def2e  expected 73bede2def2e  MATCH
探针残留: ls: cannot access 'b0_t5_drift_probe.py': No such file or directory
park 守卫残留: No such file or directory
b0-t5 containers: 0
SEC-A 五枚门（收工再跑一次）: 5 passed, 41 deselected in 1.85s
```

⇒ 本任务的全部取证动作（植入探针 ×1、`.env` park ×3、容器 1 枚）**没有留下任何残留**，
六个字节锚点全部与开工/前任务钉值相同，工作树状态与开工逐行相同。

