
**Files:** Create `app/llm/classifier.py`、`router.py`；测试类③。

**Interfaces:** `classify(query:str, *, mode, needs_tools=False, needs_stream=False) -> RequestProfile`（complexity：len≥60 或 对比/为什么/方案/风险/多条件词→high；有连接的多约束→medium；else low——词表模块常量+注释）；`plan(profile, registry, health_view: Mapping[str, dict]) -> RoutePlan`：过滤顺序 enabled→caps（chat 恒需；mode 对应 caps；needs_tools→tools；needs_stream→stream）→ external policy（V2.3 仅透传旗标）→ health（provider healthy ∧ not circuit_open，全灭时降级为"忽略 health 但记 PRIMARY_UNHEALTHY/CIRCUIT_OPEN"还是抛 NoCapable？**冻结：健康全灭→仍抛 NoCapableModelError，由 fallback 的 legacy 分支或业务降级承接**——评审确认与 D2 一致）→ limits（context 粗估 len(messages) 字符/2，超限候选剔除）→ priority[mode] 降序 → 同分 pricing 低优；reason codes 全程记录；`profile.mode` 在 priority 缺失键=0 分剔除（tools priority 0 → agent 模式剔除，与 capability 双保险）。P95≤10ms：60 候选×200 次循环计时测试。

