# Task 6 review package (working tree; zero commits)
HEAD 7cc5efc

## git status --porcelain
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

## NEW: mutation harness (345 lines)
+++ b/.superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py
@@ -0,0 +1,345 @@
+"""B0 变异台（Task 6 / B0-11）：每一发都必须杀至少一条门，否则那枚门是纸门。
+
+跑法（仓库任意 cwd，路径按本文件位置解析）：
+
+    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py
+    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py N1 N4
+    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/ent_b0_mutations.py --check
+
+字节安全（与 SEC-A 19 发、V2.3 同一规矩，四条都不许省）：读字节 → `bytes.replace(old, new, 1)`
+→ 写字节 → 跑定向 pytest → **`finally` 里写回读到的那份原字节**（不从 git 取）→ 核对 sha1 与
+注入前一致，不过就立刻中止整轮。锚点必须**恰好命中一次**：0 次报 `TARGET-NOT-FOUND`、>1 次报
+`ANCHOR-NOT-UNIQUE`，两者都不动树——一条有多解的 needle 就是"我以为在改 A，其实改到了 B"，
+那一行的红或绿都不能归因。
+
+比 SEC-A 的骨架多四处（都是本台的宾语决定的，不是口味）：
+
+1. **目标不止 `backend/`**：B0 的门钉在 CI 交付面上，所以四枚目标里两枚在仓库根
+   （`.github/workflows/ci.yml` / `.gitattributes`）。路径一律 `REPO / rel`。
+2. **needle 按磁盘字节形态写**：实测 ci.yml 是 147 枚 CRLF / 0 枚裸 LF ⇒ 三枚 ci.yml 的
+   needle 用 `LC(...)` 拼 `\r\n`；conftest.py、门模块、`.gitattributes` 全是 LF ⇒ 用 `L(...)`。
+   拿 `\n` 拼 ci.yml 的 needle 我第一次就撞过，结果是 `TARGET-NOT-FOUND`（0 命中），不是错改。
+3. **还原除 sha1 外另核一次 `cmp`**：sha1 相同是"我算的两次一致"，`cmp` 是"外部工具逐字节
+   比对读到的原件"。SEC-A Task 4 那一轮登记过 `git diff` 对未跟踪文件恒返 0 的假绿（D5），
+   本台的 `.gitattributes` 与门模块**正是未跟踪件**，所以还原证明不沾 git。
+4. **定向节点跑整枚门模块而不是单枚函数**：台的职责是"哪几枚门杀掉了这一发"，单枚节点答不了
+   这个问题（一发杀两枚时第二枚不会被读到）。代价是每发约 32s（16 枚里有两枚要起收集子进程），
+   六发共约 3 分钟——仍然**串行**跑，绝不并行：这一台同时只能有一枚变异在树上。
+
+stdout/stderr 在 import 期就重钉成 UTF-8：宿主控制台是 cp936，失败信息里的中文断言会先把
+**打印**炸掉，而那时 `finally` 已经还原了文件 ⇒ 留下的是一份跑不完的证据表，价值等于零。
+
+N1 攻的是 conftest 的 `collect_ignore`——不是改名，而是"日常最容易发生的那种藏"。
+"""
+
+from __future__ import annotations
+
+import hashlib
+import os
+import shutil
+import subprocess
+import sys
+import tempfile
+from pathlib import Path
+
+REPO = Path(__file__).resolve().parents[4]
+BACKEND = REPO / "backend"
+
+for _stream in (sys.stdout, sys.stderr):
+    if hasattr(_stream, "reconfigure"):
+        _stream.reconfigure(encoding="utf-8", errors="replace")
+
+
+def L(*lines: str) -> str:
+    """按 LF 拼一段多行 needle（每行末尾都带换行，所以末行也带）。"""
+    return "".join(line + "\n" for line in lines)
+
+
+CRLF = "\r\n"
+
+
+def LC(*lines: str) -> str:
+    """按 **CRLF** 拼 needle：ci.yml 磁盘上是 147 枚 CRLF、0 枚裸 LF，只能用这一形。"""
+    return "".join(line + CRLF for line in lines)
+
+
+#: 门册所在节点。六发的判据全部落在这一枚模块里（规格 §6.1—§6.4），所以定向跑整模块。
+GATE_MODULE = "tests/test_ci_gate_contract.py"
+
+#: 四枚目标在**未变异**状态的 sha1（Task 6 开工前实测，逐字记在 task-6-report.md §1）。
+#: `--check` 拿它做"字节还原一致"的比对基准：不是"我记得没改"，是"树和开工那天同一份字节"。
+BASELINE_SHA1 = {
+    "backend/tests/conftest.py": "b0c5eee33ccdb49824405a10b8e282b4d52ab36d",
+    ".github/workflows/ci.yml": "931846cba8575e2e994633abc39a48492c1ea029",
+    ".gitattributes": "5738e2743ea768943e083cb1ff85fd9793ee7f57",
+    "backend/tests/test_ci_gate_contract.py": "450484c09592ef3e89f8798c65737c563e4ca217",
+}
+
+# ---------------------------------------------------------------------------
+# 六发。每发：代号 / 规格判据 / 目标 / 编辑对 / 计划点名的判据节点。
+# needle 的歧义消解逐条记在紧邻的注释里，报告 §2 抄录。
+# ---------------------------------------------------------------------------
+
+MUTATIONS: list[dict] = [
+    # §6.1 收集数钉。**最容易发生的那种藏**：不改名、不加 skip/xfail，只在 conftest 里顺手
+    # 加一行 `collect_ignore` —— 那枚模块从此不被收集，而 16 枚门里只有总数看得见。
+    # 歧义消解：计划 needle `_GUARDED = False` 在 conftest.py 命中**两次**（模块级 :157 与会话
+    # 夹具 finally 里那枚缩进的 :774），`replace(...,1)` 等于靠行序赌。补下一行 `_SESSION_GUARD`
+    # 的原文 ⇒ 只剩模块级那一枚（:774 那枚缩进 8 空格且下一行是 `_CREDENTIAL_GUARD = None`）。
+    {
+        "code": "N1",
+        "spec": "§6.1 收集数钉",
+        "rel": "backend/tests/conftest.py",
+        "edits": [(
+            L("_GUARDED = False",
+              '_SESSION_GUARD: "LedgerGuard | None" = None'),
+            L("_GUARDED = False",
+              'collect_ignore = ["test_web_security.py"]  # 变异台 N1：一行藏掉整枚模块',
+              '_SESSION_GUARD: "LedgerGuard | None" = None'),
+        )],
+        "node": "test_collected_count_matches_the_pinned_number",
+    },
+    # §6.2 单 runner 钉。必须是**真的 step**，不能是注释：`_step_script()` 会把整行 `#` 注释
+    # 剥掉，所以树上原本那句"原既有步 unittest discover 已删除"的注释杀不掉这枚门（这正是
+    # I-1 那颗地雷的另一面）。ci.yml 是 CRLF ⇒ 用 LC。
+    # 歧义消解：主门那两枚 step 行里，`run: python -m pytest backend/tests -q` 只出现一次，
+    # 但计划要的是"插在 step 之前"，所以锚在 `- name:` 那一行上（含步名的整枚 step 抬头，
+    # 唯一）；新 step 落在主门之前不影响顺序钉的四枚锚点相对次序。
+    {
+        "code": "N2",
+        "spec": "§6.2 单 runner 钉",
+        "rel": ".github/workflows/ci.yml",
+        "edits": [(
+            LC('      - name: "Run backend contract suite (single runner: pytest)"'),
+            LC("      - run: python -m unittest discover -s backend/tests -p 'test_*.py' -v",
+               '      - name: "Run backend contract suite (single runner: pytest)"'),
+        )],
+        "node": "test_backend_contracts_has_no_unittest_discover_step",
+    },
+    # §6.3 依赖同源钉：把"同源"换回 f6c67b5 那版的手写清单（远端当场 ModuleNotFoundError 的
+    # 原形）。锚 `-r backend/requirements.txt` 在 ci.yml 命中 1 次（`hashFiles('backend/
+    # requirements.txt')` 里那枚前面是引号不是 `-r `，不构成第二次命中）；为免读成人手抄的
+    # 半行，needle 取整行 + CRLF。
+    {
+        "code": "N3",
+        "spec": "§6.3 依赖同源钉",
+        "rel": ".github/workflows/ci.yml",
+        "edits": [(
+            LC("          python -m pip install --disable-pip-version-check"
+               " -r backend/requirements.txt"),
+            LC("          python -m pip install --disable-pip-version-check"
+               ' "fastapi>=0.115,<1" "pydantic>=2.8,<3" "python-multipart>=0.0.9"'
+               ' "qdrant-client>=1.12,<2" "httpx>=0.27,<1" "PyJWT>=2.9,<3"'),
+        )],
+        "node": "test_install_face_uses_requirements_txt_as_the_source",
+    },
+    # §6.3 豁免表形状钉：多装一枚没豁免过的包（`bandit`）。锚取安装步最后一整行，
+    # `--disable-pip-version-check pytest` 全文件唯一（SECA-20 那步是 `python -m pytest`，
+    # 不含 `pip install`）。
+    {
+        "code": "N4",
+        "spec": "§6.3 豁免表形状钉",
+        "rel": ".github/workflows/ci.yml",
+        "edits": [(
+            LC("          python -m pip install --disable-pip-version-check pytest"),
+            LC("          python -m pip install --disable-pip-version-check pytest",
+               "          python -m pip install --disable-pip-version-check bandit"),
+        )],
+        "node": "test_extra_pip_arguments_are_exactly_the_exemption_table",
+    },
+    # §6.4 行尾钉：删 `*.sh text eol=lf` 整行（含其换行 ⇒ 行整体消失，不是留一枚空规则）。
+    # `.gitattributes` 磁盘上是 LF、CR 字节 0（Task 4 §1 实测），所以用 L。锚在文件里唯一。
+    {
+        "code": "N5",
+        "spec": "§6.4 行尾规则钉",
+        "rel": ".gitattributes",
+        "edits": [(
+            L("*.sh text eol=lf"),
+            "",
+        )],
+        "node": "test_gitattributes_carries_the_required_rules",
+    },
+    # §6.4 覆盖度钉的**空判角落**（Task 4 评审登记：这条钉没有非空地板）。两枚编辑一起才
+    # 表达得出那一形——只收 tracked 一侧会得到 `313 == 0`，那是响亮地红，不是评审说的那一格；
+    # 两侧同时收空才是 `0 == 0`、missing/extra 皆空、rows={} ⇒ 覆盖度钉放行。
+    # 判据（不改）：`test_index_has_no_crlf_entries` 会跟着变**空判绿**，`i/-text` 枚举集合钉
+    # 应当当场红。若两枚都绿 ⇒ 覆盖度钉缺地板这一形无人拦，本发记 SURVIVED，交 controller 裁。
+    # 锚各命中 1 次（`_tracked_paths()` 的另一个调用点在门 16 里，那里是 `tracked = subprocess.
+    # run(...)` 形状，不是同一串）。
+    {
+        "code": "N6",
+        "spec": "§6.4 覆盖度钉的空判地板",
+        "rel": "backend/tests/test_ci_gate_contract.py",
+        "edits": [
+            (
+                L("    records = _index_eol_records()"),
+                L('    records: "list[str]" = []  # 变异台 N6：index 面收空'),
+            ),
+            (
+                L("    tracked = _tracked_paths()"),
+                L('    tracked: "list[str]" = []  # 变异台 N6：跟踪面收空 ⇒ 覆盖度钉 0 == 0'),
+            ),
+        ],
+        "node": "test_index_has_no_crlf_entries / test_non_text_index_entries_are_exactly_the_enumerated_set",
+    },
+]
+
+
+def sha1(path: Path) -> str:
+    return hashlib.sha1(path.read_bytes()).hexdigest()
+
+
+def anchor_counts(spec: dict) -> "list[int]":
+    text = (REPO / spec["rel"]).read_bytes().decode("utf-8")
+    return [text.count(old) for old, _ in spec["edits"]]
+
+
+def compare_with_cmp(path: Path, original: bytes) -> "tuple[str, int]":
+    """外部 `cmp` 逐字节比对（原件按**读到的字节**写到系统临时目录，不进仓库）。
+
+    cmp 不在 PATH 上（纯 PowerShell 宿主）时退化成 Python 逐字节比，并在结果里写明用的是哪种，
+    不把"没核"混进"核过"。
+    """
+    exe = shutil.which("cmp")
+    if exe is None:
+        return ("bytes-eq", 0 if path.read_bytes() == original else 1)
+    tmp = Path(tempfile.mkdtemp(prefix="ent_b0_restore_")) / path.name
+    tmp.write_bytes(original)
+    try:
+        proc = subprocess.run([exe, str(tmp), str(path)], capture_output=True)
+        return ("cmp", proc.returncode)
+    finally:
+        tmp.unlink(missing_ok=True)
+        os.rmdir(tmp.parent)
+
+
+def check() -> int:
+    """`--check`：什么都不跑、什么都不改，只核两件事——锚点仍各命中一次、四枚目标字节未残留。"""
+    bad = 0
+    print("== --check（不注入、不跑测试）==")
+    for spec in MUTATIONS:
+        counts = anchor_counts(spec)
+        status = "ANCHOR-OK" if all(c == 1 for c in counts) else (
+            "TARGET-NOT-FOUND" if 0 in counts else "ANCHOR-NOT-UNIQUE")
+        if status != "ANCHOR-OK":
+            bad += 1
+        print(f"{status}\t{spec['code']}\tcounts={counts}\t{spec['rel']}")
+    print()
+    for rel, expected in sorted(BASELINE_SHA1.items()):
+        path = REPO / rel
+        actual = sha1(path) if path.is_file() else "MISSING"
+        ok = actual == expected
+        bad += 0 if ok else 1
+        print(f"{'RESTORED-OK' if ok else 'RESTORED-MISMATCH'}\t{rel}\t{actual[:12]}"
+              f"{' == ' + expected[:12] if ok else ' != ' + expected[:12]}")
+    total = len(MUTATIONS) + len(BASELINE_SHA1)
+    print(f"\n{total - bad}/{total} 项通过（锚点 {len(MUTATIONS)} 发 + 字节 {len(BASELINE_SHA1)} 枚）")
+    return 1 if bad else 0
+
+
+def run_node(node: str) -> "tuple[int, str]":
+    """定向跑一枚节点：**不带 `-x`**（首红即停会把"哪几枚门真杀得掉这一发"读成"哪枚先红"，
+    而 unittest/pytest 的序都不是判据）。全文落系统临时目录，不进仓库。
+    """
+    proc = subprocess.run(
+        [sys.executable, "-m", "pytest", node, "-q", "--tb=line", "-p", "no:cacheprovider"],
+        cwd=str(BACKEND),
+        capture_output=True,
+        text=True,
+        encoding="utf-8",
+        errors="replace",
+        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
+    )
+    raw = (proc.stdout or "") + (proc.stderr or "")
+    slug = node.replace("/", "_").replace("::", "_").replace(".py", "")
+    Path(tempfile.gettempdir(), f"ent_b0_mutation_{slug}.txt").write_text(raw, encoding="utf-8")
+    return proc.returncode, raw
+
+
+def failed_nodes(raw: str) -> "list[str]":
+    out = []
+    for line in raw.splitlines():
+        if line.startswith("FAILED ") or line.startswith("ERROR "):
+            out.append(line.split(" - ")[0].split(" ", 1)[1])
+    return out
+
+
+def summarize(raw: str) -> str:
+    for line in reversed(raw.splitlines()):
+        if "passed" in line or "failed" in line or "error" in line:
+            return line.strip()
+    return "(无摘要)"
+
+
+def gate_name(node_id: str) -> str:
+    return node_id.split("::", 1)[1] if "::" in node_id else node_id
+
+
+def main(argv: "list[str]") -> int:
+    if argv and argv[0] == "--check":
+        return check()
+    wanted = {a.upper() for a in argv}
+    selected = [m for m in MUTATIONS if not wanted or m["code"] in wanted]
+    if not selected:
+        print(f"未选中任何变异：{argv}")
+        return 2
+    rows = []
+    for spec in selected:
+        code = spec["code"]
+        path = REPO / spec["rel"]
+        original = path.read_bytes()
+        before = sha1(path)
+        text = original.decode("utf-8")
+        counts = [text.count(old) for old, _ in spec["edits"]]
+        if any(c == 0 for c in counts):
+            print(f"{code}\tTARGET-NOT-FOUND\tcounts={counts}\t树未动", flush=True)
+            rows.append((code, spec["spec"], spec["rel"], f"counts={counts}",
+                         "TARGET-NOT-FOUND", "-", "n/a", "n/a"))
+            continue
+        if any(c != 1 for c in counts):
+            print(f"{code}\tANCHOR-NOT-UNIQUE\tcounts={counts}\t树未动", flush=True)
+            rows.append((code, spec["spec"], spec["rel"], f"counts={counts}",
+                         "ANCHOR-NOT-UNIQUE", "-", "n/a", "n/a"))
+            continue
+        mutated = text
+        for old, new in spec["edits"]:
+            mutated = mutated.replace(old, new, 1)
+        assert mutated != text, f"{code} 注入是空操作"
+        try:
+            path.write_bytes(mutated.encode("utf-8"))
+            print(f"[{code}] 注入 {spec['rel']} {before[:12]} -> {sha1(path)[:12]}"
+                  f"（锚点唯一 {counts}）", flush=True)
+            rc, raw = run_node(GATE_MODULE)
+            print(f"[{code}] pytest（{GATE_MODULE} 全 16 枚）: {summarize(raw)}", flush=True)
+            red = failed_nodes(raw)
+            for name in red[:16]:
+                print(f"[{code}]   RED {gate_name(name)}")
+            rows.append((code, spec["spec"], spec["rel"], "1 次/编辑",
+                         "KILLED" if rc != 0 else "SURVIVED",
+                         ",".join(gate_name(n) for n in red[:4]) or "-",
+                         "OK", "-"))
+        finally:
+            path.write_bytes(original)
+            after = sha1(path)
+            method, cmp_rc = compare_with_cmp(path, original)
+            if after != before or cmp_rc != 0:
+                # 还原不了就停下：把变异留在树上，比少一行证据严重得多。
+                print(f"{code}\tRESTORE-FAILED\tsha1 {before} != {after}\t"
+                      f"{method} rc={cmp_rc}\t中止整轮", flush=True)
+                raise SystemExit(3)
+            if rows and rows[-1][0] == code:
+                # 只回填**这一发**那行（run_node 抛异常时行还没 append，不能错填到上一发上）。
+                rows[-1] = rows[-1][:7] + (f"OK（sha1 同 + {method} rc=0）",)
+        print(f"[{code}] 还原：sha1 与注入前相同、{method} rc={cmp_rc}", flush=True)
+    print()
+    print("| 变异 | 规格判据 | 目标文件 | 锚点命中 | 结果 | 红掉的门 | sha1 还原 |")
+    print("| --- | --- | --- | --- | --- | --- | --- |")
+    for code, spec_row, rel, anchors, verdict, red, _node, restore in rows:
+        print(f"| {code} | {spec_row} | {rel} | {anchors} | {verdict} | {red} | {restore} |")
+    bad = [r for r in rows if r[4] != "KILLED"]
+    print(f"\n{len(rows) - len(bad)}/{len(rows)} KILLED")
+    return 1 if bad else 0
+
+
+if __name__ == "__main__":
+    sys.exit(main(sys.argv[1:]))

## gate file floor delta (snap-task6-post -> now)
