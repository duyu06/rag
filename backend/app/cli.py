"""凭据运维面（规格 §8.6 / §8.7 / §11）。口令只从环境变量读，绝不进 argv。

argv 是**可观察**的：`ps`、shell history、CI 的日志抓取都会把口令抄走，所以这里没有
`--password` 这一项，也不接受任何位置参数形式的口令。判据在契约用例里是按 argparse 的
**行为**钉的（未定义选项 ⇒ `SystemExit`），不是翻 `--help` 文本——文本会随措辞漂移。

`must_change` 由动作决定，而不是由写路径决定：`bootstrap-admin` 造的是"这个账号从此能登录"
（门关上），`reset` 造的是"这口令不是你选的"（门开着）。两个动作走的是 `auth.provision_credentials`
同一条写路径，因此清锁与版本 bump 不可能只在其中一支发生（SECA-12 / §7.5）。

本模块**不**创建、**不**修改、也**不**启用或停用任何身份：身份的唯一真源是配置文件
（SEC-A-010），CLI 顺手建号会造出第二个真源，而"停用一个账号"这件事在这里根本没有对应动作。

`credentials migrate` 是这条运维面上唯一的**读入**动作（规格 §11 / §20.5）：升级工件
`data/legacy_credentials.json` 只有被运维点名执行时才会被消费，启动路径绝不自动导入。理由不是
"自动不方便"，而是自动导入会把 §8.5 那半句「生产代码不再自动导入 legacy」吃掉——M19 那发变异
（缺行就顺手导）与全新安装的 `legacy_count=0` 判据都靠这半句活着。显式动作换来三样东西：退出码、
可归档的逐字段输出、一个明确的 actor。它**不读任何明文口令**（写的就是工件里已有的摘要），
所以 `CREDENTIALS_PASSWORD` 这一格规则与它无关。
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from app import auth, credentials, credentials_migration, directory, user_store
from app.audit import recent_events, record_event
from app.config import settings
from app.user_store import CredentialStoreError

#: 口令的唯一来路。名字是运维接口的一部分（部署文档与 `.env` 模板都写它）。
PASSWORD_ENV_VAR = "CREDENTIALS_PASSWORD"

#: 动作 → 落库后的 `must_change`。缺这一格的动作在下面就被 argparse 拒了。
_MUST_CHANGE_BY_ACTION = {"bootstrap-admin": False, "reset": True}

#: 退出码是**一张表**，不是散在两个函数里的字面量（规格 §11 的 rc 表；与上面那张意图表同源）。
#: 执行这一步的是人或脚本，二者都要能分辨"把开关拨回去"（2）与"存储写不进去"（1）；§15.1 第 6
#: 步靠它判读。数值一格未动——这里只给既有分类起名字。要新增一格必须先改 §11 那张表，不在此处。
_EXIT_OK = 0
#: 基础设施事故：`CredentialStoreError` **与 `sqlite3.Error` 同归这一格**（DB 锁 / 卷满 / 表不
#: 存在），且两条写腿与 `migrate` 都不得以裸栈出到运维面前。
_EXIT_STORE_INCIDENT = 1
#: 运维一次能修完的拒绝：企业形态挡下导入、工件整份读不得、身份不存在、env 口令缺失或过短、
#: 策略不通过。三段子含义由 stderr 那句话分诊，不再各自开码（§11 表下的那段裁定）。
_EXIT_REFUSED = 2
#: 不该出现的分支 = 开发者缺陷。给 3 而不是并入 2：脚本唯一需要可靠分辨的是"事故=1"与"非 1"，
#: 把开发期缺陷混进"运维能自己修"那一格，只会让它被重跑一遍。
_EXIT_DEV_DEFECT = 3

_COPY_NO_ENV_PASSWORD = (
    f"{PASSWORD_ENV_VAR} 未设置或不足 12 字符：口令只能放在这个环境变量里，"
    "不接受任何命令行参数形式"
)

#: 企业形态那一格的拒绝文案。点名动作与"一行未写"是同一句话的两半：运维看完要知道文件该
#: 留在原地（不是"导了 0 个人"），也要知道下一步是拨开关而不是重跑。文案里没有 digest。
_COPY_ENTERPRISE_REFUSES_MIGRATION = (
    "企业形态（SECURITY_ENTERPRISE_MODE=true）不导入任何 legacy："
    "`credentials migrate` 已拒绝，未写入任何一行。升级工件留在原地，"
    "把开关拨回 false 再执行这一步"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="凭据运维面（口令只从环境变量读）"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    actions = commands.add_parser("credentials").add_subparsers(
        dest="action", required=True
    )
    bootstrap = actions.add_parser(
        "bootstrap-admin", help="为**已存在的**身份写入 argon2id 凭据"
    )
    bootstrap.add_argument("--username", required=True)
    reset = actions.add_parser("reset", help="重置口令并强制下次登录改密")
    reset.add_argument("--username", required=True)
    actions.add_parser("migration-status", help="打印各算法行数与逐账号状态")
    # 没有 `--path`、没有 `--password`、没有 `--force`：`migrate` 的输入位置由 §8.2 钉死在
    # `credentials_migration.LEGACY_INPUT_PATH`，"导多少次"由 `only_missing` 决定（幂等），
    # 每多一枚开关就是多一条能把已收敛账号写回 legacy 的路。
    actions.add_parser(
        "migrate", help="导入升级工件 data/legacy_credentials.json（运维显式，启动不自动做）"
    )
    return parser


def _password_from_env() -> str | None:
    """读出口令；缺失或不足下界时返回 None，由调用方给出**同一句**提示。

    两条输入形状（没设 / 太短）必须汇成一句可执行的话：分成两句就会有一句在讲"你给的
    值太短"——那等于把值本身的存在性说出去了。这里任何分支都不打印取值。
    """
    value = os.environ.get(PASSWORD_ENV_VAR)
    if value is None or len(value) < auth._MIN_PASSWORD_LENGTH:
        return None
    return value


def _last_successful_login(events: list[dict]) -> dict[str, str]:
    """从既有审计面派生"逐账号最后成功登录时间"（§8.7，不加 schema 列）。

    裁定理由（progress.md：为观测字段动认证主表的 schema 会把 §8.8 的事务不变量拖进来）：
    这一格只读不写、取的是 `LOGIN/SUCCESS` 里最大的那个 timestamp，手法与 `knowledge_os`
    名册的 `list_users` 同源。审计轮转后取不到 ⇒ 打印 `-`，那是可接受的观测退化，不是安全退化。
    """
    last: dict[str, str] = {}
    for event in events:
        if event.get("action") == "LOGIN" and event.get("status") == "SUCCESS":
            name = str(event.get("username"))
            stamp = str(event.get("timestamp", ""))
            # ISO-8601（UTC、定宽）字典序 == 时间序，直接比字符串即取到最新那一枚。
            if stamp >= last.get(name, ""):
                last[name] = stamp
    return last


def _print_status() -> int:
    status = credentials_migration.status()
    print(f"legacy_count={status.legacy_count} argon2id_count={status.argon2id_count}")
    last_login = _last_successful_login(recent_events(5000))
    for row in status.accounts:
        # 逐账号四格全在（§8.7 验收证据面）：派生的最后成功登录时间、`must_change`、
        # 是否锁定，外加凭据行自己的 `updated_at`（此前被整个丢掉）。审计里没有 ⇒ `-`。
        print(
            f"{row.username}\t{row.algorithm}\tv{row.credentials_version}"
            f"\tmust_change={int(row.must_change)}\tlocked={row.locked_until or '-'}"
            f"\tlast_login={last_login.get(row.username) or '-'}"
            f"\tupdated_at={row.updated_at or '-'}"
        )
    return _EXIT_OK


def _migrate_legacy_artifact() -> int:
    """legacy 导入的唯一生产入口（§11 规则四条各自落在这里）。

    - **企业形态先拒**，连一次 DDL 都不发：§8.5 企业列写的就是「不导入任何 legacy」，"开关一拨、
      文件还在"不能变成绕过 fail-closed 的通道。
    - **工件不在场 ⇒ rc 0 且 `artifact_present=False`**：那是全新安装的合法稳态，不是失败。把一次
      正常收工判成事故，运维下一步就是去找 `--skip-missing` 之类的开关，而那类开关才是真危险。
    - **`import_from_artifact()` 用它的默认 `only_missing=True`**：已存在的行连试都不试。改成覆写的
      那一刻，重跑导入就会把已收敛的 argon2id 行降回 legacy，`legacy_count` 永远闭不上——那正是
      SEC-A-004 判红的那个形状。
    - **不接触口令**：本函数里没有一行读 `PASSWORD_ENV_VAR` 的代码，`_password_from_env` 那条路
      与它无关（§11 规则 4）。

    退出码取自本文件顶部那张表（§11）：0 成功（含"没有工件"）、1 存储事故、2 运维形态/权限类
    拒绝。异常消息原样转 stderr，不再包一层：`user_store` 与 `credentials_migration` 的消息本身
    就只带用户名与路径、不带任何 digest（口径同两条写腿的 `print(str(exc))`）。

    **建表与导入同属一条腿**：库锁住 / 卷满时 `ensure_user_credentials_schema()` 自己就会抛
    `sqlite3.OperationalError`，把它留在 `try` 外面等于让最常见的基础设施事故以裸栈出场——Python
    恰好以 1 退出，但运维看到的是一截 traceback，而 §11 要求这一格"不得以裸栈出到运维面前"。
    """
    if settings.security_enterprise_mode:
        print(_COPY_ENTERPRISE_REFUSES_MIGRATION, file=sys.stderr)
        return _EXIT_REFUSED
    try:
        # schema 也在这条腿里（见上面那段）：`import_from_artifact()` 读路径不建表，建表是调用方
        # 的前置条件，而"库根本打不开"这件事必须在两边都被归成同一次事故。
        user_store.ensure_user_credentials_schema()
        report = credentials_migration.import_from_artifact()
    except (CredentialStoreError, sqlite3.Error) as exc:
        # `CredentialStoreError` 只裹住 `user_store` 自己认下的那几格（约束冲突 + 账号缺失）；
        # busy/locked、卷满、文件打不开不走那条道，它们以 `sqlite3.Error` 家族直接出场。两半同归
        # "基础设施事故"：运维要分辨的只是"重跑一次"还是"去修盘"，不是第三枚退出码。
        print(str(exc), file=sys.stderr)
        return _EXIT_STORE_INCIDENT
    except credentials_migration.MigrationArtifactError as exc:
        # 整份拒是运维一次能修完的失败（导出那一步的事），不是存储事故：给 2，与"身份不存在"
        # "口令不合格"同一类。库里一行都没有——`read_artifact` 在任何写之前就把整份判掉了。
        print(str(exc), file=sys.stderr)
        return _EXIT_REFUSED
    # 逐字段打印（`-` = 该格无值，口径同 `_print_status`）：四个字段各自一行，跑一次留一份台账。
    print(f"artifact_present={report.artifact_present}")
    print(f"imported={len(report.imported)} {','.join(report.imported) or '-'}")
    print(f"skipped={len(report.skipped)} {','.join(report.skipped) or '-'}")
    print(f"reason={report.reason or '-'}")
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.action == "migrate":
        # 分派放在建表**之前**：企业形态那一格要求"一行不写"，而 `ensure_user_credentials_schema()`
        # 自己也是一次写（DDL + 把库文件建出来）。下面那条注释讲的"各动作都要过这一道"对
        # `migrate` 依然成立，只是改由 `_migrate_legacy_artifact()` 在拒绝判定之后自己过。
        return _migrate_legacy_artifact()
    # 建表是 `credentials_migration` 的调用方前置条件（它的读路径不建表），放在这里
    # 而不是各动作内部：`migration-status` 与两条写腿都要过这一道。
    user_store.ensure_user_credentials_schema()
    if args.action == "migration-status":
        return _print_status()

    identity = directory.get_identity(args.username)
    if identity is None:
        print(f"身份不存在：{args.username}（请先写入 config/users.json）", file=sys.stderr)
        return _EXIT_REFUSED
    password = _password_from_env()
    if password is None:
        print(_COPY_NO_ENV_PASSWORD, file=sys.stderr)
        return _EXIT_REFUSED
    reason = auth.validate_new_password(args.username, password)
    if reason:
        # 三条腿里 CLI 也是改凭据的一条：策略拒绝同样落 `password_policy_rejected`，
        # 否则脚本化的批量尝试只在 HTTP 面留痕、CLI 面留不下（§9.1 审计与展示两栏）。
        # 事件只带账号名与角色，取值/长度/hash 一概不进。
        record_event(
            username=args.username,
            role=identity.role,
            action="PASSWORD",
            status="DENIED",
            detail=auth.AUDIT_PASSWORD_POLICY_REJECTED,
        )
        print(reason, file=sys.stderr)
        return _EXIT_REFUSED

    if args.action not in _MUST_CHANGE_BY_ACTION:
        # 走到这里只可能是 parser 添了**第三条口令腿**却忘了进这张意图表——那是开发期缺陷
        # （`migrate` 不落在这里：它在建表之前就分派掉了，压根不写 argon2id 行）。宁可点名
        # 退出，也不让 `_MUST_CHANGE_BY_ACTION[args.action]` 崩一个 `KeyError` 栈；更不静默取
        # 某个默认值，因为"重置却忘了置门"这类事故正是从静默 fallback 里漏出来的。
        print(
            f"未预期的 credentials 动作：{args.action}（`_MUST_CHANGE_BY_ACTION` 未同步）",
            file=sys.stderr,
        )
        return _EXIT_DEV_DEFECT
    must_change = _MUST_CHANGE_BY_ACTION[args.action]
    try:
        version = auth.provision_credentials(
            args.username, plain_password=password, must_change=must_change
        )
    except CredentialStoreError as exc:
        # 固定文案、零口令：`user_store` 的异常消息本身就不带凭据材料，原样转出去即可。
        # 这一格仍然只接 `CredentialStoreError`：把 `sqlite3.Error` 同样扩到两条口令腿是另一件
        # 事（那个洞早于本任务，收口方已按 §11 表下那条另记），本轮不顺手改它的行为。
        print(str(exc), file=sys.stderr)
        return _EXIT_STORE_INCIDENT
    finally:
        # 用完立刻从本进程的环境里抹掉：后面任何一次 print、异常或子进程继承都不该再拿到它。
        os.environ.pop(PASSWORD_ENV_VAR, None)

    record_event(
        username=args.username,
        role=identity.role,
        action="PASSWORD",
        status="SUCCESS",
        detail="credential_bootstrap" if args.action == "bootstrap-admin" else "password_reset_by_admin",
        # CLI 无独立 actor（信任边界=能读写该库的进程），username 与 target 同指被操作的账号；
        # 仍显式带 `target` 这格，好让审计查询"谁被重置过"两条腿共用一个字段口径。
        target=args.username,
    )
    print(
        f"{args.username}: algorithm={credentials.ALGORITHM_ARGON2ID}"
        f" version={version} must_change={int(must_change)}"
    )
    return _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
