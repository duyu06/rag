# SEC-A Task 10a — DONE (infrastructure evidence + closure half)

**(A) image rebuild + dual probe: GREEN. (B) SECA-19 = `GREEN` on the container numbers.
(C) four smoke scenarios observed + the real upgrade path converged end to end.
(D) `legacy_count=0` out-of-band on the real DB, closure gates green.**

- Scope executed in this half: **(A)** image rebuild + dual import probe, **(B)** Argon2 benchmark
  (container = criterion), **(C)** compose smoke four scenarios + real upgrade-path convergence
  (T10-8 + 补正), **(D)** `backend/tests/test_security_a_closure.py` + out-of-band real-DB query.
- Explicitly NOT in this half (next agent): Step 4 mutation bench, Step 6 both-cwd full suite,
  Step 7 acceptance doc, Step 8 commit list. **No git write commands were run** (only
  `git status` / `git log` / `git ls-files` / `git check-ignore`, all read-only).
  `model-router-v2.3-rc1` was listed (`git tag --list`) and never touched.
- Verdicts: **SECA-19 `GREEN`**, **SECA-04 `GREEN`** — both derived below, from the deployed form.

---

## 0. Pre-flight (read-only), before any build

### 0.1 Tree settled check (build-safety rule learned in this project)

`docker compose build backend` copies `backend/` into the image, so nothing may be mutating
`backend/app/**` during a build. Checked before building:

- `git status --short` (read-only): 17 tracked modifications + the 20 deliberately-untracked SEC-A
  files (`backend/app/{cli,credentials,credentials_migration,directory,login_throttle,security_startup,user_store}.py`,
  `backend/config/users{,.demo}.json`, 5 SEC-A test files, 2 docs). No new movement vs the
  controller's own listing.
- Newest mtime under `backend/app/*.py` = `app/security.py` `2026-09-26T15:59:59`; the check ran at
  `17:22:23` ⇒ **82 minutes of quiet**, no parallel writer. (Task 9 is closed; nothing was dispatched
  by me, and this agent does not spawn subagents.)
- Files created *during* this task that live inside the build context: **none**. The benchmark script
  lives in `.superpowers/scripts/` (outside `./backend`), and the closure test file was written
  **after** the build finished, so no artifact in this report was produced from a half-written tree.

### 0.2 Bind-mount topology (controller's T10-8 premise, re-verified by me)

```
$ docker inspect rag-backend-1 --format '{{range .Mounts}}...'
bind  |  E:\xiangmu\rag\backend\data  ->  /app/data
bind  |  E:\xiangmu\rag\demo-data     ->  /app/demo-data
volume|  /var/lib/docker/volumes/rag_hf_cache/_data -> /app/.cache/huggingface
```

⇒ Container `/app/data/conversations.db` **is the same file** as host
`backend/data/conversations.db`. Plan Step 5's sentence "容器内库与宿主库…两者是不同文件" does not
hold under this topology (T10-8 already ruled this); reading it twice is the same fact. If the
project ever moves to a named volume, the two must be queried separately again.

Path resolution is *relative on both sides*, which is what makes them coincide:
`backend/.env` carries `CONVERSATION_DB_PATH=data/conversations.db`, container `cwd=/app`
(Dockerfile `WORKDIR /app`), host `cwd=backend/`, and `user_store.database_path()` reads
`os.getenv` with the same default ⇒ both resolve to the bind-mounted file.

### 0.3 Pre-state of the real DB (the number T10-8 says must not be dressed up as GREEN)

```
PRE_STATE tables: ['conversations', 'llm_request_logs', 'message_sources', 'messages', 'sqlite_sequence']
has user_credentials: False
```

Confirmed independently on the host file and via `docker compose exec backend`: **no
`user_credentials` table exists before this run.** Per §8.7 / T10-8, "table absent" means
"the upgrade path has never been walked", NOT `legacy_count=0` ⇒ no credit is taken for it here.

### 0.4 FINDING (deviation from the plan's / T10-8's premise) — nothing in the shipped code
### runs the migration import at container start

T10-8 step 1 says: "container start ⇒ lifespan imports `backend/data/legacy_credentials.json`".
**That wiring does not exist in the tree.** Evidence (grep over `backend/app/**`):

```
$ grep -rn "credentials_migration|import_from_artifact|ensure_user_credentials_schema" app/
app/cli.py:21   from app import auth, credentials, credentials_migration, directory, user_store
app/cli.py:86   status = credentials_migration.status()
app/cli.py:105  user_store.ensure_user_credentials_schema()
app/user_store.py:114 (the definition itself)
```

- `main.py` lifespan runs exactly three things: `security_startup.assert_startup_safe()`,
  `warmup_identity_permissions()`, `warmup_llm_router()` (`main.py:87-89`). No schema creation, no
  import.
- `credentials_migration.import_from_artifact()` has **zero production callers**; the CLI exposes
  only `bootstrap-admin`, `reset`, `migration-status` (`cli.py:45-51`) — there is no
  `credentials migrate` / `import` subcommand.
- Consequence in the deployed form, which I verified rather than inferred: on the pre-rebuild
  container the credentials table does not exist, so the honest upgrade path is
  "`ensure_user_credentials_schema()` then `import_from_artifact()`" performed by an operator.

**What I did about it (no code changed — this half must not edit `app/`):** I drove the operator
upgrade path by calling exactly the two public functions the CLI itself composes, in the same order
and with the same arguments, inside the release container. That is the documented §8.2 "upgrade from
a pre-SEC-A version" input path; it is *not* a hand-edit of the DB and it is *not* a value invented
for the report. Recorded as a **finding** for the acceptance doc: the lifespan hook the plan assumed
is absent, so an operator upgrading today must run the import manually (or a follow-up task wires it
into lifespan). §8.2's wording ("只有升级路径…才导入 legacy") is satisfied in substance; the
*trigger* is the operator, not the process start.

### 0.5 Environment note carried forward for (D)

`backend/tests/conftest.py` redirects `CONVERSATION_DB_PATH` to a session tmp DB and
`sec_a_seed.seed_demo_credentials()` writes argon2id rows there. Therefore closure tests #2 and #3
are statements about the **test** DB; only the out-of-band query in (D) means `legacy_count=0` for
the real file. The report keeps those two apart deliberately.

---

## (A) Release image rebuild + dual import probe — **DONE, evidence GREEN**

Order actually run (build **before** `up -d`, per the pre-flight rule, so a failed build could not
take the running service down; the old container stayed `Up (healthy)` throughout the build):

1. read-only `git status --short` + mtime scan of `backend/app/**` (§0.1) → tree settled;
2. read-only real-DB pre-state (`user_credentials` absent, §0.3) and `docker inspect` mount proof (§0.2);
3. `docker compose build backend` → **exit code 0**, new image `1abba3717aa7` (`rag-backend:latest`,
   2.68 GB, 79 packages). Build wall time ≈ 32 min: `COPY requirements.txt .` is *above* both pip
   layers in `backend/Dockerfile`, so adding `argon2-cffi` invalidated the whole dependency chain and
   `pip install torch --index-url …/whl/cpu` reran too. Not a failure, but worth recording because
   the next release build will pay it again.
4. `docker compose up -d backend` → `Container rag-backend-1 Recreated … Started`;
   `docker compose ps backend` → `Up 35 seconds (healthy)`;
   `docker inspect rag-backend-1 --format '{{.Image}}'` →
   `sha256:1abba3717aa7bb55a248f5c97f8d373deb5003cfd99fa4dcb6a94dc7011f5223` (the new image is the
   one serving traffic; healthcheck `/api/ready` passing).

### A.1 The plan's Step 1 probe, verbatim

```
$ docker exec rag-backend-1 python -c "import argon2, credentials_probe" 2>/dev/null || \
  docker exec rag-backend-1 python -c "… PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1) …"
argon2 import OK True
```
Expected line met exactly.

### A.2 The exact wheels that landed in the image

```
$ docker run --rm --entrypoint pip rag-backend:latest freeze | grep -i argon2
argon2-cffi==25.1.0
argon2-cffi-bindings==26.1.0
cffi==2.1.1

$ cat /usr/local/lib/python3.12/site-packages/argon2_cffi_bindings-26.1.0.dist-info/WHEEL
Wheel-Version: 1.0
Generator: scikit-build-core 1.0.3
Root-Is-Purelib: false
Tag: cp310-abi3-manylinux_2_26_x86_64
Tag: cp310-abi3-manylinux_2_28_x86_64
```
⇒ the **binary manylinux wheel** installed (not a source build): the loaded extension is
`/usr/local/lib/python3.12/site-packages/_argon2_cffi_bindings/_ffi.abi3.so`, and
`argon2.low_level.hash_secret_raw(..., type=Type.ID)` returns a digest inside the container
(`b55f1d5fb2fb6f614bc71861a29e87a4` for the fixed probe inputs). Pure-python half:
`argon2_cffi-25.1.0-py3-none-any.whl`.

### A.3 The SEC-A code actually landed in the image, byte-for-byte from the settled tree

```
$ docker exec rag-backend-1 python -c "sha1 of /app/app/<module>.py"   # ← →  host backend/app/<module>.py
credentials          e2b74e382300   ==  e2b74e382300
user_store           8d74e0ae22df   ==  8d74e0ae22df
credentials_migration 18e1f0d13a69  ==  18e1f0d13a69
directory            80edfd90b724   ==  80edfd90b724
login_throttle       c92934b8707f   ==  c92934b8707f
security_startup     6bd74f9ee1e1   ==  6bd74f9ee1e1
cli                  daf6b1380e3c   ==  daf6b1380e3c
```
Re-checked **after** the build (and after `HEAD` moved from `bc43ca3` to `696d522` mid-task — the
app tree did not move with it, no `backend/app/*.py` mtime is newer than `15:59:59`).
This is the half of the pre-flight rule that matters: the deployed form is the same bytes the tests
describe. Also note the pre-rebuild container could not even import `app.user_store`
(`ImportError: cannot import name 'user_store' from 'app'`) — that ImportError *is* the proof the old
image predated SEC-A, and it is why the rebuild had to come first.

### A.4 Host-side counterpart probe (same profile, same command shape)

```
$ cd backend && python -c "… PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1) …"
host python 3.13.7 | argon2-cffi 25.1.0 | bindings 26.1.0
argon2 import OK True
```
Side by side: container python 3.12.14 / host 3.13.7, **identical dependency versions**, both
probes print `argon2 import OK True` ⇒ release-gate step 1 ("宿主 + 容器双向 import 探针") holds on
both faces.

---

## (B) Argon2 benchmark — **SECA-19 = GREEN, judged on the container numbers**

Script: `.superpowers/scripts/run_argon2_benchmark.py` (LF endings), written from the plan's code
with the budget dict, the profile literals (`2 / 19456 / 1`), serial 50 / concurrent 32 on 2 workers
and the verdict formula kept verbatim. It does **not** read `os.environ` or `settings` for strength
parameters (that shape is what M16 kills), and it does **not** touch `m/t/p`.

**Why 2 workers, in the script's own comment** (not just here): `ARGON2_MAX_CONCURRENT_OPS=2` is the
`BoundedSemaphore` ceiling in `app/credentials.py:57`, i.e. the most Argon2 work a production process
may pay at once. Running the benchmark on more workers would measure a case the gate never admits
(each op gets more of the machine, P95 comes out *lower*); fewer workers would not show the queueing.
So the measurement is taken with **the gate saturated** — 2 workers × 16 rounds = 32 queued ops —
which is the worst case the budget is written against, not an ideal one.

### B.1 Container (the criterion) — `argon2-benchmark-container.json`

Run exactly as the plan gives it (`docker compose cp … backend:/tmp/bench.py` +
`docker compose exec backend python /tmp/bench.py | tee …`):

```json
{"environment": "linux", "python": "3.12.14",
 "serial":     {"runs": 50, "p50_ms": 50.3, "p95_ms": 55.3},
 "concurrent": {"runs": 32, "workers": 2,  "p95_ms": 66.7},
 "peak_rss_delta_kib": 39280,
 "budget": {"serial_p95_ms": 1500.0, "concurrent_p95_ms": 3000.0, "rss_delta_kib": 262144},
 "budget_checks": {"serial_p95": true, "concurrent_p95": true, "peak_rss_delta": true},
 "verdict": "GREEN"}
```

| budget item | measured (container) | limit | margin |
| --- | --- | --- | --- |
| serial P95 | **55.3 ms** (p50 50.3 ms) | ≤ 1500 ms | 27× headroom |
| concurrent P95 (gate saturated, 2 workers) | **66.7 ms** | ≤ 3000 ms | 45× headroom |
| peak RSS delta | **39 280 KiB = 38.4 MiB** | ≤ 262 144 KiB (256 MiB) | 6.7× headroom |

RSS delta reads right: 2 slots × 19 MiB ≈ 38 MiB, i.e. the semaphore ceiling is also the memory
ceiling. `ru_maxrss` on Linux is **KiB**, which is the unit `BUDGET["rss_delta_kib"]` is written in —
the container is Linux, so the assumption holds exactly where the judgement is made (§17 L3).

### B.2 Host (context only) — `argon2-benchmark-host.json`

```json
{"environment": "win32", "python": "3.13.7",
 "serial": {"runs": 50, "p50_ms": 50.0, "p95_ms": 52.6},
 "concurrent": {"runs": 32, "workers": 2, "p95_ms": 67.9},
 "peak_rss_delta_kib": null, "verdict": "NOT_THE_CRITERION"}
```
Host latency lands within 5% of the container on all three readings (a second host run, with the
container benchmark already finished, gave 60.5 / 83.5 ms — ordinary noise, still two orders away
from the budget). The container is therefore **not** a pathological environment; that is the whole
point of recording the host column, it is not the verdict.

**Deviation D-B1 (recorded, not silently rewritten).** The plan's host command
`python .superpowers/scripts/run_argon2_benchmark.py` cannot run verbatim on this workspace's host:
`resource` is a POSIX-only module, so the plan's line-1 `import resource` raises
`ModuleNotFoundError` on win32. Fixed **without touching the container path**: the import is now
`try/except ImportError` → `resource = None`, and on such a platform `peak_rss_delta_kib` is `null`,
`budget_checks.peak_rss_delta` is `null`, and the script emits
`verdict: "NOT_THE_CRITERION"` with a `verdict_reason` instead of letting a `None` participate in the
`and` chain (a missing number must never read as "within budget"). On Linux — i.e. in the container,
where SECA-19 is actually judged — `resource` is always present and the verdict formula is the plan's
verbatim three comparisons. The `ru_maxrss` KiB/bytes unit difference is documented in the script and
in the JSON (`environment_detail.peak_rss_delta_unit`); the container branch was deliberately **not**
"fixed" to match the host.

**Deviation D-B2.** `docker compose exec backend python /tmp/bench.py` needed
`MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'` on this Git Bash host, which rewrote `/tmp/bench.py`
into `C:/Users/…/Temp/bench.py` and failed with "can't open file /app/C:/Users/…". Same trap as the
V2.3 MSYS note in project memory. Container-side nothing changed; the rerun produced B.1.
The host JSON is also written with `PYTHONIOENCODING=utf-8` so the artifact is valid UTF-8 JSON
(the first attempt emitted cp936 bytes for the Chinese strings and could not be parsed back).

### B.3 Verdict

**SECA-19 = `GREEN`**, from `argon2-benchmark-container.json` (environment `linux`,
python 3.12.14, image `1abba3717aa7`). No downgrade of `m/t/p`, no env-sourced strength, no
substitution of the host numbers, no edit of the spec's budget values.

---

## (C) compose smoke, four scenarios + the real upgrade-path convergence — **DONE**

Order is T10-8's, because that ordering *is* the honest convergence and it doubles as the
upgrade-path proof. Everything below was run against the deployed form: the rebuilt release
container (`1abba3717aa7`, `healthy`) over HTTP `http://localhost:8001` and via
`docker compose exec -T backend`.

**口令 discipline (SEC-A-002), how it was actually kept here:** the demo口令 appear only in the
command lines I executed (they are already literals in spec §2 and in the existing test suite);
**no file in this repo contains one.** Every HTTP response was captured with `curl -o <tmp>` into
`mktemp -d` **outside the repository** (`C:\Users\zhang\AppData\Local\Temp\tmp.o30W1rNEPj`), and
what I recorded from those bodies is status codes, key sets, booleans and `cmp`/sha1 results — never
a body that could carry a口令, and never a token value. `docker compose exec` output was piped
through `tr`/`tail`, never tee'd into the repo. The one place a Chinese body string is compared is a
boolean equality against the §9.1 frozen literal, printed as `True`.

### C.1 Pre-state (must be measured before, not asserted after)

§0.3 already recorded it: `user_credentials` **absent** from `backend/data/conversations.db`, and
§0.2 recorded by `docker inspect` that `backend/data` is a **bind mount** to container `/app/data`
⇒ one and the same file. Per T10-8 I do **not** read "table absent" as `legacy_count=0`.

### C.2 Scenario 1 head — `bootstrap-admin` must not invent an identity

```
$ docker compose exec -T backend python -m app.cli credentials bootstrap-admin --username admin
CREDENTIALS_PASSWORD 未设置或不足 12 字符：口令只能放在这个环境变量里，不接受任何命令行参数形式
rc=2
```
Plan expected `rc=2`. **Which branch produced it, exactly:** the deployed container is dev posture
(`SECURITY_ENTERPRISE_MODE` unset ⇒ `False`), so `admin` **is** a loaded identity
(`config/users.demo.json`) and the identity branch passed; `rc=2` came from the
"口令 only from `CREDENTIALS_PASSWORD`, never argv" branch (`cli.py:113-116`). Also visible here:
the copy names only the variable, never a value or a length of a value. The identity-missing /
enterprise-mode `rc=2` branch is a different line (`cli.py:109-112`) and is covered by
`test_credentials_contract.py`; I did not claim to have exercised it in the deployed form.

### C.3 Upgrade input imported (the operator path — see finding §0.4)

`bootstrap-admin` above already ran `ensure_user_credentials_schema()` (`cli.py:105`), so the table
exists. The import itself had to be driven as an operator action, because **nothing in `app/` calls
`import_from_artifact()`** (§0.4 finding):

```
$ docker compose exec -T backend python -c "… import_from_artifact() …"
artifact_present= True imported= 5 ['admin', 'hr01', 'sales01', 'user', 'viewer'] skipped= () reason= ''

$ docker compose exec -T backend python -m app.cli credentials migration-status
legacy_count=5 argon2id_count=0
admin    legacy-sha256  v1  must_change=1  locked=-   …
hr01     legacy-sha256  v1  must_change=1  locked=-   …
sales01  legacy-sha256  v1  must_change=1  locked=-   …
user     legacy-sha256  v1  must_change=1  locked=-   …
viewer   legacy-sha256  v1  must_change=1  locked=-   …
```
This is the **`before` column of §14** in the deployed form: five `legacy-sha256` rows, all
`must_change=1`, all `credentials_version=1`.

### C.4 Convergence — one real login per demo account (progressive rehash)

Five `POST /api/auth/login` calls, one per account, each with the §2 literal口令 for that account:

```
admin -> 200   sales01 -> 200   hr01 -> 200   user -> 200   viewer -> 200
```
Login **response shape** (§9.1/§11 pin — key set, not the token value), identical for all five:
```
top_keys  = ['access_token', 'password_change_required', 'token_type', 'user']
password_change_required = True        (all five)
user_keys = ['access_role', 'display_name', 'permissions', 'role', 'username']
```
⇒ the §2 "登录响应键集合" reading is `{access_token, token_type, user}` **plus** the one additive
key SEC-A declares in §11 (`password_change_required`), and the nested `user` key set still matches
the `_LOCAL_KEYS` equality pins in `test_feishu_identity_contract.py`.

Then `migration-status`, same file, same process, no hand-edit:
```
legacy_count=0 argon2id_count=5
admin    argon2id  v1  must_change=1   …
hr01     argon2id  v1  must_change=1   …
sales01  argon2id  v1  must_change=1   …
user     argon2id  v1  must_change=1   …
viewer   argon2id  v1  must_change=1   …
```
T10-8 step 4's **three-way reconciliation**, all three from the same read:
`legacy_count=0` + `algorithm` distribution is `argon2id` **only** + `must_change` is still `1` on
every row. Note `credentials_version` stayed **`v1`**: the rehash is an in-place strength upgrade,
not a session invalidation — that is SEC-A-003 ("不掉线") visible in the data, and it is the reason
the tokens from C.4 are still usable in C.5.

### C.5 Scenario 3 — `must_change` **survived** the rehash and still gates the data plane

The 补正's point, tested rather than asserted (`app/auth.py:331` passes `record.must_change`'s
original value into `apply_rehash`; only `_bump_and_clear` via `set_password_argon2` clears it):

```
GET /api/knowledge-bases  (admin's token, issued in C.4)  -> 403
body keys: ['detail'] | detail == '当前账号需先修改口令'  -> True
GET /api/auth/me          (same token, whitelist leg)     -> 200
me keys: [access_role, display_name, password_change_required, permissions, role, username]
         password_change_required = True
```
**Which of 403/200 was observed, and why:** **403**. The plan allowed either, and the difference is
meaningful: 403 is the state the upgrade path actually lands in (five弱口令 accounts, none of which
has changed口令 yet), and it proves the rehash did **not** quietly open the gate. The `403 → 200`
transition is then produced deliberately in C.7 rather than assumed.

### C.6 Scenario 2 and scenario 4

**Scenario 2 — wrong口令 vs unknown account must be the same face:**
```
POST /api/auth/login {"username":"admin",         …wrong…}  -> 401
POST /api/auth/login {"username":"nosuchaccount", …wrong…}  -> 401
$ cmp s2-wrongpw.json s2-unknown.json             -> identical
sha1(body) 3b9054717ae8 == 3b9054717ae8   bytes=37   keys=['detail']
detail == '用户名或密码错误' -> True
```
⇒ byte-identical 401 bodies (same 37 bytes, same sha1), not merely "both 401".

**Scenario 4 — lockout:** five wrong口令 on `viewer`, then the **correct** one:
```
attempt1..5 = 401 401 401 401 401
correct口令 while locked -> 401
locked-body == unified-failure-body -> True   detail == '用户名或密码错误'
'锁定' not in detail -> True                   (no lock wording on the face)
DB:  viewer locked_until=2026-09-26T10:08:44.350006+00:00   (= lock moment + ACCOUNT_LOCK_SECONDS=900)
Audit: AUTH_LOGIN_LOCKED events in the tail = 1, users=['viewer'], actions=['LOGIN']
```
⇒ §7.4 / §17 L1 observed live: the lock is externally indistinguishable and diagnosable only on the
DB and audit faces. The audit token never reaches the HTTP body.

### C.7 The one account through `POST /api/auth/password/change` (SECA-03's second half + the breaking change)

Chosen account: **`user`** — deliberately *not* `admin`, so the demo admin keeps its documented口令,
and *not* `viewer`, which scenario 4 had already locked.

```
POST /api/auth/password/change  (user's C.4 token; current口令 + a new 18-char口令)  -> 200
change keys = ['access_token', 'changed', 'password_change_required', 'token_type']
changed = True | password_change_required = False | token_type = bearer
no口令 appears anywhere in the body -> True

GET /api/knowledge-bases with the NEW token        -> 200  body keys ['knowledge_bases'], 1 kb visible
GET /api/knowledge-bases with the PRE-CHANGE token -> 401  detail == '无效登录凭证'

$ migration-status (final)
legacy_count=0 argon2id_count=5
user  argon2id  v2  must_change=0     ← the only row whose version bumped and whose gate closed
admin/hr01/sales01/viewer  argon2id  v1  must_change=1
```
Three facts interlock here, which is what §14 demands instead of a single-field assertion: the data
plane goes **403 → 200** for the same account only across a real口令 change; the **pre-change token
401s** because `set_password_argon2` bumps `credentials_version` in the same transaction as the hash
(§8.8), i.e. the "one forced re-login" breaking change §15.2 requires in the release note is
**observed**, not described; and the new口令 exists nowhere in this repository (SEC-A-002).

### C.8 Scenario 5 — artifact deletion and its re-confirmation (T10-8 step 5)

Before deleting, prove the two copies are the same material (so "both gone" is one statement, not two):
```
backend/data/legacy_credentials.json                  sha1 19cc628acbae  523 bytes
.superpowers/…/snap-task3-legacy-artifact.json        sha1 19cc628acbae  523 bytes   (identical)
both unlinked; exists -> False, False
```
(`backend/data/` is git-ignored — `.gitignore:7` — so the artifact was never on the delivery face;
the digest literals were already gone from `backend/app` and `backend/config`, re-grepped: 0 files.)

Then restart the container (fresh process, lifespan runs again) and re-do the read:
```
$ docker compose restart backend        -> health=healthy
$ … import_from_artifact()
artifact_present= False imported= 0 skipped= ()
reason= 迁移输入不存在：全新安装不生产 legacy 行（默认路径按当前工作目录解析为 /app/data/legacy_credentials.json）
$ … migration-status
legacy_count=0 argon2id_count=5
```
⇒ §8.2's separation holds in the deployed form: with the upgrade input gone, the same code path
manufactures **zero** legacy rows, and the converged distribution survives a process restart (the
rows live in the bind-mounted DB, not in process memory). That is also the fresh-install datapoint
for SECA-04b's "dev 形态无迁移输入 ⇒ 不产 legacy" half, observed rather than inferred.

### C.9 Residual state of the deployed demo DB (so a later reader is not surprised)

Written by **(C)**, which is the *only* legitimate writer in `backend/data/` for this task:
`user_credentials` now holds 5 argon2id rows; `user`'s口令 was rotated to a value recorded nowhere
(to restore a demo口令 for it: `credentials reset --username user` with `CREDENTIALS_PASSWORD`);
`admin` carries `failed_attempts=1` from scenario 2; `viewer` carries `failed_attempts=5` and
`locked_until=2026-09-26T10:08:44Z`, which expires by itself 15 min later
(`ACCOUNT_LOCK_SECONDS=900`) and was **not** hand-cleared — clearing it by editing the row would
have been exactly the "把门换成删除" move T10-8 forbids. Four accounts still have `must_change=1`;
that is the correct steady state for弱口令-derived demo accounts that have not changed口令, not a
defect to fix.

---

## (D) Closure test + out-of-band real-DB query — **DONE**

### D.1 `backend/tests/test_security_a_closure.py` (new, LF endings, 84 lines)

The plan's three tests, kept as sketched:
1. `test_steady_state_code_holds_no_legacy_digest` — scans `SCANNED_ROOTS = ("app", "config")`
   recursively for the digest literals;
2. `test_running_database_holds_no_active_legacy_credential` —
   `ensure_user_credentials_schema()` then `count_by_algorithm().get(ALGORITHM_LEGACY_SHA256, 0) == 0`;
3. `test_the_migration_artifact_is_gone_after_closure` — the artifact must not exist.

The module docstring states the distinction that (D) turns on, so the next reader cannot collapse it:
**tests #2 and #3 are statements about the *test* face** — `conftest.py` redirects
`CONVERSATION_DB_PATH` to a session tmp DB, so #2's zero means "nothing in the steady-state code path
manufactures a legacy row", which is *not* the same claim as "`legacy_count=0` in the deployed DB".
Only D.2 means that.

Deviation from the plan's literal text, recorded not rewritten: the plan/brief says "three legacy
digests"; the number is **five** (§2 fact table: 5 枚账号 hash; §12 SECA-04: "closure 三处扫描
5 枚 digest = 0 命中"). **三处 = three locations** (`app/`, `config/`, the DB), **5 = the digest
count**; the file carries the plan's five literals verbatim.

### D.2 Out-of-band query against the real DB — `closure-real-db-legacy-count.txt`

Run verbatim from the plan, `cd backend`, output redirected to the plan-named file:
```
REAL_DB argon2id=5
REAL_DB legacy_count=0
```
and then the same query from **inside** the container against `/app/data/conversations.db`, appended
to the same file with a header saying why the two readings are one fact (bind mount, §0.2) rather
than the two files plan Step 5 assumed:
```
container cwd: /app | resolved db: data/conversations.db
REAL_DB(container) argon2id=5
REAL_DB(container) legacy_count=0
REAL_DB(container) must_change=1 rows: 4
REAL_DB(container) must_change=0 rows: 1
  admin: argon2id v1 must_change=1 … user: argon2id v2 must_change=0 … viewer: argon2id v1 must_change=1
```
⇒ **this** is the 0 that SECA-04 reads.

### D.3 Focused gates green in the deployed source

```
$ cd backend && python -m pytest tests/test_secret_hygiene_contract.py tests/test_security_a_closure.py -q
48 passed in 56.20s                       (45 hygiene/SECA-20 + 3 closure)
```
Because an order-dependent closure test would be a landmine for the next agent's full-suite run, I
also checked it alongside every SEC-A suite that constructs legacy rows at all:
```
$ python -m pytest tests/test_credentials_contract.py tests/test_user_directory_contract.py \
    tests/test_authentication_leg_contract.py tests/test_password_lifecycle_contract.py \
    tests/test_security_a_closure.py -q
270 passed, 101 subtests passed in 88.47s
```
No new `EXEMPTIONS` row was needed for the closure file's digest literals (the SECA-20 faces match
"key = quoted value" shapes and live-key material shapes; a bare 64-hex digest is neither, and that
gate's own `豁免表 == 命中表` pin stayed green). The `[ledger-guard]` line in that run's summary is
the pre-existing **read**-level note (writes are what fail a test), not a finding of this task.

Final-state re-check, after every deletion above (so the numbers cited are the numbers that stand):
`tests/test_security_a_closure.py -q` → **3 passed**; `docker compose ps backend` →
`Up 11 minutes (healthy)`; `GET /api/ready` → 200; `git status --short` → 38 entries
(17 tracked modifications + 20 pre-existing untracked SEC-A files + this task's new test file),
i.e. nothing in the tree moved that this task did not move on purpose.

### D.4 SECA-04 verdict

**`GREEN`.** Every half has its own artifact and none of them is "table absent":
- algorithm distribution **before**: `legacy-sha256` × 5, `argon2id` × 0, `must_change=1` × 5 (C.3);
- algorithm distribution **after**: `argon2id` × 5, `legacy_count=0` (C.4), reached by five real
  logins through the shipped code path — no DB hand-edit at any point;
- out-of-band real-DB `legacy_count=0`, host and container, same bind-mounted file (D.2);
- three-location scan 0 hits: `app/` + `config/` by test #1 (green), the DB by D.2, and the artifact
  deleted with both copies' sha1 recorded before deletion (C.8);
- post-restart re-confirmation that the deleted artifact yields `imported=0`, i.e. closure is stable
  across a process restart.

Vocabulary check: nothing here is `PENDING_EXTERNAL` — the migration is closed, and §8.7's
`legacy_count>0 ⇒ BLOCKED` branch did not trigger.



## Findings and deviations (recorded, per this project's rule: record the ruling, don't rewrite the plan)

| # | What | Why this is not a silent rewrite |
| --- | --- | --- |
| **F-1** | **No production code runs the migration import.** `credentials_migration.import_from_artifact()` has zero callers outside tests; `main.py`'s lifespan runs only the three V2.3-era gates (`:87-89`); the CLI exposes no `migrate`/`import` action. Plan Step 3 and T10-8 step 1 both assume container start imports the artifact. | T10-8's ordering is still executable, but the trigger is an **operator** invocation, so "升级即自动导入" is not what ships today. I drove the two public functions the CLI itself composes, in-container, and changed no `app/` code. **Needs a controller ruling:** either wire schema+import into the lifespan (an `app/` change, not mine to make unasked) or record the manual step in §8.6's 运维体检 and in the acceptance doc's upgrade procedure. Corollary worth stating in the doc: here the table itself was created by `bootstrap-admin`'s `ensure_user_credentials_schema()` leg (F-1 is also why the pre-rebuild DB had no table at all). |
| **F-2** | Plan Step 5's "容器内库与宿主库…两者是不同文件" | Already corrected by T10-8; re-verified by `docker inspect` (§0.2) and by the two readings agreeing (D.2). I kept both readings, labelled as one fact, so that a future named-volume topology shows up as a *difference* instead of silently agreeing. |
| **F-3** | Brief's "three legacy digests" vs spec/plan's five | The number is five (§2 fact table, §12 SECA-04 "三处扫描 5 枚 digest"); "三处" counts **locations**. Documented in the test file's docstring and D.1 so nobody "fixes" it the wrong way later. |
| **D-B1** | `resource` is POSIX-only ⇒ the plan's host benchmark command cannot run verbatim on win32 | Fixed on the host side only; the container path and the three-comparison verdict formula are the plan's verbatim, and a missing RSS value yields `NOT_THE_CRITERION` rather than a silently-passing `None`. Details in B.2. |
| **D-B2** | Git Bash rewrote `/tmp/bench.py` into a Windows path; the host JSON first landed in cp936 | Both are harness facts about *this workstation*; nothing container-side changed. See B.2. |
| **F-4** | `COPY requirements.txt .` sits **above both** pip layers in `backend/Dockerfile` ⇒ adding `argon2-cffi` invalidated the torch layer too: build wall time ≈ 32 min, and the pre-rebuild container could not even `import app.user_store` (`ImportError`) | One line for the acceptance doc's release procedure (any requirements change re-downloads `torch`). The ImportError is also the cleanest proof the old image predated SEC-A. |
| **F-5** | `HEAD` is still `bc43ca3`; `git ls-files backend/tests/test_security_a_closure.py` → 0 (my new test is untracked, like the rest of SEC-A) | Recorded for Step 8. Image-vs-tree sha1 equality for all 7 SEC-A modules was re-verified *after* the build (§A.3), so nothing in the deployed form depends on which commit HEAD is at. |
| **F-6** | T10-4 (deferred-minor triage), T10-9 (`main.py:460-461` 404 with no audit event; canary literals), T10-2/T10-3 re-confirmations, Step 4 mutation bench, Step 6 both-cwd suite | **Out of this half's scope, not silently dropped** — they remain open in `progress.md` for the next agent. I did not touch any of them, deliberately. |

---

## Files created / deleted / modified

**Created (by me):**
- `.superpowers/scripts/run_argon2_benchmark.py`
- `.superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-container.json` — **the SECA-19 criterion**
- `.superpowers/sdd/SECURITY_A_PLAN/argon2-benchmark-host.json` — context only
- `.superpowers/sdd/SECURITY_A_PLAN/closure-real-db-legacy-count.txt`
- `.superpowers/sdd/SECURITY_A_PLAN/task-10a-report.md` (this file)
- `backend/tests/test_security_a_closure.py`

**Deleted (T10-8 step 5):**
- `backend/data/legacy_credentials.json` (sha1 `19cc628acbae`, 523 B)
- `.superpowers/sdd/SECURITY_A_PLAN/snap-task3-legacy-artifact.json` (identical sha1 and size)

**Modified by me:** nothing outside the files above. No edit to `backend/app/**`,
`docs/SECURITY_A_SPECIFICATION.md`, `docs/SECURITY_A_PLAN.md`, `backend/requirements.txt`, the
egress-guard D6 exemption counts, or any file in the untouchable list. `backend/app/main.py`'s sha1
prefix is still `4232af1b4bf7` — the same value the Task-9 `main.py.sha1-….bak` snapshot in this
directory carries, i.e. byte-unchanged through this whole task.

**Written by the application, not by me** (the operator upgrade path deliberately exercised in (C)):
`backend/data/conversations.db` (+`-wal`/`-shm`) gained the `user_credentials` table and 5 rows;
`backend/data/audit.jsonl` gained the `LOGIN` / `AUTHORIZATION/DENIED password_change_required` /
`AUTH_LOGIN_LOCKED` / `PASSWORD/SUCCESS password_changed` events the smoke produced. **This is the
one legitimate writer in `backend/data/` for this task** — stated explicitly so a later reader can
tell it apart from test-written material, of which there is none (conftest's session guard fails any
test that writes credential rows into the protected DB).

**Container side effects:** `/tmp/bench.py` inside `rag-backend-1` (transient, dies with the
container); `rag-backend:latest` is now `1abba3717aa7` — the previous image `f5a2bc5e4651` is still
in the local image store, so a rollback is possible; none was needed (the service came up healthy on
the new image and stayed up for every step of (C)).

## What the next agent still owes (Step 4 / 6 / 7 / 8)

- Step 4: the 19-throw mutation bench (`.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`).
- Step 6: full suite in both cwds, digit-for-digit.
- Step 7: `docs/SECURITY_A_ACCEPTANCE_2026-09-26.md` (T10-1's date correction) — it can cite
  (A)/(B)/(C)/(D) here verbatim: SECA-19 container numbers, the before/after algorithm distribution,
  the four scenarios with 403-then-200 explained, the artifact-deletion proof, the out-of-band
  `legacy_count=0`. T10-2's seven-key env/config table, T10-3's audit-attribution section, T10-4's
  triage, T10-9's two items and **F-1** still need writing up there; §17's L-series must gain the
  Task-8 probe/fallback microsecond-window ruling the ledger already queued, and should consider
  whether F-1 belongs there or in the upgrade runbook.
- Step 8: `git status --short` + the explicit path list for the user; no commit or tag without
  separate authorisation; never touch `model-router-v2.3-rc1`.

