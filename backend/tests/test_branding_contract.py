from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BrandingContractsTest(unittest.TestCase):
    def test_yaoke_brand_identity_is_wired(self):
        layout = (ROOT / "frontend/src/app/layout.tsx").read_text(encoding="utf-8")
        overlay = (ROOT / "frontend/src/components/BrandingOverlay.tsx").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        logo = ROOT / "frontend/public/yaoke-logo.webp"

        self.assertIn('title: "yaoke"', layout)
        self.assertIn('BrandingOverlay', layout)
        self.assertIn('BRAND_NAME = "yaoke"', overlay)
        self.assertIn('/yaoke-logo.webp', overlay)
        self.assertTrue(logo.exists(), "yaoke logo asset is missing")
        self.assertGreater(logo.stat().st_size, 1024, "yaoke logo asset looks unexpectedly small")
        self.assertTrue(readme.startswith('<p align="center">'))
        self.assertIn('# yaoke · 企业 AI 知识中台', readme)


if __name__ == "__main__":
    unittest.main()
