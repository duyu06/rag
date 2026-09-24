from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
LEGACY_BRAND = ("Nexus" + "KB").lower()


class BrandingContractsTest(unittest.TestCase):
    def test_yaoke_brand_identity_is_wired(self):
        layout = (ROOT / "frontend/src/app/layout.tsx").read_text(encoding="utf-8")
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        env_example = (ROOT / "backend/.env.example").read_text(encoding="utf-8")
        logo = ROOT / "frontend/public/yaoke-logo.webp"

        # 浏览器标题带上中文产品定位；lang 已切到 zh-CN。
        self.assertIn('title: "yaoke · 企业知识操作系统"', layout)
        self.assertIn('description: "yaoke · 企业知识库：问答 / 检索 / 证据 / 评测 / 治理"', layout)
        self.assertIn('<html lang="zh-CN">', layout)
        # 品牌标记仍是内联的字母 mark（不是图片资源），侧栏与登录页各一处。
        self.assertIn('<div className="side-brand">', page)
        self.assertIn('<span className="mark" aria-hidden="true">Y</span>', page)
        self.assertIn(
            '<span className="mark" style={{ background: "#fff", color: "var(--dark)" }} aria-hidden="true">Y</span>',
            page,
        )
        self.assertNotIn('/yaoke-logo.webp', layout)
        self.assertNotIn('/yaoke-logo.webp', page)
        self.assertIn('<strong>yaoke</strong>', page)
        self.assertIn('<span>企业知识操作系统</span>', page)
        self.assertIn('QDRANT_COLLECTION=yaoke', env_example)
        self.assertIn('JWT_SECRET=change-me-before-production-yaoke-demo-secret', env_example)
        self.assertTrue(logo.exists(), "yaoke logo asset is missing")
        self.assertGreater(logo.stat().st_size, 1024, "yaoke logo asset looks unexpectedly small")
        self.assertTrue(readme.startswith('<p align="center">'))
        self.assertIn('# yaoke · 企业 AI 知识中台', readme)

    def test_legacy_brand_string_is_absent_from_repository_utf8_files(self):
        offenders: list[str] = []
        skip_dirs = {".git", "node_modules", ".next", "__pycache__", ".venv", "venv"}

        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                if path.stat().st_size > 2_000_000:
                    continue
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if LEGACY_BRAND in text.lower():
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(
            offenders,
            [],
            "legacy brand string remains in: " + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
