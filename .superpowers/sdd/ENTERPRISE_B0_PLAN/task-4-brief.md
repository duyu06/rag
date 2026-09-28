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

