from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = spec_from_file_location("web_safety", ROOT / "backend/app/web_safety.py")
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
safe_public_url = MODULE.safe_public_url


class WebSecurityTest(unittest.TestCase):
    def test_public_https_allowed(self):
        self.assertEqual(safe_public_url("https://example.com/a?q=1"), "https://example.com/a?q=1")

    def test_local_and_private_targets_rejected(self):
        blocked = [
            "http://localhost:8001",
            "http://127.0.0.1",
            "http://10.0.0.1",
            "http://172.16.1.1",
            "http://192.168.1.1",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]",
            "file:///etc/passwd",
            "ftp://example.com/file",
        ]
        for value in blocked:
            with self.subTest(value=value):
                self.assertIsNone(safe_public_url(value))

    def test_userinfo_and_local_suffix_rejected(self):
        self.assertIsNone(safe_public_url("https://user:pass@example.com"))
        self.assertIsNone(safe_public_url("http://service.local/path"))


if __name__ == "__main__":
    unittest.main()
