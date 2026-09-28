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

