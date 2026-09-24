# Task 11 容器层冒烟证据（2026-09-24）

镜像：`rag-backend:7b350b4d183d`（2.67 GB，本次重建；此前 33 小时前的旧镜像已不存在于运行态）

## 1. 启动门（warmup fail-fast 未触发）

```
Container rag-qdrant-1   Healthy
Container rag-backend-1  Started → Up 26 seconds (healthy)

backend-1 | INFO: Started server process [1]
backend-1 | INFO: Waiting for application startup.
backend-1 | INFO: Application startup complete.
backend-1 | INFO: Uvicorn running on http://0.0.0.0:8001
backend-1 | INFO: 127.0.0.1:59212 - "GET /api/ready HTTP/1.1" 200 OK
```

⇒ `lifespan` 里的 `warmup_identity_permissions()` + `warmup_llm_router()`（注册表 fail-fast）
**双双通过**，服务未被启动门阻断；健康探针 `/api/health` 200。
⇒ 顺带证明 `Dockerfile` 的 `COPY config ./config`（飞书桥那轮加的）把 V2.3 新增的
`config/llm_registry.json` 一起打进了镜像 —— 没有这一步，容器内注册表读不到、启动就会 fail-fast。

## 2. 观测面形状（容器内直跑端点所用的同一组合函数）

`/api/system/status` 从宿主 curl ⇒ **HTTP 401**（需 `system:operate`，鉴权没有被放宽，是正确行为）。
因此改为在容器内调用该端点的同一组合（`aggregate_status()` → `public_llm_status()`）：

```
router_enabled = True                     # LLM_ROUTER_ENABLED 出厂默认 true，容器里走路由
registry_file  = config/llm_registry.json
db_path        = data/conversations.db    # 与 ConversationStore 同 env 源
aggregate keys = ['aborted_rate','breaker','fallback_rate','p95_latency_ms','providers','requests_5m','success_rate']
public keys    = 上面 7 枚 + 'status'
whitelist size = 13
providers      = {'ollama': {'healthy': True}}
breaker        = {'ollama': {'state': 'closed'}}
ledger rows    = []
```

要点：
- **D4 成立**：`providers.*.healthy` 只来自 probe（`ollama`  healthy=True），熔断态单列 `breaker`，
  两键互不渗透。
- **白名单逐枚**：`PUBLIC_LLM_STATUS_KEYS` 13 枚，出口块里没有未登记键外泄（前缀放行=0）。
- 账本 0 行：容器内是干净部署态，符合预期（`init_usage_db()` 建表但无写入）。

## 3. 本轮**没有**做的事（如实）

- 没打模型：没做真实问答/生成（`phi3:mini` 冷加载会重演 P0 时的内存压力，且真机生成证据已由
  `REAL-LLM-FAILOVER-001` 交过）。
- 没拿管理员凭据去 curl 受权限保护的端点（凭据属你；401 本身就是正确结论）。
- 没做前端构建复验（V2.3 前端零改动，`llm` 块是 additive；前端模型控制台归 V2.6）。
- 没重启别的项目的容器（见 `container-restore-log.md` 的最小影响矩阵）。
