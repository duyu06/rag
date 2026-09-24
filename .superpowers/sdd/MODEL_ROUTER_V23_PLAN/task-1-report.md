# Task 1 报告 — models + registry + 配置键（Model Router V2.3）

状态：**完成（DONE_WITH_CONCERNS，疑虑全为移交项与非阻断加固，见「需上层确认」）**
门槛达成：定向 `37 passed / 66 subtests / 0 failed`；全套件 **444 passed, 539 subtests, 0 failed**
（基线 407 + 本任务新增 37，零新增失败；brief 写的「≥417」是按「≥10 例」估的下限，实际交付 37 例，方向一致）。
无 git 写；未碰 `main.py`/`main_agent.py`/lifespan（pre-flight 裁决：warmup 只建函数，接线在 Task 5）。

## 交付文件

| 文件 | 内容 |
| --- | --- |
| `backend/app/llm/models.py`（新） | §3 冻结清单 12 个数据对象：`ModelCapabilities/ModelPricing/ModelLimits/ModelDefinition`（pydantic，`extra="forbid"` + `frozen=True`）、`RequestProfile/RouteCandidate/RoutePlan`（frozen dataclass）、`LLMRequest/ToolCall/LLMResponse/LLMChunk`（pydantic）、`UsageRecord`（dataclass，§8 冻结 19 列逐字镜像）。常量 `PRIORITY_KEYS=("chat","rag","tools")`、`CAPABILITY_KEYS` |
| `backend/app/llm/registry.py`（新） | `RegistryError(ValueError)`、`_RegistryFile`（顶层 forbid + `version>=1` + `models` 非空）、`Registry`（frozen，`get(id)`/`ids()`）、`load_registry(path)`、四类校验、`provider_credentials(model) -> ProviderCredentials`、`get_registry/reset_registry/warmup` |
| `backend/app/llm/__init__.py`（新） | 符号再导出（12 模型类 + 8 注册表符号 + `__all__`）。**不留空壳 `complete()/stream()`**——Task 4 落地，避免「能 import 不能调用」的假接口 |
| `backend/config/llm_registry.json`（新） | spec §3 的 5 条目，零 secret（Dockerfile 已有 `COPY config ./config`，无需改镜像） |
| `backend/app/config.py`（改） | §12 键 14 个（含中文注释），插在 `openai_*` 之后；旧键零改动 |
| `backend/.env.example`（改） | 末尾新增「Model Router V2.3」中文注释块（沿用 FEISHU 块风格：段首重启提示 + 逐键注释） |
| `backend/tests/test_model_router_v23_contract.py`（新） | 37 例 / 6 类（Task 2–4 继续在此文件追加矩阵用例） |

## 红 → 绿证据

1. **红（A：实现缺失）** 临时移走 `app/llm/` 与 `config/llm_registry.json` →
   `ModuleNotFoundError: No module named 'app.llm'`，collection error 1 error。
2. **红（B：配置键缺失）** 实现到位、仅剥离 `config.py` 的 §12 键块（1513 字符）→
   **30 failed / 29 passed**（`RouterSettingsTests` 默认值表 + 边界拒绝 + `.env.example` 逐键全红，
   warmup/单例组因 `llm_router_enabled` 不存在连带红）。随后按原字节还原。
3. **绿** 定向 `37 passed, 66 subtests passed in 0.55s`。
4. **全套件** 终态复跑 `444 passed, 13 warnings, 539 subtests passed in 149.70s`
   （变异自查还原后又跑一次同样 444/539，0 failed；改动前基线复跑实测
   `407 passed, 464 subtests` — 只增不减）。
5. **真实宿主冒烟**（读真 `backend/.env`，OPENAI key 空）：
   `ids=('ollama-ornith','ollama-phi3','openai','deepseek-chat','qwen-plus')`、
   `enabled=(True,True,False,False,False)`、`ollama creds base=http://localhost:11434 key=''`
   ⇒ 动态 enabled 在现网配置下即生效，本地两条可用。

## 测试构成（brief 四组 ≥10 例，实际 37）

- **加载**（`ShippedRegistryTests` 5）：出厂文件 = §3 五条目 + priority 100/100/0 与 80/80/0 +
  三条 tools=true；零 secret 双层钉（文本层扫 `api_key/base_url/authorization/secret/bearer/sk-`，
  结构层要求每个键名都在 §3 schema 白名单内）；**动态 enabled**（无 key ⇒ openai False，
  有 key ⇒ openai True 且 deepseek/qwen 仍 False）；ollama 两条无 key 也 enabled；`get()` 未知 id 抛错。
- **校验失败**（`RegistryValidationTests` 9）：重复 id / priority 键越界（含 `agent`、拼错 `toools`，
  并钉「空 priority 合法」）/ 能力全 false / 未知顶层键 / **条目内塞 api_key·base_url** /
  pricing 内塞 gold / 空 models / 结构坏四情形（文件缺失、JSON 语法、顶层是数组、缺 version、
  models 非列表）/ 漏写旗标 fail-closed 默认 False。
- **凭据解析**（`ProviderCredentialsTests` 8）：ollama（base 来自 Settings，**恒无 key**，
  即使宿主误设 `OLLAMA_API_KEY` 也不外带）、尾斜杠归一、内置 openai 复用 `OPENAI_*`、
  deepseek/qwen 的 `SecretStr` 解包 + strip、未知 provider 走 `{大写}_*` env 约定、
  `_MODEL_OVERRIDE` 生效而 `OLLAMA_MODEL` 不生效、缺 base_url ⇒ `RegistryError`、
  条目的字段集恰等于 `ModelDefinition.model_fields`（凭据不可能来自 JSON）。
- **单例与 warmup**（`RegistrySingletonAndWarmupTests` 4）：`get_registry` 缓存到 `reset_registry`
  （换配置键不换快照 + 换文件后 reset 才生效）、`warmup` 关闭时**不读文件不装配**、
  打开且文件坏 ⇒ 上抛且 `_registry` 保持 None（无半装配残留）、正常时只装配一次。
- **数据模型形状**（`ModelDataObjectTests` 6）：`RequestProfile` frozen + `needs_reasoning` 默认、
  `RouteCandidate/RoutePlan` 元组形状与 frozen、`LLMRequest` 可变默认值不跨实例共享
  （`first.tools.append` 不污染 `second.tools`）+ 默认值表、`ToolCall/LLMResponse/LLMChunk/ModelLimits` 形状、
  `UsageRecord` 19 列名与顺序逐字等式（Task 5 建表依据）、包面 `__all__` 全部可取。
- **配置键**（`RouterSettingsTests` 5）：14 键默认值表、8 个越界值构造期拒、
  breaker window 下限 8 与 `app/resilience.CircuitBreaker` 同轨、`.env.example` 逐键（含
  bool/SecretStr 真实 env 解析路径 + 等于类默认值）、无参 `Settings()` 仍可构造且默认注册表可加载。

隔离手法沿用 TypeSafe V2 Task 2：`Settings(_env_file=None)` 关 dotenv +
`mock.patch.dict(os.environ, {}, clear=True)` 关宿主 OS env，再把该实例打到
`app.llm.registry.settings` 上（注册表与凭据都不读进程全局单例 ⇒ 宿主
`backend/.env`（OPENAI 空 key、`OLLAMA_MODEL=ornith-1.5:9b-text`）不串味）。
每个用例 `setUp/tearDown` 复位单例，避免跨用例读到上一份快照。

## D1 实现口径（要点核对）

- 查找顺序：`Settings.{provider}_{field}` →（无该字段时）OS env `{PROVIDER}_{FIELD}` → 空串。
  选这个顺序的理由是 spec D1 的「内置 openai 条目复用现有 `OPENAI_*`，**不产生第二套配置**」：
  `backend/.env` 里的 key 必须继续生效（legacy `rag.py` 判的就是 `settings.openai_api_key`），
  而 deepseek/qwen 也已是 Settings 键；只有 moonshot 这类无 Settings 字段的 provider 才退到 env。
- env 名运行期拼装（`f"{provider.upper()}_{field.upper()}"`，字段名常量是小写
  `("api_key","base_url","model_override")`）⇒ 源码里不出现 `_API_KEY`/`OLLAMA_BASE_URL`
  大写**字面量凭据键**，Task 9 的 D6 静态扫描不必为凭据拼接开代码级豁免（详见移交项）。
- ollama：`api_key` 恒 `""`；`OLLAMA_MODEL` **不参与** model 覆盖——注册表里 ornith/phi3 两条
  ollama 条目各自写死模型名，全局默认值一覆盖就把它们折叠成同一模型，REAL-LLM-FAILOVER-001
  的源→备对子当场消失。只有显式 `OLLAMA_MODEL_OVERRIDE` 生效（已钉测试）。
- `base_url` 缺失 ⇒ `RegistryError`（配置事故，不是运行期可重试错误）。
- 动态 enabled：`external=true ∧ api_key 空 ⇒ enabled=False`，**在 `load_registry` 解析层完成**，
  所以 `Registry.models[*].enabled` 读到的永远是生效值，Task 3 的 enabled 过滤不必再判 key；
  方向不反向（`enabled=false` 的占位条目即使 key 到位也不自动打开）。JSON 不能带注释
  （且 `extra=forbid` 禁止 `_comment` 键），故「写明注释」落在
  `registry.py` 模块 docstring + `config.py` 键注释 + `.env.example` 块注释 + 测试四处。

## 偏离与自定边界（需上层确认；均为加固或必需，未放宽任何 spec 约束）

1. **接口加法（非改动词）**：①`ProviderCredentials` 除冻结的 `base_url/api_key` 外多一个
   `model_override: str = ""`——D1 约定含 `_MODEL_OVERRIDE`，而冻结签名里没地方放它，
   带默认值的第三字段是向后兼容的最小落点（Task 2 不读它也能跑）。
   ②`Registry.ids()` 只读辅助（测试与观测用）。③`ModelDefinition` 之外的四个注册表模型也
   `extra="forbid"`（brief 只写「未知顶层键 forbid」）：条目里出现 `api_key` 是 D1 红线，
   必须与顶层同权拒绝——已有专项用例钉住。
2. **`models` 非空（`min_length=1`）**：空注册表会让每个请求都 `NO_CAPABLE_MODEL`，按 §3
   「结构校验失败 = fail-fast」归入配置事故。不影响 Task 3/4 测零候选：
   它们可直接 `Registry(models=())`（该构造不校验）。
3. **动态 enabled 泛化**：brief 只点名 openai；实现按「external ∧ 无 key」通用于 deepseek/qwen
   与未来条目（ollama 因 `external=false` 不受影响）。
4. **§12 键数口径**：任务消息写「12 个新键」，brief/spec §12 列的是 **14 个**
   （10 个路由/熔断键 + `deepseek_api_key/base_url` + `qwen_api_key/base_url`）。按 brief 全 14 实现。
5. **自定边界**（brief 未给边界的键按现有文件风格补，全闭区间并逐边验证）：
   `llm_model_timeout_seconds` 1..300；`llm_breaker_window` **8**..200（与 `MIN_WINDOW=8` 同轨）、
   `open_seconds` 1..3600、`half_open_probes` 1..10、`failure_ratio` 0..1；
   `llm_total_budget_ms` 5000..120000、`llm_retry_per_model` 0..2 按 brief 原样。
6. **注册表取值里我补的部分**（spec 只冻结本地两条 priority、三云条 tools=true、5 条目 id/model）：
   云端 priority（openai 90/90/100、deepseek 70/70/90、qwen 60/60/80 —— 本地优先于云，
   `LOCAL_PREFERRED` 的方向）、capabilities 的 stream/reasoning 旗标（ornith reasoning=true，
   其余 false：phi3/gpt-4.1-mini/deepseek-chat/qwen-plus 都不是推理模型）、limits、以及
   **pricing 为厂商牌价占位**（0.40/1.60、0.27/1.10、0.40/1.20 USD per 1M，本地 0/0）。
   价格只进 §8 `estimated_cost` 估算，Task 11 验收前应按真实账单校准；改数不改结构。
7. **`LLMRequest/LLMResponse/ToolCall/LLMChunk` 未加 `extra="forbid"`**：Task 2 要在这一层吸收
   两侧 provider 的可选字段，frozen 形状留给 provider 决定；registry 侧才需要 forbid。

## 变异自查（14/14 killed，脚本化，跑完按原字节还原）

脚本 `%TEMP%\mr_t1_mutation_check.py`（仓库外，不新增项目文件）。
前置 `[baseline-unmutated] rc=0 37 passed`，收尾 `[restored] rc=0 37 passed`；
结束后 grep 确认无 `if False` / `except Exception:` 残留。

| 变异 | 结果 | 被谁抓 |
| --- | --- | --- |
| M1 去掉重复 id 校验 | killed (1) | `test_duplicate_id_rejected` |
| M2 去掉 priority 键越界校验 | killed (2) | priority 用例 + 零 secret 结构白名单用例 |
| M3 去掉「能力全 false」校验 | killed (1) | `test_all_false_capabilities_rejected` |
| M4 顶层 forbid → ignore | killed (1) | `test_unknown_top_level_key_rejected` |
| M5 条目级 forbid → ignore | killed (3) | 条目内 api_key/base_url/拼错键 三例 |
| M6 ollama 不再强制无 key | killed (1) | `test_ollama_uses_base_url_and_never_a_key` |
| M7 缺 base_url 不再报错 | killed (1) | `test_missing_base_url_is_a_config_error` |
| M8 去掉动态 enabled 判定 | killed (2) | openai 有/无 key 两用例（含 deepseek 不反向打开） |
| M9 warmup 吞异常 | killed (1) | `test_warmup_fail_fast_and_leaves_no_half_built_singleton` |
| M10 `get_registry` 不缓存 | killed (2) | 缓存用例（`assertIs` + 换文件不换快照） |
| M11 `SecretStr` 不解包 | killed (1) | `test_secret_str_provider_keys_are_unwrapped` |
| M12 允许空 `models` | killed (1) | `test_empty_models_list_rejected` |
| M13 capabilities 缺省改 fail-open | killed (1) | `test_missing_capability_flags_default_to_false_fail_closed` |
| M14 base_url 不做 rstrip | killed (1) | `test_trailing_slash_normalised_on_base_url` |

四类校验、凭据三 provider、enabled 判定（brief 点名的三类）各有 ≥1 发命中。

## 移交后续任务的项（本任务不改）

- **Task 2**：`provider_credentials()` 抛的 `RegistryError`（缺 base_url / 未知 provider 配置不全）
  应翻译成 `LLMError(kind="config")` 并由 fallback 记 `PROVIDER_CONFIG_FAILED`；
  `warmup()` 目前不接线。另：§8 冻结 19 列里**没有** `estimated` 列，而 Task 2 要求
  「usage 缺失记 0 + estimated 旗标」⇒ 该旗标只能活在内存/响应对象里，或 Task 5 明确加列决策
  （加列即改 §8 冻结表，需上层裁决，本任务不动）。
- **Task 5**：`warmup` 挂 lifespan（与 `identity.warmup` 并排，pre-flight 裁决归 T1 函数 / T5 接线）。
- **Task 9**：D6 单一出口扫描——`app/llm/registry.py` 的命中全部在 docstring 散文里
  （解释 D1 约定时提到 `OLLAMA_BASE_URL`、`_API_KEY`），代码内无大写凭据键字面量；
  若按整文件扫需把该文件（连同 legacy 的 `rag.py`/`agent.py`/`native_stream.py`）进豁免清单，
  或把扫描限定为非注释行。`app/config.py` 同理（`*_api_key` 小写字段名，本来就必须在）。
  ⇒ **本条已被 Fix round 1 的 I-2 消解**：`app/llm/` 现为永久零命中目录，Task 9 不必为注册表层
  开文档豁免（legacy 三文件那半仍然要扫）。
- **消费方现状**：三条链路仍走各自 httpx 直连（Task 6–8 迁移），本任务未改任何调用点，
  故 legacy 行为逐字不变；全套件 407 例零回归即为此证据。

## Fix round 1（评审放行后的 2 Important + 3 Minor）

门槛：**定向 39 passed / 76 subtests / 0 failed**（37 + 新增 2）；**全套件 446 passed /
549 subtests / 0 failed**（基线 444 + 本环 2，零新增失败）。改动仅
`backend/app/llm/registry.py`、`backend/app/llm/models.py`、
`backend/tests/test_model_router_v23_contract.py`；无 git 写、无子代理、未碰调用点。

| 项 | 改动 | 位置 |
| --- | --- | --- |
| **I-1** 泄漏面 | `RegistryError` 不再内插 `str(ValidationError)`：新增 `_validation_detail(exc)`，用 `exc.errors(include_url=False, include_context=False)` 只渲染 `loc: msg`（多错用「；」串），并 `raise ... from None` 切断 `__cause__`/`__context__` | `registry.py` `load_registry` 的 except 分支 + `_validation_detail` |
| **I-1** 钉 | `test_validation_failure_message_never_echoes_entry_values`：5 个用例（条目写 api_key / 条目写 base_url / pricing 塞未知键 / provider 非法 / priority 值非整数）各带 canary 值 `sk-CANARY-9f2c74-not-in-any-message`，同时断言 canary **不在** `str(exc)`、**不在** 完整 traceback 文本（`_traceback_text` 走 `traceback.format_exception`，即启动日志的真实形状），并断言 `models.0.<key>` 仍在消息里（诊断不减） | 测试 `RegistryValidationTests` |
| **I-2** 零命中 | 模块 docstring 三处（连带另两处，共 5 处）大写 env 字面量全部改述为「由 `_env_name` 运行期拼出的 D1 凭据约定」，并新增一句口径：`app/llm/` 是 D6 扫描下的永久零命中目录、不留文档豁免；校验段补记「只列 loc+msg」的理由（D1/D3） | `registry.py` 模块 docstring |
| **M-1** 反向钉 | 动态 enabled 用例改为**三个 external 条目各自的 key 同时到位**（openai 明文 + deepseek/qwen `SecretStr`），保留 `deepseek-chat` / `qwen-plus` 的 `assertFalse` ⇒ 从「别的 provider 有 key 也不开」升级为「自己有了 key 也照样不开」，防未来简化成 `enabled = bool(key)` | 测试 `test_openai_entry_enabled_is_resolved_from_api_key_presence` |
| **M-2** 注释 | `_credential_value` 下加一行：Settings→env 两路对同一凭据等价（pydantic-settings 已把同名大写 env 读进字段），**故意不钉**这个偏序 | `registry.py` |
| **M-3** 收紧 | `ModelDefinition.provider` 加 `pattern="^[a-z0-9_]+$"`（该值要参与 env 名大写拼装，含大写/连字符/空格/换行即拼出解析不到的键）+ `test_provider_name_outside_lowercase_convention_rejected`：5 个非法形态直验 `ValidationError`、注册表路径同样拒且不回显值、`x_1` 合法不误伤 | `models.py` + 测试 |

### I-1 变异自查（脚本化，跑完按原字节还原）

前置 `[baseline-unmutated] rc=0 39 passed`，收尾 `[restored] rc=0 39 passed / 76 subtests`。

| 变异 | 结果 | 说明 |
| --- | --- | --- |
| M-A 还原旧拼接 `f"…：{exc}") from exc` | **killed（6 failed）** | canary 5 subtest + provider 用例全红：`str(exc)` 里出现 `input_value='sk-CANARY-…'` |
| M-B 保留 `_validation_detail` 但改回 `from exc` | **killed（5 failed）** | 消息本身干净，**5 个 canary subtest 全部由 traceback 断言抓红**——原始 `ValidationError` 作为 cause 打印出 `input_value='sk-CANARY-…'`，正是「warmup 不 catch ⇒ 启动日志泄漏」那条路径 |
| M-C `_validation_detail` 里带上 `err['input']` | **killed（6 failed）** | 证明钉的是「值不外泄」而非「消息非空」 |

修复后实测（真实误写两条凭据键的样本）：
`LLM 注册表结构不合法：<tmp>：models.0.api_key: Extra inputs are not permitted；models.0.base_url: Extra inputs are not permitted`，
`__cause__=None`、`__suppress_context__=True`，canary 在消息与 traceback 中均 0 命中。

### I-2 复核

`grep -E "_API_KEY|OLLAMA_BASE_URL|OPENAI_API_KEY|_MODEL_OVERRIDE|OLLAMA_MODEL|/api/chat|chat/completions|_BASE_URL" backend/app/llm/` ⇒ **零命中**（含注释与 docstring；大小写敏感，与 spec §2 的 D6 字面量清单同口径）。

### 本环副作用检查

- provider 收紧不影响出厂文件：`config/llm_registry.json` 五个 provider（ollama/openai/deepseek/qwen）全部合规，
  `test_shipped_file_matches_spec_section_three_entries` 与真实宿主 `Settings()` 冒烟照旧绿。
- 未放宽任何 spec 约束：D1 查找顺序、动态 enabled 方向、fail-fast 语义、§3 冻结字段名与 §12 键全部原样。
