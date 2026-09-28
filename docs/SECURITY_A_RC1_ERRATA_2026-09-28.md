# SECURITY-A RC1 ERRATA — `security-a-rc1` 不可交付（2026-09-28）

| 字段 | 值 |
| --- | --- |
| tag | `security-a-rc1`（annotated，对象 `33a8202b863ce0ce1ae4e84014eab54af98a1300`） |
| commit | `7cc5efc0460abb01171c20cee61ef01bf5282a3d` |
| finding | `resolve_for_user()` 按 dict 接口取 `feishu_open_id`，而该参数已由 SEC-A 自己换成 pydantic 模型 `UserIdentity` ⇒ `AttributeError` |
| repro | 干净签出 + `pytest -k login_payload` ⇒ FAILED（命令与输出见 §3） |
| cause | 验收读数取自带**未提交**兼容修复的工作树，而非 tag 所指树 |
| impact | `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` 的 `CONDITIONAL PASS` 对该 tag **不成立**；tag 不是可交付 RC |
| disposition | `security-a-rc1` = **ERRATA ISSUED / SUPERSEDED / NOT SHIPPABLE**；不可变、不 amend、不移位 |
| action | `SEC-A-CORR-01`（最小修正面）→ 未来 `security-a-rc2` |
| 签发人 | 控制器（本会话），经用户 2026-09-28 裁定 |
| 关联 | `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` 顶部 ERRATA 块；`docs/ENTERPRISE_B0_ACCEPTANCE_2026-09-28.md` §10.1 |

## 1. 这张卡不做什么

- **不删、不改**原验收报告里的任何读数。"1316 passed / 36 warnings / 1133 subtests，两 cwd 逐位相同"
  是本会话真实量到的结果，保留为**历史测量**，只是它测量的对象不是被认证的那棵树。
- **不动 tag**。不 amend、不移位、不重写历史（与 SEC-A 对 §3 T6 的既有裁定同一立场）。
- **不宣布 SEC-A 的判据作废**。缺陷是一行接口失配，不是 Argon2 档位、认证面语义、令牌生命周期、
  两层节流或扫描门的问题；§20 的八轮回写与 19 发变异台结论不受本卡影响。

## 2. 缺陷本体

已提交树（`7cc5efc`）中：

```python
# backend/app/identity/__init__.py:59-66
def resolve_for_user(username: str, role: str, record: dict) -> FeishuGrant | None:
    """Grant for one local account. None keeps today's local-only semantics."""
    from app.config import settings
    open_id = str(record.get("feishu_open_id") or "")
```

而 SEC-A 之后 `record` 的实际类型是 `app/directory.py:52` 的：

```python
class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str; display_name: str; role: str
    feishu_open_id: str | None = Field(default=None, min_length=1)
    enabled: bool = True
```

调用方传的正是这个模型实例：`backend/app/auth.py:358` 与 `:442` 都写
`resolve_for_user(identity.username, identity.role, identity)`。
`UserIdentity` 是 pydantic 模型、不是 `Mapping`，没有 `.get()` ⇒ 每次调用抛
`AttributeError`，登录腿与 `/me` 一起炸。

**为什么会漏**：签名写的是 `record: dict`，而这个模块的注释、类型提示与真实数据流早在 SEC-A 的
身份/凭据分家里就变了；类型提示不是运行时契约，`python -m pytest` 也不会因为签名撒谎而失败。
工作树里那份未提交的飞书桥接改动顺手把它改成了 `getattr(...)`，于是本地"从未红过"。

## 3. 复现（干净签出，非工作树）

```bash
T=$(mktemp -d) && git clone --no-local -b main <repo> "$T/r" && cd "$T/r" && git checkout 7cc5efc
python -m pytest backend/tests/test_rbac_contract.py -q -k login_payload
```

实测输出（控制器 2026-09-28 本机执行）：

```
…\site-packages\pydantic\main.py:1042: AttributeError
FAILED backend/tests/test_rbac_contract.py::CapabilityMatrixTests::test_login_payload_exposes_canonical_role_and_permissions
1 failed, 14 deselected in 1.76s
```

且该树 `backend/app/identity/__init__.py:63` 逐字为 `open_id = str(record.get("feishu_open_id") or "")`。

第二次独立证据来自远端：B0 主门第一次真跑全部 1332 枚的 run `36436145777` 中，
113 条 `FAILED|ERROR` 里 **111 条**是同一句
`AttributeError: 'UserIdentity' object has no attribute 'get'`，另 1 条"冷启动后登录不上 / 500"
是它的下游。

## 4. 修正面（`SEC-A-CORR-01`）

```text
backend/app/identity/__init__.py        ← 唯一的产品代码改动面
+ 直接需要的测试与文档（结构钉 §5）
```

原则：**从已提交树重新生成最小 patch**，不搬运工作树里那两份飞书未完成改动的其余 diff；
按 `UserIdentity` 的属性接口取值，不再假装它是 dict。

## 5. 必须留下的结构钉

修正不能只让测试变绿，要把"这个接口失配"本身钉住，否则同类改动还会回来：

- `resolve_for_user(UserIdentity(...))` **不得**对 `Mapping.get` 有调用面（AST 级判据，
  而不是只测一次 happy path）。
- 一个 `feishu_open_id=None` 的账号必须走"本地语义"（返回 `None`），**不是**异常。
- 反向保真：`getattr` 的默认值不能把"字段缺失"和"字段为 None"混成同一件事而放过本该拒绝的形态。
- 干净签出复验：`login_payload` / RBAC contracts / Feishu identity contracts / SEC-A contracts /
  全量两 cwd / 远端 `backend-contracts`。

## 6. 方法论教训（进 B0 侧台账，不进 SEC-A 判据）

**宿主工作树绿 ≠ 已提交树绿 ≠ 干净签出绿 ≠ CI 绿。** 这四者此前被当成一件事，是这次误认证的根。
今后任何封版读数必须标注它取自哪一层；SEC-A 那三格"两 cwd 相同"读数的层级是**工作树**，
本卡已把这一点写进原报告顶部而不是抹掉它。
