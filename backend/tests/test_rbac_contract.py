from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.knowledge import allowed_ids, resolve_requested  # noqa: E402


class RoleMatrixTests(unittest.TestCase):
    def test_admin_can_access_every_demo_kb(self):
        self.assertEqual(
            set(allowed_ids("ADMIN")),
            {"kb_public", "kb_hr", "kb_product", "kb_sales", "kb_service"},
        )

    def test_sales_cannot_access_hr(self):
        self.assertNotIn("kb_hr", allowed_ids("SALES"))
        with self.assertRaises(PermissionError):
            resolve_requested("SALES", "kb_hr")

    def test_hr_cannot_access_sales_or_product(self):
        self.assertEqual(set(allowed_ids("HR")), {"kb_public", "kb_hr"})
        for kb_id in ("kb_sales", "kb_product", "kb_service"):
            with self.assertRaises(PermissionError):
                resolve_requested("HR", kb_id)

    def test_all_scope_resolves_to_role_acl(self):
        self.assertEqual(resolve_requested("SALES", "all"), allowed_ids("SALES"))
        self.assertEqual(resolve_requested("HR", None), allowed_ids("HR"))


class RetrievalWiringContractTests(unittest.TestCase):
    """Fast CI checks for the two ACL injection points without model downloads."""

    def test_qdrant_vector_and_scroll_paths_use_kb_filter(self):
        source = (BACKEND_DIR / "app" / "store.py").read_text(encoding="utf-8")
        self.assertIn("query_filter=self._kb_filter(knowledge_base_ids)", source)
        self.assertIn("scroll_filter=self._kb_filter(knowledge_base_ids)", source)

    def test_retrieval_passes_acl_to_vector_and_bm25_sources(self):
        source = (BACKEND_DIR / "app" / "retrieval.py").read_text(encoding="utf-8")
        self.assertIn("vector_store.vector_search(", source)
        self.assertIn("knowledge_base_ids=knowledge_base_ids", source)
        self.assertIn("all_chunks(knowledge_base_ids=knowledge_base_ids)", source)


if __name__ == "__main__":
    unittest.main()
