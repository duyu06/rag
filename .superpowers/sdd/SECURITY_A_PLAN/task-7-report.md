# Task 7 report — 改密 / 管理员重置端点 + 凭据运维 CLI

Working dir: `E:\xiangmu\rag`. Built incrementally; each gate appended the moment it passed.
Pre-change snapshots: `.superpowers/sdd/SECURITY_A_PLAN/snap-task7-pre-app/`,
`snap-task7-pre-test_password_lifecycle_contract.py`,
`snap-task7-pre-test_authentication_leg_contract.py`, `snap-task7-pre-conftest.py`.

Entering baseline sha1:
- `backend/app/auth.py` 35c15bc66f0e0f6fc256ac104ffdc8aafe66182c
- `backend/app/main.py` 3fe74f1fb35e65035ca1860be0610e90ebf39a03
- `backend/tests/test_password_lifecycle_contract.py` 83a4af869a0ab2656cf9019f7ef533e3583d9b4a

## Plan of record (planned steps)

1. Pre-change snapshots (done, see above).
2. Step 1 RED: append Task 7 tests (policy / self-service change / admin reset / CLI) to
   `tests/test_password_lifecycle_contract.py`; extend the route-enumeration `WHITELIST` to
   `{"POST /api/auth/password/change", "GET /api/auth/me"}` in the same change. — done
3. Step 2: capture RED evidence (`app.cli` missing + 404s on the new routes). — done (RED-A/RED-B)
4. Steps 3–5: implement `auth.validate_new_password`, `auth.provision_credentials`,
   the two endpoints in `main.py`, and `app/cli.py`. — done, focused file green
5. GREEN on the focused file; then the auth-leg file; then the four gate bundles; then both-cwd full suites.
   — focused/auth-leg/gates A–C done; both-cwd full suites: see "Gate log" GREEN-3/4
6. Hand-run the CLI: `migration-status`, `bootstrap-admin` (existing + missing identity), `reset`,
   each with and without `CREDENTIALS_PASSWORD`. — done, output pasted verbatim
7. Three revert-proofs (fresh token, must_change split, `--password` argv), restore byte-exactly,
   report sha1s. — done (see "Revert-proofs"; sha1s equal before/after each case)
8. Handoffs 1–8 disposition + self-review + concerns. — written below

## RED evidence

**RED-A** (Step 2, `app.cli` absent) — `cd backend && python -m pytest tests/test_password_lifecycle_contract.py -q`:

```
_________ ERROR collecting tests/test_password_lifecycle_contract.py __________
tests\test_password_lifecycle_contract.py:65: in <module>
    from app import cli  # noqa: E402  —— 凭据运维面（本文件是它唯一的契约读者）
E   ImportError: cannot import name 'cli' from 'app' (E:\xiangmu\rag\backend\app\__init__.py)
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 1.83s
```

**RED-B** (the two routes do not exist yet) — same shape as the brief's "两条 404", captured with an
inline probe against a temp `CONVERSATION_DB_PATH` and a redirected `app.audit.AUDIT_PATH`
(nothing written under `backend/data/`; probe was `python - <<'PY'`, no file left behind):

```
knowledge-bases: 200 0.015s {'knowledge_bases': [{'id': 'kb_public', ...
POST /api/auth/password/change -> 404
POST /api/admin/users/ghost/password/reset -> 404
```

Side-fact taken from the same probe: `GET /api/knowledge-bases` is a local registry read
(0.015s, no Qdrant/LLM), so it is safe as the "改完密就能正常用" data face in the change tests —
which is why Task 6's `/api/query` tripwire idiom is not needed there.

## Gate log

**GREEN-1 — focused files** (`cd /e/xiangmu/rag/backend`):

```
$ python -m pytest tests/test_password_lifecycle_contract.py -q
63 passed, 12 subtests passed in 58.05s        # entering: 38 passed / 5 subtests
$ python -m pytest tests/test_authentication_leg_contract.py -q
46 passed, 7 subtests passed in 46.78s         # entering: 46 tests — unmoved
```

+25 tests / +7 subtests, all in the lifecycle file (4 policy + 6 self-change + 6 admin-reset +
8 CLI + the reworked whitelist probe). The auth leg is untouched at 46.

Intermediate RED-C (before implementation, after the test append) produced exactly the three
shapes the brief predicts once `app.cli` exists: the 3 first-run failures were
`PasswordPolicyTests` (422 copy ordering), `CliTests.test_the_cli_never_accepts_a_password_on_argv`
(`argparse.SubParsersAction` does not exist — my probe used a private class name), and
`CliTests.test_the_cli_writes_the_enum_audit_token_and_no_password` (exit 2 on the second call,
because `main()` pops `CREDENTIALS_PASSWORD` from `os.environ` — see ruling R-6). All three are
test-side or ordering findings, recorded under "Self-review".

**GREEN-2 — the three gate bundles** (`cd /e/xiangmu/rag/backend`):

```
$ python -m pytest tests/test_rbac_contract.py tests/test_typesafe_security_contract.py \
    tests/test_feishu_identity_contract.py tests/test_typesafe_api_runtime.py -q
140 passed, 13 warnings, 200 subtests passed in 99.43s      # entering: 140 passed
$ python -m pytest tests/test_model_router_v23_contract.py tests/test_llm_egress_guard.py -q
427 passed, 18 warnings, 452 subtests passed in 78.65s      # entering: 427, D6 counts unmoved
$ python -m pytest tests/test_credentials_contract.py tests/test_user_directory_contract.py -q
121 passed, 82 subtests passed in 45.08s
```

D6's egress counts are pinned *inside* `test_llm_egress_guard.py`, so 427 green is the
statement that they did not move; the route-enumeration gate went green in both directions with
the two-entry whitelist (bundle A includes it).

## CLI hand-runs

Run as `python -m app.cli` through a two-line wrapper that only redirects
`app.audit.AUDIT_PATH` into the same temp dir as the temp `CONVERSATION_DB_PATH` — the CLI
module itself, argparse, `directory`, `user_store` and `auth` all execute for real. Nothing was
written under `backend/data/` (verified: the audit lines below landed in the temp file only).
The console first echoed the Chinese as GBK mojibake (known MSYS/GBK shape on this box); the
verbatim UTF-8 strings are the ones quoted, and both runs produced the same bytes.

```
$ CREDENTIALS_PASSWORD=<unset>            python -m app.cli credentials migration-status
legacy_count=0 argon2id_count=0                                     [exit 0]
$ CREDENTIALS_PASSWORD=<set, 24 chars>    python -m app.cli credentials migration-status
legacy_count=0 argon2id_count=0                                     [exit 0]

$ CREDENTIALS_PASSWORD=<unset>            python -m app.cli credentials bootstrap-admin --username admin
CREDENTIALS_PASSWORD 未设置或不足 12 字符：口令只能放在这个环境变量里，不接受任何命令行参数形式
                                                                    [exit 2]
$ CREDENTIALS_PASSWORD='an-operator-password 123'  ... bootstrap-admin --username admin
admin: algorithm=argon2id version=1 must_change=0                   [exit 0]

$ CREDENTIALS_PASSWORD='an-operator-password 123'  ... bootstrap-admin --username ghost
身份不存在：ghost（请先写入 config/users.json）                        [exit 2]

$ CREDENTIALS_PASSWORD=<unset>            python -m app.cli credentials reset --username admin
CREDENTIALS_PASSWORD 未设置或不足 12 字符：口令只能放在这个环境变量里，不接受任何命令行参数形式
                                                                    [exit 2]
$ CREDENTIALS_PASSWORD='a-second-operator pw 1234' ... reset --username admin
admin: algorithm=argon2id version=2 must_change=1                   [exit 0]

$ python -m app.cli credentials migration-status
legacy_count=0 argon2id_count=1
admin	argon2id	v2	must_change=1	locked=-                          [exit 0]
```

Refusals that must not echo the value (same copy for "unset" and "too short", value never shown):

```
$ CREDENTIALS_PASSWORD='short'  ... bootstrap-admin --username admin   -> the one copy above, exit 2
$ CREDENTIALS_PASSWORD='admin'  ... reset        --username admin       -> the one copy above, exit 2
```
(`'admin'` is also the username: the message does not distinguish "too short" from "absent",
and it never carries the value.)

`--password` on argv is rejected by argparse, and the help face has no password option:

```
$ python -m app.cli credentials bootstrap-admin --username admin --password argvleak
usage: python -m app.cli [-h] {credentials} ...
python -m app.cli: error: unrecognized arguments: --password argvleak   [exit 2]

$ python -m app.cli credentials --help
usage: python -m app.cli credentials [-h] {bootstrap-admin,reset,migration-status} ...
  bootstrap-admin     为**已存在的**身份写入 argon2id 凭据
  reset               重置口令并强制下次登录改密
  migration-status    打印各算法行数与逐账号状态
options:
  -h, --help          show this help message and exit
```

Audit face written by those two successful runs (temp sink, note: no password, no hash):

```
{"username": "admin", "role": "ADMIN", "action": "PASSWORD", "status": "SUCCESS", "detail": "credential_bootstrap"}
{"username": "admin", "role": "ADMIN", "action": "PASSWORD", "status": "SUCCESS", "detail": "password_reset_by_admin"}
```

(empty — appended as gates pass)

**GREEN-3 — full suite from both cwds, on the delivered bytes** (run sequentially, after the
gates; each is a whole-session run with the conftest ledger + credential guards active):

```
$ cd /e/xiangmu/rag/backend && python -m pytest -q
1193 passed, 36 warnings, 1111 subtests passed in 225.27s (0:03:45)
$ cd /e/xiangmu/rag && python -m pytest backend/tests -q
1193 passed, 36 warnings, 1111 subtests passed in 216.54s (0:03:36)
```

Equal across cwds, zero failures, zero errors. Against the entering baseline
1168 / 36 / 1101: **+25 tests, +10 subtests, warnings unchanged at 36**. The subtest split is
accounted for: +7 are this file's new policy table (5 → 12), and +3 land in gate bundle A
(task-6's report records it entering at 197 subtests; it now reads 200) — they come from
`test_feishu_identity_contract.py`'s own file- and site-driven AST sweeps
(`rglob("*.py")` over `app/`, `_python_sources(BACKEND_DIR / "app")`), which now see
`app/cli.py` and the two added endpoints. Both bundles stayed green through them, i.e. the new
module passes the repo's own stale-reference / forbidden-call scans.

**GREEN-5 — final re-run of the focused file after all revert-proofs were restored:**

```
$ python -m pytest tests/test_password_lifecycle_contract.py -q
63 passed, 12 subtests passed in 58.04s
```

Delivered sha1s (and the byte shape, which is what the LF/CRLF constraint is about):

| file | sha1 | bytes | shape |
| --- | --- | --- | --- |
| `backend/app/auth.py` | `30f91912d447941d3c92e18878238a862a52499b` | 20913 | LF, loneLF=451, CRLF=0 |
| `backend/app/main.py` | `3ae6c266b0301f05b3cb3a2ffc84be39197bd278` | 35984 | CRLF=861, loneLF=0 |
| `backend/app/cli.py` (new) | `78a922e1419c30e21872585b1c86ec321410e1fc` | 5445 | LF, loneLF=127, CRLF=0 |
| `backend/tests/test_password_lifecycle_contract.py` | `4f712c8ff6cab5012d1162ad521421938e6ed85f` | 89039 | LF, loneLF=1597, CRLF=0 |

Only `app/auth.py` and `app/main.py` differ from `snap-task7-pre-app/` (checked with `cmp` over
every `*.py` in the snapshot); `app/cli.py` is new. Post snapshots:
`snap-task7-post-app/`, `snap-task7-post-test_password_lifecycle_contract.py`.

## Implemented vs brief / deviations

Everything the brief names exists and behaves as specified: `auth.validate_new_password`,
`auth.provision_credentials`, `POST /api/auth/password/change` on
`require_user_pending_password`, `POST /api/admin/users/{username}/password/reset` on the
**existing** `system:operate`, `app/cli.py` with `main(argv)` + `PASSWORD_ENV_VAR` +
`build_parser()`, three actions (`bootstrap-admin`, `reset`, `migration-status`), and the
Task 7 tests appended to `test_password_lifecycle_contract.py`. Nine rulings where the brief
and the code/spec disagreed or under-specified:

**R-1 — the change response shape (handoff #1).** The brief's own Step-1 snippet pins
`{"changed": True}` as the *whole* body **and** asserts that the pre-change login token still
gets 200 from `/api/knowledge-bases` afterwards. Those two cannot both hold on top of Task 6:
`set_password_argon2` bumps `credentials_version`, and `_user_from_token` compares the claim
against the table — `test_the_pending_leg_compares_versions_as_well` already pins that a bumped
token cannot even reach `/me`. Ruled against the spec (§7.5 revocation is the point): the body is
`{"changed", "access_token", "token_type", "password_change_required"}`, the token is issued
*after* the write (so `cv` is the new epoch), and the test now asserts old token → 401
`无效登录凭证` **and** fresh token → 200. Pinned by
`test_the_change_response_shape_is_pinned_and_carries_no_password` (key set, `access_token !=
old`, `cv == table version`, no password / no `$argon2` in the body).

**R-2 — `new_password: Field(min_length=12)` rejected in favour of `min_length=1`.** A pydantic
floor answers a short new password with FastAPI's English structural error under `detail`, which
§9.1 forbids on the display face — and it would make `validate_new_password`'s Chinese copy
unreachable over HTTP. Both fields therefore use `min_length=1` (exactly the shape
`LoginRequest.password` already uses; a short *current* password must still produce the 401
Chinese copy, not a 422) and `max_length=_MAX_PASSWORD_LENGTH`, imported from `auth` so the cap is
one fact rather than three literals. The 12/128 rule and the echo rule are enforced in the handler
→ 422 + Chinese. Pinned by asserting `detail == "新口令长度需在 12 到 128 个字符之间"`, which goes
red the moment someone moves the floor back into the model.

**R-3 — the username-echo rule is unreachable over HTTP for `admin`.** Any casefold-equal string
of `"admin"` is 5 chars, below the floor, so the length rule always answers first; a test that
posted `"ADMIN"` as the new password would have been pinning the length copy while *thinking* it
pinned the echo rule. The HTTP pin therefore uses a ≥12-char username (`operations-lead-01`,
`name.upper()`), and the brief's `admin / ADMIN / AdMiN` triples stay verbatim at the function
level. Ordering (length first, echo second) is now an explicit, named fact.

**R-4 — test scaffolding the brief assumed away.** `_ClientCase`, `self._admin_headers()` and
`_seed_legacy_admin(user_store, auth)` do not exist in Task 6's file; they are implemented with
those exact names so the brief's test bodies are otherwise verbatim. `_seed_legacy_admin` must
delete-then-import because `import_legacy_digest` is `ON CONFLICT DO NOTHING` — otherwise "seed a
legacy admin" silently keeps the argon2 row and the test passes for the wrong reason. Its two
module arguments are checked against the file's own imports (a reload split would otherwise red on
an assertion instead of on the fixture).

**R-5 — two names in the brief's CLI sketch do not exist.** It prints
`credentials.ALGORITHM_ARGON2ID` without importing `credentials`, and calls `auth.record_event`,
which is `import record_event as _record_event` inside `auth` (i.e. `auth.record_event` raises
`AttributeError`). Fixed: `cli` imports `credentials` from `app` and takes `record_event` from
`app.audit` directly.

**R-6 — `_password_from_env()` returns `str | None` instead of raising `SystemExit`.** The brief
flags its own roundabout shape and authorizes this variant. `SystemExit` from inside `main()`
would exit 1 while every other input error exits 2, and the sketch read the env twice. Now one
read, one combined copy for "unset" and "under the floor" (so the message never reveals that a
value was supplied), `main()` returns 2, and the value never enters the message. The pop-out-of
`os.environ` is kept and is now *pinned* — `test_the_cli_writes_the_enum_audit_token_and_no_password`
has to re-supply the env for the second command, which is what makes the pop observable rather
than a comment (this pin is what caught the second CLI call returning 2 during the first green run).

**R-7 — the route-enumeration gate's two designed reds were taken, not worked around.**
`WHITELIST` grew to exactly the two entries (handoff #2), and `PARAM_SAMPLES` gained
`"username": "user-nonexistent"` because a new path param must be registered with a
necessarily-absent sample. Task 6's whitelist probe posted **no body**, which was fine while the
only whitelisted leg was `GET /me`: an empty-body 422 on the change leg would read as "the gate
did not block it" and the check would pass while testing nothing. It now carries a per-route legal
request plus a value-level expectation (`PENDING_PROBE`).

**R-8 — 404 for an unknown identity on the admin reset is kept** (`账号不存在`): the subject has
already passed `system:operate`, so this is the authorized-admin resource face; the login leg
remains the only enumeration face (§9.1). Pinned, plus "the 404 writes no row".

**R-9 — audit `username` differs between the two reset faces, by design and asymmetrically.** The
HTTP reset records the **acting admin** (`user.username`, `user.role`) because the capability use
is what must be attributable; the CLI records the **target** (a CLI process has no actor identity
to name — the operator is the process owner, not a principal). `record_event` has no target field,
so the HTTP face cannot carry both without inventing one. See concerns.

**R-10 — the change leg's failure audit goes out as a LOGIN event.** `record_login_event`
(action LOGIN, DENIED, token ∈ `LOGIN_AUDIT_DETAILS`) is the brief's shape and it is the right
one: `invalid_credentials` / `AUTH_LOGIN_LOCKED` on the change leg mean exactly what they mean on
the login leg. No new audit enum, no second counter (handoff #5).

## Revert-proofs

Driver lived in a temp dir (outside the repo), each mutation restored from an in-memory copy and
re-hashed before the next case. `BEFORE` / `AFTER` sha1s of `main.py` and `cli.py` were equal at
every step, and the focused file re-runs green afterwards (GREEN-5 above).

**(a) delete the fresh-token return** — dropped the line
`        "access_token": issue_token(result.user),` from `main.py`, ran
`SelfServiceChangeTests` + `MustChangeGateCoverageTests`:

```
FAILED ...::SelfServiceChangeTests::test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens
FAILED ...::SelfServiceChangeTests::test_the_change_response_shape_is_pinned_and_carries_no_password
FAILED ...::MustChangeGateCoverageTests::test_the_pending_dependency_is_used_by_the_whitelist_only
3 failed, 10 passed in 40.05s        # first failure is KeyError: 'access_token' (mid-session leg)
    restored byte-exactly: main.py sha1=43b29a691a056812430842736a0603472c8bd736
```

i.e. handoff #1 is load-bearing in three independent places, including the route-enumeration
gate's own probe.

**(b) drop the `must_change` distinction between change and reset** — the reset endpoint's
`must_change=True` flipped to `False`:

```
>       self.assertTrue(user_store.get_record("hr01").must_change, "reset 没置门")
E       AssertionError: False is not true : reset 没置门
FAILED ...::AdminResetTests::test_reset_forces_the_gate_while_a_self_change_clears_it
1 failed in 35.65s
    restored byte-exactly: main.py sha1=43b29a691a056812430842736a0603472c8bd736
```

The named test is the paired one (R-1/handoff #3): it does a self-service change **and** an admin
reset in the same body, so flipping either direction reds it.

**(c) add a `--password` argv option** — `reset.add_argument("--password")` appended in `cli.py`:

```
        with self.assertRaises(SystemExit):        # bootstrap-admin: still raises (option added to reset only)
        with self.assertRaises(SystemExit):
        self.assertEqual("reset", args.action)
>       self.assertFalse(hasattr(args, "password"), "命名空间里多了一枚口令槽位")
E       AssertionError: True is not false : 命名空间里多了一枚口令槽位
FAILED ...::CliTests::test_the_cli_never_accepts_a_password_on_argv
1 failed in 36.51s
    restored byte-exactly: cli.py sha1=52318f137c700f28cd1d5bc49415de5683ed0fbc
```

Reported honestly: with the option added to **one** leaf command only, the red came from the
namespace-slot pin, not from the two `assertRaises(SystemExit)` calls (which probe
`bootstrap-admin` and a `--pwd` spelling). That is exactly why the slot check exists — the
`SystemExit` shape alone would let a single-command regression through. (By the same argparse
semantics, adding the option to `bootstrap-admin` would also red the first `assertRaises` — that
direction was reasoned from the failure shape above, not separately executed.)

## Handoff status (1–8)

1. **Fresh token after a version bump — DONE.** `access_token` re-issued after provisioning;
   `password_change_required` read back from the table through `main`'s own
   `_password_change_required` binding (the one Task 6 pins, so no second door). Response shape
   decided and pinned (R-1). Tests: `test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens`,
   `test_the_change_response_shape_is_pinned_and_carries_no_password`.
2. **`WHITELIST` extended in the same change — DONE**, two entries, both directions of the gate
   still green (`140 passed` in bundle A includes the enumeration). `PENDING_PROBE` makes the
   "both really reach their handler" half non-vacuous (R-7).
3. **`must_change` = 1 after admin reset, 0 after self-service — DONE, both directions in ONE
   test** (`test_reset_forces_the_gate_while_a_self_change_clears_it`) plus the CLI halves
   (`test_bootstrap_writes_an_argon2_row_and_leaves_the_gate_closed` → `must_change` False,
   `test_cli_reset_clears_a_stale_lock_and_leaves_the_gate_open` → True), and the login face says
   `password_change_required: true` for a reset target.
4. **Reset clears a stale lock in the same transaction — proved through the endpoint AND the CLI**,
   not just the store: `test_admin_reset_clears_a_stale_lock_in_the_same_transaction`
   (`locked_until` None, `failed_attempts` 0, v2, and a real login succeeds afterwards) and
   `test_cli_reset_clears_a_stale_lock_and_leaves_the_gate_open`. Both ride
   `auth.provision_credentials` → `user_store.set_password_argon2`, so neither can pass on a
   different write path.
5. **Shared throttle key space — HONORED, nothing built.** The change leg verifies the current
   password via `authenticate_with_result`, so it writes/reads the same `failed_attempts` /
   `locked_until`. `test_the_change_leg_shares_the_login_lockout_state_rather_than_a_second_counter`
   locks the account, shows the change leg answering 401 + `AUTH_LOGIN_LOCKED` + untouched
   credentials, and asserts no second counter exists. **Task 8 handoff:** the throttle itself
   (two-layer, per-IP/identity) is untouched here; when it lands it must cover
   `POST /api/auth/password/change` as the same guessing surface — the endpoint must not be
   exempted just because it is not `/api/auth/login`.
6. **`MigrationReport.skipped` — NOT printed, therefore NOT reinterpreted.** `migration-status`
   prints `credentials_migration.status()` (`MigrationStatus`: two counts + per-account lines) and
   never touches a `MigrationReport`. The module docstring states the invariant for whoever adds an
   import action: print the merged count verbatim or split the field, do not silently re-explain it.
   No `import` action was invented (the brief's parser has exactly three actions).
7. **No `--password` on argv — DONE.** argparse rejects it (`unrecognized arguments`, exit 2), the
   namespace has no slot that could hold one, `--help` lists only `--username`, the value is only
   ever read from `CREDENTIALS_PASSWORD`, it is popped from `os.environ` immediately after use, and
   no stdout/stderr/audit/response surface carries it (each asserted, plus the hand-runs above).
8. **`enabled=false` pairing — untouched and not implied.** The CLI has no disable-adjacent action:
   it writes credentials for an identity that already exists and never reads or writes `enabled`.
   `test_the_cli_prints_nothing_that_claims_an_enable_or_disable_action` pins that the output
   contains neither `启用`/`停用`/`enabled`. The bootstrap-admin-of-a-disabled-identity path stays
   inert because login and the token leg both refuse `enabled=false` (Task 6's pairing pins still
   green in bundles A/C).

## Files changed

- `backend/app/auth.py` — `_MIN_PASSWORD_LENGTH` / `_MAX_PASSWORD_LENGTH`,
  `COPY_PASSWORD_LENGTH` / `COPY_PASSWORD_SAME_AS_USERNAME`, `validate_new_password`,
  `provision_credentials`. Nothing else moved (LF preserved).
- `backend/app/main.py` — three new `app.auth` imports + `_MAX_PASSWORD_LENGTH` +
  `from app.directory import get_identity as get_user_identity`; `PasswordChangeRequest`,
  `AdminPasswordResetRequest`; `change_password`, `admin_reset_password` (CRLF preserved,
  `loneLF=0` after the patch).
- `backend/app/cli.py` — **new**: `PASSWORD_ENV_VAR`, `build_parser`, `_password_from_env`,
  `_print_status`, `main`, `__main__` entry.
- `backend/tests/test_password_lifecycle_contract.py` — 25 tests + 7 subtests added
  (`PasswordPolicyTests`, `SelfServiceChangeTests`, `AdminResetTests`, `CliTests`, `_ClientCase`
  and four module helpers), `WHITELIST`/`PARAM_SAMPLES`/`PENDING_PROBE` extended, `io`/`os`
  imports, module docstring's Task 7 face paragraph.

## Self-review findings / concerns

Findings caught and fixed during this task (each is now a test, not a comment):

- `import_legacy_digest` is `ON CONFLICT DO NOTHING`, so "seed a legacy admin" over an existing
  argon2 row is silently a no-op → the fixture deletes first (R-4). Without that the flagship
  SECA-03 test would have been green while testing the argon2 path.
- The Task 6 whitelist probe posted no body; on a body-carrying whitelisted leg that reads as
  "not blocked" while never reaching the handler (R-7).
- The CLI pops `CREDENTIALS_PASSWORD` from `os.environ` after reading it, so a test that runs two
  commands inside one `mock.patch.dict` sees exit 2 on the second. That failure was the *correct*
  behavior and the test was wrong — the pin was rewritten to prove the pop instead of fighting it
  (R-6).
- `_password_from_env` returning `None` (not raising) keeps every input error at exit 2; argparse
  also uses 2, so "you gave me a bad command line" and "you gave me no password" are the same
  status for an operator script to test.
- `data/audit.jsonl` in the repo grew during this task's **full-suite** runs (pre-existing
  behavior of the non-SEC-A suites); none of my CLI hand-runs touched it — their audit lines went
  to the temp sink and are quoted verbatim above.

Concerns / honest edges, in priority order:

1. **The admin reset's audit line names the actor, not the target** (R-9). `record_event` has no
   target field, and §9.1 wants `detail` to stay an enumerated token, so "who was reset" is only
   recoverable from the credential table's version bump plus the timestamp. Proposed for Task 10:
   either an additive `target` key on `record_event` or a second event — a decision bigger than
   this endpoint, which is why it is not invented here.
2. **Policy ordering is now observable and only documented by two tests**: length before echo
   (R-3). If someone later wants "echo wins over length", the 422 copy changes and both named
   tests red — intended.
3. **[已更正 — 见 fix report P0]** 本条原描述（"new passwords still hit pydantic's English
   structural error; there is no `RequestValidationError` handler in `app/`"）在评审修复轮里已作废：
   两条新腿的 `PasswordChangeRequest` / `AdminPasswordResetRequest` 已去掉 `max_length`，超长/漏填
   改由 `validate_new_password` 的中文 422 判、并由一枚**按路径作用域**的 `RequestValidationError`
   处理器把这两条腿的校验错误回显清零（`app/main.py`）。登录腿仍保留 `max_length`（现取自
   `_MAX_PASSWORD_LENGTH`），它不在本轮脱敏作用域内——那是既有端点、其 422 载荷未被本规格改动。
4. **[已更正 — 原判断有误]** 本条原写"the new legs cannot reach `PasswordCapacityError`"是**错的**。
   `/api/auth/password/change` 会经 `authenticate_with_result(user.username, request.current_password)`
   校验旧口令，那一步走 `_verify_argon2`、落在 Argon2 并发闸门之下 ⇒ 改密腿是**第二条未翻译的
   capacity-500 面**（`PasswordCapacityError` 裸逸成 500）；重置腿在 `provision_credentials` 给新口令
   做 argon2id 哈希时也过同一道闸门。二者都**未**在本轮翻译（本轮只把 `CredentialStoreError` 那类
   存储事故翻成中文 500；`PasswordCapacityError` 是另一条 RuntimeError，不被那枚 except 捕获）。
   capacity→中文 503 的统一处理仍归 Task 8（见其移交清单）。
5. **The change leg has no throttle of its own yet** (by design, handoff #5). Today it inherits
   the account-level lock through `authenticate_with_result`; the IP/identity layer is Task 8, and
   it must include this route.
6. Left deliberately: the `bootstrap-admin` help string in `app/cli.py` contains literal
   `**已存在的**` — markdown asterisks rendered in a terminal help line. It is a one-string fix,
   but the full-suite counts above were measured on the delivered bytes, and re-touching
   `app.cli` would put into the tree a byte pattern those counts do not describe. Flagged for the
   next touch of this file (with the same reasoning that kept the report from quietly re-baselining).
7. Argon2 cost: this file went 38 → 63 tests and now takes ~58s (it pays real hashing per test).
   Still the slowest file in the SEC-A set; if the suite's wall time becomes a problem, the
   `install_demo_credentials` template-copy path is the lever, not fewer assertions.


