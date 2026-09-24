# 容器恢复对账 — 2026-09-24（用户口径：最小影响，不批量恢复）

背景：本轮 RAG 验收前停过 11 个容器（见 `container-stop-log.txt`），随后 Docker 引擎故障，
`wsl --shutdown` + 重启 Docker Desktop 恢复（server 29.7.2，23:05 左右就绪）。
**注意：引擎恢复 ≠ 业务环境恢复**——WSL 重启把另两个项目的全部容器一并停掉了。

## 依赖判定（本机实测，不是推测）

`grep -rn -i "otel|opentelemetry|prometheus|grafana|temporal|minio|boto3|s3\." backend/app/ backend/requirements*.txt docker-compose.yml`
⇒ **零命中**。`docker-compose.yml` 的 services 只有 `qdrant`、`backend`、`frontend`。
V2.3 的 trace 落盘面是 `app/agent_trace.save_trace()` 写的 **JSONL 文件**，
metrics 出口是进程内 stats + `/api/system/status`（D3/D4），
⇒ **OTel Collector / Prometheus / Grafana / Temporal / MinIO 都不是本轮验收的依赖，全部不恢复。**

## 执行矩阵（container / reason / compose project / timestamp / result）

| container | reason | compose project | timestamp | result |
| --- | --- | --- | --- | --- |
| `rag-qdrant-1` | RAG 检索硬依赖（BGE 向量 + 稀疏索引） | `rag` | 23:06 | 已 `docker compose up -d qdrant`（待健康复核） |
| `rag-backend-1` | V2.3 验收主体（router 接线 + warmup 冒烟） | `rag` | 构建中 | 镜像重建中（`t11-docker-build4.log`，pip 层）；完成后 `up -d backend` |
| `aclc-otel-collector-1` | — | `aclc` | — | **不恢复**：非本轮依赖，交回 aclc 会话 |
| `aclc-prometheus-1` | — | `aclc` | — | **不恢复**：同上 |
| `aclc-temporal-1` | — | `aclc` | — | **不恢复**：与 Model Router 验收无关 |
| `aclc-object-storage-1` | — | `aclc` | — | **不恢复**：无 fixture 依赖 |
| `ai-commerce-prometheus-1` | — | `ai-commerce` | — | **不恢复**：交回该项目会话 |
| `ai-commerce-grafana-1` | — | `ai-commerce` | — | **不恢复**：UI 观测非硬依赖 |
| `ai-commerce-otel-collector-1` | — | `ai-commerce` | — | **不恢复**：同上 |
| `ai-commerce-temporal-1` / `-temporal-ui-1` | — | `ai-commerce` | — | **不恢复**：同上 |
| `ai-commerce-object-storage-1` | — | `ai-commerce` | — | **不恢复**：同上 |
| `yaoke-minio` | — | yaoke（PrismPix） | — | **不恢复**：PrismPix 与本轮无关 |

## 事实修正：不是我起的，是 Docker Desktop 按 restart policy 自己带回来的

23:38 复查 `docker ps`：**`aclc-api-1`、`aclc-postgres-1`、`aclc-redis-1`、`yaoke-postgres`、`yaoke-redis`
已经 Up**（`aclc-api-1` 当时还在 `health: starting`）。我没有对它们执行任何 `start`/`up`——
它们带 `restart: unless-stopped/always` 类策略，引擎一恢复就自愈。
⇒ 「其他项目一律不动」这条我只在**动作层面**做到了；**状态层面**这两个项目的有状态容器已经自己回来了，
需要它们会话自己确认迁移/健康状态，别把它当成"已被我恢复"或"仍停着"。
仍保持停止的：`aclc-temporal-1`、`aclc-object-storage-1`、`aclc-prometheus-1`、
`ai-commerce-*`（含 api/web/postgres/redis，无自愈）、`ai-commerce` 的观测栈、`yaoke-minio`、
`rag-backend-1`（`Exited (137)` = 被 OOM 杀，正等 V2.3 新镜像重建后拉起）。

## 被 WSL 重启顺带停掉、但**属于其他会话**、我不动的容器

`aclc-api-1`、`aclc-postgres-1`、`aclc-redis-1`、`ai-commerce-api-1`、`ai-commerce-web-1`、
`ai-commerce-postgres-1`、`ai-commerce-redis-1`、`yaoke-postgres`、`yaoke-redis`
⇒ 由各自项目会话按自己的 compose / migration 状态恢复（它们可能有进行中的迁移，跨项目批量 `up -d` 会污染验收现场）。

## 停前基线（用于对账，摘自 `container-stop-log.txt` 与当时 `docker ps`）

停止前运行中：`aclc-api-1`、`aclc-postgres-1`、`aclc-redis-1`、`aclc-temporal-1`、
`aclc-object-storage-1`、`aclc-prometheus-1`、`ai-commerce-api-1`、`ai-commerce-web-1`、
`ai-commerce-postgres-1`、`ai-commerce-redis-1`、`ai-commerce-temporal-1`、`ai-commerce-temporal-ui-1`、
`ai-commerce-grafana-1`、`ai-commerce-prometheus-1`、`ai-commerce-otel-collector-1`、
`ai-commerce-object-storage-1`、`yaoke-postgres`、`yaoke-redis`、`yaoke-minio`、
`rag-backend-1`、`rag-qdrant-1`。
