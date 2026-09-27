"""口令哈希原语：全仓唯一允许对口令做密码学运算的模块（SEC-A-005）。

只认识口令，不认识 username、不查库、不做失败语义——那些在 auth/user_store 上头。
"""

from __future__ import annotations

import hashlib
import hmac
import re
from contextlib import contextmanager
from dataclasses import dataclass
from threading import BoundedSemaphore

import argon2

from app.config import settings

ALGORITHM_ARGON2ID = "argon2id"
ALGORITHM_LEGACY_SHA256 = "legacy-sha256"

# OWASP Password Storage Cheat Sheet 的 Argon2id 最低推荐档（19 MiB / t=2 / p=1）。
# 出处不是 RFC 9106（它推荐 2 GiB/t=1/p=4 或 64 MiB/t=3/p=4），措辞别改回去。
# 这三枚常量不可经 env 调整：能运维调的安全强度等于没有强度（SEC-A-008）。
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 19456
ARGON2_PARALLELISM = 1

ARGON2_HASH_PREFIX = "$argon2id$"
_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")


class CredentialConfigError(RuntimeError):
    """algorithm 列与编码串互相矛盾。不猜、不降级、不 try-both。"""


class PasswordCapacityError(RuntimeError):
    """并发槽已满。调用方翻译成 503，不是认证失败。"""


@dataclass(frozen=True)
class VerifyOutcome:
    ok: bool
    needs_rehash: bool


_HASHER = argon2.PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST,
    parallelism=ARGON2_PARALLELISM,
)

# 与当前档位同源的常量工作单元：未知账号 / disabled / 无凭据行 三态都要消耗
# 一次真实运算，否则"账号不存在"就是一条响应时间指纹。
_DUMMY_PLAINTEXT = "yaoke-constant-work-dummy-credential"
_DUMMY_HASH = _HASHER.hash(_DUMMY_PLAINTEXT)

_SLOTS = BoundedSemaphore(max(1, int(settings.argon2_max_concurrent_ops)))


def hasher() -> argon2.PasswordHasher:
    return _HASHER


def dummy_hash() -> str:
    return _DUMMY_HASH


def hash_password(plain: str) -> str:
    # 写入侧付的是与校验侧**同一档**内存硬运算，所以它必须过同一道闸：闸门外每一次 provisioning
    # 写、每一次渐进重哈希都是不受上限的 19 MiB 工作，"第一层绑定内存硬运算"这句话就只对一半。
    # 这里没有二次占槽：本模块的槽一律是"进函数占、出函数还"，调用方（`verify_password` 的槽
    # 在返回前已归还）不会跨边界持有它，而 `BoundedSemaphore` 不可重入——同一线程嵌套占槽就是
    # 自锁，那条风险由 `test_one_slot_is_enough_for_a_verify_followed_by_a_hash` 钉住。
    with argon2_slot():
        return _HASHER.hash(plain)


def needs_rehash(encoded: str) -> bool:
    # 参数漂移判定交给库：自行比较字符串会漏掉"改了 m/t/p 但 v=19 不变"这一类。
    # 库异常不许以任何形式走出这个边界模块（理由与 `_verify_argon2` 那半条同一条）：
    # `check_needs_rehash` 对**非 PHC** 的输入抛的是 `argon2.exceptions.InvalidHashError`
    # （⊂ ValueError），而本模块给上游的错误分类只有 `CredentialConfigError` 一种——放它出去，
    # 症状就是一条与凭据无关的裸栈落在登录面上（登录面的分类只有"口令错 / 503 / 存储事故"）。
    # 本模块内部的两处调用都在 PHC 串上（前缀判定已过），所以这一格改的是**公开面**的口径。
    try:
        return _HASHER.check_needs_rehash(encoded)
    except argon2.exceptions.InvalidHashError as exc:
        raise CredentialConfigError("Argon2 编码串无法解析") from exc


@contextmanager
def argon2_slot():
    if not _SLOTS.acquire(blocking=False):
        raise PasswordCapacityError("password operation capacity exceeded")
    try:
        yield
    finally:
        _SLOTS.release()


def capacity_available() -> bool:
    """步骤 0 的**非阻塞探针**：只回答"现在还能不能占下一格"，不留下任何预约。

    与 `argon2_slot` 的差别就是这条腿存在的全部理由：闸门若在运算处才判，身份/凭据/锁定
    查找已经跑完了——饱和时"锁着的账号答 401、其余答 503"，§7.4 的不可区分脸就成了存在性
    指纹。探针不预约（占而不放等于自己造一条饥饿通道），所以它与真正占用之间必然有竞态窗口，
    运算处那一次 `argon2_slot()` 抛错**原样保留**为兜底：任何路径都不许消耗一格它没预约过的槽，
    也不许把容量事实降级成凭据结论。
    """
    if not _SLOTS.acquire(blocking=False):
        return False
    _SLOTS.release()
    return True


def verify_password(plain: str, *, algorithm: str, encoded: str) -> VerifyOutcome:
    if algorithm == ALGORITHM_ARGON2ID:
        if not encoded.startswith(ARGON2_HASH_PREFIX):
            raise CredentialConfigError(
                f"algorithm={algorithm!r} 与编码串前缀不符"
            )
        return _verify_argon2(plain, encoded)
    if algorithm == ALGORITHM_LEGACY_SHA256:
        if not _LEGACY_HEX.match(encoded):
            raise CredentialConfigError(
                f"algorithm={algorithm!r} 与编码串形态不符"
            )
        return VerifyOutcome(
            # 没有 `.lower()`：上面那道 `_LEGACY_HEX` 只认小写，能走到这一行的串里一个大写字母
            # 都没有，夹一次 lower 是零作用的死代码。大写摘要的归一化发生在**写入侧**
            # （`credentials_migration.read_artifact`），钉在那一侧——两侧都夹就等于让"库里存的
            # 形态"与"能验的形态"由两处各自决定，而这一格的正解只有一条：表里存什么就比什么。
            ok=hmac.compare_digest(_legacy_digest(plain), encoded),
            needs_rehash=True,
        )
    raise CredentialConfigError(f"未知 algorithm：{algorithm!r}")


def verify_dummy(plain: str) -> VerifyOutcome:
    """恒定一次同档 Argon2 运算，永不成功；异常是"口令不对"的正常路径。"""
    outcome = _verify_argon2(plain, _DUMMY_HASH)
    # 判定一律压成 False：这条路径的载荷和明文都是本模块自己造的，"知道那串明文"的人
    # 能让 _verify_argon2 返回 ok=True，而它的调用方（未知账号 / 已停用 / 无凭据行）把
    # 返回值当认证结论用。留下来的只有运算量与档位，那才是这条路径存在的全部理由。
    return VerifyOutcome(ok=False, needs_rehash=outcome.needs_rehash)


def _verify_argon2(plain: str, encoded: str) -> VerifyOutcome:
    with argon2_slot():
        try:
            _HASHER.verify(encoded, plain)
        except argon2.exceptions.VerifyMismatchError:
            return VerifyOutcome(ok=False, needs_rehash=needs_rehash(encoded))
        except argon2.exceptions.VerificationError as exc:
            # argon2-cffi 的异常树里 InvalidHashError ⊂ ValueError，与 VerificationError 是两支：
            # 前缀对、体内损坏的 PHC 串在 verify() 上抛的是 VerificationError("Decoding failed")。
            # 只捕 InvalidHashError 等于永远捕不到，库异常会逃出这个边界模块变成上游 500。
            raise CredentialConfigError("Argon2 编码串无法解析") from exc
    return VerifyOutcome(ok=True, needs_rehash=needs_rehash(encoded))


def _legacy_digest(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()
