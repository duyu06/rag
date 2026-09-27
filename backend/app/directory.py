"""身份声明层（规格 §6.4）。身份的唯一真源是文件，凭据状态在 user_store，两边不得互串。

role 的取值**不在这里**校验：`access_role_for()` 对未知角色返回 None、权限表退化为空集，
那已经是 fail-closed。在这里再抄一份角色白名单只会造出第二个真源（RBAC 改了这里没改 = 静默失配）。

`enabled` 只被**声明**，不在这里被判定：身份侧不回答"这个人现在能不能登录"。名册那一面按字
投影它（文件里写着停用的人，成员页上就是停用），登录面另有它自己的口径——停用账号在那里必须
与根本不认识的账号不可分辨（规格 §7.3：与口令错同一条哑校验路径、同一个 401）。两处读的都是
文件里这同一个字段，谁也不许另存一份"这个账号现在是什么状态"。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

#: 两份文件都是**相对路径**，按进程 cwd 解析：镜像的 WORKDIR 就是 `backend/`，`config/` 整目录
#: 随镜像 COPY，所以"身份文件在场"是部署事实而不是配置项。口径与 `config/llm_registry.json`、
#: `config/feishu_permissions.json` 以及本目录里 `data/` 那一组常量同轨。
ENTERPRISE_IDENTITIES_FILE = Path("config/users.json")
DEMO_IDENTITIES_FILE = Path("config/users.demo.json")

#: 敏感键黑名单。`extra="forbid"` 已经挡掉一切未知键，这张表挡的是"看起来无害的写法"：
#: `hash` / `legacy` 这类名字既不在字段集里也不像凭据，但出现在身份文件里就是有人把两件事
#: 写到了一起。命中即拒，不做"忽略该字段后继续"。
FORBIDDEN_IDENTITY_KEYS = frozenset(
    {"password", "password_hash", "hash", "secret", "token", "api_key", "credentials", "legacy"}
)

# 敏感键与"看起来像凭据"的形态是两道独立的门：`extra="forbid"` 挡不住 display_name 里塞 digest。
# 判"纯 hex 且 ≥40 位"而不是恰好 64：摘要家族不止 SHA-256（SHA-1=40、SHA-384=96），而 64 位
# 那一种恰恰是本项目升级前一直在用的形态。下限停在 40 而不是 32 是刻意的——32 位纯 hex 正是
# UUID 去掉连字符的长度，把机器账号拒在启动期的代价高于"顺带拦下 MD5"的收益。
# 两道判定都按大小写不敏感跑：摘要是从别处粘进文件的东西，粘出来常带大写，`$Argon2id$` 与
# `$argon2id$` 是同一条散列——一道认大小写、一道不认，就留下"同一串材料换个写法就放过"的缝。
_HEX_DIGEST = re.compile(r"^[0-9a-f]{40,}$", re.IGNORECASE)
# PHC 编码（`$argon2id$…` / `$2b$…`）不是 hex，上面那道看不见它，但它是同一类材料。
_PHC_DIGEST = re.compile(r"^\$[a-z0-9]+\$", re.IGNORECASE)


class IdentityConfigError(RuntimeError):
    """身份文件不合法 ⇒ 启动失败。不是告警，不是忽略该条目。"""


class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    role: str = Field(min_length=1, max_length=32)
    # `min_length=1`：空串是一个"看起来没有、实际上有值"的 open_id，而 open_id 的唯一性
    # 只判非 null 的取值——两个没接飞书的账号都会撞上这个空串，报错信息还会指着 open_id 说事。
    feishu_open_id: str | None = Field(default=None, min_length=1)
    enabled: bool = True


def _digest_reason(text: str, noun: str) -> str | None:
    """一段文本是不是"凭据材料"的形状；命中只回成因描述，**不回显**这段文本。

    `noun` 说的是被判定的是哪一面（"取值"/"键名"），只影响措辞，不影响判定。

    判之前先把串内空白全部去掉，而不是只 `strip()` 首尾：摘要是从终端/表格/口令表里分段粘
    进来的东西，中间夹一道换行是常态，只 trim 两端会放过"四十位 + 换行 + 二十位"这种形态。
    去掉空白后恰成 40 位以上纯 hex 的合法取值不存在（人名、部门名、role、open_id 都不是十六
    进制串），所以这一步不扩大误拒面。
    """
    compact = "".join(text.split())
    if _HEX_DIGEST.match(compact):
        return f"含疑似口令摘要的{noun}"
    if _PHC_DIGEST.match(compact):
        return f"含疑似口令散列的{noun}"
    return None


def _credential_shape_violation(node: Any) -> str | None:
    """递归找"凭据形状"（键名与取值同两道判定），命中就返回一句**不回显内容**的成因描述。

    递归不是为了优雅：`{"display_name": {"password": "…"}}` 这种嵌套写法会一路走到字段
    校验器，而校验器的默认报错文本带着**输入值**——那份值可能是某人从口令表里粘过来的。
    在这里拦下，它就不会以任何形式进启动日志。

    键名也要过同样的判定，因为回显面不止取值一个：`extra="forbid"` 的报错 `loc` 里装的正是
    那个多出来的**键名**，`{"<64 位 digest>": true}` 就会把 digest 原样拼进启动消息。
    """
    if isinstance(node, Mapping):
        offending = {str(key).lower() for key in node} & FORBIDDEN_IDENTITY_KEYS
        if offending:
            return f"含凭据字段 {sorted(offending)}"
        for key in node:
            reason = _digest_reason(str(key), "键名")
            if reason is not None:
                return reason
        for value in node.values():
            reason = _credential_shape_violation(value)
            if reason is not None:
                return reason
        return None
    if isinstance(node, (list, tuple)):
        for value in node:
            reason = _credential_shape_violation(value)
            if reason is not None:
                return reason
        return None
    if isinstance(node, str):
        return _digest_reason(node, "取值")
    return None


def _read_document(path: Path) -> Any:
    if not path.exists():
        raise IdentityConfigError(f"身份文件不存在：{path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # "在场但读不出来"与"形态不对"是同一条出路：整份拒。让它以 `UnicodeDecodeError`
        # 往上逃，症状就是一条与身份毫无关系的栈。消息只点名路径，不回显内容。
        raise IdentityConfigError(f"身份文件读不出来：{path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise IdentityConfigError(f"身份文件不是合法 JSON：{path}") from exc


def _validate_records(path: Path) -> list[UserIdentity]:
    """把一份身份文件读成记录列表，任何一处不合法都从 `IdentityConfigError` 出去。

    记录只从 `path` 那一份文件来：**没有**"把已在内存里的记录递进来"这条旁路。身份的
    唯一真源是文件集（SEC-A-010），多一条注入路径就多一处绕开上面那道凭据形态扫描的地方；
    真要换源得先改这段理由和它的用例，而不是加一个默认可选的参数。
    """
    document = _read_document(path)
    # 顶层键封闭：多一个键就是有人往这份身份文件里放了本规格不认识的东西（凭据最容易这样进来）。
    if not isinstance(document, dict) or set(document) - {"identities"}:
        raise IdentityConfigError(f"身份文件顶层键必须是唯一的 identities：{path}")
    records = document.get("identities")
    if not isinstance(records, list):
        raise IdentityConfigError(f"{path}: identities 必须是数组")
    identities: list[UserIdentity] = []
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            raise IdentityConfigError(f"{path}: identities[{index}] 必须是对象")
        reason = _credential_shape_violation(raw)
        if reason is not None:
            raise IdentityConfigError(f"{path}: identities[{index}] {reason}")
        try:
            identities.append(UserIdentity(**raw))
        except ValidationError as exc:
            # 只取 `loc` + `type`：字段取值一律不进消息（理由同 `_credential_shape_violation`）。
            # 原文仍在异常链上，定位能力一点没少。
            detail = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
                for item in exc.errors()
            )
            raise IdentityConfigError(f"{path}: identities[{index}] 不合法：{detail}") from exc
    return identities


def load_identities(*, include_demo: bool) -> dict[str, UserIdentity]:
    """enterprise 先、demo 后；重名一律拒，**不做**字典覆盖式合并。

    `{**enterprise, **demo}` 的坏处不是"会覆盖"这么抽象：demo 文件里放一个同名账号就等于
    改掉那个人的 role，而 role 是权限的入口。合并因此只能"撞上就停"，两种形态都跑同一套
    校验（企业形态只有一份文件，冲突面天然为空，但少跑一次就会有一次没跑过的那支）。
    """
    sources: list[Path] = [ENTERPRISE_IDENTITIES_FILE]
    if include_demo:
        sources.append(DEMO_IDENTITIES_FILE)
    merged: dict[str, UserIdentity] = {}
    seen_open_ids: dict[str, str] = {}
    for source in sources:
        for identity in _validate_records(source):
            if identity.username in merged:
                raise IdentityConfigError(
                    f"username 重复：{identity.username}（{source}）"
                    "——后加载的身份不得覆盖先加载的（demo 文件不得改写企业身份）"
                )
            if identity.feishu_open_id is not None:
                if identity.feishu_open_id in seen_open_ids:
                    # open_id 是外部身份→内部账号的查找键：两个人共用一个，授予就会串到别人身上。
                    raise IdentityConfigError(
                        "feishu_open_id 重复："
                        f"{identity.feishu_open_id} 同时属于 {seen_open_ids[identity.feishu_open_id]}"
                        f" 与 {identity.username}"
                    )
                seen_open_ids[identity.feishu_open_id] = identity.username
            merged[identity.username] = identity
    return merged


#: 按形态分格的缓存。存进去的是 `MappingProxyType` 只读视图，而不是活 dict：`identities()`
#: 的注解是 `Mapping`，交回可写的 dict 就等于允许任一调用方 `pop()` 一下——那会把某个人的
#: 身份从进程生命周期内的身份真源里抹掉，名册少一人、部门计数跟着少一人，且没人会察觉。
_CACHE: dict[bool, Mapping[str, UserIdentity]] = {}


def identities() -> Mapping[str, UserIdentity]:
    """按形态缓存。形态在进程生命周期内不变（启动守卫负责它的成立）。

    `settings` 在调用时取而不是 import 时钉死：本模块的形态判定必须跟着**当前**配置走
    （测试接缝与启动守卫都靠这一点），而 import 期取值会把 `app.config` 的加载顺序变成
    身份层的一部分。
    """
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    if mode not in _CACHE:
        _CACHE[mode] = MappingProxyType(load_identities(include_demo=not mode))
    return _CACHE[mode]


def get_identity(username: str) -> UserIdentity | None:
    return identities().get(str(username))


def reset_cache() -> None:
    _CACHE.clear()


@contextmanager
def override_identities(mapping: Mapping[str, UserIdentity]) -> Iterator[None]:
    """测试接缝：换掉**当前形态**那一份身份缓存，用例既不必改文件也不必改产品代码。

    它是"身份从文件来"这条口径下唯一合法的注入点，所以进来的必须已经是 `UserIdentity`
    对象（形态与文件读出的那条路同源，凭据材料在类型层就放不进来）。

    只替换**当前形态**那一份缓存，退出时连同其余键一起还原——留着半份替换，下一个用例
    就会在自己的 setUp 里读到别人的人。
    """
    from app.config import settings

    mode = bool(settings.security_enterprise_mode)
    saved = dict(_CACHE)
    _CACHE[mode] = MappingProxyType(dict(mapping))
    try:
        yield
    finally:
        _CACHE.clear()
        _CACHE.update(saved)
