# Task 1 报告：基线复量与常数标定（measure-only）

- 计划：`docs/ENTERPRISE_B0_PLAN.md` / 规格：`docs/ENTERPRISE_B0_SPECIFICATION.md`（冻结）
- 基线 commit：`7cc5efc`（= tag `security-a-rc1`），全程零提交（台账 R2）
- 工作区：`.superpowers/sdd/ENTERPRISE_B0_PLAN/`（台账 R0；计划正文的 `ENTERPRISE_B0/` 为旧称）
- 本任务性质：只测量、只新增探针与基线明细，**不触碰任何交付面**（`backend/app/**`、`frontend/**`、`docker-compose.yml`、既有 `scripts/*` 一字未动）
- 宿主：Windows / Git Bash，宿主 Python 3.13.7，pytest 9.1.1，控制台 cp936

---

## Step 1：探针脚本（门量法的唯一实现）

新建 `scripts/b0_collection_probe.py`（逐字转写自 brief，未增删逻辑）。对外接口：

- `main() -> int`
- `collected_node_ids(root: Path = REPO_ROOT) -> list[str]`
- 量法：统计匹配 `^backend/tests/[^:]+::` 的行数；子进程固定 `cwd=仓库根`、固定剥掉 `REAL_LLM_ACCEPTANCE`；收集期非 0 直接 `raise`（不咽）。

落盘后核对：本次运行环境里 `REAL_LLM_ACCEPTANCE` 本就是未设置状态（见 Step 2 原文），与 CI 默认形态一致。

---

## Step 2：探针实测——TOTAL 与逐模块计数

Run（仓库根，实测耗时 `1m1.688s` ≈ 62 s）：

```
$ python scripts/b0_collection_probe.py
```

原始输出全文：

```
REAL_LLM_ACCEPTANCE=[UNSET]

real	1m1.688s
user	0m0.031s
sys	0m0.078s
rc=0
=== head -5 ===
TOTAL 1316
   16  backend/tests/test_agent_contracts.py
    7  backend/tests/test_agent_routing_contracts.py
   68  backend/tests/test_authentication_leg_contract.py
    2  backend/tests/test_branding_contract.py
=== line count ===
40
=== full ===
TOTAL 1316
   16  backend/tests/test_agent_contracts.py
    7  backend/tests/test_agent_routing_contracts.py
   68  backend/tests/test_authentication_leg_contract.py
    2  backend/tests/test_branding_contract.py
    1  backend/tests/test_chat_persistence_contract.py
    1  backend/tests/test_citation_ui_contract.py
   11  backend/tests/test_complex_accuracy_contract.py
    3  backend/tests/test_conversation_retry_contract.py
    3  backend/tests/test_conversation_store.py
    4  backend/tests/test_conversation_ui_p1c_contract.py
   92  backend/tests/test_credentials_contract.py
    5  backend/tests/test_deployment_contract.py
  103  backend/tests/test_feishu_identity_contract.py
   35  backend/tests/test_llm_egress_guard.py
  101  backend/tests/test_llm_usage_contract.py
  392  backend/tests/test_model_router_v23_contract.py
    4  backend/tests/test_p16_review_regressions.py
    3  backend/tests/test_p17_runtime_smoke_contract.py
    8  backend/tests/test_p17_streaming_contract.py
    3  backend/tests/test_p18_interview_readiness_contract.py
   77  backend/tests/test_password_lifecycle_contract.py
   15  backend/tests/test_rbac_contract.py
   15  backend/tests/test_real_llm_failover_gate.py
   11  backend/tests/test_retrieval_performance_contract.py
    2  backend/tests/test_runtime_metadata_contract.py
    6  backend/tests/test_runtime_usability_contract.py
   46  backend/tests/test_secret_hygiene_contract.py
   17  backend/tests/test_security_a_closure.py
    3  backend/tests/test_typesafe_api_runtime.py
    8  backend/tests/test_typesafe_judgments.py
    5  backend/tests/test_typesafe_retrieval.py
   19  backend/tests/test_typesafe_security_contract.py
  120  backend/tests/test_typesafe_v2_core.py
   47  backend/tests/test_typesafe_v2_pipeline.py
    2  backend/tests/test_ui_consistency_contract.py
   53  backend/tests/test_user_directory_contract.py
    2  backend/tests/test_version_hygiene_contract.py
    3  backend/tests/test_web_search_contracts.py
    3  backend/tests/test_web_security.py
```

**读数与 brief Expected 对照：一致。**

| 项 | Expected | 实测 | 判定 |
| --- | --- | --- | --- |
| `TOTAL` | 1316 | **1316** | GREEN |
| 模块行数 | 39（brief 已自行修正 41→39） | **39**（文件共 40 行 = 1 行 TOTAL + 39 行计数） | GREEN |
| `backend/tests/test_*.py` 枚数 | 40 | **40**（`ls backend/tests/test_*.py \| wc -l`） | GREEN |
| 默认 0 枚贡献的文件 | `test_real_llm_failover_acceptance.py` | 确认在磁盘上存在（40517 字节），但不出现在计数里 ⇒ 默认收集 0 枚 | GREEN |

39 行计数之和机器复核：16+7+68+2+1+1+11+3+3+4+92+5+103+35+101+392+4+3+8+3+77+15+15+11+2+6+46+17+3+8+5+19+120+47+2+53+2+3+3 = **1316** ✓（逐模块计数与 TOTAL 自洽，无漏计/重计）。

---

## Step 3：四格 `cwd` × `backend/.env` 复量（规格 §8.1）

> **本节结论先说：格 2 / 格 4 与 brief 的 Expected（"四格 failed=0"）不符，实测 `2 failed`。
> 已归因，且归因结果说明"不等"来自 brief Step 3 这段测量手法自己的残留物，不是收集面/配置的 cwd 依赖。
> 详见下方"归因"小节。数字未做任何放宽或凑改。**
>
> **【修复轮 1 状态更新（保留本节原文不删）】**上面这句"不符"是**首轮手法的产物**，不是被测事实。
> brief Step 3 已按 controller 裁定 R6 改为"用 `mktemp -d` 把 `.env` 挪出仓库"，
> 照新手法重跑格 2 / 格 4 后：**四格齐平 `1316 passed / 0 failed / rc=0`**。
> 判定（B0-04 要求四格齐平）**没变**，变的只有测量手法。终稿读数、provenance 与复原校验见文末《修复轮 1》。
> 下面两处 `2 failed`（格 2 / 格 4）就此标记为 **superseded**，但**故意保留全文**：
> 它是《门的敏感性证据》的物证之一，也是"手法残留能红到什么程度"的现场记录。

四格各自独立跑（格 3/4 用 `(cd backend && …)` 子 shell，cwd 不漂移 —— 台账 R5 的修正形态），
每格输出重定向到 `/tmp/b0-cN.txt` 后取 `tail -1`。

### 格 1：cwd=仓库根，`.env` 在场（既有形态）

```
$ python -m pytest backend/tests -q > /tmp/b0-c1.txt 2>&1; tail -1 /tmp/b0-c1.txt
rc=0
1316 passed, 36 warnings, 1133 subtests passed in 122.76s (0:02:02)
```

wall clock（`time`）：`real 2m6.597s`。

### 格 2：cwd=仓库根，`.env` 移开（brief 指明的 CI 形态）

```
$ mv backend/.env backend/.env.bak
$ python -m pytest backend/tests -q > /tmp/b0-c2.txt 2>&1; tail -1 /tmp/b0-c2.txt
rc=1
2 failed, 1314 passed, 36 warnings, 1133 subtests passed in 100.44s (0:01:40)
$ mv backend/.env.bak backend/.env      # 复原
sha after restore: 4d7f974107dd         # 与 sha_before 相同
```

wall clock：`real 1m43.841s`。移开期间实测确认过状态：`.env exists? NO ; .env.bak exists? YES`。

失败点名（原文，`grep -n FAILED /tmp/b0-c2.txt`）：

```
92:FAILED backend/tests/test_secret_hygiene_contract.py::test_repository_tracked_files_hold_no_credential_material
93:FAILED backend/tests/test_secret_hygiene_contract.py::test_the_exemption_table_matches_the_hit_set
```

失败断言原文（截自 `/tmp/b0-c2.txt` FAILURES 段）：

```
E       AssertionError: assert {'backend/.en...g.py': 1, ...} == {'backend/.en...i.py': 1, ...}
E
E         Omitting 16 identical items, use -vv to show
E         Right contains 1 more item:
E         {'backend/.env.bak': 2}
```

### 归因：这两枚红是 Step 3 手法自带的残留，不是环境变量

链条（每一环都有实测证据，见下）：

1. brief Step 3 的"移开"= 仓库内改名 `backend/.env` → `backend/.env.bak`，
   于是在整段 pytest 期间，工作树里**多出一枚未被忽略的文件** `.env.bak`（内容是 `.env` 的逐字节副本，含凭据形态字面量）。
2. `.gitignore` 第 6 行是精确路径规则 `backend/.env`，**不匹配** `.env.bak`：
   ```
   $ grep -n -i env .gitignore
   4:.venv/
   5:venv/
   6:backend/.env
   15:frontend/.env.local
   $ git check-ignore -v backend/.env.bak
   rc=1 (1 = NOT ignored)
   ```
3. SEC-A 的 secret 卫生门扫描面定义在 `backend/tests/test_secret_hygiene_contract.py:595` `_delivery_surface_names()`：
   `git ls-files -z --cached --others --exclude-standard` ⇒ tracked **∪ 未被忽略的 untracked**。
   由第 2 环，`.env.bak` 落进扫描面。
4. 于是两枚用同一份扫描实现的钉子各红一次：
   - `test_repository_tracked_files_hold_no_credential_material`：`.env.bak ×2 未豁免`；
   - `test_the_exemption_table_matches_the_hit_set`（反向闸，要求命中集与豁免表**互等**）：命中集凭空多一档 `{'backend/.env.bak': 2}`。
   见 `backend/tests/test_secret_hygiene_contract.py:626` 与 `:635`。

**关键判读**：这两枚红**与 `.env` 是否在场无关**，只与 `.env.bak` 是否在树里有关。
所以 brief Expected 那句"四格 `failed=0`"按 Step 3 现写法（仓库内改名）**不可能成立**——
它测到的不是"CI 形态"，而是"CI 形态 + 一枚 SEC-A 眼里像凭据泄漏的新文件"。
属 B0 靶区但归因清楚（§10.3），交 Task 2 之后决定：改名目标挪出交付面（如仓库外临时目录），
或让 B0 的门在扫 SEC-A 面之前先排除自己的测量残留。**本任务不改测试、不改门、不放宽判据。**

### 格 3：cwd=`backend`，`.env` 在场

```
$ (cd backend && python -m pytest tests -q > /tmp/b0-c3.txt 2>&1); tail -1 /tmp/b0-c3.txt
rc=0
1316 passed, 36 warnings, 1133 subtests passed in 98.14s (0:01:38)
```

wall clock：`real 1m41.218s`。node id 形状 `tests/test_model_router_v23_contract.py::`（**不带** `backend/` 前缀）——
这是"这一格真的从 `backend/` 跑"的物证，不是靠 `cd` 措辞自证。

> 第一次尝试这格时我把 `time` 写成 `time ((cd backend && …))`，bash 把 `((` 当算术展开，
> 报 `syntax error in expression` 且**根本没启动 pytest**（`/tmp/b0-c3.txt` 不存在）。
> 已改成 `time (cd backend && …)` 重跑，上面是重跑的真实读数。记录在此以免被误读成"跑过一次失败的格"。

### 格 4：cwd=`backend`，`.env` 移开

```
$ mv backend/.env backend/.env.bak
$ (cd backend && python -m pytest tests -q > /tmp/b0-c4.txt 2>&1); tail -1 /tmp/b0-c4.txt
rc=1
2 failed, 1314 passed, 36 warnings, 1133 subtests passed in 106.02s (0:01:46)
$ mv backend/.env.bak backend/.env
restored sha: 4d7f974107dd
```

wall clock：`real 1m52.063s`。失败点名与格 2 **同名同因**（路径前缀随 cwd 变成 `tests/`）：

```
92:FAILED tests/test_secret_hygiene_contract.py::test_repository_tracked_files_hold_no_credential_material
93:FAILED tests/test_secret_hygiene_contract.py::test_the_exemption_table_matches_the_hit_set
```

### 对照格 2′ / 4′（本任务补测，用于坐实上面的归因）

brief 的写法把两个变量绑在一起测（`.env` 不在场 **且** `.env.bak` 多出来）。
为把"env 维度"单独量出来，另跑两格：**同样让 `backend/.env` 不在场，但把它挪到仓库外**
（`/tmp/b0-env-parked.env`，Git Bash 的 TMPDIR，落在交付面之外），跑完立刻挪回并核 sha。

```
$ mv backend/.env /tmp/b0-env-parked.env
$ python -m pytest backend/tests -q          # 格 2′：cwd=仓库根
1316 passed, 36 warnings, 1133 subtests passed in 147.88s (0:02:27)   rc=0
$ (cd backend && python -m pytest tests -q)  # 格 4′：cwd=backend
1316 passed, 36 warnings, 1133 subtests passed in 159.60s (0:02:39)   rc=0
$ mv /tmp/b0-env-parked.env backend/.env     # 两次都回到 4d7f974107dd
```

**归因闭环**：`.env` 真不在场时两格都 **1316 passed / rc=0**，
加上场版格 1/格 3 也是 1316 passed ⇒ `.env` 这个维度对结果**中性**；
格 2/格 4 的 `2 failed` 全部由 `.env.bak` 残留解释。

### 四格矩阵总表（含对照格）

| 格 | cwd | `backend/.env` | 树里有 `.env.bak`? | 末行读数 | passed | failed | errors | rc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 仓库根 | 在场 | 无 | `1316 passed, 36 warnings, 1133 subtests passed in 122.76s (0:02:02)` | 1316 | 0 | 0（未印即 0） | 0 |
| 2 | 仓库根 | 移开（改名在树内） | **有** | `2 failed, 1314 passed, 36 warnings, 1133 subtests passed in 100.44s (0:01:40)` | 1314 | **2** | 0 | 1 |
| 3 | backend | 在场 | 无 | `1316 passed, 36 warnings, 1133 subtests passed in 98.14s (0:01:38)` | 1316 | 0 | 0 | 0 |
| 4 | backend | 移开（改名在树内） | **有** | `2 failed, 1314 passed, 36 warnings, 1133 subtests passed in 106.02s (0:01:46)` | 1314 | **2** | 0 | 1 |
| 2′ | 仓库根 | 移开（挪出仓库） | 无 | `1316 passed, 36 warnings, 1133 subtests passed in 147.88s (0:02:27)` | 1316 | 0 | 0 | 0 |
| 4′ | backend | 移开（挪出仓库） | 无 | `1316 passed, 36 warnings, 1133 subtests passed in 159.60s (0:02:39)` | 1316 | 0 | 0 | 0 |

**"哪两格只差 env 在场"**：`(格 1, 格 2)` 同为 cwd=仓库根、`(格 3, 格 4)` 同为 cwd=backend，
这两对各自"只差 `.env` 那一维"；`(格 1, 格 3)` 与 `(格 2, 格 4)` 则只差 cwd。
四格确为四个**不同**的命令组合（台账 R5 的要求满足；node id 前缀 `backend/tests/` vs `tests/` 是独立物证）。

**等读判定（分两轴，不含混）**：

- **收集轴**：六格读数全部 `passed + failed = 1316`，`errors=0` ⇒ **收集面/配置对 cwd 与 `.env` 均无依赖，GREEN**。
  Task 2 的 `EXPECTED_COLLECTED` 基线因此可以钉 1316。
- **通过轴**：四格不等（1316 vs 1314+2failed），与 brief Expected 冲突 ⇒ **按 brief 原文判 FAIL**，已归因如上。
  等价表述：若 B0 的门照 brief 这段写法实现，它会**永久红在 SEC-A 的门上**；
  而 CI 里 `backend/.env` 从来不存在（gitignored，不会凭空造），所以 **CI 的真实形态 = 对照格 2′/4′（1316 passed）**，
  brief 那句"格 2 才是 CI 形态" env 维度说对了、残留维度说漏了。

### `backend/.env` 完整性（移开=改名，全程未删除）

| 时点 | sha256 前 12 位 |
| --- | --- |
| 动手前 `sha_before` | `4d7f974107dd` |
| 格 2 复原后 | `4d7f974107dd` |
| 格 4 复原后 | `4d7f974107dd` |
| 对照 2′ 复原后 | `4d7f974107dd` |
| 对照 4′ 复原后（= 收工态） | `4d7f974107dd` |

前后一致 ✓。收工复核：`.env present` / `.env.bak absent (clean)` / park 文件 `absent (clean)`，
每次移开都挂了 `trap … EXIT` 兜底（实际未触发过，全靠显式 `mv` 复原）。

---

## Step 4：基线明细文件

Run：

```
$ python scripts/b0_collection_probe.py --node-ids --out .superpowers/sdd/ENTERPRISE_B0_PLAN/baseline/collected-node-ids.txt
wrote .superpowers\sdd\ENTERPRISE_B0_PLAN\baseline\collected-node-ids.txt (1316 node ids)
rc=0
real	0m30.203s
```

Expected `wrote ... (1316 node ids)` ⇒ **GREEN**（路径分隔符按 Windows 原样打印为反斜杠，枚数正确）。

文件自证：

```
行数            1316            （= 每行一枚 node id，无夹带表头/尾行）
distinct 模块   39              （cut -d: -f1 | sort -u | wc -l，与 Step 2 的 39 行计数一致）
字节数          162455
含 CR 的行数    0               （newline="\n" 强制 LF，供 Task 4 的行尾钉使用）
首行  backend/tests/test_agent_contracts.py::AgentContractsTest::test_agent_loop_is_bounded_and_discards_hidden_reasoning_from_trace
末行  backend/tests/test_web_security.py::WebSecurityTest::test_userinfo_and_local_suffix_rejected
```

路径按 controller 裁定 R0 落在 `ENTERPRISE_B0_PLAN/baseline/`（brief 正文的 `ENTERPRISE_B0/baseline/` 为旧称）。
定位重申：这枚文件是 Task 2 失败信息的**对照源**，不是判据本体；判据是常数 `EXPECTED_COLLECTED`。

---

## 附：`--collect-only` 两枚 cwd 的耗时

| cwd | 命令 | 墙钟 | pytest 自报收集耗时 | 收集枚数 |
| --- | --- | --- | --- | --- |
| 仓库根（探针内部形态） | `python scripts/b0_collection_probe.py` | `real 1m1.688s`（冷） | 未印（探针只数行） | 1316 |
| 仓库根（同一形态，热跑） | `python scripts/b0_collection_probe.py --node-ids --out …` | `real 0m30.203s` | 未印 | 1316 |
| `backend` | `(cd backend && python -m pytest tests -q --collect-only)` | `real 0m34.924s`（另一次 `0m30.600s`） | `1316 tests collected in 27.70s` | 1316 |

耗时与 brief/环境说明给的 "40–62 s" 对照：冷跑 `61.7 s` 落在区间内，**热跑 `30.2 s` / `34.9 s` 低于区间下限**。
原因可指认——`.pytest_cache` 在仓库根已 warmed（`ls -a` 见 `.pytest_cache/`），二次收集跳过重解析。
判读：**耗时不是稳定判据，别拿它当门**；只有枚数是。若后续任务用耗时设阈值会随机红。

### 顺带量到的一条探针性质（Task 2 必须知道）

`--collect-only` 从 `backend/` 跑时，node id 前缀**随 cwd 变**：

```
^tests/[^:]+::         count = 1316
^backend/tests/[^:]+:: count = 0
```

探针的 `NODE_ID = re.compile(r"^backend/tests/[^:]+::")` 因此是 **cwd 耦合**的：
只要 `collected_node_ids()` 的 `cwd=root` 里 `root` 被换成 `backend/`，它会静默匹配 0 枚
（本探针在这种情况下返回 `TOTAL 0` 而非报错——`rc` 仍是 0）。
这不是缺陷修复项，而是"探针必须钉 `cwd=REPO_ROOT`"这条约束的**理由**；
Task 2 复用同一量法时不许把 root 参数化到别处，否则门会绿变成 0 枚。

---

## Step 5a：`git status --porcelain` 基线原文（Task 4 的 no-op 对照物）

**动手前**（Task 1 起点，脚本尚未创建）：

```
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
```

**Step 6 收工后**（唯一增量是探针脚本；快照与基线文件在 `.superpowers/` 里，被 gitignore 挡掉）：

```
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

HEAD 基线：`git rev-parse HEAD` = `7cc5efc0460abb01171c20cee61ef01bf5282a3d`（短 `7cc5efc`）。

### 两枚 identity 文件的基线 sha（台账 R3 要的强判据）

```
$ python - <<'PY'
import hashlib
from pathlib import Path
for rel in ("backend/app/identity/README.md", "backend/app/identity/__init__.py"):
    print(rel, hashlib.sha256(Path(rel).read_bytes()).hexdigest()[:12])
PY
backend/app/identity/README.md 3bc681bbc52c
backend/app/identity/__init__.py 2cfab9f18182
```

收工后**复量同值**（Task 1 全程没碰它们）：

```
backend/app/identity/README.md 3bc681bbc52c
backend/app/identity/__init__.py 2cfab9f18182
```

这两枚是**别的特性留下的既有未提交改动，不属于本任务**，按 controller 指示原样留着、不提交、不还原。
`git status --porcelain -- backend/app` 前后同为这两行（**非空**，正是 R3 说的"基线非空"）：

```
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
```

Task 5 Step 4 判"B0 有没有越界改 app"时，请比对**上面这两枚 sha**，不要比对"列表是否为空"。
另外 `git diff --stat -- backend/app` 附带印出：

```
warning: in the working copy of 'backend/app/identity/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/identity/__init__.py', LF will be replaced by CRLF the next time Git touches it
 backend/app/identity/README.md   | 13 ++++++++-----
 backend/app/identity/__init__.py | 13 ++++++++++---
 2 files changed, 18 insertions(+), 8 deletions(-)
```

这两条 CRLF warning 是 **`.gitattributes` 缺席的现症**，属 Task 4 的靶区，本任务原样记录不处理。

---

## Step 5b：`progress.md` 台账追加

按 brief 要求写入完成行，但**限定语不敢省**（否则"四格等读"会被后来人当成通过轴也等）：

```
- **Task 1 complete：基线 1316 / 四格等读 / no-op 对照基线已存**（"等读"限定在**收集轴**：六格
  `passed+failed` 皆 1316、`errors=0`；**通过轴不等** —— 格 2/格 4 实测 `2 failed`，见 R6。
- **R6 Step 3 的"仓库内改名 `.env` → `.env.bak`"会把 SEC-A 的门拖红（Task 1 实测发现）**：…
```

R6 记的是**发现**不是**裁定**：挪出交付面 vs. 让门排除自身残留，两条路都能走，
留给 controller 在 Task 2 派发前定（本任务无权改 brief 的 Expected，也无权改测试）。

---

## Step 6：快照（代替提交）

```
$ mkdir -p .superpowers/sdd/ENTERPRISE_B0_PLAN/snap-task1-post
$ cp scripts/b0_collection_probe.py .superpowers/sdd/ENTERPRISE_B0_PLAN/snap-task1-post/
$ git status --porcelain
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
```

快照与在用脚本同 sha（`a62e3e228e5e` 两边一致），拷贝可信。

**与 Expected 的偏差（性质说明，非失败）**：brief 预期"`git status --porcelain` 只多出
`scripts/b0_collection_probe.py` 与 `.superpowers/sdd/ENTERPRISE_B0/**`"。实测只多出前者，
因为 `.gitignore:25` 有 `.superpowers/` 规则 ⇒ 工作区过程件默认不被跟踪：

```
$ git check-ignore -v .superpowers/sdd/ENTERPRISE_B0_PLAN/baseline/collected-node-ids.txt
.gitignore:25:.superpowers/	.superpowers/sdd/ENTERPRISE_B0_PLAN/baseline/collected-node-ids.txt
```

后果要说清：**基线明细文件与本报告不进 git**（`.gitignore` 第 23 行注释写明"过程证据以 `-f` 精选入库，默认不跟踪"）。
Task 2 若要把 `collected-node-ids.txt` 变成可评审的入库交付物，需要显式 `git add -f`
—— 本任务无提交权限，**不做**，仅在此登记。

---

## 逐步判定汇总

| Step | 判据 | 实测 | 判定 |
| --- | --- | --- | --- |
| 1 | 探针逐字落盘，接口 `main()`/`collected_node_ids()` | `scripts/b0_collection_probe.py`，sha `a62e3e228e5e`，可运行 | GREEN |
| 2 | `TOTAL 1316` + 39 行模块计数 | 1316 / 39 行（和亦 1316） | GREEN |
| 3 | 四格 `passed` 全等、`failed=0`、`errors=0`、四格命令互异 | 收集轴等读（六格皆 1316）；**通过轴不等：格 2/格 4 `2 failed`**；命令确为四组合 | **FAIL（已归因，非本任务可修）** |
| 3（**修复轮 1 复量，本判定的终稿**） | 同上（判据未变、未放宽） | 手法改为 `mktemp -d` 挪出仓库后重跑格 2/格 4：四格齐平 `1316 passed / 0 failed / rc=0`，命令仍为四组合 | **GREEN**（首轮那行的 FAIL 属手法残留，已由同判据的正确复量取代） |
| 4 | `wrote … (1316 node ids)` | 同值；文件 1316 行 / 39 模块 / LF | GREEN |
| 5 | 报告 + progress 台账 + identity sha 基线 | 本报告 + `progress.md` 追加 R6 | GREEN |
| 6 | 快照；只多出探针与工作区 | 快照已存；`backend/app/**` 一字未动（sha 复量同值）；工作区因 gitignore 不入 git | GREEN（偏差已注） |

## 交给 Task 2 的常数与提醒

1. `EXPECTED_COLLECTED` 基线 = **1316**（本任务未加任何测试；Task 2 自加 13 枚 ⇒ 1329，与台账冲突扫描表一致）。
2. 门复用 `collected_node_ids()` 时**必须保持 `cwd=REPO_ROOT`**：正则 `^backend/tests/` 是 cwd 耦合的，
   换 root 会静默得 0（见上文附节）。
3. 若 B0 的门/脚本还要做"`.env` 不在场"这类复量，**改名目标别落在仓库里**——
   `backend/.env.bak` 不被 `.gitignore` 匹配，会进 SEC-A 的交付面扫描，把 SECA-20 两枚钉子拖红。
   CI 真实形态下 `backend/.env` 根本不存在，也绝不存在 `.env.bak`，对应本报告的对照格 2′/4′（1316 passed）。
   **（修复轮 1 更新：这条已由 controller 裁定 R6 写进 brief Step 3 正文，mandate 形态 = `HOLD="$(mktemp -d)"; mv backend/.env "$HOLD/env"` → 跑 → `mv "$HOLD/env" backend/.env; rmdir "$HOLD"` → 断言 `git status --porcelain` 回基线。Task 2 直接抄该形态，别再自创"树内改名"。）**
4. **（修复轮 1 新增）门的敏感性是可用证据，不必另造**：一枚未跟踪未忽略的文件即可同时红
   `test_repository_tracked_files_hold_no_credential_material` 与 `test_the_exemption_table_matches_the_hit_set`，
   删掉即复绿（见文末《交付面扫描门的敏感性证据》）。Task 5 写 B0-09 验收时可直接引这组 node id + 门的原文。

---

## 收工自检（把上文两处"我说是"变成机器说的）

```
$ awk 'NR>1 {s+=$1; n++} END {print "rows="n, "sum="s}' /tmp/b0-probe.txt
rows=39 sum=1316
```

⇒ Step 2 那句"39 行计数与 TOTAL 自洽"由手算升级为机器算，无差额。

基线明细文件的形状不变量（Task 2 的对照源要经得起这三问）：

```
lines: 1316
all match ^backend/tests/...:: : True
sorted == as-written: True
duplicates: 0
```

工作树收工态（与 Step 6 同读，未因后续写报告而漂移）：

```
$ git status --porcelain
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
$ test -f backend/.env        → .env present
$ test -f backend/.env.bak    → absent (clean)
$ sha256(backend/.env)[:12]   → 4d7f974107dd（= sha_before）
$ sha256(两枚 identity)[:12]  → 3bc681bbc52c / 2cfab9f18182（= 基线，一字未改）
```

未做的事（按约束刻意不做）：任何 `git add`/`commit`/`stash`/`checkout`/`restore`/`clean`/`config`；
未动 `backend/app/**`、`frontend/**`、`docker-compose.yml` 与既有 `scripts/*`；未装包、未联网、未起 docker；
未派发任何子代理；未为了让格 2/格 4 绿而放宽任何断言或改写任何测试。

---

## 修复轮 1（R6 裁定落地：判定不变、手法改对，重测格 2 / 格 4）

> 本轮性质：**只重测被裁定为"测量手法错"的两格 + 更正本报告**。
> 不修门、不改测试、不放宽任何断言与期望值；`backend/app/**`、`backend/tests/**`、`frontend/**`、
> 既有 `scripts/*`、`docker-compose.yml` 一字未动；零 git 写操作（读 `git status`/`rev-parse`/`ls-files`/`check-ignore`）。

### 裁定与本轮动作

controller 裁定 R6：**判定不变、手法已修**。B0-04 仍要求四格齐平 `1316 passed / 0 failed`；
brief Step 3 已改写为"用 `mktemp -d` 把 `backend/.env` 挪出仓库、跑完立刻放回、并断言 `git status --porcelain` 回到基线"。
本轮就是照改写后的 Step 3 原文重跑 **格 2** 与 **格 4**（格 1 / 格 3 不受该手法缺陷影响，读数继续沿用）。

本轮实际执行序列（两格各自独立，一条命令内完成 park → 跑 → 复原 → 校验，挂了 `trap … EXIT` 兜底防残留）：

```bash
sha_before=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest()[:12])")
HOLD="$(mktemp -d)"; trap 'test -f "$HOLD/env" && mv "$HOLD/env" backend/.env' EXIT
mv backend/.env "$HOLD/env"            # 挪出仓库：树里既无 .env 也无 .env.bak
python -m pytest backend/tests -q > /tmp/b0-cN.txt 2>&1
mv "$HOLD/env" backend/.env; rmdir "$HOLD"
sha_after=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest()[:12])")
git status --porcelain                 # 必须与基线逐行相同
```

park 目录用 `mktemp -d` 落在仓库外（Git Bash 的 `$TMPDIR`），
且校验过：**跑的那一刻树里既没有 `backend/.env` 也没有任何 `backend/.env.bak`**。

### 格 2（修正手法重跑）：cwd=仓库根，`.env` 挪出仓库

```
$ mv backend/.env "$HOLD/env"      # HOLD=/tmp/tmp.XavyaBQQnz（mktemp -d，仓库外）
  .env absent ; .env.bak absent    # 移开期间的实测树状态
$ python -m pytest backend/tests -q > /tmp/b0-c2.txt 2>&1
rc=0
1316 passed, 36 warnings, 1133 subtests passed in 195.89s (0:03:15)
$ grep -c FAILED /tmp/b0-c2.txt → 0
$ mv "$HOLD/env" backend/.env ; rmdir "$HOLD"
env sha 4d7f974107dd -> 4d7f974107dd
```

wall clock：`real 3m24.079s`。末行原文即上面那一句，**failed=0、errors 未印即为 0、rc=0**。
⇒ **与 brief Expected 相符**；原格 2 那句 `2 failed, 1314 passed`（树内改名手法）就此作废（superseded）。

### 格 4（修正手法重跑）：cwd=`backend`，`.env` 挪出仓库

```
$ mv backend/.env "$HOLD/env"      # HOLD=/tmp/tmp.JfQF8ryjWt（mktemp -d，仓库外）
  .env absent ; .env.bak absent
$ (cd backend && python -m pytest tests -q > /tmp/b0-c4.txt 2>&1)
rc=0
1316 passed, 36 warnings, 1133 subtests passed in 189.63s (0:03:09)
$ grep -c FAILED /tmp/b0-c4.txt → 0
$ mv "$HOLD/env" backend/.env ; rmdir "$HOLD"
env sha 4d7f974107dd -> 4d7f974107dd
```

wall clock：`real 3m18.006s`。
**cwd 物证**（不靠 `cd` 措辞自证）：本输出文件里的路径形状是
```
tests/test_...py（warning 段实测 3 例均不带 `backend/` 前缀）
```
与格 2 的 `backend/tests/...` 形状不同 ⇒ 这一格确实从 `backend/` 起跑。

### 四格总表（修复轮 1 定稿，含 provenance）

| 格 | cwd | `backend/.env` | 末行读数（原文） | passed | failed | rc | 出处 / provenance |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 仓库根 | 在场 | `1316 passed, 36 warnings, 1133 subtests passed in 122.76s (0:02:02)` | 1316 | 0 | 0 | **首轮 Step 3**（本轮未重跑：该格不涉及缺陷手法，读数仍有效） |
| 2 | 仓库根 | 缺席 | `1316 passed, 36 warnings, 1133 subtests passed in 195.89s (0:03:15)` | 1316 | 0 | 0 | **修复轮 1 重跑**（`mktemp -d` 挪出仓库；首轮同格的 `2 failed` 读数保留在上文，标记为 superseded） |
| 3 | backend | 在场 | `1316 passed, 36 warnings, 1133 subtests passed in 98.14s (0:01:38)` | 1316 | 0 | 0 | **首轮 Step 3**（同格 1，不涉及缺陷手法） |
| 4 | backend | 缺席 | `1316 passed, 36 warnings, 1133 subtests passed in 189.63s (0:03:09)` | 1316 | 0 | 0 | **修复轮 1 重跑**（同格 2 的修正手法；首轮 `2 failed` 同样 superseded） |

**通过轴等读判定（本轮主判据）**：四格 `passed=1316`、`failed=0`、`errors` 未印即 0、`rc=0` —— **四格齐平，GREEN**。
B0-04 要求的"四格齐平 `1316 passed / 0 failed`"就此达成，且是在**没有测量残留**的前提下达成的。

**收集轴**：四格 `passed+failed=1316` 与首轮六格、Step 2 探针 `TOTAL 1316` 三方互证 ⇒ `EXPECTED_COLLECTED` 基线钉 **1316** 不受本轮影响。

**首轮对照格 2′ / 4′ 的地位**：修复轮 1 的格 2 / 格 4 与它们是**同一手法**（挪出仓库）的两次独立复现，
读数一致（1316 passed / rc=0）。对照格不是孤证了：`env 维度中性` 这一判现在有 4 次独立跑支持（2、2′、4、4′）。
**首轮的 2′/4′ 记录与格 2/格 4 的 `2 failed` 记录都原样保留在上文，不删除** ——
`.env.bak` 那段是"测量残留会把 SEC-A 门拖红"的**现场事故记录**，与下文《门的敏感性证据》里
刻意做的那次最小化复验互为两证（一次是意外踩到、一次是主动植入并撤除）。

### 复原校验（R6 明文要求的两条，实测原文）

```
$ git status --porcelain                      # 复原后
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py
$ diff <(那五行的基线原文) <(当前 git status --porcelain) → 无差异
IDENTICAL: git status 与基线逐行相同                       # 机器判定，不是"我看了下"
```

- **`git status` 等式**：与 Step 5a 记录的基线**逐行相同**（5 行，含那两枚既有 identity 改动）。
- **`.env` sha**：`4d7f974107dd -> 4d7f974107dd`（格 2、格 4 各测一次，两次的 `sha_before` 与 `sha_after` 均等于首轮登记的值）。
- **残留清零复核**：`backend/.env.bak` absent、`B0_SENSOR_PROBE.env` absent、`mktemp -d` 目录已 `rmdir`（`ls -d /tmp/tmp.??` 无输出）、无 `*b0-env-parked*`。
- **identity 两枚未被牵连**：`3bc681bbc52c` / `2cfab9f18182`，与 Step 5a 基线同值。
- **扫描面收工态**：`git ls-files --cached --others --exclude-standard | wc -l` = **316** 枚名（不含 `backend/.env`，它由 `.gitignore:6` 挡住；不含任何 `.env.bak`）。

### 交付面扫描门的敏感性证据（Task 5 可直接引给 B0-09）

**结论先说**：SEC-A 的 secret 卫生门**是活的、且归因准确** —— 单单一枚"未跟踪但没被忽略"的文件落进树里，
就同时打红两枚钉子；把这枚文件删掉，两枚立刻复绿。全程只跑那一个模块（46 枚，约 30 s/次），没动任何测试。

三步实测（同一模块 `backend/tests/test_secret_hygiene_contract.py`）：

| 步 | 树状态 | 读数（末行原文） | rc |
| --- | --- | --- | --- |
| A 基线 | 无额外文件 | `46 passed in 31.52s` | 0 |
| B 植入 | 多出**一枚**未跟踪文件 `B0_SENSOR_PROBE.env`（内容 = 合成字面量 `JWT_SECRET="<32 字节假值>"`，非真凭据） | `2 failed, 44 passed in 29.93s` | 1 |
| C 撤除 | 删掉那一枚 | `46 passed in 32.29s` | 0 |

**变红的两枚 node id（原文）**：

```
FAILED backend/tests/test_secret_hygiene_contract.py::test_repository_tracked_files_hold_no_credential_material
FAILED backend/tests/test_secret_hygiene_contract.py::test_the_exemption_table_matches_the_hit_set
```

**门的归因原文（不是我们替它编的）**：

```
E  AssertionError: 交付面出现凭据形态的字面量：… B0_SENSOR_PROBE.env ×1 未豁免
E  assert [] == ['B0_SENSOR_PROBE.env ×1 未豁免']
E  AssertionError: assert {'backend/.en...i.py': 1, ...} == {'B0_SENSOR_P...i.py': 1, ...}
E    Right contains 1 more item:
E    {'B0_SENSOR_PROBE.env': 1}
```

**让它们复绿的是什么**：`rm B0_SENSOR_PROBE.env` —— 只删掉那枚测量残留，没碰任何断言、没碰豁免表、没碰 `.gitignore`。
⇒ 门的红/绿**完全跟随扫描面（`git ls-files -c -o --exclude-standard`）的实际内容**，这正是它该有的性质。

**为什么这条对 B0-09 值钱**：
1. **门没瞎**：一枚新文件 = 一处命中 = 两枚钉子同时红（正向那条报"未豁免"，反向那条报"命中集多出 `{'…': 1}`"）。
   这两枚用的是同一份 `_hit_counts`/`_delivery_surface_names` 实现（`test_secret_hygiene_contract.py:580`/`:595`），
   所以红得**同步**、指得**同名**——不是两件事各红一半。
2. **归因到文件级**：失败信息给的是 `(路径, 处数)`，本轮实测为 `B0_SENSOR_PROBE.env ×1`，
   与被植入的那一枚逐字相符；没有"某个集合不相等"式的黑洞信息。
3. **B0 的测量自己也会踩它**：首轮格 2/格 4 的红就是同一条性质被"仓库内改名"踩到的结果。
   ⇒ 任何后续脚本/门若要做"`.env` 不在场"这类复量，**残留必须落在交付面之外**（`mktemp -d`，本轮形态），
   否则门会把测量自己的残留当泄漏报。
4. 附带边界（供 Task 5 写验收口径时照抄，别说过头）：门扫的是**交付面**，
   `backend/.env` 本身被 `.gitignore:6` 挡在射程外，`.superpowers/**` 由 `_UNSCANNED_PREFIXES` 整目录排除
   （`test_secret_hygiene_contract.py:433`）—— 所以"门是活的"**不等于**"仓内绝无凭据材料"。

### 修复轮 1 收工态（机器判定，非"我看了下"）

```
$ git status --porcelain | diff - <基线五行原文>            → 无输出（IDENTICAL）
$ sha256(backend/.env)[:12]                                 → 4d7f974107dd（= 首轮 sha_before，两格各复量一次同值）
$ test -e backend/.env.bak                                  → absent
$ test -e B0_SENSOR_PROBE.env                               → absent
$ ls -d /tmp/tmp.??（两次 mktemp -d 的 park 目录）          → 无输出，已 rmdir
$ sha256(identity 两枚)[:12]                                → 3bc681bbc52c / 2cfab9f18182（= Step 5a 基线）
$ git ls-files --cached --others --exclude-standard | wc -l → 316
$ git rev-parse HEAD                                        → 7cc5efc0460abb01171c20cee61ef01bf5282a3d（未动）
```

本轮**依旧**没做的事：任何 `git add`/`commit`/`push`/`stash`/`checkout`/`restore`/`clean`/`config`（只用了
`status`/`rev-parse`/`ls-files`/`check-ignore`/`diff`）；未改 `backend/app/**`、`backend/tests/**`、`frontend/**`、
既有 `scripts/*`、`docker-compose.yml`；未装包、未联网、未起 docker；未派发子代理；
**未为了让数字好看而放宽任何断言或改写任何期望值** —— 本轮唯一的改动是把测量手法里的残留物拿掉。

一处诚实的读数差异：本轮两格的墙钟（`3m24s` / `3m18s`）明显长于首轮同两格（`1m44s` / `1m52s`），
也长于对照格 2′/4′（`2m28s` / `2m39s`）。这是 I/O 与机器负载抖动，不属判据；
沿袭首轮结论 **"耗时不是稳定判据，别拿它当门"**（见上文《附：`--collect-only` 两枚 cwd 的耗时》），
故本轮只报枚数与 rc，不给耗时设任何阈值。









