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
        self.assertIn('"think": bool(think)', agent)
        self.assertIn("messages.append(message)", agent)
        self.assertNotIn("reasoning_content", trace)
        self.assertNotIn('"thinking"', trace)

    def test_p16_ollama_keeps_model_warm_and_bounds_synthesis(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn('ollama_keep_alive: str = "30m"', config)
        self.assertIn("agent_think_tool_routing: bool = True", config)
        self.assertIn("agent_think_synthesis: bool = False", config)
        self.assertIn("agent_num_predict_synthesis", config)
        self.assertIn('"keep_alive": settings.ollama_keep_alive', agent)
        self.assertIn('"num_predict": int(num_predict)', agent)
        self.assertIn("routing_turn = bool(tools)", agent)

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

    def test_conversation_context_is_bounded_and_local_mode_has_fast_path(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        conversation_agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        routes = (ROOT / "backend/app/conversation_routes.py").read_text(encoding="utf-8")
        config = (ROOT / "backend/app/config.py").read_text(encoding="utf-8")
        self.assertIn("agent_history_max_messages: int = Field(default=8, ge=0, le=20)", config)
        self.assertIn("agent_local_fast_path: bool = True", config)
        self.assertIn("return normalized[-limit:]", agent)
        self.assertIn("history=history", routes)
        self.assertIn('mode == "local" and settings.agent_local_fast_path', conversation_agent)
        self.assertIn('"fast_path": True', conversation_agent)
        self.assertIn('"llm_calls": llm_calls', conversation_agent)
        self.assertIn("tool_registry.execute", conversation_agent)
        self.assertIn("selected_knowledge_base_id=knowledge_base_id", conversation_agent)

    def test_short_followup_query_replaces_stale_entity_within_same_family(self):
        conversation_agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        self.assertIn("ENTITY_PATTERN", conversation_agent)
        self.assertIn("def _entity_family", conversation_agent)
        self.assertIn("current_entities", conversation_agent)
        self.assertIn("previous_entities", conversation_agent)
        self.assertIn("_entity_family(candidate) == family", conversation_agent)
        self.assertIn("re.escape(old)", conversation_agent)
        self.assertIn("retrieval_query_context_max_chars", conversation_agent)


if __name__ == "__main__":
    unittest.main()
