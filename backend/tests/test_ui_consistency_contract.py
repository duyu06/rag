from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class UiConsistencyContractsTest(unittest.TestCase):
    def test_typesafe_judgment_layer_card_area_is_chinese_first(self):
        """判定层观测区（TypeSafe V2 Task 7）：卡片区存在、文案按术语基准、块缺失不崩。"""
        system = (ROOT / "frontend/src/views/SystemView.tsx").read_text(encoding="utf-8")
        trace = (ROOT / "frontend/src/views/TraceView.tsx").read_text(encoding="utf-8")
        api_client = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")

        # Kicker 与七张卡（比率/计数/熔断态），值一律"一位小数百分比"。
        self.assertIn("<Kicker>判定层观测</Kicker>", system)
        for label in (
            "触发率",
            "跳过率",
            "缓存命中",
            "超时率",
            "降级率",
            "每查询外呼数 P95",
            "熔断状态",
        ):
            self.assertIn(f'label="{label}"', system)
        self.assertIn("toFixed(1)", system)
        # 改名不留半截旧口径：`requests_per_query_p95` 只数**真实外呼**（缓存命中不计数），
        # 分母是"进入判定层的查询数"，故显示层写"每查询外呼数"；Token 卡同按查询口径。
        self.assertNotIn("每请求判定数", system)
        self.assertNotIn("每请求输入 Token", system)
        # 比率的分母为 0 时显示 "—"：后端此时把比率折成 0.0，那是"没样本"不是"零触发"。
        self.assertIn("(typesafe?.sample_count ?? 0) > 0", system)
        self.assertIn("fmtRate(typesafe?.trigger_rate, typesafeHasSamples)", system)
        self.assertIn('value == null || !hasSamples ? "—"', system)
        # 成本的小数位自适应：<0.001 保留 6 位（否则 $0.00005 会被折成 $0.00），其余 4 位。
        self.assertIn("toFixed(Math.abs(value) < 0.001 ? 6 : 4)", system)

        # 数据源是 status.typesafe；mode=off 或整块缺失 → 显示"未启用"，不得崩。
        self.assertIn("status?.typesafe", system)
        self.assertIn('typesafe.mode === "off"', system)
        self.assertIn("未启用", system)
        self.assertIn("typesafe?: TypesafeStats | null", api_client)

        # 熔断三态与五档模式：代码枚举值不动，显示层中文（术语基准"枚举值 → 中文"）。
        for chinese in ("闭合", "打开", "半开", "只观测", "按需判定", "高置信免判", "恒判"):
            self.assertIn(chinese, system)

        # 不新增缩写英文：Stat/Kv 的 label 不接受英文裸标签（P50/P95/Token 属保留项）。
        self.assertNotRegex(system, r'label="[A-Za-z]')

        # trace 子事件由后端写进 detail，前端只渲染既有 detail 文本 ⇒ 不重复加标签。
        self.assertIn('key: "rerank", name: "重排序"', trace)
        self.assertIn("{stage.detail}", trace)
        self.assertNotIn("typesafe_trigger", trace)

    def test_main_ui_matches_p18_readiness_p17_streaming_and_p16_retrieval_baseline(self):
        page = (ROOT / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
        nav = (ROOT / "frontend/src/lib/nav.ts").read_text(encoding="utf-8")
        home = (ROOT / "frontend/src/views/HomeView.tsx").read_text(encoding="utf-8")
        ask = (ROOT / "frontend/src/views/AskView.tsx").read_text(encoding="utf-8")
        evaluation = (ROOT / "frontend/src/views/EvaluationView.tsx").read_text(encoding="utf-8")
        api_client = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
        readiness = (ROOT / "frontend/src/components/DemoReadiness.tsx").read_text(encoding="utf-8")
        chat = (ROOT / "frontend/src/components/ConversationChatPanel.tsx").read_text(encoding="utf-8")
        demo_tools = (ROOT / "frontend/src/components/DemoTools.tsx").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        stale_ten_question_copy = "当前内置 " + "10 道"
        stale_demo_label = "P1." + "2 · 真实指标 + 审计"

        # 品牌 + 中文产品定位在工作台与登录页各出现一次；构建阶段在首页系统栏。
        self.assertIn("<strong>yaoke</strong>", page)
        self.assertIn("<span>企业知识操作系统</span>", page)
        self.assertIn('<div className="row"><span>构建版本</span><b>P1.8</b></div>', home)
        # 可观测性（原 DemoReadiness 工作台面板）迁入 10 系统视图，仍受 system:operate 管控。
        self.assertIn('import SystemView from "@/views/SystemView";', page)
        self.assertIn('{ key: "system", idx: "10", zh: "系统", perms: ["system:operate"] },', nav)
        self.assertIn('if (!allowed.includes(view)) setView("home");', page)
        self.assertIn('{view === "ask" && <AskView {...sharedProps} />}', page)
        self.assertIn(
            'const canAsk = hasPermission(user, "conversation:write")'
            ' && hasPermission(user, "agent:run")'
            ' && hasPermission(user, "knowledge:query");',
            ask,
        )
        # 四路检索评测：mode key 保持英文，展示名走中文映射；数据集规模逐次运行显示。
        self.assertIn('modes: ["vector", "bm25", "hybrid", "hybrid_rerank"],', api_client)
        self.assertIn("数据集 {fmtNum(run.dataset_size)} 个用例", evaluation)
        self.assertIn("run.modes[mode]", evaluation)
        self.assertIn("const m = run.modes[mode];", evaluation)
        self.assertIn('bm25: "关键词"', evaluation)
        self.assertIn('hybrid_rerank: "混合+重排"', evaluation)
        self.assertNotIn(stale_ten_question_copy, page)
        self.assertNotIn(stale_demo_label, page)
        self.assertNotIn("function ChatPanel(", page)

        self.assertIn("演示就绪检查", readiness)
        self.assertIn('api.agentTools("local")', readiness)
        self.assertIn('api.agentTools("auto")', readiness)
        self.assertIn("native_streaming", readiness)
        self.assertIn('label: "本地工具策略"', readiness)
        self.assertIn('label: "自动工具策略"', readiness)

        self.assertIn("本地模式支持原生流式输出", chat)
        self.assertIn("conversationApi.sendStream(", chat)
        self.assertIn("onStatus: applyServerStatus", chat)
        self.assertIn("P1.8 / v0.8.0", demo_tools)
        self.assertIn("演示就绪检查", demo_tools)
        self.assertIn("当前版本：**P1.8 / v0.8.0**", readme)
        self.assertIn("scripts/release_smoke.py --stream", readme)
        self.assertIn("docs/P1_8_READINESS.md", readme)
        self.assertIn("docs/P1_7_STREAMING.md", readme)
        self.assertIn("docs/P1_6_RELEASE.md", readme)
        self.assertIn("docs/P1_5_CONVERSATIONS.md", readme)


if __name__ == "__main__":
    unittest.main()
