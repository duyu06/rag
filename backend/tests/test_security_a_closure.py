"""SEC-A closure 门（Task 10 / 计划 Step 5）：三处扫描里能在测试面自证的那几处。

判据出处是规格 §4 SEC-A-004 与 §12 SECA-04 那一行："SQL 门 `legacy_count=0` + closure 三处扫描
5 枚 digest = 0 命中"。**三处**指的是三个位置（`app/`、`config/`、库），digest 是 5 枚而不是
3 枚——数值以规格 §2 那张表为准（5 枚账号 hash 作为源码字面量存在，已推送 `origin/main`）。

必须说清、也最容易被后人读错的一件事：**这个文件里每条用例证的都是"测试面"**。
`tests/conftest.py` 的会话级护栏把 `CONVERSATION_DB_PATH` 整场改道到临时库，所以

- `test_running_database_holds_no_active_legacy_credential` 数的是**测试库**（那里既没有 demo
  的 legacy 行，也不该有——§8.2 明写全新安装不生产 legacy 行）；
- 生产库（`backend/data/conversations.db`）的 `legacy_count=0` **不由本文件证明**。它由
  `.superpowers/sdd/SECURITY_A_PLAN/closure-real-db-legacy-count.txt` 那份带外查询证明，两份证据
  不许互相冒充：拿本用例去签 SECA-04 的库半边，等于用"临时库里恰好没人插过 legacy 行"顶替
  "升级路径真的收敛过"。

第三条用例是 closure 的收尾形状：`data/legacy_credentials.json` 是**升级工件**（§8.2），
它的生命周期被严格限定在"从 SEC-A 之前的版本升级"这一条路径上，`legacy_count` 归零之后必须删除。
它还活着 = 收敛没关门；它归零前被删 = 把还没迁完的人关在门外。所以这条断言只可能出现在
closure 文件里，出现在别的文件里都是错的时序。

**Task 10f 起，本文件还多一段（那八枚）**：SPEC-A §16「必须原样绿」点名的 8 处登录调用点里，
`tests/test_real_llm_failover_acceptance.py:686` 是唯一一枚跑在**自己造的临时库**上的——它拿不到
会话级 `seed_demo_credentials()`，而那份文件是 V2.3 封版产物（一字不许改）。§16 的裁决是
「改的是它们脚下的凭据来源」，于是接缝住在 `tests/real_llm_failover_kit.py` §5.5，触发点住在
`tests/conftest.py`，**判据全在本文件**：正向（接缝在场⇒200+键集）、§8.5 的负向对照（schema 在、
行不在⇒统一 401 `invalid_credentials`，这条不许因为"测试想要 200"就被放宽）、
`init_usage_db` 那枚建库入口与 `user_store` 的读腿都**不**把凭据表建出来（**Task 10g 把这半句
重新表述过**：原来那句"生产侧没长出自动建表那条腿"一句话塞了两件事，而其中"app 自己不建表"
已被 §8.5 增补段推翻——现在成立的三分法是"读路径与 usage 建库入口不建、**lifespan 建**"，
建表那一侧的判据在下面那段）、
保护集拒写、开关只有 `acceptance_enabled()` 一枚、装卸不叠层、触发点在开关打开时真的装上
（子进程回到同一枚断言，判据不写两份）。这一段证的仍是**测试面**：产品的 fail-closed 语义
由它前面那几枚与 `test_credentials_contract.py` 继续看守。

**Task 10g 起，本文件最后还有一段（后面那六枚）**：它证的是**部署面**——全新安装（没跑过任何
CLI、没做过任何手工 DDL）冷启动之后的那条登录腿。§8.5 的企业列一直写着「`user_credentials`
无行 ⇒ 任何登录统一失败（fail-closed，**非 500**）」，而实现里从没人建过那张表
（§20.6 记的根因：两处注释把建表交给「启动编排 / CLI」，启动编排那半句从没被写下），于是那句话
在部署面上是破的、矩阵却是绿的。那六枚同时钉两侧：lifespan **必须**建表（回归本体 + 企业形态
零行 + 幂等 + DDL 失败 fail-fast），而读路径与 `usage` 那枚入口**仍然不许**建表
（§8.5 保留的那半句，两侧都成立才叫判据）；最后一枚钉的是本任务为护栏配的那份放宽**只**放过
那一枚 DDL —— 同一座漏斗里写出行、漏斗外面建表，两个方向都仍然判写。

这些 digest 字面量住在本文件而不是 `app/`/`config/`：**这是有意的**。closure 扫描要读的就是那两棵
树，把被扫的东西放进被扫的树里会自相矛盾（M15 杀的就是这个形状）；测试目录不在扫描根里。SECA-20
那道 secret 门也**不会**因此需要新的一行豁免：它的三枚面要的是"键名 = 引号值"的形状
（`password=…` / `api_key: …`）或现网密钥的材料形状（`sk-…` / `ghp_…` / `eyJ…` / PEM），一枚裸
64 位 hex 两样都不沾——这由那扇门自己的 `豁免表 == 命中表` 钉复确认，命中数一枚不加。
"""

from __future__ import annotations

import contextlib
import inspect
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
for _entry in (str(BACKEND_DIR), str(BACKEND_DIR / "tests")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import pytest
import real_llm_failover_kit as kit                                  # noqa: E402
from app import credentials, user_store  # noqa: E402
from sec_a_seed import DEMO_TEST_CREDENTIALS  # noqa: E402

#: 规格 §2 事实表点名的 5 枚账号 hash（`admin / sales01 / hr01 / user / viewer`），
#: 与计划 Step 5 的清单逐字相同。**不要**从 `data/legacy_credentials.json` 现推：那个文件在
#: closure 的最后一步被删除，判据不能依赖一个注定消失的输入。
LEGACY_DIGESTS = (
    "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894",
)
#: 静态可自证的两处。第三处是库，走 `count_by_algorithm()`（下面第二条用例）。
SCANNED_ROOTS = ("app", "config")
#: 升级工件的唯一合法位置（`credentials_migration.LEGACY_INPUT_PATH` 的默认值按进程 cwd 解析，
#: 镜像里 WORKDIR 就是 `backend/`）。断言按 `BACKEND_DIR` 锚定，不跟着调用方的 cwd 漂。
MIGRATION_ARTIFACT = BACKEND_DIR / "data" / "legacy_credentials.json"


def test_steady_state_code_holds_no_legacy_digest():
    """SECA-04 的代码/配置半边：三处扫描中稳态可静态自证的两处。"""
    offenders = []
    for root in SCANNED_ROOTS:
        for path in (BACKEND_DIR / root).rglob("*"):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [f"{path}:{digest}" for digest in LEGACY_DIGESTS if digest in body]
    assert [] == offenders


def test_running_database_holds_no_active_legacy_credential():
    """SECA-04 的库半边：这是 release gate 的硬门，未归零 ⇒ BLOCKED（不是 PENDING）。

    读的是**测试库**（见模块 docstring 那条区分）。这里先 `ensure_user_credentials_schema()`
    是必要的而不是多余的：`user_store` 的读函数**不建表**（唯一的建表者是它自己），表不存在时
    报错才是产品语义；在测试面把表建出来才能问"有没有 legacy 行"这个问题。
    """
    user_store.ensure_user_credentials_schema()
    counts = user_store.count_by_algorithm()
    assert 0 == counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)


def test_the_migration_artifact_is_gone_after_closure():
    """升级工件在 closure 之后必须不在场：§8.2 把它限定成一次性输入，不是长期真源。"""
    assert not MIGRATION_ARTIFACT.exists()


# ---------------------------------------------------------------------------
# Task 10f：P0 登录腿脚下的凭据来源接缝（规格 §16 点名的
# `test_real_llm_failover_acceptance.py:686`，接缝定义在 `tests/real_llm_failover_kit.py` §5.5）
#
# 这八枚用例证的是**接缝**，不是产品。产品侧那条"全新安装不自动造凭据行 ⇒ 统一 401"
# 的语义（§8.5）由下面的负向对照继续钉着——它必须**在没有接缝的那条路上**成立，
# 否则接缝就悄悄把 fail-closed 放宽成了"测试帮忙建号"。
# ---------------------------------------------------------------------------

#: P0 登录腿的账号（口令住在 `sec_a_seed` 的测试字面量里，这里**不**复制第二份）。
P0_LOGIN_USERNAME = "admin"
#: `/api/auth/login` 的成功面键集（`app/main.py` 的那一枚返回，含 SECA-11 的 additive 键）。
LOGIN_RESPONSE_KEYS = {"access_token", "token_type", "user",
                       "password_change_required"}
#: §8.5 塌成同一条脸的那枚审计 token（四种失败态的唯一区别就在这一格里）。
AUDIT_INVALID_CREDENTIALS = "invalid_credentials"

#: 闸②给"开关只能读一枚 env"用的同款正则：接缝自己**一枚都不许多读**。
_ENV_READ_RE = re.compile(r"(?:getenv|(?:\(|\.|\b)(?:source|os\.environ|environ)\.get)\(\s*"
                          r"([A-Za-z_][A-Za-z0-9_]*)")


def _p0_shaped_db(tmp_path: Path, label: str) -> Path:
    """照 P0 `setUp` 的形状造落点：`<...>/run/<stamp>/conversations.db`（父目录先在场）。"""
    run_dir = tmp_path / "run" / label
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "conversations.db"


def _login_once(username: str, password: str):
    """打一次 `/api/auth/login`：与 P0 `_http_face_200` 同形（`TestClient` 不进 lifespan）。"""
    from fastapi.testclient import TestClient

    from app.main import app as fastapi_app

    return TestClient(fastapi_app).post("/api/auth/login",
                                        json={"username": username, "password": password})


#: 终审判定 C2 的处置件。本文件那枚"登录 200"的用例驱动**真实签发腿**：`issue_token` 读的是
#: `settings.jwt_secret`，而本机 `backend/.env` 里那枚是 **31 字节** ⇒ PyJWT 每次签发一句
#: `InsecureKeyLengthWarning`——整套件的警告基线于是成了宿主机 `.env` 的函数，"警告数不变"这枚
#: 回归信号不再可信。本仓对这一类早有专用件（`sec_a_fixtures.LongJwtSecretMixin`），但它是
#: unittest 的 `setUp` 混入、而这一枚是 pytest 函数用例 ⇒ 这里用**等价的长 secret 注入**：只换
#: `jwt_secret` 那一个属性（假材料、拼接构造，口径同本文件 `DEV_COLD_BOOT` 那句"两列都给 ≥32
#: 字节的假 secret"）。**没有**用 `filterwarnings` 压掉（静音会把别的来源的同一枚警告一起藏掉），
#: **没有**改规格里的警告数。
SEAM_JWT_SECRET = "x" * 48


def test_seam_gives_the_p0_login_leg_its_credential_source(tmp_path, monkeypatch, request):
    """正向（§16 那句"改的是它们脚下的凭据来源"）：接缝在场 ⇒ 同一条路登录 200 + 键集齐。

    走的必须是 P0 用的那枚**入口**（`usage.init_usage_db(显式路径)`），不是"另外造一份带行的库"：
    接缝包的正是这一步，换一步就证不到它。
    """
    from app.llm import usage as usage_module

    db = _p0_shaped_db(tmp_path, "seam-on")
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    monkeypatch.setenv("REAL_LLM_ACCEPTANCE", "1")        # 与 P0 的收集门同一枚开关
    request.addfinalizer(usage_module.reset_usage_state)  # 路径覆盖是进程全局
    request.addfinalizer(kit.uninstall_login_credential_seam)

    unwrapped = usage_module.init_usage_db
    assert kit.install_login_credential_seam() is True
    assert kit.login_credential_seam_is_installed() is True
    assert usage_module.init_usage_db is not unwrapped, "开关打开了却没换上包装 = 接缝是空的"

    returned = usage_module.init_usage_db(str(db))        # 透传：返回值也是真函数那一个
    assert Path(returned) == db
    tables = kit.other_tables(db)
    assert kit.CREDENTIAL_TABLE in tables, f"临时库里没有凭据表：{tables}"
    assert "llm_request_logs" in tables, f"接缝把账本表挤掉了：{tables}"
    assert kit.ledger_rows(db) == [], "接缝往账本里塞了行 ⇒ P0 的 rows==1 判据不再可信"

    # 见 `SEAM_JWT_SECRET`：只把签发腿脚下那枚 secret 换够长，判据（200 + 键集）一字未动。
    from app import config as config_module

    with mock.patch.object(config_module.settings, "jwt_secret", SEAM_JWT_SECRET):
        response = _login_once(P0_LOGIN_USERNAME, DEMO_TEST_CREDENTIALS[P0_LOGIN_USERNAME])
    assert response.status_code == 200, response.text
    assert set(response.json()) == LOGIN_RESPONSE_KEYS


def test_p0_login_leg_without_the_seam_stays_fail_closed(tmp_path, monkeypatch, request):
    """负向对照（§8.5 的原事实，必须**保住**）：schema 在场、行不在场 ⇒ 401 `invalid_credentials`。

    状态取的是控制器实测的那一行：`temp DB + ensure_user_credentials_schema() only`。
    这一枚是接缝的边界声明：全新安装**不**因为"测试想要一个 200"就长出自动建号那条腿，
    四种失败态对外仍不可区分（§8.5），所以判据取**审计 token** 与**状态码**，
    不取响应体里的状态词。
    """
    import app.main as main_module
    from app.llm import usage as usage_module

    recorded: list[str] = []
    monkeypatch.setattr(main_module, "record_login_event",
                        lambda **kwargs: recorded.append(str(kwargs.get("detail"))))
    db = _p0_shaped_db(tmp_path, "no-seam")
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    monkeypatch.delenv("REAL_LLM_ACCEPTANCE", raising=False)
    request.addfinalizer(usage_module.reset_usage_state)

    unwrapped = usage_module.init_usage_db
    assert kit.install_login_credential_seam() is False, "开关不合却装上了接缝"
    assert kit.login_credential_seam_is_installed() is False
    assert usage_module.init_usage_db is unwrapped, "接缝拒绝安装却还是动了产品模块的属性"

    usage_module.init_usage_db(str(db))
    assert kit.CREDENTIAL_TABLE not in kit.other_tables(db)
    # 把凭据 schema 建出来（§8.5 那条事实说的是"有表、没有行"），接缝不在场 ⇒ 谁也没种行。
    user_store.ensure_user_credentials_schema()
    assert 0 == sum(user_store.count_by_algorithm().values()), "没人种行，表里却出现了凭据行"

    response = _login_once(P0_LOGIN_USERNAME, DEMO_TEST_CREDENTIALS[P0_LOGIN_USERNAME])
    assert response.status_code == 401, response.text
    assert recorded == [AUDIT_INVALID_CREDENTIALS], recorded
    assert "用户名或密码错误" == response.json()["detail"]


def test_harness_entry_point_alone_leaves_no_credential_schema(tmp_path, monkeypatch, request):
    """接缝**为什么必须**落在那枚建库入口上：`usage` 那枚入口与 `user_store` 的读腿都不建凭据表。

    **本枚的目标在 Task 10g 之后被拆开写过**（原句"harness 入口单独跑时凭据 schema 压根不在场
    ⇒ 生产侧没长出自动建表那条腿"是**一句话塞了两件事**，第二件已被 §8.5 增补段改掉）：
    现在成立的表述是三句——① `usage.init_usage_db()` 那枚建库入口不建凭据表；
    ② `user_store` 的**读路径**不建表；③ **app 的 lifespan 建**（那是 §20.6 的裁定，
    由下面 `test_the_app_boot_creates_the_table_while_a_bare_read_still_does_not` 等四枚钉着）。
    ①②两半由**接缝与测试面**继续看守：接缝仍然必须存在，因为 P0 走的是①那条入口而不是③，
    sealed P0 的临时库上打登录腿拿到的不是 401 而是一条 `no such table` 的
    `sqlite3.OperationalError`——这比"统一 401"更难看了，也正是 §16 要求"改它们脚下的
    凭据来源"的那件事。接缝走 `install_demo_credentials()` ⇒ 同一枚唯一建表者 + 真写腿，
    **没有**为此在接缝或读路径上加任何自动建表/自动建号分支（这一枚钉的就是那两半没被加）。

    最后那一步"读完之后再点一次表清单"是本次重新表述时**新加**的判据（不是放宽）：它把
    ②钉成"读过之后那份文件里仍然没有这张表"，于是"把 DDL 搬进 `_connect()`"这种把本枚
    变成静默通过的写法，会在这里红而不是在这里绿。
    """
    import sqlite3

    from app.llm import usage as usage_module

    db = _p0_shaped_db(tmp_path, "schema-absent")
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    request.addfinalizer(usage_module.reset_usage_state)

    usage_module.init_usage_db(str(db))

    assert "llm_request_logs" in kit.other_tables(db)
    assert kit.CREDENTIAL_TABLE not in kit.other_tables(db)
    with pytest.raises(sqlite3.OperationalError) as raised:
        user_store.get_record(P0_LOGIN_USERNAME)
    assert kit.CREDENTIAL_TABLE in str(raised.value)
    # ②：那次读**不许**顺手把表建出来（判据在文件上，不在异常消息上——消息可以换文案）。
    assert kit.CREDENTIAL_TABLE not in kit.other_tables(db), \
        "读腿把凭据表建出来了 ⇒ DDL 搬进了 `_connect()`，本枚从『红』退化成『绿』的那种写法"


def test_seam_does_not_write_credentials_into_a_protected_database(tmp_path):
    """接缝的落点义务：保护集下的真库**动手之前就拒**，且拒完之后那份文件一个字节没变。

    `install_demo_credentials()` 自己过这一关（护栏看不见文件级复制），接缝只是转发——
    这一枚钉的是"转发没有把这关转发掉"。真库只以**只读**方式被点数（`kit.other_tables`）。
    """
    import conftest as ledger_guard

    real_db = Path(ledger_guard.REAL_DB_PATH)
    before = kit.other_tables(real_db) if real_db.is_file() else []
    assert ledger_guard.path_is_protected(real_db), "落点判定漂了：这一枚的判据就没了对象"
    with pytest.raises(AssertionError):
        kit.prepare_login_credentials(real_db)
    assert (kit.other_tables(real_db) if real_db.is_file() else []) == before


def test_seam_reads_no_env_of_its_own_and_gates_only_on_acceptance_switch():
    """接缝的开关纪律：唯一一枚门是 `acceptance_enabled()`，自己**一枚 env 都不许多读**。

    与闸②（`test_real_llm_failover_gate.py::test_acceptance_enabled_reads_one_env_name_only`）
    同款判据、同款正则：那里钉的是收集门，这里钉的是凭据门。两处口径分开 = 有一天谁能
    在接缝里加第二个条件，把接缝点亮成"默认套件也种行"。
    """
    source = inspect.getsource(kit.install_login_credential_seam)
    assert [] == _ENV_READ_RE.findall(source), "接缝自己解析了 env：开关长成了两枚"
    assert "acceptance_enabled()" in source, "接缝没走那枚唯一的门"
    assert "init_usage_db" in source, "接缝包的必须是 P0 用的那枚建库入口"


def test_seam_is_idempotent_and_leaves_no_layer_behind():
    """接缝可反复装卸，且卸完之后 `usage.init_usage_db` 回到**原来那一枚**（不叠层）。"""
    from app.llm import usage as usage_module

    unwrapped = usage_module.init_usage_db
    with mock.patch.dict(os.environ, {"REAL_LLM_ACCEPTANCE": "1"}):
        assert kit.install_login_credential_seam() is True
        wrapped = usage_module.init_usage_db
        assert kit.install_login_credential_seam() is True
        assert usage_module.init_usage_db is wrapped, "第二次安装叠了第二层包装"
        assert kit.uninstall_login_credential_seam() is True
        assert kit.uninstall_login_credential_seam() is False
    assert usage_module.init_usage_db is unwrapped
    assert kit.login_credential_seam_is_installed() is False


def test_conftest_fixture_arms_the_seam_only_when_the_switch_is_on(request):
    """触发点的行为事实（`conftest.p0_login_credential_seam`）：开关在⇒接缝在位，不在⇒一字未动。

    默认套件走的是"不在"那一支；"在"那一支由下面那枚用例起的**子进程**回到**这同一枚**断言
    来跑（判据不写两份）。这一枚证明的是：接缝不是"谁手工叫一下才动"的孤零零函数，
    它挂在 sealed P0 的 `setUp` 之前就会发生的那一步上。
    """
    from app.llm import usage as usage_module

    armed = request.getfixturevalue("p0_login_credential_seam")
    assert armed is kit.acceptance_enabled()
    assert kit.login_credential_seam_is_installed() is kit.acceptance_enabled()
    if not kit.acceptance_enabled():
        assert usage_module.init_usage_db.__name__ == "init_usage_db", \
            "默认套件里 `init_usage_db` 已被包上 ⇒ 接缝不再是惰性的"


def test_conftest_fixture_arms_the_seam_for_the_real_acceptance_path():
    """带 `REAL_LLM_ACCEPTANCE=1` 起一枚子进程，让上面那枚断言走"开关在"那一支。

    它**不** import 那枚 sealed 文件、**不**碰 provider：真机端到端要的是真 failover 对
    （本机 ornith 装不起来、OpenAI key 为空 ⇒ 那是 PENDING_EXTERNAL，不在这里冒充）。
    这里证的是一句更窄也更可核的话：把开关摆到会话起点，conftest 的夹具就把接缝装上，
    于是 P0 的 `setUp` 调 `init_usage_db` 时脚下已经有凭据来源。
    """
    import subprocess

    environ = dict(os.environ, **{kit.ENV_SWITCH: kit.SWITCH_ON})
    target = f"tests/{Path(__file__).name}::" \
             f"{test_conftest_fixture_arms_the_seam_only_when_the_switch_is_on.__name__}"
    completed = subprocess.run([sys.executable, "-m", "pytest", target, "-q",
                                "-p", "no:cacheprovider"],
                               cwd=str(BACKEND_DIR), env=environ,
                               capture_output=True, text=True, timeout=600)
    assert completed.returncode == 0, (
        f"开关打开的那一跑没能把接缝装上（rc={completed.returncode}）：\n"
        f"{completed.stdout[-2000:]}\n{completed.stderr[-500:]}")


# ---------------------------------------------------------------------------
# Task 10g：lifespan 的那半句「启动编排」（§8.5 增补段 / §20.6 第七轮回写）
#
# 上面那一整段（Task 10f）证的是**测试面**的接缝；这一段证的是**部署面**：全新安装
# （没跑过任何 CLI）冷启动之后的登录腿。控制器实测的形状是
# `sqlite3.OperationalError: no such table: user_credentials` ⇒ 未处理 ⇒ HTTP 500，
# 当场破掉 §8.5 企业列自己那句「`user_credentials` 无行 ⇒ 任何登录统一失败
# （fail-closed，**非 500**）」。根因不在读路径的异常处理，而在 `user_store.py:105-113`
# 与 `credentials_migration.py:157-160` 两处注释一起交给「启动编排 / CLI」、却从没人写下的
# 那半句：CLI 那条只有运维敲过才生效，lifespan 里此前只有守卫与两枚 warmup。
#
# 这一段因此把**两侧**同时钉住（缺一侧就是空心判据，§20.6 记的正是这个形状）：
# app 的 lifespan 必须建表（否则 500），读路径与 `usage` 那枚建库入口仍然不许建表
# （否则 env 被清掉时往生产库提交 DDL，Task 2 那条已冻结的理由）。"表不在场"与
# "表在场但零行" 是两格事实，`test_p0_login_leg_without_the_seam_stays_fail_closed`
# 钉的是后一格，`test_harness_entry_point_alone_leaves_no_credential_schema` 钉的是
# 前两格的接缝侧，下面第一枚钉的是**部署侧的**"表不在场"。
# ---------------------------------------------------------------------------

#: 冷启动登录腿用的错口令。取"错不错根本进不了判定"这一格：库里没有可校验的行 ⇒ 认证腿在
#: 身份/凭据查找那一步就恒成本返回（§7.3），这一枚不与 `sec_a_seed` 的口令字面量比较。
COLD_BOOT_GUESS = "wrong-once"

#: 两形态各自那一套 `settings` 取值，钉在用例自己身上、不吃 `backend/.env`（同
#: `test_credentials_contract.py::LegacyImportCliTests.setUp` 那句"不吃环境"的理由：
#: 哪天宿主把 `SECURITY_ENTERPRISE_MODE` 拨成 true，dev 那几枚会以拒启动红掉，症状却读成
#: "登录腿坏了"）。企业那一列是 §8.5 三格守卫**全部通过**的最小配置——默认 secret 或空/含 `*`
#: 的白名单会让起进程直接拒启动，那就到不了登录腿。
#: 两列都给 ≥32 字节的假 secret（拼接构造，不指向任何环境）：默认 dev secret 短于 PyJWT 建议
#: 下限，会让下面那枚"登录 200"的用例多出一句 `InsecureKeyLengthWarning`，而"整套件警告数
#: 不变"是本仓的回归信号（口径同 `sec_a_fixtures.LongJwtSecretMixin`：换钥匙，不静音警告）。
DEV_COLD_BOOT = dict(security_enterprise_mode=False,
                     jwt_secret="x" * 48,
                     cors_allow_origins="http://localhost:3000")
ENTERPRISE_COLD_BOOT = dict(security_enterprise_mode=True,
                            jwt_secret="x" * 48,
                            cors_allow_origins="https://kb.example")


@contextlib.contextmanager
def _cold_boot(*, enterprise: bool = False, raise_server_exceptions: bool = False):
    """真起一次 app（`with TestClient(app)` 才会跑 lifespan），落点由调用方的 env 决定。

    `raise_server_exceptions=False` 不是装饰：本段第一枚用例要判的是**部署状态码**是 401 还是
    500（§8.5 企业列那句话讲的正是状态码），而默认的 `True` 会把缺陷形态从"一句
    `500 != status` 的红"变成一条裸栈——同一个失败，前者说得出破的是哪句承诺。

    两枚 warmup 换成 no-op 是**继承既有姿势**（`test_secret_hygiene_contract.py::
    StartupGuardLifespanTests._guard_only`）：`warmup_llm_router()` 按**当前目录**解析
    `config/llm_registry.json`，本套件从 `backend/` 与仓库根两种 cwd 跑，留着它证的就不是
    建表那一行；它们会不会被调用另有 `test_llm_usage_contract.py::WarmupWiringTests::
    test_lifespan_calls_both_warmups_side_by_side` 钉着。本处**不打桩**的是：§8.5 守卫、
    被测的那句建表、以及 `/api/auth/login` 整条腿。

    `settings` 那三格是 patch **单例的属性**而不是把整个对象换掉：`app/auth.py` 的签发腿拿的是
    import 期绑定的那一个 `settings` 名字，换对象会让"守卫看到的"与"token 看到的"劈成两把钥匙。
    """
    import app.main as main_module
    from app import config as config_module
    from fastapi.testclient import TestClient

    overrides = ENTERPRISE_COLD_BOOT if enterprise else DEV_COLD_BOOT
    with contextlib.ExitStack() as stack:
        for name, value in overrides.items():
            stack.enter_context(mock.patch.object(config_module.settings, name, value))
        stack.enter_context(mock.patch.object(main_module, "warmup_identity_permissions"))
        stack.enter_context(mock.patch.object(main_module, "warmup_llm_router"))
        with TestClient(main_module.app,
                        raise_server_exceptions=raise_server_exceptions) as client:
            yield client


def _login(client, username: str, guess: str = COLD_BOOT_GUESS):
    """打一次 `/api/auth/login`（口令那格走 `COLD_BOOT_GUESS`，调用方不必每次抄一遍）。

    审计 token 不在这里收：那是调用方 patch `main.record_login_event` 的事（与上面
    `test_p0_login_leg_without_the_seam_stays_fail_closed` 同一手法，两处不各写一份收集器）。
    """
    return client.post("/api/auth/login", json={"username": username, "password": guess})



def test_a_fresh_install_cold_boot_answers_login_with_the_unified_401(tmp_path, monkeypatch):
    """**这就是坏掉的那一枚**（§20.6 / §8.5 增补段）：全新安装冷启动后的登录是统一 401，不是 500。

    现场逐字照控制器那次复现：一个全新的 `CONVERSATION_DB_PATH`（文件压根不在场）、
    没有任何 CLI、没有任何手工 DDL、真起一次 app，然后打 `/api/auth/login`。
    修之前这里出去的是未处理的 `sqlite3.OperationalError`（⇒ 500），修之后是 §8.5 那张
    四态合一的脸。dev 形态与 §8.5 企业列**同一条判据**，企业那一格另有下面那枚。
    """
    import app.main as main_module

    db = tmp_path / "conversations.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    recorded: list[str] = []
    monkeypatch.setattr(main_module, "record_login_event",
                        lambda **kwargs: recorded.append(str(kwargs.get("detail"))))

    with _cold_boot() as client:
        response = _login(client, P0_LOGIN_USERNAME)

    assert 500 != response.status_code, "全新安装登录又退回 500：lifespan 那句建表没了"
    assert 401 == response.status_code, response.text
    assert "用户名或密码错误" == response.json()["detail"]
    # 有身份、无凭据行那一格塌成的 token（§9.1：四种失败态对外同一张脸，区别只在审计面）。
    assert [AUDIT_INVALID_CREDENTIALS] == recorded, recorded


def test_enterprise_cold_boot_logins_are_the_uniform_401_and_never_a_500(tmp_path, monkeypatch):
    """§8.5 企业列第一次在**部署面**被钉：`user_credentials` 无行 ⇒ 任何登录统一 401（非 500）。

    三格守卫先要过（默认 secret / 白名单缺失都会让起进程直接拒，那就到不了登录腿），
    所以这里给的是 `ENTERPRISE_COLD_BOOT`。企业形态不加载 demo 身份 ⇒ 账号名存在与否
    本就不可见；两条登录（demo 名与一个不存在的名字）必须是**同一张脸**：同一个状态码、
    同一段中文、同一枚审计 token，且都不是 500。
    """
    import app.main as main_module

    db = tmp_path / "conversations.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    recorded: list[str] = []
    monkeypatch.setattr(main_module, "record_login_event",
                        lambda **kwargs: recorded.append(str(kwargs.get("detail"))))

    with _cold_boot(enterprise=True) as client:
        responses = [_login(client, P0_LOGIN_USERNAME),
                     _login(client, "no-such-identity-at-all")]

    assert 0 == sum(user_store.count_by_algorithm().values()), "冷启动把凭据行也造出来了"
    for response in responses:
        assert 500 != response.status_code, response.text
        assert 401 == response.status_code, response.text
        assert "用户名或密码错误" == response.json()["detail"]
    assert [AUDIT_INVALID_CREDENTIALS] * 2 == recorded, recorded


def test_the_app_boot_creates_the_table_while_a_bare_read_still_does_not(tmp_path, monkeypatch):
    """「读路径不建表」这条裁定**两个方向**都要钉住：app 起来之后表在场；只读一次的裸库没有。

    反方向那一半不是多余的：把这次修复做成"把 DDL 搬进 `user_store._connect()`"同样能让
    上面两枚用例绿（登录不再 500），而它违反的正是 §8.5 保留的那半句——env 被清掉时
    默认落点会退回 `data/conversations.db`，让读顺手提交 DDL 等于往**可能是生产库**的那份
    文件里长出半张凭据表（`user_store.py:105-113` 的理由块）。这一枚把那条路也堵死。
    """
    import sqlite3

    booted = tmp_path / "booted-by-the-app.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(booted))
    with _cold_boot():
        pass
    assert kit.CREDENTIAL_TABLE in kit.other_tables(booted), \
        "lifespan 没把凭据表建出来 ⇒ 登录腿会退回 500"

    untouched = tmp_path / "read-only.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(untouched))
    with pytest.raises(sqlite3.OperationalError) as raised:
        user_store.get_record(P0_LOGIN_USERNAME)
    assert kit.CREDENTIAL_TABLE in str(raised.value)
    assert kit.CREDENTIAL_TABLE not in kit.other_tables(untouched), \
        "一次**读**就把表建出来了 ⇒ DDL 被搬进了 `_connect()`，§8.5 那半句已冻结的理由被推翻"


def test_booting_twice_on_a_file_that_already_has_rows_changes_nothing(tmp_path, monkeypatch):
    """幂等（`CREATE TABLE IF NOT EXISTS`）：表与行都已在场时冷启动不报错、不重建、不清行。

    覆盖 §20.6 说的那台"跑过一次 CLI 的机器"与"全新安装"必须同形：`install_demo_credentials`
    在目标文件不在场时是**整份复制模板**（表 + 5 行 argon2id，一枚 Argon2 都不重算），
    形状就是"运维先建过表、也种过行"。两遍冷启动之后行数一格不变，而且那条真登录仍然 200
    ——"表还在"与"行还在"是两格，判据取后者。
    """
    import sec_a_seed

    db = tmp_path / "conversations.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    sec_a_seed.install_demo_credentials(db)
    rows_before = user_store.count_by_algorithm()
    assert 0 < sum(rows_before.values()), "夹具没把行种进去 ⇒ 后面那枚等式是空的"

    for attempt in (1, 2):
        with _cold_boot() as client:
            response = client.post("/api/auth/login",
                                   json={"username": P0_LOGIN_USERNAME,
                                         "password": DEMO_TEST_CREDENTIALS[P0_LOGIN_USERNAME]})
        assert 200 == response.status_code, f"第 {attempt} 遍冷启动后登录不上：{response.text}"
        assert set(response.json()) == LOGIN_RESPONSE_KEYS

    assert kit.CREDENTIAL_TABLE in kit.other_tables(db)
    assert rows_before == user_store.count_by_algorithm(), "两遍启动改写了凭据行"


def test_a_failing_schema_step_refuses_to_start_the_process(tmp_path, monkeypatch):
    """建表那一步失败必须按守卫的既有形状 fail-fast：**穿出启动阶段**，不是留下一台会 500 的 app。

    这一枚判的是"修好的那一半"有没有被做成 `try/except` 里静音 + 继续起进程 —— 那种修法今天
    能让上面四枚全绿（表由 CLI 建过的机器不 500、全新机器起来一台会 500 的 app 也仍然"登录是
    500 而不是启动失败"），而 §8.5 增补段要的是**这一格失败等于这一格拒启动**。
    注入按**类型**不按消息（`sqlite3.OperationalError` 就是真实症状那一型：盘不可用 / 库只读）。
    `_cold_boot()` 在这里刻意**不**给 `raise_server_exceptions=False`：那枚开关管的是请求期，
    启动阶段的异常本来就该原样穿出 `__enter__`——它没穿出来说明起来了一台会服务的 app。
    """
    import sqlite3

    db = tmp_path / "conversations.db"
    monkeypatch.setenv("CONVERSATION_DB_PATH", str(db))
    with mock.patch.object(user_store, "ensure_user_credentials_schema",
                           side_effect=sqlite3.OperationalError("disk busy")):
        with pytest.raises(sqlite3.OperationalError):
            with _cold_boot():
                pytest.fail("建表失败却让进程起来了 ⇒ 症状退化成每请求各撞一次 500")

    assert kit.CREDENTIAL_TABLE not in kit.other_tables(db)


def test_the_widened_guard_lets_through_exactly_that_one_ddl(tmp_path):
    """本任务动过 `tests/conftest.py` 的归类 ⇒ 那份放宽要有效应钉，不能只靠注释自称很窄。

    会话护栏多挂的那道闸（`install_credential_store(..., watch_schema_funnel=True)`）只放过
    "唯一建表者在自己漏斗里提交的那一枚 `CREATE TABLE IF NOT EXISTS user_credentials`"。
    三个方向各一枚断言，缺一条就是把门调歪：
    ① 漏斗之内的那枚 DDL ⇒ 留在 read（lifespan 那一行的形状；否则每次"清 env 起进程"的测试
       都会被误判成"它写了凭据行"）；
    ② 同一座漏斗里**写出行**（"启动顺手造凭据" = M19）⇒ 仍然 write；
    ③ **漏斗外面**提交同一枚 DDL（"DDL 搬进 `_connect()`" = §8.5 保留的那半句失守）⇒ 仍然 write。
    这里自建一份与 `_GuardProbe` 同配置的探针护栏（假真库在 tmp 下），不借会话那一个实例，
    免得把统计写进 `credential_redirects()` 那本会话账上（`_real_ensure_schema` 那一处换的是
    **测试侧**护栏自己的属性，产品代码一字未动）。
    """
    import conftest as ledger_guard

    protected = tmp_path / "data"
    protected.mkdir()
    protected_db = protected / "conversations.db"
    target = tmp_path / "isolated" / "conversations.db"
    target.parent.mkdir()
    guard = ledger_guard.LedgerGuard(original_path=lambda: protected_db, target=target,
                                     protected_dirs=(protected,),
                                     label="[credential-guard]", subject="真实凭据表",
                                     warn_on_read=False)
    guard.install_credential_store(user_store, watch_schema_funnel=True)
    kinds = lambda: [kind for _src, _dst, kind in guard.records]
    try:
        user_store.ensure_user_credentials_schema()
        assert [ledger_guard.REDIRECT_READ] == kinds(), \
            "启动建表被判成写事故 ⇒ 第三道闸没装上，§8.5 增补段与护栏互相打脸"

        guard.records.clear()
        # 一条**读腿**拿到的连接上执行同一枚 DDL：这正是"把 DDL 搬进 `_connect()`"的形状。
        connection = user_store._connect()
        with connection:
            connection.executescript(user_store._SCHEMA)
        connection.close()
        assert [ledger_guard.REDIRECT_WRITE] == kinds(), \
            "漏斗之外的建表被放过了 ⇒「读路径不建表」这条裁定失去护栏"

        guard.records.clear()
        real_funnel = guard._real_ensure_schema
        guard._real_ensure_schema = lambda: user_store.create_argon2(
            P0_LOGIN_USERNAME, plain_password="a-good-password 123", must_change=False)
        try:
            guard.guarded_ensure_schema()
        finally:
            guard._real_ensure_schema = real_funnel
        assert [ledger_guard.REDIRECT_WRITE] == kinds(), \
            "同一座漏斗里写出**行**也被放过 ⇒ M19（启动自动造凭据）静默"
    finally:
        guard.uninstall()
