# Task 3 review package (working tree; zero commits by design)

HEAD: 7cc5efc

## git status --porcelain
 M .github/workflows/ci.yml
 M backend/app/identity/README.md
 M backend/app/identity/__init__.py
?? backend/tests/test_ci_gate_contract.py
?? docs/ENTERPRISE_B0_PLAN.md
?? docs/ENTERPRISE_B0_SPECIFICATION.md
?? scripts/b0_collection_probe.py

## ci.yml diff vs HEAD (tracked file)
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index bcb5d90..9a2a12e 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -20,27 +20,32 @@ jobs:
       # 依赖刻意取"能 import `app.*` 的最小集"，与 backend-integration 那套轻量安装同源
       # （conftest 会话夹具会 module-level import `sec_a_seed` → `app.llm.*` → httpx；
       # 只装 pydantic+argon2 的第一版在 CI 收集阶段就 ModuleNotFoundError: httpx，本地却绿）。
-      - name: Install SECA-20 secret-scan dependencies
-        run: >-
-          python -m pip install --disable-pip-version-check
-          pytest
-          "fastapi>=0.115,<1"
-          "pydantic>=2.8,<3"
-          "pydantic-settings>=2.4,<3"
-          "python-multipart>=0.0.9"
-          "httpx>=0.27,<1"
-          "PyJWT>=2.9,<3"
-          "numpy>=1.26,<3"
-          "rank-bm25>=0.2.2"
-          "qdrant-client>=1.12,<2"
-          "argon2-cffi>=23.1.0,<26"
+      - name: Cache pip wheels
+        uses: actions/cache@v4
+        with:
+          path: ~/.cache/pip
+          key: b0-${{ runner.os }}-py3.12-${{ hashFiles('backend/requirements.txt') }}
+      - name: Install backend dependencies (same source as requirements.txt)
+        run: |
+          # B0 §5.1：依赖真源只有 backend/requirements.txt 一份。
+          # torch 这一行不是新增依赖，是**发行源选择**：sentence-transformers 的传递依赖，
+          # CPU wheel ~200MB 而不是默认那个带 CUDA 的 ~2.5GB。配方照抄 backend-quality。
+          python -m pip install --disable-pip-version-check torch --index-url https://download.pytorch.org/whl/cpu
+          python -m pip install --disable-pip-version-check -r backend/requirements.txt
+          python -m pip install --disable-pip-version-check pytest
       - name: Run SECA-20 delivery-surface secret scan
         run: >-
           python -m pytest backend/tests/test_secret_hygiene_contract.py -q
           -k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"
       - run: python -m compileall -q backend/app scripts
       - run: python scripts/validate_demo_assets.py
-      - run: python -m unittest discover -s backend/tests -p 'test_*.py' -v
+      # B0 §5.2 两条顺序理由，删掉任何一条都会让 test_step_ordering_still_explains_itself 红：
+      #   (1) SECA-20 扫描步排在主门之前：成本为零，主门红了扫描照样已报。
+      #   (2) compose/pwsh 两步保持在最后：它们在主门不再恒红之后才第一次真起跑（B0-10）。
+      # 原既有步 `python -m unittest discover -s backend/tests -p 'test_*.py' -v` 已删除：
+      # 它从原理上收不到模块级裸函数（§2 的 45 枚差），且它在 main 上本就红，红到吞掉后面两步。
+      - name: "Run backend contract suite (single runner: pytest)"
+        run: python -m pytest backend/tests -q
       - name: Validate Docker Compose configuration
         run: |
           cp backend/.env.example backend/.env

## gate file delta (Task-2-fix1 snapshot -> now)
@@ -30,6 +30,14 @@ ci.yml 类门的共同口径：所有对**命令**的匹配都先在 `_step_scri
 `_job_steps` 会把两枚 step **之间**的注释归进前一枚 step，拿原文匹配命令的门因此会永远红在错误
 的 step 上。唯一例外是 `test_step_ordering_still_explains_itself` 的文字存在半边：它的宾语正是
 注释本身，必须看原文。
+
+第 16 枚门（R9 ②）不属于上面四族，它守的是"这份 workflow 打得开"：Task 3 真踩到计划正文里的
+`- name: Run backend contract suite (single runner: pytest)` —— plain scalar 里的 `: ` 被 YAML
+读成映射分隔符，`yaml.safe_load` 当场 `ScannerError`，而上面 15 枚门全是正则 + 行切片、从不
+加载 YAML ⇒ 一份语法就错的 ci.yml 可以拿 14 绿，到远端才炸 `Invalid workflow file`。PyYAML 既
+不在 `backend/requirements.txt` 里（B0 也不许动它），门又必须只用标准库，所以这里**不做 YAML
+解析器**（那等于给自己造第二份真相），只钉住刚刚真咬过我们的那一形：含 `: ` 的 plain scalar
+必须整体加引号。
 """
 from __future__ import annotations
 
@@ -80,8 +88,11 @@ def _per_module(ids: list[str]) -> "dict[str, int]":
     return out
 
 
-# 常数在修复轮 1 重新实测回写：1316 是 Task 1 的基线，本文件现在贡献 15 枚（卡 H / 卡 I 各加一枚）。
-EXPECTED_COLLECTED = 1331
+# 常数每加一枚门就要重新实测回写（不许凑）：1316 是 Task 1 的基线，本文件现在贡献 16 枚
+# （卡 H / 卡 I 各加一枚 = 15，R9 ② 的第 16 枚 = 含 `: ` 的 plain scalar 必须加引号）。
+# Task 3 修复轮 1 的读数：`python scripts/b0_collection_probe.py` → TOTAL 1332，
+# `--node-ids | grep test_ci_gate_contract | wc -l` → 16 ⇒ 1316 + 16 = 1332，两侧都是实测量。
+EXPECTED_COLLECTED = 1332
 
 
 def test_collected_count_matches_the_pinned_number():
@@ -126,7 +137,7 @@ def test_the_gate_module_itself_carries_no_skip_or_xfail_decorator():
 
     为什么必须是机器判据而不是口径：枚数钉对 skip 类标记天生瞎（独立评审实测：带三种哑门标记的
     夹具照样被 `--collect-only` 打印 4 枚 node id、rc=0），所以随便给一枚门挂上 skip 标记就能让
-    本文件 15 枚全绿而其中任意几枚永不执行——正是规格 F6"门在场但哑了"。这一格把"哑掉"
+    本文件 16 枚全绿而其中任意几枚永不执行——正是规格 F6"门在场但哑了"。这一格把"哑掉"
     变成可判定的。
     """
     source = Path(__file__).resolve().read_bytes().decode("utf-8", "replace")
@@ -234,8 +245,8 @@ def test_backend_contracts_runs_the_pytest_suite():
     而它要防的"主门被删掉"永远抓不到。
 
     I-5 是另一半：光"命中一次目录级调用"不够 —— 同一步挂上 `-k` / `--ignore` / `--deselect` /
-    `-x` / `--lf` 之类旗标就只跑一个子集，收集数钉（B0-01）声称的那 1331 枚从此没有任何一步
-    真正执行过，而 15 枚门照样全绿。所以主门正文里一枚过滤旗标都不许出现。
+    `-x` / `--lf` 之类旗标就只跑一个子集，收集数钉（B0-01）声称的那 1332 枚从此没有任何一步
+    真正执行过，而 16 枚门照样全绿。所以主门正文里一枚过滤旗标都不许出现。
     """
     runs = _test_runs(_ci_text(), BACKEND)
     suite_wide = [step for step in runs
@@ -479,6 +490,113 @@ def test_every_exemption_row_states_why():
         assert count >= 1, token
         assert len(why) >= 12, f"豁免行 `{token}` 的『为什么』短到不像是理由，像是占位"
 
+# ---------------------------------------------------------------------------
+# 第 16 枚门（R9 ②）：plain scalar 的值里含 `: ` 时，整个值必须带引号。
+# 口径只钉这一形、刻意不扩：门要守的是"刚刚真咬过我们的东西"，不是一台 YAML 机器。
+# ---------------------------------------------------------------------------
+
+#: 结构行的形状：`[缩进][- ]键: 值`。键限定成 ASCII 单词字符（workflow 的键全在这一族：
+#: `name` / `run` / `uses` / `key` / `shell` / `python-version`……），于是中文散文、
+#: `- 6333:6333`（ports 序列项）、`qdrant/qdrant:v1.19.1`（冒号后没有空格）都不算结构行。
+_STRUCTURAL_SCALAR_LINE = re.compile(
+    r"^(?P<indent>[ \t]*)"
+    r"(?:(?P<dash>-)[ \t]+)?"
+    r"(?P<key>[A-Za-z0-9][A-Za-z0-9_.\-]*)[ \t]*:[ \t]+(?P<value>\S.*)$")
+
+#: 块标量的开头指示符：`|` `|-` `|+` `|2` `>` `>-` `>+`……值为这一形时它下面缩进更深的行全是正文。
+_BLOCK_SCALAR_INDICATOR = re.compile(r"^[|>][0-9]*[-+]?[0-9]*$")
+
+#: flow 集合的值：`branches: [main]` / `ports: [6333, 6334]` / `with: {…}`。
+_FLOW_STYLE_VALUE = re.compile(r"^[\[{]")
+
+#: 内联注释：plain scalar 里"空格 + 井号"起就是注释（YAML 自己也是这条规则），
+#: 注释里的 `: ` 是散文、不是值的一部分。
+_INLINE_COMMENT = re.compile(r"[ \t]#")
+
+
+def _fully_quoted(value: str) -> bool:
+    """整体被同一枚引号包住（`"…"` / `'…'`）：里面的 `: ` 是值的一部分，YAML 不会误读。"""
+    return len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'")
+
+
+def _workflow_scalar_entries(text: str) -> "list[tuple[int, str, str, bool]]":
+    """把 workflow 原文切成结构标量条目 `(行号, 键, 值, 是否带 `- ` 前缀)`。
+
+    这里唯一的"语义"是一条缩进规则：一枚 `键: |` / `键: >-` 之后、缩进比它深的行都是正文，
+    整段跳过。这不是怕麻烦，而是**判据不能反过来咬人**——`run: |` 里的 python/shell 代码随时
+    可以合法写出 `print("failed: x")`，那枚冒号在 YAML 语义里根本没有歧义，拿它判红就是一枚
+    会自己假红的门。跳过正文也不等于放宽：本门的宾语是 step 名与键值，Task 3 炸的也正是它。
+    同样刻意留在范围外的是多行 plain scalar 的续行、锚点与别名（`&x` / `*x`）——它们都不是
+    咬过我们的那一形，再往下钉就等于开始重造解析器（R9 ② 明令禁止的那份"第二套真相"）。
+    """
+    out: "list[tuple[int, str, str, bool]]" = []
+    block_indent = None
+    for lineno, line in enumerate(text.splitlines(), 1):
+        stripped = line.strip()
+        if not stripped or stripped.startswith("#"):
+            # 空行 / 整行注释：ci.yml:22 那句 `ModuleNotFoundError: httpx` 走这一支被放过
+            continue
+        indent = len(line) - len(line.lstrip(" \t"))
+        if block_indent is not None:
+            if indent > block_indent:
+                continue                       # 块标量的正文，不是 `键: 值`
+            block_indent = None                # 缩进回落 ⇒ 块结束，本行照常参与检查
+        match = _STRUCTURAL_SCALAR_LINE.match(line)
+        if match is None:
+            continue
+        value = match.group("value").rstrip()
+        if _BLOCK_SCALAR_INDICATOR.match(value):
+            block_indent = indent              # 这一行没值可查，它只是开了一个块
+            continue
+        out.append((lineno, match.group("key"), value, match.group("dash") is not None))
+    return out
+
+
+def _unquoted_colon_bearing_scalars(text: str) -> "list[tuple[int, str, str]]":
+    """条目里"值含 `: ` 却没整体加引号"的那几枚 —— R9 ① 咬过我们的原形。
+
+    邻形登记（**刻意不钉**，要扩得控制器点头）：值以冒号**结尾**（`- name: Note:`）同样让
+    PyYAML 报 `ScannerError: mapping values are not allowed here`，可 R9 ② 的字面范围是
+    "值里含 `: `"。本枚按字面走，邻形只留这一句注释 + 报告里的实测证据。
+    """
+    offenders: "list[tuple[int, str, str]]" = []
+    for lineno, key, value, dashed in _workflow_scalar_entries(text):
+        if _FLOW_STYLE_VALUE.match(value):
+            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
+        if _fully_quoted(value):
+            continue
+        body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
+        if ": " in body:
+            offenders.append((lineno, ("- " if dashed else "") + key, body))
+    return offenders
+
+
+def test_workflow_plain_scalars_bearing_a_colon_space_are_quoted():
+    """第 16 枚门（R9 ②）：`- name:` / `key:` 这类 plain scalar 值里含 `: ` 时必须整体加引号。
+
+    存在理由是一次真实事故、不是审美：计划正文原本写
+    `- name: Run backend contract suite (single runner: pytest)`，那枚没引号的 `: ` 让 YAML
+    把它读成嵌套映射，`yaml.safe_load` 当场 `ScannerError: mapping values are not allowed
+    here` ——而前面 15 枚门**没有一枚会加载 YAML**（PyYAML 不在 requirements.txt，门也不许引
+    第三方依赖），所以一份连 GitHub 都打不开的 workflow 能拿 14 绿，直到远端报
+    `Invalid workflow file` 才响。修法是钉形状而不是引依赖。地板与
+    `test_extra_pip_arguments_are_exactly_the_exemption_table` 的"非空 tokenize"同族：扫不到
+    任何 `- name:` 就当场红，因为那只可能是门哑了，不可能是"步名全都合法"。
+    """
+    text = _ci_text()
+    entries = _workflow_scalar_entries(text)
+    named = [row for row in entries if row[1] == "name" and row[3]]
+    assert named, (
+        f"workflow 里一枚 `- name:` 结构行都没扫到（结构行共 {len(entries)} 枚）：这不能读成"
+        f"『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）")
+    offenders = _unquoted_colon_bearing_scalars(text)
+    assert not offenders, (
+        f"{len(offenders)} 枚 plain scalar 的值里含 `: ` 却没整体加引号 —— YAML 会把那枚冒号读成"
+        f"映射分隔符，整份 workflow 直接 `ScannerError`："
+        + "；".join(f"第 {lineno} 行 `{key}: {value}`" for lineno, key, value in offenders)
+        + "\n修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），"
+          "不是把带冒号的那半句删掉")
+
 REQUIRED_GITATTRIBUTES_RULES = (
     "* text=auto",
     "*.sh text eol=lf",
@@ -567,7 +685,7 @@ def test_eol_rules_are_a_no_op_for_the_current_tree():
     assert checked, "`.sh` / `.ps1` 一枚都不在面上：这条 no-op 证明退化成了空判"
     assert not offenders, "加规则会改动工作树：" + "；".join(offenders)
 
-#: 15 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
+#: 16 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
 #: 只遍历本模块的用例，对本文件被摘走任何东西都无感。
 _OWN_TEST_NAMES = (
     "test_collected_count_matches_the_pinned_number",
@@ -581,6 +699,7 @@ _OWN_TEST_NAMES = (
     "test_extra_pip_arguments_are_exactly_the_exemption_table",
     "test_install_face_pip_source_values_are_pinned",
     "test_every_exemption_row_states_why",
+    "test_workflow_plain_scalars_bearing_a_colon_space_are_quoted",
     "test_gitattributes_carries_the_required_rules",
     "test_index_has_no_crlf_entries",
     "test_non_text_index_entries_are_exactly_the_enumerated_set",
