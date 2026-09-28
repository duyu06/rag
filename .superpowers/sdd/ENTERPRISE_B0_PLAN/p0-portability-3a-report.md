# V2.3-P0-EVIDENCE-PORTABILITY 3A 报告 · 从原始真源导出可移植证据包

**工作树态**：零提交、零 git 写命令（只用了 `git ls-files` / `git rev-parse` 读面）。
**本步不改判据**：`validate_evidence()`、P0 闸的③判定、矩阵文案一字未动（那是 3B）。
**增量写**：每完成一步立即追加，末一次性补。

---

## 读数 1：四枚原始件 sha1 当场重算 == 原始 JSON 记录值

命令（cwd=`E:\xiangmu\rag\backend`，`python -c`，读 `kit.EVIDENCE_FILE` 的 `files_sha1` 后逐枚重算）：

```
files_sha1 entries in raw JSON : 4
1. [MATCH] role=primary_probe bytes=3010
   recorded   = 961985e87a275677bfa23fa02f3eef6f7cd51380
   recomputed = 961985e87a275677bfa23fa02f3eef6f7cd51380
2. [MATCH] role=trace_jsonl bytes=845
   recorded   = 356826f73d7c9f8a839a7089f77d023f7feef21f
   recomputed = 356826f73d7c9f8a839a7089f77d023f7feef21f
3. [MATCH] role=ledger_db bytes=16384
   recorded   = b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1
   recomputed = b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1
4. [MATCH] role=acceptance_module bytes=40517
   recorded   = da92cdf51de5dbfad3107f1dc744d18e4173e07c
   recomputed = da92cdf51de5dbfad3107f1dc744d18e4173e07c
MATCH count = 4 / 4
```

同一轮里 `kit.sha1_of(path)` 与裸 `hashlib.sha1(read_bytes())` 两枚实现各算一遍，逐枚相等（不是只信其中一枚）。

⇒ 四枚原始件此刻仍在、hash 仍对得上记录值 ⇒ 今天导出的包对真源负责。
字节数与简报表格一致（16384 / 845 / 3010 / 40517），但**上表是本机当场重算的读数**，不是引用简报。


## 读数 2：六枚文件存在、LF-only、可解析、无绝对路径

```
  result.json          exists=True bytes= 8150 CR=0 LF=300 endsLF=True json.loads=OK toplevel=dict
  response.json        exists=True bytes= 2505 CR=0 LF=92 endsLF=True json.loads=OK toplevel=dict
  ledger-row.json      exists=True bytes= 2117 CR=0 LF=77 endsLF=True json.loads=OK toplevel=dict
  trace-attempts.json  exists=True bytes= 1326 CR=0 LF=60 endsLF=True json.loads=OK toplevel=dict
  primary-probe.json   exists=True bytes= 3160 CR=0 LF=106 endsLF=True json.loads=OK toplevel=dict
  manifest.json        exists=True bytes= 6774 CR=0 LF=208 endsLF=True json.loads=OK toplevel=dict
```

绝对路径（`grep -c`，逐枚）：简报口径 `'E:\\'` 与更宽的 `'E:'` / `'C:'` / `'[a-z]:\'` **全部 = 0**

```
  ledger-row.json        'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
  manifest.json          'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
  primary-probe.json     'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
  response.json          'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
  result.json            'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
  trace-attempts.json    'E:\'=0  'E:'=0  'C:'=0  '/E:'=0
```

口径说明：`portable_files[].path` 用**仓相对 posix**（干净签出要按它定位文件才能重算），
`protected_repo_ledgers` 的键也用仓相对——那两枚键的 basename 同名（都叫 `conversations.db`），
压成 basename 会把「仓库真库 0 行」这枚证明压没。其余原始件位置一律只留 basename。
JSON 文本里控制字符必然是转义序列，所以 `.json` 导出件的 LF-only 是结构性的；仍逐枚量了 `CR=0`。

## 读数 3：`portable_files` 每条 sha256 独立重算

重算用**仓相对路径**打开文件、独立一行 `hashlib.sha256(...).hexdigest()`（不复用导出函数里的任何值）：

```
  EQUAL  bytes EQUAL  docs/evidence/model-router-v23/real-llm-failover-001/result.json  sha256=ca9f7a4e22e615c6cf648b3f…
  EQUAL  bytes EQUAL  docs/evidence/model-router-v23/real-llm-failover-001/response.json  sha256=c0aa6c9f0b1465b14960879f…
  EQUAL  bytes EQUAL  docs/evidence/model-router-v23/real-llm-failover-001/ledger-row.json  sha256=a87b7178aab096a57a2fe23a…
  EQUAL  bytes EQUAL  docs/evidence/model-router-v23/real-llm-failover-001/trace-attempts.json  sha256=1aa8a1dbfb6bb12bc67fbe18…
  EQUAL  bytes EQUAL  docs/evidence/model-router-v23/real-llm-failover-001/primary-probe.json  sha256=9084df5502c6d58b9ce343f4…
```

⇒ 五枚载荷件的 sha256 + bytes 全部可重算（`write_portable_bundle()` 落盘后自己也会从盘上再算一遍，
对不上就抛 `AssertionError`，所以「manifest 说的」= 「盘上那枚字节」）。

## 读数 4：`trace_id` 三处逐字符一致

```
  manifest.trace_id        = 'p0-failover-6146ff1417d7'
  trace-attempts.trace_id  = 'p0-failover-6146ff1417d7'
  ledger-row.trace_id      = 'p0-failover-6146ff1417d7'
  逐字符相等 = True | trace_id_consistent(文件内) = True
  trace-attempts.trace_id_pointers = {"trace.trace_id": "p0-failover-6146ff1417d7",
                                      "ledger.row.trace_id": "p0-failover-6146ff1417d7",
                                      "request.trace_id": "p0-failover-6146ff1417d7"}
```

## 读数 5：十枚断言

```
  assertion_count = 10 | len(assertions) = 10 | all_pass = True
    1 primary_really_called                  pass=True observed_nonempty=True type=dict elapsed_ms=2.1
    2 failure_classified_model_unavailable   pass=True observed_nonempty=True type=dict elapsed_ms=0.1
    3 fallback_called                        pass=True observed_nonempty=True type=dict elapsed_ms=0.0
    4 phi3_valid_chinese_answer              pass=True observed_nonempty=True type=dict elapsed_ms=0.0
    5 fallback_index_is_one                  pass=True observed_nonempty=True type=dict elapsed_ms=0.0
    6 trace_id_consistent                    pass=True observed_nonempty=True type=dict elapsed_ms=0.0
    7 model_route_two_attempts               pass=True observed_nonempty=True type=dict elapsed_ms=1.1
    8 usage_row_landed                       pass=True observed_nonempty=True type=dict elapsed_ms=0.0
    9 zero_prompt_stored                     pass=True observed_nonempty=True type=dict elapsed_ms=0.1
   10 api_face_is_200                        pass=True observed_nonempty=True type=dict elapsed_ms=40642.2
  名字与 §10 常量表一致 = True
```

## 实现落点（3A 只动这几处）

| 文件 | 改动 | 判据是否受影响 |
| --- | --- | --- |
| `backend/tests/real_llm_failover_kit.py` | 新增 §7：`build_portable_bundle()` / `write_portable_bundle()` / `sha256_of()` + 私有投影件；模块 docstring 加一条 §7 边界 | 否——`validate_evidence()` 一字未改（与 pristine `git show HEAD:` 逐行 diff：**0 行删除**、476 行新增；补 `source_run_dir` 后为 481 行新增，见《终态一览》） |
| `.superpowers/scripts/run_p0_failover_acceptance.sh` | `[4/4]` 在 sha1 回打之后、`green_permission()` 之前调 `kit.write_portable_bundle(evidence)`；抬头「三件事」→「四件事」 | 否——退出码与许可判定原样；`bash -n` 通过、两枚 heredoc 的 python 段 `ast.parse` 通过、**CR 0** |
| `docs/evidence/model-router-v23/real-llm-failover-001/*.json` | 新增六枚（一次性回导走同一函数，未另写 CLI） | 否 |

未触碰：`backend/app/**`、`.gitattributes`、`.github/workflows/ci.yml`、`docs/ENTERPRISE_B0_*`、
`docs/SECURITY_A_*`、`test_real_llm_failover_gate.py` 的断言、原始件（`.db` / `.jsonl` / probe / 证据 JSON 只读）。
`test_real_llm_failover_acceptance.py` **刻意没改**：它的 sha1 在原始证据 `files_sha1` 里，改它就等于
自己把自己的 provenance 弄脏（读数 1 里它仍是 `da92cdf51de5dbfad3107f1dc744d18e4173e07c`）。

闸①的源码面同时扫 `real_llm_failover_kit.py`（`test_the_evidence_collector_kit_is_clean_too`），
所以新增代码按它的口径写过一遍：skip 家族名字 / 非 docstring 字符串常量 / `exec|eval|compile|__import__|vars|globals|locals`
**零命中**（当场用同一套正则对重建后的文件跑过：`GATE-1 hits in rebuilt kit: []`）。

## 字段映射：`bundle 字段 ← 原始 JSON 指针`

原始证据 = `.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/real-llm-failover-001.json`（下称 **raw**，只读）；
A-2 探针件 = 同目录 `ornith-primary-load-probe.json`（下称 **probe**，只读）。
「投影」= 逐字取值不做推断；「basename」= 去绝对路径只留文件名；「仓相对」= 相对仓库根的 posix 路径。

### `result.json`

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `case_id` | `raw.case_id` | 投影 |
| `evidence_schema_version` | `raw.schema_version` | 投影（原始证据自己的版本，=1） |
| `source_run_generated_at` | `raw.generated_at` | 投影（**不得丢**） |
| `assertions[].id/name/pass/observed/elapsed_ms` | `raw.assertions[]` 同名键 | 逐条原样（`observed` 完整带出；失败例的 `failure` 也原样） |
| `assertion_count` | `len(raw.assertions)` | 计数 |
| `all_pass` | `raw.assertions[].pass` | 全与 |
| `expected_assertion_names[]` | `kit.ASSERTION_NAMES` | §10 十字常量表（不是 raw 的字段，是**判据名**的同一出处） |

### `response.json`

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `answer.*`（含 `text`） | `raw.answer.*` | **全量**：`text/chars/cjk_chars/model/finish_reason/input_tokens/output_tokens/usage_estimated` 一枚不减 |
| `provider_calls[]` | `raw.provider_calls[]` | 逐条原样（含 `error_body_excerpt` 原文） |
| `provider_transport` | `raw.provider_transport` | 原样（**raw 里就是 null**，见 null 清单） |
| `summary.{calls,entry_id_in_order,model_in_order,ok_in_order,http_status_in_order,error_kind_in_order,request_bytes_in_order,elapsed_ms_in_order}` | 同名键并置 | 由上两段机械列序，不新增事实 |
| `summary.elapsed_ms_sum` | `raw.provider_calls[].elapsed_ms` | 求和（41596.4+20032.8=61629.2） |
| `summary.request_bytes_method` | `raw.provider_calls[0].request_bytes_method` | 投影（「报文长度是重建而非抓包」这条边界随件带出） |
| `summary.answer_chars` / `answer_cjk_chars` | `raw.answer.chars` / `.cjk_chars` | 投影 |

### `ledger-row.json`

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `ledger_source.path_basename` | `raw.ledger.path` | basename（临时库仍在 ignored 目录，不入库） |
| `ledger_source.rows` | `raw.ledger.rows` | 投影（=1） |
| `ledger_source.tables` | `raw.ledger.tables` | 投影（`llm_request_logs`、`sqlite_sequence`） |
| `row`（19 列） | `raw.ledger.row` | **原样**（`id/trace_id/request_id/route_mode/route_reason/provider/model/fallback_index/input_tokens/output_tokens/total_tokens/ttft_ms/latency_ms/estimated_cost/currency/success/error_type/status_code/created_at`） |
| `trace_id` | `raw.ledger.row.trace_id` | 投影（读数 4 的第二处） |
| `canary_needles` | `raw.ledger.canary_needles` | 原样 5 枚（当时扫库用的针） |
| `canary_hits` | `raw.ledger.canary_hits` | 原样（空表 = 零入库那枚断言的盘面事实） |
| `forbidden_column_proof.columns_checked` | `kit._BUNDLE_FORBIDDEN_COLUMNS` | 与 `validate_evidence()` 内那枚 inline 清单**逐字相同**（prompt/context/messages/reasoning） |
| `forbidden_column_proof.columns_present_in_row` | `raw.ledger.row` 的键 | 实测（= 空表 ⇒ 证明成立） |
| `forbidden_column_proof.row_columns` | `raw.ledger.row` 的键 | 排序列出（19 列全在明面上，便于反查） |
| `forbidden_column_proof.canary_hit_count` | `len(raw.ledger.canary_hits)` | 计数 |
| `forbidden_column_proof.protected_repo_ledgers` | `raw.ledger.protected_repo_ledgers` | 值原样（`backend/data/conversations.db`=0、`data/conversations.db`=null），键 → 仓相对 |

### `trace-attempts.json`

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `trace_id` | `raw.trace.trace_id` | 投影（**顶层无 `trace_id` 键**，见 null 清单） |
| `trace_id_pointers` | `raw.trace.trace_id` / `raw.ledger.row.trace_id` / `raw.request.trace_id` | 三处并置 |
| `trace_id_consistent` | 同上三处 | 值集合大小为 1 且无 None ⇒ true |
| `trace_source.path_basename` / `.lines` | `raw.trace.path` / `raw.trace.lines` | basename / 投影 |
| `model_route_stage` | `raw.trace.model_route_stage` | 投影（`fallback`） |
| `model_route_selected_index` | `raw.trace.model_route_selected_index` | 投影（1） |
| `model_route_keys` | `raw.trace.model_route_keys` | 原样 9 枚 |
| `model_route_attempts[]` | `raw.trace.model_route_attempts` | 原样两枚（ornith failed / model_unavailable，phi3 success） |
| `chain` | `raw.chain` | 原样（产品侧同一次路由结论：`selected_index/reason_codes/attempts/response_model`） |

### `primary-probe.json`（probe 件的文本化投影，不是路径引用）

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `case_id` | `kit.CASE_ID` | 常量（probe 件自己没有 case_id 键） |
| `source_file_basename` | `kit.PROBE_FILE` 的文件名 | basename |
| `stage` / `started_at` | `probe.stage` / `probe.started_at` | 投影 |
| `inventory_before` / `inventory_after` | `probe.inventory_before` / `.inventory_after` | 原样（`base_url/reachable/tags/loaded/error/has_primary/has_fallback`） |
| `memory_before` / `memory_after` | `probe.memory_before` / `.memory_after` | 原样（含 `verdict` 中文判定） |
| `probe.*` | `probe.probe.*` | 原样 15 键：`case_note/model/url/request_bytes/request_payload/timeout_seconds/started_at/status_code/raw_error_body/raw_error_body_chars/answer_content/probe_result/classification/elapsed_ms/error` |
| `projection` | —（说明字段） | 声明「逐字投影、不含绝对路径」 |

### `manifest.json`

| bundle 字段 | ← 原始指针 | 处理 |
| --- | --- | --- |
| `evidence_schema_version` | `kit.BUNDLE_SCHEMA_VERSION` | =1（bundle 自己的形状版本） |
| `case_id` | `raw.case_id` | 投影 |
| `generated_at` | 导出时刻 | `kit.utc_now()`，ISO8601 带时区（交付件里实测 `2026-09-28T16:19:52+00:00`） |
| `source_run_generated_at` | `raw.generated_at` | 投影 = `2026-09-24T13:52:06+00:00`（**没丢**） |
| `trace_id` | `raw.trace.trace_id` | 投影 = `p0-failover-6146ff1417d7` |
| `trace_id_source.pointers/consistent/note` | `raw.trace.trace_id`、`raw.ledger.row.trace_id`、`raw.request.trace_id` | 同源核对，并把「顶层键不存在」写进件里 |
| `source_tree_hash` | 导出当场的 `git rev-parse HEAD`（只读） | 实测 `7923ee47955197406ee0dd498f74587d8915a7d8`；取不到则 null，不猜不缓存 |
| `source_tree_hash_origin` | —（说明字段） | 记命令与「取不到写 null」的口径 |
| `release_image` | **raw 没有这枚事实** | `null`（见 null 清单；证据面缺口，不圆场） |
| `environment` | `raw.environment` | 原样（`before/after/memory_before/memory_after`），其中 `probe_reference` → basename |
| `plan` | `raw.plan` | 原样 |
| `config_overrides` | `raw.config_overrides` | 原样，其中 `llm_registry_file` → basename `llm_registry.json` |
| `registry_file` | `raw.registry_file` | 仓相对 `backend/config/llm_registry.json` |
| `registry_mutated` | `raw.registry_mutated` | 原样中文说明 |
| `exported_by.function` | `kit.BUNDLE_EXPORT_FUNCTION` | 导出函数标识 |
| `exported_by.source_basenames` | 导出实际读过的原始件 | **basename 列表**（5 枚，无绝对路径） |
| `portable_files[].path` | 五枚载荷件 | 仓相对 posix（干净签出按它定位才能重算） |
| `portable_files[].sha256` / `.bytes` | 载荷件字节 | `hashlib.sha256` / 长度；落盘后再从盘上重算核对 |
| `raw_provenance[].name/role/sha1/bytes` | `raw.files_sha1` 的键（清单来源） | basename / 四枚 role / **当场重算** sha1 / 盘上字节 |
| `raw_provenance[].recorded_sha1/matches_recorded/present` | `raw.files_sha1` 的值 | 让「原始件此刻还对不对得上证据自己的表」在 bundle 里就是事实 |
| `source_run_dir` | `raw.run_artifacts.run_dir` | **仓相对 posix**：`.superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/20260924-215206`。加它的原因是实测发现同目录里有**同名彩排件**（见 findings 7），只给 basename 会让 3B 无法唯一定位被指纹过的那一枚；`run_artifacts` 没记时写 null |
| `absent_source_fields` | —（诚实清单） | 原始件没有、因此写成 null 的字段 |

**manifest 不在 `portable_files` 里**：一件东西不可能给自己算 sha256（自指）。所以 manifest 是载体、
五枚载荷件是被验对象；3B 若让闸采信 bundle，逐条验的就是这五条。这是刻意的设计决定，不是漏项。

## 原始件里没有、因此写成 null 的字段（绝不发明）

| 字段 | 检查过的指针 | 写成 | 依据（当场实测，不是推断） |
| --- | --- | --- | --- |
| `release_image` | raw 与 probe 的**全部**递归键名（含 `environment` / `environment.before` / `environment.after` / `answer` / `ledger.row` / `plan`），按 `image` / `release` / `container` 三枚词干筛；再按值筛 `docker` / `image` / `sha256:` | `null` | 递归扫两枚原始件：键名命中 = `（无）`，值命中 = `（无）`。本轮跑的是**宿主 Ollama**（`environment.before.base_url = http://localhost:11434`），不存在镜像这件事 ⇒ 不造一个名字 |
| `trace_id`（**顶层键**） | raw 顶层 | manifest 写的是取自 `trace.trace_id` 的真实值，不是 null | `"trace_id" in raw` 实测 = `False`：**顶层不是 null，而是键本身不存在**（简报叙述说的是「顶层 trace_id: null」，与实测不符，以实测为准）。值另有三处同源指针，读数 4 已核对逐字符一致 |
| `provider_transport`（`response.json`） | `raw.provider_transport` | `null`（原样带出） | 键存在、值就是 `None`——这是原始件自己的记录，不是导出脚本缺字段 |
| `ledger.row.ttft_ms` / `status_code` / `error_type` | `raw.ledger.row.*` | `null`（原样带出） | 同上：raw 里就是 null，`row` 逐列原样 |
| `probe.probe.answer_content` | `probe.probe.answer_content` | `null`（原样带出） | primary 那一次真没答出来（500），raw 里就是 null |

一句结论：这五处 null 全是原始件自己的形状，导出脚本一个字段都没圆。真正的证据面缺口只有一条——
`release_image` 当时没被记录（P0 跑宿主 Ollama，无镜像事实），交回控制器裁：要么在 3B 之后要求采集器
把运行形态（宿主 / 容器）显式记进证据，要么在矩阵与闸的口径里写明「本 case 无镜像字段」。

## 读数 6：SEC-A 扫描门与 P0 闸复跑（本步**不新增任何红**）

两枚模块同跑（cwd=`E:\xiangmu\rag\backend`）：

```
$ python -m pytest tests/test_real_llm_failover_gate.py tests/test_secret_hygiene_contract.py -q -p no:cacheprovider --tb=line
............................................................. [100%]
61 passed, 11 subtests passed in 38.20s
```

逐枚拆开取数（同一条命令分两次跑）：

```
tests/test_secret_hygiene_contract.py  →  46 passed in 140.16s (0:02:20)      ← 简报要求的 46 枚，原样
tests/test_real_llm_failover_gate.py   →  15 passed, 11 subtests passed in 6.72s
```

顺带把 B0 的行尾/收集数那两枚模块也跑了（我改了 `real_llm_failover_kit.py`，而闸①会扫它的源码面）：

```
tests/test_ci_gate_contract.py + tests/test_llm_egress_guard.py
→ 51 passed, 92 subtests passed in 48.39s
```

SECA-20 扫描面读数（用扫描门自己的 `_delivery_surface_names()` / `_hit_counts()`，不另起口径）：

```
扫描面文件数 = 407
命中文件数 = 16 | 命中处数 = 31
bundle 贡献的命中 = （0 枚、0 处）
面里是否已含六枚 bundle 文件：
    docs/evidence/model-router-v23/real-llm-failover-001/ledger-row.json 命中处数= 0
    docs/evidence/model-router-v23/real-llm-failover-001/manifest.json 命中处数= 0
    docs/evidence/model-router-v23/real-llm-failover-001/primary-probe.json 命中处数= 0
    docs/evidence/model-router-v23/real-llm-failover-001/response.json 命中处数= 0
    docs/evidence/model-router-v23/real-llm-failover-001/result.json 命中处数= 0
    docs/evidence/model-router-v23/real-llm-failover-001/trace-attempts.json 命中处数= 0
```

⇒ 面数照涨（允许），**命中仍是 16 文件 / 31 处**；六枚新件（含真机响应文本与 primary 的 500 错误体原文）
**零命中** ⇒ 没有触发「停下报告」的那条线，也没有加豁免行、没有改文案规避。

关于「P0 闸仍红」：**本机读到的是 15 passed（绿）**，原因不是判据变了，而是这台机器上四枚原始件仍在、
sha1 仍对得上（读数 1）。判据未变这件事用 diff 证明，而不是用话讲：`real_llm_failover_kit.py` 相对
pristine 是 **0 行删除 / 476 行新增**，`validate_evidence()` 的函数体一字未动。
干净签出必然红这一点，用同一份判据在**仓外 temp** 模拟过（只把 `files_sha1` 的键换成签出里不存在的路径，
盘上一个文件都没挪）：

```
本机（四枚原始件在场）validate_evidence 问题清单 = （空 ⇒ 证据成立）
干净签出模拟：
    sha1 对不上：C:\clean-checkout\conversations.db（表里 b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1，盘上 <missing>）
    sha1 对不上：C:\clean-checkout\agent_traces.jsonl（表里 356826f73d7c9f8a839a7089f77d023f7feef21f，盘上 <missing>）
    sha1 对不上：C:\clean-checkout\ornith-primary-load-probe.json（表里 961985e87a275677bfa23fa02f3eef6f7cd51380，盘上 <missing>）
    sha1 对不上：C:\clean-checkout\test_real_llm_failover_acceptance.py（表里 da92cdf51de5dbfad3107f1dc744d18e4173e07c，盘上 <missing>）
⇒ sha1 类问题数 = 4
```

（真实干净签出里 `test_real_llm_failover_acceptance.py` 是被跟踪的、能对上的那一枚，所以实际是**三枚 missing**；
上面这条模拟把四枚一并换成不存在的路径，为的是证明「missing 就会红」这条判据本身没被我说动。）
远端主门那条 P0 红的消解属于 3B：3A 只交付「能被重算」的载体。

## 读数 7：全量套件收集数不变

```
$ python -m pytest --collect-only -q -p no:cacheprovider
...
1335 tests collected in 35.58s
```

⇒ 与 `EXPECTED_COLLECTED = 1335` 一致：**没有新增测试**，没有动那枚钉。

## 补充取数（简报七条之外，为「机械导出」这句话负责）

**A. 可重放**：同一函数、固定 `generated_at` 跑两遍 ⇒ 六枚文本逐字节相同。

```
   identical = True | files = 6
```

**B. 逐字段回指原始 JSON**：18 组等值断言，17 组 OK，唯一一条不相等的是**刻意**的绝对路径降级——

```
   FAIL result.assertions == raw.assertions
```

差在哪一行，当场逐行 diff 出来了（只有这一处）：

```
assertion id 8 usage_row_landed differs
    -  "ledger_path": "E:\\xiangmu\\rag\\.superpowers\\sdd\\MODEL_ROUTER_V23_PLAN\\task10\\run\\20260924-215206\\conversations.db",
    +  "ledger_path": "conversations.db",
```

**C. 全部被降级的指针（除上一条外，bundle 里没有第二处「值不等于 raw」**）：

```
    manifest.environment ← raw.environment（probe_reference 压成 basename）
    manifest.config_overrides ← raw.config_overrides（llm_registry_file 压成 basename）
    ledger_source.path_basename ← raw.ledger.path（basename）
    trace_source.path_basename ← raw.trace.path（basename）
    manifest.registry_file ← raw.registry_file（仓相对 posix）
    result.assertions[8].observed.ledger_path ← raw（basename，见 B）
```

**D. 键的降级形状**（`protected_repo_ledgers` 是唯一需要仓相对而不是 basename 的键，因为两枚 basename 同名）：

```
   raw 原键 = ['E:\\xiangmu\\rag\\backend\\data\\conversations.db', 'E:\\xiangmu\\rag\\data\\conversations.db']
   bundle 键 = ['backend/data/conversations.db', 'data/conversations.db']
```

**E. 原始件自身的行尾事实**（与 bundle 的 LF-only 口径不同，值得记一笔，免得 3B 误读）：

```
  real-llm-failover-001.json   bytes 18289 CR 569 LF 569   ← 原始证据是 **CRLF**（write_json 走文本模式）
  ornith-primary-load-probe.json bytes 3010 CR 103 LF 103  ← 同上
  real_llm_failover_kit.py     CR 0     ← 代码件一直 LF
```
⇒ bundle 六枚是 `CR=0`；`write_portable_bundle()` 用 `write_bytes` 落盘（`write_text` 在 Windows 会把 `\n` 换成 CRLF）。
`raw_provenance` 记的是**原始件的 sha1**，与行尾无关，所以这条不影响 provenance 的可重算性。

## 交回控制器的 findings

1. **`release_image` 当时没被记录**（键不存在，不是 null）。P0 跑的是宿主 Ollama ⇒ 没有镜像这一事实。
   manifest 写 `null` 并随件带出 `absent_source_fields`。要么 3B 之后让采集器把运行形态显式记进证据，
   要么在闸/矩阵口径里写明「本 case 无镜像字段」。**不批准**为了让 manifest 好看而编一个镜像名。
2. **简报说「顶层 `trace_id: null`」，实测是顶层根本没有 `trace_id` 这枚键**（`"trace_id" in raw` = False）。
   值取自 `trace.trace_id`，并与 `ledger.row.trace_id`、`request.trace_id` 三处同源核对一致（读数 4）。
   这条差异只影响「怎么描述缺口」，不影响导出结果。
3. **本机 P0 闸读到的是绿**（四枚原始件在场、sha1 MATCH）。恒红发生在干净签出/远端；
   本步按裁定只换载体，判据一字未动 ⇒ 远端那条 P0 红**不会**因为这一步变绿，也不会变得更红。
4. **manifest 不在 `portable_files` 里**（自指 hash 不可能）。3B 采信 bundle 时，逐条重算的是这五条 +
   manifest 的声明；如果 3B 想要「连 manifest 一起可验」，得引入外部锚（例如把 manifest 的 sha256
   写进矩阵或 CI 变量），那是 3B 的裁定，不是 3A 能替它决定的。
5. **`exported_by.source_basenames` 含 5 枚**（原始证据 JSON + probe + 三枚 `files_sha1` 里的件 +
   acceptance 模块），而 `raw_provenance` 只有 4 枚（严格按简报的四枚 role）。差的那一枚是证据 JSON 自己——
   它不在 `files_sha1` 里（原始件刻意不自指纹，见 `sha1_scope_note`），所以它只作为「读了什么」出现，
   不进 provenance。
6. **提交面提示**（不代控制器动手）：六枚新文件目前 untracked，已被 `--others` 纳入 SECA-20 扫描面且 0 命中；
   内容是纯 LF ⇒ `git add` 之后在 `git ls-files --eol` 上是 `i/lf`，不会新增 `i/-text`，
   撞上 B0 §6.4 那枚枚举钉的风险为零（那枚钉看的是跟踪面，本轮跟踪面一字未动）。

## 读数 3 的口径补正 + 导出后补的一枚字段

### A. 重算必须锚在仓库根，不能锚在 cwd

我自己踩了一次就记下来：同一份 manifest，以 `backend/` 为 cwd 裸开 `portable_files[].path` 会得到五枚
`<missing>`（第一版补测打印 `DIFFER ×5`），因为 `portable_files.path` 是**仓相对 posix**。三种锚法当场各跑一遍：

```
A) 以仓库根为 cwd 直接打开仓相对 path：
    EQUAL docs/evidence/model-router-v23/real-llm-failover-001/result.json
    EQUAL docs/evidence/model-router-v23/real-llm-failover-001/response.json
    EQUAL docs/evidence/model-router-v23/real-llm-failover-001/ledger-row.json
    EQUAL docs/evidence/model-router-v23/real-llm-failover-001/trace-attempts.json
    EQUAL docs/evidence/model-router-v23/real-llm-failover-001/primary-probe.json
B) 以 manifest 自身位置为锚（不依赖 cwd）：
    EQUAL ×5（同上五行逐枚相等）
C) 以 backend/ 为 cwd 时：裸用仓相对 path 打不开的文件 = 5 枚
```

⇒ 读数 3 的「全部相等」是在口径 A/B（正确锚法）下取的；口径 C 的 DIFFER 是**路径锚点**问题，不是字节问题。
**3B 的闸要按 A 或 B 解析**（推荐 B：以 manifest 自己的位置为锚，与 pytest 的 cwd 无关——B0 的两格读数
本来就分别在 `E:\xiangmu\rag` 与 `E:\xiangmu\rag\backend` 跑）。这条判据不由 3A 替 3B 定，只把坑标出来。

### B. 导出后的独立复核，顺手发现一枚真问题

复核脚本故意**不看 manifest 里的绝对路径**，只在 `task10/**` 与 `backend/tests/**` 里按 basename 定位后重算：

```
raw_provenance 盘上重算：
   MATCH trace_jsonl       agent_traces.jsonl                     356826f73d7c9f8a839a7089f77d023f7feef21f bytes=845
   MATCH ledger_db         conversations.db                       b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1 bytes=16384
   MATCH primary_probe     ornith-primary-load-probe.json         961985e87a275677bfa23fa02f3eef6f7cd51380 bytes=3010
   MATCH acceptance_module test_real_llm_failover_acceptance.py   da92cdf51de5dbfad3107f1dc744d18e4173e07c bytes=40517
⇒ 四枚全部 MATCH = True
```

但同一枚脚本的第一次运行里还打印出两枚**同名不同摘要**的彩排件（这是原始目录里的真实形状）：

```
  = manifest 记的那枚        961985e87a275677bfa23fa02f3eef6f7cd51380 ornith-primary-load-probe.json  task10/ornith-primary-load-probe.json
  ≠ 同名彩排件                d3cfc8b56c6f3c8ca7d224618194b4b611f255ed agent_traces.jsonl            task10/rehearsal/run/20260924-214030/agent_traces.jsonl
  ≠ 同名彩排件                d981c1676ed13d1f78ad237512d5b63c8a598274 conversations.db              task10/rehearsal/run/20260924-214030/conversations.db
  = manifest 记的那枚        356826f73d7c9f8a839a7089f77d023f7feef21f agent_traces.jsonl            task10/run/20260924-215206/agent_traces.jsonl
  = manifest 记的那枚        b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1 conversations.db              task10/run/20260924-215206/conversations.db
```

⇒ 只给 basename 的 `raw_provenance` 在**本机**不能唯一定位被指纹过的那一枚（`rehearsal/` 里躺着同名的、
sha1 不同的彩排件）。裁定说「只留 basename + hash」，我没违反它，也没让 3B 去猜：补记一枚
`source_run_dir`（← `raw.run_artifacts.run_dir`，仓相对 posix），把这四枚件所在的 run 目录钉死。

```
source_run_dir = .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/20260924-215206
```

### C. 补这枚字段之后重导一次，并复验受影响的面

`source_run_dir` 只进 manifest，所以五枚载荷件的字节**一枚都没变**（读数 2/3/4/5 的表仍然成立）：

```
字节未变的载荷件 = ['ledger-row.json', 'primary-probe.json', 'response.json', 'result.json', 'trace-attempts.json']
变化的件 = ['manifest.json']
```

末次导出后的**全套复验**（对最终交付的六枚再取一遍，`manifest.json` 由 6774 B 长成 6863 B）：

```
   result.json          bytes= 8150 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
   response.json        bytes= 2505 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
   ledger-row.json      bytes= 2117 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
   trace-attempts.json  bytes= 1326 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
   primary-probe.json   bytes= 3160 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
   manifest.json        bytes= 6863 CR=0 endsLF=True json.loads=OK  drive-path-hits=0
    EQUAL result.json / EQUAL response.json / EQUAL ledger-row.json / EQUAL trace-attempts.json / EQUAL primary-probe.json
   trace_id 三处 = True
   十枚 = True
   source_run_dir = .superpowers/sdd/MODEL_ROUTER_V23_PLAN/task10/run/20260924-215206 | raw_provenance MATCH ×4 = True
   非 docstring 字符串命中行 =（无）          ← 闸①扫 kit 的源码面
   面文件数 = 407 | 命中文件 = 16 | 命中处数 = 31
   bundle + kit 命中 =（0）
```

补完字段后复跑的两枚门（读数以 `---- COLLECT ----` 之后那条为准）：

```
$ pytest tests/test_secret_hygiene_contract.py -k "tracked_files or exemption_table"
2 passed, 44 deselected in 1.69s
$ pytest tests/test_real_llm_failover_gate.py
15 passed, 11 subtests passed in 9.24s
```

### D. 原始件自身的行尾事实（与 bundle 的 LF-only 不同，别误读）

```
  real-llm-failover-001.json     bytes 18289 CR 569 LF 569   ← 原始证据是 **CRLF**（write_json 走文本模式）
  ornith-primary-load-probe.json bytes  3010 CR 103 LF 103   ← 同上
  real_llm_failover_kit.py       CR 0                        ← 代码件一直 LF
```
⇒ bundle 六枚是 `CR=0`；`write_portable_bundle()` 用 `write_bytes` 落盘（`write_text` 在 Windows 会把 `\n`
换成 CRLF，那正是本包要避免的）。`raw_provenance` 记的是原始件的 **sha1**，与行尾无关，
所以这条不影响 provenance 的可重算性；但如果 3B 想让原始件也入库，那两枚 CRLF 会立刻撞上 B0 的 `i/crlf=0`——
这也是「本体不入库、只导文本投影」这一裁定的另一条理由。

## 真跑路径能调用它（不靠嘴上说）

裁定要求「让真机 runner 在跑完一次验收后调用它」。我没有真跑一次验收（那要真加载 phi3、还会改写原始件），
而是把 runner `[4/4]` 那枚 heredoc **逐字抽出来当场执行**（51 行，`ast.parse` 过、`bash -n` 过），
证明这段真跑时代码确实会走到导出并落盘：

```
执行 runner [4/4] 段逐字（长度 51 行）——它内部会调 kit.write_portable_bundle
...
可移植证据包（3A：只换载体，判据一字未改）：
  generated_at=2026-09-28T16:19:52+00:00  source_run_generated_at=2026-09-24T13:52:06+00:00
  trace_id=p0-failover-6146ff1417d7  source_tree_hash=7923ee47955197406ee0dd498f74587d8915a7d8  release_image=None
  ca9f7a4e22e615c6cf648b3f05fc00d9e85ef1dc02dc4f3962399444bc55b247     8150B  docs/evidence/model-router-v23/real-llm-failover-001/result.json
  ...（其余四枚同批打印）
  raw trace_jsonl       sha1=356826f73d7c9f8a839a7089f77d023f7feef21f bytes=845 对得上记录值=True
  raw ledger_db         sha1=b93ce392a1d7c4c1c9aa89ff81e852f4643ef0b1 bytes=16384 对得上记录值=True
  raw primary_probe     sha1=961985e87a275677bfa23fa02f3eef6f7cd51380 bytes=3010 对得上记录值=True
  raw acceptance_module sha1=da92cdf51de5dbfad3107f1dc744d18e4173e07c bytes=40517 对得上记录值=True
矩阵改 GREEN 的许可条件（当前状态 GREEN）：
  [满足] 证据 JSON 存在于约定路径 ...
  [满足] 证据内部自洽（10 枚断言各自带实测值） ...
  [满足] 矩阵 P0 行当前状态 ∈ {BLOCKED, GREEN} ...
green_permitted_by_evidence = False
>>> 该段以 sys.exit(1) 结束（本机矩阵已是 GREEN ⇒ green_permitted_by_evidence=False，属 3B 的判定，不改）
```

⇒ 五枚载荷件的 sha256 与读数 3 完全相同（真跑路径产出的字节与手工回导一致，可重放）；
runner 的退出码语义没被本步动过（`green_permitted_by_evidence` 的算法原样，矩阵仍是 GREEN）。
交付件的 `generated_at` 就是这一轮写进去的 `2026-09-28T16:19:52+00:00`。

末次全量复跑（补完 `source_run_dir`、并跑过上面那段之后的最终态）：

```
$ pytest tests/test_secret_hygiene_contract.py -q
46 passed in 35.32s                                  ← 简报要求的 46 枚，末次复跑仍是 46
$ pytest tests/test_real_llm_failover_gate.py -q
15 passed, 11 subtests passed in 9.24s
$ pytest --collect-only -q
1335 tests collected in 69.45s
$ pytest tests/test_secret_hygiene_contract.py -k "tracked_files or exemption_table"
2 passed, 44 deselected in 1.69s                     ← 命中集与豁免表互等那两枚
```

## 终态一览（对最终交付的六枚 + 两处代码改动）

| 简报验收条 | 读数 | 结论 |
| --- | --- | --- |
| 1 四枚原始件 sha1 | MATCH ×4（`b93ce392…` / `356826f7…` / `961985e8…` / `da92cdf5…`），两枚实现各算一遍 | ✅ |
| 2 六枚存在 / LF / 可解析 / 无绝对路径 | `CR=0` ×6、`json.loads` ×6、`E:` / `C:` / `[a-z]:\` / 盘符正则命中 = 0 | ✅ |
| 3 `portable_files` sha256 独立重算 | EQUAL ×5（含 bytes 相等），锚法见《读数 3 的口径补正》 | ✅ |
| 4 `trace_id` 三处逐字符 | `p0-failover-6146ff1417d7`：manifest / trace-attempts / ledger-row 相等，且与 raw 三指针相等 | ✅ |
| 5 十枚断言 | 条数 10、逐枚 `pass=true`、`observed` 非空、名字合 §10 常量表 | ✅ |
| 6 两枚模块复跑 | hygiene 全模块 **46 passed**（首格 140.16s、末格 35.32s）、P0 闸 **15 passed + 11 subtests**、ci-gate+egress **51 passed + 92 subtests**、零新增红；SECA-20 面 407 文件 / **16 命中文件 / 31 处**（bundle + kit 贡献 0） | ✅ |
| 7 全量 `--collect-only` | 首格 **1335 tests collected in 35.58s**、改字段后复格 **1335 tests collected in 69.45s** = `EXPECTED_COLLECTED` | ✅ |

改动面（工作树，未提交、零 git 写命令；只用过 `git show` / `git ls-files` / `git rev-parse` / `git status` 这些读面）：

```
 M .superpowers/scripts/run_p0_failover_acceptance.sh   bytes 9645  CR 0   （[4/4] 调 write_portable_bundle + 抬头「四件事」）
 M backend/tests/real_llm_failover_kit.py              bytes 68492  CR 0   （新增 §7：0 行删除 / 481 行新增）
?? docs/evidence/                                       六枚 bundle 文件，纯 LF，SECA-20 面上 0 命中
```

其余 `M` / `??` 条目（`backend/app/identity/*`、`test_ci_gate_contract.py`、`test_feishu_identity_contract.py`、
`docs/SECURITY_A_*`、`progress.md`、`baseline/`、`mutations/`）是本轮开工前就在工作树里的既有改动，本步未触碰。
临时件已清：`output/p0-3a-gate-run.txt` 与三枚 chunk 文件都删了，仓库里除六枚证据件与两处代码改动外无残留。

## 交回控制器的 findings（续：7 / 8 / 9）

7. **`raw_provenance` 只给 basename 在本机不能唯一定位**：`task10/rehearsal/run/20260924-214030/` 里躺着
   同名的 `conversations.db`（`d981c1676ed1…`）与 `agent_traces.jsonl`（`d3cfc8b56c6f…`），sha1 与
   被指纹过的那两枚**不同**。已按裁定处理：不动 `raw_provenance` 的字段形状，另补一枚
   `source_run_dir`（仓相对）把 run 目录钉死。3B 若要按 provenance 逐枚重算，请用
   `source_run_dir + name`，不要用全盘 `rglob(name)`——那会先把彩排件捞进来。
8. **原始件是 CRLF，bundle 是 LF**（见《D. 原始件自身的行尾事实》）。这正印证「本体不入库、只导文本投影」：
   那两枚原始 JSON 若被 `git add`，`i/crlf` 会立刻撞上 B0 行尾枚举钉。3B 别把「bundle 干净」误读成
   「原始件也干净」。
9. **`write_portable_bundle()` 在 runner 里是硬调用**（不 try/except）：docs 写不进去就当红。
   理由是「导不出证据」和「证据不成立」都该让第一现场看见；但如果控制器希望真跑成功时 bundle 失败
   不阻塞判据，那要把这枚调用改成打印告警后继续——那是判据外的取舍，我没有替 3B 决定。

## 一句话交付

六枚 bundle 文件已经在 `docs/evidence/model-router-v23/real-llm-failover-001/`，
每条 `portable_files` 的 sha256 都能用仓相对路径独立重算并对上，四枚原始件的 sha1 当场 MATCH；
`release_image` 因为原始件没有这枚事实而写成 `null`（连同 `absent_source_fields` 一起随件带出）；
`validate_evidence()` 与 P0 闸的判定语义一字未动，收集数仍 1335，SECA-20 仍 16 文件 / 31 处，无新增红。
