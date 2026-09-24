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
        # 显示层中文标签（ui 文案基准）；检查项 key 与后端比较值仍是英文枚举。
        self.assertIn('label: "API 运行时"', panel)
        self.assertIn('label: "Qdrant"', panel)
        self.assertIn('label: "Ornith"', panel)
        self.assertIn('label: "演示语料"', panel)
        self.assertIn('label: "本地工具策略"', panel)
        self.assertIn('label: "自动工具策略"', panel)
        self.assertIn('label: "原生流式输出"', panel)
        self.assertIn('health.native_streaming === true && health.phase === "P1.8"', panel)
        self.assertIn('ready ? "就绪" : "降级"', panel)

    def test_readiness_is_admin_only_on_dashboard(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        nav = (ROOT / "frontend/src/lib/nav.ts").read_text(encoding="utf-8")
        # 就绪 / 可观测性面板不再是工作台里的 DemoReadiness，而是 10 系统视图；
        # 访问控制由导航声明的 system:operate 权限 + 视图回落共同保证。
        self.assertIn('{ key: "system", idx: "10", zh: "系统", perms: ["system:operate"] },', nav)
        self.assertIn("{view === \"system\" && <SystemView {...sharedProps} />}", page)
        self.assertIn("if (!allowed.includes(view)) setView(\"home\");", page)
        self.assertIn("const sections = useMemo(() => visibleSections(user), [user]);", page)


if __name__ == "__main__":
    unittest.main()
