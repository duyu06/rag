## Task 10: 收口（镜像重建 → 容器基准 → 变异台 → closure → 验收文档）

**Files:**
- Create: `backend/tests/test_security_a_closure.py`
- Create: `.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`
- Create: `.superpowers/scripts/run_argon2_benchmark.py`
- Delete: `backend/data/legacy_credentials.json`（closure 的最后一步，且必须在 `legacy_count=0` 之后）
- Create: `docs/SECURITY_A_ACCEPTANCE_2026-09-25.md`

- [ ] **Step 1: 重建发布镜像并做双向 import 探针**（release gate 第 1、6 步）

```bash
cd /e/xiangmu/rag
docker compose build backend
docker compose up -d backend
sleep 3 && docker compose ps backend
docker exec rag-backend-1 python -c "import argon2, credentials_probe" 2>/dev/null || \
docker exec rag-backend-1 python -c "
import argon2
from argon2 import PasswordHasher
ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
h = ph.hash('container-probe 123')
print('argon2 import OK', ph.verify(h, 'container-probe 123'))
"
```
Expected: 打印 `argon2 import OK True`。装不上 wheel ⇒ **SECA-19 = `BLOCKED`**，不得改用宿主结果凑数、不得降档（SEC-A-008），并在验收文档记录 wheel 与镜像层的确切失败信息。

- [ ] **Step 2: 容器内 Argon2 基准**（SECA-19；写 `.superpowers/scripts/run_argon2_benchmark.py`）

```python
"""在发布容器内实测 Argon2id 档位的延迟与内存，作为 SECA-19 的判据。

预算（规格 §12 SECA-19）：串行 P95 ≤ 1500ms；ARGON2_MAX_CONCURRENT_OPS 并发 P95 ≤ 3000ms；
单次运算峰值 RSS 增量 ≤ 256 MiB。不满足 ⇒ BLOCKED，降档必须走规格修订。
"""

import json
import resource
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher

TIME_COST, MEMORY_COST, PARALLELISM = 2, 19456, 1
SERIAL_RUNS, CONCURRENT_RUNS, WORKERS = 50, 32, 2
BUDGET = {"serial_p95_ms": 1500.0, "concurrent_p95_ms": 3000.0, "rss_delta_kib": 256 * 1024}

ph = PasswordHasher(time_cost=TIME_COST, memory_cost=MEMORY_COST, parallelism=PARALLELISM)
password = f"benchmark-password {time.time_ns()}"
encoded = ph.hash(password)
baseline_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def one(_: int) -> float:
    started = time.perf_counter()
    ph.verify(encoded, password)
    return (time.perf_counter() - started) * 1000.0


def p95(samples):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


serial = [one(i) for i in range(SERIAL_RUNS)]
with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    concurrent = list(pool.map(one, range(CONCURRENT_RUNS)))
peak_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - baseline_kib

report = {
    "profile": {"time_cost": TIME_COST, "memory_cost": MEMORY_COST, "parallelism": PARALLELISM},
    "environment": sys.platform,
    "serial": {
        "runs": SERIAL_RUNS,
        "p50_ms": round(statistics.median(serial), 1),
        "p95_ms": round(p95(serial), 1),
    },
    "concurrent": {"runs": CONCURRENT_RUNS, "workers": WORKERS, "p95_ms": round(p95(concurrent), 1)},
    "peak_rss_delta_kib": int(peak_kib),
    "budget": BUDGET,
}
report["verdict"] = "GREEN" if (
    report["serial"]["p95_ms"] <= BUDGET["serial_p95_ms"]
    and report["concurrent"]["p95_ms"] <= BUDGET["concurrent_p95_ms"]
    and report["peak_rss_delta_kib"] <= BUDGET["rss_delta_kib"]
) else "BLOCKED"
print(json.dumps(report, indent=2, ensure_ascii=False))
```

串行 50 次 + 并发 32 次/2 worker 的选择理由要写进报告注释：`ARGON2_MAX_CONCURRENT_OPS=2` 是闸门上限，基准必须在**闸门满配**下测，否则测出来的是理想值而不是最坏值。

```bash
cd /e/xiangmu/rag
docker compose cp .superpowers/scripts/run_argon2_benchmark.py backend:/tmp/bench.py
docker compose exec backend python /tmp/bench.py | tee .superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-container.json
python .superpowers/scripts/run_argon2_benchmark.py > .superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-host.json
```
Expected: 容器报告 `verdict` 字段可读。**容器数才是判据**，宿主数只作为对照（V2.3 P0 的机器依赖教训）。

- [ ] **Step 3: compose smoke 四场景**（release gate 第 6 步）

```bash
cd /e/xiangmu/rag
API=http://localhost:8001
# 场景 1：升级路径登录（容器内 DB 若为旧库，先跑迁移导入）
docker compose exec backend python -m app.cli credentials bootstrap-admin --username admin  # 期望 rc=2：企业形态或身份缺失时不得建身份
docker compose exec backend python -m app.cli credentials migration-status
curl -sS -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | tee .superpowers/sdd/SECURITY_A_PLAN/smoke-01-login.json
# 场景 2：错口令（与场景 1 的未知账号必须同形）
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"definitely-wrong-123"}'
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d '{"username":"nosuchaccount","password":"definitely-wrong-123"}'
# 场景 3：must_change 数据面阻断（若场景 1 返回 password_change_required=true）
TOKEN=$(python -c "import json;print(json.load(open('.superpowers/sdd/SECURITY_A_PLAN/smoke-01-login.json'))['access_token'])")
curl -sS -o /dev/null -w '%{http_code}\n' $API/api/knowledge-bases -H "Authorization: Bearer $TOKEN"
# 场景 4：锁定（错口令连打到 ACCOUNT_MAX_FAILED_ATTEMPTS 次后，正确口令也必须 401）
```
Expected: 场景 2 两条都 401 且响应体逐字相同；场景 3 为 403（`password_change_required`）或 200（该账号已改过密）——两者都要在验收文档里写明当时是哪一种、为什么。

- [ ] **Step 4: 变异台 19 发**（写 `.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`）

harness 骨架（**必须**字节安全：读字节 → 替换 → 写 → 跑定向测试 → 还原 → sha1 核对，`finally` 里也还原）：

```python
"""SECA 变异台：每一发都必须杀至少一条测试，否则那条测试是死代码。"""

import hashlib
import subprocess
import sys
from pathlib import Path

BACKEND = Path("E:/xiangmu/rag/backend")

# (代号, 相对路径, 原文片段, 变异后片段, 期望红的测试节点)
MUTATIONS = [
    ("M1", "app/credentials.py", "    return _HASHER.hash(plain)", "    return hashlib.sha256(plain.encode('utf-8')).hexdigest()", "test_credentials_contract.py::Argon2ProfileTests"),
    ("M2", "app/auth.py", "if _password_change_required(user.username):", "if False:", "test_password_lifecycle_contract.py::SelfServiceChangeTests"),
    ("M3", "app/auth.py", "if not isinstance(claimed, int) or claimed != record.credentials_version:", "if False:", "test_password_lifecycle_contract.py::TokenRevocationTests"),
    ("M4", "app/auth.py", "credentials.verify_dummy(password)", "pass", "test_authentication_leg_contract.py::UnifiedFailureTests"),
    ("M5", "app/main.py", 'raise HTTPException(status_code=401, detail="用户名或密码错误")', 'raise HTTPException(status_code=401, detail="用户名或密码错误" if result.audit_detail != auth.AUDIT_LOGIN_LOCKED else "账号已锁定，请稍后再试")', "test_authentication_leg_contract.py::LockedHttpFaceTests"),
    ("M6", "app/login_throttle.py", 'return f"{str(username).casefold()}|{client_ip}"', 'return str(username).casefold()', "test_authentication_leg_contract.py::ThrottleLayerTests"),
    ("M7", "app/user_store.py", "WHERE username = ?", "WHERE locked_until IS NULL AND username = ?", "test_authentication_leg_contract.py::ThrottleLayerTests"),
    ("M8", "app/security.py", "str(key).lower() in PERSISTENCE_SENSITIVE_KEYS", '"token" in str(key).lower()', "test_secret_hygiene_contract.py"),
    ("M9", "app/user_store.py", "    encoded = credentials.hash_password(plain_password)", '    encoded = "[REDACTED]"  # 模拟授权凭据库被通用 redactor 罩过（只改第一处 create_argon2）', "test_credentials_contract.py::UserStoreSchemaTests"),
    ("M10", "app/user_store.py", "def _bump_and_clear(", "def _bump_and_clear_disabled(", "test_credentials_contract.py::UserStoreTransactionTests"),
    ("M11", "app/user_store.py", " failed_attempts = 0, locked_until = NULL, updated_at = ?", " updated_at = ?", "test_password_lifecycle_contract.py::AdminResetTests"),
    ("M12", "app/directory.py", 'model_config = ConfigDict(extra="forbid")', 'model_config = ConfigDict(extra="ignore")', "test_user_directory_contract.py"),
    ("M13", "app/auth.py", "from app import credentials, directory, user_store", "import hashlib\nfrom app import credentials, directory, user_store\n\n\ndef _m13_probe(password: str) -> str:\n    return hashlib.sha256(password.encode('utf-8')).hexdigest()", "test_credentials_contract.py::CentralisationScanTests"),
    ("M14", "app/auth.py", "if forced and not wrote:\n            detail = AUDIT_REHASH_DEGRADED", "if forced and not wrote:\n            return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)", "test_authentication_leg_contract.py::LegacyUpgradeTests"),
    ("M15", "config/users.demo.json", '"username": "admin"', '"username": "admin", "password_hash": "a"', "test_user_directory_contract.py"),
    ("M16", "app/credentials.py", "ARGON2_MEMORY_COST = 19456", "ARGON2_MEMORY_COST = int(os.environ.get('ARGON2_MEMORY_COST', 19456))", "test_credentials_contract.py::Argon2ProfileTests"),
    ("M17", "app/auth.py", "if not isinstance(claimed, int) or claimed != record.credentials_version:", "if claimed is not None and claimed != record.credentials_version:", "test_password_lifecycle_contract.py::TokenRevocationTests"),
    ("M18", "app/directory.py", "            if identity.username in merged:", "            if False:", "test_user_directory_contract.py"),
    ("M19", "app/auth.py", "if identity is None or not identity.enabled or record is None:", "if identity is None or not identity.enabled:\n        if record is None:\n            user_store.import_legacy_digest(username, 'a' * 64, must_change=True)\n            record = user_store.get_record(username)", "test_authentication_leg_contract.py::SourceRemovalTests"),
]


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def run(node: str) -> int:
    return subprocess.call(
        [sys.executable, "-m", "pytest", node, "-q", "-x"], cwd=str(BACKEND)
    )


def main() -> int:
    results = []
    for code, relative, old, new, node in MUTATIONS:
        path = BACKEND / relative
        original = path.read_bytes()
        before = sha1(path)
        text = original.decode("utf-8")
        if text.count(old) < 1:
            results.append((code, "TARGET-NOT-FOUND", ""))
            continue
        try:
            path.write_bytes(text.replace(old, new, 1).encode("utf-8"))
            killed = run(node) != 0
            results.append((code, "KILLED" if killed else "SURVIVED", node))
        finally:
            path.write_bytes(original)
            assert sha1(path) == before, f"{code} 还原失败：{path}"   # 还原不了就停下，别把变异留在树上
    for row in results:
        print("\t".join(row))
    survived = [row for row in results if row[1] != "KILLED"]
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

```bash
cd /e/xiangmu/rag && python .superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py
```
Expected: 19 行全 `KILLED`，退出码 0。任何 `SURVIVED` ⇒ 对应 SECA 行是死测试，**补测试而不是撤变异**（不得反向放宽）。`TARGET-NOT-FOUND` 说明计划里的片段与真实代码漂移，按当时代码原文修正片段，不改判据。

- [ ] **Step 5: closure 门与三处扫描**（`backend/tests/test_security_a_closure.py`）

```python
LEGACY_DIGESTS = (
    "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9",
    "6bc0a63cb29c92306020c0a6bbc358cc4628db277dc06e253535e126517ad637",
    "070a3b5e8d4bd5c46acccb91c9c54614c0cd649e78c4c4719e3a64270bae5ddf",
    "e606e38b0d8c19b24cf0ee3808183162ea7cd63ff7912dbb22b5e803286b4446",
    "65375049b9e4d7cad6c9ba286fdeb9394b28135a3e84136404cfccfdcc438894",
)
SCANNED_ROOTS = ("app", "config")


def test_steady_state_code_holds_no_legacy_digest():
    """SECA-04 的代码/配置半边：三处扫描中稳态可静态自证的两处。"""
    offenders = []
    for root in SCANNED_ROOTS:
        for path in (BACKEND_DIR / root).rglob("*"):
            if not path.is_file():
                continue
            body = path.read_text(encoding="utf-8", errors="ignore")
            offenders += [f"{path}:{digest}" for digest in LEGACY_DIGESTS if digest in body]
    assert [] == offenders


def test_running_database_holds_no_active_legacy_credential():
    """SECA-04 的库半边：这是 release gate 的硬门，未归零 ⇒ BLOCKED（不是 PENDING）。"""
    user_store.ensure_user_credentials_schema()
    counts = user_store.count_by_algorithm()
    assert 0 == counts.get(credentials.ALGORITHM_LEGACY_SHA256, 0)


def test_the_migration_artifact_is_gone_after_closure():
    assert not (BACKEND_DIR / "data" / "legacy_credentials.json").exists()
```

**上面三条测的是测试库**（conftest 把 `CONVERSATION_DB_PATH` 会话级重定向到 tmp）。生产库必须在带外单独查一次并留证——这是 `legacy_count=0` 真正的那个 0：

```bash
cd /e/xiangmu/rag/backend && python - <<'PY' | tee ../.superpowers/sdd/SECURITY_A_PLAN/closure-real-db-legacy-count.txt
import sqlite3
from pathlib import Path

db = Path("data/conversations.db")
if not db.exists():
    print("REAL_DB_MISSING: 生产库不存在，SECA-04 的库半边记 PENDING_EXTERNAL 而不是 GREEN")
    raise SystemExit(0)
connection = sqlite3.connect(db)
tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if "user_credentials" not in tables:
    print("REAL_DB_HAS_NO_user_credentials: 生产库尚未初始化凭据表 ⇒ 稳态无 legacy 行，"
          "但必须同时确认没有 demo 行可登（企业形态）")
    raise SystemExit(0)
for algorithm, count in connection.execute(
    "SELECT algorithm, COUNT(*) FROM user_credentials GROUP BY algorithm"
):
    print(f"REAL_DB {algorithm}={count}")
legacy = connection.execute(
    "SELECT COUNT(*) FROM user_credentials WHERE algorithm='legacy-sha256'"
).fetchone()[0]
print(f"REAL_DB legacy_count={legacy}")
PY
```

`legacy_count=0` ⇒ SECA-04 记 `GREEN`；`>0` ⇒ **`BLOCKED`**（不是 `PENDING`，规格 §8.7）；容器内库（`/app/data/conversations.db`）与宿主库都要各查一次，两者是不同文件。

- [ ] **Step 6: 全套件两 cwd 对账**

```bash
cd /e/xiangmu/rag/backend && python -m pytest -q 2>&1 | tail -3
cd /e/xiangmu/rag && python -m pytest backend/tests -q 2>&1 | tail -3
```
Expected: 两行 `N passed` 数字**逐位相同**；记录到验收文档。V2.3 基线数（950 / 961）只作为历史事实引用，不作为本规格基线（规格 §17 L5）。

- [ ] **Step 7: 写验收文档**

`docs/SECURITY_A_ACCEPTANCE_2026-09-25.md` 必含段落（版式照 `MODEL_ROUTER_V23_ACCEPTANCE_2026-09-24.md`）：判据表 · 交付了什么 · 27 行矩阵与状态列（三值）· 变异台 19 行结果 · before/after 证据（schema dump、算法分布、三处扫描、Argon2 容器/宿主两份 JSON、compose smoke 原始输出）· 已知限制（L1–L6 + 一次强制重登录的 breaking change）· 后续登记（§18 清单，含弱口令字典与专用 security job）· 冻结基线（tree SHA / 镜像 ID / 套件数 / 本文档修订）。

- [ ] **Step 8: 快照与提交（提交需当轮授权）**

```bash
cd /e/xiangmu/rag
cp -r backend/app .superpowers/sdd/SECURITY_A_PLAN/snap-task10-app
cp docs/SECURITY_A_ACCEPTANCE_2026-09-25.md .superpowers/sdd/SECURITY_A_PLAN/
git status --short
```
把 `git status` 与拟提交的文件清单交给用户，**逐条确认后**再执行 `git add <显式路径>` + 一次提交（不用 `git add -A`）；tag 名建议 `security-a-rc1`。**不得**触碰 `model-router-v2.3-rc1`，不得 amend 已发布的 RC。


---

## 控制器移交（Task 1–9 完成后追加，与本任务同等强制）

上面是计划原文。以下 7 条是前九个任务收口时留下的、**只能由 Task 10 处理**的账，逐条要么闭合要么写成登记项，不许静默消失。

**T10-1 · 日期与文件名**：计划原文写 `docs/SECURITY_A_ACCEPTANCE_2026-09-25.md`，实际收口日是 2026-09-26 ⇒ 文件名用 **`docs/SECURITY_A_ACCEPTANCE_2026-09-26.md`**，并在文档"冻结基线"段注明这条来自计划原文的字符串更正（回执文档的日期必须是签发日，不是计划撰写日）。

**T10-2 · `.env.example` 七枚键（控制器核验：已全部落地，此条降为复确认）**：`progress.md` 里那条"仍缺 `SECURITY_ENTERPRISE_MODE` / `CORS_ALLOW_ORIGINS`"是 **Task 8 时点的旧账**——Task 9 落地时已补。控制器 2026-09-26 实测：`SECURITY_ENTERPRISE_MODE=false`（`:138`）、`CORS_ALLOW_ORIGINS=http://localhost:3000`（`:141`）、`ARGON2_MAX_CONCURRENT_OPS=2`、`LOGIN_THROTTLE_WINDOW_SECONDS=60`、`LOGIN_THROTTLE_MAX_ATTEMPTS=10`、`ACCOUNT_MAX_FAILED_ATTEMPTS=5`、`ACCOUNT_LOCK_SECONDS=900`（`:148-152`）七枚俱在。本条只剩一件事：**在验收文档里把这七枚键与其默认值列成一张表**（§10 的 env/config 分界证据：哪些是强度参数不可 env 调、哪些是可运维旋钮），并复确认 `test_secret_hygiene_contract.py` 的键集合无交集钉仍然红得起来（SECA-02 的一半）。

**T10-3 · 写腿审计归因（控制器核验：Task 9 修复轮已闭合，此条降为复确认）**：`main.py` 现在改密/重置两条腿的**每一格**拒绝都带 `action="PASSWORD"`（429/503 经 `_auth_availability_denial(..., action="PASSWORD")`，401 经 `record_login_event(..., action="PASSWORD")`，写库事故经 `_audit(..., "PASSWORD", status="FAILED")` 且管理员重置腿带 `target=username`），并有 `PasswordLegActionAttributionTests` 四腿 + 反向钉（登录腿仍全 `LOGIN`）。Task 10 只需在验收文档的"审计面事件归属"一节按现状写清，不需要改代码。

**T10-4 · 分诊全部 deferred minor（必须逐条给结论，且**以当前树实测为准、不得照抄 ledger**）**：`progress.md` 里的 `minor (deferred)` 条目有相当一部分已被后续任务顺带收掉（控制器已核实 T10-2、T10-3 两条是旧账；Task 7 那条"no-echo 路径集合无自证钉"疑似已被 `test_password_lifecycle_contract.py` 的路由枚举门取代，"口令长度无上限"疑似已被 `auth._MAX_PASSWORD_LENGTH` 取代）。**逐条先读当前代码判是否仍在**，再三选一：**闭合**（改+钉）/ **写入验收文档"已知限制"（L 系列）** / **转 §18 后续登记**。零结论的条目视为任务未完成。可疑仍在的几处：422 结构体文案「请求参数不合法」是 §9.1 表里没有的第三枚值且无中文钉；`_last_successful_login` 与 `knowledge_os.py:692-701` 逐字重复；`PASSWORD/FAILED` 的 detail 带自由文本；Task 8 探针—兜底之间那格不可压缩的微秒窗口（控制器已裁定为已知限制，须进 §17/L 系列）。

**T10-5 · `test_real_llm_failover_acceptance.py:685` 的凭据冲突**：该文件是计划"不可触碰"清单里的哈希锁定文件，而它内部有一处登录走真实凭据面。**先实测再判定**：在当前树上跑一次该文件（真实 LLM 关闭 ⇒ 期望它按既有 skip 机制跳过而不是红）。跳过 ⇒ 记为"本版不可复现的真实面，转 PENDING_EXTERNAL 并在文档写明理由"；红 ⇒ 只能通过 **`tests/conftest.py` 侧补种子**修（不得改该文件、不得放宽它的断言），修完复跑。禁止用"它是 skip 的"当作不测的理由。

**T10-6 · 镜像与容器的先后**：`docker compose build backend` 会把 `backend/` 整棵拷进镜像 ⇒ **构建前必须确认没有任何并行 agent 在改 `backend/app/**`**（构建期间读到半成品会把坏代码烧进发布镜像）。构建成功后按 Step 1 的 import 探针 + Step 2 容器基准执行；**容器数才是 SECA-19 的判据**，宿主数仅作对照。任一档不满足 ⇒ 该矩阵行 `BLOCKED`，禁止降 `m/t/p`、禁止拿宿主数凑、禁止改规格数值（SEC-A-008）。

**T10-7 · Step 8 是停止点**：本任务**不提交、不打 tag**。只产出 `git status --short` 与拟提交路径清单交回控制器。禁止 `git add -A`、禁止 amend、禁止移动/触碰 `model-router-v2.3-rc1`。清单里必须显式包含 SEC-A 新增的 untracked 文件（`backend/app/{credentials,user_store,credentials_migration,directory,login_throttle,security_startup,cli}.py`、`backend/config/users*.json`、`backend/tests/{test_credentials_contract,test_user_directory_contract,test_authentication_leg_contract,test_password_lifecycle_contract,test_secret_hygiene_contract,sec_a_seed,sec_a_fixtures}.py`、两份 spec/plan、验收文档），并**排除** `data/**`、`output/**`、`.superpowers/**`（若前九个任务的提交清单里曾纳入过快照，按现状说明差异）。

矩阵状态词汇只有 `GREEN / PENDING_EXTERNAL / BLOCKED` 三值。`legacy_count>0` ⇒ SECA-04 记 `BLOCKED`（不是 PENDING）。

**T10-8 · 真实库拓扑与收敛路线（控制器 2026-09-26 实测，纠正计划 Step 5 的一处事实错误）**：

- `backend/data` 是**bind mount** ⇒ 容器里的 `/app/data/conversations.db` 与宿主的 `backend/data/conversations.db` **是同一个文件**（`docker inspect rag-backend-1` → `"Type":"bind","Source":"E:\xiangmu\rag\backend\data"`）。计划原文"容器内库与宿主库都要各查一次，两者是不同文件"在本项目拓扑下**不成立**：查两次只是同一事实读两遍。要么按同一文件写清（并说明这是 bind mount 拓扑的结果，换 named volume 就要分查），要么显式登记为拓扑前提。
- 该库**当前没有 `user_credentials` 表**（表集合只有 `conversations / conversations…` 五枚），因此今天既无 legacy 行也无 argon2 行。SECA-04 的库半边不能拿"表不存在"当 GREEN 的证据——那只是"还没走过升级路径"。
- 因此 closure 的真实顺序是（Step 1 重建镜像 → Step 3 smoke 期间顺带完成，别另起一轮）：
  1. `docker compose up -d backend` 后，lifespan 按 §8.2 升级路径读 `backend/data/legacy_credentials.json`（该文件今天还在，523 字节）⇒ 导入 5 枚 legacy 行、`must_change=1`；
  2. `credentials migration-status` 留证（`artifact_present=true / imported=5 / legacy_count=5`）；
  3. 5 个 demo 账号各走一次真实登录（Step 3 场景 1 的扩展）⇒ 渐进重哈希把每行就地升成 `argon2id` 并清 `must_change`；
  4. 三方对账：`REAL_DB legacy_count=0` + `algorithm` 分布只有 `argon2id` + `must_change` 计数 0 ⇒ **SECA-04 记 GREEN 的唯一合法路径**；
  5. 删 `backend/data/legacy_credentials.json` **和**快照副本 `.superpowers/sdd/SECURITY_A_PLAN/snap-task3-legacy-artifact.json`，重启容器复确认 `migration-status` 报 `artifact_present=false`，closure 三条扫描（`app/`、`config/`、DB）0 命中。
  任何一步做不到 ⇒ 按 §8.7 记 `BLOCKED` 并写清卡在哪一步，**不得**用"表不存在所以 0 行"糊过去，也不得为了归零直接手改库（那不是收敛，是把门换成删除）。

**T10-9 · 复评移交的两条（不得当成"已知"就跳过）**：
- `backend/app/main.py:460-461`：管理员重置腿对**不存在账号**的 404 一格审计事件都不写，与同一路由其余每一格拒绝不对称。判它是否属 SEC-A 的审计面契约（§9.1 只枚举认证/改密腿）；要么补一枚 `PASSWORD/NOT_FOUND` 之类的枚举 token + 用例，要么在验收文档"已知限制"里写明这是有意边界。**不得**写成中文自由文本 detail 之外的新语义。
- 验收文档若要引用 V2.3 的 canary 字面量（`sk-CANARY-…` 是**材料形状**，会被 secret 门抓），按 `路径:行号` 指过去，**不要把字面量抄进 `docs/**`**——否则门会为一枚假凭据红，而唯一出路是新增一行豁免，正是这一档设计声称要免掉的摩擦。

**T10-8 补正（控制器核过实现，省掉一轮猜测）**：渐进重哈希**保留** `must_change`（`app/auth.py:330`
取 `record.must_change` 原值传给 `apply_rehash`，只有 `set_password_argon2` 那条 `_bump_and_clear` 才清它）。
⇒ 上面第 3、4 步的次序不变但含义要说准：**5 个 demo 账号各登录一次就让 `legacy_count` 归零**，而它们
仍然全部带着 `must_change=1` 与 `cv` bump，因此第 4 步之后数据面仍是 403「需先修改口令」——那正是
§8.4 `authentication → must_change → authorization` 与"一次强制重登录"breaking change 的现场，
不要把它当失败去"修"。要在 smoke 里额外走一格"改密后数据面通"（SECA-03），就拿其中一个账号真改一次
口令，改完再打 `$API/api/knowledge-bases` 应为 200，并留旧 token 打同一格应为 401 的证据（cv 失效）。
