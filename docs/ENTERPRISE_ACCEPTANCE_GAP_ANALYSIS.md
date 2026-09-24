# 企业级验收框架 G0–G19 差距盘点（2026-09-23）

来源：《企业级 RAG 知识库验收方案 V1.0》（用户方案书）对照当前代码库的只读盘点。证据路径相对 `E:\xiangmu\rag`。规模快照：pytest 392 collected；复杂评测集 59+16 题、基础集 30 题；CI 4 jobs；前端测试 0；备份脚本 0。

| Gate | 现状 | 关键证据 / 缺口一句话 |
| --- | --- | --- |
| G0 工程 | 部分 | `.github/workflows/ci.yml` 已有 build/测试/真BGE门禁/前端构建；缺 lint、typecheck、依赖扫描(pip-audit)、工具化 secret 扫描(gitleaks)、OpenAPI 契约测试 |
| G1 知识治理 | 大部分缺失 | payload 仅 8 字段（`ingestion.py:162`）；无 owner/version/checksum/密级/生效期；同名重传=覆盖重索引，无 superseded/active |
| G2 检索质量 | 接近良好 | Hit@1/Hit@3/MRR 双实现有实测；缺 Recall@5、nDCG@10、graded relevance |
| G3 生成质量 | 缺失 | `complex_accuracy.py` 只查拒答标记词与回合存在性；Groundedness/Correctness/Completeness 零自动度量 |
| G4 引用 | 部分 | 引用编号+打开原文有（`CitationActions.tsx`、`main.py:404` 二次ACL）；Precision/Coverage 无计算，citation_verify 是展示性假步骤（`knowledge_os.py:912`），无页内定位高亮 |
| G5 ACL | 部分（库级为限） | 五角色×库矩阵+fail-closed+运行时 7 例全绿（`test_rbac_contract.py`）；无文档级/chunk 级 ACL、无 VIEWER×全端点矩阵 |
| G6 多租户 | 缺失 | `tenant_id` 全仓零命中；`docs/SECURITY_REVIEW.md:20` 自认 |
| G7 注入防护 | 部分 | 检索侧 TypeSafe `contains_prompt_injection`（默认 shadow）；摄取侧零扫描、TypeSafe 关闭即无兜底 |
| G8 敏感数据 | 部分 | 密钥形态脱敏贯穿审计/trace；无盐 SHA256 密码（`auth.py:173`）一票否决级、无 PII 检测、MIME 不校验、无 rate limit |
| G9 拒答 | 部分 | 无答案仅 2 题+关键词判定；无拒答率指标 |
| G10 Query Rewrite | 缺失 | 现标 `passthrough`；仅会话层规则式追问增强；原始 query 保护约束无测试 |
| G11 性能 | 部分 | 分段 timings+单查询 benchmark 有；无并发压测/容量曲线/SLO 成文 |
| G12 稳定性 | 判定层强主链弱 | `resilience.py` 熔断+预算已成型（TypeSafe 已接）；主 LLM 调用无重试熔断、INDEXING 崩溃永卡、Qdrant 挂直抛 503 |
| G13 备份恢复 | 缺失 | 零脚本零演练；数据散在 sqlite/jsonl/documents/Qdrant volume |
| G14 可观测 | 部分 | agent 路 trace_id+SystemView 全；/api/query 无 request_id/trace_id，主 LLM tokens/cost 不采集 |
| G15 审计 | 部分 | 事件面广+双向脱敏；无 ACL_CHANGE/CONFIG_CHANGE、单文件不防篡改 |
| G16 模型治理 | 部分 | env 可配三 provider；`rag.py:41` if-key 硬分支；无注册表/灰度/成本预算（=Model Router V2 靶区） |
| G17 版本治理 | 部分 | `retrieval_schema_version` 有且 demo 自动重建；用户文档不触发、无双索引灰度回滚 |
| G18 Prompt 版本 | 缺失 | RAG/Agent prompt 为源码常量无版本号（仅 TypeSafe 有 PROMPT_VERSION） |
| G19 Golden Dataset | 部分 | case schema 有雏形；缺 tenant/role/expected_sections/expected_answer_contains/answerable/forbidden_document 字段 |

## 缺失能力 Top 排序（重要性 × 成本，靠前先做）

1. G8 密码 pbkdf2/bcrypt 替换 + MIME 真校验（低成本速赢，一票否决项）
2. G14/G18 request_id/trace_id 全链路 + prompt 版本化入审计（低成本高判定价值）
3. G1 文档元数据治理（owner/version/checksum/密级/生效期，扩 registry+payload）
4. G19→G3/G4 Golden Dataset schema 升级 + 答案级断言评测
5. G9 无答案集扩容与拒答率指标化
6. G4 Citation Precision/Coverage 计算 + 替换假 citation_verify + 页内定位
7. G7 摄取侧 injection/PII 本地规则兜底
8. G13 备份/恢复脚本 + 真实 restore 演练
9. G11 并发压测（`benchmark_retrieval.py` + concurrency）+ SLO 成文
10. G12 主 LLM 复用 resilience + INDEXING 卡死回收
11. G6 多租户全线（结构性，成本高，硬门槛）
12. G2 Recall@5/nDCG@10（需 graded labels）
13. G17 双索引灰度回滚（collection 别名）
14. G15 ACL_CHANGE/CONFIG_CHANGE + 防篡改链（依赖 G1/G6 先行）

## 排期决议

按既定顺序：TypeSafe V2（执行中，Task 8 真实验收）→ Model Router V2.1–2.4（对应 G16 主体）→ 企业验收框架。框架本身按 scope check 至少拆三个 spec：A 安全速赢包（G8/G7/G14/G18 低成本项）、B 知识治理与数据集（G1/G19/G3/G4/G9）、C 运维可靠性与租户（G13/G11/G12/G6/G17/G15）。每个 spec 独立 spec→plan→SDD 循环；本盘点是它们的共同输入。
