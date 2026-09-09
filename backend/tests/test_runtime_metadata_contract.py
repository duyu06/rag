from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RuntimeMetadataContractsTest(unittest.TestCase):
    def test_p14_runtime_metadata_is_consistent(self):
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        self.assertIn('app.title = "yaoke API"', entry)
        self.assertIn('app.version = "0.4.0"', entry)
        self.assertIn('"version": "0.4.0"', entry)


if __name__ == "__main__":
    unittest.main()
