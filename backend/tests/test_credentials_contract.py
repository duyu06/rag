from __future__ import annotations

import ast
import contextlib
import dataclasses
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import unittest
import uuid
import warnings
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import argon2  # 与 `app.credentials` 同一个第三方依赖，这里只要它的异常类做断言

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import cli, credentials, credentials_migration, user_store  # noqa: E402

#: `user_store.database_path` 在 **import 期**（会话护栏还没装上）的那一枚函数。
#: 收集期早于会话 fixture（conftest 自己的理由："护栏的重定向发生在用例开始时，比 import
#: 晚"），所以这里拿到的必然是产品代码那一份。护栏装上去之后再叫 `user_store.database_path()`，
#: 返回的是**改道之后**的路径——那是测试面的事实，拿它去钉"本模块读哪个 env 键"等于让护栏
#: 自证。只有钉 env 口径的用例用这一枚；钉"护栏在场"的用例走 `ledger_guard` 的公开口径。
RAW_DATABASE_PATH = user_store.database_path

#: 会话级护栏（`tests/conftest.py`）的对外口径。凭据表与账本同库同 env，所以"这张表有
#: 没有人盯"只能从护栏自己问出来；import 失败 = 护栏文件被删 = 全套件 collection error。
TESTS_DIR = BACKEND_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import conftest as ledger_guard  # noqa: E402


class Argon2ProfileTests(unittest.TestCase):
    def test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant(self):
        self.assertEqual(2, credentials.ARGON2_TIME_COST)
        self.assertEqual(19456, credentials.ARGON2_MEMORY_COST)
        self.assertEqual(1, credentials.ARGON2_PARALLELISM)

    def test_the_profile_does_not_budge_when_the_environment_is_poisoned(self):
        """SECA-19 / SEC-A-008 的那半条：**强度参数不是运维旋钮**。

        上面那条只钉住"今天这枚常量等于 19456"。它钉不住的是"这一枚从哪里来"：写成
        `int(os.environ.get('ARGON2_MEMORY_COST', 19456))` 之后它一字不差地继续绿，而
        现网只要设一枚环境变量就能静默降档（M16 就是这个形状，变异台第一跑正是它 SURVIVED）。
        所以这一例判的是**因果**：把档位 env 全部投毒成低配，模块重新执行一遍之后仍然
        只认代码里那一档。

        执行的是 `spec_from_file_location` 造出的**一枚只活在本例里的**模块对象，不是
        `importlib.reload(credentials)`：后者会把 `_HASHER`、`PasswordCapacityError` 换成
        第二份对象，而 `app.main` 在 import 期就把旧那枚类绑进了自己的 except 分支
        （`sec_a_fixtures` 头一段写的正是这笔税）。它只在执行期间挂一次 `sys.modules`
        （`@dataclass` 要按模块名回查命名空间），`finally` 里立刻摘掉，出了本例就不存在。
        """
        source = BACKEND_DIR / "app" / "credentials.py"
        probe_name = "_seca_profile_probe"
        with mock.patch.dict(
            os.environ,
            {
                "ARGON2_TIME_COST": "1",
                "ARGON2_MEMORY_COST": "1",
                "ARGON2_PARALLELISM": "4",
            },
        ):
            spec = importlib.util.spec_from_file_location(probe_name, source)
            probe = importlib.util.module_from_spec(spec)
            # `@dataclass` 在构造类时按 `sys.modules[cls.__module__]` 回查自己的命名空间
            # （`dataclasses._process_class`），所以临时注册是必需的，不是随手写法；
            # `finally` 里立刻摘掉——本例之外谁都不该看见这枚第二个 `credentials`。
            sys.modules[probe_name] = probe
            try:
                spec.loader.exec_module(probe)
            finally:
                sys.modules.pop(probe_name, None)
        self.assertEqual(2, probe.ARGON2_TIME_COST)
        self.assertEqual(19456, probe.ARGON2_MEMORY_COST)
        self.assertEqual(1, probe.ARGON2_PARALLELISM)
        # 常量对上了还不算：真正参与运算的是**构造出来的那台 hasher**，档位要问它自己。
        hasher = probe.hasher()
        self.assertEqual(2, hasher.time_cost)
        self.assertEqual(19456, hasher.memory_cost)
        self.assertEqual(1, hasher.parallelism)
        self.assertEqual(19456, credentials.hasher().memory_cost)  # 本例没有换掉活的那一份

    def test_hasher_exposes_one_shared_instance_at_that_profile(self):
        # 上游登录腿的测试会把 `credentials.hasher()` 返回对象的 verify 打桩：hasher() 每
        # 次新建实例的话，被换掉的就不是真正参与校验的那一个，桩会静默空转。
        shared = credentials.hasher()
        self.assertIs(shared, credentials.hasher())
        self.assertEqual(credentials.ARGON2_TIME_COST, shared.time_cost)
        self.assertEqual(credentials.ARGON2_MEMORY_COST, shared.memory_cost)
        self.assertEqual(credentials.ARGON2_PARALLELISM, shared.parallelism)

    def test_hashed_password_is_a_verifiable_argon2id_phc_string(self):
        encoded = credentials.hash_password("correct horse battery staple 12")
        self.assertTrue(encoded.startswith("$argon2id$"), encoded)
        outcome = credentials.verify_password(
            "correct horse battery staple 12",
            algorithm=credentials.ALGORITHM_ARGON2ID,
            encoded=encoded,
        )
        self.assertTrue(outcome.ok)
        self.assertFalse(outcome.needs_rehash)  # 刚按当前档位生成

    def test_a_wrong_password_does_not_verify(self):
        encoded = credentials.hash_password("right answer 1234567890")
        outcome = credentials.verify_password(
            "wrong answer 1234567890",
            algorithm=credentials.ALGORITHM_ARGON2ID,
            encoded=encoded,
        )
        self.assertFalse(outcome.ok)


class AlgorithmColumnTests(unittest.TestCase):
    """规格 §6.2：分派权威是列，编码串前缀只做交叉校验。"""

    def test_argon2_column_with_a_non_argon2_payload_is_a_hard_failure(self):
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                "x", algorithm=credentials.ALGORITHM_ARGON2ID, encoded="deadbeef"
            )

    def test_legacy_column_with_a_non_hex_payload_is_a_hard_failure(self):
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                "x",
                algorithm=credentials.ALGORITHM_LEGACY_SHA256,
                encoded="zz" * 32,
            )

    def test_argon2_column_with_a_right_prefix_and_an_unparseable_body_is_a_hard_failure(self):
        # "列说 argon2id、载荷是垃圾"这一类只有硬失败一种出口：库自己解不开 PHC 串时抛的是
        # VerificationError("Decoding failed")，让它裸逃出去上游就是 500，咽进 ok=False 就是
        # 静默的"口令错了"——后者会把一条脏数据变成永久登录不上且无人报错。
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                "p",
                algorithm=credentials.ALGORITHM_ARGON2ID,
                encoded="$argon2id$v=19$m=1,t=1,p=1$aaa$bbb",
            )

    def test_needs_rehash_on_a_non_phc_input_is_a_config_error_not_a_library_error(self):
        """台账 Task 1 那一格：`needs_rehash` 公开面的异常分类。

        `check_needs_rehash` 对非 PHC 串抛的是 `argon2.exceptions.InvalidHashError`（⊂ ValueError），
        让它裸逃出去就是上游一条与凭据无关的栈——而本模块给上游的分类只有
        `CredentialConfigError` 一种（同"前缀对、体内损坏"那一发的理由，`_verify_argon2` 里已认过
        一次）。翻成分类异常、原文留在 `__cause__`：定位能力一点没丢。
        """
        with self.assertRaises(credentials.CredentialConfigError) as caught:
            credentials.needs_rehash("not-a-phc-string")
        self.assertIsInstance(caught.exception.__cause__, argon2.exceptions.InvalidHashError)
        # 真 PHC 串照旧正常返回（这一格管的是"别把库异常放出去"，不是"什么都拒"）。
        self.assertFalse(
            credentials.needs_rehash(credentials.hash_password("a-password 123456")))

    def test_an_unregistered_algorithm_value_is_a_hard_failure_not_a_try_both(self):
        # 载荷故意用一条能对上 legacy 摘要的值：分派权威只有 algorithm 列这两枚取值，
        # 列写错时"猜一个算法试试"会让它悄悄按另一种算法放行。
        plain = "legacy-demo-password"
        with self.assertRaises(credentials.CredentialConfigError):
            credentials.verify_password(
                plain,
                algorithm="sha256",
                encoded=hashlib.sha256(plain.encode("utf-8")).hexdigest(),
            )

    def test_a_legacy_digest_still_authenticates_under_the_legacy_column(self):
        plain = "legacy-demo-password"
        encoded = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        outcome = credentials.verify_password(
            plain, algorithm=credentials.ALGORITHM_LEGACY_SHA256, encoded=encoded
        )
        self.assertTrue(outcome.ok)
        self.assertTrue(outcome.needs_rehash)  # legacy 永远要收敛


class DummyVerifyTests(unittest.TestCase):
    def test_dummy_verification_costs_one_argon2_run_and_never_succeeds(self):
        outcome = credentials.verify_dummy("anything at all 1234567890")
        self.assertFalse(outcome.ok)

    def test_the_dummy_payloads_own_plaintext_still_does_not_verify(self):
        # 这条腿的哈希和明文都是本模块自己造的，底层 verify 对那串明文返回"匹配"。把它喂
        # 进去必须照样 ok=False：调用方（未知账号 / 已停用 / 无凭据行）拿这个返回值当认证结论。
        outcome = credentials.verify_dummy(credentials._DUMMY_PLAINTEXT)
        self.assertIs(False, outcome.ok)
        # needs_rehash 仍取底层判定，不许顺手写成常量——它说的是档位漂移，与成败无关。
        self.assertEqual(
            credentials.needs_rehash(credentials.dummy_hash()), outcome.needs_rehash
        )

    def test_dummy_string_is_generated_with_the_current_profile(self):
        # 若 dummy 串档位与当前 profile 不一致，§7.3 的"工作量可比"就是空话。
        self.assertTrue(
            credentials.dummy_hash().startswith(
                f"{credentials.ARGON2_HASH_PREFIX}v=19$"
                f"m={credentials.ARGON2_MEMORY_COST},"
                f"t={credentials.ARGON2_TIME_COST},"
                f"p={credentials.ARGON2_PARALLELISM}$"
            )
        )


class CapacityGateTests(unittest.TestCase):
    """并发槽是可用性事实：耗尽只能以 PasswordCapacityError 出现，不许伪装成认证结论。"""

    def test_a_full_slot_pool_turns_an_argon2_verify_into_a_capacity_error(self):
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            with self.assertRaises(credentials.PasswordCapacityError):
                credentials.verify_password(
                    "x",
                    algorithm=credentials.ALGORITHM_ARGON2ID,
                    encoded=credentials.dummy_hash(),
                )

    def test_a_full_slot_pool_turns_the_dummy_path_into_a_capacity_error(self):
        # 哑校验若不占同一道闸，"账号不存在"那条腿就是绕过容量门的后门：攻击者拿不存在的
        # 账号刷，闸门一次都不拦。
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            with self.assertRaises(credentials.PasswordCapacityError):
                credentials.verify_dummy("x")

    def test_a_full_slot_pool_turns_a_provisioning_hash_into_a_capacity_error(self):
        # 写入侧（新建 / 改密 / 渐进重哈希共用的那一枚 `hash_password`）付的是**同一档**内存硬
        # 运算。它若留在闸门外，第一层"绑定内存硬运算"这句立身理由只对一半：每一次 provisioning
        # 写、每一次 legacy 渐进重哈希都是不受上限的 19 MiB 工作，DoS 面只是换了个入口。
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            with self.assertRaises(credentials.PasswordCapacityError):
                credentials.hash_password("a-good-password 123456")

    def test_one_slot_is_enough_for_a_verify_followed_by_a_hash(self):
        # `BoundedSemaphore` **不可重入**：写入侧一旦嵌在校验侧那一格里，同一线程第二次占槽就
        # 是自锁（症状正是上一例那个异常，且以 503 出去、看起来像"负载真的满了"）。这条把
        # "占→还→再占"钉成**串行**事实：整段只给一格，verify 与 hash 都必须做成，做完槽完整
        # 还回来——谁哪天把 provisioning 塞进 `argon2_slot()` 的 with 体内，这条当场红。
        slots = threading.BoundedSemaphore(1)
        encoded = credentials.hash_password("a-good-password 123456")
        with mock.patch.object(credentials, "_SLOTS", slots):
            outcome = credentials.verify_password(
                "a-good-password 123456",
                algorithm=credentials.ALGORITHM_ARGON2ID,
                encoded=encoded,
            )
            credentials.hash_password("another-good-password 789")
        self.assertTrue(outcome.ok)
        self.assertTrue(slots.acquire(blocking=False), "两笔运算都必须已归还自己的槽")

    def test_the_step_zero_probe_reserves_nothing_and_never_lies_when_full(self):
        # 步骤 0 那枚探针只回答"现在能不能占"，不许留下预约：占而不放等于闸门自己造一条
        # 饥饿通道（第一层从此永远 503）。所以它返回 True 之后同一格槽必须仍可被真正占走。
        slots = threading.BoundedSemaphore(1)
        with mock.patch.object(credentials, "_SLOTS", slots):
            self.assertTrue(credentials.capacity_available())
            self.assertTrue(credentials.capacity_available())
            with credentials.argon2_slot():
                self.assertFalse(credentials.capacity_available())
        self.assertTrue(slots.acquire(blocking=False), "探针自己不许占住任何一格")

    def test_the_slot_is_given_back_even_when_the_body_raises(self):
        # 漏还一次槽 = 容量永久缩一格，跑几轮就把整道门焊死（形同拒绝服务）。
        slots = threading.BoundedSemaphore(1)
        with mock.patch.object(credentials, "_SLOTS", slots):
            with self.assertRaises(ZeroDivisionError):
                with credentials.argon2_slot():
                    raise ZeroDivisionError
            self.assertTrue(
                slots.acquire(blocking=False), "异常路径必须归还槽位，且只归还一次"
            )

    def test_capacity_exhaustion_is_a_distinct_family_from_a_config_error(self):
        # 这两类在上游翻译成不同的 HTTP 语义；谁成了谁的子类，一条 except 就会顺带吃掉另一类。
        self.assertFalse(
            issubclass(
                credentials.PasswordCapacityError, credentials.CredentialConfigError
            )
        )
        self.assertFalse(
            issubclass(
                credentials.CredentialConfigError, credentials.PasswordCapacityError
            )
        )


class CentralisationScanTests(unittest.TestCase):
    """SECA-05：口令参与运算的 hashlib 命中面 == 豁免表，且豁免表只有一个常任成员。"""

    HASHES = re.compile(r"sha256|sha512|md5|blake2|pbkdf2")
    # 词面判定天然会被改名绕过（`pwd` / 一个不带口令字样的 str 变量），所以词表按"最可能被
    # 用来命名口令原料的字样"放宽：口令本字族、裸 plain/digest/hash、以及明文的常见变体。
    # (?<![a-z])…(?![a-z]) 这两道边界是防合成词误伤——实测 `hashlib.sha256(...).hexdigest()`
    # 的 unparse 文本里 digest 只以 `hexdigest` 的形态出现，加了边界就不会把非口令站点带进来。
    PASSWORD_WORDS = re.compile(
        r"(?i)password|passwd|secret"
        r"|(?<![a-z])(?:plain|digest|hash)(?![a-z])"
        r"|plain[-_]?(?:text|hash|pw)"
    )
    #: 过渡豁免表：口令哈希收进 `credentials.py` 是一个原子动作——认证腿切到 `user_store`
    #: 那一轮，`auth.py` 自己算摘要的那处站点与这张表里的条目必须同时消失（留着条目不等于
    #: 多一道保险，下面的等值钉会把空转的豁免直接判红）。今天它是空的；谁再往自己的模块里
    #: 加一处口令摘要，就得同时在这里留下一枚名字，而那一笔由等值钉负责追问。
    TRANSITIONAL_EXEMPT: frozenset[str] = frozenset()

    #: 同一个口令站点写成 hashlib 的五种绑法。只认 `import hashlib` + `hashlib.<algo>(...)`
    #: 那一种的话，其余四种是"整份文件从扫描面上消失"，连判红都不会有——漏判比误判贵。
    PASSWORD_SITE_SHAPES = (
        "import hashlib\n\n\ndef f(password):\n"
        "    return hashlib.sha256(password.encode('utf-8')).hexdigest()\n",
        "import hashlib as hl\n\n\ndef f(password):\n"
        "    return hl.sha256(password.encode('utf-8')).hexdigest()\n",
        "from hashlib import sha256\n\n\ndef f(password):\n"
        "    return sha256(password.encode('utf-8')).hexdigest()\n",
        "from hashlib import sha256 as s\n\n\ndef f(password):\n"
        "    return s(password.encode('utf-8')).hexdigest()\n",
        "from hashlib import *\n\n\ndef f(password):\n"
        "    return sha256(password.encode('utf-8')).hexdigest()\n",
    )
    #: 反向样本：缓存键一类的非口令摘要，形态与上面逐一对应，一条都不许进命中集。
    NON_PASSWORD_SHAPES = (
        "import hashlib\n\n\ndef f(payload):\n"
        "    return hashlib.sha256(payload.encode('utf-8')).hexdigest()\n",
        "import hashlib as hl\n\n\ndef f(payload):\n"
        "    return hl.sha256(payload.encode('utf-8')).hexdigest()\n",
        "from hashlib import sha256\n\n\ndef f(payload):\n"
        "    return sha256(payload.encode('utf-8')).hexdigest()\n",
        "from hashlib import sha256 as s\n\n\ndef f(payload):\n"
        "    return s(payload.encode('utf-8')).hexdigest()\n",
    )
    _STAR = "*"

    @classmethod
    def _hashlib_bindings(cls, tree: ast.AST) -> dict[str, str]:
        """本文件里由 hashlib 绑定的名字 -> 它实际指向的算法名（模块本身记作 `hashlib`）。

        三种绑法都要认：`import hashlib`（含 `import hashlib.blake2b`，它绑的还是 hashlib）、
        `import hashlib as hl`、`from hashlib import sha256 [as s]`。别名要记回原算法名，
        否则 `from hashlib import sha256 as s` 换个名字就把算法名本身从判据里抹掉了。
        """
        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "hashlib":
                        bindings[alias.asname or "hashlib"] = "hashlib"
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] != "hashlib":
                    continue
                for alias in node.names:
                    if alias.name == cls._STAR:
                        # 星号导入绑定了哪些名字静态不知道，只能记下"这文件里有这回事"。
                        bindings[cls._STAR] = cls._STAR
                    else:
                        bindings[alias.asname or alias.name] = alias.name
        return bindings

    @classmethod
    def _hashlib_password_calls(cls, tree: ast.AST) -> list[tuple[int, str]]:
        """一棵 AST 里"口令参与运算的 hashlib 调用点"，返回 (行号, 调用文本)。"""
        bindings = cls._hashlib_bindings(tree)
        sites: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if bindings.get(func.value.id) != "hashlib":
                    continue
                algorithm = func.attr
            elif isinstance(func, ast.Name):
                algorithm = bindings.get(func.id)
                if algorithm is None and cls._STAR in bindings:
                    algorithm = func.id
                if algorithm is None:
                    continue
            else:
                continue
            text = ast.unparse(node)
            if cls.HASHES.search(algorithm) and cls.PASSWORD_WORDS.search(text):
                sites.append((node.lineno, text))
        return sites

    def _hashlib_password_sites(self) -> list[str]:
        hits: list[str] = []
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for lineno, text in self._hashlib_password_calls(tree):
                hits.append(f"{path.relative_to(BACKEND_DIR)}:{lineno} {text}")
        return hits

    def _exemption_table(self) -> frozenset[str]:
        return frozenset({"app/credentials.py"}) | self.TRANSITIONAL_EXEMPT

    @staticmethod
    def _relative_dir(site: str) -> str:
        return site.split(":")[0].replace("\\", "/")

    def test_only_credentials_module_hashes_passwords(self):
        exempt = self._exemption_table()
        self.assertEqual(
            [],
            [
                site
                for site in self._hashlib_password_sites()
                if self._relative_dir(site) not in exempt
            ],
            "表外出现了口令摘要：收进 app/credentials.py，或（仅当它是一次真实的过渡态）"
            f"在 CentralisationScanTests.TRANSITIONAL_EXEMPT 里留下文件名。当前豁免表：{sorted(exempt)}",
        )

    def test_the_exemption_table_is_equal_to_the_hit_set(self):
        # 上一钉管"表外不许有命中"，这一钉管反向"表里不许有表外用不上的豁免"。
        hits = {self._relative_dir(site) for site in self._hashlib_password_sites()}
        self.assertEqual(
            set(self._exemption_table()), hits,
            "豁免表与命中集不等值：表里留下的名字已经没有对应的口令摘要站点——那是一条空转的"
            "豁免（收拢已经完成还挂着条目）。改的是 CentralisationScanTests.TRANSITIONAL_EXEMPT，"
            f"不是这条断言。表={sorted(self._exemption_table())} 命中={sorted(hits)}",
        )

    def test_the_credentials_exemption_is_earned_by_an_actual_hit(self):
        # 豁免表是"这里允许出现口令哈希"的声明，声明必须由真命中兑现。本模块的口令运算是
        # 按词面认出来的（词表见上），所以形参一旦改成不带信号的名字，这处站点会静默消失，
        # 豁免就变成自证；恰等于 1 也防住"复制出一份第二个口令摘要点"。
        sites = [
            site
            for site in self._hashlib_password_sites()
            if self._relative_dir(site) == "app/credentials.py"
        ]
        self.assertEqual(1, len(sites), sites)

    def test_every_hashlib_binding_shape_reaches_the_same_password_site(self):
        for source in self.PASSWORD_SITE_SHAPES:
            with self.subTest(binding=source.splitlines()[0]):
                self.assertEqual(
                    1, len(self._hashlib_password_calls(ast.parse(source)))
                )

    def test_a_non_password_digest_stays_out_of_the_hit_set_under_every_binding(self):
        for source in self.NON_PASSWORD_SHAPES:
            with self.subTest(binding=source.splitlines()[0]):
                self.assertEqual([], self._hashlib_password_calls(ast.parse(source)))


class _CredentialDbPerTest(unittest.TestCase):
    """每例一份临时库：`CONVERSATION_DB_PATH` 指到 tmp，收尾还原 env。

    三件事一起办：
    ① 凭据表与会话面**同库**，用例不各占一份文件就会互相撞
    `user_credentials.username` 这条主键（同名账号在这些用例里是常态）。
    ② 出厂默认是**相对**路径 `data/conversations.db` ⇒ 不重定向的用例等于往仓库里
    那份真库写假凭据行。
    ③ **只换 env，不 reload、不碰 `app.config`**：`user_store` 没有 import 期状态
    （路径每次连接时现读 env，schema 只有 `ensure_user_credentials_schema()` 才建），
    所以换 env 就已经换完了库；reload 换来的模块对象反而会让 `mock.patch.object` 之类
    "先拿属性再打桩"的写法打在旧对象上。`settings` 更碰不得——它是进程级单例，
    `app.main` / `app.llm.*` 在 import 期就把那个对象绑进了自己的命名空间，reload 换掉
    的只是 `app.config.settings` 这个模块属性，后面跑的用例改的是再没人读的那一份，
    症状是一份不相干的 FileNotFoundError。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_db_path = os.environ.get("CONVERSATION_DB_PATH")
        os.environ["CONVERSATION_DB_PATH"] = str(Path(self._tmp.name) / "creds.db")
        user_store.ensure_user_credentials_schema()

    def tearDown(self):
        if self._saved_db_path is None:
            os.environ.pop("CONVERSATION_DB_PATH", None)
        else:
            os.environ["CONVERSATION_DB_PATH"] = self._saved_db_path
        self._tmp.cleanup()


class UserStoreSchemaTests(_CredentialDbPerTest):
    def test_column_set_may_hold_a_hash_but_never_a_plaintext_field(self):
        """SECA-08：明文字段不是"没人写"，是"不存在可写的地方"。"""
        columns = set(user_store.column_names())
        self.assertIn("password_hash", columns)
        self.assertTrue({"password", "plaintext_password", "raw_password"}.isdisjoint(columns))
        self.assertNotIn(
            "algorithm",
            inspect.signature(user_store.create_argon2).parameters,
        )
        self.assertNotIn(
            "algorithm",
            inspect.signature(user_store.set_password_argon2).parameters,
        )

    def test_created_rows_are_always_argon2id(self):
        """SECA-01 的持久层半边：普通写路径拿不到 legacy 这个取值。"""
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        self.assertTrue(record.password_hash.startswith("$argon2id$"))
        self.assertEqual(1, record.credentials_version)

    def test_the_algorithm_check_is_the_last_line_of_defence(self):
        """台账 Task 2 那一格：CHECK 约束本身此前**没有任何直接钉**。

        函数面拿不到第三枚取值（`create_argon2` 只写 argon2id、`import_legacy_digest` 只写
        legacy-sha256），所以"这张表里只可能有这两种算法"这句话的全部强制力都落在 `:34` 那条
        DDL 上——而 DDL 是会被 `ALTER`、被恢复来的备份、被第二个写方绕过的东西。这一例故意
        不经过任何函数面，直插一列 `bcrypt`：它必须撞在 CHECK 上，而不是安静地多出一行
        谁都不认识的凭据（那一行既过不了 `verify_password` 的分派，也数不进 `legacy_count`）。
        """
        user_store.create_argon2("admin", plain_password="a-good-password 123",
                                 must_change=False)
        with contextlib.closing(sqlite3.connect(user_store.database_path())) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    f"INSERT INTO {user_store.TABLE_NAME}"
                    " (username, algorithm, password_hash, updated_at)"
                    " VALUES ('probe', 'bcrypt', 'not-a-real-hash', '2026-01-01T00:00:00+00:00')"
                )
        self.assertEqual({credentials.ALGORITHM_ARGON2ID},
                         set(user_store.count_by_algorithm()))

    def test_only_the_restricted_importer_can_create_a_legacy_row(self):
        self.assertTrue(
            user_store.import_legacy_digest(
                "sales01", hashlib.sha256(b"sales123").hexdigest(), must_change=True
            )
        )
        record = user_store.get_record("sales01")
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
        self.assertTrue(record.must_change)
        self.assertEqual(
            {credentials.ALGORITHM_LEGACY_SHA256: 1},
            {k: v for k, v in user_store.count_by_algorithm().items() if v},
        )

    def test_the_column_list_authority_is_the_table_and_the_insert(self):
        """列序不需要人记：`_COLUMNS` 由表验货，INSERT 由 `_COLUMNS` 生成。

        三条钉连成一链：往 `_SCHEMA` 加一列而忘了 `_COLUMNS` ⇒ 第一条红；改了
        `_COLUMNS` 而忘了表 ⇒ 同一条红；列名段被人手改歪（收拢前的写法复辟）⇒ 第二条红；
        加了列忘了给 VALUES 补一个占位 ⇒ 第三条红。SQL 文本本身与收拢前两处手写语句逐字
        相同，所以这不是一次语义改动。
        """
        self.assertEqual(tuple(user_store.column_names()), user_store._COLUMNS)
        statement = user_store._insert_sql(ignore_conflicts=False)
        self.assertEqual(
            "INSERT INTO user_credentials (username, algorithm, password_hash,"
            " credentials_version, must_change, failed_attempts, locked_until, updated_at)"
            " VALUES (?, ?, ?, 1, ?, 0, NULL, ?)",
            statement,
        )
        self.assertEqual(
            statement + " ON CONFLICT(username) DO NOTHING",
            user_store._insert_sql(ignore_conflicts=True),
        )
        # 每一列都要有归属：5 个 `?` 之外那 3 列是字面量（1 / 0 / NULL）。
        self.assertEqual(len(user_store._COLUMNS), statement.count("?") + 3)


class UserStoreIsolationTests(_CredentialDbPerTest):
    """规格 §6.1 的"同库"半边：一个真源、一条解析路径、读路径不建表。"""

    def test_the_effective_path_is_the_siblings_own_env_key(self):
        # 默认值与覆盖取值都是 `conversation_store` / `llm.usage` 用的那一枚 env 键。分叉
        # 的代价不是理论：`settings` 会读 `.env`（dotenv），两个兄弟不读——运维把该键在
        # `.env` 里挪成绝对路径时，只有凭据表跟着搬，备份与轮转就跟着错文件走。
        # 走 `RAW_DATABASE_PATH`（import 期那一份）而不是 `user_store.database_path`：后者在
        # 会话里已被护栏包走，env 清空时它给的是改道目标，那样这条钉测的就是护栏而不是口径。
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Path("data/conversations.db"), RAW_DATABASE_PATH())
        with mock.patch.dict(
            os.environ, {"CONVERSATION_DB_PATH": "elsewhere/creds.db"}, clear=True
        ):
            self.assertEqual(Path("elsewhere/creds.db"), RAW_DATABASE_PATH())

    #: 同一个"从 `app` 里拿配置模块"的动作在 AST 里有几种写法。`from app import config` 那一发
    #: 是本轮补的（台账 Task 2 的移交项）：只读 `ImportFrom.module` 时它报的是 `app`，
    #: `config` 藏在 alias 上 ⇒ 整条分叉路径从判据里消失，连判红都不会有。
    CONFIG_BINDING_SHAPES = (
        "from app import config\n",
        "from app import config as cfg\n",
        "import app.config\n",
        "import app.config as cfg\n",
        "from . import config\n",
        "from app.config import settings\n",
    )

    @staticmethod
    def _imported_names(source: str) -> list[str]:
        """一份源码里所有"可能被用来指到某模块"的绑定名（模块点分路径 + 被绑的名字）。"""
        names: list[str] = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.append(node.module)
                names.extend(alias.name for alias in node.names)
        return names

    @classmethod
    def _config_bindings(cls, source: str) -> list[str]:
        return [name for name in cls._imported_names(source)
                if "config" in name.split(".")[-1]]

    def test_the_module_never_resolves_the_shared_file_through_settings(self):
        # 上一条管"取值口径"，这一条管"不许有第二个口径"：import `app.config` 就等于给
        # `CONVERSATION_DB_PATH` 长出一个 dotenv 侧的真源（env 与 `.env` 谁赢取决于谁先读）。
        self.assertEqual(
            [],
            self._config_bindings(Path(user_store.__file__).read_text(encoding="utf-8")),
            "user_store 的 import 面混进了配置模块",
        )

    def test_every_way_of_binding_the_config_module_is_recognised(self):
        """门自己的覆盖面：六种绑法每种都判得出，缺一种就是"整条分叉路径不可见"。

        判据只能写成"每一种都被认出来"而不是"命中数恰好是 N"：`from app import config` 那一条
        在加宽前给的是空集，那正是它要红的那一发（实测：把 `_imported_names` 退回只读
        `ImportFrom.module` 的旧写法，这一枚 subTest 立刻指名 `from app import config`）。
        """
        for source in self.CONFIG_BINDING_SHAPES:
            with self.subTest(binding=source.strip()):
                self.assertTrue(
                    self._config_bindings(source),
                    f"这一形态没被认成配置模块绑定：{source!r}")

    def test_a_benign_import_face_is_not_reported(self):
        """反向：本模块真实的 import 面（`os`/`sqlite3`/`app.credentials`）一条都不许进命中集。"""
        for source in (
            "import os\nimport sqlite3\nfrom app import credentials\n",
            "from contextlib import closing\nfrom pathlib import Path\n",
        ):
            with self.subTest(source=source.splitlines()[0]):
                self.assertEqual([], self._config_bindings(source))

    def test_read_paths_never_create_the_schema(self):
        # 读函数顺手建表 = 在任何一次"env 被 clear 掉 ⇒ 路径退回默认值"的调用里往那个
        # 文件提交一次 DDL，落点可能是生产库，而且护栏看不见（它只包 usage）。0 字节就是
        # "一条 DDL 都没提交"的证据。
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "unseeded.db"
            with mock.patch.object(user_store, "database_path", return_value=target):
                with self.assertRaises(sqlite3.OperationalError):
                    user_store.get_record("admin")
                with self.assertRaises(sqlite3.OperationalError):
                    user_store.list_records()
                # PRAGMA 认不出表只给空结果，不建表也不报错。
                self.assertEqual([], user_store.column_names())
            self.assertEqual(0, target.stat().st_size)

    def test_a_guard_can_redirect_this_module_through_the_same_seam(self):
        # `tests/conftest.py` 包 `usage` 的手法就是换掉模块级 `database_path`
        # （`LedgerGuard.install`）。本模块必须能被同一个手法包走——那是凭据表在 env 被清掉
        # 时仍不落生产库的唯一兜底，也是本文件不 reload 的前提。
        wrapped = Path(self._tmp.name) / "redirected.db"
        env_db = Path(os.environ["CONVERSATION_DB_PATH"])

        def rows(path: Path) -> int:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
            try:
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (user_store.TABLE_NAME,),
                ).fetchone()
                if table is None:
                    return -1
                count = connection.execute(
                    f"SELECT COUNT(*) FROM {user_store.TABLE_NAME}"
                ).fetchone()[0]
                return int(count)
            finally:
                connection.close()

        with mock.patch.object(user_store, "database_path", return_value=wrapped):
            user_store.ensure_user_credentials_schema()
            user_store.create_argon2(
                "admin", plain_password="a-good-password 123", must_change=False
            )
        self.assertEqual(1, rows(wrapped))
        self.assertEqual(0, rows(env_db))


class UserStoreTransactionTests(_CredentialDbPerTest):
    """SECA-11 / SECA-12：新 hash、bump、清锁必须是一个提交单位。"""

    def test_password_change_bumps_version_and_clears_lock_state_together(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
        user_store.record_login_failure(
            "admin", max_attempts=1, lock_seconds=900
        )
        self.assertIsNotNone(user_store.get_record("admin").locked_until)

        new_version = user_store.set_password_argon2(
            "admin", plain_password="new-password 123456", must_change=False
        )
        record = user_store.get_record("admin")
        self.assertEqual(new_version, record.credentials_version)
        self.assertEqual(2, record.credentials_version)
        self.assertFalse(record.must_change)
        self.assertEqual(0, record.failed_attempts)
        self.assertIsNone(record.locked_until)

    def test_delete_record_answers_whether_a_row_was_actually_taken_away(self):
        """台账 Task 2 那一格：`delete_record` 此前只在别的用例里**当夹具用**，它自己没钉。

        它是这张表上唯一的"抹掉一行"，`True`/`False` 分别是"这一行现在没了"与"这个人本来
        就没有行"——把返回值读丢，删错名字就是一件无人知道的事（口令还在、行却没了的那种）。
        """
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
        self.assertFalse(user_store.delete_record("no-such-account"))
        self.assertTrue(user_store.delete_record("admin"))
        self.assertIsNone(user_store.get_record("admin"))
        # 第二次删同一枚名字：行已经不在了，答案必须是"我没有抹掉任何东西"。
        self.assertFalse(user_store.delete_record("admin"))

    def test_clear_login_failures_only_moves_the_counter_and_is_idempotent(self):
        """同一条台账的另一格：清计数在成功登录腿上被间接演过，它自己的两条边界没有钉。

        两条边界各挡一种事故：**只**动 `failed_attempts`/`locked_until`（清一次失败计数不该
        把人的口令纪元推进、也不该改 `must_change`——那是 §6.3 的会话失效判定在读的字段）；
        未知账号静默无操作（登录腿之后才清，清不中也得能收工，且不给谁新建一行）。
        """
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=True)
        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
        locked = user_store.get_record("admin")
        self.assertIsNotNone(locked.locked_until)
        user_store.clear_login_failures("admin")
        cleared = user_store.get_record("admin")
        self.assertEqual(0, cleared.failed_attempts)
        self.assertIsNone(cleared.locked_until)
        self.assertEqual(locked.credentials_version, cleared.credentials_version)
        self.assertTrue(cleared.must_change)
        user_store.clear_login_failures("no-such-account")
        self.assertEqual(["admin"], sorted(r.username for r in user_store.list_records()))

    def test_a_failing_version_bump_rolls_back_the_new_hash(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=False)
        before = user_store.get_record("admin")
        with mock.patch.object(
            user_store, "_bump_and_clear", side_effect=user_store.CredentialStoreError("boom")
        ):
            with self.assertRaises(user_store.CredentialStoreError):
                user_store.set_password_argon2(
                    "admin", plain_password="new-password 123456", must_change=False
                )
        after = user_store.get_record("admin")
        self.assertEqual(before.password_hash, after.password_hash)
        self.assertEqual(before.credentials_version, after.credentials_version)

    def test_rehash_is_guarded_by_the_version_it_was_computed_for(self):
        user_store.create_argon2("admin", plain_password="old-password 123456", must_change=True)
        # 版本快照取在**重哈希之前**：下面两条钉子都由它推出来，这样"实现顺手 bump 了版本"
        # 这一类变异体既过不了第二条，也过不了第三条（陈旧版本号恰好命中当前行）。
        version_before = user_store.get_record("admin").credentials_version
        self.assertTrue(
            user_store.apply_rehash(
                "admin",
                plain_password="old-password 123456",
                must_change=True,
                expected_version=version_before,
            )
        )
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, record.algorithm)
        # 渐进重哈希**不 bump 版本**（SECA-01 之外的另一条独立不变量：登录只改强度，
        # 不改会话）——版本一涨，§6.3 的 token 失效判定就把一次正常登录变成了强制重登。
        self.assertEqual(version_before, record.credentials_version)
        # 陈旧版本（并发下别人已经改过密）⇒ 整条 UPDATE 不落地。+1 是从上面那枚**重哈希
        # 前**的快照推出来、从没落进库里的版本号：一旦 rehash 意外 bump 了版本，这条就会
        # 反过来落地并返回 True（旧写法 `record.credentials_version + 5` 在两种实现下都
        # 返回 False，等于没钉）。
        self.assertFalse(
            user_store.apply_rehash(
                "admin",
                plain_password="old-password 123456",
                must_change=False,
                expected_version=version_before + 1,
            )
        )
        after = user_store.get_record("admin")
        self.assertTrue(after.must_change)
        self.assertEqual(version_before, after.credentials_version)
        self.assertEqual(record.password_hash, after.password_hash)


class CredentialStoreErrorSurfaceTests(_CredentialDbPerTest):
    """存储层的三条出口：异常消息、异常链、dataclass repr——都不许带驱动文案或口令材料。"""

    def test_a_duplicate_username_raises_a_store_error_with_the_cause_kept(self):
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
        first_hash = user_store.get_record("admin").password_hash
        with self.assertRaises(user_store.CredentialStoreError) as caught:
            user_store.create_argon2(
                "admin", plain_password="another-good-password 456", must_change=False
            )
        message = str(caught.exception)
        # 裸 `sqlite3.IntegrityError` 会把驱动文案原样送进服务端日志与运维控制台；
        # `CredentialStoreError` 才是本模块对外的分类。原文仍在 `__cause__` 上。
        self.assertNotIn("UNIQUE constraint", message)
        self.assertNotIn("user_credentials.username", message)
        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        self.assertIn("admin", message)
        self.assertNotIn("another-good-password 456", f"{message}{caught.exception.__cause__!r}")
        # 撞键那条 INSERT 回滚，已有行原样不动。
        self.assertEqual(first_hash, user_store.get_record("admin").password_hash)

    def test_the_missing_account_message_names_nothing_the_response_face_could_leak(self):
        # §9.1 把「有身份无凭据行」折成与口令错同一条 401（`用户名或密码错误` /
        # `invalid_credentials`）。这条异常正是在登录/改密腿上被抓的，消息里带账号名就
        # 等于给响应面或审计 detail 递了一枚"这个用户名存在吗"的探针。
        with self.assertRaises(user_store.CredentialStoreError) as caught:
            user_store.set_password_argon2(
                "nobody-here", plain_password="a-good-password 123", must_change=False
            )
        self.assertEqual(user_store.ACCOUNT_MISSING_MESSAGE, str(caught.exception))
        self.assertNotIn("nobody-here", str(caught.exception))

    def test_a_record_repr_does_not_carry_the_password_hash(self):
        # 本模块没有 logging，repr 就是密文材料进日志的唯一通道（口径同 `SecretStr`）。
        user_store.create_argon2("admin", plain_password="a-good-password 123", must_change=False)
        record = user_store.get_record("admin")
        self.assertTrue(record.password_hash.startswith("$argon2id$"))
        self.assertNotIn(record.password_hash, repr(record))
        self.assertNotIn("$argon2id$", repr(record))
        # repr=False 只关掉打印面：比较与字段本身都还在（等值钉仍按全部列判）。
        self.assertEqual(record, user_store.get_record("admin"))


class _ArtifactFixtures(_CredentialDbPerTest):
    """`_CredentialDbPerTest` + 升级工件的形状真源（一份，两处用例共读）。

    为什么提上来而不是在新类里再抄一遍：§8.2 的模块级用例与 §11 的 CLI 用例判的是**同一份
    输入**（"什么算一份合法工件"由 `read_artifact` 那三枚顶层键说了算）。抄第二份 `_valid()`
    就等于让"合法工件"长出一个测试侧真源，将来收紧顶层键时只改一处、另一处继续喂脏值还判绿。

    默认路径（`data/legacy_credentials.json`，按**进程 cwd** 解析）那格另给一枚上下文管理器：
    它必须落在临时目录里，否则"让默认路径真的命中一份工件"这件事等于往 `backend/data/` 写
    凭据材料（§8.2 明令禁止的位置）。本夹具给的 `CONVERSATION_DB_PATH` 是**绝对**路径（临时目录
    里那个文件），所以换 cwd 不跟着换库——那是刻意复刻 §17 L7 记下的分叉形状，不是现网形态：
    compose 挂的是**目录**（`docker-compose.yml` 的 `./backend/data:/app/data`），`backend/.env`
    里那枚键仍是相对值，默认部署下库与工件同源。
    """

    def _artifact(self, payload: dict) -> Path:
        path = Path(self._tmp.name) / "artifact.json"
        path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        return path

    def _valid(self, block: dict[str, str]) -> dict:
        """一份形态合法的工件（三枚顶层键都在）：只改 credentials 的用例用它，免得每处重抄。"""
        return {
            "generated_at": "2026-09-25T00:00:00+00:00",
            "source": "app/auth.py@pre-SEC-A",
            "credentials": block,
        }

    @contextlib.contextmanager
    def _with_artifact_at_default_path(self, payload: dict) -> Iterator[Path]:
        """把 `payload` 放到**默认路径**上并站在临时目录里：交出那份文件的绝对路径。

        序列化发生在 chdir 之前（`json.dumps` 不碰 cwd，写文件才碰），yield 出去的绝对路径
        在退出上下文之后仍然可用于 `exists()` 断言——"工件没被谁吃掉"正是调用方要问的话。
        """
        document = json.dumps(payload)
        original = os.getcwd()
        os.chdir(self._tmp.name)
        try:
            (Path("data")).mkdir(parents=True, exist_ok=True)
            (Path("data") / "legacy_credentials.json").write_text(
                document, encoding="utf-8", newline="\n")
            yield Path(self._tmp.name) / "data" / "legacy_credentials.json"
        finally:
            # 必须回位：`tearDown` 删临时目录时进程还站在里面的话，Windows 上删不掉。
            os.chdir(original)

    @contextlib.contextmanager
    def _standing_where_the_default_path_is_empty(self) -> Iterator[None]:
        """站在一份**没有**工件的临时目录里（默认路径按 cwd 解析 ⇒ 这就是全新安装）。"""
        original = os.getcwd()
        os.chdir(self._tmp.name)
        try:
            yield
        finally:
            os.chdir(original)


class MigrationPathTests(_ArtifactFixtures):
    """规格 §8.2 的升级腿：`data/legacy_credentials.json` → legacy 行。

    夹具用 `_ArtifactFixtures`（底下就是 `_CredentialDbPerTest`）——换 env 而不 reload 的理由
    写在那份夹具的文档字符串里（本类的用例同样依赖"模块对象不被换掉"：`mock.patch.object`
    打在旧对象上是静默空转）。
    """

    def test_a_fresh_install_without_an_artifact_imports_nothing(self):
        """SECA-04b：全新安装不生产 legacy 行，这是 §8.2 分家的落点。"""
        report = credentials_migration.import_from_artifact(
            Path(self._tmp.name) / "does-not-exist.json"
        )
        self.assertFalse(report.artifact_present)
        self.assertEqual((), report.imported)
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_the_default_input_path_reports_where_it_actually_looked(self):
        """默认路径没命中时，`reason` 必须带上它**解析到哪儿**了。

        `CONVERSATION_DB_PATH` 给绝对值时（容器 / systemd 形态）库跟着 env 搬走，工件仍钉在 cwd
        底下——一次谁也没被迁移的升级就带着"全新安装不生产 legacy 行"这句话绿过去，而 SEC-A-003
        要的是升级这一腿真的把人迁过去。把解析后的绝对路径打进报告，是运维一眼看出走偏的最小成本。
        """
        directory = Path(self._tmp.name)
        original = os.getcwd()
        os.chdir(directory)
        try:
            looked = str(credentials_migration.LEGACY_INPUT_PATH.resolve())
            report = credentials_migration.import_from_artifact()
            # 显式传路径时不许被这条口径波及：落点是调用方自己选的，指错了也是它的事。
            explicit = credentials_migration.import_from_artifact(directory / "else-where.json")
        finally:
            # 必须在 `tearDown` 之前回位：夹具清理临时目录时进程还站在里面，Windows 上删不掉。
            os.chdir(original)
        self.assertFalse(report.artifact_present)
        self.assertEqual((), report.imported)
        self.assertIn(looked, report.reason)
        self.assertNotIn(looked, explicit.reason)

    def test_imported_rows_are_legacy_and_flagged_for_forced_change(self):
        path = self._artifact(
            {
                "generated_at": "2026-09-25T00:00:00+00:00",
                "source": "app/auth.py@pre-SEC-A",
                "credentials": {"admin": "a" * 64},
            }
        )
        report = credentials_migration.import_from_artifact(path)
        self.assertEqual(("admin",), report.imported)
        record = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
        self.assertTrue(record.must_change)
        self.assertEqual(1, credentials_migration.status().legacy_count)

    def test_reimporting_does_not_downgrade_an_already_upgraded_row(self):
        user_store.create_argon2("admin", plain_password="already-migrated 123456", must_change=False)
        path = self._artifact({"generated_at": "x", "source": "y", "credentials": {"admin": "a" * 64}})
        # 数一下写手被叫了几次：今天"不降级"是 `INSERT ... DO NOTHING` 兜住的，所以只钉结果
        # 的话，"根本不试"与"试一次靠 SQL 吞掉"两种实现同形。`import_legacy_digest` 哪天改成
        # UPSERT（改密/reset 那条腿迟早有人想复用），前者仍然安全、后者当场把 argon2id 行写回
        # legacy——那枚 `call_count == 0` 就是留给那一天的门。
        with mock.patch.object(
            user_store, "import_legacy_digest", wraps=user_store.import_legacy_digest
        ) as writer:
            report = credentials_migration.import_from_artifact(path)
        self.assertEqual((), report.imported)
        self.assertEqual(("admin",), report.skipped)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
        self.assertEqual(0, writer.call_count, "已存在行被跳过的意思是**不去写它**")

    def test_a_malformed_artifact_is_rejected_as_a_whole(self):
        for payload in (
            {"generated_at": "x", "source": "y", "credentials": {"admin": "not-hex"}},
            {"generated_at": "x", "source": "y", "credentials": ["admin"]},
            {"generated_at": "x", "source": "y", "credentials": {}, "oops": 1},
        ):
            with self.subTest(keys=sorted(payload)):
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(self._artifact(payload))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_an_artifact_that_cannot_be_read_is_rejected_like_a_malformed_one(self):
        """"在场但读不出来"与"形态错"是同一条出路：整份拒，消息点名路径。

        三种都真到得了：路径被目录占住（`IsADirectoryError`）、编码不是 UTF-8（Windows 上从
        记事本/Excel 导出来的 GBK 与 UTF-16 都不 exotic）。少这道拦截，它们今天以裸异常的形态
        往上逃——那不是"导入这一步整份拒、运维一次修完"的形状，而读一半内容再逃也不是。
        """
        root = Path(self._tmp.name)
        as_directory = root / "artifact-dir.json"
        as_directory.mkdir()
        payload = {
            "generated_at": "2026-09-25T00:00:00+00:00",
            "source": "升级前的 app/auth.py 抄录",       # 非 ASCII：GBK/UTF-16 才真的与 UTF-8 分道
            "credentials": {"admin": "a" * 64},
        }
        text = json.dumps(payload, ensure_ascii=False)
        gbk = root / "artifact-gbk.json"
        gbk.write_bytes(text.encode("gbk"))
        utf16 = root / "artifact-utf16.json"
        utf16.write_bytes(text.encode("utf-16"))
        for path in (as_directory, gbk, utf16):
            with self.subTest(artifact=path.name):
                with self.assertRaises(credentials_migration.MigrationArtifactError) as caught:
                    credentials_migration.read_artifact(path)
                self.assertIn(str(path), str(caught.exception))
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(path)
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_a_null_credentials_field_is_not_reported_as_an_absent_one(self):
        """`{"credentials": null}` 是"带了这个字段、没带任何账号"，与"忘了带字段"分得开。

        两种都拒，但消息不能同一条：前者指向导出那一步（它写空了），后者指向工件的键名
        （它压根没这字段）。
        """
        for payload, named in (
            ({"generated_at": "x", "source": "y"}, "缺少 credentials"),
            (self._valid(None), "取值为 null"),
        ):
            with self.subTest(keys=sorted(payload)):
                with self.assertRaises(credentials_migration.MigrationArtifactError) as caught:
                    credentials_migration.read_artifact(self._artifact(payload))
                self.assertIn(named, str(caught.exception))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    # --- SEC-A-004 的调用方扫描：按名字解析，不按属性后缀认调用 ----------------
    #: 受限写手住在哪个模块、叫什么名。扫描按这两枚值解析绑定，认不出来源的接收者一律算调用。
    WRITER_MODULE = "app.user_store"
    WRITER_FUNCTION = "import_legacy_digest"
    WRITER_FULL = WRITER_MODULE + "." + WRITER_FUNCTION
    STAR = "*"

    #: 写手在一份文件里能被绑上的形状。只认 `user_store.import_legacy_digest(...)` 那一种的话，
    #: `from app.user_store import import_legacy_digest` + 裸调用就是"整条受限路径从扫描面上
    #: 消失，连判红都不会有"——与 `CentralisationScanTests.PASSWORD_SITE_SHAPES` 同一条理由。
    WRITER_SHAPES = (
        "from app import user_store\n\n\ndef run(digest):\n"
        "    return user_store.import_legacy_digest('admin', digest, must_change=True)\n",
        "import app.user_store\n\n\ndef run(digest):\n"
        "    return app.user_store.import_legacy_digest('admin', digest, must_change=True)\n",
        "from app import user_store as store\n\n\ndef run(digest):\n"
        "    return store.import_legacy_digest('admin', digest, must_change=True)\n",
        "from app.user_store import import_legacy_digest\n\n\ndef run(digest):\n"
        "    return import_legacy_digest('admin', digest, must_change=True)\n",
        "from app.user_store import import_legacy_digest as put\n\n\ndef run(digest):\n"
        "    return put('admin', digest, must_change=True)\n",
        "from .user_store import import_legacy_digest\n\n\ndef run(digest):\n"
        "    return import_legacy_digest('admin', digest, must_change=True)\n",
        # 星号导入静态展不开，只能按"这文件里有这回事"处理：裸名字撞上写手名就算一次调用。
        "from app.user_store import *\n\n\ndef run(digest):\n"
        "    return import_legacy_digest('admin', digest, must_change=True)\n",
        # 两段链（Task 3 移交的那一发，实测旧规则 1 命中、加宽前 0 命中）：头一段是本文件
        # 认得的模块绑定、尾巴挂在它身上——`credentials_migration` 里 `from app import user_store`
        # 恰好就把受限模块绑成了它自己的属性，所以这条路径写得进 legacy 行。
        "from app import credentials_migration\n\n\ndef run(digest):\n"
        "    return credentials_migration.user_store.import_legacy_digest(\n"
        "        'admin', digest, must_change=True)\n",
    )
    #: 反向样本：形态与上面同形，但没有一条真的叫到受限写手。误判与漏判一样贵——调用方集合
    #: 一旦需要人回来记"哪些其实不算"，下一次就没人记得那条豁免为什么存在。
    NON_WRITER_SHAPES = (
        "from app import credentials\n\n\ndef run(digest):\n"
        "    return credentials.import_legacy_digest('admin', digest)\n",
        "from app.elsewhere import import_legacy_digest\n\n\ndef run(digest):\n"
        "    return import_legacy_digest('admin', digest)\n",
        "from app import user_store\n\n\ndef describe():\n"
        "    return 'import_legacy_digest 是全仓唯一能造 legacy 行的写手'\n",
        "from app.user_store import create_argon2\n\n\ndef run(plain):\n"
        "    return create_argon2('admin', plain_password=plain, must_change=False)\n",
    )

    @classmethod
    def _writer_bindings(
            cls, tree: ast.AST, package: str) -> tuple[dict[str, str], dict[str, str], bool]:
        """(名字 -> 它绑到的模块点分路径, 名字 -> 它绑到的写手全名, 有没有 `import *`)。

        `import` 与 `from ... import` 两侧、绝对与相对都认：相对导入的基准是被扫文件所在的包
        （`app/` 下的 `from .user_store import ...` 指的就是 `app.user_store`）。别名记回原路径，
        否则换个名字就把调用方从判据里抹掉了。`import app.user_store` 这类没起别名的绑的是包名
        `app`，所以映射按"实际能写出来的最短前缀"记。模块绑定要**全收**（不只写手那一个）：
        分清"这个接收者属于别的模块"和"这个接收者查不到来源"，靠的就是前者。
        """
        modules: dict[str, str] = {}
        funcs: dict[str, str] = {}
        star = False
        parts = package.split(".")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    modules[alias.asname or head] = alias.name if alias.asname else head
            elif isinstance(node, ast.ImportFrom):
                base = ".".join(parts[: len(parts) - node.level + 1]) if node.level else ""
                dotted = ".".join(piece for piece in (base, node.module or "") if piece)
                for alias in node.names:
                    if alias.name == cls.STAR:
                        star = star or dotted == cls.WRITER_MODULE
                        continue
                    full = f"{dotted}.{alias.name}"
                    target = alias.asname or alias.name
                    if full == cls.WRITER_FULL:
                        funcs[target] = full
                    #: 静态分不出 `from app import x` 里的 x 是模块还是函数，两条都记：接收者
                    #: 判据要的是"它属于哪条路径"，记多一条不会漏判，记少一条会（误判成未知）。
                    modules[target] = full
        return modules, funcs, star

    @classmethod
    def _legacy_writer_calls(cls, tree: ast.AST, package: str = "app") -> list[tuple[int, str]]:
        """一棵 AST 里"叫到受限写手"的位置，返回 (行号, 调用文本)。

        残留边界（与同文件的 hashlib 扫描同一档）：把写手赋给局部变量、或经 `getattr` 取出来再
        调，这类要跟着数据流才看得见，本扫描不做。
        """
        modules, funcs, star = cls._writer_bindings(tree, package)
        sites: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                if funcs.get(func.id) == cls.WRITER_FULL or (
                    star and func.id == cls.WRITER_FUNCTION
                ):
                    sites.append((node.lineno, ast.unparse(node)))
            elif isinstance(func, ast.Attribute) and func.attr == cls.WRITER_FUNCTION:
                root, _, rest = ast.unparse(func.value).partition(".")
                head = modules.get(root)
                if not rest:
                    receiver = head
                else:
                    # 链尾非空、而头一段是本文件认得的绑定 ⇒ 调用发生在"**某个模块身上的一个
                    # 属性**"上。静态展不开那条尾巴：`from app import credentials_migration` 之后
                    # `credentials_migration.user_store` 就是受限模块本身（import 会把名字挂在
                    # 父模块上），换个写法它也可以真是别的模块。这两种在 AST 里同形，而漏判的
                    # 代价是"整条受限路径从扫描面上消失"——所以按未知计入，不假扮成"属于别人"。
                    receiver = None
                if receiver in (None, cls.WRITER_MODULE):
                    # 接收者查不到来源时**照样算一次调用**（收拢前的口径就是这个方向）：多判一笔
                    # 有人才会来解释，静默漏掉的那一次没人知道这里发生过一次迁移写。
                    sites.append((node.lineno, ast.unparse(node)))
        return sites

    def _legacy_writer_callers(self) -> set[str]:
        """`backend/app/` 下每个"叫到受限写手"的文件，按相对 `backend/` 的 posix 路径报。

        用相对路径而不是 `path.name`：两个子包里各有一份同名模块时（`app/x/store.py` 与
        `app/store.py`），按文件名收会塌成同一条，判绿的那一次正好把第二个调用方藏掉。
        """
        callers: set[str] = set()
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            package = path.parent.relative_to(BACKEND_DIR).as_posix().replace("/", ".")
            if self._legacy_writer_calls(tree, package):
                callers.add(path.relative_to(BACKEND_DIR).as_posix())
        return callers

    def test_only_the_migration_module_may_call_the_legacy_writer(self):
        """SEC-A-004：受限路径必须真的受限——按调用方扫描，不按函数名信任。"""
        self.assertEqual({"app/credentials_migration.py"}, self._legacy_writer_callers())

    def test_every_writer_binding_shape_is_counted_as_a_caller(self):
        for source in self.WRITER_SHAPES:
            with self.subTest(binding=source.splitlines()[0]):
                self.assertEqual(1, len(self._legacy_writer_calls(ast.parse(source))))

    def test_a_similar_shape_stays_out_of_the_caller_set(self):
        for source in self.NON_WRITER_SHAPES:
            with self.subTest(binding=source.splitlines()[0]):
                self.assertEqual([], self._legacy_writer_calls(ast.parse(source)))

    def test_an_unreadable_shape_is_rejected_before_any_row_is_written(self):
        """脏 digest 的正确症状是**导入即拒**，不是那个人的第一次登录。

        `import_legacy_digest` 刻意不校验 64-hex（形态校验归迁移器），所以少一道前置校验
        的后果是把 `"not-hex"` 一路写进表里：`verify_password` 到那时抛的
        `CredentialConfigError` 会落在登录面上，而登录面的分类只有"口令错 / 503 / 存储事故"
        三种——一条永远不会成功的凭据行就这么被读成"用户记错了口令"。
        """
        path = self._artifact(self._valid({"admin": "a" * 63, "sales01": "zz" * 32}))
        with self.assertRaises(credentials_migration.MigrationArtifactError):
            credentials_migration.import_from_artifact(path)
        self.assertEqual({}, user_store.count_by_algorithm())
        self.assertIsNone(user_store.get_record("admin"))
        # 大写形态：`import_legacy_digest` 自己会 lower()，但表里存的必须是它能验的形态。
        upper = self._artifact(self._valid({"hr01": "A" * 64}))
        self.assertEqual({"hr01": "a" * 64}, credentials_migration.read_artifact(upper))

    def test_provenance_fields_are_required(self):
        """`source`/`generated_at` 是"升级工件"与"随手放的凭据文件"之间唯一的机器可辨差别。

        §8.2 把这条区分写成整节的立论根据（closure 删的是工件，不是凭据真源），所以它不能
        只靠文档：一份没有出处的 digest 集一律拒读，宁可让运维重跑一次导出。
        """
        for payload in (
            {"credentials": {"admin": "a" * 64}},
            {"generated_at": "  ", "source": "app/auth.py@pre-SEC-A",
             "credentials": {"admin": "a" * 64}},
            {"generated_at": "2026-09-25T00:00:00+00:00",
             "credentials": {"admin": "a" * 64}},
        ):
            with self.subTest(keys=sorted(payload)):
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(self._artifact(payload))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_an_empty_artifact_is_not_reported_as_a_missing_one(self):
        """空 credentials ⇒ 报错，不是"当成没有工件"。

        后者会把"升级只导了 0 个人"读成"这是全新安装"，两种状态在 `MigrationReport` 上必须
        可分：`artifact_present` 说的是**文件在不在场**，导入条数说的是另一件事。
        """
        path = self._artifact(self._valid({}))
        with self.assertRaises(credentials_migration.MigrationArtifactError):
            credentials_migration.import_from_artifact(path)

    def test_a_writers_declination_is_never_reported_as_an_import(self):
        """`import_legacy_digest` 返回 False = 那行没落地 ⇒ 不许进 `imported`。

        写手用的是 `ON CONFLICT(username) DO NOTHING`：`only_missing=False` 时它会对已存在
        的行回 False。把它记成"导入成功"就是报告说导了 5 个人、库里其实只有 3 个——而
        `legacy_count` 正是 SECA-04 判闭合的那个数字，台账错一位比少导一人更难查。
        """
        user_store.create_argon2("admin", plain_password="already-migrated 123456",
                                 must_change=False)
        path = self._artifact(self._valid({"admin": "a" * 64, "sales01": "b" * 64}))
        report = credentials_migration.import_from_artifact(path, only_missing=False)
        self.assertEqual(("sales01",), report.imported)
        self.assertEqual(("admin",), report.skipped)
        self.assertTrue(report.reason)
        self.assertTrue(report.artifact_present)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
        self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256,
                         user_store.get_record("sales01").algorithm)

    def test_a_store_incident_stays_a_store_incident(self):
        """写失败是存储事故：不许被翻成"口令错了"，也不许咽成一次跳过。"""
        path = self._artifact(self._valid({"admin": "a" * 64, "sales01": "b" * 64}))
        with mock.patch.object(
            user_store,
            "import_legacy_digest",
            side_effect=user_store.CredentialStoreError("disk full"),
        ):
            with self.assertRaises(user_store.CredentialStoreError) as caught:
                credentials_migration.import_from_artifact(path)
        # 分类没被改写：它既不是"工件形态错"，也不是认证结论。
        self.assertNotIsInstance(caught.exception, credentials_migration.MigrationArtifactError)
        self.assertNotIsInstance(caught.exception, credentials.CredentialConfigError)
        # 报错面不带口令材料（digest 也算：它进了异常消息就等于进了服务端日志）。
        self.assertNotIn("a" * 64, str(caught.exception))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_a_blank_username_is_rejected_with_the_rest_of_the_artifact(self):
        """主键为空/纯空白的行能写进表里，但永远查不出来——它该在导入这一步就被拒。"""
        for payload in (
            self._valid({"": "a" * 64}),
            self._valid({"   ": "a" * 64}),
        ):
            with self.subTest(usernames=sorted(payload["credentials"])):
                with self.assertRaises(credentials_migration.MigrationArtifactError):
                    credentials_migration.import_from_artifact(self._artifact(payload))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_neither_the_report_nor_a_rejection_echoes_a_digest(self):
        """报告与异常消息都是会被打印/审计的面：那里只许出现用户名。"""
        digest = "abcdef0123456789" * 4
        report = credentials_migration.import_from_artifact(
            self._artifact(self._valid({"admin": digest}))
        )
        self.assertNotIn(digest, repr(report))
        bad = digest[:-1] + "z"
        with self.assertRaises(credentials_migration.MigrationArtifactError) as caught:
            credentials_migration.import_from_artifact(
                self._artifact(self._valid({"admin": bad}))
            )
        self.assertNotIn(bad, str(caught.exception))
        self.assertIn("admin", str(caught.exception))

    def test_status_separates_the_two_algorithm_families(self):
        """`migration-status` 是 SECA-04 的硬门读数：两族分开数，且逐行可点名。"""
        user_store.create_argon2("admin", plain_password="already-migrated 123456",
                                 must_change=False)
        credentials_migration.import_from_artifact(
            self._artifact(self._valid({"sales01": "b" * 64, "viewer": "c" * 64}))
        )
        status = credentials_migration.status()
        self.assertEqual(2, status.legacy_count)
        self.assertEqual(1, status.argon2id_count)
        self.assertEqual(("admin", "sales01", "viewer"), tuple(a.username for a in status.accounts))
        self.assertEqual(
            {"admin": credentials.ALGORITHM_ARGON2ID,
             "sales01": credentials.ALGORITHM_LEGACY_SHA256,
             "viewer": credentials.ALGORITHM_LEGACY_SHA256},
            {a.username: a.algorithm for a in status.accounts},
        )
        self.assertEqual((1, 1, 1), tuple(a.credentials_version for a in status.accounts))
        self.assertEqual((False, True, True), tuple(a.must_change for a in status.accounts))
        self.assertEqual((None, None, None), tuple(a.locked_until for a in status.accounts))
        for row in status.accounts:
            self.assertIsInstance(row.updated_at, str)
            self.assertTrue(row.updated_at)
        # 状态面也不许带出口令材料：`AccountStatus` 里压根没有 `password_hash` 这一格
        # （口径同 `UserStoreSchemaTests`：不是"没人写"，是"没有可写的地方"）。
        self.assertNotIn(
            "password_hash", {field.name for field in dataclasses.fields(status.accounts[0])}
        )


class LegacyImportCliTests(_ArtifactFixtures):
    """规格 §11：`python -m app.cli credentials migrate` 是 legacy 导入的**唯一生产入口**。

    §20.5 的裁定有两半，本类的用例一一对上，缺一半就有一条测不到的路：
    - 「导入是运维显式动作」⇒ 四条退出码全部按 CLI 的**行为**判（真进程、真临时库、真工件），
      不给 `cli` 本身打桩——桩掉被测对象等于把契约换成对自己写法的复述。
    - 「启动仍然绝不自动导入」⇒ `test_starting_the_app_...` 真起一次 lifespan。`TestClient(app)`
      不进上下文管理器根本不跑 lifespan（`test_secret_hygiene_contract.py::
      StartupGuardLifespanTests` 就是为此存在），所以那一条既要点真上下文、又要留下"lifespan
      确实跑过"的证据，否则"零行"可能只是因为压根没启动。
    """

    #: 工件里的合成摘要：形状合法（64 位小写 hex），取值沿用本文件既有用例的口径（`"a" * 64`），
    #  不是 §4 那 5 枚真值——它们不许出现在任何写进仓库的文件里。
    DIGESTS = {"admin": "a" * 64, "sales01": "b" * 64}

    #: `migrate` 的证据面就是这四行、这个顺序（§11 末段："证据面是那四行可归档的 stdout"）。
    _FIELD_ORDER = ("artifact_present", "imported", "skipped", "reason")

    def setUp(self):
        """把 dev 形态钉在本类自己身上，不吃环境（§8.5 的默认值）。

        不钉的代价不是"少一条断言"，是**症状指错地方**：哪天 `backend/.env` 或 CI 把
        `SECURITY_ENTERPRISE_MODE` 拨成 true，本类的 happy path 会以 rc=2 一起红，读起来像
        "`migrate` 坏了"，而真正变的只是环境。企业形态那一格另有两条用例把同一枚属性 patch 成
        True——外层这枚 False 被它们临时盖住、退出时原样还回来，两件事互不牺牲。
        """
        super().setUp()
        dev_mode = mock.patch.object(cli.settings, "security_enterprise_mode", False)
        dev_mode.start()
        self.addCleanup(dev_mode.stop)

    def _four_field_face(self, out: str) -> list[str]:
        """钉"恰好四行、按 §11 的字段序"，再把那四行原样交给调用方比取值。

        为什么 `assertIn` 不够：这是一份要归档的运维输出，不是给人看一眼的日志。有人在末尾加一行
        "贴心提示"（或把 `skipped` 挪到 `imported` 前面）时，逐格 `assertIn` 全绿，而按行读它的
        脚本当场错。行数、顺序、取值三件事都要钉得住。
        """
        lines = out.splitlines()
        self.assertEqual(4, len(lines), f"`migrate` 的证据面是四行，实测 {lines!r}")
        self.assertEqual(
            list(self._FIELD_ORDER), [line.split("=", 1)[0] for line in lines],
            "四行的顺序就是归档台账的表头：改顺序等于改格式")
        return lines

    def _cli(self, argv: list[str]) -> tuple[int, str, str]:
        """跑一次 CLI，把 `(rc, stdout, stderr)` 一起交回来：三格都是判据面。"""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dev_import_lands_legacy_rows_and_prints_the_four_fields(self):
        """§11 规则 1：有工件 ⇒ rc 0、四字段逐格可归档，行本身由 `migration-status` 自证。

        四行按**等值**判（不是逐格 `assertIn`）：这一格是运维归档进验收文档的那份证据，形状与
        取值一起才算钉住。见 `_four_field_face`。
        """
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        self.assertEqual(
            ["artifact_present=True", "imported=2 admin,sales01", "skipped=0 -", "reason=-"],
            self._four_field_face(out))
        self.assertEqual("", err)
        records = {record.username: record for record in user_store.list_records()}
        self.assertEqual({"admin", "sales01"}, set(records))
        for record in records.values():
            self.assertEqual(credentials.ALGORITHM_LEGACY_SHA256, record.algorithm)
            self.assertTrue(record.must_change, "导入的行必须带着强制改密门（§8.2 升级路径）")
        # 观测面闭环：SECA-04 判闭合用的是 `migration-status` 那行读数，不是报告字段。
        status_code, status_out, status_err = self._cli(["credentials", "migration-status"])
        self.assertEqual(0, status_code, f"out={status_out!r} err={status_err!r}")
        self.assertIn("legacy_count=2", status_out)
        self.assertIn("must_change=1", status_out)

    def test_an_absent_artifact_is_a_legal_steady_state_and_still_exits_zero(self):
        """§11 规则 1 的那一格：`artifact_present=False, imported=0` 是**成功**。

        这条用例的全部价值在它判红的方向：把"没有工件"实现成非零退出、或往 stderr 说一句
        "导入失败"，全新安装就永远收不掉 `migrate` 这一格。合法缺席的输入被判成事故，这件事
        本项目在别的门上已经被咬过一次。
        """
        with self._standing_where_the_default_path_is_empty():
            code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        # 形状照钉；`reason` 那一格带**解析后的绝对路径**（§17 L7 的"人眼可诊"），取值随临时目录
        # 变，所以那一行只要求它把找过的位置说出来，不逐字比。
        lines = self._four_field_face(out)
        self.assertEqual("artifact_present=False", lines[0])
        self.assertEqual("imported=0 -", lines[1])
        self.assertIn("legacy_credentials.json", lines[3])
        self.assertEqual("", err, "合法稳态不该往 stderr 说话")
        self.assertNotIn("Traceback", out + err)
        status = credentials_migration.status()
        self.assertEqual((0, 0), (status.legacy_count, status.argon2id_count))

    def test_enterprise_mode_refuses_the_import_and_writes_not_a_single_row(self):
        """§11 规则 2 + §8.5 企业列：`SECURITY_ENTERPRISE_MODE=true` ⇒ 拒、零行、非零退出。

        企业形态下"文件还在所以顺手导"是 §8.5 fail-closed 被绕过的最直接形状。既有那行只比
        三格取值、不比整条记录：失败信息里因此永远不会出现 `password_hash` 那一段。
        """
        user_store.create_argon2("admin", plain_password="already-migrated 123456",
                                 must_change=False)
        before = user_store.get_record("admin")
        with self._with_artifact_at_default_path(
                self._valid({"admin": "a" * 64, "sales01": "b" * 64, "viewer": "c" * 64})):
            with mock.patch.object(cli.settings, "security_enterprise_mode", True):
                code, out, err = self._cli(["credentials", "migrate"])
            self.assertEqual(2, code, f"out={out!r} err={err!r}")
            self.assertEqual("", out, "拒绝那一格没有可打印的字段")
            self.assertIn("企业形态", err)
            self.assertIn("migrate", err)
            # 一行不写：既有 argon2id 行没被降级，也没有任何 legacy 行长出来。
            after = user_store.get_record("admin")
            self.assertEqual(
                (before.algorithm, before.credentials_version, before.must_change),
                (after.algorithm, after.credentials_version, after.must_change))
            status = credentials_migration.status()
            self.assertEqual((0, 1), (status.legacy_count, status.argon2id_count))

    def test_the_enterprise_refusal_does_not_even_create_the_database_file(self):
        """"一行不写"要连 DDL 一起算：`ensure_user_credentials_schema()` 自己也是一次写。

        判据是**那份文件根本不存在**（`_connect()` 一被叫到就 mkdir + 建库）。把企业检查挪到
        建表之后，上一条仍然绿、这一条立刻红——它们测的不是同一件事。
        """
        untouched = Path(self._tmp.name) / "untouched.db"
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            with mock.patch.object(cli.settings, "security_enterprise_mode", True), \
                    mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(untouched)}):
                code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(2, code, f"out={out!r} err={err!r}")
        self.assertFalse(untouched.exists(), f"企业形态的拒绝路上把库建出来了：{untouched}")

    def test_migrate_builds_the_schema_itself_against_a_virgin_database(self):
        """`migrate` 自己带建表那一步——生产库是全新的，从没人为它建过表（F-1 的全部理由）。

        本类里唯一一枚**不用** `setUp` 那份库的用例，理由是那枚被钉的调用点在 `setUp` 面前是
        隐形的：`_CredentialDbPerTest.setUp` 已经跑过 `ensure_user_credentials_schema()`，只要
        CLI 沿用那份库，把 `cli.py` 里那行删掉本类仍然全绿——而 `migrate` 存在的意义正是对着
        **virgin 生产库**执行一次。把 `CONVERSATION_DB_PATH` 指到 setUp 没碰过的新文件上才复刻
        得出那一格：判据是三件事——rc 0、`imported` 与工件同数、那个文件现在真在（表就在它里面，
        用只读连接按行验，免得"文件被建出来但里面没表"也算过）。
        """
        virgin = Path(self._tmp.name) / "virgin-production.db"
        self.assertFalse(virgin.exists(), "夹具已经把这份库建出来了：这条钉会是空的")
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            with mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(virgin)}):
                code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(0, code, f"out={out!r} err={err!r}")
        self.assertIn("imported=2 admin,sales01", out)
        self.assertTrue(virgin.exists(),
                        "`migrate` 没带 schema 那一步：对着全新生产库跑它就会 `no such table`")
        connection = sqlite3.connect(f"file:{virgin.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT username, algorithm, must_change FROM user_credentials ORDER BY username"
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [("admin", credentials.ALGORITHM_LEGACY_SHA256, 1),
             ("sales01", credentials.ALGORITHM_LEGACY_SHA256, 1)],
            [tuple(row) for row in rows],
            "行要落在**这份新文件**里，不是 setUp 那份库")

    def test_running_it_twice_imports_nothing_and_never_downgrades_a_converged_row(self):
        """§11 规则 3：`only_missing=True` ⇒ 第二次只补真缺的行，已收敛的一行都不许回写。

        `writer.call_count == 0` 是这条用例的重心：只看结果的话，"根本不试"与"试一次靠
        `INSERT ... DO NOTHING` 吞掉"同形（口径同 `MigrationPathTests` 里那枚模块级钉）。
        今天它由 `only_missing` 兜住，写手哪天被改成 UPSERT 就当场红。
        """
        user_store.create_argon2("admin", plain_password="already-migrated 123456",
                                 must_change=False)
        with self._with_artifact_at_default_path(
                self._valid({"admin": "a" * 64, "sales01": "b" * 64, "viewer": "c" * 64})):
            first, first_out, first_err = self._cli(["credentials", "migrate"])
            self.assertEqual(0, first, f"out={first_out!r} err={first_err!r}")
            self.assertIn("imported=2 sales01,viewer", first_out)
            self.assertIn("skipped=1 admin", first_out)
            with mock.patch.object(user_store, "import_legacy_digest",
                                   wraps=user_store.import_legacy_digest) as writer:
                second, second_out, second_err = self._cli(["credentials", "migrate"])
        self.assertEqual(0, second, f"out={second_out!r} err={second_err!r}")
        self.assertEqual(
            ["artifact_present=True", "imported=0 -", "skipped=3 admin,sales01,viewer",
             "reason=-"],
            self._four_field_face(second_out))
        self.assertEqual(0, writer.call_count, "已存在行的意思是**不去写它**")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm)
        status = credentials_migration.status()
        self.assertEqual((2, 1), (status.legacy_count, status.argon2id_count))

    def test_starting_the_app_never_consumes_the_upgrade_artifact(self):
        """§11 规则 1 的另一半 / §20.5：启动路径**不**新增自动导入。

        真起一次 lifespan（`with TestClient(app)` 才跑）：工件在场、库里一行都没有 ⇒ 起来之后
        仍然一行都没有、工件仍在原地。两个 warmup 换成 `MagicMock` 不是装饰，`called` 就是
        "lifespan 真的跑过"的证据——缺了它，"零行"可能只是压根没启动。哪天有人把
        `import_from_artifact()` 接进 lifespan，这一条是唯一会红的那个地方。
        """
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        rows_before = len(user_store.list_records())
        with mock.patch("app.main.warmup_identity_permissions") as identity_warmup, \
                mock.patch("app.main.warmup_llm_router") as router_warmup:
            with self._with_artifact_at_default_path(self._valid(self.DIGESTS)) as artifact:
                with TestClient(fastapi_app):
                    pass
            self.assertTrue(identity_warmup.called, "lifespan 没跑：这条钉是空的")
            self.assertTrue(router_warmup.called, "lifespan 没跑：这条钉是空的")
        self.assertEqual(rows_before, len(user_store.list_records()))
        self.assertEqual(0, credentials_migration.status().legacy_count)
        self.assertTrue(artifact.exists(), "启动路径把升级工件消费掉了")

    def test_the_migrate_face_carries_no_credential_material_and_reads_no_password(self):
        """§11 规则 4 + SEC-A-002：`migrate` 写的就是工件里已有的摘要，明文与摘要都不许见面。

        三面同判：env（它不需要口令，也没资格弹掉别人的口令）、argv（命名空间里没有能装口令的
        槽位）、stdout/stderr（既不含那两枚合成摘要、也不含它们的前缀，更不含**任何**一段
        ≥16 位连续 hex——这条比"逐枚点名 5 枚真值"更强，而且不需要把真值抄进仓库文件）。
        """
        sentinel = "unused-by-this-action-" + "x" * 8
        with mock.patch.dict(os.environ, {cli.PASSWORD_ENV_VAR: sentinel}):
            with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
                code, out, err = self._cli(["credentials", "migrate"])
            self.assertEqual(0, code, f"out={out!r} err={err!r}")
            # 用完不弹：`bootstrap-admin`/`reset` 那条腿弹的是它自己取到的口令，本动作没取过。
            self.assertIn(cli.PASSWORD_ENV_VAR, os.environ,
                          "migrate 读走（并弹掉）了它根本不该碰的口令 env")
        face = out + err
        self.assertNotIn(sentinel, face)
        self.assertNotIn(cli.PASSWORD_ENV_VAR, face)
        args = cli.build_parser().parse_args(["credentials", "migrate"])
        self.assertEqual({"command", "action"}, set(vars(args)),
                         "`migrate` 多出了一枚能装凭据材料的参数")
        for digest in self.DIGESTS.values():
            self.assertNotIn(digest, face)
            self.assertNotIn(digest[:8], face, "输出面里出现了摘要前缀")
        self.assertIsNone(re.search(r"[0-9a-f]{16,}", face), "输出面里出现了一段长 hex")
        self.assertNotIn("$argon2", face)

    def test_a_store_incident_exits_nonzero_without_becoming_a_digest_face(self):
        """§11 规则 3：底层存储事故 ⇒ 非零退出，且两格输出里不许出现口令或摘要。

        `CredentialStoreError` 不许被咽成一次"跳过"（那会把 `legacy_count` 停在一个没人知道
        的数上），也不许翻成"这个人的口令错了"——原样转出去即可，口径同 `bootstrap-admin`
        那条腿的 `print(str(exc))`。
        """
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            with mock.patch.object(user_store, "import_legacy_digest",
                                   side_effect=user_store.CredentialStoreError("disk full")):
                code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(1, code, f"out={out!r} err={err!r}")
        self.assertEqual("", out)
        self.assertIn("disk full", err)
        self.assertNotIn("Traceback", out + err)
        for digest in self.DIGESTS.values():
            self.assertNotIn(digest, out + err)
        self.assertIsNone(re.search(r"[0-9a-f]{16,}", out + err))
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_a_locked_database_is_an_incident_and_never_a_naked_traceback(self):
        """§11 rc 表：DB 锁 / 卷满与 `CredentialStoreError` **同归 1**，且不得以裸栈出场。

        上一条测的是 `user_store` 自己裹好的那几格；busy/locked 不走那条道——它以
        `sqlite3.OperationalError` 出场，而 `except CredentialStoreError` 接不住它。当时的后果是
        解释器兜底："碰巧"退出 1，运维面前却是一截 traceback。这一条把那个偶然变成契约：退出码
        由本模块给出，stderr 一行话说完。
        """
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            with mock.patch.object(user_store, "import_legacy_digest",
                                   side_effect=sqlite3.OperationalError("database is locked")):
                code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(1, code, f"out={out!r} err={err!r}")
        self.assertEqual("", out, "事故那一格没有可归档的字段")
        self.assertEqual(["database is locked"], err.splitlines(),
                         "一行说完：不带栈、不带二次提示")
        self.assertNotIn("Traceback", out + err)
        self.assertEqual(0, credentials_migration.status().legacy_count)

    def test_a_database_that_cannot_even_be_opened_fails_the_same_way_on_the_schema_leg(self):
        """建表那一步也在事故面**之内**：`ensure_user_credentials_schema()` 自己就要连库。

        它在实现里排在 `import_from_artifact()` 之前，卷满 / 文件打不开这类事故最早就发生在那里；
        把它留在 `try` 外面，等于 §11 那一格里最常见的一种形态从来没被接住。桩的取值特意用
        `sqlite3.DatabaseError`（锁之外的驱动错误的公共基类）而不是 `OperationalError`，顺手钉住
        "接的是这个**家族**，不是某一枚子类"。
        """
        with self._with_artifact_at_default_path(self._valid(self.DIGESTS)):
            with mock.patch.object(user_store, "ensure_user_credentials_schema",
                                   side_effect=sqlite3.DatabaseError("disk I/O error")):
                code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(1, code, f"out={out!r} err={err!r}")
        self.assertEqual("", out)
        self.assertEqual(["disk I/O error"], err.splitlines())
        self.assertNotIn("Traceback", out + err)

    def test_a_malformed_artifact_is_refused_as_a_whole_before_any_row_lands(self):
        """整份拒这条出路在 CLI 面上的形状：非零、说人话、库里一行没有、摘要不外泄。

        这一格规格没有点名（§11 四条规则里讲的是"工件不在场"，不是"工件读不得"），实现取
        rc=2：与"身份不存在""env 口令不合格"同一类**运维一次能修完**的拒绝。见报告 §5 记录。
        """
        with self._with_artifact_at_default_path(self._valid({"admin": "not-hex"})):
            code, out, err = self._cli(["credentials", "migrate"])
        self.assertEqual(2, code, f"out={out!r} err={err!r}")
        self.assertEqual("", out, "被拒的工件没有可打印的字段")
        self.assertIn("admin", err)
        self.assertNotIn("not-hex", err)
        self.assertNotIn("Traceback", out + err)
        self.assertEqual(0, credentials_migration.status().legacy_count)


class _GuardProbe(unittest.TestCase):
    """自建一份「假真库」+ 一个只盯它的护栏实例，用来驱动**真的** `user_store` 函数。

    与会话级护栏同手法（`test_model_router_v23_contract.py::LedgerGuardClassificationTests`
    就是这个形状），刻意不在真库上演练：本类的每一笔"写"都记在自己那个 `LedgerGuard` 实例
    的 list 上，所以既不会污染会话统计，也不会被会话归责钩子读成事故——归责钩子读的仍是
    `credential_write_redirects()` 那条真通道，由 `CredentialGuardWiringTests` 点数。
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.protected_dir = root / "data"                      # 模拟「保护集里的真库」目录
        self.protected_dir.mkdir()
        self.protected_db = self.protected_dir / "conversations.db"
        self.isolated_dir = root / "isolated"
        self.isolated_dir.mkdir()
        self.artifact_dir = root

    def seed_offline(self, target: Path) -> None:
        """在护栏**不在场**时把表建到目标库里：建表本身是一笔 write，不能混进被驱动的样本。"""
        with mock.patch.object(user_store, "database_path", return_value=target):
            user_store.ensure_user_credentials_schema()

    def install_guard(self, target: Path) -> "ledger_guard.LedgerGuard":
        """自建一份与**会话那份同配置**的护栏：同一个 label/subject/`warn_on_read`。

        配置要照抄，否则本类演练的是另一个形状的护栏。抄得齐不齐由会话那枚哨兵管
        （`CredentialGuardWiringTests` 盯的是真接线的存在性与改道目标）。
        """
        guard = ledger_guard.LedgerGuard(
            original_path=lambda: self.protected_db,
            target=target,
            protected_dirs=(self.protected_dir,),
            label="[credential-guard]",
            subject="真实凭据表",
            warn_on_read=False,
        )
        guard.install_credential_store(user_store)
        self.addCleanup(guard.uninstall)
        return guard

    def table_rows(self, path: Path) -> int:
        """目标库里 `user_credentials` 的行数（表不在场时 -1）。"""
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            found = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (user_store.TABLE_NAME,),
            ).fetchone()
            if found is None:
                return -1
            return int(connection.execute(
                f"SELECT COUNT(*) FROM {user_store.TABLE_NAME}").fetchone()[0])
        finally:
            connection.close()


class CredentialStoreGuardTests(_GuardProbe):
    """护栏对凭据面的三道事实：改道、读写归类、以及"改道是真改道"。

    两枚方向相反的钉子（缺一道就是漏判）：纯读必须**留**在 read（把读也判红是 N1 的病灶），
    真写必须**升**到 write（判成 read 就是这张表上没有任何人在看）。归类不靠函数名清单：
    写证据取自 sqlite 自己回传的语句，所以以后新加一条写腿不需要谁记得回到 conftest 加名字。
    """

    def test_a_pure_read_stays_read_and_lands_nothing_on_the_protected_path(self):
        target = self.isolated_dir / "conversations.db"
        self.seed_offline(target)
        guard = self.install_guard(target)
        self.assertIsNone(user_store.get_record("admin"))
        self.assertEqual(list(user_store._COLUMNS), user_store.column_names())
        self.assertEqual({}, user_store.count_by_algorithm())
        kinds = [kind for _src, _dst, kind in guard.records]
        self.assertEqual([ledger_guard.REDIRECT_READ] * 3, kinds,
                         "读被记成写 ⇒ 每条正常读用例都会被会话钩子判红（N1 的病灶）")
        self.assertEqual((), guard.violations())
        self.assertFalse(self.protected_db.exists(),
                         "读路径在保护集下留下了一份 0 字节库：mkdir + connect 的落点没被改道")

    def test_a_credential_write_is_classified_write_and_lands_in_the_target(self):
        target = self.isolated_dir / "conversations.db"
        self.seed_offline(target)
        guard = self.install_guard(target)
        user_store.create_argon2("admin", plain_password="a-good-password 123",
                                 must_change=False)
        self.assertEqual([(str(self.protected_db), str(target), ledger_guard.REDIRECT_WRITE)],
                         list(guard.records),
                         "写没被记成 write ⇒ 这张表上没人盯（会话钩子的输入就是这一笔）")
        self.assertEqual(1, len(guard.violations()))
        self.assertEqual(1, self.table_rows(target), "改道是真改道：行要落在目标库")
        self.assertFalse(self.protected_db.exists(), "真写路径碰到了保护集下的文件")

    def test_a_schema_creation_on_the_redirected_path_is_a_write_too(self):
        """`ensure_user_credentials_schema()` 走的是一条 DDL，不是 DML：它也必须是 write。

        这条钉子管的是 Task 2 留的那个形状——读路径**不**建表，建表只有一次真 DDL 提交；
        如果归类只认 INSERT/UPDATE/DELETE，那"谁在启动期往真库建了半张表"就正好看不见。
        """
        target = self.isolated_dir / "fresh.db"
        guard = self.install_guard(target)
        user_store.ensure_user_credentials_schema()
        self.assertEqual([ledger_guard.REDIRECT_WRITE],
                         [kind for _src, _dst, kind in guard.records],
                         "建表（executescript 的 CREATE TABLE）没被记成写")
        self.assertEqual(list(user_store._COLUMNS), user_store.column_names())
        self.assertEqual(
            [ledger_guard.REDIRECT_WRITE, ledger_guard.REDIRECT_READ],
            [kind for _src, _dst, kind in guard.records],
        )
        self.assertFalse(self.protected_db.exists())

    def test_the_write_mark_is_per_connection_not_a_latch(self):
        """读→写→读 ⇒ 归类必须是 read / write / read，且**一条连接只升一次**。

        写证据挂在**这一条连接**上。做成"第一次写之后整条会话都算写"的实现（latch）会让后面
        每一条只读用例被判红，做成"第一次写之后不再记"的实现会把第二笔事故读成静默——两个方向
        在这里各有一枚断言。最后那步 `record_login_failure` 是故意的：`max_attempts=1` 让它
        在**同一条连接**里跑两条 UPDATE（涨计数 + 落 lock），是唯一能暴露"每条写语句各升一次
        ⇒ 一笔事故记成两笔"的形状。
        """
        target = self.isolated_dir / "conversations.db"
        self.seed_offline(target)
        guard = self.install_guard(target)
        user_store.list_records()
        user_store.create_argon2("admin", plain_password="a-good-password 123",
                                 must_change=False)
        user_store.list_records()
        self.assertEqual(
            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE,
             ledger_guard.REDIRECT_READ],
            [kind for _src, _dst, kind in guard.records],
        )
        self.assertEqual(1, len(guard.violations()))
        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
        self.assertEqual(
            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE,
             ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE],
            [kind for _src, _dst, kind in guard.records],
            "多条写语句的同一条连接被记成了多笔事故 ⇒ 判红信息里的条数不再等于碰真库的连接数",
        )
        self.assertEqual(2, len(guard.violations()))
        # 前提本身也要成立：第二条 UPDATE 真的跑过（`max_attempts=1` 没生效的话，上面那步
        # 退化成"一条连接一次写"，这一枚钉子就空转了）。读放在所有 records 断言之后：它自己
        # 也是一笔改道，只是归类是 read。
        self.assertIsNotNone(user_store.get_record("admin").locked_until)

    def test_the_restricted_legacy_writer_goes_through_the_same_seam(self):
        """受限迁移器写下的那一行同样要落在改道后的库里。

        这一条把两件事接上：`import_from_artifact` 的读（`get_record`）留在 read，它的写
        （`import_legacy_digest`）升到 write。少了后一半，"受限路径"就成了护栏的盲区——而
        它恰好是唯一能造出 legacy 行的那条路径。
        """
        target = self.isolated_dir / "conversations.db"
        self.seed_offline(target)
        artifact = self.artifact_dir / "artifact.json"
        artifact.write_text(
            json.dumps(
                {
                    "generated_at": "2026-09-25T00:00:00+00:00",
                    "source": "app/auth.py@pre-SEC-A",
                    "credentials": {"admin": "a" * 64},
                }
            ),
            encoding="utf-8",
            newline="\n",
        )
        guard = self.install_guard(target)
        report = credentials_migration.import_from_artifact(artifact)
        self.assertEqual(("admin",), report.imported)
        self.assertEqual(
            [ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE],
            [kind for _src, _dst, kind in guard.records],
        )
        self.assertEqual(1, self.table_rows(target))
        self.assertFalse(self.protected_db.exists())


class CredentialGuardWiringTests(unittest.TestCase):
    """接线本身要有钉子：`install()` 只包 `usage` 的那一行改掉之后，谁保证 `user_store` 也被包。"""

    @staticmethod
    def _columns_in(path: Path) -> list[str]:
        """直接点数某份文件里 `user_credentials` 的列（文件/表不在场 ⇒ 空表结构）。"""
        if not path.is_file():
            return []
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(f"PRAGMA table_info({user_store.TABLE_NAME})").fetchall()
        finally:
            connection.close()
        return [str(row[1]) for row in rows]

    def test_the_session_guard_watches_the_credential_table_too(self):
        self.assertTrue(ledger_guard.guard_is_active(),
                        "会话护栏没跑起来 ⇒ 本类的钉全是空的")
        self.assertTrue(ledger_guard.credential_guard_is_active(),
                        "`user_store` 的 seams 没挂在会话护栏上 ⇒ 凭据写无人盯")

    def test_raw_database_path_is_the_unguarded_function(self):
        """`RAW_DATABASE_PATH` 的前提要当场成立：它是**产品代码**那个函数，不是护栏的桩。

        护栏若早在本模块 import 之前装上，这里抓到的就是 `LedgerGuard` 的 bound method，
        `UserStoreIsolationTests::test_the_effective_path_is_the_siblings_own_env_key` 立刻退回
        "护栏自证"。两条属性一起看就分得开：bound method 的 `__module__` 是 conftest、
        `__qualname__` 带类名。
        """
        self.assertEqual("app.user_store", RAW_DATABASE_PATH.__module__)
        self.assertEqual("database_path", RAW_DATABASE_PATH.__qualname__)

    def test_the_credential_table_resolves_to_the_same_file_as_the_ledger(self):
        """规格 §6.1 的"同库"由同一个改道目标兑现：两张表解析到同一个文件。

        env 被清空时 `database_path()` 会退回相对默认值，那正是护栏存在的理由；这里同时钉
        "退回来的路径不在保护集底下"（改道生效）与"两张表落在同一份文件"（真源只有一个）。
        两枚路径要在**同一种 env 条件**下取：宿主把 `CONVERSATION_DB_PATH` 指到保护集外的一份
        文件时，一侧给 env 值、另一侧给改道目标，等式会假红。而 clear 块里叫
        `effective_ledger_path()` 会经 N1 的通道发一句"只读了真实账本"的提醒——本枚钉子要的
        只是等式，所以就地吞掉它：全仓没有用例断言这枚 warning（它的口径是 `read_redirects()`
        与会话收尾汇总），吞掉不会把提醒从别人那里偷走。
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with mock.patch.dict(os.environ, {}, clear=True):
                ledger_path = ledger_guard.effective_ledger_path()
                credential_path = ledger_guard.effective_credential_path()
        self.assertFalse(ledger_guard.path_is_protected(credential_path),
                         f"env 清空后凭据表仍指向保护集：{credential_path}")
        self.assertEqual(ledger_path.resolve(), credential_path.resolve())

    def test_a_credential_connect_under_a_cleared_env_cannot_touch_the_real_databases(self):
        """Task 2 移交的残余：`_connect()` 会 mkdir + 打开文件，落点在 env 被清掉时是生产库。

        快照取的是「在不在场 + 表清单」而不是字节数/时间戳：本仓库的 dev 后端可能正往同一份
        库里写会话行，拿 mtime 判据会把那种正常写读成事故。凭据面的义务只有两条——不许凭空多出
        一份 0 字节库，也不许多出 `user_credentials` 这半张表。
        """
        def snapshot() -> dict[str, tuple[bool, tuple[str, ...] | None]]:
            return {
                str(path): (path.is_file(), ledger_guard.real_db_tables(path))
                for path in ledger_guard.REAL_DB_PATHS
            }

        before = snapshot()
        # 先让**改道目标**里有这张表：否则"读到的列结构"两侧都是空，等式在两种实现下同形，
        # 这枚钉子就空转。建表走 `mock.patch.object(database_path)` 绕开护栏接缝——它既不会被
        # 记成写改道（那条路没经过 `guarded_store_database_path`），也不会判红。
        with mock.patch.object(user_store, "database_path",
                               return_value=ledger_guard.effective_credential_path()):
            user_store.ensure_user_credentials_schema()
        with mock.patch.dict(os.environ, {}, clear=True):
            columns = user_store.column_names()
            redirected = ledger_guard.effective_credential_path()
        # 那次读**落在哪份文件**要单独验：`column_names()` 只可能给"无表"或"完整列"，一个
        # 两态都接受的断言分不清"读到改道库"与"读到别的文件"，等于没钉。
        self.assertEqual(list(user_store._COLUMNS), columns, "读到的不是完整表结构")
        self.assertTrue(redirected.is_file(),
                        "改道之后连目标文件都没落地 ⇒ 那次读没经过护栏的接缝")
        self.assertEqual(self._columns_in(redirected), columns,
                         f"读到的列结构与改道目标 {redirected} 里的不一致 ⇒ 读的不是它")
        self.assertEqual(before, snapshot(),
                         "一次改道读让真库多出了文件或表 ⇒ 落点没被护栏接走")

    def test_a_credential_read_is_reported_only_after_its_kind_has_settled(self):
        """`warn_on_read=False` 的代价与出路：这一面**不**在用例进行中发提醒。

        归类要到语句执行时才定型，而 warning 必须当场发 ⇒ 一条**写**改道会先收到一句"只读"的
        自相矛盾。所以中途静默，同一份事实改由定型后的两枚口径（`credential_redirects()` /
        `credential_read_redirects()`）与收尾的 `[credential-guard]` 汇总承担——那两枚口径如果
        没有消费方，"提醒没丢"这句话就只是注释。
        """
        total_before = len(ledger_guard.credential_redirects())
        reads_before = len(ledger_guard.credential_read_redirects())
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with mock.patch.dict(os.environ, {}, clear=True):
                user_store.column_names()
        self.assertEqual(
            [], [w for w in caught if "credential-guard" in str(w.message)],
            "凭据面在用例进行中发了 read 提醒：那时归类还没定型，写改道会先收到一句『只读』")
        self.assertEqual(total_before + 1, len(ledger_guard.credential_redirects()),
                         "这一次改道读没进定型后的完整口径")
        self.assertEqual(reads_before + 1, len(ledger_guard.credential_read_redirects()),
                         "这一次改道读没进定型后的读口径 ⇒ 提醒真的丢了")

    def test_the_growth_rule_is_measured_against_the_session_baseline(self):
        """增长判据本身要有一枚钉：起点几行不重要，涨没涨才重要。

        真库里今天没有凭据行（也不许为测试去造一份），所以算术只能在换掉两枚读数的口径下验：
        起点 5 / 现在 5 ⇒ 不涨；现在 6 ⇒ 涨 1；起点缺这一份库 ⇒ 按 0 起算（fail-closed）。
        """
        with mock.patch.object(ledger_guard, "real_user_credential_row_counts",
                               return_value={"dev/x.db": 5}), \
                mock.patch.object(ledger_guard, "_SESSION_START_CREDENTIAL_ROWS",
                                  {"dev/x.db": 5}):
            self.assertEqual({}, ledger_guard.credential_row_growth())
        with mock.patch.object(ledger_guard, "real_user_credential_row_counts",
                               return_value={"dev/x.db": 6}), \
                mock.patch.object(ledger_guard, "_SESSION_START_CREDENTIAL_ROWS",
                                  {"dev/x.db": 5}):
            self.assertEqual({"dev/x.db": 1}, ledger_guard.credential_row_growth())
        with mock.patch.object(ledger_guard, "real_user_credential_row_counts",
                               return_value={"dev/x.db": 1}), \
                mock.patch.object(ledger_guard, "_SESSION_START_CREDENTIAL_ROWS", {}):
            self.assertEqual({"dev/x.db": 1}, ledger_guard.credential_row_growth(),
                             "没拍到起点就退回『必须为 0』：宁可假红，不可静默放过")

    def test_no_test_in_this_session_wrote_a_credential_row_into_a_real_database(self):
        """会话级哨兵（与账本那枚同形）：本会话零凭据**写**改道，且真库行数没因测试涨过。

        行数判"会话期间不增长"而不是"必须为 0"：`python -m app.cli credentials bootstrap-admin`
        这条 dev 路径就是把 argon2id 行写进 `backend/data/conversations.db`（compose 挂载同一份
        文件），跑过它的机器上"== 0"会永久假红并把账记到测试头上。基线由会话 fixture 在装闸
        **之前**拍，所以会话内真涨一行仍然当场红。
        """
        self.assertEqual([], list(ledger_guard.credential_write_redirects()),
                         "有用例的凭据写落到了保护集下的真实库 ⇒ 见 conftest 的凭据面说明")
        counts = ledger_guard.real_user_credential_row_counts()
        self.assertIn(str(ledger_guard.REAL_DB_PATH), counts, "哨兵没数 `backend/data` 那份真库")
        baseline = ledger_guard.credential_row_counts_at_session_start()
        self.assertIn(str(ledger_guard.REAL_DB_PATH), baseline,
                      "会话没拍到起点 ⇒ 这条哨兵退化成『必须为 0』，dev bootstrap 过的机器会假红")
        self.assertEqual({}, ledger_guard.credential_row_growth(),
                         "真实库里的凭据行在会话期间变多了（SECA-04 的台账会被污染）："
                         f"现在 {counts}，会话起点 {baseline}")


class AuditSinkIsolationTests(unittest.TestCase):
    """审计落盘面的会话级改道（`conftest.isolated_audit_sink`）必须在场并且真的在接。

    钉的是"我的事件进了改道后的汇"，不是"仓库那本账的字节没动"：`backend/data/audit.jsonl` 是
    compose 挂载下**运维正在写**的那本账（dev 后端与 Task 10 的 smoke 都在写它），拿它的尺寸当
    判据会把正常运维活动读成测试事故——同一条理由见 `conftest.real_db_tables` 的 docstring。
    唯一例是"刚写进去的那一枚事件不在仓库那本账里"：marker 只存在于本例，所以这一条不flaky。
    """

    def test_the_session_moves_the_audit_sink_out_of_the_repo_data_dir(self) -> None:
        from app import audit as audit_module

        sink = Path(audit_module.AUDIT_PATH).resolve()
        repo_data = (Path("data") / "audit.jsonl").resolve().parent
        self.assertNotIn(repo_data, sink.parents,
                         f"审计汇还落在仓库的 `data/` 里 ⇒ 会话闸没装上：{sink}")
        self.assertNotEqual(Path("data") / "audit.jsonl", Path(audit_module.AUDIT_PATH),
                            "审计汇还是产品代码里那枚相对默认值 ⇒ 会话闸没装上")

    def test_a_recorded_event_lands_in_the_sink_and_not_in_the_operational_log(self) -> None:
        from app import audit as audit_module

        sink = Path(audit_module.AUDIT_PATH)
        # marker 每次运行唯一：固定串会让"这次没写进去"被上一轮留下的历史证伪成假红。
        marker = f"sec-a-sink-probe-{uuid.uuid4().hex}"
        before = len(sink.read_text(encoding="utf-8").splitlines()) if sink.exists() else 0
        audit_module.record_event(username=marker, role="admin", action="LOGIN",
                                  detail="invalid_credentials")
        after = sink.read_text(encoding="utf-8").splitlines()
        self.assertEqual(before + 1, len(after), "审计事件没落到改道后的汇里")
        self.assertIn(marker, after[-1])

        # 判的是**产品那本账的绝对路径**：本套件按两种 cwd 跑，`Path("data")/…` 在仓库根上会落到
        # 另一枚 gitignored 的 `rag/data/audit.jsonl`（根 cwd 跑测试/跑应用的副产品），于是同一句
        # 断言在两种 cwd 下问的是两个不同文件——2026-09-27 的终态复测就是这么红的。
        operational = BACKEND_DIR / "data" / "audit.jsonl"
        if operational.is_file():
            self.assertNotIn(marker, operational.read_text(encoding="utf-8", errors="ignore"),
                             "本例事件同时出现在运维那本账里 ⇒ 写手没有每次现取 AUDIT_PATH")


class SessionAttributionHookTests(unittest.TestCase):
    """逐例归责那枚会话钩子（`fail_the_offending_test_on_repo_ledger_write`）自己要有用例。

    两张表的"写改道 ⇒ 本例红"全走它，而它读的是**自己那份 records 从 `before` 起切的片**：
    切片起点写成常量、或两枚 `before` 混用，症状都是"肇事用例静默通过"——没有任何别的用例
    会替它红。所以这里手工推进那枚生成器：过 yield → 往会话的 records 上 append 一笔假写 →
    让它收尾，要求它按表说话、并且按本例的窗口说话。
    """

    @staticmethod
    def _start_hook() -> Any:
        """拿到那枚**未被 fixture 装饰器包住**的生成器函数并推进到 yield 之后。

        `pytest.fixture` 在新版本里返回的是包装对象（直接调会报"called directly"），生成器函数
        在 `__wrapped__` 上；老版本返回函数本身 ⇒ 两枚都试。
        """
        fixture = ledger_guard.fail_the_offending_test_on_repo_ledger_write
        factory = getattr(fixture, "__wrapped__", fixture)
        hook = factory()
        next(hook)                                     # setUp：记下两枚 before
        return hook

    def _blame_with_a_fake_write(self, guard: Any, decoy: Any) -> str:
        """给会话钩子喂一笔属于 `guard` 这张表的写改道，返回它抛出的消息。

        `decoy`（另一张表那份）先放一笔**读**：两枚 `before` 因此取到不同值，"把账本那枚
        `before` 复用给凭据分支"这种写法才在这里红——定向跑里两枚计数本来都是 0，不加这笔
        就分不清它读的是哪一份 records。
        """
        records, decoy_records = guard.records, decoy.records
        mark, decoy_mark = len(records), len(decoy_records)
        try:
            decoy_records.append((str(ledger_guard.REAL_DB_PATH), str(decoy.target),
                                  ledger_guard.REDIRECT_READ))
            hook = self._start_hook()
            records.append((str(ledger_guard.REAL_DB_PATH), str(guard.target),
                            ledger_guard.REDIRECT_WRITE))
            with self.assertRaises(AssertionError) as caught:
                hook.send(None)
        finally:
            del records[mark:]                         # 假笔不许留给会话里后面的哨兵
            del decoy_records[decoy_mark:]
        return str(caught.exception)

    def test_a_credential_write_redirect_blames_the_offending_test(self):
        message = self._blame_with_a_fake_write(
            ledger_guard._CREDENTIAL_GUARD, ledger_guard._SESSION_GUARD)
        self.assertIn("凭据", message)
        self.assertIn("_CredentialDbPerTest", message, "消息要给得出修法，否则肇事者拿不到地图")
        self.assertNotIn("账本", message, "凭据面的事故说成账本面 = 递一张错地图（N1 的病灶）")

    def test_a_ledger_write_redirect_blames_the_offending_test(self):
        message = self._blame_with_a_fake_write(
            ledger_guard._SESSION_GUARD, ledger_guard._CREDENTIAL_GUARD)
        self.assertIn("账本", message)
        self.assertIn("usage", message)
        self.assertNotIn("凭据", message, "两枚消息各说各的表：混着说等于没有说")

    def test_a_write_recorded_before_the_test_started_is_not_blamed_on_it(self):
        """两枚 `before` 那枚切片起点要有钉子：假笔放在 setUp **之前**，钩子必须闭嘴。

        起点写成常量 0（或者干脆整表扫）就是这一枚红：那样第一个肇事用例之后的**每一例**都会被
        同一笔事故判红，归责信息里点名的人全是对的、用例全是错的。两张表各跑一遍。
        """
        for name in ("_CREDENTIAL_GUARD", "_SESSION_GUARD"):
            guard = getattr(ledger_guard, name)
            with self.subTest(guard=name):
                records = guard.records
                mark = len(records)
                try:
                    records.append((str(ledger_guard.REAL_DB_PATH), str(guard.target),
                                    ledger_guard.REDIRECT_WRITE))
                    hook = self._start_hook()
                    with self.assertRaises(StopIteration):     # 走完收尾，一路没判红
                        hook.send(None)
                finally:
                    del records[mark:]
