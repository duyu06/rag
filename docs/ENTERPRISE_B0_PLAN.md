# ENTERPRISE-B0 门禁地基 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `backend-contracts` 从"一枚收不到裸函数的 unittest 步 + 一份会漂移的手写依赖清单"改成"单一 pytest runner + 依赖与 `requirements.txt` 同源 + 收集数被钉住"，并把行尾归一化从机器属性变成仓库属性。

**Architecture:** 四枚结构门（收集数 / 单 runner / 依赖同源 / 行尾形状）住在一枚新测试文件里，由它们反向规定 `ci.yml` 与 `.gitattributes` 的形状；B0 不改 `backend/app/**` 的任何一行，因此"门会不会自己骗自己"是唯一的判定面。

**Tech Stack:** Python 3.12（CI）/ 3.13.7（宿主）、pytest、GitHub Actions（ubuntu-latest）、Git（`git ls-files --eol`、`git ls-files -z --cached --others --exclude-standard`）。

**Spec:** `docs/ENTERPRISE_B0_SPECIFICATION.md`（判据、不变量、已知限制都在那边；本计划只管"怎么做"，不重开设计）

---

## 本仓库对本计划的三处改动（用户既有规矩优先于技能默认）

1. **没有 per-task commit。** 本项目 HEAD 由用户长期规矩保持滞后，SEC-A 全程零提交、最后一次性批提交。每个任务结尾的"Commit"步骤一律替换为**快照 + 台账**：`snap-taskN-post/` 目录、`progress.md` 一行 `Ruling:`/complete 记录、`taskN-report.md`。唯一的真提交发生在 Task 7，且需要用户显式授权。
2. **子代理不得跑任何 git 写命令。** 派发实现/评审子代理时，prompt 里要明写这一条（SEC-A 全程如此）。
3. **不放宽规格与测试。** 任何一步"过不了"时，出路只有：改实现、或按 §10.3 三分法归因后停下来报告。把断言改弱、加 `skip`、删用例，一律算任务失败。

---

## Global Constraints

- `backend/app/**` 的最终 diff 必须为空（B0-12；口径：`git diff --name-only security-a-rc1 -- backend/app` ∪ 已暂存未提交 ∪ 未跟踪）。
- 不动 `backend/requirements.txt`、`docker-compose.yml`、`scripts/**` 的**既有文件**、`frontend/**`（`requirements.txt` 是被引用方，改它 = 越界）。**新增** `scripts/b0_collection_probe.py` 允许且必要（Task 1 的量法唯一实现）——B0 禁的是改动既有交付脚本，尤其 `scripts/deploy.ps1`（CI 语法校验的对象）与 `scripts/*_integration.py`。这条厘清见 §"Rulings" R1，SEC-A 先例是 `scripts/sec_a_fresh_boot_probe.py` 与 `sec_a_smoke_http.py` 两枚新探针入库。
- 不动两枚 tag：`model-router-v2.3-rc1`、`security-a-rc1`。不 amend、不移位、不重写历史。
- `.gitattributes` 必须是可证明的 no-op（B0-007）：**基线工作树本来就不干净**（`backend/app/identity/README.md`、`backend/app/identity/__init__.py` 两枚未提交改动），所以判据是"与基线逐行相同"，不是"干净"。
- 编辑 `.github/workflows/ci.yml` 必须保持 **CRLF**（实测该文件 134 枚 CRLF / 0 枚裸 LF）。写坏成 LF 会让整份文件在 `git diff` 里翻一遍。
- 新建文件一律 **LF**（SEC-A/V2.3 的工具产物同形态）。
- 引用 `ci.yml` 的内容时**认 step 名与正文，不认行号**。
- 状态词只用 `GREEN / PENDING_EXTERNAL / BLOCKED`；没取到读数的格子不许写 `GREEN`。
- 宿主 cp936 控制台：任何自写脚本要打印中文，先 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`（SEC-A 变异台为此踩过一次）。
- **测量不得在交付面里留副本**（R6，Task 1 实测发现）：`.gitignore` 第 6 行是**精确路径** `backend/.env`，
  所以 `.env.bak`、`env.tmp` 这类"就地改名躲一下"的写法会作为"未忽略的 untracked"落进 SECA-20 扫描门
  的面（`git ls-files --cached --others --exclude-standard`），当场把两枚钉子拖红。
  凡需要把某个文件从树里藏起来测一次，**必须挪到仓库之外**（`$TEMP` 下的一次性目录），还原后
  断言 `git status --porcelain` 与基线逐行相同。Task 1 Step 3 / Task 3 Step 6 / Task 5 Step 3 全受此约束。
  附带收益：这条敏感性本身就是 B0-09 的一条证据——门对"树里多一枚文件"确实会红，且红的归因链已被走通。
- 全量测试套件基线读数：**1316 collected / 1316 passed / 0 failed**。**耗时以 Task 1 实测为准，不套计划里的旧数**：
  四格 pytest 自报区间 **98.14–195.89s**（墙钟 101–204s），collect-only 62s / 41s 两格。
  结论沿用 Task 1 的判读：**不拿墙钟当判据**，只拿收集数与 passed/failed 当判据。

---

## File Structure

| 文件 | 责任 | 动作 |
| --- | --- | --- |
| `backend/tests/test_ci_gate_contract.py` | B0 的四枚门 + 全部解析 helper | 新建 |
| `.github/workflows/ci.yml` | 唯一被规定形状的交付面 | 修改（`backend-contracts` job） |
| `.gitattributes` | 行尾归一化的仓库属性 | 新建 |
| `scripts/b0_collection_probe.py` | 独立跑一次收集并输出 node-id 清单（门的基线文件生产者，也是排障工具） | 新建 |
| `.superpowers/sdd/ENTERPRISE_B0/baseline/collected-node-ids.txt` | 收集数钉的**明细基线**（只用于失败信息里的集合差） | 新建（证据件） |
| `.superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py` | 五发变异台 | 新建 |
| `.superpowers/sdd/ENTERPRISE_B0/{progress.md,taskN-report.md,snap-taskN-*/}` | SDD 台账与快照 | 新建 |
| `docs/ENTERPRISE_B0_SPECIFICATION.md` | 规格 | 已存在（本计划不改它，除非走修订卡） |

---

## Task 1: 基线复量与常数标定（measure-only，不产出任何交付面改动）

**Files:**
- Create: `scripts/b0_collection_probe.py`
- Create: `.superpowers/sdd/ENTERPRISE_B0/baseline/collected-node-ids.txt`
- Create: `.superpowers/sdd/ENTERPRISE_B0/task-1-report.md`
- Create: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: 无。
- Produces: `scripts/b0_collection_probe.py` 的 `main() -> int` 与 `collected_node_ids(root: Path) -> list[str]`（Task 2 的门复用同一量法）；四个格子的实测读数；`EXPECTED_COLLECTED` 的**基线值** 1316（Task 2 在此基础上加自己那一份）。

- [ ] **Step 1: 写探针脚本（这是门的量法唯一实现，门自己不许另写一套）**

```python
"""B0 收集面探针：把"收集到几枚、分别来自哪个模块"变成一行行可核对的输出。

    python scripts/b0_collection_probe.py                # 打印总数 + 逐模块计数
    python scripts/b0_collection_probe.py --node-ids     # 只打 node id，每行一枚（喂给基线文件）
    python scripts/b0_collection_probe.py --out FILE     # 写文件而不是 stdout

量法（规格 §6.1）：**统计匹配 `^backend/tests/[^:]+::` 的行数**，不解析尾行的
`N tests collected` 文句——那是给人读的，形状会变。子进程固定 `cwd=仓库根`、固定剥掉
`REAL_LLM_ACCEPTANCE`，因为 CI 的默认形态就是"那枚门关着、从仓库根跑"。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NODE_ID = re.compile(r"^backend/tests/[^:]+::")


def collected_node_ids(root: Path = REPO_ROOT) -> list[str]:
    env = dict(os.environ)
    env.pop("REAL_LLM_ACCEPTANCE", None)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q", "--collect-only"],
        cwd=root, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False)
    if child.returncode != 0:
        # 收集期非 0 就是 import 失败/配置炸了：这正是 F1 的相反面（会响），不许咽下去。
        raise RuntimeError(
            f"collect-only rc={child.returncode}\n{child.stdout[-2000:]}\n{child.stderr[-2000:]}")
    return [line.strip() for line in child.stdout.splitlines() if NODE_ID.match(line.strip())]


def module_counts(ids: list[str]) -> "Counter[str]":
    return Counter(node_id.split("::", 1)[0] for node_id in ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node-ids", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    ids = collected_node_ids()
    if args.node_ids:
        body = "".join(f"{node_id}\n" for node_id in sorted(ids))
    else:
        rows = "\n".join(f"{count:>5}  {module}" for module, count in sorted(module_counts(ids).items()))
        body = f"TOTAL {len(ids)}\n{rows}\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8", newline="\n")
        print(f"wrote {args.out} ({len(ids)} node ids)")
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 跑探针，确认 1316 与逐模块分布**

Run: `cd /e/xiangmu/rag && python scripts/b0_collection_probe.py | head -5`
Expected: 首行 `TOTAL 1316`，随后 41 行（40 枚 `test_*.py` 里 39 枚有贡献 + `test_real_llm_failover_acceptance.py` 默认 0 枚所以不出现 ⇒ 应为 **39 行**；行数不符就按实测记，不要凑）。

- [ ] **Step 3: 四格 `cwd` × `backend/.env` 复量（规格 §8.1）**

```bash
cd /e/xiangmu/rag
sha_before=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest()[:12])")

# 格 1：cwd=仓库根，.env 在场（今天的既有形态）
python -m pytest backend/tests -q > /tmp/b0-c1.txt 2>&1; tail -1 /tmp/b0-c1.txt

# 格 2：cwd=仓库根，.env 缺席 —— 这才是 CI 形态（env_file 是相对 cwd 的）
# 挪出仓库，绝不在树里留 `.env.bak`：那会落进 SECA-20 扫描面把两枚钉子拖红（Global Constraints R6）
HOLD="$(mktemp -d)"; mv backend/.env "$HOLD/env"; echo "parked at $HOLD"
python -m pytest backend/tests -q > /tmp/b0-c2.txt 2>&1; tail -1 /tmp/b0-c2.txt
mv "$HOLD/env" backend/.env; rmdir "$HOLD"

# 格 3：cwd=backend，.env 在场
(cd backend && python -m pytest tests -q > /tmp/b0-c3.txt 2>&1); tail -1 /tmp/b0-c3.txt

# 格 4：cwd=backend，.env 缺席（同样挪出仓库，同一条 R6 约束）
HOLD="$(mktemp -d)"; mv backend/.env "$HOLD/env"
(cd backend && python -m pytest tests -q > /tmp/b0-c4.txt 2>&1); tail -1 /tmp/b0-c4.txt
mv "$HOLD/env" backend/.env; rmdir "$HOLD"

sha_after=$(python -c "import hashlib;print(hashlib.sha256(open('backend/.env','rb').read()).hexdigest()[:12])")
echo "env sha $sha_before -> $sha_after"
```
四格必须**互不相同地覆盖两个维度**（用 `(cd backend && …)` 子 shell，避免 cwd 漂移把某格重复测两遍——
第一版这段就错在只测到三格、"仓库根+无 `.env`"测了两遍、"backend+无 `.env`"从没测）。
Expected: 四格 `passed` 全等、`failed=0`、`errors=0`，且四格是四个**不同**的命令组合。**任何一格不等就当场停下报告**——
那说明收集面/配置有 cwd 依赖，属 B0 靶区但要先归因（§10.3）。`env sha` 前后必须相同（移开=改名，不是删除）。

- [ ] **Step 4: 写基线明细文件**

Run: `python scripts/b0_collection_probe.py --node-ids --out .superpowers/sdd/ENTERPRISE_B0/baseline/collected-node-ids.txt`
Expected: `wrote ... (1316 node ids)`。这枚文件是 Task 2 失败信息的对照源，**不是**判据本体（判据是那个常数）。

- [ ] **Step 5: 写 task-1-report.md 与 progress.md**

`task-1-report.md` 必须含：四格读数表（含 `.env` sha 前后）、探针 TOTAL 读数、逐模块计数、collect-only 耗时两格、`git status --porcelain` 基线原文（Task 4 的 no-op 对照物），以及**这两枚 app 文件的基线 sha**（Task 5 Step 4 靠它判"B0 有没有越界改 app"，没有这行证据 Task 5 只能靠"列表为空"这种会红在别人改动上的弱判据）：

```bash
python - <<'PY'
import hashlib
from pathlib import Path
for rel in ("backend/app/identity/README.md", "backend/app/identity/__init__.py"):
    print(rel, hashlib.sha256(Path(rel).read_bytes()).hexdigest()[:12])
PY
```
`progress.md` 首行台账：`- Task 1 complete：基线 1316 / 四格等读 / no-op 对照基线已存`。

- [ ] **Step 6: 快照（代替提交）**

```bash
mkdir -p .superpowers/sdd/ENTERPRISE_B0/snap-task1-post
cp scripts/b0_collection_probe.py .superpowers/sdd/ENTERPRISE_B0/snap-task1-post/
git status --porcelain
```
Expected: 只多出 `scripts/b0_collection_probe.py` 与 `.superpowers/sdd/ENTERPRISE_B0/**`，`backend/app/**` 一字未动。

---

## Task 2: 四枚门（红相：此时它们必须红）

**Files:**
- Create: `backend/tests/test_ci_gate_contract.py`
- Modify: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: Task 1 的量法（`NODE_ID` 正则与 `cwd=仓库根`/剥离 `REAL_LLM_ACCEPTANCE` 的子进程形态）；`.superpowers/sdd/ENTERPRISE_B0/baseline/collected-node-ids.txt`。
- Produces: `_job_steps(text, job) -> list[str]`、`_step_script(step) -> str`、`_index_eol_rows() -> dict[str, str]`、`EXPECTED_COLLECTED`、`PIP_INSTALL_EXEMPTIONS`、`REQUIRED_GITATTRIBUTES_RULES`、`ALLOWED_NON_TEXT_INDEX_ENTRIES`（Task 3/4 要让这些名字成立）。

- [ ] **Step 1: 写模块头与 helper（照 SEC-A 的门文件形态：docstring 先说清每枚门对哪次事故）**

```python
"""ENTERPRISE-B0 的门禁地基契约（规格 §6）。

这个文件守的四枚门，每一枚都对应 B0 事实基线里一次已经发生过的真实形状：

1. **收集数钉（§6.1 / F1）**——SEC-A 六枚门文件里的 40 枚裸 `pytest` 函数，CI 今天只用 pytest
   跑 5 枚，其余走一枚从原理上收不到裸函数的 `unittest` 步。"有测试步"和"测试被收集"是两件
   事，本枚门把后者变成可判定的：收集数必须等于钉住的常数。
2. **单 runner 钉（§6.2 / F1、F3）**——把 `unittest discover` 加回来是最"省事"的修法，而那
   正好让本文件自己变成纸门。所以禁第二 runner 必须是机器判据，不是口头约定。
3. **依赖同源钉（§6.3 / F2）**——`f6c67b5` 把扫描步接进 CI 时远端当场 `ModuleNotFoundError:
   httpx`，因为写进 YAML 的手写清单不等于本地实测那一包集合。本枚门要求安装面引用
   `backend/requirements.txt` 本身，并把豁免收窄成一张"表 + 处数 + 为什么"的形状（沿用
   SECA-20 扫描门的 EXEMPTIONS 设计，不另起一套）。
4. **行尾钉（§6.4 / F5）**——`core.autocrlf=true` 是**每台机器**的设置，不是仓库属性：index 侧
   实测 100% LF，工作树却 LF/CRLF/MIXED 三态并存。没有 `.gitattributes` 时，下一台
   `autocrlf=false` 的机器（Linux 默认）可以把 CRLF 字节写进 index。

自我存续子钉 `test_the_gate_module_itself_is_collected` 抓的是"门还在场但哑了"（被 skip、被
marker 摘空、常数被人凑）；它**抓不到**门自己被改名或删除，那是规格 §14 L6 登记的不可消除
自指盲区，别把它当已解决。
"""
from __future__ import annotations

import functools
import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TESTS_DIR = BACKEND_DIR / "tests"
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITATTRIBUTES_FILE = REPO_ROOT / ".gitattributes"
BASELINE_NODE_IDS = (REPO_ROOT / ".superpowers" / "sdd" / "ENTERPRISE_B0_PLAN"
                     / "baseline" / "collected-node-ids.txt")

BACKEND = "backend-contracts"
```

- [ ] **Step 2: 写收集面 helper 与三枚收集钉**

```python
_NODE_ID = re.compile(r"^backend/tests/[^:]+::")
OWN_MODULE = "backend/tests/test_ci_gate_contract.py"


@functools.lru_cache(maxsize=1)
def _collected() -> tuple[str, ...]:
    """与 `scripts/b0_collection_probe.py` 同一量法：子进程、固定 cwd、剥掉验收开关。

    不在进程内用 unittest loader —— 那枚 loader 看不到裸函数（本规格 §2 的 45 枚差就是这么
    来的），用它当量法等于让门继承它要消灭的缺陷。
    """
    env = dict(os.environ)
    env.pop("REAL_LLM_ACCEPTANCE", None)
    child = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-q", "--collect-only"],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False)
    assert child.returncode == 0, (
        f"收集子进程 rc={child.returncode}；门的判据不建立在"
        f"『收不动就算过』上\n{child.stdout[-2000:]}\n{child.stderr[-2000:]}")
    return tuple(line.strip() for line in child.stdout.splitlines() if _NODE_ID.match(line.strip()))


def _per_module(ids: list[str]) -> "dict[str, int]":
    out: "dict[str, int]" = {}
    for node_id in ids:
        module = node_id.split("::", 1)[0]
        out[module] = out.get(module, 0) + 1
    return out


# 常数在 Step 5 按实测回写：1316 是 Task 1 的基线，本文件自己还要贡献 13 枚。
EXPECTED_COLLECTED = 1329


def test_collected_count_matches_the_pinned_number():
    ids = list(_collected())
    if len(ids) == EXPECTED_COLLECTED:
        return
    baseline = ([line.strip() for line in BASELINE_NODE_IDS.read_text(encoding="utf-8").splitlines()
                 if line.strip()] if BASELINE_NODE_IDS.is_file() else [])
    # `.superpowers/` 是 gitignored ⇒ **CI 里这枚明细基线根本不存在**。所以它只能用来把失败信息
    # 写得能看，绝不能进判据：判据只有"实收 == 常数"这一条，基线缺席时红照样红、只是少一份差集。
    lost = sorted(set(baseline) - set(ids))
    gained = sorted(set(ids) - set(baseline))
    raise AssertionError(
        f"收集数 {len(ids)} ≠ 钉住的 {EXPECTED_COLLECTED}。\n"
        f"消失 {len(lost)} 枚：{lost[:15]}\n新增 {len(gained)} 枚：{gained[:15]}\n"
        f"逐模块计数：{_per_module(ids)}")


def test_the_gate_module_itself_is_collected():
    """自我存续：不依赖总数，只盯"本文件贡献了几枚"。凑总数、加 skip 都会在这里红。"""
    mine = [node_id for node_id in _collected() if node_id.startswith(f"{OWN_MODULE}::")]
    assert sorted(mine) == sorted(
        f"{OWN_MODULE}::{name}" for name in _OWN_TEST_NAMES), (
        f"门自己被摘了或哑了：本文件应有 {len(_OWN_TEST_NAMES)} 枚，实收 {len(mine)} 枚")


def test_collection_measurement_counts_node_ids_not_the_summary_line():
    """解析器自己是判据的一部分：它必须能认出「尾行文句不算一枚」。

    真实形状来自 §2：`Ran N tests` 里那 20 枚差是 subTest 中断，不是收集差异。
    """
    sample = "\n".join([
        "backend/tests/test_ci_gate_contract.py::test_a",
        "backend/tests/test_ci_gate_contract.py::TestB::test_c",
        "",
        "2 tests collected in 0.01s",
    ])
    assert sum(1 for line in sample.splitlines() if _NODE_ID.match(line.strip())) == 2
```

- [ ] **Step 3: 写 ci.yml 解析 helper 与三枚 runner 钉**

```python
def _ci_text() -> str:
    return CI_FILE.read_text(encoding="utf-8")


_JOB_HEAD = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$", re.MULTILINE)


def _job_block(text: str, job: str) -> str:
    """按两空格缩进的 job 头切块。认名字，不认行号（§2 的"行号不可信"教训）。"""
    keep: "list[str]" = []
    inside = False
    for line in text.splitlines(keepends=True):
        head = _JOB_HEAD.match(line)
        if head:
            inside = head.group(1) == job
            continue
        if inside:
            keep.append(line)
    return "".join(keep)


_STEP_HEAD = re.compile(r"^      - ", re.MULTILINE)


def _job_steps(text: str, job: str) -> "list[str]":
    """每个 step 一段原文。step 内多行/折叠标量都归进同一段 ⇒ 判据只看正文里出现/没出现什么。"""
    block = _job_block(text, job)
    if not block:
        raise AssertionError(f"ci.yml 里没有 job `{job}`：门不能对『找不到』保持沉默")
    cuts = [m.start() for m in _STEP_HEAD.finditer(block)]
    if not cuts:
        raise AssertionError(f"job `{job}` 里没有 step")
    cuts.append(len(block))
    return [block[a:b] for a, b in zip(cuts, cuts[1:])]


def _test_runs(text: str, job: str) -> "list[str]":
    return [step for step in _job_steps(text, job) if "run:" in step]


def test_backend_contracts_has_no_unittest_discover_step():
    runs = _test_runs(_ci_text(), BACKEND)
    offenders = [step for step in runs if "unittest discover" in step]
    assert not offenders, (
        f"F1 复活：`backend-contracts` 里又出现 unittest 收集（{len(offenders)} 处）。"
        f"裸 pytest 函数枚枚不收，而 job 可以是绿的")


def test_backend_contracts_runs_the_pytest_suite():
    """必须是"跑整个目录"的那一步，不是 SECA-20 那种跑单文件的子集。

    `(?!/)` 是这枚门的实质：只写 `"python -m pytest backend/tests" in step` 的话，
    SECA-20 那步（`backend/tests/test_secret_hygiene_contract.py`）子串命中 ⇒ 门在改造前就绿，
    而它要防的"主门被删掉"永远抓不到。
    """
    runs = _test_runs(_ci_text(), BACKEND)
    suite_wide = [step for step in runs
                  if re.search(r"python -m pytest backend/tests(?!/)", step)]
    assert suite_wide, (
        "主门不跑全量套件：B0-01 的收集数钉必须由这一步实际执行，而不是只写在文档里。"
        "注意 SECA-20 那枚单文件子集不算——它只跑 5 枚")


def test_step_ordering_still_explains_itself():
    """顺序的两条理由（§5.2）要用文字留在树上：它俩是"为什么不顺手挪一步"的唯一长期答案。"""
    block = _job_block(_ci_text(), BACKEND)
    assert "SECA-20" in block and "unittest" in block, (
        "ci.yml 里解释扫描步为何排在主门之前的注释被删了：那正是 f6c67b5 那轮踩过的地方")
```

- [ ] **Step 4: 写依赖同源钉（含豁免表）**

```python
#: 除 requirements.txt 之外允许出现的 pip 参数 → (处数, 为什么它是豁免而不是偷懒)。
#: 形状沿用 SECA-20 扫描门的 `EXEMPTIONS`：键不含行号，处数是计数，多一处少一处都红。
PIP_INSTALL_EXEMPTIONS: "dict[str, tuple[int, str]]" = {
    "pytest": (1, "测试运行器，不是应用运行时依赖。塞进 requirements.txt 会让镜像为跑测试多背一包"),
    "torch": (1, "不是新增依赖：sentence-transformers 的传递依赖就在 requirements.txt 里。"
                "这一行只选 CPU 发行源（~200MB 而不是默认那个带 CUDA 的 ~2.5GB）"),
}


def _install_steps(text: str, job: str) -> "list[str]":
    return [step for step in _test_runs(text, job) if "pip install" in step]


def test_install_face_uses_requirements_txt_as_the_source():
    steps = _install_steps(_ci_text(), BACKEND)
    assert steps, "`backend-contracts` 没有任何安装步"
    assert any("-r backend/requirements.txt" in step for step in steps), (
        "依赖又变成 YAML 里的手写清单：`f6c67b5` 的远端 ModuleNotFoundError 就是这么来的")


def _pip_package_tokens(step_texts: "list[str]") -> "list[str]":
    """只取 `pip install` 之后的**包名** token。

    绝不拿整段 step 文本去 tokenize：那会把 YAML 注释里的中文词、`sentence-transformers`、
    `-r backend/requirements.txt` 里的 `requirements.txt` 全算成"未豁免参数"，门一落地就假红。
    带值选项（`-r` / `--index-url`）连值一起跳；含 `/` 的是路径不是包名。
    """
    takes_value = {"-r", "--requirement", "--index-url", "--extra-index-url", "-i", "-f", "--find-links"}
    out: "list[str]" = []
    for text in step_texts:
        for line in text.splitlines():
            body = line.split("#", 1)[0]          # 注释先整段丢掉
            if "pip install" not in body:
                continue
            skip_next = False
            for raw in body.split("pip install", 1)[1].split():
                token = raw.strip("\"'")
                if skip_next:
                    skip_next = False
                    continue
                if token.startswith("-"):
                    skip_next = token in takes_value and "=" not in token
                    continue
                if "/" in token or token.endswith(".txt"):
                    continue
                out.append(token)
    return out


def test_extra_pip_arguments_are_exactly_the_exemption_table():
    """三个方向都算违规（与 SECA-20 的 `_gate_offenders` 同判据）：多出来的、处数不等、死行。"""
    seen: "dict[str, int]" = {}
    for token in _pip_package_tokens(_install_steps(_ci_text(), BACKEND)):
        seen[token] = seen.get(token, 0) + 1
    offenders: "list[str]" = []
    for token, count in sorted(seen.items()):
        row = PIP_INSTALL_EXEMPTIONS.get(token)
        if row is None:
            offenders.append(f"未豁免的包 `{token}` ×{count}")
        elif count != row[0]:
            offenders.append(f"`{token}` ×{count} ≠ 豁免表 {row[0]} 处")
    offenders += [f"豁免表死行：`{token}` 当前 0 处"
                  for token in sorted(set(PIP_INSTALL_EXEMPTIONS) - set(seen))]
    assert not offenders, "安装面漂移：" + "；".join(offenders)


def test_every_exemption_row_states_why():
    for token, (count, why) in PIP_INSTALL_EXEMPTIONS.items():
        assert count >= 1, token
        assert len(why) >= 12, f"豁免行 `{token}` 的『为什么』短到不像是理由，像是占位"
```

- [ ] **Step 5: 写行尾四枚钉，并把 `EXPECTED_COLLECTED` 按实测回写**

```python
REQUIRED_GITATTRIBUTES_RULES = (
    "* text=auto",
    "*.sh text eol=lf",
    "*.ps1 text eol=crlf",
)
REQUIRED_BINARY_RULES = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.ico",
                         "*.gif", "*.woff", "*.woff2")
#: `i/-text` 的合法集合。两枚 markdown 是被 git 判成非文本的**已知状态**（含 140 / 1 个游离 CR），
#: 规格 §7 明确不在 B0 强转它们；把它写成"恰好这三枚"，才既不会静默扩多、也不会静默消失。
ALLOWED_NON_TEXT_INDEX_ENTRIES = frozenset({
    ".superpowers/sdd/SECURITY_A_PLAN/task-10d-report.md",
    "docs/MODEL_ROUTER_V23_DESIGN.md",
    "frontend/public/yaoke-logo.webp",
})
_EOL_LINE = re.compile(r"^(i/\S+)\s+(w/\S+)\s+(attr/\S*)\s*\t(.+)$")


def _index_eol_rows() -> "dict[str, str]":
    out: "dict[str, str]" = {}
    for line in subprocess.run(["git", "ls-files", "--eol"], cwd=REPO_ROOT,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", check=True).stdout.splitlines():
        row = _EOL_LINE.match(line.strip())
        if row:
            out[row.group(4)] = row.group(1)
    return out


def test_gitattributes_carries_the_required_rules():
    assert GITATTRIBUTES_FILE.is_file(), "没有 .gitattributes：行尾归一化仍由每台机器的 core.autocrlf 决定"
    rules = {line.strip() for line in GITATTRIBUTES_FILE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")}
    missing = [rule for rule in REQUIRED_GITATTRIBUTES_RULES if rule not in rules]
    assert not missing, f".gitattributes 缺必需规则：{missing}"
    binary = {rule.split()[0] for rule in rules if rule.endswith("binary")}
    assert set(REQUIRED_BINARY_RULES) <= binary, f"二进制扩展名没显式声明：{set(REQUIRED_BINARY_RULES) - binary}"


def test_index_has_no_crlf_entries():
    rows = _index_eol_rows()
    offenders = sorted(path for path, index_eol in rows.items() if index_eol == "i/crlf")
    assert not offenders, f"{len(offenders)} 枚文件的 CRLF 被提交进了 index（整文件 diff 的形状）：{offenders[:10]}"


def test_non_text_index_entries_are_exactly_the_enumerated_set():
    rows = _index_eol_rows()
    found = {path for path, index_eol in rows.items() if index_eol == "i/-text"}
    assert found == set(ALLOWED_NON_TEXT_INDEX_ENTRIES), (
        f"非文本形态漂移：多出来 {sorted(found - set(ALLOWED_NON_TEXT_INDEX_ENTRIES))}，"
        f"少了 {sorted(set(ALLOWED_NON_TEXT_INDEX_ENTRIES) - found)}。"
        f"新来一枚游离 CR 的文件，和有人把已封版工件强转文本，都走这一格")


def test_eol_rules_are_a_no_op_for_the_current_tree():
    """B0-007 的静态半边：凡被 `eol=` 规则管着的文件，工作树形态**已经**等于规则要求。

    成立 ⇒ 加 `.gitattributes` 不改变任何文件的签出形态，也就不会制造全量归一 diff。
    """
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT,
                             capture_output=True, check=True).stdout.split(b"\0")
    checked = 0
    offenders: "list[str]" = []
    for raw in tracked:
        if not raw:
            continue
        relative = raw.decode("utf-8", "replace")
        suffix = Path(relative).suffix.lower()
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        body = path.read_bytes()
        if suffix == ".sh":
            checked += 1
            if b"\r" in body:
                offenders.append(f"{relative} 含 CR，但规则要求 eol=lf")
        elif suffix == ".ps1":
            checked += 1
            if body.count(b"\r\n") == 0:
                offenders.append(f"{relative} 没有 CRLF，但规则要求 eol=crlf")
    assert checked, "`.sh` / `.ps1` 一枚都不在面上：这条 no-op 证明退化成了空判"
    assert not offenders, "加规则会改动工作树：" + "；".join(offenders)
```

回写常数（不许沿用本计划里的预估 1329）：

Run: `python scripts/b0_collection_probe.py | head -1`
Expected: `TOTAL <实测 N>`；把 `EXPECTED_COLLECTED = N` 写进文件，并把 N 与"本文件贡献 13 枚"同时记进 `task-2-report.md`。若 N ≠ 1316 + 13，说明有模块被 import 失败拖住，当场报告不要凑数。

- [ ] **Step 6: 逐枚点名 `_OWN_TEST_NAMES`（自我存续钉的第二个源，故意与装饰器重复）**

放在 helper 区之后：

```python
#: 13 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
#: 只遍历本模块的用例，对本文件被摘走任何东西都无感。
_OWN_TEST_NAMES = (
    "test_collected_count_matches_the_pinned_number",
    "test_the_gate_module_itself_is_collected",
    "test_collection_measurement_counts_node_ids_not_the_summary_line",
    "test_backend_contracts_has_no_unittest_discover_step",
    "test_backend_contracts_runs_the_pytest_suite",
    "test_step_ordering_still_explains_itself",
    "test_install_face_uses_requirements_txt_as_the_source",
    "test_extra_pip_arguments_are_exactly_the_exemption_table",
    "test_every_exemption_row_states_why",
    "test_gitattributes_carries_the_required_rules",
    "test_index_has_no_crlf_entries",
    "test_non_text_index_entries_are_exactly_the_enumerated_set",
    "test_eol_rules_are_a_no_op_for_the_current_tree",
)
```

- [ ] **Step 7: 跑定向套件，确认"该红的红、该绿的绿"**

Run: `python -m pytest backend/tests/test_ci_gate_contract.py -q`
Expected（**逐枚点名，别按"改造前的门都该红"猜**）：
- **红 5 枚**：`test_backend_contracts_has_no_unittest_discover_step`、`test_backend_contracts_runs_the_pytest_suite`（`(?!/)` 让 SECA-20 的单文件子集不算数）、`test_install_face_uses_requirements_txt_as_the_source`、`test_extra_pip_arguments_are_exactly_the_exemption_table`、`test_gitattributes_carries_the_required_rules`。
- **绿 8 枚**：三枚收集钉（常数已按 Step 5 实测回写）、`test_step_ordering_still_explains_itself`、`test_every_exemption_row_states_why`、以及 `test_index_has_no_crlf_entries` / `test_non_text_index_entries_are_exactly_the_enumerated_set` / `test_eol_rules_are_a_no_op_for_the_current_tree` 三枚**回归守卫**（它们不是迁移门：index 本来就全 LF、`i/-text` 本来就是那三枚、`.sh`/`.ps1` 形态本来就合规）。
若出现"全绿"⇒ 解析 helper 失效（找不到 job 块时抛的是 AssertionError 还是静默返回空，必查）。
若 `test_the_gate_module_itself_is_collected` 红在 `_OWN_TEST_NAMES` 与实收不符 ⇒ 按实收修名单，不许改 `dir()` 自动遍历。

- [ ] **Step 8: 全量套件不许被本文件弄坏**

Run: `python -m pytest backend/tests -q`
Expected（**红相的合法终态，不是"全绿"**）：收集数 `1329`；套件 `1324 passed, 5 failed`，且那 5 枚红**必须逐枚等于** Step 7 名单里的 5 枚门。
（Step 8 原稿写的是"`1329 + 0 failed`"，那是**红相里不可能成立的要求**——5 枚门红正是本任务的交付物。Task 2 实测把这条纠正为上面的形状；若红名单里出现第 6 枚，那才是回归。）
本文件那 13 枚里有 1 枚会跑子进程收集，Task 2 实测 **+29s**（约为该 job 的 20%）—— **这是本任务有意引入的常驻成本**，写进报告，由 Task 5 的耗时读数复核是否可接受（不可接受时按 §10.3 报，不许悄悄换成进程内量法）。

- [ ] **Step 9: 台账与快照**

`progress.md` 追加：`- Task 2 complete：13 枚门落地，红相 {k} 枚红（清单见 task-2-report.md），EXPECTED_COLLECTED=<N> 双写完成`。
快照 `snap-task2-post/test_ci_gate_contract.py`。子代理不得跑 git 写命令。

---

## Task 3: `ci.yml` 形态改造（让三枚门转绿，且不动其余三个 job）

**Files:**
- Modify: `.github/workflows/ci.yml`（只改 `backend-contracts`）
- Modify: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: Task 2 的 `_job_block` / `_job_steps` / `_test_runs` 对形状的假设（job 头两空格、step 头六空格、`run:` 在同一 step 段内）。
- Produces: 目标步骤序列（规格 §5.1），使 Task 2 的 runner/依赖/顺序注释钉转绿。

- [ ] **Step 1: 先备份字节，改完再逐字节比对形态**

```bash
cp .github/workflows/ci.yml .superpowers/sdd/ENTERPRISE_B0/snap-task3-pre-ci.yml
python -c "b=open('.github/workflows/ci.yml','rb').read();print('CRLF',b.count(b'\r\n'),'bareLF',b.count(b'\n')-b.count(b'\r\n'))"
```
Expected: `CRLF 134 bareLF 0`。**这组数改完必须仍然 bareLF=0**（CRLF 数会随新增行数上升）。若 implementer 的工具把文件写成 LF，`git diff` 会整份翻转 —— 那一条 diff 本身就是要拒收的。

- [ ] **Step 2: 把 `backend-contracts` 的安装步换成同源两行 + cache**

用这段**整块替换** `Install SECA-20 secret-scan dependencies` 那一步（逐包清单删除）：

```yaml
      - name: Cache pip wheels
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: b0-${{ runner.os }}-py3.12-cpu-torch-${{ hashFiles('backend/requirements.txt') }}
      - name: Install backend dependencies (same source as requirements.txt)
        run: |
          # B0 §5.1：依赖真源只有 backend/requirements.txt 一份。
          # torch 这一行不是新增依赖，是**发行源选择**：sentence-transformers 的传递依赖，
          # CPU wheel ~200MB 而不是默认那个带 CUDA 的 ~2.5GB。配方照抄 backend-quality。
          python -m pip install --disable-pip-version-check torch --index-url https://download.pytorch.org/whl/cpu
          python -m pip install --disable-pip-version-check -r backend/requirements.txt
          python -m pip install --disable-pip-version-check pytest
```

**形状要求（Task 2 实测到的性质，别改）**：安装步必须用 `run: |` 字面块，**每条 `pip install` 自带完整参数、各占一个物理行**。
`_pip_package_tokens` 是按物理行认 `pip install` 的；折叠成 `>-` 后，YAML 语义是一行、原文却是好几行，
包名就对不上号，豁免表钉会因"死行"红在错误的理由上。顺带一条同源事实：旧的
`Install SECA-20 secret-scan dependencies` 正是 `>-` 形态，所以本门把它看成"零个包"——不影响判据
（该步整枚被本任务删掉），但别拿它当"豁免表已经核对过"的证据。

- [ ] **Step 3: 把 unittest 步换成 pytest 主门，并保住顺序注释**

```yaml
      # B0 §5.2 两条顺序理由，删掉任何一条都会让 test_step_ordering_still_explains_itself 红：
      #   (1) SECA-20 扫描步排在主门之前：成本为零，主门红了扫描照样已报。
      #   (2) compose/pwsh 两步保持在最后：它们在主门不再恒红之后才第一次真起跑（B0-10）。
      # 原既有步 `python -m unittest discover -s backend/tests -p 'test_*.py' -v` 已删除：
      # 它从原理上收不到模块级裸函数（§2 的 45 枚差），且它在 main 上本就红，红到吞掉后面两步。
      - name: "Run backend contract suite (single runner: pytest)"
        run: python -m pytest backend/tests -q
```

**引号不是排版**：`- name:` 的值里带 `: ` 时，plain scalar 会被 YAML 判成映射分隔符 ⇒ 整份 workflow `ScannerError`。
Task 3 实现时实测踩到（原稿无引号 ⇒ `line 47, column 56`）。15 枚门都**不解析 YAML**（它没有 PyYAML 可用，
且必须只依赖标准库），所以错的 workflow 照样能拿 14 绿。为此加第 16 枚门，见 R9。
删除的行：`      - run: python -m unittest discover -s backend/tests -p 'test_*.py' -v`。

- [ ] **Step 4: 跑定向门**

Run: `python -m pytest backend/tests/test_ci_gate_contract.py -q -k "contracts or ordering or requirements_txt or exemption or states_why"`
Expected: 除 `.gitattributes` 那枚之外全绿；行尾钉仍红（Task 4 的活）。**不许为了绿把它们临时注释掉。**

- [ ] **Step 5: 行尾形态复核**

Run: `python -c "b=open('.github/workflows/ci.yml','rb').read();print('CRLF',b.count(b'\r\n'),'bareLF',b.count(b'\n')-b.count(b'\r\n'))"`
Expected: `bareLF 0`。不等则本步未完成：先转回 CRLF 再往下走（SEC-A 的 identity 模块踩过同一处）。

- [ ] **Step 6: 本地等价（先于远端，规格 §8 / B0-008）**

```bash
HOLD="$(mktemp -d)"; mv backend/.env "$HOLD/env"       # 挪出仓库，不在树里留副本（R6）
python -m pytest backend/tests -q 2>&1 | tail -3
mv "$HOLD/env" backend/.env; rmdir "$HOLD"
git status --porcelain                                  # 必须与 Task 1 记的基线逐行相同
```
Expected: 与 CI 同形态（无 `.env`、cwd=仓库根）下的完整读数。红就按 §10.3 三分法归因，**不要**在这里改 `backend/app/**`。

- [ ] **Step 7: 台账与快照**

`task-3-report.md` 必须含：ci.yml 的 step 清单（新旧对照，按 step 名不按行号）、CRLF 前后计数、Step 6 的无 `.env` 读数、`git diff --stat` 里 `backend/app/**` 为空的证据。快照 `snap-task3-post/ci.yml`。

---

## Task 4: `.gitattributes` + 行尾钉转绿 + no-op 证明

**Files:**
- Create: `.gitattributes`
- Modify: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: Task 2 的 `REQUIRED_GITATTRIBUTES_RULES` / `REQUIRED_BINARY_RULES` / `ALLOWED_NON_TEXT_INDEX_ENTRIES`。
- Produces: 与规格 §7 逐字一致的规则文件；四枚行尾钉绿。

- [ ] **Step 1: 记 no-op 对照基线（三件，全部在改文件之前取）**

```bash
cd /e/xiangmu/rag
git status --porcelain > /tmp/b0-eol-before-status.txt
python -c "
import hashlib,subprocess
fs=[f.decode() for f in subprocess.run(['git','ls-files','-z'],capture_output=True).stdout.split(b'\x00') if f]
h=hashlib.sha256()
for f in sorted(fs):
    try: h.update(f.encode()+b'\0'+open(f,'rb').read()+b'\0')
    except OSError: h.update(f.encode()+b'\0MISSING\0')
print('WORKTREE-AGGREGATE', h.hexdigest()[:12])" > /tmp/b0-eol-before-agg.txt
cat /tmp/b0-eol-before-status.txt
```
Expected: 三行 `M`/`??` 之外的内容 = 已知基线（两枚 identity 未提交 + Task 1–3 的新增件）。**聚合 sha 是"工作树没被改动"的硬证物**，SEC-A 的 §14 同一配方。

- [ ] **Step 2: 写 `.gitattributes`（LF，内容与规格 §7 逐字一致）**

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

三条刻意的"不做"，写在这里防下一个人顺手加：不给 `*.py` / `*.md` / `*.yml` 加 `eol=`（会改变 120 枚 CRLF 工作树文件的签出形态 = 被禁止的全量归一）；不加 `*.md text`（会把已封版的 `docs/MODEL_ROUTER_V23_DESIGN.md` 在 index 里改字节）；`i/-text` 那三枚由 Task 2 的形状钉看住，不靠归一化处理。

- [ ] **Step 3: 跑行尾四枚钉**

Run: `python -m pytest backend/tests/test_ci_gate_contract.py -q -k "gitattributes or crlf or non_text or no_op"`
Expected: 4 passed。

- [ ] **Step 4: no-op 动态证明**

```bash
git status --porcelain > /tmp/b0-eol-after-status.txt
git diff --stat | tail -3
diff /tmp/b0-eol-before-status.txt /tmp/b0-eol-after-status.txt && echo "STATUS 逐行相同"
```
Run: 重取 Step 1 的聚合 sha
Expected: `STATUS 逐行相同`（新文件 `.gitattributes` 会让两次的 `??` 段差一行——把它按 `grep -v gitattributes` 排除后再比，并在报告里写明排除的是哪一行，**不许**为了对上而改动别的）；`git diff` 对既有跟踪文件为空；聚合 sha 除 `.gitattributes` 自身外逐文件不变。

- [ ] **Step 5: 证伪一把（B0-07 的可红性，本地即可，不碰远端）**

```bash
python - <<'PY'
from pathlib import Path
p = Path(".gitattributes"); original = p.read_bytes()
try:
    p.write_bytes(original.replace(b"*.sh text eol=lf", b"", 1))
    import subprocess; subprocess.run(["python","-m","pytest","backend/tests/test_ci_gate_contract.py","-q","-k","gitattributes"],check=False)
finally:
    p.write_bytes(original)
PY
git diff --exit-code .gitattributes && echo "还原一致"
```
Expected: 中间那跑 **FAILED**；最后打印 `还原一致`。

- [ ] **Step 6: 台账与快照**

`task-4-report.md` 含：status 前后对照、聚合 sha 前后、no-op 判据逐条结论、Step 5 的红相输出。快照 `snap-task4-post/gitattributes`。

---

## Task 5: 全量回归 + SECA-20 漂移复量 + 耗时读数

**Files:**
- Create: `.superpowers/sdd/ENTERPRISE_B0/task-5-report.md`
- Modify: `.superpowers/sdd/ENTERPRISE_B0/progress.md`

**Interfaces:**
- Consumes: Task 2–4 的全部交付面。
- Produces: B0-01 / B0-09 / B0-13 的读数；四格 `.env` 复量的终态版（Task 1 是改造前，这里必须是改造后）。

- [ ] **Step 1: SECA-20 扫描门漂移复量（B0-09）**

```bash
python -m pytest backend/tests/test_secret_hygiene_contract.py -q \
  -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"
python -c "
import sys;sys.path.insert(0,'backend/tests')
import test_secret_hygiene_contract as m
names=m._delivery_surface_names();hits=m._hit_counts(names)
print('surface files',len(names),'hit files',len(hits),'occurrences',sum(hits.values()))"
```
Expected: 5 passed；`surface files 258 → 因 `.gitattributes`/新脚本而变`、`hit files 16`、`occurrences 31`。
判读规则（写死，防止把新增当漂移）：**命中文件数 16 与处数 31 必须不变**（新增的都是纯 CI/门文件，不含凭据形状）；面文件数允许只增不减，增量必须逐枚归因（预期：`.gitattributes`、`scripts/b0_collection_probe.py`、`backend/tests/test_ci_gate_contract.py`）。面数**变少**即红：那意味着有文件从交付面消失了，正是 SEC-A 那次误删快照目录暴露的方向。

两条来自 Task 1 评审的硬要求（Important 2 / Minor 7，规格 §16 卡 F 同源）：

1. **任何"植入 → 看红 → 删除"的证据动作必须 trap 兜底**。要往交付面里放一枚带凭据形状的文件（B0-09 的敏感性复验就是这种），必须
   `trap 'rm -f "$PROBE"; unset PROBE' EXIT INT TERM` 兜住异常与中断，并在结尾**断言面文件数回到植入前**。
   Task 1 首轮那次是用裸 `rm` 收的尾——这次没留残留是运气，一次中断就会把两枚红门交给下一个任务，
   而那恰好是 Task 1 被派去刻画的那类失效。
2. **原始证据落进工作区，不留 `%TEMP%`**：把本任务的四格与漂移复量的原始输出复制到
   `.superpowers/sdd/ENTERPRISE_B0_PLAN/evidence/`（SEC-A 的先例是 `task-10i-ci-proof.txt`）。
   B0-03 的"本地 vs 远端同 commit 收集数相同"要能在会话被截断后仍被重新导出，而不是只剩报告里的转述。

- [ ] **Step 2: 全量套件两格复量（含耗时）**

```bash
time python -m pytest backend/tests -q > /tmp/b0-full-root.txt 2>&1; tail -2 /tmp/b0-full-root.txt
cd backend && time python -m pytest tests -q > /tmp/b0-full-backend.txt 2>&1; tail -2 /tmp/b0-full-backend.txt; cd ..
```
Expected: 两格 passed 数相同、`failed=0`、`errors=0`；记录两格耗时（B0-13 用：本文件那枚子进程收集常驻 +40~62s）。

- [ ] **Step 3: 无 `.env` 终态格（CI 形态）**

Run: Step 3 of Task 1 的格 2 命令，逐字重跑
Expected: 与 Step 2 的 root 格读数逐位相同；不同则 §10.3 归因，报告优先。

- [ ] **Step 3.5: 容器内 3.12 那一格（规格 §8.2 / B0-15）**

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.12.14-slim bash -lc \
  "pip install --quiet -r backend/requirements.txt pytest && python -m pytest backend/tests -q 2>&1 | tail -3"
```
判读：这一格回答的是"3.12 上会不会红"，即宿主 3.13.7 与 CI 3.12 那枚差的唯一本地证据。
- 容器与镜像可用且装包成功 ⇒ 记录三行读数，结论 `GREEN` 或按 §10.3 归因。
- 容器不可用 / 拉不到 `python:3.12.14-slim` / 装包要走的网络被挡 ⇒ 写 `BLOCKED` + 一句具体原因，**不阻塞 B0 封版**（远端 B0-02 才是这一维度的权威判据；本格是强化项）。
不许把这一格写成 `GREEN` 除非真取到读数。SEC-A 的容器基准就是在同一台镜像上做的，先查那套镜像是否还在：`docker images | grep -i python`。

- [ ] **Step 4: app 面为零（B0-12）**

Expected：判据按规格 §11 B0-12 **卡 J 的三子句形态**执行，不是"列表为空"：

```bash
git diff --name-only HEAD -- backend/app          # 减去两枚 identity 后必须为空
git diff --cached --name-only -- backend/app      # 必须为空
python - <<'PY'                                    # 两枚 identity 的 sha 必须等于 Task 1 基线
import hashlib
from pathlib import Path
for rel in ("backend/app/identity/README.md", "backend/app/identity/__init__.py"):
    print(rel, hashlib.sha256(Path(rel).read_bytes()).hexdigest()[:12])
PY
```

`security-a-rc1` peel 出来就是 HEAD，那两枚未提交改动**本来就出现在 diff 里**——用 `security-a-rc1` 作 diff 基准
会把 B0 红在不属于它的改动上（这是卡 G 第一子句被落地证伪后由卡 J 修正的原委，规格 §11 为准）。
两枚 identity 在报告里逐枚点名"不是我改的"，**不许**提交、**不许**顺手改动。

- [ ] **Step 5: 报告**

`task-5-report.md` 汇总 B0-01..B0-13 里所有可在本地结的格子，每格：命令 / 读数 / 结论三件齐全。状态词只用 `GREEN/PENDING_EXTERNAL/BLOCKED`。

---

## Task 6: 变异台五发

**Files:**
- Create: `.superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py`
- Create: `.superpowers/sdd/ENTERPRISE_B0/mutation-bench.txt`

**Interfaces:**
- Consumes: Task 2 的钉、Task 3 的 ci.yml 原文、Task 4 的 `.gitattributes` 原文（needle 取自磁盘字节形态）。
- Produces: 五发逐发红 + `--check` 还原一致。

- [ ] **Step 1: 写台子（骨架照抄 SEC-A 的字节安全纪律，四条都不许省）**

```python
"""B0 变异台：每一发都必须杀至少一条门，否则那枚门是纸门。

    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py
    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py N1 N4
    python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py --check

字节安全（与 SEC-A 19 发同一规矩）：读字节 → bytes.replace(old,new,1) → 写字节 → 定向 pytest
→ `finally` 写回**读到的那份原字节** → 核对 sha1。anchor 必须**恰好命中一次**：0 次报
TARGET-NOT-FOUND，>1 次报 ANCHOR-NOT-UNIQUE，两者都不动树。还原不从 git 取。
N1 攻的是 conftest 的 `collect_ignore`——不是改名，而是"日常最容易发生的那种藏"。
"""
```

`REPO = Path(__file__).resolve().parents[4]`（与 SEC-A 同深度）。启动即
`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。

- [ ] **Step 2: 五发 needle（逐字取自已落盘的交付面，anchor 唯一性在 Step 3 验）**

| 代号 | 规格判据 | 目标文件 | 编辑 | 定向节点 |
| --- | --- | --- | --- | --- |
| N1 | §6.1 收集数钉 | `backend/tests/conftest.py` | `_GUARDED = False` → 同串 + `collect_ignore = ["test_web_security.py"]\n` | `test_collected_count_matches_the_pinned_number` |
| N2 | §6.2 单 runner 钉 | `.github/workflows/ci.yml` | 主门那两行 → 那两行之前插 `- run: python -m unittest discover -s backend/tests -p 'test_*.py' -v`（保持 CRLF 拼接） | `test_backend_contracts_has_no_unittest_discover_step` |
| N3 | §6.3 依赖同源钉 | `.github/workflows/ci.yml` | `-r backend/requirements.txt` → `pytest-fastapi-pydantic`（把同源换回手写） | `test_install_face_uses_requirements_txt_as_the_source` |
| N4 | §6.3 豁免表形状 | `.github/workflows/ci.yml` | `... install --disable-pip-version-check pytest` → 追加一行装 `bandit`（未豁免参数） | `test_extra_pip_arguments_are_exactly_the_exemption_table` |
| N5 | §6.4 行尾钉 | `.gitattributes` | 删 `*.sh text eol=lf` 整行 | `test_gitattributes_carries_the_required_rules` |
| N6 | §6.4 覆盖度钉的空判角落（Task 4 评审登记） | `backend/tests/test_ci_gate_contract.py` | 把 `_index_eol_rows()` 的 tracked 侧强制成空集合，令 `0 == 0` 通过覆盖度钉 | 必须仍被 `i/-text` 枚举集合钉抓红；**若两枚都绿则覆盖度钉缺地板，判 SURVIVED** |

N1 的 needle 之所以选 `conftest.py`：它是 B0 唯一没规定"不许改"却又最容易被顺手加一行 `collect_ignore` 的文件；如果收集数钉连这种最常见的藏法都抓不到，B0 的全部价值不成立。

- [ ] **Step 3: 跑全轮并留证据**

Run: `python .superpowers/sdd/ENTERPRISE_B0/mutations/ent_b0_mutations.py | tee .superpowers/sdd/ENTERPRISE_B0/mutation-bench.txt`
Expected: 5 行 `KILLED`，随后 `--check` 全 `RESTORED-OK`。出现 `TARGET-NOT-FOUND` / `ANCHOR-NOT-UNIQUE` ⇒ needle 按磁盘原文补上下文再重跑，**判据一字不许改**（SEC-A 六发歧义就是这么处理的）。
任何一发 `SURVIVED` ⇒ 那枚门是纸门：回到 Task 2 修门，不算任务完成。

- [ ] **Step 4: 台账**

`progress.md` 追加五发的 (代号, 判据, 结果, 被杀节点) 表。

---

## Task 7: 远端往返 + 验收文档 + 提交闸

**Files:**
- Create: `docs/ENTERPRISE_B0_ACCEPTANCE_<YYYY-MM-DD>.md`（封版当日定名）
- Create: `.superpowers/sdd/ENTERPRISE_B0/task-7-report.md`

**Interfaces:**
- Consumes: Task 1–6 全部读数。
- Produces: B0-02 / B0-03 / B0-10 的远端权威读数；提交清单。

- [ ] **Step 1: 出提交清单（不许 `git add -A`）**

```bash
git status --porcelain
git ls-files --others --exclude-standard | wc -l
```
清单分两栏：**允许入仓**（`ci.yml`、`.gitattributes`、`backend/tests/test_ci_gate_contract.py`、`scripts/b0_collection_probe.py`、`docs/ENTERPRISE_B0_*`、`.superpowers/sdd/ENTERPRISE_B0_PLAN/**`）/ **必须排除**（`snap-task*/`、`/tmp` 落盘物、任何 `backend/.env*`、identity 那两枚未提交项——它们不属于 B0，留给用户单独处置）。

**另有一枚必须单独点名的入库项（R15 红 3 的正解）**：`backend/tests/real_llm_failover_kit.py:79` 定义的
`EVIDENCE_FILE = .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`，被 `.gitignore:25`
的整目录规则挡掉 ⇒ 干净 checkout 里不存在，而 `test_p0_row_status_matches_the_evidence` 要求矩阵行的状态与它一致。
矩阵写 `GREEN` 是**真实结论**（V2.3 期间真跑过），不许为了消红把它改成 `BLOCKED`；门要求"证据必须在场"也是**正确判据**，
不许放宽。唯一的诚实出路是让这枚证据件出现在交付面上：按 SEC-A 对 `docs/` 与探针脚本的先例，用
`git add -f .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json` 精选入库，
**并且**入库前必须过 SECA-20 扫描门（它一旦被跟踪就进入扫描面；若有凭据形状，门会红，那时改判为
"摘出可复算字段、写入一枚无敏感内容的跟踪摘要件"，并把这条决定写进验收文档）。
这一步需要用户显式授权，且属于"精选路径单文件添加"，**不得**用 `git add -A`、不得放宽 `.gitignore` 整目录规则。

- [ ] **Step 2: 停下来要授权（这一步是闸，不是步骤）**

向用户报：本地全部读数 + 拟提交清单 + commit message 草案。**未获显式授权不 `git add`、不 `git commit`、不 `git push`。** SEC-A 的既有规矩。

- [ ] **Step 3: 远端往返**

Push 后读 step 级结论（不是 job 级）：
```bash
gh run list -L 3
gh run view <run-id> --json jobs,name,url,conclusion
```
Expected: `backend-contracts` 整 job `success`。**特别盯 B0-10**：compose 配置校验与 `deploy.ps1` pwsh 语法校验两道第一次真起跑——任一红就是既有缺陷被暴露，按 §10.3 归因，不许在 B0 里顺手改 `docker-compose.yml` 或 `scripts/deploy.ps1`（两者都在禁止名单）。

- [ ] **Step 4: 验收文档**

矩阵 15 行逐行填（判据 / 量法 / 读数 / 结论 / 证据件路径）。B0-02、B0-03、B0-10、B0-13 只能来自远端；取不到就写 `BLOCKED` 并说明差什么。文档必须包含一条对 §14 L6/L7 的复述——封版文档不写"收集面已彻底可靠"，写"收集面被一枚钉住，该钉不防自己被删除"。

- [ ] **Step 5: tag 决策留给用户**

B0 是否单独打 tag 由用户定（SEC-A 的 `security-a-rc1` 形态）。**不擅自打。**

---

## Self-Review（本计划写完后自查，结论记在 `progress.md`）

**1. Spec coverage**

| 规格条目 | 落在哪 |
| --- | --- |
| §5.1 步骤序列 / §5.2 顺序理由 | Task 3 Step 2–3（顺序理由被一枚钉看住） |
| §6.1 收集数钉 + 自我存续子钉 | Task 2 Step 2、Step 6 |
| §6.2 单 runner | Task 2 Step 3 |
| §6.3 依赖同源 + 豁免表 | Task 2 Step 4 |
| §6.4 行尾三钉 | Task 2 Step 5 |
| §7 no-op 规则集 | Task 4 Step 2 |
| §8.1 四格复量 | Task 1 Step 3（改造前）+ Task 5 Step 3（改造后） |
| §8.2 容器内 3.12 那一格 | Task 5 Step 3.5（自审发现此处原本无落点，已补；不可用时按 `BLOCKED` 结，不阻塞封版） |
| §8.3 远端权威 | Task 7 Step 3 |
| §9 五发变异 | Task 6 |
| §10 白名单 / 归因三分法 | 每个 Task 的 Files 段 + Task 5 Step 4 + Task 7 Step 3 |
| §14 L6 自指盲区 | Task 7 Step 4（验收文档必须复述） |

**补记两处（自查真找到的两个错，都已改在树上，不是"待办"）：**

1. **§8.2 原本无落点**。第一版计划的覆盖表里那格写的是"缺"，但我只写了"处理方式"却没真去 Task 5 加步骤——即"自查发现问题的下一步被当成了已解决"。现已补成 **Task 5 Step 3.5**，带可跑命令与 `BLOCKED` 出口（容器不可用时不阻塞封版，因为 3.12 那一维的权威判据是远端 B0-02）。
2. **依赖同源钉的解析器会假红**。第一版用 `re.findall` 对整段 step 文本 tokenize，再拿一枚 `allowed` 白名单去滤噪声。实测推演即错两处：`-r backend/requirements.txt` 里的 `requirements.txt` 落在白名单外 ⇒ **门在 Task 3 落地当场红在自己的解析器上**；YAML 注释里的 `sentence-transformers`、`CUDA`、`wheel` 也全会被算成"未豁免的包"。已改成 `_pip_package_tokens()`：先丢注释、只取 `pip install` 之后的 token、带值选项连值一起跳、含 `/` 或以 `.txt` 结尾的不是包名。白名单整枚删除——**用白名单滤自己的语法，等于让门的口径跟着白名单漂**，这正是 §2 里 F2 的形状。

**2. Placeholder scan**：Task 2 Step 5 的 `EXPECTED_COLLECTED = 1329` 是**预估 + 强制回写命令**，不是 TBD（回写命令与"不符就停下报告、不许凑数"的判读规则都在）。Task 7 Step 1 的 `<YYYY-MM-DD>` 同理：命名规则由规格钉死，日期由封版当日的实测决定。其余无占位。

**3. Type consistency**：`_job_block` / `_job_steps` / `_test_runs` / `_install_steps` / `_pip_package_tokens` 五个 helper 的定义与 Task 3 写 YAML 时依赖的缩进假设（job 头 2 空格、step 头 6 空格）一致；`_index_eol_rows()` 返回 `path → i/<eol>`，取值域只有 `i/lf`、`i/crlf`、`i/-text`、`i/none` 四种，三处用法（`i/crlf`、`i/-text`、其余）与之相符；`ALLOWED_NON_TEXT_INDEX_ENTRIES` 是 `frozenset`、断言处用 `set(...)` 比较，等价；`PIP_INSTALL_EXEMPTIONS` 的 `(1, "...")` 行值与 `_pip_package_tokens` 的"每枚包各计一次"语义相符——Task 3 Step 4 的定向跑必须确认 `pytest` 与 `torch` 各恰 1 处（若 `--index-url` 的跳过逻辑写错，`cpu` 会被当成第二枚包名，那一跑就会红在这里，属预期的好红）。`_OWN_TEST_NAMES` 的 13 枚与文件内实际 `def test_` 枚数由 `test_the_gate_module_itself_is_collected` 互校，新增用例时必须同步扩名单——这是刻意的摩擦。
