"""Model Router V2.3 —— D6 单一出口守卫 + 验收矩阵收口（Task 9 段 A）。

本文件是 **D6（`app/llm/provider.py` 之外的第二条出口）的收口件**。既有扫描件各有分工，
三者不重叠：

- `tests/test_model_router_v23_contract.py::SingleEgressStructureTests`
  = `app/llm/` **目录内部**的 AST 级结构钉（只有 provider.py import httpx；非 provider 文件
  对端点字面量做到全文零命中）。它**不看** `app/` 的其余部分。
- `tests/test_llm_usage_contract.py::ModelRouteProducerUniquenessTests`
  = trace 九键的「唯一生产者/唯一挂载点」防回潮钉（同一份文件枚举、同一份豁免结构）。
- **本文件** = 全 `app/` 的模式集扫描（AST 面 + 全文字面量面两层，各自等式钉）、
  业务入口的「不裸放 `ValueError`」扫描、`error_type='unknown'` 归零的行为用例，
  以及 `docs/MODEL_ROUTER_V23_MATRIX.md` 的机器化收口（矩阵每行的承载测试必须真实存在）。

两层为什么必须分开（Task 8 的 m-1/m-2 教训）
------------------------------------------
D6 的判据是「**代码**里不许有第二条出口」，而矩阵 #19 的静态扫描按 brief 点名的模式集是
**全文** rg（不解析语法）。两者的命中数**天然不等**：迁移说明里正当的散文（
`conversation_agent.py` 头注释写着「不许再把 `/api/chat` + `httpx.stream` 内联回来」）
在全文面算命中，在 AST 面不算。所以本文件把两层各自钉成等式，并额外钉第三层关系：

    全文面命中数 == 代码面命中数 + 散文命中数          （逐模式、逐文件，三次独立测量）

三面都是逐行数出来的（`fulltext_hits()` / `code_hits()` / `prose_hits()`，Task 9 复审
Minor 4 之后代码面不再只是「全文 − 散文」的算术差），并且与 AST 面**跨算法互验**
（`test_the_measured_code_face_is_confirmed_by_the_ast_face`）+ 分区自核
（`test_the_three_faces_are_measured_on_a_real_line_partition`）。
散文不是「被忽略的噪声」，它是**单列计数**的一层：谁把出口挪进注释里躲 AST 面，全文面就红；
谁在代码里真开第二条腿，两层同时红。注释里也不许声称「两层同数」。

矩阵文档的耦合闸是**双向**的（Task 9 复审 Minor 3）
------------------------------------------------
- 正向：文档里每一枚 node-id 都必须真实存在（`test_every_row_carries_a_real_test_or_an_honest_status`）。
- 反向：本文件的每一枚测试类都必须被矩阵点名一次
  （`test_every_guard_test_class_is_discoverable_from_the_document`）——
  只有正向闸时「套件新增一枚不挂表的例」永远绿。
另配 `ScanningHelpersAreAllLiveTests`：扫描 helper 一枚都不许变成死代码（第三层是不是
真的在测量，从今天起不靠读码判断）。

豁免表（终态见 `EXEMPTIONS`）
--------------------------
按 brief 的要求，豁免不是「允许出现」而是**等式**：这些文件、各这么多处、多一处就红。
另配 `test_exemption_table_has_no_dead_rows` 反向闸：表里每一行都必须在某一面真的有命中，
养闲条目（放大一档）同样红。
"""
from __future__ import annotations

import ast
import io
import os
import re
import sqlite3
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
MATRIX_DOC = BACKEND_DIR.parent / "docs" / "MODEL_ROUTER_V23_MATRIX.md"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402

import app.llm as llm  # noqa: E402
import app.llm.fallback as fallback_module  # noqa: E402
import app.llm.registry as registry_module  # noqa: E402
import app.llm.usage as usage_module  # noqa: E402
import app.llm.provider as provider_module  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.errors import LLMError  # noqa: E402
from app.llm.models import ModelDefinition, RequestProfile  # noqa: E402
from app.llm.registry import Registry, load_registry  # noqa: E402
from app.llm.router import REASON_CODES, NoCapableModelError  # noqa: E402

#: 会话级护栏（`tests/conftest.py`）的对外口径；import 失败 = 护栏被删 = 全套件红。
TESTS_DIR = BACKEND_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import conftest as ledger_guard  # noqa: E402


# ==========================================================================
# 0. 扫描面与模式集（唯一出处：两层都用它）
# ==========================================================================
#: brief 点名的五枚模式 + 三枚配套模式（`/v1/chat/completions` 在现网是 0 命中，
#: provider 的 OpenAI 腿发的是 `base_url + "/chat/completions"`，所以「字面带引号」与
#: 「spec 原文端点」分开钉；`OLLAMA_BASE_URL` 大写 env 名 0 命中，因为 `registry.py` 是
#: 运行期拼装（T1 移交）⇒ 那一条钉成「恒 0」而不是「有豁免」）。
PATTERNS: dict[str, re.Pattern[str]] = {
    "ollama_chat_endpoint": re.compile(r"/api/chat"),
    "openai_chat_endpoint": re.compile(r"/v1/chat/completions"),
    "openai_chat_path_literal": re.compile(r'"/chat/completions"'),
    "ollama_base_url_env": re.compile(r"OLLAMA_BASE_URL"),
    "api_key_env": re.compile(r"_API_KEY"),
    "httpx_verb": re.compile(r"httpx\.(?:post|stream)"),
    "import_httpx": re.compile(r"^import httpx\b", re.MULTILINE),
    "llm_credential_name": re.compile(
        r"\b(?:openai|deepseek|qwen|ollama)_(?:api_key|base_url)\b"),
}

#: 代码面（AST）的 httpx「出口动词」：构造客户端或直接发请求都算第二条腿。
HTTPX_EGRESS_ATTRS = frozenset(
    {"post", "stream", "get", "put", "patch", "delete", "request", "Client", "AsyncClient"})

#: 被允许出现命中的文件（相对 `backend/` 的 posix 路径）+ **为什么**。
#: 这张表同时是本文件的「豁免表终态」，Task 9 段 B 与终审按它复用。
EXEMPTIONS: dict[str, str] = {
    "app/llm/provider.py":
        "唯一合法出口（真 import httpx + 两侧端点字面量 + 凭据 env 名散文）。D6 的白名单本体。",
    "app/rag.py":
        "legacy 应急腿：`LLM_ROUTER_ENABLED=false` 的两条 `httpx.post` 分支 + 端点字面量 + "
        "`settings.openai_api_key`/`openai_base_url`/`ollama_base_url` 读法。§1 已判 "
        "「下一稳定版必须删除」，删除时把本行与等式一起收掉。",
    "app/agent.py":
        "legacy 应急腿：`import httpx` + 一处 `httpx.post` + 端点字面量 1 处（DESIGN §9.1 "
        "Task 8 补正：agent 链两条腿都有 legacy 形态，旗标含义是「回到未路由的世界」）。",
    "app/conversation_agent.py":
        "**0 命中**，只出现在退役说明的散文里（`native_stream.py` 已退役 ⇒ 本链没有 legacy "
        "出口）。留在表里是为了让「有人把 `/api/chat` 内联回来」这条变异第一眼就被读到。",
    "app/identity/feishu_client.py":
        "飞书开放平台的 httpx 客户端（`import httpx` + `httpx.Client`），**不是 LLM 出口**："
        "D6 的单一出口只管模型调用（Task 2 评审 M-5）。按文件级例外钉，不用「整目录跳过」。",
    "app/config.py":
        "§12 的 `*_api_key` / `*_base_url` **字段声明**（含 `ollama_base_url` 的默认值），"
        "是凭据的配置面而不是外呼面 ⇒ AST 的属性读法天然不计（声明不是 `ast.Attribute`），"
        "全文面按等式计入（T1 移交）。",
    "app/llm/health.py":
        "读 `settings.openai_api_key` 一枚（legacy RAG 链的选择语义，T2 冻结）+ 头注释散文里"
        "提了一句历史形态的 `httpx.get`。探针自己不发请求，统一经 provider 层（D6）。",
    "app/knowledge_os.py":
        "`/api/system/status` 的 legacy 展示面读一次 `settings.openai_api_key` 决定 provider "
        "标签；无 httpx、无端点字面量。",
    "app/main.py":
        "同上：legacy 端点面上的 `settings.openai_api_key` 读法（provider 标签），非出口。",
    "app/main_agent.py":
        "同上：agent 版 app 工厂里的 provider 标签读法，非出口。",
}


def app_python_files() -> list[Path]:
    """扫描面 = 交付面：`backend/app/**/*.py`，去 `__pycache__`（字节码不算源码）。"""
    return sorted(path for path in APP_DIR.rglob("*.py")
                  if "__pycache__" not in path.parts)


def relative(path: Path) -> str:
    """豁免表与扫描结果共用的键：相对 `backend/` 的 **posix** 路径（不是 `path.name`）。

    用 `path.name` 比对是 T5 复审 N2 点名的漏洞：子目录里的同名文件会自动免检
    （`app/x/usage.py` 之类）。相对路径 + posix 让「哪个目录的哪个文件」成为键的一部分。
    """
    return path.relative_to(BACKEND_DIR).as_posix()


def docstring_and_comment_lines(tree: ast.AST, source: str) -> set[int]:
    """散文行号集合 = docstring（模块/类/函数）的全部行 + `#` 注释的全部行。

    这就是「全文面」与「代码面」的分界线：它不做语义判断，只做**出处**判断，
    因此两层之和恒等于全文面（`test_fulltext_face_equals_code_face_plus_prose`）。
    """
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                value = body[0].value
                prose.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                prose.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass                                       # 语法破损由 AST 面那一条先红，这里不重复报
    return prose


def _count(pattern: re.Pattern[str], lines: list[str], row_numbers: set[int] | None) -> int:
    if row_numbers is None:
        return sum(len(pattern.findall(line)) for line in lines)
    return sum(len(pattern.findall(lines[number - 1])) for number in row_numbers
               if number <= len(lines))


def fulltext_hits() -> dict[str, dict[str, int]]:
    """全文面：逐模式 → {相对路径: 命中数}（注释与 docstring 也算命中）。"""
    out: dict[str, dict[str, int]] = {name: {} for name in PATTERNS}
    for path in app_python_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for name, pattern in PATTERNS.items():
            total = _count(pattern, lines, None)
            if total:
                out[name][relative(path)] = total
    return out


def prose_hits() -> dict[str, dict[str, int]]:
    """散面：与全文面同一算法，只数「注释 + docstring」的行。"""
    out: dict[str, dict[str, int]] = {name: {} for name in PATTERNS}
    for path in app_python_files():
        source = path.read_text(encoding="utf-8")
        prose = docstring_and_comment_lines(ast.parse(source), source)
        lines = source.splitlines()
        for name, pattern in PATTERNS.items():
            total = _count(pattern, lines, prose)
            if total:
                out[name][relative(path)] = total
    return out


def code_line_numbers(path: Path) -> set[int]:
    """该文件里**非散文**的行号（全文行集减去散面行集 ⇒ 代码面的行集合）。"""
    source = path.read_text(encoding="utf-8")
    prose = docstring_and_comment_lines(ast.parse(source), source)
    return set(range(1, len(source.splitlines()) + 1)) - prose


def code_hits() -> dict[str, dict[str, int]]:
    """代码面：**独立测量**（把每枚模式的命中限制在 `code_line_numbers()` 的行集上）。

    Task 9 评审 Minor 4 的收口：这张面以前只是「全文 − 散文」的**差值**（推导量），
    `code_line_numbers()` 定义了却零使用 ⇒ 第三层的加法等式对任何实现都恒真。现在它
    与全文面、散文面一样是逐行数出来的，第三层才是三次测量互验（`test_fulltext_face_
    equals_code_face_plus_prose` 同时核派生值与测量值，两者不许脱钩）。
    """
    out: dict[str, dict[str, int]] = {name: {} for name in PATTERNS}
    for path in app_python_files():
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        code = code_line_numbers(path)
        for name, pattern in PATTERNS.items():
            total = _count(pattern, lines, code)
            if total:
                out[name][relative(path)] = total
    return out


def ast_httpx_imports() -> dict[str, int]:
    tree_map: dict[str, int] = {}
    for path in app_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Import)
                 and any(alias.name.split(".")[0] == "httpx" for alias in node.names)]
        found += [node for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom)
                  and (node.module or "").split(".")[0] == "httpx"]
        if found:
            tree_map[relative(path)] = len(found)
    return tree_map


def ast_httpx_egress_calls() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in app_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        sites = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx"
                 and node.func.attr in HTTPX_EGRESS_ATTRS]
        if sites:
            out[relative(path)] = len(sites)
    return out


def ast_endpoint_string_constants() -> dict[str, dict[str, int]]:
    """代码里的**字符串常量**含端点字面量（docstring 已由 `prose` 行集排除在外的语义等价物）。

    与 `business_file_has_no_second_llm_egress`（Task 7）同一口径：属性名 `settings.
    ollama_base_url` 在这里不计，它另有 `ast_credential_attribute_reads` 一枚等式钉。
    """
    out: dict[str, dict[str, int]] = {}
    #: 端点面在字符串常量层的判据（带引号的模式不算「常量内容」，所以剥掉引号取路径本体）。
    needles = {"ollama_chat_endpoint": "/api/chat",
               "openai_chat_endpoint": "/v1/chat/completions",
               "openai_chat_path_literal": "/chat/completions"}
    for path in app_python_files():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        docstrings = docstring_and_comment_lines(tree, source)
        buckets: dict[str, int] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if node.lineno in docstrings:
                continue
            for name, needle in needles.items():
                if needle in node.value:
                    buckets[name] = buckets.get(name, 0) + 1
        if buckets:
            out[relative(path)] = buckets
    return out


def ast_credential_attribute_reads() -> dict[str, dict[str, int]]:
    """`settings.<凭据名>` 的**属性读法**：凭据被谁拿去自己拼 URL/发请求。"""
    out: dict[str, dict[str, int]] = {}
    names = {"openai_api_key", "deepseek_api_key", "qwen_api_key",
             "openai_base_url", "deepseek_base_url", "qwen_base_url", "ollama_base_url"}
    for path in app_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        buckets: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in names:
                buckets[node.attr] = buckets.get(node.attr, 0) + 1
        if buckets:
            out[relative(path)] = buckets
    return out


# ==========================================================================
# 1. 终态等式表（2026-09-24 由本文件作者**实测**算出，不是抄来的）
# ==========================================================================
# 全文面（含散文）
FULLTEXT_EXPECTED: dict[str, dict[str, int]] = {
    "ollama_chat_endpoint": {"app/agent.py": 1, "app/conversation_agent.py": 1,
                             "app/llm/provider.py": 2, "app/rag.py": 2},
    "openai_chat_endpoint": {},
    "openai_chat_path_literal": {"app/llm/provider.py": 1, "app/rag.py": 1},
    "ollama_base_url_env": {},
    "api_key_env": {"app/llm/provider.py": 1},
    "httpx_verb": {"app/agent.py": 4, "app/conversation_agent.py": 1, "app/rag.py": 4},
    "import_httpx": {"app/agent.py": 1, "app/identity/feishu_client.py": 1,
                     "app/llm/provider.py": 1, "app/rag.py": 1},
    "llm_credential_name": {"app/agent.py": 2, "app/config.py": 7, "app/knowledge_os.py": 1,
                            "app/llm/health.py": 2, "app/main.py": 1, "app/main_agent.py": 1,
                            "app/rag.py": 7},
}
#: 散文面（docstring + `#` 注释）：与全文面同结构，逐文件逐模式。
PROSE_EXPECTED: dict[str, dict[str, int]] = {
    "ollama_chat_endpoint": {"app/conversation_agent.py": 1, "app/llm/provider.py": 1,
                             "app/rag.py": 1},
    "openai_chat_endpoint": {},
    "openai_chat_path_literal": {},
    "ollama_base_url_env": {},
    "api_key_env": {"app/llm/provider.py": 1},
    "httpx_verb": {"app/agent.py": 3, "app/conversation_agent.py": 1, "app/rag.py": 2},
    "import_httpx": {},
    "llm_credential_name": {"app/agent.py": 1, "app/llm/health.py": 1, "app/rag.py": 2},
}
#: 代码面 = 全文 − 散文（下表是差值，由第三层的加法等式再核一遍）。
CODE_EXPECTED: dict[str, dict[str, int]] = {
    "ollama_chat_endpoint": {"app/agent.py": 1, "app/llm/provider.py": 1, "app/rag.py": 1},
    "openai_chat_endpoint": {},
    "openai_chat_path_literal": {"app/llm/provider.py": 1, "app/rag.py": 1},
    "ollama_base_url_env": {},
    "api_key_env": {},
    "httpx_verb": {"app/agent.py": 1, "app/rag.py": 2},
    "import_httpx": {"app/agent.py": 1, "app/identity/feishu_client.py": 1,
                     "app/llm/provider.py": 1, "app/rag.py": 1},
    "llm_credential_name": {"app/agent.py": 1, "app/config.py": 7, "app/knowledge_os.py": 1,
                            "app/llm/health.py": 1, "app/main.py": 1,
                            "app/main_agent.py": 1, "app/rag.py": 5},
}
# AST 面（独立算法，与「全文 − 散文」互相核对）
AST_IMPORTS_EXPECTED = {"app/agent.py": 1, "app/identity/feishu_client.py": 1,
                        "app/llm/provider.py": 1, "app/rag.py": 1}
AST_EGRESS_CALLS_EXPECTED = {"app/agent.py": 1, "app/identity/feishu_client.py": 1,
                             "app/llm/provider.py": 1, "app/rag.py": 2}
AST_ENDPOINT_CONSTANTS_EXPECTED = {
    "app/agent.py": {"ollama_chat_endpoint": 1},
    "app/llm/provider.py": {"ollama_chat_endpoint": 1, "openai_chat_path_literal": 1},
    "app/rag.py": {"ollama_chat_endpoint": 1, "openai_chat_path_literal": 1},
}
AST_CREDENTIAL_ATTRS_EXPECTED = {
    "app/agent.py": {"ollama_base_url": 1},
    "app/knowledge_os.py": {"openai_api_key": 1},
    "app/llm/health.py": {"openai_api_key": 1},
    "app/main.py": {"openai_api_key": 1},
    "app/main_agent.py": {"openai_api_key": 1},
    "app/rag.py": {"openai_api_key": 3, "openai_base_url": 1, "ollama_base_url": 1},
}


# ==========================================================================
# 2. D6：AST 面
# ==========================================================================
class D6AstFaceTests(unittest.TestCase):
    """出口 = 可执行节点：`import httpx` / `httpx.<动词>` 调用 / 端点字符串常量 / 凭据属性读法。"""

    def test_scan_surface_is_real_and_provider_is_on_it(self):
        files = app_python_files()
        self.assertGreater(len(files), 40, "扫描面缩水成空跑了")
        self.assertIn("app/llm/provider.py", {relative(p) for p in files})
        self.assertEqual([], [p for p in files if not p.is_file()])

    def test_httpx_import_sites_are_exactly_the_equalled_four(self):
        self.assertEqual(AST_IMPORTS_EXPECTED, ast_httpx_imports(),
                         msg="新增/删除一处 `import httpx` —— 改表之前先答它是不是第二条出口")

    def test_httpx_egress_calls_are_the_provider_plus_two_legacy_legs_plus_feishu(self):
        self.assertEqual(AST_EGRESS_CALLS_EXPECTED, ast_httpx_egress_calls(),
                         msg="httpx 出口动词的调用点必须逐枚对上豁免表")

    def test_endpoint_literals_in_code_only_live_in_provider_and_the_two_legacy_legs(self):
        self.assertEqual(AST_ENDPOINT_CONSTANTS_EXPECTED, ast_endpoint_string_constants())

    def test_credential_attribute_reads_are_the_legacy_legs_plus_the_display_face(self):
        # `app/config.py` 的字段声明**不在**这里：声明不是 `ast.Attribute`，所以「配置面 ≠ 出口面」
        # 由 AST 天然区分；它仍在全文面（`llm_credential_name`）里被等式计入。
        self.assertEqual(AST_CREDENTIAL_ATTRS_EXPECTED, ast_credential_attribute_reads())

    def test_no_business_module_dispatches_on_the_provider_name(self):
        """§2 冻结「业务层禁止 `if provider == ...` 形态」的静态半段。

        扫描面刻意是**路由与执行面**（三条链 + `classifier/router/fallback`）：那里按
        provider 的**厂牌字面量**分支就是「第二条出口的胚胎」。判据只认
        `... == "ollama" / "openai"` 这一形，不认按 provider **身份**做的集合运算——
        `fallback.py:520` 的 `model.provider in self.config_failed`（§6：401/403 之后本次
        请求内跳过同 provider 的其余候选）与 `CircuitBreaker(name=provider)`（D4）都是
        厂牌无关的。两枚已知的合法比较也**不在**面上，理由写死：
        - `app/llm/registry.py:251` `provider == "ollama"` = D1 的凭据约定（ollama 无 key）；
        - `app/main.py:232` = legacy `/api/system/status` 的 provider 标签（展示面，无外呼）。
        `app/llm/provider.py` 本身当然分发（`PROVIDERS` 字典），它是唯一出口的白名单本体。
        """
        scope = [*CHAIN_FILES, "app/llm/classifier.py", "app/llm/router.py",
                 "app/llm/fallback.py"]
        offenders: list[str] = []
        for rel in scope:
            source = (BACKEND_DIR / rel).read_text(encoding="utf-8")
            tree = ast.parse(source)
            prose = docstring_and_comment_lines(tree, source)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Compare) and node.lineno not in prose):
                    continue
                if not any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops):
                    continue
                constants = [c.value for c in node.comparators
                             if isinstance(c, ast.Constant)]
                if {"ollama", "openai"} & set(constants):
                    offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual([], offenders, "路由/执行面按 provider 厂牌字面量分支了")


# ==========================================================================
# 3. D6：全文字面量面（矩阵 #19 的「rg 形态」）+ 两层的关系
# ==========================================================================
class D6FullTextFieldTests(unittest.TestCase):
    def test_fulltext_hits_are_equalled_per_pattern(self):
        for name, expected in FULLTEXT_EXPECTED.items():
            with self.subTest(pattern=name):
                self.assertEqual(expected, fulltext_hits()[name])

    def test_prose_hits_are_equalled_per_pattern(self):
        for name, expected in PROSE_EXPECTED.items():
            with self.subTest(pattern=name):
                self.assertEqual(expected, prose_hits()[name])

    def test_fulltext_face_equals_code_face_plus_prose(self):
        """三层的加法关系（Task 8 m-1/m-2 的教训）：全文 = 代码 + 散文，逐模式逐文件。

        这一枚是「注释不许声称两层同数」的正解：本文件**承认**两者不等（差值就是散文），
        并把差值本身做成等式。任何「把出口挪进字符串常量/注释」的写法都会破坏其中一个等式。

        Task 9 评审 Minor 4 之后这里核的是**三次独立测量**：全文面逐行数、散文面逐行数、
        代码面也逐行数（限制在 `code_line_numbers()` 的行集上）。派生值（全文 − 散文）与
        测量值（行集过滤）必须逐模式逐文件相等——两者一旦脱钩，说明行集分类有洞；
        只留派值的话这条等式对任何实现都恒真（评审实测：内圈恒真、8 枚模式失败 0）。
        """
        full, prose, measured = fulltext_hits(), prose_hits(), code_hits()
        for name in PATTERNS:
            with self.subTest(pattern=name):
                derived = {key: full[name].get(key, 0) - prose[name].get(key, 0)
                           for key in set(full[name]) | set(prose[name])}
                derived = {key: value for key, value in derived.items() if value}
                self.assertEqual(CODE_EXPECTED[name], derived)
                self.assertEqual(CODE_EXPECTED[name], measured[name],
                                 f"{name}：代码面的**测量值**与 CODE_EXPECTED 脱钩")
                self.assertEqual(derived, measured[name],
                                 f"{name}：派生式与行集测量式给出的代码面不是同一张表")
                for key in set(full[name]) | set(prose[name]):
                    self.assertEqual(
                        full[name].get(key, 0), derived.get(key, 0) + prose[name].get(key, 0),
                        f"{name} @ {key}：全文面与（代码 + 散文）脱钩")

    def test_the_three_faces_are_measured_on_a_real_line_partition(self):
        """「独立测量」的前提：散文行集与代码行集必须是**真分区**，且两族都真的出现过。

        逐文件核三件事：①不相交（同一行不许既算代码又算散文，否则差值会重复计数）、
        ②并起来是全文件（漏掉的行会让代码面少数）、③两族都非空（分区退化成空集时上面
        那些等式全部空跑）。这是评审 Minor 4 的另一半：不核分区，「代码面」这个词就只是
        一张派生表的别称。
        """
        prose_lines = code_lines = 0
        for path in app_python_files():
            source = path.read_text(encoding="utf-8")
            total = set(range(1, len(source.splitlines()) + 1))
            prose = docstring_and_comment_lines(ast.parse(source), source)
            code = code_line_numbers(path)
            rel = relative(path)
            self.assertEqual(set(), prose & code, f"{rel}：一行既算散文又算代码")
            self.assertEqual(total, prose | code, f"{rel}：有行既不在散文也不在代码 ⇒ 分区漏了")
            self.assertTrue(prose <= total and code <= total, f"{rel}：分区越界")
            prose_lines += len(prose)
            code_lines += len(code)
        self.assertGreater(prose_lines, 0, "整个扫描面没有一行散文 ⇒ 散面是空跑")
        self.assertGreater(code_lines, 0, "整个扫描面没有一行代码 ⇒ 扫描面退化了")

    def test_the_measured_code_face_is_confirmed_by_the_ast_face(self):
        """第三层与第一层**跨算法**互验：行集数出来的代码面必须等于 AST 数出来的同一件事。

        `import httpx` 这一枚尤其有牙：AST 面（`ast.Import`/`ast.ImportFrom` 节点）完全
        **不读**散文行集，而代码面读 ⇒ 谁把 `docstring_and_comment_lines()` 改成多吞几行
        （例如把整份文件当 docstring），派生值与 `CODE_EXPECTED` 仍然自洽，只有这条会红。
        端点面同理：AST 侧数的是**字符串常量节点**，行集侧数的是**非散文行上的正则命中**。
        两张表由两种算法各算一遍，逐文件逐模式相等（评审 Minor 4 要的「三层互验」）。
        """
        measured = code_hits()
        self.assertEqual(AST_IMPORTS_EXPECTED, measured["import_httpx"],
                         "行集代码面与 AST 的 `import httpx` 落点集不是同一张表")
        endpoints = {"ollama_chat_endpoint", "openai_chat_path_literal"}
        from_code_face: dict[str, dict[str, int]] = {}
        for name, row in measured.items():
            if name not in endpoints:
                continue
            for rel, count in row.items():
                from_code_face.setdefault(rel, {})[name] = count
        self.assertEqual(AST_ENDPOINT_CONSTANTS_EXPECTED, from_code_face,
                         "行集代码面与 AST 的端点字符串常量面不是同一张表")

    def test_every_pattern_has_an_explicit_row_even_when_the_answer_is_zero(self):
        # 恒 0 的两枚（`/v1/chat/completions`、`OLLAMA_BASE_URL`）是**刻意留行**的：
        # 前者因为 provider 的 OpenAI 腿拼的是 `base_url + "/chat/completions"`（spec 原文端点
        # 在本仓不做字面量匹配 ⇒ 改注册表 base_url 也躲不过 `openai_chat_path_literal`），
        # 后者因为 `registry.py` 按 D1 运行期拼装 env 名（T1 移交）。
        self.assertEqual(set(PATTERNS), set(FULLTEXT_EXPECTED))
        self.assertEqual(set(PATTERNS), set(PROSE_EXPECTED))
        self.assertEqual(set(PATTERNS), set(CODE_EXPECTED))
        self.assertEqual({}, FULLTEXT_EXPECTED["openai_chat_endpoint"])
        self.assertEqual({}, FULLTEXT_EXPECTED["ollama_base_url_env"])

    def test_providers_endpoint_literals_are_present_and_unique(self):
        """出口必须**真的还在**（否则「只有 provider 有」可以靠删掉 provider 的出口来骗过）。"""
        literals = ast_endpoint_string_constants()
        self.assertEqual({"ollama_chat_endpoint": 1, "openai_chat_path_literal": 1},
                         literals["app/llm/provider.py"])
        text = (BACKEND_DIR / "app" / "llm" / "provider.py").read_text(encoding="utf-8")
        self.assertIn("httpx.Client", text)
        self.assertEqual(1, ast_httpx_imports()["app/llm/provider.py"])
        self.assertEqual(1, ast_httpx_egress_calls()["app/llm/provider.py"])


# ==========================================================================
# 4. 豁免表自身
# ==========================================================================
class ExemptionTableTests(unittest.TestCase):
    def test_only_exempted_files_may_have_code_face_hits(self):
        for name, table in CODE_EXPECTED.items():
            for key in table:
                with self.subTest(pattern=name, file=key):
                    self.assertIn(key, EXEMPTIONS, "新的命中文件必须先过评审再进表")

    def test_exemption_table_has_no_dead_rows(self):
        """表里每一行都要在某一面真的有命中 ⇒ 把表放大一档（多列一个文件）立刻红。"""
        seen: set[str] = set()
        for table in (fulltext_hits(), prose_hits(), CODE_EXPECTED):
            for row in table.values():                 # {模式: {文件: 计数}}
                seen |= set(row)
        for table in (AST_IMPORTS_EXPECTED, AST_EGRESS_CALLS_EXPECTED,
                      AST_ENDPOINT_CONSTANTS_EXPECTED, AST_CREDENTIAL_ATTRS_EXPECTED):
            seen |= set(table)                         # {文件: ...}
        for key in EXEMPTIONS:
            with self.subTest(file=key):
                self.assertTrue((BACKEND_DIR / key).is_file(), "豁免了不存在的文件")
                self.assertIn(key, seen, "死行：这一档没有任何命中支撑")
        self.assertEqual(set(EXEMPTIONS), seen,
                         "豁免表与命中集必须互等：多一档少一档都是漂移")

    def test_no_directory_is_skipped_whole(self):
        """按 brief：不许用「整目录跳过」糊 ⇒ 扫描面必须真的覆盖到各子包。

        非空跑的证明：`app/identity/`（feishu 的 httpx 客户端）与 `app/tools/` 都在面上；
        任何「`if "identity" in parts: continue`」式写法都会让 `feishu_client.py` 从
        `import httpx` 的等式里消失 ⇒ 上一条互等式立刻红。
        """
        scanned = {relative(path) for path in app_python_files()}
        self.assertIn("app/identity/feishu_client.py", scanned)
        self.assertIn("app/llm/provider.py", scanned)
        self.assertIn("app/tools/registry.py", scanned)
        directories = {Path(p).parent for p in scanned}
        self.assertGreaterEqual(len(directories), 4, "扫描面退化成了单层目录")
        self.assertGreater(len(scanned), 40)


# ==========================================================================
# 5. 业务入口不裸放 `ValueError`（Task 3 移交项）
# ==========================================================================
#: 链路上的文件（D2 的降级判据要接得住东西，所以这几个文件里的 `raise ValueError` 全数点名）。
CHAIN_FILES = ("app/rag.py", "app/agent.py", "app/conversation_agent.py")
LLM_PACKAGE_FILES = tuple(f"app/llm/{path.name}" for path in sorted((APP_DIR / "llm").glob("*.py")))
#: 现网允许的 `ValueError`：**入参校验**（编程错误），不是降级路径。
#: - `app/agent.py` 的 `run_agent` 里 `mode` 越界那一枚（在任何模型调用之前，400 面）
#: - `app/llm/classifier.py` 的 `mode` 越界（§4 冻结：mode 由调用点声明）
#: - `app/llm/router.py` 的 `NoCapableModelError` 理由码越界（T3 移交：理由码必须是
#:   `REASON_CODES` 成员，裸 str 在构造期就转 `ValueError` ⇒ 见
#:   `test_a_bare_string_reason_code_is_rejected_at_construction_not_silently_kept`）
#: 位置一律按「文件 + 函数 + 分支」写、不写裸行号（Task 9 评审 m-2：裸行号一改就漂）。
CHAIN_VALUE_ERROR_EXPECTED = {"app/agent.py": 1}
LLM_VALUE_ERROR_EXPECTED = {"app/llm/classifier.py": 1, "app/llm/router.py": 1}
VALUE_ERROR_RAISES_EXPECTED = {**CHAIN_VALUE_ERROR_EXPECTED, **LLM_VALUE_ERROR_EXPECTED}


def value_error_raises(paths: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rel in paths:
        tree = ast.parse((BACKEND_DIR / rel).read_text(encoding="utf-8"))
        found = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)
                 and ast.unparse(node.exc.func).split(".")[-1] in {"ValueError", "Exception"}]
        if found:
            out[rel] = len(found)
    return out


class NoBareValueErrorOnTheChainTests(unittest.TestCase):
    """D2 的可接住性：降级靠的是**类型**，裸 `ValueError` 接不住 ⇒ 等于给用户 500。"""

    def test_chain_files_raise_no_value_error_except_the_named_input_checks(self):
        self.assertEqual(CHAIN_VALUE_ERROR_EXPECTED, value_error_raises(list(CHAIN_FILES)))

    def test_llm_package_raises_no_value_error_except_the_named_entry_checks(self):
        # 两张表的并集就是总表：改一张不改另一张 = 表自身漂移（`VALUE_ERROR_RAISES_EXPECTED`
        # 只用于这份自洽核，扫描面永远按链/按包分开算）。
        self.assertEqual(set(VALUE_ERROR_RAISES_EXPECTED),
                         set(CHAIN_VALUE_ERROR_EXPECTED) | set(LLM_VALUE_ERROR_EXPECTED))
        self.assertEqual(LLM_VALUE_ERROR_EXPECTED, value_error_raises(list(LLM_PACKAGE_FILES)))

    def test_no_value_error_is_raised_from_inside_an_except_handler_on_the_chain(self):
        """最阴的一种：把「可接住的失败」在 except 里换成裸 `ValueError` ⇒ 上层降级支形同不存在。"""
        offenders: list[str] = []
        for rel in [*CHAIN_FILES, *LLM_PACKAGE_FILES]:
            tree = ast.parse((BACKEND_DIR / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Raise) and isinstance(inner.exc, ast.Call)
                            and ast.unparse(inner.exc.func).split(".")[-1] == "ValueError"):
                        offenders.append(f"{rel}:{inner.lineno}")
        self.assertEqual([], offenders)

    def test_the_two_declared_types_are_catchable_by_the_documented_clauses(self):
        # 「可接住」= 类型学上就接得住：既不是 ValueError 的子类（业务 except ValueError 支
        # 会误吞），也不是 LLMError 的子类（`except LLMError` 支会把它当 provider 归类，
        # 而它根本没有 kind）。
        self.assertTrue(issubclass(NoCapableModelError, Exception))
        self.assertFalse(issubclass(NoCapableModelError, ValueError))
        self.assertFalse(issubclass(NoCapableModelError, LLMError))
        self.assertFalse(issubclass(LLMError, ValueError))

    def test_a_bare_string_reason_code_is_rejected_at_construction_not_silently_kept(self):
        """T3 移交的实现版：理由码越界 ⇒ 构造期 `ValueError`（编程错误），不是静默降级。"""
        with self.assertRaises(ValueError):
            NoCapableModelError(stage="capability", reason_codes=("CIRCUIT_OPENN",))
        with self.assertRaises(ValueError):
            NoCapableModelError(stage="capability", reason_codes=("熔断",))
        # 合法构造必须成功，且 `NO_CAPABLE_MODEL` 只随异常。
        exc = NoCapableModelError(stage="health", reason_codes=("CIRCUIT_OPEN",))
        self.assertEqual(("CIRCUIT_OPEN", "NO_CAPABLE_MODEL"), exc.reason_codes)
        self.assertEqual("health", exc.stage)

    def test_reason_codes_passed_by_the_router_are_module_constants_not_bare_strings(self):
        """静态面：`reason_codes=` 的参数里不许出现字符串字面量（拼错的码必须在构造期响）。"""
        offenders: list[str] = []
        for rel in LLM_PACKAGE_FILES:
            tree = ast.parse((BACKEND_DIR / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not ast.unparse(node.func).endswith("NoCapableModelError"):
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "reason_codes":
                        continue
                    for inner in ast.walk(keyword.value):
                        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                            offenders.append(f"{rel}:{node.lineno}:{inner.value}")
        self.assertEqual([], offenders)
        self.assertIn("CIRCUIT_OPEN", REASON_CODES)

    def test_each_chain_still_catches_the_zero_candidate_error_where_the_design_says(self):
        """D2 的落点等式：Agent 3 支 / RAG 2 支；SSE 链**没有**这一支（表里记 0 是事实不是漏）。

        SSE 的零候选面：本链 `mode` 恒为 `rag`（`needs_tools=False`），出厂注册表下 rag 档
        候选恒存在 ⇒ 理论不触发（§5/D2 原文）。真触达时由路由层的 generic 异常支转成
        error 帧/503 文案（`conversation_stream_routes.py` / `conversation_routes.py`），
        不新增事件类型（D5）。谁给这条链加了 `except NoCapableModelError` 都要显式改这张表，
        并在评审里说明它接的是哪一支降级。
        """
        counts = {}
        for rel in CHAIN_FILES:
            tree = ast.parse((BACKEND_DIR / rel).read_text(encoding="utf-8"))
            counts[rel] = sum(1 for node in ast.walk(tree)
                              if isinstance(node, ast.ExceptHandler) and node.type
                              and "NoCapableModelError" in ast.unparse(node.type))
        self.assertEqual({"app/rag.py": 2, "app/agent.py": 3, "app/conversation_agent.py": 0},
                         counts)

    def test_the_http_faces_do_not_translate_the_two_declared_types_into_500(self):
        """D2「不得 500/503 给用户裸错」的静态半段：链路上不许有 `except NoCapableModelError`
        之后再 `raise HTTPException(500)` 的形状（503 只允许出现在**既有**兜底文案支里）。"""
        offenders: list[str] = []
        for rel in CHAIN_FILES:
            tree = ast.parse((BACKEND_DIR / rel).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.ExceptHandler) and node.type
                        and "NoCapableModelError" in ast.unparse(node.type)):
                    continue
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Call)
                            and ast.unparse(inner.func).endswith("HTTPException")
                            and any(isinstance(a, ast.Constant) and a.value == 500
                                    for a in inner.args)):
                        offenders.append(f"{rel}:{inner.lineno}")
        self.assertEqual([], offenders)


# ==========================================================================
# 6. `unknown` 的归因出口 = 库查询（Task 5 移交；不设 `unknown_rate` 观测键）
# ==========================================================================
#: 三条链允许写进 `error_type` 的形状：provider 的 kind（可带 `:状态码` / `:no_fallback`）。
PROVIDER_KINDS = ("retryable", "config", "hard", "model_unavailable")
LEDGER_SENTINELS = ("client_aborted", "unknown")


class UnknownAttributionTests(unittest.TestCase):
    """「全套件跑完 `error_type='unknown'` 应为 0」的**真测试**版（不是文档里的一句话）。

    为什么做成自建库而不是读会话库：`tests/conftest.py` 的护栏把**任何**落向保护集的行逐例
    判红，所以整套件的正常节奏是「每条链写进自己的临时库」⇒ 会话库在收尾时是空的，读它等于
    空跑（虚假的绿）。这里改成：真 provider 代码 + 假传输，把三种 profile 的失败出口写进
    **本用例自有的**库，再跑那句 SQL。非空（`rows > 0`）与归零同时成立，才是这句话的意思。
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / "conversations.db"
        env = mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(self.db)}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        usage_module.init_usage_db(self.db)
        # 本用例的前提就是「护栏在场且我这枚路径不在保护集里」：护栏被删 ⇒ 下面那句
        # `assertFalse(path_is_protected)` 失去意义，而 import 本身已经是耦合强度
        # （`tests/conftest.py` 消失 ⇒ 本文件 collection error ⇒ 全套件红）。
        self.assertTrue(ledger_guard.guard_is_active(),
                        "会话护栏没装上：本用例的自建库前提不成立")
        self.assertFalse(ledger_guard.path_is_protected(self.db),
                         "临时库撞进了保护集：那笔写会被逐例判红，本用例的口径也就不成立了")
        previous = llm.set_usage_sink(None)                        # 用真落库函数
        self.addCleanup(lambda: llm.set_usage_sink(previous))
        llm.reset_circuit_breakers()
        self.addCleanup(llm.reset_circuit_breakers)
        settings = Settings(_env_file=None, ollama_base_url="http://ollama.test:11434",
                            openai_api_key="", llm_retry_per_model=0,
                            llm_breaker_enabled=False, llm_total_budget_ms=30000)
        for patch in (mock.patch.object(registry_module, "settings", settings),
                      mock.patch.object(fallback_module, "routing_health_view",
                                        lambda *args, **kwargs: {}),
                      mock.patch.object(llm, "get_registry",
                                        lambda: Registry(models=(_entry(), _other())))):
            patch.start()
            self.addCleanup(patch.stop)
        self.requests: list[httpx.Request] = []

    def serve(self, status: int, body: dict | None = None) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(status, json=body if body is not None else {"error": "boom"})

        patcher = mock.patch.object(provider_module, "_transport",
                                    httpx.MockTransport(handler))
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self) -> list[dict]:
        connection = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in connection.execute(
                "SELECT model, success, error_type, fallback_index, route_mode, status_code"
                " FROM llm_request_logs ORDER BY id")]
        finally:
            connection.close()

    def count_sql(self, where: str) -> int:
        connection = sqlite3.connect(f"file:{self.db.as_posix()}?mode=ro", uri=True)
        try:
            return int(connection.execute(
                f"SELECT count(*) FROM llm_request_logs {where}").fetchone()[0])
        finally:
            connection.close()

    def _drive(self, mode: str, status: int, *, needs_tools: bool = False) -> None:
        self.serve(status)
        profile = RequestProfile(mode=mode, complexity="low", needs_tools=needs_tools,
                                needs_stream=False, needs_reasoning=False)
        with self.assertRaises(LLMError):
            llm.complete([{"role": "user", "content": "违约金条款怎么说"}], mode=mode,
                         profile=profile, trace_id=f"t-{mode}")

    def test_three_profile_failure_exits_land_zero_unknown_rows(self):
        self._drive("chat", 500)                                   # retryable → 全链失败
        self._drive("rag", 401)                                    # config
        self._drive("agent", 400, needs_tools=True)                # hard（可 fallback 仍失败）
        rows = self.rows()
        self.assertGreaterEqual(len(rows), 3, "非空跑：三档 profile 各写一行失败账")
        # ★ 矩阵 #15/§8.1 的那句 SQL：
        self.assertEqual(0, self.count_sql("WHERE error_type='unknown'"),
                         "有链漏写 kind ⇒ 被归成 unknown ⇒ 实现缺陷，不是样本")
        self.assertEqual(0, self.count_sql("WHERE success=1 AND error_type IS NOT NULL"))
        for row in rows:
            with self.subTest(model=row["model"], mode=row["route_mode"]):
                self.assertEqual(0, row["success"])
                self.assertIsNotNone(row["error_type"])
                self.assertNotIn(row["error_type"], LEDGER_SENTINELS,
                                 "账本哨兵只能由 `usage.py` 产出，链上只许写 provider 的 kind")
                head = str(row["error_type"]).split(":")[0]
                self.assertIn(head, PROVIDER_KINDS)
        self.assertEqual({"chat", "rag", "agent"}, {row["route_mode"] for row in rows})

    def test_a_zero_candidate_request_writes_no_row_at_all(self):
        """`requests_5m` 不含零候选请求（T5 裁定）⇒ 这条**行为**半段不许只在文档里。"""
        def raise_no_candidate(_profile, _registry, _health):
            raise NoCapableModelError(stage="enabled")

        with (mock.patch.object(llm, "plan", raise_no_candidate),
              self.assertRaises(NoCapableModelError)):
            llm.complete([{"role": "user", "content": "问题"}], mode="rag",
                         trace_id="t-zero")
        self.assertEqual([], self.rows())
        self.assertEqual(0, self.count_sql("WHERE 1=1"))
        self.serve(500)
        self._drive("rag", 500)
        self.assertEqual(0, self.count_sql("WHERE error_type='unknown'"))
        self.assertEqual(1, self.count_sql("WHERE 1=1"))           # 有失败账 ⇒ 计数没在骗自己


def _entry(**overrides) -> ModelDefinition:
    data = {
        "id": "guard-ornith", "provider": "ollama", "model": "ornith-1.5:9b-text",
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 100, "rag": 100, "tools": 100},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def _other() -> ModelDefinition:
    return _entry(id="guard-phi3", model="phi3:mini",
                  priority={"chat": 80, "rag": 80, "tools": 80})


# ==========================================================================
# 6b. 扫描 helper 的死代码闸（Task 9 评审 Minor 4 的反证）
# ==========================================================================
#: 本文件的扫描 helper 清单：每一枚都必须**被另一枚函数引用**，一枚都不许是死代码。
#: 「第三层到底是不是独立测量」以前只能靠人读码判断（`code_line_numbers()` 定义了但零
#: 使用 ⇒ 代码面其实是从「全文 − 散文」推导的）。现在把它做成闸：谁把代码面改回算术差、
#: 让 `code_hits()` / `code_line_numbers()` 失去调用者，这一枚立刻红。
SCAN_HELPERS = (
    "app_python_files", "relative", "docstring_and_comment_lines", "_count",
    "fulltext_hits", "prose_hits", "code_hits", "code_line_numbers",
    "ast_httpx_imports", "ast_httpx_egress_calls", "ast_endpoint_string_constants",
    "ast_credential_attribute_reads", "value_error_raises", "parse_matrix_rows",
)


def _module_functions(tree: ast.AST) -> list[ast.AST]:
    """顶层函数 + 顶层类里的方法（= 本文件里所有可能充当「调用者」的作用域）。"""
    out: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
        elif isinstance(node, ast.ClassDef):
            out.extend(m for m in node.body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return out


class ScanningHelpersAreAllLiveTests(unittest.TestCase):
    """「不许留着未使用的 helper 假装它在起作用」（评审 Minor 4 原话）的机器化。"""

    def test_every_scan_helper_has_a_caller_outside_itself(self):
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        scopes = _module_functions(tree)
        defined = {node.name for node in scopes}
        self.assertTrue(set(SCAN_HELPERS) <= defined,
                        "SCAN_HELPERS 列了本文件不存在的函数：这张清单自己漂了")
        used_by: dict[str, set[str]] = {name: set() for name in SCAN_HELPERS}
        for scope in scopes:
            for node in ast.walk(scope):
                if isinstance(node, ast.Name) and node.id in used_by and node.id != scope.name:
                    used_by[node.id].add(scope.name)
        dead = {name: sorted(callers) for name, callers in used_by.items() if not callers}
        self.assertEqual({}, dead,
                         "死掉的扫描 helper：它名义上在量的那一面其实没有任何人在算")

    def test_the_code_face_is_measured_from_line_sets_not_derived(self):
        """`code_hits()` 的**实现本体**必须按行集数，不许退回去算「全文 − 散文」的算术差。

        只核「helper 有人调用」挡得住死代码，挡不住「调用者换成了别的用例、第三层又变回
        推导」。所以这里直接看函数体：①必须引用 `code_line_numbers`（行集来源），
        ②不得引用 `fulltext_hits` / `prose_hits`（那两张表一旦被调用就说明差值在推导）。
        """
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        fn = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "code_hits")
        names = {node.id for node in ast.walk(fn) if isinstance(node, ast.Name)}
        self.assertIn("code_line_numbers", names,
                      "代码面不是按行集测出来的：`code_hits` 没引用 `code_line_numbers`")
        self.assertNotIn("fulltext_hits", names, "`code_hits` 在调用全文面 ⇒ 差值是推导的")
        self.assertNotIn("prose_hits", names, "`code_hits` 在调用散文面 ⇒ 差值是推导的")

    def test_the_code_face_helpers_are_called_from_the_layer_they_certify(self):
        """代码面的两枚 helper 必须由**第三层那几枚用例**调用（不是被随手塞在别处）。

        只核「有人调用」不够：把它们在别的用途里用一次也能过关，然后第三层又变回推导。
        所以这里点名要求 `code_hits` / `code_line_numbers` 的调用者落在
        `D6FullTextFieldTests` 的三个方法里（派生 vs 测量互验、分区自核、跨算法互验）。
        """
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        host = next(node for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name == "D6FullTextFieldTests")
        callers: set[str] = set()
        for method in host.body:
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(method):
                if isinstance(node, ast.Name) and node.id in {"code_hits", "code_line_numbers"}:
                    callers.add(method.name)
        self.assertEqual(
            {"test_fulltext_face_equals_code_face_plus_prose",
             "test_the_three_faces_are_measured_on_a_real_line_partition",
             "test_the_measured_code_face_is_confirmed_by_the_ast_face"},
            callers, "代码面的测量调用者必须留在第三层那几枚用例里")


# ==========================================================================
# 7. 矩阵收口：`docs/MODEL_ROUTER_V23_MATRIX.md` 的每一行必须有真实承载测试
# ==========================================================================
MATRIX_STATUSES = ("GREEN", "PENDING_EXTERNAL", "BLOCKED")
#: 表格列序（与文档同一份口径）。
MATRIX_COLUMNS = ("#", "用例", "方法", "预期", "承载测试", "状态")


def parse_matrix_rows(text: str) -> list[dict[str, str]]:
    """解析文档里的 19+1 表：只认「第一列是行号/行名」的那几张。"""
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != len(MATRIX_COLUMNS):
            continue
        if cells[0] == "#":
            continue                          # 表头：列序由 `test_document_exists_...` 统一钉
        if all(set(cell) <= {"-", ":"} and cell for cell in cells):
            continue                          # markdown 的分隔行（`| --- | --- |`）
        rows.append(dict(zip(MATRIX_COLUMNS, cells)))
    return rows


class MatrixDocumentClosureTests(unittest.TestCase):
    """文档与测试套件的耦合闸：**双向**（Task 9 评审 Minor 3 之后不再只是正向）。

    正向 = 矩阵里写的每一枚 node-id 都必须**真的存在**：改名 / 删例 / 把 PENDING 写成 PASS
    都会让本用例红，而只看文档的评审者不会发现「承载测试」是一枚不存在的字符串。
    反向 = 本文件的每一枚测试类都必须被矩阵点名一次，否则「套件新增一枚不挂表的例」
    在只有正向闸的年代永远绿。
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = MATRIX_DOC.read_text(encoding="utf-8")
        cls.rows = parse_matrix_rows(cls.text)

    def _test_index(self) -> dict[str, set[str]]:
        """{测试文件名: {`类::方法` ∪ 顶层函数名}}，按 AST 现算（不起 pytest）。"""
        index: dict[str, set[str]] = {}
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names: set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    for member in node.body:
                        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            names.add(f"{node.name}::{member.name}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
            index[path.name] = names
        return index

    def test_document_exists_with_the_full_matrix(self):
        self.assertTrue(MATRIX_DOC.is_file(), f"缺少 {MATRIX_DOC}")
        self.assertIn("| " + " | ".join(MATRIX_COLUMNS) + " |", self.text,
                      "表头列序不许漂")
        self.assertGreaterEqual(len(self.rows), 20, "19+1 = 20 行，缺行就是矩阵没收口")
        numbered = [row for row in self.rows if row["#"].isdigit()]
        self.assertEqual({str(i) for i in range(1, 20)}, {row["#"] for row in numbered})

    def test_every_row_carries_a_real_test_or_an_honest_status(self):
        index = self._test_index()
        for row in self.rows:
            with self.subTest(row=row["#"], case=row["用例"][:24]):
                self.assertIn(row["状态"], MATRIX_STATUSES,
                              "状态值域冻结：GREEN / PENDING_EXTERNAL / BLOCKED。"
                              "无 key 环境下的云端项只能 PENDING，不许写 PASS/FAIL")
                carriers = re.findall(
                    r"(test_[A-Za-z0-9_]+\.py)::([A-Za-z_][A-Za-z0-9_]*)::(test_[A-Za-z0-9_]+)",
                    row["承载测试"])
                if row["状态"] == "GREEN":
                    self.assertTrue(carriers, "GREEN 行必须给出至少一枚 node-id")
                for file_name, class_name, method in carriers:
                    self.assertIn(file_name, index, f"承载文件不存在：{file_name}")
                    self.assertIn(f"{class_name}::{method}", index[file_name],
                                  f"承载测试不存在：{file_name}::{class_name}::{method}")

    def test_every_guard_test_class_is_discoverable_from_the_document(self):
        """**反向**闸（Task 9 评审 Minor 3）：本文件的每一枚测试类都要被矩阵点名一次。

        原来的闸是单向的：文档写了不存在的例 ⇒ 红；套件里新增一枚不挂表的例 ⇒ 永远绿
        （评审原话「`_test_index()` 现算了全套件索引却只用于校验文档侧名字」）。这里把
        方向反过来：用 AST 现算本文件的测试类清单，逐枚要求在文档正文出现至少一次。
        口径修正：评审点名的「12 枚类名」按盘面事实是 **6 枚**（本文件 `class *Tests`
        共 6 张 / 29 枚用例，2026-09-24 实测），清单由 AST 现算所以新增类自动进分母。
        """
        tree = ast.parse(Path(__file__).resolve().read_text(encoding="utf-8"))
        classes = sorted(node.name for node in tree.body
                         if isinstance(node, ast.ClassDef)
                         and any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                                 and m.name.startswith("test_") for m in node.body))
        self.assertGreaterEqual(len(classes), 6, "本文件的测试类掉档：扫描件被删过了？")
        self.assertIn("MatrixDocumentClosureTests", classes, "闸自己必须在这张清单里")
        for name in classes:
            with self.subTest(cls=name):
                self.assertIn(name, self.text,
                              "套件里有这张类表、矩阵却没挂到 ⇒ 文档不可反向发现（单向闸）")

    def test_the_two_mandated_calibers_are_written_and_one_is_a_real_test(self):
        """§8 口径两句话 + 「unknown=0」不只是文档：本文件里必须有那枚真用例。"""
        self.assertIn("不含零候选请求", self.text)
        self.assertIn("error_type='unknown'", self.text)
        self.assertIn("UnknownAttributionTests", self.text)
        self.assertIn("PENDING_EXTERNAL", self.text)
        methods = {name for name in dir(UnknownAttributionTests) if name.startswith("test_")}
        self.assertEqual(2, len(methods))
        # unknown 不设观测键（与 success_rate 共线）⇒ 文档只许出现一次「为什么不加」，
        # 不许长出第 14 枚键的名字。
        self.assertIn("不设", self.text)
        self.assertIn("共线", self.text)
        self.assertLessEqual(self.text.count("unknown_rate"), 1)

    def test_pending_external_rows_are_the_cloud_entries_only(self):
        pending = [row for row in self.rows if row["状态"] == "PENDING_EXTERNAL"]
        self.assertTrue(pending, "云厂商实连条目必须逐行列出（Task 11 验收文档要抄它）")
        for row in pending:
            with self.subTest(row=row["#"]):
                self.assertTrue(any(word in (row["用例"] + row["方法"])
                                    for word in ("OpenAI", "DeepSeek", "Qwen", "云", "实连",
                                                 "LIVE-CLOUD")),
                                "PENDING_EXTERNAL 只允许用于需要云 key 的实连项")

    def test_shipped_registry_file_is_what_the_matrix_claims(self):
        """注册表条目与 §3 一致（矩阵 1/2/14 的前提，也是 `#16 providers` 的分母）。

        刻意在**清空 OS env** 下读：D1 的动态 enabled（`external ∧ 无 key ⇒ False`）让三朵云
        条目在无 key 的验收环境里全部 `enabled=False` ⇒ 可路由面只剩 `ollama`。这不是巧合，
        而是文档里 `PENDING_EXTERNAL` 那几行的机器化前提：哪天 `.env` 真放了 key，本用例与
        那几行一起进入「可改判」的状态（届时 C1–C4 的承载测试必须补上）。
        """
        path = str(BACKEND_DIR / "config" / "llm_registry.json")
        with mock.patch.dict(os.environ, {}, clear=True):
            registry = load_registry(path)
        self.assertEqual({"ollama-ornith", "ollama-phi3", "openai", "deepseek-chat",
                          "qwen-plus"}, set(registry.ids()))
        self.assertEqual({"openai", "deepseek-chat", "qwen-plus"},
                         {model.id for model in registry.models if model.external})
        self.assertEqual({"ollama"}, {model.provider for model in registry.models
                                      if model.enabled})
        self.assertEqual(0, len([m for m in registry.models if m.external and m.enabled]),
                         "无 key 环境里云端条目不许 enabled：那会让 #16/#17 的分母偷偷变大")


if __name__ == "__main__":
    unittest.main()
