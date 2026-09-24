from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ConversationUIP1CContractTests(unittest.TestCase):
    def test_chat_is_rendered_directly_without_portal_adapter(self):
        layout = (ROOT / "frontend/src/app/layout.tsx").read_text(encoding="utf-8")
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        ask = (ROOT / "frontend/src/views/AskView.tsx").read_text(encoding="utf-8")
        adapter = ROOT / "frontend/src/components/ConversationExperience.tsx"
        self.assertNotIn("ConversationExperience", layout)
        self.assertFalse(adapter.exists())
        # 问答工作台现在由 views/AskView 直接挂载在 shell 的视图分支上。
        self.assertIn('import AskView from "@/views/AskView";', page)
        self.assertIn('{view === "ask" && <AskView {...sharedProps} />}', page)
        self.assertNotIn("ConversationExperience", page)
        self.assertIn(
            'const canAsk = hasPermission(user, "conversation:write")'
            ' && hasPermission(user, "agent:run")'
            ' && hasPermission(user, "knowledge:query");',
            ask,
        )
        self.assertNotIn("function ChatPanel(", page)

    def test_conversation_layout_has_responsive_classes(self):
        panel = (ROOT / "frontend/src/views/AskView.tsx").read_text(encoding="utf-8")
        css = (ROOT / "frontend/src/app/globals.css").read_text(encoding="utf-8")
        for class_name, marker in (
            ("ask", '<div className="ask">'),
            ("thread", '<div className="thread" aria-live="polite">'),
            ("inspector", '<aside className="inspector panel"'),
            ("composer", '<form className="composer"'),
        ):
            self.assertIn(marker, panel)
            self.assertIn(f".{class_name} {{", css)
        # 断点体系：宽屏 → 单列（≤1023）→ 侧栏折叠（≤767）。
        self.assertIn("@media (max-width: 1439px)", css)
        self.assertIn("@media (max-width: 1023px)", css)
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn(".ask, .split { grid-template-columns: minmax(0, 1fr); }", css)
        self.assertIn(".ask .inspector, .split .inspector { position: static; width: 100%; }", css)
        self.assertIn("onStatus: (phase) => {", panel)
        self.assertIn('event === "status"', (ROOT / "frontend/src/lib/conversations.ts").read_text(encoding="utf-8"))

    def test_agent_debugger_surfaces_p1b_timings(self):
        debugger = (ROOT / "frontend/src/views/TraceView.tsx").read_text(encoding="utf-8")
        # 旧的 admin/agent 调试页已并入 06 请求追踪，逐阶段耗时在此呈现。
        self.assertIn("阶段时间轴", debugger)
        for key in (
            "query_received",
            "query_rewrite",
            "acl_filter",
            "vector_search",
            "bm25",
            "hybrid_fusion",
            "rerank",
            "context_build",
            "generation",
            "citation_verify",
        ):
            self.assertIn(f'key: "{key}"', debugger)
        self.assertIn("raw.elapsed_ms ?? null", debugger)
        self.assertIn('["总耗时", fmtMs(trace.elapsed_ms)]', debugger)
        self.assertIn("瓶颈", debugger)
        # 调试器只渲染阶段/工具事件，不外泄模型的 hidden reasoning。
        self.assertNotIn("reasoning", debugger)
        self.assertNotIn("thinking", debugger)
        self.assertIn(
            "Agent Trace 不保存 hidden reasoning / chain-of-thought",
            (ROOT / "docs/P1_7_STREAMING.md").read_text(encoding="utf-8"),
        )

    def test_release_smoke_has_safe_and_real_agent_modes(self):
        smoke = (ROOT / "scripts/release_smoke.py").read_text(encoding="utf-8")
        self.assertIn('parser.add_argument(\n        "--agent"', smoke)
        self.assertIn("SQLite conversation create + restore", smoke)
        self.assertIn("real Ornith Local Fast Path -> Qdrant -> Citation -> timings", smoke)
        self.assertIn("conversation cleanup", smoke)


if __name__ == "__main__":
    unittest.main()
