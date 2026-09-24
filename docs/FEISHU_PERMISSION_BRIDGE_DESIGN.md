# 飞书权限桥接（Permission Bridge）设计

日期：2026-09-22 · 状态：已批准（方案 A）· 关联：`docs/RBAC_UX_DESIGN.md`

## 1. 目标与边界

为 rag 后端预留企业身份源接口，首期实现飞书（Lark）权限匹配：以飞书侧的**部门/组织架构**与**群成员身份**为信号，同时决定用户的**平台角色级别**（admin/user/viewer）与**知识库可见范围**。

边界决议（已与需求方确认）：

- 对接深度：**接口定义 + 真实飞书 API 客户端**（按官方文档实现），不含飞书 OAuth 登录跳转；无凭证环境下全部用 mock 验证。
- 匹配输出：角色级别 + 知识库白名单，均由飞书主导（开关开启时）。
- 失败策略：**缓存优先，失败收紧**——绝不在飞书不可用时放大权限。
- 中文化、界面文案与本设计无关，独立推进。

## 2. 架构

新增包 `backend/app/identity/`，四个模块各司其职：

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `base.py` | `PermissionSource` 抽象接口与 `ExternalIdentity`/`FeishuGrant` 数据模型；未来 OIDC/企微只需新增 provider 实现 | 无 IO |
| `feishu_client.py` | 真实飞书客户端：tenant_access_token → 用户部门 → 部门名 → 用户所在群；transport 构造注入 | `base`、httpx |
| `mapper.py` | 纯函数：`ExternalIdentity + rules → FeishuGrant | None` | `base`、规则配置 |
| `resolver.py` | 编排：TTL 缓存、失败收紧链、审计事件 | 前三者、`app.audit` |

### 2.1 feishu_client

按飞书开放平台服务端 API：

1. `POST {base}/open-apis/auth/v3/tenant_access_token/internal`（app_id + app_secret）换取 tenant_access_token；进程内缓存，按响应 `expire` 提前 60s 刷新。
2. `GET {base}/open-apis/contact/v3/users/{open_id}` 读取用户 `department_ids`。
3. `GET {base}/open-apis/contact/v3/departments/{department_id}` 解析部门名（用于按名称匹配与展示）。
4. `GET {base}/open-apis/im/v1/chats`（分页 `page_token`）取群列表及 `chat_id`/`name`。注意：tenant_access_token 身份下该接口返回的是**机器人所在群**，因此"群成员身份"的实际语义是"用户与机器人同群的交集"（需配合群成员接口 `GET /open-apis/im/v1/chats/{chat_id}/members` 逐群确认成员，群数量由规则配置里的 chat 白名单限定，避免全量扫群）。无凭证时该链路由 mock 验证。

约束：单次请求超时默认 3s；**失败不自动重试**（重试压力交给缓存策略）；HTTP 层封装成可注入 transport，单测用假实现。

### 2.2 mapper 与规则配置

规则文件 `backend/config/feishu_permissions.json`（路径可配置）：

```json
{
  "rules": [
    {
      "match": { "department_ids": ["od-hr-001"], "department_names": [], "chat_ids": [], "chat_names": [] },
      "grant": { "access_role": "user", "knowledge_base_ids": ["kb_hr_private", "kb_public"] }
    },
    {
      "match": { "chat_names": ["知识库管理员群"] },
      "grant": { "access_role": "admin", "knowledge_base_ids": ["*"] }
    }
  ]
}
```

语义：

- 一条规则命中 = 一次授予；**多条命中时角色取最高（admin > user > viewer），知识库白名单取并集**；`"*"` 表示全部。
- 收紧语义只用于失败回退，不用于规则合并。
- 飞书正常返回但零命中：视为正常“无授予”，走本地语义（见 §3），**不标记降级**。

### 2.3 resolver

- 缓存：进程内 `username → (grant, fetched_at)`，TTL 默认 900s；过期条目标记为 `stale` 保留一份用于降级。
- 解析链（`enabled` 时）：新鲜缓存 → 实时拉飞书 → 成功则写缓存返回；失败则 stale 缓存（标 `degraded`）→ 再失败则“本地角色 + 仅公共知识库”，并审计 `FEISHU_PERMISSION / DEGRADED`。
- `username → 飞书 open_id` 桥接：本地用户记录预留 `feishu_open_id` 字段；无该字段者直接走本地语义，不发请求。

## 3. 与现有代码的接缝

- `Settings`（`app/config.py`）新增：`feishu_permissions_enabled=False`、`feishu_app_id`、`feishu_app_secret: SecretStr`、`feishu_base_url="https://open.feishu.cn"`、`feishu_timeout_seconds=3.0`、`feishu_cache_ttl_seconds=900`、`feishu_rules_file`。
- `CurrentUser` 增加可选 `grant` 字段；`permissions` 计算字段优先按 `grant.access_role` 推导，无 grant 时维持现状。
- `auth.py:require_user` 解析 JWT、查本地用户后调用 `resolver.resolve(username)` 注入 grant（仅开关开启时）。
- `knowledge.py:resolve_requested` 增加可选 effective 白名单参数：有 grant 时以 `grant.knowledge_base_ids` 为权威，否则维持部门规则。下游 `_allowed_ids`、检索前过滤、`enforce_permission` 消费的都是 effective 结果，无需逐点改动。
- 审计事件复用 `record_event` 与 `redact_text`；secret 与 token 不落日志、不进响应。

## 4. 数据流

```
请求 → require_user → JWT → 本地用户
  ├─ 开关关 → 现状行为（零变化）
  └─ 开关开 → resolver.resolve(username)
        缓存新鲜? ─是→ 直接使用
        └否→ feishu_client 拉取 → mapper 匹配 → 写缓存
             └异常→ stale 缓存(degraded) → 本地+公共库(degraded·审计)
  → CurrentUser(+grant) → enforce_permission / _allowed_ids / 检索过滤
```

## 5. 错误处理

| 场景 | 结果 | 审计 |
| --- | --- | --- |
| API 超时/HTTP 错误/token 失败，有新鲜或 stale 缓存 | 用缓存（stale 时标 degraded 语义） | `FEISHU_PERMISSION / DEGRADED` |
| 同上，无缓存 | 本地角色 + 仅公共知识库 | `FEISHU_PERMISSION / DEGRADED` |
| 飞书正常返回但无匹配规则/用户 | 本地角色 + 本地部门可见集 | 无 |
| 用户未配置 `feishu_open_id` | 纯本地语义，不发请求 | 无 |
| 规则配置文件缺失/损坏（开关开启时） | 启动期 fail-fast 报错；运行期不因规则热更新失败而提权 | 启动日志 |

## 6. 测试与验收

- `mapper`：纯函数单测，覆盖单条/多条命中、角色取高、并集、`"*"`、零命中。
- `resolver`：FakeTransport 覆盖命中缓存、stale 降级、无缓存收紧、未配置 open_id 直通本地。
- `feishu_client`：假 httpx 验证四个端点请求结构、token 缓存与分页。
- 回归护栏（TestClient）：`enabled=False` 时断言既有 18 项验收行为逐一不变（导航、403 措辞、ACCESS/DENIED 审计、KB 白名单）；`enabled=True` + mock 断言角色/范围按飞书生效、DEGRADED 可审计、降级不放权。
- 接入文档：`backend/app/identity/README.md` 说明新增 provider（OIDC/企微）与凭证配置步骤。

## 7. 明确不做（YAGNI）

- 不做飞书 OAuth 登录跳转、事件订阅（permission 变更推送）、后台同步快照表（方案 C 留作演进路径）、多身份源并存仲裁。
