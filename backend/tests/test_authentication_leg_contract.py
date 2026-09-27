"""认证腿的契约（规格 §7.1–§7.4 / §8.3 / §8.4 / §9.1，SECA-03/04b/13/14/21/24）。

五件事各自有钉子，且判据都不是"函数返回什么"这么抽象的形状：

1. **升级路径当场收敛**：legacy 行 + 旧口令 ⇒ 登录成功、同一行被换成 argon2id、
   `must_change=1`，且数据面立刻被门挡住（§8.3 要拒的正是"只重哈希不置门"那一半）。
2. **四种失败态在响应面与审计面上逐字相同**，等价性由**结构事实**判：每态恰好一次
   `PasswordHasher.verify`、同一档位、同一实例（§7.3 明写不设毫秒阈值——flaky 的安全门
   会被下一个人直接 skip，那比没有门更糟）。第四态在 `algorithm` 列上有两种形态
   （argon2 行走真 verify、legacy 行只做 `compare_digest`），两条也必须落在同一格成本上，
   否则"这个账号还没升级"本身就是一张响应时间指纹。
3. **渐进重哈希不改会话**（版本不 bump）；写盘失败只记降级、不拒登录（§8.3 冻结裁定），
   而那一格降级必须在真 HTTP 面上落成审计事件——"不静默"判的是审计里有这笔，不是返回值里
   有那个 token。
4. **`must_change` 门住在依赖层**：白名单只有 `/api/auth/me` 与改密腿，其余 403 + 中文文案，
   机器可读信号是审计 token（§9.1 的两栏分工）。门测的是一枚**活着**的 token——换代在前、
   签发在后；顺序反了撞上的就是 §7.5 那条凭据纪元 401，那不是门的判据（`TokenClaimFaceTests`
   与 `test_password_lifecycle_contract.py` 钉的正是那条腿）。
5. **审计值域由出口自己把**：`record_login_event` 认 tuple 常量里的三枚取值，空串（成功面）
   根本进不了写手，值域外的文本直接抛——判定不住在调用方的字符串抄写里。

另有一枚**反向钉**（`PasswordCapacitySurfaceTests`）：它原本是 Task 6 埋的"并发闸门溢出在
登录腿上没人翻译"的缺口哨兵，断的是未处理 500 + 零审计。翻译落地（503 + 中文文案 +
`password_capacity`）之后它**改了断言、用例保留**——旧断言留在原地等于把门反着钉：下一次
"翻译又被删掉"它会照样喊绿。

两层保护各有自己的键与自己的哨兵（`ThrottleLayerTests` / `ThrottleHttpFaceTests`）：
pre-hash 节流按 `(归一化 username, client_ip)` 分桶、进程内、排在任何身份查找之前；
账号锁定按 username、落库、跨来源地址共享。合并成一枚就必然丢掉一种保护，而两枚键各自
只有一条用例能杀掉对应的计划突变（M6 去掉 `client_ip` ⇒ SECA-16a；把锁定也按 IP 键 ⇒ SECA-16b）。
429 与 503 都是**可用性**事实：它们在凭据结论之前判出，因此两栏文案（展示面中文 / 审计面
token）里都不许出现任何关于账号存在与否的话——这条不写成一句注释，写成逐字节的面对比。
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = BACKEND_DIR / "tests"
for _path in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app import auth, credentials, directory, login_throttle, user_store  # noqa: E402
from app import config as config_module  # noqa: E402
from app import credentials_migration  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
import sec_a_fixtures  # noqa: E402  —— 换库 / 审计落点 / JWT secret 三件地基只留一份实现
from sec_a_seed import (  # noqa: E402
    SEED_RECORD,
    ensure_demo_credentials,
    seed_demo_credentials,
)

LEGACY_ADMIN = hashlib.sha256(b"admin123").hexdigest()
GOOD_PASSWORD = "a-good-password 123456"

#: PHC 串里的档位段（`$argon2id$v=19$m=…,t=…,p=…$盐$摘要`）。按内容认、不按段序号认：
#: 数段数会把"版本号挪位置"这类格式事实混进判据，而这条钉子要问的只有"是不是当前档位"。
_PROFILE = re.compile(r"m=\d+,t=\d+,p=\d+")


def _current_profile() -> str:
    """当前档段的字面量（`m=…,t=…,p=…`）——成本等价性比的是它，不是毫秒。"""
    return (
        f"m={credentials.ARGON2_MEMORY_COST},"
        f"t={credentials.ARGON2_TIME_COST},"
        f"p={credentials.ARGON2_PARALLELISM}"
    )


@contextlib.contextmanager
def _hasher_runs():
    """数"这段代码真的叫了几次 Argon2 运算"，同时让运算照常发生。

    桩只能打在 `credentials._HASHER` 上：`argon2.PasswordHasher` 是 `__slots__` 类，
    `mock.patch.object(hasher_instance, "verify")` 会直接 AttributeError（读不了也写不了）。
    `wraps=` 保住真实运算，所以"零次"是真零次；而万一它被叫了，返回的也是真的判定结论，
    不会像裸 MagicMock 那样把"没人校验"伪装成"校验通过"。
    """
    shared = credentials.hasher()
    with mock.patch.object(credentials, "_HASHER", wraps=shared) as spy:
        yield spy.verify


def _fresh_db(test: unittest.TestCase) -> Path:
    """每例一份临时库（实现见 `sec_a_fixtures`）：本文件的用例反复写凭据行与失败计数。"""
    return sec_a_fixtures.fresh_db(test, filename="leg.db")


def _put_locked_until(username: str, value: str) -> None:
    """把 `locked_until` 直接写成给定文本：模拟"这一行不是本仓库写进去的"那批形状。

    产品侧的写入方只写带偏移的 ISO 串（`user_store.record_login_failure`），所以坏值只能
    来自运维手改、异源备份恢复、或 SQLite 的 `CURRENT_TIMESTAMP` 惯用法——认证腿对它们的
    口径是"坏了就当锁着"，不是"读不懂就当没锁"。
    """
    connection = user_store._connect()
    try:
        with connection:
            connection.execute(
                "UPDATE user_credentials SET locked_until = ? WHERE username = ?",
                (value, str(username)),
            )
    finally:
        connection.close()


class _AuditToTempFile(sec_a_fixtures.AuditToTempFileMixin, unittest.TestCase):
    """审计落到临时文件：既取到证，又不往仓库的 `data/audit.jsonl` 里写测试笔迹。"""


class _LongJwtSecret(sec_a_fixtures.LongJwtSecretMixin):
    """本文件的用例自带一枚够长的 JWT secret（≥32 字节）。

    默认 dev secret 短于 PyJWT 的建议下限，于是每次签发/校验都喊一句
    `InsecureKeyLengthWarning`。那是本机 `.env` 里那枚 secret 的事实（secret 卫生另有它
    自己的任务与门），不是认证腿的回归面；这里选择"用例自己配一把够长的钥匙"，而不是
    静音警告——静音会把别的来源的同一枚警告一起藏掉。钥匙只属于本文件：别的契约文件签的
    token 不许拿这把钥匙解得开，警告与撤销的归因才分得清。
    """

    SECRET = "sec-a-auth-leg-test-secret-0123456789abcdef"


class LegacyUpgradeTests(unittest.TestCase):
    """SECA-03 半边 A：升级路径不掉线，且当场收敛。"""

    def setUp(self):
        _fresh_db(self)

    def test_a_legacy_digest_still_logs_in_and_is_upgraded_in_place(self):
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        before = user_store.get_record("admin")

        result = auth.authenticate_with_result("admin", "admin123")

        self.assertIsNotNone(result.user)
        self.assertEqual("admin", result.user.username)
        self.assertTrue(result.password_change_required)
        after = user_store.get_record("admin")
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, after.algorithm)
        self.assertTrue(after.password_hash.startswith("$argon2id$"))
        self.assertTrue(after.must_change)
        # 渐进重哈希不改会话 ⇒ 版本不动（登录只改强度，不改 token 生命周期）
        self.assertEqual(before.credentials_version, after.credentials_version)

    def test_the_progressive_rehash_pays_the_slot_the_verify_just_gave_back(self):
        """一格槽就够走完整条腿：`argon2_max_concurrent_ops=1` 时"verify → 渐进重哈希"照样收敛。

        槽是**不可重入**的 `BoundedSemaphore`，所以写入侧一旦嵌在校验侧那一格里，同一线程第二次
        占槽就是自锁——症状不是挂死，而是当场 `PasswordCapacityError`，被登录腿那句
        `except Exception` 吞成"重哈希降级"：人进来了、legacy 行留着、响应面一切正常，升级静默
        不收敛。这条判的是结果：只给一格，行**必须**被换成 argon2id，且不留下降级 token。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(1)):
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNotNone(result.user)
        self.assertEqual("", result.audit_detail)
        self.assertEqual(
            credentials.ALGORITHM_ARGON2ID, user_store.get_record("admin").algorithm
        )

    def test_the_upgraded_row_no_longer_holds_the_legacy_digest(self):
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        auth.authenticate_with_result("admin", "admin123")
        self.assertNotIn(LEGACY_ADMIN, user_store.get_record("admin").password_hash)
        self.assertEqual(
            0, user_store.count_by_algorithm().get(credentials.ALGORITHM_LEGACY_SHA256, 0)
        )

    def test_a_rehash_write_failure_still_logs_in_and_records_degraded(self):
        """SECA-21：UPDATE 失败是收敛延迟，不是把用户挡在门外。"""
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        with mock.patch.object(
            user_store, "apply_rehash", side_effect=user_store.CredentialStoreError("locked db")
        ):
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNotNone(result.user)
        self.assertEqual("AUTH_REHASH_DEGRADED", result.audit_detail)
        self.assertTrue(result.password_change_required)
        self.assertEqual(
            credentials.ALGORITHM_LEGACY_SHA256, user_store.get_record("admin").algorithm
        )

    def test_capacity_loss_at_the_rehash_hop_degrades_instead_of_refusing_the_login(self):
        """闸门在写入侧安家之后，**成功登录之后**那一跳也可能抛容量错误：它不许变成 503。

        口令已经对了、判定已经给了，此刻"服务器没槽了"是一条可用性事实，不是凭据结论；
        让它把这次登录翻成 503 等于把闸门升级成第二道认证门（并给攻击者一条"占满槽 ⇒ 让已知
        口令的账号登不进去"的现成通路）。规格 §7.1 的排序里闸门在**运算之前**，不在运算之后
        补判一次。所以这里的形状与写盘失败完全一致：人进来、legacy 行留着、token 记下降级。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        with mock.patch.object(
            credentials,
            "hash_password",
            side_effect=credentials.PasswordCapacityError("slots exhausted at the write hop"),
        ):
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNotNone(result.user)
        self.assertEqual("AUTH_REHASH_DEGRADED", result.audit_detail)
        self.assertTrue(result.password_change_required)
        self.assertEqual(
            credentials.ALGORITHM_LEGACY_SHA256, user_store.get_record("admin").algorithm
        )
        # 降级不是静默：token 必须是那条 SUCCESS+degraded，而不是任何拒绝面。
        self.assertNotIn(result.audit_detail, (auth.AUDIT_INVALID_CREDENTIALS,))

    def test_an_argon2_row_with_drifted_params_rehashes_without_forcing_a_change(self):
        """needs_rehash 的两种来源要分开：参数漂移**不**置 must_change（规格 §8.3）。"""
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        stale = user_store.get_record("admin")
        with mock.patch.object(
            credentials, "needs_rehash", return_value=True
        ) as needs_rehash:
            result = auth.authenticate_with_result("admin", GOOD_PASSWORD)
        needs_rehash.assert_called_once()
        self.assertIsNotNone(result.user)
        self.assertFalse(result.password_change_required)
        after = user_store.get_record("admin")
        self.assertNotEqual(stale.password_hash, after.password_hash)
        self.assertFalse(after.must_change)
        self.assertEqual(stale.credentials_version, after.credentials_version)
        self.assertEqual("", result.audit_detail)

    def test_the_rehash_carries_the_version_of_the_row_the_login_leg_just_read(self):
        """钉的是**接线**：登录腿把它刚读到的那一行版本号交给 `apply_rehash`，只交一次。

        这里用 `wraps=` 让真写入照常发生，所以乐观锁今天是**赢**的（那一行的版本没被人动过），
        本枚用例因此不声称钉住"落空那一刻"的行为——落空的那一条由下面那枚真并发写者去钉。
        它要钉的是三件更容易写歪的事：期望版本来自同一次读、只叫一次、写成就没有降级 token。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        record = user_store.get_record("admin")
        with mock.patch.object(
            user_store, "apply_rehash", wraps=user_store.apply_rehash
        ) as rehash:
            result = auth.authenticate_with_result("admin", "admin123")
        rehash.assert_called_once()
        self.assertEqual(record.credentials_version, rehash.call_args.kwargs["expected_version"])
        self.assertEqual("", result.audit_detail)

    def test_a_rehash_that_loses_the_version_race_leaves_the_concurrent_winner_alone(self):
        """乐观锁真的落空（并发已改密）⇒ 登录照样成，但登录腿那一笔写不许覆写赢家。"""
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        stale = user_store.get_record("admin")
        real_rehash = user_store.apply_rehash

        def write_competitor(username: str, **kwargs) -> bool:
            # 竞态发生在"登录腿读完版本"与"登录腿写回"之间，所以这里先让并发改密落库
            # （它 bump 版本），再把参数原样交给真函数——那条 UPDATE 的 WHERE 于是必然落空。
            user_store.set_password_argon2(
                username, plain_password="a-brand-new-password 123", must_change=False
            )
            return real_rehash(username, **kwargs)

        with mock.patch.object(
            user_store, "apply_rehash", side_effect=write_competitor
        ):
            result = auth.authenticate_with_result("admin", "admin123")
        after = user_store.get_record("admin")
        self.assertIsNotNone(result.user)
        # 行归赢家：版本是并发改密 bump 出来的那一个，口令与门状态也都是它写的值。
        self.assertEqual(stale.credentials_version + 1, after.credentials_version)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, after.algorithm)
        self.assertFalse(after.must_change)
        # "没写成"就是没写成：降级 token 判的是这一笔写的结果，不事后查那一行归谁。
        # 口令错的那一条腿（新口令能进、旧口令进不去）由 `set_password_argon2` 的语义保证，
        # 这里只确认登录腿没有把赢家的编码串盖回去。
        self.assertEqual("AUTH_REHASH_DEGRADED", result.audit_detail)
        self.assertNotEqual(stale.password_hash, after.password_hash)
        self.assertIsNotNone(auth.authenticate_with_result("admin", "a-brand-new-password 123").user)

    def test_a_legacy_row_that_was_not_flagged_still_leaves_the_gate_up(self):
        """置门读的是**出身**，不是那一行原本的 `must_change`（§8.3 前半）。

        迁移工件里的 `must_change` 是历史字段（旧安装可能压根没这个概念），所以"legacy 行
        登录成功"本身就足以置门。少了这一臂，症状正是规格点名的那个窗口：行已升级成
        argon2id、人却可以直接自由读数据面。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=False)
        self.assertFalse(user_store.get_record("admin").must_change, "夹具得先真的是未置门的那一行")

        result = auth.authenticate_with_result("admin", "admin123")

        self.assertIsNotNone(result.user)
        self.assertTrue(result.password_change_required)
        after = user_store.get_record("admin")
        self.assertTrue(after.must_change)
        self.assertEqual(credentials.ALGORITHM_ARGON2ID, after.algorithm)

    def test_a_wrong_password_counts_a_failure_and_keeps_the_credential_row(self):
        """失败计数是账号级持久状态（§7.2 第二层），但一次错口令不改凭据行本身。"""
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        before = user_store.get_record("admin")
        result = auth.authenticate_with_result("admin", f"wrong-{GOOD_PASSWORD}")
        self.assertIsNone(result.user)
        self.assertEqual(auth.AUDIT_INVALID_CREDENTIALS, result.audit_detail)
        after = user_store.get_record("admin")
        self.assertEqual(1, after.failed_attempts)
        self.assertIsNone(after.locked_until)
        self.assertEqual(before.password_hash, after.password_hash)
        self.assertEqual(before.credentials_version, after.credentials_version)

    def test_the_account_locks_at_the_configured_attempt_ceiling(self):
        """阈值读 `settings.account_max_failed_attempts`：达到即写 `locked_until`。"""
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        attempts = int(config_module.settings.account_max_failed_attempts)
        for _ in range(attempts):
            auth.authenticate_with_result("admin", f"wrong-{GOOD_PASSWORD}")
        record = user_store.get_record("admin")
        self.assertEqual(attempts, record.failed_attempts)
        self.assertIsNotNone(record.locked_until)

    def test_a_successful_login_clears_the_failed_attempt_counter(self):
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        auth.authenticate_with_result("admin", f"wrong-{GOOD_PASSWORD}")
        self.assertEqual(1, user_store.get_record("admin").failed_attempts)
        self.assertIsNotNone(auth.authenticate_with_result("admin", GOOD_PASSWORD).user)
        self.assertEqual(0, user_store.get_record("admin").failed_attempts)

    def test_a_broken_locked_until_timestamp_is_treated_as_locked(self):
        """时间戳坏了 ⇒ 宁可当锁定：不给一次免费的 Argon2 运算，也不把它读成"没锁"。"""
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        _put_locked_until("admin", "not-a-timestamp")
        with _hasher_runs() as verify:
            result = auth.authenticate_with_result("admin", GOOD_PASSWORD)
        self.assertIsNone(result.user)
        self.assertEqual("AUTH_LOGIN_LOCKED", result.audit_detail)
        self.assertEqual(0, verify.call_count, "坏时间戳被读成了「没锁」")

    def test_a_locked_until_timestamp_without_an_offset_is_treated_as_locked(self):
        """**解析得出但没有偏移**的那一种坏法，判定与"解析不出"同一臂：当锁着。

        `datetime.fromisoformat("2099-01-01 00:00:00")` 不报错，它给出一枚 naive datetime，
        而 naive 与 aware 的 `now` 一比就是 TypeError——只捕 ValueError 的话这条异常会逃出
        认证腿变成 500，且"锁不锁"这件事根本没被判过。这种形态的产地是运维手改、异源备份
        恢复、SQLite 的 `CURRENT_TIMESTAMP` 惯用法，也就是本分支存在的整一类损坏行。
        """
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        _put_locked_until("admin", "2099-01-01 00:00:00")
        with _hasher_runs() as verify:
            result = auth.authenticate_with_result("admin", GOOD_PASSWORD)
        self.assertIsNone(result.user)
        self.assertEqual("AUTH_LOGIN_LOCKED", result.audit_detail)
        self.assertEqual(0, verify.call_count, "无偏移的时间戳被读成了「没锁」")


class UnifiedFailureTests(unittest.TestCase):
    """SECA-13 结构半边 + §9.1：四态在响应面上完全相同。"""

    def setUp(self):
        _fresh_db(self)

    def _identities(self) -> dict[str, directory.UserIdentity]:
        identities = dict(directory.load_identities(include_demo=True))
        identities["paused"] = directory.UserIdentity(
            username="paused", display_name="停用账号", role="VIEWER", enabled=False
        )
        identities["orphan"] = directory.UserIdentity(
            username="orphan", display_name="无凭据账号", role="VIEWER"
        )
        return identities

    def _results(self):
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        with directory.override_identities(self._identities()):
            return [
                auth.authenticate_with_result("nobody-at-all", "whatever 123456"),
                auth.authenticate_with_result("paused", "whatever 123456"),
                auth.authenticate_with_result("orphan", "whatever 123456"),
                auth.authenticate_with_result("admin", "wrong-password 123456"),
            ]

    def test_all_four_states_return_the_same_user_and_audit_detail(self):
        results = self._results()
        self.assertTrue(all(result.user is None for result in results))
        self.assertEqual(
            {auth.AUDIT_INVALID_CREDENTIALS}, {result.audit_detail for result in results}
        )
        self.assertTrue(
            all(result.password_change_required is False for result in results),
            "失败态不许顺带说出「改完口令就能进」这类状态事实",
        )

    def test_all_four_states_consume_exactly_one_argon2_run_each(self):
        """判定用结构事实，不用毫秒阈值（规格 §7.3）：四态各一次、同一档位、同一枚实例。"""
        expected_profile = _current_profile()
        shared = credentials.hasher()
        self.assertIs(shared, credentials.hasher())      # 单例：桩换不掉真参与运算的那一枚
        with _hasher_runs() as verify:
            results = self._results()
        self.assertEqual(4, len(results))
        self.assertTrue(all(result.user is None for result in results))
        # 四态各一次运算，且每次都落到当前档位上：哑校验不是"免费的早退"。
        self.assertEqual(4, verify.call_count, [call.args for call in verify.call_args_list])
        self.assertEqual(
            {expected_profile},
            {_PROFILE.search(str(call.args[0])).group() for call in verify.call_args_list},
        )

    def test_a_wrong_password_on_a_legacy_row_consumes_one_argon2_run_too(self):
        """第四态的另一种 algorithm 形态：legacy 行的错口令也得付一次同档运算。

        `credentials.verify_password` 对 legacy 行只做 `hmac.compare_digest`，压根不碰
        Argon2。少这一笔就有两件事同时成立：猜未升级账号的口令几乎免费，且响应时间直接
        指纹出"这一行还是 legacy"——收敛窗口里那就是一张账号枚举面，而 §7.3 的四态合一
        只说了"第四态执行真实 verify"，没预料到第四态有两种形态。账号级失败计数只滞后拦
        高频猜测，拦不住这个时间差。
        """
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        with _hasher_runs() as verify:
            result = auth.authenticate_with_result("admin", "wrong-admin123")
        self.assertIsNone(result.user)
        self.assertEqual(auth.AUDIT_INVALID_CREDENTIALS, result.audit_detail)
        self.assertEqual(1, verify.call_count, [call.args for call in verify.call_args_list])
        self.assertEqual(
            {_current_profile()},
            {_PROFILE.search(str(call.args[0])).group() for call in verify.call_args_list},
        )
        # 补的那一次是哑校验：它占运算，但绝不给结论。
        self.assertEqual(credentials.dummy_hash(), verify.call_args_list[0].args[0])
        self.assertEqual(1, user_store.get_record("admin").failed_attempts)

    def test_a_disabled_identity_cannot_log_in_even_with_a_valid_password(self):
        """`enabled=false` 归入"无可校验凭据"那条腿（§7.1 步骤 1）：口令对也一样进不去。"""
        user_store.create_argon2("paused", plain_password=GOOD_PASSWORD, must_change=False)
        with directory.override_identities(self._identities()):
            result = auth.authenticate_with_result("paused", GOOD_PASSWORD)
        self.assertIsNone(result.user)
        self.assertEqual(auth.AUDIT_INVALID_CREDENTIALS, result.audit_detail)
        self.assertEqual(
            credentials.ALGORITHM_ARGON2ID, user_store.get_record("paused").algorithm,
            "停用不是改密理由：那一行必须原样留着",
        )

    def test_a_locked_account_reports_the_internal_detail_only(self):
        """SECA-14：对外仍是与其余四态逐字相同的中文响应面，锁定原因只进审计 token。"""
        user_store.create_argon2("admin", plain_password=GOOD_PASSWORD, must_change=False)
        user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
        with _hasher_runs() as verify:
            result = auth.authenticate_with_result("admin", GOOD_PASSWORD)
        self.assertIsNone(result.user)
        self.assertEqual("AUTH_LOGIN_LOCKED", result.audit_detail)
        # 锁定判定在昂贵运算之前（§7.1 步骤 3 早于 4）；`locked_until` 是"锁到的时刻"，
        # 把它读成"已经过期"会让这一枚直接变成"永远锁不住"。
        self.assertEqual(0, verify.call_count)


class HttpFailureSurfaceTests(_LongJwtSecret, _AuditToTempFile):
    """§7.3 的判定对象是 HTTP 面：状态码 + 响应体 + 审计 token 三件全等。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials()

    def _post(self, username: str, password: str):
        return TestClient(fastapi_app).post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def test_the_four_failure_states_are_identical_on_status_body_and_audit(self):
        identities = dict(directory.load_identities(include_demo=True))
        identities["paused"] = directory.UserIdentity(
            username="paused", display_name="停用账号", role="VIEWER", enabled=False
        )
        identities["orphan"] = directory.UserIdentity(
            username="orphan", display_name="无凭据账号", role="VIEWER"
        )
        bodies: list[tuple[int, str]] = []
        with directory.override_identities(identities):
            for username, password in (
                ("nobody-at-all", "whatever 123456"),
                ("paused", "whatever 123456"),
                ("orphan", "whatever 123456"),
                ("admin", "wrong-password 123456"),
            ):
                response = self._post(username, password)
                bodies.append((response.status_code, response.text))
            # 锁定态排在四态之后：它需要前面那笔失败计数真的把账号锁上。
            user_store.record_login_failure("admin", max_attempts=1, lock_seconds=900)
            locked = self._post("admin", "admin123")
        expected = (401, '{"detail":"用户名或密码错误"}')
        self.assertEqual([expected] * 4, bodies)
        self.assertEqual(expected, (locked.status_code, locked.text))
        # 锁定原因只在审计面；响应体里连「锁定」两个字都不许出现（§7.4）
        self.assertNotIn("锁定", locked.text)
        self.assertEqual(
            [auth.AUDIT_INVALID_CREDENTIALS] * 4 + ["AUTH_LOGIN_LOCKED"],
            [event["detail"] for event in self.events()],
        )
        self.assertEqual(
            [("LOGIN", "DENIED", "UNKNOWN")] * 5,
            [(e["action"], e["status"], e["role"]) for e in self.events()],
        )

    def test_a_denied_login_carries_neither_a_token_nor_the_password(self):
        response = self._post("admin", "wrong-password 123456")
        self.assertNotIn("access_token", response.text)
        self.assertNotIn("wrong-password 123456", response.text)
        self.assertNotIn(
            "wrong-password 123456", self.audit_path.read_text(encoding="utf-8")
        )


class PasswordCapacitySurfaceTests(_LongJwtSecret, _AuditToTempFile):
    """容量溢出在两条 HTTP 腿上的形状：503 + 中文文案 + `password_capacity`，一格不多一格不少。

    这枚钉子原本是 Task 6 埋的**反向钉**（那时没人翻译 ⇒ 断的是"未处理 500 + 零审计"这个
    当下缺口）。翻译落地后它**改了断言、用例保留**：留着旧断言等于把门反着钉——下一次
    "翻译又被删掉"它会照样喊绿。

    为什么这条值得单独有脸：认证腿切换之后，每一次登录（含未知账号那条哑校验）都要过一次
    `settings.argon2_max_concurrent_ops` 那么宽的槽。几枚并发的口令猜测就能把登录面打成
    不可用，而"不可用"必须以它自己的状态码出现，不能被伪装成凭据结论（401 会把一次服务过载
    说成"你的口令不对"，用户据此改口令、运维据此查凭据，两头都得到错地图）。
    """

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials()

    def _login(self, username: str, password: str = "admin123"):
        return TestClient(fastapi_app, raise_server_exceptions=False).post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def test_capacity_exhaustion_surfaces_as_a_translated_503_on_the_login_leg(self):
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            response = self._login("admin")
        self.assertEqual(503, response.status_code, response.text)
        # 展示面只有中文那一句（字面量钉死，不比"常量 vs 常量"），审计面只有 token。
        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
        self.assertEqual(
            [auth.AUDIT_PASSWORD_CAPACITY], [event["detail"] for event in self.events()]
        )
        # 堆栈不外泄、口令不上响应面（§9.3 的脱敏作用域与这条可用性路径无关，照样成立）。
        self.assertNotIn("admin123", response.text)
        self.assertNotIn("Traceback", response.text)
        # 英文 token 不许渗进 body：两栏一旦互换，展示面就成了机器可读性的抄本。
        self.assertNotIn("password_capacity", response.text)

    def test_the_capacity_face_says_the_same_thing_about_an_unknown_account(self):
        """503 不构成账号存在性枚举面——**为什么**：未知账号那条腿过的是同一道槽。

        §7.3 让四种失败态各消耗一次同档运算，容量这道闸 therefore 对"有这一行凭据"和
        "根本没有这个账号"同样会关；两脸逐字节相同 ⇒ 这一格可用性事实里读不出任何身份结论。
        这也是把 429/503 排在凭据结论之前的全部意义：先说"现在不行"，后说"你是谁"。
        """
        faces = set()
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            for username in ("admin", "nobody-at-all"):
                response = self._login(username)
                faces.add((response.status_code, response.text))
        self.assertEqual(1, len(faces), faces)
        self.assertEqual(503, next(iter(faces))[0])

    def test_a_locked_account_shares_the_capacity_face_instead_of_leaking_a_401(self):
        """§7.1 步骤 0 的**第二半**：容量判定与节流同一步，所以饱和时锁定脸也是 503。

        锁定那条腿在昂贵运算之前就返回结论（§7.4 显式排除它于 timing 承诺之外）。于是只要
        容量判定还排在身份/凭据/锁定查找**之后**，"锁着的账号答 401、其余一切答 503"这条
        差就在饱和下成立——§7.4 拿可用性代价换来的那张不可区分脸，随即变成一条账号存在性
        指纹。这里要的是逐字节同脸，且两格都是可用性结论、不含任何凭据语义。
        """
        _put_locked_until("admin", "2099-01-01T00:00:00+00:00")
        faces = set()
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            for username in ("admin", "nobody-at-all"):
                response = self._login(username, GOOD_PASSWORD)
                faces.add((response.status_code, response.text))
        self.assertEqual({(503, '{"detail":"服务繁忙，请稍后重试"}')}, faces)

    def test_the_change_leg_is_the_second_capacity_face_and_gets_the_same_503(self):
        """/api/auth/password/change 校验旧口令 ⇒ 它是第二个容量面，不是凭据结论的第二张脸。

        两条腿都跑 `authenticate_with_result`，因此都从同一道闸门里过；只翻译登录那一腿的
        话，攻击者就把改密面当成免费的 DoS 放大器（同一枚槽、无人接异常、裸栈上 500）。
        """
        user = auth.authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        headers = {"Authorization": f"Bearer {auth.issue_token(user)}"}
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            response = TestClient(fastapi_app, raise_server_exceptions=False).post(
                "/api/auth/password/change",
                json={
                    "current_password": "admin123",
                    "new_password": "a-brand-new-password 4242",
                },
                headers=headers,
            )
        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
        self.assertEqual(
            [auth.AUDIT_PASSWORD_CAPACITY], [event["detail"] for event in self.events()]
        )
        self.assertNotIn("admin123", response.text)
        self.assertNotIn("a-brand-new-password", response.text)
        # 新口令没改进去：容量结论不产生任何写副作用（这一腿的写路径在校验之后）。
        self.assertIsNone(user_store.get_record("admin").locked_until)

    def test_the_reset_leg_write_is_the_third_capacity_face_and_gets_the_same_503(self):
        """写入侧进闸之后，管理员重置这条腿**才**真的够到容量面（此前它压根抛不出那枚异常）。

        这一格的读者已经过 `system:operate`，所以 503 在这里不构成枚举面——对外那张脸仍是登录腿
        的四态合一（§9.1）。它钉的是另一件事：可用性事实不许在任何一条腿上长成未处理的裸栈，
        也不许顺手把口令写进去（容量结论没有写副作用）。
        """
        user = auth.authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        headers = {"Authorization": f"Bearer {auth.issue_token(user)}"}
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            response = TestClient(fastapi_app, raise_server_exceptions=False).post(
                "/api/admin/users/admin/password/reset",
                json={"new_password": "a-brand-new-password 4242"},
                headers=headers,
            )
        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
        self.assertNotIn("a-brand-new-password", response.text)
        self.assertNotIn("Traceback", response.text)
        self.assertEqual(
            [auth.AUDIT_PASSWORD_CAPACITY], [event["detail"] for event in self.events()]
        )
        # 没写进去：门没开、版本没 bump，口令还是 seed 那一枚。
        record = user_store.get_record("admin")
        self.assertFalse(record.must_change)
        self.assertEqual(1, record.credentials_version)

    def test_the_change_legs_write_hop_is_a_capacity_face_of_its_own(self):
        """把凭据那一跳用替身挡开，剩下的判据才**只**属于写库那一跳。

        第一跳与写跳共用同一道闸、且**串行**（第一跳先还槽），所以只掏空 `_SLOTS` 时红的是前一跳
        ——那一格已由上面 `test_the_change_leg_is_the_second_capacity_face…` 钉住。这里替掉前一跳，
        钉的就是"provisioning 进闸之后，改密腿的写面有没有人翻译"：没有这条，写腿的容量面可以
        悄悄退回裸 500，而整个文件依旧全绿。
        """
        user = auth.authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        headers = {"Authorization": f"Bearer {auth.issue_token(user)}"}
        verified = auth.LoginResult(user, "", False)
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            with mock.patch(
                "app.main.authenticate_with_result", return_value=verified
            ) as first_hop:
                response = TestClient(fastapi_app, raise_server_exceptions=False).post(
                    "/api/auth/password/change",
                    json={
                        "current_password": "admin123",
                        "new_password": "a-brand-new-password 4242",
                    },
                    headers=headers,
                )
        first_hop.assert_called_once()
        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual({"detail": "服务繁忙，请稍后重试"}, response.json())
        self.assertNotIn("a-brand-new-password", response.text)
        self.assertNotIn("Traceback", response.text)
        self.assertFalse(user_store.get_record("admin").must_change)

    def test_capacity_exhaustion_is_the_same_on_the_dummy_leg_as_on_a_real_verify(self):
        """哑校验与真 verify 共用同一道闸：不存在"拿不存在的账号绕过容量门"那条腿。

        这条钉的是**腿级**事实：上游拿到的是同一个 `PasswordCapacityError`，而不是一个认证
        结论——HTTP 面那两枚 503 钉子翻译的就是它，翻译没落地时这里也还剩一条红。
        """
        for username in ("admin", "nobody-at-all"):
            with self.subTest(username=username):
                with mock.patch.object(
                    credentials, "_SLOTS", threading.BoundedSemaphore(0)
                ):
                    with self.assertRaises(credentials.PasswordCapacityError):
                        auth.authenticate_with_result(username, "whatever 123456")


class MustChangeGateTests(_LongJwtSecret, unittest.TestCase):
    """§8.4：门在依赖层，顺序是 authentication → must_change → authorization。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials("admin")

    def _token(self, password: str = "admin123") -> str:
        """先拿 token 再动凭据行：门的判定读的是表，不是签发那一刻的状态。"""
        user = auth.authenticate("admin", password)
        self.assertIsNotNone(user)
        return auth.issue_token(user)

    def _force_change(self, *, must_change: bool = True) -> None:
        user_store.set_password_argon2(
            "admin", plain_password="a-brand-new-password 123", must_change=must_change
        )

    def _gated_token(self) -> str:
        """**先换代、再签 token**：门的判据从来是"一枚活着的 token 撞上门"。

        顺序反过来（旧 token + 改密）先撞上的会是 §7.5 的凭据纪元不符那条 401，那一例测的
        就不是门了。下面三例共用这一枚夹具，`test_a_dead_token_does_not_reach_the_gate`
        钉的正是反过来的那个顺序。
        """
        self._force_change()
        return self._token("a-brand-new-password 123")

    def test_require_user_blocks_until_the_password_is_changed(self):
        token = self._gated_token()
        with self.assertRaises(HTTPException) as raised:
            auth.require_user(f"Bearer {token}")
        self.assertEqual(403, raised.exception.status_code)
        self.assertEqual("当前账号需先修改口令", raised.exception.detail)

    def test_the_whitelist_dependency_still_returns_the_user(self):
        token = self._gated_token()
        user = auth.require_user_pending_password(f"Bearer {token}")
        self.assertEqual("admin", user.username)

    def test_a_dead_token_does_not_reach_the_gate(self):
        """§8.4 的顺序：authentication 在门之前，而"认证"今天含凭据纪元比对。

        同一枚旧 token、同一张置了门的表：出路必须是 401「无效登录凭证」，不能是 403。
        判成 403 的写法（先查门再验 token）会把"你的会话已经作废"说成"你去改个口令"，
        而那恰好是撤销通道最不想对外确认的那件事。
        """
        token = self._token()
        self._force_change()
        with self.assertRaises(HTTPException) as raised:
            auth.require_user(f"Bearer {token}")
        self.assertEqual(401, raised.exception.status_code)
        self.assertEqual("无效登录凭证", raised.exception.detail)

    def test_a_completed_change_reopens_the_gated_leg(self):
        self._force_change(must_change=False)
        self.assertEqual(
            "admin", auth.require_user(f"Bearer {self._token('a-brand-new-password 123')}").username
        )

    def test_the_gate_denial_is_audited_as_an_enum_not_as_the_chinese_copy(self):
        token = self._gated_token()
        with mock.patch.object(auth, "_record_event") as record:
            with self.assertRaises(HTTPException):
                auth.require_user(f"Bearer {token}")
        record.assert_called_once_with(
            username="admin",
            role="ADMIN",
            action="AUTHORIZATION",
            status="DENIED",
            detail="password_change_required",
        )

    def test_authentication_still_comes_first(self):
        """没有有效 token 就轮不到查门：门的顺序在 authentication 之后（§8.4 末段）。"""
        for authorization, copy in ((None, "请先登录"), ("Bearer nonsense", "无效登录凭证")):
            with self.subTest(authorization=authorization):
                with self.assertRaises(HTTPException) as raised:
                    auth.require_user_pending_password(authorization)
                self.assertEqual(401, raised.exception.status_code)
                self.assertEqual(copy, raised.exception.detail)


class HttpMustChangeGateTests(_LongJwtSecret, _AuditToTempFile):
    """SECA-03 的另一半：升级成功当场被门挡住数据面，改完口令才通。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        user_store.import_legacy_digest("admin", LEGACY_ADMIN, must_change=True)
        self.client = TestClient(fastapi_app)

    def _headers(self) -> dict[str, str]:
        login = self.client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123"}
        )
        self.assertEqual(200, login.status_code, login.text)
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_whitelist_passes_while_the_data_face_is_blocked(self):
        headers = self._headers()
        self.assertEqual(200, self.client.get("/api/auth/me", headers=headers).status_code)
        blocked = self.client.get("/api/knowledge-bases", headers=headers)
        self.assertEqual(403, blocked.status_code, blocked.text)
        self.assertEqual("当前账号需先修改口令", blocked.json()["detail"])
        self.assertEqual(
            [("DENIED", "password_change_required")],
            [(e["status"], e["detail"]) for e in self.events() if e["action"] == "AUTHORIZATION"],
        )

    def test_after_the_password_change_the_data_face_opens(self):
        headers = self._headers()
        self.assertEqual(403, self.client.get("/api/knowledge-bases", headers=headers).status_code)
        user_store.set_password_argon2(
            "admin", plain_password="a-brand-new-password 123", must_change=False
        )
        # 门开了不等于旧会话活了（§7.5）：手里那一枚因为凭据换代直接作废，
        # 判成 401 才对——"改完口令还用旧 token 进得去"是第二条撤销绕过。
        stale = self.client.get("/api/knowledge-bases", headers=headers)
        self.assertEqual(401, stale.status_code, stale.text)
        self.assertEqual("无效登录凭证", stale.json()["detail"])
        relogin = self.client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "a-brand-new-password 123"},
        )
        self.assertEqual(200, relogin.status_code, relogin.text)
        opened = self.client.get(
            "/api/knowledge-bases",
            headers={"Authorization": f"Bearer {relogin.json()['access_token']}"},
        )
        self.assertEqual(200, opened.status_code, opened.text)

    def test_a_degraded_rehash_is_written_to_the_audit_log_by_the_http_leg(self):
        """§8.3 的"不静默"落在 HTTP 面上只有那四行 `main.py`：这一枚钉的就是那四行。

        腿级用例（`test_a_rehash_write_failure_still_logs_in_and_records_degraded`）只证明
        `LoginResult.audit_detail` 里带了那个 token；token 变成审计事件靠的是登录处理里
        "成功面上 detail 非空 ⇒ 叫 `record_login_event`"那一臂。这一枚打的是真 HTTP 面，
        所以 §8.3 那句"不静默"要有审计落笔，只有这一枚保证得了：降级事件必须与既有成功
        事件**同时**在场，少一笔就等于把"人已经进来、行还没收敛"这件事只留在 `legacy_count`
        那个数字里。
        """
        with mock.patch.object(
            user_store, "apply_rehash",
            side_effect=user_store.CredentialStoreError("database is locked"),
        ):
            login = self.client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin123"}
            )
        self.assertEqual(200, login.status_code, login.text)
        self.assertIn("access_token", login.json())
        # 降级那一笔与既有的成功事件**同时**存在：`main.py` 不因为多了一笔就少写既有那一笔
        # （SEC-A-006 的既有成功面一字不动），也不把降级写成 DENIED——人已经进来了。
        self.assertEqual(
            [("SUCCESS", "AUTH_REHASH_DEGRADED"), ("SUCCESS", None)],
            [
                (event["status"], event.get("detail"))
                for event in self.events()
                if event["action"] == "LOGIN"
            ],
        )
        self.assertEqual("UNKNOWN", self.events()[0]["role"])
        self.assertNotIn("admin123", self.audit_path.read_text(encoding="utf-8"))


class SourceRemovalTests(unittest.TestCase):
    #: "把执行停下来一会儿"的调用名。`sleep` 一族之外还要收 `wait`：`threading.Event().wait()`
    #: 与 `time.sleep(1)` 在这条腿上做的是同一件事（台账 Task 5 那一格：旧判据只认 `sleep`，
    #: `Event().wait()` 整条漏走）。**刻意不收 `join`**——本仓的 `str.join` 光这五个模块里就有
    #: 四处，收它等于把误判面做出来；而误判一多，下一个读代码的人来放宽的就是这枚钉子本身。
    #: 也不指望这张词表穷尽一切（`queue.get()` 阻塞、`select.select()` 同理）：它管的是
    #: "最常被想到的那两种修平手法"，命中即红、由人来判，不是自动化的意图检测。
    DELAY_CALL_NAMES = frozenset({"sleep", "wait"})

    #: 同一件"停下来"的写法（含台账点名的 `Event().wait()` 那一发，两种绑定都演）。
    DELAY_SHAPES = (
        "import time\n\n\ndef f():\n    time.sleep(1)\n",
        "from time import sleep\n\n\ndef f():\n    sleep(1)\n",
        "import asyncio\n\n\nasync def f():\n    await asyncio.sleep(1)\n",
        "from threading import Event\n\n\ndef f():\n    Event().wait(1)\n",
        "import threading\n\n\ndef f():\n    threading.Event().wait(1)\n",
    )
    #: 反向样本：形似而不属于这张词表的调用，一条都不许进命中集（`join` 是**明知不收**的那一个，
    #: 收进来判红的那些写法归上面的词表，不由这两条负责）。
    NON_DELAY_SHAPES = (
        "def f(parts):\n    return ''.join(parts)\n",
        "def f(bucket):\n    return bucket.allow('admin|127.0.0.1')\n",
    )

    @classmethod
    def _delay_call_lines(cls, tree: ast.AST) -> list[int]:
        """一棵 AST 里"调用点上函数名落在延迟词表内"的行号。"""
        lines: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in cls.DELAY_CALL_NAMES:
                lines.append(node.lineno)
        return lines

    def test_auth_no_longer_holds_a_user_table_or_a_password_hash(self):
        self.assertFalse(hasattr(auth, "USERS"))
        self.assertFalse(hasattr(auth, "_password_digest"))

    def test_auth_imports_no_hashing_primitive_for_password_work(self):
        """口令运算收在 `credentials.py`：auth 里连 `hashlib` / `hmac` 都不该再出现。"""
        tree = ast.parse(Path(auth.__file__).read_text(encoding="utf-8"))
        heads: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                heads.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                heads.add(node.module.split(".")[0])
        self.assertEqual(set(), heads & {"hashlib", "hmac"}, sorted(heads))

    def test_no_artificial_delay_on_the_login_leg(self):
        """§7.4：统一靠"锁定路径不跑 Argon2"，不靠 sleep 修平（人工延迟本身是攻击面）。

        判据是 AST，而且扫的是登录腿的**调用图**（编排层 `auth` + 运算层 `credentials` +
        两条被叫到的状态腿 `user_store`/`directory`）：单子串判据只盯一枚文件、别处一个字
        都不说，而延迟最可能被加到的正是运算层那一侧。这里认的是调用点上的**函数名**——
        裸 `sleep()` 与 `time.sleep()` / `gevent.sleep()` / `asyncio.sleep()` 这类属性调用
        同形命中，判的是源码结构而不是某一段文本有没有出现过。

        词表本轮由"只有 `sleep`"扩到 `DELAY_CALL_NAMES`（台账 Task 5 那一格：`Event().wait()`
        与 `time.sleep(1)` 在这条腿上做的是同一件事，旧判据整条漏走），扩得对不对由同文件的
        `test_the_delay_detector_sees_the_shapes_it_claims_to` 当场自证。
        """
        call_graph = (auth, credentials, user_store, directory, login_throttle)
        offenders: list[str] = []
        for module in call_graph:
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            offenders.extend(f"{module.__name__}:{lineno}"
                             for lineno in self._delay_call_lines(tree))
        self.assertEqual([], offenders, f"登录腿的调用图上出现人工延迟：{offenders}")

    def test_the_delay_detector_sees_the_shapes_it_claims_to(self):
        """门自己的覆盖面：每一种"停下来"的写法都判得出，且反向样本一条都不进命中集。

        这一枚是加宽词表时才补的：只在真树上跑的判据说不出"它今天抓得住哪几种写法"，
        而下一位想加延迟的人换个写法（`Event().wait()` 就是台账点名的那一种）它就静默。
        """
        for source in self.DELAY_SHAPES:
            with self.subTest(shape=source.splitlines()[0]):
                self.assertEqual(1, len(self._delay_call_lines(ast.parse(source))),
                                 f"这一形态没被认成人工延迟：{source!r}")
        for source in self.NON_DELAY_SHAPES:
            with self.subTest(benign=source.splitlines()[-1].strip()):
                self.assertEqual([], self._delay_call_lines(ast.parse(source)),
                                 f"误判了一条不是延迟的调用：{source!r}")

    def test_every_demo_login_path_is_argon2_after_the_seed(self):
        """SECA-04b 的一半：全新库（无升级工件）不可能出现 legacy 行。"""
        _fresh_db(self)
        ensure_demo_credentials()
        self.assertEqual(
            {},
            {
                algorithm: count
                for algorithm, count in user_store.count_by_algorithm().items()
                if algorithm != credentials.ALGORITHM_ARGON2ID
            },
        )

    def test_a_missing_credential_row_never_imports_the_upgrade_artifact(self):
        """SECA-04b 的另一半（M19 的靶心）：缺行是"无可校验凭据"，不是"那就导 legacy"。"""
        _fresh_db(self)
        with mock.patch.object(
            credentials_migration.user_store,
            "import_legacy_digest",
            side_effect=AssertionError("全新安装不许写 legacy 行"),
        ):
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNone(result.user)
        self.assertEqual(auth.AUDIT_INVALID_CREDENTIALS, result.audit_detail)
        self.assertEqual({}, user_store.count_by_algorithm())

    def test_enterprise_mode_with_no_credentials_fails_closed_rather_than_500(self):
        """零账号 + 零凭据 ⇒ 统一 401。500 会把「配置未就绪」泄成一条堆栈。"""
        _fresh_db(self)
        with mock.patch.object(
            config_module.settings, "security_enterprise_mode", True
        ), directory.override_identities({}):
            response = TestClient(fastapi_app).post(
                "/api/auth/login", json={"username": "admin", "password": "admin123"}
            )
        self.assertEqual(401, response.status_code)
        # 展示面中文；审计面才是 invalid_credentials
        self.assertEqual("用户名或密码错误", response.json()["detail"])
        self.assertNotIn("traceback", response.text.lower())

    def test_the_session_seed_happened_exactly_once(self):
        """SECA-24 的性能半边：seed 次数 ≤ 身份数，不随用例数增长。

        再叫一次 `seed_demo_credentials()` 也必须原地不动（每行都已在会话库里）——
        这一句同时钉住"台账只由会话级 seed 写"和"重复调用不重算 Argon2"两件事。
        """
        seed_demo_credentials()
        self.assertEqual(5, len(SEED_RECORD))
        self.assertEqual(5, len(set(SEED_RECORD)))


class AuditVocabularyTests(unittest.TestCase):
    """登录面的 `detail` 是封闭枚举：五枚取值 + 成功面的空串，自由文本不得进入。"""

    def test_the_three_tokens_keep_their_frozen_spellings(self):
        self.assertEqual("invalid_credentials", auth.AUDIT_INVALID_CREDENTIALS)
        self.assertEqual("AUTH_LOGIN_LOCKED", auth.AUDIT_LOGIN_LOCKED)
        self.assertEqual("AUTH_REHASH_DEGRADED", auth.AUDIT_REHASH_DEGRADED)

    def test_the_two_availability_tokens_keep_their_frozen_spellings(self):
        """两格可用性事实也是枚举成员，不是绕过值域的第二条审计腿。

        拼写进枚举、枚举由 writer 自己判成员——加一枚 token 的正确做法只有这一种：
        扩 `LOGIN_AUDIT_DETAILS`，而不是在 `main.py` 里直接叫 `_record_event`。
        """
        self.assertEqual("login_throttled", auth.AUDIT_LOGIN_THROTTLED)
        self.assertEqual("password_capacity", auth.AUDIT_PASSWORD_CAPACITY)
        self.assertEqual("登录尝试过于频繁，请稍后再试", auth.COPY_LOGIN_THROTTLED)
        self.assertEqual("服务繁忙，请稍后重试", auth.COPY_PASSWORD_CAPACITY)
        # 展示面与审计面永不互换（§9.1 两栏）：中文文案不是枚举成员，token 不上响应体。
        self.assertNotIn(auth.COPY_LOGIN_THROTTLED, auth.LOGIN_AUDIT_DETAILS)
        self.assertNotIn(auth.COPY_PASSWORD_CAPACITY, auth.LOGIN_AUDIT_DETAILS)

    def test_the_enum_lives_in_one_tuple_and_the_writer_is_the_one_that_checks_it(self):
        """值域由 `record_login_event` 自己把：判定用同一枚 tuple 常量，不靠调用方抄字符串。

        只比"三个常量字面量 vs 三个常量字面量"的那种钉子是同一份东西跟自己比——把值域换成
        两枚、或往审计出口塞第四枚取值，它都照样绿。这里钉的是**出口处的成员判定**：
        tuple 是唯一的值域出处，而值域外的文本必须在写手面前抛，不是被洗成合法 token。
        """
        self.assertEqual(
            (auth.AUDIT_INVALID_CREDENTIALS, auth.AUDIT_LOGIN_LOCKED,
             auth.AUDIT_REHASH_DEGRADED, auth.AUDIT_LOGIN_THROTTLED,
             auth.AUDIT_PASSWORD_CAPACITY),
            auth.LOGIN_AUDIT_DETAILS,
        )
        with mock.patch.object(auth, "_record_event") as record:
            for detail in auth.LOGIN_AUDIT_DETAILS:
                auth.record_login_event(username="admin", detail=detail)
        self.assertEqual(list(auth.LOGIN_AUDIT_DETAILS),
                         [call.kwargs["detail"] for call in record.call_args_list])
        with mock.patch.object(auth, "_record_event") as record:
            for escaped in ("用户名或密码错误", "invalid_credential", "AUTH_LOGIN_LOCK "):
                with self.subTest(detail=escaped):
                    with self.assertRaises(ValueError):
                        auth.record_login_event(username="admin", detail=escaped)
            record.assert_not_called()

    def test_the_success_face_never_reaches_the_audit_writer_through_this_door(self):
        """空串是**成功面**的取值：它到了这里就是一条 DENIED + 空白 detail 的伪拒绝事件。

        "成功路径的 `audit_detail` 为空、事件由既有 `_audit(user,'LOGIN')` 记"这件事要成立，
        空值就必须根本进不了这个出口——把它写成 DENIED 等于凭空造出一条不存在的拒绝。
        """
        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(username="admin", detail="")
        record.assert_not_called()

    def test_a_denied_login_audits_exactly_one_event_with_the_frozen_shape(self):
        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(
                username="ghost", detail=auth.AUDIT_INVALID_CREDENTIALS
            )
        record.assert_called_once_with(
            username="ghost",
            role="UNKNOWN",
            action="LOGIN",
            status="DENIED",
            detail="invalid_credentials",
        )

    def test_an_empty_username_is_recorded_as_unknown_not_as_blank(self):
        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(username="", detail=auth.AUDIT_INVALID_CREDENTIALS)
        self.assertEqual("unknown", record.call_args.kwargs["username"])

    def test_a_degraded_rehash_is_a_success_event_because_the_user_got_in(self):
        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(username="admin", detail=auth.AUDIT_REHASH_DEGRADED)
        self.assertEqual("SUCCESS", record.call_args.kwargs["status"])

    def test_the_login_leg_does_not_audit_the_success_face(self):
        """成功面沿用 `main.py` 既有的 `_audit(user, "LOGIN")`（SEC-A-006：一字不动）。"""
        _fresh_db(self)
        ensure_demo_credentials("admin")
        with mock.patch.object(auth, "_record_event") as record:
            result = auth.authenticate_with_result("admin", "admin123")
        self.assertIsNotNone(result.user)
        self.assertEqual("", result.audit_detail)
        record.assert_not_called()


class TokenClaimFaceTests(_LongJwtSecret, unittest.TestCase):
    """令牌面（§7.5）：登录腿交出去的结论里，后续判定只读 `sub` 那一格。

    与 `test_feishu_identity_contract.py` 里那枚"伪造 claim 不放大权限"的钉子同族，两半各
    钉一列：`role` / `access_role` / `name` 是**装饰性**的（每请求由身份声明文件与授予
    重解析），`cv` 是**提示性**的（只说"要比哪个版本"，权威在表里那一行）。所以这一枚钉的
    不是"payload 长什么样"，而是"payload 说话不算数"——把 token 里的任何一列当成结论，
    都等于让那把签名秘密直接颁发权限。
    """

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials("admin")
        self.identity = directory.UserIdentity(
            username="admin", display_name="本地管理员", role="ADMIN"
        )

    def _forged(self, **overrides) -> str:
        """一枚**生命周期上活着**（cv 取自表）的自签 token：这样才轮得到权限面发言。"""
        payload = {
            "sub": "admin",
            "name": "自称的超级名字",
            "role": "ADMIN",
            "access_role": "admin",
            "iss": "yaoke",
            "iat": 1,
            "exp": 2 ** 31 - 1,
            auth.CREDENTIAL_VERSION_CLAIM: user_store.get_record("admin").credentials_version,
        }
        payload.update(overrides)
        return jwt.encode(payload, config_module.settings.jwt_secret, algorithm="HS256")

    def test_every_forged_claim_column_is_overridden_by_the_table_and_the_file(self):
        """降权演示：token 里写 ADMIN/admin，身份与授予给出的仍是文件与表那两侧的答案。"""
        forged = self._forged(
            **{"role": "ADMIN", "access_role": "admin", "name": "自称的超级名字"}
        )
        with directory.override_identities(
            {"admin": directory.UserIdentity(
                username="admin", display_name="只读访客演示账号", role="VIEWER")}
        ):
            online = auth.require_user(f"Bearer {forged}")
        self.assertEqual("admin", online.username)              # 只有 sub 被采纳
        self.assertEqual("VIEWER", online.role)                 # role 由身份文件重述
        self.assertEqual("viewer", online.access_role)          # 权限跟着本地角色走
        self.assertEqual("只读访客演示账号", online.display_name)  # 展示名同样不认 token 那一格
        self.assertNotIn("system:operate", online.permissions)
        self.assertIsNone(online.grant, "授予未开时不得由任何 claim 伪造出来")

    def test_the_version_claim_is_a_hint_not_an_authority(self):
        """`cv` 与其余 claim 的分工：它**参与**判定，但判定读的是表，所以写大它换不来会话。"""
        with directory.override_identities({"admin": self.identity}):
            live = self._forged()
            self.assertEqual("admin", auth.require_user(f"Bearer {live}").username)
            inflated = self._forged(**{auth.CREDENTIAL_VERSION_CLAIM: 10_000})
            with self.assertRaises(HTTPException) as raised:
                auth.require_user(f"Bearer {inflated}")
            self.assertEqual(401, raised.exception.status_code)
            # 表换代之后，连那一枚刚才还活着的 token 也一起死：claim 里的数字没变过。
            user_store.set_password_argon2(
                "admin", plain_password="a-brand-new-password 123", must_change=False
            )
            with self.assertRaises(HTTPException) as stale:
                auth.require_user(f"Bearer {live}")
        self.assertEqual("无效登录凭证", raised.exception.detail)
        self.assertEqual("无效登录凭证", stale.exception.detail)


class ThrottleLayerTests(unittest.TestCase):
    """两层保护各有自己的键、成本与清零：这一层把它们分开各钉一条直接断言。

    判据不是"看起来限了流"，而是三件可杀的事——昂贵运算真的被跳过（SECA-15）、
    桶键里 `client_ip` 参与（M6 唯一可杀处）、账号锁只看 username（M7 唯一可杀处）。
    """

    def setUp(self):
        _fresh_db(self)
        user_store.create_argon2(
            "admin", plain_password="a-good-password 123456", must_change=False
        )
        self.throttle = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=3)

    def test_expensive_work_is_skipped_once_the_bucket_is_exhausted(self):
        """SECA-15：闸门在 Argon2 之前，否则认证面自己就是 DoS 面。

        桩只能打在 `credentials._HASHER` 上（`PasswordHasher` 是 `__slots__` 类，实例属性
        写不进去也读不出），所以这里复用文件里那枚 `_hasher_runs()`：`verify` 被叫没被叫，
        判的是同一条真运算有没有发生。
        """
        bucket = login_throttle.throttle_bucket("admin", "10.0.0.9")
        for _ in range(3):
            self.assertTrue(self.throttle.allow(bucket))
        self.assertFalse(self.throttle.allow(bucket))
        with mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle):
            with _hasher_runs() as verify:
                with self.assertRaises(auth.LoginThrottledError):
                    auth.authenticate_with_result(
                        "admin", "a-good-password 123456", client_ip="10.0.0.9"
                    )
        verify.assert_not_called()

    def test_two_source_addresses_on_the_same_username_have_independent_buckets(self):
        """SECA-16a：M6（throttle 键去掉 ip）只能被这条直接断言杀掉。"""
        first = login_throttle.throttle_bucket("admin", "10.0.0.1")
        second = login_throttle.throttle_bucket("admin", "10.0.0.2")
        self.assertNotEqual(first, second)
        for _ in range(3):
            self.throttle.allow(first)
        self.assertFalse(self.throttle.allow(first))
        self.assertTrue(self.throttle.allow(second))

    def test_many_source_addresses_on_one_username_share_the_account_lock(self):
        """SECA-16b：账号级持久计数按 username，与 throttle 层正交（M7 唯一可杀处）。"""
        attempts = settings.account_max_failed_attempts
        for index in range(attempts):
            result = auth.authenticate_with_result(
                "admin", "wrong-password 123456", client_ip=f"10.0.0.{index + 1}"
            )
            self.assertIsNone(result.user)
        record = user_store.get_record("admin")
        self.assertGreaterEqual(record.failed_attempts, attempts)
        self.assertIsNotNone(record.locked_until)
        self.assertFalse(login_throttle.is_locked(None))
        self.assertTrue(login_throttle.is_locked(record.locked_until))
        # 换一个从头到尾没出现过的来源地址来读**同一行**凭据：结论仍是"锁着"，且不付一次
        # Argon2。若把锁定也按 IP 键（M7），上面那几条 assertTrue 照样绿——只有这一格
        # 看得出"计数被地址冲淡了"：锁不锁只由 username 那一行决定。
        with mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle):
            with _hasher_runs() as verify:
                later = auth.authenticate_with_result(
                    "admin", "a-good-password 123456", client_ip="10.9.9.9"
                )
        self.assertIsNone(later.user)
        self.assertEqual(auth.AUDIT_LOGIN_LOCKED, later.audit_detail)
        self.assertEqual(0, verify.call_count)

    def test_the_bucket_slides_once_the_window_passes(self):
        """窗口是滑动的、不是"到点整片清零"：`login_throttle_window_seconds` 就是这一格语义。"""
        bucket = login_throttle.throttle_bucket("admin", "10.0.0.7")
        for _ in range(3):
            self.assertTrue(self.throttle.allow(bucket, now=1_000.0))
        self.assertFalse(self.throttle.allow(bucket, now=1_010.0))
        self.assertTrue(self.throttle.allow(bucket, now=1_061.0))

    def test_stale_buckets_are_reaped_while_live_ones_survive(self):
        """整表回收（`_sweep_stale`）：桶数上限是"一个窗口内在场的地址数"，不是"见过的地址数"。

        判据只能是表本身的大小：回收对**任何一次答复**都与逐桶剪枝等价（被丢的桶再命中一次即
        重新计入），所以这里没有"换个答复来看"的写法——那才是测不到东西的那一种。下面那枚
        `base` 取的是**真实** monotonic，今天只是为了让这一例里的算术读起来像一条时间线：
        回收时缝的起点已改由第一次调用拿到的时刻惰性播种（`PreHashThrottle._last_sweep` 初值
        `None`），注入一条与真实单调钟无关的时钟照样能回收——那一份保证由
        `test_reaping_does_not_depend_on_the_clock_the_test_injects` 钉，不再由这里的取值迁就。
        """
        base = time.monotonic()
        aged = [
            login_throttle.throttle_bucket("admin", f"10.0.0.{index}")
            for index in range(3)
        ]
        for bucket in aged:
            self.assertTrue(self.throttle.allow(bucket, now=base))
        live = login_throttle.throttle_bucket("admin", "10.0.9.9")
        self.assertTrue(self.throttle.allow(live, now=base + 30))
        self.assertEqual(4, len(self.throttle._hits))
        # 同一个窗口内：一行都不许被回收（回收每窗口至多一次，且判据是"已出窗"）。
        neighbour = login_throttle.throttle_bucket("admin", "10.0.1.1")
        self.assertTrue(self.throttle.allow(neighbour, now=base + 40))
        self.assertEqual(5, len(self.throttle._hits))
        # 越过窗口：三格 aged 已出窗 ⇒ 丢弃；live 与在场这两格留着。
        newcomer = login_throttle.throttle_bucket("admin", "10.0.1.2")
        self.assertTrue(self.throttle.allow(newcomer, now=base + 61))
        self.assertEqual({live, neighbour, newcomer}, set(self.throttle._hits))
        # 丢掉的桶再命中一次即重新计入 ⇒ 回收不改变任何一次答复（也丢不掉配额本身）。
        self.assertTrue(self.throttle.allow(aged[0], now=base + 62))
        self.assertEqual(4, len(self.throttle._hits))

    def test_reaping_does_not_depend_on_the_clock_the_test_injects(self):
        """台账 Task 8 那一格：注入时钟与构造期真实 monotonic 混基准——本轮把这枚雷拆了。

        旧写法把回收时缝的起点钉在 `PreHashThrottle()` 构造时读到的**真实单调钟**上，于是
        `allow(now=)` 给一条比它小的时钟（"从零点起算"的 1_000.0 是最自然的写法）时，
        `moment - _last_sweep` 恒为负、整片回收**永不发生**；而丢弃谓词与逐桶剪枝等价，所以
        **答复一个字都没变**——只看答复的用例看不出任何区别，那正是台账说的"下一位读者的坑"。
        现在起点是 `None`、由第一次调用拿到的时刻惰性播种，这条用例因此不必知道真实单调钟
        在哪里（上一例里那句 `base = time.monotonic()` 就是为迁就它才写的）。
        """
        independent_epoch = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=3)
        aged = [login_throttle.throttle_bucket("admin", f"10.7.0.{index}")
                for index in range(3)]
        for bucket in aged:
            self.assertTrue(independent_epoch.allow(bucket, now=1_000.0))
        live = login_throttle.throttle_bucket("admin", "10.7.9.9")
        self.assertTrue(independent_epoch.allow(live, now=1_030.0))
        self.assertEqual(4, len(independent_epoch._hits))
        # 越过一个窗口：三格 aged 出窗 ⇒ 收掉；live 与刚进来的这一格留着。
        newcomer = login_throttle.throttle_bucket("admin", "10.7.9.8")
        self.assertTrue(independent_epoch.allow(newcomer, now=1_061.0))
        self.assertEqual({live, newcomer}, set(independent_epoch._hits))
        # `reset()` 回到"从没被叫过"，不是回到真实单调钟的此刻：夹具跑在注入时钟上。
        independent_epoch.reset()
        self.assertIsNone(independent_epoch._last_sweep)
        self.assertTrue(independent_epoch.allow(live, now=1_000.0))
        self.assertEqual(1_000.0, independent_epoch._last_sweep)

    def test_a_successful_login_clears_the_persistent_counter(self):
        user_store.record_login_failure("admin", max_attempts=9, lock_seconds=900)
        self.assertTrue(
            auth.authenticate_with_result("admin", "a-good-password 123456").user
        )
        record = user_store.get_record("admin")
        self.assertEqual(0, record.failed_attempts)
        self.assertIsNone(record.locked_until)

    def test_the_capacity_gate_surfaces_as_a_capacity_error_not_a_denial(self):
        """503 ≠ 401：可用性事实不能被伪装成凭据结论——**兜底那一半**也算。

        步骤 0 的探针只探不预约，于是"探针说有空、真要占时没了"这一格竞态是可达的（负载本身
        就在动）。那时抛错的责任回到运算处 `argon2_slot` 那一次：本例把探针钉成"永远有空"，
        逼这条腿一路走到真运算处，判的是它仍然只能以容量错误出去。

        （此例原先靠给一个**没有身份声明**的账号造 legacy 行来触发抛错——那行夹具在断言之前的
        路径上根本走不到，抛点也来自另一条腿，与
        `test_capacity_exhaustion_is_the_same_on_the_dummy_leg_as_on_a_real_verify` 重复；
        兜底这一半此前没有钉子。）
        """
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            with mock.patch.object(
                credentials, "capacity_available", return_value=True
            ) as probe:
                with self.assertRaises(credentials.PasswordCapacityError):
                    auth.authenticate_with_result("admin", GOOD_PASSWORD)
        probe.assert_called_once()


class ThrottleHttpFaceTests(_LongJwtSecret, _AuditToTempFile):
    """429 的 HTTP 面：中文文案、审计 token，以及对"存在的账号"与"不存在的账号"一字不差。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        ensure_demo_credentials()
        self.throttle = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=2)
        self.client = TestClient(fastapi_app)

    def _login(self, username: str):
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "wrong-password 123456"},
        )

    def _change(self, headers, body):
        return self.client.post("/api/auth/password/change", json=body, headers=headers)

    def test_a_throttled_login_is_a_429_with_chinese_copy_and_one_audit_token(self):
        with mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle):
            self.assertEqual(401, self._login("admin").status_code)
            self.assertEqual(401, self._login("admin").status_code)
            response = self._login("admin")
        self.assertEqual(429, response.status_code, response.text)
        self.assertEqual({"detail": "登录尝试过于频繁，请稍后再试"}, response.json())
        self.assertEqual(
            [auth.AUDIT_INVALID_CREDENTIALS] * 2 + [auth.AUDIT_LOGIN_THROTTLED],
            [event["detail"] for event in self.events()],
        )
        # 两栏不互换：token 不进 body，口令不上任何一面；文案不提账号、也不提"锁定"。
        self.assertNotIn("login_throttled", response.text)
        self.assertNotIn("wrong-password", response.text)
        self.assertNotIn("锁", response.text)

    def test_the_429_face_is_byte_identical_for_a_known_and_an_unknown_account(self):
        """节流判定在身份查找之前 ⇒ 429 天生账号无关；这条把它钉成逐字节的对比。

        桶键里确实有账号名，但那格键读的是**客户端自己交上来的字符串**，没查过任何表：
        "admin" 与 "nobody-at-all" 各自耗尽自己的桶、给出同一张脸，于是攻击者拿 429 既证不出
        某个账号存在，也证不出它不存在——可用性结论与身份结论在两面各说各的话。
        """
        faces = []
        with mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle):
            for username in ("admin", "nobody-at-all"):
                for _ in range(2):
                    self._login(username)
                response = self._login(username)
                faces.append((response.status_code, response.text))
        self.assertEqual(
            [(429, '{"detail":"登录尝试过于频繁，请稍后再试"}')] * 2, faces
        )

    def test_the_change_leg_shares_the_bucket_and_gets_the_same_429(self):
        """改密腿与登录腿共用 (username, client_ip) 这一格桶：一条腿耗尽，另一条立刻吃 429。

        "一个猜测面、一把计数器"是 Task 7 钉过的事实，两把计数器等于给攻击者留一条不被记录
        的通道；这里反过来钉它的另一半——换腿不清零，所以换腿也不是第 3 份免费配额。
        """
        user = auth.authenticate("admin", "admin123")
        self.assertIsNotNone(user)
        headers = {"Authorization": f"Bearer {auth.issue_token(user)}"}
        body = {
            "current_password": "wrong-old-password 123456",
            "new_password": "a-brand-new-password 4242",
        }
        with mock.patch.object(login_throttle, "pre_hash_throttle", self.throttle):
            self.assertEqual(401, self._change(headers, body).status_code)
            self.assertEqual(401, self._login("admin").status_code)   # 同一格桶的第 2 次
            throttled = self._change(headers, body)                    # 第 3 次 ⇒ 没有配额
        self.assertEqual(429, throttled.status_code, throttled.text)
        self.assertEqual({"detail": "登录尝试过于频繁，请稍后再试"}, throttled.json())
        # 口令没改进去：429 判在凭据结论之前，因此不产生任何写副作用。
        self.assertNotIn("changed", throttled.json())
        self.assertIsNone(user_store.get_record("admin").locked_until)


class LockedHttpFaceTests(_LongJwtSecret, _AuditToTempFile):
    """M5 的靶子：锁定原因一旦渗到 HTTP 面，就是账号存在性枚举面（SECA-14 的 HTTP 半边）。"""

    def setUp(self):
        super().setUp()
        _fresh_db(self)
        user_store.create_argon2(
            "admin", plain_password="a-good-password 123456", must_change=False
        )
        # 本类每例要打掉生产单例 8 次配额（5 次失败 + 锁定/口令错/未知账号三张脸），而它测的是
        # **锁定脸**，不是节流脸：`LOGIN_THROTTLE_MAX_ATTEMPTS` 一旦被环境调到 8 以下，那三张脸
        # 里就会先冒出 429，红的原因与被测事实毫无关系。这里换上一格宽到不可能命中的桶——
        # 判据一个字没改，只是把它不关心的那一层从等式里拿掉。
        bucket_patch = mock.patch.object(
            login_throttle,
            "pre_hash_throttle",
            login_throttle.PreHashThrottle(window_seconds=60, max_attempts=10_000),
        )
        bucket_patch.start()
        self.addCleanup(bucket_patch.stop)
        self.client = TestClient(fastapi_app)

    def _login(self, username: str, password: str):
        return self.client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )

    def test_locked_wrong_password_and_unknown_account_are_the_same_http_face(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        locked = self._login("admin", "a-good-password 123456")   # 口令对，但账号已锁
        wrong = self._login("admin", "still-wrong 123456")
        unknown = self._login("nosuchaccount", "still-wrong 123456")
        faces = {
            (r.status_code, json.dumps(r.json(), sort_keys=True))
            for r in (locked, wrong, unknown)
        }
        self.assertEqual(1, len(faces), faces)
        self.assertEqual(401, locked.status_code)
        self.assertNotIn("锁", json.dumps(locked.json(), ensure_ascii=False))

    def test_the_lock_reason_reaches_the_audit_face_only(self):
        for _ in range(settings.account_max_failed_attempts):
            self._login("admin", "definitely-wrong 123456")
        self._login("admin", "a-good-password 123456")
        details = [event["detail"] for event in self.events()]
        self.assertIn(auth.AUDIT_LOGIN_LOCKED, details)
        self.assertNotIn(auth.AUDIT_LOGIN_THROTTLED, details)
