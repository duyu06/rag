from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CitationUiContractsTest(unittest.TestCase):
    def test_web_and_enterprise_citations_have_distinct_actions(self):
        actions = (ROOT / "frontend/src/components/CitationActions.tsx").read_text(encoding="utf-8")

        self.assertIn('kbName !== "知识库"', actions)
        # 显示层中文化后，公开网页来源的标签前缀是 "网页 · "（原 "Web · "）。
        self.assertIn('kbName.startsWith("网页 ·")', actions)
        self.assertIn('kbTag.textContent = `网页 · ${parsed.hostname}`', actions)
        self.assertIn('yaoke-web-source-open', actions)
        self.assertIn('yaoke-source-open', actions)
        self.assertIn('api.openSource(kbId, fileName)', actions)
        self.assertIn('个证据来源', actions)


if __name__ == "__main__":
    unittest.main()
