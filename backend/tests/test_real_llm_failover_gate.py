"""A-1 反造假闸：P0 承载例「不许藏 skip / 不许默认冒充跑过 / 矩阵不许无证据改 GREEN」。

出处 = Task 9 复审对 `docs/MODEL_ROUTER_V23_MATRIX.md` 承载闸的批评（原话大意）：
`MatrixDocumentClosureTests` 只按 **AST 核存在**——矩阵里写一枚 node-id，闸只回答「这个
文件里有这个类和方法吗」。于是给 P0 例挂上 `@unittest.skipUnless(有真机)` 之后，
文档说「P0 有承载例」、套件说「这例存在且没红」，而它**一次都没真跑过**。这是结构性漏洞，
不是文案问题。

本文件把三问钉成机器判据（三问的**顺序**就是造假路径的三层）：

① 源码面：P0 承载例的文件里**一枚 skip 家族令牌都不许有**——装饰器、属性、调用、
   **以及字符串常量**（`getattr(fn, "skipIf")`、`exec("@pytest.mark.skip")` 这两条后门
   就死在这里）。同时运行面要求 `__unittest_skip__` / `__expected_failure__` /
   `__test__ is False` 三者逐枚为假，并把 `getattr(fn, "__wrapped__", fn)` 的整条链
   逐跳拉出来重扫一遍（装饰器换个函数掉包也在这里红）。

② 收集面：那枚例的**唯一**门是 `REAL_LLM_ACCEPTANCE=1` 这一枚显式 env 开关，
   且默认关闭时它**不被收集**（不是 skipped）。两向都钉：
   关 ⇒ 子进程 `--collect-only` 收集数 **恰好 0**（「既不红也不冒充绿」这件事本身是断言），
   开 ⇒ 收集数 **恰好 1**（否则「永远不可能被跑」也是一种造假）。

③ 文档面：矩阵 P0 行的状态字段的合法取值**写死在本文件里**——
   没有成立的证据 ⇒ 只许 `BLOCKED`；证据成立 ⇒ 只许 `GREEN`。
   判据是 `real_llm_failover_kit.validate_evidence()`：十枚断言各带实测值、真外呼两次的
   模型名/字节数/耗时、primary 错误体里的服务端原文、临时库恰好一行且零 canary 命中、
   以及**逐枚重算的 sha1**。矩阵文案自己不算数。

③ 的**载体分层**（P0-EVIDENCE-PORTABILITY 3B，用户 2026-09-28 裁定 = 台账 R26 第 ③ 条）：
   上面那句「逐枚重算 sha1」重算的是原始件（sqlite / trace jsonl / 现场 probe）的**绝对路径**，
   而那三枚本体按裁定不入库（`.gitignore:25` 整目录挡住）⇒ 干净签出里永远算不出 ⇒ 这枚闸
   在任何 CI 形态下恒红（远端实测 run `36436145777`）。3A 已经把它换成**可移植载体**：
   `docs/evidence/model-router-v23/real-llm-failover-001/` 下六枚纯文本 JSON，每条 hash
   都能在干净签出重算。于是 ③ 现在分两层判：

   - **portable 层**（`kit.validate_portable_bundle`）：无条件必须过。七条 interlock +
     凡 bundle 载得出的 §6 逐条判据（`[C-*]`）全部仍是「必须」，一条没松。
   - **raw 层**（`kit.validate_evidence`，判据本体一字未改）：只在四枚原始件能按
     `manifest.source_run_dir` + `raw_provenance[].sha1` **双条件**定位到时才跑（在场才校验）。
     原始件不在场 = 干净签出的正常形态，**不构成红**；在场又对不上 = 红。
   - **`[T-*]` 真值层**（`kit.tracked_evidence_truth_problems`，3B 修复轮 1 的 H1/H2）：
     无条件必须过，读的就是**已跟踪的那枚原始证据 JSON**。管三件事——`rehearsal` 的真值、
     `completed is True`、`provider_transport` 这枚键**在场且为 null**（成员判定，不是 `.get()`，
     所以「缺键」不许冒充「null」）。这三条过去只长在 §6 里，而 §6 被条件成了「四枚运行态
     本体都在场才跑」⇒ 干净签出（= CI 的形态）里它们一次都没执行过；可它们判的是**这枚入库
     文本自己写着的事实**，与本体在不在场无关，所以没有任何理由跟着一起条件化。
   - **provenance/blob 半**（`kit.raw_layer_problems`，M1）：`full` 与 `json-only` **两条分支
     都跑**，逐枚重算，只有条目本身不在场才跳过该条目。过去它是全有或全无——「篡改一枚
     运行态件 + 缺席另一枚」会让整层静默不跑。其中唯一被 git 跟踪的 `acceptance_module`
     改按 **git blob 身份**验（导出记 `git hash-object`，判定比 `git rev-parse HEAD:<path>`，
     并再比一次当下工作树重算），不再比工作树字节的 sha1——后者随签出 EOL 形态变，
     是「同一份真话在两台机器上一真一假」的那种判据；blob 身份不变 ⇒ CI 第一次拿到一枚
     真重算得动的 raw 腿。

   换的是载体，不是验收事实：语义边界（R26 钉死）= portable 缺失/畸形/hash 不配 ⇒ 要求
   `BLOCKED`；portable 全过 + interlock 齐 ⇒ 允许 `GREEN`。原始件按 basename 或字节大小定位
   在这一层是被禁止的，因为 `task10/rehearsal/run/20260924-214030/` 里躺着同名、**同字节**、
   sha1 不同的彩排件（实测）；闸要的正面非彩排凭据是 bundle 里那枚写着 `null` 的
   `provider_transport`、`response.json` 的 `provider_transport_present`、以及
   `manifest.source_run_flags` 那五枚布尔位（键在场 / 值为 null / completed 为真 /
   rehearsal 不为真 / 那枚键在原始件里确实在场），**不是「读不到就算过」**。逐条映射表在
   `.superpowers/sdd/ENTERPRISE_B0_PLAN/p0-portability-3b-report.md`（§5 + `## 3B 修复轮 1`）。

闸自己也在判据内（`P0GateSelfIntegrityTests`）：本文件同样零 skip 令牌、自己的每枚类都
挂在矩阵上、并且它自己**必须**在默认套件里被收集到（否则这道闸可以靠「把自己也藏起来」过关）。
"""
from __future__ import annotations

import ast
import fnmatch
import inspect
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
MATRIX_DOC = BACKEND_DIR.parent / "docs" / "MODEL_ROUTER_V23_MATRIX.md"
for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import real_llm_failover_kit as kit                                    # noqa: E402

#: ① 的令牌集（**唯一出处**：装饰器面 / 属性面 / 字符串面三张扫都用它）。
SKIP_NAME_RE = re.compile(
    r"^(?:skip|skipIf|skipUnless|skipTest|skipMessage|expectedFailure|"
    r"_shouldSkip|pytestmark|__unittest_skip__|__unittest_skip_why__|"
    r"__unittest_expecting_failure__|__test__)$")
#: 出现在**字符串常量**里的这些字样同样可疑。刻意用**大小写不敏感的子串**而不是词边界：
#: `getattr(unittest, "skip" + "If")` 这种「把令牌拆成两段」的写法在词边界规则下能溜过去，
#: 子串规则下 `"skip"` 那一段就已经命中（`__qualname__` 必须在文件 AST 里对得上，
#: 见 `test_unwrapped_call_chain_is_clean_hop_by_hop`，是同一件事的另一半）。
SKIP_STRING_RE = re.compile(r"skip|xfail|__test__|expectedfailure", re.IGNORECASE)
#: 动态构造代码的入口：藏 skip 分支最省事的办法，本用例一律不许（零命中）。
FORBIDDEN_CALLS = frozenset({"exec", "eval", "compile", "__import__", "vars"})

#: ③ 的**唯一合法取值**（写死，不读文档、不读 env、不读证据里的自述）。
P0_STATUS_WITHOUT_EVIDENCE = "BLOCKED"
P0_STATUS_WITH_EVIDENCE = "GREEN"

#: ③ 的 portable 层外部锚：`docs/evidence/model-router-v23/real-llm-failover-001/manifest.json`
#: 的 **sha256**（由仓根锚定的 `kit.BUNDLE_DIR` 读盘现算，不按 cwd）。
#:
#: **为什么需要它**：manifest 是六枚里唯一「声明别人 hash」的那枚，一件东西给自己算 hash 是
#: 自指（3A《交回控制器的 findings 4》实测：`portable_files` 里刻意不含 manifest 自己）。
#: 少了外部锚，「改 bundle 不更 hash」这条造假路就只改 manifest 一处即可绕开——正是 R26
#: 点名要堵的那一格。
#:
#: **为什么取「钉进闸文件常量」而不是「落进 docs 规格」**（简报给了两枚候选，取一说明）：
#: 闸文件是**被执行、被 ① 源码面扫、被 B0 收集数钉**的代码面，改它是一处可见的 diff，
#: 评审看得见；而把锚落进 markdown 等于让「验收文档说啥算啥」重新长回来——那正是 R26
#: 第 ③ 条明令不许走的第二条出路。代价也要说平白：真机重跑一次就会换 manifest 的字节，
#: 于是必须同步更新这枚常数（runner 会打印新锚值；漏更 ⇒ `[I2]` 响亮地红，不是静默放过）。
#: 锚只钉 manifest，载荷五枚仍由 manifest 逐条声明 + 当场重算（两层互不遮蔽）。
#:
#: **3B 修复轮 1 的重钉（要大声说的一句）**：旧值 `68749a00e2e2…` 作废。那一轮为修
#: H1/H2/M1 三条，bundle 的**载体侧**多了字段（`response.json` 的
#: `provider_transport_present`、`manifest.source_run_flags` 五枚布尔位、
#: `raw_provenance[].repo_path` + `git_blob`），全部经 `kit.build_portable_bundle` /
#: `kit.write_portable_bundle` **重导**得到——没有手改任何一枚 bundle JSON。
#: manifest 换了字节 ⇒ 这枚锚必须同批改；漏更就是 `[I2]` 响亮地红，不是静默放过。
PORTABLE_MANIFEST_SHA256 = "c39a09f83b6abdab475cbf3527b2d92ba5459dbbaa55535c1f26b9f634308508"

#: ② 的子进程判定用度。
COLLECT_TIMEOUT_SECONDS = 180


# ==========================================================================
# 共享的 AST 扫描件
# ==========================================================================
def _docstring_constants(tree: ast.AST) -> set[int]:
    """模块 / 类 / 函数三层的 docstring 节点 id（它们**是文档**，不参与令牌扫描）。

    为什么可以放行：docstring 不会被执行，「闸不许 P0 例藏 skip」与「闸不许 P0 例的文档
    提到 skip 这个词」是两件事——后者会让这道闸无法把自己写清楚。字符串**常量**（会进
    `getattr` / `exec` 的那一类）不在放行范围内，见 `_skip_hits`。
    """
    out: set[int] = set()

    def first_string(node) -> None:
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            out.add(id(body[0].value))

    first_string(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first_string(node)
    return out


def _skip_hits(tree: ast.AST, *, scan_strings: bool = True) -> list[str]:
    """AST 面上所有 skip 家族命中点（装饰器 / 名字 / 属性 / 调用 / 非 docstring 字符串）。

    `scan_strings=False` 只给**闸自己的源码**用：那张令牌清单本身就是「含 skip 字样的字符串
    常量」，逐字符串扫它会自我命中。闸上换成下面那条 `getattr(…, "<skip 名>")` 的**精确**
    规则——后门照样红，清单照样能写。
    """
    docstrings = _docstring_constants(tree)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and SKIP_NAME_RE.match(node.id):
            hits.append(f"L{node.lineno}: name {node.id}")
        elif isinstance(node, ast.Attribute) and SKIP_NAME_RE.match(node.attr):
            hits.append(f"L{node.lineno}: attr .{node.attr}")
        elif isinstance(node, ast.FunctionDef) and SKIP_NAME_RE.match(node.name):
            hits.append(f"L{node.lineno}: def {node.name}")
        elif isinstance(node, ast.keyword) and SKIP_NAME_RE.match(node.arg or ""):
            hits.append(f"L{node.lineno}: kwarg {node.arg}")
        elif scan_strings and isinstance(node, ast.Constant) and id(node) not in docstrings:
            if isinstance(node.value, str) and SKIP_STRING_RE.search(node.value):
                hits.append(f"L{node.lineno}: 字符串常量 {node.value[:40]!r}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "id", None) if isinstance(func, ast.Name) else None
            attribute = getattr(func, "attr", None) if isinstance(func, ast.Attribute) else None
            if name in FORBIDDEN_CALLS:
                # 只算**裸调用**：`re.compile()` 是合法用法，`compile()` 才可以藏字节码。
                hits.append(f"L{node.lineno}: 动态代码入口 {name}()")
            if attribute == "class_eval" or name in {"globals", "locals"}:
                hits.append(f"L{node.lineno}: 动态改写运行时的 {attribute or name}")
            if name == "getattr" and len(node.args) >= 2 \
                    and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str) \
                    and SKIP_NAME_RE.match(node.args[1].value):
                hits.append(f"L{node.lineno}: getattr(…, {node.args[1].value!r})")
    return hits


def carrier_methods(tree: ast.AST) -> list[tuple[str, str]]:
    """P0 承载例 = 本文件里「类名含 Failover 且继承 TestCase」的 `test_*` 方法清单。"""
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [ast.unparse(b) for b in node.bases]
        if "Failover" not in node.name or not any(
                base.endswith("TestCase") or base.endswith("unittest.TestCase")
                for base in bases):
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and member.name.startswith("test_"):
                out.append((node.name, member.name))
    return out


def collect_only(env: dict[str, str], target: str) -> tuple[int, list[str], str]:
    """子进程 `pytest --collect-only -q`：返回 (退出码, node-id 清单, 原始输出)。

    刻意**不**在本进程内 `import` 那枚文件来「模拟收集」：pytest 的收集判定还看
    `__test__`、conftest 钩子与 `python_files` 匹配。判据要打在真收集器上。
    """
    command = [sys.executable, "-m", "pytest", target, "--collect-only", "-q",
               "-p", "no:cacheprovider"]
    completed = subprocess.run(command, cwd=str(BACKEND_DIR), env=env,
                               capture_output=True, text=True,
                               timeout=COLLECT_TIMEOUT_SECONDS)
    raw = completed.stdout + completed.stderr
    node_ids: list[str] = []
    for line in raw.splitlines():
        text = line.strip().replace("\\", "/")
        if "::" in text and text.startswith("tests/"):
            node_ids.append(text)
    return completed.returncode, node_ids, raw


def load_acceptance_module(*, enabled: bool):
    """按开关把那枚文件 import 进来（**不跑任何用例**），返回模块对象。

    开关为假时文件末尾会把类 `del` 掉 ⇒ 拿不到类正是②要的事实。
    """
    environ = dict(os.environ)
    if enabled:
        environ[kit.ENV_SWITCH] = kit.SWITCH_ON
    else:
        environ.pop(kit.ENV_SWITCH, None)
    with mock.patch.dict(os.environ, environ, clear=True):
        sys.modules.pop(kit.ACCEPTANCE_FILE.stem, None)
        import importlib
        return importlib.import_module(kit.ACCEPTANCE_FILE.stem)


#: ①运行面上要逐枚探开的属性名。**清单是一枚常量元组**而不是 `getattr(obj, "<字面量>")`：
#: 后者会被本文件自己的「getattr 藏 skip 名」规则命中（探测器不能长得像藏身处，否则
#: `P0GateSelfIntegrityTests` 只能靠给闸开后门来放行自己——那正是本次要堵的那类洞）。
RUNTIME_SKIP_ATTRS: tuple[str, ...] = (
    "__unittest_skip__", "__unittest_expecting_failure__", "__expected_failure__")
RUNTIME_TEST_FLAG = "__test__"


def runtime_skip_attributes(obj) -> list[str]:
    """运行面上的 skip 痕迹（①的运行面对象：类与方法都过一遍）。"""
    found = [name for name in RUNTIME_SKIP_ATTRS if getattr(obj, name, False)]
    if getattr(obj, RUNTIME_TEST_FLAG, True) is False:
        found.append(RUNTIME_TEST_FLAG + " is False")
    return found


def unwrap_chain(fn):
    """`getattr(fn, "__wrapped__", fn)` 的**整条**链（一跳一元素，含自身）。"""
    seen = []
    current = fn
    while current is not None and len(seen) < 10:
        seen.append(current)
        current = getattr(current, "__wrapped__", None)
    return seen


# ==========================================================================
# ① 源码面 + 运行面：不许藏 skip / expectedFailure
# ==========================================================================
class P0CarrierHasNoSkipBranchTests(unittest.TestCase):
    """闸①：P0 承载例的源码面与运行面**都**零 skip 痕迹。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = kit.ACCEPTANCE_FILE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)
        cls.methods = carrier_methods(cls.tree)

    def test_the_carrier_exists_and_is_exactly_one(self):
        """先把「承载例是谁」钉死：恰好一枚 `test_*` 方法，文件也必须在场。

        这枚是①②③的地基——没有确定的承载例，「零 skip」可以靠**把例删掉**来成立。
        """
        self.assertTrue(kit.ACCEPTANCE_FILE.is_file(), f"缺 {kit.ACCEPTANCE_FILE}")
        self.assertEqual(1, len(self.methods),
                         f"P0 承载例应恰好一枚 test 方法，实得 {self.methods}")
        class_name, method_name = self.methods[0]
        self.assertTrue(method_name.startswith("test_real_llm_failover_001"),
                        f"承载例方法名要能对上 §10 的 P0 行：{method_name}")
        self.assertIn("RealLlmFailover001", class_name)

    def test_carrier_source_has_zero_skip_family_tokens(self):
        hits = _skip_hits(self.tree)
        self.assertEqual([], hits,
                         "P0 承载例的**代码面**出现 skip 家族令牌（装饰器/属性/字符串/"
                         "exec 全算）——Task 9 复审点名的『skipUnless 也能过关』从此不能再走")

    def test_carrier_class_and_method_carry_no_runtime_skip_marks(self):
        module = load_acceptance_module(enabled=True)
        class_name, method_name = carrier_methods(self.tree)[0]
        klass = getattr(module, class_name, None)
        self.assertIsNotNone(klass,
                             f"开关打开后 {class_name} 却不在模块命名空间里 ⇒ 收集门不止一枚")
        offenders = runtime_skip_attributes(klass)
        method = getattr(klass, method_name)
        offenders += runtime_skip_attributes(method)
        self.assertEqual([], offenders, f"运行面上的 skip/expectedFailure 痕迹：{offenders}")
        self.assertTrue(callable(method))

    def test_unwrapped_call_chain_is_clean_hop_by_hop(self):
        """`getattr(fn, "__wrapped__", fn)` 也不许藏 skip 分支：**逐跳**重扫源码。

        造假形态：`def _gate(fn): @unittest.skipUnless(...) ... ; return wrapper`，再把
        `wrapper.__wrapped__ = fn`。这条链上每一跳的函数体都单独过一遍令牌扫描，
        并要求最后一跳的 `__qualname__` 能在文件 AST 里找到（防「另起一枚文件外的函数」）。
        """
        module = load_acceptance_module(enabled=True)
        class_name, method_name = carrier_methods(self.tree)[0]
        method = getattr(getattr(module, class_name), method_name)
        chain = unwrap_chain(method)
        self.assertGreaterEqual(len(chain), 1)
        known_functions = {f"{node.name}" for node in ast.walk(self.tree)
                           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for hop in chain:
            with self.subTest(qualname=getattr(hop, "__qualname__", repr(hop))):
                # 每一跳都必须**定义在这枚文件里**：`functools.wraps` 会把 `__qualname__`
                # 冒充成原方法（M4 变异实测），只看名字会被骗过去，`co_filename` 骗不过去。
                self.assertEqual(
                    kit.ACCEPTANCE_FILE.name, Path(hop.__code__.co_filename).name,
                    f"链上有一枚函数不来自 {kit.ACCEPTANCE_FILE.name}：那是掉包")
                source = inspect.getsource(hop)
                self.assertEqual([], _skip_hits(ast.parse(_dedent(source))),
                                 "wrapped 链上的某一跳里藏了 skip 分支")
                tail = hop.__qualname__.rsplit(".", 1)[-1]
                self.assertIn(tail, known_functions,
                              "承载例被换成了本文件 AST 里不存在的一枚函数（掉包）")

    def test_the_evidence_collector_kit_is_clean_too(self):
        """证据采集器（`real_llm_failover_kit.py`）也在①的射程内：它一句 skip 都不该有。

        理由：采集器被用例与闸**同时**信任，它可以决定「什么算证据成立」。
        那里藏一枚 skip 分支 = 把闸①与闸③同时买通。
        """
        tree = ast.parse(Path(kit.__file__).read_text(encoding="utf-8"))
        self.assertEqual([], _skip_hits(tree))


def _dedent(source: str) -> str:
    import textwrap

    return textwrap.dedent(source)


# ==========================================================================
# ② 收集面：唯一的 env 门 + 默认不被收集
# ==========================================================================
class P0CollectionGateTests(unittest.TestCase):
    """闸②：门只有 `REAL_LLM_ACCEPTANCE=1`，且**关闭时收集数为 0**（不是 skipped）。"""

    def test_the_gate_is_exactly_one_env_switch(self):
        tree = ast.parse(kit.ACCEPTANCE_FILE.read_text(encoding="utf-8"))
        last = tree.body[-1]
        self.assertIsInstance(last, ast.If,
                              "收集门必须是模块末尾的一枚 if（不是装饰器、不是 fixture）")
        self.assertEqual([], last.orelse, "收集门不许有 else 分支（那条路上还能长第二枚门）")
        test = last.test
        self.assertIsInstance(test, ast.UnaryOp)
        self.assertIsInstance(test.op, ast.Not)
        call = test.operand
        self.assertIsInstance(call, ast.Call)
        self.assertEqual("acceptance_enabled",
                         getattr(call.func, "attr", getattr(call.func, "id", "")),
                         "收集门必须走 kit.acceptance_enabled()，别处解析开关 = 两处口径")
        self.assertEqual([], call.args, "开关判定不接受任何额外参数（不接受『第二个条件』）")
        deleted = [ast.unparse(target) for node in last.body
                   if isinstance(node, ast.Delete) for target in node.targets]
        self.assertEqual([carrier_methods(tree)[0][0]], deleted,
                         "关闭时唯一的动作是把承载类从命名空间摘掉（收集 0 枚）")

    def test_acceptance_enabled_reads_one_env_name_only(self):
        self.assertEqual("REAL_LLM_ACCEPTANCE", kit.ENV_SWITCH,
                         "开关名改口 = 文档/runner/闸三方对不上，必须先过这枚断言")
        self.assertEqual("1", kit.SWITCH_ON, "开关取值必须是显式的 1")
        source = inspect.getsource(kit.acceptance_enabled)
        reads = re.findall(r"(?:getenv|(?:\(|\.|\b)(?:source|os\.environ|environ)\.get)\(\s*"
                           r"([A-Za-z_][A-Za-z0-9_]*)", source)
        self.assertEqual(["ENV_SWITCH"], reads,
                         f"acceptance_enabled 读了不止一枚 env：{reads}")
        self.assertIn("if", source)
        self.assertNotIn("importlib", source)

    def test_collected_zero_when_off_and_one_when_on(self):
        """双向收集判据：关 ⇒ **恰好 0**；开 ⇒ **恰好 1**。"""
        base_env = dict(os.environ)
        off_env = {key: value for key, value in base_env.items()
                   if key != kit.ENV_SWITCH}
        on_env = dict(base_env, **{kit.ENV_SWITCH: kit.SWITCH_ON})
        target = str(Path("tests") / kit.ACCEPTANCE_FILE.name)

        code_off, ids_off, raw_off = collect_only(off_env, target)
        with self.subTest(direction="默认关闭"):
            self.assertEqual([], ids_off,
                             f"默认套件收集到了 P0 例（应当 0 枚）：{ids_off}\n{raw_off[-400:]}")
            self.assertNotIn("skipped", raw_off.lower(),
                             "收集阶段冒出 skipped ⇒ 有人把『不收集』改回了『skip 掉』")
            self.assertIn(code_off, (0, 5), f"退出码异常：{code_off}\n{raw_off[-400:]}")

        code_on, ids_on, raw_on = collect_only(on_env, target)
        with self.subTest(direction="开关打开"):
            self.assertEqual(1, len(ids_on),
                             f"开了开关却收集到 {len(ids_on)} 枚：{ids_on}\n{raw_on[-400:]}")
            self.assertIn("RealLlmFailover001Tests::test_real_llm_failover_001", ids_on[0])
            self.assertEqual(0, code_on)
            self.assertNotIn("skipped", raw_on.lower())

    def test_no_other_test_file_hides_a_carrier_from_collection(self):
        """全仓唯二的「把类从命名空间摘掉」语法只许出现在 P0 承载例那一处。

        为什么不是「跑一次全仓 `--collect-only`」：那枚子进程要 25 秒，而它抓的造假面
        （换文件名/换目录再混一枚默认可收集的 P0）用 AST 就能当场抓住——收集门长成的
        形状就是「模块末尾一枚条件 `del`」。这一枚还顺住另一头的歪：把同一招用到
        别的用例上给自己开后门。
        """
        offenders: list[str] = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            if path.name == kit.ACCEPTANCE_FILE.name:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:                       # 只看模块顶层
                if isinstance(node, ast.If) and any(
                        isinstance(child, ast.Delete) for child in node.body):
                    offenders.append(f"{path.name}: 顶层条件性 del")
                if isinstance(node, ast.Delete):
                    offenders.append(f"{path.name}: 顶层 del {ast.unparse(node)}")
        self.assertEqual([], offenders,
                         "别的测试文件在收集阶段摘自己的类 ⇒ 收集门长在了不该长的地方")


# ==========================================================================
# ③ 文档面：矩阵 P0 行状态与执行证据互锁
# ==========================================================================
REPO_ROOT = BACKEND_DIR.parent

#: 仓库的忽略规则——**只服务于失败文案**（R15 裁定：判据不读它；3B 之后判的仍是
#: `kit.p0_evidence_verdict()` = portable 层（§8）+ raw 层（§6 `validate_evidence()`，
#: 判据本体一字未动）那一条，一个字没松）。
GITIGNORE_FILE = REPO_ROOT / ".gitignore"


def _ignored_face_hint(path: Path) -> str:
    """这枚文件被 `.gitignore` 的**哪一条**挡在交付面外（红的时候才现算）。

    为什么现算而不写死一句"它被 .gitignore 挡着"：这段话唯一的用途是让第一现场读得懂，
    规则哪天改了，写死的那句就变成第二条误导。为什么在这里不派 `git check-ignore` 子进程：
    断言的 msg 是**先算好再交给 assertEqual** 的，这里冒出一个异常会把「红」变成「error」，
    现场比现在更难读。匹配只按 `.gitignore` 的字面形状做两件事：目录规则看路径分量、
    文件规则看整体与文件名——命中不了就如实说"未被命中"。
    """
    try:
        rel = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return f"（{path} 不在仓库内 ⇒ 谈不上被仓库的忽略规则挡住）"
    try:
        lines = GITIGNORE_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return f"（读不到 {GITIGNORE_FILE.name}：{exc}）"
    for number, pattern in enumerate(lines, start=1):
        rule = pattern.strip()
        if not rule or rule.startswith("#"):
            continue
        bare = rule.rstrip("/").lstrip("/")
        if rule.endswith("/") and bare and bare in rel.split("/")[:-1]:
            return f"命中 `{GITIGNORE_FILE.name}:{number}` 的 `{rule}`——整目录不进交付面"
        if not rule.endswith("/") and (
                fnmatch.fnmatch(rel, bare) or fnmatch.fnmatch(Path(rel).name, bare)):
            return f"命中 `{GITIGNORE_FILE.name}:{number}` 的 `{rule}`"
    return f"未被 `{GITIGNORE_FILE.name}` 命中（那它本就该随仓库一起交付）"


def _evidence_absence_note(read_error: str | None) -> str:
    """证据件**不在场**时，把「缺的是哪一枚、为什么不在、该动哪一面」说全。

    这一段的动机是 B0 Task 5 容器格的第一现场：那三枚红里这一枚最误导人——判据给出的是
    `'BLOCKED' != 'GREEN'`，等号左边是闸要求的值、右边是矩阵写的值，读者的第一反应是"去把矩阵
    改回 BLOCKED"。而那恰好是本文件最不肯看到的动作：矩阵写着 GREEN 是 V2.3 那次真机跑的**真实
    结论**（`kit.validate_evidence` 的十枚判据 + 逐枚重算 sha1 就是为它作的保），把它改成
    BLOCKED 等于伪造一次结论。真正不在场的东西是**证据件本身**——它落在 `.superpowers/` 下、
    被仓库的忽略规则整目录挡在交付面外，于是任何干净 checkout（CI runner / 发布容器）里这一枚
    都**不可判**。不可判 ≠ 已通过，所以本枚照旧红（R15：判据一分不松），只是要说清红在哪。
    """
    if read_error != "missing":
        return ""
    rel = kit.EVIDENCE_FILE
    try:
        rel = kit.EVIDENCE_FILE.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        pass
    return (
        "\n\n—— 这一格缺的不是矩阵那一行，是那枚没进交付面的过程件 ——"
        f"\n- 证据件路径：{kit.EVIDENCE_FILE}（仓库相对 `{rel}`）"
        f"\n- 本轮读取结果：{read_error!r} —— 文件根本不在场（不是内容不合格）。"
        f"\n- 它{_ignored_face_hint(kit.EVIDENCE_FILE)}；"
        "⇒ 干净 checkout（CI / 发布容器）里它**必然**不在场，本机才在场。"
        "\n- 所以本行在干净 checkout 里是**不可判**，而不可判 ≠ 已通过：判据照旧要求 "
        f"{P0_STATUS_WITHOUT_EVIDENCE!r}，本枚照旧红。"
        "\n- 出路不是改矩阵（把 GREEN 写成 BLOCKED 等于伪造 V2.3 的真实结论），"
        "而是让证据上交付面：把上面那枚 JSON 以 `git add -f` 精选入库"
        "（B0 计划 Task 7 的 staging 段已登记，需用户明确授权后才能提交）。"
        "\n- 【订正 3B】上面那条『git add -f 原始件』的出路已被用户 2026-09-28 裁定（台账 R26 ③）"
        "**作废**：不批准把 `.db` + trace 原件整体入库。交付面改成了**可移植文本载体** "
        "`docs/evidence/model-router-v23/real-llm-failover-001/`，raw 本体继续 ignored；"
        "于是本枚的红因只由上面那份 [I*]/[C-*]/[X] 问题清单决定——原始件不在场是干净签出的"
        "**正常形态**（raw 层按裁定不参与），它自己不再构成红。"
        "\n- 想要本机复算这份证据：跑 .superpowers/scripts/run_p0_failover_acceptance.sh。"
    )


def _problem_list_block(problems: list[str], limit: int = 40) -> str:
    """把问题清单排成一列（判据本身不受影响，只是让第一现场一眼看完不是只看第一条）。"""
    head = "\n".join(f"  · {item}" for item in problems[:limit])
    if len(problems) > limit:
        head += f"\n  ·（另有 {len(problems) - limit} 条同类，见 kit 的 " \
                "[I*]/[C-*]/[T-*]/[X] 标签）"
    return head + "\n"


def _verdict_branch_line(verdict: dict) -> str:
    """**走了哪一层**的公告行——3B 的验收要求「raw 层校验确实执行了」必须能被打印出来。

    为什么用 print 而不是只写在断言消息里：绿的时候没有断言消息可读，而『本机跑的是 full 分支、
    干净签出跑的是 json-only/absent 分支』这件事本身就是判据的一部分（不然分层可以静默降级）。

    3B 修复轮 1 起这行还打印两件事，因为它们都是「分层有没有偷偷降级」的第一现场：
    - `[T-*]` 那一层的条数（H1/H2：三枚真值判据在**任何**分支都执行，包括干净签出）；
    - `acceptance_module` 的 **git blob 腿**实测值（M1：唯一被跟踪的那枚 raw 目标，
      在 `json-only` 里也真的重算了一次——记录值 / HEAD blob / 工作树重算三枚并排打出来，
      不相等就直接进问题清单，不在这个字符串里藏结论）。
    """
    files = verdict.get("resolved_raw") or []
    located = ", ".join(f"{item['role']}={'在场' if item['present'] else '缺席'}"
                        for item in files) or "（manifest 不在场 ⇒ 无 provenance 可定位）"
    blob_rows = [item for item in files if item.get("role") == "acceptance_module"]
    blob = blob_rows[0] if blob_rows else {}
    blob_line = (f"blob 记录={blob.get('git_blob_recorded')} "
                 f"HEAD={blob.get('git_blob_head')} "
                 f"工作树重算={blob.get('git_blob_worktree')} "
                 f"一致={blob.get('matches_blob')}")
    return (f"[P0 闸③ 分支] portable 层：{len(verdict['portable_problems'])} 条问题"
            f"（bundle 目录 {verdict['bundle_dir']}，读包结果 {verdict['bundle_read_error']}）"
            f" | [T-*] 真值层：{len(verdict.get('truth_problems') or [])} 条（无条件执行）"
            f" | raw 层状态 = {verdict['raw_state']}"
            f"（full = §6 validate_evidence() 实跑；json-only = provenance/blob 腿 + 面对面核对，"
            f"§6 因本体不入库而不跑；absent = 证据 JSON 自己不在场，[T-*] 直接响）"
            f" | raw 问题 {len(verdict['raw_problems'])} 条"
            f" | 原始件双条件定位：{located}"
            f" | acceptance_module 的 git blob 腿：{blob_line}")


def _portable_failure_note(verdict: dict) -> str:
    """portable 层红的时候，把「缺的是载体还是事实、该动哪一面」说全（只服务于失败文案）。

    与 `_evidence_absence_note` 的分工：那一枚说原始件（本体不入库、干净签出必然不可判），
    这一枚说 bundle 载体本身。两者都不改判据，只是别让下一个人在『去把矩阵改回 BLOCKED』
    这条错路上花时间——那是本文件最不肯看到的动作。
    """
    lines = [
        "\n\n—— portable 层（3B 之后 P0 的唯一 CI 判据载体）——",
        f"- bundle 目录：{verdict['bundle_dir']}",
        f"- 读包结果：{verdict['bundle_read_error']!r}"
        "（'missing' = 六枚一枚都没读到；其余 = 读到了但某几枚不成立）",
        f"- 外部锚（闸文件常量 PORTABLE_MANIFEST_SHA256）期望 manifest 的 sha256 = "
        f"{PORTABLE_MANIFEST_SHA256}",
        f"- raw 层分支 = {verdict['raw_state']} ⇒ 原始件不在场**不是**这一格红的原因；"
        "红的原因只在上面那条问题清单里",
        "- 出路按问题标签分诊：[I1] 缺件 / [I2] hash 不配 ⇒ 重跑 runner 重导 bundle"
        "（`.superpowers/scripts/run_p0_failover_acceptance.sh` 的 [4/4] 会调 "
        "`kit.write_portable_bundle`）；[I3]–[I7] ⇒ 那次运行本身不成立，只能重跑真机；"
        "锚对不上 ⇒ 同一批里把闸文件常数与 bundle 一起改（可见的代码改动），"
        "**不是**把矩阵改成 BLOCKED 来消红。",
    ]
    return "\n".join(lines)


class P0MatrixStatusLockedToEvidenceTests(unittest.TestCase):
    """闸③：没跑过真机 ⇒ 矩阵 P0 行只许 `BLOCKED`；跑过 ⇒ 只许 `GREEN` 且证据成立。

    3B 起这条判定分两层取数（module docstring 的『③ 的载体分层』那一节就是判据本体的一部分）：
    portable 层无条件必须过，raw 层只在原始件按 `source_run_dir` + sha1 双条件定位得到时跑。
    """

    def test_the_two_legal_values_are_pinned_in_the_gate(self):
        """合法取值写在**闸里**这一事实本身也要能被看见（防止有人改常量而不是改判定）。"""
        self.assertEqual(("BLOCKED", "GREEN"),
                         (P0_STATUS_WITHOUT_EVIDENCE, P0_STATUS_WITH_EVIDENCE))
        source = kit.MATRIX_DOC.read_text(encoding="utf-8")
        self.assertIn("状态值域只有", source, "矩阵的三值域说明被删了？")
        self.assertIn("GREEN / PENDING_EXTERNAL / BLOCKED", source,
                      "状态值域的那一行字变了：闸③的合法取值要同步改，不能各说各话")

    def test_p0_row_status_matches_the_evidence(self):
        status = kit.matrix_p0_status()
        self.assertIsNotNone(status, "矩阵里没有 P0 行了（§10 的『+1』被删）")
        verdict = kit.p0_evidence_verdict(manifest_sha256_pin=PORTABLE_MANIFEST_SHA256)
        problems = verdict["problems"]
        print(_verdict_branch_line(verdict))
        if problems:
            self.assertEqual(
                P0_STATUS_WITHOUT_EVIDENCE, status,
                f"P0 的证据不成立（{len(problems)} 条问题，逐条点名见下），矩阵那一行却写着 "
                f"{status!r}。唯一合法取值是 {P0_STATUS_WITHOUT_EVIDENCE!r}——"
                "改状态之前请先跑 .superpowers/scripts/run_p0_failover_acceptance.sh"
                "（它会在 sha1 回打之后重新导出 bundle）\n"
                + _problem_list_block(problems)
                + _portable_failure_note(verdict)
                + _evidence_absence_note(verdict["raw_evidence_error"]))
            return
        self.assertEqual(
            P0_STATUS_WITH_EVIDENCE, status,
            f"证据已经成立（portable 七条 interlock + 搬过来的逐条判据 + raw 层"
            f"{'实跑' if verdict['raw_state'] == 'full' else '不在场，按裁定不参与'}，"
            f"见上面打印的分支），矩阵还写着 {status!r}："
            "要么把 P0 行改成 GREEN，要么说明这份证据不该存在")

    def test_the_evidence_judgment_does_not_degrade(self):
        """判据自身的变异探针：每缺一枚关键事实，判据必须**点名**它（raw 层 + portable 层各一批）。

        为什么单独钉这一枚（Task 9 复审的教训形状）：闸③读的是采集器的判据，判据退化成
        「数一数有没有 10 条」时，本文件一切照常绿。四枚变异各打一枪，打的就是
        「模型序 / 服务端错误体 / 账本行数 / 落盘指纹」这四枚最容易被糊弄的位。

        3B 追加 portable 层那一批（同一枚 node-id，**不新增用例**，免得动 B0 的收集数钉）：
        分层之后最怕的就是「portable 层是一枚摆设」，所以七条 interlock 与搬过来的 `[C-*]`
        逐条都要有一发「改它 ⇒ 它自己点名」的枪。每发先验 baseline 不含该标签，
        再验改后必含 ⇒ 杀掉它的确实是这一枚判据，不是别处顺带红。
        """
        base = _valid_looking_evidence()
        mutations = [
            ("外呼模型序被换（primary 直接给 phi3）",
             lambda e: e.__setitem__("provider_calls",
                                     [e["provider_calls"][1], e["provider_calls"][0]]),
             "外呼模型序"),
            ("错误体换成了不含加载特征的文字",
             lambda e: e["provider_calls"][0].__setitem__(
                 "error_body_excerpt", "upstream temporarily unavailable, please retry"),
             "不含 §6 的加载失败特征"),
            ("账本写成两行",
             lambda e: e["ledger"].__setitem__("rows", 2),
             "临时库行数"),
            ("sha1 表里写一枚对不上的摘要",
             lambda e: e.__setitem__("files_sha1", {str(kit.PROBE_FILE): "0" * 40}),
             "sha1 对不上"),
        ]
        for label, mutate, expected in mutations:
            with self.subTest(mutation=label):
                candidate = json.loads(json.dumps(base, ensure_ascii=False))
                mutate(candidate)
                problems = kit.validate_evidence(candidate)
                self.assertTrue(any(expected in problem for problem in problems),
                                f"该判据没红（退化）：{expected} ⇒ {problems}")

        baseline = _portable_payload_copy()
        self.assertIsNotNone(baseline, "portable 层探针取不到 bundle：分层判据无从验证")
        base_problems = kit.validate_portable_bundle(
            baseline, manifest_sha256_pin=PORTABLE_MANIFEST_SHA256)
        for label, mutate, expected in _portable_mutations():
            with self.subTest(portable_mutation=label):
                candidate = _portable_payload_copy()
                self.assertFalse(any(expected in problem for problem in base_problems),
                                 f"baseline 已经带着 {expected}：bundle 本身就不成立，"
                                 "这发探针证明不了任何事（先看闸③那一枚的红因清单）")
                mutate(candidate)
                problems = kit.validate_portable_bundle(
                    candidate, manifest_sha256_pin=PORTABLE_MANIFEST_SHA256)
                self.assertTrue(any(expected in problem for problem in problems),
                                f"portable 层判据没红（退化）：{expected} ⇒ {problems}")


def _portable_payload_copy() -> dict | None:
    """从盘上读一份**全新的** bundle 并深拷贝（探针改的是内存副本，绝不落盘）。

    为什么不落盘：`docs/evidence/` 是 P0 的交付面，证伪只能在**副本**上做（原地证伪由
    `p0-portability-3b-mutations.py` 那枚字节安全台另跑一遍，每发 `finally` 原字节还原）。
    """
    payload, _error = kit.read_portable_bundle()
    if payload is None:
        return None
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _drop_portable_file(payload: dict, name: str) -> None:
    """内存里把某枚件变成「不在场」。"""
    payload["files"][name] = {"path": payload["files"][name]["path"], "present": False,
                              "bytes": None, "sha256": "<missing>", "data": None,
                              "parse_error": None}


def _edit_portable(payload: dict, name: str, mutate, restamp: bool = True) -> None:
    """改某枚件的 dict 内容，再按 §7 的序列化口径重算它的 text/bytes/sha256。

    `restamp=True` 会把 manifest 的 `portable_files` 声明跟着改（**故意**让 `[I2]` 那一关先过）：
    只有喂平了 hash，杀掉这一发的才可能是语义判据本身。`restamp=False` 就是简报点名的
    那枚造假：「改 portable 件但不更 manifest hash」。
    """
    entry = payload["files"][name]
    mutate(entry["data"])
    kit.dump_portable_payload(payload, name)
    if restamp:
        kit.restamp_portable_manifest(payload)


def _edit_manifest(payload: dict, mutate) -> None:
    """改 manifest 的内容并重算它自己的 sha256（外部锚那一关会另外响，互不遮蔽）。"""
    mutate(payload["files"][kit.BUNDLE_MANIFEST_FILE]["data"])
    kit.dump_portable_payload(payload, kit.BUNDLE_MANIFEST_FILE)


def _manifest_provenance(manifest: dict, role: str) -> dict:
    """取 manifest.raw_provenance 里指定 role 的那一枚条目（只给下面的探针用）。"""
    for item in manifest.get("raw_provenance") or []:
        if isinstance(item, dict) and item.get("role") == role:
            return item
    raise AssertionError(f"raw_provenance 里没有 role={role} 的条目")


def _portable_mutations() -> list[tuple[str, object, str]]:
    """portable 层的逐枚探针：`(说明, 改法, 期望被点名的标签)`，七条 interlock 全覆盖。

    标签出处见 `real_llm_failover_kit` §8；期望的是**那一条**判据自己响，不是随便有条问题。
    """
    rehearsal_dir = (kit.EVIDENCE_DIR.relative_to(kit.REPO_ROOT).as_posix()
                     + "/rehearsal/run/20260924-214030")
    return [
        ("删掉一枚 portable 件（ledger-row.json）",
         lambda p: _drop_portable_file(p, kit.BUNDLE_LEDGER_ROW_FILE), "[I1] bundle 件缺失"),
        ("改 portable 件但不更 manifest hash",
         lambda p: _edit_portable(p, kit.BUNDLE_RESPONSE_FILE,
                                  lambda d: d["answer"].__setitem__("text", "x" * 40),
                                  restamp=False),
         "[I2] sha256 不配"),
        ("manifest 自己被改而闸的锚没更（外部锚那半条）",
         lambda p: _edit_manifest(p, lambda m: m.__setitem__("trace_id", "p0-tampered")),
         "闸里的外部锚"),
        ("改 response 的 model_used（answer.model → primary 的名字）",
         lambda p: _edit_portable(p, kit.BUNDLE_RESPONSE_FILE,
                                  lambda d: d["answer"].__setitem__("model",
                                                                    kit.PRIMARY_MODEL)),
         "[I3]"),
        ("改 ledger.row.model（phi3 → 陌生模型）",
         lambda p: _edit_portable(p, kit.BUNDLE_LEDGER_ROW_FILE,
                                  lambda d: d["row"].__setitem__("model", "qwen:7b")),
         "[I3]"),
        ("改成功那枚 trace attempt 的 model",
         lambda p: _edit_portable(p, kit.BUNDLE_TRACE_FILE,
                                  lambda d: d["model_route_attempts"][1].__setitem__(
                                      "model", kit.PRIMARY_MODEL)),
         "[I3]"),
        ("改 planned primary（manifest.plan.primary_model）",
         lambda p: _edit_manifest(p, lambda m: m["plan"].__setitem__("primary_model",
                                                                     "llama3:latest")),
         "[I4]"),
        ("probe 原文换成非文档化的失败（去掉 alloc 那一族字面）",
         lambda p: _edit_portable(p, kit.BUNDLE_PROBE_FILE,
                                  lambda d: (d["probe"].__setitem__(
                                      "raw_error_body",
                                      "{\"error\":\"model is busy with another request\"}"),
                                      d["probe"]["classification"].__setitem__(
                                          "message", "模型忙：another request"))),
         "[I5]"),
        ("trace_id 三处里改一处（ledger-row 顶层）",
         lambda p: _edit_portable(p, kit.BUNDLE_LEDGER_ROW_FILE,
                                  lambda d: d.__setitem__("trace_id", "p0-failover-deadbeef")),
         "[I6]"),
        ("bundle 的来源指向彩排 run dir（反彩排那一发）",
         lambda p: _edit_manifest(p, lambda m: m.__setitem__("source_run_dir", rehearsal_dir)),
         "指向彩排目录"),
        ("raw_provenance 的当场重算与记录值不等（洗出来的 bundle）",
         lambda p: _edit_manifest(p, lambda m: m["raw_provenance"][0].__setitem__(
             "sha1", "0" * 40)), "[I7] "),
        ("provider_transport 从 null 换成替身字样",
         lambda p: _edit_portable(p, kit.BUNDLE_RESPONSE_FILE,
                                  lambda d: d.__setitem__("provider_transport",
                                                          "httpx.MockTransport")),
         "[C-传输层]"),
        ("账本行冒出禁存列 prompt",
         lambda p: _edit_portable(p, kit.BUNDLE_LEDGER_ROW_FILE,
                                  lambda d: d["row"].__setitem__("prompt", "x")),
         "[C-禁存列]"),
        ("一枚断言的 pass 改成 false",
         lambda p: _edit_portable(p, kit.BUNDLE_RESULT_FILE,
                                  lambda d: d["assertions"][0].__setitem__("pass", False)),
         "[C-断言全过]"),
        # ---- 3B 修复轮 1 新增：H1 / H2 / M1 / M2 四条加强判据各有一发「改它 ⇒ 它自己点名」 ----
        ("manifest.source_run_flags.completed_is_true 改成 false（H1 载体侧）",
         lambda p: _edit_manifest(p, lambda m: m["source_run_flags"].__setitem__(
             "completed_is_true", False)),
         "[I7] source_run_flags.completed_is_true"),
        ("manifest.source_run_flags.rehearsal_truthy 改成 true（H1 反彩排载体侧）",
         lambda p: _edit_manifest(p, lambda m: m["source_run_flags"].__setitem__(
             "rehearsal_truthy", True)),
         "[I7] source_run_flags.rehearsal_truthy"),
        ("manifest.source_run_flags.provider_transport_key_present 改成 false（H2 载体侧）",
         lambda p: _edit_manifest(p, lambda m: m["source_run_flags"].__setitem__(
             "provider_transport_key_present", False)),
         "[I7] source_run_flags.provider_transport_key_present"),
        ("response.json 的 provider_transport_present 改成 false（H2 源端成员判定）",
         lambda p: _edit_portable(p, kit.BUNDLE_RESPONSE_FILE,
                                  lambda d: d.__setitem__("provider_transport_present", False)),
         "[C-传输层] response.json 的 provider_transport_present"),
        ("trace_id_source.pointers 里一枚改成 null（M2：少一条腿不许算一致）",
         lambda p: _edit_manifest(p, lambda m: m["trace_id_source"]["pointers"].__setitem__(
             "request.trace_id", None)),
         "[I6] trace_id_source.pointers 里有指针为 null"),
        ("trace_id_source.pointers 摘掉一枚键（M2 的另一头：键集合不是那三枚）",
         lambda p: _edit_manifest(p, lambda m: m["trace_id_source"]["pointers"].pop(
             "ledger.row.trace_id")),
         "[I6] trace_id_source.pointers 的键名不是那三枚"),
        ("raw_provenance 的 git_blob 写成不合规形状（M1 blob 腿的载体侧）",
         lambda p: _edit_manifest(p, lambda m: _manifest_provenance(
             m, "acceptance_module").__setitem__("git_blob", "deadbeef")),
         "[I7] acceptance_module 的 git_blob 不是 40 位十六进制"),
        ("raw_provenance 的 repo_path 退化成 basename（M1：判据不许变回单机耦合）",
         lambda p: _edit_manifest(p, lambda m: _manifest_provenance(
             m, "acceptance_module").__setitem__("repo_path",
                                                 "test_real_llm_failover_acceptance.py")),
         "[I7] acceptance_module 的 repo_path 应为仓相对"),
        ("provider_calls 的模型序被对调",
         lambda p: _edit_portable(p, kit.BUNDLE_RESPONSE_FILE,
                                  lambda d: d.__setitem__(
                                      "provider_calls",
                                      [d["provider_calls"][1], d["provider_calls"][0]])),
         "[C-模型序]"),
    ]


def _valid_looking_evidence() -> dict:
    """一枚「形状齐全」的证据骨架，只给判据变异探针用（**不是**可放行的证据）。

    `files_sha1` 里放的是探针件的**真**摘要，所以除被 mutate 的那一枚之外不再报 sha1 问题。
    """
    excerpt = ("模型不可用（alloc）：{\"error\":\"llama-server reported out-of-memory "
               "during startup: alloc_tensor_range: failed to allocate Vulkan0 buffer\"}")
    assertions = [{"id": number, "name": name, "pass": True,
                   "observed": {"placeholder": number}}
                  for number, name, _label in kit.ASSERTION_NAMES]
    return {
        "case_id": kit.CASE_ID,
        "schema_version": kit.SCHEMA_VERSION,
        "completed": True,
        "assertions": assertions,
        "provider_calls": [
            {"model": kit.PRIMARY_MODEL, "ok": False, "error_kind": "model_unavailable",
             "request_bytes": 211, "elapsed_ms": 22465.5, "error_body_excerpt": excerpt},
            {"model": kit.FALLBACK_MODEL, "ok": True, "error_kind": None,
             "request_bytes": 900, "elapsed_ms": 31000.0, "error_body_excerpt": None},
        ],
        "ledger": {"rows": 1, "canary_hits": [], "canary_needles": [kit.PROMPT_CANARY],
                   "row": {"fallback_index": 1, "success": 1, "model": kit.FALLBACK_MODEL,
                           "trace_id": "t-1"}},
        "trace": {"trace_id": "t-1", "model_route_attempts": [{}, {}]},
        "answer": {"text": "员工出差住宿需事前经部门经理审批，每晚上限 600 元，"
                           "发票须在 30 天内提交。"},
        "timings_ms": {"total": 61000.0},
        "files_sha1": kit.fingerprint([kit.PROBE_FILE]),
    }


class P0GateSelfIntegrityTests(unittest.TestCase):
    """闸自己的三枚自检：把自己也放进判据里，否则「把闸藏起来」是一种通关方式。"""

    def test_the_gate_source_has_zero_skip_family_tokens(self):
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        hits = _skip_hits(tree, scan_strings=False)
        self.assertEqual([], hits, "闸的源码里出现了 skip 令牌 ⇒ 判据可以被关闭")

    def test_the_gate_is_collected_in_the_default_suite(self):
        env = {key: value for key, value in dict(os.environ).items()
               if key != kit.ENV_SWITCH}
        _code, ids, _raw = collect_only(env, str(Path("tests") / Path(__file__).name))
        self.assertGreaterEqual(len(ids), 8,
                                "闸自己被收集到的例数掉档：这道闸已经不再看守任何东西")
        for name in ("test_carrier_source_has_zero_skip_family_tokens",
                     "test_collected_zero_when_off_and_one_when_on",
                     "test_p0_row_status_matches_the_evidence"):
            self.assertTrue(any(node.endswith(name) for node in ids),
                            f"闸的判据 {name} 不在收集清单里")

    def test_gate_classes_are_discoverable_from_the_matrix_doc(self):
        """反向耦合（照 `MatrixDocumentClosureTests` 的口径）：本文件的每枚类都要挂在表上。"""
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        classes = sorted(node.name for node in tree.body
                         if isinstance(node, ast.ClassDef)
                         and any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and m.name.startswith("test_") for m in node.body))
        self.assertGreaterEqual(len(classes), 3)
        text = MATRIX_DOC.read_text(encoding="utf-8")
        for name in classes:
            with self.subTest(cls=name):
                self.assertIn(name, text, "闸的类没被矩阵点名 ⇒ 文档不可反向发现")


if __name__ == "__main__":
    unittest.main(verbosity=2)
