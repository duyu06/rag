# yaoke Windows 部署

推荐环境：Windows 10/11 + Docker Desktop + Ollama + PowerShell。

## 一条命令部署

在仓库根目录执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\deploy.ps1
```

脚本默认完成：

1. 检查 Docker Engine / Docker Compose / Ollama / Python
2. 检查 `localhost:11434` Ollama API
3. 缺少 `backend/.env` 时从 `.env.example` 自动创建，并生成随机 JWT secret
4. 检查 `OLLAMA_MODEL`，缺少时自动 `ollama pull`
5. `docker compose up -d --build --remove-orphans`
6. 等待 Qdrant / Backend / Frontend 健康
7. 执行 `check_demo.py`
8. 初始化 20 份 Demo 文档
9. 执行 Retrieval/RBAC smoke
10. 执行真实 Ornith Agent smoke

基础部署通过时最后会输出：

```text
yaoke deployment: PASS
Web:            http://localhost:3000
Swagger:        http://localhost:8001/docs
Qdrant:         http://localhost:6333/dashboard
Agent Debugger: http://localhost:3000/admin/agent
```

## 联网功能一起验收

公共 DDGS 受当前网络环境影响，因此默认不作为基础部署硬门槛。

要同时测试 Web Search：

```powershell
.\scripts\deploy.ps1 -Web
```

这会额外执行：

```text
python scripts/agent_smoke.py --agent --web
```

## 常用参数

```powershell
# 已经 build 过，只重启/验收
.\scripts\deploy.ps1 -SkipBuild

# 不自动下载 Ollama 模型
.\scripts\deploy.ps1 -SkipModelPull

# 已经初始化过 Demo 数据
.\scripts\deploy.ps1 -SkipDemoInit

# 只启动，不运行 smoke tests
.\scripts\deploy.ps1 -SkipSmoke

# 部署成功后自动打开浏览器
.\scripts\deploy.ps1 -OpenBrowser

# 慢机器延长启动等待到 10 分钟
.\scripts\deploy.ps1 -StartupTimeoutSeconds 600
```

参数可以组合，例如：

```powershell
.\scripts\deploy.ps1 -SkipBuild -SkipDemoInit -Web -OpenBrowser
```

## 首次部署注意事项

### 1. Ollama 必须运行在 Windows 宿主机

宿主机：

```text
http://localhost:11434
```

Docker Backend 会通过 Compose 自动使用：

```text
http://host.docker.internal:11434
```

不要把 Windows Ollama 放进当前 Compose，也不要把 `backend/.env` 手工改成 `http://qdrant:...` 之类地址。

### 2. 第一次 Demo 初始化可能明显更慢

首次真正入库会加载/下载：

```text
BAAI/bge-small-zh-v1.5
```

如果启用 Reranker，还可能加载：

```text
BAAI/bge-reranker-base
```

这不属于服务启动失败。

### 3. 数据不会因为普通重启被删除

脚本不会运行：

```text
docker compose down -v
```

Qdrant 使用 named volume，`backend/data` 使用宿主机目录。

## 部署失败时

脚本会自动打印：

```text
docker compose ps
backend 最后 120 行日志
frontend 最后 80 行日志
qdrant 最后 80 行日志
```

如果需要手工进一步排查：

```powershell
docker compose ps
docker compose logs --tail=200 backend
docker compose logs --tail=200 frontend
docker compose logs --tail=200 qdrant
ollama list
Invoke-RestMethod http://localhost:11434/api/tags
```

## 最终可演示验收标准

基础部署必须全部满足：

```text
Qdrant health                 PASS
Backend /api/ready            PASS
Frontend /                    PASS
Demo corpus                   20/20 ready
Vector/BM25/Hybrid retrieval  PASS
SALES/HR RBAC                 PASS
ornith-1.5:9b Agent           PASS
enterprise_search Tool Call   PASS
Citation / Trace              PASS
```

联网功能单独验收：

```text
web_search Tool Call          PASS
DDGS public results           PASS
Web Citation                  PASS
```

公网搜索失败时，应先区分是 DDGS/网络问题还是企业本地 RAG 问题，不应把两者混为一个故障。
