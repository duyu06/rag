from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
STALE_MARKERS = (
    "0." + "3.0",
    "P1." + "2 · 真实指标 + 审计",
    "当前内置 " + "10 道",
)


class VersionHygieneContractsTest(unittest.TestCase):
    def test_stale_version_markers_are_absent(self):
        offenders: list[str] = []
        skip_dirs = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv"}

        for path in ROOT.rglob("*"):
            if not path.is_file() or any(part in skip_dirs for part in path.parts):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            matched = [marker for marker in STALE_MARKERS if marker in text]
            if matched:
                offenders.append(f"{path.relative_to(ROOT)} -> {', '.join(matched)}")

        self.assertEqual(offenders, [], "stale version markers remain: " + "; ".join(offenders))

    def test_active_release_entrypoints_are_p15_v050(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        demo_tools = (ROOT / "frontend/src/components/DemoTools.tsx").read_text(encoding="utf-8")
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")

        stale_current_line = "当前版本：**P1." + "4 / v0.4.0**"
        stale_demo_line = "P1." + "4 / v0.4.0 · Agent + 真实指标 + 审计"
        stale_runtime_version = 'app.version = "0.' + '4.0"'

        self.assertIn("当前版本：**P1.5 / v0.5.0**", readme)
        self.assertIn("P1.5 / v0.5.0 · Conversation + Agent", demo_tools)
        self.assertIn('app.version = "0.5.0"', entry)
        self.assertIn('"phase": "P1.5"', entry)

        self.assertNotIn(stale_current_line, readme)
        self.assertNotIn(stale_demo_line, demo_tools)
        self.assertNotIn(stale_runtime_version, entry)


if __name__ == "__main__":
    unittest.main()
