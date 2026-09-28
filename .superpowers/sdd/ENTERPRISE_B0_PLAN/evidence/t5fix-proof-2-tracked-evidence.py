"""Fix 2 的效力证明（**仓外**运行；不改仓库里任何文档，也不改那枚 gitignored 过程件）。

四组读数：
  ① 宿主现状（过程件在场）⇒ 交付面声称成立、本机十枚判据成立、两件互锁成立 ⇒ 门要求 GREEN。
  ② 模拟干净 checkout（把过程件"拿掉"= 只把 read_evidence 指到不存在的路径）⇒ 新判据照样
     判得出东西（要求 GREEN，矩阵写着 GREEN ⇒ 绿），**而旧判据在这里必红**（缺件 ⇒ 判 BLOCKED，
     矩阵写 GREEN ⇒ 'BLOCKED' != 'GREEN'）。这一组就是"机器本地的绿"被消掉的直接证据。
  ③ 非空洞性：对 §4 做四枚变异（整节删掉 / 某枚实测清空 / 耗时改数 / 归类原文删掉），
     交付面声称必须**点名**报出问题 ⇒ 门退回"要求 BLOCKED"，对着 GREEN 的矩阵就红。
  ④ 声称与本机过程件的互锁：把 JSON 的耗时改一枚数 ⇒ 必须报"不等"。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(r"E:/xiangmu/rag")
SCRATCH = Path(__file__).resolve().parent          # 仓外
for p in (str(REPO / "backend"), str(REPO / "backend" / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import importlib
import real_llm_failover_kit as kit
import test_real_llm_failover_gate as gate

DOC = gate.TRACKED_EVIDENCE_DOC
print(f"① 交付面文档 = {DOC.name}  tracked? 见报告 git ls-files 行")
claim, problems = gate._p0_claim_from_tracked_doc()
print(f"   交付面声称问题           = {problems}")
evidence, read_error = kit.read_evidence()
print(f"   本机过程件在场?           = {evidence is not None}  read_error={read_error}")
print(f"   validate_evidence 问题    = {kit.validate_evidence(evidence)}")
print(f"   两件互锁问题              = {gate._machine_copy_agrees_with_doc(claim, evidence)}")
print(f"   矩阵 P0 行现读状态        = {kit.matrix_p0_status()}")

# ---- ② 干净 checkout 模拟：过程件不在场 ------------------------------------
print("=" * 72)
print("② 模拟干净 checkout（`.superpowers/` 整目录被 .gitignore:25 挡掉 ⇒ JSON 不在场）")
missing_path = SCRATCH / "definitely-not-here.json"
clean_evidence, clean_error = kit.read_evidence(missing_path)
print(f"   read_evidence(不存在路径) = {clean_evidence} / {clean_error!r}")
print(f"   交付面声称问题（不变）    = {gate._p0_claim_from_tracked_doc()[1]}")
substantiated_new = not gate._p0_claim_from_tracked_doc()[1]
print(f"   新判据 ⇒ 证据成立？        = {substantiated_new} ⇒ 只许 "
      f"{kit and gate.P0_STATUS_WITH_EVIDENCE}")
# 旧判据逐字重放：`if evidence is None or problems: 要求 BLOCKED`
old_rule_status = gate.P0_STATUS_WITHOUT_EVIDENCE if (
    clean_evidence is None or kit.validate_evidence(clean_evidence)) else gate.P0_STATUS_WITH_EVIDENCE
print(f"   旧判据会要求              = {old_rule_status!r}，而矩阵写着 "
      f"{kit.matrix_p0_status()!r} ⇒ 旧门在这一格必红（'BLOCKED' != 'GREEN'）")
print(f"   新判据会要求              = "
      f"{gate.P0_STATUS_WITH_EVIDENCE if substantiated_new else gate.P0_STATUS_WITHOUT_EVIDENCE!r}"
      f" ⇒ 与矩阵一致，且这条要求是**判出来的**而不是**因为文件在**")

# ---- ③ 非空洞性：四枚文档变异 ----------------------------------------------
print("=" * 72)
print("③ 四枚变异：交付面声称被改坏时，门必须点名问题（而不是放过）")
text = DOC.read_text(encoding="utf-8")
mutations = [
    ("§4 整节被删", lambda t: t.replace(
        "## 4. P0 真机十字（唯一 P0）", "## 4. P0 真机十字（这一节被人搬走了）", 1
    ).replace("| 1 | primary 真被调用 |", "| x | primary 真被调用 |")),
    ("第 8 枚的实测格子被清空", lambda t: t.replace(
        "| 8 | usage 落库 | 临时账本恰好 1 行、19 列，`model = phi3:mini` |",
        "| 8 | usage 落库 |  |")),
    ("耗时被改数（41 596 → 41 000）", lambda t: t.replace("41 596 ms", "41 000 ms")),
    ("归类原文被删（model_unavailable）", lambda t: t.replace("`model_unavailable`", "某种失败")),
]
for label, mutate in mutations:
    damaged = SCRATCH / f"damaged-doc-{label[:6]}.md"
    damaged.write_text(mutate(text), encoding="utf-8")
    gate.TRACKED_EVIDENCE_DOC = damaged
    try:
        _claim, issues = gate._p0_claim_from_tracked_doc()
        print(f"   [{label}] ⇒ 问题 {len(issues)} 项：{issues}")
    finally:
        damaged.unlink()
        gate.TRACKED_EVIDENCE_DOC = DOC

# ---- ④ 声称与过程件互锁 ------------------------------------------------------
print("=" * 72)
print("④ 互锁：过程件被事后改数（primary 耗时 41 596 → 39 999）时必须报不等")
tampered = json.loads(json.dumps(evidence, ensure_ascii=False))
tampered["provider_calls"][0]["elapsed_ms"] = 39999.0
print(f"   互锁问题 = {gate._machine_copy_agrees_with_doc(claim, tampered)}")
print("=" * 72)
print(f"收尾核对：交付面文档仍在场 = {DOC.is_file()}  变异副本已删除 = "
      f"{not list(SCRATCH.glob('damaged-doc-*.md'))}")
