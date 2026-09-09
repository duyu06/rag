from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo-data"
DEMO_PY = ROOT / "backend" / "app" / "demo.py"
EVAL_JSON = ROOT / "backend" / "eval_dataset.json"
VALID_KBS = {"kb_public", "kb_hr", "kb_product", "kb_sales", "kb_service"}
EXPECTED_DOCS = 20
EXPECTED_QUESTIONS = 30


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def read_manifest() -> list[dict[str, str]]:
    module = ast.parse(DEMO_PY.read_text(encoding="utf-8"))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DEMO_MANIFEST":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, list):
                        return value
    fail("DEMO_MANIFEST not found")
    return []


def main() -> None:
    manifest = read_manifest()
    if len(manifest) != EXPECTED_DOCS:
        fail(f"DEMO_MANIFEST expected {EXPECTED_DOCS}, got {len(manifest)}")

    names = [str(item.get("file_name", "")) for item in manifest]
    if len(set(names)) != len(names):
        fail("duplicate file_name in DEMO_MANIFEST")

    kb_counts = Counter(str(item.get("knowledge_base_id", "")) for item in manifest)
    if set(kb_counts) != VALID_KBS:
        fail(f"manifest KB IDs mismatch: {sorted(kb_counts)}")
    for kb in sorted(VALID_KBS):
        if kb_counts[kb] != 4:
            fail(f"{kb} expected 4 demo docs, got {kb_counts[kb]}")

    disk_files = {path.name for path in DEMO_DIR.glob("*.md")}
    missing = sorted(set(names) - disk_files)
    extra = sorted(disk_files - set(names))
    if missing:
        fail(f"manifest files missing from demo-data: {missing}")
    if extra:
        fail(f"unmapped demo-data files: {extra}")

    dataset = json.loads(EVAL_JSON.read_text(encoding="utf-8"))
    if len(dataset) != EXPECTED_QUESTIONS:
        fail(f"evaluation dataset expected {EXPECTED_QUESTIONS}, got {len(dataset)}")

    questions = [str(item.get("question", "")).strip() for item in dataset]
    if any(not q for q in questions):
        fail("evaluation contains empty question")
    if len(set(questions)) != len(questions):
        fail("evaluation contains duplicate question")

    eval_kb_counts: Counter[str] = Counter()
    for index, item in enumerate(dataset, start=1):
        kb = str(item.get("knowledge_base_id", ""))
        expected_file = str(item.get("expected_file", ""))
        if kb not in VALID_KBS:
            fail(f"question {index}: invalid KB {kb}")
        if expected_file not in names:
            fail(f"question {index}: expected_file not in manifest: {expected_file}")
        manifest_kb = next(entry["knowledge_base_id"] for entry in manifest if entry["file_name"] == expected_file)
        if manifest_kb != kb:
            fail(f"question {index}: expected_file belongs to {manifest_kb}, not {kb}")
        eval_kb_counts[kb] += 1

    for kb in sorted(VALID_KBS):
        if eval_kb_counts[kb] < 4:
            fail(f"{kb} has too few evaluation questions: {eval_kb_counts[kb]}")

    print("[OK] demo manifest: 20 docs / 5 KBs / 4 docs each")
    print("[OK] demo-data mapping: exact match")
    print("[OK] evaluation dataset: 30 unique questions")
    print("[OK] expected_file ↔ knowledge_base_id mapping")
    print("Demo asset validation: PASS")


if __name__ == "__main__":
    main()
