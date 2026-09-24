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
   没有成立的证据 JSON ⇒ 只许 `BLOCKED`；证据成立 ⇒ 只许 `GREEN`。
   判据是 `real_llm_failover_kit.validate_evidence()`：十枚断言各带实测值、真外呼两次的
   模型名/字节数/耗时、primary 错误体里的服务端原文、临时库恰好一行且零 canary 命中、
   以及**逐枚重算的 sha1**。矩阵文案自己不算数。

闸自己也在判据内（`P0GateSelfIntegrityTests`）：本文件同样零 skip 令牌、自己的每枚类都
挂在矩阵上、并且它自己**必须**在默认套件里被收集到（否则这道闸可以靠「把自己也藏起来」过关）。
"""
from __future__ import annotations

import ast
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
class P0MatrixStatusLockedToEvidenceTests(unittest.TestCase):
    """闸③：没跑过真机 ⇒ 矩阵 P0 行只许 `BLOCKED`；跑过 ⇒ 只许 `GREEN` 且证据成立。"""

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
        evidence, read_error = kit.read_evidence()
        problems = kit.validate_evidence(evidence)
        if evidence is None or problems:
            self.assertEqual(
                P0_STATUS_WITHOUT_EVIDENCE, status,
                f"P0 还没跑过真机（证据：{read_error or problems}），矩阵那一行却写着 "
                f"{status!r}。唯一合法取值是 {P0_STATUS_WITHOUT_EVIDENCE!r}——"
                "改状态之前请先跑 .superpowers/scripts/run_p0_failover_acceptance.sh")
            return
        self.assertEqual(
            P0_STATUS_WITH_EVIDENCE, status,
            f"证据已经成立（十枚断言 + sha1 + 服务端错误体齐了），矩阵还写着 {status!r}："
            "要么把 P0 行改成 GREEN，要么说明这份证据不该存在")

    def test_the_evidence_judgment_does_not_degrade(self):
        """判据自身的四枚变异探针：每缺一枚关键事实，`validate_evidence` 必须**点名**它。

        为什么单独钉这一枚（Task 9 复审的教训形状）：闸③读的是采集器的判据，判据退化成
        「数一数有没有 10 条」时，本文件一切照常绿。四枚变异各打一枪，打的就是
        「模型序 / 服务端错误体 / 账本行数 / 落盘指纹」这四枚最容易被糊弄的位。
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
