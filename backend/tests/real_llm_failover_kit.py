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
from typing import Any

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
#: 上限不设（真生成的长度不可预测）。
MIN_ANSWER_CHARS = 8
MIN_ANSWER_CJK_CHARS = 4

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
    if not any(marker in lowered for marker in
               ("alloc", "failed to load", "not found", "no such model")):
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


def green_permission(evidence_path: Path | str = EVIDENCE_FILE) -> dict[str, Any]:
    """「矩阵 P0 行能不能改成 GREEN」的许可判定：逐条列条件，**runner 与闸同一份**。

    本函数不改矩阵、不写矩阵——那一步归主 agent 裁（A-4 的硬约束）。
    """
    evidence, read_error = read_evidence(evidence_path)
    status = matrix_p0_status()
    problems = validate_evidence(evidence)
    conditions = [
        ("证据 JSON 存在于约定路径", evidence is not None,
         f"{Path(evidence_path)}（{read_error or '已解析'}）"),
        ("证据内部自洽（10 枚断言各自带实测值）", not problems,
         "; ".join(problems) if problems else "十枚全过、错误体/字节数/sha1 均可复核"),
        ("矩阵 P0 行当前状态 ∈ {BLOCKED, GREEN}", status in ("BLOCKED", "GREEN"),
         f"现读状态 = {status}"),
    ]
    all_met = all(ok for _name, ok, _detail in conditions) and status == "BLOCKED"
    return {
        "case_id": CASE_ID,
        "checked_at": utc_now(),
        "matrix_status_now": status,
        "evidence_path": str(Path(evidence_path).resolve()),
        "evidence_present": evidence is not None,
        "evidence_problems": problems,
        "conditions": [{"name": name, "ok": ok, "detail": detail}
                       for name, ok, detail in conditions],
        "green_permitted_by_evidence": all_met,
        "note": "即便 green_permitted_by_evidence=true，改矩阵的动作仍归主 agent；"
                "本函数只给判据，不碰 docs/MODEL_ROUTER_V23_MATRIX.md。",
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


if __name__ == "__main__":          # 手工跑一次探针：python tests/real_llm_failover_kit.py
    _record = probe_primary_load()
    print(json.dumps(_record, ensure_ascii=False, indent=2))
