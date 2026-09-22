from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class EnterpriseSecurityContractsTest(unittest.TestCase):
    def test_production_fails_closed_on_demo_auth_and_wildcard_perimeter(self):
        security = (ROOT / "backend/app/security.py").read_text(encoding="utf-8")
        self.assertIn('AUTH_MODE must be oidc in production', security)
        self.assertIn('CORS_ALLOWED_ORIGINS must be an explicit allowlist', security)
        self.assertIn('TRUSTED_HOSTS must be an explicit allowlist', security)
        self.assertIn('AUDIT_HMAC_KEY is required', security)
        self.assertIn("Unsafe production configuration", security)

    def test_oidc_validates_signature_issuer_audience_and_maps_roles(self):
        auth = (ROOT / "backend/app/auth.py").read_text(encoding="utf-8")
        self.assertIn("PyJWKClient", auth)
        self.assertIn("issuer=issuer", auth)
        self.assertIn("audience=audience", auth)
        self.assertIn('options={"require": ["exp", "iat", "sub"]}', auth)
        self.assertIn("def _oidc_role", auth)
        self.assertIn('mode == "oidc"', auth)

    def test_local_jwt_issuance_is_demo_only(self):
        auth = (ROOT / "backend/app/auth.py").read_text(encoding="utf-8")
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        self.assertIn("Local JWT issuance is disabled outside demo auth mode", auth)
        self.assertIn("本地密码登录已禁用，请使用企业 SSO", main)

    def test_security_headers_request_id_and_cors_allowlist_are_wired(self):
        main = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
        security = (ROOT / "backend/app/security.py").read_text(encoding="utf-8")
        self.assertIn("allow_origins=cors_origins()", main)
        self.assertIn("TrustedHostMiddleware", main)
        self.assertIn('response.headers["X-Request-ID"]', security)
        self.assertIn('response.headers["X-Content-Type-Options"] = "nosniff"', security)
        self.assertIn('response.headers["X-Frame-Options"] = "DENY"', security)

    def test_production_requires_fail_closed_distributed_rate_limit(self):
        security = (ROOT / "backend/app/security.py").read_text(encoding="utf-8")
        limiter = (ROOT / "backend/app/rate_limit.py").read_text(encoding="utf-8")
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("RATE_LIMIT_ENABLED must be true", security)
        self.assertIn("RATE_LIMIT_FAIL_OPEN must be false", security)
        self.assertIn("Redis.from_url", limiter)
        self.assertIn("status_code=429", limiter)
        self.assertIn("status_code=503", limiter)
        self.assertIn("image: redis:7-alpine", compose)

    def test_audit_redacts_secrets_and_supports_integrity_verification(self):
        audit = (ROOT / "backend/app/audit.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("AUDIT_PATH", audit)
        self.assertIn("[REDACTED]", audit)
        self.assertIn("hmac-sha256", audit)
        self.assertIn("def verify_audit_chain", audit)
        self.assertIn("audit_hmac_key: SecretStr", config)
        self.assertIn("audit_query_max_chars", config)


if __name__ == "__main__":
    unittest.main()
