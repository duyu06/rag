from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class P18InterviewReadinessContractsTest(unittest.TestCase):
    def test_readiness_panel_uses_live_runtime_sources(self):
        panel = (ROOT / "frontend/src/components/DemoReadiness.tsx").read_text(encoding="utf-8")
        self.assertIn("Promise.allSettled([", panel)
        self.assertIn("api.health()", panel)
        self.assertIn("api.demoStatus()", panel)
        self.assertIn('api.stats("all")', panel)
        self.assertIn('api.agentTools("local")', panel)
        self.assertIn('api.agentTools("auto")', panel)
        self.assertIn('toolPolicyOk(local, ["enterprise_search"])', panel)
        self.assertIn('toolPolicyOk(auto, ["enterprise_search", "web_search"])', panel)

    def test_readiness_gate_covers_runtime_corpus_policy_and_streaming(self):
        panel = (ROOT / "frontend/src/components/DemoReadiness.tsx").read_text(encoding="utf-8")
        self.assertIn('label: "API Runtime"', panel)
        self.assertIn('label: "Qdrant"', panel)
        self.assertIn('label: "Ornith"', panel)
        self.assertIn('label: "Demo Corpus"', panel)
        self.assertIn('label: "Local Tool Policy"', panel)
        self.assertIn('label: "Auto Tool Policy"', panel)
        self.assertIn('label: "Native Streaming"', panel)
        self.assertIn('health.native_streaming === true && health.phase === "P1.8"', panel)
        self.assertIn('ready ? "READY" : "DEGRADED"', panel)

    def test_readiness_is_admin_only_on_dashboard(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        self.assertIn('user.role === "ADMIN" && <DemoReadiness onNavigate={onNavigate} />', page)


if __name__ == "__main__":
    unittest.main()
