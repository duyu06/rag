from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class EnterpriseModelRouterContractsTest(unittest.TestCase):
    def test_knowledge_bases_have_explicit_sensitivity(self):
        knowledge = (ROOT / "backend/app/knowledge.py").read_text(encoding="utf-8")
        self.assertIn('"sensitivity": "public"', knowledge)
        self.assertIn('"sensitivity": "internal"', knowledge)
        self.assertIn('"sensitivity": "confidential"', knowledge)
        self.assertIn('"sensitivity": "restricted"', knowledge)
        self.assertIn("def sensitivity_for_ids", knowledge)

    def test_restricted_data_fails_closed_to_local_models(self):
        router = (ROOT / "backend/app/llm_router.py").read_text(encoding="utf-8")
        self.assertIn('if value == "restricted":', router)
        self.assertIn("return False", router)
        self.assertIn("if not candidates and not allow_external:", router)
        self.assertIn('resolve_llm_config("ollama")', router)

    def test_fallback_is_bounded_and_only_for_retryable_failures(self):
        router = (ROOT / "backend/app/llm_router.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("llm_router_max_attempts", config)
        self.assertIn("{408, 409, 425, 429, 500, 502, 503, 504}", router)
        self.assertIn("if not retryable:", router)
        self.assertIn("candidates[: int(settings.llm_router_max_attempts)]", router)

    def test_streaming_only_fails_over_before_first_visible_token(self):
        router = (ROOT / "backend/app/llm_router.py").read_text(encoding="utf-8")
        self.assertIn("Fail over only before the first visible token", router)
        self.assertIn("first = next(iterator)", router)
        self.assertIn("if emitted or not retryable:", router)

    def test_provider_secrets_are_isolated(self):
        provider = (ROOT / "backend/app/llm_provider.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("deepseek_api_key: SecretStr", config)
        self.assertIn("qwen_api_key: SecretStr", config)
        self.assertIn("DEEPSEEK_API_KEY", provider)
        self.assertIn("QWEN_API_KEY", provider)
        self.assertIn("without borrowing another provider's secret", provider)

    def test_admin_control_plane_is_admin_only_and_redacted(self):
        routes = (ROOT / "backend/app/llm_admin_routes.py").read_text(encoding="utf-8")
        provider = (ROOT / "backend/app/llm_provider.py").read_text(encoding="utf-8")
        self.assertIn("require_admin(user)", routes)
        self.assertIn('@router.get("/router")', routes)
        self.assertIn('@router.get("/providers/health")', routes)
        self.assertIn('@router.post("/circuit-breakers/reset")', routes)
        self.assertIn("def public_runtime_config", provider)
        self.assertNotIn('"api_key": cfg.api_key', provider)

    def test_agent_trace_records_route_metadata_not_hidden_reasoning(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        trace = (ROOT / "backend/app/agent_trace.py").read_text(encoding="utf-8")
        self.assertIn('"type": "model_route"', agent)
        self.assertNotIn("reasoning_content", trace)


if __name__ == "__main__":
    unittest.main()
