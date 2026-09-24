from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.auth import (  # noqa: E402
    CurrentUser,
    access_role_for,
    authenticate,
    enforce_permission,
    permissions_for_role,
)
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

    def test_user_and_viewer_are_public_scope_only(self):
        self.assertEqual(allowed_ids("USER"), ["kb_public"])
        self.assertEqual(allowed_ids("VIEWER"), ["kb_public"])

    def test_unknown_role_is_fail_closed(self):
        self.assertEqual(allowed_ids("UNKNOWN"), [])
        with self.assertRaises(PermissionError):
            resolve_requested("UNKNOWN", None)
        with self.assertRaises(PermissionError):
            resolve_requested("UNKNOWN", "kb_public")


class CapabilityMatrixTests(unittest.TestCase):
    def test_legacy_department_roles_map_to_user_access(self):
        self.assertEqual(access_role_for("ADMIN"), "admin")
        self.assertEqual(access_role_for("SALES"), "user")
        self.assertEqual(access_role_for("HR"), "user")
        self.assertEqual(access_role_for("VIEWER"), "viewer")

    def test_viewer_is_read_only(self):
        permissions = set(permissions_for_role("VIEWER"))
        self.assertEqual(
            permissions,
            {"knowledge:read", "conversation:read", "trace:read"},
        )
        viewer = CurrentUser(username="viewer", display_name="Viewer", role="VIEWER")
        with self.assertRaises(HTTPException) as raised:
            enforce_permission(viewer, "knowledge:query")
        self.assertEqual(raised.exception.status_code, 403)

    def test_user_can_query_but_cannot_administer(self):
        permissions = set(permissions_for_role("USER"))
        self.assertTrue({"knowledge:query", "conversation:write", "agent:run"} <= permissions)
        self.assertFalse({"knowledge:manage", "audit:read", "system:operate"} & permissions)

    def test_admin_has_sensitive_capabilities(self):
        permissions = set(permissions_for_role("ADMIN"))
        self.assertTrue(
            {
                "knowledge:manage",
                "retrieval:debug",
                "evaluation:run",
                "audit:read",
                "system:operate",
                "trace:read:any",
            }
            <= permissions
        )

    def test_login_payload_exposes_canonical_role_and_permissions(self):
        viewer = authenticate("viewer", "viewer123")
        self.assertIsNotNone(viewer)
        payload = viewer.model_dump() if viewer else {}
        self.assertEqual(payload["role"], "VIEWER")
        self.assertEqual(payload["access_role"], "viewer")
        self.assertEqual(
            set(payload["permissions"]),
            {"knowledge:read", "conversation:read", "trace:read"},
        )


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

    def test_sensitive_routes_use_declarative_permissions(self):
        main_source = (BACKEND_DIR / "app" / "main.py").read_text(encoding="utf-8")
        agent_source = (BACKEND_DIR / "app" / "agent_routes.py").read_text(encoding="utf-8")
        conversation_source = (BACKEND_DIR / "app" / "conversation_routes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('require_permission("knowledge:manage")', main_source)
        self.assertIn('require_permission("audit:read")', main_source)
        self.assertIn('require_permission("retrieval:debug")', main_source)
        self.assertIn('require_permissions("agent:run", "knowledge:query")', agent_source)
        self.assertIn('require_permission("conversation:write")', conversation_source)
        self.assertIn("_validate_knowledge_base_scope(user, request.knowledge_base_id)", conversation_source)

    def test_streaming_conversation_history_is_reloaded_through_acl_sanitizer(self):
        source = (BACKEND_DIR / "app" / "conversation_stream_routes.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_load_conversation_for_user", source)
        self.assertGreaterEqual(source.count("_load_conversation_for_user(conversation_id, user)"), 2)
        self.assertNotIn("conversation_store.get(conversation_id, username=user.username)", source)


if __name__ == "__main__":
    unittest.main()
