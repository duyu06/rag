"""REAL-LLM-FAILOVER-001 的共享件：开关、现场探针、证据采集与「矩阵改 GREEN 的许可」校验。

为什么单独一枚模块（而不是把代码塞进用例里）
------------------------------------------
同一份事实有三处消费者，它们必须**逐字**同意：

1. `tests/test_real_llm_failover_acceptance.py`（P0 用例本体）跑完真机后按这里的 schema
   写证据 JSON；
2. `tests/test_real_llm_failover_gate.py`（A-1 反造假闸）用 `validate_evidence()` 决定
   「矩阵 P0 行今天有没有资格是 GREEN」；
3. `.superpowers/scripts/run_p0_failover_acceptance.sh`（A-4 一键 runner）在跑之前用
   `probe_primary_load()` / `memory_facts()` 做环境前置，跑之后用 `green_permission()`
   打印许可结论。

三处共用一份实现 ⇒ 「采集器说绿、闸说没证据、runner 说可以改矩阵」这种三方各说各话
从结构上就不可能出现。

本模块**不 import 任何测试框架、不发任何模型请求**（除了 `probe_primary_load()` 那一枚
显式调用的有界探针），所以被闸用例在被收集阶段就能安全 import。

诚实边界（写在脸上，不许后来人误解）
----------------------------------
- `probe_primary_load()` 用 stdlib `urllib` 直连 Ollama，**不是**走 `app/llm/provider.py`。
  它是「现场取证」不是「产品链路」：产品链路的出口唯一性由 D6 扫描守（那一张扫描面是
  `app/`，不含 `tests/`）。本文件的 URL 字面量因此不会、也不该被读成第二条业务出口。
- `request_bytes` 是**用真适配器重建**的报文长度（`PROVIDERS[provider].payload(...)`），
  不是 wire 抓包；证据里带着 `request_bytes_method` 说明这一点。
- `validate_evidence()` 会**重新 sha1 盘上的文件**并逐枚比对 `files_sha1`。所以「手抄一份
  JSON 声称跑过」在文件层面就会被抓住——但真正的不可伪造性来自「phi3 的中文答案只能真生成
  出来」，sha1 只是防篡改的第二道。
- §5.5 的**登录凭据接缝**（`install_login_credential_seam()`）是 SEC-A Task 10f 登记的
  harness 侧垫脚：它包 `usage.init_usage_db`，只在那枚开关（`acceptance_enabled()`）打开时
  装上，开关不合时对 `app.llm.usage` 一个字节都不碰。它是「测试怎么造出凭据行」这件事，
  不是「产品怎么造出凭据行」——§8.2 的设计（生产代码永不自动造凭据行）由
  `tests/test_security_a_closure.py` 的负向对照继续钉住，接缝**没有**把它放宽。
  所有 import 都在函数体内（与 `repo_ledger_row_counts()` 借 conftest 同一手法），
  所以本模块在收集阶段被 import 时仍然零副作用。
- §7 的**可移植证据包**（`build_portable_bundle()` / `write_portable_bundle()`，
  P0-EVIDENCE-PORTABILITY 3A）只做一件事：把上面那份原始证据 JSON 与 A-2 探针件
  **机械投影**成 `docs/evidence/` 下六枚文本件，让干净签出能逐文件重算 sha256。
  它**不判 GREEN、不改矩阵、不碰 `validate_evidence()`**：3A 换的是载体，判据归 3B。
  原始件（`.db` / `.jsonl` / 探针）仍留在 ignored 目录里，bundle 只带它们的
  basename + sha1，且任何绝对路径都不进导出件（单机耦合正是这次闸恒红的病根）。
- §8 的**可移植层判据**（`validate_portable_bundle()` / `p0_evidence_verdict()`，同一条修正的
  3B）把「矩阵 P0 行有没有资格 GREEN」拆成两层：**portable 层无条件必须过**（干净签出唯一
  能重算的一层，七条 interlock + 从 §6 搬过来的逐条判据），**raw 层只在原始件按
  `manifest.source_run_dir` + `raw_provenance[].sha1` 双条件定位得到时才跑**。
  §6 `validate_evidence()` 的判据本体一字未改；改的只是「哪一层在什么形态下负责」。
  语义边界由 R26 第 ③ 条钉死：raw 不在场不影响 portable 的判定，portable 缺失/畸形/hash
  不配 ⇒ 闸要求 `BLOCKED`。原始件的定位规矩也写死在这里——**绝不按 basename 或字节大小找**，
  因为 `task10/rehearsal/run/…` 里有同名同字节、sha1 不同的彩排件。
- §8 的分层在 **3B 修复轮 1（台账 R27 的四条点名条款）** 收成三条腿，一条都不再随
  运行态本体的缺席而静默下线：
  · **portable 层**（`validate_portable_bundle`）—— 无条件必须过，另加 `source_run_flags`
    五枚布尔位与 `raw_provenance[].git_blob` 两段新载体（H1/H2/M1 的载体侧）；
  · **`[T-*]` 真值层**（`tracked_evidence_truth_problems`）—— 无条件必须过，读的是**已跟踪的
    原始证据 JSON**：`rehearsal` 真值、`completed is True`、`provider_transport` **键在场且为
    null**（成员判定，不是 `.get()`）。这三枚过去只长在 §6 里，而 §6 被条件成「四枚本体
    都在场才跑」⇒ 干净签出（CI 形态）里一枚都不执行，这是评审测出来的 H1/H2；
  · **raw 层**分两半：provenance + **git blob 腿**（`raw_layer_problems` / `blob_leg_problems`）
    在 `full` 与 `json-only` **两条分支都跑**（M1：过去全有或全无，「篡改一枚 + 缺席另一枚」
    会静默放过），§6 `validate_evidence()` 那一半仍只在 `full` 跑（它的对象确实没入库）。
    被 git 跟踪的那枚 `acceptance_module` 改按 **blob 身份**而不是工作树字节的 sha1 判定：
    blob 相等与签出 EOL 形态无关，本机与 CI 因此拿到同一条真重算腿。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import platform
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

TESTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

# ==========================================================================
# 1. 冻结常量
# ==========================================================================
#: A-1 闸②点名的**唯一**收集开关。默认关闭 ⇒ P0 例不被收集（不是 skipped）。
ENV_SWITCH = "REAL_LLM_ACCEPTANCE"
SWITCH_ON = "1"

ACCEPTANCE_FILE = TESTS_DIR / "test_real_llm_failover_acceptance.py"
GATE_FILE = TESTS_DIR / "test_real_llm_failover_gate.py"
MATRIX_DOC = REPO_ROOT / "docs" / "MODEL_ROUTER_V23_MATRIX.md"

#: 证据落在 SDD 目录（与 task-10 报告同级），**绝不**落在 `backend/data/`。
EVIDENCE_DIR = REPO_ROOT / ".superpowers" / "sdd" / "MODEL_ROUTER_V23_PLAN" / "task10"
PROBE_FILE = EVIDENCE_DIR / "ornith-primary-load-probe.json"
EVIDENCE_FILE = EVIDENCE_DIR / "real-llm-failover-001.json"

CASE_ID = "REAL-LLM-FAILOVER-001"
SCHEMA_VERSION = 1

#: 注册表条目 id 与生效模型名（`config/llm_registry.json` 出厂值，本用例**只读**不改）。
PRIMARY_ENTRY_ID = "ollama-ornith"
PRIMARY_MODEL = "ornith-1.5:9b-text"
FALLBACK_ENTRY_ID = "ollama-phi3"
FALLBACK_MODEL = "phi3:mini"

#: §10 P0 行的十枚断言（**逐字**对应 DESIGN §10 P0 那一行的十字，顺序即编号）。
ASSERTION_NAMES: tuple[tuple[int, str, str], ...] = (
    (1, "primary_really_called", "primary 真被调用"),
    (2, "failure_classified_model_unavailable", "失败归类 model_unavailable"),
    (3, "fallback_called", "fallback 被调"),
    (4, "phi3_valid_chinese_answer", "phi3 给出有效中文回答"),
    (5, "fallback_index_is_one", "fallback_index==1"),
    (6, "trace_id_consistent", "trace_id 全链一致"),
    (7, "model_route_two_attempts", "model_route 两枚 attempt"),
    (8, "usage_row_landed", "usage 落库一行"),
    (9, "zero_prompt_stored", "零 prompt 入库"),
    (10, "api_face_is_200", "API 面 200 语义"),
)

#: 探针文案（A-2 专用；与 P0 的 prompt 无关，canary 不参与）。
PROBE_PROMPT = "Reply with exactly one word: pong"
#: P0 的 prompt canary：出现在真 prompt 里，账本任何一枚单元格都不许含它。
PROMPT_CANARY = "CANARY-9c1f4e7a-6b0d-4e2f-8a13-zhengju"
#: 「有效中文回答」的下限：刻意给得**保守**（phi3:mini 是真的会只回一句），
#: 上限不设（真生成的长度不可预测）。§6 与 §8 同一份。
MIN_ANSWER_CHARS = 8
MIN_ANSWER_CJK_CHARS = 4
#: §6「文档化的加载失败族」的特征字面（**唯一出处**）。3B 把 `validate_evidence()` 里那枚
#: inline 元组提到这里、字面一字未改，为的是 portable 层（§8）与 raw 层（§6）不可能各写一套
#: 「什么算真加载失败」——两处读同一枚常量，才是「原文要求一字不松」的机器保证。
MODEL_UNAVAILABLE_MARKERS: tuple[str, ...] = ("alloc", "failed to load", "not found",
                                             "no such model")

#: 真加载 phi3:mini（2.18 GB）+ 真加载失败 ornith 的余量。spec 允许几分钟，
#: 所以这里给的是**秒**级的宽松门，不是「跑得快」的假设。
REAL_CALL_TIMEOUT_SECONDS = 900
#: A-2 探针的硬上限（brief 冻结：整体 ≤120 秒，失败就停）。
PROBE_TIMEOUT_SECONDS = 120

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


# ==========================================================================
# 2. 开关与环境
# ==========================================================================
def acceptance_enabled(environ: dict[str, str] | None = None) -> bool:
    """收集开关：**只**读 `ENV_SWITCH` 这一枚 env（值必须恰好是 `"1"`）。

    闸②要求「门只能是一枚显式 env 开关」，所以本函数不许长出第二个条件。
    """
    source = os.environ if environ is None else environ
    return source.get(ENV_SWITCH, "") == SWITCH_ON


def default_ollama_base_url(environ: dict[str, str] | None = None) -> str:
    """探针/前置要打的 base url：**优先问产品自己**（`settings.ollama_base_url`）。

    顺序 = `OLLAMA_BASE_URL` env → `app.config.settings.ollama_base_url`（含 `backend/.env`
    的现网值）→ `http://127.0.0.1:11434`。为什么不是只看 env：真链路走的是 settings，
    探针打的必须**是同一条腿**，否则「现场证据」描述的是另一个 server。
    """
    source = os.environ if environ is None else environ
    url = source.get("OLLAMA_BASE_URL")
    if not url:
        try:
            from app.config import settings

            url = str(settings.ollama_base_url or "")
        except Exception:                                   # noqa: BLE001 - 退回硬默认
            url = ""
    return (url or "http://127.0.0.1:11434").rstrip("/")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: 判定线：phi3:mini 权重 2.18 GB + 运行时 KV/宿主开销的最低余量。
#: 低于这条线时 runner 只会**打印**警告并拒绝继续（`--yes` 才放行），不改任何判定口径。
#: 量不到内存的平台（探针/采集器仍可跑）记 `enough_for_phi3=False` + `verdict` 说明「未知」，
#: 宁可让 runner 多问一句，也不许把「没测到」读成「够」。
PHI3_LOAD_FLOOR_GIB = 3.2


def memory_facts() -> dict[str, Any]:
    """可用物理内存（GB）+ 一句「够不够装 phi3:mini」的判定。"""
    facts: dict[str, Any] = {"platform": platform.system(), "total_gib": None,
                             "available_gib": None, "memory_load_percent": None}
    if facts["platform"] == "Windows":
        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.wintypes.DWORD),
                ("dwMemoryLoad", ctypes.wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            gib = float(1 << 30)
            facts["total_gib"] = round(status.ullTotalPhys / gib, 2)
            facts["available_gib"] = round(status.ullAvailPhys / gib, 2)
            facts["memory_load_percent"] = int(status.dwMemoryLoad)
    else:
        try:
            info = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            avail = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_AVPHYS_PAGES")
            facts["total_gib"] = round(info / (1 << 30), 2)
            facts["available_gib"] = round(avail / (1 << 30), 2)
        except (ValueError, OSError, AttributeError):
            pass
    available = facts["available_gib"]
    facts["phi3_load_floor_gib"] = PHI3_LOAD_FLOOR_GIB
    facts["enough_for_phi3"] = bool(available is not None
                                    and available >= PHI3_LOAD_FLOOR_GIB)
    if available is None:
        facts["verdict"] = "未知：本机量不到物理内存 ⇒ runner 需要 --yes 才继续"
    elif facts["enough_for_phi3"]:
        facts["verdict"] = (f"够：可用 {available:.2f} GiB ≥ {PHI3_LOAD_FLOOR_GIB} GiB")
    else:
        facts["verdict"] = (f"不够：可用 {available:.2f} GiB < {PHI3_LOAD_FLOOR_GIB} GiB"
                            " ⇒ 加载 phi3:mini 有把机器打进 paging 的风险")
    return facts


# ==========================================================================
# 3. Ollama 现场：清单 / 已加载 / 有界加载探针
# ==========================================================================
def memory_check(samples: int = 3, interval_seconds: float = 1.5) -> dict[str, Any]:
    """**多次**采样可用内存再判定（本机实测会在 0.52 ↔ 3.46 GiB 之间跳）。

    单次快照做「够/不够」判定是不诚实的：读到高值就放行、读到低值就拒绝，两边都是噪声。
    取 `min()` ⇒ 只要采样窗口里出现过不够的时刻，runner 就要求 `--yes` 才继续。
    """
    taken: list[dict[str, Any]] = []
    for index in range(max(1, int(samples))):
        if index:
            time.sleep(interval_seconds)
        taken.append(memory_facts())
    values = [item["available_gib"] for item in taken if item["available_gib"] is not None]
    low = min(values) if values else None
    return {
        "samples": taken,
        "min_available_gib": low,
        "max_available_gib": max(values) if values else None,
        "phi3_load_floor_gib": PHI3_LOAD_FLOOR_GIB,
        "enough_for_phi3": bool(low is not None and low >= PHI3_LOAD_FLOOR_GIB),
        "verdict": ("够：{} 次采样的最低可用 {:.2f} GiB ≥ {:.1f} GiB".format(
                        len(taken), low or 0.0, PHI3_LOAD_FLOOR_GIB)
                    if low is not None and low >= PHI3_LOAD_FLOOR_GIB
                    else "不够（或量不到）：最低可用 {} GiB；真跑要 --yes 显式越权".format(
                        "未知" if low is None else f"{low:.2f}")),
    }


def _http_json(method: str, url: str, payload: dict | None = None,
               timeout: float = 10.0) -> Any:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def ollama_inventory(base_url: str | None = None, timeout: float = 10.0) -> dict[str, Any]:
    """`/api/tags` + `/api/ps`：跑 P0 之前的环境前置（条目在不在、有没有已加载模型）。

    连不上不抛异常，只如实记 `reachable=False`——runner 要拿它当判定输入，不是崩溃源。
    """
    root = (base_url or default_ollama_base_url()).rstrip("/")
    out: dict[str, Any] = {"base_url": root, "reachable": False, "tags": [], "loaded": [],
                           "error": None}
    try:
        tags = _http_json("GET", f"{root}/api/tags", timeout=timeout)
        out["tags"] = [{"name": m.get("name"), "size_gib": round(
            float(m.get("size") or 0) / (1 << 30), 2)} for m in tags.get("models", [])]
        loaded = _http_json("GET", f"{root}/api/ps", timeout=timeout)
        out["loaded"] = [m.get("name") for m in loaded.get("models", [])]
        out["reachable"] = True
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    names = {m["name"] for m in out["tags"]}
    out["has_primary"] = PRIMARY_MODEL in names
    out["has_fallback"] = FALLBACK_MODEL in names
    return out


def probe_primary_load(model: str = PRIMARY_MODEL, *,
                       base_url: str | None = None,
                       timeout_seconds: float = PROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """A-2：**一次**真实加载尝试，逐字记下原始状态码 / 错误体 / 耗时。

    形状按产品链路的出口报文构造（`ollama_payload` 的同形：`model/stream=false/
    keep_alive/messages/tools=[]/options{temperature,num_predict}`），但 `num_predict=1`
    + `keep_alive="0"` + 整体超时 ≤120 秒，失败就停——它的产出是**现场证据**，
    不是又一次业务外呼。返回的 dict 里 `raw_error_body` 是服务端回显的**原文**（截断前
    先把长度记下来），这是 T2 的 `model_unavailable` 归类今天是否仍然命中的唯一实据。
    """
    root = (base_url or default_ollama_base_url()).rstrip("/")
    url = f"{root}/api/chat"
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": "0",
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "tools": [],
        "options": {"temperature": 0.2, "num_predict": 1},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    record: dict[str, Any] = {
        "case_note": "A-2 有界探针：primary 的真实加载尝试（本机 Ollama，非 mock）",
        "model": model,
        "url": url,
        "request_bytes": len(body),
        "request_payload": payload,
        "timeout_seconds": timeout_seconds,
        "started_at": utc_now(),
        "status_code": None,
        "raw_error_body": None,
        "raw_error_body_chars": 0,
        "answer_content": None,
        "probe_result": "probe_failed",
        "classification": None,
        "elapsed_ms": None,
        "error": None,
    }
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            record["status_code"] = int(response.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        record["status_code"] = int(exc.code)
    except Exception as exc:                                  # noqa: BLE001 - 逐字记下即可
        record["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        record["error"] = f"{type(exc).__name__}: {exc}"
        return record
    record["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    record["raw_error_body_chars"] = len(raw)
    status = record["status_code"] or 0
    if 200 <= status < 300:
        record["probe_result"] = "loaded_ok"
        try:
            record["answer_content"] = json.loads(raw).get("message", {}).get("content")
        except ValueError:
            record["raw_error_body"] = raw[:2000]
    else:
        record["probe_result"] = "load_failed"
        record["raw_error_body"] = raw[:2000]
    # 归类走**真**实现（app.llm.errors），这样「探针命中 model_unavailable」才是
    # 「T2 的归类今天仍然命中」，而不是探针自己给自己打分。
    from app.llm import errors as llm_errors

    error = llm_errors.classify(status, raw)
    record["classification"] = None if error is None else {
        "kind": error.kind, "status_code": error.status_code,
        "no_fallback": error.no_fallback, "message": str(error)}
    return record


# ==========================================================================
# 4. 证据落盘与 sha1
# ==========================================================================
def ensure_evidence_dir() -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    return EVIDENCE_DIR


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    ensure_evidence_dir()
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                     sort_keys=False) + "\n", encoding="utf-8")
    return Path(path)


def sha1_of(path: Path | str) -> str:
    target = Path(path)
    if not target.is_file():
        return "<missing>"
    digest = hashlib.sha1()
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(paths: list[Path | str]) -> dict[str, str]:
    """{绝对路径: sha1}——证据里的「sha1 表」，`validate_evidence()` 会逐枚重算。"""
    return {str(Path(p).resolve()): sha1_of(p) for p in paths}   # noqa: C416


# ==========================================================================
# 5. 账本面（临时库）事实
# ==========================================================================
def ledger_rows(db_path: Path | str) -> list[dict[str, Any]]:
    """**只读**打开临时库，返回 `llm_request_logs` 全部行（表不存在 ⇒ 空列表）。"""
    target = Path(db_path)
    if not target.is_file():
        return []
    connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "llm_request_logs" not in tables:
            return []
        return [dict(row) for row in
                connection.execute("SELECT * FROM llm_request_logs ORDER BY id")]
    finally:
        connection.close()


def scan_cells(rows: list[dict[str, Any]], needles: list[str]) -> list[dict[str, Any]]:
    """逐枚单元格扫 canary（§8「永不存储」的机械化：全列、不挑列）。"""
    hits: list[dict[str, Any]] = []
    for row in rows:
        for column, value in row.items():
            text = "" if value is None else str(value)
            for needle in needles:
                if needle and needle in text:
                    hits.append({"row_id": row.get("id"), "column": column,
                                 "needle": needle[:24], "cell_chars": len(text)})
    return hits


def other_tables(db_path: Path | str) -> list[str]:
    target = Path(db_path)
    if not target.is_file():
        return []
    connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        return sorted(str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"))
    finally:
        connection.close()


def repo_ledger_row_counts() -> dict[str, int | None]:
    """仓库**真实**库（`backend/data/` 与仓库根 `data/`）的 `llm_request_logs` 行数。

    P0 跑完之后这份表必须逐枚是 0 或 None（表不存在）——它是「真机验收没把生产库写成
    样本库」的唯一现场证据。实现直接借 `tests/conftest.py` 的哨兵（同一份口径，
    不在此处复制第二份 SQL，否则两侧可能不一致）。
    """
    import conftest as ledger_guard

    return {str(path): count for path, count in
            ledger_guard.real_ledger_row_counts().items()}


# ==========================================================================
# 5.5 P0 登录腿的凭据接缝（SEC-A Task 10f）
# ==========================================================================
# **为什么存在（不是"顺手补一句 seed"）**
#
# SEC-A 把 `app/auth.py` 的硬编码 `USERS` 换成 SQLite 里的 argon2id 行之后，按规格
# §8.2/§8.5/§8.6 的设计：**生产代码永不自动造凭据行**。一份只有 schema 的新库里没有任何
# 凭据行，登录因此**统一**塌成 401 `invalid_credentials`（fail-closed，不是 500，也不是
# "帮你建一个"）。这条设计本身是对的，被 `tests/test_security_a_closure.py` 与
# `test_credentials_contract.py` 钉着。
#
# 代价落在 §16「必须原样绿」那 8 处登录调用点里最特殊的一枚：
# `test_real_llm_failover_acceptance.py:686`。它跑在**自己造的临时库**上（`setUp` 调
# `usage.init_usage_db(<证据目录>/run/<stamp>/conversations.db)`），因此**拿不到**
# `tests/conftest.py` 那份会话级 `seed_demo_credentials()`（那份 seed 落在会话临时库，
# 不是这一枚文件）。规格对这一枚的要求写得很死：调用形式与口令字面量都不改，
# 「改的是它们脚下的凭据来源（fixture 造 argon2id 行，§8.2 与 SECA-24）」——而那份文件是
# V2.3 封版产物（do-not-touch），所以"脚下"只能由 harness 层来垫。本接缝就是那层垫脚。
#
# **它凭什么对默认套件是惰性的**：唯一的门是 `acceptance_enabled()`（即
# `REAL_LLM_ACCEPTANCE=1`，与 §闸② 给 P0 用例设的那枚收集门同一枚开关、同一个函数）。
# 这里刻意**不**长出第二个条件：两处解析开关 = 两处口径，正是闸②点名禁止的形状。
# 因此默认套件里 `install_login_credential_seam()` 直接返回 False，`app.llm.usage`
# 的 `init_usage_db` 属性**一字未动**（由 `tests/test_security_a_closure.py` 钉住）。
#
# **它为什么不走第四条 seed 路径**：造行这件事完全委托
# `tests/sec_a_seed.install_demo_credentials(target)`——那枚函数已经负责"种进**指定的这一份**
# 文件"，并且**动手之前**先过保护集这一关（往 `backend/data/` 下的真库盖凭据行是整套护栏
# 最想拦的形状）。落点顺序（先种凭据、后建账本表）也与
# `test_model_router_v23_contract.py:4127-4131` 那处已存在的用法同形：目标文件尚不在场时
# 走"整份复制模板"，一次 Argon2 都不重算。
#: 接缝垫进临时库的那张表（表名以产品侧 `user_store.TABLE_NAME` 为准，这里只做证据描述）。
CREDENTIAL_TABLE = "user_credentials"

#: 还原钩子：非 None 表示 `init_usage_db` 当前挂着本接缝。
_LOGIN_SEAM_RESTORE: "Callable[[], None] | None" = None


def prepare_login_credentials(db_path: Path | str) -> None:
    """把 demo 凭据行（argon2id）种进**指定的那一份**库文件。

    纯委托给 `sec_a_seed.install_demo_credentials()`：口令字面量的唯一真源在那枚模块里，
    本函数不复制字面量、不写 SQL、不列 schema。保护集拒写也由那枚函数负责（本函数只转发，
    因此"拒写"这件事在接缝这条路上同样成立，见 closure 用例）。
    """
    import sec_a_seed

    sec_a_seed.install_demo_credentials(Path(db_path))


def login_credential_seam_is_installed() -> bool:
    """当前进程的 `usage.init_usage_db` 是否挂着本接缝（判据取自还原钩子，不取自 env）。"""
    return _LOGIN_SEAM_RESTORE is not None


def install_login_credential_seam() -> bool:
    """把 `app.llm.usage.init_usage_db` 包一层：建库之前先给那一份文件垫凭据行。

    返回「接缝是否在位」。开关不合 ⇒ **一个字节都不碰**产品模块并返回 False（默认套件的
    形状）。已在位时幂等（不叠第二层包装）。

    包装是**透传**的：参数原样转发、返回值原样返回、异常原样上抛；接缝只在"调用方显式
    指名了落点"时动作（`path is None` 时落点由 env 决定，那是会话临时库——它早就被
    `conftest.seeded_demo_credentials` 种过了，这里不越权替别人决定落点）。
    """
    global _LOGIN_SEAM_RESTORE
    if not acceptance_enabled():
        return False
    if _LOGIN_SEAM_RESTORE is not None:
        return True
    from app.llm import usage as usage_module

    previous = usage_module.init_usage_db

    def init_usage_db_with_credentials(*args: Any, **kwargs: Any) -> Any:
        target = args[0] if args else kwargs.get("path")
        if target is not None:
            prepare_login_credentials(target)
        return previous(*args, **kwargs)

    usage_module.init_usage_db = init_usage_db_with_credentials
    _LOGIN_SEAM_RESTORE = (
        lambda module=usage_module, value=previous: setattr(
            module, "init_usage_db", value))
    return True


def uninstall_login_credential_seam() -> bool:
    """摘掉接缝（还原 install 时抓下的那枚属性，可能是上一层包装）。返回"摘之前是否在位"。"""
    global _LOGIN_SEAM_RESTORE
    restore = _LOGIN_SEAM_RESTORE
    if restore is None:
        return False
    restore()
    _LOGIN_SEAM_RESTORE = None
    return True


# ==========================================================================
# 6. 证据校验 = 「矩阵 P0 行有没有资格 GREEN」的唯一判据
# ==========================================================================
def _assertions_of(evidence: dict[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for item in evidence.get("assertions") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            out[item["id"]] = item
    return out


def validate_evidence(evidence: dict[str, Any] | None) -> list[str]:
    """返回**问题清单**（空表 = 这份证据成立）。闸与 runner 共用，避免两套口径。

    每一枚问题都对应一种具体的造假路径，不是格式洁癖：
    - 只查「有没有 10 条」⇒ 有人能交 10 条 `pass=true` 的空壳；所以逐枚要求 `observed`
      非空且关键枚带**可复核的量**（模型名 / 状态码 / 字节数 / 耗时）。
    - 不查 attempt 的模型名 ⇒ 有人把 primary 换成 phi3、一次真加载就「过」了十字；
      所以要求第 0 枚是 `ornith-1.5:9b-text`、第 1 枚是 `phi3:mini`。
    - 不查错误体 ⇒ 「加载失败」可以凭空写。所以要求 primary 那枚带 ≥20 字的原文摘要，
      并且命中 §6 的 `alloc` / `failed to load` / `model ... not found` 族之一。
    - 不重算 sha1 ⇒ JSON 可以手抄。所以逐枚重算盘上文件。
    - 不查「矩阵状态 vs 证据」⇒ 证据在、矩阵仍 BLOCKED 也算矛盾（这条由 `green_permission` 判）。
    """
    problems: list[str] = []
    if not isinstance(evidence, dict):
        return ["证据不是 JSON 对象（缺文件 / 解析失败 / 有人手写了个字符串）"]
    if evidence.get("case_id") != CASE_ID:
        problems.append(f"case_id 不是 {CASE_ID}")
    if evidence.get("rehearsal"):
        problems.append("这是一枚**离线彩排件**（provider 传输层被换成 MockTransport），"
                        "不是真机证据：它不许出现在矩阵 GREEN 的判据里")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version 应为 {SCHEMA_VERSION}")
    if evidence.get("completed") is not True:
        problems.append("completed 不为 true：这次运行没跑到收尾，任何断言都不作数")
    if evidence.get("provider_transport") is not None:
        # 真机的定义性事实：`provider.py` 的测试接缝 `_transport` 必须是 None。
        # 挂着 `httpx.MockTransport` 跑一遍再落一份漂亮 JSON 是**最容易的造假路径**，
        # 这一枚判据把它从「证据成立」里直接摘掉（离线彩排件因此永远撑不起 GREEN）。
        problems.append(f"这次运行挂了传输层替身 {evidence['provider_transport']!r}："
                        "MockTransport 下产生的 JSON 不是真机证据")

    assertions = _assertions_of(evidence)
    if len(assertions) != len(ASSERTION_NAMES):
        problems.append(f"断言条数 {len(assertions)} != 10")
    for number, key, label in ASSERTION_NAMES:
        item = assertions.get(number)
        if item is None:
            problems.append(f"缺第 {number} 枚断言（{label}）")
            continue
        if item.get("name") != key:
            problems.append(f"第 {number} 枚 name 应为 {key}")
        if item.get("pass") is not True:
            problems.append(f"第 {number} 枚 pass 不为 true")
        observed = item.get("observed")
        if not isinstance(observed, dict) or not observed:
            problems.append(f"第 {number} 枚 observed 是空的：只有判词没有实测值")

    calls = evidence.get("provider_calls") or []
    if len(calls) != 2:
        problems.append(f"真外呼次数 {len(calls)} != 2（primary + fallback 各一次）")
    names = [call.get("model") for call in calls if isinstance(call, dict)]
    if names != [PRIMARY_MODEL, FALLBACK_MODEL]:
        problems.append(f"外呼模型序 {names} != [{PRIMARY_MODEL}, {FALLBACK_MODEL}]")
    for call in calls:
        if not isinstance(call, dict):
            problems.append("provider_calls 里有一枚不是对象")
            continue
        if not isinstance(call.get("request_bytes"), int) or call["request_bytes"] <= 0:
            problems.append(f"{call.get('model')} 没有正的 request_bytes")
        if not isinstance(call.get("elapsed_ms"), (int, float)) or call["elapsed_ms"] <= 0:
            problems.append(f"{call.get('model')} 没有正的 elapsed_ms（耗时没打？）")
    first = calls[0] if calls and isinstance(calls[0], dict) else {}
    excerpt = str(first.get("error_body_excerpt") or "")
    if first.get("ok") is not False:
        problems.append("primary 那枚外呼不是失败：P0 的前提（真加载失败）没发生")
    if first.get("error_kind") != "model_unavailable":
        problems.append("primary 的归类不是 model_unavailable")
    if len(excerpt) < 20:
        problems.append("primary 的错误体摘要短于 20 字：没有服务端原文可复核")
    lowered = excerpt.lower()
    if not any(marker in lowered for marker in MODEL_UNAVAILABLE_MARKERS):
        problems.append("primary 的错误体不含 §6 的加载失败特征字面")
    second = calls[1] if len(calls) > 1 and isinstance(calls[1], dict) else {}
    if second.get("ok") is not True:
        problems.append("fallback 那枚外呼不是成功")

    ledger = evidence.get("ledger") or {}
    if ledger.get("rows") != 1:
        problems.append(f"临时库行数 {ledger.get('rows')} != 1")
    if ledger.get("canary_hits"):
        problems.append("canary 在账本里命中了：§8 的「零 prompt 入库」破防")
    for needle in (PROMPT_CANARY,):
        if needle not in (ledger.get("canary_needles") or []):
            problems.append(f"canary 清单里没有 {needle[:16]}…：扫的不是这份 prompt")
    row = (ledger.get("row") or {})
    if row.get("fallback_index") != 1:
        problems.append("账本行的 fallback_index != 1")
    if row.get("success") not in (1, True):
        problems.append("账本行 success 不为真")
    if row.get("model") != FALLBACK_MODEL:
        problems.append("账本行的 model 不是 phi3:mini")
    for column in ("prompt", "context", "messages", "reasoning"):
        if column in row:
            problems.append(f"账本行出现了禁存列 {column}")

    trace = evidence.get("trace") or {}
    if len(trace.get("model_route_attempts") or []) != 2:
        problems.append("trace 的 model_route.attempts 不是两枚")
    if trace.get("trace_id") != (row.get("trace_id") if isinstance(row, dict) else None):
        problems.append("trace 与账本的 trace_id 不同源")

    answer = evidence.get("answer") or {}
    if len(str(answer.get("text") or "")) < MIN_ANSWER_CHARS:
        problems.append("phi3 的答案短于下限")
    timings = evidence.get("timings_ms") or {}
    if not isinstance(timings.get("total"), (int, float)) or timings["total"] <= 0:
        problems.append("timings_ms.total 缺失或非正")

    files = evidence.get("files_sha1") or {}
    if not files:
        problems.append("files_sha1 是空的：没有可核的落盘指纹")
    for path, digest in files.items():
        # 无条件重算：表里列了就必须对得上（文件被删/被改 ⇒ `<missing>` 或摘要不同 ⇒ 问题）。
        if sha1_of(path) != digest:
            problems.append(f"sha1 对不上：{path}（表里 {digest}，盘上 {sha1_of(path)}）")
    return problems


def read_evidence(path: Path | str = EVIDENCE_FILE) -> tuple[dict[str, Any] | None, str | None]:
    target = Path(path)
    if not target.is_file():
        return None, "missing"
    try:
        return json.loads(target.read_text(encoding="utf-8")), None
    except ValueError as exc:
        return None, f"unparsable: {exc}"


def matrix_p0_status() -> str | None:
    """从 `docs/MODEL_ROUTER_V23_MATRIX.md` 现读 P0 行的状态字段（不缓存、不猜）。"""
    import test_llm_egress_guard as guard

    rows = guard.parse_matrix_rows(MATRIX_DOC.read_text(encoding="utf-8"))
    for row in rows:
        if row["#"] == "P0":
            return row["状态"].strip("* ").strip()
    return None


def green_permission(evidence_path: Path | str = EVIDENCE_FILE, *,
                     bundle_dir: Path | str | None = None) -> dict[str, Any]:
    """「矩阵 P0 行能不能改成 GREEN」的许可判定：**与闸同一条口径**，逐条列条件。

    3B 修复轮 1 的 L6：这一枚过去只看 `validate_evidence()`（§6 那一层），而 3B 之后
    闸用的是 `p0_evidence_verdict()` = portable 层 + `[T-*]` + raw 层。runner 又是拿
    `green_permission()` 的返回值决定退出码的（`.superpowers/scripts/
    run_p0_failover_acceptance.sh` 末段）⇒ 两份口径重新长出来，而「两套口径」正是本文件
    §6 头上那段共享 kit 注释当初要防的事。现在 runner 与闸**都**走
    `p0_evidence_verdict()`，差别只在闸还多比一枚矩阵状态字。

    锚的取法要说平白：外部锚 `PORTABLE_MANIFEST_SHA256` 的**唯一出处是闸文件**（这是
    3B 的裁定，理由写在那枚常量上方）。本函数在运行时**现读**那枚常数（只 import、不改），
    所以 runner 拿到的判据与闸拿到的是同一枚锚；读不到常数就当条件不成立，
    **不降级成「不做锚校验」**——那样就等于把 `[I2]` 的外层悄悄关掉。

    本函数不改矩阵、不写矩阵——那一步归主 agent 裁（A-4 的硬约束）。
    """
    import importlib

    target_bundle_dir = BUNDLE_DIR if bundle_dir is None else bundle_dir
    anchor, anchor_error = None, None
    try:
        anchor = importlib.import_module(
            "test_real_llm_failover_gate").PORTABLE_MANIFEST_SHA256
    except Exception as exc:                      # 无 sys.path / 闸文件损坏 / 常数改名
        anchor_error = f"{type(exc).__name__}: {exc}"
    verdict = p0_evidence_verdict(manifest_sha256_pin=anchor, bundle_dir=target_bundle_dir,
                                  evidence_path=evidence_path)
    status = matrix_p0_status()
    problems = verdict["problems"]
    conditions = [
        ("证据 JSON 存在于约定路径", verdict["raw_state"] != "absent",
         f"{Path(evidence_path)}（读包结果 {verdict['raw_evidence_error'] or '已解析'}，"
         f"raw_state={verdict['raw_state']}）"),
        ("闸的外部锚常数可读（否则 [I2] 的锚校验会被静默关掉）", anchor is not None,
         f"锚 = {anchor}" if anchor else f"读不到：{anchor_error}"),
        ("P0 判定成立 = portable 层 + [T-*] 真值层 + raw 层三条腿一起过（与闸同一份口径）",
         not problems, "; ".join(problems) if problems
         else "portable 层 0 条、[T-*] 0 条、raw 层 0 条（逐层计数见 verdict）"),
        ("矩阵 P0 行当前状态 ∈ {BLOCKED, GREEN}", status in ("BLOCKED", "GREEN"),
         f"现读状态 = {status}"),
    ]
    all_met = all(ok for _name, ok, _detail in conditions) and status == "BLOCKED"
    return {
        "case_id": CASE_ID,
        "checked_at": utc_now(),
        "matrix_status_now": status,
        "evidence_path": str(Path(evidence_path).resolve()),
        "bundle_dir": str(Path(target_bundle_dir)),
        "manifest_sha256_pin": anchor,
        "evidence_present": verdict["raw_state"] != "absent",
        "raw_state": verdict["raw_state"],
        "verdict": verdict,
        "evidence_problems": problems,
        "layer_problem_counts": {
            "portable": len(verdict["portable_problems"]),
            "truth": len(verdict["truth_problems"]),
            "raw": len(verdict["raw_problems"]),
        },
        "conditions": [{"name": name, "ok": ok, "detail": detail}
                       for name, ok, detail in conditions],
        "green_permitted_by_evidence": all_met,
        "note": "即便 green_permitted_by_evidence=true，改矩阵的动作仍归主 agent；"
                "本函数只给判据，不碰 docs/MODEL_ROUTER_V23_MATRIX.md。"
                "判据与 test_real_llm_failover_gate 的 p0_evidence_verdict() 同一份。",
    }


def selfcheck_primary_leg() -> dict[str, Any]:
    """离线自检：**零模型加载**，把 P0 的「primary 腿」四段对着 A-2 的真错误体跑通。

    A-3 要求「不加载 phi3 也能验的部分就验掉」，验的就是这四段：

    1. 探针记下的**服务端原文**过一遍 `app.llm.errors` ⇒ 归类仍必须是 `model_unavailable`
       （T2 的 `500 + alloc/failed to load` 判据今天仍然命中，不是当年的回忆）。
    2. 出厂注册表在 `mode=rag` 下的计划仍是 `ollama-ornith → ollama-phi3`
       （P0 的**对象**存在；注册表被人改过就该在这里红，而不是在五分钟的加载之后）。
    3. provider 侧对 ornith 条目的**生效模型名**与 D1 凭据解析可用（真外呼会发出去的那个名字）。
    4. §8 的 19 列里**没有**能装下 prompt 的列（零入库那枚断言的结构性前提），
       并把 P0 形状的出口报文重量算出来（runner 打印，跑完与真值对照）。

    返回一份可打印的事实表；任何一段不合预期就抛 `AssertionError`（runner 会红）。
    """
    from app.llm import errors as llm_errors
    from app.llm import normalize as normalize_module
    from app.llm import provider as provider_module
    from app.llm import usage as usage_module
    from app.llm.models import LLMRequest, RequestProfile
    from app.llm.registry import credentials_for_provider, get_registry
    from app.llm.router import plan as plan_route

    probe, probe_error = read_evidence(PROBE_FILE)
    if probe is None:
        raise AssertionError(f"缺 A-2 探针件 {PROBE_FILE}（{probe_error}）：先跑 --probe")
    body = probe.get("probe") or {}
    raw = body.get("raw_error_body") or ""
    status = body.get("status_code")
    if not raw or not status:
        raise AssertionError(f"探针件里没有原文错误体：{body.get('probe_result')}")

    classified = llm_errors.classify(int(status), raw)
    if classified is None or classified.kind != "model_unavailable":
        raise AssertionError(
            f"归类不再是 model_unavailable（今天实得 {getattr(classified, 'kind', None)}）："
            "要么 §6 的判据漂了，要么 Ollama 换了错误文案")

    registry = get_registry()
    route_plan = plan_route(RequestProfile(mode="rag", complexity="low",
                                           needs_tools=False, needs_stream=False),
                            registry, {})
    plan_ids = (route_plan.primary.model.id,
                tuple(c.model.id for c in route_plan.fallbacks))
    if plan_ids[0] != PRIMARY_ENTRY_ID or plan_ids[1][:1] != (FALLBACK_ENTRY_ID,):
        raise AssertionError(f"出厂注册表的 rag 计划不再是 ornith → phi3：{plan_ids}")

    primary = route_plan.primary.model
    creds = credentials_for_provider(primary.provider, label=primary.id)
    target = provider_module.effective_model_name(primary, creds)
    if target != PRIMARY_MODEL:
        raise AssertionError(f"ornith 条目的生效模型名是 {target}，不是 {PRIMARY_MODEL}")

    request = LLMRequest(messages=[{"role": "system", "content": "自检"},
                                   {"role": "user",
                                    "content": f"{PROMPT_CANARY} 自检用的问题"}],
                         temperature=0.2, num_predict=256, keep_alive="0")
    payload = normalize_module.ollama_payload(request, target, stream=False)
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if PROMPT_CANARY.encode("utf-8") not in payload_bytes:
        raise AssertionError("出口报文里没有 canary：⑩/⑨ 两枚断言的扫描对象不对")
    columns = tuple(usage_module._INSERT_COLUMNS) + ("id",)
    forbidden = [name for name in columns
                 if any(word in name.lower()
                        for word in ("prompt", "context", "message", "reasoning", "query"))]
    if len(columns) != 19 or forbidden:
        raise AssertionError(f"§8 的 19 列形状不对或长出了禁存列：{columns} {forbidden}")

    return {
        "selfcheck": "primary 腿离线自检（零模型加载）",
        "probe_status_code": status,
        "probe_elapsed_ms": body.get("elapsed_ms"),
        "probe_error_body_head": raw[:160],
        "classification_kind": classified.kind,
        "classification_message": str(classified),
        "marker_hit": next((m for m in llm_errors.MODEL_UNAVAILABLE_MARKERS
                            if m in raw.lower()), ""),
        "no_fallback": classified.no_fallback,
        "retryable_current_model": classified.retryable,
        "rag_plan": {"primary": route_plan.primary.model.id,
                     "fallbacks": [c.model.id for c in route_plan.fallbacks],
                     "reason_codes": list(route_plan.reason_codes)},
        "effective_primary_model_name": target,
        "egress_payload_bytes_with_canary": len(payload_bytes),
        "ledger_columns": len(columns),
        "ledger_forbidden_columns": forbidden,
        "checked_at": utc_now(),
    }


# ==========================================================================
# 7. 可移植证据包（P0-EVIDENCE-PORTABILITY **3A：只换载体，不改判据**）
# ==========================================================================
#: bundle 的落点：`docs/` 下 ⇒ 干净签出可见、可跟踪、可逐文件重算 hash。
#: 原始件（临时 `.db` / `.jsonl` / A-2 探针）继续留在被 `.gitignore` 挡住的 `.superpowers/` 里，
#: bundle 只带它们的 **basename + sha1**（provenance），本体一概不入库。
BUNDLE_DIR = REPO_ROOT / "docs" / "evidence" / "model-router-v23" / "real-llm-failover-001"
BUNDLE_SCHEMA_VERSION = 1
#: bundle 与闸的 `schema_version` 是两件事：这枚是「bundle 的字段形状版本」。
BUNDLE_REL_DIR = BUNDLE_DIR.relative_to(REPO_ROOT).as_posix()

#: 六枚文件名就是 bundle 契约（3B 的闸会照这张表逐枚重算：少一枚、多一枚都该红）。
BUNDLE_RESULT_FILE = "result.json"
BUNDLE_RESPONSE_FILE = "response.json"
BUNDLE_LEDGER_ROW_FILE = "ledger-row.json"
BUNDLE_TRACE_FILE = "trace-attempts.json"
BUNDLE_PROBE_FILE = "primary-probe.json"
BUNDLE_MANIFEST_FILE = "manifest.json"
#: manifest 之外的五枚载荷件。**manifest 自己不在 `portable_files` 里**：一件东西不可能给自己算
#: hash（自指），所以它是「载体」而不是「被验对象」；干净签出要重算的是这五枚 + manifest 的声明。
_BUNDLE_PAYLOAD_FILES = (BUNDLE_RESULT_FILE, BUNDLE_RESPONSE_FILE, BUNDLE_LEDGER_ROW_FILE,
                         BUNDLE_TRACE_FILE, BUNDLE_PROBE_FILE)
BUNDLE_FILE_NAMES = _BUNDLE_PAYLOAD_FILES + (BUNDLE_MANIFEST_FILE,)
BUNDLE_EXPORT_FUNCTION = "backend/tests/real_llm_failover_kit.py::build_portable_bundle"

#: `manifest.trace_id_source.pointers` 的**恰好三枚键名**（唯一出处：导出与 `[I6]` 判定共用）。
#: 3B 修复轮 1 的 M2：过去 `[I6]` 那条写的是 `set(pointers.values()) - {None} != values
#: or len(pointers) != 3`——把一枚指针改成 `null` 后，等号两边都只是「剩下的那两枚真值」，
#: 于是**三处同源这条规则在少一条腿的情况下照样成立**。键名钉成常量，判定要求三枚
#: 既在场又非空，缺一枚即红。
_TRACE_ID_POINTER_KEYS = ("trace.trace_id", "ledger.row.trace_id", "request.trace_id")

#: `raw_provenance` 里唯一**被 git 跟踪**的那一枚（3B 修复轮 1 的 M1 裁定）。
#: 它的 provenance 记的是「工作树字节的 sha1」，而工作树字节随签出形态变——`.gitattributes`
#: 写的是 `* text=auto`、本机 `core.autocrlf=true` ⇒ Windows 侧签出可能是 CRLF，
#: Linux CI 侧是 LF ⇒ 同一份真话在一台机器上绿、另一台上红。
#: **git blob 身份是签出不变的**（`git hash-object` 先过 clean 过滤器把 CRLF 折回 LF，
#: 与 `git rev-parse HEAD:<path>` 同源），所以这一枚改按 blob 验：
#: 导出当场记 `git_blob = git hash-object <工作树文件>`，raw 层比 `git rev-parse HEAD:<仓相对路径>`，
#: 并另比一次「当下工作树的 blob」——这样本地改了这个文件（未提交）也会当场响。
#: 其余三枚是 gitignored 的运行态件（`.db` / `.jsonl` / 现场 probe），**根本不在 HEAD 里**，
#: 无 blob 可比 ⇒ 维持「sha1 + 只在在场时校验」的语义一字不动。
_GIT_BLOB_ROLES = ("acceptance_module",)

#: 上面那枚 role 对应的**仓相对 posix 路径**（由 `ACCEPTANCE_FILE ← __file__` 推出来，
#: 不是字面量、不是绝对路径）：`[I7]` 拿它核对 manifest 记的 `repo_path`，raw 层拿它做
#: `git rev-parse HEAD:<path>`。任何一棵签出的这枚相对路径都是同一个字符串，所以这一条腿
#: 与机器无关。
_ACCEPTANCE_REPO_PATH = ACCEPTANCE_FILE.relative_to(REPO_ROOT).as_posix()

#: `raw_provenance.role` 的四枚取值（简报冻结的口径）。认不出的原始件记 `other`——
#: 宁可多一枚待判定的 `other`，也不许把陌生的文件硬塞进已有 role。
_RAW_PROVENANCE_ROLES = (
    ("conversations.db", "ledger_db"),
    ("agent_traces.jsonl", "trace_jsonl"),
    ("ornith-primary-load-probe.json", "primary_probe"),
    ("test_real_llm_failover_acceptance.py", "acceptance_module"),
)
#: 账本行的禁存列：与 `validate_evidence()` 里那枚 inline 清单**逐字相同**。判定仍只在
#: `validate_evidence()` 一处（本步一个字没动它）；这里只是把「当时确实没有这些列」写成可重算的事实。
_BUNDLE_FORBIDDEN_COLUMNS = ("prompt", "context", "messages", "reasoning")
#: Windows 绝对路径的机械识别：单枚字母 + `:` + 分隔符，且字母前一枚不是字母/数字
#: （`http://` 的 `p:`、`phi3:mini` 的 `3:` 都不算，否则会把 URL 与模型名啃掉）。
#: bundle 里绝对路径**一条都不许留**（单机耦合是这次闸恒红的病根），一律换成 basename。
_ABSOLUTE_PATH_RE = re.compile("(?<![A-Za-z0-9])[A-Za-z]:[\\\\/][^\"'<>|,;)\\s]*")


def sha256_of(path: Path | str) -> str:
    """与 `sha1_of()` 同一口径的 sha256（bundle 的 `portable_files` 用它；文件不存在 ⇒ `<missing>`）。"""
    target = Path(path)
    if not target.is_file():
        return "<missing>"
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _basename_of_path_token(token: str) -> str:
    """把一枚路径 token 换成 basename（`E:\\a\\b\\c.db` / `/a/b/c.db` 都取 `c.db`）。"""
    parts = [part for part in re.split(r"[\\/]+", token.strip()) if part]
    for part in reversed(parts):
        if part.rstrip(":"):
            return part
    return token


def _scrub_absolute_paths(value: Any) -> Any:
    """递归清洗 dict/list/str：任何字符串里的绝对路径换成 basename，键同样清洗。

    这是**兜底**而不是主映射：字段级的指针映射在 `_bundle_*()` 各函数里逐条写明。
    清洗后若还能匹配到绝对路径就抛错（宁可导出失败，也不交出一枚单机耦合的 bundle）。
    """
    if isinstance(value, str):
        scrubbed = _ABSOLUTE_PATH_RE.sub(
            lambda match: _basename_of_path_token(match.group(0)), value)
        if _ABSOLUTE_PATH_RE.search(scrubbed):
            raise AssertionError(f"绝对路径清洗后仍残留：{scrubbed[:120]!r}")
        return scrubbed
    if isinstance(value, dict):
        return {_scrub_absolute_paths(key): _scrub_absolute_paths(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub_absolute_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_scrub_absolute_paths(item) for item in value]
    return value


def _relative_repo_path(path_text: Any) -> Any:
    """仓内绝对路径 → 仓相对 posix 路径；仓外或读不到 ⇒ basename。

    为什么这里用仓相对而不是 basename：`protected_repo_ledgers` 的两枚键 basename 完全同名
    （都是 `conversations.db`），压成 basename 就把「仓库真库 0 行」这枚证明压没了。
    仓相对 posix 不是绝对路径，干净签出读得到同一枚位置。
    """
    if not isinstance(path_text, str) or not path_text:
        return path_text
    try:
        return Path(path_text).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return _basename_of_path_token(path_text)


def _git_head_hash() -> str | None:
    """导出当场跑一次**只读**的 `git rev-parse HEAD`；拿不到就返回 None（manifest 写 null）。

    为什么不猜、不缓存、不拿上一次的那枚 hash 顶：`source_tree_hash` 的唯一用途是
    「这份 bundle 描述的是哪一枚代码树」。填错比留空坏——留空是证据面缺口，填错是造假。
    """
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                                capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if result.returncode != 0:
        return None
    head = (result.stdout or "").strip()
    return head if re.fullmatch(r"[0-9a-f]{7,40}", head or "") else None


def _git(repo_args: list[str], repo_root: Path) -> str | None:
    """跑一枚**只读** git 命令并校验输出是对象 id 的形状；任何失败都返回 None（不猜）。

    与 `_git_head_hash()` 同一口径：`git hash-object` 不带 `-w` 时**只算名字、不落对象库、
    不动任何 ref**，`git rev-parse HEAD:<path>` 同理。本步「不做任何 git 写操作」的硬约束
    靠的就是这一枚函数不接受任何带写语义的参数。
    """
    import subprocess

    try:
        result = subprocess.run(["git", *repo_args], cwd=repo_root,
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip()
    return out if re.fullmatch(r"[0-9a-f]{7,40}", out) else None


def git_blob_of_worktree(path: Path | str, *, repo_root: Path = REPO_ROOT) -> str | None:
    """`git hash-object <文件>`：工作树字节**过完 clean 过滤器之后**的 blob id。

    这一枚就是「签出形态无关」的那半：CRLF 与 LF 两份字节经过 `* text=auto` + autocrlf
    的 clean 过滤都会落成同一枚 blob，于是它可比、可重算，且不会因为换了台机器就变结论。
    """
    return _git(["hash-object", "--", str(path)], repo_root)


def git_blob_of_head(rel_path: str, *, repo_root: Path = REPO_ROOT) -> str | None:
    """`git rev-parse HEAD:<仓相对 posix 路径>`：这枚路径在**当前提交**里的 blob id。

    取不到（文件不在 HEAD / 没有 git / 路径写错）⇒ None，由调用方按「响亮地红」处理。
    """
    return _git(["rev-parse", f"HEAD:{rel_path}"], repo_root)


def _raw_role(name: str) -> str:
    """原始件的 role（简报冻结的四枚取值），认不出 ⇒ `other`。"""
    for pattern, role in _RAW_PROVENANCE_ROLES:
        if name == pattern or name.endswith(pattern):
            return role
    return "other"


def _load_bundle_source(value: Any, default_path: Path) -> dict[str, Any]:
    """把「已经读好的 dict / 一枚路径 / None（用默认路径）」统一成 dict。"""
    if isinstance(value, dict):
        return value
    target = default_path if value is None else Path(str(value))
    source, error = read_evidence(target)
    if source is None:
        raise ValueError(f"读不到原始件 {target.name}：{error}")
    return source


def _raw_provenance(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """`raw_provenance`：原始件的 **basename + 当场重算的 sha1 + bytes + role**。

    - 清单来源 = 原始证据自己的 `files_sha1`（那才是这次运行真正指纹过的件），不另起一套。
    - `sha1` 是**导出当场重算**的；同时带出 `recorded_sha1` 与 `matches_recorded`，
      让「原始件此刻还对不对得上证据自己的表」这件事在 bundle 里就是事实，不是口头承诺。
    - `_GIT_BLOB_ROLES` 里那几枚（= 唯一被 git 跟踪的 `acceptance_module`）**另记两枚字段**：
      `git_blob`（导出当场的 `git hash-object`，即工作树字节过完 clean 过滤器之后的 blob id）
      与 `repo_path`（仓相对 posix，供 raw 层做 `git rev-parse HEAD:<repo_path>`）。
      理由见那枚常量上方的注释：这一枚的**工作树 sha1 是签出相关的**，拿它当 CI 判据会
      在 Windows 签出上冤枉一次真话；blob 身份不随签出形态变。其余三枚运行态件不在 HEAD 里，
      没有 blob 可比，字段写成 null 并记进 `absent_source_fields` 之外的自述里（不猜）。
    """
    entries: list[dict[str, Any]] = []
    for path_text, recorded in sorted((evidence.get("files_sha1") or {}).items(),
                                      key=lambda item: Path(item[0]).name):
        target = Path(path_text)
        present = target.is_file()
        actual = sha1_of(target)
        role = _raw_role(target.name)
        entry: dict[str, Any] = {
            "name": target.name,
            "role": role,
            "sha1": actual,
            "recorded_sha1": recorded,
            "matches_recorded": bool(present) and actual == recorded,
            "present": present,
            "bytes": target.stat().st_size if present else None,
        }
        if role in _GIT_BLOB_ROLES:
            entry["repo_path"] = _relative_repo_path(path_text)
            entry["git_blob"] = git_blob_of_worktree(target) if present else None
            entry["git_blob_origin"] = ("导出当场跑的只读命令 `git hash-object <工作树文件>`"
                                        "（过 clean 过滤器 ⇒ 与签出 EOL 形态无关）")
        entries.append(entry)
    return entries


def _source_run_flags(evidence: dict[str, Any]) -> dict[str, bool]:
    """原始证据 JSON 的**运行形态布尔位**（H1 + H2 的载体侧，唯一的一份算式）。

    为什么要把五枚布尔位文本化进 manifest（而不是只留在 §6 那句判词里）：
    那三枚判据的对象是**这枚被跟踪的文本自己写着的事实**，跟 run 目录里那三枚没入库的
    本体没关系，所以它们该长在**无条件必须过**的那一层。长在 manifest 里还有一层好处：
    manifest 的字节被闸里的外部锚钉着 ⇒ 想改这几枚布尔位就得连带动锚，是可见的 diff。
    同一枚算式在 `cross_check_bundle_and_raw`（载体 ↔ 真源面对面）与
    `tracked_evidence_truth_problems`（读盘现判）里各自复用，不留第二份真相。
    """
    return {
        "completed_is_true": evidence.get("completed") is True,
        "rehearsal_present": "rehearsal" in evidence,
        "rehearsal_truthy": bool(evidence.get("rehearsal")),
        "provider_transport_key_present": "provider_transport" in evidence,
        "provider_transport_is_null": evidence.get("provider_transport") is None,
    }


def _bundle_result(evidence: dict[str, Any]) -> dict[str, Any]:
    """`result.json` = 十枚断言本体（逐枚 `name` / `pass` / `observed` / `elapsed_ms`）。

    字段来源（逐条机械投影，不做任何推断）：
    - `assertions[]`               ← 原始 `assertions[]` 原样（含 `id`；失败例的 `failure` 一并带出）
    - `case_id`                    ← 原始 `case_id`
    - `evidence_schema_version`    ← 原始 `schema_version`
    - `source_run_generated_at`    ← 原始 `generated_at`
    - `expected_assertion_names[]` ← 本模块常量 `ASSERTION_NAMES`（§10 十字的唯一出处）
    """
    assertions = [_scrub_absolute_paths(item) for item in evidence.get("assertions") or []]
    return {
        "case_id": evidence.get("case_id"),
        "evidence_schema_version": evidence.get("schema_version"),
        "source_run_generated_at": evidence.get("generated_at"),
        "assertion_count": len(assertions),
        "all_pass": bool(assertions) and all(bool(item.get("pass")) for item in assertions),
        "assertions": assertions,
        "expected_assertion_names": [{"id": number, "name": name, "zh": zh}
                                     for number, name, zh in ASSERTION_NAMES],
    }


def _bundle_response(evidence: dict[str, Any]) -> dict[str, Any]:
    """`response.json` = `answer.*` 全量（含 `text`）+ `provider_calls` 摘要。

    字段来源：
    - `answer`                     ← 原始 `answer`（`text/chars/cjk_chars/model/finish_reason/
                                      input_tokens/output_tokens/usage_estimated` 一枚不减）
    - `provider_calls[]`           ← 原始 `provider_calls[]` 逐条原样
    - `provider_transport`         ← 原始 `provider_transport`（当时记的是 null，就写 null）
    - `provider_transport_present` ← 原始件里**这枚键本身在不在**（3B 修复轮 1 的 H2：
      「键缺席」与「键在且为 null」在过去不可区分，于是唯一的非彩排正面凭据在**源端**
      退化成了『读不到就算过』；这一枚把两件事拆成两枚可重算的事实）
    - `summary.*`                  ← 由上面两段的**同名字段**并列成的序列表，不新增事实
    """
    answer = _scrub_absolute_paths(evidence.get("answer") or {})
    calls = [_scrub_absolute_paths(item) for item in evidence.get("provider_calls") or []]
    return {
        "case_id": evidence.get("case_id"),
        "source_run_generated_at": evidence.get("generated_at"),
        "answer": answer,
        "provider_calls": calls,
        "provider_transport": evidence.get("provider_transport"),
        "provider_transport_present": "provider_transport" in (evidence or {}),
        "summary": {
            "calls": len(calls),
            "entry_id_in_order": [item.get("entry_id") for item in calls],
            "model_in_order": [item.get("model") for item in calls],
            "ok_in_order": [item.get("ok") for item in calls],
            "http_status_in_order": [item.get("http_status") for item in calls],
            "error_kind_in_order": [item.get("error_kind") for item in calls],
            "request_bytes_in_order": [item.get("request_bytes") for item in calls],
            "elapsed_ms_in_order": [item.get("elapsed_ms") for item in calls],
            "elapsed_ms_sum": round(sum(float(item.get("elapsed_ms") or 0.0)
                                        for item in calls), 1),
            "request_bytes_method": next((item.get("request_bytes_method")
                                          for item in calls), None),
            "answer_chars": answer.get("chars"),
            "answer_cjk_chars": answer.get("cjk_chars"),
        },
    }


def _bundle_ledger_row(evidence: dict[str, Any]) -> dict[str, Any]:
    """`ledger-row.json` = `ledger.row` 原样 + canary 事实 + 禁存列证明。

    字段来源：
    - `row`                            ← 原始 `ledger.row`（逐列原样）
    - `ledger_source.path_basename`    ← 原始 `ledger.path` 的 **basename**（绝对路径不外泄）
    - `ledger_source.rows` / `.tables` ← 原始 `ledger.rows` / `ledger.tables`
    - `canary_needles` / `canary_hits` ← 原始 `ledger.canary_needles` / `ledger.canary_hits`
    - `forbidden_column_proof.columns_checked` ← `_BUNDLE_FORBIDDEN_COLUMNS`
      （与 `validate_evidence()` 那枚 inline 清单同形）
    - `forbidden_column_proof.columns_present_in_row` ← `row` 的键实测（成立时必为空表）
    - `forbidden_column_proof.protected_repo_ledgers` ← 原始 `ledger.protected_repo_ledgers`，
      键换成**仓相对** posix（两枚键 basename 同名，压成 basename 会把证明压没）
    """
    ledger = evidence.get("ledger") or {}
    row = ledger.get("row") if isinstance(ledger.get("row"), dict) else {}
    hits = ledger.get("canary_hits") or []
    protected = ledger.get("protected_repo_ledgers") or {}
    return {
        "case_id": evidence.get("case_id"),
        "ledger_source": {
            "path_basename": Path(str(ledger.get("path") or "")).name,
            "rows": ledger.get("rows"),
            "tables": _scrub_absolute_paths(ledger.get("tables")),
        },
        "row": _scrub_absolute_paths(row),
        "trace_id": row.get("trace_id"),
        "canary_needles": _scrub_absolute_paths(ledger.get("canary_needles")),
        "canary_hits": _scrub_absolute_paths(hits),
        "forbidden_column_proof": {
            "columns_checked": list(_BUNDLE_FORBIDDEN_COLUMNS),
            "columns_present_in_row": [column for column in _BUNDLE_FORBIDDEN_COLUMNS
                                       if column in row],
            "row_columns": sorted(row),
            "canary_hit_count": len(hits),
            "protected_repo_ledgers": {_relative_repo_path(key): value
                                       for key, value in protected.items()},
            "note": "禁存列清单与 validate_evidence() 里那枚 inline 清单逐字相同；"
                    "判定仍只在 validate_evidence() 一处，本件只是把「当时确实没有这些列」"
                    "写成干净签出可重算的事实。",
        },
    }


def _bundle_trace_attempts(evidence: dict[str, Any]) -> dict[str, Any]:
    """`trace-attempts.json` = trace 的 model_route 事实 + trace_id 的三处同源证明。

    字段来源：
    - `trace_id`               ← 原始 `trace.trace_id`（**顶层没有 `trace_id` 这枚键**，
                                 值只能从这一处取；另两处 `ledger.row.trace_id`、
                                 `request.trace_id` 作为同源核对一并带出）
    - `model_route_attempts[]` ← 原始 `trace.model_route_attempts`
    - `model_route_selected_index` / `model_route_stage` / `model_route_keys`
      ← 原始 `trace.model_route_selected_index` / `.model_route_stage` / `.model_route_keys`
    - `trace_source.path_basename` / `.lines` ← 原始 `trace.path` 的 basename / `trace.lines`
    - `chain`                  ← 原始 `chain`（产品侧同一次路由的结论，用于与 trace 面对面）
    """
    trace = evidence.get("trace") or {}
    row = (evidence.get("ledger") or {}).get("row") or {}
    request = evidence.get("request") or {}
    pointers = {
        "trace.trace_id": trace.get("trace_id"),
        "ledger.row.trace_id": row.get("trace_id"),
        "request.trace_id": request.get("trace_id"),
    }
    distinct = {value for value in pointers.values()}
    return {
        "case_id": evidence.get("case_id"),
        "trace_id": trace.get("trace_id"),
        "trace_id_pointers": pointers,
        "trace_id_consistent": len(distinct) == 1 and None not in distinct,
        "trace_source": {
            "path_basename": Path(str(trace.get("path") or "")).name,
            "lines": trace.get("lines"),
        },
        "model_route_stage": trace.get("model_route_stage"),
        "model_route_selected_index": trace.get("model_route_selected_index"),
        "model_route_keys": _scrub_absolute_paths(trace.get("model_route_keys")),
        "model_route_attempts": _scrub_absolute_paths(trace.get("model_route_attempts")),
        "chain": _scrub_absolute_paths(evidence.get("chain")),
    }


def _bundle_primary_probe(probe: dict[str, Any]) -> dict[str, Any]:
    """`primary-probe.json` = A-2 探针件的**文本化投影**（不是「原文件的路径引用」）。

    字段来源（全部 ← 原始 probe 件的同名键，逐字投影）：
    `stage` / `started_at` / `inventory_before` / `inventory_after` /
    `memory_before` / `memory_after` / `probe`（含 `raw_error_body` 原文与 `classification`）。
    `source_file_basename` ← `PROBE_FILE` 的 basename（原始件本体继续在 ignored 目录，不入库）。
    """
    return {
        "case_id": CASE_ID,
        "source_file_basename": PROBE_FILE.name,
        "stage": probe.get("stage"),
        "started_at": probe.get("started_at"),
        "inventory_before": _scrub_absolute_paths(probe.get("inventory_before")),
        "inventory_after": _scrub_absolute_paths(probe.get("inventory_after")),
        "memory_before": _scrub_absolute_paths(probe.get("memory_before")),
        "memory_after": _scrub_absolute_paths(probe.get("memory_after")),
        "probe": _scrub_absolute_paths(probe.get("probe")),
        "projection": "文本化投影：字段值逐字来自原始 probe；本件不含原始件的绝对路径，"
                      "也不是指向原始件的路径引用。",
    }


def _bundle_text(payload: dict[str, Any]) -> str:
    """bundle 的序列化口径只有一处：JSON / 不转义中文 / 缩进 2 / LF / 末尾换行。

    绝对路径在这一层被**最后兜底**清洗一次（字段级映射在各 `_bundle_*()` 里已各自处理）。
    `json.dumps` 会把控制字符写成转义序列，所以 `\r` 不可能以裸字节出现在 JSON 文本里；
    落盘用 `write_bytes`（`write_text` 在 Windows 上会把 `\n` 换成 CRLF，那正是本包要避免的）。
    """
    scrubbed = _scrub_absolute_paths(payload)
    return json.dumps(scrubbed, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def build_portable_bundle(evidence: Any = None, *, probe: Any = None,
                          generated_at: str | None = None) -> dict[str, str]:
    """把一次真机运行的原始产物**机械投影**成六枚 bundle 文件文本：`{文件名: 文本}`。

    输入（全部只读）：`evidence` 缺省读 `EVIDENCE_FILE`，`probe` 缺省读 `PROBE_FILE`，
    原始件本身一个字节都不改。`raw_provenance` 里那四枚 sha1 是在**本函数内当场重算**的。

    输出六枚（顺序即 `BUNDLE_FILE_NAMES`）：
    `result.json` / `response.json` / `ledger-row.json` / `trace-attempts.json` /
    `primary-probe.json` / `manifest.json`。

    manifest 的字段来源：
    - `evidence_schema_version`   = `BUNDLE_SCHEMA_VERSION`（bundle 自己的形状版本，本轮 = 1）
    - `case_id`                   ← 原始 `case_id`
    - `generated_at`              = 导出时刻（`utc_now()`，ISO8601 带时区）
    - `source_run_generated_at`   ← 原始 `generated_at`（**不得丢**）
    - `trace_id`                  ← 原始 `trace.trace_id`（顶层无此键；另两处同源，见 `trace_id_source`）
    - `source_tree_hash`          ← 导出当场的 `git rev-parse HEAD`（只读；拿不到写 null）
    - `release_image`             ← 原始件**没有这枚事实** ⇒ 写 null，并记进 `absent_source_fields`
    - `environment` / `plan` / `config_overrides` / `registry_file` / `registry_mutated`
      ← 原始件同名键（有值就用，绝对路径按规则换成 basename / 仓相对）
    - `exported_by`               = 导出函数标识 + 读了哪些原始件的 **basename 列表**
    - `portable_files`            = 五枚载荷件的 `{path, sha256, bytes}`（path 为仓相对 posix）
    - `raw_provenance`            = `_raw_provenance()`（basename + 当场重算 sha1 + bytes + role，
                                    被 git 跟踪的那枚另记 `repo_path` + `git_blob`）
    - `source_run_flags`          = `_source_run_flags()`（原始 JSON 的五枚运行形态布尔位：
                                    `completed_is_true` / `rehearsal_present` / `rehearsal_truthy`
                                    / `provider_transport_key_present` /
                                    `provider_transport_is_null`；机械投影，不做任何推断）
    - `absent_source_fields`      = 原始件里没有、因此写成 null 的字段（诚实清单）

    本函数**不判 GREEN、不改矩阵、不碰 `validate_evidence()`**：3A 只负责「能被重算」。
    """
    source = _load_bundle_source(evidence, EVIDENCE_FILE)
    probe_source = _load_bundle_source(probe, PROBE_FILE)

    payloads = {
        BUNDLE_RESULT_FILE: _bundle_result(source),
        BUNDLE_RESPONSE_FILE: _bundle_response(source),
        BUNDLE_LEDGER_ROW_FILE: _bundle_ledger_row(source),
        BUNDLE_TRACE_FILE: _bundle_trace_attempts(source),
        BUNDLE_PROBE_FILE: _bundle_primary_probe(probe_source),
    }
    texts = {name: _bundle_text(payload) for name, payload in payloads.items()}

    portable_files: list[dict[str, Any]] = []
    for name in _BUNDLE_PAYLOAD_FILES:
        data = texts[name].encode("utf-8")
        portable_files.append({"path": f"{BUNDLE_REL_DIR}/{name}",
                               "sha256": hashlib.sha256(data).hexdigest(),
                               "bytes": len(data)})

    trace = source.get("trace") or {}
    row = (source.get("ledger") or {}).get("row") or {}
    request = source.get("request") or {}
    trace_id_pointers = {"trace.trace_id": trace.get("trace_id"),
                         "ledger.row.trace_id": row.get("trace_id"),
                         "request.trace_id": request.get("trace_id")}
    #: 键名集合与 `[I6]` 判定共用同一枚常量（见 §8 `_TRACE_ID_POINTER_KEYS`）：
    #: 谁改了导出这边的键名，那边的「三枚都在场且非空」立刻响，不会留下两口径。
    if tuple(trace_id_pointers) != _TRACE_ID_POINTER_KEYS:
        raise AssertionError("trace_id_source.pointers 的键名与 _TRACE_ID_POINTER_KEYS 不同源")
    head_hash = _git_head_hash()

    manifest = {
        "evidence_schema_version": BUNDLE_SCHEMA_VERSION,
        "case_id": source.get("case_id"),
        "generated_at": generated_at or utc_now(),
        "source_run_generated_at": source.get("generated_at"),
        "trace_id": trace.get("trace_id"),
        "trace_id_source": {
            "pointers": trace_id_pointers,
            "consistent": (len({value for value in trace_id_pointers.values()}) == 1
                           and None not in trace_id_pointers.values()),
            "note": "原始证据**顶层没有 `trace_id` 这枚键**（实测：absent，不是 null）；"
                    "值取自 trace.trace_id，并与 ledger.row.trace_id、request.trace_id 同源核对。",
        },
        "source_tree_hash": head_hash,
        "source_tree_hash_origin": "导出当场跑的只读命令 `git rev-parse HEAD`；"
                                   "取不到（无 git / 非仓库 / 命令失败）时写 null，不猜、不缓存。",
        "release_image": None,
        "environment": _scrub_absolute_paths(source.get("environment")),
        "plan": _scrub_absolute_paths(source.get("plan")),
        "config_overrides": _scrub_absolute_paths(source.get("config_overrides")),
        "registry_file": _relative_repo_path(source.get("registry_file")),
        "registry_mutated": _scrub_absolute_paths(source.get("registry_mutated")),
        "exported_by": {
            "function": BUNDLE_EXPORT_FUNCTION,
            "source_basenames": [EVIDENCE_FILE.name, PROBE_FILE.name]
                                + [entry["name"] for entry in _raw_provenance(source)
                                   if entry["name"] != PROBE_FILE.name],
        },
        "portable_files": portable_files,
        "raw_provenance": _raw_provenance(source),
        #: 原始证据 JSON 自己的运行形态布尔位（H1/H2 的载体侧；算式唯一出处 =
        #: `_source_run_flags()`）。这五枚是「非彩排的正面凭据」能被干净签出重算的那份载体：
        #: 键在不在、值是不是 null、completed 是不是 true、rehearsal 是不是被写了真。
        "source_run_flags": _source_run_flags(source),
        #: `raw_provenance` 只给 basename（裁定口径），但同一次 SDD 目录里存在**同名彩排件**
        #: （实测 `task10/rehearsal/run/…/conversations.db` 与 `agent_traces.jsonl` 各一枚、sha1 不同），
        #: 所以这里补记原始件所在的 run 目录（仓相对 posix，不是绝对路径）：3B 不必靠猜就能定位到
        #: 被指纹过的那一枚。缺省（`run_artifacts` 没记）⇒ null，同样不猜。
        "source_run_dir": _relative_repo_path((source.get("run_artifacts") or {}).get("run_dir")),
        "absent_source_fields": [
            {"field": "release_image",
             "checked_pointers": ["<顶层>", "environment", "environment.before",
                                  "environment.after", "answer", "ledger.row", "plan"],
             "written_as": None,
             "why": "原始件从未记录镜像名：本轮跑的是宿主 Ollama"
                    "（environment.before.base_url 为现场地址），不存在镜像这一事实。不造一个名字。"},
            {"field": "trace_id（顶层键）",
             "checked_pointers": ["<顶层 trace_id>"],
             "written_as": "取自 trace.trace_id",
             "why": "顶层不是 null 而是**键本身不存在**；值另有三处同源指针，已核对一致。"},
        ],
    }
    texts[BUNDLE_MANIFEST_FILE] = _bundle_text(manifest)
    return {name: texts[name] for name in BUNDLE_FILE_NAMES}


def write_portable_bundle(evidence: Any = None, *, probe: Any = None,
                          generated_at: str | None = None,
                          bundle_dir: Path | str = BUNDLE_DIR) -> dict[str, Any]:
    """落盘六枚 bundle 文件并**从盘上重算** manifest 声明的 sha256，返回 manifest。

    重算不等就抛 `AssertionError`：manifest 说的是「盘上那枚字节」，不是「我以为写了什么」。
    真机 runner（`.superpowers/scripts/run_p0_failover_acceptance.sh` 的 [4/4]）跑完一次验收
    就调这里一次 ⇒ bundle 与原始件同批产生，不会随时间失去可再生性。
    """
    texts = build_portable_bundle(evidence, probe=probe, generated_at=generated_at)
    target_dir = Path(bundle_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in BUNDLE_FILE_NAMES:
        (target_dir / name).write_bytes(texts[name].encode("utf-8"))

    manifest = json.loads(texts[BUNDLE_MANIFEST_FILE])
    for entry in manifest["portable_files"]:
        on_disk = target_dir / Path(entry["path"]).name
        actual = sha256_of(on_disk)
        if actual != entry["sha256"] or (on_disk.is_file() and on_disk.stat().st_size
                                         != entry["bytes"]):
            raise AssertionError(
                f"落盘后重算对不上：{on_disk.name}（manifest 说 {entry['sha256']} "
                f"{entry['bytes']}B，盘上 {actual} "
                f"{on_disk.stat().st_size if on_disk.is_file() else '<missing>'}B）")
    return manifest


# ==========================================================================
# 8. 可移植证据包的判据层（P0-EVIDENCE-PORTABILITY **3B**）
# ==========================================================================
#: 3B 的分层：
#: - **portable 层**（`validate_portable_bundle`）= 干净签出唯一能重算的一层，**无条件必须过**。
#: - **raw 层**（`validate_evidence`，§6，一字未改其判据）= 只在原始件按
#:   `manifest.source_run_dir` + `raw_provenance[].sha1` **双条件**定位得到时才跑（在场才校验）。
#: 语义边界（R26 第 ③ 条）：raw 不在场 ⇒ 不影响 portable 的判定；portable 缺失/畸形/hash 不配
#: ⇒ 本层直接给问题清单，闸据此要求矩阵写 `BLOCKED`；portable 全过 + 七条 interlock 成立 ⇒ 允许 `GREEN`。
#:
#: 判据标签：每条问题串都以 `[I1]`…`[I7]`（七条 interlock）、`[C-<名>]`（从 §6 搬过来的
#: 逐条判据）、`[X]`（bundle↔原始件面对面核对）开头。闸的失败文案、证伪台的归因、报告里
#: 那张逐条映射表**共用这一套标签**，同一枚判据不许有两个名字。
#: `raw_provenance.role` → 定位方式。**没有一条是「按 basename 全盘搜索」或「按字节大小挑」**：
#: `task10/rehearsal/run/20260924-214030/` 里躺着同名、**同字节**、不同 sha1 的彩排件（3A 读数
#: 《交回控制器的 findings 7》实测），仓里另有 `data/`、`rev6r1_mutation_lab/` 两处同名件，
#: 所以定位只能是「仓根 + manifest.source_run_dir + 这枚 name」，其余两枚走 kit 自己的常量路径。
_RUN_DIR_ROLES = ("ledger_db", "trace_jsonl")
#: 原始件必须**逐枚**对上这两个名字（与 §6 的四枚 role 同源，多一枚/少一枚都红）。
_RAW_PROVENANCE_EXPECTATIONS = (
    ("ledger_db", "conversations.db"),
    ("trace_jsonl", "agent_traces.jsonl"),
    ("primary_probe", "ornith-primary-load-probe.json"),
    ("acceptance_module", "test_real_llm_failover_acceptance.py"),
)
#: 真机 run 目录末段的形状（`run/<yyyymmdd>-<hhmmss>`）。
#: 反彩排的第一道——彩排那族的 name 里带着 `rehearsal` 分量（见下方逐分量检查），第二道是
#: sha1 逐枚重算，第三道是 portable 载荷件里那枚**正面**凭据 `provider_transport is None`
#: （见 `[C-传输层]`）。三道叠起来才叫「不许把彩排件洗成真凭据」。
_SOURCE_RUN_STEM_RE = re.compile(r"\d{8}-\d{6}")


def portable_bundle_paths(bundle_dir: Path | str = BUNDLE_DIR) -> dict[str, Path]:
    """六枚 bundle 文件的路径，**全部由仓根锚定**（`BUNDLE_DIR ← REPO_ROOT ← __file__`）。

    刻意不接受 cwd：3A《读数 3 的口径补正》实测过「以 `backend/` 为 cwd 裸开 `portable_files[].path`
    会得到五枚 `<missing>`」——按 cwd 解析会假 DIFFER，闸就再也不是判据了。
    """
    target = Path(bundle_dir)
    return {name: target / name for name in BUNDLE_FILE_NAMES}


def read_portable_bundle(bundle_dir: Path | str = BUNDLE_DIR) -> tuple[dict[str, Any] | None,
                                                                       str | None]:
    """读六枚 bundle 文件：`{name: {path, present, bytes, sha256, data, parse_error}}`。

    `sha256` 是**本函数从盘上读的字节**当场算的（不是读 manifest 说的），所以 §8 的每一枚
    hash 判据都是「声明 vs 实测」的对照而不是自我引用。六枚全缺 ⇒ `(None, "missing")`。
    """
    files: dict[str, Any] = {}
    for name, path in portable_bundle_paths(bundle_dir).items():
        entry: dict[str, Any] = {"path": str(path), "present": False, "bytes": None,
                                 "sha256": "<missing>", "data": None, "parse_error": None,
                                 "has_cr": False}
        if path.is_file():
            raw = path.read_bytes()
            entry.update(present=True, bytes=len(raw), has_cr=(b"\r" in raw),
                         sha256=hashlib.sha256(raw).hexdigest())
            try:
                entry["data"] = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                entry["parse_error"] = f"{type(exc).__name__}: {exc}"
        files[name] = entry
    if not any(item["present"] for item in files.values()):
        return None, "missing"
    return {"dir": str(Path(bundle_dir)), "files": files}, None


def set_portable_payload_text(payload: dict[str, Any], name: str, text: str) -> None:
    """把内存里某枚载荷件换成 `text` 并重算它的 `bytes`/`sha256`（**不落盘**）。

    存在的理由：证伪台要在**不碰 `docs/evidence/`** 的前提下证明「改内容杀不掉语义判据」
    这件事不可能发生——先把 hash 那一关喂平（`restamp_portable_manifest`），杀掉它的才只能是
    interlock 本身。只在证伪脚本与闸的退化探针里用。
    """
    data = text.encode("utf-8")
    entry = payload["files"][name]
    entry["text"] = text
    entry["bytes"] = len(data)
    entry["has_cr"] = "\r" in text
    entry["sha256"] = hashlib.sha256(data).hexdigest()


def dump_portable_payload(payload: dict[str, Any], name: str) -> None:
    """把内存里改过的 `data` 重新序列化回该件的 `text`/`sha256`/`bytes`（序列化口径同 §7）。"""
    set_portable_payload_text(payload, name, _bundle_text(payload["files"][name]["data"]))


def restamp_portable_manifest(payload: dict[str, Any]) -> None:
    """按 payload 当前的 `sha256`/`bytes` 重写 manifest 的 `portable_files` 声明（内存，不落盘）。

    用途同上：让 `[I2]` 那一关先过，于是「改 portable 件不更 manifest hash」与「改了 hash 也改了
    内容」这两种造假在判据上是**两枚不同的洞**，证伪台可以分别打。
    """
    manifest_entry = payload["files"][BUNDLE_MANIFEST_FILE]
    manifest = manifest_entry["data"]
    if not isinstance(manifest, dict):
        return
    by_name = {Path(str(item.get("path") or "")).name: item
               for item in manifest.get("portable_files") or [] if isinstance(item, dict)}
    for name in _BUNDLE_PAYLOAD_FILES:
        item = by_name.get(name)
        entry = payload["files"].get(name) or {}
        if item is not None and entry.get("sha256"):
            item["sha256"] = entry["sha256"]
            item["bytes"] = entry["bytes"]
    set_portable_payload_text(payload, BUNDLE_MANIFEST_FILE,
                              _bundle_text(manifest))


def _get(payload: dict[str, Any] | None, name: str) -> Any:
    """取某件的**已解析 dict**（缺件/解析失败 ⇒ None，由 `[I1]` 先报掉）。"""
    if not isinstance(payload, dict):
        return None
    entry = (payload.get("files") or {}).get(name)
    if not isinstance(entry, dict) or not entry.get("present"):
        return None
    return entry.get("data")


def _portable_bytes(payload: dict[str, Any], name: str) -> bytes:
    """该件在内存里的字节：优先用被探针改过的 `text`，否则回盘上读到的长度口径。"""
    entry = (payload.get("files") or {}).get(name) or {}
    text = entry.get("text")
    if isinstance(text, str):
        return text.encode("utf-8")
    return b""


def validate_portable_bundle(payload: dict[str, Any] | None,
                             *, manifest_sha256_pin: str | None = None,
                             repo_root: Path = REPO_ROOT) -> list[str]:
    """可移植证据包的判据：返回**问题清单**（空表 = bundle 成立、允许矩阵写 GREEN）。

    七条 interlock（R26 第 ③ 条点名的 CI 侧必检项）逐条落在这里，另加从 §6
    `validate_evidence()` 搬过来的逐条判据 `[C-*]`（凡 bundle 载得出的事实，一律仍是**必须**）。
    `manifest_sha256_pin` 是闸文件里的**外部锚**（manifest 给自己算 hash 是自指，算不出）；
    传 None 表示本次调用不做锚校验（只给闸内的退化探针用；CI 与本机那次一定传值）。
    """
    problems: list[str] = []
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
        return [f"[I1] bundle 整包不在场（{BUNDLE_REL_DIR} 下一枚都没读到）："
                "可移植证据包是 3B 之后 P0 的唯一 CI 判据载体"]
    files = payload["files"]

    # ---- [I1] 齐件：六枚一枚不缺、一枚不多（缺件 = 载体没了，不是「证据没跑过」）----
    for name in BUNDLE_FILE_NAMES:
        if not (files.get(name) or {}).get("present"):
            problems.append(f"[I1] bundle 件缺失：{name}（{BUNDLE_REL_DIR}/{name}）")
        elif (files[name] or {}).get("parse_error"):
            problems.append(f"[I1] bundle 件解析失败：{name} ⇒ {files[name]['parse_error']}")
    extras = sorted(p.name for p in Path(payload.get("dir") or BUNDLE_DIR).glob("*.json")
                    if p.name not in BUNDLE_FILE_NAMES)
    if extras:
        problems.append(f"[I1] bundle 目录里有契约之外的件：{extras}（六枚文件名就是契约）")

    manifest = _get(payload, BUNDLE_MANIFEST_FILE)
    if not isinstance(manifest, dict):
        problems.append("[I1] manifest 不是 JSON 对象：后面的 interlock 无从算起")
        return problems

    # ---- [I2] hash 全配 + manifest 自己被锚 ----
    declared = manifest.get("portable_files")
    if not isinstance(declared, list) or not declared:
        problems.append("[I2] manifest.portable_files 缺失或为空：没有可重算的声明")
        declared = []
    expected_paths = {f"{BUNDLE_REL_DIR}/{name}" for name in _BUNDLE_PAYLOAD_FILES}
    seen_paths = set()
    for item in declared:
        if not isinstance(item, dict):
            problems.append("[I2] portable_files 里有一枚不是对象")
            continue
        path_text = str(item.get("path") or "")
        seen_paths.add(path_text)
        name = Path(path_text).name
        entry = files.get(name)
        if entry is None or not entry.get("present"):
            problems.append(f"[I2] manifest 声明的件不在场：{path_text}")
            continue
        if str(repo_root / path_text) != str(entry.get("path")):
            problems.append(f"[I2] manifest 声明的路径与实读位置不同源（**必须按仓根解析、"
                            f"不得按 cwd**）：声明 {repo_root / path_text}，实读 {entry.get('path')}")
        if entry.get("sha256") != item.get("sha256"):
            problems.append(f"[I2] sha256 不配：{name}（manifest 说 {item.get('sha256')}，"
                            f"盘上 {entry.get('sha256')}）")
        if entry.get("bytes") != item.get("bytes"):
            problems.append(f"[I2] 字节数不配：{name}（manifest 说 {item.get('bytes')}，"
                            f"盘上 {entry.get('bytes')}）")
    if seen_paths != expected_paths:
        problems.append(f"[I2] portable_files 的路径集合不是那五枚：{sorted(seen_paths)}")
    if manifest_sha256_pin is not None:
        actual_manifest = (files.get(BUNDLE_MANIFEST_FILE) or {}).get("sha256")
        if actual_manifest != manifest_sha256_pin:
            problems.append(f"[I2] manifest 自己的 sha256 对不上闸里的外部锚（载体之外那枚锚）："
                            f"锚 {manifest_sha256_pin}，盘上 {actual_manifest}。"
                            "改了 bundle 就必须同时改闸上的锚——那是一处可见的代码改动，"
                            "不是改一枚 JSON 里的自述")
    # ---- 载体纯度：bundle 的本事就是「换载体不换含义」，所以它**不许**再长回单机耦合 ----
    for name in BUNDLE_FILE_NAMES:
        data = _get(payload, name)
        if data is None:
            continue
        if _ABSOLUTE_PATH_RE.search(json.dumps(data, ensure_ascii=False)):
            problems.append(f"[I2] {name} 里出现绝对路径：单机耦合正是这枚闸恒红的病根，"
                            "干净签出重算不了的路径不能进交付面")
        cr_present = bool((files.get(name) or {}).get("has_cr")) or \
            "\r" in ((files.get(name) or {}).get("text") or "")
        if cr_present:
            problems.append(f"[I2] {name} 含 CR：bundle 的六枚是纯 LF，混行尾会让 hash 随机器漂。"
                            "若这是 `git checkout` 干的：本机 `core.autocrlf` 与 `.gitattributes`"
                            " 的 `* text=auto` 会把签出的文本件转成 CRLF，"
                            "而闸钉的 sha256 量的是仓里那枚 LF 字节（CI 用 ubuntu-latest，"
                            "签出即 LF；Windows 上请让这枚路径保持 LF 再跑）")

    result = _get(payload, BUNDLE_RESULT_FILE) or {}
    response = _get(payload, BUNDLE_RESPONSE_FILE) or {}
    ledger_file = _get(payload, BUNDLE_LEDGER_ROW_FILE) or {}
    trace_file = _get(payload, BUNDLE_TRACE_FILE) or {}
    probe_file = _get(payload, BUNDLE_PROBE_FILE) or {}

    # ---- [C-*] 从 §6 搬来的逐条判据：凡 bundle 载得出，就仍是「必须」而不是「在场才校验」----
    for name, body in (("result.json", result), ("response.json", response),
                       ("ledger-row.json", ledger_file), ("trace-attempts.json", trace_file),
                       ("primary-probe.json", probe_file), ("manifest.json", manifest)):
        if body and body.get("case_id") != CASE_ID:
            problems.append(f"[C-case_id] {name} 的 case_id 不是 {CASE_ID}")
    if result.get("evidence_schema_version") != SCHEMA_VERSION:
        problems.append(f"[C-schema_version] result.json 的 evidence_schema_version "
                        f"应为 {SCHEMA_VERSION}")
    if manifest.get("evidence_schema_version") != BUNDLE_SCHEMA_VERSION:
        problems.append(f"[C-schema_version] manifest 的 evidence_schema_version "
                        f"应为 {BUNDLE_SCHEMA_VERSION}")

    assertions = _assertions_of(result)
    if len(assertions) != len(ASSERTION_NAMES):
        problems.append(f"[C-断言条数] result.json 的断言条数 {len(assertions)} != 10")
    if result.get("assertion_count") != len(ASSERTION_NAMES):
        problems.append(f"[C-断言条数] result.json 自报 assertion_count "
                        f"{result.get('assertion_count')} != 10")
    if result.get("all_pass") is not True:
        problems.append("[C-断言全过] result.json 的 all_pass 不为 true")
    for number, key, label in ASSERTION_NAMES:
        item = assertions.get(number)
        if item is None:
            problems.append(f"[C-断言条数] 缺第 {number} 枚断言（{label}）")
            continue
        if item.get("name") != key:
            problems.append(f"[C-断言名] 第 {number} 枚 name 应为 {key}")
        if item.get("pass") is not True:
            problems.append(f"[C-断言全过] 第 {number} 枚 pass 不为 true")
        observed = item.get("observed")
        if not isinstance(observed, dict) or not observed:
            problems.append(f"[C-断言实测值] 第 {number} 枚 observed 是空的：只有判词没有实测值")
    expected_names = [{"id": number, "name": key, "zh": zh}
                      for number, key, zh in ASSERTION_NAMES]
    if result.get("expected_assertion_names") != expected_names:
        problems.append("[C-断言名] result.json 的 expected_assertion_names 与 kit.ASSERTION_NAMES "
                        "不同源（§10 十字的清单不许有两份）")

    calls = response.get("provider_calls") or []
    if len(calls) != 2:
        problems.append(f"[C-外呼两次] 真外呼次数 {len(calls)} != 2（primary + fallback 各一次）")
    names = [call.get("model") for call in calls if isinstance(call, dict)]
    if names != [PRIMARY_MODEL, FALLBACK_MODEL]:
        problems.append(f"[C-模型序] 外呼模型序 {names} != [{PRIMARY_MODEL}, {FALLBACK_MODEL}]")
    for call in calls:
        if not isinstance(call, dict):
            problems.append("[C-外呼两次] provider_calls 里有一枚不是对象")
            continue
        if not isinstance(call.get("request_bytes"), int) or call["request_bytes"] <= 0:
            problems.append(f"[C-请求字节] {call.get('model')} 没有正的 request_bytes")
        if not isinstance(call.get("elapsed_ms"), (int, float)) or call["elapsed_ms"] <= 0:
            problems.append(f"[C-耗时] {call.get('model')} 没有正的 elapsed_ms（耗时没打？）")
    first = calls[0] if calls and isinstance(calls[0], dict) else {}
    second = calls[1] if len(calls) > 1 and isinstance(calls[1], dict) else {}
    if first.get("ok") is not False:
        problems.append("[C-primary真失败] primary 那枚外呼不是失败：P0 的前提没发生")
    if first.get("error_kind") != "model_unavailable":
        problems.append("[C-失败归类] primary 的归类不是 model_unavailable")
    excerpt = str(first.get("error_body_excerpt") or "")
    if len(excerpt) < 20:
        problems.append("[C-错误体原文] primary 的错误体摘要短于 20 字：没有服务端原文可复核")
    lowered = excerpt.lower()
    if not any(marker in lowered for marker in MODEL_UNAVAILABLE_MARKERS):
        problems.append("[C-错误体原文] primary 的错误体不含 §6 的加载失败特征字面")
    if second.get("ok") is not True:
        problems.append("[C-fallback成功] fallback 那枚外呼不是成功")

    transport_entry = files.get(BUNDLE_RESPONSE_FILE) or {}
    transport_data = transport_entry.get("data") or {}
    if "provider_transport" not in transport_data:
        problems.append("[C-传输层] response.json 没有 provider_transport 这一枚键："
                        "『读不到就算过』不是凭据，正面凭据必须是**写着 null**")
    elif transport_data.get("provider_transport") is not None:
        problems.append(f"[C-传输层] 这次运行挂了传输层替身 "
                        f"{transport_data['provider_transport']!r}：不是真机证据")
    #: H2 的源端那一半（3B 修复轮 1）：导出当刻原始件里**有没有这枚键**也是事实。
    #: 少了它，「从一份压根没记 provider_transport 的原始件洗出来的 bundle」照样能写着 null 过关。
    if transport_data.get("provider_transport_present") is not True:
        problems.append("[C-传输层] response.json 的 provider_transport_present 不为 true："
                        "原始证据 JSON 里根本没有 provider_transport 这枚键（缺键 ≠ 为 null），"
                        "非彩排的正面凭据必须是**键在场且写着 null**")

    answer = response.get("answer") or {}
    answer_text = str(answer.get("text") or "")
    if len(answer_text) < MIN_ANSWER_CHARS:
        problems.append("[C-答案长度] phi3 的答案短于下限")
    if len(_CJK.findall(answer_text)) < MIN_ANSWER_CJK_CHARS:
        problems.append("[C-答案中文] phi3 答案的 CJK 字数低于下限")
    summary = response.get("summary") or {}
    if not isinstance(summary.get("elapsed_ms_sum"), (int, float)) or summary["elapsed_ms_sum"] <= 0:
        problems.append("[C-耗时] response.json 的 summary.elapsed_ms_sum 缺失或非正")

    row = ledger_file.get("row") or {}
    if ledger_file.get("trace_id") != row.get("trace_id"):
        problems.append("[C-trace_id] ledger-row.json 顶层 trace_id 与 row.trace_id 不同源")
    if (ledger_file.get("ledger_source") or {}).get("rows") != 1:
        problems.append(f"[C-账本一行] 临时库行数 "
                        f"{(ledger_file.get('ledger_source') or {}).get('rows')} != 1")
    hits = ledger_file.get("canary_hits") or []
    if hits:
        problems.append("[C-canary零命中] canary 在账本里命中了：§8 的「零 prompt 入库」破防")
    for needle in (PROMPT_CANARY,):
        if needle not in (ledger_file.get("canary_needles") or []):
            problems.append(f"[C-canary针] canary 清单里没有 {needle[:16]}…：扫的不是这份 prompt")
    if row.get("fallback_index") != 1:
        problems.append("[C-fallback_index] 账本行的 fallback_index != 1")
    if row.get("success") not in (1, True):
        problems.append("[C-账本success] 账本行 success 不为真")
    if row.get("model") != FALLBACK_MODEL:
        problems.append(f"[C-账本model] 账本行的 model 不是 {FALLBACK_MODEL}")
    for column in _BUNDLE_FORBIDDEN_COLUMNS:
        if column in row:
            problems.append(f"[C-禁存列] 账本行出现了禁存列 {column}")
    proof = ledger_file.get("forbidden_column_proof") or {}
    if tuple(proof.get("columns_checked") or ()) != _BUNDLE_FORBIDDEN_COLUMNS:
        problems.append("[C-禁存列] forbidden_column_proof.columns_checked 与 §6 那份清单不同源")
    if proof.get("columns_present_in_row"):
        problems.append(f"[C-禁存列] 证明件自己写着出现了禁存列 {proof['columns_present_in_row']}")
    if proof.get("canary_hit_count") != len(hits):
        problems.append("[C-canary零命中] canary_hit_count 与 canary_hits 的实际条数不等")

    attempts = trace_file.get("model_route_attempts") or []
    if len(attempts) != 2:
        problems.append("[C-两枚attempt] trace 的 model_route.attempts 不是两枚")
    if trace_file.get("trace_id_consistent") is not True:
        problems.append("[C-trace_id] trace-attempts.json 自报 trace_id_consistent 不为 true")
    if trace_file.get("trace_id") != row.get("trace_id"):
        problems.append("[C-trace_id] trace-attempts 与账本行的 trace_id 不同源")

    # ---- [I3] 三处同源：response.model == ledger.row.model == 成功那枚 attempt.model == phi3 ----
    success_indexes = [index for index, item in enumerate(attempts)
                       if isinstance(item, dict) and item.get("result") == "success"]
    if success_indexes != [1]:
        problems.append(f"[I3] 成功的 trace attempt 不是恰好第 1 枚：{success_indexes}")
    selected = trace_file.get("model_route_selected_index")
    if selected != 1:
        problems.append(f"[I3] model_route_selected_index {selected} != 1")
    if trace_file.get("model_route_stage") != "fallback":
        problems.append(f"[I3] model_route_stage 不是 fallback：{trace_file.get('model_route_stage')}")
    success_model = (attempts[1].get("model")
                     if len(attempts) > 1 and isinstance(attempts[1], dict) else None)
    answer_model = (response.get("answer") or {}).get("model")
    chain_model = (trace_file.get("chain") or {}).get("response_model")
    if {answer_model, row.get("model"), success_model, chain_model} != {FALLBACK_MODEL}:
        problems.append(f"[I3] 三处同源的 fallback 模型名不全是 {FALLBACK_MODEL}："
                        f"answer.model={answer_model} ledger.row.model={row.get('model')} "
                        f"成功 attempt.model={success_model} chain.response_model={chain_model}")
    if (result.get("assertions") or [{}]) and isinstance(assertions.get(4), dict):
        observed4 = assertions[4].get("observed") or {}
        if observed4.get("model_field") != FALLBACK_MODEL:
            problems.append(f"[I3] 第 4 枚断言 observed.model_field "
                            f"{observed4.get('model_field')} != {FALLBACK_MODEL}")
    observed10 = (assertions.get(10) or {}).get("observed") or {}
    if observed10.get("status_code") != 200:
        problems.append(f"[C-api面200] 第 10 枚断言 observed.status_code "
                        f"{observed10.get('status_code')} != 200（§10 P0 行的最后一枚是"
                        "「fallback 成功不塌成 5xx」，这一格在 bundle 里是可重算的量，"
                        "不是只有一句 pass=true）")

    # ---- [I4] 计划主模型 == kit.PRIMARY_MODEL（复用常量，不复抄字面量）----
    plan = manifest.get("plan") or {}
    planned = plan.get("primary_model")
    if planned != PRIMARY_MODEL:
        problems.append(f"[I4] manifest.plan.primary_model {planned!r} != {PRIMARY_MODEL}")
    if plan.get("primary_entry") != PRIMARY_ENTRY_ID:
        problems.append(f"[I4] manifest.plan.primary_entry "
                        f"{plan.get('primary_entry')!r} != {PRIMARY_ENTRY_ID}")
    if plan.get("fallback_models") != [FALLBACK_MODEL]:
        problems.append(f"[I4] manifest.plan.fallback_models {plan.get('fallback_models')!r} "
                        f"!= [{FALLBACK_MODEL}]")
    attempt0 = attempts[0] if attempts and isinstance(attempts[0], dict) else {}
    if attempt0.get("model") != PRIMARY_MODEL:
        problems.append(f"[I4] attempts[0].model {attempt0.get('model')!r} != {PRIMARY_MODEL}"
                        "（计划主模型与真外呼的第一枚对不上）")
    if attempt0.get("result") != "failed":
        problems.append(f"[I4] attempts[0].result {attempt0.get('result')!r} != failed")
    observed7 = (assertions.get(7) or {}).get("observed") or {}
    if (observed7.get("primary") or {}).get("model") != PRIMARY_MODEL:
        problems.append(f"[I4] 第 7 枚断言 observed.primary.model 不是 {PRIMARY_MODEL}")
    if first.get("model") != PRIMARY_MODEL:
        problems.append(f"[I4] response.provider_calls[0].model 不是 {PRIMARY_MODEL}")

    # ---- [I5] primary-probe.json 命中的是文档化的加载失败族（原文要求一字不松）----
    probe_body = probe_file.get("probe") or {}
    probe_markers = (f"{probe_body.get('raw_error_body') or ''} "
                     f"{(probe_body.get('classification') or {}).get('message') or ''}").lower()
    if not any(marker in probe_markers for marker in MODEL_UNAVAILABLE_MARKERS):
        problems.append("[I5] primary-probe.json 的原文不含 §6 那族加载失败特征字面 "
                        f"{MODEL_UNAVAILABLE_MARKERS}：探针撑不起『真加载失败』这一枚前提")
    if (probe_body.get("classification") or {}).get("kind") != "model_unavailable":
        problems.append("[I5] 探针的 classification.kind 不是 model_unavailable")
    if probe_body.get("status_code") != 500:
        problems.append(f"[I5] 探针的 status_code {probe_body.get('status_code')} != 500")
    if probe_body.get("probe_result") != "load_failed":
        problems.append("[I5] 探针的 probe_result 不是 load_failed")
    if probe_body.get("model") != PRIMARY_MODEL:
        problems.append(f"[I5] 探针打的模型不是计划主模型 {PRIMARY_MODEL}")
    if probe_body.get("answer_content") is not None:
        problems.append("[I5] 探针居然拿到了答案：primary 没失败，P0 的前提不成立")

    # ---- [I6] trace_id 跨文件逐字符一致（顶层 trace_id 键在原始件里不存在，这里只读 bundle）----
    trace_ids = {"manifest": manifest.get("trace_id"),
                 "trace-attempts": trace_file.get("trace_id"),
                 "ledger-row": ledger_file.get("trace_id"),
                 "ledger-row.row": row.get("trace_id")}
    values = set(trace_ids.values())
    if len(values) != 1 or None in values or "" in values:
        problems.append(f"[I6] trace_id 四处不一致或为空：{trace_ids}")
    pointers = (manifest.get("trace_id_source") or {}).get("pointers")
    #: M2（3B 修复轮 1）：过去这条件是 `set(pointers.values()) - {None} != values
    #: or len(pointers) != 3`——把任一枚指针改成 `null`，`- {None}` 就把它摘掉，剩下的两枚
    #: 照样等于 `values`，枚数也还是 3 ⇒ 「三处同源」在**少一条腿**的情况下宣告成立。
    #: 现在要求：键名集合恰好是那三枚、每一枚都非 null、且它们的值就是那个唯一真值。
    if not isinstance(pointers, dict):
        problems.append(f"[I6] manifest.trace_id_source.pointers 不是对象：{pointers!r}")
    elif tuple(sorted(pointers)) != tuple(sorted(_TRACE_ID_POINTER_KEYS)):
        problems.append(f"[I6] trace_id_source.pointers 的键名不是那三枚："
                        f"{sorted(pointers)} != {sorted(_TRACE_ID_POINTER_KEYS)}")
    elif any(value is None for value in pointers.values()):
        problems.append(f"[I6] trace_id_source.pointers 里有指针为 null：{pointers}"
                        "——三处同源要的是三条腿都在，缺腿不等于一致")
    elif set(pointers.values()) != values:
        problems.append(f"[I6] manifest.trace_id_source.pointers 与四处真值不同源：{pointers}")
    if (manifest.get("trace_id_source") or {}).get("consistent") is not True:
        problems.append("[I6] manifest.trace_id_source.consistent 不为 true")
    observed6 = (assertions.get(6) or {}).get("observed") or {}
    if {observed6.get("entry_trace_id"), observed6.get("ledger_trace_id"),
            observed6.get("trace_file_trace_id")} != values:
        problems.append("[I6] 第 6 枚断言 observed 里的三枚 trace_id 与 bundle 四处不同源")

    # ---- [I7 的前半] provenance / 反彩排：这些都长在 manifest 自己身上，矩阵状态那半在闸里 ----
    if manifest.get("exported_by", {}).get("function") != BUNDLE_EXPORT_FUNCTION:
        problems.append(f"[I7] exported_by.function 不是本机导出函数 {BUNDLE_EXPORT_FUNCTION}")
    #: H1 / H2 的载体侧（3B 修复轮 1）：原始 JSON 那五枚运行形态布尔位**文本化进了 manifest**，
    #: 于是它们落在被外部锚钉住的字节上，portable 层单独就能判——不再需要「raw 本体在场」
    #: 这个前提。这里的强度是「必须」，不是「在场才必须」。
    flags = manifest.get("source_run_flags")
    if not isinstance(flags, dict):
        problems.append("[I7] manifest.source_run_flags 不在场或不是对象：completed / "
                        "rehearsal / provider_transport 三枚真值判据在 portable 层没有载体")
    else:
        for key in sorted(_source_run_flags({})):      # 键名集合的唯一出处就是这枚算式
            if key not in flags:
                problems.append(f"[I7] source_run_flags 缺 {key} 这一枚布尔位")
        if flags.get("completed_is_true") is not True:
            problems.append(f"[I7] source_run_flags.completed_is_true 不为 true（实得 "
                            f"{flags.get('completed_is_true')!r}）：这次运行没到收尾")
        if flags.get("rehearsal_truthy"):
            problems.append("[I7] source_run_flags.rehearsal_truthy 为真：离线彩排件"
                            "（MockTransport）不许撑起 GREEN")
        if flags.get("provider_transport_key_present") is not True:
            problems.append("[I7] source_run_flags.provider_transport_key_present 不为 true："
                            "原始件里根本没有 provider_transport 这枚键——缺键不是 null，"
                            "『读不到就算过』不是凭据")
        if flags.get("provider_transport_is_null") is not True:
            problems.append(f"[I7] source_run_flags.provider_transport_is_null 不为 true："
                            f"实得 {flags.get('provider_transport_is_null')!r}：挂了传输层替身")
    provenance = manifest.get("raw_provenance")
    if not isinstance(provenance, list) or len(provenance) != len(_RAW_PROVENANCE_EXPECTATIONS):
        problems.append(f"[I7] raw_provenance 应为 {len(_RAW_PROVENANCE_EXPECTATIONS)} 枚，"
                        f"实得 {provenance if isinstance(provenance, list) else type(provenance)}")
        provenance = provenance if isinstance(provenance, list) else []
    roles = {(item or {}).get("role") for item in provenance if isinstance(item, dict)}
    if roles != {role for role, _name in _RAW_PROVENANCE_EXPECTATIONS}:
        problems.append(f"[I7] raw_provenance 的 role 集合不是那四枚：{sorted(roles)}")
    for item in provenance:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        expected_name = dict(_RAW_PROVENANCE_EXPECTATIONS).get(role)
        if expected_name and item.get("name") != expected_name:
            problems.append(f"[I7] {role} 的 name 应为 {expected_name}，实得 {item.get('name')}")
        if role in _GIT_BLOB_ROLES:
            #: M1 裁定的载体侧：这一枚 provenance 必须自带**签出无关**的那条腿。
            #: 缺 `git_blob` / 形状不对 / `repo_path` 不是仓相对 posix ⇒ 当场红（不许静默降级
            #: 回「只比工作树 sha1」，那正是 Windows 签出会冤枉真话的那条路）。
            blob = str(item.get("git_blob") or "")
            if not re.fullmatch(r"[0-9a-f]{40}", blob):
                problems.append(f"[I7] {role} 的 git_blob 不是 40 位十六进制：{blob!r}"
                                "（被跟踪的交付件必须有 blob 身份这一条腿；导出时 git 读不到"
                                "就是要在这里响，不是留到 raw 层再猜）")
            repo_path = item.get("repo_path")
            if repo_path != _ACCEPTANCE_REPO_PATH:
                problems.append(f"[I7] {role} 的 repo_path 应为仓相对 {_ACCEPTANCE_REPO_PATH!r}，"
                                f"实得 {repo_path!r}（raw 层拿它做 `git rev-parse HEAD:<path>`，"
                                "写成绝对路径就把这枚判据变回单机耦合）")
        digest = str(item.get("sha1") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", digest):
            problems.append(f"[I7] {role} 的 sha1 不是 40 位十六进制：{digest!r}"
                            "（<missing> 之类的占位说明导出时那枚件就不在）")
            continue
        if item.get("recorded_sha1") != digest:
            problems.append(f"[I7] {role} 当场重算的 sha1 与证据自己的 files_sha1 记录值不等："
                            f"{digest} vs {item.get('recorded_sha1')}")
        if item.get("matches_recorded") is not True:
            problems.append(f"[I7] {role} 的 matches_recorded 不为 true：导出当刻原始件就对不上"
                            "证据自己的指纹表（彩排件/被换过的件正是从这里露出来）")
        if item.get("present") is not True:
            problems.append(f"[I7] {role} 导出当刻 present 不为 true：本体不在，provenance 是空的")
    run_dir = manifest.get("source_run_dir")
    if not isinstance(run_dir, str) or not run_dir:
        problems.append("[I7] manifest.source_run_dir 缺失：没有它就只能按 basename 找原始件，"
                        "而同名彩排件是实测存在的（3A findings 7）")
    else:
        parts = [part for part in run_dir.split("/") if part]
        if any(part.lower() == "rehearsal" for part in parts):
            problems.append(f"[I7] source_run_dir 指向彩排目录：{run_dir}"
                            "——离线彩排件（MockTransport）永远不许撑起 GREEN")
        if not run_dir.startswith(f"{EVIDENCE_DIR.relative_to(REPO_ROOT).as_posix()}/"):
            problems.append(f"[I7] source_run_dir 不在证据目录之下：{run_dir}")
        elif len(parts) < 2 or parts[-2] != "run" or not _SOURCE_RUN_STEM_RE.fullmatch(parts[-1]):
            problems.append(f"[I7] source_run_dir 的末两段不是 run/<yyyymmdd>-<hhmmss> 形状："
                            f"{run_dir}")
    if manifest.get("trace_id") is not None and not manifest.get("absent_source_fields"):
        problems.append("[I7] manifest 没有 absent_source_fields 诚实清单：release_image 这类"
                        "原始件里没有的字段必须写明『为什么是 null』，不许静默")
    tree_hash = manifest.get("source_tree_hash")
    if tree_hash is not None and not re.fullmatch(r"[0-9a-f]{7,40}", str(tree_hash)):
        problems.append(f"[I7] source_tree_hash 不是 git 对象 id 的形状：{tree_hash!r}")
    return problems


def resolve_raw_provenance(manifest: dict[str, Any] | None,
                           *, repo_root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    """按 **双条件**定位原始件：仓根 + `manifest.source_run_dir` + 该 role 的 name。

    这是本文件里唯一允许碰原始件的定位代码，它的规矩写死在这里：
    - **绝不** `rglob(name)`、**绝不**按字节大小挑选、**绝不**用 `files_sha1` 里那枚绝对路径
      （那枚绝对路径在干净签出上指向别的机器 / 干脆不存在，正是 R25 诊断出的病根）；
    - 两枚 run 目录里的件走 `source_run_dir`；probe 与 acceptance 模块走 kit 自己的常量路径
      （`PROBE_FILE` / `ACCEPTANCE_FILE`，同样由仓根锚定）；
    - 定位到之后仍然要**逐枚重算 sha1**，与 `raw_provenance[].sha1` 和 `recorded_sha1` 两两对齐。
    - **例外（M1 裁定）**：`_GIT_BLOB_ROLES` 里那枚 = `acceptance_module` 是四枚里唯一**被 git
      跟踪**的件，它的「工作树字节 sha1」是**签出相关**的（`* text=auto` + `core.autocrlf=true`
      的 Windows 签出可能是 CRLF，Linux CI 是 LF）⇒ 这一枚改记/改比 **blob 身份**：
      `git_blob_recorded`（manifest 里那枚）/ `git_blob_head`（`git rev-parse HEAD:<repo_path>`）/
      `git_blob_worktree`（`git hash-object` 当下工作树，过 clean 过滤器）。blob 相等于是
      「同一份内容」这件事与 EOL 形态无关，本机与 CI 于是拿到**同一条真重算腿**。
    """
    entries = (manifest or {}).get("raw_provenance")
    if not isinstance(entries, list):
        return []
    run_dir = (manifest or {}).get("source_run_dir")
    out: list[dict[str, Any]] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        role, name = item.get("role"), item.get("name")
        if role in _RUN_DIR_ROLES and isinstance(run_dir, str) and run_dir:
            target: Path | None = repo_root / run_dir / str(name)
            locator = "仓根 + manifest.source_run_dir + name"
        elif role == "primary_probe":
            target, locator = PROBE_FILE, "kit.PROBE_FILE（仓根锚定的唯一出处）"
        elif role == "acceptance_module":
            target, locator = ACCEPTANCE_FILE, "kit.ACCEPTANCE_FILE（被跟踪的交付件）"
        else:
            target, locator = None, "无定位规则"
        present = bool(target is not None and Path(target).is_file())
        actual = sha1_of(target) if present else "<missing>"
        declared = str(item.get("sha1") or "")
        recorded = str(item.get("recorded_sha1") or "")
        row: dict[str, Any] = {
            "role": role, "name": name, "path": str(target) if target else None,
            "locator": locator, "present": present, "sha1": actual,
            "declared_sha1": declared, "recorded_sha1": recorded,
            "matches_declared": present and actual == declared,
            "matches_recorded": present and actual == recorded}
        if role in _GIT_BLOB_ROLES:
            repo_path = item.get("repo_path")
            row["repo_path"] = repo_path if isinstance(repo_path, str) else None
            row["git_blob_recorded"] = str(item.get("git_blob") or "") or None
            row["git_blob_head"] = (
                git_blob_of_head(repo_path, repo_root=repo_root)
                if isinstance(repo_path, str) and repo_path else None)
            row["git_blob_worktree"] = (git_blob_of_worktree(target, repo_root=repo_root)
                                        if present else None)
            row["matches_blob"] = bool(row["git_blob_recorded"]
                                       and row["git_blob_recorded"] == row["git_blob_head"]
                                       and row["git_blob_worktree"] == row["git_blob_recorded"])
        out.append(row)
    return out


def blob_leg_problems(row: dict[str, Any]) -> list[str]:
    """`_GIT_BLOB_ROLES` 那一枚的 raw 腿：按 **git blob 身份**验，不按工作树字节验。

    三条都判，缺一即红（这一条腿在干净签出里也真跑得动，所以 M1 之后 `json-only` 分支
    也调用它 —— CI 第一次拿到一枚可重算的 raw 判据）：
    1. manifest 记的 `git_blob` 必须是 40 位十六进制；
    2. 必须等于 `git rev-parse HEAD:<repo_path>`（载体描述的那棵树里这枚交付件就是这份内容）；
    3. 当下工作树 `git hash-object` 出来的 blob 必须还是同一枚（本地改了没提交也算不一致）。
    """
    problems: list[str] = []
    role = row.get("role")
    recorded = row.get("git_blob_recorded") or ""
    head = row.get("git_blob_head")
    worktree = row.get("git_blob_worktree")
    if not re.fullmatch(r"[0-9a-f]{40}", str(recorded)):
        problems.append(f"[I7-blob] {role} 的 git_blob 记录值不可用：{recorded!r}")
        return problems
    if head is None:
        problems.append(f"[I7-blob] 读不到 `git rev-parse HEAD:{row.get('repo_path')}`"
                        f"（{role}）：这枚被跟踪的交付件不在当前提交里，或这棵树不是 git 仓库"
                        "——不可判按红处理，不许静默放过")
    elif recorded != head:
        problems.append(f"[I7-blob] {role} 的 blob 与 HEAD 里的不等：bundle 记 {recorded}，"
                        f"HEAD:{row.get('repo_path')} 是 {head}"
                        "⇒ 载体描述的那份交付件已经不是现在仓库里的这一枚（签出形态不参与本判据）")
    if worktree is None:
        problems.append(f"[I7-blob] {role} 的工作树文件不在场：{row.get('path')}"
                        "（它被 git 跟踪 ⇒ 任何签出都该有它；缺席 = 有人删了判据的对象）")
    elif worktree != recorded:
        problems.append(f"[I7-blob] {role} 的工作树重算 blob 与记录不等：{worktree} vs "
                        f"{recorded}（{row.get('path')}）⇒ 本地有未提交的改动")
    return problems


def raw_layer_problems(resolved: list[dict[str, Any]]) -> list[str]:
    """raw 层（**在场才校验**）里 provenance 那一半：逐枚重算 sha1，blob 腿除外。

    `_GIT_BLOB_ROLES` 里那一枚走 `blob_leg_problems()`（签出无关），其余三枚维持
    「sha1 + 只在在场时校验」的语义一字未动；缺席的运行态件继续**不构成红**（R26 ③）。
    """
    problems: list[str] = []
    for row in resolved:
        if row.get("role") in _GIT_BLOB_ROLES:
            problems += blob_leg_problems(row)
            continue
        if not row["present"]:
            continue      # 不在场 = 这一层这一枚不跑（由 verdict 的 raw_state 说清），不是问题
        if not row["matches_declared"]:
            problems.append(f"[I7] 原始件 sha1 与 bundle 声明不等：{row['role']} "
                            f"{row['declared_sha1']} vs 盘上 {row['sha1']}（{row['path']}）")
        if not row["matches_recorded"]:
            problems.append(f"[I7] 原始件 sha1 与证据自己的 files_sha1 记录值不等："
                            f"{row['role']} {row['recorded_sha1']} vs 盘上 {row['sha1']}")
    return problems


def tracked_evidence_truth_problems(evidence: dict[str, Any] | None) -> list[str]:
    """从**已跟踪的原始证据 JSON** 逐枚判三枚真值判据——**无条件**，不看 raw 本体在不在场。

    3B 修复轮 1 的 H1 / H2。这三枚判据原本只长在 §6 `validate_evidence()` 里，而 §6 那一层
    被分层条件成了「四枚运行态原始件都在场才跑」⇒ 干净签出（CI 的形态）里它们**一次都不执行**：
    往这枚已跟踪的 JSON 里注入 `"rehearsal": true` 或 `"completed": false`、或干脆把
    `provider_transport` 这枚键删掉，闸照样绿。这三枚都不是「运行态本体的属性」，
    而是**这枚被跟踪的文本自己写着的事实** ⇒ 没有任何理由按 raw 缺席来条件化它们。

    为什么这里不算放宽 §6：§6 那三行**一字未动**（本机 full 分支里它们照旧响），本函数只是
    把同一件事在**另一层**再判一遍；两条腿的标签不同（`[T-*]` vs §6 的原句），
    为的是红的时候读得懂是哪一层抓住的，而不是让同一句话有两个名字。
    """
    if not isinstance(evidence, dict):
        return ["[T-载体] 已跟踪的原始证据 JSON 读不出对象：rehearsal / completed / "
                "provider_transport 三枚真值判据**无从执行**（缺键不算通过，缺整件也不算）"]
    problems: list[str] = []
    if evidence.get("rehearsal"):
        problems.append("[T-彩排] 原始证据 JSON 自己写着 rehearsal 为真：这是**离线彩排件**"
                        "（provider 传输层被换成 MockTransport），它不许撑起矩阵 GREEN——"
                        "简报『反彩排件』那一条要求保留的就是这一枚真值判定")
    if evidence.get("completed") is not True:
        problems.append(f"[T-收尾] 原始证据 JSON 的 completed 不为 true（实得 "
                        f"{evidence.get('completed')!r}）：这次运行没跑到收尾，任何断言都不作数")
    #: H2 的核心形状：**成员判定**而不是 `.get()`。缺键与显式 null 在 `.get()` 下面都是 None，
    #: 于是唯一的非彩排正面凭据退化成了『读不到就算过』；这里把两件事拆开，缺键单独响。
    if "provider_transport" not in evidence:
        problems.append("[T-传输层] 原始证据 JSON 里**没有 provider_transport 这枚键**："
                        "缺键不等于为 null，非彩排的正面凭据必须是『键在场且写着 null』"
                        "（简报『反彩排件』里点名的『不是靠读不到就算过』）")
    elif evidence["provider_transport"] is not None:
        problems.append(f"[T-传输层] 这次运行挂了传输层替身 "
                        f"{evidence['provider_transport']!r}：MockTransport 下的 JSON 不是真机证据")
    return problems


def cross_check_bundle_and_raw(payload: dict[str, Any] | None,
                               evidence: dict[str, Any] | None) -> list[str]:
    """bundle ↔ 原始证据 JSON 的**面对面**核对（原始件在场才跑，纯文本比较、不碰绝对路径）。

    存在的理由：换载体最怕的就是「bundle 说 A、原始件说 B」——那枚 bundle 就是从别的 run
    （或彩排 run）洗出来的。这里逐段比 `build_portable_bundle` 声明的机械投影：
    投影既然是逐字取值，两份就必须相等；不等 ⇒ 载体与真源不是同一次运行。
    """
    problems: list[str] = []
    if not isinstance(evidence, dict) or not isinstance(payload, dict):
        return problems
    manifest = _get(payload, BUNDLE_MANIFEST_FILE) or {}
    result = _get(payload, BUNDLE_RESULT_FILE) or {}
    response = _get(payload, BUNDLE_RESPONSE_FILE) or {}
    ledger_file = _get(payload, BUNDLE_LEDGER_ROW_FILE) or {}
    trace_file = _get(payload, BUNDLE_TRACE_FILE) or {}

    def compare(label: str, left: Any, right: Any) -> None:
        if left != right:
            problems.append(f"[X] bundle 与原始证据不同源（{label}）：bundle 说 "
                            f"{str(left)[:120]!r}，原始件说 {str(right)[:120]!r}"
                            "——载体与真源不是同一次运行，或者有人改了其中一份")

    compare("case_id", manifest.get("case_id"), evidence.get("case_id"))
    compare("source_run_generated_at", manifest.get("source_run_generated_at"),
            evidence.get("generated_at"))
    compare("trace.trace_id", trace_file.get("trace_id"),
            (evidence.get("trace") or {}).get("trace_id"))
    compare("ledger.row", ledger_file.get("row"),
            _scrub_absolute_paths((evidence.get("ledger") or {}).get("row") or {}))
    compare("answer", response.get("answer"), _scrub_absolute_paths(evidence.get("answer") or {}))
    compare("provider_calls", response.get("provider_calls"),
            _scrub_absolute_paths(evidence.get("provider_calls") or []))
    compare("provider_transport", response.get("provider_transport"),
            evidence.get("provider_transport"))
    #: H2（3B 修复轮 1）：上面那枚 `compare` 用的是 `.get()`，「键不存在」与「键为 null」
    #: 在它眼里长得一样。所以这里既比**源端成员判定**（response.json 的那枚新字段），
    #: 也逐枚比 manifest `source_run_flags` 与「拿同一份算式现读原始件」的结果——
    #: 算式只有 `_source_run_flags()` 一份，两份结果不等就说明载体与真源不是同一次运行。
    compare("provider_transport_present", response.get("provider_transport_present"),
            "provider_transport" in evidence)
    #: H1（3B 修复轮 1）：`rehearsal` / `completed` 这两枚真值过去在这一层**根本没人比**，
    #: 于是「bundle 说这次跑完了、原始件说没跑完（或干脆写着是彩排件）」这种载体与真源
    #: 不同源的形状是静默放过的。五枚布尔位逐枚比，缺键与 false 也不算同一件事。
    flags = manifest.get("source_run_flags")
    compare("source_run_flags 在场", isinstance(flags, dict), True)
    live_flags = _source_run_flags(evidence)
    for key, value in sorted(live_flags.items()):
        compare(f"source_run_flags.{key}", (flags or {}).get(key), value)
    compare("assertions", result.get("assertions"),
            [_scrub_absolute_paths(item) for item in evidence.get("assertions") or []])
    compare("plan", manifest.get("plan"), evidence.get("plan"))
    compare("trace.model_route_attempts", trace_file.get("model_route_attempts"),
            _scrub_absolute_paths((evidence.get("trace") or {}).get("model_route_attempts")))
    compare("chain", trace_file.get("chain"), _scrub_absolute_paths(evidence.get("chain")))
    compare("ledger.rows", (ledger_file.get("ledger_source") or {}).get("rows"),
            (evidence.get("ledger") or {}).get("rows"))
    compare("ledger.canary_needles", ledger_file.get("canary_needles"),
            _scrub_absolute_paths((evidence.get("ledger") or {}).get("canary_needles")))
    compare("ledger.canary_hits", ledger_file.get("canary_hits"),
            _scrub_absolute_paths((evidence.get("ledger") or {}).get("canary_hits") or []))
    return problems


def p0_evidence_verdict(*, manifest_sha256_pin: str | None = None,
                        bundle_dir: Path | str = BUNDLE_DIR,
                        evidence_path: Path | str = EVIDENCE_FILE,
                        repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """「P0 这一行有没有资格 GREEN」的**完整**判定 = portable 层（必须）+ `[T-*]`（无条件）
    + raw 层（provenance/blob 两条分支都跑，`validate_evidence()` 仍是在场才跑）。

    返回的 `raw_state` 就是要打印给第一现场看的那枚分支：
    - `full`      —— 四枚原始件都能按 `source_run_dir` + sha1 双条件定位到 ⇒ §6 的
                     `validate_evidence()` 全量跑一遍（判据一字未改），再加 provenance + 面对面核对；
    - `json-only` —— 原始证据 JSON 在场、但 run 目录里的件不在（干净签出的正常形态）⇒
                     **provenance/blob 腿照旧逐枚重算**（M1 修复轮 1：过去这里全有或全无，
                     篡改一枚 + 缺席一枚会静默放过），再加面对面核对；§6 那一层因为它的
                     对象（run 目录本体）没入库，仍然只在 `full` 里跑——这是 §5 表里那格条件化；
    - `absent`    —— 连已跟踪的证据 JSON 都不在场 ⇒ `[T-*]` 那一层**自己响**（不可判 ≠ 通过），
                     provenance/blob 腿与 §6 不参与。
    三条分支共同点是 portable 层无条件必须过；`[T-*]`（H1/H2）在三条分支里都执行。
    """
    payload, bundle_error = read_portable_bundle(bundle_dir)
    portable = validate_portable_bundle(payload, manifest_sha256_pin=manifest_sha256_pin,
                                       repo_root=repo_root)
    manifest = _get(payload, BUNDLE_MANIFEST_FILE) or {}
    evidence, evidence_error = read_evidence(evidence_path)
    resolved = resolve_raw_provenance(manifest, repo_root=repo_root)
    all_present = bool(resolved) and all(row["present"] for row in resolved)

    #: 三枚真值判据（`[T-*]`）：**只要这枚已跟踪的 JSON 在场就判**，与 run 目录里那三枚
    #: 没入库的本体在不在场无关（H1/H2）。它不在场也不能算过——那是第四种「读不到就算过」，
    #: 所以 `absent` 分支在这里给一条响的判据，而不是安静地把这三枚判据丢掉。
    truth = tracked_evidence_truth_problems(evidence)
    #: provenance 那一半（含 `acceptance_module` 的 git blob 腿）**两条分支都要调**（M1）：
    #: `raw_layer_problems()` 本来就跳过不在场的条目，所以「在场但对不上 ⇒ 红」在
    #: `json-only` 里同样成立。过去这里写成全有或全无，于是「篡改 agent_traces.jsonl
    #: 并且删掉 conversations.db」这一组合会让整层**静默不跑**（实测 15 passed）。
    raw: list[str] = []
    if evidence is not None:
        raw_state = "full" if all_present else "json-only"
        raw = raw_layer_problems(resolved)
        if all_present:
            raw = validate_evidence(evidence) + raw
        raw = raw + cross_check_bundle_and_raw(payload, evidence)
    else:
        raw_state = "absent"

    return {
        "case_id": CASE_ID,
        "checked_at": utc_now(),
        "bundle_dir": str(Path(bundle_dir)),
        "bundle_read_error": bundle_error,
        "portable_problems": portable,
        "raw_state": raw_state,
        "truth_problems": truth,
        "raw_problems": raw,
        "raw_evidence_error": evidence_error,
        "resolved_raw": resolved,
        "problems": portable + truth + raw,
        "note": "判据 = portable 层（七条 interlock + 搬过来的 [C-*] 逐条判据）"
                " + [T-*]（已跟踪 JSON 的三枚真值，无条件）"
                " + raw 层（provenance/blob 腿两条分支都跑；validate_evidence() 仅 full 分支，"
                "判据本体一字未改 + 面对面核对）。",
    }


if __name__ == "__main__":          # 手工跑一次探针：python tests/real_llm_failover_kit.py
    _record = probe_primary_load()
    print(json.dumps(_record, ensure_ascii=False, indent=2))
