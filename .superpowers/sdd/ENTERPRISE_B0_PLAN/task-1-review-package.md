# Task 1 review package (working-tree diff; this project runs with zero commits until an explicit authorization)

BASE/HEAD: 7cc5efc (unchanged — no commits by design)

## git status --porcelain
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py

## git diff --stat (tracked)
warning: in the working copy of 'backend/app/identity/README.md', LF will be replaced by CRLF the next time Git touches it
warning: in the working copy of 'backend/app/identity/__init__.py', LF will be replaced by CRLF the next time Git touches it
 backend/app/identity/README.md   | 13 ++++++++-----
 backend/app/identity/__init__.py | 13 ++++++++++---
 2 files changed, 18 insertions(+), 8 deletions(-)

## NEW FILE: scripts/b0_collection_probe.py
warning: in the working copy of 'scripts/b0_collection_probe.py', LF will be replaced by CRLF the next time Git touches it
    diff --git a/scripts/b0_collection_probe.py b/scripts/b0_collection_probe.py
    new file mode 100644
    index 0000000..eb4b811
    --- /dev/null
    +++ b/scripts/b0_collection_probe.py
    @@ -0,0 +1,64 @@
    +"""B0 收集面探针：把"收集到几枚、分别来自哪个模块"变成一行行可核对的输出。
    +
    +    python scripts/b0_collection_probe.py                # 打印总数 + 逐模块计数
    +    python scripts/b0_collection_probe.py --node-ids     # 只打 node id，每行一枚（喂给基线文件）
    +    python scripts/b0_collection_probe.py --out FILE     # 写文件而不是 stdout
    +
    +量法（规格 §6.1）：**统计匹配 `^backend/tests/[^:]+::` 的行数**，不解析尾行的
    +`N tests collected` 文句——那是给人读的，形状会变。子进程固定 `cwd=仓库根`、固定剥掉
    +`REAL_LLM_ACCEPTANCE`，因为 CI 的默认形态就是"那枚门关着、从仓库根跑"。
    +"""
    +from __future__ import annotations
    +
    +import argparse
    +import os
    +import re
    +import subprocess
    +import sys
    +from collections import Counter
    +from pathlib import Path
    +
    +REPO_ROOT = Path(__file__).resolve().parents[1]
    +NODE_ID = re.compile(r"^backend/tests/[^:]+::")
    +
    +
    +def collected_node_ids(root: Path = REPO_ROOT) -> list[str]:
    +    env = dict(os.environ)
    +    env.pop("REAL_LLM_ACCEPTANCE", None)
    +    child = subprocess.run(
    +        [sys.executable, "-m", "pytest", "backend/tests", "-q", "--collect-only"],
    +        cwd=root, env=env, capture_output=True, text=True,
    +        encoding="utf-8", errors="replace", check=False)
    +    if child.returncode != 0:
    +        # 收集期非 0 就是 import 失败/配置炸了：这正是 F1 的相反面（会响），不许咽下去。
    +        raise RuntimeError(
    +            f"collect-only rc={child.returncode}\n{child.stdout[-2000:]}\n{child.stderr[-2000:]}")
    +    return [line.strip() for line in child.stdout.splitlines() if NODE_ID.match(line.strip())]
    +
    +
    +def module_counts(ids: list[str]) -> "Counter[str]":
    +    return Counter(node_id.split("::", 1)[0] for node_id in ids)
    +
    +
    +def main(argv: list[str] | None = None) -> int:
    +    parser = argparse.ArgumentParser()
    +    parser.add_argument("--node-ids", action="store_true")
    +    parser.add_argument("--out", type=Path)
    +    args = parser.parse_args(argv)
    +    ids = collected_node_ids()
    +    if args.node_ids:
    +        body = "".join(f"{node_id}\n" for node_id in sorted(ids))
    +    else:
    +        rows = "\n".join(f"{count:>5}  {module}" for module, count in sorted(module_counts(ids).items()))
    +        body = f"TOTAL {len(ids)}\n{rows}\n"
    +    if args.out:
    +        args.out.parent.mkdir(parents=True, exist_ok=True)
    +        args.out.write_text(body, encoding="utf-8", newline="\n")
    +        print(f"wrote {args.out} ({len(ids)} node ids)")
    +    else:
    +        sys.stdout.write(body)
    +    return 0
    +
    +
    +if __name__ == "__main__":
    +    raise SystemExit(main())
