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
          key: b0-${{ runner.os }}-py3.12-${{ hashFiles('backend/requirements.txt') }}
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
      - name: Run backend contract suite (single runner: pytest)
        run: python -m pytest backend/tests -q
```
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

