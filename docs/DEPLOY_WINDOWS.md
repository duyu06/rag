# yaoke P1.5 · Windows 部署

推荐环境：Windows 11 + Docker Desktop + Ollama + Python 3。

## 一键部署

在仓库根目录使用 PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\deploy.ps1
```

脚本会按顺序执行：

1. 检查 Docker Desktop / Docker Compose / Ollama / Python。
2. 不存在 `backend/.env` 时从 `.env.example` 创建。
3. 如果 JWT secret 仍是 Demo 默认值，自动生成随机本地 secret。
4. 检查并按需拉取 `ornith-1.5:9b`。
5. 通过 Ollama `/api/chat` 真正加载一次 Ornith；模型 blob 损坏会在 Docker 启动前直接失败。
6. `docker compose up -d --build`。
7. 等待 Backend 与 Frontend ready。
8. 执行 `release_smoke.py` 基础验收。
9. 初始化 20 份 Demo 数据；已 20/20 ready 时自动跳过重建。
10. 执行真实 Local Fast Path：Ornith → Retrieval → Qdrant → Citation → Trace。

成功后访问：

```text
Web      http://localhost:3000
Swagger  http://localhost:8001/docs
Qdrant   http://localhost:6333/dashboard
Debugger http://localhost:3000/admin/agent
```

## 常用参数

只重启容器、不重新 build：

```powershell
.\scripts\deploy.ps1 -NoBuild
```

不初始化 Demo：

```powershell
.\scripts\deploy.ps1 -SkipDemoInit
```

只做基础部署，不运行真实 Agent smoke：

```powershell
.\scripts\deploy.ps1 -SkipAgentSmoke
```

额外验证 DDGS 公网 Web Search：

```powershell
.\scripts\deploy.ps1 -Web
```

模型已经明确安装、不允许脚本自动 pull：

```powershell
.\scripts\deploy.ps1 -SkipModelPull
```

## 数据与模型缓存

Docker Compose 持久化：

```text
qdrant_data                  Qdrant 向量数据
hf_cache                     Hugging Face / BGE 模型缓存
./backend/data               Conversation / Audit / Agent Trace
```

普通 `docker compose down` 不会删除 named volumes。

只有执行：

```powershell
docker compose down -v
```

才会删除 Qdrant 与 Hugging Face named volumes。部署/面试机器上不要随意使用 `-v`。

## 当前固定版本

部署 Compose 与 CI 使用：

```text
Qdrant 1.19.1
Python 3.12 backend image
Node.js 22 frontend image
Ornith ornith-1.5:9b
```

固定 Qdrant 版本是为了避免 `latest` 在面试或重新部署当天发生非预期升级。

## Ornith 500 unable to load model

如果部署脚本在“Loading ornith-1.5:9b”阶段失败，先不要排查 Docker。直接在 PowerShell 执行：

```powershell
ollama --version
ollama list
ollama ps
ollama run ornith-1.5:9b
```

仍出现 `500 Internal Server Error: unable to load model` 时，优先升级 Ollama，然后重新拉取该模型：

```powershell
ollama rm ornith-1.5:9b
ollama pull ornith-1.5:9b
ollama run ornith-1.5:9b
```

不要直接手工删除随机 blob；Ollama blob 可能被多个模型共用。

## 诊断

容器状态：

```powershell
docker compose ps
```

Backend：

```powershell
docker compose logs --tail 200 backend
```

Qdrant：

```powershell
docker compose logs --tail 200 qdrant
```

Frontend：

```powershell
docker compose logs --tail 200 frontend
```

真实发布 smoke：

```powershell
python scripts/release_smoke.py --agent
```

检索性能：

```powershell
python scripts/benchmark_retrieval.py --mode hybrid
```

部署通过的最低标准：

```text
Backend ready
Frontend ready
Demo 20/20 ready
release_smoke.py PASS
release_smoke.py --agent PASS
```

公网 Web Search 可以作为附加验收，不应成为本地企业知识库可用性的阻断条件。
