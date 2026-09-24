# 飞书权限桥接 `app/identity` —— 启用、语义口径、运维与 provider 接入

本目录把"飞书里这个人是谁"翻译成"本系统里这个账号能做什么、能看到哪些知识库"。
默认**全关**：`feishu_permissions_enabled=false` 时本包一行代码都不执行，行为与接入前逐字相同。

设计背景见 `docs/FEISHU_PERMISSION_BRIDGE_DESIGN.md`；本文件是**运维与接入的操作口径**（怎么做、做完什么结果）。

文件地图：

| 文件 | 职责 |
| --- | --- |
| `__init__.py` | 唯一对外入口：`resolve_for_user()`（每请求）、`warmup()`（启动门闸）、`get_resolver()` / `reset_resolver()`（装配与缓存复位） |
| `base.py` | 数据模型：`ExternalIdentity` / `FeishuGrant` / 规则四件套（`RuleMatch`、`RuleGrant`、`FeishuRule`、`FeishuRuleSet`） |
| `feishu_client.py` | 飞书 OpenAPI 客户端（tenant token、分页（每接口最多 50 页的安全上限）、异常一律收口成 `FeishuAPIError`） |
| `mapper.py` | `load_rule_set()`（加载期校验）与 `match_identity()`（命中合并） |
| `resolver.py` | 进程内 TTL 缓存 + 失败收紧链 + 降级审计 |

---

## 1. 启用五步

### 第 1 步：配环境变量（`.env`，键名大小写不敏感）

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `FEISHU_PERMISSIONS_ENABLED` | `false` | 总开关。`false` 时后面四个键全部无意义 |
| `FEISHU_APP_ID` | 空 | 飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | 空 | App Secret（`SecretStr`：不落日志、不进响应，`get_secret_value()` 才取到明文） |
| `FEISHU_BASE_URL` | `https://open.feishu.cn` | 私有化部署改这里 |
| `FEISHU_RULES_FILE` | `config/feishu_permissions.json` | 规则文件路径，**相对后端进程 CWD**（本地是 `backend/`，容器里是 `/app/`） |

三个可选调参键：`FEISHU_TIMEOUT_SECONDS`（单次请求超时，默认 3s，失败不自动重试）、
`FEISHU_CACHE_TTL_SECONDS`（授予新鲜期，默认 900s）、`FEISHU_CACHE_STALE_SECONDS`
（旧授予还能沿用的上限，默认 86400s）。
故障期降级产物的复用窗口是常量 `FAILURE_CACHE_SECONDS = 60`，**故意不是配置键**（护栏，不是策略参数）。

飞书应用需要的权限：读取通讯录用户与部门、读取机器人所在群及其成员。

### 第 2 步：准备规则文件 `backend/config/feishu_permissions.json`

```json
{
  "rules": [
    {
      "match": { "department_names": ["人力资源"] },
      "grant": { "access_role": "user", "knowledge_base_ids": ["kb_public", "kb_hr"] }
    },
    {
      "match": { "chat_names": ["知识库管理员群"] },
      "grant": { "access_role": "admin", "knowledge_base_ids": ["*"] }
    }
  ]
}
```

`match` 四个键（`department_ids` / `department_names` / `chat_ids` / `chat_names`）**同条内是"与"**，
每个键内部是"或"（列表里有任一元素命中即可）；`grant` 两个键（`access_role` / `knowledge_base_ids`）任缺其一即"这项不授予"。
`knowledge_base_ids` 只认 `app/knowledge.py:KNOWLEDGE_BASES` 里注册过的 id，未知 id 在交集时被丢弃（不会变成可见范围）。

### 第 3 步：给要接管的本地账号配 `feishu_open_id`

`app/auth.py` 的 `USERS` 里，每个账号加一行 `"feishu_open_id": "ou_xxxxxxxxxxxxx"`
（在飞书通讯录里按姓名/邮箱查该员工的 open_id）。**没加这个字段的账号永远走本地语义，系统也不会为它发一次请求**——
这就是"逐个账号灰度上线"的开关，不必一次全量。

### 第 4 步：重启后端

启动时 `app/main.py` 的 lifespan 会调一次 `identity.warmup()`：装配 resolver 并把规则文件加载一遍。
开关为真且规则文件缺失 / JSON 坏 / 有空 `match` / 有未知键 → **进程直接启动失败**，错误在启动日志最前面（fail-fast）。
开关为假时 `warmup()` 立刻 return，零文件读取、零装配、零外呼。

### 第 5 步：验证

```bash
# 1) 登录该账号，确认 access_role 已被授予接管（响应里**没有** grant 键，见 §2.5）
curl -s -X POST localhost:8001/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"viewer","password":"***"}' | jq '.user'

# 2) 用拿到的 token 看知识范围是否等于授予的库集合
curl -s localhost:8001/api/knowledge-bases -H "Authorization: Bearer $TOKEN" | jq -r '.knowledge_bases[].id'

# 3) 越权请求应是 403 + 一行 ACCESS/DENIED 审计
curl -s localhost:8001/api/stats?knowledge_base_id=kb_product -H "Authorization: Bearer $TOKEN"
# {"detail":"当前账号无权访问该知识库"}

# 4) 降级/拒绝审计（audit:read 权限）；也可直接看落盘文件
curl -s "localhost:8001/api/audit?limit=50" -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.events[:5]'
tail -n 20 backend/data/audit.jsonl      # action=FEISHU_PERMISSION status=DEGRADED 等
```

期望结果：授予的角色/库集合接管了本地 `ROLE_ACCESS`；被授予范围之外的库返回 403；
把飞书 App Secret 改错再请求一次，应答范围收成分降级授予（见 §2.4）并留一行 `DEGRADED` 审计。

---

## 2. 语义口径（判定只有一个权威）

### 2.1 命中与合并：角色取高、库取并集、`"*"` 是全库

一次解析可能命中多条规则，合并规则固定：

- **平台角色取高**：`admin > user > viewer`（`base.ROLE_RANK`）。命中 `user` 与 `admin` 两条 → `admin`。
- **知识库白名单取并集**：所有命中规则的 `knowledge_base_ids` 合并去重；任一条含 `"*"` →
  `all_knowledge_bases=True`，输出为 `KNOWLEDGE_BASES` 的**全部**库（`"*"` 本身不会留在白名单里）。
- 合并阶段**不做任何收紧**——收紧只发生在失败回退（§2.4）。

### 2.2 加载期就拒掉的两种规则文件

`load_rule_set()` 在启动门闸里执行，以下两种直接 `ValueError`（进程起不来）：

1. **空 `match`**：`{"match": {}}` 等价于"向全员授予"，是配置事故而不是宽松规则。
2. **未知键**：四个规则模型都是 `model_config = ConfigDict(extra="forbid")`。
   拼错的键（`access_role` 写成 `access_roles`、`department_ids` 写成 `department_id`、
   与 `match`/`grant` 平级多写一个 `when`）不会被静默忽略——静默忽略的结果是
   "这条规则看起来命中了却什么都没授予"，从响应上完全看不出来。
   报错文案会指名文件路径与 offending 键。

> 只有**规则模型**是 `extra="forbid"`。`ExternalIdentity` / `FeishuGrant` 不是：它们承接飞书
> 返回的松散结构与内部缓存条目，多带字段是常态，收紧会把降级变成异常。

### 2.3 三态与"空授予 = 本地语义"

| 情况 | `resolve_for_user` 返回 | 平台角色 / 知识范围 | 审计 |
| --- | --- | --- | --- |
| 开关关闭 | `None` | 本地语义（`ROLE_ACCESS` + `access_role_for(role)`） | 无 |
| 账号无 `feishu_open_id`（或为空） | `None`，**不发请求** | 本地语义 | 无 |
| 飞书正常返回但规则**零命中** | 空授予（`access_role=None`、库为空、`degraded=False`） | 本地语义（既不收紧也不放大） | 无 |
| 命中≥一条 | 命中授予 | 以授予为权威 | 无 |

空授予不等于"没有授予"这个事实——它是一次**成功解析**，因此绝不写进 60s 故障缓存、也不算降级。
判定"这份授予是否接管范围"只住在一个地方：`FeishuGrant.is_authoritative()`。

### 2.4 失败收紧链（任何路径都不放宽权限）

抓取失败（超时 / 非 2xx / 业务码非 0 / token 拿不到 / **分页超过 50 页安全上限**）时，按顺序收紧：

1. 旧条目仍在 `FEISHU_CACHE_STALE_SECONDS` 内 → **沿用旧授予并标 `degraded=True`**（范围与角色不放大）。
2. 没有可用旧条目 → **本地角色（`access_role=None`）+ 仅公共知识库**（`public_kb_ids()`）。

两条都写一行 `FEISHU_PERMISSION / DEGRADED` 审计，detail 是 redact 后的失败原因。
降级产物同样进缓存，但只活 60s（`FAILURE_CACHE_SECONDS`）：故障期不是"每请求一次外呼 + 每请求一行审计"，
恢复后最多隔一个失败窗口就重试成功。

### 2.5 授予不进响应，鉴权不信 JWT

- `CurrentUser.grant` 声明为 `Field(default=None, exclude=True)`：**只影响序列化**，
  `/api/auth/login` 与 `/api/auth/me` 的响应体键集合固定为
  `username / display_name / role / access_role / permissions`，不含 `grant`。
  前端只读 `access_role` 与 `permissions`（它们本就是授予的投影），外部身份结构体不跨 API 边界。
  `user.grant` 在服务端内部照旧可读，`knowledge.allowed_for(user)` 等判定不受影响。
- token 里的 `role` / `access_role` claim **仅为兼容展示用，鉴权不读该字段**：
  `require_user` 每请求按 `USERS` 表重解析授予。伪造 claim 提不了权（契约测试有这一例）。
- 403 文案是对外契约，两处、各一种，不得漂成第三样：
  缺能力 → `当前账号缺少权限：<permission>`（配套审计 `AUTHORIZATION / DENIED`，
  detail 为 `missing_permission=<permission>`）；
  越知识范围 → `当前账号无权访问该知识库`，零可见 → `当前账号无知识库访问权限`
  （配套审计 `ACCESS / DENIED`）。

### 2.6 "只给角色、不给库" = 零可见（不是全库）

`grant: {"access_role": "admin"}` 这种写法给出的是"平台能力 = admin、知识范围 = 无"。
`allowed_for()` 返回空列表，`/api/query`、`/api/query/stream`、`/api/retrieval/debug`、`/api/stats`、
`/api/documents`、`/api/search`、`/api/chunks`、`/api/evaluation/run`、agent 工具 `enterprise_search`
等**所有取数入口**一律 403（`当前账号无知识库访问权限`）。这是 **fail closed 的有意设计**（早期版本在此处把空列表当成"没白名单"
而放行全库，已在评审 C1 修复并在向量层、缓存键两处加了纵深）。

要给 admin 全库，请显式写 `knowledge_base_ids: ["*"]`。对运维的反直觉之处就在这句话上：**角色与库范围是两条独立轴**。

一个容易漏的入口：`/api/evaluation/run` 的 `knowledge_base_id` **来自 `eval_dataset.json` 而不是请求参数**，
看起来"用户没传库"就不判范围。它同样把库内容读进响应（`cases[].top_files`），所以是取数入口：
执行前先对数据集里出现过的每个 distinct 库过一次用户范围（`main._allowed_ids`），
**全部通过才开始跑评测**——收窄授予的账号得到 403 + 一行 `ACCESS / DENIED`，不会先跑出半份报告。

---

## 3. 运维提示

- **改绑定或改规则文件后必须让进程重新装配**：规则与 resolver 是进程内单例 + 进程内缓存，
  **没有配置热更新**。三种做法任选：重启后端（推荐，也会重走启动门闸）；调 `app.identity.reset_resolver()`
  （下一次请求懒装配，**不会**触发门闸校验）；或按账号粒度等 `FEISHU_CACHE_TTL_SECONDS` 自然过期。
  注意 `reset_resolver()` 只清装配与缓存，`USERS` 里 `feishu_open_id` 的改动仍需重启进程才生效（那是源码里的演示账号表）。
- **降级审计是分窗口的，不是每请求**：同一用户在 60s 失败窗口内只留 1 行 `FEISHU_PERMISSION / DEGRADED`。
  因此"审计里 DEGRADED 行数 ÷ 60s"≈ 受影响用户数，不要按请求量估计；反过来，
  长时间故障会稳定地每用户每分钟一行，不会被刷屏。
- **冷路径开销按演示规模设计**：一次冷解析要发 `fetch_user` + 每个部门一次 `department_name`（部门名**无缓存**）
  + 规则里出现的每个群一次 `list_chats` / `chat_member_ids` 确认成员；且**没有 single-flight**——
  同一用户 TTL 到期的瞬间，并发请求会各自打一遍飞书。演示/小团队规模（几十到几百账号、TTL 900s）够用；
  要上更大规模，先补部门名缓存与 per-user 请求合并，再调 TTL。
- **容器里规则文件要真的存在**：`backend/Dockerfile` 只 `COPY app`，`config/` 既没进镜像也没在
  `docker-compose.yml` 里挂载。开了开关又用默认 `FEISHU_RULES_FILE`，容器会**启动失败**（门闸）。
  接入时加 `COPY config ./config`，或把规则文件挂到 `/app/config/feishu_permissions.json` 并用
  `FEISHU_RULES_FILE` 指准路径。
- **规则文件是敏感配置**：里面的部门名/群名会泄漏组织结构。它与 App Secret 都不进响应、不落审计
  （`app/security.py:redact_text` 会把 `Bearer …` 与 TypeSafe key 形态抹掉）。
- **关掉开关就是彻底回到今天**：`FEISHU_PERMISSIONS_ENABLED=false` + 重启，本包不再被调用，无需删 `feishu_open_id`。

---

## 4. 新增一个外部身份 provider（OIDC / 企业微信）四步

本包只承诺一件事：把外部身份翻译成 `ExternalIdentity`，其余（合并、缓存、降级、审计、auth 接线）都与 provider 无关。
接入新源按下面四步，**不要**新增第二条判定链。

1. **实现同构的 fetch 方法**：新建 `app/identity/<provider>_client.py`，提供与 `FeishuClient` 同构的四个方法——
   `fetch_user(uid) -> dict`（含 `department_ids`）、`department_name(department_id) -> str`、
   `list_chats() -> list[ChatInfo]`、`chat_member_ids(chat_id) -> list[str]`。
   异常必须**在客户端边界收口成一个 `RuntimeError` 子类**（对照 `FeishuAPIError`），
   否则 `resolver.resolve()` 的 `except (FeishuAPIError, RuntimeError)` 接不住，降级链会变成 500。
   分页游标一律按 `str(value or "")` 读（外部接口会把空游标显式写成 `null`，`str(None)` 是真值 `"None"`），
   且每个分页接口都要有页数安全上限（对照 `_MAX_PAGES`）——超限抛回同一个 `RuntimeError` 子类。
   HTTP 层封装成可注入 transport，单测用假实现（参考 `feishu_client.py` + `httpx.MockTransport`）。
2. **在 `resolve_for_user` / `get_resolver` 处选择 provider**：`app/identity/__init__.py` 仍是唯一装配缝——
   按 `settings` 决定注入哪个 client，保持"一个 `_resolver` 单例 + 一个 `warmup()` 门闸"。
   本地账号表里的桥接字段也要分源（例如新增 `<provider>_user_id`），
   并在 `resolve_for_user()` 里按同一三态判断（无桥接字段 = 本地语义，零请求）。
3. **让规则能判别 provider**：给 `FeishuRule` 加判别字段（如 `provider: Literal["feishu", "wecom"] = "feishu"`），
   `match_identity()` 先按 provider 过滤再匹配；也可以直接给每个 provider 一份 `*_rules_file` 键（更简单，
   代价是跨源策略要自己保证不冲突）。改了模型就必须同步 `backend/config/` 下所有示例规则——
   它们是 `extra="forbid"` 的，新键没写进模型（或旧文件没加键）会在启动门闸上直接失败。
4. **补同类 contract 测试**：在 `tests/test_feishu_identity_contract.py` 里照现有分组加同构用例，
   至少覆盖这五类，缺一项就等于新源没有回归锚：
   规则加载（含未知键 / 空 match 拒载）、命中合并（取高 / 并集 / `"*"`）、
   启动门闸（`enabled` + 坏文件 → `warmup()` 抛、`disabled` → 零操作）、
   开关三态的端到端链（`resolve_for_user` → `CurrentUser` → `allowed_for` / `resolve_for`）、
   降级（只给公共库 + 恰好一行 `DEGRADED`）。

`ExternalIdentity` 的字段语义（部门 id / 部门名 / 群 id / 群名）是 provider 无关的公共词汇。
新源若不天然具备"群"这一维，返回空列表即可——`resolver._visible_chats()` 对空白名单是零外呼早退，不会白打请求。

---

## 5. 明确不做（YAGNI）

不做飞书 OAuth 登录跳转（只读通讯录做匹配）、不做权限变更事件订阅（靠 TTL 收敛）、
不做后台同步快照表、不做多身份源并存仲裁（同一账号只由一个 provider 接管）。
角色与库范围的**授予策略**仍然只写在规则文件里，不做管理界面。
