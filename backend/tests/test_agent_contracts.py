from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AgentContractsTest(unittest.TestCase):
    def test_tool_registry_contains_required_tools(self):
        registry = (ROOT / "backend/app/tools/registry.py").read_text(encoding="utf-8")
        self.assertIn('name="enterprise_search"', registry)
        self.assertIn('name="web_search"', registry)
        self.assertIn('frozenset({"local", "auto", "web"})', registry)
        self.assertIn('frozenset({"auto", "web"})', registry)

    def test_agent_loop_is_bounded_and_discards_hidden_reasoning_from_trace(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        trace = (ROOT / "backend/app/agent_trace.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("agent_max_tool_rounds: int = Field(default=3, ge=1, le=3)", config)
        self.assertIn("for round_index in range(1, max_rounds + 1)", agent)
        self.assertIn("Tool-call limit reached", agent)
        self.assertIn('"think": True', agent)
        self.assertIn("messages.append(message)", agent)
        self.assertNotIn("reasoning_content", trace)
        self.assertNotIn('"thinking"', trace)

    def test_agent_routes_and_tools_endpoint_exist(self):
        routes = (ROOT / "backend/app/agent_routes.py").read_text(encoding="utf-8")
        dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
        self.assertIn('@router.get("/tools")', routes)
        self.assertIn('@router.post("/agent/query")', routes)
        self.assertIn('@router.post("/agent/query/stream")', routes)
        self.assertIn('@router.get("/agent/traces/{trace_id}")', routes)
        self.assertIn("app.main_agent:app", dockerfile)

    def test_enterprise_tool_enforces_backend_rbac(self):
        enterprise = (ROOT / "backend/app/tools/enterprise_search.py").read_text(encoding="utf-8")
        self.assertIn("resolve_requested(context.role, requested)", enterprise)
        self.assertIn('status="DENIED"', enterprise)
        self.assertIn("selected_knowledge_base_id", enterprise)


if __name__ == "__main__":
    unittest.main()
