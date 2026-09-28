# Task 3 fix-round-2 scoped diff

gate file: snap-task3-fix1-post -> now
@@ -36,8 +36,10 @@ ci.yml 类门的共同口径：所有对**命令**的匹配都先在 `_step_scri
 读成映射分隔符，`yaml.safe_load` 当场 `ScannerError`，而上面 15 枚门全是正则 + 行切片、从不
 加载 YAML ⇒ 一份语法就错的 ci.yml 可以拿 14 绿，到远端才炸 `Invalid workflow file`。PyYAML 既
 不在 `backend/requirements.txt` 里（B0 也不许动它），门又必须只用标准库，所以这里**不做 YAML
-解析器**（那等于给自己造第二份真相），只钉住刚刚真咬过我们的那一形：含 `: ` 的 plain scalar
-必须整体加引号。
+解析器**（那等于给自己造第二份真相），只钉住刚刚真咬过我们的那一族形状：含 `: ` 的 plain scalar
+必须整体加引号；R10 的修复轮 2 又补了两条——同一枚 `ScannerError` 家族里的尾冒号邻形
+（`- name: Note:`）一起钉，而判定顺序改成"先剥行内注释、再判引号"，因为反序会把
+`- name: "…"  # 说明` 这形合法写法判成假红（假红正是本仓库最贵的那种错：它教会人加豁免）。
 """
 from __future__ import annotations
 
@@ -491,8 +493,10 @@ def test_every_exemption_row_states_why():
         assert len(why) >= 12, f"豁免行 `{token}` 的『为什么』短到不像是理由，像是占位"
 
 # ---------------------------------------------------------------------------
-# 第 16 枚门（R9 ②）：plain scalar 的值里含 `: ` 时，整个值必须带引号。
-# 口径只钉这一形、刻意不扩：门要守的是"刚刚真咬过我们的东西"，不是一台 YAML 机器。
+# 第 16 枚门（R9 ② 落地；R10 修复轮 2 把邻形扩了一形）：plain scalar 的值里含 `: `、
+# 或剥完行内注释后以 `:` 结尾时，整个值必须带引号。
+# 口径仍钉在"刚刚真咬过我们的那一族形状"上，不扩成一台 YAML 机器：tab / 缩进 / 引号配对
+# 三件套按 R10 判为 YAGNI，留在临时脚本里当证据。
 # ---------------------------------------------------------------------------
 
 #: 结构行的形状：`[缩进][- ]键: 值`。键限定成 ASCII 单词字符（workflow 的键全在这一族：
@@ -553,20 +557,24 @@ def _workflow_scalar_entries(text: str) -> "list[tuple[int, str, str, bool]]":
 
 
 def _unquoted_colon_bearing_scalars(text: str) -> "list[tuple[int, str, str]]":
-    """条目里"值含 `: ` 却没整体加引号"的那几枚 —— R9 ① 咬过我们的原形。
-
-    邻形登记（**刻意不钉**，要扩得控制器点头）：值以冒号**结尾**（`- name: Note:`）同样让
-    PyYAML 报 `ScannerError: mapping values are not allowed here`，可 R9 ② 的字面范围是
-    "值里含 `: `"。本枚按字面走，邻形只留这一句注释 + 报告里的实测证据。
+    """条目里"值有歧义、又没整体加引号"的那几枚 —— R9 ① 咬过我们的原形 + R10 扩的尾冒号邻形。
+
+    **顺序就是判据本身**（修复轮 2 的 I-3）：先剥行内注释、再判引号。反序会假红——
+    `- name: "…(single runner: pytest)"  # 说明` 的原始值末字符是注释散文，`_fully_quoted()`
+    于是认不出那对引号，合法 YAML 被判红。这不是讲究：本仓库的失效史就是
+    假红 → 有人加豁免 → 真形状跟着漏（§2、卡 I 各留了一页）。
+    尾冒号邻形（Minor 5，R10 点头才扩）：剥完的值以 `:` **结尾**（`- name: Note:`）是嵌套映射
+    的 opener，宿主 PyYAML 实测 `ScannerError: mapping values are not allowed here`，与含 `: `
+    同属一枚事故家族 ⇒ 一个子句一起钉。**仍然不做** tab / 缩进 / 引号配对三件套（R10 判 YAGNI）。
     """
     offenders: "list[tuple[int, str, str]]" = []
     for lineno, key, value, dashed in _workflow_scalar_entries(text):
-        if _FLOW_STYLE_VALUE.match(value):
-            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
-        if _fully_quoted(value):
-            continue
         body = _INLINE_COMMENT.split(value, 1)[0].rstrip()
-        if ": " in body:
+        if _FLOW_STYLE_VALUE.match(body):
+            continue                           # flow 集合里的冒号是 YAML 自己的分隔符
+        if _fully_quoted(body):
+            continue                           # 整体被同一对引号包住 ⇒ 冒号是值的一部分
+        if ": " in body or body.endswith(":"):
             offenders.append((lineno, ("- " if dashed else "") + key, body))
     return offenders
 
@@ -582,6 +590,12 @@ def test_workflow_plain_scalars_bearing_a_colon_space_are_quoted():
     `Invalid workflow file` 才响。修法是钉形状而不是引依赖。地板与
     `test_extra_pip_arguments_are_exactly_the_exemption_table` 的"非空 tokenize"同族：扫不到
     任何 `- name:` 就当场红，因为那只可能是门哑了，不可能是"步名全都合法"。
+
+    修复轮 2（R10 的 I-3 + Minor 5）动了这枚门的**两处**，门数与门名都不变（R10 明令不加门）：
+      * 判定顺序：行内注释先剥、引号后判。反序会假红 `- name: "…"  # 说明` 这形——它在 YAML 里
+        完全合法（宿主 PyYAML 复验通过），而本仓库的失效史是"假红 → 加豁免 → 真形状跟着漏"。
+      * 覆盖面：除"值里含 `: `"外，另钉"剥完注释的值以 `:` 结尾"（`- name: Note:`），同一枚
+        `ScannerError` 事故家族、同一条修法。
     """
     text = _ci_text()
     entries = _workflow_scalar_entries(text)
@@ -591,8 +605,8 @@ def test_workflow_plain_scalars_bearing_a_colon_space_are_quoted():
         f"『步名全都合法』，只能读成这枚门哑了（卡 I (2) 的同一判据）")
     offenders = _unquoted_colon_bearing_scalars(text)
     assert not offenders, (
-        f"{len(offenders)} 枚 plain scalar 的值里含 `: ` 却没整体加引号 —— YAML 会把那枚冒号读成"
-        f"映射分隔符，整份 workflow 直接 `ScannerError`："
+        f"{len(offenders)} 枚 plain scalar 的值里含 `: `（或以 `:` 结尾）却没整体加引号 —— YAML 会把"
+        f"那枚冒号读成映射分隔符或嵌套映射的 opener，整份 workflow 直接 `ScannerError`："
         + "；".join(f"第 {lineno} 行 `{key}: {value}`" for lineno, key, value in offenders)
         + "\n修法=给值整体加双引号（Task 3 对主门步名就是这么修的，文本一字不改），"
           "不是把带冒号的那半句删掉")

## ci.yml full diff vs HEAD
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
index bcb5d90..74a66da 100644
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -14,33 +14,47 @@ jobs:
       - uses: actions/setup-python@v5
         with:
           python-version: '3.12'
-      # SECA-20（SEC-A 验收矩阵第 20 行）的执行位置。两步都必须在下面那枚既有步之前：
-      # GitHub 的步骤一旦失败，同一 job 后续步骤不再执行——放在 `unittest discover` 之后
-      # 等于这道门永远不跑（终审实测该既有步在 main HEAD 上就是红的，且早于 SEC-A）。
-      # 依赖刻意取"能 import `app.*` 的最小集"，与 backend-integration 那套轻量安装同源
-      # （conftest 会话夹具会 module-level import `sec_a_seed` → `app.llm.*` → httpx；
-      # 只装 pydantic+argon2 的第一版在 CI 收集阶段就 ModuleNotFoundError: httpx，本地却绿）。
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
+      # SECA-20（SEC-A 验收矩阵第 20 行）的执行位置：这一步必须排在主门之前——GitHub 的步骤
+      # 一旦失败，同一 job 后续步骤不再执行 ⇒ 排在主门之后，它在主门红的那次运行里永远轮不到。
+      # 依赖现状：本 job 装**整份** backend/requirements.txt（下面那枚安装步就是唯一真源）；
+      # backend-integration 仍是它自己那套手写轻量清单。两枚 job 跑法不同——这里用 pytest 收
+      # 整个 backend/tests、经 conftest；那边只跑 scripts/*.py——依赖来源随之分家，别互相抄：
+      # 往这里加包名会红在豁免表钉上（f6c67b5 那版正是手写清单，远端当场 ModuleNotFoundError: httpx）。
+      # 历史（已作废，只当事故记录读）：B0 之前本 job 刻意取"能 import `app.*` 的最小集"、与
+      # backend-integration 同源；只装 pydantic+argon2 的第一版在 CI 收集阶段就红、本地却绿。
+      - name: Cache pip wheels
+        uses: actions/cache@v4
+        with:
+          path: ~/.cache/pip
+          key: b0-${{ runner.os }}-py3.12-cpu-torch-${{ hashFiles('backend/requirements.txt') }}
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
+      # B0 §5.2 的两条顺序理由在下面 (1)(2)。旧抬头那句『删掉任何一条都会让门红』经修复轮 2
+      # 实测证伪、已按实测重写（逐块删注释跑 test_step_ordering_still_explains_itself，
+      # 实验表在 task-3-report.md《Task 3 修复轮 2》）。机器的与人审的分界是：
+      #   机器钉：step 相对顺序严格递增（扫描 < 主门 < compose < pwsh）——把扫描步挪到主门
+      #   之后当场红；文字半边只 grep 两枚 token 还在不在 job 块里：扫描步的编号由那枚 step
+      #   的**名字**自己供着（删注释删不掉它），旧 runner 的名字仅系在下面“原既有步已删除”
+      #   那一句上 ⇒ 删那一句才红，删 (1) 或删 (2) 任何一条门都照绿。
+      #   所以这两条理由的取舍与措辞由**人审**担保（规格要求它们逐字留在树上），别以为门拦得住。
+      #   (1) SECA-20 扫描步排在主门之前：成本为零，主门红了扫描照样已报。
+      #   (2) compose/pwsh 两步保持在最后：它们在主门不再恒红之后才第一次真起跑（B0-10）。
+      # 原既有步 `python -m unittest discover -s backend/tests -p 'test_*.py' -v` 已删除：
+      # 它从原理上收不到模块级裸函数（§2 的 45 枚差），且它在 main 上本就红，红到吞掉后面两步。
+      - name: "Run backend contract suite (single runner: pytest)"
+        run: python -m pytest backend/tests -q
       - name: Validate Docker Compose configuration
         run: |
           cp backend/.env.example backend/.env
