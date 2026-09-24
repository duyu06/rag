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
        self.assertIn("current/external", agent.lower())
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


class AgentToolRoutingAfterMigrationTest(unittest.TestCase):
    """Task 8 之后仍然成立的三条工具回路契约（源面）。

    运行面对应用例：`test_model_router_v23_contract.AgentToolCallStandardisationTests`
    （`ToolCall` 标准化）与 `AgentNoCapableFastPathTests`（D2 降级）。这里钉的是
    「工具执行权仍在后端、审计仍成对、降级仍不引入第二条 web 出口」。
    """

    AGENT = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")

    def test_tool_execution_still_lives_in_the_loop_not_in_the_llm_package(self):
        self.assertIn("tool_registry.execute(tool_name, arguments, context)", self.AGENT)
        self.assertIn("tool_registry.schemas(mode)", self.AGENT)
        # 降级腿也是**后端**决定执行哪枚工具（模型没资格，且按构造拿不到 web 证据）。
        self.assertIn('"enterprise_search",', self.AGENT)
        self.assertIn('mode="local"', self.AGENT)

    def test_tool_calls_are_read_through_the_standardised_reader(self):
        # 回填形状（`function.name` / `function.arguments`）与 legacy 腿共用同一个读取器。
        self.assertIn("for call in response.tool_calls", self.AGENT)
        self.assertIn('"function": {"name": call.name, "arguments": dict(call.arguments)}',
                      self.AGENT)
        self.assertIn("_tool_arguments(call)", self.AGENT)

    def test_degradation_keeps_the_audit_pair_and_adds_no_new_egress(self):
        self.assertIn('action="TOOL_CALL"', self.AGENT)
        self.assertIn('action="TOOL_RESULT"', self.AGENT)
        self.assertEqual(2, self.AGENT.count('action="TOOL_CALL"'))   # 回路 + 降级腿各一笔
        self.assertEqual(2, self.AGENT.count('action="TOOL_RESULT"'))


if __name__ == "__main__":
    unittest.main()
