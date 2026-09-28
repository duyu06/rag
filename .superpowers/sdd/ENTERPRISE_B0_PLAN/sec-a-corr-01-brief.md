# SEC-A-CORR-01 任务简报（最小修正 `security-a-rc1` 的接口失配）

**来源裁定**：`docs/SECURITY_A_RC1_ERRATA_2026-09-28.md` 与台账 **R26**（用户 2026-09-28）。
**这不是 B0 的一部分**，也不得被写成 B0 的成果；它是 SEC-A 的 corrective 修正面。

## 目标

让**已提交树**在干净签出下可认证。缺陷本体：`backend/app/identity/__init__.py` 的
`resolve_for_user()` 用 dict 接口 `record.get("feishu_open_id")` 取一个
`app/directory.py:52` 的 pydantic 模型 `UserIdentity`（`extra="forbid"`，字段
`feishu_open_id: str | None`）⇒ `AttributeError`，登录腿与 `/me` 一起炸。

## 允许的改动面（越界即任务失败）

| 允许 | 用途 |
| --- | --- |
| `backend/app/identity/__init__.py` | 唯一产品代码改动 |
| `backend/tests/test_feishu_identity_contract.py` | 结构钉的新增位置 |
| `docs/SECURITY_A_SPECIFICATION.md` | 只在需要登记 §20.x 追加轮时改，且必须走五段式修订卡 |
| `.superpowers/sdd/ENTERPRISE_B0_PLAN/**` | 台账与报告 |

**禁止**：`backend/app/identity/README.md`（工作树里那堆 diff 属于未完成的飞书桥接文档改写，
**不得**随本次修正发布）；`backend/app/**` 任何其它文件；`backend/requirements.txt`；
`docs/ENTERPRISE_B0_*`；两枚 tag；`.gitignore`。

## 实现要求

从**已提交树**重新生成最小 patch，不要整搬工作树 diff。工作树里 `__init__.py` 的当前 diff
恰好是最小面（`from typing import Any` + 签名 `record: Any` + docstring + 一处
`getattr(record, "feishu_open_id", "")`），可作参照，但你要**逐 hunk 确认它没有夹带别的意图**。

设计原则（照工作树那句注释保留，它是对的）：用 `getattr` 而非 `isinstance`——
身份类型由 `directory` 拥有，`identity` 这层反过来依赖它的字段集就会变成第二个认身份的地方；
`directory` 加字段时不必回来改这里，缺字段时照旧退成"没接飞书"（`None` = 本地语义），不是异常。

## 必须新增的结构钉（AST 级，不是 happy path）

这次能漏掉的根因是"签名写 `dict`，没人验运行时类型"，所以修正必须把**接口形状**钉住：

1. **`Mapping.get` 调用面钉**：扫 `backend/app/identity/__init__.py` 的 AST，断言
   `resolve_for_user` 函数体内不存在 `<expr>.get(...)` 形式的属性访问（或等价：不存在名为 `get`
   的 `Call.func.attr`）。理由要写在注释里：类型提示不是运行时契约，`pytest` 不会因为签名撒谎而失败，
   所以只能钉"调用形状"。
2. **`None` 走本地语义**：`UserIdentity(feishu_open_id=None)` ⇒ `resolve_for_user(...)` 返回 `None`
   且不抛。
3. **缺失字段与 None 不得混成同一件事而放过应拒的形态**：`getattr` 默认值不能把"账号没有该字段"
   和"字段存在但为空串"都静默变成同一个通过路径。用真实 `UserIdentity` 构造（`extra="forbid"`
   本身就拒未知键，这枚钉要落在**行为**上：空串 open_id 不得发请求）。
4. **反向保真**：断言这枚结构钉在把 `getattr` 改回 `record.get` 时会红（本地验证即可，不落盘）。

## 验收（逐条取读数，写进报告）

1. 干净签出复现修复前失败：`git clone` 到临时目录、`git checkout 7cc5efc`、
   `pytest -k login_payload` ⇒ FAILED（作为"修的是真问题"的证据）。
2. 工作树修复后：`backend/tests/test_rbac_contract.py -k login_payload` ⇒ PASSED。
3. 定向回归四组：RBAC contracts、Feishu identity contracts、SEC-A contracts
   （`test_credentials_contract.py` / `test_secret_hygiene_contract.py` /
   `test_authentication_leg_contract.py` / `test_password_lifecycle_contract.py`）、
   以及 B0 的门模块 `test_ci_gate_contract.py`（必须仍 16 passed / 1332 收集）。
4. 全量套件两 cwd，逐格标注 cwd 与 `.env` 状态。
5. 远端 `backend-contracts`：由控制器在 push 后取 step 级读数，**不由本任务主张**。

## 硬约束

- **不做任何 git 写操作**（不 add / 不 commit / 不 push / 不 stash / 不 checkout 移动 HEAD）。
  提交与推送由控制器统一执行。
- 不改判据、不加 skip/xfail、不放宽既有断言；不得为了让套件绿而改动 `backend/app` 之外的产品代码。
- 不动 `security-a-rc1` 与 `model-router-v2.3-rc1`。
- 不派子代理。
- 任何"修不动/判据与规格打架"的情况：停下报告，不要就近改一句让它过。

## 交付物

`.superpowers/sdd/ENTERPRISE_B0_PLAN/sec-a-corr-01-report.md`，**增量写**（每步跑完就追加，
不要最后一次性补，长会话会被截断）。内容：逐 hunk 的最小面确认、四枚结构钉的代码与各自的证红读数、
修复前干净签出的失败原文、四组定向回归原文、全量两格读数（含 cwd/`.env` 标注）、
以及"本修正没有发布 README 那堆 diff"的显式证明（`git status` 里该文件仍为 M 且未 staged）。
