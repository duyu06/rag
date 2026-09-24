"""Model Router V2.3 契约测试（按任务累积）。

Task 1 = 注册表 + 数据模型 + 配置键：覆盖 brief 的四组（加载 / 校验失败 / 凭据解析 /
warmup fail-fast），外加 `models.py` 冻结形状与 §12 配置键（默认值、边界、
`.env.example` 同步）。

Task 2 = errors（§6 三分类逐码）+ normalize（两侧报文与流式，含 tool_calls 字符串→dict、
usage 缺失 estimated 旗标、`[DONE]`、中文 UTF-8 拆包）+ provider（唯一出口、
model_override、未知 provider、RegistryError→config）+ health（probe 收编、60s 缓存、
`/api/health` 消费形状不变）+ D6 的结构护栏（httpx / endpoint 字面量只在 provider.py）。

测试隔离沿用 TypeSafe V2 Task 2 的手法：`Settings(_env_file=None)` 关 dotenv +
`mock.patch.dict(os.environ, {}, clear=True)` 关宿主 OS env，再把造出来的 Settings
打到 `app.llm.registry.settings`（与 `app.llm.health.settings`）上——注册表与凭据都不读
进程全局的 `settings` 单例，因此宿主 `backend/.env`（OPENAI key 为空、
OLLAMA_MODEL=ornith-1.5:9b-text）不会串味。
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import time
import traceback
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
from fastapi import HTTPException  # noqa: E402  #18/D2 的 HTTP 面兜底语义
from pydantic import SecretStr, ValidationError  # noqa: E402

import app.agent as agent_module  # noqa: E402
import app.agent_routes as agent_routes_module  # noqa: E402  第二条 SSE 出口（评审 I-4）
import app.agent_trace as agent_trace_module  # noqa: E402
import app.audit as audit_module  # noqa: E402
import app.conversation_agent as conversation_agent_module  # noqa: E402
import app.conversation_stream_routes as stream_routes_module  # noqa: E402
import app.llm as llm  # noqa: E402
import app.llm.classifier as classifier_module  # noqa: E402
import app.llm.errors as errors_module  # noqa: E402
import app.llm.fallback as fallback_module  # noqa: E402
import app.llm.registry as registry_module  # noqa: E402
import app.llm.router as router_module  # noqa: E402
import app.llm.usage as usage_module  # noqa: E402
import app.main as main_module  # noqa: E402
import app.main_agent as main_agent_module  # noqa: E402
import app.rag as rag_module  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm import errors, normalize  # noqa: E402
from app.llm import health as health_module  # noqa: E402
from app.llm import provider as provider_module  # noqa: E402
from app.llm.classifier import classify  # noqa: E402
from app.llm.errors import LLMError  # noqa: E402
from app.llm.fallback import (  # noqa: E402
    AllCandidatesFailedError,
    Attempt,
    FallbackResult,
    StreamInterrupted,
    StreamSession,
    StreamSummary,
)
from app.llm.router import NoCapableModelError, plan  # noqa: E402
from app.llm.models import (  # noqa: E402
    LLMChunk,
    LLMRequest,
    LLMResponse,
    ModelCapabilities,
    ModelDefinition,
    ModelLimits,
    ModelPricing,
    RequestProfile,
    RouteCandidate,
    RoutePlan,
    ToolCall,
    UsageRecord,
)
from app.llm.registry import (  # noqa: E402
    ProviderCredentials,
    Registry,
    RegistryError,
    get_registry,
    load_registry,
    provider_credentials,
    reset_registry,
    validate_registry,
    warmup,
)

SHIPPED_REGISTRY = BACKEND_DIR / "config" / "llm_registry.json"

from app.agent_trace import MODEL_ROUTE_KEY  # noqa: E402  §8.1 第 4 条的唯一挂载点键名
from app.auth import CurrentUser  # noqa: E402  SSE 链的用户面（`_local_fast_path` 的入参）

#: 会话级护栏（`tests/conftest.py`，评审 I-2）的对外口径：防回潮钉从那里读「生效路径」与
#: 「本会话被拦下的写真实账本次数」。护栏文件被删 ⇒ 本文件 import 失败 ⇒ 全套件红——这是
#: 刻意要的耦合强度：`llm_request_logs` 是 §8 全部聚合的唯一数据源，不容测试写脏。
TESTS_DIR = BACKEND_DIR / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import conftest as ledger_guard  # noqa: E402


def make_settings(**overrides) -> Settings:
    """确定性构造：屏蔽 `.env` 与宿主 OS env，字段只由 kwargs + 类默认值决定。"""
    with mock.patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **overrides)


def entry(**overrides) -> dict:
    """最小合法条目：校验类用例只改一个字段就能变红。"""
    data = {
        "id": "m1",
        "provider": "ollama",
        "model": "test-model:latest",
        "enabled": True,
        "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": False,
                         "stream": True, "reasoning": False},
        "priority": {"chat": 10, "rag": 10, "tools": 0},
        "limits": {"context_tokens": 4096, "max_output_tokens": 512},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return data


def registry_payload(*models: dict, **top: object) -> dict:
    data: dict = {"version": 1, "models": list(models)}
    data.update(top)
    return data


class _RegistryFixture(unittest.TestCase):
    """公共底座：临时注册表文件 + registry.settings 打桩 + 单例复位。"""

    def setUp(self) -> None:
        reset_registry()
        self.addCleanup(reset_registry)

    def use_settings(self, **overrides) -> Settings:
        fake = make_settings(**overrides)
        patcher = mock.patch.object(registry_module, "settings", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def load(self, payload: dict) -> Registry:
        return self.load_raw(json.dumps(payload))

    def load_raw(self, text: str) -> Registry:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        self.addCleanup(_unlink, handle.name)
        return load_registry(handle.name)

    def model(self, **overrides) -> ModelDefinition:
        return ModelDefinition.model_validate(entry(**overrides))


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _traceback_text(exc: BaseException) -> str:
    """完整 traceback 文本（含 __cause__/__context__ 链）：泄漏面按日志实际长什么样来钉。"""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


class ShippedRegistryTests(_RegistryFixture):
    """出厂 `config/llm_registry.json` = spec §3 的 5 条目，且零 secret。"""

    def test_shipped_file_matches_spec_section_three_entries(self):
        self.use_settings()
        registry = load_registry(str(SHIPPED_REGISTRY))
        self.assertEqual(
            ("ollama-ornith", "ollama-phi3", "openai", "deepseek-chat", "qwen-plus"),
            registry.ids())
        by_id = {m.id: m for m in registry.models}
        ornith, phi3 = by_id["ollama-ornith"], by_id["ollama-phi3"]
        self.assertEqual(("ollama", "ornith-1.5:9b-text"), (ornith.provider, ornith.model))
        self.assertEqual(("ollama", "phi3:mini"), (phi3.provider, phi3.model))
        # §3 冻结的 priority：本地两条 100/100/0 与 80/80/0（tools 档 0 = agent 剔除）。
        self.assertEqual({"chat": 100, "rag": 100, "tools": 0}, ornith.priority)
        self.assertEqual({"chat": 80, "rag": 80, "tools": 0}, phi3.priority)
        self.assertFalse(ornith.capabilities.tools)
        self.assertFalse(phi3.capabilities.tools)
        # openai / deepseek / qwen 三条 tools=true（§3）。
        for model_id in ("openai", "deepseek-chat", "qwen-plus"):
            with self.subTest(model=model_id):
                self.assertTrue(by_id[model_id].capabilities.tools)
                self.assertTrue(by_id[model_id].external)

    def test_shipped_file_carries_no_credentials_anywhere(self):
        # D1 红线（两层钉）：文本层扫凭据字面量，结构层要求每个键名都在 §3 schema 内。
        text = SHIPPED_REGISTRY.read_text(encoding="utf-8").lower()
        for forbidden in ("api_key", "apikey", "base_url", "authorization",
                          "secret", "bearer", "sk-"):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, text)

        allowed = {
            "": {"version", "models"},                      # 顶层
            "models[]": {"id", "provider", "model", "enabled", "external",
                         "capabilities", "priority", "limits", "pricing"},
            "models[].capabilities": set(ModelCapabilities.model_fields),
            "models[].priority": {"chat", "rag", "tools"},
            "models[].limits": {"context_tokens", "max_output_tokens"},
            "models[].pricing": {"input_per_1m", "output_per_1m", "currency"},
        }
        doc = json.loads(text)
        self.assertEqual(allowed[""], set(doc))
        for model in doc["models"]:
            self.assertEqual(allowed["models[]"], set(model))
            self.assertEqual(allowed["models[].capabilities"], set(model["capabilities"]))
            self.assertEqual(allowed["models[].priority"], set(model["priority"]))
            self.assertEqual(allowed["models[].limits"], set(model["limits"]))
            self.assertEqual(allowed["models[].pricing"], set(model["pricing"]))

    def test_openai_entry_enabled_is_resolved_from_api_key_presence(self):
        # JSON 写 enabled=true 是「意图」，解析层按 key 收成事实值（brief 的动态判定）。
        self.use_settings()  # openai_api_key 默认空串
        by_id = {m.id: m for m in load_registry(str(SHIPPED_REGISTRY)).models}
        self.assertFalse(by_id["openai"].enabled)

        self.use_settings(openai_api_key="sk-not-empty",
                          deepseek_api_key=SecretStr("ds-not-empty"),
                          qwen_api_key=SecretStr("qk-not-empty"))
        by_id = {m.id: m for m in load_registry(str(SHIPPED_REGISTRY)).models}
        self.assertTrue(by_id["openai"].enabled)
        # 反向钉（各自的 key 都到位）：key 到位 ≠ 自动打开——enabled=false 的占位条目必须
        # 停在 false。这一对断言防的是未来把动态判定简化成 `enabled = bool(key)`。
        self.assertFalse(by_id["deepseek-chat"].enabled)
        self.assertFalse(by_id["qwen-plus"].enabled)

    def test_local_entries_stay_enabled_without_any_key(self):
        # ollama external=false：无 key 也可用（D1「ollama 无 key」在 enabled 侧的体现）。
        self.use_settings()
        registry = load_registry(str(SHIPPED_REGISTRY))
        self.assertEqual({"ollama-ornith", "ollama-phi3"},
                         {m.id for m in registry.models if m.enabled})

    def test_get_returns_model_and_unknown_id_raises_registry_error(self):
        self.use_settings()
        registry = load_registry(str(SHIPPED_REGISTRY))
        self.assertEqual("phi3:mini", registry.get("ollama-phi3").model)
        with self.assertRaises(RegistryError):
            registry.get("no-such-model")


class RegistryValidationTests(_RegistryFixture):
    """四类校验失败 + 结构性坏文件一律 `RegistryError(ValueError)`。"""

    def test_registry_error_is_value_error(self):
        self.assertTrue(issubclass(RegistryError, ValueError))

    def test_duplicate_id_rejected(self):
        with self.assertRaises(RegistryError) as ctx:
            self.load(registry_payload(entry(), entry()))
        self.assertIn("重复 id", str(ctx.exception))

    def test_priority_key_outside_allowed_set_rejected(self):
        # mode=agent 复用 tools 档，因此 "agent" 不是合法键；拼错必须响。
        for bad in ({"chat": 1, "agent": 2}, {"toools": 1}, {}):
            with self.subTest(priority=bad):
                if not bad:
                    self.load(registry_payload(entry(priority={})))  # 空 priority 合法
                    continue
                with self.assertRaises(RegistryError):
                    self.load(registry_payload(entry(priority=bad)))

    def test_all_false_capabilities_rejected(self):
        with self.assertRaises(RegistryError) as ctx:
            self.load(registry_payload(entry(capabilities={
                "chat": False, "rag": False, "tools": False, "stream": False,
                "reasoning": False})))
        self.assertIn("capabilities", str(ctx.exception))

    def test_unknown_top_level_key_rejected(self):
        with self.assertRaises(RegistryError):
            self.load(registry_payload(entry(), extra_runtime_logic="router.sort(x)"))

    def test_credential_or_unknown_key_inside_entry_rejected(self):
        # extra=forbid 让「把 key/base_url 写进 JSON」和「拼错字段名」都在启动期暴露。
        for bad_entry in (
            dict(api_key="sk-live-leak"),
            dict(base_url="http://attacker:11434"),
            dict(model_id="typo"),
            dict(pricing={"input_per_1m": 0.0, "output_per_1m": 0.0, "gold": "USD"}),
        ):
            with self.subTest(extra=sorted(bad_entry)):
                payload = registry_payload(entry(**bad_entry))
                with self.assertRaises(RegistryError):
                    self.load(payload)

    def test_provider_name_outside_lowercase_convention_rejected(self):
        # provider 参与 D1 的 env 名拼装（大写化后当凭据键名查），所以只收 ^[a-z0-9_]+$：
        # 大写/连字符/空格/换行/空串都会拼出解析不到的 env 名 = 配置事故，模型层直接拒。
        for bad in ("OpenAI", "openai-v1", "open ai", "ollama\nEVIL", ""):
            with self.subTest(provider=bad):
                with self.assertRaises(ValidationError):
                    ModelDefinition.model_validate(entry(provider=bad))
        # 走注册表加载同样拒，且消息不回显条目值（与 I-1 同轨）；合法形态不误伤。
        canary = "OpenAI-CANARY-hyphen"
        with self.assertRaises(RegistryError) as ctx:
            self.load(registry_payload(entry(provider=canary)))
        self.assertIn("models.0.provider", str(ctx.exception))
        self.assertNotIn(canary, str(ctx.exception))
        self.assertEqual("x_1", self.load(
            registry_payload(entry(provider="x_1"))).models[0].provider)

    def test_validation_failure_message_never_echoes_entry_values(self):
        # D1/D3：RegistryError 由 warmup 原样抛进启动日志 ⇒ 异常文本与 traceback 里
        # 只许出现「位置 + 原因」，条目字段值（误写进来的 key 明文）必须为 0 命中。
        canary = "sk-CANARY-9f2c74-not-in-any-message"
        cases = {
            "条目里写 api_key": (entry(api_key=canary), "models.0.api_key"),
            "条目里写 base_url": (entry(base_url=canary), "models.0.base_url"),
            "pricing 里塞未知键": (entry(pricing={"input_per_1m": 0.0,
                                                  "output_per_1m": 0.0,
                                                  "gold": canary}),
                                   "models.0.pricing.gold"),
            "provider 名不合法": (entry(provider=f"OpenAI-{canary}"), "models.0.provider"),
            "priority 值不是整数": (entry(priority={"chat": canary}),
                                    "models.0.priority.chat"),
        }
        for label, (bad_entry, expected_loc) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(RegistryError) as ctx:
                    self.load(registry_payload(bad_entry))
                message = str(ctx.exception)
                self.assertNotIn(canary, message)
                self.assertNotIn(canary, _traceback_text(ctx.exception))
                # 诊断能力不减：键名与路径照旧在消息里（否则运维无从下手）。
                self.assertIn(expected_loc, message)

    def test_empty_models_list_rejected(self):
        # 空注册表会让每个请求都 NO_CAPABLE_MODEL —— 配置事故，不当「全部禁用」静默跑。
        with self.assertRaises(RegistryError):
            self.load(registry_payload())

    def test_structurally_broken_sources_rejected(self):
        missing_path = str(BACKEND_DIR / "config" / "no_such_registry.json")
        cases = {
            "文件不存在": lambda: load_registry(missing_path),
            "JSON 语法错": lambda: self.load_raw("{{{ not json"),
            "顶层不是对象": lambda: self.load_raw("[1, 2]"),
            "缺 version": lambda: self.load({"models": [entry()]}),
            "models 非列表": lambda: self.load({"version": 1, "models": {"id": "m1"}}),
        }
        for label, call in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(RegistryError):
                    call()

    def test_missing_capability_flags_default_to_false_fail_closed(self):
        # 漏写旗标 = 「不会这项」，而不是 None/True；limits/pricing 同理吃默认值。
        partial = entry()
        partial["capabilities"] = {"chat": True}
        del partial["limits"], partial["pricing"], partial["priority"]
        registry = self.load(registry_payload(partial))
        caps = registry.models[0].capabilities
        self.assertTrue(caps.chat)
        self.assertEqual((False, False, False, False),
                         (caps.rag, caps.tools, caps.stream, caps.reasoning))
        self.assertEqual(ModelLimits(), registry.models[0].limits)
        self.assertEqual(ModelPricing(), registry.models[0].pricing)
        self.assertEqual({}, registry.models[0].priority)


class ProviderCredentialsTests(_RegistryFixture):
    """D1 解析：ollama 无 key、openai 复用现有配置、其余按大写前缀、缺 base_url 即拒。"""

    def test_ollama_uses_base_url_and_never_a_key(self):
        self.use_settings(ollama_base_url="http://host.docker.internal:11434")
        creds = provider_credentials(self.model())
        self.assertEqual("http://host.docker.internal:11434", creds.base_url)
        self.assertEqual("", creds.api_key)

        # 即使宿主误设 OLLAMA_API_KEY，ollama 也不外带凭据（D1）。
        with mock.patch.dict(os.environ, {"OLLAMA_API_KEY": "should-be-ignored"}, clear=True):
            self.assertEqual("", provider_credentials(self.model()).api_key)

    def test_trailing_slash_normalised_on_base_url(self):
        self.use_settings(ollama_base_url="http://localhost:11434/")
        self.assertEqual("http://localhost:11434",
                         provider_credentials(self.model(provider="ollama")).base_url)

    def test_builtin_openai_entry_reuses_existing_openai_config(self):
        # 不产生第二套配置：Settings.openai_* 即凭据来源（与 legacy rag.py 同源）。
        self.use_settings(openai_api_key="sk-from-dotenv",
                          openai_base_url="https://api.openai.com/v1")
        creds = provider_credentials(self.model(provider="openai", external=True))
        self.assertEqual("sk-from-dotenv", creds.api_key)
        self.assertEqual("https://api.openai.com/v1", creds.base_url)

    def test_secret_str_provider_keys_are_unwrapped(self):
        self.use_settings(deepseek_api_key=SecretStr("  ds-key  "),
                          deepseek_base_url="https://api.deepseek.com/v1")
        creds = provider_credentials(self.model(provider="deepseek", external=True))
        self.assertEqual("ds-key", creds.api_key)  # strip 后不外泄空白
        self.assertEqual("https://api.deepseek.com/v1", creds.base_url)

        self.use_settings(qwen_api_key=SecretStr("qk"),
                          qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        creds = provider_credentials(self.model(provider="qwen", external=True))
        self.assertEqual("qk", creds.api_key)
        self.assertEqual("https://dashscope.aliyuncs.com/compatible-mode/v1", creds.base_url)

    def test_unknown_provider_falls_back_to_env_convention(self):
        # Settings 里没有 moonshot_* 字段 ⇒ 走 {PROVIDER大写}_API_KEY/_BASE_URL。
        self.use_settings()
        env = {"MOONSHOT_API_KEY": "mk", "MOONSHOT_BASE_URL": "https://api.moonshot.cn/v1"}
        with mock.patch.dict(os.environ, env, clear=True):
            creds = provider_credentials(self.model(provider="moonshot", external=True))
        self.assertEqual(ProviderCredentials(
            base_url="https://api.moonshot.cn/v1", api_key="mk", model_override=""), creds)

    def test_model_override_is_optional_and_provider_scoped(self):
        self.use_settings(ollama_base_url="http://localhost:11434")
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "phi3:mini",
                                          "OLLAMA_MODEL_OVERRIDE": "override:latest"},
                             clear=True):
            creds = provider_credentials(self.model())
        self.assertEqual("override:latest", creds.model_override)
        # 只有显式 _MODEL_OVERRIDE 生效：OLLAMA_MODEL 不把两条本地条目折叠成同一模型。
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "phi3:mini"}, clear=True):
            self.assertEqual("", provider_credentials(self.model()).model_override)

    def test_missing_base_url_is_a_config_error(self):
        self.use_settings()
        with self.assertRaises(RegistryError) as ctx:
            provider_credentials(self.model(provider="moonshot", external=True))
        self.assertIn("base url", str(ctx.exception))

    def test_credentials_never_read_the_registry_json(self):
        # 条目里没有凭据字段（extra=forbid），解析凭据只可能来自 env/Settings。
        model = self.model()
        self.assertEqual(set(ModelDefinition.model_fields),
                         set(model.model_dump()))
        self.assertNotIn("api_key", model.model_dump())


class RegistrySingletonAndWarmupTests(_RegistryFixture):
    """单例 + reset + warmup fail-fast（lifespan 接线留 Task 5，pre-flight 裁决）。"""

    def good_file(self, *ids: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(registry_payload(*[entry(id=i) for i in (ids or ("alpha",))]), handle)
        handle.close()
        self.addCleanup(_unlink, handle.name)
        return handle.name

    def broken_file(self) -> str:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        handle.write("{ not json }")
        handle.close()
        self.addCleanup(_unlink, handle.name)
        return handle.name

    def file_with(self, *models: dict) -> str:
        """指定条目集合的注册表文件（I-3 的三例都要自己控制 provider / enabled）。"""
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(registry_payload(*models), handle)
        handle.close()
        self.addCleanup(_unlink, handle.name)
        return handle.name

    def test_get_registry_caches_until_reset(self):
        first, second = self.good_file("alpha"), self.good_file("beta", "gamma")
        fake = self.use_settings(llm_registry_file=first)
        self.assertEqual(("alpha",), get_registry().ids())
        # 换配置键不换单例——文件只在启动时读一次（与 identity.get_resolver 同构）。
        fake.llm_registry_file = second
        self.assertEqual(("alpha",), get_registry().ids())
        self.assertIs(get_registry(), get_registry())
        reset_registry()
        self.assertEqual(("beta", "gamma"), get_registry().ids())

    def test_warmup_skips_everything_when_router_disabled(self):
        self.use_settings(llm_router_enabled=False, llm_registry_file=self.broken_file())
        self.assertIsNone(warmup())
        self.assertIsNone(registry_module._registry)  # 没读文件、没装配

    def test_warmup_fail_fast_and_leaves_no_half_built_singleton(self):
        self.use_settings(llm_router_enabled=True, llm_registry_file=self.broken_file())
        with self.assertRaises(RegistryError):
            warmup()
        self.assertIsNone(registry_module._registry)

    def test_warmup_loads_once_when_enabled(self):
        self.use_settings(llm_router_enabled=True, llm_registry_file=self.good_file())
        warmup()
        loaded = registry_module._registry
        self.assertIsNotNone(loaded)
        warmup()  # 第二次不重新装配
        self.assertIs(loaded, registry_module._registry)

    def test_warmup_rejects_enabled_entry_with_unregistered_provider(self):
        # 评审 I-3：`enabled` 条目的 provider 必须 ∈ `provider.PROVIDERS` 键集。
        # 未登记名在运行期是 `LLMError(kind=hard, no_fallback=True)` ⇒ 整条链终止
        # （Task 2 报告 D-5），所以打字错误必须死在启动日志里，而不是第一个请求上。
        # "deepseek_chat" 是 schema 合法（^[a-z0-9_]+$）却没登记的名字 ⇒ 由校验拦下。
        self.use_settings(llm_router_enabled=True,
                          llm_registry_file=self.file_with(entry(provider="deepseek_chat")))
        with self.assertRaises(RegistryError) as ctx:
            warmup()
        message = str(ctx.exception)
        self.assertIn("未登记", message)
        self.assertIn("deepseek_chat", message)
        self.assertIn("m1", message)                      # 说清是哪一条
        self.assertIn("ollama", message)                  # 并给出可用的分发面
        # 文件本身是好的：炸在装配之后的校验步，所以单例已建但 warmup 不 catch ⇒ 启动失败。
        self.assertIsNotNone(registry_module._registry)

        # 评审字面给的 "deepseek-chat"（带连字符）连模型层的 provider 模式都过不了，
        # warmup 同样抛——只是死在 load 那一步。两条路都不放行，且都不留可服务的半配置。
        self.use_settings(llm_registry_file=self.file_with(entry(provider="deepseek-chat")))
        reset_registry()
        with self.assertRaises(RegistryError):
            warmup()

    def test_warmup_accepts_every_registered_provider_name(self):
        # ollama / openai / qwen / deepseek 四个登记名都要过 warmup。云端三条必须真的
        # enabled（external=True 要配 key，否则解析层把 enabled 收成 False，用例空跑）。
        fake = self.use_settings(llm_router_enabled=True,
                                 openai_api_key="sk-x",
                                 deepseek_api_key=SecretStr("ds-x"),
                                 qwen_api_key=SecretStr("qk-x"),
                                 llm_registry_file=self.file_with(
                                     entry(id="a", provider="ollama"),
                                     entry(id="b", provider="openai", external=True),
                                     entry(id="c", provider="qwen", external=True),
                                     entry(id="d", provider="deepseek", external=True)))
        self.assertIsNone(warmup())
        registry = get_registry()
        self.assertEqual(("a", "b", "c", "d"), registry.ids())
        self.assertTrue(all(model.enabled for model in registry.models))

        # 出厂注册表同样过（修复没把现网 5 条目判死）。
        fake.llm_registry_file = str(SHIPPED_REGISTRY)
        reset_registry()
        self.assertIsNone(warmup())
        self.assertEqual(5, len(get_registry().models))

    def test_validate_registry_is_the_public_seam_and_skips_disabled_entries(self):
        # 校验面单独可测：`supported_providers` 由调用方注入——registry 不 import provider
        # （provider 已经 import registry，反向模块级 import 就是环）。
        enabled = self.model(id="local", provider="ollama")
        disabled_typo = self.model(id="typo", provider="moonshot", enabled=False)
        self.assertIsNone(validate_registry(
            Registry(models=(enabled, disabled_typo)),
            supported_providers=frozenset({"ollama"})))
        with self.assertRaises(RegistryError) as ctx:
            validate_registry(Registry(models=(self.model(id="oops", provider="moonshot"),)),
                              supported_providers=frozenset({"ollama"}))
        self.assertIn("oops", str(ctx.exception))
        # 空的分发面 ⇒ 每个 enabled 条目都违规（不依赖 provider 层的具体键集）。
        with self.assertRaises(RegistryError):
            validate_registry(Registry(models=(enabled,)), supported_providers=frozenset())
        # 两处投影不得漂移：SUPPORTED_PROVIDERS 就是 PROVIDERS 的键集，且四个名字都对。
        self.assertEqual(frozenset(provider_module.PROVIDERS),
                         provider_module.SUPPORTED_PROVIDERS)
        self.assertEqual({"ollama", "openai", "deepseek", "qwen"},
                         provider_module.SUPPORTED_PROVIDERS)


class ModelDataObjectTests(_RegistryFixture):
    """§3 冻结清单的形状：默认值、不可变性、§8 列镜像。"""

    def test_request_profile_is_frozen_with_reasoning_default(self):
        profile = RequestProfile(mode="rag", complexity="low", needs_tools=False,
                                 needs_stream=True)
        self.assertFalse(profile.needs_reasoning)
        with self.assertRaises(FrozenInstanceError):
            profile.mode = "chat"  # type: ignore[misc]

    def test_route_objects_hold_tuples_not_lists(self):
        candidate = RouteCandidate(model=self.model(), score=80)
        self.assertEqual((), candidate.reason_codes)
        plan = RoutePlan(primary=candidate, fallbacks=(candidate,))
        self.assertEqual(1, len(plan.fallbacks))
        with self.assertRaises(FrozenInstanceError):
            plan.primary = candidate  # type: ignore[misc]

    def test_llm_request_defaults_are_not_shared_between_instances(self):
        first = LLMRequest(messages=[{"role": "user", "content": "hi"}])
        first.tools.append({"type": "function"})
        second = LLMRequest(messages=[])
        self.assertEqual([], second.tools)      # 可变默认值必须是每实例一份
        self.assertEqual(0.2, second.temperature)
        self.assertIsNone(second.think)
        self.assertIsNone(second.num_predict)
        self.assertIsNone(second.keep_alive)

    def test_provider_message_shapes(self):
        call = ToolCall(id="c1", name="search", arguments={"q": "x"})
        response = LLMResponse(content="答", tool_calls=(call,), finish_reason="tool_calls",
                              model="phi3:mini", provider="ollama", input_tokens=3,
                              output_tokens=5, latency_ms=12.5)
        self.assertEqual(1, len(response.tool_calls))
        self.assertIsInstance(response.tool_calls[0], ToolCall)
        self.assertEqual(4096, self.model().limits.context_tokens)
        chunk = LLMChunk(text="a")
        self.assertFalse(chunk.finish)
        self.assertEqual("", LLMChunk().text)
        self.assertIsNone(LLMChunk().usage)
        self.assertEqual((8192, 2048),
                         (ModelLimits().context_tokens, ModelLimits().max_output_tokens))

    def test_usage_record_mirrors_section_eight_columns(self):
        # §8 冻结 19 列，顺序与列名逐字镜像；Task 5 直接按此建表，不得漂移。
        shipped = ("id", "trace_id", "request_id", "route_mode", "route_reason",
                   "provider", "model", "fallback_index", "input_tokens",
                   "output_tokens", "total_tokens", "ttft_ms", "latency_ms",
                   "estimated_cost", "currency", "success", "error_type",
                   "status_code", "created_at")
        self.assertEqual(shipped, tuple(f.name for f in fields(UsageRecord)))
        record = UsageRecord(trace_id="t", request_id="r", route_mode="rag",
                             route_reason=("CAPABILITY_MATCH",), provider="ollama",
                             model="phi3:mini", fallback_index=1, input_tokens=10,
                             output_tokens=20, total_tokens=30, ttft_ms=120.0,
                             latency_ms=900.0, estimated_cost=0.0, currency="USD",
                             success=True, error_type=None, status_code=200)
        self.assertIsNone(record.id)          # 自增主键与 created_at 交给 SQLite
        self.assertIsNone(record.created_at)

    def test_package_surface_is_re_exported(self):
        for name in llm.__all__:
            with self.subTest(symbol=name):
                self.assertIsNotNone(getattr(llm, name))
        self.assertIs(llm.RegistryError, RegistryError)
        self.assertIs(llm.ModelCapabilities, ModelCapabilities)


class RouterSettingsTests(_RegistryFixture):
    """§12 配置键：默认值、边界、`.env.example` 同步、无参构造仍可启动。"""

    ROUTER_FIELDS = (
        "llm_router_enabled", "llm_registry_file", "llm_total_budget_ms",
        "llm_model_timeout_seconds", "llm_retry_per_model", "llm_breaker_enabled",
        "llm_breaker_window", "llm_breaker_failure_ratio", "llm_breaker_open_seconds",
        "llm_breaker_half_open_probes", "deepseek_api_key", "deepseek_base_url",
        "qwen_api_key", "qwen_base_url",
    )

    def test_defaults_are_the_frozen_shipped_values(self):
        s = make_settings()
        self.assertTrue(s.llm_router_enabled)
        self.assertEqual("config/llm_registry.json", s.llm_registry_file)
        self.assertEqual(30000, s.llm_total_budget_ms)
        self.assertEqual(20, s.llm_model_timeout_seconds)
        self.assertEqual(1, s.llm_retry_per_model)
        self.assertTrue(s.llm_breaker_enabled)
        self.assertEqual(20, s.llm_breaker_window)
        self.assertEqual(0.30, s.llm_breaker_failure_ratio)
        self.assertEqual(60, s.llm_breaker_open_seconds)
        self.assertEqual(3, s.llm_breaker_half_open_probes)
        self.assertEqual("", s.deepseek_api_key.get_secret_value())
        self.assertEqual("", s.qwen_api_key.get_secret_value())
        self.assertEqual("https://api.deepseek.com/v1", s.deepseek_base_url)
        self.assertEqual("https://dashscope.aliyuncs.com/compatible-mode/v1",
                         s.qwen_base_url)
        # 默认注册表文件必须真实存在且能通过校验——出厂配置不该是坏配置。
        self.assertTrue(SHIPPED_REGISTRY.is_file())

    def test_out_of_range_values_are_rejected_at_construction(self):
        # 越界即 ValidationError：坏配置死在启动期，而不是运行期第一个请求。
        for name, bad in (
            ("llm_total_budget_ms", 4999), ("llm_total_budget_ms", 120001),
            ("llm_retry_per_model", -1), ("llm_retry_per_model", 3),
            ("llm_breaker_window", 7), ("llm_model_timeout_seconds", 0),
            ("llm_breaker_failure_ratio", 1.5), ("llm_breaker_half_open_probes", 0),
        ):
            with self.subTest(field=name, value=bad):
                with self.assertRaises(ValidationError):
                    make_settings(**{name: bad})

    def test_breaker_window_floor_matches_resilience_primitive(self):
        # 与 app/resilience.CircuitBreaker 的 window>=8 同轨（TypeSafe V2 同一教训）。
        from app.resilience import CircuitBreaker

        s = make_settings()
        CircuitBreaker(name="ollama", window=s.llm_breaker_window,
                       failure_ratio=s.llm_breaker_failure_ratio,
                       open_seconds=s.llm_breaker_open_seconds,
                       half_open_probes=s.llm_breaker_half_open_probes)
        with self.assertRaises(ValidationError):
            make_settings(llm_breaker_window=7)

    def test_env_example_documents_every_router_key_and_matches_defaults(self):
        text = (BACKEND_DIR / ".env.example").read_text(encoding="utf-8")
        documented: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            key, sep, value = stripped.partition("=")
            if sep and key.strip().startswith(("LLM_", "DEEPSEEK_", "QWEN_")):
                documented[key.strip()] = value.strip()
        required = {f.upper() for f in self.ROUTER_FIELDS}
        self.assertEqual(set(), required - set(documented),
                         msg=f".env.example 缺少 §12 键: {sorted(required - set(documented))}")
        reference = make_settings()
        with mock.patch.dict(os.environ, documented, clear=True):
            loaded = Settings(_env_file=None)   # 真实 env 解析路径（含 bool/SecretStr）
        for key, value in documented.items():
            name = key.lower()
            with self.subTest(key=key):
                self.assertIn(name, Settings.model_fields)
                if not value:
                    continue
                actual, expected = getattr(loaded, name), getattr(reference, name)
                if isinstance(expected, SecretStr):
                    actual, expected = actual.get_secret_value(), expected.get_secret_value()
                self.assertEqual(actual, expected)

    def test_argless_settings_still_constructs_on_host_env(self):
        # 无参 Settings() 是 app 的真实启动路径（读 backend/.env / OS env），不得因新键崩。
        # cwd 钉（Task 9 段 A / Task 5 复审 N3）：本例**刻意不覆盖** `llm_registry_file`，
        # 而它的出厂默认是相对路径 `config/llm_registry.json`（§12 冻结）⇒ 它按「当前工作目录」
        # 落地，从仓库根跑就会去找 `rag/config/`（不存在）。生产上 uvicorn 就从 `backend/` 起，
        # 所以这里把 cwd 钉到 `BACKEND_DIR`：轻修法，不动 §12 的冻结默认值，也不放宽断言——
        # 两种 cwd 跑全套件（`backend/` 与仓库根）现在得到同一组数字。
        original_cwd = os.getcwd()
        os.chdir(BACKEND_DIR)
        self.addCleanup(os.chdir, original_cwd)
        s = Settings()
        self.assertIn(s.llm_router_enabled, (True, False))
        self.assertIsInstance(s.deepseek_api_key, SecretStr)
        self.assertTrue(load_registry(s.llm_registry_file).models)


# ==========================================================================
# Task 2：errors（§6 三分类）+ normalize（两侧报文）+ provider（唯一出口）+ health（probe 收编）
#
# 报文级断言全部走 `httpx.MockTransport`：注入点是 `app.llm.provider._transport`，
# 所以「假传输 + 真 provider 代码路径」——header、URL、payload 形状、usage 提取、异常归类
# 都是端到端结果，不是对 mock 的自说自话。
# ==========================================================================

OLLAMA_URL = "http://ollama.test:11434"
OPENAI_URL = "https://api.openai.test/v1"
OLLAMA_CHAT_URL = OLLAMA_URL + "/api/chat"
OPENAI_CHAT_URL = OPENAI_URL + "/chat/completions"


class Recorded:
    """一次被拦截的请求：url / headers（小写键）/ json 请求体。"""

    def __init__(self, request: httpx.Request) -> None:
        self.url = str(request.url)
        self.method = request.method
        self.headers = {k.lower(): v for k, v in request.headers.items()}
        self.raw = request.read()
        self.payload = json.loads(self.raw.decode("utf-8")) if self.raw else None


def _response(status: int = 200, *, json_body=None, content=None, text: str = "") -> httpx.Response:
    if json_body is not None:
        return httpx.Response(status, json=json_body)
    if content is not None:
        return httpx.Response(status, content=content)
    return httpx.Response(status, text=text)


def ollama_def(**overrides) -> ModelDefinition:
    data = {
        "id": "ollama-phi3", "provider": "ollama", "model": "phi3:mini",
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": False, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 80, "rag": 80, "tools": 0},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def openai_def(**overrides) -> ModelDefinition:
    data = {
        "id": "openai", "provider": "openai", "model": "gpt-4.1-mini",
        "enabled": True, "external": True,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 90, "rag": 90, "tools": 100},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def request_of(**overrides) -> LLMRequest:
    data: dict = {"messages": [{"role": "user", "content": "问题"}]}
    data.update(overrides)
    return LLMRequest.model_validate(data)


class _EgressFixture(unittest.TestCase):
    """公共底座：清 env + 打桩 settings + 注入 MockTransport + 请求录制。"""

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        reset_registry()
        self.addCleanup(reset_registry)
        health_module.reset_health_cache()
        self.addCleanup(health_module.reset_health_cache)
        self.requests: list[Recorded] = []
        self.use_settings()

    def use_settings(self, **overrides) -> Settings:
        base = {
            "ollama_base_url": OLLAMA_URL,
            "ollama_model": "ornith-1.5:9b-text",
            "ollama_keep_alive": "30m",
            "openai_base_url": OPENAI_URL,
            "openai_api_key": "",
            "openai_model": "gpt-4.1-mini",
        }
        base.update(overrides)
        fake = make_settings(**base)
        for module, attribute in ((registry_module, "settings"), (health_module, "settings"),
                                  (rag_module, "settings")):
            if hasattr(module, attribute):
                patcher = mock.patch.object(module, attribute, fake)
                patcher.start()
                self.addCleanup(patcher.stop)
        return fake

    def serve(self, responder) -> None:
        """responder: `httpx.Response` | `(status, json_body)` | `callable(request) -> Response`。"""

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(Recorded(request))
            if callable(responder):
                return responder(request)
            if isinstance(responder, httpx.Response):
                return responder
            status, body = responder
            return _response(status, json_body=body)

        patcher = mock.patch.object(provider_module, "_transport",
                                    httpx.MockTransport(handler))
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve_sequence(self, *responders: httpx.Response) -> None:
        """按次序应答（重试/降级用例：同一端点两次不同结果）。"""
        queue = list(responders)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(Recorded(request))
            return queue.pop(0) if len(queue) > 1 else queue[0]

        patcher = mock.patch.object(provider_module, "_transport",
                                    httpx.MockTransport(handler))
        patcher.start()
        self.addCleanup(patcher.stop)

    @property
    def last(self) -> Recorded:
        self.assertTrue(self.requests, "期望 provider 发出过至少一次请求")
        return self.requests[-1]


# --------------------------------------------------------------------------
# errors.py：§6 映射表逐码
# --------------------------------------------------------------------------
class ErrorClassificationTests(unittest.TestCase):
    def test_retryable_status_table_is_code_by_code(self):
        # §6 冻结的六个码：可重试（同模型重试 1 次），仍可 fallback。
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertEqual(errors.RETRYABLE_STATUSES, frozenset(
                    {408, 429, 500, 502, 503, 504}))
                error = errors.classify(status, "gateway busy")
                self.assertEqual("retryable", error.kind)
                self.assertEqual(status, error.status_code)
                self.assertTrue(error.retryable)
                self.assertTrue(error.fallback_allowed)

    def test_auth_statuses_are_config_not_retryable(self):
        for status in (401, 403):
            with self.subTest(status=status):
                error = errors.classify(status, "invalid api key")
                self.assertEqual("config", error.kind)
                self.assertTrue(error.is_config)
                self.assertFalse(error.retryable)
                # 401/403 的语义是「本次请求内跳过该 provider 其余候选」，不是全站终止：
                # 凭据互相独立的下一个 provider 仍然可用（spec §6）。
                self.assertTrue(error.fallback_allowed)

    def test_bad_request_statuses_allow_fallback_but_no_retry(self):
        for status in (400, 404, 422):
            with self.subTest(status=status):
                error = errors.classify(status, "bad request")
                self.assertEqual("hard", error.kind)
                self.assertFalse(error.retryable)
                self.assertTrue(error.fallback_allowed)
                self.assertFalse(error.no_fallback)

    def test_model_unavailable_body_markers(self):
        # §6 逐字列出的四个 body 特征；kind 独立于 retryable，但照样可以 fallback。
        for marker in ("cannot alloc memory", "failed to load model",
                       "model not found", "no such model"):
            with self.subTest(marker=marker):
                error = errors.classify(500, marker)
                self.assertEqual("model_unavailable", error.kind)
                self.assertTrue(error.fallback_allowed)
                # 冻结项：对同一个加载失败的模型再发一次只是白等超时。
                self.assertFalse(error.retryable)

    def test_hard_terminal_body_markers_are_no_fallback(self):
        # 「请求体超限 / 工具 schema 非法 / 能力不支持」= NO_FALLBACK，直接返回业务错误。
        for marker in ("payload too large", "payload_too_large", "invalid tool schema",
                       "this model is unsupported", "context_length_exceeded"):
            with self.subTest(marker=marker):
                error = errors.classify(400, marker)
                self.assertEqual("hard", error.kind)
                self.assertTrue(error.no_fallback)
                self.assertFalse(error.fallback_allowed)

    def test_model_unavailable_marker_wins_over_no_fallback_marker(self):
        # Ollama 的加载失败文案里常混着 "unsupported" 之类字样：它是「换模型」不是「请求不合法」。
        error = errors.classify(500, "failed to load model: unsupported architecture")
        self.assertEqual("model_unavailable", error.kind)
        self.assertTrue(error.fallback_allowed)

    def test_config_status_is_decided_before_any_body_marker(self):
        # 评审 I-1（§10 矩阵 #7）：401/403 的判定**前置**于两组 body 特征。
        # 网关的凭据/地域拒绝习惯把 `unsupported` 之类字样写进 message，那是
        # `PROVIDER_CONFIG_FAILED` 的原料——不是 NO_FALLBACK 硬终态，也不是「换模型」。
        bodies = (
            ('{"error":{"message":"The region is unsupported for your credentials"}}', "region"),
            ('{"error":{"message":"no such model for this key"}}', "no such model"),
            ("cannot alloc a new session for this tenant", "alloc"),
        )
        for status in (401, 403):
            for body, fragment in bodies:
                with self.subTest(status=status, body=body[:40]):
                    error = errors.classify(status, body)
                    self.assertEqual("config", error.kind)
                    self.assertTrue(error.is_config)
                    self.assertFalse(error.retryable)
                    self.assertFalse(error.no_fallback)
                    # 401/403 仍允许 fallback（凭据互相独立的下一个 provider 可用）。
                    self.assertTrue(error.fallback_allowed)
                    self.assertEqual(status, error.status_code)
                    # 归类让位给状态码，但原文摘要照旧进消息（运维要看网关说了什么）。
                    self.assertIn(fragment, str(error))

    def test_quoted_model_name_not_found_is_model_unavailable(self):
        # 评审 I-2：真机 Ollama 缺模型回的是 `model 'x' not found` / `model "x" not found`
        # ——模型名夹在引号中间，§6 冻结的四枚字面一枚都不命中（`model not found` 是连续的）。
        # 修法只**增补**一枚窄正则，冻结字面一字不动（下一行就是这个断言）。
        self.assertEqual(("alloc", "failed to load", "model not found", "no such model"),
                         errors.MODEL_UNAVAILABLE_MARKERS)
        forms = (
            "model 'x' not found",
            'model "x" not found',
            '{"error":"model \\"phi3:mini\\" not found"}',   # HTTP body 的真实形状：引号带 JSON 转义
            'model "phi3:mini"\nnot found',                  # `\s+` 能吃换行（下一段钉消息面）
        )
        for body in forms:
            for status in (404, 500):
                with self.subTest(status=status, body=repr(body)[:48]):
                    error = errors.classify(status, body)
                    self.assertEqual("model_unavailable", error.kind)
                    self.assertTrue(error.fallback_allowed)
                    self.assertFalse(error.retryable)          # 冻结项：不重试当前模型
                    self.assertEqual(status, error.status_code)
        # D3 日志面：命中片段进消息前必须和 body 摘要一样压平（正则里有 `\s+`，能吃换行）。
        message = str(errors.classify(404, 'model "phi3:mini"\nnot found'))
        self.assertNotIn("\n", message)
        self.assertNotIn("\r", message)
        self.assertLess(len(message), 300)

    def test_quoted_model_regex_leaves_other_not_found_shapes_alone(self):
        # 反向钉（评审 I-2）：两种「含 not found 却不是模型未加载」的形态不得被吞。
        schema = errors.classify(400, "Invalid parameter: 'tool_choice' not found in schema")
        self.assertEqual("hard", schema.kind)                  # 仍是可 fallback 的 hard
        self.assertFalse(schema.no_fallback)
        self.assertTrue(schema.fallback_allowed)
        gateway = errors.classify(404, "404 page not found")   # 网关页，不是 Ollama
        self.assertEqual("hard", gateway.kind)                 # 按表：404 = non-retryable-hard
        self.assertFalse(gateway.retryable)
        self.assertTrue(gateway.fallback_allowed)
        self.assertIsNone(errors.classify(200, "404 page not found"))

    def test_unlisted_statuses_have_defined_buckets(self):
        # spec 只枚举常见码；实现必须对全码表有定义，否则未知码会掉回 None 而被当成成功。
        cases = {501: "retryable", 507: "retryable", 405: "hard", 409: "hard",
                 413: "hard", 418: "hard", 451: "hard"}
        for status, kind in cases.items():
            with self.subTest(status=status):
                error = errors.classify(status, "unexpected")
                self.assertIsNotNone(error)
                self.assertEqual(kind, error.kind)
                self.assertTrue(error.fallback_allowed)

    def test_success_statuses_classify_as_no_error(self):
        for status in (200, 204, 301, 307):
            with self.subTest(status=status):
                self.assertIsNone(errors.classify(status, "all good"))

    def test_from_response_never_returns_none(self):
        # 200 却带错误体（Ollama 流内 error 帧）：不能归成「没有错误」。
        error = errors.from_response(200, "model not found")
        self.assertEqual("model_unavailable", error.kind)
        error = errors.from_response(200, "")
        self.assertEqual("retryable", error.kind)
        self.assertEqual(200, error.status_code)

    def test_timeout_and_connection_exceptions_are_retryable(self):
        cases = (
            httpx.ConnectTimeout("timed out"), httpx.ReadTimeout("timed out"),
            httpx.WriteTimeout("timed out"), httpx.PoolTimeout("timed out"),
            httpx.ConnectError("connection refused"),
            httpx.ReadError("read error"),
            httpx.RemoteProtocolError("peer closed connection"),
        )
        for exc in cases:
            with self.subTest(exc=type(exc).__name__):
                error = errors.from_exception(exc)
                self.assertEqual("retryable", error.kind)
                self.assertIsNone(error.status_code)
                self.assertTrue(error.retryable)
                self.assertTrue(error.fallback_allowed)

    def test_http_status_error_goes_through_the_table(self):
        request = httpx.Request("POST", OLLAMA_CHAT_URL)
        response = httpx.Response(429, request=request, text="rate limited")
        exc = httpx.HTTPStatusError("429", request=request, response=response)
        error = errors.from_exception(exc)
        self.assertEqual("retryable", error.kind)
        self.assertEqual(429, error.status_code)
        self.assertIn("rate limited", str(error))

    def test_malformed_json_is_hard_not_a_crash(self):
        # §10 矩阵 #8：malformed JSON 必须「归类正确」——是 hard（可 fallback），不是 retryable。
        for exc in (json.JSONDecodeError("x", "<html>", 0), ValueError("nope")):
            with self.subTest(exc=type(exc).__name__):
                error = errors.from_exception(exc)
                self.assertEqual("hard", error.kind)
                self.assertFalse(error.retryable)
                self.assertTrue(error.fallback_allowed)

    def test_llmerror_passes_through_and_unknown_exception_is_contained(self):
        original = errors.LLMError("config", 401, "凭据被拒")
        self.assertIs(original, errors.from_exception(original))
        unexpected = errors.from_exception(RuntimeError("boom"))
        self.assertEqual("hard", unexpected.kind)
        self.assertTrue(unexpected.fallback_allowed)

    def test_error_message_excerpt_is_bounded_and_flattened(self):
        # D3：错误消息会被写日志/进 trace，body 摘要必须截断且不带换行（不整段搬回模型输出）。
        body = "line1\nline2\r\n" + ("x" * 500)
        message = str(errors.classify(500, body))
        self.assertLess(len(message), 300)
        self.assertNotIn("\n", message)
        self.assertNotIn("\r", message)


# --------------------------------------------------------------------------
# normalize.py：报文形状（Ollama 逐字平移 agent.py）
# --------------------------------------------------------------------------
class OllamaPayloadShapeTests(unittest.TestCase):
    """`agent.py::_ollama_chat` 的构造逐字平移：键序、空 tools 带键、think/keep_alive 形状。"""

    def test_tool_routing_turn_matches_agent_payload_field_by_field(self):
        req = request_of(
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
            tools=[{"type": "function", "function": {"name": "enterprise_search"}}],
            temperature=0.2, think=True, keep_alive="30m", num_predict=768)
        payload = normalize.ollama_payload(req, "ornith-1.5:9b-text")
        self.assertEqual({
            "model": "ornith-1.5:9b-text",
            "stream": False,
            "think": True,
            "keep_alive": "30m",
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
            "tools": [{"type": "function",
                       "function": {"name": "enterprise_search"}}],
            "options": {"temperature": 0.2, "num_predict": 768},
        }, payload)
        # 键序也照抄现网：Ollama 不关心顺序，但顺序一致才让「逐字平移」可被 diff 验证。
        self.assertEqual(["model", "stream", "think", "keep_alive", "messages", "tools",
                          "options"], list(payload))

    def test_empty_tools_still_emits_the_tools_key_like_production(self):
        # 现网 synthesis 轮（agent.py `_ollama_chat(messages, [])`）发的是 `"tools": []`，
        # 不是省略键：部分 Ollama 版本对「无键」与「空数组」的工具模板处理不同。
        payload = normalize.ollama_payload(
            request_of(think=False, keep_alive="30m", num_predict=512), "phi3:mini")
        self.assertIn("tools", payload)
        self.assertEqual([], payload["tools"])
        self.assertFalse(payload["think"])
        self.assertEqual(512, payload["options"]["num_predict"])

    def test_optional_keys_are_omitted_not_falsy_when_unset(self):
        # rag 的 legacy Ollama 请求根本不发 think/keep_alive/options.num_predict。
        # `None` ⇒ 整键省略，这样一个模块同时平移得动两种现网形状（而不是恒发 false）。
        payload = normalize.ollama_payload(request_of(), "phi3:mini")
        self.assertNotIn("think", payload)
        self.assertNotIn("keep_alive", payload)
        self.assertEqual({"temperature": 0.2}, payload["options"])
        self.assertTrue(payload["stream"] is False)

    def test_num_predict_is_coerced_to_int_for_ollama_options(self):
        payload = normalize.ollama_payload(request_of(num_predict=512.0), "phi3:mini")
        self.assertIsInstance(payload["options"]["num_predict"], int)

    def test_payload_does_not_mutate_the_request(self):
        req = request_of(messages=[
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-a", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "甲"}}}]},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}"},
        ], tools=[{"type": "function"}])
        baseline = [{"role": "user", "content": "问题"},
                    {"role": "assistant", "content": "", "tool_calls": [
                        {"id": "call-a", "type": "function",
                         "function": {"name": "enterprise_search",
                                      "arguments": {"query": "甲"}}}]},
                    {"role": "tool", "tool_name": "enterprise_search", "content": "{}"}]
        normalize.ollama_payload(req, "phi3:mini", stream=True)
        normalize.openai_payload(req, "phi3:mini", stream=True)
        self.assertEqual([{"type": "function"}], req.tools)
        # I-4（Task 9 段 B）升级：`openai_payload` 出口前的映射是**副本**上的动作。
        # 这里必须钉整份 messages：`dict(m)` 只是浅拷贝，映射若就地改
        # `tool_calls[].function.arguments` / 把 `tool_name` 换成 `tool_call_id`，
        # 下一轮 Ollama 腿与 `run_agent` 读到的就是被改坏的形状（原来只钉一条 user 消息，
        # 挡不住这个；同一条事实的幂等面见 `OpenAIMultiTurnReplayTests`）。
        self.assertEqual(baseline, req.messages)


class OpenAIPayloadShapeTests(unittest.TestCase):
    def test_payload_carries_temperature_from_the_request_not_a_layer_default(self):
        # 「默认对齐 rag.py 现值 0.1 由 LLMRequest 携带」：本层只透传，rag 链自己带 0.1。
        # 评审 I-4：常量的**单一出处**挪到包级别（构造 LLMRequest 的是调用方，不是报文层），
        # normalize 里不留第二个符号；包 docstring 把 Task 6 的义务写在文本上。
        self.assertEqual(0.1, llm.RAG_LEGACY_TEMPERATURE)
        self.assertIn("RAG_LEGACY_TEMPERATURE", llm.__all__)
        self.assertIn("RAG_LEGACY_TEMPERATURE", llm.__doc__ or "")
        self.assertFalse(hasattr(normalize, "RAG_LEGACY_TEMPERATURE"))
        self.assertEqual(0.1, normalize.openai_payload(
            request_of(temperature=0.1), "gpt-4.1-mini")["temperature"])
        self.assertEqual(0.2, normalize.openai_payload(
            request_of(), "gpt-4.1-mini")["temperature"])
        # Ollama 侧同源：options.temperature 也是透传，本层不注入 0.1。
        self.assertEqual(0.1, normalize.ollama_payload(
            request_of(temperature=0.1), "phi3:mini")["options"]["temperature"])

    def test_tools_key_is_absent_when_empty_and_stream_false_for_complete(self):
        payload = normalize.openai_payload(request_of(), "gpt-4.1-mini")
        self.assertEqual({
            "model": "gpt-4.1-mini",
            "messages": [{"role": "user", "content": "问题"}],
            "temperature": 0.2,
            "stream": False,
        }, payload)
        with_tools = normalize.openai_payload(
            request_of(tools=[{"type": "function"}], num_predict=128), "gpt-4.1-mini")
        self.assertEqual([{"type": "function"}], with_tools["tools"])
        self.assertEqual(128, with_tools["max_tokens"])   # num_predict → max_tokens

    def test_stream_payload_asks_for_the_final_usage_block(self):
        # 不发 include_usage 就拿不到末尾 usage 帧 ⇒ §8 记账与 §6 usage 提取都会静默失效。
        payload = normalize.openai_payload(request_of(), "gpt-4.1-mini", stream=True)
        self.assertTrue(payload["stream"])
        self.assertEqual({"include_usage": True}, payload["stream_options"])


# --------------------------------------------------------------------------
# normalize.py：响应解析
# --------------------------------------------------------------------------
class ResponseParsingTests(unittest.TestCase):
    def test_openai_complete_response_extracts_usage_and_finish_reason(self):
        parsed = normalize.parse_openai_response({
            "model": "gpt-4.1-mini-2025", "choices": [{"finish_reason": "stop",
                                                       "message": {"role": "assistant",
                                                                   "content": "答案"}}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 7},
        }, "gpt-4.1-mini", "openai", 12.5)
        self.assertEqual(("答案", "stop", 21, 7, 12.5),
                         (parsed.content, parsed.finish_reason, parsed.input_tokens,
                          parsed.output_tokens, parsed.latency_ms))
        # 响应模型名取 provider 回显值：usage 归因要指向真正被调用的那个模型（§9）。
        self.assertEqual("gpt-4.1-mini-2025", parsed.model)
        self.assertFalse(parsed.usage_estimated)

    def test_ollama_complete_response_reads_message_and_eval_counts(self):
        parsed = normalize.parse_ollama_response({
            "model": "phi3:mini", "done_reason": "length",
            "message": {"role": "assistant", "content": "本地答案"},
            "prompt_eval_count": 33, "eval_count": 9,
        }, "phi3:mini", "ollama", 3.0)
        self.assertEqual(("本地答案", "length", 33, 9),
                         (parsed.content, parsed.finish_reason, parsed.input_tokens,
                          parsed.output_tokens))
        self.assertEqual("ollama", parsed.provider)
        self.assertFalse(parsed.usage_estimated)

    def test_missing_usage_is_zero_plus_in_memory_estimate_flag(self):
        bodies = {
            "openai": (normalize.parse_openai_response,
                       {"choices": [{"message": {"content": "x"}}]}, "phi3", "openai"),
            "ollama": (normalize.parse_ollama_response,
                       {"message": {"content": "x"}, "done": True}, "phi3", "ollama"),
        }
        for label, (parser, body, model_name, provider_name) in bodies.items():
            with self.subTest(provider=label):
                parsed = parser(body, model_name, provider_name, 1.0)
                self.assertEqual((0, 0), (parsed.input_tokens, parsed.output_tokens))
                self.assertTrue(parsed.usage_estimated)
                # §8 冻结 19 列里没有 estimated：旗标只活在内存/trace。
                self.assertNotIn("estimated",
                                 {f.name for f in fields(UsageRecord)} - {"estimated_cost"})
                self.assertNotIn("estimated", UsageRecord().__dict__)

    def test_non_integer_token_counts_are_treated_as_missing(self):
        parsed = normalize.parse_openai_response({
            "choices": [{"message": {"content": "x"}}],
            "usage": {"prompt_tokens": "12", "completion_tokens": None},
        }, "m", "openai", 1.0)
        self.assertEqual((0, 0), (parsed.input_tokens, parsed.output_tokens))
        self.assertTrue(parsed.usage_estimated)

    def test_reasoning_content_is_never_read(self):
        # D3：CoT/reasoning 不得进入任何被下游消费的对象（更不许进 prompt/context 存储）。
        parsed = normalize.parse_openai_response({
            "choices": [{"message": {"content": "正文", "reasoning": "SECRET-THINKING",
                                     "reasoning_content": "SECRET-THINKING"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }, "m", "openai", 1.0)
        self.assertEqual("正文", parsed.content)
        self.assertNotIn("SECRET-THINKING", repr(parsed.model_dump()))

    def test_missing_structures_raise_llmerror_not_keyerror(self):
        for label, call in (
            ("openai 无 choices",
             lambda: normalize.parse_openai_response({}, "m", "openai", 1.0)),
            ("ollama 无 message",
             lambda: normalize.parse_ollama_response({"done": True}, "m", "ollama", 1.0)),
        ):
            with self.subTest(case=label):
                with self.assertRaises(errors_module.LLMError) as ctx:
                    call()
                self.assertEqual("hard", ctx.exception.kind)
        # Ollama 的文案与 agent.py 现网 RuntimeError 一致（迁移时运维读到的字没变）。
        with self.assertRaises(errors_module.LLMError) as ctx:
            normalize.parse_ollama_response({"done": True}, "m", "ollama", 1.0)
        self.assertIn("Ollama 返回缺少 message", str(ctx.exception))


class ToolCallStandardisationTests(unittest.TestCase):
    def test_openai_string_arguments_are_parsed_into_dict(self):
        calls = normalize.parse_openai_tool_calls([
            {"id": "call_1", "type": "function",
             "function": {"name": "enterprise_search",
                          "arguments": "{\"query\": \"年假\", \"top_k\": 5}"}},
        ])
        self.assertEqual((1,), (len(calls),))
        self.assertEqual(("call_1", "enterprise_search", {"query": "年假", "top_k": 5}),
                         (calls[0].id, calls[0].name, calls[0].arguments))
        self.assertIsInstance(calls[0].arguments, dict)

    def test_ollama_object_arguments_and_absent_id_are_normalised(self):
        # Ollama 回的是对象且没有 id：id 保持空串（Task 8 不得假设唯一 id）。
        parsed = normalize.parse_ollama_response({
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "web_search",
                                                     "arguments": {"query": "q"}}}]},
            "done_reason": "stop", "done": True,
        }, "phi3:mini", "ollama", 2.0)
        self.assertEqual(1, len(parsed.tool_calls))
        self.assertEqual("", parsed.tool_calls[0].id)
        self.assertEqual({"query": "q"}, parsed.tool_calls[0].arguments)

    def test_broken_arguments_degrade_to_empty_dict_instead_of_raising(self):
        # 现网 `agent.py::_tool_arguments` 的口径：坏 JSON / 非对象 ⇒ {}，让工具自己报缺参。
        cases = ['{"query":', "not json", "[1, 2]", 7, None, ""]
        for raw in cases:
            with self.subTest(arguments=raw):
                calls = normalize.parse_openai_tool_calls(
                    [{"id": "c", "function": {"name": "t", "arguments": raw}}])
                self.assertEqual({}, calls[0].arguments)
        self.assertEqual((), normalize.parse_openai_tool_calls(None))
        self.assertEqual((), normalize.parse_openai_tool_calls(["oops", 3]))


# --------------------------------------------------------------------------
# normalize.py：流式解析
# --------------------------------------------------------------------------
class StreamParsingTests(unittest.TestCase):
    def test_openai_sse_delta_lines_then_done_and_usage(self):
        frames = [
            b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"\xe5\xa5\xbd"}}]}\n\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2}}\n\n',
            b'data: [DONE]\n\n',
        ]
        chunks = list(normalize.openai_stream_lines(iter(frames)))
        self.assertEqual("你好", "".join(c.text for c in chunks))
        self.assertTrue(chunks[-1].finish)
        self.assertEqual({"input_tokens": 9, "output_tokens": 2, "total_tokens": 11,
                          "estimated": False}, chunks[-1].usage)

    def test_openai_sse_skips_comments_and_heartbeats(self):
        frames = [b': keep-alive\n\n', b'\n', b'event: message\n',
                  b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n', b'data: [DONE]\n']
        self.assertEqual("ok", "".join(c.text
                                       for c in normalize.openai_stream_lines(iter(frames))))

    def test_openai_stream_without_done_marker_is_classified_not_silently_truncated(self):
        frames = [b'data: {"choices":[{"delta":{"content":"\xe4\xb8\xad"}}]}\n\n']
        with self.assertRaises(errors_module.LLMError) as ctx:
            list(normalize.openai_stream_lines(iter(frames)))
        self.assertEqual("retryable", ctx.exception.kind)   # 没吐字前失败 = 可静默换模型
        self.assertEqual(200, ctx.exception.status_code)
        self.assertIn("[DONE]", str(ctx.exception))

    def test_ollama_ndjson_stream_with_done_and_eval_counts(self):
        body = (
            b'{"message":{"role":"assistant","content":"\xe7\xad\x94"},"done":false}\n'
            b'{"message":{"role":"assistant","content":"\xe6\xa1\x88"},"done":false}\n'
            b'{"message":{"role":"assistant","content":""},"done":true,'
            b'"done_reason":"stop","prompt_eval_count":14,"eval_count":6}\n'
        )
        chunks = list(normalize.ollama_stream_lines([body]))
        self.assertEqual("答案", "".join(c.text for c in chunks))
        self.assertTrue(chunks[-1].finish)
        self.assertEqual({"input_tokens": 14, "output_tokens": 6, "total_tokens": 20,
                          "estimated": False}, chunks[-1].usage)

    def test_ollama_stream_without_done_is_an_error(self):
        # 与 native_stream.py 同语义：未收到 done=true 不得当成成功（否则会落一条截断答案）。
        with self.assertRaises(errors_module.LLMError) as ctx:
            list(normalize.ollama_stream_lines(
                [b'{"message":{"content":"\xe5\x8d\x8a"},"done":false}\n']))
        self.assertEqual("retryable", ctx.exception.kind)
        self.assertIn("done=true", str(ctx.exception))

    def test_ollama_in_stream_error_frame_is_classified_by_body(self):
        # 200 状态里的 {"error": ...}：模型没加载成功要归成 model_unavailable，不能掩成成功。
        with self.assertRaises(errors_module.LLMError) as ctx:
            list(normalize.ollama_stream_lines(
                [b'{"error":"failed to load model: cannot alloc memory"}\n']))
        self.assertEqual("model_unavailable", ctx.exception.kind)

    def test_malformed_stream_line_is_hard_not_crash(self):
        for label, line in (("ollama", b'<html>500</html>\n'),
                            ("openai", b'data: {oops}\n\n')):
            with self.subTest(protocol=label):
                parser = (normalize.ollama_stream_lines if label == "ollama"
                          else normalize.openai_stream_lines)
                with self.assertRaises(errors_module.LLMError) as ctx:
                    list(parser([line]))
                self.assertEqual("hard", ctx.exception.kind)
                self.assertIn("Ollama" if label == "ollama" else "OpenAI",
                              str(ctx.exception))

    def test_multibyte_character_split_across_packets_survives(self):
        # 中文场景必测：一个汉字的 3 个字节落在两个分片里。逐包 decode 会抛
        # UnicodeDecodeError（或 errors=replace 把字打烂），增量解码器把尾部扣住续上。
        whole = '{"message":{"role":"assistant","content":"企业知识库验收"},"done":true}\n'
        encoded = whole.encode("utf-8")
        cut = encoded.index("知".encode("utf-8")) + 1          # 正好切在字符中间
        chunks = [encoded[:cut], encoded[cut:]]
        for size in (1, 2, 3, 7):                              # 逐字节喂也不丢字
            pieces = [encoded[i:i + size] for i in range(0, len(encoded), size)]
            with self.subTest(chunk_size=size):
                out = list(normalize.ollama_stream_lines(iter(pieces)))
                self.assertEqual("企业知识库验收", "".join(c.text for c in out))
        with self.subTest("split pair"):
            out = list(normalize.ollama_stream_lines(iter(chunks)))
            self.assertEqual("企业知识库验收", "".join(c.text for c in out))

    def test_line_is_not_parsed_until_newline_arrives(self):
        # 半行 JSON 不进解析器（否则会拿残缺串去 json.loads 报硬错）。
        payload = b'{"message":{"content":"abc"},"done":true}\n'
        out = list(normalize.ollama_stream_lines([payload[:12], payload[12:]]))
        self.assertEqual("abc", "".join(c.text for c in out))


# --------------------------------------------------------------------------
# provider.py：唯一出口
# --------------------------------------------------------------------------
class ProviderCompleteTests(_EgressFixture):
    def test_ollama_complete_request_line_is_single_egress(self):
        self.serve(_response(200, json_body={
            "model": "phi3:mini", "message": {"role": "assistant", "content": "本地答案"},
            "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 4}))
        response = provider_module.complete(
            ollama_def(), request_of(think=False, keep_alive="30m", num_predict=512), 5.0)
        self.assertEqual(OLLAMA_CHAT_URL, self.last.url)
        self.assertEqual("POST", self.last.method)
        self.assertNotIn("authorization", self.last.headers)     # D1：ollama 恒无 key
        self.assertEqual({"model": "phi3:mini", "stream": False, "think": False,
                          "keep_alive": "30m",
                          "messages": [{"role": "user", "content": "问题"}],
                          "tools": [],
                          "options": {"temperature": 0.2, "num_predict": 512}},
                         self.last.payload)
        self.assertEqual(("本地答案", 12, 4, "ollama"),
                         (response.content, response.input_tokens, response.output_tokens,
                          response.provider))
        self.assertGreaterEqual(response.latency_ms, 0.0)

    def test_openai_complete_sends_bearer_and_reads_usage(self):
        self.use_settings(openai_api_key="sk-test-only-in-egress")
        self.serve(_response(200, json_body={
            "model": "gpt-4.1-mini",
            "choices": [{"finish_reason": "stop",
                         "message": {"role": "assistant", "content": "云端答案"}}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 11}}))
        response = provider_module.complete(openai_def(), request_of(), 5.0)
        self.assertEqual(OPENAI_CHAT_URL, self.last.url)
        self.assertEqual("Bearer sk-test-only-in-egress", self.last.headers["authorization"])
        self.assertEqual("application/json", self.last.headers["content-type"])
        self.assertEqual((30, 11), (response.input_tokens, response.output_tokens))
        self.assertEqual("openai", response.provider)
        # key 只活在一次请求里：不得出现在响应对象/异常文本（D3/D6）。
        self.assertNotIn("sk-test", repr(response.model_dump()))

    def test_ollama_never_carries_an_authorization_header_even_if_env_is_set(self):
        # D1：ollama 恒无 key。宿主误设 OLLAMA_API_KEY 也不得被外带到 /api/chat。
        os.environ["OLLAMA_API_KEY"] = "should-be-ignored"
        self.serve(_response(200, json_body={"message": {"content": "x"}, "done": True}))
        provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertNotIn("authorization", self.last.headers)

    def test_model_override_replaces_the_requested_model(self):
        # Task 1 移交项：ProviderCredentials.model_override 非空 ⇒ 替换请求模型名。
        # 走 OS env 而不是 Settings：`ollama_model_override` 不是 §12 的键（D1 的 env 约定）。
        os.environ["OLLAMA_MODEL_OVERRIDE"] = "override:latest"
        self.serve(_response(200, json_body={"message": {"content": "x"}, "done": True}))
        provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertEqual("override:latest", self.last.payload["model"])

    def test_provider_response_without_model_echoes_the_effective_model(self):
        # 无回显时取「替换后的名字」，于是 usage/trace 归因仍指向真正调用的模型。
        os.environ["OLLAMA_MODEL_OVERRIDE"] = "override:latest"
        self.serve(_response(200, json_body={"message": {"content": "x"}, "done": True}))
        response = provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertEqual("override:latest", response.model)

    def test_unknown_provider_is_a_hard_terminal_no_fallback(self):
        model = ollama_def(id="moonshot-k1", provider="moonshot", model="kimi-k1")
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(model, request_of(), 5.0)
        self.assertEqual("hard", ctx.exception.kind)
        self.assertTrue(ctx.exception.no_fallback)
        self.assertEqual([], self.requests)          # 分发失败不发请求

    def test_missing_base_url_becomes_config_error(self):
        self.use_settings(ollama_base_url="")
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertEqual("config", ctx.exception.kind)
        self.assertIn("凭据不可用", str(ctx.exception))
        self.assertEqual([], self.requests)

    def test_openai_compat_without_key_fails_fast_as_config(self):
        # 不发一次注定 401 的往返（Task 4 直接拿到 PROVIDER_CONFIG_FAILED 的原料）。
        self.serve(_response(401, json_body={"error": "nope"}))
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(openai_def(), request_of(), 5.0)
        self.assertEqual("config", ctx.exception.kind)
        self.assertEqual([], self.requests)

    def test_http_error_statuses_surface_as_classified_llmerror(self):
        cases = {429: "retryable", 500: "retryable", 400: "hard", 404: "hard",
                 401: "config", 403: "config"}
        for status, kind in cases.items():
            with self.subTest(status=status):
                self.use_settings(openai_api_key="sk-test")
                self.serve(_response(status, json_body={"error": {"message": "upstream"}}))
                with self.assertRaises(errors_module.LLMError) as ctx:
                    provider_module.complete(openai_def(), request_of(), 5.0)
                self.assertEqual(kind, ctx.exception.kind)
                self.assertEqual(status, ctx.exception.status_code)

    def test_load_failure_500_is_model_unavailable_for_the_real_failover_case(self):
        # REAL-LLM-FAILOVER-001 的归类前提：ornith 加载失败（500 + alloc/failed to load）
        # 必须是 model_unavailable，Task 4 才能立刻换 phi3。
        self.serve(_response(500, text='{"error":"failed to load model: cannot alloc"}'))
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(ollama_def(model="ornith-1.5:9b-text"),
                                     request_of(), 5.0)
        self.assertEqual("model_unavailable", ctx.exception.kind)
        self.assertTrue(ctx.exception.fallback_allowed)

    def test_real_ollama_404_model_not_found_body_is_model_unavailable(self):
        # 评审 I-2 的端到端面：真机 Ollama 缺模型回 404 + JSON 转义引号的 body，
        # 经 `complete()`（而不是只对 classify 单测）也必须落到 model_unavailable，
        # 否则 Task 10 的「模型名写错 ⇒ 立刻换候选」在真链路上不成立。
        self.serve(_response(404, text='{"error":"model \\"ornith-1.5:9b-text\\" not found"}'))
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(ollama_def(model="ornith-1.5:9b-text"),
                                     request_of(), 5.0)
        self.assertEqual("model_unavailable", ctx.exception.kind)
        self.assertEqual(404, ctx.exception.status_code)
        self.assertTrue(ctx.exception.fallback_allowed)
        self.assertFalse(ctx.exception.retryable)

    def test_connection_failure_is_retryable_and_never_leaks_httpx_types(self):
        def refuse(_request):
            raise httpx.ConnectError("connection refused")

        self.serve(refuse)
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertEqual("retryable", ctx.exception.kind)
        self.assertNotIsInstance(ctx.exception, httpx.HTTPError)

    def test_timeout_argument_reaches_the_transport(self):
        self.serve(_response(200, json_body={"message": {"content": "x"}, "done": True}))
        provider_module.complete(ollama_def(), request_of(), 0.0001)
        self.assertEqual(1, len(self.requests))

    def test_malformed_success_body_is_hard_not_retryable_crash(self):
        self.serve(_response(200, text="<html>gateway</html>"))
        with self.assertRaises(errors_module.LLMError) as ctx:
            provider_module.complete(ollama_def(), request_of(), 5.0)
        self.assertEqual("hard", ctx.exception.kind)


class ProviderStreamTests(_EgressFixture):
    def test_ollama_stream_posts_true_and_yields_chunks(self):
        body = (b'{"message":{"content":"\xe4\xb8\x80"},"done":false}\n'
                b'{"message":{"content":"\xe4\xba\x8c"},"done":false}\n'
                b'{"message":{"content":""},"done":true,"prompt_eval_count":7,'
                b'"eval_count":2}\n')
        self.serve(_response(200, content=body))
        chunks = list(provider_module.stream(
            ollama_def(), request_of(think=False, keep_alive="30m", num_predict=512), 5.0))
        self.assertEqual(OLLAMA_CHAT_URL, self.last.url)
        self.assertEqual("application/json", self.last.headers["content-type"])
        self.assertTrue(self.last.payload["stream"])
        self.assertEqual("一二", "".join(c.text for c in chunks))
        self.assertTrue(chunks[-1].finish)
        self.assertEqual(2, chunks[-1].usage["output_tokens"])

    def test_openai_stream_splits_multibyte_frames_from_the_transport(self):
        whole = (b'data: {"choices":[{"delta":{"content":"\xe7\x9f\xa5\xe8\xaf\x86"}}]}\n\n'
                 b'data: [DONE]\n\n')
        pieces = [whole[i:i + 3] for i in range(0, len(whole), 3)]   # 每片 3 字节：必切字符
        self.serve(_response(200, content=iter(pieces)))
        self.use_settings(openai_api_key="sk-test")
        chunks = list(provider_module.stream(openai_def(), request_of(), 5.0))
        self.assertEqual("知识", "".join(c.text for c in chunks))
        self.assertTrue(self.last.payload["stream_options"]["include_usage"])

    def test_dispatch_errors_raise_at_call_time_not_at_first_next(self):
        # commit 边界的前提：坏 provider / 坏凭据必须在发请求之前就炸，Task 4 才能计入
        # attempt 并换下一个候选（矩阵 #10 的「pre-commit 静默换模型」）。
        model = ollama_def(id="x", provider="moonshot")
        with self.assertRaises(errors_module.LLMError):
            provider_module.stream(model, request_of(), 5.0)
        self.assertEqual([], self.requests)

    def test_http_error_is_raised_on_first_iteration(self):
        self.serve(_response(503, text="unavailable"))
        iterator = provider_module.stream(ollama_def(), request_of(), 5.0)
        with self.assertRaises(errors_module.LLMError) as ctx:
            next(iterator)
        self.assertEqual("retryable", ctx.exception.kind)
        self.assertEqual(503, ctx.exception.status_code)

    def test_mid_stream_error_body_classified_then_propagates(self):
        self.serve(_response(200, content=b'{"error":"failed to load model"}\n'))
        with self.assertRaises(errors_module.LLMError) as ctx:
            list(provider_module.stream(ollama_def(), request_of(), 5.0))
        self.assertEqual("model_unavailable", ctx.exception.kind)


# --------------------------------------------------------------------------
# health.py：probe 收编 + 60s 缓存
# --------------------------------------------------------------------------
class HealthProbeTests(_EgressFixture):
    def test_probe_ollama_true_and_detail_shape_is_unchanged(self):
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        ok, detail = health_module.probe_ollama()
        self.assertEqual(OLLAMA_URL + "/api/tags", self.last.url)
        self.assertEqual((True, "model=ornith-1.5:9b-text"), (ok, detail))
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(detail, str)

    def test_probe_ollama_reports_connected_but_model_missing(self):
        self.serve(_response(200, json_body={"models": [{"name": "phi3:mini"}]}))
        ok, detail = health_module.probe_ollama()
        self.assertFalse(ok)
        self.assertEqual("Ollama 已连接，但未发现模型 ornith-1.5:9b-text", detail)

    def test_probe_ollama_connection_failure_detail_keeps_exception_class_name(self):
        def refuse(_request):
            raise httpx.ConnectError("connection refused")

        self.serve(refuse)
        ok, detail = health_module.probe_ollama()
        self.assertFalse(ok)
        self.assertTrue(detail.startswith("ConnectError: "), detail)

    def test_probe_ollama_accepts_tag_without_colon_and_bare_model_name(self):
        self.serve(_response(200, json_body={"models": [{"name": "phi3:mini"}]}))
        self.use_settings(ollama_model="phi3")
        self.assertEqual((True, "model=phi3"), health_module.probe_ollama())

    def test_probe_llm_falls_back_to_ollama_without_openai_key(self):
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        self.assertEqual((True, "model=ornith-1.5:9b-text"), health_module.probe_llm())
        self.assertEqual(1, len(self.requests))       # 不会顺手再探 openai

    def test_probe_llm_uses_openai_compatible_endpoint_when_key_present(self):
        self.use_settings(openai_api_key="sk-test")
        self.serve(_response(200, json_body={"data": []}))
        ok, detail = health_module.probe_llm()
        self.assertEqual((True, "openai-compatible"), (ok, detail))
        self.assertEqual(OPENAI_URL + "/models", self.last.url)
        self.assertEqual("Bearer sk-test", self.last.headers["authorization"])

    def test_probe_llm_default_timeout_is_2_5_seconds(self):
        import inspect

        self.assertEqual(2.5, inspect.signature(health_module.probe_llm).parameters["timeout"]
                         .default)
        self.assertEqual(2.5,
                         inspect.signature(health_module.probe_ollama).parameters["timeout"]
                         .default)

    def test_rag_status_consumption_shape_is_unchanged_after_migration(self):
        """`/api/health` 两个入口的键集合与语义逐字不变（SystemView 的 llm_* 消费面）。

        刻意**直接调路由函数**而不是走 TestClient：`app.main_agent` 在 import 时会把
        `app.main.app` 上的 `/` 与 `/api/health` 路由摘掉换成 P1.8 版本，所以「哪个函数挂在
        `/api/health` 上」在全套件里取决于模块导入顺序——直调把顺序依赖摘掉，并且两个入口
        都钉住（比原来只测一个更强）。probe 走 MockTransport，因此这条也端到端证明了
        「health → provider → HTTP」这一段真的在发请求。
        """
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        main_settings = self.use_settings()
        patchers = [mock.patch.object(module, "settings", main_settings)
                    for module in (main_module, main_agent_module)]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(main_module.vector_store, "ping", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        legacy = main_module.health()
        self.assertEqual({
            "status": "healthy", "vector_db_connected": True, "llm_connected": True,
            "llm_detail": "model=ornith-1.5:9b-text", "ollama_connected": True,
            "llm_provider": "ollama", "llm_model": "ornith-1.5:9b-text",
        }, legacy)

        agent = main_agent_module.yaoke_health()
        self.assertEqual("healthy", agent["status"])
        self.assertTrue(agent["native_streaming"])
        self.assertTrue(agent["llm_connected"])            # agent 链用的就是 ollama
        self.assertEqual("model=ornith-1.5:9b-text", agent["llm_detail"])
        self.assertEqual("ollama", agent["llm_provider"])
        self.assertTrue(agent["agent_llm_connected"])
        self.assertTrue(agent["legacy_rag_connected"])
        self.assertEqual("ollama", agent["legacy_rag_provider"])
        # 键集合 additive-only：迁移没吃掉任何一个既有键。
        for key in ("version", "phase", "vector_db_connected", "agent_llm_detail",
                    "legacy_rag_detail", "llm_model"):
            with self.subTest(key=key):
                self.assertIn(key, agent)
        self.assertEqual(2, len(self.requests))            # 两个入口各探一次，没有旁路


class ProviderHealthViewTests(_EgressFixture):
    def registry(self) -> Registry:
        return Registry(models=(ollama_def(), ollama_def(id="ollama-ornith", model="x"),
                                openai_def()))

    def test_view_shape_is_provider_keyed_healthy_flag(self):
        self.serve(_response(200, json_body={"models": [], "data": []}))
        view = health_module.provider_health_view(self.registry())
        # provider 级健康 = 端点可达（模型有没有装是 §6 `model_unavailable` + Task 4 降级
        # 的职责，D4 的粒度就是 provider）；openai 侧空 key 属 config 失败 ⇒ 不健康。
        self.assertEqual({"ollama": {"healthy": True}, "openai": {"healthy": False}},
                         dict(view))
        self.assertEqual([OLLAMA_URL + "/api/tags"], [r.url for r in self.requests])
        self.use_settings(openai_api_key="sk-test")
        health_module.reset_health_cache()
        view = health_module.provider_health_view(self.registry())
        self.assertEqual({"ollama": True, "openai": True},
                         {name: entry["healthy"] for name, entry in view.items()})

    def test_health_is_provider_scoped_not_model_scoped(self):
        # phi3 / ornith 同属 ollama：ollama 起着就是 healthy，路由仍会选 ornith，
        # 加载失败由 §6 的 model_unavailable + Task 4 的 fallback 承接（D4 的 provider 粒度）。
        self.serve(_response(200, json_body={"models": [{"name": "phi3:mini"}]}))
        view = health_module.provider_health_view(
            Registry(models=(ollama_def(),)))
        self.assertEqual({"ollama": {"healthy": True}}, dict(view))

    def test_only_enabled_providers_are_probed(self):
        self.serve(_response(200, json_body={"models": [], "data": []}))
        disabled_openai = openai_def(enabled=False)
        health_module.provider_health_view(
            Registry(models=(ollama_def(), disabled_openai)))
        self.assertEqual([OLLAMA_URL + "/api/tags"], [r.url for r in self.requests])

    def test_cache_hit_does_not_hit_the_network_again(self):
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        registry = Registry(models=(ollama_def(),))
        first = health_module.provider_health_view(registry)
        second = health_module.provider_health_view(registry)
        self.assertEqual(1, len(self.requests))
        self.assertEqual(first["ollama"], second["ollama"])
        # 缓存窗口 60s：status 轮询与 router 过滤共用一份视图，不各探一次。
        self.assertEqual(60.0, health_module.HEALTH_CACHE_TTL_SECONDS)

    def test_cache_refreshes_after_ttl_window(self):
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        registry = Registry(models=(ollama_def(),))
        clock = {"t": 1000.0}
        patcher = mock.patch.object(health_module, "_now", lambda: clock["t"])
        patcher.start()
        self.addCleanup(patcher.stop)
        health_module.provider_health_view(registry)
        clock["t"] += health_module.HEALTH_CACHE_TTL_SECONDS - 1
        health_module.provider_health_view(registry)
        self.assertEqual(1, len(self.requests))
        clock["t"] += 2
        health_module.provider_health_view(registry)
        self.assertEqual(2, len(self.requests))

    def test_reset_health_cache_forces_a_fresh_probe(self):
        self.serve(_response(200, json_body={"models": [{"name": "ornith-1.5:9b-text"}]}))
        registry = Registry(models=(ollama_def(),))
        health_module.provider_health_view(registry)
        health_module.reset_health_cache()
        health_module.provider_health_view(registry)
        self.assertEqual(2, len(self.requests))

    def test_unreachable_provider_reports_unhealthy_without_raising(self):
        def refuse(_request):
            raise httpx.ConnectError("connection refused")

        self.serve(refuse)
        view = health_module.provider_health_view(Registry(models=(ollama_def(),)))
        self.assertEqual({"ollama": {"healthy": False}}, dict(view))


# --------------------------------------------------------------------------
# D6 结构护栏（Task 9 之前先钉住 app/llm 内部）
# --------------------------------------------------------------------------
class SingleEgressStructureTests(unittest.TestCase):
    LLM_DIR = BACKEND_DIR / "app" / "llm"
    FORBIDDEN_LITERALS = ("/api/chat", "/chat/completions", "/api/tags", "/models",
                          "ollama_base_url", "openai_base_url")

    def test_httpx_is_imported_only_by_provider(self):
        offenders = []
        for path in sorted(self.LLM_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                roots: list[str] = []
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or "").split(".")[0]]
                if "httpx" in roots and path.name != "provider.py":
                    offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], offenders)

    def test_endpoint_and_credential_literals_only_in_provider_source(self):
        # 比 Task 9 的全文扫描更严：只看**代码里的字符串常量与属性名**，docstring 里的
        # 协议说明（`/api/chat` 等）不算出口，因此这条不会因写文档而变红。
        offenders: list[str] = []
        for path in sorted(self.LLM_DIR.glob("*.py")):
            if path.name == "provider.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = _docstring_nodes(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node in docstrings:
                        continue
                    for literal in self.FORBIDDEN_LITERALS:
                        if literal in node.value:
                            offenders.append(f"{path.name}: 字符串 {literal!r}")
                elif isinstance(node, ast.Attribute) and node.attr in {
                        "ollama_base_url", "openai_base_url", "openai_api_key"}:
                    # health 侧允许读 openai_api_key / ollama_model（legacy 选择语义），
                    # 但**不得**自己拼 base url 发请求。
                    if node.attr != "openai_api_key":
                        offenders.append(f"{path.name}: 属性 {node.attr}")
        self.assertEqual([], offenders)


    def test_endpoint_literals_are_absent_from_non_provider_files_in_full_text(self):
        # 评审 M-5：Task 9 的单一出口扫描是**全文** rg（不解析 AST），于是 docstring / 注释
        # 里的端点路径也算命中。上一条用例刻意放过散文（改文档不该变红），这一条把
        # 「`app/llm/` 非 provider 文件全文零命中」钉死：散文要提端点就换成中文描述
        # （`ollama_payload` 的 docstring 就是这么写的）。
        offenders: list[str] = []
        scanned = 0
        for path in sorted(self.LLM_DIR.glob("*.py")):
            if path.name == "provider.py":
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for literal in self.FORBIDDEN_LITERALS:
                if literal in text:
                    offenders.append(f"{path.name}: 全文含 {literal}")
        self.assertGreater(scanned, 4)                      # 真扫到了文件，不是空跑
        self.assertEqual([], offenders)


def _docstring_nodes(tree: ast.AST) -> set[ast.AST]:
    """收集模块/类/函数的 docstring 节点：它们是散文，不是可执行出口。"""
    found: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                    body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                found.add(body[0].value)
    return found


# ==========================================================================
# Task 3：classifier（规则复杂度，零 IO）+ router.plan（§5 冻结过滤顺序，纯函数）
#
# health_view 一律用 stub dict（T2 交接：真视图由 `provider_health_view(registry)` 供给，
# 本任务只钉 router 消费它的语义：`{provider: {"healthy": bool, "circuit_open": bool}}`，
# 缺 provider 键 ⇒ 默认健康）。
# ==========================================================================

ROUTER_SOURCE = (BACKEND_DIR / "app" / "llm" / "router.py").read_text(encoding="utf-8")
CLASSIFIER_SOURCE = (BACKEND_DIR / "app" / "llm" / "classifier.py").read_text(encoding="utf-8")


def route_def(**overrides) -> ModelDefinition:
    """全能力条目：路由用例只改自己关心的那一维（caps/priority/pricing/enabled…）。"""
    data = {
        "id": "m-all", "provider": "ollama", "model": "all-caps:1",
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": True},
        "priority": {"chat": 10, "rag": 10, "tools": 10},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def registry_of(*models: ModelDefinition) -> Registry:
    return Registry(models=models)


def profile_of(**overrides) -> RequestProfile:
    data: dict = {"mode": "chat", "complexity": "low", "needs_tools": False,
                  "needs_stream": False}
    data.update(overrides)
    return RequestProfile(**data)


def plan_of(*models: ModelDefinition, **kwargs) -> RoutePlan:
    """`plan()` 的薄封装：profile / health_view 从 kwargs 里取，默认 chat 低复杂度全健康。"""
    profile = kwargs.pop("profile", None) or profile_of(**kwargs.pop("profile_", {}))
    health_view = kwargs.pop("health_view", {})
    return plan(profile, registry_of(*models), health_view)


def ids_of(result: RoutePlan) -> tuple[str, ...]:
    return (result.primary.model.id,) + tuple(c.model.id for c in result.fallbacks)


def codes_of(candidate: RouteCandidate) -> set[str]:
    return set(candidate.reason_codes)


# --------------------------------------------------------------------------
# classifier.py：§4 规则复杂度（禁 LLM 判路由）
# --------------------------------------------------------------------------
class ClassifierTests(unittest.TestCase):
    def test_signature_is_keyword_only_and_profile_shape(self):
        import inspect

        parameters = inspect.signature(classify).parameters
        self.assertEqual(["query", "mode", "needs_tools", "needs_stream"],
                         list(parameters))
        self.assertIs(parameters["query"].kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        for name in ("mode", "needs_tools", "needs_stream"):
            self.assertIs(parameters[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameters["needs_tools"].default, False)
        self.assertIs(parameters["needs_stream"].default, False)
        # mode 无默认值：调用点必须显式声明（RAG=rag、SSE=rag+stream、Agent=agent）。
        self.assertIs(parameters["mode"].default, inspect.Parameter.empty)
        with self.assertRaises(TypeError):
            classify("问题")                                  # 漏声明 mode = 编译期就拒
        profile = classify("问题", mode="rag")
        self.assertIsInstance(profile, RequestProfile)
        self.assertEqual("rag", profile.mode)
        self.assertEqual("low", profile.complexity)
        self.assertFalse(profile.needs_tools)
        self.assertFalse(profile.needs_stream)

    def test_needs_reasoning_is_always_false_in_v23(self):
        # V2.3 没有推理需求方（§3 `needs_reasoning=false` 默认 + classifier 不置真）：
        # reasoning capability 因此永不参与过滤，但字段与 caps 位在注册表里保留。
        queries = ("对比这两个方案的优缺点和风险", "长" * 200, "写个 hello world",
                   "先翻译。再校对。", "请同时给出方案和风险")
        for query in queries:
            for mode in ("chat", "rag", "agent"):
                with self.subTest(mode=mode, query=query[:12]):
                    self.assertFalse(classify(query, mode=mode, needs_tools=True,
                                             needs_stream=True).needs_reasoning)
                    self.assertFalse(classify(query, mode=mode).needs_reasoning)

    def test_needs_tools_and_stream_flags_are_passed_through(self):
        cases = (
            ({"mode": "chat"}, False, False),
            ({"mode": "agent", "needs_tools": True}, True, False),
            ({"mode": "rag", "needs_stream": True}, False, True),
            ({"mode": "agent", "needs_tools": True, "needs_stream": True}, True, True),
        )
        for kwargs, tools, stream in cases:
            with self.subTest(**kwargs):
                profile = classify("把这段改成繁体", **kwargs)
                self.assertEqual(tools, profile.needs_tools)
                self.assertEqual(stream, profile.needs_stream)
        # 真值归一：调用点传 None / 空列表（「当轮有没有工具」的自然形状）不得漏成 None。
        profile = classify("x", mode="agent", needs_tools=None, needs_stream=1)
        self.assertEqual((False, True), (profile.needs_tools, profile.needs_stream))

    def test_mode_is_validated_at_runtime(self):
        # Literal 只在类型检查期生效；`mode` 是 priority 取档的唯一键，脏值必须在入口拒，
        # 否则会产出一个 router 里谁都匹配不到的画像（静默 NO_CAPABLE_MODEL）。
        for mode in ("chat", "rag", "agent"):
            self.assertEqual(mode, classify("你好", mode=mode).mode)
        for bad in ("tools", "TOOL", "", None, "agent "):
            with self.subTest(mode=bad):
                with self.assertRaises(ValueError):
                    classify("你好", mode=bad)

    def test_high_complexity_length_threshold_is_sixty_characters(self):
        self.assertEqual(60, classifier_module.HIGH_COMPLEXITY_LENGTH_THRESHOLD)
        self.assertEqual("low", classify("改" * 59, mode="chat").complexity)
        self.assertEqual("high", classify("改" * 60, mode="chat").complexity)
        self.assertEqual("high", classify("改" * 200, mode="rag").complexity)
        # 空白不计入长度（粘贴带来的换行不该把「一个词」升级成复杂请求）。
        self.assertEqual("low", classify("  " + "改" * 57 + "  \n", mode="chat").complexity)

    def test_high_complexity_markers_include_the_frozen_words(self):
        # 任务书逐字点名的词必须都在表里（表可以更长，不能更短）。
        table = classifier_module.HIGH_COMPLEXITY_MARKERS
        for word in ("对比", "为什么", "方案", "风险", "优缺点", "多条件", "同时", "分别"):
            with self.subTest(word=word):
                self.assertIn(word, table)
        for word in table:
            with self.subTest(word=word):
                self.assertGreaterEqual(len(word), 2, "单字标记会误伤普通问句")
                # 模板本身不含任何标记词，因此命中只可能来自被测词。
                query = f"读一遍{word}核数字"
                self.assertLess(len(query), classifier_module.HIGH_COMPLEXITY_LENGTH_THRESHOLD)
                self.assertEqual("high", classify(query, mode="rag").complexity)

    def test_medium_complexity_markers_exclude_high_words(self):
        table = classifier_module.MEDIUM_CONNECTIVE_MARKERS
        for word in table:
            with self.subTest(word=word):
                self.assertGreaterEqual(len(word), 2)
                self.assertNotIn(word, classifier_module.HIGH_COMPLEXITY_MARKERS)
                self.assertEqual(
                    "medium", classify(f"读一遍{word}核数字", mode="rag").complexity)

    def test_medium_complexity_from_multiple_clauses(self):
        # 两句独立子句（无标记词、长度不够）= 多约束请求 ⇒ medium，不是 low。
        for query in ("先翻译第一段。再校对第二段。",
                      "先翻译第一段；再校对第二段",
                      "先翻译第一段\n再校对第二段"):
            with self.subTest(query=query):
                self.assertLess(len(query), classifier_module.HIGH_COMPLEXITY_LENGTH_THRESHOLD)
                self.assertEqual("medium", classify(query, mode="rag").complexity)
        # 单句里的逗号/顿号不算子句（否则每个带顿号的问题都成 medium）。
        self.assertEqual("low", classify("把甲、乙、丙，三段的引号统一", mode="rag").complexity)

    def test_low_complexity_is_the_default_for_short_direct_requests(self):
        for query in ("你好", "把这段改成繁体", "translate this sentence", "今天星期几",
                      "", "   ", "总结一下这段的引号格式"):
            with self.subTest(query=query):
                self.assertEqual("low", classify(query, mode="chat").complexity)

    def test_complexity_rule_precedence_is_high_then_medium_then_low(self):
        # 长度线优先于子句数：长句即便没有标记词也是 high。
        long_multi = "先把这段内容翻译完整。" * 6
        self.assertGreaterEqual(len(long_multi), classifier_module.HIGH_COMPLEXITY_LENGTH_THRESHOLD)
        self.assertEqual("high", classify(long_multi, mode="rag").complexity)
        # 短多子句 + high 词并存时取 high（high 短路在 medium 之前）。
        self.assertEqual("high", classify("先对比第一段。再校对第二段。", mode="chat").complexity)
        # 都不命中才落到 medium（两句、不够长、无标记词）。
        self.assertEqual("medium",
                         classify("先把这段内容翻译完整。再校对一遍。", mode="rag").complexity)

    def test_classify_is_deterministic_and_io_free(self):
        self.assertEqual(classify("对比两个方案", mode="rag"),
                         classify("对比两个方案", mode="rag"))
        _assert_pure_function_source(self, CLASSIFIER_SOURCE, "classifier.py",
                                     extra_allowed_modules={"app.llm.models"})

    def test_spec_section_four_word_style_is_not_coupled_to_typesafe_router(self):
        # §4「复用 typesafe_router 的词表风格，独立实现不成环」：风格可借鉴，import 不行。
        self.assertNotIn("typesafe_router", CLASSIFIER_SOURCE)


# --------------------------------------------------------------------------
# router.py：§5 冻结过滤顺序 enabled→caps→external→health→limits→priority→cost
# --------------------------------------------------------------------------
class RouterPipelineTests(unittest.TestCase):
    def test_signature_and_return_shape(self):
        import inspect

        parameters = inspect.signature(plan).parameters
        self.assertEqual(["profile", "registry", "health_view"], list(parameters))
        self.assertEqual(NoCapableModelError.__bases__, (Exception,))
        # D2 的降级由调用方（Agent fast-path）承接，所以它是独立异常而不是 `LLMError` 子类
        # （否则 Task 4 的 `except LLMError` 会把「零候选」误当成一次可重试的 provider 故障）。
        self.assertFalse(issubclass(NoCapableModelError, errors_module.LLMError))
        result = plan_of(route_def(id="a"), route_def(id="b", priority={"chat": 5}))
        self.assertIsInstance(result, RoutePlan)
        self.assertIsInstance(result.primary, RouteCandidate)
        self.assertIsInstance(result.fallbacks, tuple)
        self.assertIsInstance(result.reason_codes, tuple)
        self.assertEqual("a", result.primary.model.id)
        self.assertEqual(("b",), tuple(c.model.id for c in result.fallbacks))

    def test_no_capable_model_error_rejects_codes_outside_the_frozen_enum(self):
        # 入口校验（评审 I-1）：reason code 是**机器码**，Task 4/5 原样落
        # `usage.route_reason` 与 trace。plan() 只会传 health 步那两个码，但 Task 4 手工传码
        # 时拼错一个字母就会安静地流到前端，所以这里在构造时就拒（ValueError，不是 assert：
        # `python -O` 会把 assert 删掉）。
        for bad in ("capabilit_match", "CIRCUIT_OPENN", "NO_CAPABLE_MODELS", ""):
            with self.subTest(code=bad):
                with self.assertRaises(ValueError) as ctx:
                    NoCapableModelError(reason_codes=(bad,))
                self.assertIn(bad, str(ctx.exception))
                with self.assertRaises(ValueError):    # 混在合法码里同样拒
                    NoCapableModelError(reason_codes=("CAPABILITY_MATCH", bad))
        # 合法侧不得被校验误伤：枚举内任意组合都收，且 `NO_CAPABLE_MODEL` 必随、只随一次。
        self.assertEqual(("CIRCUIT_OPEN", "PRIMARY_UNHEALTHY", "NO_CAPABLE_MODEL"),
                         NoCapableModelError(
                             reason_codes=("CIRCUIT_OPEN", "PRIMARY_UNHEALTHY")).reason_codes)
        self.assertEqual(("NO_CAPABLE_MODEL",), NoCapableModelError().reason_codes)
        self.assertEqual(("NO_CAPABLE_MODEL",),
                         NoCapableModelError(
                             reason_codes=("NO_CAPABLE_MODEL",)).reason_codes)
        # plan() 的实际抛点仍然走得通（校验没有把 health 码判成越界）。
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(route_def(), health_view={"ollama": {"circuit_open": True}})
        self.assertEqual(("CIRCUIT_OPEN", "NO_CAPABLE_MODEL"), ctx.exception.reason_codes)

    def test_stage_literal_carries_the_context_stage_task_4_raises(self):
        # 评审 I-1 的另一半：Task 4 的 execute 前置收口（按请求体把候选剔空）要抛
        # `stage="context"`，而这个值今天还没有任何产生者。现在就把接缝钉住，别等 T4
        # 写到那里才发现 Literal 里少一项、只能回头改 T3（`_Stage` 是私有别名，模块外
        # 唯一的消费方式就是这个构造入口）。
        import typing

        stages = typing.get_args(router_module._Stage)
        self.assertEqual({"enabled", "capability", "health", "limits", "priority", "context"},
                         set(stages))
        for stage in stages:
            with self.subTest(stage=stage):
                profile = profile_of(mode="rag")
                error = NoCapableModelError(profile=profile, stage=stage)
                self.assertEqual(stage, error.stage)
                self.assertIs(profile, error.profile)
                self.assertEqual(("NO_CAPABLE_MODEL",), error.reason_codes)
                self.assertIn(f"stage={stage}", str(error))

    def test_enabled_step_drops_disabled_entries_even_at_top_priority(self):
        result = plan_of(route_def(id="off", enabled=False, priority={"chat": 1000}),
                         route_def(id="on", priority={"chat": 10}),
                         profile=profile_of(mode="chat"))
        self.assertEqual(("on",), ids_of(result))

    def test_disabled_entries_leave_no_trace_in_exception_reasons(self):
        # enabled 是第一步：全部禁用 ⇒ 停在 enabled 段，不该被误报成「能力不符」。
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(route_def(enabled=False))
        self.assertEqual("enabled", ctx.exception.stage)
        self.assertEqual(("NO_CAPABLE_MODEL",), ctx.exception.reason_codes)

    def test_capability_step_drops_mismatched_entry_at_priority_100(self):
        # capability > preference（§5 冻结）：priority=100 不得覆盖能力不符。
        no_tools = route_def(id="no-tools", capabilities={"chat": True, "rag": True,
                                                          "tools": False, "stream": True},
                             priority={"chat": 100, "rag": 100, "tools": 100})
        weak = route_def(id="tools", priority={"chat": 10, "rag": 10, "tools": 10})
        result = plan_of(no_tools, weak, profile=profile_of(mode="agent"))
        self.assertEqual(("tools",), ids_of(result))
        self.assertEqual(10, result.primary.score)

    def test_chat_capability_is_always_required(self):
        # 「chat 恒需」：rag/tools/stream 全通过但 chat=False 的条目在任何 mode 下都不入选。
        no_chat = route_def(id="no-chat", capabilities={"chat": False, "rag": True,
                                                        "tools": True, "stream": True},
                            priority={"chat": 999, "rag": 999, "tools": 999})
        for mode in ("chat", "rag", "agent"):
            with self.subTest(mode=mode):
                with self.assertRaises(NoCapableModelError) as ctx:
                    plan_of(no_chat, profile=profile_of(mode=mode))
                self.assertEqual("capability", ctx.exception.stage)
        both = route_def(id="both", priority={"chat": 1, "rag": 1})
        self.assertEqual(("both",), ids_of(plan_of(no_chat, both,
                                                   profile=profile_of(mode="rag"))))

    def test_mode_maps_to_the_matching_capability_and_priority_column(self):
        # mode=rag ⇒ 需要 caps.rag 且取 priority.rag；mode=agent ⇒ caps.tools/priority.tools
        # （§3：priority 只有 chat/rag/tools 三档，agent 复用 tools）。
        chat_only = route_def(id="chat-only", capabilities={"chat": True, "rag": False,
                                                            "tools": False, "stream": False},
                              priority={"chat": 500, "rag": 500, "tools": 500})
        rag_only = route_def(id="rag-only", capabilities={"chat": True, "rag": True,
                                                          "tools": False, "stream": False},
                             priority={"chat": 5, "rag": 5, "tools": 5})
        self.assertEqual(
            ("chat-only", "rag-only"),
            ids_of(plan_of(chat_only, rag_only, profile=profile_of(mode="chat"))))
        self.assertEqual(("rag-only",), ids_of(plan_of(chat_only, rag_only,
                                                       profile=profile_of(mode="rag"))))
        result = plan_of(chat_only, rag_only, profile=profile_of(mode="rag"))
        self.assertEqual(5, result.primary.score)      # 取的是 rag 档，不是 chat 档

    def test_needs_tools_flag_is_a_second_capability_gate(self):
        # 双态：needs_tools=False 时 tools 能力不参与（rag 链不该被工具模型门槛挡住）；
        # True 时即使 mode=rag 也要求 tools（§5「必需 capability」按需求收口）。
        with_tools = route_def(id="tools", capabilities={"chat": True, "rag": True,
                                                         "tools": True, "stream": True},
                               priority={"chat": 10, "rag": 10, "tools": 10})
        without = route_def(id="plain", capabilities={"chat": True, "rag": True,
                                                      "tools": False, "stream": True},
                            priority={"chat": 900, "rag": 900, "tools": 900})
        loose = plan_of(without, with_tools, profile=profile_of(mode="rag"))
        self.assertEqual(("plain", "tools"), ids_of(loose))       # priority 900 在前
        tight = plan_of(without, with_tools,
                        profile=profile_of(mode="rag", needs_tools=True))
        self.assertEqual(("tools",), ids_of(tight))
        self.assertTrue(tight.primary.model.capabilities.tools)

    def test_needs_stream_flag_is_a_second_capability_gate(self):
        streaming = route_def(id="streamer", capabilities={"chat": True, "rag": True,
                                                           "tools": False, "stream": True},
                              priority={"chat": 10, "rag": 10})
        blocker = route_def(id="blocker", capabilities={"chat": True, "rag": True,
                                                        "tools": False, "stream": False},
                            priority={"chat": 900, "rag": 900})
        self.assertEqual(("blocker", "streamer"),
                         ids_of(plan_of(streaming, blocker, profile=profile_of(mode="rag"))))
        self.assertEqual(("streamer",),
                         ids_of(plan_of(streaming, blocker,
                                        profile=profile_of(mode="rag", needs_stream=True))))

    def test_needs_reasoning_gates_the_reasoning_capability(self):
        # V2.3 classifier 恒不置真，但 router 必须消费该字段：否则 V2.5 一置真就静默选到
        # 不支持 reasoning 的模型。双态都钉。
        deep = route_def(id="deep", capabilities={"chat": True, "reasoning": True},
                         priority={"chat": 10})
        shallow = route_def(id="shallow", capabilities={"chat": True, "reasoning": False},
                            priority={"chat": 900})
        self.assertEqual(("shallow", "deep"),
                         ids_of(plan_of(deep, shallow, profile=profile_of(mode="chat"))))
        self.assertEqual(("deep",),
                         ids_of(plan_of(deep, shallow,
                                        profile=profile_of(mode="chat", needs_reasoning=True))))

    def test_external_policy_is_passthrough_in_v23(self):
        # §5「external policy（本版本仅记录，不拦截）」：贵的、external=true 的高优先级条目
        # 照样当 primary；LOCAL_PREFERRED 只标 external=false 的入选者，不是加分项。
        external = route_def(id="cloud", provider="openai", external=True,
                             priority={"chat": 100},
                             pricing={"input_per_1m": 5.0, "output_per_1m": 20.0})
        local = route_def(id="local", priority={"chat": 50})
        result = plan_of(local, external, profile=profile_of(mode="chat"))
        self.assertEqual(("cloud", "local"), ids_of(result))
        self.assertFalse("LOCAL_PREFERRED" in codes_of(result.primary))
        self.assertIn("LOCAL_PREFERRED", codes_of(result.fallbacks[0]))

    def test_health_step_drops_unhealthy_provider(self):
        down = route_def(id="local-down", priority={"chat": 900})
        up = route_def(id="cloud-up", provider="openai", external=True,
                       priority={"chat": 10})
        result = plan_of(down, up, profile=profile_of(mode="chat"),
                         health_view={"ollama": {"healthy": False}})
        self.assertEqual(("cloud-up",), ids_of(result))
        self.assertEqual({"CAPABILITY_MATCH", "PRIMARY_UNHEALTHY"},
                         set(result.reason_codes))

    def test_health_step_drops_circuit_open_provider(self):
        # D4：熔断态在 plan 阶段就出清（`CircuitBreaker.allow()` 是 Task 4 的第二道门）。
        down = route_def(id="local", priority={"chat": 900})
        up = route_def(id="cloud", provider="openai", external=True, priority={"chat": 10})
        result = plan_of(down, up, profile=profile_of(mode="chat"),
                         health_view={"ollama": {"healthy": True, "circuit_open": True}})
        self.assertEqual(("cloud",), ids_of(result))
        self.assertEqual({"CAPABILITY_MATCH", "CIRCUIT_OPEN"}, set(result.reason_codes))

    def test_unhealthy_and_circuit_open_are_reported_separately(self):
        # 两个信号独立：只 circuit_open 不得冒领 PRIMARY_UNHEALTHY，反之亦然；都坏则都记。
        a = route_def(id="a", priority={"chat": 900})
        b = route_def(id="b", provider="openai", external=True, priority={"chat": 10})
        result = plan_of(a, b, health_view={"ollama": {"healthy": False,
                                                       "circuit_open": True}})
        self.assertEqual({"PRIMARY_UNHEALTHY", "CIRCUIT_OPEN"},
                         set(result.reason_codes) - {"CAPABILITY_MATCH"})
        self.assertEqual(("b",), ids_of(result))

    def test_provider_missing_from_health_view_defaults_to_healthy(self):
        # `health_view.get(provider, {"healthy": True})` 的语义：视图没覆盖的 provider
        # 不是「不健康」，否则 Task 5 扩表时router会静默饿死。
        model = route_def(id="local")
        for view in ({}, None, {"openai": {"healthy": False}}, {"ollama": {}},
                     {"ollama": {"healthy": True}}):
            with self.subTest(view=view):
                self.assertEqual(("local",), ids_of(plan_of(model, health_view=view)))

    def test_all_candidates_unhealthy_raises_no_capable_model(self):
        # 冻结裁决（brief + D2）：健康全灭**不降级**成「忽略 health 继续排」，而是抛异常，
        # 由 fallback 的 legacy 分支 / Agent fast-path 承接。
        profile = profile_of(mode="rag", complexity="high", needs_stream=True)
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(route_def(id="a"), route_def(id="b"), profile=profile,
                    health_view={"ollama": {"healthy": False}})
        error = ctx.exception
        self.assertEqual("health", error.stage)
        self.assertEqual(("PRIMARY_UNHEALTHY", "NO_CAPABLE_MODEL"), error.reason_codes)
        self.assertIs(profile, error.profile)
        # 异常文本带 profile 摘要（日志/trace 只剩字符串时也要能定位是哪次请求）：
        # 五个字段逐字、顺序固定，且 NO_CAPABLE_MODEL 只出现在异常侧。
        text = str(error)
        self.assertIn("mode=rag complexity=high needs_tools=False needs_stream=True"
                      " needs_reasoning=False", text)
        for fragment in ("NO_CAPABLE_MODEL", "stage=health"):
            self.assertIn(fragment, text)
        self.assertLess(len(text), 400)

    def test_circuit_open_only_wipeout_also_raises(self):
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(route_def(), health_view={"ollama": {"circuit_open": True}})
        self.assertEqual("health", ctx.exception.stage)
        self.assertEqual(("CIRCUIT_OPEN", "NO_CAPABLE_MODEL"), ctx.exception.reason_codes)

    def test_capability_wipeout_raises_without_health_codes(self):
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(route_def(id="no-tools", capabilities={"chat": True, "tools": False}),
                    profile=profile_of(mode="agent"))
        self.assertEqual("capability", ctx.exception.stage)
        self.assertEqual(("NO_CAPABLE_MODEL",), ctx.exception.reason_codes)
        # 异常是普通 Exception，消息可读且**不回显**任何条目凭据面（D3）。
        self.assertNotIn("api_key", str(ctx.exception))

    def test_limits_step_rejects_non_positive_token_limits(self):
        # 形式校验：`model_construct` 能绕过 pydantic 的 `ge=1`，所以 router 自己也要挡一道
        # （零/负上限的条目进不了 provider 调用，属于配置事故）。
        broken = ModelDefinition.model_construct(
            id="zero", provider="ollama", model="m", enabled=True, external=False,
            capabilities=ModelCapabilities(chat=True, rag=True),
            priority={"chat": 100}, pricing=ModelPricing(),
            limits=ModelLimits.model_construct(context_tokens=0, max_output_tokens=0))
        good = route_def(id="good", priority={"chat": 10})
        self.assertEqual(("good",), ids_of(plan_of(broken, good)))
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(broken)
        self.assertEqual("limits", ctx.exception.stage)

    def test_context_estimation_is_deferred_to_task_4_and_documented(self):
        # 接口缺口（T3 → T4 移交）：`plan(profile, ...)` 收的是画像，**没有消息体**，
        # 因此 §5 的「context 粗估」不在这里发生。签名与文档同时钉住，防止后来者以为漏了。
        self.assertEqual(["profile", "registry", "health_view"],
                         list(__import__("inspect").signature(plan).parameters))
        # 直接对源码断言不含 `messages`（评审 M 残留：原来那句 `replace("Task 4", "")` 是
        # 空操作 —— 删掉「Task 4」这个字样跟「有没有 messages」毫无关系，只会让读的人以为
        # 存在某种豁免关系）。字面量 "Task 4" **允许**、也应该出现在源码里：它就是书面移交，
        # 所以下一条正向断言照旧。
        self.assertNotIn("messages", ROUTER_SOURCE)
        for fragment in ("Task 4", "context_tokens"):
            self.assertIn(fragment, ROUTER_SOURCE)
        self.assertIn("上下文", (plan.__doc__ or "") + ROUTER_SOURCE)

    def test_priority_ordering_is_descending_and_fallbacks_keep_the_ladder(self):
        result = plan_of(route_def(id="mid", priority={"chat": 80}),
                         route_def(id="top", priority={"chat": 100}),
                         route_def(id="low", priority={"chat": 50}),
                         route_def(id="bottom", priority={"chat": 10}))
        self.assertEqual(("top", "mid", "low", "bottom"), ids_of(result))
        self.assertEqual((100, 80, 50, 10),
                         (result.primary.score,)
                         + tuple(c.score for c in result.fallbacks))
        self.assertIn("HIGHER_PRIORITY", codes_of(result.primary))

    def test_missing_or_zero_priority_key_eliminates_the_candidate(self):
        # brief：「priority 缺失键 = 0 分剔除」+「tools priority 0 → agent 模式剔除」，
        # 与 capability 双保险（ornith/phi3 的 tools 档就是 0）。
        zero = route_def(id="zero", priority={"chat": 100, "rag": 100, "tools": 0})
        missing = route_def(id="missing", priority={"chat": 100},
                            capabilities={"chat": True, "rag": True, "tools": True})
        keeper = route_def(id="keeper", priority={"chat": 10, "rag": 10, "tools": 10})
        self.assertEqual(("keeper",), ids_of(plan_of(zero, missing, keeper,
                                                    profile=profile_of(mode="agent"))))
        self.assertEqual(("keeper",), ids_of(plan_of(missing, keeper,
                                                     profile=profile_of(mode="rag"))))
        self.assertIn("zero", ids_of(plan_of(zero, keeper, profile=profile_of(mode="chat"))))
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(zero, profile=profile_of(mode="agent"))
        self.assertEqual("priority", ctx.exception.stage)
        self.assertEqual(("NO_CAPABLE_MODEL",), ctx.exception.reason_codes)

    def test_tie_on_priority_is_broken_by_lower_total_unit_price(self):
        cheap = route_def(id="cheap", provider="openai", external=True,
                          priority={"chat": 70},
                          pricing={"input_per_1m": 0.1, "output_per_1m": 0.2})
        pricey = route_def(id="pricey", provider="openai", external=True,
                           priority={"chat": 70},
                           pricing={"input_per_1m": 4.0, "output_per_1m": 8.0})
        # 声明顺序两个方向都测：赢的必须是便宜的那个（否则「stable sort 侥幸」蒙不过去）。
        for order in ((pricey, cheap), (cheap, pricey)):
            with self.subTest(declared=[m.id for m in order]):
                result = plan_of(*order)
                self.assertEqual(("cheap", "pricey"), ids_of(result))
                self.assertIn("LOWER_COST", codes_of(result.primary))
                self.assertNotIn("LOWER_COST", codes_of(result.fallbacks[0]))
                self.assertNotIn("HIGHER_PRIORITY", codes_of(result.primary))

    def test_tie_on_priority_and_cost_is_broken_by_declaration_order(self):
        # 最后一道必须确定：同分同价不得依赖 dict 迭代顺序。
        first = route_def(id="a", priority={"chat": 70})
        second = route_def(id="b", priority={"chat": 70})
        self.assertEqual(("a", "b"), ids_of(plan_of(first, second)))
        self.assertEqual(("b", "a"), ids_of(plan_of(second, first)))

    def test_reason_code_set_equality_on_a_representative_plan(self):
        # 一条计划里同时出现四种「入选理由」+ 一种「剔除理由」，逐候选核集合等式。
        result = plan_of(
            route_def(id="local-top", priority={"chat": 100}),                      # cost 0
            route_def(id="cloud-dear", provider="qwen", external=True,
                      priority={"chat": 100},
                      pricing={"input_per_1m": 1.0, "output_per_1m": 1.0}),         # cost 2
            route_def(id="cloud-mid", provider="deepseek", external=True,
                      priority={"chat": 100},
                      pricing={"input_per_1m": 0.5, "output_per_1m": 0.5}),         # cost 1
            route_def(id="cloud-down", provider="openai", external=True,
                      priority={"chat": 90}),                                       # 不健康剔除
            route_def(id="local-low", priority={"chat": 20}),
            health_view={"openai": {"healthy": False}},
        )
        # 同分带内按 cost 升序：0 → 1 → 2；20 分档殿后；90 分档 provider 不健康出局。
        self.assertEqual(("local-top", "cloud-mid", "cloud-dear", "local-low"),
                         ids_of(result))
        self.assertEqual({"CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOWER_COST",
                          "LOCAL_PREFERRED"}, codes_of(result.primary))
        self.assertEqual({"CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOWER_COST"},
                         codes_of(result.fallbacks[0]))      # external ⇒ 无 LOCAL_PREFERRED
        self.assertEqual({"CAPABILITY_MATCH", "HIGHER_PRIORITY"},
                         codes_of(result.fallbacks[1]))      # 同分带里最贵 ⇒ 无 LOWER_COST
        self.assertEqual({"CAPABILITY_MATCH", "LOCAL_PREFERRED"},
                         codes_of(result.fallbacks[2]))      # 分数垫底 ⇒ 无 HIGHER_PRIORITY
        self.assertEqual({"CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOWER_COST",
                          "LOCAL_PREFERRED", "PRIMARY_UNHEALTHY"}, set(result.reason_codes))
        # 合并序：入选理由在前，剔除理由在后（trace 读起来是「为什么选它」→「谁被挤掉」）。
        self.assertEqual("PRIMARY_UNHEALTHY", result.reason_codes[-1])
        self.assertEqual(len(set(result.reason_codes)), len(result.reason_codes))  # 去重

    def test_every_emitted_reason_code_is_in_the_frozen_enum(self):
        # 冻结枚举逐字（plan Global Constraints）：集合等式 + 全程扫描零越界。
        self.assertEqual(
            {"LOCAL_PREFERRED", "CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOWER_COST",
             "PRIMARY_UNHEALTHY", "CIRCUIT_OPEN", "FALLBACK_AFTER_TIMEOUT",
             "PROVIDER_CONFIG_FAILED", "NO_CAPABLE_MODEL"},
            set(router_module.REASON_CODES))
        seen: set[str] = set()
        for mode in ("chat", "rag", "agent"):
            for needs_tools in (False, True):
                for view in ({}, {"ollama": {"healthy": False}},
                             {"ollama": {"circuit_open": True}}):
                    profile = profile_of(mode=mode, needs_tools=needs_tools)
                    models = (route_def(id="t", capabilities={"chat": True, "rag": True,
                                                              "tools": True, "stream": True}),
                              route_def(id="p", provider="openai", external=True,
                                        capabilities={"chat": True, "rag": True,
                                                      "tools": False, "stream": True}))
                    try:
                        result = plan_of(*models, profile=profile, health_view=view)
                    except NoCapableModelError as exc:
                        seen.update(exc.reason_codes)
                        continue
                    seen.update(result.reason_codes)
                    for candidate in (result.primary,) + result.fallbacks:
                        seen.update(candidate.reason_codes)
        self.assertEqual(set(), seen - set(router_module.REASON_CODES))
        self.assertIn("NO_CAPABLE_MODEL", seen)        # 扫描真的走到了异常分支，不是空跑
        # NO_CAPABLE_MODEL 只随异常：任何成功计划都不得携带它。
        ok = plan_of(route_def())
        self.assertNotIn("NO_CAPABLE_MODEL", ok.reason_codes)

    def test_enabled_runs_before_capability_so_a_disabled_mismatch_stops_at_enabled(self):
        # 顺序钉（评审 M 残留，封死步 1↔2 交换）：既禁用、又能力不符的条目必须停在 enabled。
        # 「配置根本没开」与「开着但不会做这件事」是两种降级，前者是先说的话；交换两步后
        # stage 退化成 capability，而既有的 `test_disabled_entries_leave_no_trace…` 用的是
        # 能力相符的条目，抓不到这次交换 —— 两条合起来才是完整的 enabled 先手证据。
        dead = route_def(id="off-and-blind", enabled=False,
                         capabilities={"chat": True, "rag": True, "tools": False,
                                       "stream": True},
                         priority={"chat": 100, "rag": 100, "tools": 100})
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(dead, profile=profile_of(mode="agent", needs_tools=True))
        self.assertEqual("enabled", ctx.exception.stage)
        self.assertEqual(("NO_CAPABLE_MODEL",), ctx.exception.reason_codes)
        # 同一画像下只要把它打开，就轮到 capability 说话（证明上面那条确实是被 enabled 挡的）。
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(dead.model_copy(update={"enabled": True}),
                    profile=profile_of(mode="agent", needs_tools=True))
        self.assertEqual("capability", ctx.exception.stage)

    def test_limits_never_outranks_the_steps_around_it(self):
        # 顺序钉（评审 M 残留，封死 2↔5 与 5↔6）：同一条候选**同时踩两步**时，先跑的那步独占
        # stage。limits（步 5）夹在 capability（步 2）与 priority（步 6）之间，只测一侧时它和
        # 另一个邻居交换仍然绿，所以两侧各钉一次、且都用「双重违规的单条候选」构造。
        broken_limits = ModelDefinition.model_construct(
            id="broken", provider="ollama", model="m", enabled=True, external=False,
            capabilities=ModelCapabilities(chat=True, rag=True, tools=False),
            priority={"chat": 100, "rag": 100}, pricing=ModelPricing(),
            limits=ModelLimits.model_construct(context_tokens=0, max_output_tokens=0))
        # 2↔5：既能力不符（agent 要 tools）又 limits 违规 ⇒ 步 2 先说话，limits 不冒领。
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(broken_limits, profile=profile_of(mode="agent", needs_tools=True))
        self.assertEqual("capability", ctx.exception.stage)
        # 5↔6：既 limits 违规又 priority 缺该档键（=0 分）⇒ 步 5 先说话，priority 不冒领。
        # （现实现就是 limits 在前，所以这条断言成立；反过来说：谁把两步交换，这里必红。）
        zero_priority = broken_limits.model_copy(update={"priority": {}})
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(zero_priority, profile=profile_of(mode="chat"))
        self.assertEqual("limits", ctx.exception.stage)

    def test_capability_runs_before_health_so_dead_provider_stays_silent(self):
        # 顺序钉（变异「交换过滤顺序」必红）：能力不符的候选**进不了** health 段，
        # 所以它所在 provider 的不健康不得出现在理由里。
        mismatch = route_def(id="no-tools", capabilities={"chat": True, "tools": False},
                             priority={"chat": 100})
        keeper = route_def(id="cloud", provider="openai", external=True,
                           capabilities={"chat": True, "tools": True},
                           priority={"chat": 10, "tools": 10})
        result = plan_of(mismatch, keeper, profile=profile_of(mode="agent"),
                         health_view={"ollama": {"healthy": False}})
        self.assertEqual(("cloud",), ids_of(result))
        self.assertNotIn("PRIMARY_UNHEALTHY", result.reason_codes)

    def test_health_runs_before_limits_so_the_health_wipeout_owns_the_stage(self):
        # 同一条候选链上两个过滤步都能清空时，先跑的那步拥有 stage 与理由码：
        # health 在 limits 之前（§5 冻结顺序），所以这里必须是 health + PRIMARY_UNHEALTHY。
        broken_limits = ModelDefinition.model_construct(
            id="broken", provider="ollama", model="m", enabled=True, external=False,
            capabilities=ModelCapabilities(chat=True), priority={"chat": 10},
            pricing=ModelPricing(),
            limits=ModelLimits.model_construct(context_tokens=0, max_output_tokens=0))
        unhealthy = route_def(id="cloud", provider="openai", external=True)
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(broken_limits, unhealthy,
                    health_view={"ollama": {"healthy": False},
                                 "openai": {"healthy": False}})
        self.assertEqual("health", ctx.exception.stage)
        self.assertEqual(("PRIMARY_UNHEALTHY", "NO_CAPABLE_MODEL"),
                         ctx.exception.reason_codes)

    def test_priority_step_is_the_last_filter_before_ordering(self):
        # 顺序钉：priority=0 的候选即便健康、能力齐、limits 正常也进不了计划（最后一步剔除）。
        zero = route_def(id="zero", priority={"chat": 0})
        healthy_high = route_def(id="high", provider="openai", external=True,
                                 priority={"chat": 1})
        self.assertEqual(("high",), ids_of(plan_of(zero, healthy_high)))
        with self.assertRaises(NoCapableModelError) as ctx:
            plan_of(zero, health_view={"ollama": {"healthy": True}})
        self.assertEqual("priority", ctx.exception.stage)

    def test_plan_is_a_pure_function_over_its_inputs(self):
        _assert_pure_function_source(self, ROUTER_SOURCE, "router.py",
                                     extra_allowed_modules={"app.llm.models",
                                                            "app.llm.registry"})
        models = [route_def(id="a"), route_def(id="b", provider="openai", external=True,
                                               priority={"chat": 99})]
        registry = Registry(models=tuple(models))
        view = {"ollama": {"healthy": True}}
        profile = profile_of(mode="chat")
        first = plan(profile, registry, view)
        second = plan(profile, registry, view)
        self.assertEqual(ids_of(first), ids_of(second))
        self.assertEqual(("a", "b"), registry.ids())        # 注册表未被就地排序/改写
        self.assertEqual({"ollama": {"healthy": True}}, view)   # 健康视图未被写脏
        self.assertEqual(profile, profile_of(mode="chat"))  # 画像未被改

    def test_router_does_not_touch_credentials_or_the_provider_layer(self):
        # 结构性前提（D1/D6）：router 只消费注册表里已解析的 enabled 事实值，
        # 不解析凭据、不 import provider/health/config，也不读 env。
        for forbidden in ("provider_credentials", "credentials_for_provider", "api_key",
                          "base_url", "import os", "import httpx", "app.llm.provider",
                          "app.llm.health", "app.config"):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, ROUTER_SOURCE)


class ShippedRegistryRoutingTests(_RegistryFixture):
    """出厂注册表（§3 五条目）在真实 enabled 解析下的路由形状。"""

    def test_package_re_exports_the_decision_symbols(self):
        # Task 4/8 从包级别 import `NoCapableModelError`（D2 的降级入口）与 `classify`：
        # 断言**同一对象**，避免包里有第二份定义。
        self.assertIs(llm.classify, classify)
        self.assertIs(llm.plan, plan)
        self.assertIs(llm.NoCapableModelError, NoCapableModelError)
        self.assertEqual(router_module.REASON_CODES, llm.REASON_CODES)
        self.assertEqual(classifier_module.MODES, ("chat", "rag", "agent"))
        for name in ("classify", "plan", "NoCapableModelError", "REASON_CODES"):
            self.assertIn(name, llm.__all__)

    def registry_with_keys(self, **keys) -> Registry:
        self.use_settings(**keys)
        return load_registry(str(SHIPPED_REGISTRY))

    def test_chat_plan_prefers_the_local_primary_and_keeps_phi3_as_fallback(self):
        registry = self.registry_with_keys()          # 无 openai key ⇒ 三条 external 全 disabled
        result = plan(profile_of(mode="chat", complexity="high"), registry, {})
        self.assertEqual(("ollama-ornith", "ollama-phi3"), ids_of(result))
        self.assertEqual(100, result.primary.score)
        self.assertEqual(80, result.fallbacks[0].score)
        self.assertEqual({"CAPABILITY_MATCH", "HIGHER_PRIORITY", "LOCAL_PREFERRED"},
                         set(result.reason_codes))

    def test_rag_stream_plan_requires_stream_capability(self):
        registry = self.registry_with_keys()
        result = plan(profile_of(mode="rag", needs_stream=True), registry, {})
        self.assertEqual(("ollama-ornith", "ollama-phi3"), ids_of(result))
        # 出厂两条本地条目都带 stream=true，所以流式过滤不改变形状（改的是 rag 档打分）。
        self.assertEqual(100, result.primary.score)

    def test_agent_plan_is_a_pre_flight_no_capable_without_a_cloud_key(self):
        # D2 的前提：tools 模型全在云上，没有 key 时注册表里没有任何 agent 候选
        # ⇒ plan() 抛异常，Agent 侧走 fast-path（Task 8），而不是发一次注定失败的请求。
        registry = self.registry_with_keys()
        with self.assertRaises(NoCapableModelError) as ctx:
            plan(profile_of(mode="agent", needs_tools=True), registry, {})
        self.assertEqual("capability", ctx.exception.stage)
        self.assertIn("mode=agent", str(ctx.exception))

    def test_agent_plan_uses_the_tools_column_when_the_key_arrives(self):
        registry = self.registry_with_keys(openai_api_key="sk-only-for-this-test")
        result = plan(profile_of(mode="agent", needs_tools=True), registry, {})
        self.assertEqual("openai", result.primary.model.id)
        self.assertEqual(100, result.primary.score)     # priority.tools=100
        self.assertEqual((), result.fallbacks)          # 本地两条 tools=false + tools 档 0
        self.assertNotIn("LOCAL_PREFERRED", result.reason_codes)

    def test_unhealthy_ollama_routes_rag_traffic_to_the_cloud_entry(self):
        registry = self.registry_with_keys(openai_api_key="sk-only-for-this-test")
        result = plan(profile_of(mode="rag"), registry, {"ollama": {"healthy": False}})
        self.assertEqual(("openai",), ids_of(result))
        self.assertIn("PRIMARY_UNHEALTHY", result.reason_codes)
        # 全灭裁决：唯一可用候选也不健康 ⇒ 抛，而不是「忽略 health 硬选一个」。
        with self.assertRaises(NoCapableModelError):
            plan(profile_of(mode="rag"), registry, {"ollama": {"healthy": False},
                                                    "openai": {"healthy": False}})


class RouterBenchmarkTests(unittest.TestCase):
    """§5 验收线：`plan()` 纯内存 P95 ≤ 10ms（矩阵 #14）。

    非 CI 抖动容差 = **进程内 min-of-3 轮**：每轮 200 次独立计时取 P95，三轮里最好的
    一轮仍超预算才判 FAIL（宿主上杀毒/索引进程能把单轮 P95 顶到十几毫秒，但不会连续
    三轮都顶上去）。断言消息带最差轮数字，失败时能一眼区分「抖动」与「性能回归」。
    """

    BUDGET_MS = 10.0
    ITERATIONS = 200
    ROUNDS = 3

    @staticmethod
    def p95(samples_ms: list[float]) -> float:
        import math

        ordered = sorted(samples_ms)
        return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]

    def measure(self, profile: RequestProfile, registry: Registry, health_view,
                *, expect_fallbacks: int) -> tuple[float, float]:
        """三轮 × 200 次计时，返回 (最好轮的 P95, 最差轮的 P95) 毫秒。"""
        import time

        warm = plan(profile, registry, health_view)     # 预热：冷启动噪声不计入任何一轮
        self.assertEqual(expect_fallbacks, len(warm.fallbacks))  # 计时对象真在满候选上排序
        rounds: list[float] = []
        for _ in range(self.ROUNDS):
            samples: list[float] = []
            for _ in range(self.ITERATIONS):
                start = time.perf_counter()
                plan(profile, registry, health_view)
                samples.append((time.perf_counter() - start) * 1000.0)
            self.assertEqual(self.ITERATIONS, len(samples))
            rounds.append(self.p95(samples))
        return min(rounds), max(rounds)

    def test_p95_under_budget_on_the_shipped_five_entry_registry(self):
        models = tuple(
            route_def(id=f"m{i}", provider="ollama" if i == 0 else "openai",
                      external=i != 0,
                      priority={"chat": 100 - 10 * i, "rag": 100 - 10 * i,
                                "tools": 100 - 10 * i},
                      pricing={"input_per_1m": float(i), "output_per_1m": float(i)})
            for i in range(5))
        best, worst = self.measure(profile_of(mode="chat"), Registry(models=models), {},
                                   expect_fallbacks=4)
        self.assertLessEqual(best, self.BUDGET_MS,
                             f"5 条目 P95 best-of-{self.ROUNDS}={best:.3f}ms"
                             f"（最差轮 {worst:.3f}ms）超出 {self.BUDGET_MS}ms 预算")

    def test_p95_under_budget_on_a_sixty_candidate_registry(self):
        # brief 的规模口径：60 候选 × 200 次计时。混合 external / 价格 / provider / 能力，
        # 让能力过滤、健康查表、打分排序、cost tie-break 四段全部落在计时范围内。
        providers = ("ollama", "openai", "deepseek", "qwen")
        models = tuple(
            route_def(id=f"m{i}", provider=providers[i % len(providers)],
                      model=f"model-{i}", external=providers[i % len(providers)] != "ollama",
                      capabilities={"chat": True, "rag": True, "tools": i % 2 == 0,
                                    "stream": True, "reasoning": i % 5 == 0},
                      priority={"chat": 1000 - i, "rag": 900 - i, "tools": 500 - i},
                      pricing={"input_per_1m": round(i * 0.13, 2),
                               "output_per_1m": round(i * 0.31, 2)})
            for i in range(60))
        registry = Registry(models=models)
        # qwen 不健康：60 条里有 15 条走 health 剔除分支，视图查表也在计时里。
        health_view = {name: {"healthy": name != "qwen"} for name in providers}
        cases = (
            ("chat", profile_of(mode="chat"), 44),
            ("agent", profile_of(mode="agent", needs_tools=True, needs_stream=True), 29),
            ("rag", profile_of(mode="rag", complexity="high"), 44),
        )
        for label, profile, expected_fallbacks in cases:
            with self.subTest(mode=label):
                best, worst = self.measure(profile, registry, health_view,
                                           expect_fallbacks=expected_fallbacks)
                self.assertLessEqual(best, self.BUDGET_MS,
                                     f"{label}: P95 best-of-{self.ROUNDS}={best:.3f}ms"
                                     f"（最差轮 {worst:.3f}ms）超出 {self.BUDGET_MS}ms 预算")


def _assert_pure_function_source(case: unittest.TestCase, source: str, name: str,
                                 *, extra_allowed_modules: set[str]) -> None:
    """纯函数护栏：import 只允许白名单模块，且源码里没有 env/时钟/随机/网络/文件来源。"""
    tree = ast.parse(source)
    allowed = {"__future__", "typing"} | extra_allowed_modules
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            continue
        for module in modules:
            case.assertIn(module, allowed,
                          f"{name} 的 import {module} 不在白名单 {sorted(allowed)}")
    for forbidden in ("open(", "environ", "getenv", "perf_counter", "monotonic",
                      "random", "datetime", "subprocess", "socket", "time."):
        case.assertNotIn(forbidden, source, f"{name} 出现非纯来源 {forbidden}")


# ==========================================================================
# Task 4：fallback executor（重试 / 逐 provider 熔断 / 总预算 / 流式 commit）
#         + 包级公共入口 `llm.router_enabled() / complete() / stream()`
#
# 两类接缝并用，缺一不可：
# - **stub provider**（替换 `app.llm.provider.complete/stream`）：§10 #3–#8/#10/#11 的
#   行为裁决要看得见「哪个候选被调用了几次、当次 timeout 传了多少秒」——`timeout` 不进
#   HTTP 报文，MockTransport 永远看不到它，所以预算收缩只有这一种测法。
# - **真 MockTransport**（`_EgressFixture.serve`）：证明归类→报文→解析整条链真的活着
#   （retryable/model_unavailable/hard 来自真实状态码与 body，而不是测试自造的异常），
#   以及 `model_override` 端到端。
# - **假钟**（`fallback._now`）：预算与 ttft 完全确定，测试不睡 30 秒；熔断器另有自己的
#   `clock` 参数（`resilience.py` 公开面），需要推进 OPEN→HALF_OPEN 时注入实例时钟。
# ==========================================================================

FALLBACK_SOURCE = (BACKEND_DIR / "app" / "llm" / "fallback.py").read_text(encoding="utf-8")
PACKAGE_SOURCE = (BACKEND_DIR / "app" / "llm" / "__init__.py").read_text(encoding="utf-8")

OLLAMA_OK_BODY = {"model": "phi3:mini", "message": {"role": "assistant", "content": "好的"},
                  "done": True, "prompt_eval_count": 4, "eval_count": 2}


def fb_def(**overrides) -> ModelDefinition:
    """执行器用例的候选条目：全能力 + 足够上下文，只改测试关心的那一维。"""
    data = {
        "id": "fb-a", "provider": "ollama", "model": "fb-a-model",
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 10, "rag": 10, "tools": 10},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def fb_candidate(model: ModelDefinition, score: int) -> RouteCandidate:
    return RouteCandidate(model=model, score=score, reason_codes=("CAPABILITY_MATCH",))


def fb_plan(*models: ModelDefinition,
            reason_codes: tuple[str, ...] = ("CAPABILITY_MATCH",)) -> RoutePlan:
    """手工候选链：**声明序即执行序**（矩阵要的 `fallback_index` 必须由测试摆得出）。"""
    candidates = tuple(fb_candidate(model, 100 - 10 * position)
                       for position, model in enumerate(models))
    return RoutePlan(primary=candidates[0], fallbacks=candidates[1:],
                     reason_codes=reason_codes)


def fb_request(content: str = "问题", **overrides) -> LLMRequest:
    data: dict = {"messages": [{"role": "user", "content": content}]}
    data.update(overrides)
    return LLMRequest.model_validate(data)


def fb_response(model: ModelDefinition, text: str = "好的", **overrides) -> LLMResponse:
    data: dict = {"content": text, "model": model.model, "provider": model.provider,
                  "input_tokens": 4, "output_tokens": 2, "latency_ms": 120.0}
    data.update(overrides)
    return LLMResponse.model_validate(data)


def fb_chunk(text: str = "", **overrides) -> LLMChunk:
    data: dict = {"text": text}
    data.update(overrides)
    return LLMChunk.model_validate(data)


def fb_error(kind: str, status: int | None = None, message: str = "", **overrides) -> LLMError:
    return errors.LLMError(kind, status, message or f"{kind}{status or ''}", **overrides)


def fb_timeout_error() -> LLMError:
    """真·超时归类：走 `errors.from_exception`，于是 `FALLBACK_AFTER_TIMEOUT` 的判据
    （status None + 消息前缀「超时」）与被测代码同源，不是测试自造的形状。"""
    return errors.from_exception(httpx.ReadTimeout("read timed out"))


def s_ok(response: LLMResponse) -> LLMResponse:
    return response


def s_raises(exc: BaseException) -> BaseException:
    return exc


def s_stream(*items, then: BaseException | None = None):
    """流式脚本：`s_stream(c1, c2, then=exc)` ⇒ 先吐完再抛（pre/post commit 由内容块决定）。"""
    def handler(_call):
        def gen():
            for item in items:
                yield item
            if then is not None:
                raise then
        return gen()
    return handler


def s_stream_raises(exc: BaseException):
    """开流即抛（`provider.stream()` 调用时就失败，或第一次 `next()` 才失败都由异常类型决定）。"""
    def handler(_call):
        raise exc
    return handler


class FakeClock:
    """可推进的假钟（同时服务 `fallback._now` 与 `CircuitBreaker(clock=…)`）。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = float(start)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        if seconds:
            self.value += float(seconds)

    def ms_since(self, mark: float) -> float:
        return (self.value - mark) * 1000.0


class StubCall:
    """一次被 stub 接住的 provider 调用：模型、当次 timeout（秒）、该模型第几次被调。"""

    def __init__(self, model: ModelDefinition, timeout: float, ordinal: int,
                 sequence: int, stream: bool) -> None:
        self.model_id = model.id
        self.provider = model.provider
        self.model = model.model
        self.timeout = timeout
        self.ordinal = ordinal
        self.sequence = sequence
        self.stream = stream

    def __repr__(self) -> str:                                  # 断言失败时可读
        return (f"StubCall(#{self.sequence} {self.model_id} "
                f"{'stream' if self.stream else 'complete'} timeout={self.timeout}")


class _FallbackFixture(_EgressFixture):
    """Task 4 底座：熔断器复位 + 假钟 + fallback/包级 settings 打桩 + stub provider 接缝。"""

    #: 执行器用例的默认配置。`retry=0` 让矩阵用例只测「换候选」，重试另有专测；
    #: `window=8` 是 `CircuitBreaker` 的下限，于是 4 条失败回执就足以触发熔断。
    SETTINGS_DEFAULTS: dict = {
        "llm_retry_per_model": 0,
        "llm_total_budget_ms": 30000,
        "llm_model_timeout_seconds": 20,
        "llm_breaker_enabled": True,
        "llm_breaker_window": 8,
        "llm_breaker_failure_ratio": 0.30,
        "llm_breaker_open_seconds": 60,
        "llm_breaker_half_open_probes": 3,
    }

    def setUp(self) -> None:
        self.clock = FakeClock(1000.0)
        clock_patcher = mock.patch.object(fallback_module, "_now", self.clock)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        fallback_module.reset_circuit_breakers()
        self.addCleanup(fallback_module.reset_circuit_breakers)
        self.calls: list[StubCall] = []
        self.clock_step = 0.0        # 每次外呼推进的秒数（预算收缩用例用）
        self.stream_step = 0.0       # 流式每产出一个 chunk 推进的秒数（ttft 用例用）
        super().setUp()              # 内部调用 self.use_settings（被本类覆写）
        self._isolate_usage_ledger()

    def _isolate_usage_ledger(self) -> None:
        """**本族的账本隔离**（评审 I-2 的同类洞：Task 6 之前只有 `PackageEntryPointTests` 做了）。

        症状：`llm.complete()` 收尾必调 `_log_usage` → `usage_sink()` 在 sink 未注册时
        **惰性解析到真 `app.llm.usage.log_usage`** → 生效路径是 `data/conversations.db`
        = 仓库里的**真实库**（`_EgressFixture` 把宿主 env 清空了，所以连
        `CONVERSATION_DB_PATH` 都读不到）。`llm_request_logs` 是 §8 全部聚合的唯一数据源，
        一次定向跑往里灌一行 `success=1` 的假账，T9/T10/T11 在开发机上读到的 status 数字
        就失真。所以隔离做在本类的 `setUp` 上，而不是逐个用例补——子类再多也不会漏。

        两道一起上，缺一都留有缝隙：
        1. 显式内存 sink（照 `PackageEntryPointTests` 现成姿势）⇒ 一行都不落地；
        2. `CONVERSATION_DB_PATH` 指到临时目录 ⇒ 子类为了测「惰性解析」那一支把 sink 换回
           `None` 时（`test_usage_sink_falls_back_to_late_bound_app_llm_usage` 就是），
           落的是临时库而不是真库。

        外层 `mock.patch.dict(os.environ, {}, clear=True)` 是 Task 1 就在用的隔离手法，
        不改它：本层的 patch 在它**之内**启动、按 LIFO 先还原。
        """
        self.ledger_rows: list[UsageRecord] = []
        previous_sink = llm.set_usage_sink(self.ledger_rows.append)
        self.addCleanup(lambda: llm.set_usage_sink(previous_sink))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = mock.patch.dict(os.environ, {
            "CONVERSATION_DB_PATH": str(Path(directory.name) / "conversations.db")})
        env.start()
        self.addCleanup(env.stop)

    def use_settings(self, **overrides) -> Settings:
        base = dict(self.SETTINGS_DEFAULTS)
        base.update(overrides)
        fake = super().use_settings(**base)
        # _EgressFixture 只把 settings 打到 registry/health/rag；执行器与包级入口要自己那份。
        for module in (fallback_module, llm):
            patcher = mock.patch.object(module, "settings", fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.settings = fake
        return fake

    # --- stub provider ----------------------------------------------------
    def _record(self, model: ModelDefinition, timeout: float, stream: bool):
        ordinals = self._ordinals()
        ordinal = ordinals[model.id] = ordinals.get(model.id, 0) + 1
        self.calls.append(StubCall(model, timeout, ordinal, len(self.calls), stream))
        self.clock.advance(self.clock_step)
        return ordinal

    def _ordinals(self) -> dict:
        if not hasattr(self, "_per_model_ordinals"):
            self._per_model_ordinals: dict[str, int] = {}
        return self._per_model_ordinals

    def stub_complete(self, script: dict) -> None:
        def fake(model, req, timeout):
            ordinal = self._record(model, timeout, stream=False)
            handler = self._handler_for(script, model, ordinal)
            if isinstance(handler, BaseException):
                raise handler
            return handler(ordinal) if callable(handler) else handler

        patcher = mock.patch.object(provider_module, "complete", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def stub_stream(self, script: dict) -> None:
        def fake(model, req, timeout):
            ordinal = self._record(model, timeout, stream=True)
            handler = self._handler_for(script, model, ordinal)
            if isinstance(handler, BaseException):
                raise handler
            produced = handler(ordinal) if callable(handler) else handler

            def pump():
                for item in produced:
                    self.clock.advance(self.stream_step)
                    if isinstance(item, BaseException):
                        raise item
                    yield item
            return pump()

        patcher = mock.patch.object(provider_module, "stream", fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _handler_for(self, script: dict, model: ModelDefinition, ordinal: int):
        if model.id not in script:
            raise AssertionError(
                f"候选 {model.id} 没有脚本：执行器不该外呼它（已调用 {self.called_ids}）")
        return script[model.id]

    # --- 观测 -------------------------------------------------------------
    @property
    def called_ids(self) -> list[str]:
        return [call.model_id for call in self.calls]

    @property
    def timeouts(self) -> list[float]:
        return [call.timeout for call in self.calls]

    def drain(self, session) -> list[LLMChunk]:
        return list(session.chunks())


# --------------------------------------------------------------------------
# 冻结面：签名、数据对象、异常族
# --------------------------------------------------------------------------
class FallbackContractTests(_FallbackFixture):
    def test_run_complete_signature_is_frozen(self):
        import inspect

        parameters = inspect.signature(fallback_module.run_complete).parameters
        self.assertEqual(["chain_source", "req", "trace_id", "request_id"],
                         list(parameters))
        self.assertEqual(inspect.Parameter.KEYWORD_ONLY,
                         parameters["trace_id"].kind)
        self.assertIsNone(parameters["trace_id"].default)
        self.assertIsNone(parameters["request_id"].default)
        fields_ = tuple(field_.name for field_ in _dc_fields(FallbackResult))
        self.assertEqual(("response", "attempts", "selected_index", "reason_codes",
                          "budget_ms"), fields_[:5])            # brief 冻结的五字段与顺序
        self.assertEqual(("model_id", "provider", "result", "error_type", "latency_ms"),
                         tuple(field_.name for field_ in _dc_fields(Attempt)))

    def test_run_stream_signature_and_session_surface(self):
        import inspect

        parameters = inspect.signature(fallback_module.run_stream).parameters
        self.assertEqual(["chain_source", "req", "trace_id", "request_id"],
                         list(parameters))
        session = fallback_module.run_stream(fb_plan(fb_def()), fb_request())
        self.assertIs(False, session.committed)
        self.assertEqual(-1, session.selected_index)             # 未选中前是 -1，不是 0
        self.assertEqual((), session.attempts)
        self.assertTrue(callable(session.chunks))
        self.assertTrue(callable(session.finish))
        self.assertEqual(("response_text", "usage", "ttft_ms", "attempts", "selected_index",
                          "reason_codes"),
                         tuple(f_.name for f_ in _dc_fields(StreamSummary))[:6])

    def test_chain_source_accepts_plan_or_profile_and_rejects_otherwise(self):
        self.stub_complete({"fb-a": fb_response(fb_def())})
        profile = profile_of(mode="chat")
        registry = registry_of(fb_def())
        with mock.patch.object(fallback_module, "routing_health_view",
                               lambda *a, **k: {}):
            with mock.patch.object(fallback_module, "get_registry", lambda: registry):
                result = fallback_module.run_complete(profile, fb_request())
        self.assertEqual(0, result.selected_index)               # 便利入口：执行器自己 plan
        self.assertEqual(["fb-a"], self.called_ids)
        for bogus in ("plan", 42, None):
            with self.subTest(bogus=type(bogus).__name__):
                with self.assertRaises(TypeError):
                    fallback_module.run_complete(bogus, fb_request())

    def test_stream_interrupted_is_not_an_llm_error_and_carries_the_triple(self):
        self.assertTrue(issubclass(StreamInterrupted, Exception))
        self.assertFalse(issubclass(StreamInterrupted, LLMError),
                         "混进 LLMError 会让调用方的 `except LLMError` 把已交付内容的会话"
                         "当成可整体重发的错误")
        exc = StreamInterrupted("前半段", [Attempt("fb-a", "ollama", "failed", "retryable")],
                                0, error=fb_error("retryable", None))
        self.assertEqual("前半段", exc.partial_text)
        self.assertEqual(1, len(exc.attempts))
        self.assertEqual(0, exc.selected_index)
        self.assertEqual("retryable", exc.error_type)
        self.assertNotIn("前半段", str(exc))                     # D3：内容不进异常消息

    def test_all_candidates_failed_error_is_an_llm_error_with_attempts_attached(self):
        self.assertTrue(issubclass(AllCandidatesFailedError, LLMError))
        attempts = [Attempt("fb-a", "ollama", "failed", "retryable", 10.0),
                    Attempt("fb-b", "ollama", "skipped_circuit", None, 0.0)]
        exc = AllCandidatesFailedError(attempts, last_error=fb_error("retryable", 503))
        self.assertEqual("retryable", exc.kind)                  # 沿用最后一个真实失败的归类
        self.assertEqual(503, exc.status_code)
        self.assertEqual(tuple(attempts), exc.attempts)
        self.assertFalse(exc.budget_exhausted)
        self.assertIn("熔断跳过 1 次", str(exc))
        no_error = AllCandidatesFailedError([attempts[1]])
        self.assertEqual("hard", no_error.kind)                  # 没外呼过 ⇒ 没有可沿用的归类

    def test_the_router_flag_is_read_only_by_router_enabled(self):
        tree = ast.parse(PACKAGE_SOURCE)
        readers = [node.lineno for node in ast.walk(tree)
                   if isinstance(node, ast.Attribute) and node.attr == "llm_router_enabled"]
        self.assertEqual(1, len(readers), "legacy 旗标属于调用方分支，包内只许读一次")
        enabled_bodies = [node for node in ast.walk(tree)
                          if isinstance(node, (ast.FunctionDef,)) and node.name == "router_enabled"]
        self.assertEqual(1, len(enabled_bodies))
        span = range(enabled_bodies[0].lineno, enabled_bodies[0].end_lineno + 1)
        self.assertTrue(all(line in span for line in readers),
                        "旗标只能被 router_enabled() 读")


# --------------------------------------------------------------------------
# 上下文前置收口（Task 3 移交①②④）
# --------------------------------------------------------------------------
class ContextGateTests(_FallbackFixture):
    def test_estimator_uses_the_frozen_formula_on_the_whole_message_dict(self):
        message = {"role": "user", "content": "x" * 40}
        self.assertEqual(len(str(message)) / 2,
                         fallback_module.estimate_prompt_tokens([message]))
        self.assertEqual(0.0, fallback_module.estimate_prompt_tokens([]))
        self.assertEqual(2, fallback_module.CONTEXT_CHARS_PER_TOKEN)

    def test_boundary_is_inclusive_at_the_context_limit(self):
        import math

        messages = [{"role": "user", "content": "y" * 200}]
        estimated = fallback_module.estimate_prompt_tokens(messages)
        fits_at = int(math.ceil(estimated))                      # 上限**恰好等于**粗估
        plan = fb_plan(fb_def(id="fits", limits={"context_tokens": fits_at,
                                                 "max_output_tokens": 512}))
        kept, dropped = fallback_module.fit_chain_to_context(plan, fb_request(messages=messages))
        self.assertEqual(1, len(kept))                           # 等于上限 ⇒ 装得下
        self.assertEqual(0, dropped)
        plan = fb_plan(fb_def(id="tight", limits={"context_tokens": max(fits_at - 1, 1),
                                                  "max_output_tokens": 512}))
        kept, dropped = fallback_module.fit_chain_to_context(plan, fb_request(messages=messages))
        self.assertEqual((), kept)
        self.assertEqual(1, dropped)

    def test_oversized_candidates_are_pruned_before_any_call(self):
        small = fb_def(id="small", limits={"context_tokens": 30, "max_output_tokens": 512})
        big = fb_def(id="big", limits={"context_tokens": 8192, "max_output_tokens": 512})
        self.stub_complete({"big": fb_response(big)})
        result = fallback_module.run_complete(fb_plan(small, big),
                                              fb_request(content="z" * 400))
        self.assertEqual(["big"], self.called_ids)               # 小上下文候选没浪费一次外呼
        self.assertEqual(0, result.selected_index)               # 收口后的链下标
        self.assertEqual(1, result.context_dropped)              # 移交④：被剔计数

    def test_empty_after_pruning_raises_no_capable_at_the_context_stage(self):
        tiny = fb_def(id="tiny", limits={"context_tokens": 8, "max_output_tokens": 512})
        with self.assertRaises(NoCapableModelError) as caught:
            fallback_module.run_complete(fb_plan(tiny), fb_request(content="q" * 400))
        error = caught.exception
        self.assertEqual("context", error.stage)
        self.assertEqual(("NO_CAPABLE_MODEL",), error.reason_codes)   # 不造新码
        self.assertIn("被剔 1 条", str(error))
        self.assertEqual([], self.called_ids)

    def test_stream_prunes_at_open_time_before_any_chunk(self):
        tiny = fb_def(id="tiny", limits={"context_tokens": 8, "max_output_tokens": 512})
        with self.assertRaises(NoCapableModelError) as caught:
            fallback_module.run_stream(fb_plan(tiny), fb_request(content="q" * 400))
        self.assertEqual("context", caught.exception.stage)      # 不必消费 chunks() 才抛


# --------------------------------------------------------------------------
# §10 矩阵 #3–#8：真 MockTransport（归类来自真实状态码与 body）
# --------------------------------------------------------------------------
class FallbackTransportMatrixTests(_FallbackFixture):
    def test_matrix_3_429_retries_the_same_model_then_succeeds(self):
        self.use_settings(llm_retry_per_model=1, openai_api_key="")
        model = fb_def(id="fb-a")
        self.serve_sequence(_response(429, json_body={"error": "too many requests"}),
                            _response(200, json_body=OLLAMA_OK_BODY))
        result = fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual(2, len(self.requests))                  # 同一模型两次
        self.assertEqual(0, result.selected_index)
        self.assertEqual([("failed", "retryable"), ("success", None)],
                         [(a.result, a.error_type) for a in result.attempts])
        self.assertEqual("好的", result.response.content)
        self.assertEqual(4, result.response.input_tokens)

    def test_matrix_4_500_model_load_failure_falls_back_to_second_candidate(self):
        first = fb_def(id="fb-a")
        second = fb_def(id="fb-b", model="fb-b-model")
        self.serve_sequence(_response(500, json_body={"error": "failed to load model"}),
                            _response(200, json_body=OLLAMA_OK_BODY))
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(1, result.selected_index)               # fallback_index=1
        self.assertEqual(["fb-a-model", "fb-b-model"],
                         [request.payload["model"] for request in self.requests])
        self.assertEqual("model_unavailable", result.attempts[0].error_type)

    def test_matrix_5_timeout_falls_back_and_marks_fallback_after_timeout(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        attempts = {"n": 0}

        def handler(_request):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise httpx.ReadTimeout("read timed out")
            return _response(200, json_body=OLLAMA_OK_BODY)

        self.serve(handler)
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(1, result.selected_index)
        self.assertIn("FALLBACK_AFTER_TIMEOUT", result.reason_codes)
        self.assertEqual("retryable", result.attempts[0].error_type)
        # plan 的理由码在前、执行期码在后（T3 移交③的 concat 口径）
        self.assertEqual(("CAPABILITY_MATCH", "FALLBACK_AFTER_TIMEOUT"),
                         result.reason_codes)

    def test_timeout_cause_detection_follows_the_classification_not_missing_status(self):
        # FALLBACK_AFTER_TIMEOUT 的判据：真超时 / 408 算；连接失败与 5xx 不算。
        cases = (
            (errors.from_exception(httpx.ReadTimeout("read timed out")), True),
            (errors.classify(408, "gateway timeout"), True),
            (errors.from_exception(httpx.ConnectError("connection refused")), False),
            (fb_error("retryable", 500), False),
            (fb_error("hard", 400), False),
        )
        for error, expected in cases:
            with self.subTest(kind=error.kind, status=error.status_code):
                self.assertEqual(expected, fallback_module._looks_like_timeout(error))

    def test_matrix_6_400_does_not_retry_current_but_allows_fallback(self):
        self.use_settings(llm_retry_per_model=1)                 # 给了重试额度也不能用在这
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.serve_sequence(_response(400, json_body={"error": "bad request"}),
                            _response(200, json_body=OLLAMA_OK_BODY))
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(2, len(self.requests))                  # 每个候选恰好一次
        self.assertEqual(1, result.selected_index)
        self.assertEqual("hard", result.attempts[0].error_type)

    def test_matrix_7_401_marks_provider_config_failed_and_skips_same_provider(self):
        first = fb_def(id="fb-a")
        same = fb_def(id="fb-b")
        other = fb_def(id="fb-c", provider="deepseek", model="deep-chat",
                       external=True, priority={"chat": 1, "rag": 1, "tools": 1})
        self.stub_complete({
            "fb-a": s_raises(fb_error("config", 401, "invalid api key", provider="ollama")),
            "fb-c": fb_response(other, text="云上的答案"),
        })
        result = fallback_module.run_complete(fb_plan(first, same, other), fb_request())
        self.assertEqual(["fb-a", "fb-c"], self.called_ids)      # 同 provider 的 fb-b 未外呼
        self.assertEqual(2, result.selected_index)               # 收口后链上的第三个候选
        self.assertIn("PROVIDER_CONFIG_FAILED", result.reason_codes)
        self.assertEqual(["fb-a", "fb-c"], [a.model_id for a in result.attempts])
        # 被跳过的候选**不产 Attempt**：没有真实调用就没有回执（D4 的记账口径）
        self.assertEqual(2, len(result.attempts))
        self.assertEqual("云上的答案", result.response.content)

    def test_matrix_7_401_still_uses_the_status_code_classification(self):
        # 同一件事的 transport 版：401 的归类来自 `errors.classify`，不是测试自造的异常。
        model = fb_def(id="fb-a")
        self.serve(_response(401, json_body={"error": "unauthorized"}))
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual("config", caught.exception.kind)
        self.assertIn("PROVIDER_CONFIG_FAILED", caught.exception.reason_codes)

    def test_matrix_8_malformed_json_is_classified_not_crashing(self):
        self.use_settings(llm_retry_per_model=1)
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.serve_sequence(_response(200, text="this is not json"),
                            _response(200, json_body=OLLAMA_OK_BODY))
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(2, len(self.requests))
        self.assertEqual("hard", result.attempts[0].error_type)  # 坏响应不重试、可换候选
        self.assertEqual(1, result.selected_index)

    def test_hard_terminal_no_fallback_is_raised_verbatim_and_stops_the_chain(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        terminal = errors.LLMError("hard", 400, "请求不被支持（payload too large）",
                                   no_fallback=True, provider="ollama")
        self.stub_complete({"fb-a": s_raises(terminal), "fb-b": s_raises(
            AssertionError("硬终态之后不该再外呼"))})
        with self.assertRaises(LLMError) as caught:
            fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertIs(caught.exception, terminal)                # **原对象**上抛
        self.assertEqual(["fb-a"], self.called_ids)
        self.assertTrue(caught.exception.no_fallback)
        self.assertFalse(caught.exception.fallback_allowed)

    def test_budget_shrinks_per_call_and_stops_when_exhausted(self):
        self.clock_step = 11.0                                   # 每次外呼真实吃掉 11 秒
        chain = tuple(fb_def(id=f"fb-{i}") for i in range(5))
        failure = fb_error("retryable", 500)
        self.stub_complete({model.id: s_raises(failure) for model in chain})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(fb_plan(*chain), fb_request())
        # min(llm_model_timeout_seconds=20, remaining/1000)：预算 30s，第 4 次外呼不该发生
        self.assertEqual([20.0, 19.0, 8.0], self.timeouts)
        self.assertEqual(3, len(self.calls))
        self.assertTrue(caught.exception.budget_exhausted)
        self.assertIn("FALLBACK_AFTER_TIMEOUT", caught.exception.reason_codes)
        self.assertEqual(3, len(caught.exception.attempts))      # 被预算闸掉的不产回执
        self.assertIn("预算耗尽", str(caught.exception))

    def test_attempt_timeout_is_capped_by_model_timeout_and_by_remaining_budget(self):
        model = fb_def(id="fb-a")
        self.stub_complete({"fb-a": fb_response(model)})
        fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual([20.0], self.timeouts)                  # 预算富余时封顶在模型超时
        self.use_settings(llm_total_budget_ms=5000)              # 预算比模型超时更紧
        fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual(5.0, self.timeouts[-1])

    def test_every_candidate_failing_aggregates_into_one_llm_error(self):
        chain = (fb_def(id="fb-a"), fb_def(id="fb-b"))
        self.stub_complete({model.id: s_raises(fb_error("retryable", 503))
                            for model in chain})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(fb_plan(*chain), fb_request())
        error = caught.exception
        self.assertEqual(["fb-a", "fb-b"], self.called_ids)
        self.assertEqual(2, len(error.attempts))
        self.assertEqual("retryable", error.kind)
        self.assertEqual(503, error.status_code)
        self.assertFalse(error.budget_exhausted)
        self.assertNotIn("问题", str(error))                      # D3：不含请求内容


# --------------------------------------------------------------------------
# 重试预算（llm_retry_per_model）
# --------------------------------------------------------------------------
class RetryBudgetTests(_FallbackFixture):
    def test_retry_count_follows_the_setting_exactly(self):
        model = fb_def(id="fb-a")
        for retry, expected in ((0, 1), (1, 2), (2, 3)):
            with self.subTest(llm_retry_per_model=retry):
                self.calls.clear()
                self.use_settings(llm_retry_per_model=retry, llm_breaker_enabled=False)
                self.stub_complete({"fb-a": s_raises(fb_error("retryable", 500))})
                with self.assertRaises(AllCandidatesFailedError) as caught:
                    fallback_module.run_complete(fb_plan(model), fb_request())
                self.assertEqual(expected, len(self.calls))
                self.assertEqual(expected, len(caught.exception.attempts))
                self.assertTrue(all(a.result == "failed"
                                    for a in caught.exception.attempts))

    def test_model_unavailable_never_retries_the_current_model(self):
        # 冻结：对同一个加载失败的模型再发一次只是白等一次超时 ⇒ 换模型更快。
        self.use_settings(llm_retry_per_model=2, llm_breaker_enabled=False)
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_complete({
            "fb-a": s_raises(fb_error("model_unavailable", 500)),
            "fb-b": fb_response(second),
        })
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(["fb-a", "fb-b"], self.called_ids)
        self.assertEqual(1, result.selected_index)

    def test_config_and_hard_never_retry_the_current_model(self):
        for kind, status in (("config", 403), ("hard", 404)):
            with self.subTest(kind=kind):
                self.calls.clear()
                self.use_settings(llm_retry_per_model=2, llm_breaker_enabled=False)
                model = fb_def(id="fb-a")
                self.stub_complete({"fb-a": s_raises(fb_error(kind, status))})
                with self.assertRaises(AllCandidatesFailedError):
                    fallback_module.run_complete(fb_plan(model), fb_request())
                self.assertEqual(1, len(self.calls))

    def test_retries_share_the_budget_and_each_gets_a_smaller_timeout(self):
        self.clock_step = 12.0
        self.use_settings(llm_retry_per_model=2, llm_breaker_enabled=False)
        model = fb_def(id="fb-a")
        self.stub_complete({"fb-a": s_raises(fb_error("retryable", 500))})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual([20.0, 18.0, 6.0], self.timeouts)       # 30→12→24 秒后的余额
        self.assertTrue(caught.exception.budget_exhausted is False)


# --------------------------------------------------------------------------
# 熔断（D4）
# --------------------------------------------------------------------------
class CircuitBreakerIntegrationTests(_FallbackFixture):
    def _trip_ollama(self, samples: int = 4) -> None:
        failure = fb_error("retryable", 500)
        chain = tuple(fb_def(id=f"fb-{i}") for i in range(samples))
        self.stub_complete({model.id: s_raises(failure) for model in chain})
        with self.assertRaises(AllCandidatesFailedError):
            fallback_module.run_complete(fb_plan(*chain), fb_request())
        self.calls.clear()

    def test_one_breaker_per_provider_and_singleton_reuse(self):
        from app.resilience import CircuitBreaker as _Breaker

        first = fallback_module.circuit_breaker("ollama")
        self.assertIs(first, fallback_module.circuit_breaker("ollama"))
        other = fallback_module.circuit_breaker("deepseek")
        self.assertIsNot(first, other)
        self.assertIsInstance(first, _Breaker)
        self.assertEqual("ollama", first.name)                   # D4：按 provider 命名
        self.assertEqual({"ollama", "deepseek"}, set(fallback_module.BREAKERS))

    def test_open_breaker_skips_candidate_without_call_and_marks_reason(self):
        self._trip_ollama()
        guarded = fb_def(id="fb-guard")
        self.stub_complete({"fb-guard": s_raises(fb_error("retryable", 500))})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(fb_plan(guarded), fb_request())
        self.assertEqual([], self.called_ids)                    # 一次都没外呼
        attempt = caught.exception.attempts[0]
        self.assertEqual("skipped_circuit", attempt.result)
        self.assertIsNone(attempt.error_type)                    # 没有真实调用就没有错误类型
        self.assertEqual(0.0, attempt.latency_ms)
        self.assertIn("CIRCUIT_OPEN", caught.exception.reason_codes)

    def test_skipped_candidate_is_not_recorded_in_the_breaker(self):
        self._trip_ollama()
        breaker = fallback_module.BREAKERS["ollama"]
        guarded = fb_def(id="fb-guard")
        self.stub_complete({"fb-guard": s_raises(fb_error("retryable", 500))})
        with self.assertRaises(AllCandidatesFailedError):
            fallback_module.run_complete(fb_plan(guarded), fb_request())
        self.assertEqual("open", breaker.state)                  # 迟到/跳过回执一律不记（D4）

    def test_open_breaker_does_not_degrade_healthy(self):
        # D4：熔断打开不是「不健康」的一种，它不该冒领 degraded，也不该改 status 的 healthy。
        self._trip_ollama()
        registry = registry_of(fb_def(id="fb-a"))
        view = fallback_module.routing_health_view(registry, include_probes=False)
        self.assertEqual({"healthy": True, "circuit_open": True}, view["ollama"])
        with mock.patch.object(health_module, "provider_health_view",
                               lambda _registry: {"ollama": {"healthy": False}}):
            merged = fallback_module.routing_health_view(registry)
        self.assertEqual({"healthy": False, "circuit_open": True}, merged["ollama"])

    def test_breaker_disabled_bypasses_gate_entirely(self):
        self._trip_ollama()
        self.use_settings(llm_breaker_enabled=False)
        model = fb_def(id="fb-live")
        self.stub_complete({"fb-live": fb_response(model)})
        result = fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual(["fb-live"], self.called_ids)           # OPEN 也照样外呼
        self.assertEqual(0, result.selected_index)
        self.assertNotIn("CIRCUIT_OPEN", result.reason_codes)
        self.assertIsNone(fallback_module.circuit_breaker("ollama"))
        self.assertFalse(fallback_module.circuit_is_open("ollama"))

    def test_receipt_table_matches_the_real_call_outcome(self):
        """「每真实调用回执」（§6）+ D4 的归类表：逐 kind 核对喂给 breaker 的值。"""
        class Recorder:
            state = "closed"

            def __init__(self) -> None:
                self.receipts: list[bool] = []

            def allow(self) -> bool:
                return True

            def record(self, ok: bool) -> None:
                self.receipts.append(ok)

        cases = (
            (fb_error("retryable", 500), False),
            (fb_error("model_unavailable", 500), False),
            (fb_error("config", 401), False),
            (fb_error("hard", 400), True),        # 对方活着并回了话 ⇒ 不是 provider 的锅
            (errors.from_exception(ValueError("boom")), False),   # 外呼没发生 ⇒ 失败回执
        )
        for error, expected in cases:
            with self.subTest(kind=error.kind, status=error.status_code):
                fallback_module.reset_circuit_breakers()
                self.calls.clear()
                recorder = Recorder()
                model = fb_def(id="fb-a")
                self.stub_complete({"fb-a": s_raises(error)})
                patcher = mock.patch.object(fallback_module, "circuit_breaker",
                                            lambda _name: recorder)
                patcher.start()
                with self.assertRaises(AllCandidatesFailedError):
                    fallback_module.run_complete(fb_plan(model), fb_request())
                patcher.stop()
                self.assertEqual([expected], recorder.receipts)

    def test_success_records_a_positive_receipt(self):
        class Recorder:
            state = "closed"

            def __init__(self) -> None:
                self.receipts: list[bool] = []

            def allow(self) -> bool:
                return True

            def record(self, ok: bool) -> None:
                self.receipts.append(ok)

        recorder = Recorder()
        model = fb_def(id="fb-a")
        self.stub_complete({"fb-a": fb_response(model)})
        patcher = mock.patch.object(fallback_module, "circuit_breaker",
                                    lambda _name: recorder)
        patcher.start()
        fallback_module.run_complete(fb_plan(model), fb_request())
        patcher.stop()
        self.assertEqual([True], recorder.receipts)

    def test_hard_with_http_status_is_not_a_provider_failure_and_returns_the_probe_slot(self):
        from app.resilience import CircuitBreaker as _Breaker

        mono = FakeClock(0.0)
        breaker = _Breaker(name="ollama", window=8, failure_ratio=0.30, open_seconds=60,
                           half_open_probes=1, clock=mono)
        for _ in range(4):
            breaker.record(False)
        self.assertEqual("open", breaker.state)
        mono.advance(61.0)                                       # 冷却到期 ⇒ HALF_OPEN
        fallback_module.BREAKERS["ollama"] = breaker

        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_complete({
            "fb-a": s_raises(fb_error("hard", 400)),             # 对方活着并回了话
            "fb-b": fb_response(second),
        })
        result = fallback_module.run_complete(fb_plan(first, second), fb_request())
        self.assertEqual(["fb-a", "fb-b"], self.called_ids)
        # 若 hard 不回执，唯一的名额就泄漏了：第二个候选会被自己的熔断器闸掉。
        self.assertEqual(1, result.selected_index)
        self.assertEqual("closed", breaker.state)


# --------------------------------------------------------------------------
# §7 流式 commit 边界（矩阵 #10 / #11 关键对）
# --------------------------------------------------------------------------
class StreamCommitTests(_FallbackFixture):
    def test_happy_path_commits_at_first_content_chunk(self):
        model = fb_def(id="fb-a")
        self.stream_step = 0.35
        self.stub_stream({"fb-a": s_stream(
            fb_chunk("你"), fb_chunk("好"),
            fb_chunk("", finish=True, usage={"input_tokens": 5, "output_tokens": 2,
                                             "total_tokens": 7, "estimated": False}))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        chunks = self.drain(session)
        self.assertTrue(session.committed)
        self.assertEqual(["你", "好", ""], [c.text for c in chunks])
        summary = session.finish()
        self.assertEqual("你好", summary.response_text)
        self.assertTrue(summary.completed)
        self.assertEqual(0, summary.selected_index)              # 链的第一个候选
        self.assertEqual({"input_tokens": 5, "output_tokens": 2, "total_tokens": 7,
                          "estimated": False}, summary.usage)
        self.assertEqual(350.0, summary.ttft_ms)                 # 第一个**内容** chunk 的时刻
        self.assertEqual("fb-a", summary.model_id)
        self.assertEqual("ollama", summary.provider_name)
        self.assertEqual((("success", None),),
                         tuple((a.result, a.error_type) for a in summary.attempts))

    def test_leading_non_content_chunks_do_not_commit_and_are_withheld(self):
        model = fb_def(id="fb-a")
        self.stream_step = 0.5
        self.stub_stream({"fb-a": s_stream(fb_chunk(""), fb_chunk(""), fb_chunk("首"))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        chunks = self.drain(session)
        self.assertEqual(["首"], [c.text for c in chunks])       # 两个空块没被吐出去
        self.assertEqual(1500.0, session.finish().ttft_ms)        # 3 个 chunk × 500ms

    def test_ttft_is_measured_from_session_start_not_from_the_open(self):
        model = fb_def(id="fb-a")
        self.stream_step = 0.25
        self.stub_stream({"fb-a": s_stream(fb_chunk("第一段"), fb_chunk("第二段"))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        self.drain(session)
        self.assertEqual(250.0, session.finish().ttft_ms)

    def test_matrix_10_pre_commit_failure_switches_model_invisibly(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_stream({
            "fb-a": s_stream(fb_chunk(""), then=fb_error("retryable", 500)),
            "fb-b": s_stream(fb_chunk("换了模型的答案")),
        })
        session = fallback_module.run_stream(fb_plan(first, second), fb_request())
        chunks = self.drain(session)
        self.assertEqual(["换了模型的答案"], [c.text for c in chunks])   # 用户无感
        self.assertEqual(["fb-a", "fb-b"], self.called_ids)
        self.assertEqual(1, session.selected_index)
        self.assertTrue(session.committed)
        summary = session.finish()
        self.assertEqual([("failed", "retryable"), ("success", None)],
                         [(a.result, a.error_type) for a in summary.attempts])
        self.assertEqual("换了模型的答案", summary.response_text)

    def test_config_failure_in_stream_skips_the_rest_of_that_provider(self):
        first = fb_def(id="fb-a")
        same_provider = fb_def(id="fb-b")
        other = fb_def(id="fb-c", provider="deepseek")
        self.stub_stream({
            "fb-a": s_stream_raises(fb_error("config", 401, provider="ollama")),
            "fb-c": s_stream(fb_chunk("云上")),
        })
        session = fallback_module.run_stream(fb_plan(first, same_provider, other),
                                             fb_request())
        self.assertEqual(["云上"], [c.text for c in self.drain(session)])
        self.assertEqual(["fb-a", "fb-c"], self.called_ids)      # fb-b 一次都没被调用
        self.assertIn("PROVIDER_CONFIG_FAILED", session.reason_codes)
        self.assertEqual(2, session.selected_index)              # 收口后链上的第三个候选

    def test_pre_commit_open_failure_and_ordinary_failures_both_switch(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_stream({
            "fb-a": s_stream_raises(fb_error("retryable", 500)),   # 请求都没发出去就失败
            "fb-b": s_stream(fb_chunk("答案")),
        })
        session = fallback_module.run_stream(fb_plan(first, second), fb_request())
        chunks = self.drain(session)
        self.assertEqual(["答案"], [c.text for c in chunks])
        self.assertEqual(1, session.selected_index)
        self.assertEqual([("failed", "retryable"), ("success", None)],
                         [(a.result, a.error_type) for a in session.attempts])

    def test_matrix_11_post_commit_failure_never_switches_model(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.use_settings(llm_retry_per_model=2)                 # 有重试额度也不许重开
        self.stub_stream({
            "fb-a": s_stream(fb_chunk("已经给你"), then=fb_error("retryable", 500)),
            "fb-b": s_stream(fb_chunk("绝不该出现")),
        })
        session = fallback_module.run_stream(fb_plan(first, second), fb_request())
        delivered = []
        with self.assertRaises(StreamInterrupted) as caught:
            for item in session.chunks():
                delivered.append(item.text)
        self.assertEqual(["已经给你"], delivered)
        self.assertEqual(["fb-a"], self.called_ids)              # 第二个候选一次都没被调用
        error = caught.exception
        self.assertTrue(session.committed)
        self.assertEqual("已经给你", error.partial_text)
        self.assertEqual(0, error.selected_index)
        self.assertEqual("retryable", error.error_type)
        self.assertEqual(1, len(error.attempts))
        self.assertEqual("fb-a", error.model_id)

    def test_post_commit_config_failure_also_stops_the_chain(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_stream({
            "fb-a": s_stream(fb_chunk("内容"), then=fb_error("config", 403)),
            "fb-b": s_stream(fb_chunk("不")),
        })
        session = fallback_module.run_stream(fb_plan(first, second), fb_request())
        with self.assertRaises(StreamInterrupted):
            self.drain(session)
        self.assertEqual(["fb-a"], self.called_ids)

    def test_usage_is_taken_from_the_successful_attempt_only(self):
        first, second = fb_def(id="fb-a"), fb_def(id="fb-b")
        self.stub_stream({
            "fb-a": s_stream(fb_chunk("", usage={"input_tokens": 999, "output_tokens": 999,
                                                 "total_tokens": 1998, "estimated": False}),
                             then=fb_error("retryable", 500)),
            "fb-b": s_stream(fb_chunk("答"),
                             fb_chunk("", finish=True,
                                      usage={"input_tokens": 7, "output_tokens": 3,
                                             "total_tokens": 10, "estimated": False})),
        })
        session = fallback_module.run_stream(fb_plan(first, second), fb_request())
        self.drain(session)
        summary = session.finish()
        self.assertEqual({"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                          "estimated": False}, summary.usage)    # 失败轮的半截账被丢弃

    def test_missing_usage_is_zeroed_and_marked_estimated(self):
        model = fb_def(id="fb-a")
        self.stub_stream({"fb-a": s_stream(fb_chunk("没有 usage"))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        self.drain(session)
        self.assertEqual({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
                          "estimated": True}, session.finish().usage)

    def test_all_candidates_failing_pre_commit_raises_the_aggregate(self):
        chain = (fb_def(id="fb-a"), fb_def(id="fb-b"))
        self.stub_stream({model.id: s_stream_raises(fb_error("retryable", 502))
                          for model in chain})
        session = fallback_module.run_stream(fb_plan(*chain), fb_request())
        with self.assertRaises(AllCandidatesFailedError) as caught:
            self.drain(session)
        self.assertEqual(2, len(caught.exception.attempts))
        summary = session.finish()                               # 抛错后仍可汇总（T7 记账）
        self.assertIsNone(summary.response_text)
        self.assertFalse(summary.committed)
        self.assertFalse(summary.completed)
        self.assertEqual(-1, summary.selected_index)
        self.assertEqual("retryable", summary.error_type)

    def test_clean_empty_stream_is_a_success_not_a_failure(self):
        model = fb_def(id="fb-a")
        self.stub_stream({"fb-a": s_stream()})                   # 一个 chunk 都没有
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        self.assertEqual([], self.drain(session))
        summary = session.finish()
        self.assertTrue(summary.completed)
        self.assertFalse(summary.committed)                      # 从未交付过内容
        self.assertEqual(0, summary.selected_index)
        self.assertEqual(["fb-a"], self.called_ids)              # 没有第二次外呼

    def test_breaker_open_skips_candidate_in_stream_too(self):
        failure = fb_error("retryable", 500)
        chain = tuple(fb_def(id=f"fb-{i}") for i in range(4))
        self.stub_stream({model.id: s_stream_raises(failure) for model in chain})
        with self.assertRaises(AllCandidatesFailedError):
            self.drain(fallback_module.run_stream(fb_plan(*chain), fb_request()))
        self.calls.clear()
        guarded = fb_def(id="fb-guard")
        survivor = fb_def(id="fb-live", provider="deepseek")
        self.stub_stream({"fb-guard": s_stream_raises(failure),
                          "fb-live": s_stream(fb_chunk("活着"))})
        session = fallback_module.run_stream(fb_plan(guarded, survivor), fb_request())
        self.assertEqual(["活着"], [c.text for c in self.drain(session)])
        self.assertEqual(["fb-live"], self.called_ids)           # ollama 被闸住
        self.assertIn("CIRCUIT_OPEN", session.reason_codes)
        self.assertEqual([("skipped_circuit", None), ("success", None)],
                         [(a.result, a.error_type) for a in session.attempts])

    def test_stream_budget_shrinks_across_candidates(self):
        self.clock_step = 12.0
        chain = tuple(fb_def(id=f"fb-{i}") for i in range(4))
        self.stub_stream({model.id: s_stream_raises(fb_error("retryable", 500))
                          for model in chain})
        session = fallback_module.run_stream(fb_plan(*chain), fb_request())
        with self.assertRaises(AllCandidatesFailedError) as caught:
            self.drain(session)
        self.assertEqual([20.0, 18.0, 6.0], self.timeouts)
        self.assertEqual(3, len(self.calls))
        self.assertTrue(caught.exception.budget_exhausted)
        self.assertEqual((), tuple(a for a in session.attempts
                                   if a.result == "skipped_circuit"))

    def test_session_is_single_use_and_finish_needs_consumption(self):
        model = fb_def(id="fb-a")
        self.stub_stream({"fb-a": s_stream(fb_chunk("x"))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        with self.assertRaises(RuntimeError):
            session.finish()                                     # 没消费就没有账可汇总
        self.drain(session)
        with self.assertRaises(RuntimeError):
            session.chunks()                                     # 重开请求归执行器负责

    def test_stream_session_exposes_the_frozen_surface(self):
        import inspect

        self.assertEqual(["self"], list(inspect.signature(StreamSession.finish).parameters))
        self.assertEqual(["self"], list(inspect.signature(StreamSession.chunks).parameters))
        model = fb_def(id="fb-a")
        self.stub_stream({"fb-a": s_stream(fb_chunk("x"))})
        session = fallback_module.run_stream(fb_plan(model), fb_request())
        self.assertEqual(30000.0, session.budget_ms)
        self.assertEqual(0, session.context_dropped)
        self.assertEqual((), session.attempts)
        self.assertEqual("", session.partial_text)
        self.assertIsNone(session.selected_candidate)
        self.drain(session)
        self.assertEqual(0, session.selected_index)
        self.assertIsNotNone(session.selected_candidate)


# --------------------------------------------------------------------------
# 包级公共入口：router_enabled / complete / stream + usage 接缝
# --------------------------------------------------------------------------
class PackageEntryPointTests(_FallbackFixture):
    def setUp(self) -> None:
        super().setUp()
        # 路由视图不打探针（`routing_health_view` 会走 health.provider_health_view）
        patcher = mock.patch.object(fallback_module, "routing_health_view",
                                    lambda *args, **kwargs: {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.records: list[UsageRecord] = []
        previous = llm.set_usage_sink(self.records.append)
        self.addCleanup(lambda: llm.set_usage_sink(previous))
        llm.reset_circuit_breakers()

    def use_registry(self, *models: ModelDefinition) -> None:
        patcher = mock.patch.object(llm, "get_registry", lambda: registry_of(*models))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_router_enabled_reads_the_flag_from_settings(self):
        self.assertTrue(llm.router_enabled())                    # §12 默认 true
        self.use_settings(llm_router_enabled=False)
        self.assertFalse(llm.router_enabled())
        self.assertTrue(callable(llm.router_enabled))            # 函数而非常量快照

    def test_complete_orchestrates_classify_plan_run(self):
        first = fb_def(id="fb-a", priority={"chat": 10, "rag": 10, "tools": 10})
        second = fb_def(id="fb-b", priority={"chat": 5, "rag": 5, "tools": 5})
        self.use_registry(first, second)
        self.stub_complete({"fb-a": fb_response(first, text="主答")})
        result = llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertIsInstance(result, FallbackResult)
        self.assertEqual("主答", result.response.content)
        self.assertEqual(0, result.selected_index)
        # 计划码在前（router 的入选理由）、执行期码在后 —— T3 移交③的 concat 口径
        self.assertEqual(("CAPABILITY_MATCH", "LOCAL_PREFERRED", "HIGHER_PRIORITY"),
                         result.reason_codes)
        self.assertEqual(["fb-a"], self.called_ids)

    def test_complete_passes_every_request_knob_into_llm_request(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        seen: list[LLMRequest] = []

        def fake(_model, req, _timeout):
            seen.append(req)
            return fb_response(_model)

        patcher = mock.patch.object(provider_module, "complete", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        llm.complete([{"role": "system", "content": "略"}, {"role": "user", "content": "问题"}],
                     mode="rag", temperature=0.1, tools=[{"type": "function"}],
                     think=True, num_predict=256, keep_alive="30m")
        req = seen[0]
        self.assertEqual(0.1, req.temperature)
        self.assertEqual([{"type": "function"}], req.tools)
        self.assertIs(True, req.think)
        self.assertEqual(256, req.num_predict)
        self.assertEqual("30m", req.keep_alive)
        self.assertEqual(2, len(req.messages))
        self.assertEqual("问题", llm._query_of(req.messages))     # 分类只看最后一条消息

    def test_classifier_is_skipped_when_the_caller_brings_a_profile(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.stub_complete({"fb-a": fb_response(model)})
        with mock.patch.object(llm, "classify",
                               side_effect=AssertionError("给了 profile 还去 classify")):
            result = llm.complete([{"role": "user", "content": "你好"}], mode="chat",
                                  profile=profile_of(mode="chat", complexity="high"))
        self.assertEqual(0, result.selected_index)
        self.assertEqual(1, len(self.records))
        self.assertEqual("chat", self.records[0].route_mode)     # mode 取调用点声明

    def test_stream_requires_stream_capability_by_default(self):
        no_stream = fb_def(id="fb-nostream",
                           capabilities={"chat": True, "rag": True, "tools": True,
                                         "stream": False, "reasoning": False},
                           priority={"chat": 99, "rag": 99, "tools": 99})
        streams = fb_def(id="fb-stream", priority={"chat": 10, "rag": 10, "tools": 10})
        self.use_registry(no_stream, streams)
        self.stub_stream({"fb-stream": s_stream(fb_chunk("流"))})
        session = llm.stream([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual(["流"], [c.text for c in self.drain(session)])
        self.assertEqual(["fb-stream"], self.called_ids)         # 高分但不会流 ⇒ 不入选

        self.calls.clear()
        self.stub_complete({"fb-nostream": fb_response(no_stream)})
        result = llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual(["fb-nostream"], self.called_ids)       # 非流式入口放宽该要求
        self.assertEqual("fb-nostream", result.attempts[0].model_id)

    def test_no_capable_model_is_propagated_not_swallowed(self):
        # Task 3 移交③：出厂注册表无 key 时 agent 必然零候选 ⇒ fast-path 是常驻主干分支。
        self.use_settings(llm_registry_file=str(SHIPPED_REGISTRY), openai_api_key="")
        registry = load_registry(str(SHIPPED_REGISTRY))
        patcher = mock.patch.object(llm, "get_registry", lambda: registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.assertRaises(NoCapableModelError) as caught:
            llm.complete([{"role": "user", "content": "调用工具"}], mode="agent",
                         tools=[{"type": "function"}])
        self.assertEqual("capability", caught.exception.stage)
        self.assertEqual([], self.called_ids)                    # 未发出任何外呼
        self.assertEqual([], self.records)                       # 零候选没有 provider 事实

    def test_usage_sink_receives_a_row_on_success(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.clock_step = 0.4                                    # 每次外呼真实花 400ms
        self.stub_complete({"fb-a": fb_response(model, input_tokens=11, output_tokens=5)})
        result = llm.complete([{"role": "user", "content": "你好"}], mode="chat",
                              trace_id="t-1", request_id="r-1")
        self.assertEqual(1, len(self.records))
        record = self.records[0]
        self.assertEqual("t-1", record.trace_id)
        self.assertEqual("r-1", record.request_id)
        self.assertEqual("chat", record.route_mode)
        self.assertEqual("ollama", record.provider)
        self.assertEqual(model.model, record.model)
        self.assertEqual(0, record.fallback_index)
        self.assertEqual(16, record.total_tokens)
        self.assertTrue(record.success)
        self.assertIsNone(record.error_type)
        self.assertEqual(result.reason_codes, record.route_reason)
        self.assertEqual(400.0, record.latency_ms)               # 全链 attempt 之和（预算口径）

    def test_usage_sink_receives_a_failure_row_and_the_error_still_propagates(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.stub_complete({"fb-a": s_raises(fb_error("retryable", 503))})
        with self.assertRaises(AllCandidatesFailedError):
            llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual(1, len(self.records))
        record = self.records[0]
        self.assertFalse(record.success)
        self.assertEqual("retryable", record.error_type)
        self.assertEqual(503, record.status_code)
        self.assertEqual(-1, record.fallback_index)

    def test_usage_sink_failure_is_fail_open(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.stub_complete({"fb-a": fb_response(model)})

        def explode(_record):
            raise RuntimeError("数据库写不进去")

        llm.set_usage_sink(explode)
        result = llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual("好的", result.response.content)        # 记账失败不影响生成

    def test_usage_sink_falls_back_to_late_bound_app_llm_usage(self):
        """T5 接缝的三面：显式 sink 优先 → 惰性解析 `usage.log_usage` → 取不到才静默跳过。

        `app/llm/usage.py` 已由 Task 5 建好，所以「惰性解析」这一支**今天真的解析得到**
        落库函数——这正是 T4 留接缝的目的：T5 不必回来改 T4 的编排就自动接上。原来那句
        「今天的真实状态：没有 usage 模块」的钉随 T5 落地而失效，于是改钉成三面。

        面 3 打的是**包属性** `llm.usage`，不是 `sys.modules`：`from app.llm import usage`
        先读父包上的子模块属性，真模块一旦被 import 过，只换 `sys.modules` 换不掉它
        （第一版就是这么红的：`usage_sink()` 返回了真 `log_usage`）。
        """
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.stub_complete({"fb-a": fb_response(model)})
        rows: list[UsageRecord] = []
        sink = rows.append

        previous = llm.set_usage_sink(sink)
        self.addCleanup(llm.set_usage_sink, previous)
        self.assertIs(llm.usage_sink(), sink)                     # 面 1：显式 sink 在前
        self.assertIs(llm.set_usage_sink(None), sink)             # 返回值 = 前一个 sink

        llm.set_usage_sink(None)                                  # 面 2：T5 自动接线
        self.assertIs(llm.usage_sink(), usage_module.log_usage)

        with mock.patch.object(llm, "usage", mock.MagicMock(spec=[]), create=True):
            self.assertIsNone(llm.usage_sink())                   # 面 3：无落库函数
            result = llm.complete([{"role": "user", "content": "你好"}], mode="chat")
        self.assertEqual("好的", result.response.content)          # 记账缺口不影响生成
        self.assertEqual([], rows)

    def test_log_stream_usage_folds_a_summary_into_a_row(self):
        model = fb_def(id="fb-a")
        self.use_registry(model)
        self.stream_step = 0.45                                  # 2 个 chunk ⇒ 全链 900ms
        self.stub_stream({"fb-a": s_stream(
            fb_chunk("答"), fb_chunk("", finish=True,
                                     usage={"input_tokens": 3, "output_tokens": 4,
                                            "total_tokens": 7, "estimated": False}))})
        session = llm.stream([{"role": "user", "content": "你好"}], mode="rag")
        self.drain(session)
        summary = session.finish()
        record = llm.log_stream_usage(summary, mode="rag", trace_id="t", request_id="r")
        self.assertEqual(1, len(self.records))
        self.assertIs(self.records[0], record)
        self.assertEqual(3, record.input_tokens)
        self.assertEqual(4, record.output_tokens)
        self.assertEqual(7, record.total_tokens)
        self.assertEqual(450.0, record.ttft_ms)
        self.assertEqual("rag", record.route_mode)
        self.assertTrue(record.success)
        self.assertEqual(0, record.fallback_index)
        # I1：`latency_ms` 是**实测全链**（与非流式 `_usage_from_result` 同口径）。
        # 写成 `summary.budget_ms` 就是把配置常数（默认 30000）落进 §8 的延迟列，
        # 于是 `p95_latency_ms` 永远钉在预算天花板上，快链慢链在观测面上不可区分。
        self.assertEqual(900.0, sum(a.latency_ms for a in summary.attempts))
        self.assertEqual(900.0, record.latency_ms)
        self.assertNotEqual(summary.budget_ms, record.latency_ms)
        # `budget_ms` 的独立断言：它仍然是「这次给了多少预算」的事实，留在汇总面上
        # （trace / T7 payload 消费）；§8 冻结 19 列没有 budget 列 ⇒ 既不当延迟也不加列。
        self.assertEqual(30000.0, summary.budget_ms)
        self.assertEqual(float(self.settings.llm_total_budget_ms), summary.budget_ms)
        self.assertFalse(hasattr(record, "budget_ms"))

    def test_log_stream_usage_latency_is_the_sum_of_every_hop_not_the_last_one(self):
        """两跳流式链（pre-commit 静默换模型，矩阵 #10 的形状）的账本口径。

        单跳用例证不了「之和」：这里第一跳失败 200ms、第二跳成功 400ms，
        行里必须是 600ms —— 既不是最后一跳（400），也不是预算（30000）。
        """
        first = fb_def(id="fb-a", priority={"chat": 10, "rag": 10, "tools": 10})
        second = fb_def(id="fb-b", priority={"chat": 5, "rag": 5, "tools": 5})
        self.use_registry(first, second)
        self.clock_step = 0.2                                    # 每次真实外呼进闸 200ms
        self.stream_step = 0.1                                   # 第二跳 2 个 chunk × 100ms
        self.stub_stream({
            "fb-a": s_stream_raises(fb_error("retryable", 500)),
            "fb-b": s_stream(fb_chunk("换了模型的答案"),
                             fb_chunk("", finish=True,
                                      usage={"input_tokens": 2, "output_tokens": 3,
                                             "total_tokens": 5, "estimated": False})),
        })
        session = llm.stream([{"role": "user", "content": "你好"}], mode="rag")
        self.drain(session)
        summary = session.finish()
        self.assertEqual(["fb-a", "fb-b"], self.called_ids)
        self.assertEqual((200.0, 400.0), tuple(a.latency_ms for a in summary.attempts))
        record = llm.log_stream_usage(summary, mode="rag")
        self.assertEqual(600.0, record.latency_ms)               # 两跳之和
        self.assertNotEqual(summary.attempts[-1].latency_ms, record.latency_ms)
        self.assertNotEqual(summary.budget_ms, record.latency_ms)
        self.assertEqual(1, record.fallback_index)               # 内容来自第二跳
        self.assertTrue(record.success)
        self.assertIsNone(record.error_type)                     # 成功收尾不冒领会话级错误

    def test_package_reexports_the_executor_surface(self):
        for name in ("run_complete", "run_stream", "FallbackResult", "Attempt",
                     "StreamSession", "StreamSummary", "StreamInterrupted",
                     "AllCandidatesFailedError", "router_enabled", "complete", "stream",
                     "reset_circuit_breakers", "log_stream_usage", "set_usage_sink"):
            self.assertIn(name, llm.__all__)
            self.assertIsNotNone(getattr(llm, name))
        self.assertIs(llm.run_complete, fallback_module.run_complete)
        self.assertIs(llm.FallbackResult, fallback_module.FallbackResult)
        self.assertIs(llm.StreamInterrupted, fallback_module.StreamInterrupted)


def _dc_fields(cls):
    from dataclasses import fields as _fields
    return _fields(cls)


# --------------------------------------------------------------------------
# model_override 端到端（Task 1 移交项在整条链上的落点）
# --------------------------------------------------------------------------
class ModelOverrideEndToEndTests(_FallbackFixture):
    def test_override_replaces_the_wire_model_and_the_usage_attribution(self):
        model = fb_def(id="fb-openai", provider="openai", model="registry-name",
                       external=True)
        self.use_settings(openai_api_key="sk-test-key")
        with mock.patch.dict(os.environ, {"OPENAI_MODEL_OVERRIDE": "prod-alias-2026"}):
            self.serve(_response(200, json_body={
                "choices": [{"message": {"role": "assistant", "content": "改写后的名字"},
                             "finish_reason": "stop"}],
                "model": "prod-alias-2026",
                "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}))
            result = fallback_module.run_complete(fb_plan(model), fb_request())
        self.assertEqual("prod-alias-2026", self.last.payload["model"])   # 请求体用别名
        self.assertEqual("prod-alias-2026", result.response.model)         # 归因指向真被调的
        self.assertEqual(0, result.selected_index)
        self.assertEqual("改写后的名字", result.response.content)
        self.assertEqual("openai", result.attempts[0].provider)


# ==========================================================================
# Task 6：RAG 生成链迁移（§9 第一条）+ 矩阵 #18 的 legacy 双路等价 + T5 移交的执行面 `plan`
#
# 三条纪律：
# 1. **报文面而不是响应面**。矩阵 #18 要的是「旗标关掉 ⇒ 三链回到今天的报文」，只看返回
#    文本抓不到温度漂移，所以 router 腿走**真** `provider` + `httpx.MockTransport`
#    （注入点 `provider_module._transport`），legacy 腿走 `httpx.post` 替身并**录下请求体**，
#    两侧同一次问答的 payload 逐键对比。偏差只允许被**枚举**，不允许被忽略。
# 2. **零真实外呼**。两条腿都是替身；健康视图整轮换成 stub（`provider_health_view`），
#    于是 `self.requests` 里出现的每一个请求都是这次生成该出现的。
# 3. **既有契约不降强度**。`[1]` 引用标记、`联网来源：` 尾块、`注：本次联网检索部分失败…`
#    那一句的位置与措辞、`已完成检索，但当前 LLM 服务不可用…` + `模型连接错误：{类名}`
#    都在 router 路上重钉一遍（今天只有 legacy 路钉着它们）。
# ==========================================================================

#: 与 `_EgressFixture.use_settings` 的默认值同名：两条腿的 `model` 键因此可以直比。
RAG_LOCAL_MODEL = "ornith-1.5:9b-text"
RAG_CLOUD_MODEL = "gpt-4.1-mini"
#: 一次问答的固定证据行（企业知识库 + 联网行）。
ENTERPRISE_ROWS: list[dict] = [
    {"id": "p-1", "file_name": "报销制度.md", "page": 3, "content": "差旅住宿上限每天陆佰元。"},
]
WEB_ROWS: list[dict] = [
    {"source_type": "web", "file_name": "财政部通知", "url": "https://example.gov/notice",
     "content": "2026 年差旅标准调整。"},
]
#: 中文 canary：埋在问题里，落库后全列扫 0 命中（D3 禁存项，沿用 Task 5 的姿势）。
RAG_PROMPT_CANARY = "涉密项目代号玄武的年度预算上限为人民币玖仟万元整"
PLAIN_QUESTION = "差旅住宿上限是多少？" + RAG_PROMPT_CANARY
ROUTER_ANSWER = "差旅住宿上限每天陆佰元 [1]。"
WEB_QUESTION = "[[NEXUS_WEB_SEARCH]] 差旅标准今年调过吗？" + RAG_PROMPT_CANARY
LLM_UNAVAILABLE_COPY = "已完成检索，但当前 LLM 服务不可用，因此暂不生成推断性答案。"


def rag_entry(**overrides) -> ModelDefinition:
    """RAG 迁移用例的条目底座：一条本地 ollama 候选（rag 档 100 分）。"""
    data = {
        "id": "ollama-ornith", "provider": "ollama", "model": RAG_LOCAL_MODEL,
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": False, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 100, "rag": 100, "tools": 0},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def cloud_entry(**overrides) -> ModelDefinition:
    """OpenAI 兼容腿：`model` 与 `settings.openai_model` 同名 ⇒ 两侧 `model` 键可直比。"""
    data = {
        "id": "openai", "provider": "openai", "model": RAG_CLOUD_MODEL,
        "enabled": True, "external": True,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 100, "rag": 100, "tools": 100},
        "limits": {"context_tokens": 128000, "max_output_tokens": 8192},
        "pricing": {"input_per_1m": 0.40, "output_per_1m": 1.60, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def ollama_body(content: str, model: str = RAG_LOCAL_MODEL) -> dict:
    return {"model": model, "message": {"role": "assistant", "content": content},
            "done": True, "done_reason": "stop",
            "prompt_eval_count": 11, "eval_count": 7}


def openai_body(content: str, model: str = RAG_CLOUD_MODEL) -> dict:
    return {"model": model,
            "choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}}


class LegacyPost:
    """一次被录下来的 legacy 出口调用（url + 全部关键字参数）。"""

    def __init__(self, url: str, kwargs: dict) -> None:
        self.url = url
        self.kwargs = kwargs


class _RagMigrationFixture(_EgressFixture):
    """Task 6 底座：真 `provider` 出口（MockTransport）+ legacy `httpx.post` 替身 + 临时账本。

    与 `_FallbackFixture` 的差别刻意在**不 stub provider**：温度等价与 usage 落库都要走完整
    的 `llm.complete → classify → plan → run_complete → provider → normalize → httpx` 链，
    stub 掉 provider 就等于把「报文里真的写了 0.1」换成「我告诉它写了 0.1」。
    """

    RAG_SETTINGS_DEFAULTS: dict = {
        "llm_router_enabled": True,
        "llm_retry_per_model": 0,
        "llm_total_budget_ms": 30000,
        "llm_model_timeout_seconds": 20,
        "llm_breaker_enabled": False,        # 本组测的是链的形状，不是熔断；熔断另有 T4 专测
        "web_search_enabled": True,
    }

    def setUp(self) -> None:
        fallback_module.reset_circuit_breakers()
        self.addCleanup(fallback_module.reset_circuit_breakers)
        self.legacy_calls: list[LegacyPost] = []
        super().setUp()                                      # 内部调用 self.use_settings
        # 账本：临时库 + 真 `log_usage`（sink 置 None ⇒ 包级惰性解析到它）。
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "conversations.db"
        usage_module.reset_usage_state()
        self.addCleanup(usage_module.reset_usage_state)
        usage_module.init_usage_db(self.db_path)
        previous_sink = llm.set_usage_sink(None)
        self.addCleanup(lambda: llm.set_usage_sink(previous_sink))
        # 第三道（与 `_FallbackFixture._isolate_usage_ledger` 同一理由）：`init_usage_db`
        # 的覆盖值优先于 env，所以本行今天不改变任何落点；它挡的是「有人把覆盖值删了」——
        # 那种事故下生效路径会退回 `database_path()` 的 env 源，而 env 被外层 clear 掉了
        # ⇒ 直接写仓库真库。护栏（`tests/conftest.py`）是第四道。
        env = mock.patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(self.db_path)})
        env.start()
        self.addCleanup(env.stop)

    def use_settings(self, **overrides) -> Settings:
        base = dict(self.RAG_SETTINGS_DEFAULTS)
        base.update(overrides)
        fake = super().use_settings(**base)
        # `_EgressFixture` 只打到 registry/health/rag 三处；旗标与预算要打在包级和执行面上。
        for module in (llm, fallback_module, usage_module):
            patcher = mock.patch.object(module, "settings", fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.settings = fake
        return fake

    def use_registry(self, *models: ModelDefinition) -> None:
        """候选链由用例给；`llm` 与 `usage` 两处指到同一份（model 列与成本都要查它）。"""
        registry = Registry(models=models or (rag_entry(),))
        for module in (llm, usage_module):
            patcher = mock.patch.object(module, "get_registry", lambda: registry)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.registry = registry

    def healthy_providers(self, **unhealthy: bool) -> None:
        """健康视图 stub（**不打探针**）：`healthy_providers(ollama=False)` 造不健康。"""
        def fake_view(registry):
            names = sorted({m.provider for m in registry.models if m.enabled})
            return {name: {"healthy": bool(unhealthy.get(name, True))} for name in names}
        patcher = mock.patch.object(health_module, "provider_health_view", fake_view)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fail_on_any_probe(self) -> None:
        """比 `healthy_providers` 更硬：探针函数一被调用就让测试炸。"""
        def forbidden(*args, **kwargs):
            raise AssertionError("展示面/生成面不许打健康探针")
        patcher = mock.patch.object(health_module, "provider_health_view", forbidden)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- 两条腿互相禁用的两道闸 -------------------------------------------
    def guard_legacy_egress_off(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("router 路上不得再走 legacy 的 httpx.post（那是第二条出口）")
        patcher = mock.patch.object(rag_module.httpx, "post", forbidden)
        patcher.start()
        self.addCleanup(patcher.stop)

    def guard_router_off(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("LLM_ROUTER_ENABLED=false 时不得调用 llm.complete()")
        patcher = mock.patch.object(llm, "complete", forbidden)
        patcher.start()
        self.addCleanup(patcher.stop)

    def legacy_serve(self, body: dict | None, *, exc: BaseException | None = None) -> None:
        def fake_post(url, **kwargs):
            self.legacy_calls.append(LegacyPost(url, kwargs))
            if exc is not None:
                raise exc
            # `raise_for_status()` 在 httpx 0.28 上要求 response 带着 request（真客户端
            # 由 transport 挂上去），所以这里替身自己挂一次。
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))
        patcher = mock.patch.object(rag_module.httpx, "post", fake_post)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- 账本直读 ----------------------------------------------------------
    def raw_rows(self) -> list[dict]:
        import sqlite3
        connection = sqlite3.connect(self.db_path)
        try:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(
                "SELECT * FROM llm_request_logs ORDER BY id")]
        finally:
            connection.close()


# --------------------------------------------------------------------------
# 1. 迁移面：走 router、一次外呼、答案形状与既有契约不变
# --------------------------------------------------------------------------
class RagRouterMigrationTests(_RagMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.use_registry(rag_entry())
        self.healthy_providers()

    def route_leg(self, body: dict | None = None, question: str = PLAIN_QUESTION,
                  rows: list[dict] | None = None) -> str:
        """router 腿：真 `llm.complete` → 真 provider → MockTransport；legacy 出口上闸。"""
        self.use_settings(llm_router_enabled=True)
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=body if body is not None
                             else ollama_body(ROUTER_ANSWER)))
        return rag_module.generate_answer(question,
                                          ENTERPRISE_ROWS if rows is None else rows)

    def test_the_rag_chain_goes_through_the_router_exactly_once(self):
        answer = self.route_leg()
        self.assertEqual(ROUTER_ANSWER, answer)
        self.assertEqual(1, len(self.requests), "一次问答应当只有一次真实外呼")
        self.assertEqual(OLLAMA_CHAT_URL, self.requests[-1].url)
        payload = self.requests[-1].payload
        self.assertEqual(RAG_LOCAL_MODEL, payload["model"])
        self.assertEqual(["system", "user"], [m["role"] for m in payload["messages"]])
        self.assertEqual(rag_module.SYSTEM_PROMPT, payload["messages"][0]["content"])

    def test_the_prompt_still_carries_the_citation_and_evidence_contract(self):
        """`[1]` 引用与证据块的措辞（既有契约，迁移不许降强度）。"""
        self.route_leg()
        user = self.last.payload["messages"][1]["content"]
        self.assertIn("[1] 类型：企业知识库", user)
        self.assertIn("来源：报销制度.md，第 3 页", user)
        self.assertIn("请给出答案，并对关键结论标注引用编号", user)
        self.assertIn("答案必须使用简体中文", user)
        self.assertIn(PLAIN_QUESTION, user)
        self.assertIn("用户未开启联网搜索，只使用企业知识库证据。", user)
        self.assertNotIn("[[NEXUS_WEB_SEARCH]]", user)      # 标记被 clean_question 剥掉

    def test_web_sources_tail_block_keeps_position_and_wording(self):
        """`联网来源：` 尾块的形状与编号偏移（企业条数之后继续排）逐字不变。"""
        with mock.patch.object(rag_module, "search_web", return_value=list(WEB_ROWS)):
            answer = self.route_leg(body=ollama_body("答案是陆佰元 [1] [2]。\n\n"),
                                    question=WEB_QUESTION)
        lines = answer.split("\n")
        self.assertEqual(["", "联网来源："], lines[-3:-1])
        self.assertEqual("- [2] 财政部通知 — https://example.gov/notice", lines[-1])
        self.assertIn("答案是陆佰元 [1] [2]。", answer)
        self.assertTrue(answer.endswith("\n联网来源：\n- [2] 财政部通知 — "
                                        "https://example.gov/notice"))
        self.assertNotIn("注：本次联网检索部分失败", answer)   # 没失败就不该出现那一注
        # 联网证据进 prompt 的那一块也仍是原形状（build_context 未迁移）。
        self.assertIn("[2] 类型：互联网检索", self.last.payload["messages"][1]["content"])
        self.assertIn("用户已明确开启联网搜索。企业知识库证据优先",
                      self.last.payload["messages"][1]["content"])

    def test_the_partial_failure_note_keeps_position_and_wording(self):
        """联网失败那一注**接在正文之后、尾块之前**（这里 web_rows 为空 ⇒ 只有那一注）。"""
        with mock.patch.object(rag_module, "search_web",
                               side_effect=RuntimeError("上游 500")):
            answer = self.route_leg(body=ollama_body("部分成功 [1]"), question=WEB_QUESTION)
        self.assertEqual("部分成功 [1]\n\n注：本次联网检索部分失败，答案主要依据已成功获得的"
                         "证据。", answer)
        self.assertNotIn("联网来源：", answer)

    def test_no_evidence_short_circuits_without_any_egress(self):
        self.assertEqual("当前知识库中未找到可靠依据。",
                         rag_module.generate_answer(PLAIN_QUESTION, []))
        self.assertEqual([], self.requests)

    def test_the_plan_travels_with_the_result_the_rag_chain_gets(self):
        """T5 移交的义务在**真链**上可用：`result.plan` 是 `RoutePlan`，且 primary 与响应
        模型名同源。（矩阵 #17 的 trace 半段归 T7/T8：RAG 链今天没有 trace。）"""
        seen: list = []
        real_complete = llm.complete

        def spy(*args, **kwargs):
            result = real_complete(*args, **kwargs)
            seen.append(result)
            return result

        patcher = mock.patch.object(llm, "complete", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.route_leg()
        self.assertEqual(1, len(seen))
        result = seen[0]
        self.assertIsInstance(result.plan, RoutePlan)
        self.assertEqual("ollama-ornith", result.plan.primary.model.id)
        self.assertEqual(llm.effective_model_name_for_entry(result.plan.primary.model),
                         result.response.model)                    # primary 与响应同一个词
        self.assertEqual(RAG_LOCAL_MODEL, result.response.model)
        self.assertEqual(0, result.selected_index)
        self.assertEqual(0, result.context_dropped)
        self.assertEqual((), result.plan.fallbacks)            # 单条目注册表：没有备胎


# --------------------------------------------------------------------------
# 2. 温度等价门闸（T2 移交 I-4）：两条 provider 腿 × 双路，偏差被枚举而不是被忽略
# --------------------------------------------------------------------------
class RagTemperatureEquivalenceTests(_RagMigrationFixture):
    """同一次问答，legacy 报文 vs router 报文逐键对照。

    **已核实的构造性事实（裁定见 task-6-report）**：`normalize.ollama_payload` 恒发
    `options.temperature` 与 `tools: []`（现网 `agent.py` 的形状平移），而 legacy Ollama
    分支两个键都没有（吃 Ollama 服务端默认）。于是 Ollama 腿「与 legacy 报文逐字相等」
    **按构造不可能成立**——本组因此不伪造等价：温度钉**显式值**，报文钉**键集合差恰好是
    `{"options", "tools"}`**。OpenAI 腿是真等价（两侧都发顶层 `temperature`），钉逐字相等。
    """

    def run_router_leg(self, *, body: dict, registry: tuple, key: str) -> dict:
        self.use_registry(*registry)
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key=key)
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=body))
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        return dict(self.last.payload)

    def run_legacy_leg(self, *, body: dict, key: str) -> dict:
        self.use_settings(llm_router_enabled=False, openai_api_key=key)
        self.guard_router_off()
        self.legacy_serve(body)
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        return dict(self.legacy_payload)

    @property
    def legacy_payload(self) -> dict:
        self.assertTrue(self.legacy_calls, "legacy 腿应发出过一次 httpx.post")
        self.assertEqual(1, len(self.legacy_calls))
        return self.legacy_calls[-1].kwargs["json"]

    def test_openai_leg_temperature_is_byte_equal_to_the_legacy_payload(self):
        routed = self.run_router_leg(body=openai_body(ROUTER_ANSWER),
                                     registry=(cloud_entry(),), key="sk-rag-legacy-key")
        legacy = self.run_legacy_leg(body=openai_body(ROUTER_ANSWER),
                                     key="sk-rag-legacy-key")
        # ① 温度：逐字相等且等于常量（这一腿是**真等价**）。
        self.assertEqual(llm.RAG_LEGACY_TEMPERATURE, legacy["temperature"])
        self.assertEqual(llm.RAG_LEGACY_TEMPERATURE, routed["temperature"])
        self.assertEqual(legacy["temperature"], routed["temperature"])
        self.assertEqual(0.1, routed["temperature"])
        # ② 其余共同键逐字相等。
        self.assertEqual(legacy["model"], routed["model"])
        self.assertEqual(legacy["messages"], routed["messages"])
        self.assertEqual({"Authorization"}, set(self.legacy_calls[-1].kwargs["headers"]))
        self.assertEqual("Bearer sk-rag-legacy-key",
                         self.last.headers["authorization"])
        # ③ 偏差被**枚举**：router 只多一枚显式 `stream: False`（legacy 靠服务端默认）。
        self.assertEqual({"stream"}, set(routed) - set(legacy))
        self.assertEqual(set(), set(legacy) - set(routed))
        self.assertIs(False, routed["stream"])

    def test_ollama_leg_pins_the_explicit_temperature_and_enumerates_the_deviation(self):
        routed = self.run_router_leg(body=ollama_body(ROUTER_ANSWER),
                                     registry=(rag_entry(),), key="")
        legacy = self.run_legacy_leg(body=ollama_body(ROUTER_ANSWER), key="")
        # ① 显式温度：router 报文自己就得说 0.1（不看 legacy 有没有这个键）。
        self.assertEqual(llm.RAG_LEGACY_TEMPERATURE, routed["options"]["temperature"])
        self.assertEqual(0.1, routed["options"]["temperature"])
        # ② legacy 那条腿压根没有 options/tools 两键 ⇒ 它今天吃的是 Ollama 服务端默认。
        self.assertNotIn("options", legacy)
        self.assertNotIn("tools", legacy)
        # ③ 键集合差**恰好**两枚（多一枚少一枚都红：偏差必须有名有姓）。
        self.assertEqual({"options", "tools"}, set(routed) - set(legacy))
        self.assertEqual(set(), set(legacy) - set(routed))
        # ④ 其余三键逐字相等。
        self.assertEqual(legacy["model"], routed["model"])
        self.assertEqual(legacy["messages"], routed["messages"])
        self.assertEqual(legacy["stream"], routed["stream"])
        self.assertIs(False, legacy["stream"])
        # ⑤ 空 tools 也发键是现网 `agent.py` 的形状（normalize 模块 docstring 冻结），
        #    不是本任务新加的第三枚偏差。
        self.assertEqual([], routed["tools"])
        self.assertEqual({"temperature"}, set(routed["options"]))

    def test_flag_off_never_calls_the_router(self):
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.guard_router_off()
        self.legacy_serve(ollama_body("legacy 的答案 [1]"))
        self.assertEqual("legacy 的答案 [1]",
                         rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))
        self.assertEqual(1, len(self.legacy_calls))
        self.assertEqual([], self.requests)                  # MockTransport 一次没响

    def test_flag_on_never_calls_the_legacy_httpx_post(self):
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key="")
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=ollama_body("router 的答案 [1]")))
        self.assertEqual("router 的答案 [1]",
                         rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))
        self.assertEqual(1, len(self.requests))

    def test_both_paths_deliver_the_same_answer_for_the_same_body(self):
        """两条腿喂同一个响应体 ⇒ 对外文本逐字相同（响应面等价，配合上面的报文面等价）。"""
        body = ollama_body("差旅住宿上限每天陆佰元 [1]。")
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key="")
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=body))
        routed_answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        routed_payload = dict(self.last.payload)
        self.assertEqual(1, len(self.requests))

        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.guard_router_off()
        self.legacy_serve(body)
        legacy_answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertEqual("差旅住宿上限每天陆佰元 [1]。", routed_answer)
        self.assertEqual(routed_answer, legacy_answer)         # 对外文本等价
        self.assertEqual(self.legacy_payload["messages"], routed_payload["messages"])

    def test_legacy_endpoint_urls_and_timeout_are_unchanged(self):
        """legacy 那两条分支连 URL 与 timeout 都要原样（矩阵 #18：一个字节都不改）。"""
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.guard_router_off()
        self.legacy_serve(ollama_body("x"))
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertEqual(OLLAMA_CHAT_URL, self.legacy_calls[-1].url)
        self.assertEqual(120, self.legacy_calls[-1].kwargs["timeout"])
        self.assertNotIn("headers", self.legacy_calls[-1].kwargs)

        self.legacy_serve(openai_body("y"))
        self.use_settings(llm_router_enabled=False, openai_api_key="sk-rag-legacy-key")
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertEqual(OPENAI_CHAT_URL, self.legacy_calls[-1].url)
        self.assertEqual(120, self.legacy_calls[-1].kwargs["timeout"])


# --------------------------------------------------------------------------
# 3. 失败面（D2）：零候选 / 全链失败都落现文案，HTTP 面不炸
# --------------------------------------------------------------------------
class RagFailureFaceTests(_RagMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.guard_legacy_egress_off()

    def test_no_capable_model_returns_the_current_copy_without_raising(self):
        """真注册表面孔 + 所有 provider 不健康的 health_view ⇒ `NoCapableModelError`。"""
        self.use_registry(rag_entry(), rag_entry(id="ollama-phi3", model="phi3:mini",
                                                 priority={"chat": 80, "rag": 80,
                                                           "tools": 0}))
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("不该被读到")))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertTrue(answer.startswith(LLM_UNAVAILABLE_COPY), answer)
        self.assertIn("最相关原文：[1] 差旅住宿上限每天陆佰元。", answer)
        self.assertIn("模型连接错误：", answer)
        self.assertEqual([], self.requests)                  # 一条请求都没发出

    def test_the_failure_copy_names_the_exception_class_not_a_fixed_literal(self):
        """`模型连接错误：{type(exc).__name__}` 的**类名**是归因事实，不许换成字面量。"""
        self.use_registry(rag_entry())
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("x")))
        self.assertIn("模型连接错误：NoCapableModelError",
                      rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))

        self.use_registry(rag_entry())
        self.healthy_providers()
        self.serve(_response(500, json_body={"error": "failed to load model"}))
        self.assertIn("模型连接错误：AllCandidatesFailedError",
                      rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))

    def test_the_source_preview_and_web_tail_survive_the_failure(self):
        """兜底文案也要带联网来源尾块（legacy 就是这个形状：`_append_web_sources` 两侧共用）。"""
        self.use_registry(rag_entry())
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("x")))
        with mock.patch.object(rag_module, "search_web", return_value=list(WEB_ROWS)):
            answer = rag_module.generate_answer(WEB_QUESTION, ENTERPRISE_ROWS)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)
        self.assertTrue(answer.endswith("\n联网来源：\n- [2] 财政部通知 — "
                                        "https://example.gov/notice"), answer)

    def test_context_gate_wipeout_degrades_to_the_same_copy(self):
        """§5 的上下文收口（Task 4 前置）把候选剔空 ⇒ 同一句文案，不是 500。"""
        self.use_registry(rag_entry(limits={"context_tokens": 1, "max_output_tokens": 1}))
        self.healthy_providers()
        self.serve(_response(200, json_body=ollama_body("x")))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)
        self.assertIn("模型连接错误：NoCapableModelError", answer)

    def test_a_full_chain_failure_writes_one_row_with_a_provider_kind(self):
        """§8.1 第 2 条：`success=0` 的行**必须**带 `error_type` 的 kind，不许留空。"""
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.serve(_response(500, json_body={"error": "failed to load model"}))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertIn("模型连接错误：AllCandidatesFailedError", answer)
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)
        row = rows[0]
        self.assertEqual(0, row["success"])
        self.assertEqual("model_unavailable", row["error_type"])      # provider 的 kind
        self.assertTrue(row["error_type"], "失败账不许留空 error_type")
        self.assertEqual("rag", row["route_mode"])
        self.assertEqual(-1, row["fallback_index"])                   # 没选中任何候选
        self.assertEqual(500, row["status_code"])

    def test_the_zero_candidate_exit_writes_no_row_at_all(self):
        """D2 的零候选（`NoCapableModelError`）在任何外呼**之前** ⇒ 没有 attempt、没有行
        （与 Task 5 的裁定同源：把「路由没找到模型」算成模型失败会污染 `success_rate`）。
        本例同时钉住那条写账义务的**可执行部分**：链上绝不产出 `success=0` 而 `error_type`
        为空的行。

        **姿势**（评审 Minor 1）：第二枚断言扫的是一张**非空**表——先落一行合法的成功账，
        再跑零候选那一支。空表上的全表扫描恒真（`[] == []`），那枚断言就退化成「没有行」
        的同义反复；有了对照组，它才真的在说「有失败行时失败行必带 kind」。
        """
        # 对照组：一次真成功 = 一行 `success=1` 的合法账（表非空）。
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.assertEqual(ROUTER_ANSWER,
                         rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))
        control = self.raw_rows()
        self.assertEqual(1, len(control), control)
        self.assertEqual(1, control[0]["success"])
        # 零候选那一支：同一个临时库，行数必须**不动**。
        self.use_registry(rag_entry())
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("x")))
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), f"零候选不该新增行，实际：{rows}")
        self.assertEqual(1, rows[0]["success"], "库里那一行仍是对照组的成功账")
        self.assertEqual([], [row for row in rows
                              if not row["success"] and not (row["error_type"] or "")],
                         "非空表上才成立：链上没有一行 `success=0` 而 `error_type` 为空")

    def test_a_malformed_legacy_body_still_degrades_instead_of_raising(self):
        """legacy 腿 catch-all 的**宽度**就是现网行为：响应体缺 `message` 键今天冒
        `KeyError`，落的是同一句兜底文案。把 except 收窄成「只 catch Router 那一族」就会
        把这条链从降级变成 500 —— 那是行为变更，不是重构（矩阵 #18）。
        """
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.legacy_serve({"not_a_chat_response": True})
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)
        self.assertIn("模型连接错误：KeyError", answer)

    def test_a_legacy_connection_error_keeps_the_exception_class_name(self):
        """legacy 腿的连接失败：类名照旧是 httpx 的那个（迁移没有换掉运维读到的词）。"""
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.legacy_serve(None, exc=httpx.ConnectError("connection refused"))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertIn("模型连接错误：ConnectError", answer)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)

    def test_the_http_face_still_returns_200_when_no_candidate_is_capable(self):
        """D2「不得 500/503 给用户裸错」在 `/api/query` 上成立。

        顺手做掉评审 I-2 里那枚「同源但可容忍」：这条用例打的是**真 HTTP 面**，
        `record_event` 会把问题文本追加进 `data/audit.jsonl`（audit 记 query 是既有设计，
        D3 的「永不存储」约束的是 `llm_request_logs`，所以**不算违规**）。但测试自己那一笔
        没理由落在仓库的数据目录里 ⇒ 把 `AUDIT_PATH` 指到临时文件，与账本同一套隔离姿势。
        """
        from fastapi.testclient import TestClient
        from app.main import app as fastapi_app

        audit_dir = tempfile.TemporaryDirectory()
        self.addCleanup(audit_dir.cleanup)
        audit_patcher = mock.patch.object(audit_module, "AUDIT_PATH",
                                          Path(audit_dir.name) / "audit.jsonl")
        audit_patcher.start()
        self.addCleanup(audit_patcher.stop)

        self.use_registry(rag_entry())
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("x")))
        client = TestClient(fastapi_app)
        login = client.post("/api/auth/login",
                            json={"username": "admin", "password": "admin123"})
        self.assertEqual(200, login.status_code, login.text)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        rows = [{**ENTERPRISE_ROWS[0], "knowledge_base_id": "kb_public",
                 "knowledge_base_name": "公共制度", "vector_score": 0.9}]
        with mock.patch.object(main_module.retrieval_service, "search_with_timings",
                               return_value=(rows, {})):
            response = client.post("/api/query", headers=headers,
                                   json={"question": PLAIN_QUESTION, "k": 1})
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertIn(LLM_UNAVAILABLE_COPY, body["answer"])
        self.assertIn("模型连接错误：", body["answer"])
        self.assertEqual(RAG_LOCAL_MODEL, body["model_used"])


# --------------------------------------------------------------------------
# 3b. 模型面（终审 I-11-2 / DESIGN §9）：`/api/query` 的 `model_used` 报的是
#     **这次真答出那句话的模型**，不是计划面的 primary
# --------------------------------------------------------------------------
class RagModelFaceTests(_RagMigrationFixture):
    """§9 冻结句「响应 model 字段来自实际选中模型」的三张面孔：fallback / 零候选 / legacy。

    修前的病灶：`main.py` 的 `model_used` 无条件读 `current_model_name()`，而后者只跑
    `plan()` 取计划 primary（docstring 自陈「不进 fallback」）⇒ 任何发生 fallback 的请求，
    响应体与账本 `llm_request_logs.model` **必然劈叉**。修法是把执行面事实经可变盒子
    （`generate_answer(..., model_out=...)`）带出来，盒子为空才回退展示面读数。
    因此本组的钉子有两类：① HTTP 面上的字段值（对外契约），② 盒子本身写不写键
    （①靠 `or` 兜底看不见的空串/猜值，只能由②拦住）。
    """

    def setUp(self) -> None:
        super().setUp()
        # 真 HTTP 面会把问题文本追加进 `data/audit.jsonl`（audit 记 query 是既有设计）；
        # 测试自己那一笔没理由落在仓库数据目录里 ⇒ 与 `RagFailureFaceTests` 同一套隔离姿势。
        audit_dir = tempfile.TemporaryDirectory()
        self.addCleanup(audit_dir.cleanup)
        patcher = mock.patch.object(audit_module, "AUDIT_PATH",
                                    Path(audit_dir.name) / "audit.jsonl")
        patcher.start()
        self.addCleanup(patcher.stop)

    def authed_client(self):
        """真 HTTP 面的登录态（与 `RagFailureFaceTests` 同一个 admin 面孔）。"""
        from fastapi.testclient import TestClient

        from app.main import app as fastapi_app

        client = TestClient(fastapi_app)
        login = client.post("/api/auth/login",
                            json={"username": "admin", "password": "admin123"})
        self.assertEqual(200, login.status_code, login.text)
        return client, {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _search_leg_stubbed(self):
        rows = [{**ENTERPRISE_ROWS[0], "knowledge_base_id": "kb_public",
                 "knowledge_base_name": "公共制度", "vector_score": 0.9}]
        return mock.patch.object(main_module.retrieval_service, "search_with_timings",
                                 return_value=(rows, {}))

    def http_query_body(self, question: str = PLAIN_QUESTION) -> dict:
        """打真 `/api/query`：检索腿替身，**生成腿是真链**（provider 出口仍是 MockTransport）。"""
        client, headers = self.authed_client()
        with self._search_leg_stubbed():
            response = client.post("/api/query", headers=headers,
                                   json={"question": question, "k": 1})
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def http_stream_done_payload(self) -> dict:
        """打真 `/api/query/stream`，取回 `done` 事件那一段的 payload。"""
        client, headers = self.authed_client()
        with self._search_leg_stubbed():
            with client.stream("POST", "/api/query/stream", headers=headers,
                               json={"question": PLAIN_QUESTION, "k": 1}) as response:
                lines = list(response.iter_lines())
                # 流式响应没 `read()` 之前不许碰 `.text`（httpx 会 `ResponseNotRead`），
                # 所以失败信息用已经收下来的行。
                self.assertEqual(200, response.status_code, lines)
        done = [line for line in lines if line.startswith("data:") and "finish_reason" in line]
        self.assertEqual(1, len(done), f"`done` 事件必须恰好一枚：{lines}")
        return json.loads(done[0][len("data:"):].strip())

    def test_no_event_other_than_done_carries_the_model_key(self):
        """DESIGN §9.2 第 4 条「不扩散」：本版唯一的键集合变化就是 `done`。

        `sources` / `token` 事件的 payload 里出现 `model_used` 就是**第二处**响应面契约变更
        （前端与 SSE 词汇表按 additive-only 冻结），所以这里扫的是**全部** `data:` 行而不是
        只挑 `done` 那一行：除 `done` 之外任何一帧带这个键都算红。
        """
        self.use_two_rag_candidates()
        self.serve_primary_boom_then_phi3_ok()
        client, headers = self.authed_client()
        with self._search_leg_stubbed():
            with client.stream("POST", "/api/query/stream", headers=headers,
                               json={"question": PLAIN_QUESTION, "k": 1}) as response:
                lines = list(response.iter_lines())
                self.assertEqual(200, response.status_code, lines)
        frames = [json.loads(line[len("data:"):].strip())
                  for line in lines if line.startswith("data:")]
        self.assertGreaterEqual(len(frames), 3, f"至少要 sources + token* + done：{lines}")
        with_key = [index for index, frame in enumerate(frames)
                    if rag_module.MODEL_USED_KEY in frame]
        self.assertEqual([len(frames) - 1], with_key,
                         f"`model_used` 只许出现在最后一帧（done）：{frames}")
        self.assertEqual("stop", frames[-1]["finish_reason"])
        self.assertTrue(all(rag_module.MODEL_USED_KEY not in frame for frame in frames[:-1]))

    def use_two_rag_candidates(self) -> None:
        """primary=ornith（rag 档 100）+ fallback=phi3（rag 档 80）：两枚名字必须能分辨。"""
        self.use_registry(rag_entry(),
                          rag_entry(id="ollama-phi3", model="phi3:mini",
                                    priority={"chat": 80, "rag": 80, "tools": 0}))
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key="")
        self.guard_legacy_egress_off()

    def serve_primary_boom_then_phi3_ok(self) -> None:
        self.serve_sequence(_response(500, json_body={"error": "model not loaded"}),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER,
                                                                 model="phi3:mini")))

    # --- ① fallback：响应必须报第二候选 -------------------------------------
    def test_the_box_carries_the_model_that_actually_answered(self):
        """盒子层钉子：primary 真失败、第二候选真成功 ⇒ 盒子里是那**第二枚**名字。"""
        self.use_two_rag_candidates()
        self.serve_primary_boom_then_phi3_ok()
        box: dict[str, str] = {}
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS, model_out=box)
        self.assertEqual(ROUTER_ANSWER, answer)
        self.assertEqual({"model_used": "phi3:mini"}, box)
        self.assertNotIn(RAG_LOCAL_MODEL, box.values())     # 计划面 primary 不许进盒子
        self.assertEqual(2, len(self.requests))

    def test_the_http_face_reports_the_fallback_model_not_the_planned_primary(self):
        """对外契约（§9 冻结句）：发生 fallback 时 `model_used` == 账本 `model` 列。"""
        self.use_two_rag_candidates()
        self.serve_primary_boom_then_phi3_ok()
        body = self.http_query_body()
        self.assertEqual(ROUTER_ANSWER, body["answer"])
        self.assertEqual("phi3:mini", body["model_used"])
        self.assertNotEqual(RAG_LOCAL_MODEL, body["model_used"],
                            "报的是计划面 primary ⇒ I-11-2 的劈叉回来了")
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(1, rows[0]["success"], rows)
        self.assertEqual(rows[0]["model"], body["model_used"])
        self.assertEqual("phi3:mini", rows[0]["model"])
        self.assertEqual({"answer", "query", "sources", "num_sources", "model_used"},
                         set(body), "§9：既有响应键集合不许动")

    def test_a_non_fallback_answer_reports_the_same_name_as_before(self):
        """对照组：没发生 fallback 时盒子与计划面同名 ⇒ 这次修复不是把字段换成猜值。"""
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key="")
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        box: dict[str, str] = {}
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS, model_out=box)
        self.assertEqual({"model_used": RAG_LOCAL_MODEL}, box)
        self.assertEqual(box["model_used"], rag_module.current_model_name())

    # --- ② 零候选 / 全链失败：不写键，回退展示面，且**绝不出现空串** ----------
    def test_no_capable_model_writes_no_box_and_falls_back_to_the_plan_face(self):
        self.use_two_rag_candidates()
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("不该被读到")))
        box: dict[str, str] = {"model_used": "占位：调用方给盒子预置脏值必须被忽略"}
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS,
                                            model_out=box)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)
        self.assertIn("模型连接错误：NoCapableModelError", answer)
        self.assertEqual({"model_used": "占位：调用方给盒子预置脏值必须被忽略"}, box,
                         "零候选路上没有「实际答话的模型」这枚事实 ⇒ 一个键都不许多写")
        self.assertEqual([], self.requests)
        planned = rag_module.current_model_name()
        body = self.http_query_body()
        self.assertIn(LLM_UNAVAILABLE_COPY, body["answer"])
        self.assertEqual(planned, body["model_used"])
        self.assertEqual(RAG_LOCAL_MODEL, body["model_used"])
        self.assertTrue(str(body["model_used"]).strip(), "兜底位不许是空串")

    def test_every_candidate_failing_writes_no_box(self):
        """全链失败（`AllCandidatesFailedError`）同样不写键：失败腿没有资格报模型名。"""
        self.use_two_rag_candidates()
        self.serve(_response(500, json_body={"error": "boom"}))
        box: dict[str, str] = {}
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS, model_out=box)
        self.assertIn("模型连接错误：AllCandidatesFailedError", answer)
        self.assertEqual({}, box)
        self.assertEqual(2, len(self.requests))

    def test_a_provider_echoing_an_empty_model_writes_no_box(self):
        """回显空串 ⇒ 不写（宁缺毋空）：写进去就是让 `or` 去替调用方兜谎。"""
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=True, openai_api_key="")
        self.guard_legacy_egress_off()
        silent_echo = ollama_body(ROUTER_ANSWER)
        silent_echo.pop("model")                       # 一台不回填模型名的 provider
        self.serve(_response(200, json_body=silent_echo))
        box: dict[str, str] = {}
        # 生效名有两个来源：`normalize.parse_*` 先读**回显**、再退到本地 target
        # （`str(data.get("model") or model)`）。两头都给空 ⇒ 才是真正的空回显。
        with mock.patch.object(provider_module, "effective_model_name",
                               lambda model, creds: ""):
            answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS,
                                                model_out=box)
        self.assertEqual(ROUTER_ANSWER, answer)
        self.assertEqual({}, box)

    # --- ②b 流式腿（同一枚盒子的第二个调用点）：done 事件「有事实才挂键」 ----------
    def test_the_stream_leg_reports_the_answered_model_in_the_done_event(self):
        """`/api/query/stream` 也带盒子 ⇒ 发生 fallback 时 `done.model_used` 是第二候选。

        这一枚钉的是**本次新增**的那枚可选键（挂上去就必须有测试），不是既有契约：
        `done` 的其余键（`finish_reason` / `timings`）逐字不变。
        """
        self.use_two_rag_candidates()
        self.serve_primary_boom_then_phi3_ok()
        payload = self.http_stream_done_payload()
        self.assertEqual("phi3:mini", payload[rag_module.MODEL_USED_KEY])
        self.assertEqual("stop", payload["finish_reason"])
        self.assertEqual({"finish_reason", "model_used"}, set(payload))

    def test_the_stream_leg_adds_no_key_when_nothing_answered(self):
        """零候选 ⇒ `done` 回到迁移前的键集合（不写空串、不写计划面名字）。"""
        self.use_two_rag_candidates()
        self.healthy_providers(ollama=False)
        self.serve(_response(200, json_body=ollama_body("不该被读到")))
        payload = self.http_stream_done_payload()
        self.assertNotIn(rag_module.MODEL_USED_KEY, payload)
        self.assertEqual({"finish_reason"}, set(payload))

    # --- ③ legacy（矩阵 #18）：与迁移前**逐字一致** -------------------------
    def test_matrix_18_legacy_model_used_is_the_pre_migration_name_verbatim(self):
        """两张面孔**故意不同名**的对照：注册表 primary 是本地 ornith，legacy 判断只看云 key。

        只有「legacy 路不写盒子 + `model_used` 仍取 `_legacy_model_name()`」同时成立，
        下面的 `RAG_CLOUD_MODEL` 才会出现；legacy 分支里写死任何「实际名」都会红。
        """
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=False, openai_api_key="sk-rag-legacy-key")
        self.guard_router_off()
        self.legacy_serve(openai_body(ROUTER_ANSWER))
        box: dict[str, str] = {}
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS, model_out=box)
        self.assertEqual(ROUTER_ANSWER, answer)
        self.assertEqual({}, box, "legacy 路上盒子必须一个键都不写")
        body = self.http_query_body()
        self.assertEqual(RAG_CLOUD_MODEL, body["model_used"])
        self.assertEqual(self.settings.openai_model, body["model_used"])
        self.assertEqual(rag_module._legacy_model_name(), body["model_used"])
        self.assertNotEqual(RAG_LOCAL_MODEL, body["model_used"],
                            "legacy 的模型名不许被路由面的名字替换（矩阵 #18）")
        self.assertEqual([], self.raw_rows(), "legacy 不经路由 ⇒ 不该有路由账")

    def test_matrix_18_legacy_model_used_without_a_cloud_key_is_the_local_name(self):
        """另一支 legacy：无云 key ⇒ 迁移前后都是 `settings.ollama_model`，逐字不变。"""
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.guard_router_off()
        self.legacy_serve(ollama_body(ROUTER_ANSWER))
        box: dict[str, str] = {}
        rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS, model_out=box)
        self.assertEqual({}, box)
        body = self.http_query_body()
        self.assertEqual(self.settings.ollama_model, body["model_used"])
        self.assertEqual(RAG_LOCAL_MODEL, body["model_used"])
        self.assertEqual(ROUTER_ANSWER, body["answer"])
        self.assertEqual([], self.raw_rows())


# --------------------------------------------------------------------------
# 4. 记账面（§8.1 / D3）：一次成功一行 `route_mode="rag"`，禁存项零命中
# --------------------------------------------------------------------------
class RagLedgerTests(_RagMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.guard_legacy_egress_off()

    def test_one_success_row_with_route_mode_rag_and_no_prompt_bytes(self):
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertEqual(ROUTER_ANSWER, answer)
        self.assertEqual(1, len(self.requests))
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)
        row = rows[0]
        self.assertEqual(1, row["success"])
        self.assertEqual("rag", row["route_mode"])
        self.assertEqual("ollama", row["provider"])
        self.assertEqual(RAG_LOCAL_MODEL, row["model"])
        self.assertEqual(0, row["fallback_index"])
        self.assertEqual((11, 7, 18), (row["input_tokens"], row["output_tokens"],
                                       row["total_tokens"]))
        self.assertIsNone(row["error_type"])
        self.assertIsNone(row["trace_id"])                   # RAG 链刻意没有 trace_id
        self.assertIsNone(row["ttft_ms"])                    # 非流式没有 ttft
        self.assertIn("CAPABILITY_MATCH", json.loads(row["route_reason"]))
        # 禁存项（D3）：整行序列化后，中文问题 / 证据 / prompt 片段 0 命中。
        blob = json.dumps({k: str(v) for k, v in row.items()}, ensure_ascii=False)
        for canary in (RAG_PROMPT_CANARY, "差旅住宿上限每天陆佰元", "报销制度.md",
                       rag_module.SYSTEM_PROMPT[:24], "请依据以下证据回答问题"):
            self.assertNotIn(canary, blob)
        for forbidden in ("prompt", "messages", "context", "reasoning", "api_key",
                          "authorization"):
            self.assertNotIn(forbidden, set(row))

    def test_the_ledger_follows_the_candidate_that_actually_answered(self):
        """fallback 命中时 `model` 列与 `fallback_index` 都指向真被调的那一条。"""
        self.use_registry(rag_entry(), rag_entry(id="ollama-phi3", model="phi3:mini",
                                                 priority={"chat": 80, "rag": 80,
                                                           "tools": 0}))
        self.serve_sequence(
            _response(500, json_body={"error": "failed to load model"}),
            _response(200, json_body=ollama_body("备胎的答案 [1]", model="phi3:mini")))
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertEqual("备胎的答案 [1]", answer)
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)                 # 一次问答一行
        self.assertEqual(1, rows[0]["fallback_index"])
        self.assertEqual("phi3:mini", rows[0]["model"])
        self.assertEqual(1, rows[0]["success"])
        reason_codes = json.loads(rows[0]["route_reason"])
        self.assertIn("CAPABILITY_MATCH", reason_codes)
        self.assertIn("LOCAL_PREFERRED", reason_codes)
        self.assertEqual(len(set(reason_codes)), len(reason_codes))   # 落库前已去重


# --------------------------------------------------------------------------
# 5. 展示面 `current_model_name()`：经 router 解析，禁外呼、禁抛异常
# --------------------------------------------------------------------------
class RagDisplayedModelNameTests(_RagMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.fail_on_any_probe()
        self.serve(_response(200, json_body=ollama_body("展示面不该外呼")))

    def test_without_a_cloud_key_it_is_the_local_setting(self):
        """出厂注册表（真文件）+ 无 key ⇒ primary 必然是本地条目 = `settings.ollama_model`。"""
        self.use_settings(openai_api_key="")
        patcher = mock.patch.object(llm, "get_registry",
                                    lambda: load_registry(str(SHIPPED_REGISTRY)))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(self.settings.ollama_model, rag_module.current_model_name())
        self.assertEqual(RAG_LOCAL_MODEL, rag_module.current_model_name())
        self.assertEqual([], self.requests)

    def test_the_display_face_never_touches_the_network(self):
        """**三道闸**（评审 Minor 2 后补齐）：探针一被调用就炸（`setUp` 的
        `fail_on_any_probe`）+ MockTransport 一次不响（`self.requests == []`）+
        `httpx` 的三个出口 `get`/`post`/`Client` 全部上闸。

        前两枚挡的是「经本包的合法出口打网络」，第三枚挡的是「绕过本包自己搓一次请求」——
        没有它，「展示面零网络」只是读代码读出来的结论（评审者得自己加 socket 级实测才敢
        判 PASS）。与 T7 的展示面同形。
        """
        self.use_registry(rag_entry())

        def forbidden(*args, **kwargs):
            raise AssertionError("展示面 current_model_name() 不许出网")

        for name in ("get", "post", "Client"):
            patcher = mock.patch.object(rag_module.httpx, name, forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        for _ in range(3):
            self.assertEqual(RAG_LOCAL_MODEL, rag_module.current_model_name())
        self.assertEqual([], self.requests)

    def test_a_broken_registry_degrades_to_the_legacy_name_instead_of_raising(self):
        def broken() -> Registry:
            raise RegistryError("LLM 注册表文件不可用：boom")
        for module in (llm, usage_module):
            patcher = mock.patch.object(module, "get_registry", broken)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.use_settings(openai_api_key="", llm_router_enabled=True)
        self.assertEqual(self.settings.ollama_model, rag_module.current_model_name())
        self.use_settings(openai_api_key="sk-some-cloud-key")
        self.assertEqual(self.settings.openai_model, rag_module.current_model_name())

    def test_zero_candidates_degrade_instead_of_raising(self):
        """rag capability 全 false ⇒ `plan()` 在第 2 步就抛，展示面不能跟着抛。"""
        self.use_registry(rag_entry(capabilities={"chat": True, "rag": False,
                                                  "tools": False, "stream": False,
                                                  "reasoning": False}))
        self.assertEqual(self.settings.ollama_model, rag_module.current_model_name())

    def test_the_name_follows_the_registry_primary_not_the_ollama_setting(self):
        """反证：上面的等式**不是**因为两处都读同一个 setting —— 分叉时注册表说了算。"""
        self.use_settings(ollama_model="a-completely-different-local-model")
        self.use_registry(rag_entry())                       # model=RAG_LOCAL_MODEL
        self.assertEqual(RAG_LOCAL_MODEL, rag_module.current_model_name())
        self.assertNotEqual(self.settings.ollama_model, rag_module.current_model_name())

    def test_the_cloud_primary_is_reported_when_a_key_arrives(self):
        self.use_settings(openai_api_key="sk-rag-cloud")
        self.use_registry(cloud_entry(),
                          rag_entry(priority={"chat": 10, "rag": 10, "tools": 0}))
        self.assertEqual(RAG_CLOUD_MODEL, rag_module.current_model_name())

    def test_flag_off_keeps_the_legacy_resolution_byte_for_byte(self):
        self.use_settings(llm_router_enabled=False, openai_api_key="")
        self.assertEqual(self.settings.ollama_model, rag_module.current_model_name())
        self.use_settings(llm_router_enabled=False, openai_api_key="sk-rag-cloud")
        self.assertEqual(self.settings.openai_model, rag_module.current_model_name())
        self.assertEqual([], self.requests)

    def test_model_override_alias_reaches_the_display_face(self):
        """D1 的 `{PROVIDER}_MODEL_OVERRIDE` 在展示面上也生效（§9：名字=真被调的那个）。"""
        self.use_registry(rag_entry())
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL_OVERRIDE": "prod-alias-2026"}):
            self.assertEqual("prod-alias-2026", rag_module.current_model_name())


# --------------------------------------------------------------------------
# 6. T5 移交：执行面三对象带 `plan`（+ `context_dropped`），末位默认值不破既有构造
# --------------------------------------------------------------------------
class PlanCarrierTests(_FallbackFixture):
    """`run_complete` / `StreamSession.finish()` / `all_failed()` 三个填值点，
    外加「末位可加」的形状纪律（frozen dataclass 的末位默认值 ⇒ T4 的构造断言不破）。"""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(fallback_module, "routing_health_view",
                                    lambda *a, **k: {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fallback_result_carries_the_exact_plan_it_executed(self):
        plan = fb_plan(fb_def())
        self.stub_complete({"fb-a": fb_response(fb_def())})
        result = fallback_module.run_complete(plan, fb_request())
        self.assertIs(plan, result.plan)
        self.assertEqual("fb-a", result.plan.primary.model.id)

    def test_stream_summary_carries_the_plan(self):
        plan = fb_plan(fb_def())
        self.stub_stream({"fb-a": s_stream(fb_chunk("答"))})
        session = fallback_module.run_stream(plan, fb_request())
        self.drain(session)
        self.assertIs(plan, session.finish().plan)

    def test_aggregate_failure_carries_plan_and_context_dropped(self):
        """D2 降级路上最需要解释的那一条：`AllCandidatesFailedError` 也带执行面事实。"""
        plan = fb_plan(fb_def(id="fb-a"), fb_def(id="fb-b"))
        self.stub_complete({"fb-a": s_raises(fb_error("retryable", 500)),
                            "fb-b": s_raises(fb_error("retryable", 503))})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(plan, fb_request(), trace_id="t")
        error = caught.exception
        self.assertIs(plan, error.plan)
        self.assertEqual(0, error.context_dropped)           # 没剔过就是 0，而不是缺字段
        self.assertEqual(2, len(error.attempts))

    def test_the_context_drop_count_reaches_the_aggregate_error(self):
        """N4 那枚哑键：被上下文收口剔掉的那一条要能在异常里读到。"""
        small = fb_def(id="fb-small", limits={"context_tokens": 10,
                                              "max_output_tokens": 8})
        big = fb_def(id="fb-big", priority={"chat": 1, "rag": 1, "tools": 1})
        plan = fb_plan(small, big)
        self.stub_complete({"fb-big": s_raises(fb_error("retryable", 500))})
        with self.assertRaises(AllCandidatesFailedError) as caught:
            fallback_module.run_complete(plan, fb_request("x" * 4000))
        self.assertIs(plan, caught.exception.plan)
        self.assertEqual(1, caught.exception.context_dropped)

    def test_plan_defaults_to_none_for_legacy_constructions(self):
        """末位带默认值 ⇒ 不填 `plan` 的既有构造（T4/T5 那十二处）照旧成立。"""
        legacy_shape = FallbackResult(fb_response(fb_def()),
                                      (Attempt("fb-a", "ollama", "success"),),
                                      0, ("CAPABILITY_MATCH",), 30000.0)
        self.assertIsNone(legacy_shape.plan)
        self.assertEqual(0, legacy_shape.context_dropped)
        positional = StreamSummary("答", {}, 1.0, (), 0)
        self.assertIsNone(positional.plan)
        error = AllCandidatesFailedError((Attempt("fb-a", "ollama", "failed", "retryable"),))
        self.assertIsNone(error.plan)
        self.assertEqual(0, error.context_dropped)

    def test_the_new_fields_are_last_and_defaulted(self):
        """「末位 + 带默认值」是**不破坏既有位置参构造**的唯一姿势，钉成等式。"""
        import inspect
        for cls in (FallbackResult, StreamSummary):
            with self.subTest(cls=cls.__name__):
                declared = _dc_fields(cls)
                self.assertEqual("plan", declared[-1].name)
                self.assertIsNone(declared[-1].default)
                self.assertNotIn("plan", tuple(f.name for f in declared[:-1]))
        parameters = inspect.signature(AllCandidatesFailedError.__init__).parameters
        self.assertEqual(["plan", "context_dropped"], list(parameters)[-2:])
        self.assertIsNone(parameters["plan"].default)
        self.assertEqual(0, parameters["context_dropped"].default)

    def test_complete_passes_the_result_object_through_untouched(self):
        """包级 `complete()` 不改返回形状，因此 `plan` 是**透传**而不是重建。"""
        model = fb_def(id="fb-a")
        plan = fb_plan(model)
        self.stub_complete({"fb-a": fb_response(model)})
        with mock.patch.object(llm, "_plan", lambda profile: plan):
            result = llm.complete([{"role": "user", "content": "你好"}], mode="rag")
        self.assertIs(plan, result.plan)
        self.assertIsInstance(result, FallbackResult)


# --------------------------------------------------------------------------
# 6b. 矩阵 #17 的**「真调用」半段**（评审 I-1）：真执行面产出 × §8.1 唯一挂载点
#     ——归属口径见 `task-6-brief.md`「Task 5 评审移交项」第 3 条与 `progress.md:40`。
#     #17 的集成主语是**被测对象的集成**（真 `llm.complete()` 的输出接 `app.agent_trace`），
#     不是「给 `app/rag.py` 造一条 trace」：RAG 链今天没有 trace 对象（`save_trace` 的调用点
#     只有 `agent.py` 与 `conversation_agent.py`），所以这里拿 RAG 链**真实跑出来的**那份
#     `result` / `AllCandidatesFailedError` 去接挂载点，`rag.py` 与 `fallback.py` 一行不改。
# --------------------------------------------------------------------------
#: §8.1 第 4 条回写后的**九键**（顺序 = `usage.model_route_trace` 的产出顺序）。
MODEL_ROUTE_NINE_KEYS = ("mode", "requirements", "primary", "fallbacks",
                         "selected_reason_codes", "attempts", "stage",
                         "selected_index", "context_dropped")


class ModelRouteIntegrationTests(_RagMigrationFixture):
    """#17 的「真调用」半段：九键齐备 + 执行面事实同源 + 禁存项 0 命中 + 真 JSONL 往返。

    T5 的 `AgentTraceModelRouteSeamTests` 钉的是**纯函数与接缝本身**（自己造的 plan /
    result → 九键 → 内存往返），它替不了本例：本例的输入是**真链**跑出来的——真
    `classify → plan → run_complete → provider(MockTransport)`，异常那一支也是真聚合的。
    """

    def setUp(self) -> None:
        super().setUp()
        self.use_registry(rag_entry())
        self.healthy_providers()
        self.guard_legacy_egress_off()

    def spy_the_real_chain(self) -> dict:
        """把包级入口看到的 `(outcome, profile)` 抓回来。

        `profile` 由 `llm.classify` 的 spy 抓 ⇒ 它是**这条链真正用过的那份画像**，不是测试
        另造一份（否则 #17 的 requirements 半段就又是自比自）。`outcome` 成功时是
        `FallbackResult`，失败时是异常对象本身（rag 的兜底文案在 spy 之外，不影响抓取）。
        """
        captured: dict = {}
        real_complete = llm.complete
        real_classify = llm.classify

        def classify_spy(*args, **kwargs):
            profile = real_classify(*args, **kwargs)
            captured["profile"] = profile
            return profile

        def complete_spy(*args, **kwargs):
            try:
                outcome = real_complete(*args, **kwargs)
            except BaseException as exc:                       # noqa: BLE001 - 看完再原样上抛
                captured["outcome"] = exc
                raise
            captured["outcome"] = outcome
            return outcome

        for name, replacement in (("classify", classify_spy), ("complete", complete_spy)):
            patcher = mock.patch.object(llm, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        return captured

    def assert_no_private_bytes(self, trace: dict) -> None:
        """D3/§8 的禁存项：整份 trace 序列化后中文问题 / 证据正文 / prompt 片段 0 命中。

        值面用 canary 扫；键面靠上面那几枚**键集合等式**（九键 + `_candidate_view` /
        `_attempt_view` / `requirements` 的键集）封口——`model_route` 里没有能装下
        prompt 的落点。这里不再扫「有没有叫 prompt/messages 的**子串**」：`requirements`
        里合法地有一枚 `needs_reasoning`，子串扫会把合规形状读成违规。
        """
        blob = json.dumps(trace, ensure_ascii=False)
        for canary in (RAG_PROMPT_CANARY, "差旅住宿上限每天陆佰元", "报销制度.md",
                       rag_module.SYSTEM_PROMPT[:24], "请依据以下证据回答问题"):
            self.assertNotIn(canary, blob, f"trace 里出现了禁存项：{canary[:12]}…")

    def test_a_real_llm_complete_lands_a_nine_key_model_route(self):
        """成功路：真 `llm.complete()` 的 `result.plan` → 落盘 trace 的九键对象。"""
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        captured = self.spy_the_real_chain()
        self.assertEqual(ROUTER_ANSWER,
                         rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS))
        result = captured["outcome"]
        profile = captured["profile"]
        self.assertIsInstance(result, FallbackResult)
        self.assertIsInstance(result.plan, RoutePlan)
        self.assertEqual("rag", profile.mode)                  # 真画像，不是测试造的

        trace = {"trace_id": "t6-integration", "events": []}
        agent_trace_module.attach_model_route(trace, result.plan, result, profile=profile)

        # ① 九键**集合**等式：多一枚、少一枚都红（§8.1 第 4 条回写后的清单）。
        self.assertIn(MODEL_ROUTE_KEY, trace, "唯一挂载点没挂上 ⇒ #17 的交付物不存在")
        route = trace[MODEL_ROUTE_KEY]
        self.assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route))
        self.assertEqual(9, len(route))
        self.assertEqual({"trace_id", "events", MODEL_ROUTE_KEY}, set(trace))   # additive
        # ② 执行面事实：attempts 非空 + primary 与响应模型名同源（M2）。
        self.assertEqual("rag", route["mode"])
        self.assertTrue(route["attempts"], "attempts 非空：这是一条真跑过一次的链")
        self.assertEqual(result.response.model, route["primary"]["model"])
        self.assertEqual(RAG_LOCAL_MODEL, route["primary"]["model"])
        self.assertEqual(result.response.model, route["attempts"][0]["model"])
        self.assertEqual("success", route["attempts"][0]["result"])
        self.assertIsNone(route["attempts"][0]["error_type"])
        self.assertEqual("primary", route["stage"])
        self.assertEqual(result.selected_index, route["selected_index"])
        self.assertEqual(0, route["context_dropped"])
        self.assertIn("CAPABILITY_MATCH", route["selected_reason_codes"])
        self.assertEqual({"complexity", "needs_tools", "needs_stream", "needs_reasoning"},
                         set(route["requirements"]))
        self.assertEqual({"id", "provider", "model", "score", "reason_codes"},
                         set(route["primary"]))
        # ③ 禁存项（D3）：整份 trace 序列化后 0 命中。
        self.assert_no_private_bytes(trace)
        # ④ **真写 JSONL 再读回**：内存对象不算交付（矩阵 #17 的方法列 = 集成）。
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent_traces.jsonl"
            with mock.patch.object(agent_trace_module, "TRACE_PATH", path):
                agent_trace_module.save_trace(trace)
                line = path.read_text(encoding="utf-8")
                self.assertEqual(1, len(line.splitlines()))
                self.assertEqual(route, json.loads(line)[MODEL_ROUTE_KEY])
                self.assert_no_private_bytes(json.loads(line))
                self.assertEqual(json.loads(line),
                                 agent_trace_module.get_trace("t6-integration"))

    def test_the_aggregate_failure_branch_lands_stage_none_with_the_drop_count(self):
        """降级路那一支必须解释得动（§8.1 第 4 条点名）：`exc.plan` + `exc.context_dropped`
        ⇒ `stage="none"`、`selected_index=-1`、`context_dropped` = **真被上下文收口剔掉的
        条数**（不是缺省 0）。T6 刚给 `AllCandidatesFailedError` 加上这两枚字段，本例是
        它的第一枚端到端钉：`context_dropped` 断言取的是 `1`，所以「不填」立刻红。
        """
        self.use_registry(rag_entry(limits={"context_tokens": 10, "max_output_tokens": 8}),
                          rag_entry(id="ollama-phi3", model="phi3:mini",
                                    priority={"chat": 80, "rag": 80, "tools": 0}))
        self.serve(_response(500, json_body={"error": "failed to load model"}))
        captured = self.spy_the_real_chain()
        answer = rag_module.generate_answer(PLAIN_QUESTION, ENTERPRISE_ROWS)
        self.assertIn(LLM_UNAVAILABLE_COPY, answer)             # D2：用户侧仍是现文案
        error = captured["outcome"]
        profile = captured["profile"]
        self.assertIsInstance(error, AllCandidatesFailedError)
        self.assertIsInstance(error.plan, RoutePlan)
        self.assertEqual(1, error.context_dropped, error.context_dropped)

        trace = {"trace_id": "t6-integration-none", "events": []}
        agent_trace_module.attach_model_route(trace, error.plan, error, profile=profile)
        route = trace[MODEL_ROUTE_KEY]
        self.assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route))
        self.assertEqual("none", route["stage"])
        self.assertEqual(-1, route["selected_index"])
        self.assertEqual(error.context_dropped, route["context_dropped"])
        self.assertEqual(1, route["context_dropped"])           # ← 变异「不填」在此红
        self.assertEqual(1, len(route["attempts"]), "被剔的那条没外呼 ⇒ 只有 1 次 attempt")
        self.assertEqual("failed", route["attempts"][0]["result"])
        self.assertEqual("model_unavailable", route["attempts"][0]["error_type"])
        self.assertEqual("phi3:mini", route["attempts"][0]["model"])
        self.assertEqual(error.plan.primary.model.id, route["primary"]["id"])
        self.assert_no_private_bytes(trace)
        # 同一份事实也在**真账本**里留了痕（trace 与账本对得上：M2 同源的另一侧）。
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(0, rows[0]["success"])
        self.assertEqual("model_unavailable", rows[0]["error_type"])
        self.assertEqual(route["attempts"][0]["model"], rows[0]["model"])


# --------------------------------------------------------------------------
# 6c. 防回潮钉：测试写真实账本 = §8 全部聚合的数据源被写脏（评审 I-2）
# --------------------------------------------------------------------------
class LedgerIsolationGuardTests(unittest.TestCase):
    """四枚等式，全部关于「测试不许**写**保护集底下的真库」（T7 步骤 0 修 N1/N3）：

    1. 护栏在场，且**生效路径**不在保护集底下（护栏改道后必然成立）；
    2. 本会话至今零次 **write** 改道 = 没有任何用例试图往真账本写行（新测试忘关 sink ⇒
       这枚红，并且肇事那一例自己也会红，见
       `conftest.fail_the_offending_test_on_repo_ledger_write`）；
    3. **两份**真库（`backend/data` 与仓库根 `data`）的 `llm_request_logs` 仍是 0 行
       （N3：仓库根那份历史库以前根本不在保护集）；
    4. **读**改道不判红（N1 的正向半段）：本会话若留下任何 read 笔，它必须带着
       `kind="read"` 而不是混进第 2 枚的等式里。

    口径变化（原来挡什么 → 现在挡什么）写在 T7 报告的「被改动的既有断言逐条清单」里：
    第 2 枚从「本会话零改道（读也算）」收窄成「零**写**改道」，同时补第 3、4 两枚
    （多库点数 + 读只出 warning），整体是**加**了一道而不是减。
    """

    def test_the_effective_ledger_path_is_not_a_protected_database(self):
        self.assertTrue(ledger_guard.guard_is_active(),
                        "护栏 fixture 没跑起来 ⇒ 这三枚钉本身就是空的")
        effective = ledger_guard.effective_ledger_path().resolve()
        self.assertFalse(ledger_guard.path_is_protected(effective),
                         f"生效路径仍指向保护集里的数据目录：{effective}")
        self.assertNotEqual(ledger_guard.REAL_DB_PATH.resolve(), effective,
                            "账本的生效路径就是那份真库 ⇒ 护栏没兜住")

    def test_no_test_in_this_session_wrote_the_real_ledger(self):
        self.assertEqual([], list(ledger_guard.write_redirects()),
                         "有用例的 usage **写**账落到了保护集下的真实库 ⇒ 见 conftest 的"
                         " I-2/N1 说明")

    def test_every_recorded_redirect_carries_a_kind_and_reads_never_pin_red(self):
        """N1：`_REDIRECTS` 的每一笔都必须带归类；读笔在场时 `write_redirects()` 仍为空。

        这一枚刻意写成「遍历 + 条件」而不是 `assertEqual([], ledger_redirects())`：
        旧等式把读也当事故，正是 N1 的病灶。归类缺失 / 拼错 ⇒ 这里红。
        """
        records = list(ledger_guard.ledger_redirects())
        for source, target, kind in records:
            self.assertIn(kind, (ledger_guard.REDIRECT_READ, ledger_guard.REDIRECT_WRITE),
                          f"改道笔没带合法归类：{kind!r}（{source}）")
            self.assertTrue(target, "每一笔都要记下改道到了哪儿")
        self.assertEqual([], [r for r in records if r[2] == ledger_guard.REDIRECT_WRITE])

    def test_the_protected_ledger_tables_are_still_empty(self):
        counts = ledger_guard.real_ledger_row_counts()
        self.assertIn(str(ledger_guard.REAL_DB_PATH), counts,
                      "保护集哨兵没数 `backend/data` 那份真库 ⇒ N3 的漏网形状")
        root_db = ledger_guard.REPO_ROOT_DATA_DIR / "conversations.db"
        self.assertIn(str(root_db), counts,
                      "仓库根那份历史库不在保护集 ⇒ N3 未修（护栏只认 backend/data）")
        for path, rows in counts.items():
            self.assertIn(rows, (0, None),
                          f"真实库被测试写了 {rows} 行账（评审 I-2）：`llm_request_logs`"
                          f" 必须是 0（{path}）")


class LedgerGuardClassificationTests(unittest.TestCase):
    """步骤 0（N1）的**变异可杀**钉：读写归类由**真的** `usage._query` / `usage._log_usage`
    驱动，而不是由测试自证。

    做法：另开一个 `LedgerGuard` 实例（保护集指向临时目录里的一份「假真库」），把三道闸
    （`database_path` / `_execute` / `_connect`）临时挂到 `app.llm.usage` 上 ⇒ 会话级护栏
    不参与、也不被污染，而 `_query` / `_execute` / `_connect`
    是产品代码里那三个真函数（`_connect(None)` 会去调被拦的 `database_path()`）。

    两枚方向相反的钉子：
    * 纯读（`_query` / `aggregate_status` 的那条路）⇒ 只留 `read` 笔、`violations()` 为空
      ⇒ 恢复旧行为（把读也记成 write）立刻红；
    * 真写（`log_usage` 走 `_execute`）⇒ `violations()` 恰有一笔 ⇒ 把归类做成恒 read
      （另一种失效）也立刻红。
    """

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.protected_dir = root / "data"                      # 模拟「保护集里的真库」
        self.protected_dir.mkdir()
        self.protected_db = self.protected_dir / "conversations.db"
        self.temp_db = root / "isolated" / "conversations.db"   # 护栏的改道目标
        self.temp_db.parent.mkdir()
        usage_module.init_usage_db(self.temp_db)                # 表建在临时库
        usage_module.reset_usage_state()                        # 不把路径覆盖留给下一例
        self.addCleanup(usage_module.reset_usage_state)

    def install_guard(self) -> ledger_guard.LedgerGuard:
        guard = ledger_guard.LedgerGuard(
            original_path=lambda: self.protected_db,
            target=self.temp_db,
            protected_dirs=(self.protected_dir,))
        guard.install(usage_module)
        self.addCleanup(guard.uninstall)
        return guard

    def test_a_pure_read_is_classified_read_and_never_pins_red(self):
        guard = self.install_guard()
        rows = usage_module._query(
            f"SELECT COUNT(*) AS n FROM {usage_module.TABLE_NAME}", (), ("n",))
        self.assertEqual([{"n": 0}], rows)                      # 读的确实是临时库
        self.assertEqual([(str(self.protected_db), str(self.temp_db),
                           ledger_guard.REDIRECT_READ)], list(guard.records))
        self.assertEqual((), guard.violations(),
                         "纯读被归类成写 ⇒ 状态页/聚合类用例会被成批误诊（N1 的病灶）")
        self.assertFalse(self.protected_db.exists(),
                         "读改道之后那份「假真库」仍不该多一个字节")

    def test_a_real_write_is_classified_write_and_would_pin_red(self):
        guard = self.install_guard()
        usage_module.log_usage(UsageRecord(trace_id="t7-guard", route_mode="rag",
                                          provider="ollama", model="m", latency_ms=1.0))
        kinds = [kind for _src, _dst, kind in guard.records]
        self.assertIn(ledger_guard.REDIRECT_WRITE, kinds,
                      "写路径（`_execute`）解析到保护集路径时必须记成 write")
        self.assertEqual(1, len(guard.violations()), guard.violations())
        # 行落在临时库而不是保护集里的那份库：改道是**真改道**，不是只改记账。
        import sqlite3
        connection = sqlite3.connect(self.temp_db)
        try:
            self.assertEqual(1, int(connection.execute(
                f"SELECT COUNT(*) FROM {usage_module.TABLE_NAME}").fetchone()[0]))
        finally:
            connection.close()

    def test_a_direct_schema_connect_is_classified_write_too(self):
        """Task 7 评审 Minor-1：直连 `usage._connect()`（默认 `ensure_schema=True`）也算**写**。

        这是 N1 那道「按 `_execute` 调用栈判 write」的窄口径回退：`_connect` 里的
        `connection.executescript(_SCHEMA)` 会真的落在解析到的路径上，旧口径把它记成 read
        ⇒ 不判红（旧旧护栏反而判红）。今天 `usage.py` 里没有这种直连点，所以钉的是**以后**。
        两枚方向相反的事实一起钉：默认 `_connect(None)` ⇒ write；`ensure_schema=False`
        （`_query` 走的那条）⇒ 仍 read ⇒ 把这道闸糊成「恒 write」同样会红。
        """
        guard = self.install_guard()
        connection = usage_module._connect(None)                # 不经 `_execute` 的直连
        connection.close()
        self.assertEqual([(str(self.protected_db), str(self.temp_db),
                           ledger_guard.REDIRECT_WRITE)], list(guard.records),
                         "直连建表的 `_connect` 没被记成 write ⇒ Minor-1 的缝还在")
        self.assertEqual(1, len(guard.violations()), guard.violations())
        usage_module._connect(None, ensure_schema=False).close()
        self.assertEqual([ledger_guard.REDIRECT_WRITE, ledger_guard.REDIRECT_READ],
                         [kind for _src, _dst, kind in guard.records],
                         "`ensure_schema=False`（读路径）也被判成写 ⇒ N1 的病灶复发")
        self.assertFalse(self.protected_db.exists(),
                         "改道是真的改道：那份「假真库」仍不该多一个字节")

    def test_the_relative_default_resolves_into_the_protected_set_from_any_cwd(self):
        """N3：默认值是**相对** `data/conversations.db` ⇒ 三候选都要撞上保护集。

        旧护栏只认 `backend/data`，所以从非 `backend/` 目录跑时整层失效（实测 10 passed
        全绿而真库恒 0 行）。这里不换 cwd（那会影响同会话的其它用例），改钉判定函数本身：
        相对路径的候选集必须同时包含 `<cwd>/path`、`BACKEND_DIR/path`、
        `BACKEND_DIR.parent/path` 三个解，且后两个正是两份历史库。
        """
        relative = Path("data/conversations.db")
        candidates = set(ledger_guard.path_candidates(relative))
        self.assertIn(ledger_guard.REAL_DB_PATH.resolve(), candidates)
        self.assertIn((ledger_guard.REPO_ROOT_DATA_DIR / "conversations.db").resolve(),
                      candidates)
        self.assertIn((Path.cwd() / relative).resolve(), candidates)
        self.assertTrue(ledger_guard.path_is_protected(relative),
                        "相对默认路径不在保护集 ⇒ 从别的目录跑套件时护栏整层失效")
        self.assertTrue(ledger_guard.path_is_protected("data/conversations.db"))
        # 反面：临时目录里的库不是保护对象（否则每条隔离良好的用例都会被记一笔）。
        self.assertFalse(ledger_guard.path_is_protected(self.temp_db))


# --------------------------------------------------------------------------
# 7. D6 豁免清单的事实源：迁移后 `app/rag.py` 还剩几处出口（Task 9 按这个数字放行）
# --------------------------------------------------------------------------
class RagLegacyEgressInventoryTests(unittest.TestCase):
    """命中数只允许两种变化：legacy 被删（那时尚全零）或**有人新开了第二条出口**（必须红）。

    所以这里钉的是**等式**而不是「不超过」——`<=` 会让「顺手再加一处 httpx 直连」静默通过，
    而那正是 D6 要拦的形状。删 legacy 的那一次（DESIGN §1：下一稳定版）连同本用例一起改。
    """

    RAG_SOURCE = (BACKEND_DIR / "app" / "rag.py").read_text(encoding="utf-8")

    def test_legacy_egress_hits_are_exactly_the_documented_inventory(self):
        code = "\n".join(line for line in self.RAG_SOURCE.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertEqual(3, code.count("httpx"),                     # 1 import + 2 post
                         "rag.py 的 httpx 代码命中必须仍是 3 处（Task 9 豁免清单口径）")
        self.assertEqual(1, code.count("import httpx"))
        self.assertEqual(2, code.count("httpx.post("))
        self.assertEqual(1, code.count('"/api/chat"'))
        self.assertEqual(1, code.count('"/chat/completions"'))
        # 展示面不许多出第三条出口：`current_model_name` 只读注册表与计划。
        self.assertEqual(0, code.count("httpx.get"))
        self.assertEqual(0, code.count("httpx.Client"))


# ==========================================================================
# Task 7：SSE 对话链迁移（DESIGN §9 第二条）+ `app/native_stream.py` 退役
#         + 矩阵 #9（SSE 序完整）/ #10（pre-commit 静默换模型）/ #11（post-commit 不换）
#         / #17（真调用 + 真落盘九键）/ #18（legacy 双路）
#
# 四条纪律（沿用 T6，再加两枚本任务特有的）：
# 1. **真链到底**：router 腿走真 `llm.stream / llm.complete → classify → plan → run_* →
#    provider` + `httpx.MockTransport`；桩只打在 provider **下方**（`_transport`）与业务
#    **外围**（工具执行 / 审计 / trace 落盘）。把 `provider.stream` 换成 stub 就等于把
#    「NDJSON 行解析真的产出了这些 chunk」换成「我说它产出了」——那测不到 commit 边界。
# 2. **零真实外呼**：本机 Ollama 正加载 phi3:mini，打 11434 一次就是硬违规；真实双模型
#    failover 归 Task 10。这里每一条 `self.requests` 都是 MockTransport 拦下来的。
# 3. **`native_stream` 是响应字段，不是模块名**：退役的是 `app/native_stream.py`，留下的是
#    `timings["native_stream"]` / `events[].native_stream`（`security.py` 白名单 + 前端消费）。
#    这条区分做成断言（`SseNativeStreamFieldFaceTests`），并钉「取值集合 = {True, False}」。
# 4. **对外形状逐项相等**：`timings` 的键集合、SSE 的事件词汇表（D5：只加 payload 字段，
#    不新增事件类型）都按**等式**钉，不按「包含」钉。
# 5. **账本义务**（§8.1 第 2 条）：流式这条腿的账由调用点在 `session.finish()` 之后交给
#    `log_stream_usage`——那里才有 ttft / commit / usage 事实；两枚哨兵由账本产出，链上只写
#    provider 的 `kind`。
# ==========================================================================

SSE_PARTS = ["差旅住宿上限", "每天陆佰元 [1]。"]
SSE_ANSWER = "".join(SSE_PARTS)
#: `redact_text` 认的两个形态之一（Bearer）。埋在**中间那个 chunk** 里：只有「逐 chunk、
#: 且在 `token_sink` 之前」才拦得住它（挪到 commit / 收尾之后，客户端早已收到原文）。
SSE_SECRET_CHUNK = "补充 Bearer leaked-token-abc123 请以制度为准"
#: 让 `public_typesafe_metrics()` 非空 ⇒ `timings["ttft_ms"]` 这一枚才会出现（既有口径）。
SSE_TYPESAFE_TIMINGS = {"typesafe_request_count": 2, "typesafe_degraded": False}
#: 评审 I-2 的**注入量**：让检索段真实推进这么久（`_StubToolRegistry.execute` 里睡）。
#: `timings["ttft_ms"]` 的零点 = 整次请求的 `started`（**含**这一段），账本 `ttft_ms` 的零点 =
#: `StreamSession._pump` 的 `_session_started`（**不含**）⇒ 两枚之差至少是这一段。把差做成
#: 事实而不是注释，「换零点」才有例红（变异 `M5a_ttft_zero_point_swapped`）。
SSE_RETRIEVAL_SLEEP_MS = 40.0
#: 配套量：每枚 chunk 交付后真实睡这么久 ⇒ `llm_ms`（零点=`llm_started`，覆盖整个消费循环）
#: 稳稳大于被抬高了的 `timings["ttft_ms"]`，既有那枚 `ttft <= llm_ms` 上界才不会因为注入量而
#: 假红。两枚 chunk ⇒ 余量约 7 倍；这枚常量不参与任何断言，只负责把「检索段」与「LLM 段」
#: 拉开到可分辨的距离。
SSE_GENERATION_SLEEP_MS = 150.0
#: 两枚轴比较的容差：`timings` 侧 `round(…, 2)`、账本侧 `round(…, 3)`，理论差值恒 >= 注入量，
#: 这里只留给取整与调度留量（不是「差不多就行」的松弛项：方向是下界，睡不够只会更红不会更绿）。
TTFT_AXIS_EPSILON_MS = 2.0
#: 对话链**两条腿**在迁移前的现网采样温度 = **0.2**。测试侧**独立写死**、不 import 产品常量，
#: 这样「产品常量被改」与「报文被改」会分别红。出处逐腿核过：非流式腿 =
#: `agent._ollama_chat(messages, [])`（`baseline-app/conversation_agent.py:297-299` 调它，
#: `app/agent.py` 的 `options` 现值 0.2），流式腿 = 被退役的 `app/native_stream.py:27-28`
#: （硬编码 0.2）。⇒ 本链历史上两条腿都是 0.2；`RAG_LEGACY_TEMPERATURE`（0.1）属于
#: `app/rag.py` 那条链，本链**不吃它**（下面有反证）。
CONVERSATION_LEGACY_TEMPERATURE_ON_THE_WIRE = 0.2
#: 迁移前后 `_local_fast_path` 返回的 `timings` **键集合**（逐项相等，不是「包含」）。
SSE_TIMING_KEYS = frozenset({
    "retrieval_ms", "vector_ms", "bm25_ms", "fusion_ms", "rerank_ms",
    "retrieval_total_ms", "bm25_cache_hit", "parallel_hybrid", "fusion",
    "vector_candidates", "bm25_candidates", "llm_ms", "total_ms", "llm_calls",
    "tool_calls", "fast_path", "native_stream",
})


def sse_stream_body(*parts: str, model: str = RAG_LOCAL_MODEL, terminate: bool = True,
                    error_after: str | None = None,
                    usage: tuple[int, int] = (11, 7)) -> bytes:
    """Ollama 的 NDJSON 流式响应体（一条 part 一行，末尾 `done: true` 带 eval_count）。

    `terminate=False` = **提前断流**（没有 `done: true`）：`normalize` 会在已经吐出内容
    之后抛 `retryable` ⇒ 正好落在 commit 之后（矩阵 #11 的形状）。
    `error_after` = 内容之后再塞一帧 `{"error": ...}`：provider 的真实归类（例如
    `failed to load` ⇒ `model_unavailable`）必须活过 commit（§8.1 第 2 条）。
    """
    rows: list[dict] = [
        {"model": model, "message": {"role": "assistant", "content": part}, "done": False}
        for part in parts
    ]
    if error_after is not None:
        rows.append({"error": error_after})
    elif terminate:
        rows.append({"model": model, "message": {"role": "assistant", "content": ""},
                     "done": True, "done_reason": "stop",
                     "prompt_eval_count": usage[0], "eval_count": usage[1]})
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")


def sse_frames(blob: str) -> list[tuple[str, dict]]:
    """把 SSE 文本拆成 `(事件名, payload)` 序列（与前端 `consumeFrame` 同一形状）。"""
    frames: list[tuple[str, dict]] = []
    for block in blob.split("\n\n"):
        lines = [line for line in block.split("\n") if line]
        event = next((l[len("event:"):].strip() for l in lines if l.startswith("event:")), None)
        data = next((l[len("data:"):] for l in lines if l.startswith("data:")), None)
        if event is not None and data is not None:
            frames.append((event, json.loads(data)))
    return frames


class _StubToolRegistry:
    """`enterprise_search` 的替身：本任务测**生成腿**，检索面有自己的契约组。

    `sleep_ms` 是**真实**推进量（评审 I-2 的 ttft 两枚轴要靠它变成可比较的事实）：
    `_local_fast_path` 的 `retrieval_ms` 就是圈着 `tool_registry.execute` 测的，所以在这里
    睡多久，`timings["ttft_ms"]`（零点=`started`）就比账本那枚（零点=会话开始）多出多久。
    """

    def __init__(self, *, status: str = "SUCCESS", evidence: list[dict] | None = None,
                 timings: dict | None = None, sleep_ms: float = 0.0) -> None:
        self.status = status
        self.evidence = ([dict(row) for row in ENTERPRISE_ROWS]
                         if evidence is None else [dict(row) for row in evidence])
        self.timings = dict(timings or {})
        self.sleep_ms = float(sleep_ms)
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, arguments: dict, context) -> dict:
        self.calls.append((name, dict(arguments)))
        if self.status != "SUCCESS":
            from app.tools.base import ToolExecutionError
            raise ToolExecutionError("stub 检索失败", status=self.status)
        if self.sleep_ms:
            time.sleep(self.sleep_ms / 1000.0)                   # 单调钟下的真实一段
        return {"ok": True, "tool": name, "evidence": [dict(r) for r in self.evidence],
                "timings": dict(self.timings)}


class _StubConversationStore:
    """SSE 路由那三个 `replace_message` 出口的替身（本组不测会话面持久化）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def replace_message(self, **kwargs) -> dict:
        self.calls.append(dict(kwargs))
        return {"id": kwargs.get("message_id"), "content": kwargs.get("content"),
                "status": kwargs.get("status"), "trace_id": kwargs.get("trace_id"),
                "sources": list(kwargs.get("sources") or [])}


class _SseMigrationFixture(_RagMigrationFixture):
    """SSE 底座：T6 的两条腿闸门 + 真 trace/审计落盘改道 + 业务外围替身。

    刻意**不**打桩的东西：`llm.stream` / `llm.complete` / `classify` / `plan` /
    `run_stream` / `provider` / `normalize` / `usage`——#9/#10/#11/#17 四行的被测对象
    就是这条链本身。
    """

    SSE_SETTINGS_DEFAULTS: dict = {"agent_local_fast_path": True,
                                   "agent_think_synthesis": False,
                                   "agent_num_predict_synthesis": 512,
                                   "agent_history_max_messages": 8}

    def setUp(self) -> None:
        super().setUp()
        self.use_registry(rag_entry())
        self.healthy_providers()

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        # **测试隔离**（任务书硬约束）：trace 与审计两条文件出口都改道到临时目录，
        # 一行都不进 `backend/data/`（`agent_traces.jsonl` / `audit.jsonl` 是真实观测面）。
        self.trace_path = root / "agent_traces.jsonl"
        self.audit_path = root / "audit.jsonl"
        for module, attribute, value in (
                (agent_trace_module, "TRACE_PATH", self.trace_path),
                (audit_module, "AUDIT_PATH", self.audit_path),
                (conversation_agent_module, "settings", self.settings)):
            patcher = mock.patch.object(module, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.tools = _StubToolRegistry()
        patcher = mock.patch.object(conversation_agent_module, "tool_registry", self.tools)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("allowed_for", lambda user: ["kb-1"]),
                            ("effective_allowed_from_grant", lambda grant: None),
                            ("visible_bases_by_ids",
                             lambda ids: [{"id": "kb-1", "name": "公共制度"}])):
            patcher = mock.patch.object(conversation_agent_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tokens: list[str] = []

    def use_settings(self, **overrides) -> Settings:
        base = dict(self.SSE_SETTINGS_DEFAULTS)
        base.update(overrides)
        return super().use_settings(**base)

    # --- 驱动 -------------------------------------------------------------
    @staticmethod
    def user() -> CurrentUser:
        return CurrentUser(username="sse-alice", display_name="SSE Alice", role="ADMIN")

    def ask(self, *, stream: bool = True, question: str = PLAIN_QUESTION,
            history: list[dict] | None = None, token_sink=None, **tool_kwargs) -> dict:
        """跑一次本地快路径（`mode="local"` ⇒ `_local_fast_path`）。"""
        if tool_kwargs:
            self.tools = _StubToolRegistry(**tool_kwargs)
            patcher = mock.patch.object(conversation_agent_module, "tool_registry",
                                        self.tools)
            patcher.start()
            self.addCleanup(patcher.stop)
        sink = self.tokens.append if (stream and token_sink is None) else token_sink
        return conversation_agent_module.run_conversation_agent(
            question=question, user=self.user(), mode="local",
            knowledge_base_id="kb-1", top_k=3, rerank=False,
            history=history if history is not None else [], token_sink=sink)

    def ask_streaming(self, **kwargs) -> dict:
        return self.ask(stream=True, **kwargs)

    def ask_buffered(self, **kwargs) -> dict:
        return self.ask(stream=False, **kwargs)

    # --- 观测面直读 -------------------------------------------------------
    def trace_rows(self) -> list[dict]:
        if not self.trace_path.exists():
            return []
        return [json.loads(line) for line in
                self.trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def audit_rows(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in
                self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def requested_models(self) -> list[str]:
        """被真的发出过请求的**生效模型名**（顺序=外呼顺序）：区分候选靠它。"""
        return [str(record.payload["model"]) for record in self.requests]

    def stream_options(self) -> dict:
        return dict(self.requests[-1].payload["options"])

    def guard_legacy_chat_off(self) -> None:
        """router 路上不许再走 legacy 的 `_ollama_chat`（那是第二条出口）。"""
        def forbidden(*args, **kwargs):
            raise AssertionError("router 路上不得再调用 legacy 的 agent._ollama_chat")
        patcher = mock.patch.object(agent_module, "_ollama_chat", forbidden)
        patcher.start()
        self.addCleanup(patcher.stop)

    def spy_legacy_chat(self) -> list[tuple]:
        calls: list[tuple] = []
        patcher = mock.patch.object(
            agent_module, "_ollama_chat",
            lambda messages, tools: calls.append((messages, tools)) or {
                "role": "assistant", "content": SSE_ANSWER})
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def guard_router_calls_off(self) -> None:
        """旗标关掉时不许碰包级入口（矩阵 #18 的「legacy 路不经过 router」）。"""
        def forbidden_factory(entry: str):
            def forbidden(*args, **kwargs):
                raise AssertionError(f"LLM_ROUTER_ENABLED=false 时不得调用 llm.{entry}()")
            return forbidden

        for name in ("complete", "stream"):
            patcher = mock.patch.object(llm, name, forbidden_factory(name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def drive_route(self, agent) -> tuple[list[tuple[str, dict]], "_StubConversationStore"]:
        """直接驱动 SSE 路由的 worker 线程：返回 `(事件序列, 会话面替身)`。

        `_stream_response` 返回的 `StreamingResponse.body_iterator` 就是那个内部生成器
        （`event_stream()`），worker 线程往队列里塞、生成器取——所以不必起 HTTP / 鉴权，
        而 D5 的事件面仍然是**真路由代码**产出的。
        """
        store = _StubConversationStore()
        with (mock.patch.object(stream_routes_module, "conversation_store", store),
              mock.patch.object(stream_routes_module, "run_conversation_agent", agent)):
            response = stream_routes_module._stream_response(
                conversation_id="c-1", assistant_message_id="m-1",
                question=PLAIN_QUESTION, history=[], mode="local",
                knowledge_base_id="kb-1", top_k=3, rerank=False, user=self.user())
            # starlette 把同步生成器包成 async generator（`iterate_in_threadpool`），
            # 所以这里必须 `asyncio.run` 取；worker 线程 + 阻塞队列照跑，不改事件形状。
            async def collect() -> str:
                parts: list[str] = []
                async for piece in response.body_iterator:
                    parts.append(piece)
                return "".join(parts)

            frames = sse_frames(asyncio.run(collect()))
        return frames, store

    def drive_agent_route(self, agent) -> list[tuple[str, dict]]:
        """驱动**第二条** SSE 出口 `/api/agent/query/stream`（评审 I-4 的落点）。

        与 `drive_route` 同一手法：不起 HTTP、不过鉴权，直接取端点返回的
        `StreamingResponse.body_iterator`（worker 线程 + 阻塞队列照跑）。桩只打在
        `run_conversation_agent` 与「会话面无关的 KB 范围校验」上 ⇒ 事件面仍是**真路由代码**
        （含新加的 `except StreamInterrupted` 支）产出的。
        """
        request = agent_routes_module.AgentQueryRequest(question=PLAIN_QUESTION, mode="local")
        with (mock.patch.object(agent_routes_module, "run_conversation_agent", agent),
              mock.patch.object(agent_routes_module, "_validate_knowledge_base_scope",
                                lambda *args, **kwargs: None)):
            response = agent_routes_module.agent_query_stream(request, user=self.user())

            async def collect() -> str:
                parts: list[str] = []
                async for piece in response.body_iterator:
                    parts.append(piece)
                return "".join(parts)

            return sse_frames(asyncio.run(collect()))


def business_file_has_no_second_llm_egress(case: unittest.TestCase,
                                           path: Path) -> None:
    """D6 判定（T7 的业务文件落点）：只看**代码**——import 与字符串常量。

    与 `SingleEgressStructureTests` 同一口径：散文里提一句端点名不是出口（本任务的迁移
    说明就写了「不许再把 `/api/chat` 内联回来」，按全文扫会把这句话读成违规）。
    `native_stream` **字段名**（`timings` 的键）因此也不在字符串黑名单里——留字段、退役
    模块正是本任务的关键区分，只有 `import` 才是模块。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "httpx" for alias in node.names):
                offenders.append("import httpx")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in {"httpx", "native_stream"}:
                offenders.append(f"from {node.module}")
            if any(alias.name == "ollama_chat_stream" for alias in node.names):
                offenders.append("import ollama_chat_stream")
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node not in docstrings):
            for literal in ("/api/chat", "/chat/completions", "ollama_base_url"):
                if literal in node.value:
                    offenders.append(f"字符串常量 {literal}")
        elif isinstance(node, ast.Attribute) and node.attr == "ollama_base_url":
            offenders.append("属性 settings.ollama_base_url")
    case.assertEqual([], offenders, f"{path.name} 里出现了第二条出口的痕迹")


# --------------------------------------------------------------------------
# 1. 矩阵 #9：流式序完整 + B 项的三条硬义务（ttft 记录点 / 逐 chunk 脱敏 / 键语义）
# --------------------------------------------------------------------------
class SseStreamContractTests(_SseMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.guard_legacy_chat_off()

    def test_the_stream_leg_forwards_every_content_chunk_in_order(self):
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        result = self.ask_streaming()
        self.assertEqual(SSE_PARTS, self.tokens)                 # 逐 chunk，不合并、不切片
        self.assertEqual(SSE_ANSWER, result["answer"])
        self.assertIs(True, result["timings"]["native_stream"])  # 字段：走了逐 token 出口
        self.assertEqual(1, len(self.requests))                  # 一次问答 = 一次外呼

    def test_the_legacy_ndjson_streaming_payload_is_reproduced_on_the_wire(self):
        """退役模块当年发的报文形状逐键复现（§9「既有对外不变」最硬的那一枚）。

        `native_stream.py` 的 payload 是 `model / stream=True / think / keep_alive /
        messages / tools=[] / options{temperature=0.2, num_predict}` —— 迁移后同一套键
        必须由 `llm.stream` 原样发出来，少一枚就是行为变更。

        **调用面 spy（Task 7 评审 I-1 补的钉）**：报文值那三枚等式挡不住「漏参」——
        `llm.stream` 的形参默认与 `LLMRequest.temperature` 的字段默认**都是 0.2**，删掉
        `temperature=` 之后线上字节一模一样（评审的变异 `M3b` 因此存活）。手法与非流式腿
        `SseBufferedAndLegacyTests` 那枚同形：spy 包一层真实现（不改任何行为），把「显式传参」
        变成可观测事实。⇒ 两腿现在各钉两个面（报文 + 调用），谁退化谁红。
        """
        seen: list[dict] = []
        real_stream = llm.stream

        def spy(*args, **kwargs):
            seen.append(dict(kwargs))
            return real_stream(*args, **kwargs)

        patcher = mock.patch.object(llm, "stream", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        self.ask_streaming()
        payload = self.requests[-1].payload
        self.assertTrue(payload["stream"])
        self.assertEqual([], payload["tools"])                   # 空 tools 仍带键
        self.assertFalse(payload["think"])
        self.assertEqual(self.settings.ollama_keep_alive, payload["keep_alive"])
        self.assertEqual({"temperature", "num_predict"}, set(payload["options"]))
        self.assertEqual(
            conversation_agent_module.CONVERSATION_LEGACY_TEMPERATURE,
            payload["options"]["temperature"])
        self.assertEqual(CONVERSATION_LEGACY_TEMPERATURE_ON_THE_WIRE,
                         payload["options"]["temperature"])
        self.assertNotEqual(llm.RAG_LEGACY_TEMPERATURE, payload["options"]["temperature"],
                            "0.1 是 `app/rag.py` 那条链的现值，SSE 流式腿不吃它")
        self.assertEqual(int(self.settings.agent_num_predict_synthesis),
                         payload["options"]["num_predict"])
        self.assertEqual("user", payload["messages"][-1]["role"])
        self.assertEqual(PLAIN_QUESTION.strip(), payload["messages"][-1]["content"])
        # ---- 调用面（I-1 缺的那枚钉；= 变异 M3b 的杀手）---------------------
        self.assertEqual(1, len(seen), "流式腿没经过 `llm.stream` ⇒ 迁移没落地")
        self.assertIn("temperature", seen[0],
                      "漏参 = 退化成形参/字段默认（两枚都是 0.2 ⇒ 报文面看不出来）")
        self.assertEqual(conversation_agent_module.CONVERSATION_LEGACY_TEMPERATURE,
                         seen[0]["temperature"],
                         "显式传的温度与产品常量不等 ⇒ 本链的温度被换走了")

    def test_ttft_is_recorded_at_the_first_content_chunk(self):
        """记录点 = 首个内容 chunk（M5b 的杀手）**且**两枚零点真的不同轴（M5a 的杀手）。

        评审 I-2 的判定：`timings["ttft_ms"]` 以整次请求的 `started` 为零点（**含**检索段），
        账本 `ttft_ms` 由 `StreamSession._commit` 以 `_session_started` 为零点（**不含**）。
        原来这里只有 `0 <= timings.ttft <= llm_ms` + 账本那枚非空 ⇒ 换零点后两条仍然成立。
        现在把检索段真实推进 `SSE_RETRIEVAL_SLEEP_MS`，两枚轴就成了一笔**可比较的事实**：
        差值 >= 同一次运行里量到的 `retrieval_ms`（差值按构造只可能更大，不会更小 ⇒ 无抖动）。
        配套地，交付回调每枚 chunk 后真实睡 `SSE_GENERATION_SLEEP_MS` ⇒ 既有的
        `ttft <= llm_ms` 上界（`llm_ms` 的零点=`llm_started`、覆盖整个消费循环）在检索段被抬高
        之后仍然稳稳成立，**一枚既有断言都不放宽**。
        """
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))

        def slow_sink(text: str) -> None:
            self.tokens.append(text)
            time.sleep(SSE_GENERATION_SLEEP_MS / 1000.0)

        result = self.ask_streaming(
            timings=SSE_TYPESAFE_TIMINGS,                       # ⇒ timings["ttft_ms"] 出现
            sleep_ms=SSE_RETRIEVAL_SLEEP_MS,                    # 检索段真实推进
            token_sink=slow_sink)
        self.assertIn("ttft_ms", result["timings"])
        self.assertIsNotNone(result["timings"]["ttft_ms"])
        self.assertGreaterEqual(float(result["timings"]["ttft_ms"]), 0.0)
        self.assertLessEqual(float(result["timings"]["ttft_ms"]),
                             float(result["timings"]["llm_ms"]))
        # 账本那枚（零点=会话开始，由 StreamSession 记）也必须非空——两枚同源于
        # 「首个内容 chunk」这件事，只是不同轴。
        rows = self.raw_rows()
        self.assertEqual(1, len(rows))
        self.assertIsNotNone(rows[0]["ttft_ms"], rows[0])
        # ---- 两枚轴现在是事实，不是注释（M5a 换零点 ⇒ 下面两枚一起红）--------
        retrieval_ms = float(result["timings"]["retrieval_ms"])
        self.assertGreaterEqual(retrieval_ms, SSE_RETRIEVAL_SLEEP_MS - TTFT_AXIS_EPSILON_MS,
                                "注入的检索段没生效 ⇒ 上面那枚轴比较会退化成恒真")
        self.assertGreater(
            float(result["timings"]["ttft_ms"]) - float(rows[0]["ttft_ms"]),
            0.0, "两枚 ttft 成了同一个数 ⇒ 有人把零点合并/冒充了（D5 口径事故）")
        self.assertGreaterEqual(
            float(result["timings"]["ttft_ms"]) - float(rows[0]["ttft_ms"]),
            retrieval_ms - TTFT_AXIS_EPSILON_MS,
            "`timings[\"ttft_ms\"]` 不再**包含**检索段 ⇒ 它的零点被换成了会话/LLM 起点，"
            "这是对外字段语义变更（评审 I-2；账本那枚的零点仍是会话开始）")

    def test_redaction_happens_per_chunk_before_the_client_sees_it(self):
        """任务书点名的变异：把 `redact_text` 从逐 chunk 挪走 ⇒ 这一例必须红。

        只对**客户端可见面**断言（`self.tokens`）：最终答案还会过一道 `redact_secrets`，
        所以「挪到收尾再洗」在响应面上看不出来，在 token 流上立刻看出来。
        """
        parts = [SSE_PARTS[0], SSE_SECRET_CHUNK, SSE_PARTS[1]]
        self.serve(_response(200, content=sse_stream_body(*parts)))
        result = self.ask_streaming()
        blob = "".join(self.tokens)
        self.assertNotIn("leaked-token-abc123", blob)
        self.assertIn("Bearer [REDACTED]", blob)
        self.assertNotIn("leaked-token-abc123", result["answer"])
        self.assertEqual(len(parts), len(self.tokens))           # 脱敏没吞掉任何一段

    def test_the_done_marker_chunk_is_not_pushed_to_the_client(self):
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        self.ask_streaming()
        self.assertNotIn("", self.tokens)                        # 空 chunk 不推
        self.assertEqual(SSE_PARTS, self.tokens)

    def test_llm_ms_llm_calls_and_model_used_keep_their_meaning(self):
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        result = self.ask_streaming()
        self.assertEqual(1, result["timings"]["llm_calls"])      # 一次会话 = 一腿一次调用
        self.assertGreaterEqual(float(result["timings"]["llm_ms"]), 0.0)
        self.assertEqual(RAG_LOCAL_MODEL, result["model_used"])  # selected 的生效模型名
        self.assertEqual(result["model_used"], self.raw_rows()[0]["model"])

    def test_model_used_follows_the_d1_model_override_alias(self):
        """M2：`model_used` 与账本 `model` 列同源于「生效模型名」，含 D1 别名。"""
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS,
                                                          model="prod-alias-2026")))
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL_OVERRIDE": "prod-alias-2026"}):
            result = self.ask_streaming()
        self.assertEqual("prod-alias-2026", result["model_used"])
        self.assertEqual("prod-alias-2026", self.raw_rows()[0]["model"])
        self.assertEqual("prod-alias-2026", self.requests[-1].payload["model"])

    def test_an_empty_answer_still_uses_the_existing_copy(self):
        """干净收但一个内容 chunk 都没有（`done` 直接到）：文案与 `native_stream` 都不变。"""
        self.serve(_response(200, content=sse_stream_body()))
        result = self.ask_streaming()
        self.assertEqual("当前没有获得足够证据生成可靠答案。", result["answer"])
        self.assertIs(True, result["timings"]["native_stream"])
        self.assertEqual([], self.tokens)

    def test_the_timings_key_set_is_exactly_what_it_was_before_the_migration(self):
        """§9「既有响应结构对外不变」：`timings` 按**等式**钉，不按「包含」钉。"""
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        result = self.ask_streaming()
        self.assertEqual(set(SSE_TIMING_KEYS), set(result["timings"]))
        again = self.ask_streaming(timings=dict(SSE_TYPESAFE_TIMINGS))
        self.assertEqual(SSE_TIMING_KEYS | {"ttft_ms"} | set(SSE_TYPESAFE_TIMINGS),
                         set(again["timings"]))

    def test_the_three_no_generation_paths_never_touch_the_llm(self):
        """DENIED / 检索失败 / 零证据三条文案路：`native_stream=False`、零外呼、零账、无 route。"""
        cases = (
            ("DENIED 授权路", {"status": "DENIED", "evidence": []},
             "当前账号无权访问该知识库，因此不能基于未授权资料回答。"),
            ("检索失败路", {"status": "FAILED", "evidence": []},
             "企业知识检索暂时失败，请稍后重试。"),
            ("零证据路", {"status": "SUCCESS", "evidence": []},
             "当前授权范围内没有检索到足够证据，暂时无法可靠回答。"),
        )
        for label, tool_kwargs, copy in cases:
            with self.subTest(case=label):
                self.tokens.clear()
                result = self.ask(stream=True, **tool_kwargs)
                self.assertEqual(copy, result["answer"])
                self.assertEqual([], self.requests, "没走到生成就不该外呼")
                self.assertIs(False, result["timings"]["native_stream"])
                self.assertEqual([], self.raw_rows(), "没走过路由就不该有账")
                trace = self.trace_rows()[-1]
                self.assertNotIn(MODEL_ROUTE_KEY, trace)
                self.assertEqual(0, result["timings"]["llm_calls"])


# --------------------------------------------------------------------------
# 2. 矩阵 #10 / #11：commit 边界（D5 的主证据）
# --------------------------------------------------------------------------
class SseCommitMatrixTests(_SseMigrationFixture):
    PRIMARY = "ornith-1.5:9b-text"
    SECOND = "phi3:mini"

    def setUp(self) -> None:
        super().setUp()
        self.guard_legacy_chat_off()
        self.use_registry(
            rag_entry(id="ollama-ornith", model=self.PRIMARY),
            rag_entry(id="ollama-phi3", model=self.SECOND,
                      priority={"chat": 80, "rag": 80, "tools": 0}))

    def serve_two_legs(self, first: httpx.Response, second: httpx.Response) -> None:
        """按**模型名**应答（不是按次序）：谁被真的调用过，证据就在 `self.requests` 里。"""
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(Recorded(request))
            model = json.loads(request.read().decode("utf-8"))["model"]
            return first if model == self.PRIMARY else second
        patcher = mock.patch.object(provider_module, "_transport",
                                    httpx.MockTransport(handler))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matrix_10_pre_commit_failure_switches_model_and_the_user_sees_one_answer(self):
        """§7：首个有效内容 token **之前**的失败 = 可安全换候选，用户无感。"""
        self.serve_two_legs(_response(500, json_body={"error": "boom"}),
                            _response(200, content=sse_stream_body(*SSE_PARTS,
                                                                   model=self.SECOND)))
        result = self.ask_streaming()
        self.assertEqual(SSE_PARTS, self.tokens)                 # 没有半截失败答案漏给客户
        self.assertEqual(SSE_ANSWER, result["answer"])
        self.assertEqual([self.PRIMARY, self.SECOND], self.requested_models())
        self.assertEqual(1, result["timings"]["llm_calls"])      # 换候选不等于多调一次 LLM
        row = self.raw_rows()[0]
        self.assertEqual(1, row["success"])
        self.assertEqual(1, row["fallback_index"])               # §10 #4/#5 的口径
        self.assertEqual(self.SECOND, row["model"])

    def test_matrix_11_post_commit_failure_never_switches_model(self):
        """§7/D5 冻结：commit 之后禁止换模型——第二条候选一次都不许被调用。"""
        self.serve_two_legs(_response(200, content=sse_stream_body(SSE_PARTS[0],
                                                                   terminate=False)),
                            _response(200, content=sse_stream_body("绝不该出现",
                                                                   model=self.SECOND)))
        with self.assertRaises(StreamInterrupted) as caught:
            self.ask_streaming()
        self.assertEqual([self.PRIMARY], self.requested_models())   # ← D5 的证明
        self.assertEqual([SSE_PARTS[0]], self.tokens)               # 已交付的部分不重播
        self.assertEqual("retryable", caught.exception.error_type)
        self.assertEqual(SSE_PARTS[0], caught.exception.partial_text)

    def test_a_provider_error_frame_after_content_keeps_its_real_kind(self):
        """任务书点名的用例：「provider 侧真实归类活过 commit」。

        断流发生在**交付之后** ⇒ `success=False` 的行必须仍带着原始 kind
        （这里是 `model_unavailable`，来自 `{"error": "... failed to load"}` 的 200 帧内
        归类），既不许留空、也不许被 `client_aborted` 顶掉（§8.1 第 2 条：留空 + 有交付
        事实才会被读成关页）。
        """
        self.serve(_response(200, content=sse_stream_body(
            *SSE_PARTS, error_after="model 'ornith' failed to load")))
        with self.assertRaises(StreamInterrupted) as caught:
            self.ask_streaming()
        self.assertEqual("model_unavailable", caught.exception.error_type)
        row = self.raw_rows()[0]
        self.assertEqual(1, len(self.raw_rows()))
        self.assertEqual(0, row["success"])
        self.assertEqual("model_unavailable", row["error_type"], row)
        self.assertNotEqual("client_aborted", row["error_type"])
        self.assertNotEqual("unknown", row["error_type"])
        # 诚实记下的一处形状（T4 冻结：usage 只取**成功收尾那一轮**的 provider 回执）：
        # commit 后中断的会话没有半截 usage 可入账 ⇒ 三枚 token 列全 0。这正因为
        # `error_type` 带着真实归类，才没被「缺席」反推成关页（§8.1 第 2 条的交付闸）。
        self.assertEqual((0, 0, 0), (row["input_tokens"], row["output_tokens"],
                                     row["total_tokens"]))
        self.assertEqual(0, row["fallback_index"])                # 交付过内容 ⇒ 选中了它
        self.assertIsNotNone(row["ttft_ms"])                      # 首 chunk 确实发生过

    def test_a_pre_commit_total_failure_writes_exactly_one_failed_row(self):
        """全链 pre-commit 皆败 ⇒ 聚合错误上抛 + 一行 `success=0` 且 kind 非空。"""
        self.serve_two_legs(_response(500, json_body={"error": "boom"}),
                            _response(503, json_body={"error": "still down"}))
        with self.assertRaises(AllCandidatesFailedError):
            self.ask_streaming()
        rows = self.raw_rows()
        self.assertEqual(1, len(rows), rows)
        self.assertEqual(0, rows[0]["success"])
        self.assertIn(rows[0]["error_type"], ("retryable", "model_unavailable"), rows[0])
        self.assertEqual(-1, rows[0]["fallback_index"])          # 没选中任何候选
        self.assertIsNone(rows[0]["ttft_ms"])                    # 一个内容 chunk 都没交付
        self.assertEqual([], self.tokens)                        # 什么都没推给客户
        self.assertEqual([self.PRIMARY, self.SECOND], self.requested_models())

    def test_the_chain_never_writes_the_ledger_sentinels_itself(self):
        """§8.1 第 2 条的结构义务：`client_aborted` / `unknown` 是**账本的产物**。

        链上只允许写 provider 的 `kind`（或 `kind:status`）。行为面已经由上面两例钉住
        （commit 后中断 = 原始 kind；pre-commit 全败 = 原始 kind 而不是关页），这里补
        源码面：本文件里出现那两枚哨兵 ⇒ 有人在替账本下结论。
        """
        source = (BACKEND_DIR / "app" / "conversation_agent.py").read_text(encoding="utf-8")
        for sentinel in ("client_aborted", "ERROR_TYPE_UNKNOWN"):
            self.assertNotIn(sentinel, source, f"链上自写了账本哨兵：{sentinel}")

    def test_a_zero_candidate_plan_writes_no_row_at_all(self):
        """D2/T5 裁定的延伸：零候选（一条请求都没发出）⇒ 0 行，与 RAG 链同一个口径。"""
        self.use_registry(rag_entry(limits={"context_tokens": 8, "max_output_tokens": 4}))
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        with self.assertRaises(NoCapableModelError):
            self.ask_streaming()
        self.assertEqual([], self.raw_rows())
        self.assertEqual([], self.requests)
        self.assertEqual([], self.tokens)                        # 用户没看到一个字


# --------------------------------------------------------------------------
# 3. 矩阵 #17（本任务这半段）：真调用 + 真落盘九键
# --------------------------------------------------------------------------
class SseTraceIntegrationTests(_SseMigrationFixture):
    def setUp(self) -> None:
        super().setUp()
        self.guard_legacy_chat_off()

    def assert_nine_keys(self, route: dict) -> None:
        self.assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route))
        self.assertEqual(9, len(route))
        self.assertEqual({"complexity", "needs_tools", "needs_stream", "needs_reasoning"},
                         set(route["requirements"]))
        self.assertEqual({"id", "provider", "model", "score", "reason_codes"},
                         set(route["primary"]))
        self.assertTrue(route["attempts"], "attempts 非空：这是一条真跑过一次的链")

    def assert_route_has_no_private_bytes(self, route: dict) -> None:
        """D3/§8 的禁存项扫 `model_route` **对象本身**（序列化后 0 命中）。

        刻意不扫整份 trace：`events[].question_preview`（用户问题前 240 字）与
        `answer_preview` 是**迁移之前就存在**的形状，本任务一枚字节都没动它们；要新增
        禁存项义务得连着 `agent.py` 的 trace 形状一起谈（不在 T7 改动面）。route 这一层
        是本次新挂上去的，所以它的义务是全新的、必须 0 命中：问题原文、证据正文、
        system prompt、证据块键名，一处都不许出现。
        """
        blob = json.dumps(route, ensure_ascii=False)
        for canary in (RAG_PROMPT_CANARY, "差旅住宿上限", "报销制度.md",
                       agent_module.AGENT_SYSTEM_PROMPT[:24], "AUTHORIZED_ENTERPRISE_EVIDENCE",
                       "sse-alice"):
            self.assertNotIn(canary, blob, f"model_route 里出现了禁存项：{canary[:12]}…")
        # 键面封口：九键 + 三张子视图的键集都是封闭的，没有能装下 prompt 的落点。
        self.assertEqual({"mode", "requirements", "primary", "fallbacks",
                          "selected_reason_codes", "attempts", "stage", "selected_index",
                          "context_dropped"}, set(route))
        self.assertEqual({"model", "result", "error_type"}, set(route["attempts"][0]))

    def test_a_real_streamed_answer_lands_a_nine_key_model_route_on_disk(self):
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        result = self.ask_streaming()
        rows = self.trace_rows()
        self.assertEqual(1, len(rows))
        trace = rows[0]
        self.assertIn(MODEL_ROUTE_KEY, trace, "唯一挂载点没挂上 ⇒ #17 的交付物不存在")
        route = trace[MODEL_ROUTE_KEY]
        self.assert_nine_keys(route)
        self.assertEqual("rag", route["mode"])
        self.assertIs(True, route["requirements"]["needs_stream"])   # SSE = rag + stream
        self.assertIs(False, route["requirements"]["needs_tools"])
        self.assertEqual(RAG_LOCAL_MODEL, route["primary"]["model"])
        self.assertEqual("primary", route["stage"])
        self.assertEqual(0, route["selected_index"])
        self.assertEqual(0, route["context_dropped"])
        self.assertEqual("success", route["attempts"][0]["result"])
        self.assertIsNone(route["attempts"][0]["error_type"])
        # additive：只多这一枚键，既有 trace 键一个不动。
        self.assertEqual({"trace_id", "timestamp", "username", "role", "mode", "model",
                          "max_tool_rounds", "context_messages", "events",
                          "evidence_count", "elapsed_ms", "timings", MODEL_ROUTE_KEY},
                         set(trace))
        self.assert_route_has_no_private_bytes(route)
        # **真 JSONL 往返**：读回来的 route 与内存里那份等价（矩阵 #17 的方法列=集成）。
        with mock.patch.object(agent_trace_module, "TRACE_PATH", self.trace_path):
            read_back = agent_trace_module.get_trace(result["trace_id"])
        self.assertEqual(trace, read_back)
        self.assert_route_has_no_private_bytes(read_back[MODEL_ROUTE_KEY])

    def test_the_interrupted_stream_also_lands_a_model_route(self):
        """T5 移交第三条：`StreamInterrupted` 那条路**也要挂**——它是最需要解释的一次离开。

        事实全部来自 `session.finish()`（`StreamInterrupted` 不带 `plan`/`context_dropped`），
        链上不自拼 dict、也不复制九键。
        """
        self.serve(_response(200, content=sse_stream_body(SSE_PARTS[0], terminate=False)))
        with self.assertRaises(StreamInterrupted):
            self.ask_streaming()
        trace = self.trace_rows()[0]
        route = trace[MODEL_ROUTE_KEY]
        self.assert_nine_keys(route)
        self.assertEqual(1, len(route["attempts"]))
        self.assertEqual("failed", route["attempts"][0]["result"])
        self.assertEqual("retryable", route["attempts"][0]["error_type"])
        self.assertEqual(0, route["selected_index"])             # 交付过内容 ⇒ 选中了它
        self.assertEqual("primary", route["stage"])
        self.assert_route_has_no_private_bytes(route)
        # 中断那次离开照样**落了盘**（不是内存对象）：JSONL 里读得到同一份九键。
        self.assertEqual(route, agent_trace_module.get_trace(
            trace["trace_id"])[MODEL_ROUTE_KEY])
        row = self.raw_rows()[0]
        self.assertEqual(0, row["success"])
        self.assertEqual("retryable", row["error_type"])          # trace 与账本同一件事
        self.assertEqual(route["attempts"][0]["model"], row["model"])

    def test_the_buffered_leg_lands_a_route_from_the_fallback_result(self):
        self.serve(_response(200, json_body=ollama_body(SSE_ANSWER)))
        self.ask_buffered()
        route = self.trace_rows()[0][MODEL_ROUTE_KEY]
        self.assert_nine_keys(route)
        self.assertIs(False, route["requirements"]["needs_stream"])
        self.assertEqual("success", route["attempts"][0]["result"])

    def test_no_route_is_attached_when_the_chain_never_reached_generation(self):
        self.ask_streaming(evidence=[])                          # 零证据文案路
        trace = self.trace_rows()[0]
        self.assertNotIn(MODEL_ROUTE_KEY, trace,
                         "没有执行面事实就不许凭空造一枚 model_route（不猜）")

    def test_the_llm_package_never_touches_trace_shapes(self):
        """结构义务：trace 形状归业务层，llm 包只产「执行面事实」，不挂 trace。"""
        offenders: list[str] = []
        for path in sorted((BACKEND_DIR / "app" / "llm").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            code = "\n".join(line for line in text.splitlines()
                             if not line.lstrip().startswith("#"))
            for needle in ("save_trace(", "TRACE_PATH", "import app.agent_trace",
                           "from app.agent_trace"):
                if needle in code:
                    offenders.append(f"{path.name}: {needle}")
        self.assertEqual([], offenders)


# --------------------------------------------------------------------------
# 4. 任务书 A + D：buffered 腿走 `llm.complete(mode="rag")`；legacy 分支保留原调用
# --------------------------------------------------------------------------
class SseBufferedAndLegacyTests(_SseMigrationFixture):
    def test_the_buffered_leg_goes_through_the_router_with_mode_rag(self):
        self.guard_legacy_chat_off()
        self.serve(_response(200, json_body=ollama_body(SSE_ANSWER)))
        result = self.ask_buffered()
        self.assertEqual(SSE_ANSWER, result["answer"])
        self.assertIs(False, result["timings"]["native_stream"])  # 没走逐 token 出口
        self.assertEqual(1, len(self.requests))
        self.assertFalse(self.requests[-1].payload["stream"])
        self.assertEqual(1, result["timings"]["llm_calls"])

    def test_the_buffered_leg_carries_the_conversation_temperature_and_the_legacy_option_keys(self):
        """任务书 A 的完整形状：`temperature=CONVERSATION_LEGACY_TEMPERATURE` **不是可选项**。

        这枚钉子必须**同时**打在两个面上，否则挡不住 T7 收尾任务书点名的变异 #1：
        * 报文面：`options.temperature` == 0.2 == 本链的 legacy 现值（与流式腿同一枚常量），
          且 != `llm.RAG_LEGACY_TEMPERATURE`（0.1，那是 `app/rag.py` 链的值）；
        * 调用面：`llm.complete(...)` 的 **kwargs 里必须有 `temperature`**。只钉报文值会
          「碰巧绿」——`LLMRequest.temperature` 的字段默认恰好也是 0.2，删掉这一参之后
          报文一模一样。spy 包一层真实现（不改变任何行为），把「显式传参」变成可观测事实。
        另外三枚（`think`/`num_predict`/`keep_alive`）照 legacy `_ollama_chat(messages, [])`
        的现值透传，漏任何一枚都是「重构顺带改了报文」。
        """
        self.guard_legacy_chat_off()
        seen: list[dict] = []
        real_complete = llm.complete

        def spy(*args, **kwargs):
            seen.append(dict(kwargs))
            return real_complete(*args, **kwargs)

        patcher = mock.patch.object(llm, "complete", spy)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.serve(_response(200, json_body=ollama_body(SSE_ANSWER)))
        self.ask_buffered()
        payload = self.requests[-1].payload
        self.assertEqual(1, len(seen), "非流式腿没经过 `llm.complete` ⇒ 迁移没落地")
        self.assertIn("temperature", seen[0],
                      "漏参 = 退化成 `LLMRequest` 的字段默认（巧合对，不算钉住）")
        self.assertEqual(conversation_agent_module.CONVERSATION_LEGACY_TEMPERATURE,
                         seen[0]["temperature"])
        self.assertEqual(CONVERSATION_LEGACY_TEMPERATURE_ON_THE_WIRE,
                         payload["options"]["temperature"])
        self.assertEqual(0.2, payload["options"]["temperature"])
        self.assertNotEqual(llm.RAG_LEGACY_TEMPERATURE, payload["options"]["temperature"],
                            "本链被换成了 `app/rag.py` 那条链的温度常量")
        self.assertEqual({"temperature", "num_predict"}, set(payload["options"]))
        self.assertFalse(payload["think"])
        self.assertEqual(self.settings.ollama_keep_alive, payload["keep_alive"])
        self.assertEqual([], payload["tools"])

    def test_both_legs_send_the_same_legacy_payload_except_the_stream_flag(self):
        """**矩阵 #18 的口径（T7 收尾修正）**：两条腿的报文与 legacy **逐字等价**。

        原来这一枚钉的是「buffered 腿 0.2 → 0.1 的**已声明偏差**」，那是任务书写错常量
        （0.1 属于 `app/rag.py` 那条链）。事实源：`agent._ollama_chat` 的 `options` 与退役的
        `app/native_stream.py:27-28` **都是 0.2** ⇒ 偏差不存在，本枚改成钉等价：
        ① 两腿的 `options` / `think` / `keep_alive` / `tools` / `messages` 逐字相等；
        ② 键集合差**恰好**是 `{"stream"}`（钉等式而不是 `<=`：多一处漂移就红）；
        ③ 两腿的温度都 == 独立写死的 legacy 现值 0.2 == 产品常量，且 != 0.1。
        """
        self.guard_legacy_chat_off()

        def dispatch(request: httpx.Request) -> httpx.Response:
            sent = json.loads(request.read().decode("utf-8"))
            if sent["stream"]:
                return _response(200, content=sse_stream_body(*SSE_PARTS))
            return _response(200, json_body=ollama_body(SSE_ANSWER))

        self.serve(dispatch)
        self.ask_streaming()
        streamed = dict(self.requests[-1].payload)
        self.ask_buffered()
        buffered = dict(self.requests[-1].payload)
        self.assertIs(True, streamed["stream"])
        self.assertIs(False, buffered["stream"])
        self.assertEqual({"stream"},
                         {key for key in set(streamed) | set(buffered)
                          if streamed.get(key) != buffered.get(key)},
                         "两腿之间只允许 `stream` 一枚不同——多一处就是顺手改了报文")
        for key in ("options", "think", "keep_alive", "tools", "messages", "model"):
            self.assertEqual(streamed[key], buffered[key], f"{key} 在两腿间漂移")
        for label, sent in (("stream", streamed), ("buffered", buffered)):
            with self.subTest(leg=label):
                self.assertEqual(CONVERSATION_LEGACY_TEMPERATURE_ON_THE_WIRE,
                                 sent["options"]["temperature"])
                self.assertEqual(conversation_agent_module.CONVERSATION_LEGACY_TEMPERATURE,
                                 sent["options"]["temperature"])
                self.assertNotEqual(llm.RAG_LEGACY_TEMPERATURE,
                                    sent["options"]["temperature"])
        self.assertEqual({"model", "stream", "think", "messages", "tools", "options",
                          "keep_alive"}, set(buffered))
        self.assertEqual({"temperature", "num_predict"}, set(buffered["options"]))



    def test_matrix_18_the_legacy_branch_still_calls_agent_ollama_chat(self):
        """旗标关掉 ⇒ buffered 腿回到**原调用**，且包级入口一次都不许被碰。"""
        self.use_settings(llm_router_enabled=False)
        calls = self.spy_legacy_chat()
        self.guard_router_calls_off()
        result = self.ask_buffered()
        self.assertEqual(SSE_ANSWER, result["answer"])
        self.assertEqual(1, len(calls), "legacy 腿必须仍然走 agent._ollama_chat")
        messages, tools = calls[0]
        self.assertEqual([], tools)
        self.assertEqual("user", messages[-1]["role"])
        self.assertEqual(PLAIN_QUESTION.strip(), messages[-1]["content"])
        self.assertIs(False, result["timings"]["native_stream"])
        self.assertEqual(RAG_LOCAL_MODEL, result["model_used"])   # legacy 的展示名不变
        self.assertEqual([], self.raw_rows(), "legacy 路不经路由 ⇒ 不该有路由账")

    def test_matrix_18_legacy_and_routed_buffered_legs_send_the_same_messages(self):
        """两腿的 `messages` **逐字相等**（旗标只切执行面，不切 prompt 口径）。"""
        legacy_calls: list[tuple] = []

        def legacy(messages, tools):
            legacy_calls.append((messages, tools))
            return {"role": "assistant", "content": SSE_ANSWER}

        self.use_settings(llm_router_enabled=False)
        with mock.patch.object(agent_module, "_ollama_chat", legacy):
            self.ask_buffered()
        self.use_settings(llm_router_enabled=True)
        self.guard_legacy_chat_off()
        self.serve(_response(200, json_body=ollama_body(SSE_ANSWER)))
        self.ask_buffered()
        self.assertEqual(legacy_calls[0][0], self.requests[-1].payload["messages"])

    def test_the_stream_leg_has_no_legacy_form_left_to_preserve(self):
        """退役的代价（如实报，不藏）：流式腿在 `LLM_ROUTER_ENABLED=false` 下**也**走路由。

        它的「原实现」就是本任务删掉的 `app/native_stream.py`；把 `/api/chat` +
        `httpx.stream` 内联回业务文件等于开第二条出口（D6 / 矩阵 #19 直接红）。所以
        #18 在这条腿上的对照面是「报文形状」（`test_the_legacy_ndjson_streaming_payload_
        is_reproduced_on_the_wire`），不是「旗标关掉走旧代码」。钉：本文件里没有端点字面量。
        **口径出处 = `docs/MODEL_ROUTER_V23_DESIGN.md` §9.1**（Task 7 评审 I-3 的正式回写；
        同一句「应急旗标不覆盖对话链流式腿」必须进 V2.3 验收文档 ⇒ 代码与文档双向可追）。
        """
        source = (BACKEND_DIR / "app" / "conversation_agent.py").read_text(encoding="utf-8")
        business_file_has_no_second_llm_egress(self, BACKEND_DIR / "app" / "conversation_agent.py")
        self.assertNotIn("ollama_chat_stream", source)
        self.use_settings(llm_router_enabled=False)
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        self.guard_legacy_chat_off()
        result = self.ask_streaming()
        self.assertEqual(SSE_ANSWER, result["answer"])           # 关掉旗标也不至于坏
        self.assertIs(True, result["timings"]["native_stream"])


# --------------------------------------------------------------------------
# 5. 任务书 C 的关键区分：`native_stream` **字段** ≠ `app.native_stream` **模块**
# --------------------------------------------------------------------------
class SseNativeStreamFieldFaceTests(unittest.TestCase):
    """任务书 C 的关键区分：退役的是**模块**，留下的是**字段**。

    三个「出现位置」各自的意义（迁移前后逐枚对齐）：
    * `events[final]["native_stream"]` —— trace 事件面；
    * `timings["native_stream"]` —— 响应/`public_timings` 面（`security.py` 白名单钉着）；
    * `run_conversation_agent` 非快路径那支的字面 `False` —— 走 `agent.run_agent` 的
      buffered 交付也不是逐 token 出口。
    """

    def source(self) -> str:
        """**方法内**读源码（评审 Minor-5）：原来挂在类属性上 ⇒ import 期读一次，
        评审/变异期间文件被换过也不会重读，静态面拿着旧字节自证。"""
        return (BACKEND_DIR / "app" / "conversation_agent.py").read_text(encoding="utf-8")

    def test_the_module_is_gone_and_nothing_imports_it(self):
        self.assertFalse((BACKEND_DIR / "app" / "native_stream.py").exists())
        offenders = []
        for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "") == "native_stream":
                    offenders.append(f"{path.name}:from")
                elif isinstance(node, ast.Import):
                    offenders.extend(f"{path.name}:import {alias.name}" for alias in node.names
                                     if alias.name in ("native_stream", "app.native_stream"))
        self.assertEqual([], offenders, "退役模块后仍有模块级 import ⇒ 启动即 ImportError")
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("app.native_stream")

    def test_the_field_is_still_whitelisted_and_still_reaches_the_response(self):
        """字段面三件事逐枚钉：白名单没动、键名没变、值语义还是「走了逐 token 出口」。"""
        from app.security import PUBLIC_TIMING_KEYS, public_timings

        self.assertIn("native_stream", PUBLIC_TIMING_KEYS)
        self.assertEqual({"native_stream": True},
                         public_timings({"native_stream": True, "evil": "x"}))
        self.assertEqual({"native_stream": False}, public_timings({"native_stream": False}))
        # 值域只有真假两枚（行为面在 `SseStreamContractTests` / `SseBufferedAndLegacyTests`
        # 各自钉过：流式腿 True、buffered 腿 False、非快路径 False）。
        source = self.source()
        self.assertNotIn('"native_stream": "', source)
        self.assertIn('"native_stream": native_stream', source)
        self.assertIn('"native_stream": False', source)

    def test_the_field_appears_exactly_at_the_three_pre_migration_sites(self):
        """响应字段在源码里的**出现位置**逐枚点数（迁移不该顺手多打一处、也不能少一处）。"""
        source = self.source()
        self.assertEqual(3, source.count('"native_stream":'),
                         "events / timings / 非快路径三支，一支都不能变")
        self.assertEqual(1, source.count("native_stream = True"),
                         "唯一置真的地方仍然是「真的走了流式出口」那一支")
        self.assertEqual(1, source.count("native_stream = False"))

    def test_no_streaming_module_or_endpoint_returned_to_the_business_layer(self):
        """D6：字段留着，但**出口**一个都不许多——业务文件里没有 httpx、没有端点字面量。"""
        business_file_has_no_second_llm_egress(self, BACKEND_DIR / "app" /
                                               "conversation_agent.py")


# --------------------------------------------------------------------------
# 6. D5 的 SSE 出口：现行事件词汇 + payload 增量（路由级）
# --------------------------------------------------------------------------
class SseRoutePayloadTests(_SseMigrationFixture):
    #: 迁移前后都允许的 SSE 事件名（D5：不新增事件类型 ⇒ 这个集合不许变大）。
    KNOWN_SSE_EVENTS = frozenset({"status", "message", "token", "trace", "sources",
                                  "done", "error", "heartbeat"})

    def test_post_commit_interruption_emits_error_then_done_with_two_new_payload_keys(self):
        """#11 的对外半段：事件名只有 `error` + `done`（现行词汇表），payload 多两枚键。"""
        def agent(**kwargs):
            kwargs["token_sink"](SSE_PARTS[0])                    # 已经交付过一个字
            raise StreamInterrupted(SSE_PARTS[0], (), 0,
                                    error=LLMError("retryable", 200, "提前结束"))

        frames, store = self.drive_route(agent)
        names = [name for name, _ in frames]
        self.assertEqual(set(), set(names) - self.KNOWN_SSE_EVENTS,
                         "D5：事件词汇表不许扩，只能加 payload 字段")
        self.assertEqual(["error", "done"], [n for n in names if n in ("error", "done")])
        self.assertLess(names.index("token"), names.index("error"))
        error = next(p for n, p in frames if n == "error")
        self.assertEqual({"detail", "status", "stream_committed", "error_type"}, set(error))
        self.assertIs(True, error["stream_committed"])
        self.assertEqual("retryable", error["error_type"])         # provider 的原始归类
        self.assertEqual(503, error["status"])
        done = next(p for n, p in frames if n == "done")
        self.assertIs(True, done["stream_committed"])
        self.assertEqual("failed", done["status"])
        self.assertEqual(1, len(store.calls))
        self.assertEqual("failed", store.calls[0]["status"])       # 会话面仍是失败行
        self.assertNotIn(SSE_PARTS[1], "".join(
            p.get("text", "") for n, p in frames if n == "token"))  # 没重播、也没补写

    def test_a_real_truncated_upstream_lands_error_plus_done_on_the_wire(self):
        """**真链版**（不手工造 `StreamInterrupted`）：上游断流 → 执行器不换模型 →
        `conversation_agent` 记账落 trace → 路由出 `error` + `done` + `stream_committed`。

        这一枚是 #11 的端到端形状：桩只打在 HTTP 传输层（`terminate=False` 的 NDJSON），
        其余全是真代码，所以「post-commit 不切模型」在事件面上也留了证据。
        """
        second = rag_entry(id="ollama-phi3", model="phi3:mini",
                           priority={"chat": 80, "rag": 80, "tools": 0})
        self.use_registry(rag_entry(), second)
        self.serve(_response(200, content=sse_stream_body(SSE_PARTS[0], terminate=False)))
        real_ask = self.ask_streaming

        def agent(**kwargs):
            return real_ask(token_sink=kwargs["token_sink"])

        frames, store = self.drive_route(agent)
        names = [name for name, _ in frames]
        self.assertEqual(["error", "done"], [n for n in names if n in ("error", "done")])
        error = next(p for n, p in frames if n == "error")
        self.assertIs(True, error["stream_committed"])
        self.assertEqual("retryable", error["error_type"])
        self.assertEqual([SSE_PARTS[0]], [p["text"] for n, p in frames if n == "token"])
        self.assertEqual([RAG_LOCAL_MODEL], self.requested_models())   # 第二条候选没被试
        self.assertEqual(0, self.raw_rows()[0]["success"])
        self.assertEqual("failed", store.calls[0]["status"])

    def test_a_pre_commit_failure_keeps_the_existing_error_shape_untouched(self):
        """additive-only：没有交付事实 ⇒ 现有 `error` payload **一字节不变**（只有两枚键）。"""
        def agent(**kwargs):
            raise RuntimeError("连接失败")

        frames, store = self.drive_route(agent)
        names = [name for name, _ in frames]
        error = next(p for n, p in frames if n == "error")
        self.assertEqual({"detail", "status"}, set(error))
        self.assertNotIn("stream_committed", error)
        self.assertNotIn("done", names)                            # 现行为：只有 error
        self.assertEqual("failed", store.calls[0]["status"])

    def test_the_success_event_order_is_unchanged(self):
        """既有 SSE 序（status/message/token/trace/sources/done）逐位不变，也不带新字段。"""
        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        real_ask = self.ask_streaming

        def agent(**kwargs):
            return real_ask(token_sink=kwargs["token_sink"])

        with mock.patch.object(stream_routes_module, "_success_payload",
                               lambda **kwargs: {"message_id": "m-1", "status": "completed"}):
            frames, store = self.drive_route(agent)
        names = [name for name, _ in frames]
        self.assertEqual(["status", "message", "status", "status", "token", "token",
                          "trace", "sources", "done"], names)
        for _name, payload in frames:
            self.assertNotIn("stream_committed", payload)
        self.assertEqual(SSE_PARTS, [p["text"] for n, p in frames if n == "token"])
        self.assertEqual("completed", store.calls[0]["status"])
        self.assertEqual(SSE_ANSWER, store.calls[0]["content"])

    def test_the_second_sse_egress_lands_the_same_d5_face_and_keeps_its_success_order(self):
        """评审 I-4：D5 的 payload 增量过去**只落在主对话 SSE** 那一支出口上。

        `/api/agent/query/stream` 传的是同一个 `token_sink` ⇒ 同一条流式腿、同一种
        post-commit 中断，过去却把 `StreamInterrupted` 吞进 generic `except Exception`
        （error-only、无 `done`、无 `stream_committed`）。修法 = 在 generic 分支**之前**加一支
        同名分支（`agent_routes.py`，与 `conversation_stream_routes.py` 同形）。这里钉三件事：
        ① 成功序逐位不变、且一帧都不带新字段（additive-only 的边界）；
        ② 中断时事件名仍只有 `error` + `done`，payload 键集合与另一支出口**逐字相等**；
        ③ 这一支是**真链可达**的（不手工造异常、让上游真断流也走同一形状）。
        """
        # 本端点自己的现行词汇表多一枚 `start`（首帧，迁移前就在）⇒ 事件集合不许**再**变大。
        agent_events = self.KNOWN_SSE_EVENTS | {"start"}

        def interrupting(**kwargs):
            kwargs["token_sink"](SSE_PARTS[0])                    # 已经交付过一个字
            raise StreamInterrupted(SSE_PARTS[0], (), 0,
                                    error=LLMError("retryable", 200, "提前结束"))

        self.serve(_response(200, content=sse_stream_body(*SSE_PARTS)))
        real_ask = self.ask_streaming

        def succeeding(**kwargs):
            return real_ask(token_sink=kwargs["token_sink"])

        ok_frames = self.drive_agent_route(succeeding)
        self.assertEqual(["start", "status", "status", "status", "token", "token",
                          "trace", "sources", "done"], [name for name, _ in ok_frames],
                         "第二条出口的既有 SSE 序一位都不许动")
        for _name, payload in ok_frames:
            self.assertNotIn("stream_committed", payload)

        frames = self.drive_agent_route(interrupting)
        names = [name for name, _ in frames]
        self.assertEqual(set(), set(names) - agent_events,
                         "D5：这条出口的事件词汇表也不许扩")
        self.assertEqual(["error", "done"], [n for n in names if n in ("error", "done")])
        self.assertLess(names.index("token"), names.index("error"))
        error = next(p for n, p in frames if n == "error")
        done = next(p for n, p in frames if n == "done")
        self.assertEqual({"detail", "status", "stream_committed", "error_type"}, set(error))
        self.assertIs(True, error["stream_committed"])
        self.assertEqual("retryable", error["error_type"])
        self.assertEqual(503, error["status"])
        self.assertIs(True, done["stream_committed"])
        self.assertEqual("retryable", done["error_type"])
        self.assertEqual("failed", done["status"])
        # **两支出口同形**（这条才是 I-4 的收口证据）：`error` 的键集合逐字相等。
        other, _store = self.drive_route(interrupting)
        self.assertEqual(set(next(p for n, p in other if n == "error")), set(error),
                         "两条 SSE 出口的 D5 payload 不对称 ⇒ 又只剩一支收口了")

        self.serve(_response(200, content=sse_stream_body(SSE_PARTS[0], terminate=False)))
        real = self.drive_agent_route(succeeding)
        real_names = [name for name, _ in real]
        self.assertEqual(["error", "done"], [n for n in real_names if n in ("error", "done")],
                         "真上游断流没走新分支 ⇒ 那一支是死代码")
        self.assertIs(True, next(p for n, p in real if n == "error")["stream_committed"])
        self.assertEqual(0, self.raw_rows()[-1]["success"])


# ==========================================================================
# Task 8：Agent 工具回路迁移（DESIGN §9 第三条）
#         矩阵 #12/#13（两侧 tool_calls → `ToolCall` 标准化，agent 侧只认内部模型）、
#         #17（agent 链**有** trace：真调用 + 真落盘九键 + `NO_CAPABLE_MODEL→fast_path`）、
#         #18（`LLM_ROUTER_ENABLED=false` 的原 httpx 报文逐字保留）、D2（零候选降级不 500）。
#
# 五条纪律（沿用 T6/T7，再加三枚本任务特有的）：
# 1. **真链到底**：router 腿走真 `llm.complete → classify → plan → run_complete →
#    provider → normalize` + `httpx.MockTransport`（注入点在 provider **下方**）；桩只打在
#    业务**外围**（工具执行 / 审计 / trace 落盘 / 知识范围解析）。
# 2. **零真实外呼**：本机 11434 上加载着 phi3:mini，打一次就是硬违规（真实 failover 归 T10）。
# 3. **逐轮开关**：`think`/`num_predict` 的 tool_routing vs synthesis 两套 settings 必须按
#    调用点原值到达报文，两种轮次各自有钉。
# 4. **温度两钉**（T7 的 M3b 教训）：只钉报文值挡不住漏参——`llm.complete` 的形参默认与
#    `LLMRequest.temperature` 的字段默认**都是 0.2**，所以两轮两腿各套一层 kwargs spy。
# 5. **D2 是常驻分支**（T3 移交）：出厂注册表 + 无云 key 下 `mode="agent"` 必然零候选
#    （本地两条 `tools=false` 且 `tools` 档 priority=0），于是 agent 工具链今天**每一次**
#    提问都走 fast path。本组把这条事实钉在用例里，而不是靠注释声明。
# ==========================================================================

#: 工具轮回执里 provider 侧给回的参数**字符串**（OpenAI 协议恒为字符串、老版 Ollama 也是）：
#: §6 的标准化义务就是把它收敛成 dict，所以这枚字面量是 C 组的核心事实。
AGENT_TOOL_ARGS_JSON = '{"query": "差旅住宿上限是多少"}'
AGENT_TOOL_QUERY = "差旅住宿上限是多少"
#: 独立写死的本链现网温度（测试侧不 import 产品常量 ⇒「改常量」与「改报文」分别红）。
AGENT_LEGACY_TEMPERATURE_ON_THE_WIRE = 0.2
#: agent 链 `agent.py::AGENT_LEGACY_TEMPERATURE` **不许**吃 rag 链的 0.1（DESIGN §9.1 第二段）。
RAG_CHAIN_TEMPERATURE = llm.RAG_LEGACY_TEMPERATURE


def agent_entry(**overrides) -> ModelDefinition:
    """agent 链用例的条目底座：一条**支持 tools** 的本地 ollama 候选（免云 key 即可路由）。

    `provider="ollama"` 是刻意的：换成 openai 兼容腿就得为它造凭据 env，而本组测的是
    「agent 链怎么消费 `LLMResponse.tool_calls`」，不是凭据解析（那归 T1/T2）。
    """
    data = {
        "id": "ollama-agent-test", "provider": "ollama", "model": RAG_LOCAL_MODEL,
        "enabled": True, "external": False,
        "capabilities": {"chat": True, "rag": True, "tools": True, "stream": True,
                         "reasoning": False},
        "priority": {"chat": 100, "rag": 100, "tools": 100},
        "limits": {"context_tokens": 8192, "max_output_tokens": 2048},
        "pricing": {"input_per_1m": 0.0, "output_per_1m": 0.0, "currency": "USD"},
    }
    data.update(overrides)
    return ModelDefinition.model_validate(data)


def ollama_tool_body(tool: str = "enterprise_search", arguments: Any = AGENT_TOOL_ARGS_JSON,
                     content: str = "", model: str = RAG_LOCAL_MODEL,
                     call_id: str = "call-1") -> dict:
    """一次**工具决策**回合的 Ollama 回执（`arguments` 默认是 JSON 字符串）。"""
    return {"model": model,
            "message": {"role": "assistant", "content": content, "tool_calls": [
                {"id": call_id, "type": "function",
                 "function": {"name": tool, "arguments": arguments}}]},
            "done": True, "done_reason": "tool_calls",
            "prompt_eval_count": 11, "eval_count": 5}


class _RecordingToolExecutor:
    """`tool_registry.execute` 的记录替身（**只替 execute**，schemas 仍走真注册表）。

    刻意不整块替换 `tool_registry`：那样 `tool_registry.schemas(mode)` 就拿不到真 schema，
    「工具轮到底把几枚、哪几枚工具发出去了」这条报文事实就没人钉了。
    """

    def __init__(self, *, evidence: list[dict] | None = None,
                 timings: dict | None = None, status: str = "SUCCESS",
                 sleep_ms: float = 0.0) -> None:
        self.evidence = ([dict(row) for row in ENTERPRISE_ROWS] if evidence is None
                         else [dict(row) for row in evidence])
        # 带上判定层读数：`run_agent` 的 `trace["timings"]` / `response["timings"]` 只在
        # `public_typesafe_metrics()` 非空时才出现（既有口径，见 SSE_TYPESAFE_TIMINGS 的注释），
        # 而 C/E 组要按**等式**钉那两枚键集合。
        self.timings = dict(timings or {"vector_ms": 12.0, "rerank_ms": 40.0,
                                        **SSE_TYPESAFE_TIMINGS})
        #: I-3：`status != "SUCCESS"` 时按 `tool_registry` 的真形状**抛** `ToolExecutionError`
        #: （`enterprise_search` 的 DENIED/FAILED 就是这么出场的），而不是返回一个错误 dict。
        self.status = status
        #: I-2：`sleep_ms` 是**真实**推进量（手法照 `_StubToolRegistry`）——降级腿的
        #: `tool_time` 与 `llm_ms` 归因要能比大小，就必须有一段真的时间在工具里流过。
        self.sleep_ms = float(sleep_ms)
        self.calls: list[tuple[str, dict, Any]] = []

    @property
    def names(self) -> list[str]:
        return [name for name, _args, _context in self.calls]

    def last_arguments(self) -> dict:
        return dict(self.calls[-1][1]) if self.calls else {}

    def execute(self, name: str, arguments: dict, context) -> dict:
        self.calls.append((name, dict(arguments), context))
        if self.status != "SUCCESS":
            from app.tools.base import ToolExecutionError
            raise ToolExecutionError("stub 检索失败", status=self.status)
        if self.sleep_ms:
            time.sleep(self.sleep_ms / 1000.0)                   # 单调钟下的真实一段
        return {"ok": True, "tool": name, "status": "SUCCESS",
                "evidence": [dict(row) for row in self.evidence],
                "timings": dict(self.timings)}


class _AgentMigrationFixture(_RagMigrationFixture):
    """Task 8 底座：T6 的真出口 + 真 trace/审计改道 + agent 链的业务外围替身。"""

    AGENT_SETTINGS_DEFAULTS: dict = {
        "agent_max_tool_rounds": 3,
        "agent_history_max_messages": 8,
        "agent_local_fast_path": True,
        "agent_think_tool_routing": True,
        "agent_think_synthesis": False,
        "agent_num_predict_tool_routing": 768,
        "agent_num_predict_synthesis": 512,
    }

    def setUp(self) -> None:
        super().setUp()                                     # 内含 use_settings
        self.use_registry(agent_entry())
        self.healthy_providers()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        # trace / 审计两条文件出口都改道：`backend/data/agent_traces.jsonl` 与
        # `audit.jsonl` 是真实观测面，一行都不许进。
        self.trace_path = root / "agent_traces.jsonl"
        self.audit_path = root / "audit.jsonl"
        self.tools = _RecordingToolExecutor()
        for target, attribute, value in (
                (agent_trace_module, "TRACE_PATH", self.trace_path),
                (audit_module, "AUDIT_PATH", self.audit_path),
                (agent_module, "settings", self.settings),
                (agent_module, "allowed_for", lambda user: ["kb-1"]),
                (agent_module, "effective_allowed_from_grant", lambda grant: None),
                (agent_module, "visible_bases_by_ids",
                 lambda ids: [{"id": "kb-1", "name": "公共制度"}]),
                (agent_module.tool_registry, "execute", self.tools.execute)):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def use_settings(self, **overrides) -> Settings:
        base = dict(self.AGENT_SETTINGS_DEFAULTS)
        base.update(overrides)
        return super().use_settings(**base)

    # --- 驱动 -------------------------------------------------------------
    @staticmethod
    def user() -> CurrentUser:
        return CurrentUser(username="agent-alice", display_name="Agent Alice", role="ADMIN")

    def ask(self, *, question: str = PLAIN_QUESTION, mode: str = "auto",
            history: list[dict] | None = None, **kwargs) -> dict:
        return agent_module.run_agent(
            question=question, user=self.user(), mode=mode,
            knowledge_base_id="kb-1", top_k=3, rerank=False,
            history=[] if history is None else history, **kwargs)

    def call_http_face(self, *, mode: str = "auto", question: str = PLAIN_QUESTION) -> Any:
        """真走 `/api/agent/query` 的端点函数（不起 HTTP、不过鉴权）。"""
        request = agent_routes_module.AgentQueryRequest(question=question, mode=mode)
        with mock.patch.object(agent_routes_module, "_validate_knowledge_base_scope",
                               lambda *args, **kwargs: None):
            return agent_routes_module.agent_query(request, user=self.user())

    # --- 观测面直读 -------------------------------------------------------
    def trace_rows(self) -> list[dict]:
        if not self.trace_path.exists():
            return []
        return [json.loads(line) for line in
                self.trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def audit_rows(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in
                self.audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def spy_complete(self) -> list[dict]:
        """包一层**真** `llm.complete`，把每次调用的 kwargs 录下来（调用面钉子的载体）。

        为什么要它：`llm.complete(temperature=0.2)` 的形参默认与 `LLMRequest.temperature`
        的字段默认都是 0.2 ⇒ 漏传参数在报文面**完全不可见**（T7 的 M3b 就是这么存活的）。
        """
        seen: list[dict] = []
        real = llm.complete

        def probe(messages, **kwargs):
            seen.append(dict(kwargs))
            return real(messages, **kwargs)

        patcher = mock.patch.object(llm, "complete", probe)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def use_shipped_registry(self) -> Registry:
        """装**出厂**注册表（真文件 + 无云 key）——D2 常驻分支的事实来源。

        `_EgressFixture.use_settings` 已把 `registry.settings` 打到 `openai_api_key=""`
        且清空 OS env，所以 `load_registry` 里的「external ∧ 无 key ⇒ enabled=False」
        判定与生产一致（不是测试自己 Stub 出来的世界）。
        """
        registry = load_registry(str(SHIPPED_REGISTRY))
        for module in (llm, usage_module):
            patcher = mock.patch.object(module, "get_registry", lambda: registry)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.shipped_registry = registry
        return registry

    def guard_legacy_egress_off(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("router 路上不得再走 legacy 的 httpx.post（那是第二条出口）")
        patcher = mock.patch.object(agent_module.httpx, "post", forbidden)
        patcher.start()
        self.addCleanup(patcher.stop)

    def spy_legacy_post(self, body: dict) -> list[dict]:
        """legacy 腿的 `httpx.post` 替身：把**请求体**整份录下来，供逐键对照。"""
        calls: list[dict] = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **{k: v for k, v in kwargs.items() if k != "json"},
                          "json": kwargs.get("json")})
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

        patcher = mock.patch.object(agent_module.httpx, "post", fake_post)
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    # --- 共用断言 ---------------------------------------------------------
    def assert_temperature(self, kwargs: dict, *, mode: str) -> None:
        """调用面：`temperature` 必须**显式**出现在 kwargs 里，且是本链的 0.2。"""
        self.assertIn("temperature", kwargs,
                      f"mode={mode} 腿漏传 temperature= ⇒ 退化成包/字段默认的巧合")
        self.assertEqual(AGENT_LEGACY_TEMPERATURE_ON_THE_WIRE, kwargs["temperature"])
        self.assertNotEqual(RAG_CHAIN_TEMPERATURE, kwargs["temperature"],
                            "0.1 属于 app/rag.py 那条链（DESIGN §9.1）")
        self.assertEqual(agent_module.AGENT_LEGACY_TEMPERATURE, kwargs["temperature"])

    def assert_wire_temperature(self, payload: dict) -> None:
        """报文面：`options.temperature` 三枚等式（产品常量 / 独立写死 / != 0.1）。"""
        self.assertEqual(AGENT_LEGACY_TEMPERATURE_ON_THE_WIRE, payload["options"]["temperature"])
        self.assertEqual(agent_module.AGENT_LEGACY_TEMPERATURE, payload["options"]["temperature"])
        self.assertNotEqual(RAG_CHAIN_TEMPERATURE, payload["options"]["temperature"])

    def assert_nine_keys(self, route: dict) -> None:
        self.assertEqual(set(MODEL_ROUTE_NINE_KEYS), set(route))
        self.assertEqual(9, len(route))
        self.assertEqual({"complexity", "needs_tools", "needs_stream", "needs_reasoning"},
                         set(route["requirements"]))
        self.assertEqual({"id", "provider", "model", "score", "reason_codes"},
                         set(route["primary"]))
        self.assertTrue(route["attempts"], "attempts 非空：这是一条真跑过一次的链")


# --------------------------------------------------------------------------
# A. 迁移面：`_ollama_chat` 走 `llm.complete(mode="agent", needs_tools=bool(tools))`
# --------------------------------------------------------------------------
class AgentRouterMigrationTests(_AgentMigrationFixture):
    def test_the_tool_turn_goes_through_the_router_in_agent_mode(self):
        self.guard_legacy_egress_off()
        seen = self.spy_complete()
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        result = self.ask()

        self.assertEqual(ROUTER_ANSWER, result["answer"])
        self.assertEqual(2, len(seen), "两轮：工具决策轮 + 第二轮（模型这轮不再要工具）")
        first, second = seen
        self.assertEqual("agent", first["mode"])
        self.assertEqual("agent", first["profile"].mode)
        self.assertIs(True, first["profile"].needs_tools, "needs_tools=bool(tools) 写死即红")
        # 循环里**每一轮**都带着 schema 问模型（`_ollama_chat(messages, schemas)`），所以
        # 第二轮同样是 needs_tools=True —— 真正不带工具的那次只出现在「工具轮次耗尽」的
        # 收尾腿（`AgentToolsFreeSynthesisTests`）与 legacy 的对话链 buffered 腿。
        self.assertIs(True, second["profile"].needs_tools)
        self.assertEqual("agent", second["profile"].mode)
        # 报文面：工具 schema 真的带出去了（auto 档 = enterprise_search + web_search）。
        self.assertEqual(2, len(self.requests))
        self.assertEqual({"enterprise_search", "web_search"}, self.schema_names(self.requests[0]))
        self.assertEqual({"enterprise_search", "web_search"}, self.schema_names(self.requests[1]))
        self.assertEqual(["enterprise_search"], self.tools.names)
        self.assertEqual(["kb-1"], [str(context.selected_knowledge_base_id)
                                    for _n, _a, context in self.tools.calls])

    @staticmethod
    def schema_names(record: Recorded) -> set[str]:
        names = set()
        for item in record.payload["tools"]:
            function = item.get("function") if isinstance(item, dict) else None
            names.add(str((function or item).get("name") or ""))
        return {name for name in names if name}

    def test_local_mode_sends_only_the_enterprise_schema(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask(mode="local")
        self.assertEqual({"enterprise_search"}, self.schema_names(self.requests[0]))

    def test_the_answer_shape_is_the_current_dict_shape(self):
        """`_ollama_chat` 对外**仍然**只交回 message dict（循环体零改的 pre-flight 冻结）。"""
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        message = agent_module._ollama_chat([{"role": "user", "content": "hi"}], [])
        self.assertIsInstance(message, dict)
        self.assertEqual({"role", "content", "tool_calls"}, set(message))
        self.assertEqual(ROUTER_ANSWER, message["content"])
        self.assertEqual([], message["tool_calls"])

    def test_trace_carries_route_and_the_response_face_is_additive_only(self):
        """响应**键集合**逐项相等（§9「既有响应结构对外不变」）；model_used 来自 selected。"""
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        result = self.ask()
        self.assertEqual({
            "answer", "query", "mode", "trace_id", "sources", "num_sources", "model_used",
            "max_tool_rounds", "context_messages", "timings",
        }, set(result))
        self.assertEqual(RAG_LOCAL_MODEL, result["model_used"])   # selected 的生效模型名
        self.assertEqual(result["model_used"], self.raw_rows()[-1]["model"])
        trace = self.trace_rows()[0]
        self.assertEqual({
            "trace_id", "timestamp", "username", "role", "mode", "model", "max_tool_rounds",
            "context_messages", "events", "evidence_count", "elapsed_ms", "timings",
            MODEL_ROUTE_KEY,
        }, set(trace))


# --------------------------------------------------------------------------
# B. 温度与逐轮开关（任务书 A + B；T7 移交的「调用面 kwargs 等式」）
# --------------------------------------------------------------------------
class AgentTemperatureEquivalenceTests(_AgentMigrationFixture):
    def test_tool_turn_temperature_is_on_both_faces(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        seen = self.spy_complete()
        self.ask()
        self.assert_temperature(seen[0], mode="agent")
        self.assert_wire_temperature(self.requests[0].payload)

    def test_tools_free_synthesis_leg_temperature_is_on_both_faces(self):
        """**不带工具 schema 的那一次**（工具轮次耗尽的收尾腿）是另一条腿：单独钉。"""
        self.settings.agent_max_tool_rounds = 1
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        seen = self.spy_complete()
        self.ask()
        self.assertEqual(2, len(seen))
        self.assert_temperature(seen[1], mode="agent")
        self.assertIs(False, seen[1]["profile"].needs_tools)
        self.assertEqual([], self.requests[1].payload["tools"])
        self.assert_wire_temperature(self.requests[1].payload)

    def test_degraded_synthesis_leg_temperature_is_on_both_faces(self):
        """D2 降级腿（`mode="rag"`）的第三枚调用面：同值 0.2，但它是**另一次** kwargs 构造。"""
        self.use_shipped_registry()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        seen = self.spy_complete()
        self.ask()
        rag_legs = [kwargs for kwargs in seen if kwargs["profile"].mode == "rag"]
        self.assertEqual(1, len(rag_legs), seen and [k["profile"].mode for k in seen])
        self.assert_temperature(rag_legs[0], mode="rag")
        self.assert_wire_temperature(self.requests[-1].payload)

    def test_the_package_defaults_still_say_two_so_the_kwargs_spy_is_load_bearing(self):
        """反证：值面**挡不住**漏参（形参默认与字段默认都是 0.2）⇒ spy 才是那枚钉子。"""
        self.assertEqual(0.2, LLMRequest(messages=[]).temperature)
        self.assertEqual(0.2, inspect.signature(llm.complete).parameters["temperature"].default)
        self.assertEqual(0.1, RAG_CHAIN_TEMPERATURE)
        self.assertEqual(0.2, agent_module.AGENT_LEGACY_TEMPERATURE)

    def test_router_and_legacy_payloads_agree_key_by_key(self):
        """#18 的报文等价：两条腿同一次问话的 `options` 与键形状逐字对，偏差只允许被枚举。"""
        # 先取 legacy 面的基准（旗标关掉 ⇒ 原 httpx 报文），再取 router 面。
        self.settings.llm_router_enabled = False
        legacy_calls = self.spy_legacy_post(ollama_body(ROUTER_ANSWER))
        agent_module._ollama_chat([{"role": "user", "content": PLAIN_QUESTION}], [])
        legacy = legacy_calls[-1]["json"]
        self.settings.llm_router_enabled = True
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        agent_module._ollama_chat([{"role": "user", "content": PLAIN_QUESTION}], [])
        routed = self.requests[-1].payload
        self.assertEqual(set(legacy), set(routed), "键集合必须同形（含空 tools 也带键）")
        self.assertEqual(legacy["options"], routed["options"])
        self.assertEqual(legacy["think"], routed["think"])
        self.assertEqual(legacy["keep_alive"], routed["keep_alive"])
        self.assertIs(False, routed["stream"])
        self.assertEqual(OLLAMA_CHAT_URL, legacy_calls[-1]["url"])


class AgentPerTurnSwitchTests(_AgentMigrationFixture):
    def test_tool_routing_turn_uses_the_reasoning_and_large_num_predict_settings(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        seen = self.spy_complete()
        self.ask()
        first = seen[0]
        self.assertIs(True, bool(first["think"]))
        self.assertEqual(768, int(first["num_predict"]))
        self.assertIs(True, self.requests[0].payload["think"])
        self.assertEqual(768, self.requests[0].payload["options"]["num_predict"])
        self.assertEqual(self.settings.ollama_keep_alive, first["keep_alive"])
        # m-8：工具轮的 `keep_alive` 补一枚**绝对值面**钉（照 RAG/SSE 组同法）。只有
        # 「kwargs == settings」那一枚的话，`settings` 自己被改错值时这一例仍会绿。
        self.assertEqual("30m", self.requests[0].payload["keep_alive"])
        self.assertEqual("30m", first["keep_alive"])

    def test_tools_free_synthesis_turn_switches_to_fast_bounded_and_think_off(self):
        """`agent_think_synthesis` / `agent_num_predict_synthesis` 的唯一消费点在这里。"""
        self.settings.agent_max_tool_rounds = 1
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        seen = self.spy_complete()
        self.ask()
        second = seen[1]
        self.assertIs(False, bool(second["think"]))
        self.assertEqual(512, int(second["num_predict"]))
        self.assertIs(False, self.requests[1].payload["think"])
        self.assertEqual(512, self.requests[1].payload["options"]["num_predict"])

    def test_the_switch_follows_settings_not_a_hardcoded_pair(self):
        """换 settings 值 ⇒ 报文跟着变（两侧都跟着才叫「按调用点原值透传」）。"""
        self.settings.agent_max_tool_rounds = 1
        self.settings.agent_think_tool_routing = False
        self.settings.agent_num_predict_tool_routing = 128
        self.settings.agent_think_synthesis = True
        self.settings.agent_num_predict_synthesis = 1024
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        self.assertIs(False, self.requests[0].payload["think"])
        self.assertEqual(128, self.requests[0].payload["options"]["num_predict"])
        self.assertIs(True, self.requests[1].payload["think"])
        self.assertEqual(1024, self.requests[1].payload["options"]["num_predict"])


# --------------------------------------------------------------------------
# C. tool_calls 标准化（矩阵 #12/#13 的 agent 半边）+ `_tool_arguments` 的存留理由
# --------------------------------------------------------------------------
class AgentToolCallStandardisationTests(_AgentMigrationFixture):
    def test_string_arguments_reach_the_tool_as_a_dict(self):
        """provider 给字符串 ⇒ normalize 收成 dict ⇒ 工具吃到 dict（回填不是再解析）。"""
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        self.assertEqual([("enterprise_search", {"query": AGENT_TOOL_QUERY})],
                         [(name, args) for name, args, _ctx in self.tools.calls])
        # 工具回执进了第二轮的 messages（`role="tool"`），且引用编号已经发过。
        tool_rows = [m for m in self.requests[1].payload["messages"]
                     if m.get("role") == "tool"]
        self.assertEqual(1, len(tool_rows))
        self.assertEqual("enterprise_search", tool_rows[0]["tool_name"])
        self.assertIn('"citation_index": 1', tool_rows[0]["content"])

    def test_the_echoed_assistant_message_carries_the_standardised_shape(self):
        """第二轮请求里回放的 assistant 消息：`arguments` 已是 dict、`id` 逐条带回。"""
        self.serve_sequence(_response(200, json_body=ollama_tool_body(call_id="call-42")),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        echoed = [m for m in self.requests[1].payload["messages"]
                  if isinstance(m.get("tool_calls"), list) and m["tool_calls"]]
        self.assertEqual(1, len(echoed))
        call = echoed[0]["tool_calls"][0]
        self.assertEqual("call-42", call["id"])
        self.assertEqual({"name": "enterprise_search", "arguments": {"query": AGENT_TOOL_QUERY}},
                         call["function"])
        self.assertIsInstance(call["function"]["arguments"], dict)

    def test_message_from_response_reads_only_the_standardised_tool_calls(self):
        """`_message_from_response` 的唯一输入是 `LLMResponse.tool_calls`（`ToolCall` 对象）。

        这就是「退回手写路径」那条变异的落点：原始 provider JSON 在 `FallbackResult` 里
        **根本不存在**（`LLMResponse` 没有 raw/message 字段），所以任何从原始 dict 取
        tool_calls 的写法都拿不到东西 ⇒ 本例直接红。
        """
        response = LLMResponse(content="", provider="ollama", model=RAG_LOCAL_MODEL,
                               tool_calls=(ToolCall(id="c1", name="web_search",
                                                    arguments={"query": "x"}),))
        message = agent_module._message_from_response(response)
        self.assertEqual([{"id": "c1", "type": "function",
                           "function": {"name": "web_search", "arguments": {"query": "x"}}}],
                         message["tool_calls"])
        self.assertEqual("assistant", message["role"])

    def test_tool_arguments_reader_serves_both_live_shapes(self):
        """`_tool_arguments` 留着的全部理由：legacy 腿交回的是**未标准化**的原始 dict。

        * router 腿：`arguments` 已是 dict（上面两例已钉）；
        * legacy 腿：`arguments` 可能仍是 JSON 字符串，坏 JSON/非对象 ⇒ `{}`（让工具
          自己报缺参，而不是把一次半截 JSON 变成 503）。这一段口径迁移前后逐字未动，
          `app/llm/normalize.py` 的 `_arguments` 注释也还指着它。
        """
        router_shape = {"id": "", "function": {"name": "enterprise_search",
                                               "arguments": {"query": "x"}}}
        legacy_string = {"function": {"name": "enterprise_search",
                                      "arguments": '{"query": "y"}'}}
        legacy_broken = {"function": {"name": "enterprise_search", "arguments": '{"query":'}}
        legacy_not_object = {"function": {"name": "t", "arguments": '["not-a-dict"]'}}
        no_function = {"function": "not-a-dict"}
        self.assertEqual(("enterprise_search", {"query": "x"}),
                         agent_module._tool_arguments(router_shape))
        self.assertEqual(("enterprise_search", {"query": "y"}),
                         agent_module._tool_arguments(legacy_string))
        self.assertEqual(("enterprise_search", {}), agent_module._tool_arguments(legacy_broken))
        self.assertEqual(("t", {}), agent_module._tool_arguments(legacy_not_object))
        self.assertEqual(("", {}), agent_module._tool_arguments(no_function))
        self.assertEqual(("", {}), agent_module._tool_arguments("not-even-a-dict"))

    def test_a_non_list_tool_calls_field_still_degrades_to_no_tools(self):
        """循环体那两行 `or []` + `isinstance(list)` 是既有护栏（#18 语义），不许顺手删。"""
        with mock.patch.object(agent_module, "_ollama_chat",
                               lambda *a, **k: {"content": "答案", "tool_calls": "nope"}):
            result = self.ask()
        self.assertEqual("答案", result["answer"])
        self.assertEqual([], self.tools.names)


def openai_tool_round_body(calls: list[tuple[str, str, dict]], *, content: str = "",
                           model: str = RAG_CLOUD_MODEL) -> dict:
    """一次**工具决策**回合的 OpenAI 回执：协议侧 `arguments` 恒为 **JSON 字符串**。

    与 `ollama_tool_body()` 对称——那一枚默认给 dict（§6 记的两协议差异之一）。
    #12b 要圈的正是整圈：provider 吃进字符串 → normalize 收成 dict → `agent.py` 回填 dict
    → **第二轮回放**时出口再映射回字符串。所以这里按**线上形状**造 body，不按内部形状造。
    """
    return {
        "model": model,
        "choices": [{"index": 0, "finish_reason": "tool_calls",
                     "message": {"role": "assistant", "content": content, "tool_calls": [
                         {"id": call_id, "type": "function",
                          "function": {"name": name,
                                       "arguments": json.dumps(arguments, ensure_ascii=False)}}
                         for call_id, name, arguments in calls]}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 5},
    }


class OpenAIMultiTurnReplayTests(_AgentMigrationFixture):
    """矩阵 #12b：工具轮**第二轮回放**在 OpenAI 腿上必须合协议（Task 8 评审 I-4）。

    评审探针 P8 的实测事实（真 provider + 假 key + MockTransport）：第二轮出口体是
    `{"role":"assistant","content":"","tool_calls":[{...,"function":{"name":"enterprise_search",
    "arguments":{"query":"…"}}}]}` ⇒ ①`arguments` 是 **dict**，OpenAI chat/completions 要求
    **JSON 字符串**；②工具回执是 `{"role":"tool","tool_name":X}`，**缺 `tool_call_id`**。
    真连必得 400（`errors.from_response` 的 non-retryable 档）。Ollama 原生腿吃 dict，不受影响。

    修法授权（DESIGN §6 冻结）：「`OpenAICompat`（`/chat/completions`）与 `OllamaNative`
    （`/api/chat`）**差异全部在此层吸收**」+「两侧 tool_calls → `ToolCall(id,name,arguments
    dict)`；**Agent 只认内部模型**」。⇒ 映射只能坐在 `app/llm/normalize.py::openai_payload`
    的**出口前**：`app/agent.py` 的回放形状、`LLMResponse`/`ToolCall` 都不动（动了就是把
    协议差异漏进业务层，§6 立刻失效）。

    本组全部走**真链**（`run_agent` → `llm.complete` → `fallback` → `provider` →
    MockTransport），审的是第二轮**出口体**，不是对某个 helper 的自说自话。
    """

    CLOUD_KEY = "sk-multi-turn-replay-canary"
    CALL_ID = "call-9"
    #: 非 ASCII 参数值：顺带钉 `json.dumps(..., ensure_ascii=False)`。
    CHINESE_QUERY = "差旅住宿上限是多少"

    def cloud_tool_round(self, calls: list[tuple[str, str, dict]]) -> tuple[Recorded, Recorded]:
        """真跑「云条目 + 工具轮 + 第二轮」，交回两次出口（第二次就是要审的回放报文）。"""
        self.use_settings(openai_api_key=self.CLOUD_KEY)
        self.use_registry(agent_entry(id="openai-replay", provider="openai",
                                      external=True, model=RAG_CLOUD_MODEL))
        self.guard_legacy_egress_off()
        self.serve_sequence(_response(200, json_body=openai_tool_round_body(calls)),
                            _response(200, json_body=openai_body(ROUTER_ANSWER)))
        result = self.ask()
        self.assertEqual(ROUTER_ANSWER, result["answer"], "两轮都走完才有第二轮的出口体")
        self.assertEqual(2, len(self.requests))
        self.assertEqual((OPENAI_CHAT_URL, OPENAI_CHAT_URL),
                         (self.requests[0].url, self.requests[1].url))
        return self.requests[0], self.requests[1]

    def replay_of(self, record: Recorded) -> tuple[dict, list[dict]]:
        """第二轮出口体里的 `(回放的 assistant 消息, 工具回执列表)`。"""
        messages = record.payload["messages"]
        echoed = [m for m in messages
                  if isinstance(m.get("tool_calls"), list) and m["tool_calls"]]
        receipts = [m for m in messages if m.get("role") == "tool"]
        self.assertEqual(1, len(echoed), "一次工具轮 ⇒ 回放的 assistant 消息恰一条")
        self.assertEqual(len(echoed[0]["tool_calls"]), len(receipts),
                         "`run_agent` 给每枚工具调用都回执一条（for call in tool_calls）")
        return echoed[0], receipts

    def test_the_second_round_sends_function_arguments_as_a_json_string(self):
        _first, second = self.cloud_tool_round(
            [(self.CALL_ID, "enterprise_search", {"query": self.CHINESE_QUERY, "top_k": 3})])
        assistant, _receipts = self.replay_of(second)
        call = assistant["tool_calls"][0]
        arguments = call["function"]["arguments"]
        self.assertIsInstance(arguments, str, "§6：内部是 dict，OpenAI 出口必须是 JSON 字符串")
        self.assertEqual({"query": self.CHINESE_QUERY, "top_k": 3}, json.loads(arguments),
                         "往返必须等价：模型第二轮要能还原自己给的参数")
        self.assertIn(self.CHINESE_QUERY, arguments, "ensure_ascii=False ⇒ 中文原样带出去")
        self.assertNotIn("\\u", arguments, "内层再转义一次就是把中文糊成 \\uXXXX")
        self.assertEqual(self.CALL_ID, call["id"], "id 逐条带回：映射不许吞掉配对键")
        self.assertEqual("enterprise_search", call["function"]["name"])
        self.assertEqual("assistant", assistant["role"])
        self.assertEqual("", assistant["content"], "P8 探针里的 content 形状（空串）不动")

    def test_the_second_round_tool_receipt_carries_the_matching_tool_call_id(self):
        _first, second = self.cloud_tool_round(
            [(self.CALL_ID, "enterprise_search", {"query": self.CHINESE_QUERY, "top_k": 3})])
        assistant, receipts = self.replay_of(second)
        receipt = receipts[0]
        self.assertEqual("tool", receipt["role"])
        self.assertEqual(assistant["tool_calls"][0]["id"], receipt["tool_call_id"],
                         "OpenAI 侧唯一的配对键：回执的 id 必须指向它那枚调用")
        self.assertNotIn("tool_name", receipt, "内部字段不外带（协议侧只认 tool_call_id）")
        self.assertEqual(["role", "tool_call_id", "content"], list(receipt))
        self.assertIn('"citation_index": 1', receipt["content"], "回执正文本身一字未动")

    def test_two_calls_with_different_names_in_one_round_pair_by_name(self):
        """同轮两枚**不同名**调用：回执按工具名配到各自的 id，而不是全领第一枚。"""
        _first, second = self.cloud_tool_round([
            ("call-ent", "enterprise_search", {"query": self.CHINESE_QUERY, "top_k": 3}),
            ("call-web", "web_search", {"query": "财政部通知"}),
        ])
        assistant, receipts = self.replay_of(second)
        self.assertEqual(["call-ent", "call-web"], [r["tool_call_id"] for r in receipts])
        self.assertEqual(["enterprise_search", "web_search"],
                         [c["function"]["name"] for c in assistant["tool_calls"]])
        self.assertIn('"tool": "enterprise_search"', receipts[0]["content"])
        self.assertIn('"tool": "web_search"', receipts[1]["content"])

    def test_two_calls_with_the_same_name_in_one_round_pair_in_order(self):
        """同轮两枚**同名**调用：第 N 枚回执配第 N 枚调用（名字同名时按出现次序消费）。"""
        _first, second = self.cloud_tool_round([
            ("call-a", "enterprise_search", {"query": "第一条", "top_k": 3}),
            ("call-b", "enterprise_search", {"query": "第二条", "top_k": 3}),
        ])
        assistant, receipts = self.replay_of(second)
        self.assertEqual(["call-a", "call-b"], [r["tool_call_id"] for r in receipts],
                         "配对规则：同名多调用按 assistant 里的出现次序逐一消费，不许重复领")
        self.assertEqual({"call-a", "call-b"}, {r["tool_call_id"] for r in receipts})
        self.assertEqual(["第一条", "第二条"],
                         [json.loads(c["function"]["arguments"])["query"]
                          for c in assistant["tool_calls"]])

    def test_the_ollama_leg_still_replays_the_dict_arguments(self):
        """两腿差异只在**出口映射**：内部模型只有一份，Ollama 腿继续吃 dict、回执形状不动。"""
        self.serve_sequence(_response(200, json_body=ollama_tool_body(call_id=self.CALL_ID)),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        self.assertEqual(2, len(self.requests))
        self.assertEqual(OLLAMA_CHAT_URL, self.requests[1].url)
        assistant, receipts = self.replay_of(self.requests[1])
        self.assertIsInstance(assistant["tool_calls"][0]["function"]["arguments"], dict,
                              "Ollama 原生腿吃 dict：这里 string 化反而是行为变更")
        self.assertEqual({"query": AGENT_TOOL_QUERY},
                         assistant["tool_calls"][0]["function"]["arguments"])
        self.assertNotIn("tool_call_id", receipts[0],
                         "#18：legacy 的 Ollama 报文形状一字不动")
        self.assertEqual("enterprise_search", receipts[0]["tool_name"])

    def test_the_mapping_prefers_the_matching_tool_name_over_position(self):
        """配对规则的第二条腿：**同名优先**，不是「按位置一律领下一枚」。

        这里刻意造一条 `run_agent` 今天产不出的报文（回执顺序与调用顺序相反）：
        `openai_payload` 是协议适配器，不是「只服务某一种生产者」的手写补丁——将来任何
        按 OpenAI 形状回放的消息都得被它兜住。位置优先的实现在这条报文上会把两枚 id
        配反（段 B 变异 M5 的落点）。
        """
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-w", "type": "function",
                 "function": {"name": "web_search", "arguments": {"query": "外"}}},
                {"id": "call-e", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "内"}}}]},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}"},
            {"role": "tool", "tool_name": "web_search", "content": "{}"},
        ]
        mapped = normalize.openai_payload(request_of(messages=messages),
                                          RAG_CLOUD_MODEL)["messages"]
        self.assertEqual(["call-e", "call-w"], [m["tool_call_id"] for m in mapped[1:]])
        self.assertNotIn("tool_name", mapped[1])

    def test_a_call_without_an_id_is_never_paired(self):
        """`id` 是空串（§6：老版 Ollama 不回 id）⇒ 配不出合法回执 ⇒ **不造假 id**。

        段 B 变异 M8 的落点：把 `_pairable_id` 那行删掉的话，这里会冒出
        `"tool_call_id": ""`——OpenAI 侧照样 400，而且 400 会更难归因（报文看起来「有」
        配对键）。宁可原样交回 `tool_name`，让缺陷留在可观察的地方。
        """
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "甲"}}}]},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}"},
        ]
        mapped = normalize.openai_payload(request_of(messages=messages),
                                          RAG_CLOUD_MODEL)["messages"]
        self.assertNotIn("tool_call_id", mapped[1])
        self.assertEqual("enterprise_search", mapped[1]["tool_name"])
        self.assertIsInstance(mapped[0]["tool_calls"][0]["function"]["arguments"], str,
                              "arguments 的映射与 id 是否可配对无关")

    def test_a_call_with_an_empty_id_does_not_let_a_later_call_steal_its_receipt(self):
        """评审 I-1 的形状：空 id 调用与非空 id 调用**混排** ⇒ 回执只许按槽位消费。

        上一例只有一枚空 id 调用 ⇒ 覆盖不到「跨槽」这一形。这里两枚同名调用
        `id=["", "k2"]` + 两枚按序回执：
        - 第 1 枚回执对应第 1 枚调用（空 id）⇒ **写不出** `tool_call_id`；它如果拿到
          `"k2"` 就是跨槽错配（旧实现把「不可配对」放在槽扫描入口，正是这个后果：
          `rev9_probes.py` P10 修复前打出 `['k2', None]`）；
        - 空 id 那枚槽**照样被消费掉** ⇒ 第 2 枚回执配第 2 枚调用（`"k2"`），次序规则
          （docstring 第 3 条「第 N 枚回执配第 N 枚调用」）不因前一枚写不出而整体失效；
          不占槽的写法（评审点名的「下一枚回执退回来重复领」）会把第 2 枚也变成孤儿，
          那同样是错——所以这里两枚回执的落点都逐字钉住。
        - 回放里的 `id=""` 原样带出，不填造、不删除。
        """
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "甲"}}},
                {"id": "k2", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "乙"}}}]},
            {"role": "tool", "tool_name": "enterprise_search", "content": "first"},
            {"role": "tool", "tool_name": "enterprise_search", "content": "second"},
        ]
        baseline = json.loads(json.dumps(messages, ensure_ascii=False))
        req = request_of(messages=messages)
        mapped = normalize.openai_payload(req, RAG_CLOUD_MODEL)["messages"]
        self.assertEqual(["", "k2"], [c["id"] for c in mapped[0]["tool_calls"]],
                         "空 id 原样留在回放里：不许填造、不许吞掉")
        self.assertNotIn("tool_call_id", mapped[1],
                         "第 1 枚回执对应的调用没有 id ⇒ 写不出配对键；领到 k2 就是跨槽错配")
        self.assertEqual("enterprise_search", mapped[1]["tool_name"], "缺陷留在可观察处")
        self.assertEqual("k2", mapped[2]["tool_call_id"],
                         "第 2 枚槽没被前一枚跳过 ⇒ 正常配对（不占槽的写法这里会掉成孤儿）")
        self.assertNotIn("tool_name", mapped[2])
        self.assertEqual(baseline, req.messages, "映射只在出口副本上")

    def test_the_egress_mapping_is_idempotent_and_never_mutates_the_request(self):
        """出口映射是**纯函数**级：同一个 `LLMRequest` 连发两腿、再发两次都不许被改写。

        `openai_payload` 里 `dict(m)` 是**浅**拷贝 ⇒ 若就地改 `tool_calls[].function`，
        调用方 messages 里的 dict 就被换成字符串，第二轮 Ollama 腿读到的是坏形状。
        顺带钉「配不上对的回执**不造假 id**」与「已经带过 `tool_call_id` 的原样透传」。
        """
        messages = [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-a", "type": "function",
                 "function": {"name": "enterprise_search", "arguments": {"query": "甲"}}}]},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}"},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}"},
            {"role": "tool", "tool_name": "enterprise_search", "content": "{}",
             "tool_call_id": "caller-supplied"},
        ]
        baseline = json.loads(json.dumps(messages, ensure_ascii=False))
        req = request_of(messages=messages)
        first = normalize.openai_payload(req, RAG_CLOUD_MODEL)["messages"]
        self.assertEqual(baseline, req.messages, "映射只发生在出口副本：调用方 messages 不动")
        self.assertIsInstance(first[1]["tool_calls"][0]["function"]["arguments"], str)
        self.assertEqual("call-a", first[2]["tool_call_id"])
        self.assertNotIn("tool_call_id", first[3], "轮里没有未消费的同名调用 ⇒ 不凭空造 id")
        self.assertEqual("caller-supplied", first[4]["tool_call_id"], "调用方给的 id 优先")
        self.assertEqual(first, normalize.openai_payload(req, RAG_CLOUD_MODEL)["messages"],
                         "同一份请求发两次必须得到同一份报文（幂等：字符串不再被二次编码）")
        self.assertEqual(baseline, normalize.ollama_payload(req, RAG_LOCAL_MODEL)["messages"],
                         "另一条腿读到的仍是内部形状")


# --------------------------------------------------------------------------
# D. D2 零候选降级（本环境的 agent 工具能力面：出厂注册表 + 无 key ⇒ 常驻分支）
# --------------------------------------------------------------------------
class AgentNoCapableFastPathTests(_AgentMigrationFixture):
    def test_shipped_registry_without_keys_offers_no_tools_capable_candidate(self):
        """钉死事实本身：不是「测试 Stub 出来的世界」，是真文件 + 真 D1 判定。"""
        registry = self.use_shipped_registry()
        tools_capable = [model.id for model in registry.models
                         if model.capabilities.tools and model.enabled]
        self.assertEqual([], tools_capable,
                         "无 key 下任何 tools=true 的条目都必须被折叠成 enabled=False")
        self.assertEqual({"ollama-ornith", "ollama-phi3"},
                         {model.id for model in registry.models if model.enabled})
        with self.assertRaises(NoCapableModelError) as ctx:
            llm.plan(RequestProfile(mode="agent", complexity="low", needs_tools=True,
                                    needs_stream=False), registry, {})
        self.assertEqual("capability", ctx.exception.stage)
        self.assertIn("NO_CAPABLE_MODEL", ctx.exception.reason_codes)

    def test_the_tool_loop_degrades_instead_of_raising_and_never_sends_tools(self):
        self.use_shipped_registry()
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        result = self.ask()                                   # 不许抛 ⇒ 更不许 500

        self.assertEqual(ROUTER_ANSWER, result["answer"])
        self.assertEqual(1, len(self.requests), "零候选那次不该发任何请求")
        for record in self.requests:
            self.assertEqual([], record.payload["tools"], "降级腿不带工具 schema")
        self.assertEqual(["enterprise_search"], self.tools.names)  # 后端直接执行检索
        self.assertEqual({"query": PLAIN_QUESTION, "top_k": 3, "knowledge_base_id": "kb-1"},
                         self.tools.last_arguments())
        self.assertEqual(1, result["num_sources"])
        self.assertEqual([1], [item["citation_index"] for item in result["sources"]])

    def test_the_trace_row_carries_the_no_capable_model_fast_path_annotation(self):
        """零候选**不产账行**（T5 裁定），所以这条事件是那一次降级唯一的解释出口。"""
        self.use_shipped_registry()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        result = self.ask()
        rows = self.trace_rows()
        self.assertEqual(1, len(rows), "一次提问一行 trace（复用 _local_fast_path 会落成两行）")
        row = rows[0]
        self.assertEqual(result["trace_id"], row["trace_id"])
        events = [event for event in row["events"]
                  if event.get("type") == "model_route_downgrade"]
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("NO_CAPABLE_MODEL→fast_path", event["note"])
        self.assertIn("NO_CAPABLE_MODEL", event["reason_codes"])
        self.assertEqual("fast_path", event["action"])
        self.assertEqual("capability", event["stage"])
        self.assertIn("mode=agent", event["profile"])
        blob = json.dumps(row, ensure_ascii=False)
        self.assertIn("NO_CAPABLE_MODEL", blob)
        self.assertIn("fast_path", blob)
        # 账本面：**只**有降级合成那一行（零候选那次没有行）——两件事一起钉才不空心。
        rows_in_ledger = self.raw_rows()
        self.assertEqual(1, len(rows_in_ledger))
        self.assertEqual("rag", rows_in_ledger[0]["route_mode"])
        self.assertEqual(1, rows_in_ledger[0]["success"])

    def test_the_http_face_still_returns_200_shape_for_a_zero_candidate_request(self):
        self.use_shipped_registry()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        body = self.call_http_face()                          # 不能 HTTPException
        self.assertEqual(ROUTER_ANSWER, body["answer"])
        self.assertEqual("auto", body["mode"], "降级不改对外 mode 取值（additive only）")

    def test_the_degraded_turn_audits_tool_call_and_result(self):
        self.use_shipped_registry()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        actions = [row["action"] for row in self.audit_rows()]
        self.assertIn("TOOL_CALL", actions)
        self.assertIn("TOOL_RESULT", actions)
        self.assertIn("QUERY", actions)
        details = " ".join(str(row.get("detail") or "") for row in self.audit_rows())
        self.assertIn("degraded=true", details)
        self.assertNotIn("web_search", self.tools.names, "降级腿按构造拿不到 web 证据")

    def test_all_candidates_failed_still_propagates_to_the_route_fallback_copy(self):
        """`AllCandidatesFailedError` **不**被 D2 吞：现网语义是上抛→503 那句，一字不改。"""
        self.serve((500, {"error": "boom"}))
        with self.assertRaises(AllCandidatesFailedError):
            self.ask()
        with self.assertRaises(AllCandidatesFailedError):
            agent_module._ollama_chat([{"role": "user", "content": "hi"}], [{"type": "1"}])
        with mock.patch.object(agent_routes_module, "_validate_knowledge_base_scope",
                               lambda *args, **kwargs: None):
            with self.assertRaises(HTTPException) as ctx:
                self.call_http_face()
        self.assertEqual(503, ctx.exception.status_code)
        self.assertTrue(str(ctx.exception.detail).startswith("Agent 服务不可用："),
                        ctx.exception.detail)

    def test_hard_terminal_llm_error_is_not_converted_into_a_fast_path(self):
        """硬终态（`LLMError` kind=hard）同样不许被降级吃掉——那是另一种业务错误。"""
        self.serve((400, {"error": "unsupported model"}))
        with self.assertRaises(LLMError) as ctx:
            self.ask()
        self.assertEqual("hard", ctx.exception.kind)
        self.assertEqual([], self.tools.names, "没降级就不会执行后端检索")

    def test_the_limit_branch_degrades_through_the_same_door(self):
        """`for…else` 那支（工具轮次耗尽后的合成）是第二处 catch 落点。"""
        self.settings.agent_max_tool_rounds = 1

        def flaky(messages, tools, **kwargs):
            if tools:
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "enterprise_search", "arguments": {"query": "x"}}}]}
            raise NoCapableModelError(profile=RequestProfile(
                mode="agent", complexity="low", needs_tools=False, needs_stream=False),
                stage="capability")

        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        with mock.patch.object(agent_module, "_ollama_chat", flaky):
            result = self.ask()
        self.assertEqual(ROUTER_ANSWER, result["answer"])
        row = self.trace_rows()[0]
        events = [event for event in row["events"]
                  if event.get("type") == "model_route_downgrade"]
        self.assertEqual(1, len(events))
        self.assertIn("NO_CAPABLE_MODEL", events[0]["reason_codes"])
        # 降级合成走的是 rag 画像（`mode="agent"` + 空 tools 只会再抛同一个异常）。
        self.assertEqual("rag", self.raw_rows()[-1]["route_mode"])
        self.assertIn("limit", [event.get("type") for event in row["events"]])

    # --- Task 8 修复轮 1：C-1 / I-2 / I-3 / m-6 --------------------------------

    @staticmethod
    def overflowing_evidence() -> list[dict]:
        """一段**装得进 dump 上限、装不进上下文**的证据（C-1 的复现口径）。

        降级腿的 `AUTHORIZED_ENTERPRISE_EVIDENCE=` 截到 16000 字符，而出厂两条本地条目
        `limits.context_tokens=8192`、`fallback.estimate_prompt_tokens` 的粗估口径是
        `sum(len(str(m)) for m in messages)/2` ⇒ 光证据 + 系统段就已 ~9300 token 估计值，
        合成腿必然再遇一次零候选（stage=`context`）。这是**默认值**不是边界值：一次普通
        提问 + 稍长证据即可（评审 C-1 实测两条路径之一）。
        """
        return [{"id": "p-long", "file_name": "报销制度.md", "page": 3,
                 "content": "差旅住宿上限每天陆佰元，超出部分不予报销。" * 700}]

    def _long_evidence_degrade(self) -> dict:
        self.use_shipped_registry()
        self.guard_legacy_egress_off()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.tools.evidence = self.overflowing_evidence()
        return self.ask()

    def test_a_second_zero_candidate_still_delivers_the_copy(self):
        """C-1：降级腿那次合成**自己**再抛 `NoCapableModelError(stage="context")` 时，
        既不许穿出 `run_agent`（→ 路由层 503），也不许让 trace 一行不落。"""
        result = self._long_evidence_degrade()          # 不抛 ⇒ 更不许 500/503

        self.assertEqual("当前没有获得足够证据生成可靠答案。", result["answer"],
                         "降级腿再遇零候选要交回 run_agent 既有的中文收尾文案")
        self.assertEqual([], self.requests, "两次都是 plan() 阶段零候选 ⇒ 一次外呼都没有")
        rows = self.trace_rows()
        self.assertEqual(1, len(rows), "仍然只落一行 trace（`save_trace` 不许被跳过）")
        events = [event for event in rows[0]["events"]
                  if event.get("type") == "model_route_downgrade"]
        self.assertEqual(2, len(events), "两枚注记：工具轮零候选 + 合成腿零候选")
        self.assertEqual("capability", events[0]["stage"])
        self.assertEqual("context", events[1]["stage"])
        for event in events:
            self.assertEqual("NO_CAPABLE_MODEL→fast_path", event["note"])
            self.assertIn("NO_CAPABLE_MODEL", event["reason_codes"])
        actions = [row["action"] for row in self.audit_rows()]
        self.assertIn("QUERY", actions, "审计不许只剩 TOOL_CALL+TOOL_RESULT 的孤儿对")
        self.assertEqual(1, actions.count("TOOL_CALL"))
        self.assertEqual(1, actions.count("TOOL_RESULT"))
        self.assertEqual(1, result["num_sources"], "证据仍然进了上下文（是装不下，不是没有）")

    def test_the_http_face_still_returns_200_shape_when_the_degraded_leg_overflows_too(self):
        """C-1 的 HTTP 面兄弟例：溢出那次 `/api/agent/query` 也**不许**抛 HTTPException。

        上一轮只钉了「零候选降级不 503」，但降级腿再抛时 `run_agent` 直接把异常交给
        `agent_routes.py` 的 `except Exception` ⇒ 503「Agent 服务不可用：…」，D2 那句
        「任何链不得因此 500/503 给用户裸错」在这一支上是不成立的。
        """
        self.use_shipped_registry()
        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.tools.evidence = self.overflowing_evidence()
        body = self.call_http_face()                    # 不能 HTTPException
        self.assertEqual("当前没有获得足够证据生成可靠答案。", body["answer"])
        self.assertEqual("auto", body["mode"])
        self.assertEqual(1, len(self.trace_rows()))

    def test_the_three_no_generation_copies_short_circuit_like_the_conversation_chain(self):
        """I-3：DENIED / 检索失败 / 零证据三支 = 同源硬文案 + **零外呼** + 零账 + 无 route。

        与 `conversation_agent.py:316-321` 的 `_local_fast_path` 逐字同文案（复审 §6 六项
        统一口径的第 6 项）。缺这一段时降级腿会在 RBAC 拒绝面上「照发合成」，把后端硬文案
        降成「模型自律 + 提示词约束」——那是等价性在行为面上不成立的那一处。
        """
        cases = (
            ("DENIED 授权路", "DENIED", None,
             "当前账号无权访问该知识库，因此不能基于未授权资料回答。",
             "NO_CAPABLE_MODEL→fast_path_denied"),
            ("检索失败路", "FAILED", None,
             "企业知识检索暂时失败，请稍后重试。",
             "NO_CAPABLE_MODEL→fast_path_failed"),
            ("零证据路", "SUCCESS", [],
             "当前授权范围内没有检索到足够证据，暂时无法可靠回答。",
             "NO_CAPABLE_MODEL→fast_path_no_evidence"),
        )
        for label, status, evidence, copy, note in cases:
            with self.subTest(case=label):
                self.use_shipped_registry()
                self.guard_legacy_egress_off()
                self.tools.status = status
                if evidence is not None:
                    self.tools.evidence = evidence
                self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
                result = self.ask()

                self.assertEqual(copy, result["answer"])
                self.assertEqual([], self.requests, "没走到生成就不该外呼")
                self.assertEqual([], self.raw_rows(), "没走过路由就不该有账")
                self.assertEqual(0, result["num_sources"])
                row = self.trace_rows()[-1]
                self.assertNotIn(MODEL_ROUTE_KEY, row,
                                 "route_out 没塞盒子 ⇒ trace 也不挂（与对话链同口径）")
                events = [event for event in row["events"]
                          if event.get("type") == "model_route_downgrade"]
                self.assertEqual(2, len(events), "零候选一枚 + 文案短路一枚")
                self.assertEqual(note, events[-1]["note"])
                self.assertEqual(status, events[-1]["tool_status"])
                self.assertIn("NO_CAPABLE_MODEL", events[-1]["reason_codes"],
                              "reason codes 是冻结枚举，不许在这里长新词")
                actions = [r["action"] for r in self.audit_rows()]
                self.assertIn("TOOL_CALL", actions)
                self.assertIn("TOOL_RESULT", actions)
                self.assertIn("QUERY", actions)

    def _prior_evidence_then_failing_round(self, *, status: str) -> dict:
        """N-3 的复现装置：**前轮**工具回路拿到两枚授权证据，**本轮**降级腿的检索按 `status` 失败。

        形状与真实链一致（不是 Stub 出来的世界）：round 1 模型要工具 → 后端执行成功 →
        证据进 `run_agent` 的累加盒；round 2 `_ollama_chat` 抛
        `NoCapableModelError(stage="capability")` → 走 `_degrade_to_local_fast_path`，
        那次 `enterprise_search` 才失败。今天出厂注册表 100% 走 D2 所以只有「round 1 就降级」
        这一种形状 ⇒ 本例的「前轮有货」分支从未被踩过；配 key / 新增 `tools=true` 条目后
        它就是常态路径（评审 N-3）。
        """
        turns = {"n": 0}

        def flaky(messages, tools, **kwargs):
            turns["n"] += 1
            if turns["n"] == 1:
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call-1", "type": "function",
                     "function": {"name": "enterprise_search",
                                  "arguments": {"query": AGENT_TOOL_QUERY}}}]}
            raise NoCapableModelError(profile=RequestProfile(
                mode="agent", complexity="low", needs_tools=True, needs_stream=False),
                stage="capability")

        executed = {"n": 0}

        def execute(name: str, arguments: dict, context) -> dict:
            executed["n"] += 1
            if executed["n"] == 1:
                return self.tools.execute(name, arguments, context)     # 前轮：证据已在手
            from app.tools.base import ToolExecutionError
            raise ToolExecutionError("stub 本轮检索失败", status=status)

        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.tools.evidence = [
            {"id": "p-1", "file_name": "报销制度.md", "page": 1,
             "content": "差旅住宿上限每天陆佰元。"},
            {"id": "p-2", "file_name": "差旅办法.md", "page": 2,
             "content": "市内交通费每人每天捌拾元。"},
        ]
        with mock.patch.object(agent_module, "_ollama_chat", flaky), \
                mock.patch.object(agent_module.tool_registry, "execute", execute):
            result = self.ask()
        self.assertEqual(2, executed["n"], "本轮确实又检索过一次（否则复现装置没生效）")
        return result

    def test_a_failed_current_round_answers_from_the_evidence_already_in_hand(self):
        """N-3：前轮已拿到授权证据 + 本轮 `enterprise_search` 失败 ⇒ 不许用失败文案抹掉在手证据。

        **判据查实结论**（权威对照 `app/conversation_agent.py:307-321` + 它的调用点）：那三支
        看的是「**本轮检索结果**」——`status` 与 `evidence` 全部只来自本函数里**那一次**
        `tool_registry.execute`（`:232-275`），`_local_fast_path` 天生只有 round 0、没有工具
        回路，所以对它而言「本轮 == 全链路」，两种读法等价、分不出来。降级腿继承同一判据时
        两条链的语义就分叉了：`agent.py` 的 `evidence` 是 `run_agent` 传进来的**累加盒**
        （`:521-530` 每轮往里 append、`evidence_keys` 去重），前轮有货、本轮空手时就会出现
        「文案说检索失败、`num_sources` 报 2」，与 `:601` 自家理由（"证据已在手"）自相矛盾。
        ⇒ 取 brief 的方案 ②：在失败支短路前加「在手的 `evidence` 非空 ⇒ 继续合成」的门。
        （方案 ①「与权威对齐=只看本轮」在这里不可实施：权威没有跨轮累加这件事，
        照抄判据等于把已授权证据丢掉，而 §8.1 的口径是「跑过就有事实」。）
        """
        result = self._prior_evidence_then_failing_round(status="FAILED")

        self.assertNotEqual("企业知识检索暂时失败，请稍后重试。", result["answer"],
                            "本轮失败不许糊掉在手的两枚授权证据")
        self.assertEqual(ROUTER_ANSWER, result["answer"])
        self.assertEqual(2, result["num_sources"],
                         "`num_sources` 与文案必须说同一件事：证据在手的合成就报在手的量")
        self.assertEqual(2, len(result["sources"]))
        self.assertEqual({"报销制度.md", "差旅办法.md"},
                         {item["file_name"] for item in result["sources"]})
        self.assertEqual([1, 2], [item["citation_index"] for item in result["sources"]],
                         "引用编号来自累加盒的去重表，不是本轮的空壳")
        # 证据真的进了那次合成的 prompt（不是只把 num_sources 改个数字）。
        prompt = " ".join(str(m.get("content") or "")
                          for m in self.requests[0].payload["messages"])
        self.assertIn("AUTHORIZED_ENTERPRISE_EVIDENCE=", prompt)
        self.assertIn("p-2", prompt, "本轮 result['evidence'] 是空壳 ⇒ dump 得用累加盒")
        self.assertEqual(1, len(self.requests), "本轮失败 ⇒ 只有那次合成外呼")
        # trace 面：本轮失败的 fact 仍然记着（不掩盖），但**不是**「文案短路」那枚注记，
        # 而是 N-3 新加的那枚「证据在手 ⇒ 继续合成」。
        row = self.trace_rows()[0]
        events = [event for event in row["events"] if event.get("type") == "model_route_downgrade"]
        self.assertEqual(["NO_CAPABLE_MODEL→fast_path",
                          "NO_CAPABLE_MODEL→fast_path_failed_with_evidence"],
                         [event["note"] for event in events])
        self.assertEqual(["capability", "degraded_synthesis"], [event["stage"] for event in events])
        self.assertEqual({"NO_CAPABLE_MODEL"},
                         set().union(*[set(event["reason_codes"]) for event in events]),
                         "理由码仍只用冻结枚举")
        self.assertEqual("FAILED", events[-1]["tool_status"])
        self.assertNotIn("copy_shortcut", [event["stage"] for event in events],
                         "「没走到生成」那枚注记不许出现在继续合成的支上")
        tool_end = [event for event in row["events"] if event.get("type") == "tool_end"]
        self.assertEqual([("SUCCESS", 2), ("FAILED", 0)],
                         [(event["status"], event["result_count"]) for event in tool_end],
                         "本轮失败这件事在 trace 上照记不误，只是不再据此丢弃证据")
        self.assertIn(MODEL_ROUTE_KEY, row, "合成真跑过路由 ⇒ 九键必须挂上")
        actions = [r["action"] for r in self.audit_rows()]
        self.assertEqual(2, actions.count("TOOL_CALL"), "本轮那次失败检索仍留审计")
        self.assertEqual(1, actions.count("QUERY"))

    def test_a_denied_current_round_keeps_the_hard_copy_even_with_evidence_in_hand(self):
        """I-3 的拒绝面**一个字节都不许松**：`DENIED` 不吃 N-3 的门，两支不许合并。

        与上一例唯一的差别是那枚 `status`：这正好是「把失败支的门写成 `status != "SUCCESS"`
        的通用形式」那条变异的落点 ⇒ 这一例要求仍然**零外呼、零账行、硬文案**。

        末尾两枚断言钉的是**刻意保留**的「不同源」现状（Task 9 复审 I-3）：拒绝面优先 ⇒
        文案说「无权访问」、`num_sources` 却报在手的 2。这不是漏网，是选择——终审若要统一
        口径，必须**同时**改文案与来源面（改一侧就让这两枚里的一枚红），而不是像 N-3 那支
        一样只把文案换成合成答案（那等于让 DENIED 吃门，本例前四枚断言立刻红）。
        """
        result = self._prior_evidence_then_failing_round(status="DENIED")

        self.assertEqual("当前账号无权访问该知识库，因此不能基于未授权资料回答。",
                         result["answer"])
        self.assertEqual([], self.requests, "拒绝面不许为了『还有证据』再去问一次模型")
        self.assertEqual([], self.raw_rows(), "没走过路由就不该有账")
        self.assertEqual(1, len(self.trace_rows()))
        events = [event for event in self.trace_rows()[0]["events"]
                  if event.get("type") == "model_route_downgrade"]
        self.assertEqual("NO_CAPABLE_MODEL→fast_path_denied", events[-1]["note"])
        self.assertEqual("DENIED", events[-1]["tool_status"], "两支的理由码不许混用")
        # ↓ 现状钉（评审 I-3 之前这两枚是缺的 ⇒ 报告所称「已钉住」当时并不成立）。
        self.assertEqual(2, result["num_sources"],
                         "拒绝面短路不改来源面：在手的 2 枚仍然报 2（刻意不同源，见 docstring）")
        self.assertIn("无权访问", result["answer"],
                      "文案必须留在拒绝面上，不许被失败文案或合成答案替换")

    def test_the_degraded_leg_tool_time_stays_out_of_the_generation_stage(self):
        """I-2：降级腿那次检索的推进量不许被算进 `llm_ms`（= stage「生成」那一行）。

        两腿各跑一次、同一个阈值：正常工具回路本来是对的（`tool_time_total`），D2 降级腿
        过去漏了这笔账 ⇒ 出厂形态下**每一次**的生成 stage 都虚高一整次检索（复审实测
        400ms 工具被记成 426ms 生成），Query Trace 的重排阶段与 p95 类观测跟着失真。
        """
        for label, degraded in (("工具回路", False), ("D2 降级腿", True)):
            with self.subTest(leg=label):
                self.tools.sleep_ms = 400.0
                if degraded:
                    self.use_shipped_registry()
                    self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
                else:
                    self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                                        _response(200, json_body=ollama_body(ROUTER_ANSWER)))
                before = len(self.trace_rows())
                result = self.ask()
                rows = self.trace_rows()
                self.assertEqual(before + 1, len(rows))
                row = rows[-1]
                events = row["events"]
                generation = next(event for event in events
                                  if event.get("type") == "stage" and event["stage"] == "generation")
                tool_end = [event for event in events if event.get("type") == "tool_end"]
                self.assertEqual(ROUTER_ANSWER, result["answer"])
                self.assertEqual(1, len(tool_end))
                self.assertGreaterEqual(tool_end[0]["latency_ms"], 300.0,
                                        "睡眠没生效 ⇒ 这一例的算术不成立")
                self.assertIsNotNone(generation["elapsed_ms"],
                                     "生成 stage 被扣到 <1ms ⇒ 工具账扣重了")
                self.assertLess(generation["elapsed_ms"], row["elapsed_ms"] - 300.0,
                                f"{label}：300ms 检索被记成了模型生成")

    def test_a_context_stage_downgrade_does_not_retrieve_again(self):
        """m-6：`stage="context"` 的零候选**不重跑** `enterprise_search`（证据已在手）。"""
        turns = {"n": 0}

        def flaky(messages, tools, **kwargs):
            turns["n"] += 1
            if tools and turns["n"] == 1:
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "enterprise_search",
                                  "arguments": {"query": AGENT_TOOL_QUERY}}}]}
            raise NoCapableModelError(profile=RequestProfile(
                mode="agent", complexity="low", needs_tools=True, needs_stream=False),
                stage="context")

        self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
        with mock.patch.object(agent_module, "_ollama_chat", flaky):
            result = self.ask()

        self.assertEqual(ROUTER_ANSWER, result["answer"])
        self.assertEqual(["enterprise_search"], self.tools.names,
                         "第二轮溢出时不该再检索一次（多一笔后端检索 + 必然二次溢出）")
        self.assertEqual(1, sum(1 for row in self.audit_rows() if row["action"] == "TOOL_CALL"))
        row = self.trace_rows()[0]
        events = [event for event in row["events"]
                  if event.get("type") == "model_route_downgrade"]
        self.assertEqual(1, len(events))
        self.assertEqual("context", events[0]["stage"])
        self.assertIn(MODEL_ROUTE_KEY, row, "合成腿真跑过路由 ⇒ 九键必须挂上")
        self.assertEqual(1, len(self.requests), "只有那次 tools-free 合成外呼")


# --------------------------------------------------------------------------
# E. 矩阵 #17 的 agent 半边：真调用 → 真挂九键 → 真落 JSONL → 读回等价
# --------------------------------------------------------------------------
class AgentModelRouteTraceTests(_AgentMigrationFixture):
    def test_the_route_lands_nine_keys_before_save_trace(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        recorded: list[dict] = []
        real_save = agent_trace_module.save_trace

        def spy(trace: dict) -> None:
            # 挂载**必须**发生在落盘之前：这里读到的就是磁盘上那一行的前身。
            recorded.append(json.loads(json.dumps(trace, ensure_ascii=False)))
            real_save(trace)

        with mock.patch.object(agent_module, "save_trace", spy):
            result = self.ask()
        self.assertEqual(1, len(recorded))
        route = recorded[0][MODEL_ROUTE_KEY]
        self.assert_nine_keys(route)
        self.assertEqual("agent", route["mode"])
        # attach 取**最后一回合**：循环里每一轮都带 schema，所以这里 needs_tools 为真
        # （不带工具的收尾腿由 `AgentToolsFreeSynthesisTests` 在报文与 kwargs 两面上钉）。
        self.assertIs(True, route["requirements"]["needs_tools"])
        self.assertEqual("primary", route["stage"])
        self.assertEqual(0, route["selected_index"])
        self.assertEqual(RAG_LOCAL_MODEL, route["attempts"][0]["model"])
        self.assertEqual("success", route["attempts"][0]["result"])
        self.assertEqual(result["trace_id"], recorded[0]["trace_id"])

    def test_the_route_round_trips_through_the_jsonl(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        result = self.ask()
        on_disk = self.trace_rows()[0][MODEL_ROUTE_KEY]
        served = agent_trace_module.get_trace(result["trace_id"])[MODEL_ROUTE_KEY]
        self.assertEqual(on_disk, served, "JSONL 读回必须与落盘那份等价")
        self.assert_nine_keys(served)

    def test_the_route_object_carries_no_prompt_or_canary(self):
        self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                            _response(200, json_body=ollama_body(ROUTER_ANSWER)))
        self.ask()
        route = self.trace_rows()[0][MODEL_ROUTE_KEY]
        blob = json.dumps(route, ensure_ascii=False)
        for canary in (RAG_PROMPT_CANARY, AGENT_TOOL_QUERY, "报销制度.md",
                       agent_module.AGENT_SYSTEM_PROMPT[:24], "AUTHORIZED_ENTERPRISE_EVIDENCE",
                       "agent-alice"):
            self.assertNotIn(canary, blob, f"model_route 里出现了禁存项：{canary[:12]}…")
        for row in self.raw_rows():
            self.assertNotIn(RAG_PROMPT_CANARY, json.dumps(row, ensure_ascii=False))

    def test_the_limit_leg_route_also_lands_nine_keys(self):
        """I-1：工具轮次耗尽那条腿——**成功支与降级支都**要挂九键（等式，不是存在性）。

        上一版收尾腿传的是局部盒 `limit_outcomes`，成功支记得 `outcomes.extend(...)` 而
        except 支漏了 ⇒ 降级那次明明真跑过路由，trace 行里却没有 `model_route`（九键是
        「跑过一次真路由」唯一的解释产物，§8.1 第 4 条），`model_used` 也跟着回落。评审的
        G2 反向变异（删掉成功支那次 merge）当时**存活**，缺的就是这一例。修法改成与主降级
        门同形（`route_out=outcomes` 直传），这里两支持平地各钉一枚键集合**等式**。
        """
        full_face = {"trace_id", "timestamp", "username", "role", "mode", "model",
                     "max_tool_rounds", "context_messages", "events", "evidence_count",
                     "elapsed_ms", "timings", MODEL_ROUTE_KEY}

        def limit_leg_degrades(messages, tools, **kwargs):
            if tools:
                return {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "enterprise_search",
                                  "arguments": {"query": AGENT_TOOL_QUERY}}}]}
            raise NoCapableModelError(profile=RequestProfile(
                mode="agent", complexity="low", needs_tools=False, needs_stream=False),
                stage="capability")

        self.settings.agent_max_tool_rounds = 1
        for label, stubbed, expected_mode in (
                ("成功支（收尾腿正常生成）", False, "agent"),
                ("降级支（收尾腿零候选后合成）", True, "rag")):
            with self.subTest(branch=label):
                before = len(self.trace_rows())
                if stubbed:
                    self.serve(_response(200, json_body=ollama_body(ROUTER_ANSWER)))
                    with mock.patch.object(agent_module, "_ollama_chat",
                                           limit_leg_degrades):
                        result = self.ask()
                else:
                    self.serve_sequence(_response(200, json_body=ollama_tool_body()),
                                        _response(200, json_body=ollama_body(ROUTER_ANSWER)))
                    result = self.ask()
                rows = self.trace_rows()
                self.assertEqual(before + 1, len(rows), "仍然只落一行 trace")
                row = rows[-1]
                self.assertEqual(ROUTER_ANSWER, result["answer"])
                self.assertEqual(full_face, set(row),
                                 "两支的 trace 键集合都必须是「挂上 model_route」那一形")
                route = row[MODEL_ROUTE_KEY]
                self.assert_nine_keys(route)
                self.assertEqual(expected_mode, route["mode"],
                                 "attach 取的是**最后那次真跑过的路由**（收尾腿），不是第一轮")
                self.assertIs(False, route["requirements"]["needs_tools"],
                              "收尾腿不带工具 schema（needs_tools=bool([])）")
                self.assertEqual(route["attempts"][0]["model"], result["model_used"],
                                 "两支都不许回落 settings.ollama_model")

    def test_no_route_is_attached_on_the_legacy_flag_off_path(self):
        """#18：关掉旗标 ⇒ trace 形状与迁移前**逐字**相同（没有 model_route 这一枚键）。"""
        self.settings.llm_router_enabled = False
        self.spy_legacy_post(ollama_body(ROUTER_ANSWER))
        with mock.patch.object(llm, "complete",
                               side_effect=AssertionError("legacy 路不得调用 llm.complete")):
            result = self.ask()
        self.assertEqual(ROUTER_ANSWER, result["answer"])
        trace = self.trace_rows()[0]
        self.assertNotIn(MODEL_ROUTE_KEY, trace)
        self.assertEqual(self.settings.ollama_model, trace["model"])
        self.assertEqual(self.settings.ollama_model, result["model_used"])


# --------------------------------------------------------------------------
# F. 矩阵 #18：legacy 分支保留（D6 豁免表的等式版）
# --------------------------------------------------------------------------
class AgentLegacyBranchTests(_AgentMigrationFixture):
    def test_matrix_18_the_legacy_payload_is_untouched_byte_for_byte(self):
        """`LLM_ROUTER_ENABLED=false` 那条 httpx 分支的**整份请求体**逐键等式（原码对照）。"""
        self.settings.llm_router_enabled = False
        calls = self.spy_legacy_post({"model": RAG_LOCAL_MODEL,
                                      "message": {"role": "assistant", "content": "旧的",
                                                  "tool_calls": []},
                                      "done": True})
        agent_module._ollama_chat([{"role": "user", "content": "问题"}],
                                  [{"type": "function", "function": {"name": "t"}}])
        self.assertEqual({
            "model": self.settings.ollama_model,
            "stream": False,
            "think": True,
            "keep_alive": "30m",
            "messages": [{"role": "user", "content": "问题"}],
            "tools": [{"type": "function", "function": {"name": "t"}}],
            "options": {"temperature": 0.2, "num_predict": 768},
        }, calls[-1]["json"])
        self.assertEqual(OLLAMA_CHAT_URL, calls[-1]["url"])
        self.assertEqual(self.settings.agent_llm_timeout_seconds, calls[-1]["timeout"])

    def test_matrix_18_the_full_loop_still_runs_on_the_legacy_egress(self):
        self.settings.llm_router_enabled = False
        calls = self.spy_legacy_post({"model": RAG_LOCAL_MODEL, "message": {
            "role": "assistant", "content": "差旅住宿上限每天陆佰元 [1]。"}, "done": True})
        result = self.ask()
        self.assertEqual("差旅住宿上限每天陆佰元 [1]。", result["answer"])
        self.assertEqual(1, len(calls), "没有工具决策就不该发第二轮")
        self.assertEqual(2, len(calls[-1]["json"]["tools"]), "auto 档仍带两枚 schema（原样）")

    def test_matrix_18_legacy_message_missing_keeps_the_same_runtime_error_text(self):
        self.settings.llm_router_enabled = False
        self.spy_legacy_post({"model": RAG_LOCAL_MODEL, "done": True})
        with self.assertRaises(RuntimeError) as ctx:
            agent_module._ollama_chat([{"role": "user", "content": "hi"}], [])
        self.assertEqual("Ollama 返回缺少 message", str(ctx.exception))

    def test_the_legacy_signature_still_takes_two_positional_arguments(self):
        """`conversation_agent`（#18 的 buffered 腿）与 `scripts/*` 都按两参调它。"""
        self.settings.llm_router_enabled = False
        self.spy_legacy_post(ollama_body("x"))
        self.assertEqual("x", agent_module._ollama_chat(
            [{"role": "user", "content": "hi"}], [])[  "content"])

    def test_d6_exemption_inventory_for_agent_py(self):
        """命中数只允许两种变化：legacy 被删（那时全零）或**有人新开了第二条出口**（必红）。

        等式而不是「不超过」——`<=` 会让「顺手再加一处 httpx 直连」静默通过（与
        `RagLegacyEgressInventoryTests` 同一口径，Task 9 的豁免表可直接抄这三行）。
        """
        tree = ast.parse((BACKEND_DIR / "app" / "agent.py").read_text(encoding="utf-8"))
        docstrings = _docstring_nodes(tree)
        imports = posts = endpoint = base_url_attr = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += sum(1 for alias in node.names
                               if alias.name.split(".")[0] == "httpx")
            elif isinstance(node, ast.Attribute):
                if (node.attr == "post" and isinstance(node.value, ast.Name)
                        and node.value.id == "httpx"):
                    posts += 1
                if node.attr == "ollama_base_url":
                    base_url_attr += 1
            elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node not in docstrings and "/api/chat" in node.value):
                endpoint += 1
        self.assertEqual(1, imports, "agent.py 的 import httpx 必须仍是 1 处（legacy 豁免）")
        self.assertEqual(1, posts, "`httpx.post(` 代码命中必须仍是 1 处（router 腿不许多一条）")
        self.assertEqual(1, endpoint, "端点路径字面量必须仍是 1 处")
        self.assertEqual(1, base_url_attr, "读 ollama_base_url 也只允许那一处")
        self.assertEqual(0, sum(1 for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                                and node.attr in {"stream", "Client", "get"}
                                and isinstance(node.value, ast.Name) and node.value.id == "httpx"))


# --------------------------------------------------------------------------
# G. 与另两条链的边界：本任务不许改它们的形状，也不许长出第三条出口
# --------------------------------------------------------------------------
class AgentChainBoundaryTests(_AgentMigrationFixture):
    def test_the_conversation_chain_keeps_calling_agent_ollama_chat_on_its_legacy_leg(self):
        """T7 的 #18 对照物：`_ollama_chat` 仍是「两参 + message dict」，本任务只加可选 kw。"""
        signature = inspect.signature(agent_module._ollama_chat)
        positional = [name for name, parameter in signature.parameters.items()
                      if parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
        self.assertEqual(["messages", "tools"], positional)
        for name in ("trace_id", "route_out"):
            self.assertIs(inspect.Parameter.KEYWORD_ONLY, signature.parameters[name].kind)
            self.assertIsNone(signature.parameters[name].default)

    def test_the_agent_chain_does_not_open_a_third_stream_egress(self):
        """brief 移交项：SSE 只有两支出口，agent 迁移**不许**再造流式分支。

        计数走 AST 而不是文本：docstring 里也要提 `llm.complete(mode="agent")` 这件事，
        按字符串数会把散文算成出口（也会把「注释里解释了一句」变成测试红）。
        包级出口在 `agent.py` 里有且只有**两**个调用点：`_chat_via_router`（mode=agent，
        工具轮与合成轮共用）与 `_synthesize_without_tools`（mode=rag，D2 降级腿）。第三处
        就要解释「同一件事为什么有第三个入口」；`llm.stream` 必须为零——两支 SSE 出口在
        `conversation_stream_routes.py` 与 `agent_routes.py`，都不是这里。
        """
        tree = ast.parse((BACKEND_DIR / "app" / "agent.py").read_text(encoding="utf-8"))
        complete_modes: list[str] = []
        streams = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if not isinstance(node.func.value, ast.Name) or node.func.value.id != "llm":
                continue
            if node.func.attr == "complete":
                complete_modes.extend(
                    str(keyword.value.value) for keyword in node.keywords
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant))
            elif node.func.attr in ("stream", "run_stream"):
                streams += 1
        self.assertEqual(2, len(complete_modes), complete_modes)
        self.assertEqual(["agent", "rag"], sorted(complete_modes))
        self.assertEqual(0, streams, "agent 链不许长出第三条流式出口（D5/矩阵 #9）")
        source = (BACKEND_DIR / "app" / "agent.py").read_text(encoding="utf-8")
        self.assertNotIn("token_sink", source)

    def test_fallback_py_is_byte_frozen_for_this_task(self):
        """硬约束：`app/llm/fallback.py` 不许被本任务碰过（sha1 前缀钉）。"""
        digest = hashlib.sha1((BACKEND_DIR / "app" / "llm" / "fallback.py").read_bytes()).hexdigest()
        self.assertTrue(digest.startswith("008d8213bc05"), digest)

    def test_the_registry_file_is_untouched(self):
        """不许为了「让 agent 链看起来能用」去翻 tools 旗标（那是注册表说谎）。"""
        payload = json.loads(SHIPPED_REGISTRY.read_text(encoding="utf-8"))
        declared = {model["id"]: model["capabilities"]["tools"] for model in payload["models"]}
        self.assertEqual({"ollama-ornith": False, "ollama-phi3": False, "openai": True,
                          "deepseek-chat": True, "qwen-plus": True}, declared)


if __name__ == "__main__":
    unittest.main()
