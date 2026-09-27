"""SEC-A-009 / §8.5 / §10 / SECA-17 / SECA-18 / SECA-20 的契约（Task 9）。

这个文件守的是三件事，各自都对应一次真实事故形状：

1. **脱敏的两个作用域（SEC-A-009）**：响应面 `redact_secrets` 语义一字不动；落盘面
   `redact_for_persistence` = 形态脱敏 + **精确全词键名**黑名单。两个方向都要有脸：敏感键
   必抹（SECA-17 正向），观测键（`input_tokens` 那族）必不误伤（子串 `token` 会顺手砸掉
   observability，即 M8）。授权凭据库 `user_store` 根本不经过任何 redactor（M9：结构钉）。
2. **响应面 / 落盘面那条边界要用真实登录证**：同一枚 access_token，登录响应里必须是**能用**的
   （客户端就靠它），落进遥测持久化面则必须被抹成占位符。一个"过宽的红actor"只有这条路能抓到。
3. **三守卫同生同死（§8.5 / SECA-18）**：直接调用 `evaluate_startup_guards`，不借 lifespan。
   另有一条**走真实 lifespan** 的钉子（`with TestClient(app)` 起一次进程）：`main.py` 里那句
   `assert_startup_safe()` 是全仓唯一的执行点，而 `TestClient(app)` 不进上下文管理器就不会跑
   lifespan——只钉函数本身时，把那一行删掉整套件照样绿。外加 root_path 下的无回显守卫（Task 7 移交的 P0）。
4. **审计事件归属由路由决定**：`/api/auth/login` 的拒绝记 `LOGIN`，`/api/auth/password/change`
   的**每一格**拒绝都记 `PASSWORD`。判据逐腿打真路由，不打 helper。

扫描门（SECA-20）用一条普通 pytest 用例跑遍交付面（tracked ∪ 未忽略的 untracked），豁免表与命中表
按 **(文件, 处数)** 互等（`test_llm_egress_guard.py` 同族做法）——键不是行号。口令变量
`CREDENTIALS_PASSWORD` 不得出现在 `.env.example`（SEC-A-002 配置半边）。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import subprocess
import sys
import threading
import unittest
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
TESTS_DIR = BACKEND_DIR / "tests"
for _entry in (str(BACKEND_DIR), str(TESTS_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import pytest  # noqa: E402

from app import agent_trace, audit, credentials, security, security_startup  # noqa: E402
from app.credentials import PasswordCapacityError  # noqa: E402

# --------------------------------------------------------------------------- #
# SECA-17 正向：落盘面按精确全词键名抹敏感键
# --------------------------------------------------------------------------- #

NOT_SECRETS = ("input_tokens", "output_tokens", "num_sources", "total_tokens", "token_type")
SECRETS = (
    "password", "password_hash", "access_token", "refresh_token",
    "authorization", "api_key", "app_secret", "tenant_access_token",
)

#: 黑名单的**内容**本身就是契约，所以要逐枚点名，而不是"遍历它自己"：只遍历表的用例对
#: 删表里的任何一枚都无感（表少一枚，循环跟着少一圈，照样绿）。`current_password` /
#: `new_password`（改密两条腿的入参键）、`secret` / `credentials`（泛键）都在这一格里。
EXPECTED_PERSISTENCE_DENY_SET = frozenset({
    "password", "password_hash", "plaintext_password", "current_password", "new_password",
    "access_token", "refresh_token", "authorization", "api_key", "app_secret",
    "tenant_access_token", "secret", "credentials",
})


def test_the_persistence_deny_set_is_exactly_the_intended_key_set():
    """删一枚、加一枚都红：等式两边是**清单**，不是自指遍历。"""
    assert EXPECTED_PERSISTENCE_DENY_SET == security.PERSISTENCE_SENSITIVE_KEYS


def test_the_persistence_deny_set_matches_case_insensitively():
    """判定读的是 `str(key).lower()`（`security.py` 里那一格）⇒ 大小写写法一律同判。

    反向也要有脸：观测键无论怎么写都不在黑名单里（`INPUT_TOKENS` 不许因为"整词等值"的
    大小写变体被抹），否则这条等值判定就退化成了又一次子串匹配。
    """
    for key in ("PASSWORD", "Current_Password", "ACCESS_TOKEN", "Api_Key", "SECRET", "Credentials"):
        assert security.redact_for_persistence({key: "v"})[key] == security.REDACTED, key
    for key in NOT_SECRETS:
        upper = {key.upper(): 1}
        assert security.redact_for_persistence(upper) == upper, key


def test_persistence_redaction_kills_sensitive_keys_by_exact_name():
    payload = {key: "sensitive-value" for key in SECRETS}
    redacted = security.redact_for_persistence(payload)
    assert all(redacted[key] == security.REDACTED for key in SECRETS), redacted


def test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample():
    """§9.3 的样本只列了几枚「等」；这张表里的每一枚都必须真的被抹（漏一枚即 M8 的另一半）。"""
    for key in security.PERSISTENCE_SENSITIVE_KEYS:
        assert security.redact_for_persistence({key: "v"})[key] == security.REDACTED, key


def test_persistence_redaction_does_not_collateral_damage_observability_keys():
    """SECA-17 的反方向：子串匹配 `token` 会顺手抹掉 usage 计数，那等于砸掉 observability 契约。

    `token_type` 是**真实**的登录响应键（bearer），把它连同 `*_tokens` 一起抹掉的就是那个"过宽的
    红actor"——正向能过不代表反方向能过，两向都得钉（M8 杀子串）。
    """
    payload = {"input_tokens": 12, "output_tokens": 34, "num_sources": 5,
               "total_tokens": 46, "token_type": "bearer"}
    # 清单与用例指的是同一张表，且这张表与黑名单**互不相交**：相交就意味着"观测键被列进了
    # 敏感键"，那正是 M8 反方向的形状。
    assert set(payload) == set(NOT_SECRETS)
    assert not set(NOT_SECRETS) & security.PERSISTENCE_SENSITIVE_KEYS
    assert payload == security.redact_for_persistence(payload)


def test_persistence_redaction_recurses_and_never_sniffs_value_content():
    """黑名单只看 dict 的**键**（整词），绝不嗅探值：值里出现 "password" 这个词不该被误抹。"""
    nested = {"detail": "the word password appears here", "usage": {"input_tokens": 7}}
    out = security.redact_for_persistence(nested)
    assert out["detail"] == "the word password appears here"
    assert out["usage"] == {"input_tokens": 7}


def test_persistence_redaction_still_runs_shape_matching():
    """落盘面 = 形态脱敏 ∪ 精确键名：值里嵌着 Bearer/apikey 形态时，形态那条腿照旧生效。"""
    out = security.redact_for_persistence({"note": "header: Bearer abc.def.ghi"})
    assert "Bearer [REDACTED]" in out["note"]


# --------------------------------------------------------------------------- #
# SEC-A-006：既有响应面 redact_secrets 语义一字不动
# --------------------------------------------------------------------------- #

def test_redact_secrets_semantics_are_unchanged():
    """既有 `redact_secrets` 的响应面语义一字不动（SEC-A-006）。

    这是**行为**探针，不是字节比对：它钉的是"形态照旧、且不因键名误伤"。调用点总数的等式钉在
    `test_the_four_persistence_faces_use_the_persistence_redactor`（AST，17 处）。
    """
    assert security.redact_secrets({"access_token": "keep-me"}) == {"access_token": "keep-me"}
    assert "Bearer [REDACTED]" in security.redact_secrets("header: Bearer abc.def.ghi")


def test_redact_secrets_does_not_apply_the_persistence_key_blacklist():
    """两个域是**两个**函数：响应面绝不因键名抹掉 access_token（登录就发不出票了）。"""
    body = {"access_token": "a-real.jwt.token", "password": "not-a-response-face"}
    kept = security.redact_secrets(body)
    assert kept == body, "响应面被落盘面的键名黑名单污染——登录/改密腿的 access_token 会被吃掉"


def test_the_two_faces_differ_on_exactly_the_key_name_blacklist():
    """两域唯一差别就是那一步整词键名判定；形态腿共用同一枚 redact_text。"""
    # 同一枚 access_token 值（非 Bearer 形态）：响应面原样、落盘面抹成占位符。
    fake = "eyJhbGciOiJIUzI1NiJ9.payload.sig"  # 变量名避开 token，免得测试自身撞扫描门的形态
    assert security.redact_secrets({"access_token": fake})["access_token"] == fake
    assert security.redact_for_persistence({"access_token": fake})["access_token"] == security.REDACTED
    # 而两者对形态的腿完全一致（Bearer 值都被脱敏），证明我没往 redact_text 之外再造第二套形态匹配。
    shared = security.redact_secrets({"note": "Bearer x.y.z"})["note"]
    assert shared == security.redact_for_persistence({"note": "Bearer x.y.z"})["note"]


# --------------------------------------------------------------------------- #
# 结构钉（M9）：授权凭据库永不经过任何 redactor
# --------------------------------------------------------------------------- #

def test_user_store_is_never_passed_through_a_redactor():
    """授权凭据库 ≠ 遥测面：把 redactor 罩到写凭据那一层，写进去的 hash 会被抹成占位符，
    下一次登录必失败（M9 就是这条）。判据是"持久层 import 里没有它"。"""
    source = (BACKEND_DIR / "app" / "user_store.py").read_text(encoding="utf-8")
    assert "redact_for_persistence" not in source
    assert "from app.security import" not in source
    assert "app.security" not in source


def _app_python_files(*, exclude_definition: bool = False) -> tuple[str, ...]:
    """`app/**/*.py` 相对 `app/` 的路径（结构钉的读法口径，与扫描门的键同形）。"""
    return tuple(sorted(
        str(path.relative_to(BACKEND_DIR / "app"))
        for path in (BACKEND_DIR / "app").rglob("*.py")
        if not (exclude_definition and path.name == "security.py")))


def _call_sites(name: str, *, files: Iterable[str] | None = None) -> int:
    """数**真调用**（AST）：`count("redact_for_persistence")` 会把 import 行与 docstring 里的
    名字一起算进来，那种数法对"多 import 一次"或"注释里提一句"都过敏，而对"把调用挪进
    f-string"完全无感。判据只能是语法树上的 Call 节点。"""
    total = 0
    for relative in (files if files is not None else _app_python_files()):
        source = (BACKEND_DIR / "app" / relative).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                total += called == name
    return total


def test_the_four_persistence_faces_use_the_persistence_redactor():
    """切换点钉死：只有 audit（写+读）与 agent_trace（存+取）这四张落盘面换了 redactor，
    每张面**恰好两处**调用；其余落点一概仍叫 `redact_secrets`。

    等式而不是 `>= 2`：写面或读面任何一张被换回去 ⇒ 1 ≠ 2 红；多出一张（有人把 redactor 罩到
    别的面上，M9 的形状）⇒ 同样红。响应面那侧给的是同一把尺子的总数钉，它保证"有人把某张
    响应面偷偷换成落盘面"不会被这张表的等式放过去。
    """
    for module in ("audit.py", "agent_trace.py"):
        source = (BACKEND_DIR / "app" / module).read_text(encoding="utf-8")
        assert "redact_secrets" not in source, module
        assert 2 == _call_sites("redact_for_persistence", files=(module,)), module
    # `security.py` 是两枚 redactor 的定义所在，它内部的自递归调用不属于任何作用盘面。
    faces = _app_python_files(exclude_definition=True)
    # 落盘面总共就这四处（audit 2 + agent_trace 2）；多一处 = 有人扩大了切换面。
    assert 4 == _call_sites("redact_for_persistence", files=faces)
    # 响应面：app/ 里 17 处调用一处都不许被换成落盘面 redactor（换一枚登录响应的 access_token
    # 就会被抹掉，客户端当场拿不到票）。
    assert 17 == _call_sites("redact_secrets", files=faces)


# --------------------------------------------------------------------------- #
# SECA-18：三件守卫同生同死（直接调用守卫函数，不借 lifespan）
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "kwargs, expected",
    [
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins="http://localhost:3000"), 1),
        (dict(enterprise_mode=True, jwt_secret="x" * 48, cors_allow_origins="https://kb.example"), 0),
        (dict(enterprise_mode=False, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 0),
        (dict(enterprise_mode=True, jwt_secret=security_startup.DEFAULT_JWT_SECRET,
              cors_allow_origins=""), 2),
        (dict(enterprise_mode=True, jwt_secret="short", cors_allow_origins="*"), 2),
        (dict(enterprise_mode=True, jwt_secret="", cors_allow_origins=""), 2),
    ],
)
def test_the_three_guards_live_or_die_together(kwargs, expected):
    """SECA-18：企业形态下三件守卫同生同死，不允许"只落了 seed 半件"。"""
    violations = security_startup.evaluate_startup_guards(**kwargs)
    assert expected == len(violations), violations


def test_default_config_makes_the_guard_a_total_noop():
    """dev / 测试形态（默认）⇒ 启动守卫整体 no-op，兑现"默认配置零额外启动行为"。"""
    assert security_startup.evaluate_startup_guards(
        enterprise_mode=False,
        jwt_secret=security_startup.DEFAULT_JWT_SECRET,
        cors_allow_origins="",
    ) == []


def test_assert_startup_safe_refuses_under_enterprise_default_and_bools_clean_otherwise():
    """守卫函数与真实 settings 的接线：企业开关 + 默认 secret ⇒ 抛；关 ⇒ 放行。"""
    from app.config import Settings

    with mock.patch("app.config.settings",
                    Settings(security_enterprise_mode=True,
                             jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                             cors_allow_origins="")):
        with pytest.raises(security_startup.SecurityStartupError):
            security_startup.assert_startup_safe()
    with mock.patch("app.config.settings",
                    Settings(security_enterprise_mode=False,
                             jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                             cors_allow_origins="")):
        security_startup.assert_startup_safe()  # 不抛


class StartupGuardLifespanTests(unittest.TestCase):
    """守卫的**唯一执行点**是 `main.py` lifespan 里那一句 `assert_startup_safe()`。

    上面那些直接调用守卫函数的钉子（SECA-18 要求的正是"不依赖 lifespan"）杀不掉"执行点被删"
    这一档：`TestClient(app)` 不进上下文管理器根本不跑 lifespan，于是删掉那一行、函数与全部
    调用者测试都还绿。这里补的正是那一格——真起一次进程。

    同一条 lifespan 里另外两步（identity / llm router 的 warmup）被换成 no-op：它们各有自己的
    契约与 cwd 假设（`warmup_llm_router` 默认开启且按 **当前目录**解析 `config/llm_registry.json`），
    本类的主题只有守卫那一句。打点的位置是 `app.main` 里那两个名字——lifespan 读的就是它们。
    """

    def _client(self):
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        return TestClient(fastapi_app)

    def _guard_only(self):
        return (mock.patch("app.main.warmup_identity_permissions"),
                mock.patch("app.main.warmup_llm_router"))

    def _patched(self, **kwargs):
        from app.config import Settings

        return mock.patch("app.config.settings", Settings(**kwargs))

    def test_enterprise_default_secret_refuses_during_real_startup(self):
        """企业形态 + 出厂默认 secret ⇒ 起进程就抛（fail-fast，不是第一个请求才炸）。

        三件守卫里这两格同时违规，正是 §8.5 "同生同死"在**执行点**上的形状：如果 lifespan
        里那句守卫被删/被包进 try 里静音，这一条就是唯一会红的地方。
        """
        first, second = self._guard_only()
        with first, second, self._patched(security_enterprise_mode=True,
                                          jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                                          cors_allow_origins=""):
            with pytest.raises(security_startup.SecurityStartupError):
                with self._client():
                    pass  # pragma: no cover —— 到不了这里

    def test_a_refused_boot_creates_nothing(self):
        """§8.5 的顺序契约：**先拒坏配置，再谈落盘**（SECA-18 新增那一格）。

        lifespan 现在是"守卫 → 建表 → 两枚 warmup"。把前两步调个个儿，症状是"企业形态 +
        出厂默认 secret 的实例在被拒之前已经往目标库里建了半张凭据表"——进程起不来，库里却
        多出一张运维没同意过的表，正是 `user_store._connect` 那段注释最怕的形状。
        库路径指到本例自己的一枚全新文件上（不是会话那份，别个用例已经把它建过了），
        于是"文件根本不该存在"是一句不会假红的判据。
        """
        import os
        import shutil
        import tempfile

        from app import security_startup

        root = Path(tempfile.mkdtemp(prefix="sec-a-order-"))
        self.addCleanup(shutil.rmtree, root, True)
        fresh_db = root / "data" / "refused-boot.db"
        first, second = self._guard_only()
        with first, second, mock.patch.dict(os.environ,
                                            {"CONVERSATION_DB_PATH": str(fresh_db)}), \
                self._patched(security_enterprise_mode=True,
                              jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                              cors_allow_origins=""):
            with pytest.raises(security_startup.SecurityStartupError):
                with self._client():
                    pass  # pragma: no cover —— 到不了这里
        assert not fresh_db.exists(), "被拒的启动已经在落盘面上建了库 ⇒ 建表排到了守卫之前"

    def test_dev_default_starts_clean_with_the_guard_in_place(self):
        """dev / 测试形态（默认）⇒ 同一条 lifespan 干净启动：守卫在场但不是障碍。

        只钉"企业形态会抛"是不够的：把 `assert_startup_safe()` 换成一句无条件抛的桩，上面
        那条照样绿。这一条把"默认配置零额外启动行为"钉到**真实启动路径**上。
        """
        first, second = self._guard_only()
        with first, second, self._patched(security_enterprise_mode=False,
                                          jwt_secret=security_startup.DEFAULT_JWT_SECRET,
                                          cors_allow_origins=""):
            with self._client() as client:
                assert 401 == client.get("/api/auth/me").status_code

    def test_enterprise_fully_configured_starts_clean(self):
        """企业形态 + ≥32 非默认 secret + 显式 CORS ⇒ 起得来（三守卫都不是"永远拒"）。"""
        first, second = self._guard_only()
        with first, second, self._patched(security_enterprise_mode=True, jwt_secret="x" * 48,
                                          cors_allow_origins="https://kb.example"):
            with self._client() as client:
                assert 401 == client.get("/api/auth/me").status_code


# --------------------------------------------------------------------------- #
# §10 / SEC-A-002 配置半边：.env.example 键集合
# --------------------------------------------------------------------------- #

def test_env_example_never_carries_a_credential_env_var():
    """SEC-A-002 的配置面半边：CREDENTIALS_PASSWORD 是一次性 CLI 变量。

    `.env` 由服务进程加载，把它写进模板等于让明文口令常驻配置面。
    """
    text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
    keys = {line.split("=", 1)[0].strip() for line in text.splitlines()
            if "=" in line and not line.strip().startswith("#")}
    assert not {key for key in keys if "PASSWORD" in key.upper()}, sorted(keys)
    assert "SECURITY_ENTERPRISE_MODE" in keys
    assert "CORS_ALLOW_ORIGINS" in keys
    assert "CREDENTIALS_PASSWORD" not in keys


# --------------------------------------------------------------------------- #
# SECA-20：仓库扫描门（豁免表与命中表按 (文件, 处数) 互等，同 test_llm_egress_guard.py）
# --------------------------------------------------------------------------- #

#: 凭据材料的 native 语法有两种，各开一枚面，谁也替代不了谁。
#:
#: **字面量面**（代码 / 配置 / 前端）：键名词干（`api_key` / `secret` / `token` / `password` /
#: `passwd`，允许 `JWT_SECRET`、`tenant_access_token` 这类前后缀）+ `:` 或 `=` + **成对引号包住、
#: 内部无空白**的 ≥16 字符串。三处细节都是刻意的：
#: ① 键名**不再要求词首 `\b`**——`_` 是词字符，`\bsecret` 在 `JWT_SECRET=` 上永远匹配不到，
#:    那等于把整类 env 形状的泄漏做成隐形（旧门的全部问题都在这里）；
#: ② 值必须是**字面量**：`password = _password_from_env` 取的是变量/调用而不是材料，散文里引用
#:    这条语句也不构成凭据；
#: ③ 注解写法（`jwt_secret: str = "…"`）同样在面上，否则配置默认值那一格就是盲区。
#:
#: **env 面**（无引号 `KEY=value` / `KEY: value` 是 native 语法的那些文件）：字面量面在结构上抓不到
#: 无引号赋值 ⇒ 另开一条 env 面（值仍要 ≥16 且无空白）。它按**语法**分两半（分档逻辑在 `_faces_for`）：
#: 配置档（`.env*` / compose / `.yml/.yaml/.ini/.conf/.toml/.cfg/.properties` / `Dockerfile*`）吃
#: **大小写不敏感**那枚，`scripts/` 吃**大小写敏感**那枚。不对称有实测理由，不是随手：脚本里
#: `name=value` 是 Python 关键字参数与 PowerShell 参数的正常写法，小写化实测会在
#: `scripts/release_smoke.py:310`（`min_token_events=args.min_token_events`）多撞一枚纯误报；配置档
#: 没有这种语法，所以那边零代价、这边要收。而 `app/config.py:8` 的 `case_sensitive=False` 正是
#: "小写键在本项目是活的凭据形状"的证据——只按大写抓会把 `db_password: <真值>` 整档放过。
#: 实测代价（Task 9 修复轮 2 量过、本档分档后复量）：拓宽到配置档全表面**不产生任何新豁免行**（仍
#: 254 文件 / 16 命中文件 / 31 处）。**但别把 0 读成结构性安全**：`.github/workflows/ci.yml` 干净的
#: 耐久理由是 GitHub Actions 把 token 一律写成 `${{ … }}`，而 `$` 不在值字符集里；同文件 `:73` 的
#: `TOKENIZERS_PARALLELISM: "false"` 今天躲过只因为值短于 16 字符——值一长就会命中。也就是说这一档
#: 的**误差方向是误报**（会红、要人判），不是漏报，这是可接受的那一侧。
#: 命名的残余风险（诚实版）：①**代码文件里的无引号赋值**仍不在 env 面射程内（Python/TS 的
#: `password = "…"` 由字面量面抓，无引号形态在那两类语言里不是合法赋值）；②`backend/.env` 今天
#: **真实存在于磁盘**且被 `.gitignore:6` 挡在扫描面之外——最可能装着活凭据的那一枚文件恰好不在这道
#: 门的射程里，这是"交付面扫描"的定义而非漏洞，但写验收文档时不得把它说成"仓内无凭据"。两条都随
#: §18 的第三方扫描器（带 git 历史，另见 §17 L6）一起收口。
#:
#: **材料形状面**：不依赖任何赋值形态的现网密钥形状（`sk-…` / `ghp_…` / `AKIA…` / `eyJ…` /
#: 私钥 PEM 头）——"贴进代码的一段裸密钥"（没有 `key =` 外壳）也红。
#:
#: **范围决策（两档，不是 15 条豁免）。**
#: - `*.md`（交付文档：`docs/**` 与 README）只上**材料形状面**。散文按定义就要引用代码与测试夹具
#:   的字面量（单是 `docs/SECURITY_A_PLAN.md` 就有 32 处合法引用），逐条进豁免表等于把门换成一张
#:   永远补不完的清单，所以赋值形态那两枚面在散文里不作数；但"贴进文档的一段现网密钥"（`sk-…` /
#:   `eyJ…` / PEM 头）照样红。实测交付文档在这一枚上今天 **0 命中** ⇒ 这一档不收豁免、不给未来留
#:   漂移债。**范围要说准**：这一枚关掉的是"现网密钥形状被贴进文档"（provider key / JWT / PEM），
#:   关不掉"文档里写了一条完整赋值形态的口令"（`OPENAI_API_KEY = "glpat-…"` 之外的
#:   `password = "…" ` 这类散文引用与真泄漏在这一档**同形**，不可分）。这条残余一并交 §18 的
#:   带历史扫描器。另一条实操约束：canary 字面量（`sk-CANARY-…`）是**材料形状**，验收文档引用它
#:   时要按 `路径:行号` 指过去，不要把字面量抄进 `docs/**`——那会让门为一枚假凭据红，正是这一档
#:   声称要免掉的那类摩擦。
#: - `.superpowers/**`（SDD 过程件：plan / report / 历轮 baseline 快照）整目录不在面上。理由更强
#:   一档：那里躺着**故意**写下的 canary 字面量（`sk-CANARY-<16位哈希>-not-in-any-message`），还有被
#:   逐字复制进来的 `app/` 源码副本（同一枚已豁免材料会再出现一遍）；它是过程**证据**，按
#:   `.gitignore` 的口径默认不入库、只在终审时精选 `-f`。把豁免表绑在这种目录上更糟：下一轮快照
#:   一入库门就红，而那次红与"有没有真凭据"毫无关系。
#: 命名的残余风险：只在过程件里出现的凭据材料本门够不到——那是 §18 已登记的第三方扫描器
#: （gitleaks，带 git 历史）后续项的职责，SEC-A 明确不引入第三方扫描器、不新增 security job。
_UNSCANNED_PREFIXES = (".superpowers/",)
_LITERAL_FACE = re.compile(
    r"""
    ["']?
    (?:api[_-]?key|secret|token|pass(?:word|wd))
    [\w-]*
    ["']?
    (?:\s*:\s*[A-Za-z0-9_\[\], .|]*)?
    \s*[:=]\s*
    (?P<quote>["'])
    [^"'\\ \t]{16,}
    (?P=quote)
    """,
    re.X | re.I,
)
_ENV_FACE = re.compile(
    r"""
    [A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|APIKEY)[A-Z0-9_]*
    [ \t]*[:=][ \t]*
    ["']?[A-Za-z0-9_.\-/+~]{16,}
    """,
    re.X,
)
_MATERIAL_FACE = re.compile(
    r"sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}"
    r"|eyJ[A-Za-z0-9_\-]{16,}|BEGIN [A-Z ]*PRIVATE KEY"
)
#: 配置文件档专用的大小写不敏感 env 面：INI/TOML/properties 与 compose 的键名没有大小写约定，
#: 只按 `[A-Z0-9_]*` 抓会把 `password: <真值>` / `db_password: <真值>` 整档放过（复评 round-2 的
#: Minor 1：这一半洞在 `.env*`/compose 上同样存在，而 compose 才是 native 无引号语法最重的一档；
#: `app/config.py:8` 的 `case_sensitive=False` 说明小写键在本项目是活的凭据形状，不是假想）。
#: 这一档**只含实际存在的方言**：`makefile`/`procfile` 在 round-2 被剔出名单——Make 的 `:` 是规则
#: 分隔符，实测 `test-secrets: backend/tests/….py` 与 `VAULT_TOKEN_PATH = /var/run/secrets/…` 都会
#: 命中，一旦落进 `(文件→处数)` 表就被永久合法化；仓内既无 Makefile 也无 Procfile，零证据不收。
#: 同理 `Modelfile.*` 留在代码档（实测 0 命中，不为一枚文件加档）。
_ENV_FACE_CI = re.compile(_ENV_FACE.pattern, re.X | re.I)
_CONFIG_SUFFIXES = (".yml", ".yaml", ".ini", ".conf", ".toml", ".cfg", ".properties")
_CONFIG_FILE_NAMES = ("dockerfile", "containerfile")
_ALL_FACES = (_LITERAL_FACE, _ENV_FACE, _MATERIAL_FACE)
_CONFIG_FACES = (_LITERAL_FACE, _ENV_FACE_CI, _MATERIAL_FACE)
_CODE_FACES = (_LITERAL_FACE, _MATERIAL_FACE)
_BINARY_SUFFIXES = {".png", ".webp", ".ico", ".woff", ".woff2", ".pyc"}

#: 豁免表的键是 **(相对路径 → (命中处数, 为什么它不是凭据材料))**，不是 `文件:行号`。
#: 行号会洗白这道门：①已经豁免的那一行上再放第二枚真凭据 = 同一个键 = 静音；②行号在上方
#: 任何一次编辑后整体漂移，表跟着漂就等于门废了。处数是**计数**，多一枚必红、少一枚（死行）也红
#: ——与 `test_llm_egress_guard.py` 的 `EXEMPTIONS` 同一形状。
#: 每一行的"为什么"必须落到**这一处材料本身**（出厂默认 / 审计枚举 token / env 变量名 / 测试诱饵 /
#: localStorage 键名 / 本地脚本自用的一次性夹具），只写"这是测试文件"的那张表就是洗白过的门。
EXEMPTIONS: dict[str, tuple[int, str]] = {
    # 出厂默认占位符：值就是 `security_startup.DEFAULT_JWT_SECRET` 那一枚，企业形态下启动守卫
    # 正因为"等于它"才拒启动（§10 明写默认值要留在模板里）。真凭据不许出现在这一格。
    "backend/.env.example": (1, "JWT_SECRET 的出厂默认占位符，与守卫用来识别「忘了改」的那枚常量同源"),
    # §9.1 审计面的枚举 token（`password_capacity` / `password_policy_rejected`）：那是给机器读的
    # 状态名，值本身不对应任何密钥材料。
    "backend/app/auth.py": (2, "审计 detail 的枚举 token 常量，展示面另有中文文案（§9.1 两栏）"),
    # CLI 读的**变量名**（`CREDENTIALS_PASSWORD`）：值是指针，明文口令由运维在一次性调用时注入。
    "backend/app/cli.py": (1, "一次性 CLI 的 env 变量名字面量，不是口令值（SEC-A-002）"),
    # 同 `.env.example`：守卫识别"默认没换"的比对基准，抄错一位就会把生产误判成安全。
    "backend/app/config.py": (1, "Settings.jwt_secret 的出厂默认值，与启动守卫的比对基准同源"),
    "backend/app/security_startup.py": (1, "DEFAULT_JWT_SECRET 常量本体，三守卫靠它识别「忘了改」"),
    # 以下三枚是同族：SEC-A 契约用例各配一枚 ≥32 字节的假 JWT secret，理由见 `sec_a_fixtures`
    # 的 `LongJwtSecretMixin`——换掉它会把套件警告计数挪走。值不指向任何环境，签名验不过。
    "backend/tests/test_authentication_leg_contract.py": (
        1, "测试自带的假 JWT secret 夹具（只为躲过 PyJWT 短密钥警告），不指向任何环境"),
    "backend/tests/test_feishu_identity_contract.py": (
        1, "测试内构造的假 feishu app-secret 声明值，只为占位一个 claim 面"),
    "backend/tests/test_password_lifecycle_contract.py": (
        2, "假 JWT secret 夹具 + 一枚审计枚举 token（`password_changed`），都不是凭据材料"),
    # V2.3 出口守卫的诱饵面：D6 要证明"provider 之外的 key 绝不出网"，手里就得有可识别的 key 值。
    # 计数 10 覆盖 `sk-*` canary 与 `api_key="…"` 诱饵两种形态；多一枚就得重新过评审。
    "backend/tests/test_model_router_v23_contract.py": (
        10, "出口/路由契约的诱饵 key 与 canary 字面量，断言的正是它们绝不外发、绝不落盘"),
    "backend/tests/test_typesafe_api_runtime.py": (
        1, "断言「这枚 key 绝不能被流出去」的诱饵值，是测试自己的诱饵"),
    "backend/tests/test_typesafe_judgments.py": (
        1, "判定层「绝 persisted」的诱饵 key，测试用假值"),
    # 本文件：两枚"响应面 vs 落盘面"的字面量样本 + 两枚假 JWT 头（无签名段，验不过）。
    # 扫描门自己的正/反例夹具按拼接构造，因此不在此表内计数。
    "backend/tests/test_secret_hygiene_contract.py": (
        4, "两域对比的字面量样本与两枚假 JWT 头（`eyJ…` 无签名段），全为构造值"),
    # 前端存的是 localStorage 的**键名**（票值运行时才存在）：两处同一个键名常量。
    "frontend/src/lib/api.ts": (1, "localStorage 键名字面量，值是运行时才签发的 token"),
    "frontend/src/lib/conversations.ts": (1, "同上：会话面复用同一枚 localStorage 键名"),
    # 本地集成脚本：服务由脚本自己起、口令由脚本自己写死，任何环境都不复用这一枚。
    "scripts/conversation_p1_integration.py": (
        1, "本地一次性集成夹具的假 secret（脚本自己起的服务），不被任何环境复用"),
    # deploy.ps1 要检测"`.env` 里仍是出厂默认"才生成随机值，两处（匹配 + 替换模式）都必须逐字
    # 引用那一枚默认值；替换写进去的是随机数，不是这里的字面量。
    "scripts/deploy.ps1": (2, "检测/替换出厂默认 JWT_SECRET 的正则字面量，与守卫比对基准同源"),
}


def _faces_for(relative: str) -> tuple[re.Pattern[str], ...]:
    """每类文件上哪几枚面。

    三档，按**语法**分而不是按目录分：

    1. `*.md`（交付文档）→ 只上材料形状面。散文按定义就要引用代码与夹具的字面量，赋值形态那两枚
       面在散文里不作数（材料面仍作数：贴进文档的一段现网 `sk-…` / `eyJ…` / PEM 照样红）。
    2. **配置档**：`.env*`、compose、`.yml/.yaml/.ini/.conf/.toml/.cfg/.properties`、`Dockerfile*`/
       `Containerfile*` → 字面量 + **大小写不敏感** env + 材料。这一档的 native 语法就是无引号
       `KEY=value` / `KEY: value`，而键名大小写没有约定。
    3. `scripts/`（脚本源码）→ 字面量 + **大小写敏感** env + 材料。**不对称是有理由的**：脚本里
       `name=value` 是 Python 关键字参数与 PowerShell 参数的正常写法，实测小写化会在
       `scripts/release_smoke.py:310`（`min_token_events=args.min_token_events`）多撞一枚纯误报，
       而那正是"大写名=value 遍地噪声"的成因。配置档没有这种语法，所以那边不收代价、这边要收。
    4. 其余（代码 / 前端）→ 字面量 + 材料两枚。

    分支顺序是**先配置档、后 `scripts/`**，所以 `scripts/ci.yml` 拿配置档那枚，不会比
    `deploy/ci.yml` 少一面。
    """
    name = PurePosixPath(relative).name.lower()
    if relative.endswith(".md"):
        return (_MATERIAL_FACE,)
    if (relative.endswith(_CONFIG_SUFFIXES) or name.startswith(_CONFIG_FILE_NAMES)
            or name.startswith(".env") or "compose" in name):
        return _CONFIG_FACES
    if relative.startswith("scripts/"):
        return _ALL_FACES
    return _CODE_FACES


def _occurrence_lines(text: str, *, relative: str) -> list[int]:
    """去重叠后的命中行号（行号只给人读，不进豁免键）。

    同一枚泄漏被两枚面各抓一次 ⇒ 区间重叠 ⇒ 合并成**一处**，所以"处数"数的是泄漏而不是正则
    匹配次数；同一行上的两处不重叠泄漏 ⇒ 两处，豁免表就会因为多一枚而红。
    """
    spans: list[list[int]] = []
    for face in _faces_for(relative):
        spans += [[match.start(), match.end()] for match in face.finditer(text)]
    spans.sort()
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [text[:start].count("\n") + 1 for start, _end in merged]


def _in_scan_scope(relative: str) -> bool:
    """范围决策落地的地方：只有 SDD 过程件整目录不在面上（markdown 仍上材料形状面，见上面那段）。"""
    return not relative.startswith(_UNSCANNED_PREFIXES)


def _hit_counts(names: Iterable[str], *, root: Path = REPO_ROOT) -> dict[str, int]:
    """文件集（相对 `root` 的 posix 路径）→ 命中处数。扫描逻辑只有这一份实现。"""
    counts: dict[str, int] = {}
    for relative in names:
        path = root / relative
        if (not _in_scan_scope(relative) or not path.is_file()
                or path.suffix in _BINARY_SUFFIXES):
            continue
        found = len(_occurrence_lines(path.read_text(encoding="utf-8", errors="ignore"),
                                      relative=relative))
        if found:
            counts[relative] = found
    return counts


def _delivery_surface_names(*, root: Path = REPO_ROOT) -> list[str]:
    """扫描面 = 会进仓库的那一面：tracked（`--cached`）∪ 未被忽略的 untracked（`--others`）。

    只读 `git ls-files`（cached）的话，SEC-A 的新文件在 `git add` 之前不在面上 ⇒ 门在提交前绿、
    提交后红（reviewer 量到的 3→7 就是这个）。`-c -o --exclude-standard` 让它扫的是**同一批文件**，
    与索引状态无关；`--exclude-standard` 是必须的：不带它 `--others` 会把 `.gitignore` 挡掉的
    东西（`node_modules/`、`backend/data/`）也列进来，那既是噪声也不是交付面。忽略规则由 git
    自己解释，本门不另起一套。
    """
    listing = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=root, capture_output=True, check=True)
    return sorted({raw.decode("utf-8", "replace") for raw in listing.stdout.split(b"\0") if raw})


def _gate_offenders(measured: Mapping[str, int]) -> list[str]:
    """命中集与豁免表对账，三个方向都算违规：未豁免的文件、处数不等、表里的死行。

    失败信息只报**路径与处数**：把命中片段抄进断言消息等于在 CI 日志里再复制一次凭据。
    """
    offenders: list[str] = []
    for relative, count in sorted(measured.items()):
        row = EXEMPTIONS.get(relative)
        if row is None:
            offenders.append(f"{relative} ×{count} 未豁免")
        elif count != row[0]:
            offenders.append(f"{relative} ×{count} ≠ 豁免表 {row[0]} 处")
    offenders += [f"{relative} 是豁免表死行（当前 0 命中）"
                  for relative in sorted(set(EXEMPTIONS) - set(measured))]
    return offenders


def test_repository_tracked_files_hold_no_credential_material():
    """SECA-20：扫描是普通 pytest 用例，本地与既有 CI job 同一道门。"""
    offenders = _gate_offenders(_hit_counts(_delivery_surface_names()))
    assert [] == offenders, (
        "交付面出现凭据形态的字面量：先确认它不是真凭据，再按 (文件, 处数) 过评审进豁免表；"
        + "; ".join(offenders)
    )


def test_the_exemption_table_matches_the_hit_set():
    """反向闸：豁免表与命中集互等——多一档（死行）、少一档、处数漂一位，都立刻红。"""
    assert {relative: row[0] for relative, row in EXEMPTIONS.items()} == _hit_counts(
        _delivery_surface_names())


def test_every_exemption_states_why_it_is_not_material():
    """豁免表的每一行都得有"为什么不是材料"，且指向的文件必须真实在场。

    一张只写"测试文件"的表就是洗白过的门：判据是每一行的理由**写得出来**（不空、短不到能
    复述成一句标签、也不止是在重复文件名），文件本身存在（死文件行由互等那条兜，这里兜的是
    空理由与养闲条目）。
    """
    for relative, (count, why) in EXEMPTIONS.items():
        assert count >= 1, relative
        text = why.strip()
        assert len(text) >= 16, f"{relative} 的理由不够具体：{text!r}"
        assert Path(PurePosixPath(relative).name).stem not in text, (
            f"{relative} 的理由只是在重复文件名")
        assert (REPO_ROOT / relative).is_file(), f"{relative} 豁免了不存在的文件"


def test_a_planted_credential_turns_the_gate_red(tmp_path):
    """SECA-20 的证伪：门必须真的能红。往"tracked 样子"的文件里植一枚假凭据 ⇒ 未豁免 ⇒ 红。

    只在 tmp 里落盘，不碰仓库索引与工作树；被植的字面量按**拼接**构造，所以本文件自己
    不会因为这条测试而多出一处命中（那会把豁免表的计数拖成移动靶）。
    """
    planted_relative = "backend/app/planted_secret_holder.py"
    planted = tmp_path / planted_relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text(f"{_ENV_KEY_NAME}=\"{_PLANTED_VALUE}\"\n", encoding="utf-8")

    measured = _hit_counts([planted_relative], root=tmp_path)
    assert 1 == measured[planted_relative], "植入的凭据形态没被抓到 ⇒ 面本身就是瞎的"
    offenders = [item for item in _gate_offenders(measured) if item.startswith(planted_relative)]
    assert offenders, "植进去的凭据没有让门红"


def test_a_second_credential_on_an_exempt_line_is_not_silenced(tmp_path):
    """豁免键含**处数**而不是行号 ⇒ 已豁免那一行上再放第二枚凭据，处数 +1 ⇒ 门红。

    这条是 Fix 的靶心：按 `文件:行` 建键的门会把它静音（同一行 = 同一个键）。这里取表里真实
    存在的一行命中（`security_startup.py` 的默认常量），在同一行尾部再植一枚，然后按同一份
    扫描实现读数。
    """
    relative = "backend/app/security_startup.py"
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    exempt_line_number = _occurrence_lines(source, relative=relative)[0]
    lines = source.splitlines(keepends=True)
    lines[exempt_line_number - 1] = (
        lines[exempt_line_number - 1].rstrip("\r\n")
        + f"  # {_ENV_KEY_NAME}=\"{_SECOND_PLANTED_VALUE}\"\n"
    )
    planted = tmp_path / relative
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("".join(lines), encoding="utf-8")

    measured = _hit_counts([relative], root=tmp_path)
    assert EXEMPTIONS[relative][0] + 1 == measured[relative], (
        "第二枚凭据没有让处数变化 ⇒ 键退化成了行号，豁免会吞掉同一行上的任何新泄漏")
    offenders = [item for item in _gate_offenders(measured) if item.startswith(relative)]
    assert offenders, "处数已经漂了却仍然对账通过 ⇒ 豁免把第二枚吞了"


def test_unquoted_config_file_assignments_are_on_the_face(tmp_path):
    """配置文件档的**无引号**赋值必须在面上（Task 9 修复轮 2：评审量的 NB-1 与其小写一半）。

    `password: <真值>` 这种 native 形状既没有引号（字面量面抓不到）、又不在 env 面射程内时，整档
    致盲。四种形状各植一枚（YAML 大写键 / INI 小写键 / Dockerfile `ENV` / compose 小写键），全部
    只在 tmp 里落盘，不碰仓库索引与工作树。
    """
    cases = {
        ".github/workflows/planted-ci.yml": f"{_ENV_KEY_NAME}: {_PLANTED_VALUE}\n",
        "backend/deploy/planted.ini": f"{_LOWER_KEY_NAME} = {_PLANTED_VALUE}\n",
        "backend/Dockerfile.planted": f"ENV {_ENV_KEY_NAME}={_PLANTED_VALUE}\n",
        "docker-compose.planted.yml": f"{_LOWER_DB_KEY_NAME}: {_PLANTED_VALUE}\n",
    }
    assert set(_CODE_FACES) < set(_CONFIG_FACES), (
        "配置档不是代码档的超集 ⇒ 有人把大小写不敏感那枚挪走时代码档会被顺带弄瞎")
    assert _CONFIG_FACES == _faces_for("backend/deploy/planted.ini"), (
        "配置文件档没有拿到大小写不敏感的 env 面")
    assert _CONFIG_FACES == _faces_for("scripts/planted-ci.yml"), (
        "`scripts/` 下的配置文件走到了脚本档 ⇒ 同一形状在两个目录下覆盖面不同")
    for relative, body in cases.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        assert 1 == len(_occurrence_lines(body, relative=relative)), (
            f"{relative} 上的无引号赋值没被抓到 ⇒ 这一档仍是瞎的")
    measured = _hit_counts(list(cases), root=tmp_path)
    assert {rel: 1 for rel in cases} == {rel: measured.get(rel, 0) for rel in cases}
    offenders = [item for item in _gate_offenders(measured)
                 for rel in cases if item.startswith(rel)]
    assert len(cases) == len(offenders), "配置文件档植进去的凭据没有让门红"


def test_scripts_keep_the_case_sensitive_env_face_and_why():
    """`scripts/` 那半的**不对称**是钉住的，不是漏的（复评 round-2 Minor 1 的另一半）。

    配置档吃大小写不敏感、脚本吃大小写敏感，理由必须落在可执行的形状上而不是只写在注释里：脚本里
    `name=value` 是合法的关键字参数，把它也算成凭据会撞出纯误报（真实例子取自本仓
    `scripts/release_smoke.py:310`）。所以这一枚同时钉住"真凭据在脚本里仍红"与"关键字参数不红"。
    """
    real_leak = f"{_ENV_KEY_NAME}={_PLANTED_VALUE}\n"          # 大写键：脚本档也抓
    keyword_arg = f"    min_token_events=args.min_token_events\n"  # 小写 kwarg：不该抓
    assert 1 == len(_occurrence_lines(real_leak, relative="scripts/deploy.ps1")), (
        "脚本档的大写 env 赋值必须仍在面上")
    assert 0 == len(_occurrence_lines(keyword_arg, relative="scripts/release_smoke.py")), (
        "关键字参数被当成凭据 ⇒ 这一档的大小写敏感限定就是误报源，别把它并进配置档")
    assert 1 == len(_occurrence_lines(keyword_arg, relative="deploy/app.ini")), (
        "同样的小写形状在配置档必须红，否则两档其实是同一档")


# 植入用的字面量按拼接构造：本文件在扫描面上，任何"键 + = + 引号 + ≥16 无空白值"的写法都会
# 让豁免表的计数变成移动靶。
_ENV_KEY_NAME = "JWT_" + "SECRET"
_LOWER_KEY_NAME = "user_" + "password"
_LOWER_DB_KEY_NAME = "db_" + "password"
_PLANTED_VALUE = "planted-" + "credential-material-32-bytes"
_SECOND_PLANTED_VALUE = "second-" + "credential-on-exempt-line"


# --------------------------------------------------------------------------- #
# 真实登录两向边界 + Task 7 移交的 root_path 无回显守卫 + 可用性事件归属
# --------------------------------------------------------------------------- #

import sec_a_fixtures  # noqa: E402
from sec_a_seed import ensure_demo_credentials  # noqa: E402


class _LoginHarness(sec_a_fixtures.LongJwtSecretMixin,
                    sec_a_fixtures.AuditToTempFileMixin, unittest.TestCase):
    """一份临时库 + 临时审计 + 够长 JWT secret + 真 app：真实登录用它拿真 token，而不是编一个。

    `SECRET` 是 ≥32 字节：默认 dev secret（31B）会让每次签发/校验各多一句
    `InsecureKeyLengthWarning`，那会把整套件的警告基线挪走——套件警告数不变是本仓的回归信号。
    """

    SECRET = ("sec-a-hygiene-login-harness-jwt" "-secret-key-40b")  # ≥32B；拆两段免被扫描门当凭据

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        super().setUp()
        sec_a_fixtures.fresh_db(self)
        ensure_demo_credentials()
        self.addCleanup(lambda: __import__("app.login_throttle", fromlist=["pre_hash_throttle"])
                        .pre_hash_throttle.reset())
        self.client = TestClient(fastapi_app)

    def _login(self, username: str, password: str):
        return self.client.post("/api/auth/login",
                                json={"username": username, "password": password})


class LoginResponseVsPersistenceBoundaryTests(_LoginHarness):
    def test_real_login_token_is_usable_yet_erased_in_a_persistence_row(self):
        """唯一能抓"过宽红actor"的证法：同一枚真 token，响应面能用、落盘面被抹。"""
        resp = self._login("admin", "admin123")
        self.assertEqual(200, resp.status_code, resp.text)
        body = resp.json()
        token = body["access_token"]
        # 响应面：token 不但在，而且**可用**（拿它打 /api/auth/me ⇒ 200）。红actor 若罩到响应面，
        # 这一步就会 401——这是"登录还能不能用"的真实回归哨兵。
        self.assertIsInstance(token, str)
        self.assertNotEqual(security.REDACTED, token)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(200, me.status_code, me.text)
        self.assertEqual("admin", me.json()["username"])

        # 落盘面（真实持久化面 agent_trace 的存 + 取）：同一枚值必须被抹成占位符。
        trace_file = self.tmp_trace()
        with mock.patch.object(agent_trace, "TRACE_PATH", trace_file):
            agent_trace.save_trace({"trace_id": "t-1", "access_token": token,
                                    "input_tokens": 5})
            restored = agent_trace.get_trace("t-1")
        self.assertEqual(security.REDACTED, restored["access_token"])
        # 反向：同一张 trace 里的观测键不误伤。
        self.assertEqual(5, restored["input_tokens"])
        # 明文 token 绝不落到持久化文件里（真实文件扫描）。
        self.assertNotIn(token, trace_file.read_text(encoding="utf-8"))

    def tmp_trace(self) -> Path:
        import tempfile

        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return Path(holder.name) / "traces.jsonl"

    def test_historical_audit_row_with_token_key_is_erased_on_read(self):
        """审计**读面** re-redaction 的目的（持久化域上线前写下的历史行也不能从 admin API 漏出）。

        同时钉一条 §9.3 的硬约束：**黑名单只匹配 dict 键名、不嗅探值内容**——一枚裸 JWT 若只是
        某个非敏感键（如 `detail`）的值，它不会被"因为长得像 token"而误抹；会被抹的是①命中键名
        的 `access_token`，②命中**形态**的 `Bearer ...`。这把"过宽红actor 去嗅值"的形状也挡住了。
        """
        bare = "eyJhbGciOiJIUzI1NiJ9.historical.sig"
        bearer = "Bearer abcdef.ghijkl.mnopqr"
        row = {"timestamp": "2020-01-01T00:00:00+00:00", "username": "admin",
               "role": "ADMIN", "action": "LOGIN", "status": "SUCCESS",
               "access_token": bare, "detail": bearer}
        self.audit_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        events = audit.recent_events(limit=5)
        self.assertEqual(1, len(events))
        self.assertEqual(security.REDACTED, events[0]["access_token"])   # 键名命中 ⇒ 抹
        self.assertIn("Bearer [REDACTED]", events[0]["detail"])          # 形态命中 ⇒ 抹
        self.assertNotIn(bare, json.dumps(events, ensure_ascii=False))


class RootPathNoEchoGuardTests(unittest.TestCase):
    """Task 7 移交的 P0：no-echo 校验处理器必须比"路由真正使用的那条路径"，不是 url.path。"""

    LEAK = "current-password-value-LEAKME-9182"

    async def _call(self, path: str, root_path: str):
        from starlette.requests import Request

        from app.main import auth_validation_error_handler
        from fastapi.exceptions import RequestValidationError

        scope = {"type": "http", "method": "POST", "path": path, "root_path": root_path,
                 "headers": [], "query_string": b"", "scheme": "http", "server": ("t", 80)}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive)
        errors = [{"type": "missing", "loc": ["body", "new_password"],
                   "msg": "Field required", "input": self.LEAK}]
        exc = RequestValidationError(errors)
        # 自我校验这条钉是不是真在测分歧：url.path（旧的比较对象）在带前缀时与 route_path 不同。
        if root_path:
            from starlette.routing import get_route_path
            self.assertNotEqual(request.url.path, get_route_path(request.scope))
        response = await auth_validation_error_handler(request, exc)
        return response

    def _body(self, response) -> str:
        return response.body.decode("utf-8")

    def test_change_leg_stays_no_echo_under_nonempty_root_path(self):
        # 带 root_path 前缀时，旧写法（比 url.path）会漏过脱敏、回落默认处理器而回显口令。
        resp = asyncio.run(self._call("/gw/api/auth/password/change", "/gw"))
        self.assertEqual(422, resp.status_code)
        self.assertNotIn(self.LEAK, self._body(resp))
        self.assertIn("请求参数不合法", self._body(resp))

    def test_reset_leg_stays_no_echo_under_nonempty_root_path(self):
        resp = asyncio.run(self._call("/gw/api/admin/users/x/password/reset", "/gw"))
        self.assertEqual(422, resp.status_code)
        self.assertNotIn(self.LEAK, self._body(resp))

    def test_change_leg_no_echo_still_holds_without_root_path(self):
        resp = asyncio.run(self._call("/api/auth/password/change", ""))
        self.assertEqual(422, resp.status_code)
        self.assertNotIn(self.LEAK, self._body(resp))

    def test_login_leg_default_validation_payload_is_unchanged(self):
        """反向钉：/api/auth/login **不在**无回显白名单里 ⇒ 仍走 FastAPI 默认处理器、结构不变。"""
        resp = asyncio.run(self._call("/gw/api/auth/login", "/gw"))
        self.assertEqual(422, resp.status_code)
        # 默认处理器的载荷是 `{"detail":[{...,"loc","input"}]}`，仍回显 input（既有行为，SEC-A-006 不动）。
        self.assertIn(self.LEAK, self._body(resp))
        self.assertNotIn("请求参数不合法", self._body(resp))


class AvailabilityEventAttributionTests(unittest.TestCase):
    """helper 层：`_auth_availability_denial` 把 action 透传给唯一的 writer，detail 值域不动。

    这一层**只**证明"传了就写对"；它在 call site 把 `action="PASSWORD"` 删掉时照样绿（用例是
    直接调 helper 的）。路由层的归属钉子在下面的 `PasswordLegActionAttributionTests`。
    """

    def test_login_leg_capacity_denial_is_still_a_login_event(self):
        from app import auth

        with mock.patch("app.main.record_login_event") as rec:
            from app.main import _auth_availability_denial

            _auth_availability_denial("admin", PasswordCapacityError("x"))
        self.assertEqual("LOGIN", rec.call_args.kwargs["action"])
        self.assertEqual(auth.AUDIT_PASSWORD_CAPACITY, rec.call_args.kwargs["detail"])

    def test_password_leg_capacity_denial_is_labelled_password_not_login(self):
        with mock.patch("app.main.record_login_event") as rec:
            from app.main import _auth_availability_denial

            _auth_availability_denial("admin", PasswordCapacityError("x"), action="PASSWORD")
        self.assertEqual("PASSWORD", rec.call_args.kwargs["action"])

    def test_record_login_event_threads_action_into_the_single_writer(self):
        from app import auth

        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(username="admin",
                                    detail=auth.AUDIT_PASSWORD_CAPACITY, action="PASSWORD")
        record.assert_called_once_with(username="admin", role="UNKNOWN", action="PASSWORD",
                                       status="DENIED", detail="password_capacity")
        # 默认仍是 LOGIN（既有冻结形状不动）。
        with mock.patch.object(auth, "_record_event") as record:
            auth.record_login_event(username="ghost", detail=auth.AUDIT_INVALID_CREDENTIALS)
        self.assertEqual("LOGIN", record.call_args.kwargs["action"])


class PasswordLegActionAttributionTests(_LoginHarness):
    """路由归属不变量：**一条路由上的事件只属于一种 action**，归属由路由决定而不是 helper 默认值。

    - `/api/auth/login` 的每一格拒绝 ⇒ `LOGIN`；
    - `/api/auth/password/change` 的每一格拒绝（策略 422 / 可用性 429·503 / 旧口令 401）⇒ `PASSWORD`。

    改密腿的旧口令校验与登录腿共用同一个判定与同一把计数器（§7.1），但**事件归属**跟着路由走：
    一条腿里三格拒登记成 `PASSWORD`、一格登记成 `LOGIN`，运维面就再也分不出"有人在爆破改密接口"
    与"有人在爆破登录接口"。判据必须逐腿打真路由——直接调 helper 时删掉 call site 的
    `action="PASSWORD"`，helper 层钉子全绿（那正是上一类测不到的那一格）。
    """

    CHANGE_PATH = "/api/auth/password/change"

    def _admin_headers(self) -> dict[str, str]:
        token = self._login("admin", "admin123").json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def _change(self, headers: dict[str, str], *, current: str, new: str):
        return self.client.post(self.CHANGE_PATH,
                                json={"current_password": current, "new_password": new},
                                headers=headers)

    def _last_event(self) -> dict:
        events = self.events()
        self.assertTrue(events, "这一腿没写下任何审计事件")
        return events[-1]

    def test_wrong_current_password_on_the_change_route_is_a_password_event(self):
        """401 那一格：旧口令错发生在改密路由上 ⇒ PASSWORD，不是 LOGIN。"""
        headers = self._admin_headers()
        response = self._change(headers, current="not-my-password 123", new="a-brand-new-pw 123456")
        self.assertEqual(401, response.status_code, response.text)
        event = self._last_event()
        self.assertEqual("invalid_credentials", event["detail"])
        self.assertEqual("PASSWORD", event["action"],
                         "同一条路由上 503/429 记 PASSWORD、401 记 LOGIN = 归属劈叉")

    def test_capacity_denial_on_the_change_route_is_a_password_event(self):
        """503 那一格（第一跳撞容量闸）：翻译点在路由上，action 由路由给。"""
        headers = self._admin_headers()
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            response = self._change(headers, current="admin123", new="a-brand-new-pw 123456")
        self.assertEqual(503, response.status_code, response.text)
        event = self._last_event()
        self.assertEqual("password_capacity", event["detail"])
        self.assertEqual("PASSWORD", event["action"])

    def test_throttle_denial_on_the_change_route_is_a_password_event(self):
        """429 那一格：桶耗尽后由 `_auth_availability_denial` 翻译，归属同样在路由上。"""
        from app import login_throttle

        headers = self._admin_headers()
        bucket = login_throttle.PreHashThrottle(window_seconds=60, max_attempts=2)
        with mock.patch.object(login_throttle, "pre_hash_throttle", bucket):
            for _ in range(2):
                self.assertEqual(401, self._change(headers, current="wrong-old-pw 123",
                                                   new="a-brand-new-pw 123456").status_code)
            throttled = self._change(headers, current="wrong-old-pw 123",
                                     new="a-brand-new-pw 123456")
        self.assertEqual(429, throttled.status_code, throttled.text)
        event = self._last_event()
        self.assertEqual("login_throttled", event["detail"])
        self.assertEqual("PASSWORD", event["action"])

    def test_policy_denial_on_the_change_route_stays_a_password_event(self):
        """422 那一格（Task 7 就记 PASSWORD）：它是这条不变量的另一头，缺席就说明归属被改过。"""
        headers = self._admin_headers()
        response = self._change(headers, current="admin123", new="abc")
        self.assertEqual(422, response.status_code, response.text)
        event = self._last_event()
        self.assertEqual("password_policy_rejected", event["detail"])
        self.assertEqual("PASSWORD", event["action"])

    def test_the_login_route_keeps_every_denial_a_login_event(self):
        """反向：登录腿一格都不改 ⇒ 归属不变量不是"把 PASSWORD 铺开"，而是按路由分。"""
        self.assertEqual(401, self._login("admin", "not-my-password 123").status_code)
        self.assertEqual(("LOGIN", "invalid_credentials"),
                         (self._last_event()["action"], self._last_event()["detail"]))
        with mock.patch.object(credentials, "_SLOTS", threading.BoundedSemaphore(0)):
            self.assertEqual(503, self._login("admin", "admin123").status_code)
        self.assertEqual(("LOGIN", "password_capacity"),
                         (self._last_event()["action"], self._last_event()["detail"]))
