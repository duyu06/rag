from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class AgentRoutingContractsTest(unittest.TestCase):
    def test_local_mode_never_exposes_web_tool(self):
        registry = (ROOT / "backend/app/tools/registry.py").read_text(encoding="utf-8")
        web_tool = (ROOT / "backend/app/tools/web_search_tool.py").read_text(encoding="utf-8")
        self.assertIn('modes=frozenset({"auto", "web"})', registry)
        self.assertIn('context.mode == "local"', web_tool)
        self.assertIn('status="DENIED"', web_tool)

    def test_agent_prompt_routes_internal_and_current_queries(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        self.assertIn("Internal policies", agent)
        self.assertIn("current external", agent.lower())
        self.assertIn("enterprise_search", agent)
        self.assertIn("web_search", agent)

    def test_tool_call_and_result_are_audited(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        self.assertIn('action="TOOL_CALL"', agent)
        self.assertIn('action="TOOL_RESULT"', agent)
        self.assertIn("trace_id=", agent)

    def test_trace_does_not_persist_reasoning_content(self):
        trace = (ROOT / "backend/app/agent_trace.py").read_text(encoding="utf-8")
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        self.assertNotIn("reasoning_content", trace)
        self.assertNotIn('"thinking":', trace)
        self.assertIn("answer_preview", agent)


if __name__ == "__main__":
    unittest.main()
