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

