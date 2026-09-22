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

    def test_prometheus_observability_covers_http_and_llm_gateway(self):
        obs = (ROOT / "backend/app/observability.py").read_text(encoding="utf-8")
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        security = (ROOT / "backend/app/security.py").read_text(encoding="utf-8")
        self.assertIn("yaoke_http_requests_total", obs)
        self.assertIn("yaoke_http_request_duration_seconds", obs)
        self.assertIn("yaoke_llm_requests_total", obs)
        self.assertIn("yaoke_llm_request_duration_seconds", obs)
        self.assertIn("yaoke_llm_tokens_total", obs)
        self.assertIn("metrics_payload", main)
        self.assertIn("prometheus_middleware", main)
        self.assertIn("METRICS_BEARER_TOKEN is required", security)

    def test_postgres_conversation_store_supports_multi_instance_backend(self):
        store = (ROOT / "backend/app/postgres_conversation_store.py").read_text(encoding="utf-8")
        factory = (ROOT / "backend/app/conversation_store.py").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("class PostgresConversationStore", store)
        self.assertIn("psycopg.connect(", store)
        self.assertIn("ON DELETE CASCADE", store)
        self.assertIn('conversation_store_backend or "sqlite"', factory)
        self.assertIn("PostgresConversationStore()", factory)
        self.assertIn("image: postgres:16-alpine", compose)
        self.assertIn("postgres_data:", compose)

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
