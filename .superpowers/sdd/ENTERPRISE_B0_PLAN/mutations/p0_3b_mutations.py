"""P0-EVIDENCE-PORTABILITY **3B** 的证伪台：九发变异 + 五发修复轮负面枪，逐发必须红在**它该红的那枚判据**上。

沿用 B0 / SEC-A 的字节安全台纪律（一字不落）：
  读字节 → 锚点必须**恰好命中一次**（0 次 `TARGET-NOT-FOUND`、>1 次 `ANCHOR-NOT-UNIQUE` 都不动树）
  → 写注入字节 → 跑定向 pytest → `finally` 用**读到的原字节**写回（不从 git 取）
  → sha256 核对 + 一次**外部 `cmp`**（与原字节的 park 副本比）。
本台另外三处与 B0 台不同，都是这单的形状逼出来的：
  ① 目标跨 `docs/evidence/**`（bundle）、闸文件、矩阵三处，且**注入值之间有名约束**
     （改了载荷件就得跟着更 manifest 的声明，改了 manifest 就得跟着更闸里的锚）；
     所以注入字节不是写死的串，而是「先算全量新字节、复验锚点数、再一次性落盘」。
  ② 判决归因到**指名判据**：只要求那枚 node-id 红**还不够**，还要求它的失败文案里出现
     这一发独有的哨兵串（九发各用互不相同的哨兵），否则「锚顺带红了」也会被记成杀。
  ③ 六发（M1–M5、M9）会改 manifest 的字节 ⇒ 必须同时把闸文件常数 `PORTABLE_MANIFEST_SHA256`
     按到新值上。不这么做的话 `[I2]` 外部锚先响，`[I3]`–`[I7]` 到底有没有牙就永远读不出来。
     还原时三处一起还原（bundle + manifest + 闸文件常数）。

**修复轮 1 补的三件事（L1 / L4 / 新增 N1–N5）**：
  · L1：`Op.needle` 过去**从来没被任何一枚 `shot()` 传过** ⇒ `check()` 恒返回 None ⇒
    「锚点全 ANCHOR-OK」是一句同义反复（和 B0 那枚没人读的 `spec["node"]` 同一类病）。
    现在逐发都带 needle，且 `--anchor-selftest` 会**不落盘**地喂给它两枚故意错的 needle，
    读回 `ANCHOR-NOT-UNIQUE` / `TARGET-NOT-FOUND` 各一次——这枚互锁从此有牙。
  · L4：`restamp_ops()` 过去只换 `sha256`、不换 `bytes` ⇒ M1/M2/M3/M5 除了该打的那枚 interlock
    还会**顺带**红 `[I2]` 的 bytes 半条，与 §12.4「只有 sha256 对照被喂平」的说法不符。
    现在两枚一起按（manifest 走 JSON 级改写 + `_bundle_text` 同口径序列化，不再裸换字符串）。
  · N1–N5：修复轮 1 那四条条款各自的「改它 ⇒ 它响」枪，打的是**已跟踪的原始证据 JSON**、
    run 目录里的运行态件、以及 manifest 的 pointers——不是 bundle 的载荷件。
    `--root <克隆>` 可以整批判据搬到干净签出上跑（`json-only` 分支），因为 H1/H2/M1/M2 这四条
    要证明的恰恰是「干净签出里它们也响」；在本机它们会同时被 `full` 分支的 §6 抓住，
    归因不纯，所以那四发的**正式读数取克隆**，N4（需要运行态件在场）只能取本机。

用法：
    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py --check
    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py --anchor-selftest
    python .superpowers/sdd/ENTERPRISE_B0_PLAN/mutations/p0_3b_mutations.py           # 十四发
    python .../p0_3b_mutations.py M3 M9 N1                                            # 选发
    python .../p0_3b_mutations.py N1 N2 N3 N5 --root <干净签出的仓根>                  # 克隆里跑
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "backend" / "tests"))
sys.path.insert(0, str(REPO / "backend"))

import real_llm_failover_kit as kit                                              # noqa: E402

BUNDLE = REPO / "docs" / "evidence" / "model-router-v23" / "real-llm-failover-001"
GATE = REPO / "backend" / "tests" / "test_real_llm_failover_gate.py"
MATRIX = REPO / "docs" / "MODEL_ROUTER_V23_MATRIX.md"
#: 修复轮 1 的 N1/N2/N3 打的是这枚**已跟踪的原始证据 JSON**（H1/H2 的判据来源就是它）。
EVIDENCE_JSON = REPO / kit.EVIDENCE_FILE.relative_to(kit.REPO_ROOT)
TARGET_MODULE = "tests/test_real_llm_failover_gate.py"
ASSIGNED = "P0MatrixStatusLockedToEvidenceTests::test_p0_row_status_matches_the_evidence"
COLLATERAL = ["P0MatrixStatusLockedToEvidenceTests::test_the_evidence_judgment_does_not_degrade"]
TIMEOUT_SECONDS = 600

#: 开工前钉死的基线（`--check` 与每发还原后都对着它比；跑完回填那种做法不算证据）。
#: **3B 修复轮 1 重钉**：`response.json` / `manifest.json` 两枚换了字节，因为载体侧新增了
#: `provider_transport_present`、`source_run_flags`、`raw_provenance[].repo_path/git_blob`
#: 三段字段——全部由 `kit.write_portable_bundle` 重导产生，没有手改任何一枚 bundle JSON。
#: 旧值：response `c0aa6c9f0b14…` / manifest `68749a00e2e2…`（闸里的锚同一批改，见 GATE 常量）。
BASELINE_SHA256 = {
    "result.json": "ca9f7a4e22e615c6cf648b3f05fc00d9e85ef1dc02dc4f3962399444bc55b247",
    "response.json": "dc5fee2215a7a0a0d7da0e74939874a87186d8a1c3d17c9971772f2ad03074d0",
    "ledger-row.json": "a87b7178aab096a57a2fe23a8f224da3eca6a0126f101d0ff00a5a2bac4b6ad4",
    "trace-attempts.json": "1aa8a1dbfb6bb12bc67fbe188196e612896e8ed10cc02439047e032f4b911293",
    "primary-probe.json": "9084df5502c6d58b9ce343f485436788b251a3411bf1e1ebb7f4d4069caabbe9",
    "manifest.json": "c39a09f83b6abdab475cbf3527b2d92ba5459dbbaa55535c1f26b9f634308508",
}
GATE_ANCHOR = BASELINE_SHA256["manifest.json"]

PAYLOAD_BY_NAME = {name: BUNDLE / name for name in BASELINE_SHA256}
#: N4 的两枚运行态原始件（`source_run_dir` 从 manifest 现读，不写死 run 目录名）。
def run_dir_of(root: Path) -> Path:
    manifest = json.loads(
        (root / "docs/evidence/model-router-v23/real-llm-failover-001/manifest.json")
        .read_text(encoding="utf-8"))
    return root / manifest["source_run_dir"]


RUN_DIR = run_dir_of(REPO)


def bind(root: Path) -> None:
    """把整套路径改指到另一棵签出（`--root <克隆>`），用于在**干净签出**上取 H1/H2/M1/M2 的读数。

    为什么必须能在克隆里跑：这四条条款要证明的是「json-only 分支里它们也响」。本机 raw 四枚
    都在场 ⇒ 走 `full` ⇒ §6 的 `validate_evidence()` 会**一起**抓同一件事，归因就不纯了。
    克隆里必须已经有本轮的 kit / 闸 / bundle（与源仓逐字节相同），否则这台子验的是另一份代码。
    """
    global REPO, BUNDLE, GATE, MATRIX, EVIDENCE_JSON, RUN_DIR, PAYLOAD_BY_NAME
    for rel in ("backend/tests/real_llm_failover_kit.py",
                "backend/tests/test_real_llm_failover_gate.py"):
        mine, theirs = REPO / rel, root / rel
        if not theirs.is_file():
            raise SystemExit(f"--root {root} 里没有 {rel}：先把本轮的 kit/闸覆进去再跑")
        if mine.read_bytes() != theirs.read_bytes():
            raise SystemExit(f"--root {root} 的 {rel} 与源仓字节不同：证伪台不许对着两份代码跑")
    REPO = root
    BUNDLE = root / "docs" / "evidence" / "model-router-v23" / "real-llm-failover-001"
    GATE = root / "backend" / "tests" / "test_real_llm_failover_gate.py"
    MATRIX = root / "docs" / "MODEL_ROUTER_V23_MATRIX.md"
    EVIDENCE_JSON = root / kit.EVIDENCE_FILE.relative_to(kit.REPO_ROOT)
    PAYLOAD_BY_NAME = {name: BUNDLE / name for name in BASELINE_SHA256}
    RUN_DIR = run_dir_of(root)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<missing>"


def bundle_text(data: dict) -> bytes:
    """按 §7 的**同一枚**序列化口径出字节（`kit._bundle_text`），并先证明口径可逆。

    先拿未改动的 dict 走一遍 `_bundle_text` 与盘上字节比：不等就说明「重新导出」与「就地改字节」
    不是一回事，那这一发的红就可能是我改格式改出来的，不是判据抓的 ⇒ 当场中止整轮。
    """
    return kit._bundle_text(data).encode("utf-8")


def roundtrip_proof() -> list[str]:
    bad = []
    for name, path in PAYLOAD_BY_NAME.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        if bundle_text(data) != path.read_bytes():
            bad.append(name)
    return bad


class Op:
    """一枚「路径 → 新字节」的注入操作，附带锚点唯一性证据。"""

    def __init__(self, path: Path, new: bytes, label: str, needle: bytes | None = None):
        self.path = path
        self.original = path.read_bytes() if path.is_file() else None
        self.new = new
        self.label = label
        self.needle = needle
        self.existed = path.is_file()

    def check(self) -> str | None:
        if self.needle is not None:
            hits = self.original.count(self.needle) if self.original is not None else 0
            if hits == 0:
                return f"TARGET-NOT-FOUND {self.path.name} {self.label}"
            if hits > 1:
                return f"ANCHOR-NOT-UNIQUE {self.path.name} {self.label} ×{hits}"
        return None

    def apply(self) -> None:
        if self.new is None:
            self.path.unlink()
        else:
            self.path.write_bytes(self.new)

    def restore(self) -> None:
        if self.original is not None:
            self.path.write_bytes(self.original)
        elif self.existed:
            self.path.unlink()


def edit_json(path: Path, keys: tuple, value) -> bytes:
    """读出 → 按指针改一处 → 按同口径序列化。哨兵值由调用方给（互不相同）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    node = data
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    return bundle_text(data)


def reanchor_ops(new_manifest_bytes: bytes, needle: bytes) -> list[Op]:
    """manifest 变了 ⇒ 闸文件里的外部锚必须跟着换，否则 `[I2]` 抢先把每一发都杀掉。

    `needle`（L1）：manifest 这一发**真正瞄准的那段原文**，台子会数它在原字节里命中几次；
    闸文件那一枚固定用旧锚串本身——它在闸里必须恰好出现一次（`--check` 也单独打印这一条）。
    """
    new_anchor = hashlib.sha256(new_manifest_bytes).hexdigest()
    gate_now = GATE.read_bytes()
    gated = gate_now.replace(GATE_ANCHOR.encode("ascii"), new_anchor.encode("ascii"), 1)
    if gated == gate_now:
        raise AssertionError("闸文件里找不到外部锚，无法重锚")
    return [Op(PAYLOAD_BY_NAME["manifest.json"], new_manifest_bytes, "manifest 新字节", needle),
            Op(GATE, gated, f"闸锚→{new_anchor[:12]}", GATE_ANCHOR.encode("ascii"))]


def restamp_ops(name: str, new_payload: bytes, extra: list[Op]) -> list[Op]:
    """载荷件变了 ⇒ 把 manifest 里那一枚声明**整条**换新值，再重锚。

    L4（修复轮 1）：过去这里只对 `sha256` 做字符串替换，**没换 `bytes`** ⇒ M1/M2/M3/M5
    除了该打的那枚 interlock 之外还会**顺带**红 `[I2]` 的 bytes 半条，
    与 §12.4 声称的「只有 sha256 对照被喂平」不符。现在走 JSON 级改写：同一枚条目里
    `sha256` 与 `bytes` 一起按，其余字段由 `_bundle_text` 同口径序列化，逐字节可逆性由
    `roundtrip_proof()` 在整轮开始前统一证明。
    """
    manifest_path = PAYLOAD_BY_NAME["manifest.json"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hits = [item for item in manifest["portable_files"]
            if Path(item["path"]).name == name]
    if len(hits) != 1:
        raise AssertionError(f"manifest 里 {name} 的声明不是恰好一枚：{len(hits)} 枚")
    old_digest = hits[0]["sha256"]
    hits[0]["sha256"] = hashlib.sha256(new_payload).hexdigest()
    hits[0]["bytes"] = len(new_payload)
    return extra + reanchor_ops(bundle_text(manifest),
                                b'"sha256": "%s"' % old_digest.encode("ascii"))


# ==========================================================================
# 九发变异 + 五发修复轮负面枪
# ==========================================================================
#: L1：每一发都必须带 **needle**（它瞄准的那段原文，在原字节里恰好命中一次）。
#: 过去 `shot()` 一枚都不传 ⇒ `Op.check()` 恒返回 None ⇒ 「锚点全 ANCHOR-OK」是同义反复。
def shot(name: str) -> list[Op]:
    if name == "M1":       # 改 response 的 model_used（answer.model）
        new = edit_json(PAYLOAD_BY_NAME["response.json"], ("answer", "model"), "phi3:mini-M1")
        return [Op(PAYLOAD_BY_NAME["response.json"], new, "answer.model=M1",
                   b'"model": "phi3:mini",\n    "finish_reason"')] \
            + restamp_ops("response.json", new, [])
    if name == "M2":       # 改 ledger.row.model
        new = edit_json(PAYLOAD_BY_NAME["ledger-row.json"], ("row", "model"), "phi3:mini-M2")
        return [Op(PAYLOAD_BY_NAME["ledger-row.json"], new, "row.model=M2",
                   b'"model": "phi3:mini"')] + restamp_ops("ledger-row.json", new, [])
    if name == "M3":       # 改成功那枚 trace attempt 的 model
        data = json.loads(PAYLOAD_BY_NAME["trace-attempts.json"].read_text(encoding="utf-8"))
        data["model_route_attempts"][1]["model"] = "phi3:mini-M3"
        new = bundle_text(data)
        return [Op(PAYLOAD_BY_NAME["trace-attempts.json"], new, "attempt[1]=M3",
                   b'"model": "phi3:mini",\n      "result": "success"')] \
            + restamp_ops("trace-attempts.json", new, [])
    if name == "M4":       # 改 planned primary
        new = edit_json(PAYLOAD_BY_NAME["manifest.json"], ("plan", "primary_model"),
                        "ornith-M4:latest")
        return reanchor_ops(new, b'"primary_model": "ornith-1.5:9b-text"')
    if name == "M5":       # probe result 换成非文档化失败
        data = json.loads(PAYLOAD_BY_NAME["primary-probe.json"].read_text(encoding="utf-8"))
        data["probe"]["raw_error_body"] = '{"error":"connection reset by peer (M5)"}'
        data["probe"]["classification"]["message"] = "模型忙：connection reset by peer (M5)"
        new = bundle_text(data)
        return [Op(PAYLOAD_BY_NAME["primary-probe.json"], new, "probe 原文=M5",
                   b'"raw_error_body"')] + restamp_ops("primary-probe.json", new, [])
    if name == "M6":       # 删掉一枚 portable 件（manifest 不动 ⇒ 外部锚仍配）
        return [Op(PAYLOAD_BY_NAME["trace-attempts.json"], None, "删件",
                   b'"model_route_attempts"')]
    if name == "M7":       # 改 portable 件，但**不**更 manifest hash
        new = edit_json(PAYLOAD_BY_NAME["response.json"], ("answer", "text"),
                        "M7 改写的答案文本，够长够中文以躲过长度判据。")
        return [Op(PAYLOAD_BY_NAME["response.json"], new, "改件不更 hash",
                   b'"answer": {\n    "text"')]
    if name == "M8":       # 矩阵 GREEN → BLOCKED（bundle 一字未动）
        needle = ("临时账本 1 行零 canary、仓库真库 0 行、trace 1 行） | GREEN |").encode("utf-8")
        replacement = needle.replace(b"| GREEN |", b"| BLOCKED |")
        return [Op(MATRIX, MATRIX.read_bytes().replace(needle, replacement, 1),
                   "矩阵状态字", needle)]
    if name == "M9":       # 反彩排：bundle 的来源指向 rehearsal run dir
        data = json.loads(PAYLOAD_BY_NAME["manifest.json"].read_text(encoding="utf-8"))
        data["source_run_dir"] = (
            kit.EVIDENCE_DIR.relative_to(kit.REPO_ROOT).as_posix()
            + "/rehearsal/run/20260924-214030")
        return reanchor_ops(bundle_text(data), b'"source_run_dir": ".superpowers')

    # ---------------- 修复轮 1 的五发负面枪（N1–N5）----------------
    # 这四枚的靶子**不是** bundle 的载荷件，而是 H1/H2/M1/M2 四条条款各自的新判据来源：
    # 已跟踪的原始证据 JSON（N1/N2/N3）、run 目录里的运行态件（N4）、manifest 的 pointers（N5）。
    if name == "N1":       # H1：往已跟踪的原始证据 JSON 注入 "rehearsal": true
        old = b'"completed": true,'
        new = EVIDENCE_JSON.read_bytes().replace(
            old, b'"completed": true, "rehearsal": true,', 1)
        return [Op(EVIDENCE_JSON, new, "注入 rehearsal=true", old)]
    if name == "N2":       # H1：completed 改成 false
        old = b'"completed": true,'
        new = EVIDENCE_JSON.read_bytes().replace(old, b'"completed": false,', 1)
        return [Op(EVIDENCE_JSON, new, "completed=false", old)]
    if name == "N3":       # H2：删掉 provider_transport 这枚键（bundle 那侧仍是 null）
        old = b'"provider_transport": null,'
        new = EVIDENCE_JSON.read_bytes().replace(old, b"", 1)
        return [Op(EVIDENCE_JSON, new, "删 provider_transport 键", old)]
    if name == "N4":       # M1：篡改 agent_traces.jsonl **并且**删掉 conversations.db
        old = b'"trace_id": "p0-failover-6146ff1417d7"'
        trace = RUN_DIR / "agent_traces.jsonl"
        db = RUN_DIR / "conversations.db"
        ops = [Op(trace, trace.read_bytes().replace(
            old, b'"trace_id": "p0-failover-N4TAMPERED"', 1), "篡改 trace_jsonl", old)]
        if db.is_file():
            ops.append(Op(db, None, "删掉 ledger_db 本体", b"SQLite format 3\x00"))
        return ops
    if name == "N5":       # M2：三枚 pointers 里把一枚改成 null
        data = json.loads(PAYLOAD_BY_NAME["manifest.json"].read_text(encoding="utf-8"))
        data["trace_id_source"]["pointers"]["request.trace_id"] = None
        return reanchor_ops(bundle_text(data),
                            b'"request.trace_id": "p0-failover-6146ff1417d7"')
    raise KeyError(name)


SHOTS = {
    "M1": ("改 response.model_used（answer.model）", "phi3:mini-M1", COLLATERAL),
    "M2": ("改 ledger.row.model", "phi3:mini-M2", COLLATERAL),
    "M3": ("改成功那枚 trace attempt 的 model", "phi3:mini-M3", COLLATERAL),
    "M4": ("改 planned primary（manifest.plan.primary_model）", "ornith-M4:latest", COLLATERAL),
    "M5": ("probe result 换成非文档化失败", "不含 §6 那族加载失败特征", COLLATERAL),
    "M6": ("删掉一枚 portable 件", "[I1] bundle 件缺失：trace-attempts.json", COLLATERAL),
    "M7": ("改 portable 件但不更 manifest hash", "[I2] sha256 不配：response.json", COLLATERAL),
    "M8": ("矩阵 GREEN → BLOCKED", "矩阵还写着", []),
    "M9": ("bundle 来源指向彩排 run dir", "指向彩排目录", COLLATERAL),
    # 修复轮 1：四条条款各一发，哨兵串就是那条判据自己的标签。
    "N1": ("H1：已跟踪的原始 JSON 注入 rehearsal=true", "[T-彩排]", COLLATERAL),
    "N2": ("H1：已跟踪的原始 JSON 的 completed 改成 false", "[T-收尾]", COLLATERAL),
    "N3": ("H2：已跟踪的原始 JSON 删掉 provider_transport 键", "[T-传输层]", COLLATERAL),
    "N4": ("M1：篡改 trace_jsonl 且删掉 ledger_db 本体",
           "[I7] 原始件 sha1 与 bundle 声明不等：trace_jsonl", COLLATERAL),
    "N5": ("M2：trace_id_source.pointers 里一枚改成 null",
           "[I6] trace_id_source.pointers 里有指针为 null", COLLATERAL),
}


def run_gate() -> tuple[int, list[str], str]:
    """跑整枚闸模块，把红面解析成**完整 node-id**（`类::方法`）。

    三件事是这一台的教训换来的，别再改回去：
    - `FAILED`/`ERROR` 之外还要收 `SUBFAILED`：本模块的判据探针是 `subTest` 形态，
      子判据红只出 `SUBFAILED[...]` 行，只按 `FAILED` 行归因会把「探针也响了」读成没响。
    - 捕获组必须取到 `类::方法` 两级：只取末段方法名会让 `ASSIGNED`（含类名前缀）永远对不上，
      于是每一发都被记成 `KILLED-INCIDENTAL`（第一版就是这么错的）。
    - **子进程编码必须钉成 UTF-8**（修复轮 1 实测补的）：本机 `python` 的 `sys.stdout.encoding`
      是 `gbk`（bash 里 `LC_ALL=C.UTF-8` 对 Windows CPython 的子进程不生效），而这一台
      是以 `encoding="utf-8"` 解码的 ⇒ 中文哨兵（`[T-彩排]`、`不含 §6 那族加载失败特征`、
      `指向彩排目录`…）解码后是乱码 ⇒ `token in raw` 恒假 ⇒ 判据明明抓住了也被记成
      `KILLED-INCIDENTAL`。这是**仪表**病不是判据病，但它会把「这发杀对了」这件事变成读不出来；
      现在用 `PYTHONIOENCODING=utf-8:replace` + `PYTHONUTF8=1` 把子进程钉死，跨 shell 都可复现。
    """
    import os

    env = dict(os.environ, PYTHONIOENCODING="utf-8:replace", PYTHONUTF8="1")
    proc = subprocess.run([sys.executable, "-m", "pytest", TARGET_MODULE, "-q",
                           "-p", "no:cacheprovider", "--tb=long", "-rf"],
                          cwd=str(REPO / "backend"), env=env,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    raw = proc.stdout + proc.stderr
    red: list[str] = []
    for line in raw.splitlines():
        text = line.strip()
        if text.startswith(("FAILED ", "ERROR ", "SUBFAILED")):
            found = re.search(r"tests/[^ :\t]+\.py::\w+::\w+", text)
            if found:
                node = found.group(0).split("::", 1)[1]
                if node not in red:
                    red.append(node)
    return proc.returncode, red, raw


def failure_blocks(raw: str) -> dict[str, str]:
    """把 `--tb=long` 的输出按**失败块**切开，键是块头里出现的 `test_…` 名字。

    终审 Important 4 的第一条：旧版 `decide()` 里 `token in raw` 的 `raw` 是**整轮**输出，
    于是别的节点（尤其那枚会打印 problems 全集的 `COLLATERAL` 探针）只要把同一串印出来，
    这一发就被记成"杀对了"。红因必须落在**这一发点名的那枚节点自己的块**里才算。
    """
    blocks: dict[str, str] = {}
    try:
        body = raw.split("=== FAILURES ====", 1)[1].split("=== short test summary info ====", 1)[0]
    except IndexError:
        return blocks
    header = re.compile(r"^_+\s*(.+?)\s*_+\s*$", re.MULTILINE)

    marks = [(m.start(), m.group(1)) for m in header.finditer(body)
             if re.search(r"\btest_\w+", m.group(1))]
    for index, (start, title) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(body)
        for name in re.findall(r"test_\w+", title):
            blocks[name] = body[start:end]
    return blocks


def decide(rc: int, red: list[str], raw: str, token: str) -> str:
    assigned_red = ASSIGNED in red
    if rc == 0:
        return "SURVIVED"
    if not red:
        return "COLLECTION-BROKEN"
    if not assigned_red:
        return "KILLED-INCIDENTAL"
    block = failure_blocks(raw).get(ASSIGNED.split("::")[-1], "")
    if not block:
        # 取不到块 = 归因没法核，宁可报"没挣到"，也不回退到"整轮里找一遍"的旧错法
        return "KILLED-NO-BLOCK"
    return "KILLED-ASSIGNED" if token in block else "KILLED-WRONG-REASON"


def check_only() -> int:
    print(f"== 基线（不注入；根 = {REPO}）==")
    bad = roundtrip_proof()
    print(f"序列化口径可逆（六枚逐字节相同）：{not bad}" + (f" 例外 {bad}" if bad else ""))
    ok = True
    for name, digest in BASELINE_SHA256.items():
        actual = sha(PAYLOAD_BY_NAME[name])
        flag = actual == digest
        ok = ok and flag
        print(f"  [{'RESTORED-OK' if flag else 'RESTORED-MISMATCH'}] {name:22s} {actual}")
    gate_bytes = GATE.read_bytes()
    gate_ok = GATE_ANCHOR.encode() in gate_bytes and gate_bytes.count(GATE_ANCHOR.encode()) == 1
    print(f"  [{'RESTORED-OK' if gate_ok else 'RESTORED-MISMATCH'}] 闸文件外部锚在场且唯一="
          f"{gate_bytes.count(GATE_ANCHOR.encode()) == 1}")
    for name in SHOTS:
        ops = shot(name)
        fails = [problem for problem in (op.check() for op in ops) if problem]
        needles = sum(1 for op in ops if op.needle is not None)
        print(f"  锚点 {name}: {'ANCHOR-OK' if not fails else ' / '.join(fails)}"
              f"（needle {needles}/{len(ops)} 枚 op 带锚）")
        # needle 一枚都不带的 shot 就是 L1 那种死互锁——这里直接判不合格，不放过。
        if needles != len(ops):
            ok = False
    return 0 if ok and not bad else 1


#: L1 的自证：**故意**喂两枚错的 needle，看互锁真的会响。全程不落盘、不动树。
ANCHOR_SELFTEST = [
    ("needle 命中 0 次（目标不在场）", "result.json", b'"no-such-key-NOT-IN-BUNDLE"'),
    ("needle 命中 >1 次（锚不唯一）", "response.json", b'"model"'),
]


def anchor_selftest() -> int:
    print("== 锚点互锁自证（不写盘、不动树）==")
    heard = []
    for label, file_name, needle in ANCHOR_SELFTEST:
        path = PAYLOAD_BY_NAME[file_name]
        op = Op(path, path.read_bytes(), "自证（不会 apply）", needle)
        problem = op.check()
        print(f"  {label}: {file_name} needle={needle[:34]!r} "
              f"实测命中={op.original.count(needle)} 次 ⇒ check() = {problem!r}")
        heard.append(bool(problem))
    verdict = all(heard) and len(set(heard)) == 1
    print(f"  两枚都响 = {verdict} ⇒ 这台子的锚互锁是活的（修复轮 1 之前它一枚都不接 needle）")
    return 0 if verdict else 1


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rest, skip = [], False
    for index, item in enumerate(argv):
        if skip:
            skip = False
            continue
        if item == "--root":
            bind(Path(argv[index + 1]))
            skip = True
            continue
        if item.startswith("--"):
            continue
        rest.append(item)
    if "--anchor-selftest" in argv:
        return anchor_selftest()
    if "--check" in argv:
        return check_only()
    wanted = [a for a in rest if a in SHOTS] or list(SHOTS)
    bad = roundtrip_proof()
    if bad:
        print(f"[中止] §7 序列化口径对盘上字节不可逆：{bad} —— 注入会改格式，红因不纯")
        return 2
    park = Path(tempfile.mkdtemp(prefix="p03b-park-"))
    tally = {}
    for name in wanted:
        label, token, collateral = SHOTS[name]
        ops = shot(name)
        problems = [op.check() for op in ops]
        problems = [p for p in problems if p]
        if problems:
            print(f"{name} {label}: 锚点检查不过 ⇒ 不动树：{problems}")
            tally[name] = "ANCHOR-ABORT"
            continue
        originals = {op.path: (op.original, park / f"{name}-{op.path.name}") for op in ops}
        for path, (blob, copy) in originals.items():
            if blob is not None:
                copy.write_bytes(blob)
        red_dir = REPO / ".superpowers/sdd/ENTERPRISE_B0_PLAN/tmp"
        red_dir.mkdir(parents=True, exist_ok=True)
        restored_ok = True
        try:
            for op in ops:
                op.apply()
            rc, red, raw = run_gate()
            verdict = decide(rc, red, raw, token)
            (red_dir / f"p0-3b-red-{name}.txt").write_text(raw, encoding="utf-8")
        finally:
            for op in ops:
                op.restore()
            for path, (blob, copy) in originals.items():
                if blob is None:
                    # 开工时这枚文件**不存在**（新建型 op）⇒ 还原的正确形态是"它又不存在了"。
                    # 旧版这里写的是 `(not path.exists() or True)`，恒真 ⇒ 这一支从来没核过任何东西
                    # （终审 Important 4 点名的第三个仪表病：本仓自己登记过的"仪表不响、结论照抄"）。
                    restored_ok = restored_ok and (not path.exists())
                    continue
                external = subprocess.run(["cmp", str(path), str(copy)],
                                          capture_output=True, text=True)
                same_sha = sha(path) == hashlib.sha256(blob).hexdigest()
                restored_ok = restored_ok and same_sha and external.returncode == 0
                digest_now = sha(path)
                baseline = BASELINE_SHA256.get(path.name)
                if baseline is not None:
                    restored_ok = restored_ok and digest_now == baseline
        extra = [node for node in red if node != ASSIGNED and node not in collateral]
        verdict += "-RESTORED-OK" if restored_ok else "-RESTORE-FAILED"
        tally[name] = verdict
        print(f"{name} {label}\n"
              f"    计划钉住的判据 = {ASSIGNED}\n"
              f"    期望的哨兵串   = {token}\n"
              f"    实测红面       = {red}\n"
              f"    计划外附带红   = {extra}\n"
              f"    还原           = {'sha256 同 + 外部 cmp rc=0 + 基线核对' if restored_ok else '失败'}\n"
              f"    判决           = {verdict}")
        if verdict.endswith("RESTORE-FAILED"):
            print("[中止整轮] 还原没对上，继续跑只会污染下一个读数")
            break
    shutil.rmtree(park, ignore_errors=True)
    counts = {}
    for verdict in tally.values():
        # 分组键保留到"判决本体"，只剥掉还原后缀：旧版 `split("-")[0]` 会把
        # KILLED-WRONG-REASON / KILLED-NO-BLOCK 也归进 `KILLED`，于是台账上"14 发全杀"
        # 能在红因没对上的时候照样印出来 —— 那正是终审要修的"仪表不响、结论照抄"。
        key = verdict.split("-RESTORED")[0]
        counts[key] = counts.get(key, 0) + 1
    print("\n== 台账 ==")
    for name in wanted:
        print(f"  {name}: {tally.get(name)}")
    print(f"  计数: {counts}")
    print(f"  park 目录已删 = {not park.exists()}")
    assigned_ok = sum(1 for name in wanted
                      if tally.get(name, "").startswith("KILLED-ASSIGNED"))
    return 0 if assigned_ok == len(wanted) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
