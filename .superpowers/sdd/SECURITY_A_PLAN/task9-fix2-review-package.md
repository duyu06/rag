# Task 9 fix round 2 - review package (snapshot diff, no commits)
Base = the head the round-1 re-review saw (its citations: EXEMPTIONS 16/31, faces at :381-407, _faces_for at :461-472).
Head = current worktree.

sha1(base backup) = 3ad48430a7b1765b51219187e5722393d377186c | lines base->head = 892 -> 948
This round changes ONE code file (the scan gate itself). Everything else is doc write-back.

## backend/tests/test_secret_hygiene_contract.py
--- base

+++ head

@@ -125,17 +125,21 @@

     assert "Bearer [REDACTED]" in out["note"]
 
 
 # --------------------------------------------------------------------------- #
 # SEC-A-006：既有响应面 redact_secrets 语义一字不动
 # --------------------------------------------------------------------------- #
 
 def test_redact_secrets_semantics_are_unchanged():
-    """既有 28 处调用点的响应面语义一字不动（SEC-A-006）。"""
+    """既有 `redact_secrets` 的响应面语义一字不动（SEC-A-006）。
+
+    这是**行为**探针，不是字节比对：它钉的是"形态照旧、且不因键名误伤"。调用点总数的等式钉在
+    `test_the_four_persistence_faces_use_the_persistence_redactor`（AST，17 处）。
+    """
     assert security.redact_secrets({"access_token": "keep-me"}) == {"access_token": "keep-me"}
     assert "Bearer [REDACTED]" in security.redact_secrets("header: Bearer abc.def.ghi")
 
 
 def test_redact_secrets_does_not_apply_the_persistence_key_blacklist():
     """两个域是**两个**函数：响应面绝不因键名抹掉 access_token（登录就发不出票了）。"""
     body = {"access_token": "a-real.jwt.token", "password": "not-a-response-face"}
     kept = security.redact_secrets(body)
@@ -352,29 +356,43 @@

 #: `passwd`，允许 `JWT_SECRET`、`tenant_access_token` 这类前后缀）+ `:` 或 `=` + **成对引号包住、
 #: 内部无空白**的 ≥16 字符串。三处细节都是刻意的：
 #: ① 键名**不再要求词首 `\b`**——`_` 是词字符，`\bsecret` 在 `JWT_SECRET=` 上永远匹配不到，
 #:    那等于把整类 env 形状的泄漏做成隐形（旧门的全部问题都在这里）；
 #: ② 值必须是**字面量**：`password = _password_from_env` 取的是变量/调用而不是材料，散文里引用
 #:    这条语句也不构成凭据；
 #: ③ 注解写法（`jwt_secret: str = "…"`）同样在面上，否则配置默认值那一格就是盲区。
 #:
-#: **env 面**（`.env*` / compose / `scripts/`）：这三处的 native 语法是**不带引号**的 `KEY=value`，
-#: 字面量面在结构上抓不到它 ⇒ 另开一条无引号面（值仍要 ≥16 且无空白）。范围收在这三处，是因为
-#: 不做范围限定的"大写名=value"在代码与正则会撞出遍地噪声。
+#: **env 面**（`.env*` / compose / `scripts/`，以及**配置文件档**：`.yml/.yaml/.ini/.conf/.toml/
+#: .cfg/.properties` 与 `Dockerfile*`/`Containerfile*`）：这些地方的 native 语法是**不带引号**的
+#: `KEY=value` / `KEY: value`，字面量面在结构上抓不到它 ⇒ 另开一条无引号面（值仍要 ≥16 且无空白）。
+#: 配置文件档额外用**大小写不敏感**的那一枚：CI/YAML 习惯写大写键，而 INI/TOML/properties 的键名
+#: 通常是小写（`password: <真值>`），只按大写抓等于给这一档留洞。范围收在"配置文件 + env + compose
+#: + scripts"，是因为不做限定的"名=value"在代码与正则会撞出遍地噪声。
+#: 实测代价（Task 9 修复轮 2 量过）：当前面上那三份配置文件（`.github/workflows/ci.yml`、
+#: `backend/Dockerfile`、`frontend/Dockerfile`）无论大小写敏感与否都是 **0 命中** ⇒ 拓宽不产生
+#: 任何新豁免行，也就是说不拓宽**换不来**任何东西，纯粹是少一面。
+#: 命名的残余风险（诚实版）：**代码文件里的无引号赋值**仍不在 env 面的射程内（Python/TS 的
+#: `password = "…"` 由字面量面抓，无引号形态在那两类语言里不是合法赋值），这一条随 §18 的
+#: 带历史第三方扫描器一起收口。
 #:
 #: **材料形状面**：不依赖任何赋值形态的现网密钥形状（`sk-…` / `ghp_…` / `AKIA…` / `eyJ…` /
 #: 私钥 PEM 头）——"贴进代码的一段裸密钥"（没有 `key =` 外壳）也红。
 #:
 #: **范围决策（两档，不是 15 条豁免）。**
 #: - `*.md`（交付文档：`docs/**` 与 README）只上**材料形状面**。散文按定义就要引用代码与测试夹具
 #:   的字面量（单是 `docs/SECURITY_A_PLAN.md` 就有 32 处合法引用），逐条进豁免表等于把门换成一张
 #:   永远补不完的清单，所以赋值形态那两枚面在散文里不作数；但"贴进文档的一段现网密钥"（`sk-…` /
 #:   `eyJ…` / PEM 头）照样红。实测交付文档在这一枚上今天 **0 命中** ⇒ 这一档不收豁免、不给未来留
-#:   漂移债，只把"真凭据只出现在 markdown 里"那条残余风险关掉。
+#:   漂移债。**范围要说准**：这一枚关掉的是"现网密钥形状被贴进文档"（provider key / JWT / PEM），
+#:   关不掉"文档里写了一条完整赋值形态的口令"（`OPENAI_API_KEY = "glpat-…"` 之外的
+#:   `password = "…" ` 这类散文引用与真泄漏在这一档**同形**，不可分）。这条残余一并交 §18 的
+#:   带历史扫描器。另一条实操约束：canary 字面量（`sk-CANARY-…`）是**材料形状**，验收文档引用它
+#:   时要按 `路径:行号` 指过去，不要把字面量抄进 `docs/**`——那会让门为一枚假凭据红，正是这一档
+#:   声称要免掉的那类摩擦。
 #: - `.superpowers/**`（SDD 过程件：plan / report / 历轮 baseline 快照）整目录不在面上。理由更强
 #:   一档：那里躺着**故意**写下的 canary 字面量（`sk-CANARY-<16位哈希>-not-in-any-message`），还有被
 #:   逐字复制进来的 `app/` 源码副本（同一枚已豁免材料会再出现一遍）；它是过程**证据**，按
 #:   `.gitignore` 的口径默认不入库、只在终审时精选 `-f`。把豁免表绑在这种目录上更糟：下一轮快照
 #:   一入库门就红，而那次红与"有没有真凭据"毫无关系。
 #: 命名的残余风险：只在过程件里出现的凭据材料本门够不到——那是 §18 已登记的第三方扫描器
 #: （gitleaks，带 git 历史）后续项的职责，SEC-A 明确不引入第三方扫描器、不新增 security job。
 _UNSCANNED_PREFIXES = (".superpowers/",)
@@ -399,17 +417,23 @@

     ["']?[A-Za-z0-9_.\-/+~]{16,}
     """,
     re.X,
 )
 _MATERIAL_FACE = re.compile(
     r"sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}"
     r"|eyJ[A-Za-z0-9_\-]{16,}|BEGIN [A-Z ]*PRIVATE KEY"
 )
+#: 配置文件档专用的大小写不敏感 env 面：INI/TOML/properties 的键名通常是小写，
+#: 只按 `[A-Z0-9_]*` 抓会把 `password: <真值>` 整档放过。
+_ENV_FACE_CI = re.compile(_ENV_FACE.pattern, re.X | re.I)
+_CONFIG_SUFFIXES = (".yml", ".yaml", ".ini", ".conf", ".toml", ".cfg", ".properties")
+_CONFIG_FILE_NAMES = ("dockerfile", "containerfile", "makefile", "procfile")
 _ALL_FACES = (_LITERAL_FACE, _ENV_FACE, _MATERIAL_FACE)
+_CONFIG_FACES = (_LITERAL_FACE, _ENV_FACE_CI, _MATERIAL_FACE)
 _CODE_FACES = (_LITERAL_FACE, _MATERIAL_FACE)
 _BINARY_SUFFIXES = {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}
 
 #: 豁免表的键是 **(相对路径 → (命中处数, 为什么它不是凭据材料))**，不是 `文件:行号`。
 #: 行号会洗白这道门：①已经豁免的那一行上再放第二枚真凭据 = 同一个键 = 静音；②行号在上方
 #: 任何一次编辑后整体漂移，表跟着漂就等于门废了。处数是**计数**，多一枚必红、少一枚（死行）也红
 #: ——与 `test_llm_egress_guard.py` 的 `EXEMPTIONS` 同一形状。
 #: 每一行的"为什么"必须落到**这一处材料本身**（出厂默认 / 审计枚举 token / env 变量名 / 测试诱饵 /
@@ -457,23 +481,27 @@

     "scripts/deploy.ps1": (2, "检测/替换出厂默认 JWT_SECRET 的正则字面量，与守卫比对基准同源"),
 }
 
 
 def _faces_for(relative: str) -> tuple[re.Pattern[str], ...]:
     """每类文件上哪几枚面。
 
     markdown 只上材料形状面（散文里的 `KEY=value` 是引用不是材料）；`.env*`、compose、`scripts/`
-    三处 native 语法真是 `KEY=value`，所以上全三枚；其余（代码 / 配置 / 前端）上字面量 + 材料两枚。
+    三处 native 语法真是 `KEY=value`，所以上全三枚；**配置文件档**（`.yml/.yaml/.ini/.conf/
+    .toml/.cfg/.properties` 与 `Dockerfile*` 等）上"字面量 + 大小写不敏感的 env + 材料"，因为
+    这一档的键名大小写没有约定；其余（代码 / 前端）上字面量 + 材料两枚。
     """
     name = PurePosixPath(relative).name.lower()
     if relative.endswith(".md"):
         return (_MATERIAL_FACE,)
     if name.startswith(".env") or relative.startswith("scripts/") or "compose" in name:
         return _ALL_FACES
+    if relative.endswith(_CONFIG_SUFFIXES) or name.startswith(_CONFIG_FILE_NAMES):
+        return _CONFIG_FACES
     return _CODE_FACES
 
 
 def _occurrence_lines(text: str, *, relative: str) -> list[int]:
     """去重叠后的命中行号（行号只给人读，不进豁免键）。
 
     同一枚泄漏被两枚面各抓一次 ⇒ 区间重叠 ⇒ 合并成**一处**，所以"处数"数的是泄漏而不是正则
     匹配次数；同一行上的两处不重叠泄漏 ⇒ 两处，豁免表就会因为多一枚而红。
@@ -611,19 +639,47 @@

 
     measured = _hit_counts([relative], root=tmp_path)
     assert EXEMPTIONS[relative][0] + 1 == measured[relative], (
         "第二枚凭据没有让处数变化 ⇒ 键退化成了行号，豁免会吞掉同一行上的任何新泄漏")
     offenders = [item for item in _gate_offenders(measured) if item.startswith(relative)]
     assert offenders, "处数已经漂了却仍然对账通过 ⇒ 豁免把第二枚吞了"
 
 
+def test_unquoted_config_file_assignments_are_on_the_face(tmp_path):
+    """配置文件档的**无引号**赋值必须在面上（Task 9 修复轮 2：拓宽这一档实测零成本）。
+
+    评审量的洞：`password: <真值>` 这种 INI/TOML/CI 的 native 形状既没有引号（字面量面抓不到）、
+    又不在 `.env*`/compose/`scripts/` 三处（env 面当时不给它），于是整档致盲。三种形状各植一枚，
+    全部只在 tmp 里落盘，不碰仓库索引与工作树。
+    """
+    cases = {
+        ".github/workflows/planted-ci.yml": f"{_ENV_KEY_NAME}: {_PLANTED_VALUE}\n",
+        "backend/deploy/planted.ini": f"{_LOWER_KEY_NAME} = {_PLANTED_VALUE}\n",
+        "backend/Dockerfile.planted": f"ENV {_ENV_KEY_NAME}={_PLANTED_VALUE}\n",
+    }
+    assert _CONFIG_FACES == _faces_for("backend/deploy/planted.ini"), (
+        "配置文件档没有拿到大小写不敏感的 env 面")
+    for relative, body in cases.items():
+        target = tmp_path / relative
+        target.parent.mkdir(parents=True, exist_ok=True)
+        target.write_text(body, encoding="utf-8")
+        assert 1 == len(_occurrence_lines(body, relative=relative)), (
+            f"{relative} 上的无引号赋值没被抓到 ⇒ 这一档仍是瞎的")
+    measured = _hit_counts(list(cases), root=tmp_path)
+    assert {rel: 1 for rel in cases} == {rel: measured.get(rel, 0) for rel in cases}
+    offenders = [item for item in _gate_offenders(measured)
+                 for rel in cases if item.startswith(rel)]
+    assert len(cases) == len(offenders), "配置文件档植进去的凭据没有让门红"
+
+
 # 植入用的字面量按拼接构造：本文件在扫描面上，任何"键 + = + 引号 + ≥16 无空白值"的写法都会
 # 让豁免表的计数变成移动靶。
 _ENV_KEY_NAME = "JWT_" + "SECRET"
+_LOWER_KEY_NAME = "user_" + "password"
 _PLANTED_VALUE = "planted-" + "credential-material-32-bytes"
 _SECOND_PLANTED_VALUE = "second-" + "credential-on-exempt-line"
 
 
 # --------------------------------------------------------------------------- #
 # 真实登录两向边界 + Task 7 移交的 root_path 无回显守卫 + 可用性事件归属
 # --------------------------------------------------------------------------- #
 

## spec/glossary deltas authored by the controller this round (not part of the code diff)
See docs/SECURITY_A_SPECIFICATION.md rows 50, 126 and section 20.4; docs/UI_COPY_GLOSSARY.md new audit-action bullet. These are inventory/wording, no acceptance criterion changed.
