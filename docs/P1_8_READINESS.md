# P1.8 · Interview Readiness / Demo Observability

P1.8 不改变 P1.6 Retrieval quality、P1.7 Conversation Streaming 或 RBAC 语义。它解决的是面试演示前的最后一个问题：

> 当前机器到底是否已经具备可演示条件，能不能在一屏里看出来？

## 目标

管理员打开工作台后，Interview Readiness 面板会实时读取现有运行接口并汇总：

- API Runtime
- Qdrant
- Ornith
- Demo Corpus
- Local Tool Policy
- Auto Tool Policy
- Native Streaming capability
- 文档 / Chunk / 今日问答 / 平均耗时 / 拒绝访问

只有所有关键 gate 都通过时，整体状态才显示 `READY`。

## Gate 定义

### API Runtime

要求：

- `/api/health.status == healthy`
- runtime metadata 为 `P1.8 / v0.8.0`

### Qdrant

要求：

- `vector_db_connected=true`

### Ornith

要求：

- `agent_llm_connected=true`
- 当前 Agent 模型来自 backend runtime，而不是前端写死

### Demo Corpus

要求：

- `ready=true`
- `ready_count == total`
- `total > 0`

内置演示数据当前预期为 20/20。

### Local Tool Policy

严格要求：

```text
enterprise_search
```

Local 模式不能暴露 `web_search`。

### Auto Tool Policy

严格要求：

```text
enterprise_search
web_search
```

### Native Streaming

health 必须报告：

```json
{
  "phase": "P1.8",
  "version": "0.8.0",
  "native_streaming": true
}
```

这个字段只表示当前 runtime 已包含 P1.7 native streaming capability，不替代真实模型性能验收。

## 为什么仍需要 release_smoke.py --stream

Readiness 面板验证的是“依赖、配置、Tool Policy 和 capability 是否就绪”。

真实 streaming 还需要本机执行：

```bash
python scripts/release_smoke.py --stream
```

该 smoke 会进一步验证：

- Conversation SSE 可连接
- 至少多个非空 token event
- 首 token 在 done 之前到达
- `native_stream=true`
- streamed text 与最终 SQLite 持久化文本一致
- 同一 assistant message id
- Citation / Trace 存在
- Conversation reload 后 Answer / Citation 仍一致

面试机器如需设 TTFT SLA：

```bash
python scripts/release_smoke.py --stream --max-ttft 8
```

TTFT SLA 默认关闭，因为硬件性能不应成为普通 CI 的代码正确性门禁。

## 面试使用方式

推荐第一屏就打开管理员工作台：

1. 指出总状态 `READY`
2. 快速扫过 Qdrant / Ornith / Demo 20/20
3. 指出 Local 只有 enterprise_search
4. 指出 Auto 才有 web_search
5. 指出 Native Streaming PASS
6. 点击“开始演示”进入 Conversation

这样后续展示 Streaming、RBAC、Evaluation、Trace 时，面试官已经知道当前环境依赖是正常的。

## 失败语义

Readiness 使用 `Promise.allSettled` 聚合多个接口。

任何一个检查失败：

- 不影响工作台其他页面继续使用
- 总状态不会显示 READY
- 对应检查显示 FAIL 或未完成
- 面板提示重新检查或查看系统状态

P1.8 不把 readiness 失败转换成业务接口 500，也不改变现有问答链路。

## 版本分层

- P1.6：Retrieval Quality / real-BGE baseline
- P1.7：Native Conversation Streaming / SSE / same-message persistence
- P1.8：Interview Readiness / Demo Observability

P1.8 的设计原则是：**把已有能力变得更容易证明，而不是为了版本号再堆新 Agent 能力。**
