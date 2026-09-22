from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class EnterpriseOperationsContractsTest(unittest.TestCase):
    def test_backup_uses_qdrant_snapshot_and_sqlite_online_backup(self):
        backup = (ROOT / "scripts/backup_enterprise.py").read_text(encoding="utf-8")
        self.assertIn('/snapshots"', backup)
        self.assertIn("src.backup(dst)", backup)
        self.assertIn("sha256_file", backup)
        self.assertIn('"manifest.json"', backup)

    def test_restore_verifies_checksums_and_requires_force(self):
        restore = (ROOT / "scripts/restore_enterprise.py").read_text(encoding="utf-8")
        self.assertIn("--force", restore)
        self.assertIn("verify_file", restore)
        self.assertIn("/snapshots/upload", restore)
        self.assertIn('priority": "snapshot"', restore)
        self.assertIn("safe_extract", restore)

    def test_admin_readiness_aggregates_security_and_critical_dependencies(self):
        routes = (ROOT / "backend/app/enterprise_routes.py").read_text(encoding="utf-8")
        entry = (ROOT / "backend/app/main_agent.py").read_text(encoding="utf-8")
        self.assertIn('prefix="/api/admin/enterprise"', routes)
        self.assertIn('@router.get("/readiness")', routes)
        self.assertIn("require_admin(user)", routes)
        self.assertIn("verify_audit_chain()", routes)
        self.assertIn("rate_limit_ready()", routes)
        self.assertIn("router_registry_snapshot()", routes)
        self.assertIn("vector_store.ping()", routes)
        self.assertIn("app.include_router(enterprise_router)", entry)


if __name__ == "__main__":
    unittest.main()
