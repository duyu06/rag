"""受限迁移路径（规格 §8.2）。全仓唯一能生产 legacy 凭据行的地方。

它**只**服务"从 SEC-A 之前的版本升级"这一条路径：没有升级工件 ⇒ 没有 legacy 行。
把"缺凭据行"当成"那就自动造 legacy"是把升级输入当成了全新安装的凭据来源（M19），
SECA-04b 按"全新安装产出的行全为 argon2id、`legacy_count=0`"判它。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import credentials, user_store

#: 工件的默认位置在 `data/`：§4 SEC-A-004 的 closure 扫描按 `app/` 与 `config/` 数 0 命中，
#: 一份**注定要被删除**的升级输入放在那两个地方会自相矛盾，也更早变成第二处凭据材料真源。
#: 相对路径与 `user_store` 的库默认值同口径（都按进程 cwd 解析），换工作目录时两件事一起换。
#: 但这条"同生同死"**只在 `CONVERSATION_DB_PATH` 未设或给相对值时成立**：该键一旦给绝对路径，
#: 库就跟着 env 搬走、工件仍钉在 cwd 底下。现网恰好没走到那一格——compose 挂的是**目录**
#: （`docker-compose.yml` 的 `./backend/data:/app/data`），`backend/.env:33` 里那枚键也仍是相对值
#: ⇒ 默认部署同源；绝对值是 systemd 式部署会自己选上的形状，届时"库搬走了、工件还在原地"，
#: 导入零行退出。这条限制连同它的失败方向（"静默不导入但 rc=0，`reason` 里带解析后的绝对路径"）
#: 登记在 §17 L7，本轮按该条裁定**不**加 `--path`。所以
#: `import_from_artifact` 在默认路径没命中时把解析后的绝对路径打进 `reason`，让运维看得见
#: 它去哪儿找过，而不是只看见"全新安装不生产 legacy 行"。
LEGACY_INPUT_PATH = Path("data/legacy_credentials.json")

#: 顶层键**封闭**：多一个键就是有人往这份工件里塞了本规格不认识的东西，整份拒读。
ARTIFACT_KEYS = frozenset({"generated_at", "source", "credentials"})

#: 出处两键是"升级工件"与"随手放着的凭据文件"之间唯一可机器辨别的差别。§8.2 的整节立论
#: 就靠这条区分，所以它不能只写在文档里。
_PROVENANCE_KEYS = frozenset({"generated_at", "source"})

_LEGACY_HEX = re.compile(r"^[0-9a-f]{64}$")


class MigrationArtifactError(RuntimeError):
    """升级工件形态不对。整体拒绝，绝不"跳过坏条目继续导几个"。"""


@dataclass(frozen=True)
class MigrationReport:
    """导入这一腿的结果。三个字段只到**用户名**粒度：digest 是凭据材料，不进可打印面。

    `reason` 说的是"为什么没导"，永远不说"口令对不对"——写失败根本不走这条道（见
    `import_from_artifact` 对 `user_store.CredentialStoreError` 的态度）。

    `skipped` 装的是**两件事**："已有凭据行、按幂等跳过"（`only_missing` 挡下的）与
    "真去写了却被主键拒收"（`declined`，只在 `only_missing=False` 或并发时出现）——两者都是
    "这个人今天没有新行"，所以台账只有一格。分辨它们在 `reason`：只有第二件才会写下
    "落行被拒"那句。为什么不给 `declined` 另开一个字段：`migrate` 的**证据面就是 §11 冻结的
    那四行 stdout**（`artifact_present / imported / skipped / reason`），加一枚字段等于加第五行
    输出、也就改了那条契约；本轮按该条把裁定写在这里，而不是改形状。
    """

    artifact_present: bool
    imported: tuple[str, ...]
    skipped: tuple[str, ...]
    reason: str = ""


@dataclass(frozen=True)
class AccountStatus:
    """一个账号的凭据状态。没有 `password_hash` 这一格：状态面要被 `migration-status` 整行
    打印，密文材料进日志是 §6.1/§8.8 一致禁止的事（口径同 `CredentialRecord` 的 `repr=False`）。
    """

    username: str
    algorithm: str
    credentials_version: int
    must_change: bool
    locked_until: str | None
    updated_at: str


@dataclass(frozen=True)
class MigrationStatus:
    legacy_count: int
    argon2id_count: int
    accounts: tuple[AccountStatus, ...]


def read_artifact(path: Path = LEGACY_INPUT_PATH) -> dict[str, str]:
    """把工件读成 `username -> 64 位小写 hex`。任何一处形态错 ⇒ 整份拒绝。

    校验做在这里而不是 `user_store.import_legacy_digest` 里，是因为脏值的症状位置不对：写手
    只落一行，脏 digest 要等到那个人**第一次登录**才被 `verify_password` 认出来，而登录面的
    分类里没有"这条凭据永远验不过"这一项——它会被读成"用户记错了口令"，且没人报警。
    导入即拒才是运维一次能修完的失败。
    """
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # "在场但读不出来"与"形态错"是同一种失败：目录占了这条路、权限不给读、编码不是
        # UTF-8（Windows 上 GBK / UTF-16 都不 exotic）。出路也只有整份拒这一条——让裸异常
        # 往上走，症状就变成运维看到半截栈而不是"这份工件有问题"。消息只点名路径：内容里有 digest。
        raise MigrationArtifactError(f"迁移输入读不出来：{path}") from exc
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        # `JSONDecodeError` 的文案只有"第几行第几列"，不回显文档内容 ⇒ 异常链可以照留：
        # 定位能力一点不丢，而 digest 一个字节也不会进任何日志面。
        raise MigrationArtifactError("迁移输入不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise MigrationArtifactError("迁移输入顶层必须是对象")
    unknown = set(payload) - ARTIFACT_KEYS
    if unknown:
        raise MigrationArtifactError(f"迁移输入含未知字段：{sorted(unknown)}")
    missing = _PROVENANCE_KEYS - set(payload)
    if missing:
        raise MigrationArtifactError(f"迁移输入缺少出处字段：{sorted(missing)}")
    for key in sorted(_PROVENANCE_KEYS):
        value = payload[key]
        if not isinstance(value, str) or not value.strip():
            raise MigrationArtifactError(f"出处字段 {key!r} 必须是非空字符串")
    if "credentials" not in payload:
        raise MigrationArtifactError("迁移输入缺少 credentials 字段")
    block = payload["credentials"]
    if block is None:
        # "键在场、取值 null"与"压根没这个键"是两件事：前者是一份写了 credentials 却没写任何
        # 账号的输入，运维要找的是导出那一步，不是"字段拼错"。
        raise MigrationArtifactError("credentials 字段在场但取值为 null：没有可导的账号")
    if not isinstance(block, dict):
        raise MigrationArtifactError("credentials 必须是 username→digest 的对象")
    if not block:
        # 空 credentials 报出去，而不是当成"没有工件"：`artifact_present` 说的是文件在不在场，
        # 一份在场但导 0 个人的输入被读成全新安装，等于把升级失败伪装成不需要升级。
        raise MigrationArtifactError("credentials 为空：这份输入不导任何人，不是升级工件")
    normalized: dict[str, str] = {}
    for username, digest in block.items():
        # `json.loads` 的对象键必为 str，所以这里只判"是不是一个能当主键用的名字"。
        if not username.strip():
            # 空主键的行写得进去、查不出来，最后只能靠一次没人知道是谁的 DELETE 收掉。
            raise MigrationArtifactError("credentials 含空白用户名")
        if username != username.strip():
            # 带首尾空白的名字不做静默 trim：那等于把 digest 发给另一个账号。
            raise MigrationArtifactError(f"用户名 {username!r} 带首尾空白")
        if not isinstance(digest, str) or not _LEGACY_HEX.match(digest.strip().lower()):
            # 消息里只出现用户名，不出现那串值：它进异常消息就等于进服务端日志与运维控制台。
            raise MigrationArtifactError(f"{username} 的迁移输入不是 64 位 hex")
        normalized[username] = digest.strip().lower()
    return normalized


def import_from_artifact(
    path: Path = LEGACY_INPUT_PATH, *, only_missing: bool = True
) -> MigrationReport:
    """读工件 → 逐行交给受限写手 `import_legacy_digest`。

    三件事是刻意的：

    1. **不建表**。schema 的唯一出处是 `user_store.ensure_user_credentials_schema()`，由启动
       编排 / CLI 调（读路径顺手建表等于让"env 被清掉"的每一次调用往真库提交一次 DDL）。
       表不在场时这里就抛 `no such table`，指向漏掉初始化的人。
       同一处编排还负责**输入路径**：默认工件按进程 cwd 解析，库路径按 `CONVERSATION_DB_PATH`
       解析，该键给绝对值时两者分叉（见 `LEGACY_INPUT_PATH` 的理由块）。启动方要么保证后端
       cwd 就是后端目录，要么显式把绝对路径交给 `path=`。
    2. **已存在的行只跳过，绝不覆写**。重跑导入把一条已升级的 argon2id 行降回 legacy，是
       `legacy_count` 永远闭不上的最直接形状；写手用的是 `INSERT ... DO NOTHING`，而这里连
       "尝试覆写"这个动作都不出现，读代码的人不必先去推那段 SQL 的语义。
    3. **`user_store.CredentialStoreError` 原样逃出去**。那是存储事故（锁、盘满、约束），
       既不是"这个人的口令错了"，也不是一次可以记进 `skipped` 的冲突：咽掉它，SECA-04 的
       `legacy_count` 会在一个没人知道的数上停住，而登录面继续对同一个人报"用户名或密码错误"。
    """
    block = read_artifact(path)
    if not block:
        reason = "迁移输入不存在：全新安装不生产 legacy 行"
        if path == LEGACY_INPUT_PATH:
            # 默认路径没命中时把**解析后的绝对路径**写进报告：库跟着绝对 env 搬走、工件却还留在
            # cwd 底下时，这条导了 0 个人的升级会读成"本来就不需要升级"（SEC-A-003 要的是前者
            # 真的把人迁过去）。看得见去哪儿找过，运维才判断得出是路径分叉而不是全新安装。
            reason += f"（默认路径按当前工作目录解析为 {path.resolve()}）"
        return MigrationReport(
            artifact_present=False,
            imported=(),
            skipped=(),
            reason=reason,
        )
    imported: list[str] = []
    skipped: list[str] = []
    declined: list[str] = []
    for username, digest in sorted(block.items()):
        if only_missing and user_store.get_record(username) is not None:
            skipped.append(username)
            continue
        # 写手的返回值就是"这一行落地了没有"。False 只可能是撞了主键（`only_missing=False`
        # 或并发），那时把它报成"导入成功"就是台账与实际行数分叉——SECA-04 判闭合用的正是
        # 这个数。
        if user_store.import_legacy_digest(username, digest, must_change=True):
            imported.append(username)
        else:
            declined.append(username)
    reason = ""
    if declined:
        reason = f"落行被拒（目标账号已有凭据行）：{sorted(declined)}"
    return MigrationReport(True, tuple(imported), tuple(sorted([*skipped, *declined])), reason)


def status() -> MigrationStatus:
    """凭据收敛面的**唯一**读数出处：CLI 打印的就是这份结构，不在它之外另造第二套计数。

    计数读 `count_by_algorithm()`（一次 GROUP BY），逐行读 `list_records()`：两处都走
    `user_store`，本模块不自己开连接，免得这张表的第二个读口径从这里长出来。
    """
    counts = user_store.count_by_algorithm()
    rows = tuple(
        AccountStatus(
            username=record.username,
            algorithm=record.algorithm,
            credentials_version=record.credentials_version,
            must_change=record.must_change,
            locked_until=record.locked_until,
            updated_at=record.updated_at,
        )
        for record in user_store.list_records()
    )
    return MigrationStatus(
        legacy_count=int(counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)),
        argon2id_count=int(counts.get(credentials.ALGORITHM_ARGON2ID, 0)),
        accounts=rows,
    )
