# RAG 权限分离与感知时延设计

## 1. 权限模型

权限分成两个互不替代的维度：

1. **平台能力（Access Role）**：决定能做什么，如查看、问答、管理、评测和运维。
2. **知识域（Business Scope）**：决定数据来自哪些知识库，如公共、HR、产品、销售和售后。

`SALES`、`HR` 是带部门知识域的成员，不再被当成平台管理员。前端只负责隐藏无权入口，FastAPI 依赖、知识库解析和检索过滤才是最终安全边界。

| 平台角色 | 查看知识/会话 | 发起问答/写会话 | 管理知识 | 调试/评测 | 审计/运维 | Trace |
|---|---:|---:|---:|---:|---:|---:|
| `viewer` | ✓ | — | — | — | — | 仅本人 |
| `user` | ✓ | ✓ | — | — | — | 仅本人 |
| `admin` | ✓ | ✓ | ✓ | ✓ | ✓ | 全部 |

| 业务角色 | 平台角色 | 可访问知识域 |
|---|---|---|
| `ADMIN` | `admin` | 全部 |
| `SALES` | `user` | 公共、产品、销售、售后 |
| `HR` | `user` | 公共、HR |
| `USER` | `user` | 公共 |
| `VIEWER` | `viewer` | 公共 |

权限名称由后端统一声明，包括 `knowledge:read`、`knowledge:query`、`knowledge:manage`、`conversation:read`、`conversation:write`、`agent:run`、`trace:read`、`trace:read:any`、`retrieval:debug`、`evaluation:run`、`audit:read` 和 `system:operate`。

## 2. 强制执行链路

```text
Bearer JWT
  → 按服务器当前用户表重建身份（不信任令牌里的旧角色）
  → FastAPI capability dependency
  → requested knowledge base scope validation
  → Qdrant metadata filter + authorized BM25 corpus
  → Agent / LLM context
  → answer + citations
```

- 未知角色默认无任何知识域，采用 fail-closed。
- 会话按 `username` 隔离；读取历史时再次按当前知识域清洗来源，防止角色变更后通过旧回答或流式上下文回看越权信息。
- 普通用户只能读取自己的 Trace；管理员才拥有 `trace:read:any`。
- 权限拒绝写入审计事件，业务统计对非管理员只返回当前用户范围。

## 3. 减少用户感知时长

实际模型耗时不被伪装，界面把等待拆成可理解且可验证的阶段：

- 点击发送后立即插入用户消息和生成中的 AI 气泡，不等待网络往返。
- SSE 立即返回 `authorizing`，随后推送 `retrieving`、`generating`、`done`；前端直接展示服务端阶段文案。
- Local 模式按 token 增量显示；10 秒无数据时发送 heartbeat，避免代理将长请求误判为断开。
- 首页健康、统计、文档和知识库并行独立落屏，单个慢接口不会阻塞其他内容。
- 首屏用结构骨架稳定布局；聊天首次进入才加载，离开后保持挂载，避免切页丢输入和会话状态。
- 上传、重命名、删除先更新局部反馈，再后台同步或失败回滚。

## 4. 验收标准

- `VIEWER` 看不到发送、上传、调试、评测和系统运维入口，对对应 API 的请求返回 403。
- `SALES` 查询 `kb_hr`、`HR` 查询销售/产品/售后知识库时，在进入检索器前返回 403。
- 未授权 Chunk 不进入 Vector、BM25、Rerank 或 LLM Context。
- 角色变化后，旧会话不会把当前无权来源送入模型上下文。
- 管理员可在系统状态页执行 Demo 初始化/重置；非管理员既无入口也无 API 权限。
- 流式响应能观察到权限校验、授权检索、生成和最终持久化状态，连接空闲时仍有 heartbeat。
