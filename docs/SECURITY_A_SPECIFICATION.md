# SEC-A · 安全速赢规格（口令存储 / 认证加固 / secret 卫生）

| 项 | 值 |
| --- | --- |
| 文档 | `docs/SECURITY_A_SPECIFICATION.md` |
| 状态 | **SPEC 冻结（2026-09-25）**：第二轮 7+2 项修正已落（§20.1），第三轮回写 §20.2 已获用户认可。实现计划见 `docs/SECURITY_A_PLAN.md`，执行方式=SDD 逐任务。本文档与计划不伴随代码改动 |
| 日期 | 2026-09-25 |
| 上游 | `docs/ENTERPRISE_ACCEPTANCE_GAP_ANALYSIS.md`（G8 的认证与密钥部分） |
| 前置 | Model Router V2.3 RC `5ba5f20e…`，tag `model-router-v2.3-rc1`（**本规格不触碰、不 amend、不移 tag**） |
| 范围裁定 | G7 摄取侧注入兜底 → 子规格 B；G14 `request_id` / G18 prompt 版本 → 子规格 C；V2.4 延期清单与本规格不相交 |

---

## 1. 目的、范围、不做什么

**目的**：消除本项目在企业安全验收中的一票否决项——无盐 SHA-256 口令哈希、源码内的可枚举凭据材料、无失败语义的认证面、无生命周期管理的令牌、以及"密钥卫生靠人盯"。

**做**（三块，全部收口）：

1. 口令存储与迁移：Argon2id、身份与凭据分家、渐进重哈希 + 强制改密收敛、稳态零遗留可判定。
2. 认证面加固：失败语义、计时与枚举、两层节流/锁定、令牌生命周期、改密与重置路径。
3. secret 卫生：仓库密钥扫描入门禁、env/config 边界、日志与遥测脱敏分层、生产形态 fail-closed。

**不做**（明确排除，避免范围漂移）：

- 不接企业 IdP / OIDC / SAML；不做 MFA、设备策略。
- 不做多租户（G6，子规格 C）。
- 不做 HTTP `logout` 端点与 jti 撤销表——令牌失效由 `credentials_version` 承担（§7.5），二者不等价但足以覆盖"改密/停用即刻废 token"这一验收要求。
- 不重写 Git 历史（§3 T6 的裁定）。
- 不改任何对外响应的既有键集合（§11 声明的 2 枚 additive 键除外）。

---

## 2. 事实基线（2026-09-25 只读盘点，全部经本会话实测）

| 事实 | 证据 |
| --- | --- |
| 口令哈希 = 无盐 SHA-256 小写 hex，全仓唯一定义、唯一调用 | `backend/app/auth.py:173`（`_password_digest`）、`:181`（`hmac.compare_digest`） |
| 5 枚账号 hash 作为源码字面量存在，且已推送 `origin/main` | `backend/app/auth.py:71-103` |
| 5 枚 digest 字典一次命中：`admin123 / sales123 / hr123 / user123 / viewer123` | 本会话脚本复现；明文同时是 `tests/test_rbac_contract.py:94` 等测试的字面量 |
| 口令**没有**任何生成 / 重置 / 修改 / 建号路径 | 全仓 `password` 命中面：仅 `auth.py`、`main.py:88`（登录模型字段）、`web_safety.py:21`（URL userinfo 校验） |
| 校验唯一入口 = `/api/auth/login` | `backend/app/main.py:238-255` |
| 无持久用户存储 | `data/conversations.db` 实测表：`conversations / messages / message_sources / sqlite_sequence / llm_request_logs` |
| Argon2id 与 bcrypt **发布容器内均不可用** | `docker exec rag-backend-1`：`argon2 MISSING`、`bcrypt MISSING`、`nacl MISSING`；宿主 bcrypt 5.0.0 系 `chromadb` 的传递依赖（`pip show` 的 `Required-by`），非本项目声明 |
| 令牌 8 小时、无刷新/登出/撤销 | `auth.py:192-206`（`exp = iat + jwt_expire_hours`）、`config.py:156`（默认 8）；全仓 `logout\|revoke\|jti\|blacklist` 零命中 |
| `require_user` 泄露账号存在性 | `auth.py:230` 单列文案「账号不存在」 |
| 节流/锁定为零 | 全仓 `rate_limit\|slowapi\|lockout\|backoff` 零命中；`docs/SECURITY_REVIEW.md:26` 自认；compose 前置无 nginx（全仓 `limit_req` 零命中） |
| CORS 全开 | `main.py:77-83`：`allow_origins=["*"]`、`allow_credentials=False` |
| 脱敏只认形态，不认键名 | `app/security.py:13-14`（`apikey_…`、`Bearer …`）、`:153-172` |
| `redact_secrets()` 调用点：`app/security.py` 之外 **17 处**，其中 **7 处**是响应面直接 `return redact_secrets(...)` | 7 处直返面（2026-09-26 实测行号，**会随实现漂动**；判据是 §9.3 那枚 AST 等式而不是下面的坐标）：`agent.py:330/1048`、`conversation_agent.py:533/602`、`conversation_store.py:175`、`main.py:738/847`；其余 10 处为赋值/传参形态。`agent_trace.py:91` 原在名单内，Task 9 按 §9.3 把该落盘面切到 `redact_for_persistence()` ⇒ 已不是 `redact_secrets` 落点（AST 量法见 §20.4） |
| 默认 JWT secret 是会真的跑起来的字面量 | `config.py:155`；compose 走 `env_file: ./backend/.env` 无守卫，仅 `scripts/deploy.ps1:95-112` 会替换；本机 `.env` 实测已设 64 字符值 |
| 既有断言把默认 secret 钉为必须存在 | `tests/test_branding_contract.py:32` |
| CI 无安全 job | `.github/workflows/ci.yml`：`backend-contracts / backend-integration / backend-quality / frontend-build`，无 pip-audit / gitleaks / bandit / typecheck |
| tracked 文件无真实凭据入库 | 本会话全字面量扫描命中面 = `.env.example` 占位符 + 测试假值；`.gitignore:6` 覆盖 `backend/.env` |
| 登录响应键集合钉的准确形状 | 顶层 `{access_token, token_type, user}` 无等值断言（既有 8 处调用点只读 `["access_token"]`）；**但** `test_feishu_identity_contract.py:1777/1778` 对嵌套的 `login.json()["user"]` 与 `me.json()` 各有一枚 `assertEqual(set(...))` 等值钉（`_LOCAL_KEYS`）⇒ `/me` 加键必须同步扩那枚期望集合，见 §11 与 §20.3 |
| 两个 app 入口共用同一实例与同一 lifespan | `main_agent.py:9`（`from app.main import app`）、`app/main.py` 模块文档自陈「`main_agent.py` 复用同一个 app 实例」（行号会漂 ⇒ 认文档串，不认坐标，见 §20.4） |
| 容器是单进程 uvicorn | `backend/Dockerfile` 末行 `CMD ["uvicorn","app.main_agent:app",…]`，无 `--workers` |

**复核更正**：本文档第 4 段口头评审时曾称脱敏调用点 51 处，那是一次被截断的合并 grep 行数；当时改口为 28（响应面 8）**仍是文本 grep 口径**。实现期以 AST 量得：`app/security.py` 之外 **17 处**调用点，其中 **7 处**为响应面直接 `return`（详见 §20.4）。规格以 AST 口径为准；本项是**计量方法更正**，不是行为放宽——「`redact_secrets()` 语义与全部调用点一字不动」这条约束不变，判定由两枚**不同性质**的钉共同承担：`test_redact_secrets_semantics_are_unchanged`（行为探针）与 `test_the_four_persistence_faces_use_the_persistence_redactor`（AST 等式），详见 §20.4。

---

## 3. 威胁登记

| ID | 威胁 | 现状 | SEC-A 的对策 |
| --- | --- | --- | --- |
| T1 | 离线口令破解（无盐 SHA-256 + 高可猜口令） | 存在，且已实证 | Argon2id + 强度下限 + 稳态零遗留 |
| T2 | 源码/配置成为凭据材料源 | 存在（5 枚 digest 在源码） | 身份文件禁凭据字段（fail startup）；digest 只作一次性迁移输入 |
| T3 | 在线口令爆破 | 存在（零节流） | pre-hash 节流 + 持久账号锁定两层 |
| T4 | 账号枚举 | 存在（两条：文案分列、耗时差异） | 四态合一 + 哑校验 + "恰好一次同档 verify"的结构门（§7.3） |
| T5 | 改密/停用后旧令牌仍可用 | 存在（最长 8h） | `credentials_version` 每请求比对 |
| T6 | **Git 历史里的 5 枚 digest** | 存在，已推送远端 | **不重写历史**。风险通过废弃口令消解：稳态 `legacy_count=0` + 5 个旧口令永久失效。此为用户明确裁定，写在此处而非隐藏 |
| T7 | 凭据材料经遥测面外泄 | 部分（形态脱敏不认 `password` 键） | `redact_for_persistence()` 精确键名黑名单，且授权凭据库例外 |
| T8 | 弱档位 Argon2 参数在资源受限容器造成可用性/耗尽面 | 未知，需实测 | SECA-19 容器基准 + 并发上限闸门 + 禁止静默降档 |

---

## 4. 冻结不变量

三条措辞已经过用户裁定修正，不得回退到更弱的原始版本。

- **SEC-A-001** 任何新建口令（创建 / 改密 / 重置 / bootstrap）写入的算法**只能**是 `argon2id`。强度来自写路径取值不可达（§6.1），不来自"约定大家不传 legacy"。
- **SEC-A-002** 明文口令不得出现在：响应体、日志、审计、trace、`llm_request_logs`、任何配置文件、CLI 参数（`argv` 可被 `ps` 与 shell history 观察）。口令仅允许存在于进程内瞬时变量与 TLS 保护下的 POST body。
- **SEC-A-003** 迁移**不得使既有账号失去登录能力**。旧口令仍可完成一次登录；此后被强制改密门引导到新口令。
- **SEC-A-004**（收窄后的准确措辞）**迁移闭合后的稳态系统不得存在任何 active `legacy-sha256` credential**。legacy hash 只允许由受限 migration path 写入临时迁移状态；普通创建 / 改密 / bootstrap / 任何 API 写路径一律禁止产出该算法。判定 = `SELECT COUNT(*) FROM user_credentials WHERE algorithm='legacy-sha256'` **必须为 0**，且 `backend/app/`、`config/`、运行库三处扫描对那 5 枚 digest 为 0 命中。
- **SEC-A-005** 哈希运算集中于 `app/credentials.py` 一处，由 AST 扫描钉住"口令参与运算的 `hashlib` 命中面 == 豁免表"。业务代码不得自行哈希口令。
- **SEC-A-006** 本次升级**不得放松任何既有认证 / 权限 / 会话契约**。§16 列出全部被触碰的既有断言，并逐条说明为何是收紧或换真源。
- **SEC-A-007** 必须提供自动化回归 + 变异证据（§12、§13），"能登录"不构成验收。

派生不变量：

- **SEC-A-008** Argon2 部署档位**不可经 env 调整**。改档位 = 改代码常量 + 本规格 §19 的修订记录 + 重跑 SECA-19。理由：可运维调的参数 = 可被静默降档的安全强度。
- **SEC-A-009** 授权凭据库（`user_credentials`）与遥测持久化面（audit / trace / logs / `llm_request_logs`）是两个不同域，不得共用同一脱敏器（§9.3）。
- **SEC-A-010** 身份唯一真源是**身份声明文件集**（`config/users.json`，dev/test 形态再加 `config/users.demo.json`）；凭据状态唯一真源是 `user_credentials` 表。任何单元不得同时持有两者。企业形态下身份文件集**只含 `users.json`** ⇒ "不载入 demo 身份"是由**不加载该文件**实现的结构事实，不是运行时按用户名过滤（后者会让 demo 用户名成为代码里的第二真源）。

---

## 5. 架构与所有权

```
  config/users.json            （企业形态唯一身份源）
  config/users.demo.json       （仅 dev/test 形态加载，两个文件都禁含凭据字段）
            │
            ↓
     app/directory.py          身份 loader（结构上无口令字段）
            │
            ↓
     app/auth.py               编排者：节流 → 身份 → 凭据 → verify → 渐进重哈希 → 门 → token
            ↑
     app/user_store.py         凭据状态持久层（写函数签名不含 algorithm）
            │                          │
            ↓                          ↓
     app/credentials.py        SQLite: user_credentials
     （唯一哈希原语 + Argon2 档位常量 + 并发闸门）
            │
            ↓
        argon2-cffi
```

| 单元 | 职责 | 明确不做 |
| --- | --- | --- |
| `app/credentials.py`（新） | `hash_password` / `verify` / `needs_rehash` / `is_legacy` / 哑校验用 dummy hash / 并发上限闸门；**唯一**持有 Argon2 参数常量 | 不查库、不认识 username、不做失败语义 |
| `app/user_store.py`（新） | `user_credentials` 表的 `ensure_schema` 与读写；写函数**签名不含 algorithm 参数** | 不做 HTTP、不 import `hashlib` 做口令运算 |
| `app/directory.py`（新） | 载入并校验身份声明文件，提供身份只读视图与测试注入接缝；企业形态**只读** `config/users.json`，dev/test 形态额外合并 `config/users.demo.json` | 不存储口令；两个文件都禁含任何凭据字段 |
| `app/auth.py`（改造） | 编排：节流 → 身份 → 凭据 → verify → 渐进重哈希 → 门 → token；`CurrentUser` / RBAC 契约不变 | 不再 import `hashlib`；不再有 `USERS` 常量 |
| `app/security.py`（扩展） | 新增 `redact_for_persistence()`；`redact_secrets()` 语义与其全部调用点（AST 等式钉 17 处，§2/§20.4）**一字不动** | 不改既有响应面 |
| `app/main.py`（改造） | 登录腿时序、改密/重置端点、lifespan 第三道守卫、CORS env 化 | 不改既有响应键集合 |

**删除 `auth.USERS`，不留兼容视图**（已锁死）。读点迁移：`knowledge_os.py:560/564/567/703` → `directory` 的只读视图。理由：兼容字典会让 SEC-A-004 的"零 legacy"退化成"另一处也算数"，并让飞书身份、RBAC、凭据迁移三处重新分叉。

---

## 6. 数据模型

### 6.1 `user_credentials`（落 `data/conversations.db`）

```sql
CREATE TABLE IF NOT EXISTS user_credentials (
  username            TEXT PRIMARY KEY,
  algorithm           TEXT NOT NULL CHECK (algorithm IN ('argon2id','legacy-sha256')),
  password_hash       TEXT NOT NULL,
  credentials_version INTEGER NOT NULL DEFAULT 1,
  must_change         INTEGER NOT NULL DEFAULT 0,
  failed_attempts     INTEGER NOT NULL DEFAULT 0,
  locked_until        TEXT,
  updated_at          TEXT NOT NULL
);
```

- 表与 `conversations` 同库 ⇒ 自动继承 `tests/conftest.py` 已有的 `CONVERSATION_DB_PATH` 会话级重定向护栏（V2.3 测试污染生产库的直接教训）。SEC-A 必须有一枚测试证明凭据写盘不落生产库。
- `user_store` 的写函数不接受 `algorithm` 实参 ⇒ SEC-A-001 是"不可达"，不是"没传"。
- **列面测试（SECA-08）**：列名集合 MAY 含 `password_hash`；MUST NOT 含 `password` / `plaintext_password` / `raw_password` / 任何明文口令字段。

### 6.2 分派权威与交叉校验

`algorithm` 列是**唯一**分派依据，**不做字符串嗅探**。编码串前缀只作交叉校验：

- `algorithm='argon2id'` 而串不以 `$argon2id$` 开头 ⇒ 硬失败（配置错误，不猜、不降级、不 try-both）。
- `algorithm='legacy-sha256'` 而串不是 64 位 hex ⇒ 硬失败。

### 6.3 Argon2 部署档位与三层版本语义

存储值 = `argon2-cffi` 原样返回的 PHC 编码串，**不做任何自包装**。

```
profile = argon2.PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
→ $argon2id$v=19$m=19456,t=2,p=1$<salt b64>$<hash b64>
```

出处（已抓原文核对）：**19 MiB / t=2 / p=1 是 OWASP Password Storage Cheat Sheet 的 Argon2id 最低推荐档**（原文："a minimum configuration of 19 MiB of memory, an iteration count of 2, and 1 degree of parallelism"）。本规格**不引用 RFC 9106 作为该档位的出处**——RFC 9106 的两个推荐 profile 是 `m=2 GiB,t=1,p=4` 与 `m=64 MiB,t=3,p=4`，与本项目档位无关。

三层版本各管各的，不得混用：

| 概念 | 含义 | 载体 |
| --- | --- | --- |
| `algorithm` | 密码算法族（`argon2id` / `legacy-sha256`） | 表列 |
| `credentials_version` | **单账号凭据状态 epoch**（per-user authentication epoch）：任何需要废弃该账号既有 token 的凭据状态变化都递增。它**不是**数据库 schema version，**也不是** Argon2 policy version | 表列 + JWT claim `cv` |
| 编码串内 `v=19` / `m,t,p` | Argon2 **算法版本 0x13** 与**实际密码学参数事实** | 编码串自身 |

三条版本轴各自独立，不得互相代偿：

```
credentials_version      → per-user auth epoch（列名保留，但语义按本表冻结）
DB migration/schema 版本 → 由 ensure_schema / 迁移系统自己管理
Argon2 PHC m/t/p/v       → 密码学参数事实
```

冻结这层语义的理由：若不写明它是"auth epoch"，后续实现者会以"schema 又没变"为由拒绝在改密时 bump `credentials_version`，从而静默废掉 §7.5 的令牌失效契约。

参数漂移判定**必须**使用 `argon2.PasswordHasher.check_needs_rehash()`，不得自行比较字符串。`v=19` 与项目版本无关：升 `m/t/p` 时 `v=19` 通常不变，把它当版本用会造成"改了参数但没换 v"的静默错判。

档位落地前必须通过 SECA-19 的容器实测；不满足 ⇒ 状态 `BLOCKED` 或走 §19 修订，**禁止静默降到 OWASP 最低线以下**。

### 6.4 身份声明文件 schema 与合并不变量

每个文件是身份记录数组，字段封闭：

```jsonc
{ "username": "admin", "display_name": "…", "role": "ADMIN",
  "feishu_open_id": "ou_…",  // 可选
  "enabled": true }           // 默认 true
```

- `extra="forbid"` + 显式敏感键黑名单（`password` / `password_hash` / `hash` / `secret` / `token` / 64-hex 形态值）⇒ 任何一条命中即 **fail startup**，不忽略、不告警放行。
- **合并顺序与冲突（结构不变量）**：dev/test 形态按 `users.json` → `users.demo.json` 顺序合并，**重复 username ⇒ 启动失败**。禁止 `{**enterprise, **demo}` 式字典合并——那等于允许 demo 文件静默覆盖同名正式身份（改角色、接管凭据行）。企业形态只加载 `users.json`，冲突面天然为空，但校验代码两形态都跑。
- **唯一性检查在两文件合并后的全集上做**：`username` 全局唯一；非 null 的 `feishu_open_id` 全局唯一（它是 `identity.resolver` 的查找键，两账号共用一个 open_id 会让授予串到别人身上）。
- `enabled: bool = true`。`enabled=false` 的账号**不参与口令校验**，走 §7.3 的哑校验路径并返回统一 401 —— disabled 不能成为第四个可区分状态，否则它自己就是一条新的 timing 枚举面。停用一个账号的运维动作 = 身份文件置 `enabled=false`（身份侧）+ 删凭据行或 bump `cv`（凭据侧，见 §8.7）。

---

## 7. 认证流程时序（登录是唯一一条腿）

### 7.1 顺序即契约

```
0. 并发闸门（Argon2 同时运算上限） + pre-hash throttle(username, client_ip)
1. 身份查找（directory）：未知 username 或 `enabled=false` ⇒ 归入"无可校验凭据"路径
2. 凭据行查找：有身份无行 ⇒ 同样归入"无可校验凭据"路径
3. 账号锁定判定（按 username 的持久状态）
4. credentials.verify（按 algorithm 列分派；"无可校验凭据"路径执行同档哑校验）
5. 失败 → 账号级失败计数 +1（达阈值写 locked_until）；成功 → 计数清零
6. 成功且（legacy 或 needs_rehash）→ 同一事务渐进重哈希
7. 发 token（claim 带 cv）
```

**步骤 0 先于任何哈希运算**：19 MiB 级内存硬哈希若排在检查之后，认证面自身即成 DoS 面（OWASP 亦提示过重 work factor 可形成资源耗尽）。并发闸门溢出时返回 `503`（可用性语义，与凭据无关，且在身份查找之前 ⇒ 不构成账号枚举面）。

`client_ip` 取 `request.client.host`；**不信任 `X-Forwarded-For`**——当前 compose 前置无 nginx（全仓 `limit_req` / 转发头处理零命中），信任转发头等于白送伪装源。

### 7.2 两层保护必须分开（不得合并成一枚键）

| 层 | 键 | 载体 | 作用 | 重启 |
| --- | --- | --- | --- | --- |
| pre-hash throttle | `(normalized_username, client_ip)` | 进程内 | 抑制单来源高频；保护哈希运算本身 | 清零可接受 |
| 持久账号锁定 | `username` | `failed_attempts` / `locked_until` | 防分布式口令猜测：多来源共享同一账号状态 | 持久 |

合并成一枚键会同时丢掉两种保护之一：只按 `(username, ip)` ⇒ 换 IP 即绕过账号锁定；只按 `username` ⇒ 单来源可把 Argon2 打成 CPU 耗尽。两枚键的独立性必须各自有直接断言（SECA-16a / 16b，§13 M6 的可杀性依赖它）。

### 7.3 哑校验与统一失败面

**四态合一**：未知账号、身份 `enabled=false`、有身份无凭据行、口令错误 —— 四态在 HTTP 状态码、HTTP 响应体（含中文 detail）、审计 token 三个面上完全相同（`401` / 「用户名或密码错误」/ `invalid_credentials`）。前三态执行一次对 `credentials.py` 内固定 dummy PHC 串的 verify，第四态执行真实 verify。

**硬门的判定形态（不造毫秒阈值门）**：四态各自断言**恰好调用一次 `PasswordHasher.verify`，且使用同一个 profile 与同一个 `PasswordHasher` 实例**（调用面 spy + 参数比对）。dummy 串参数必须与当前 profile 同档，否则工作量不可比——这条由测试钉死而非注释。

**latency 分布只作为证据采集，不作为 GREEN/BLOCKED 的输入。** 理由：毫秒阈值门在共享开发机上必然 flaky，而 flaky 的安全门会被下一轮人直接 `skip` 掉，那比没有门更糟。可判定的等价性来自"恰好一次同档运算"这个结构事实；延迟表进 §14 证据面供人事后复核。

（与 SECA-19 的区别要说清：SECA-19 也带 P95 数值，但它是**离线单次采集的容量标定**——无并发争用、无其他测试负载，测的是"这台机/这个镜像扛不扛得住这一档参数"；SECA-13 要测的是**两条路径之间的相对等价**，放进整套 pytest 里必然被噪声主导。前者可判定，后者不可，故一个进门、一个只进证据。）

**timing 等价适用范围**（用户裁定）：上述四态；**锁定路径显式排除**，见 §7.4。

### 7.4 锁定：外部统一，内部可诊断

- HTTP `401` + 与其余三态逐字相同的中文文案；审计 token `invalid_credentials`；响应体**不含**任何锁定字样。
- 审计内部记 `AUTH_LOGIN_LOCKED`，仅供运维，不出现在响应面。
- **不承诺**锁定路径与普通凭据失败的 timing 等价；**不得**用 `sleep()` / 人工延迟"修平"——固定延迟降低吞吐、易成连接占用面，且并不构成真正的 constant-time 网络行为。
- 被锁用户得不到"你被锁了"的提示，这是本规格明确接受的可用性代价（§17 L1）。可运维性走 CLI `credentials migration-status` 与审计事件。

### 7.5 令牌生命周期

`issue_token` 增加 claim `cv = credentials_version`。`require_user` 在验签之后**从表中读当前 `credentials_version` 并比对**；不等 ⇒ `401 无效登录凭证`（与普通过期同形）。

claim 里的 `cv` 只作"要比对哪个版本"的提示，**鉴权判定读表**——与既有裁定同族（`test_feishu_identity_contract.py:1802` 已钉"鉴权不读 JWT claim"）。改密 / 重置 / 停用 ⇒ bump（或删除凭据行）即废全部已发 token，不等 `exp`。

**`cv` claim 缺失（SEC-A 之前签发的 token）⇒ fail closed：等同不符 ⇒ `401 无效登录凭证`。** 这条现在决定，不留给实现：签名有效但 claim 里没有 `cv` 的令牌一律拒绝。

- 禁止写成 `if cv is None: allow()` 之类的兼容分支——那正是"为了向后兼容挖出的认证绕过洞"，且与 `test_feishu_identity_contract.py:1800` 那类自签 JWT 的既有测试面直接冲突。
- 后果如实记录：**SEC-A 上线的一刻，所有 SEC-A 之前签发的 session 发生一次强制重新登录。** 这是安全升级中可接受、且容易向用户解释的一次性 breaking session event，写进 §15 release note 与 §17 限制，不粉饰成"无感升级"。
- 由 SECA-09b 硬门 + M17 变异锁住。

---

## 8. 迁移与收敛

### 8.1 密码学前提（本规格的根）

**"保口令的一次性离线迁移"不存在。** 无盐 SHA-256 单向，管理员手上只有 `240be518…`，没有任何离线过程能产出 `argon2id$…`。口令升级只有两个来源：**登录即重哈希**（用户当场交出口令）与**换一个新口令**（放弃旧口令）。

因此迁移必须同时具备两件事：渐进重哈希保证 SEC-A-003（不掉线），强制改密 + 运维闭合动作保证 SEC-A-004 是**可判定**终点（弱口令行可以永远无人登录，把终态押在"每个人都登录过一次"上，验收永远闭不了）。

### 8.2 迁移输入 ≠ 全新安装的凭据来源（两条路径必须彻底分开）

5 枚 legacy digest 在迁移期间存放于 `data/legacy_credentials.json`。**不写进 `backend/app/` 或 `config/`**，否则 closure 的三处 0 命中扫描（§4 SEC-A-004）自相矛盾，且又造出一个凭据材料真源。

该文件的定位被严格限定为**升级工件**，不承担长期 bootstrap：

```
data/legacy_credentials.json
  = 仅服务"从 SEC-A 之前的版本升级"这一条路径
  = closure 后删除
  = 不属于 fresh installation 的凭据来源
```

**全新安装（无该文件）的凭据来源**因此只有两条，且都只产 `argon2id`：

| 场景 | 凭据来源 | 说明 |
| --- | --- | --- |
| 测试 / CI | 测试 fixture 调 `credentials.hash_password()` 在**临时 DB** 造 argon2id 行 | 口令字面量只存在于测试侧（`admin123` 等本来就是测试字面量）；**会话级 seed 一次**，避免每用例重算 Argon2；既有 8 处登录调用点的口令字面量与调用契约**不改** |
| 手工 dev / 企业部署 | CLI `credentials bootstrap-admin` 与 `credentials reset`（§8.6、§8.7） | 运维在本地进程内提供口令，走同一 Argon2id 写路径 |

⇒ 由此得到一条比 SEC-A-001 更强的结论：**SEC-A 之后，fresh 环境根本不再生成 legacy 凭据行**；`legacy-sha256` 这个取值的唯一产地是"升级路径读迁移工件"。"测试调用契约不变"与"生产代码继续 seed legacy"是两件不同的事，本规格只承诺前者（这一区分即 §8.5 形态表的依据）。

### 8.3 渐进重哈希时序

`legacy-sha256` 校验成功 ⇒ **同一条 UPDATE** 内写：`algorithm='argon2id'`、`password_hash=<新 PHC 串>`、`must_change=1`、`updated_at`。两者不可分：只重哈希不置 `must_change`，会出现"已升级但可自由访问"的窗口。

仅参数漂移（`check_needs_rehash()` 为真、算法仍是 argon2id）⇒ 重哈希但 `must_change` **保持原值**。

**重哈希写盘失败（已冻结裁定）**：本次登录**仍然成功**（统一 200 + 正常 token），legacy 行**保留**待收敛，写审计事件 `AUTH_REHASH_DEGRADED`。定性为"收敛延迟"而非"安全放行"；不静默——`legacy_count>0` 会把它暴露在 `migration-status` 上。反向理由：一次 UPDATE 失败（DB 锁 / volume 满）变成全员掉线是运维事故。此裁定由 SECA-21 硬门 + M14 反向变异锁住。

### 8.4 `must_change` 门

白名单只有两处（其余全部已鉴权端点 `403` + 中文文案「当前账号需先修改口令」，审计 token `password_change_required`）：

- `POST /api/auth/password/change`
- `GET /api/auth/me`

实现方式**不是中间件猜路径**，而是依赖注入分层：白名单两条走 `require_user_pending_password`，其余全部走 `require_user`。理由：弱口令收敛期间还能读企业知识的话，`must_change` 只是提示而非门；即便该账号原本拥有 `system:operate` 也不能绕过。

**顺序冻结为 `authentication → must_change → authorization`**（与 §9.2 同一条链，两处措辞必须一字一致）：

```
token validation（authentication）
      ↓
凭据状态查找
      ↓
must_change gate
      ↓
authorization / RBAC（enforce_permission，文案与 403 语义不变）
```

`must_change` 存在于凭据行里，只有完成 token authentication、拿到身份之后才有资格查它 ⇒ 它**不可能**排在 authentication 之前。本条要表达的是"must_change 早于 authorization"，不是"早于 authentication"。

判定读表，不读 claim。`/api/query`、两条 SSE 腿（会话流、agent 流）、agent 工具腿都在门后——端点覆盖由路由表枚举自证（SECA-10）。

### 8.5 双形态：`SECURITY_ENTERPRISE_MODE`（单开关，默认 `false`）

一枚开关同时驱动三件事，避免"enterprise 但允许默认 secret"这类矛盾组合空间：

| 形态 | `false`（dev / 测试，默认） | `true`（企业验收） |
| --- | --- | --- |
| demo 身份与凭据 | 载入 5 个 demo 身份（来自 `config/users.demo.json`）。**凭据缺行不自动导入 legacy**：全新安装的 demo 凭据只来自测试 fixture 或 CLI（§8.2 表）；只有**升级路径**（存在 `data/legacy_credentials.json`）才导入 legacy 并置 `must_change=1`——且导入是**运维显式动作**（CLI `credentials migrate`，§11），不是启动副作用 | **不加载** `config/users.demo.json`（结构事实，非按用户名过滤）；**不导入任何 legacy**；`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，非 500） |
| 默认 JWT secret | 允许（测试形态） | **拒绝启动** |
| CORS | 默认白名单 `http://localhost:3000` | `CORS_ALLOW_ORIGINS` 未配置 ⇒ **拒绝启动** |

默认 `false` ⇒ 既有 8 处登录调用点的**调用契约与口令字面量不变**。dev 侧的真实改动只有一处、且集中在测试面：fixture 需要 seed argon2id 凭据行（§8.2、SECA-24），因为生产代码不再自动导入 legacy。

守卫位置：`app/security_startup.py::assert_startup_safe()`，由 lifespan **第一个**调用（步骤序：守卫 → 建表 → `warmup_identity_permissions()` → `warmup_llm_router()`；行号会漂，认符号不认坐标——同一课见 §20.4），与两枚 warmup 同处；`main_agent.py` 复用同一 app 实例与同一 lifespan（`main_agent.py:9` 已证），故一并生效。SECA-18 有一条测试**直接调用 `assert_startup_safe()`** 断言三件守卫同时生效，不依赖 lifespan 是否被执行。**顺序本身是契约**：企业形态下默认 secret / 通配 CORS 的实例必须在任何落盘动作之前被拒——即"先拒坏配置，再谈建表"，不得倒过来。

**lifespan 还负责凭据表的存在性**（Task 10 收口时补，来由见 §20.6）：`user_store.ensure_user_credentials_schema()` 是全模块唯一建表者，而它自己的注释与 `credentials_migration` 的理由块都写着"由**启动编排** / CLI 调"。本轮实测：全新安装（没跑过任何 CLI）登录一律 500（`sqlite3.OperationalError: no such table: user_credentials`），当场违反上表企业列那句「`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，**非 500**）」。⇒ 启动编排在建表这件事上不是可选项：**lifespan 在守卫之后、warmup 之前调一次 `ensure_user_credentials_schema()`**（`IF NOT EXISTS`，幂等），失败按守卫的既有形状 fail-fast（uvicorn 退出），而不是让每个请求各自撞 500。读路径仍然不建表（那是另一条已冻结的理由：env 被清掉时往生产库提交 DDL 更糟）。

### 8.6 `bootstrap-admin` 的语义（闭合"身份真源写入空洞"）

**裁定：bootstrap 只创建凭据状态，绝不创建身份。**

- `python -m app.cli credentials bootstrap-admin --username X` 要求 `X` **已存在于企业形态的身份声明文件 `config/users.json`**。不存在 ⇒ 报错退出，不自动建行、不自动写身份文件。
- 身份唯一真源因此始终是**身份声明文件集**（企业形态即 `config/users.json`，dev/test 形态再加 demo 文件，见 SEC-A-010）；凭据唯一真源是 `user_credentials`。bootstrap 不写身份 ⇒ SEC-A-010 由此结构成立，不存在"CLI 顺手创建了第二个身份真源"。
- 口令来源：**仅**环境变量 `CREDENTIALS_PASSWORD`（`bootstrap-admin` 与 `reset` 共用同一变量名，避免两处规则漂移）。不接受 `--password` argv（`ps` 与 shell history 可观察，违反 SEC-A-002）；不做交互输入 ⇒ CLI 可在 compose/CI 里非交互执行。SECA-02 断言 `--help` 面不存在任何接收口令的选项。
- 明确**不做** HTTP bootstrap 端点：零账号时开放未鉴权写路径是竞态窗口。
- 运维人体检查：`config/users.json` 随镜像 `COPY config ./config` 打包，改身份需重建镜像或挂载覆盖——§17 L4 记录，本规格不引入身份热加载。

### 8.7 长期不登录账号如何到达 `legacy_count = 0`

渐进重哈希自身到不了零。闭合动作两条，逐账号选：

1. **管理员重置**：HTTP `POST /api/admin/users/{username}/password/reset`（需 `system:operate`，复用既有权限面，**不新增权限名**）或 CLI `python -m app.cli credentials reset --username X`。CLI 分支存在的原因：企业形态初始零账号时无 HTTP admin 可调；且 CLI 的信任边界等价于"能读写该 DB 文件的进程"，不是提权面。
2. **停用**：身份侧置 `enabled=false`（§6.4，走哑校验 + 统一 401）+ 删除凭据行 ⇒ 计数归零且不可登录。

观测：`python -m app.cli credentials migration-status` 输出 `legacy_count` 与逐账号（最后成功登录时间、`must_change`、是否锁定）——这就是验收证据的采集面。

**硬门**：`legacy_count = 0` 是 SEC-A release gate。未闭合 ⇒ SECA-04 状态 **`BLOCKED`**，不得出 `PASS`。词汇表只有 `GREEN / PENDING_EXTERNAL / BLOCKED` 三值：`legacy_count>0` 不是外部依赖（不需要凭据、不需要网络、运维一条命令即可闭合），因此**绝不写 `PENDING`**——那是本规格词表里不存在的状态，也是把内部待办伪装成外部阻塞。

### 8.8 改密 / 重置的输入与事务不变量

- 新口令下限：**长度 ≥ 12 且 ≤ 128**（沿用 `LoginRequest` 的 128 上限）、**不得等于 username**（大小写归一后比较）。Argon2 无 bcrypt 的 72 字节截断问题 ⇒ 不需要预哈希。
- **弱口令字典不在 SEC-A 内**。原文"不命中内置小字典"已删除：没有定义内容来源、条目数与归一化规则的"小字典"等于把一条安全规则留给实现者自行发挥，验收时也无法判定它是否成立。要做就必须先冻结 `PASSWORD_DENYLIST`（条目来源、规模、大小写/Unicode 归一、是否含 username 变体）——该定义工作连同实现一起登记 §18，SEC-A 不做。
- `POST /api/auth/password/change` 必须带旧口令。
- 重置的新口令由管理员指定（非服务端随机——随机口令把"能登录"变成"能登录且必然掉线"），并强制 `must_change=1`。
- **同事务不变量**（用户裁定补入）：改密/重置成功 ⇒
  `password_hash` + `algorithm='argon2id'` + `must_change`（改密 0 / 重置 1）+ `credentials_version += 1` + `failed_attempts = 0` + `locked_until = NULL` 全在**一条 SQLite 事务**。
  两个不可分点：① hash 与 cv bump 跨事务 ⇒ 存在"口令已换、旧 token 仍有效"的提交窗口（SECA-11 锁）；② 不清锁定状态 ⇒ 管理员完成 reset 后用户仍被旧 lock 挡住（SECA-12 锁）。
- 两个端点**共用 login 的 throttle 键空间**：改密端点带旧口令校验，与登录是同一爆破面，不能免检。
- 响应不回显任何口令；审计 `detail` 用枚举值 `password_changed` / `password_reset_by_admin` / `credential_bootstrap`，不写口令长度、hash、hash 前缀。

---

## 9. 错误与安全语义

### 9.1 失败值域：HTTP `detail`（中文展示面）与审计 `detail`（枚举 token）分两栏

复核修正：本节初稿把 `invalid_credentials` / `password_change_required` 直接写成 **HTTP 响应 detail**，那会让面向用户的界面第一次出现英文 token，与既有展示层文案规则（`docs/UI_COPY_GLOSSARY.md`，且现网 401/403 文案本就是中文）冲突。冻结为两栏，各管各的面：机器可读性走审计与新增布尔键，展示走中文文案。

| 状态码 | HTTP `detail`（中文，展示面） | 审计 `detail`（枚举 token） | 触发 | 性质 |
| --- | --- | --- | --- | --- |
| 401 | `用户名或密码错误` | `invalid_credentials` | 账号不存在 / 身份 `enabled=false` / 有身份无凭据行 / 口令错 / 账号处于锁定 | **文案与现网逐字相同**（既有值），新增的是"四态共用"这一事实 |
| 401 | `无效登录凭证` | `invalid_token` | 验签失败、过期、`cv` 与表内不符、**`cv` claim 缺失**、此前单列的「账号不存在」 | **收紧**（`auth.py:230` 并入既有文案） |
| 401 | `登录已过期，请重新登录` | `token_expired` | 签名有效但过期 | 不动 |
| 403 | `当前账号需先修改口令` | `password_change_required` | 已鉴权且 token 有效，表内 `must_change=1` | 新建（token 在审计面，中文在展示面） |
| 403 | `当前账号缺少权限：X` | `missing_permission=X` | 既有 | **一字不动** |
| 422 | `新口令长度需在 12 到 128 个字符之间` / `新口令不得与账号名相同` | `password_policy_rejected` | 改密 / 重置 | 新建。**不是 403**：强度不足是输入校验失败，不是权限判定，混用会把既有 RBAC 的 403 语义污染成"权限"面 |
| 429 | `登录尝试过于频繁，请稍后再试` | `login_throttled` | pre-hash throttle 命中 | 新建，不泄露账号存在性（判定在身份查找之前） |
| 503 | `服务繁忙，请稍后重试` | `password_capacity` | Argon2 并发闸门溢出 | 新建，同上 |

机器可读的 must_change 信号有两条，都不靠解析中文文案：登录/`/me` 响应体的布尔键（§11），以及审计事件的枚举 token。`AUTH_LOGIN_LOCKED` / `AUTH_REHASH_DEGRADED` 两枚 token 只存在于审计面。

**"四态不可区分"的判定对象是这三件事**：HTTP 状态码、HTTP 响应体（含中文 detail）、审计 token。四态共用同一组取值即成立；不把中文文案当协议字段解析。

`AUTH_LOGIN` 审计事件的 `detail` 值域收为枚举：`invalid_credentials` / `password_changed` / `password_reset_by_admin` / `credential_bootstrap` / `AUTH_LOGIN_LOCKED` / `AUTH_REHASH_DEGRADED`；自由文本不得进入该字段。

### 9.2 判定顺序

```
pre-hash throttle / 并发闸门
   → 身份 / 凭据 / 锁定判定
   → 口令 verify
   → 渐进重哈希（同事务）
   → 令牌签发 / 校验（cv 比对）
   → must_change 门
   → permission 门（enforce_permission，文案与 403 语义不变）
```

### 9.3 脱敏的两个作用域（SEC-A-009）

```
AUTHORIZED SECRET STORE（user_credentials）
  schema 专列；password_hash 合法字段；明文口令在类型/schema 层根本不存在
  不经任何通用 redactor

PERSISTED TELEMETRY（audit / agent_traces / 日志 / llm_request_logs）
  必经 redact_for_persistence()
```

- 新增 `redact_for_persistence()` = 既有形态脱敏 + **精确键名黑名单**（`password`、`password_hash`、`access_token`、`refresh_token`、`authorization`、`api_key`、`app_secret`、`tenant_access_token` 等）。
- **既有 `redact_secrets()` 语义与全部调用点（AST 量得 17 处，见 §2 与 §20.4）一字不动**，继续只管响应面与形态匹配。
- **全词精确匹配，不用子串**：子串 `token` 会连带抹掉 `input_tokens` / `output_tokens`（observability 数据，非秘密），甚至登录响应的 `access_token`。`tenant_access_token` 该抹 ⇒ 显式进全词集合，不指望子串兜住。
- 两个方向都必须有测试（SECA-17）：敏感键必抹 + 已知相似非敏感键必不误伤；豁免表与命中表相等（`tests/test_llm_egress_guard.py` 同族做法）。
- 切换点：`audit.record_event`、`agent_trace.save_trace`/`get_trace`、遥测类持久写入。`conversation_store` 里字符串走 `redact_text`（形态脱敏）不受影响——黑名单只匹配 dict 键名，不匹配值内容。
- **上面那枚枚举之外的两张既有落盘写手（§20.7 的 S3 点名，之前规格里没人提过）**：`backend/app/knowledge_os.py:86` 的 `_write_json` 与 `:92` 的 `_append_jsonl` 至今仍用 `redact_secrets`（形态脱敏），**不在**切换点枚举里。**这是范围边界，不是破掉的承诺**：切换面被 AST 那对等式钉着——`assert 4 == _call_sites("redact_for_persistence", …)`（`backend/tests/test_secret_hygiene_contract.py:211`，用例名 `test_the_four_persistence_faces_use_the_persistence_redactor`，`:196`）与 `assert 17 == _call_sites("redact_secrets", …)`（同文件 `:214`）⇒ 第五张落盘面一旦进来就同时把 4 和 17 判红，**不会静默漂移**。要不要把知识 OS 那两张面纳入，属 SEC-B 的语义增补（§18 登记为"纳入那两张面 ⇒ 钉 4→6，并须重写本节枚举"）。

---

## 10. secret / env / 配置边界

- `config.py:155` 的 `jwt_secret` 默认值保留（测试形态需要），但 `SECURITY_ENTERPRISE_MODE=true` + 该默认值 ⇒ **拒绝启动**。
- CORS：`allow_origins` 由 `CORS_ALLOW_ORIGINS`（逗号分隔白名单）驱动，非企业形态默认 `http://localhost:3000`；企业形态未配置 ⇒ 拒绝启动。`allow_credentials=False` **保持不动**（token 走 header，收紧 origin 才是有效项，加 credentials 反而扩大面）。
- compose 路径补一条与 `deploy.ps1:95-112` 同效的 secret 生成守卫；但**主防线是代码内启动守卫**（可测），脚本只是便利项——安全语义不得寄托在"运维跑了对的脚本"。
- `.env.example` 新增：`SECURITY_ENTERPRISE_MODE`、`CORS_ALLOW_ORIGINS`、`LOGIN_THROTTLE_WINDOW_SECONDS=60`、`LOGIN_THROTTLE_MAX_ATTEMPTS=10`、`ACCOUNT_MAX_FAILED_ATTEMPTS=5`、`ACCOUNT_LOCK_SECONDS=900`、`ARGON2_MAX_CONCURRENT_OPS=2`。**Argon2 的 `m/t/p` 不在此列**（SEC-A-008：强度参数不可 env 调）。
- `CREDENTIALS_PASSWORD` 是**一次性 CLI 专用**环境变量，**不得**出现在 `.env` 或 `.env.example`：`.env` 由服务进程加载，写进去等于把明文口令放进常驻配置面（违反 SEC-A-002）。SECA-02 有一条扫描断言钉 `.env.example` 的键集合与该口令面**无交集**。
- 节流/锁定/并发参数可 env 调（可用性旋钮），强度参数不可（安全强度）——这条区分本身要有测试。

---

## 11. API 契约变化声明

**响应面键集合变化只有 2 处，均为 additive 可选键**（本规格唯一一处键集合变更声明，比照 V2.3 §9.2 的纪律）：

| 端点 | 新增键 | 规则 |
| --- | --- | --- |
| `POST /api/auth/login` | `password_change_required: bool` | 恒在，读表判定；不读 claim |
| `GET /api/auth/me` | `password_change_required: bool` | 恒在，同上 |

已核实地基（2026-09-26 由 Task 6 实现复核更正）：**登录响应顶层**无键集合断言（既有 8 处只读 `["access_token"]`），但**嵌套的 `user` 对象与 `/api/auth/me` 有等值键集合钉** —— `test_feishu_identity_contract.py:1718` 的 `_LOCAL_KEYS`，在 `:1777`（`login.json()["user"]`）与 `:1778`（`me.json()`）两处使用。⇒ 后果与初稿判断相反：`/api/auth/me` 加这枚键**必然**要求同步把那两处期望集改成 `_LOCAL_KEYS | {"password_change_required"}`，而登录**顶层**加键不动任何既有断言。初稿把这条写成"全仓无登录响应键集合断言"，是盘点漏项而非规格推论错误：§11 的加键判定本身成立，只是 `/me` 那一处必须连带改既有钉。另：前端 `lib/api.ts:241` 类型为 `{access_token, user}` ⇒ 顶层加键非破坏性。`/api/query` 的键集合钉（`test_typesafe_api_runtime.py:91/119/148`）**不受影响**，本规格不触碰该端点响应面。

**新端点**：`POST /api/auth/password/change`、`POST /api/admin/users/{username}/password/reset`（权限 `system:operate`，不新增权限名）。

**新 CLI**：`python -m app.cli credentials bootstrap-admin | reset | migration-status | migrate`。

`migrate` 是 **legacy 导入的唯一生产入口**（Task 10 收口时补，来由见 §20.5）：它按 §8.2 的升级路径读
`data/legacy_credentials.json`、以 `only_missing=True` 写入 legacy 行并置 `must_change=1`，然后打印
`MigrationReport`（`artifact_present / imported / skipped / reason`）。规则四条，全部可测：

- **启动不自动导入**（§8.5「生产代码不再自动导入 legacy」保持不变）——消费一份含凭据材料的文件是**运维动作**，
  要有人执行、有退出码、有输出可归档；放进 lifespan 就变成"每次重启都可能悄悄造行"，与 §8.6 bootstrap
  绝不建身份的显式性不自洽。
- **企业形态直接拒绝**（`SECURITY_ENTERPRISE_MODE=true` ⇒ 非零退出、一行不写），与 §8.5 表格里企业列的
  「不导入任何 legacy」同一条路；否则"开关一拨、文件还在"就会绕过 fail-closed。
- **幂等**：`only_missing=True` ⇒ 已收敛成 argon2id 的账号不会被降级回 legacy；重复执行只补真正缺行的那些。
- 口令来源仍是 `CREDENTIALS_PASSWORD` env-only（SEC-A-002），`migrate` 自身不接触任何明文口令——它写的就是
  工件里已有的摘要。

**`credentials` 面的退出码是一张三行的表，不是散落的字面量**（实现期复评审出"rc 只有代码注释知道"，
而 §15.1 第 6 步是要由人或脚本执行的，必须能区分"把开关拨回去"与"重导一次工件"）：

| rc | 含义 | 现在的取值 |
| --- | --- | --- |
| `0` | 执行成功，**含"工件不存在"这一合法稳态**（`artifact_present=False, imported=0`） | `migrate` / `reset` / `bootstrap-admin` 成功、`migration-status` |
| `1` | **基础设施事故**：存储写不进去 —— `CredentialStoreError` **与 `sqlite3.Error` 同归这一格**（DB 锁 / 卷满 / 表不存在），且不得以裸栈出到运维面前 | 各写腿 + `migrate` |
| `2` | **运维可修的拒绝**：企业形态拒绝导入、工件形状不合法、身份不存在、env 口令缺失或过短、策略不通过 | 各动作 + argparse 自身的用法错误同为 2 |
| `3` | 开发者缺陷（不该出现的分支） | CLI 兜底 |

`2` 的三段子含义由 stderr 那句话分诊，**不再为畸形工件另开一枚码**（新开会把"事故=1"这一格搞混，
而脚本唯一需要可靠分辨的是 1 与非 1）。

**`migrate` 的证据面是那四行可归档的 stdout，不是审计事件。** `bootstrap-admin` 与 `reset` 各写一枚
`PASSWORD/*` 审计事件（它们有明确的 actor 与账号），而 `migrate` 一次可以造五行、执行者是"能写这个库
的进程"本身——§9.1 的 `detail` 取值集合是封闭的，为它另造一枚 token 属于改契约而非补漏。裁定：登记在
§8.6「CLI 无独立 actor」同一条理由下，`migrate` 不落审计，运维证据 = 退出码 + stdout（含 `reason`
里解析后的绝对路径）。

**行为变化**：`auth.py:230` 的「账号不存在」文案并入「无效登录凭证」；`must_change=1` 时白名单外端点新增 403；节流命中新增 429；并发闸门溢出新增 503。既有 403 权限文案与状态码语义不变。

---

## 12. 测试矩阵

状态词汇表严格三值 `GREEN / PENDING_EXTERNAL / BLOCKED`；能力级 PASS 语言只出现在 §15.3 叙述节，不进状态列。

| ID | 不变量 | 判定形态（行为断言，非注释） |
| --- | --- | --- |
| SECA-01 | SEC-A-001 | DB 面：改密/bootstrap/重置成功后 `SELECT algorithm` 恒 `argon2id`；再断言 `user_store` 写函数签名不可达 `algorithm` 取值 |
| SECA-02 | SEC-A-002 | 文件+HTTP 面：改密后 `audit.jsonl`/`agent_traces.jsonl`/DB 全文扫新口令字面量 = 0；登录响应体不含口令；CLI 不接受 `--password`（`--help` 面断言） |
| SECA-03 | SEC-A-003 | 端到端**升级路径**（构造含 legacy 行的 DB）：legacy 行 + `admin123` ⇒ 200 + token + 数据面被 must_change 挡；改密后数据面通 |
| SECA-04 | SEC-A-004 | SQL 门 `legacy_count=0`（未闭合 ⇒ `BLOCKED`，见 §8.7）；closure 三处扫描 5 枚 digest = 0 命中 |
| SECA-04b | §8.2 | **全新安装**（无 `legacy_credentials.json`）：dev 形态 fixture/CLI 造的行全部 `argon2id`、`legacy_count=0` 天然成立；企业形态零行 ⇒ 登录统一 401 且非 500。**两格都要测**（§20.6）：①"表在场、零行"；②"表不在场的冷启动"——lifespan 建表后仍须是统一 401，不得以 `no such table` 的 500 出人脸 |
| SECA-05 | SEC-A-005 | AST 扫描：口令参与运算的 `hashlib` 命中面恰 `credentials.py` 一处，豁免表 == 命中表 |
| SECA-06 | SEC-A-006 | 既有基线全绿（§16 第一组） |
| SECA-07 | SEC-A-010 | **两个**身份文件（`users.json` 与 `users.demo.json`）各塞 `password`/`password_hash`/legacy hex ⇒ 启动失败（非忽略、非告警）；并断言企业形态下 `users.demo.json` 根本不被加载（demo 用户名在两种形态下的可登录集合差异由文件装载面决定，不由代码用户名表决定） |
| SECA-08 | §6.1 | `user_credentials` 列名集合：MAY `password_hash`；MUST NOT `password`/`plaintext_password`/`raw_password` |
| SECA-09 | T5 | 改密后旧 token 打 `/api/query` ⇒ 401 `无效登录凭证`，与普通过期同形；重置后同断言 |
| SECA-09b | §7.5 | **签名有效但 claim 无 `cv`**（SEC-A 前签发的 token）⇒ `/api/query` 401 `无效登录凭证`。反向钉：不得存在"缺 `cv` 即放行"的兼容分支（M17 杀这条） |
| SECA-10 | §8.4 | **由路由表枚举生成**端点清单：走 `require_user`/`require_permission` 的每条（含两条 SSE 腿、agent 腿）都 must 403 + 中文文案「当前账号需先修改口令」（审计 token `password_change_required`）；且"走 `require_user_pending_password` 的端点集合" == 白名单 2 项（漏一条即红，多一条也红） |
| SECA-11 | §8.8 | 注入"hash 写成功、cv bump 失败"⇒ 整事务回滚：出现"旧 hash + 旧 cv"，绝不出现"新 hash + 旧 cv" |
| SECA-12 | §8.8 | 先锁定 → 管理员重置 ⇒ 同事务 `failed_attempts=0`/`locked_until=NULL`，新口令可登录 |
| SECA-13 | T4 | 四态（未知账号 / `enabled=false` / 有身份无凭据 / 口令错）：状态码 + 响应体 + 审计 detail 三者相等；并断言每态**恰好调用一次 `PasswordHasher.verify` 且 profile 与实例相同**（调用面 spy）。latency 分布只进 §14 证据面，**不参与判定**（不设毫秒阈值，避免 flaky 门被后人 `skip`） |
| SECA-14 | §7.4 | 锁定路径 HTTP 401、body 无锁定字样、审计 `AUTH_LOGIN_LOCKED`；显式**不**断言其 timing 等价 |
| SECA-15 | §7.1 | 超限请求**未调用** `PasswordHasher.verify`（调用面 spy 断言昂贵运算被跳过） |
| SECA-16a | §7.2 | 同 username + 不同 ip 的 throttle bucket **相互独立**（A 源耗尽不影响 B 源）——M6 的可杀性依赖这条直接断言 |
| SECA-16b | §7.2 | 不同 ip 打同一 username ⇒ 账号级 `failed_attempts` 累加并触发 `locked_until` |
| SECA-17 | SEC-A-009 | 双向：落盘面 `password`/`access_token`/`tenant_access_token` 必抹；`input_tokens`/`output_tokens`/`num_sources` 必不抹；且 `user_store` 写入路径不经任何 redactor |
| SECA-18 | §8.5 | 直接调用 `assert_startup_safe()`：企业形态 + 默认 secret ⇒ 拒；企业形态 + CORS 未配 ⇒ 拒；**三件守卫同时生效**（不得只落 seed 半件）；另加一格：拒绝启动的那次**不得已经建表**（§8.5 顺序契约） |
| SECA-19 | SEC-A-008 + T8 | **发布容器内**实测：串行 50 次 verify 的 P50/P95、`ARGON2_MAX_CONCURRENT_OPS` 并发下的 P95、峰值 RSS 增量。预算：单线程 P95 ≤ 1500 ms；并发 P95 ≤ 3000 ms；RSS 增量 ≤ 256 MiB。不满足 ⇒ `BLOCKED`，禁止降档（§19） |
| SECA-20 | G0 扫描门 | tracked-file 密钥扫描测试：植入一枚假凭据即红；`.env.example` 占位符与测试假值走豁免表，豁免表 == 命中表。**执行位置**：扫描子集（5 枚）**已在既有 `backend-contracts` job 里真跑**（`.github/workflows/ci.yml` step 3-4，排在会失败的既有步之前；本地等价取证见 §20.8 卡 D：基线绿 → 植入真形状假凭据红 → 还原绿）。其余 5 枚 SEC-A 契约文件仍只在本地（它们需要完整依赖 + 该 job 的 runner 是 `unittest discover`）。历史：§20.7 S2 先把"CI 同一道门"缩回"只保证本地"，本条按用户裁定**修 CI 而非放宽规格**后才恢复此声称。判据本身不变：豁免表 == 命中表、不新增 security job、不引入第三方扫描器 |
| SECA-21 | §8.3 冻结裁定 | 注入 UPDATE 失败 ⇒ 登录仍 200 + 正常 token + `AUTH_REHASH_DEGRADED` 审计 + legacy 行仍在 + `migration-status` 的 `legacy_count` 仍计入该行 |
| SECA-22 | 遥测污染护栏 | 凭据写盘不落生产库（继承 conftest `CONVERSATION_DB_PATH` 重定向）；测试结束后 `data/conversations.db` 无 `user_credentials` 行 |
| SECA-23 | §6.4 | 身份 loader 合并不变量：重复 username ⇒ 启动失败；demo 文件**不得**静默覆盖同名企业身份（构造同名冲突用例）；非 null `feishu_open_id` 合并后全局唯一；`enabled=false` ⇒ 走哑校验 + 统一 401（不成第四态） |
| SECA-24 | §8.2 | fixture 契约：既有 8 处登录调用点的口令字面量**不改**即可登录；断言 fixture 产出的行 `algorithm` 全为 `argon2id`、seed 为**会话级一次**（计数器断言 Argon2 hash 调用次数 ≤ 身份数，不随用例数增长） |

---

## 13. 变异清单

沿用 V2.3 的字节安全台（读字节 / 替换 / 写 / 还原 / sha1 核对 + 发内还原），禁止就地 `sed -i`。每发必须至少杀掉一枚测试，否则该测试是死代码。

| 变异 | 注入 | 期望红 |
| --- | --- | --- |
| M1 | Argon2 换成 `hashlib.sha256` | SECA-01 |
| M2 | 去掉 must_change 门 | SECA-10 |
| M3 | `require_user` 不再比对 `cv` | SECA-09 |
| M4 | 未知账号早退（删哑校验） | SECA-13 |
| M5 | 锁定返回 423 / 响应体带锁定字样 | SECA-14 |
| M6 | throttle 键去掉 `client_ip` | **SECA-16a**（同 username 不同 ip 独立性——无此直接断言则 M6 无法必杀） |
| M7 | lockout 计数键改按 ip | SECA-16b |
| M8 | redact 子串匹配 `token` | SECA-17（反误伤） |
| M9 | redactor 作用域扩到 `user_store` | SECA-17 + SECA-03（写进去的 hash 被抹，下次登录必失败） |
| M10 | cv bump 拆到 hash 之后的独立事务 | SECA-11 |
| M11 | 重置不清 lock 状态 | SECA-12 |
| M12 | `users.json` schema 放开 `extra` | SECA-07 |
| M13 | 业务代码新增一处口令 `hashlib` | SECA-05 |
| M14 | **反向**：重哈希写盘失败改为拒绝登录 | SECA-21（证明那条裁定不是空话） |
| M15 | 把 legacy digest 写进 `config/` 或 `backend/app/` | SECA-04 三处扫描 |
| M16 | `m/t/p` 改从 env 读取 | SECA-19 / SEC-A-008（强度参数不可运维调） |
| M17 | **`cv` 缺失即放行**（`if cv is None: allow()`） | SECA-09b —— 这条变异正是"为兼容旧 token 而挖的洞"，必须有门挡它 |
| M18 | 身份合并改成 `{**enterprise, **demo}` | SECA-23（demo 静默覆盖同名企业身份） |
| M19 | fresh install 时若缺凭据行就自动导入 legacy | SECA-04b（升级路径与全新安装重新混为一谈） |

---

## 14. 证据采集与 before/after

成对采集，落 `.superpowers/sdd/SECURITY_A_PLAN/` 工作区（SDD 脚本为该计划文件解析出的目录名），沿用 append-only snapshot 纪律（`snap-taskN` / `snap-taskN-r1`）与 per-row 台账（比照 `MODEL_ROUTER_V23_MATRIX.md`）。

| 证据 | before | after |
| --- | --- | --- |
| schema | 4 张业务表 dump | 含 `user_credentials` dump + 列名集合 |
| 算法分布 | `admin/sales01/hr01/user/viewer` 全 `legacy-sha256` | 全 `argon2id`，`legacy_count=0` |
| digest 扫描 | `backend/app/auth.py` 5 处命中 | 三处 0 命中 |
| 登录矩阵 | 弱口令直登、无门、无节流 | 两形态 × {成功 / 错口令 / 锁定 / must_change} 四场景 |
| Argon2 基准 | — | 容器内 P50/P95/RSS 原始 JSON（SECA-19） |
| 令牌生命周期 | 改密后旧 token 仍可用 | 改密后 401（SECA-09）；SEC-A 前签发的无 `cv` token ⇒ 401（SECA-09b） |
| 安装路径 | — | **升级路径**（存在迁移输入）与**全新安装**（无迁移输入）各自的 `algorithm` 分布与 `legacy_count`（SECA-04b） |
| 认证耗时 | — | 四态各"恰好一次 verify"的调用面记录 + latency 分布表（**只作证据**，SECA-13 判定不读它） |
| 套件 | **SEC-A 开工时实测**（V2.3 收口实测 961、其验收文档记 950；两个历史数字都不得直接充当本规格基线，见 §17 L5） | 全套件两 cwd 同数 |

**禁止的取证捷径**（V2.3 已踩过的坑，写进规格）：单字段断言不作为 P0 级判定依据（`status_code == 200` 可被改证据）；SECA 里的验收项必须是多事实互锁（HTTP 结果 + 审计事件 + DB 行 + 响应体 + 文件扫描同时成立）。

---

## 15. Release gate 与 verdict

### 15.1 顺序

1. `requirements.txt` 加 `argon2-cffi` ⇒ 宿主 + 容器双向 import 探针（任一失败 = `BLOCKED`）
2. 定向门：新增安全测试文件 + `test_rbac_contract` + `test_typesafe_security_contract` + 飞书身份 + branding
3. 全套件，**`cd backend` 与仓库根两种 cwd 同数**
4. 变异台 19 发全杀（含发内还原与 sha1 核对）
5. 结构扫描三处 0 命中
6. **重建发布镜像** → compose smoke：登录成功 / 错口令 / 改密全流程 / 锁定四场景真打一次。升级路径那一次必须先经 `credentials migrate`（§11）导入、再由真实登录收敛，`legacy_count` 从 5 走到 0 的两次读数都留证——**手工 SQL 归零不算数**
7. SECA-19 容器基准
8. 验收文档 verdict
9. 冻结：SEC-A 独立提交与 tag；**不触碰** `model-router-v2.3-rc1`（不 amend、不移 tag）

### 15.2 verdict 规则

- `PASS`：§12 的 **27 行**全 GREEN（SECA-01…24，含 04b / 09b / 16a / 16b 四个分裂行），19 发变异全杀，`legacy_count=0`，compose smoke 四场景绿。
- `CONDITIONAL PASS`：核心安全项 GREEN，存在明确命名的非核心 PENDING_EXTERNAL/BLOCKED，且每条写明复验条件与影响面。
- `FAIL` / `BLOCKED`：SECA-01 / 02 / 03 / 04 / 04b / 05 / 07 / 09b / 10 / 13 / 17 / 18 / 23 任一不成立 ⇒ **FAIL**（这些是一票否决项）。依赖或容器资源导致不可测 ⇒ `BLOCKED`，**不得用宿主数据替代容器证据**、不得降档、不得放宽规格。
- 状态列**只允许** `GREEN / PENDING_EXTERNAL / BLOCKED` 三值；`legacy_count>0` 属 `BLOCKED` 而非外部阻塞（§8.7）。
- **release note 必含一条 breaking change**：SEC-A 上线时所有此前签发的 JWT 因缺 `cv` 而失效一次（§7.5）——用户会看到一次重新登录，不得写成"无感升级"。

### 15.3 能力级叙述（与状态列分离）

叙述节按能力给结论（口令存储强度 / 认证失败语义 / 令牌生命周期 / 遥测脱敏分层 / 生产 fail-closed），每条引用 SECA ID，不复用状态词汇表的取值。

---

## 16. 既有测试处置清单（逐条声明，不搞"顺手改"）

**必须原样绿（SEC-A-006 的实体）**：`test_rbac_contract.py` 角色矩阵与 `enforce_permission` 文案；`test_typesafe_security_contract.py:231/236`；8 处 `/api/auth/login` 调用点（`test_typesafe_api_runtime.py:51`、`test_model_router_v23_contract.py:4580/4630`、`test_llm_usage_contract.py:1306`、`test_real_llm_failover_acceptance.py:686` 等）——**调用形式与口令字面量都不改**，改的是它们脚下的凭据来源（fixture 造 argon2id 行，§8.2 与 SECA-24）；`test_typesafe_api_runtime.py:91/119/148` 的 `/api/query` 键集合钉；`test_llm_egress_guard.py:5362` 的 D6 豁免面静态扫描（本规格不在 `rag.py`/`agent.py` 新增 httpx 或端点字面量）。

**改写 2 条**（各附"为何是收紧/换真源，不是放松"）：

1. `test_branding_contract.py:32`：从"字面量 `JWT_SECRET=change-me-…` 必须出现在 `.env.example`"改为"占位符形态必须出现，且企业形态启动守卫必须拒绝该值"。收紧：新增守卫断言，未删除任何现有保护。
2. `test_feishu_identity_contract.py:1707-1726`：从"直接写 `auth.USERS['viewer']`"改为走 `directory` 的测试注入接缝。换真源：`USERS` 已删除；`:1802` 那条"鉴权不读 JWT claim"的断言原样保留。

**新建**：失败语义、枚举四态、两层节流/锁定、`cv` 失效与"无 `cv` 即拒"、must_change 数据面阻断、身份文件合并不变量、全新安装与升级路径分离、Argon2 档位基准、脱敏双向、扫描门——此前**零覆盖**。

---

## 17. 已知限制（收口时命名，不得含糊）

| ID | 限制 | 影响 |
| --- | --- | --- |
| L1 | 锁定态对外不可区分 ⇒ 合法用户被锁时得不到提示 | 可用性代价；缓解路径是审计 `AUTH_LOGIN_LOCKED` + CLI status。账号锁定本身也构成"攻击者用错误口令锁死受害者"的 DoS 面（OWASP 已述），本规格接受该权衡，因锁定为 15 分钟自动过期而非人工解锁 |
| L2 | 无 HTTP `logout` / jti 撤销表 | 单令牌撤销粒度是"该账号全部令牌"，不是"某一个设备"。SEC-B/C 候选 |
| L3 | Argon2 档位受容器资源约束 | SECA-19 未过 ⇒ `BLOCKED`，不是 CONDITIONAL PASS。这台机器的内存是真实约束（V2.3 P0 已实证机器依赖前提） |
| L4 | 身份声明文件随镜像打包（`Dockerfile` 的 `COPY config ./config`）⇒ 改身份需重建镜像或挂载覆盖；且 `users.demo.json` 会**存在于企业镜像中**，只是不被加载 | 运维人体检查；不引入身份热加载（会造出第二个身份真源）。demo 用户名出现在镜像里不构成凭据泄露（用户名非秘密，且已在 Git 与既有测试字面量中），但 spec 不假装它不在——需要"镜像内零 demo 痕迹"的验收方应在打包阶段排除该文件并另立条目 |
| L5 | 基线套件数为 V2.3 的 961（本会话实测），非验收文档的 950 | 计数来源必须在收口时重新实测，两个历史数字都不得被当成本规格的基线引用 |
| L6 | Git 历史含 5 枚 digest 与明文口令（测试字面量） | 不重写历史（T6 裁定）；稳态代码/配置/库三处 0 命中。**这一格的"影响"此前写的是"旧口令永久失效"——那是过度声称，§20.7 的 S1 予以纠正**：0 命中说的是**存储形态**（那 5 枚泄露的**摘要**不再是任何一行的存法），而泄露的**明文口令**（§2 盘点的那 5 枚）在**每个账号完成强制改密之前仍然可以登录**，登进去之后还能把口令改掉——`must_change` 只挡**数据面**的 403，**不挡** `POST /api/auth/password/change`（§8.4 的白名单**刻意**包含它，否则没人能改密）。所以这一格的实际风险要靠**作废口令**消解，而不是靠措辞：运维动作 = 暴露部署之前先轮换那几枚弱出身账号（见验收文档 §12.2 与 §9.1 L6） |
| L7 | `credentials migrate` 的工件默认路径是**相对 cwd** 的 `data/legacy_credentials.json`，而库路径来自 `CONVERSATION_DB_PATH`；两者只在"未设置或同为相对路径"时天然同源 | 现网形态（`backend/.env:33` 的相对 `CONVERSATION_DB_PATH` + 镜像 `WORKDIR /app` + compose 只挂目录）确实同源，所以默认部署不踩；**改用绝对 `CONVERSATION_DB_PATH` 的 systemd 式部署**需要运维自行保证 cwd 或另传路径。失败方向是"静默不导入但 rc=0"，而 `reason` 会打印它实际解析到的绝对路径 ⇒ 人眼可诊，脚本不可诊（与"工件不存在"共用 rc=0 是 §11 规则一的有意选择）。本轮不加 `--path` 旗标（SEC-A 的 CLI 面保持最小），登记为 SEC-B 候选 |

## 18. 后续登记（SEC-B / SEC-C 候选，本规格不做）

- **G7** 摄取侧注入 / PII 本地兜底（→ 子规格 B）。
- **G14** `request_id` 全链路 + 按请求聚合的认证失败证据链（→ 子规格 C）。
- **G18** prompt 版本化（→ 子规格 C）。
- **G6** 多租户。
- `logout` / jti 细粒度令牌撤销（SEC-A 只有 per-account epoch，§17 L2）。
- `PASSWORD_DENYLIST`：条目来源、规模、大小写与 Unicode 归一、username 变体规则，连同实现一起做（§8.8 已把该要求从 SEC-A 移出，因为未定义的字典不是可验收的规则）。
- 专用 security CI job 与第三方扫描器（`gitleaks` / `pip-audit` / `bandit`）；SECA-20 的本地测试门是其前置而非替代。本地门扫的是**交付面当前文件集**，两件事它不做：**带 git 历史的检索**（§17 L6：已入库的 digest 洗不掉，只能靠作废口令收敛）与**未跟踪/被忽略文件的运行时材料**（`backend/.env` 就在这一格）。
- 身份热加载，或企业镜像打包阶段排除 `config/users.demo.json`（§17 L4 的"镜像内零 demo 痕迹"变体）。
- 水平越权与文档下载路径的安全测试（`SECURITY_REVIEW.md:35` 自列项）。
- **（SEC-A 已落一半，余下归 SEC-B）`backend-contracts` 的完整 CI 化**：SEC-A 已把 **SECA-20 扫描子集**接入该 job（装最小依赖 + pytest 步排在既有步之前，取证见 §20.8 卡 D）。仍未做的是：让其余 5 枚 SEC-A 契约文件（认证腿 / 改密 / 目录 / 凭据 / closure）也进 CI——它们模块级 import `app.main`，需要装齐 `backend/requirements.txt`（含模型栈）且该 job 的收集方式得从 `python -m unittest discover -s backend/tests`（`:22`，收不到裸 pytest 函数）换成 pytest。**同时须修一个早于 SEC-A 的事实**：该既有步在 main HEAD 上本就是红的（本地裸 venv 复现 132 tests / 3 failures / 26 errors；远端最近三次 CI 全部 failure，含 V2.3 RC 那一枚）。SEC-A 不扩这个范围，只做到"该跑的门真的在跑"。
- **（10h 按 §20.7 S3 增登记）把知识 OS 那两张既有落盘面（`app/knowledge_os.py:86` 的 `_write_json`、`:92` 的 `_append_jsonl`）纳入 `redact_for_persistence()` 的作用域** ⇒ §9.3 的切换点枚举要重写、AST 那两枚等式要从 **4→6**（`redact_for_persistence`）与 **17→15**（`redact_secrets`）同步改，并给出"知识 OS 落盘面里 `password`/`access_token` 类键必被抹"的正向用例。SEC-A 的范围是 audit + agent_trace 那四张面，纳入第三张落盘面属语义增补，走 SEC-B。

---

## 19. 决议记录与修订规则

本轮裁定（按对话顺序）：

| # | 议题 | 裁定 |
| --- | --- | --- |
| 1 | SEC-A 边界 | 只收认证与密钥基线；G7→B，G14/G18→C |
| 2 | demo 账号 | 双形态 fail-closed |
| 3 | 算法 | Argon2id + 新增 `argon2-cffi` + 重建发布镜像 |
| 4 | 认证加固深度 | 全量（失败语义 / 节流枚举 / 令牌生命周期 / 改密重置） |
| 5 | secret 卫生 | 全量（脱敏键名黑名单 / 启动守卫 / CORS 收紧 / **扫描以 pytest 契约测试落地，本轮只保证「本地」这道门**）。**不新增专用 security CI job**；`gitleaks` / `pip-audit` / `bandit` 归后续规格（§18）。**"由既有 backend CI job 执行"这半句是 §20.7 的 S2 纠正过的过度声称**：实测既有 `backend-contracts` job 没有依赖安装步、且跑的是 `python -m unittest discover` ⇒ 半数 SEC-A 门（裸 pytest 函数）今天在 CI 里不可达，CI 侧的依赖安装与 runner 形状是 **SEC-B 前置**（§18 已登记）。本裁定**没有**放宽扫描本身：门还是那道门，只是执行位置按实测写 |
| 6 | 存储与迁移 | 方案 C：身份与凭据分家 |
| 7 | 重哈希写盘失败 | 登录放行 + `AUTH_REHASH_DEGRADED` + legacy 行保留待收敛 |
| 8 | 生产形态开关 | `SECURITY_ENTERPRISE_MODE` 单开关，三守卫同生同死 |

规格级修正（用户提出，全部采纳）：

| # | 原表述 | 修正后 |
| --- | --- | --- |
| A | 档位出处写 RFC 9106 | **OWASP 最低推荐档**；RFC 9106 的 profile 是 2 GiB/64 MiB 两档，与本档无关 |
| B | "参数变更 ⇒ `v=19` 前缀版本变" | `v=19` 是 Argon2 算法版本 `0x13`，与项目版本无关；参数漂移走 `check_needs_rehash()`；三层版本分离 |
| C | "legacy hash 零持久化" | **迁移闭合后的稳态零遗留**；迁移期允许受限写入 |
| D | throttle 与 lockout 共用 `(username, ip)` | 拆两层：pre-hash throttle `(username, ip)` / 持久锁定按 `username` |
| E | "四面完全不可区分"含锁定路径 | 锁定路径**显式排除** timing 承诺，且不用 `sleep()` 修平 |
| F | `redact_for_persistence()` 作用于 `user_store` | 授权凭据库**例外**；redactor 只作用遥测持久化面 |
| G | 改密/重置未清 lock | 同事务 `failed_attempts=0` + `locked_until=NULL` |
| H | hash 与 cv bump 事务边界未声明 | 必须同事务，禁止提交窗口 |

**修订规则**：本规格一经 SDD 开工即冻结；后续发现只能走"新 issue → 规格修订节 → 新实现 → 新回归证据"，不得在实现轮顺手改措辞。Argon2 档位下调**必须**走本节的修订记录并重跑 SECA-19，禁止经 env 静默降档（SEC-A-008）。

---

## 20. 自审结论与计划切分预期

**占位扫描**：全文无 TBD / TODO / 待定；每条强度要求都给了可判定数值（`≥12`、`≤128`、`legacy_count=0`、P95 阈值、bucket 键、白名单 2 项）。

**一致性扫描（本轮已修 5 处）**：① demo 身份在 `users.json` 与"企业形态不载入 demo"矛盾 ⇒ 身份拆成 `users.json` + `users.demo.json`，形态差异由**是否加载该文件**决定（SEC-A-010 改写、§5、§8.5、SECA-07、L4 同步）；② 新口令强度不足误写 403 ⇒ 改 422，并说明为何不能污染 RBAC 的 403 语义；③ 矩阵行数口头记为 22 ⇒ 实为 23 行（16a/16b 分裂），第二轮复核后再增至 27 行（§20.1）；④ CLI 口令 env 两处命名不一致 ⇒ 统一 `CREDENTIALS_PASSWORD`，并新增"不得进 `.env`"的边界与扫描断言；⑤ §14 的 before 套件数直接引用 961 ⇒ 改为"开工时实测"，与 L5 一致。

**歧义扫描**：分派权威（`algorithm` 列，不嗅探）、timing 等价适用范围（四态，锁定路径显式排除）、`cv` 读表不读 claim、`cv` 缺失即拒、`legacy` 的唯一产地（升级路径读迁移输入；全新安装永不生产）、bootstrap 只写凭据不写身份——均已单句写死。

**范围检查**：本规格是一个内聚主题（认证与密钥基线），但体量对应 **8–10 个 SDD 任务**，可切分顺序预期为：`credentials.py` 原语与档位 → `user_store` 与 schema → `directory` 与身份文件拆分 → 迁移器与 closure 工具面 → 登录时序（两层节流/哑校验/渐进重哈希）→ 令牌 `cv` 与 must_change 门 → 改密/重置端点与 CLI → 脱敏分层与启动守卫 → 扫描门与 CI job → 容器基准与 release 收口。跨任务硬依赖只有一处：**must_change 门与渐进重哈希必须在同一轮落地**，否则会出现"legacy 已升级但可自由访问"的中间形态——该形态既是安全洞也是 SECA-10 的红。实现计划由 writing-plans 出，本文档不预先拆到任务粒度。

### 20.1 第二轮复核（用户）修正记录

七项规格级 + 两项确定性小修，全部已落进正文；文件拆分方案（`users.json` + `users.demo.json`）获批准并维持。

| # | 级别 | 原问题 | 修正落点 |
| --- | --- | --- | --- |
| 1 | P0 | closure 删掉迁移输入后，全新 dev/test 再也造不出 demo 凭据 ⇒ 与"默认 false 即零改动"冲突 | §8.2 把**升级工件**与**全新安装 bootstrap**彻底分开：fixture 造 argon2id 行（调用契约不变）/ CLI 造手工 dev；新增 SECA-04b、SECA-24、M19；§8.5 表与结尾句同步 |
| 2 | P0 | §8.4 写成 `must_change → authentication → authorization`，顺序在数学上不成立（must_change 存在凭据行里，需先完成认证） | 冻结为 `authentication → must_change → authorization`，§8.4 与 §9.2 同一链、措辞一致 |
| 3 | P0 | §8.7 用 `PENDING` 标记 `legacy_count>0`，而词表只有三值；且它根本不是外部依赖 | 改为 **`BLOCKED`**，并在 §15.2 补一条词表硬约束：内部待办不得伪装成外部阻塞 |
| 4 | P0 | SEC-A 前签发的 JWT 无 `cv`，行为未定义 ⇒ 留给实现就会长出 `if cv is None: allow()` 的绕过洞 | §7.5 冻结 fail closed；新增 SECA-09b 硬门 + M17 反向变异；§9.1 值域行、§14 证据行、§15.2 release note（一次强制重登录，不得称"无感升级"）同步 |
| 5 | P1 | `credentials_version` 同时被称作 schema/policy 版本又被每轮 bump，语义混用会诱发"schema 没变就不 bump" | §6.3 改定义为 **per-user credential/auth epoch**，三条版本轴分离表；列名保留不改 |
| 6 | P1 | 双身份文件缺 loader 不变量；`disabled` 被使用却无 schema 定义，且可能成为第四个可区分状态 | 新增 §6.4：合并顺序、重复 username 拒启动（禁 `{**prod,**demo}`）、`username` 与 `feishu_open_id` 合并后全局唯一、`enabled: bool = true`；`enabled=false` 归入 §7.3 哑校验统一失败面；新增 SECA-23 + M18 |
| 7 | P1 | §18 说 gitleaks/pip-audit 是后续，§19 决议 #5 却写"CI job"，两处冲突 | 统一为：SECA-20 是**普通 pytest 契约测试**，由既有 `backend-contracts` job 跑；SEC-A 不新增 security job、不引入第三方扫描器（§19 决议 #5、§18 同步） |
| 8 | 小修 | SECA-13 的"耗时分布验收"无阈值无公式，而 §20 声称所有要求可判定 | 硬门改为结构事实：**恰好一次 verify + 同一 profile + 同一实例**（调用面 spy）；latency 分布降为 §14 证据，明确不参与 GREEN/BLOCKED 判定（flaky 安全门会比没有门更糟——它会被 `skip`） |
| 9 | 小修 | "不命中内置小字典"未定义内容、来源与归一化 | 从 SEC-A 删除该要求，只留长度 ≥12 / ≤128 / ≠username（归一后比较）；`PASSWORD_DENYLIST` 连定义带实现登记 §18 |

同轮附带修正的交叉引用与编号冲突：§7.4 的代价条目由 §17 L2 改为正确的 L1；§6.1 的"SEC-A-008 列面测试"改标 SECA-08（`SEC-A-008` 已在 §4 指派给"Argon2 档位不可 env 调"，编号不得双占用）；矩阵行数与变异发数在 §15.1/§15.2 同步为 **27 行 / 19 发**（已按行核对，非心算）。

### 20.2 第三轮回写（写实现计划时发现，先改规格再动代码）

`docs/SECURITY_A_PLAN.md` 拆到 Task 6/7 的断言时发现：§9.1 把 `invalid_credentials` / `password_change_required` 写成了 **HTTP 响应 detail**，而本项目 401/403 面向用户的文案一直是中文（`docs/UI_COPY_GLOSSARY.md` 管辖展示层）。照原措辞实现，会让界面第一次出现英文 token——那是一次无人要求过的文案回归。

§9.1 因此改写为**两栏**：HTTP `detail` = 中文展示面（其中 401 的文案与现网**逐字相同**，新增的只是"四态共用同一组取值"这一事实）；审计 `detail` = 枚举 token。must_change 的机器可读信号是 §11 的布尔键与审计 token，不靠解析中文文案。§7.3、§7.4、§8.4、SECA-10 同步。

时序上这是"评审发现 → 回写规格 → 计划照规格写"，不是实现先落地再补文档；规格正文里保留了这条修正的来由，避免下一轮有人把它"改回更严的英文 token"。**该次回写已于 2026-09-25 获用户认可。**

### 20.3 第四轮回写（Task 6 实现期发现的盘点漏项）

§2 与 §11 原先写"全仓无登录响应键集合断言"。这是**盘点错误**：`test_feishu_identity_contract.py:1718` 的 `_LOCAL_KEYS` 在 `:1777/1778` 两处对嵌套 `user` 对象与 `/api/auth/me` 做等值键集合断言。我当时的依据是"8 处调用点只读 `access_token`"，那只覆盖了顶层。

两处已按实测改写。实质判定不变（顶层加键不破任何既有钉；`/me` 加键必须连带把期望集扩一枚，那是 §11 自己要求的契约变化，不是放松），但**Task 10 出验收文档时不得照抄旧口径**——照抄会让"本版唯一一处键集合变化"这句话在证据面变成可证伪的假话。

### 20.4 第五轮回写（Task 9 实现期的计量更正）

§2 与 §9.3 把"既有 `redact_secrets()` 调用点"记为 **28 处（响应面 8）**。Task 9 的 gate 要把这份盘点变成可复现的判据，而 AST 量出来的实际口径是：

- `app/security.py` **之外**的 `redact_secrets(...)` 调用点 **17 处**；
- 其中形态为 `return redact_secrets(...)`（响应面直接返回）**7 处**。

28 来自文本 grep：它把 `def redact_secrets` 本身、`app/security.py` 内部的自引用、以及注释与字符串里的提及都算成了调用点。两个数字不是矛盾，是**同一事实的两种量法**，而规格要的恰恰是可复现的那种。

**这条更正不放松任何约束。** §9.3 的实质要求是"`redact_secrets()` 的语义与其全部调用点一字不动"——该要求不变，判定由两枚**不同性质**的钉合起来承担（按**测试名**引用，行号会随实现漂动，本规格不再引行号）：`tests/test_secret_hygiene_contract.py::test_redact_secrets_semantics_are_unchanged` 是**行为探针**（两条断言，钉"形态照旧、且不因键名误伤"这类语义，不是字节比对）；同文件 `test_the_four_persistence_faces_use_the_persistence_redactor` 是 **AST 等式**（`17 == _call_sites("redact_secrets", …)`，替换/删除/新增任一形态都会红，同尺子另钉 `redact_for_persistence` 恰好 4 处）。把数字从 28 改成 17 不改变被保护的对象，只是让门测的是同一样东西。

同期把 §2 那行的**位置清单**换成实测坐标：原列 `agent_trace.py:91` 在 Task 9 切换后已不是 `redact_secrets` 落点（它是四张落盘面之一），而 `main.py:521/630`、`conversation_agent.py:532/601` 是规格早期的快照行号，现为 `main.py:738/847`、`conversation_agent.py:533/602`（本轮那处注释改动又推了一行）。数字与清单都是**盘点**而非判据：改判据要走规格修订，改盘点只要求它别再被下游照抄——Task 10 的验收文档正是唯一的照抄方。

另两处盘点同期回写：响应面 switch 后 `agent_trace.get_trace` 的返回不再经 `redact_secrets`（§2 的 8 处响应面 return 是切换前的快照），以及交付文档 `docs/**` 在 secret 扫描门上只上**材料形状面**（ prose 引用代码字面量是本项目的固有形状，逐行进豁免表等于把门换成一张豁免表）。这两点的判定细节属于计划与报告，规格侧只登记计量口径变更的来由。

### 20.5 第六轮回写（Task 10 收口时发现的规格空洞：升级路径没有生产入口）

Task 10a（镜像重建 + compose smoke + closure）实测报回一发实质缺陷：**`credentials_migration.import_from_artifact()` 在生产代码里零调用者**。lifespan 只跑 §8.5 那三道守卫，CLI 只有 `bootstrap-admin / reset / migration-status` 三格动作 ⇒ 规格 §8.2 描述的"升级路径导入 legacy"在实现里**没有任何入口可以发生**。实现者没有伪造证据，而是直接调那两个公共函数把升级链跑通并如实报为待裁定项。

追根是规格自己的洞，不是实现的漏写：§8.5 明写「生产代码不再自动导入 legacy」（当时为了关掉 M19 那发变异：全新安装缺行就顺手导入，把升级路径与全新安装重新混为一谈），而 §11 的 CLI 清单里从来没有导入动作。**"不许自动"与"也没有手动"同时成立，结果就是这条路径不可达。**规格里凡是写了"存在一个 X 路径"的段落，都必须能回答"谁执行 X"——这一条我此前只对了语义，没对触发者。

裁定（已回写 §11、§8.2 表格、§15.1 第 6 步）：**导入改为运维显式的 `credentials migrate`，启动仍然绝不自动导入**。四条规则的理由都在 §11。保留"不自动"那一半是刻意的：M19 与 SECA-04b 依赖它，而"每次重启都可能消费一份含凭据材料的文件"本身是更难解释的行为；显式动作换来退出码、可归档输出与明确的 actor。

**这条需要用户确认**：它是规格的一次实质增补（§11 多一枚 CLI 动作 + 对应测试），发生在 §19 冻结裁定之后、由收口阶段发现。SEC-A 的实现轮此前七轮回写都在动"措辞/口径/盘点"，这一轮第一次动"交付面"。

### 20.6 第七轮回写（Task 10 收口撞出的第二发：lifespan 从没建过凭据表）

Task 10f（给 V2.3 P0 补凭据接缝）报回一条它自己没敢裁的事实：在 P0 那条路上——`init_usage_db` 造出来的全新库——登录腿抛的是 `sqlite3.OperationalError: no such table: user_credentials`，也就是 500 而不是 401。控制器当场用 `TestClient` 复现（全新 `CONVERSATION_DB_PATH` + 启动完整 lifespan ⇒ `POST /api/auth/login` 500），两形态同病。

根因不在读路径的异常处理，而在**一句从没被写下的编排**：`user_store.py:105-113` 与 `credentials_migration.py:157-160` 两处注释都把建表的责任交给「启动编排 / CLI」，`ensure_user_credentials_schema()` 也确实是全模块唯一建表者——但 lifespan 里只有守卫与两枚 warmup，CLI 那三条动作只在运维敲过之后才生效。于是"全新安装"与"跑过一次 CLI 的机器"行为不同，而规格只描述过后者。

这条同时暴露了 §12 SECA-04b 那行的**空心形状**：它的判据是「企业形态零行 ⇒ 登录统一 401 且非 500」，用例先手工建表再断言——那条路今天成立、修完也成立，但它没经过"运维什么都没干"这个真实初始态。规格的文字承诺（企业列那句「非 500」）在部署面上是破的，而矩阵是绿的。**"表不在场"与"表在场但零行"是两格事实，验收只钉了后一格。**

裁定与回写：§8.5 增补"lifespan 在守卫之后建表（幂等），DDL 失败 fail-fast"这一条，读路径仍然不建表（另有一条已冻结的理由）。SECA-04b 的判定补上第二格：**不预建表的冷启动登录必须是 401 统一脸**。这仍是"规格先改、实现照规格写"的老顺序，且是本规格第二次由收口阶段反向补上自己没写完的编排义务（前一次是 §20.5 的导入入口）。两次同因：**规格里所有"由 X 负责"的句子都必须能在代码里指出那一行**。

### 20.7 第八轮回写（最终全分支评审判定的三处"规格式过度声称"纠正，Task 10h 落笔）

**先说这一节的性质**：§20.5、§20.6、§20.7 这三轮回写都不是"措辞/口径/盘点"那一类，而是**交付面变更或自我纠正类** amendment——§20.5 新增一枚 CLI 动作、§20.6 给 lifespan 加一次建表 DDL、§20.7 纠正三句**规格自己写过的过度声称**。**三处都需要用户确认（待用户拍板），与 §20.5/§20.6 的处置同一格**：它们发生在 §19 的"一经 SDD 开工即冻结"裁定之后，由收口阶段与终审反向往回改，控制器无权自己把它们读成"已获同意"。

同时要写清另一件事：**这一轮没有放松任何判据**。三处纠正的共同方向是**把声称缩回实测范围**（原文声称的覆盖面比代码与门真正做到的更宽），不是把要求调低；矩阵行数仍是 27，§12 那三行的判据文本（`豁免表 == 命中表` / `legacy_count=0` / 冷启动 401 非 500）一字未动。

- **S1 · §17 L6 的"旧口令永久失效"是假的安全声称**。来由：终审对着代码复核——`must_change` 的覆盖面是**数据面 403**，而 `POST /api/auth/password/change` 在 §8.4 的白名单里是**刻意**在场的（否则没人能完成那次强制改密）。于是握着 Git 历史里那 5 枚泄露**明文**的人，可以对仍带 `must_change=1` 的账号先拿到一枚票、再把口令改成自己的，顺带把真受害者锁在外面；终态镜像的 smoke S1 那一格证的正是这条路（`admin` 带 `must_change=1` ⇒ 登录 200 + token）。所以 L6 真正成立的是"**泄露的摘要不再是存储形态**"，而**不是**"泄露的明文失效"。改法：§17 L6 那格的"影响"列按此重写，验收文档 §9.1 L6 同口径（两处必须同步，否则下一轮又有人从规格里照抄旧声称）。风险消解路径仍是 T6 的"作废口令"，只是现在它附一条**运维动作**：暴露部署之前先轮换那几枚弱出身账号（验收文档 §12.2）。
- **S2 · §19 裁定 5 与 §12 SECA-20 的"与既有 `backend-contracts` CI job 同一道门"尚未成立**。来由：终审实测 `.github/workflows/ci.yml:10-25` 那枚 job **没有任何依赖安装步**，收集方式是 `python -m unittest discover -s backend/tests`（`:18`）⇒（a）`argon2-cffi`（`backend/requirements.txt:13`）没有任何 job 装过，SEC-A 的契约文件在 CI 里连 import 都过不去；（b）`unittest discover` 收不到**裸 pytest 函数**，而 SEC-A 六枚契约文件里这样的函数共 40 枚（`test_secret_hygiene_contract.py` 23 + `test_security_a_closure.py` 17），**扫描门自己就是其中一枚**。改法：两处口径改成"**本轮只保证本地这道门**"（本地实测 `10e-secret-gate.txt` ⇒ 46 passed / RC=0），CI 侧的 pip install + pytest runner 作为 **SEC-B 前置**登记进 §18。判据一字未改：仍然是"普通 pytest 契约测试 + 豁免表 == 命中表 + 不新增 security job + 不引入第三方扫描器"。
- **S3 · §9.3 的"切换点"枚举漏了两张已经在盘的落盘面**。来由：枚举写的是 audit 与 agent_trace 那四张面，而 `app/knowledge_os.py:86` 的 `_write_json`、`:92` 的 `_append_jsonl` 同样是落盘写手、至今仍走 `redact_secrets`（形态脱敏）。这**不是破掉的承诺**：SEC-A 承诺的切换面就是那四张，且 AST 那对等式（`backend/tests/test_secret_hygiene_contract.py:196` 的用例，`assert 4 == _call_sites("redact_for_persistence", …)` 在 `:211`、`assert 17 == _call_sites("redact_secrets", …)` 在 `:214`）会把"第五张面"当场判红——纳进来时 4→5/6、17 同步掉 ⇒ 不会静默漂移。改法：§9.3 加一条**点名这两个函数与两个坐标**的范围边界说明，§18 增一条"纳入那两张面 ⇒ 钉 4→6 并须重写枚举"。**没有**为了让它看起来像承诺而扩写 §9.3 的切换面。

**顺序声明**：本轮同样是"规格先改、文档与实现照规格走"。§20.7 落笔在前，验收文档 rev 2 的对应六句在后（`.superpowers/sdd/SECURITY_A_PLAN/task-10h-report.md` 逐条记录实测）。三处的实测证据（CI 那四枚坐标、AST 那两枚等式、smoke S1 的 200）都是本轮自己量的，不是引用上一轮的转述。

### 20.8 amendment 卡片（用户 2026-09-27 裁定的五段式补齐 + CI 接入）

用户 2026-09-27 **批准 §20.5 / §20.6 / §20.7 回写**，并定性质为「**conformance correction：判据没降低，但规格第一次在实现阶段被修订**」，要求每条按"原规格 → 实测反例 → 修订后的规范 → 判据是否变化 → 对应回归证据"留痕，不得改写成仿佛最初就这么设计。以下逐张补齐，随后是本裁定附带落地的 CI 接入。

**卡 A · §20.5 导入入口**
- 原规格：§8.2 表"只有升级路径（存在 `data/legacy_credentials.json`）才导入 legacy"；§8.5"生产代码不再自动导入 legacy"；§11 CLI 清单只有 `bootstrap-admin | reset | migration-status`。
- 实测反例：`credentials_migration.import_from_artifact()` 在 `app/**` **零生产调用者**（Task 10a 报回，控制器 grep 复核）⇒ 升级路径在代码里不可达；"不许自动"与"也没有手动"同时成立。
- 修订后的规范：导入 = 运维显式 `credentials migrate`（四条规则见 §11）；**启动仍绝不自动导入**。
- 判据是否变化：**否**。SEC-A-004 仍是 `legacy_count=0` 可判定；M19 与 SECA-04b 依赖的"不自动"那一半原样保留。
- 回归证据：`tests/test_credentials_contract.py::LegacyImportCliTests`（10c 修复轮后共 9 枚，企业拒绝/幂等/无工件/不碰明文/退出码各一枚以上）；证伪：删 `cli.py` 建表那一步 ⇒ 2 红（ virgin 库用例）。

**卡 B · §20.6 lifespan 建表**
- 原规格：§8.5 企业列"`user_credentials` 无行 ⇒ 任何登录统一失败（fail-closed，**非 500**）"；`user_store.py:105-113` 注：建表"由启动编排 / CLI 调"。
- 实测反例：lifespan 从没调过建表 ⇒ 全新安装每次登录抛 `sqlite3.OperationalError: no such table: user_credentials`，控制器以 `TestClient` 复现为 **HTTP 500**（两形态同病）；矩阵 SECA-04b 当时是绿的，因为它的用例先手工建了表。
- 修订后的规范：lifespan 在守卫之后、warmup 之前幂等 `ensure_user_credentials_schema()`；DDL 失败按守卫既有形状 fail-fast；**读路径仍然不建表**。SECA-04b 补第二格：不预建表的冷启动必须是统一 401。
- 判据是否变化：**否**（只是把"部署态可达"补成真的可满足）。
- 回归证据：`tests/test_security_a_closure.py` 的 10g 六枚（冷启动 401 非 500、企业零行、boot 建表而读不建表、幂等、DDL 失败拒绝启动）；`tests/test_secret_hygiene_contract.py::StartupGuardLifespanTests::test_a_refused_boot_creates_nothing`（顺序契约，证伪＝两步调换即红）；部署面 `scripts/sec_a_fresh_boot_probe.py` 在终态镜像空卷上重跑，输出与转录逐行相同。

**卡 C · §20.7 三句过度声称的撤回**
- 原规格：§17 L6"旧口令永久失效"；§19 裁定 5 / §12 SECA-20"与既有 `backend-contracts` CI job 同一道门"；§9.3 落盘面枚举只列 audit/agent_trace 两张。
- 实测反例：①`must_change` 不挡改密腿 ⇒ 历史里的明文在账号自行改密前仍可登录并改密（终态 smoke 的 `admin` 登录 200 就是这一格）；②终审实测 `ci.yml` 那枚 job 无依赖安装步且用 `unittest discover`（本地裸 venv 复现：132 tests / 3 failures / **26 errors**，早于 SEC-A）⇒ 扫描门在 CI 里根本没跑；③`knowledge_os.py:86/92` 两张落盘写手仍走形态脱敏。
- 修订后的规范：L6 只声称"泄露摘要不再是存储形态"，风险要靠**作废口令**消解并附运维动作；SECA-20 当时缩回为"只保证本地"；§9.3 点名那两张面为**范围边界**（不是破掉的承诺，AST 等式会把第五张面判红）。
- 判据是否变化：**否**，三处都是把声称缩回实测范围；矩阵仍 27 行，判据文本一字未动。
- 回归证据：`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` §9.1 L6/§12.2、§6 第 6 步、§7.1/§7；卡 D 的 CI 实测件。

**卡 D · 本裁定附带落地的 CI 接入（SECA-20 从"未成立"变成"CI 真执行"）**
用户裁定"保持规格、修 CI"，不为此新造 security pipeline。落地与取证：
- `.github/workflows/ci.yml` 的 `backend-contracts` 新增两步：**step 3 装扫描门自己的最小依赖**（pytest + pydantic + pydantic-settings + argon2-cffi），**step 4 跑扫描子集**；两步刻意排在既有 `unittest discover`（step 7）**之前**——GitHub 一步失败即中止后续步骤，排在后面的门等于永远不跑。
- 子集选择：`-k "tracked_files or exemption_table or states_why or planted_credential or exempt_line"`（5 枚）。这五枚是交付面扫描的完整闭环（命中↔豁免表相等、豁免必须说清"为什么不是材料"、植入即红、同一行第二枚不被静音）。
- **本地等价执行取证**（干净 venv，零历史依赖，仓库根 cwd，命令与 CI 逐字相同）：基线 `5 passed in 1.05s` → 植一枚真形状假凭据（`JWT_SECRET = "plaintext-material-…"` + 一枚 `sk-live-…`）`2 failed / rc=1` → 删除探针后 `5 passed / rc=0`，探针文件不存在且 `git status --porcelain` 无残留。
- **取证过程本身暴露一条门的性质，值得留档**：第一次植入我用了测试夹具惯用的**拼接**写法（`"plaintext-" + "material…"`），门**不红**——那正是夹具躲门的合法形状，也是 §18 坚持要一枚带 git 历史的第三方扫描器的理由。任何"门能红"的声明都必须用连续字面量取证，否则证的是夹具的豁免通道。
- 仍然成立的部分诚实保留：其余 5 枚 SEC-A 契约文件（认证腿/改密/目录/凭据/closure）**不在 CI 里跑**——它们模块级 import `app.main`/`app.auth`，需要完整 `requirements.txt`（含模型栈），且那枚既有 `unittest discover` 步在 main 上早已红。⇒ §18 的 SEC-B 前置改写为"把 `backend-contracts` 换成 pytest runner 并装齐依赖，让六枚契约门全进 CI；同时修既有步的红（早于 SEC-A）"。
