# Complex Accuracy Gate

这套门禁独立于原有 30 题 P1.6 基线，目的是验证系统面对更难表达和安全边界时仍然稳定，不修改原始题集或预期答案。

## 覆盖范围

- 59 道高难度单文档检索题：近义改写、数值边界、条件判断、否定表达、多约束、时间换算和相似文档干扰。
- 5 道跨文档组合题：一次问题必须同时召回两份指定文档。
- 7 道 RBAC / Scope 攻击题：直接越权请求和“忽略权限”提示注入都不得泄漏未授权知识库。
- 4 个真实多轮问答回合：检查短追问的实体继承和 Citation 来源。
- 2 道无答案题：知识库不存在事实时，真实 Ornith 必须明确说明证据不足。

## 执行

不调用 LLM 的快速门禁：

```bash
python scripts/complex_accuracy.py
```

面试机完整门禁：

```bash
python scripts/complex_accuracy.py --with-llm
```

只复测真实多轮与无答案边界：

```bash
python scripts/complex_accuracy.py --llm-only
```

TypeSafe `active` 严格门禁（逐阶段要求真实调用、零降级、模式一致，并输出 JSON）：

```bash
python scripts/complex_accuracy.py --require-typesafe --expect-typesafe-mode active --max-typesafe-degraded 0 --min-typesafe-requests 414 --json-output output/typesafe-active-complex.json
python scripts/complex_accuracy.py --llm-only --rerank-llm-boundaries --require-typesafe --expect-typesafe-mode active --max-typesafe-degraded 0 --min-typesafe-requests 36 --json-output output/typesafe-active-llm.json
```

完整实测证据见 `docs/TYPESAFE_ACCEPTANCE_2026-09-22.md`。

默认质量阈值对四路同时生效：

```text
Hit@1 >= 90%
Hit@3 >= 90%
MRR   >= 90%
RBAC / Scope = 100%
Compound = 100%
Live LLM = 100%（启用 --with-llm 时）
```

题集位于 `backend/eval_dataset_complex.json`。失败输出会列出模式、题目类别、正确来源排名和实际 Top-1，方便区分召回问题、融合问题和重排问题。
