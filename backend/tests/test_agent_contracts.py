import json
import sys
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
        # 只断"调用形"：resolve_requested(context.role, requested, allowed=...) 必须整体出现
        # （M3：`assertIn("resolve_requested(")` 换个不相干的调用也能满足，是弱条款）。
        self.assertRegex(
            enterprise,
            r"resolve_requested\(\s*context\.role,\s*requested,\s*"
            r"allowed=context\.allowed_knowledge_base_ids\s*\)",
        )
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


# TS-V2 收尾（拒答语言 P2）：生成端三处 prompt 必须把面向用户的语言锁成中文，
# 且锁定的固定拒答话术必须能被下游「无答案」判据（中文标记白名单）命中。
REFUSAL_PHRASE = "当前知识库中没有找到可以回答该问题的资料"


class AnswerLanguageContractTest(unittest.TestCase):
    def test_rag_prompt_locks_user_facing_language_to_chinese(self):
        rag = (ROOT / "backend/app/rag.py").read_text(encoding="utf-8")
        self.assertIn("无论用户使用何种语言提问，面向用户的最终答案一律使用简体中文", rag)
        self.assertIn("必须以**中文**输出拒答说明", rag)
        self.assertIn(REFUSAL_PHRASE, rag)
        # 与既有引用格式共存：[n] 约定仍然生效。
        self.assertIn("引用标记保持 [1] [2] 形式不变", rag)
        self.assertIn("关键事实使用 [1] [2] 形式标注引用来源", rag)

    def test_agent_and_conversation_fast_path_prompts_lock_chinese(self):
        agent = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")
        conversation_agent = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        # Agent 路（会话流与 /api/agent/* 共用 AGENT_SYSTEM_PROMPT）。
        self.assertIn("ALWAYS written in Simplified Chinese", agent)
        self.assertIn("无论用户使用何种语言提问，面向用户的最终答案语言为中文", agent)
        self.assertIn(REFUSAL_PHRASE, agent)
        self.assertIn("Citation markers keep the [1], [2] form", agent)
        # local fast path 追加段同样带中文硬约束（不依赖单点 prompt）。
        self.assertIn("输出语言硬约束：最终答案与拒答说明一律使用简体中文", conversation_agent)
        self.assertIn(REFUSAL_PHRASE, conversation_agent)

    def test_imported_prompts_carry_the_same_chinese_constraint(self):
        # 直接钉运行期常量对象，防止"改了注释/改了别处字符串"这类假阳性。
        sys.path.insert(0, str(ROOT / "backend"))
        from app.agent import AGENT_SYSTEM_PROMPT
        from app.rag import SYSTEM_PROMPT

        for prompt in (SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT):
            self.assertIn(REFUSAL_PHRASE, prompt)
            self.assertIn("[1]", prompt)
        self.assertIn("简体中文", SYSTEM_PROMPT)
        self.assertIn("简体中文", AGENT_SYSTEM_PROMPT)

    def test_locked_refusal_phrase_satisfies_no_answer_judge_markers(self):
        # 判据侧（scripts/complex_accuracy.py）用中文标记白名单判「无答案」：
        # 固定话术必须至少命中一个标记，且标记集必须是纯中文（语言无关判据未落地前的契约）。
        dataset = json.loads(
            (ROOT / "backend/eval_dataset_complex.json").read_text(encoding="utf-8")
        )
        cases = dataset["no_answer_cases"]
        self.assertTrue(cases)
        for case in cases:
            markers = tuple(case.get("refusal_markers") or ())
            self.assertTrue(markers, f"{case['id']} 缺少 refusal_markers")
            self.assertTrue(
                all(any("\u4e00" <= ch <= "\u9fff" for ch in marker) for marker in markers),
                f"{case['id']} 的拒答标记须为中文",
            )
            self.assertTrue(
                any(marker in REFUSAL_PHRASE for marker in markers),
                f"{case['id']}: 固定话术未命中该用例的任一中文拒答标记",
            )


# ==========================================================================
# Model Router V2.3 Task 8：agent 生成腿收编进 `app/llm`（**源面**契约）
#
# 分工：运行面（真调用 / 报文 / trace 九键 / D2 降级）在
# `tests/test_model_router_v23_contract.py` 的 `Agent*Tests` 五组里；本类只钉「形状仍在原位」
# 这一层——它挡的是行为测试看不见的那类回退：整段删掉 legacy 分支（#18 失去对照物）、
# 把 D2 的 catch 挪进 `app/llm`（偷走这条链的降级语义）、或在 `save_trace` 之后才挂
# `model_route`（那枚键就永远落不到盘上）。
# ==========================================================================
class AgentRouterMigrationContractTest(unittest.TestCase):
    AGENT = (ROOT / "backend/app/agent.py").read_text(encoding="utf-8")

    def test_the_generation_leg_has_one_router_entry_and_one_degraded_entry(self):
        self.assertIn("from app import llm", self.AGENT)
        self.assertIn("if llm.router_enabled():", self.AGENT)
        self.assertIn("return _chat_via_router(", self.AGENT)
        self.assertIn('mode="agent"', self.AGENT)          # 两轮共用的 agent 画像
        self.assertIn('needs_tools=bool(tools)', self.AGENT)
        self.assertIn('mode="rag"', self.AGENT)            # D2 降级腿的合成画像
        # 本链自己的温度出处（DESIGN §9.1：不许吃 rag 链的 0.1）
        self.assertIn("AGENT_LEGACY_TEMPERATURE = 0.2", self.AGENT)
        self.assertIn("temperature=AGENT_LEGACY_TEMPERATURE", self.AGENT)

    def test_d2_zero_candidate_downgrade_is_owned_by_this_chain(self):
        # 两处 catch：工具回路那一轮 + 工具轮次耗尽后的合成轮（`for…else` 那支）。
        self.assertEqual(2, self.AGENT.count("except NoCapableModelError as exc:"))
        self.assertIn("NO_CAPABLE_MODEL→fast_path", self.AGENT)
        self.assertIn("_degrade_to_local_fast_path(", self.AGENT)
        self.assertIn('"type": "model_route_downgrade"', self.AGENT)
        # `AllCandidatesFailedError` / 硬终态 `LLMError` **不在**本文件 catch：
        # 现网兜底语义是「异常上抛 → agent_routes 的 503 那句」，一个字都不许换。
        # （散文里提它们的名字是允许的——那是解释，不是 catch 面。）
        self.assertNotIn("except AllCandidatesFailedError", self.AGENT)
        self.assertNotIn("except LLMError", self.AGENT)
        self.assertNotIn("except (LLMError", self.AGENT)

    def test_model_route_is_attached_before_the_trace_hits_disk(self):
        self.assertIn("from app.agent_trace import attach_model_route", self.AGENT)
        self.assertIn("attach_model_route(trace, outcome.result.plan, outcome.result,"
                      " profile=outcome.profile)", self.AGENT)
        self.assertLess(self.AGENT.index("attach_model_route(trace, outcome"),
                        self.AGENT.index("    save_trace(trace)"),
                        "落盘之后再挂 = 那枚键永远不会出现在 JSONL 里")

    def test_the_degraded_leg_has_its_own_second_zero_candidate_catch(self):
        """Task 8 修复轮 C-1/I-1/I-2/I-3/m-6 的**源面**形状钉（运行面在 v23 契约文件）。

        这里只挡「把第二道 catch 整个删掉 / 把三支文案短路挪走」这类形状回退：
        运行面用例（`AgentNoCapableFastPathTests`）已各自能抓，源面这一层是第二张网。
        """
        # 两处零候选 catch 各写一次（`as exc` = 两条降级门；`as second_exc` = 第二道 catch），
        # 三支调用点共用同一个出口函数 ⇒ 不会长出第四份「降级之后再降级」的写法。
        self.assertEqual(1, self.AGENT.count("except NoCapableModelError as second_exc:"))
        self.assertEqual(3, self.AGENT.count("= _synthesize_with_second_door("))
        # m-6：`stage == "context"` 时不重跑 enterprise_search。
        self.assertIn('exc.stage == "context"', self.AGENT)
        # I-2：降级腿的工具耗时走盒子回收尾算式，不并进 `llm_ms`。
        self.assertIn("tool_time: dict[str, float]", self.AGENT)
        self.assertIn("model_ms = max(elapsed_ms - tool_time_total - sum(tool_time_box.values())",
                      self.AGENT)
        # I-3：三支硬文案与 `_local_fast_path` **逐字同源**（文案分叉=两条链不等价）。
        conversation = (ROOT / "backend/app/conversation_agent.py").read_text(encoding="utf-8")
        for copy in ("当前账号无权访问该知识库，因此不能基于未授权资料回答。",
                     "企业知识检索暂时失败，请稍后重试。",
                     "当前授权范围内没有检索到足够证据，暂时无法可靠回答。"):
            self.assertIn(copy, self.AGENT)
            self.assertIn(copy, conversation)
        # 短路那支不许顺手把 `route_out` 塞进盒子（没走生成就没有执行面事实可解释）：
        # 降级函数里对这只盒子的写入只发生在**唯一那次**合成调用上。
        degrade = self.AGENT[self.AGENT.index("def _degrade_to_local_fast_path("):
                             self.AGENT.index("def run_agent(")]
        self.assertEqual(1, degrade.count("route_out=route_out"),
                         "出现第二处 route_out 写入 = 有一支文案短路也会挂 model_route")
        self.assertIn("return fast_path_copy", degrade)

    def test_the_legacy_httpx_branch_is_still_here_verbatim(self):
        """#18 的对照物 + Task 9 的 D6 豁免项：删它要等 legacy 应急路一起删（DESIGN §1）。"""
        self.assertIn("import httpx", self.AGENT)
        self.assertIn('settings.ollama_base_url.rstrip("/") + "/api/chat"', self.AGENT)
        self.assertIn('"temperature": 0.2,', self.AGENT)   # 字面量没被常量替换（报文逐字节不变）
        self.assertIn('timeout=settings.agent_llm_timeout_seconds', self.AGENT)
        self.assertIn('raise RuntimeError("Ollama 返回缺少 message")', self.AGENT)


if __name__ == "__main__":
    unittest.main()
