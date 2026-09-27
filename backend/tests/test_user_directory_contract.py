"""身份声明层的契约（规格 §6.4 / SEC-A-010 / SECA-07 / SECA-23）。

这些用例判的不是"文件读得出来"，而是一件更窄的事：**身份文件在结构上就没有地方放凭据**。
所以重心全在拒收面上——敏感键黑名单、摘要形态、重名冲突、以及"报错面不回显取值"。
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app import config as config_module  # noqa: E402
from app import directory  # noqa: E402
from app import knowledge_os  # noqa: E402
from app.auth import CurrentUser  # noqa: E402
from app.config import Settings  # noqa: E402
from app.directory import UserIdentity  # noqa: E402

#: 出厂身份文件的**绝对**落点。测试一律走这一份，而不是"当前工作目录下的 config/"：
#: 全套件按两种 cwd 跑（`backend/` 与仓库根），相对路径口径只属于生产形态（镜像 WORKDIR=backend）。
SHIPPED_ENTERPRISE = BACKEND_DIR / "config" / "users.json"
SHIPPED_DEMO = BACKEND_DIR / "config" / "users.demo.json"

#: 一枚哨兵：出现在任何异常消息里就说明报错面回显了文件内容。它比最长字段还长，
#: 所以"合法取值"这条路走不通它，只能从校验器的报错文本里出来。
SENTINEL = "hunter2-SENTINEL-please-never-echo-this-string-is-longer-than-sixty-four"


def _record(username: str, **overrides: Any) -> dict:
    data: dict = {"username": username, "display_name": username, "role": "USER"}
    data.update(overrides)
    return data


def _write(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps({"identities": records}, ensure_ascii=False), encoding="utf-8")
    return path


class _IdentityFiles(unittest.TestCase):
    """每例一份临时身份文件对，两个模块级路径常量在用例期间被换掉。

    换常量而不是换 cwd：路径常量是本模块唯一的落点出口，换它验的就是真实读路径；换 cwd 会让
    同一进程里其它按相对路径解析的东西（会话库、模型注册表、审计文件）跟着漂。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.enterprise = _write(
            self.root / "users.json",
            [{"username": "admin", "display_name": "管理员", "role": "ADMIN"}],
        )
        self.demo = _write(
            self.root / "users.demo.json",
            [{"username": "viewer", "display_name": "只读", "role": "VIEWER"}],
        )
        self._saved = (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE)
        directory.ENTERPRISE_IDENTITIES_FILE = self.enterprise
        directory.DEMO_IDENTITIES_FILE = self.demo
        directory.reset_cache()
        self.addCleanup(directory.reset_cache)

    def tearDown(self):
        (directory.ENTERPRISE_IDENTITIES_FILE, directory.DEMO_IDENTITIES_FILE) = self._saved
        self._tmp.cleanup()

    def _load(self, *, include_demo: bool):
        return directory.load_identities(include_demo=include_demo)

    def _identities_at(self, *, enterprise_mode: bool):
        with mock.patch.object(
                config_module.settings, "security_enterprise_mode", enterprise_mode):
            return dict(directory.identities())


class IdentityFileTests(_IdentityFiles):
    """SECA-07 / SECA-23：身份文件是**结构上**无口令，不是"约定不写"。"""

    def test_enterprise_mode_does_not_read_the_demo_file_at_all(self):
        self.assertEqual({"admin", "viewer"}, set(self._load(include_demo=True)))
        self.assertEqual({"admin"}, set(self._load(include_demo=False)))

    def test_a_credential_shaped_key_fails_startup_in_either_file(self):
        for key in ("password", "password_hash", "hash", "secret", "token", "api_key"):
            with self.subTest(key=key):
                _write(self.demo, [{"username": "viewer", "display_name": "只读",
                                    "role": "VIEWER", key: "x"}])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=True)
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "password": "hunter2"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_a_legacy_digest_value_is_rejected_even_under_an_allowed_key(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "a" * 40,
                                 "role": "ADMIN"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_unknown_extra_fields_are_rejected_not_ignored(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "is_superuser": True}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_duplicate_username_across_files_fails_instead_of_letting_demo_override(self):
        """M18 的目标形态：`{**enterprise, **demo}` 必须被这条挡下。"""
        _write(self.demo, [{"username": "admin", "display_name": "假冒管理员", "role": "VIEWER"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_duplicate_feishu_open_id_across_files_fails(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "feishu_open_id": "ou_shared"}])
        _write(self.demo, [{"username": "viewer", "display_name": "只读",
                           "role": "VIEWER", "feishu_open_id": "ou_shared"}])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)

    def test_disabled_is_a_first_class_identity_flag(self):
        _write(self.enterprise, [{"username": "admin", "display_name": "管理员",
                                 "role": "ADMIN", "enabled": False}])
        self.assertFalse(self._load(include_demo=False)["admin"].enabled)

    def test_default_is_enabled(self):
        self.assertTrue(self._load(include_demo=False)["admin"].enabled)

    def test_missing_enterprise_file_is_a_hard_failure_not_an_empty_directory(self):
        self.enterprise.unlink()
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)


class CredentialShapeRejectionTests(_IdentityFiles):
    """黑名单键 + 摘要形态：两重都要有，因为 `extra="forbid"` 只看得见键名。"""

    def test_a_sixty_four_hex_digest_is_rejected_under_every_string_field(self):
        for field in ("username", "display_name", "role", "feishu_open_id"):
            with self.subTest(field=field):
                record = _record("admin")
                record[field] = "d" * 64
                _write(self.enterprise, [record])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_uppercase_digests_and_other_digest_lengths_are_rejected_too(self):
        # 摘要家族不止 SHA-256（SHA-1=40、SHA-384=96），而从别处粘过来常带大写或留首尾空白。
        for value in ("A" * 64, "b" * 40, "c" * 96, f"  {'d' * 64}  "):
            with self.subTest(trimmed=len(value.strip())):
                _write(self.enterprise, [_record("admin", display_name=value)])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_a_uuid_shaped_machine_username_is_not_mistaken_for_a_digest(self):
        # 下限停在 40 而不是 32：32 位纯 hex 正是 UUID 去掉连字符的长度。
        value = "0123456789abcdef0123456789abcdef"
        _write(self.enterprise, [_record(value, display_name="机器账号")])
        self.assertEqual({value}, set(self._load(include_demo=False)))

    def test_a_phc_encoded_hash_is_rejected_by_shape(self):
        # PHC 串（`$argon2id$…`）不是 hex，按 `{64}` 认的那道看不见它，但它是同一类材料。
        for value in ("$argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$abcdefghij",
                      "$2b$12$C6UzMD6BusSAoTFmYyO5aeZbP"):
            with self.subTest(prefix=value.split("$")[1]):
                _write(self.enterprise, [_record("admin", feishu_open_id=value)])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_a_phc_prefix_in_mixed_case_is_rejected_like_a_lowercase_one(self):
        # 两道判定都得大小写不敏感：`$Argon2id$` 与 `$argon2id$` 是同一条散列。只有一道认
        # 大小写，就等于留下"换个写法再粘一次"的缝——而 hex 那道早就已经认了大写。
        for value in ("$Argon2id$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$abcdefghij",
                      "$ARGON2ID$v=19$m=19456,t=2,p=1$c29tZXNhbHQ$abcdefghij",
                      "$2B$12$C6UzMD6BusSAoTFmYyO5aeZbP"):
            with self.subTest(prefix=value.split("$")[1]):
                _write(self.enterprise, [_record("admin", feishu_open_id=value)])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_a_digest_pasted_with_an_internal_line_break_is_still_rejected(self):
        # 只 strip() 首尾会放过串内空白：从终端/表格里 copy 一条摘要常常自带折行。
        # 每枚都 ≤64 位，所以拒它的只可能是形态判定，而不是字段长度。
        for value in ("a" * 40 + "\n", "\n" + "b" * 60,
                      "c" * 30 + "\r\n" + "c" * 30, "d" * 32 + " " + "d" * 28):
            with self.subTest(spans=len(value.split())):
                _write(self.enterprise, [_record("admin", display_name=value)])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_a_credential_key_is_named_as_such_not_as_a_typo(self):
        # `extra="forbid"` 本来也会拒这个键。黑名单独立承担的是诊断：让运维看见"这里不许放
        # 凭据"，而不是"字段名拼错了"——后者会被"改个名字再来一次"修掉。
        _write(self.enterprise, [_record("admin", password=SENTINEL[:10])])
        with self.assertRaises(directory.IdentityConfigError) as caught:
            self._load(include_demo=False)
        self.assertIn("凭据字段", str(caught.exception))
        self.assertIn("password", str(caught.exception))

    def test_a_credential_key_nested_inside_a_value_is_still_rejected(self):
        for value in ({SENTINEL: None}, [{"password": SENTINEL}], {"a": {"secret": ["x" * 64]}}):
            with self.subTest(shape=type(value).__name__):
                _write(self.enterprise, [_record("admin", display_name=value)])
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_an_ordinary_long_non_hex_value_is_not_mistaken_for_a_digest(self):
        # 反向钉子：形态检查过宽会把合法身份拒在启动期，而操作员看到的只有"含疑似摘要"。
        # 前三枚都短于 40（在下限以下，天然不误判）。后两枚**跨过**下限、只靠"非 hex"站着：
        # 少了它们，"只看长度不看字符集"的那道判定（`^.{40,}$`）可以悄悄换掉整条形态检查，
        # 全套件仍然绿——而这正是本文件唯一一条会拒掉合法身份的失败方向。
        for value in (
            "产品与解决方案中心负责人张三",
            "a" * 30 + "zzzz",
            "deadbeef" * 4 + "g",
            "f" * 39 + "u",
            "产品研发中心数据与智能平台部企业知识助手运营组资深产品经理张三，工位在研发楼三层东区",
        ):
            with self.subTest(value=value[:8]):
                _write(self.enterprise, [_record("admin", display_name=value[:64])])
                self._load(include_demo=False)

    def test_a_rejection_never_echoes_a_field_value(self):
        # 异常消息会进启动日志。一份写歪了的身份文件里，那个取值完全可能是从口令表粘过来的。
        digest_key = "f" * 64
        for field, value in (
            ("display_name", SENTINEL),      # 超长 ⇒ 字段校验器分支
            ("role", SENTINEL),              # 超长 ⇒ 字段校验器分支
            ("feishu_open_id", "e" * 64),    # 摘要形态 ⇒ 取值分支
            ("password", SENTINEL),          # 黑名单键 ⇒ 键分支
            (digest_key, True),              # 键名**本身**是摘要 ⇒ 键名分支（extra="forbid"
                                             # 的 loc 装的正是键名，放过它就等于原样拼进消息）
        ):
            with self.subTest(key=field[:12]):
                _write(self.enterprise, [_record("admin", **{field: value})])
                with self.assertRaises(directory.IdentityConfigError) as caught:
                    self._load(include_demo=False)
                self.assertNotIn(SENTINEL, str(caught.exception))
                self.assertNotIn("e" * 64, str(caught.exception))
                self.assertNotIn(digest_key, str(caught.exception))

    def test_a_blank_feishu_open_id_is_rejected_instead_of_colliding_two_accounts(self):
        # 唯一性只管**非 null** 的 open_id：`""` 一旦算"有值"，两个没接飞书的账号就会假冲突。
        _write(self.enterprise, [_record("admin", feishu_open_id="")])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_two_accounts_without_an_open_id_are_allowed(self):
        _write(self.enterprise, [_record("admin"), _record("ghost")])
        self.assertEqual({"admin", "ghost"}, set(self._load(include_demo=False)))


class IdentityDocumentShapeTests(_IdentityFiles):
    """文件级形态：顶层键封闭、必须是数组、每元素必须是对象；读不出来与形态错同一条出路。"""

    def test_the_top_level_key_set_is_closed(self):
        for document in (
            {"identities": [], "passwords": {}},
            {"users": []},
            ["admin"],
            {"identities": {"admin": {}}},
        ):
            with self.subTest(document=str(document)[:24]):
                self.enterprise.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(directory.IdentityConfigError):
                    self._load(include_demo=False)

    def test_a_record_that_is_not_an_object_is_rejected(self):
        _write(self.enterprise, ["admin"])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_malformed_json_is_a_hard_failure_naming_the_file(self):
        self.enterprise.write_text("{not json", encoding="utf-8")
        with self.assertRaises(directory.IdentityConfigError) as caught:
            self._load(include_demo=False)
        self.assertIn(str(self.enterprise), str(caught.exception))

    def test_a_file_that_cannot_be_decoded_fails_like_a_malformed_one(self):
        # Windows 上用记事本/Excel 另存为会产出 GBK 或 UTF-16。少这道拦截，症状就是一个逃出
        # 启动面的 `UnicodeDecodeError`——运维拿到半截栈，而不是"这个文件有问题"。
        text = json.dumps({"identities": [_record("admin", display_name="管理员")]},
                          ensure_ascii=False)
        for encoding in ("utf-16", "gbk"):
            with self.subTest(encoding=encoding):
                self.enterprise.write_bytes(text.encode(encoding))
                with self.assertRaises(directory.IdentityConfigError) as caught:
                    self._load(include_demo=False)
                self.assertIn(str(self.enterprise), str(caught.exception))

    def test_a_path_occupied_by_a_directory_fails_like_a_malformed_file(self):
        self.enterprise.unlink()
        self.enterprise.mkdir()
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_the_record_loader_takes_a_path_and_nothing_else(self):
        """记录只从文件来：没有"内存直传"这条旁路（身份唯一真源是文件集，SEC-A-010）。

        按签名判而不是"传两个参数试一次"：占位参数哪天被人手加回来，这条立刻红，
        而试调用只会红在"它没报错"上——后者说不清是旁路被实装了还是被静默忽略了。
        """
        self.assertEqual(
            ["path"], list(inspect.signature(directory._validate_records).parameters)
        )


class MergeInvariantTests(_IdentityFiles):
    """合并不变量：enterprise 先、demo 后、重复即拒；唯一性在**合并后的全集**上判。"""

    def test_duplicates_inside_one_file_are_rejected_too(self):
        _write(self.enterprise, [_record("admin", feishu_open_id="ou_a"),
                                 _record("admin", feishu_open_id="ou_b")])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)
        _write(self.enterprise, [_record("a", feishu_open_id="ou_same"),
                                 _record("b", feishu_open_id="ou_same")])
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=False)

    def test_the_conflict_message_names_the_clashing_identity_and_who_tried(self):
        _write(self.enterprise, [_record("admin", role="ADMIN")])
        _write(self.demo, [_record("admin", role="VIEWER")])
        with self.assertRaises(directory.IdentityConfigError) as caught:
            self._load(include_demo=True)
        message = str(caught.exception)
        self.assertIn("admin", message)
        self.assertIn("users.demo.json", message, "冲突消息要点名是哪个文件想覆盖谁")

    def test_a_broken_demo_file_cannot_reach_an_enterprise_load(self):
        # "企业形态不读 demo 文件"的结构事实：demo 那份文件坏掉或消失都不影响 enterprise 读。
        self.demo.write_text("{garbage", encoding="utf-8")
        self.assertEqual({"admin"}, set(self._load(include_demo=False)))
        self.demo.unlink()
        self.assertEqual({"admin"}, set(self._load(include_demo=False)))
        with self.assertRaises(directory.IdentityConfigError):
            self._load(include_demo=True)


class DirectoryReadFaceTests(_IdentityFiles):
    """`identities()` / `get_identity()` / 缓存 / 测试接缝。"""

    def test_the_read_face_follows_the_mode_switch(self):
        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))
        self.assertEqual({"admin"}, set(self._identities_at(enterprise_mode=True)))

    def test_the_cached_directory_is_read_only_for_every_caller(self):
        # `identities()` 交回的是缓存本体。注解是 `Mapping`，但那只挡得住静态检查：任一调用方
        # `pop()` 一次，就把一个人从进程生命周期内的身份真源里抹掉——名册当场少一人，
        # 部门计数跟着少一人，而且下一次读还是抹掉后的样子。
        live = directory.identities()
        self.assertEqual({"admin", "viewer"}, set(live))
        with self.assertRaises((TypeError, AttributeError)):
            live.pop("admin")          # type: ignore[attr-defined]
        with self.assertRaises((TypeError, AttributeError)):
            live["ghost"] = UserIdentity(username="ghost", display_name="幽灵", role="HR")
        self.assertEqual({"admin", "viewer"}, set(directory.identities()),
                         "拒写之外还不许顺手改掉：名册要读出同一批人")

    def test_the_directory_is_loaded_once_per_mode(self):
        with mock.patch.object(directory, "load_identities",
                               wraps=directory.load_identities) as loader:
            self._identities_at(enterprise_mode=False)
            self._identities_at(enterprise_mode=False)
            self.assertEqual(1, loader.call_count)
            self._identities_at(enterprise_mode=True)
            self.assertEqual(2, loader.call_count,
                             "两种形态共用一份缓存 ⇒ 企业形态会看到 demo 身份")
            swapped = _write(self.root / "other.json", [_record("other")])
            with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", swapped):
                self.assertEqual(2, loader.call_count,
                                 "改文件不 reload 是刻意的：形态在进程生命周期内不变")

    def test_reset_cache_forces_a_reload(self):
        self._identities_at(enterprise_mode=False)
        directory.reset_cache()
        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))

    def test_get_identity_is_none_for_an_unknown_username(self):
        self._identities_at(enterprise_mode=False)
        self.assertEqual("ADMIN", directory.get_identity("admin").role)
        self.assertIsNone(directory.get_identity("nobody"))
        self.assertIsNone(directory.get_identity(""))

    def test_override_identities_is_visible_and_is_always_restored(self):
        before = dict(directory._CACHE)
        replacement = {"ghost": UserIdentity(username="ghost", display_name="幽灵", role="HR")}
        with directory.override_identities(replacement):
            self.assertEqual({"ghost"}, set(directory.identities()))
            self.assertIsNone(directory.get_identity("admin"))
        self.assertEqual(before, dict(directory._CACHE), "接缝退出后缓存要还原成用例前的样子")

    def test_override_identities_restores_even_when_the_body_raises(self):
        with self.assertRaises(ZeroDivisionError):
            with directory.override_identities({}):
                raise ZeroDivisionError
        self.assertEqual({"admin", "viewer"}, set(self._identities_at(enterprise_mode=False)))


class ShippedIdentityFilesTests(unittest.TestCase):
    """随镜像打包的那两份文件本身要过同一套校验，并且**出厂形态**要钉住。"""

    def _load_shipped(self, *, include_demo: bool):
        with mock.patch.object(directory, "ENTERPRISE_IDENTITIES_FILE", SHIPPED_ENTERPRISE), \
                mock.patch.object(directory, "DEMO_IDENTITIES_FILE", SHIPPED_DEMO):
            return directory.load_identities(include_demo=include_demo)

    def test_both_files_ship_and_pass_their_own_validator(self):
        self.assertTrue(SHIPPED_ENTERPRISE.is_file())
        self.assertTrue(SHIPPED_DEMO.is_file())
        self._load_shipped(include_demo=True)

    def test_the_enterprise_file_ships_empty_so_enterprise_mode_starts_with_nobody(self):
        # 企业形态的默认不是"5 个能登录的演示账号"，是零：身份由运维写进 users.json 再重建镜像。
        self.assertEqual({}, self._load_shipped(include_demo=False))

    def test_demo_mode_ships_exactly_the_demo_accounts(self):
        loaded = self._load_shipped(include_demo=True)
        self.assertEqual({"admin", "sales01", "hr01", "user", "viewer"}, set(loaded))
        self.assertEqual({"ADMIN", "SALES", "HR", "USER", "VIEWER"},
                         {identity.role for identity in loaded.values()})
        self.assertTrue(all(identity.enabled for identity in loaded.values()))
        self.assertTrue(all(identity.feishu_open_id is None for identity in loaded.values()))

    def test_the_shipped_files_carry_relative_paths_as_the_deployment_contract(self):
        # 镜像 WORKDIR 就是 `backend/`，`config/` 整目录随镜像 COPY（Dockerfile 已核）。
        # 把这两枚常量绝对化等于换掉部署口径，所以钉字面值而不是"能读到"。
        self.assertEqual(Path("config/users.json"), directory.ENTERPRISE_IDENTITIES_FILE)
        self.assertEqual(Path("config/users.demo.json"), directory.DEMO_IDENTITIES_FILE)

    def test_no_shipped_identity_record_carries_a_key_outside_the_closed_field_set(self):
        # 直接扫 JSON 文本，不走 loader：loader 哪天被改松，这一枚还站着。
        allowed = set(UserIdentity.model_fields)
        for path in (SHIPPED_ENTERPRISE, SHIPPED_DEMO):
            document = json.loads(path.read_text(encoding="utf-8"))
            for record in document["identities"]:
                with self.subTest(path=path.name, username=record.get("username")):
                    self.assertEqual(set(), {str(k).lower() for k in record} - allowed)


class IdentityCredentialSeparationTests(unittest.TestCase):
    """SEC-A-010：一个单元不得同时持有身份与凭据状态。这里验身份侧的"不越界"。"""

    FORBIDDEN_HEADS = ("hashlib", "argon2", "sqlite3", "hmac", "secrets")

    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = ast.parse(Path(directory.__file__).read_text(encoding="utf-8"))
        cls.imported: list[str] = []
        for node in ast.walk(cls.tree):
            if isinstance(node, ast.Import):
                cls.imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                cls.imported.append(node.module)

    def test_the_identity_module_imports_neither_hash_nor_a_database_driver(self):
        heads = {name.split(".")[0] for name in self.imported}
        self.assertEqual([], sorted(heads & set(self.FORBIDDEN_HEADS)), self.imported)

    def test_settings_is_the_only_app_module_the_identity_layer_touches(self):
        # `user_store` / `credentials` / `credentials_migration` 一旦进这张清单，
        # 就是"同一单元同时持有身份与凭据"的开始（SEC-A-010 禁的那件事）。
        self.assertEqual({"app.config"}, {n for n in self.imported if n.startswith("app.")})

    def test_the_identity_module_never_calls_the_restricted_legacy_writer(self):
        calls = [ast.unparse(node) for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
        self.assertEqual([], [c for c in calls if "import_legacy_digest" in c])


class EnterpriseModeSwitchTests(unittest.TestCase):
    """`SECURITY_ENTERPRISE_MODE` 是总开关，默认必须关掉——否则既有 dev/test 形态当场变。"""

    def test_the_switch_exists_defaults_off_and_is_a_bool(self):
        field = Settings.model_fields["security_enterprise_mode"]
        self.assertIs(False, field.default)
        self.assertIs(bool, field.annotation)

    def test_the_shipped_settings_object_is_off(self):
        self.assertFalse(config_module.settings.security_enterprise_mode,
                         "默认值翻了 ⇒ 企业形态守卫会在没人配置的情况下生效")


class KnowledgeOsReadPointTests(_IdentityFiles):
    """身份读点迁移：`knowledge_os` 只认 directory，且换真源不许改响应形状。"""

    def test_the_module_no_longer_names_the_legacy_constant_table(self):
        tree = ast.parse((BACKEND_DIR / "app" / "knowledge_os.py").read_text(encoding="utf-8"))
        bound = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                    for alias in node.names}
        self.assertNotIn("USERS", bound | imported)
        self.assertIn("get_identity", bound)
        self.assertIn("directory_identities", bound)

    def _mapping(self) -> dict[str, UserIdentity]:
        return {
            "admin": UserIdentity(username="admin", display_name="系统管理员", role="ADMIN"),
            "sales01": UserIdentity(username="sales01", display_name="销售演示账号", role="SALES"),
            "ghost": UserIdentity(username="ghost", display_name="没登录过的人", role="VIEWER"),
        }

    def _query(self, username: str) -> dict:
        return {"action": "QUERY", "status": "SUCCESS", "username": username,
                "timestamp": datetime.now(timezone.utc).isoformat(), "latency_ms": 100.0}

    def test_usage_summary_counts_users_and_departments_from_the_directory(self):
        events = [self._query("admin"), self._query("admin"), self._query("sales01"),
                  self._query("someone-not-in-the-directory"),
                  {"action": "QUERY", "status": "FAILED",
                   "username": "admin", "timestamp": datetime.now(timezone.utc).isoformat()}]
        admin = CurrentUser(username="admin", display_name="系统管理员", role="ADMIN")
        with mock.patch.object(knowledge_os, "recent_events", return_value=events), \
                directory.override_identities(self._mapping()):
            payload = knowledge_os.usage_summary(admin)
        self.assertEqual(3, payload["total_users"], "总数来自目录，不是常量表也不是凭据表")
        self.assertEqual(3, payload["active_users"])
        self.assertEqual(4, payload["queries_30d"])
        self.assertEqual(100.0, payload["adoption_pct"])
        self.assertEqual({"name": "平台管理", "queries": 2}, payload["top_department"])
        self.assertEqual(4, payload["queries_today"])
        self.assertEqual(100.0, payload["avg_latency_ms"])

    def test_list_users_projects_identity_fields_and_keeps_the_response_shape(self):
        login = {"action": "LOGIN", "status": "SUCCESS", "username": "admin",
                 "timestamp": datetime.now(timezone.utc).isoformat()}
        admin = CurrentUser(username="admin", display_name="系统管理员", role="ADMIN")
        roster = {**self._mapping(),
                  "retired": UserIdentity(username="retired", display_name="停用的人",
                                          role="USER", enabled=False)}
        with mock.patch.object(knowledge_os, "recent_events", return_value=[login]), \
                directory.override_identities(roster):
            users = knowledge_os.list_users(admin)["users"]
        order = {"admin": 0, "sales01": 1, "ghost": 2, "retired": 3}
        self.assertEqual(
            [{"username": "admin", "display_name": "系统管理员", "role": "ADMIN",
              "department": "平台管理", "status": "ACTIVE", "last_login": login["timestamp"]},
             {"username": "sales01", "display_name": "销售演示账号", "role": "SALES",
              "department": "销售", "status": "ACTIVE", "last_login": None},
             {"username": "ghost", "display_name": "没登录过的人", "role": "VIEWER",
              "department": "外部访客", "status": "ACTIVE", "last_login": None},
             # 停用的人**仍在名册上**（在册与否只由文件说了算），但那一格如实跟着 `enabled` 走。
             {"username": "retired", "display_name": "停用的人", "role": "USER",
              "department": "全员", "status": "DISABLED", "last_login": None}],
            sorted(users, key=lambda user: order[user["username"]]))

    def test_usage_summary_reports_zero_adoption_when_the_directory_is_empty(self):
        # 企业形态出厂是零身份（`config/users.json` 为空数组）：没有分母就不要硬造一个 1，
        # 那会报出 `active_users=2, total_users=0, adoption_pct=200.0` 这种自相矛盾的载荷。
        events = [self._query("ghost"), self._query("nobody")]
        admin = CurrentUser(username="admin", display_name="系统管理员", role="ADMIN")
        with mock.patch.object(knowledge_os, "recent_events", return_value=events), \
                directory.override_identities({}):
            payload = knowledge_os.usage_summary(admin)
        self.assertEqual(0, payload["total_users"])
        self.assertEqual(2, payload["active_users"],
                         "审计面上的历史用户名不按目录过滤——这是 docstring 里写明的已知口径边界")
        self.assertEqual(0.0, payload["adoption_pct"], "目录为空 ⇒ 采用率是 0，不是 N×100%")
        self.assertIsNone(payload["top_department"], "没人可派生部门时不要造一个部门出来")

    def test_usage_summary_reads_the_directory_once_per_payload(self):
        # 总人数与采用率的分母必须是**同一次**读：两次读之间缓存若变了，载荷就会自己跟自己
        # 矛盾（`active_users=3, total_users=4, adoption_pct=100.0` 这类）。绑一次就无从错开。
        tree = ast.parse((BACKEND_DIR / "app" / "knowledge_os.py").read_text(encoding="utf-8"))
        fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
                  and node.name == "usage_summary")
        calls = [ast.unparse(node) for node in ast.walk(fn) if isinstance(node, ast.Call)]
        self.assertEqual(1, len([c for c in calls if c == "directory_identities()"]),
                         f"目录在一份载荷里被读了多次：{calls}")

    def test_an_unreadable_directory_cannot_be_papered_over_by_a_second_source(self):
        # 目录读失败 ⇒ 端点报错，不许退回任何常量表。这是"唯一真源"的可观察面。
        directory.reset_cache()
        with mock.patch.object(directory, "load_identities",
                               side_effect=directory.IdentityConfigError("坏文件")):
            with self.assertRaises(directory.IdentityConfigError):
                knowledge_os.usage_summary(
                    CurrentUser(username="admin", display_name="系统管理员", role="ADMIN"))
