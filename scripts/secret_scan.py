from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*")),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "aws_access_key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
]

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "__pycache__",
    "backups",
    "output",
    "data",
}
SKIP_FILES = {"backend/.env"}


def findings(text: str) -> list[str]:
    hits: list[str] = []
    for name, pattern in PATTERNS:
        if pattern.search(text):
            hits.append(name)
    return hits


def scan_workspace() -> list[str]:
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in SKIP_FILES or any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name in findings(text):
            hits.append(f"workspace:{relative}:{name}")
    return hits


def scan_history() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "log", "--all", "-p", "--no-color", "--", ".", ":(exclude)backend/.env"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ["history:scan_failed"]

    hits = []
    for name, pattern in PATTERNS:
        match = pattern.search(result.stdout)
        if match:
            hits.append(f"history:{name}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="High-confidence repository secret scan")
    parser.add_argument("--skip-history", action="store_true")
    args = parser.parse_args()

    hits = scan_workspace()
    if not args.skip_history:
        hits.extend(scan_history())

    if hits:
        print("SECRET_SCAN=FAIL")
        for hit in hits:
            print(hit)
        return 1
    print("SECRET_SCAN=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
