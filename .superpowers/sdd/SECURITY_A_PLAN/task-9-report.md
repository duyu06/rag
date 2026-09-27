# Task 9 — secret hygiene (redaction two-domains + enterprise startup guards + CORS from config + repo secret-scan gate)

## Status: IN PROGRESS (report-first; appending per gate)

Working dir: `E:\xiangmu\rag`, backend at `E:\xiangmu\rag\backend`. Entering baseline per task: 1230 passed / 36 warnings / 1114 subtests (task-8 final was 1221; re-confirming at end).

## Verified facts before any change
- `redact_secrets` call sites in `app/`: **28** (grep count). `return redact_secrets(` response faces: **8**. Files touched by count: agent.py, agent_routes.py, agent_trace.py, audit.py, conversation_agent.py, conversation_store.py, conversation_stream_routes.py, knowledge_os.py, main.py, security.py. This is the real number used in comments/assertions (task-8 review correction: not 51).
- `PERSISTENCE` faces to switch (4 sites): `audit.py:47` (record_event write), `audit.py:63` (recent_events read), `agent_trace.py:73` (save_trace), `agent_trace.py:91` (get_trace). All import `redact_secrets` from `app.security`.
- `user_store.py`: confirmed NO `app.security` import (structural pin target).
- `config.py`: `security_enterprise_mode: bool = False` at ~157; `jwt_secret` default literal `change-me-before-production-yaoke-demo-secret` at 159; `cors_allow_origins` DOES NOT exist yet.
- `main.py` CRLF: CORS `allow_origins=["*"]` at 95; single `lifespan` runs `warmup_identity_permissions()` then `warmup_llm_router()` (82-83); no-echo handler compares `request.url.path` (120) = root_path hole.
- `.env.example` CRLF: throttle/lock/capacity keys already present (138-142, Task 8). OWES `SECURITY_ENTERPRISE_MODE` + `CORS_ALLOW_ORIGINS`. No `*PASSWORD*` key present (satisfies SEC-A-002 test).
- Spec §9.3 / §10 / §8.5 / §11 / §16 read. Brief key set for `PERSISTENCE_SENSITIVE_KEYS`: password, password_hash, plaintext_password, current_password, new_password, access_token, refresh_token, authorization, api_key, app_secret, tenant_access_token, secret, credentials.
- Pre-change snapshots staged: `snap-task9-pre-app` (controller), `snap-task9-app` (mine, = copy of pre), `snap-task9-pre-test_branding_contract.py`, `snap-task9-pre-test_password_lifecycle_contract.py`.

## Plan (verbatim values from brief where given)
1. `security.py`: append `PERSISTENCE_SENSITIVE_KEYS` + `redact_for_persistence()` (exact full-word key deny set; NO substring; do NOT touch redact_text/redact_secrets).
2. `security_startup.py`: new — DEFAULT_JWT_SECRET, SecurityStartupError, evaluate_startup_guards, assert_startup_safe.
3. Switch 4 persistence faces to `redact_for_persistence`.
4. `config.py`: add `cors_allow_origins: str = "http://localhost:3000"` (CRLF surgical).
5. `main.py`: CORS from config; lifespan first-call `assert_startup_safe()` + docstring restate; root_path fix in `_is_no_echo_auth_path` / handler.
6. `.env.example`: add SECURITY_ENTERPRISE_MODE + CORS_ALLOW_ORIGINS with the credential/argon2 comments.
7. Obligation #2: distinguish availability denials (change/reset legs) — decide mechanism after reading current test pins.
8. `test_branding_contract.py:32` rewrite (tightening).
9. New `test_secret_hygiene_contract.py` (SECA-17/18/20 + env-example key gate + user_store structural pin + real-login both-ways proof + root_path pin).
10. Gates + full suite both cwds; guards proof; falsifications.

## Deviations / rulings
- (pending)

## Gate results (appended as captured)

### Focused — test_secret_hygiene_contract.py  [GREEN]
- First run: 1 failed / 30 passed / 2 warnings. RED = `test_audited_login_row_carries_no_token_and_redacts_on_read`
  (asserted a bare JWT under a NON-sensitive key `detail` should be erased — contradicts §9.3 "blacklist
  matches dict KEYS, not value content"). Also 2 InsecureKeyLengthWarnings from real login on 31B dev secret.
- Fixed: rewrote that test to exercise the read-side key-name blacklist on a historical audit row
  (`access_token` key => REDACTED; `Bearer ...` shape => REDACTED; a value-only JWT not sniffed). Added
  LongJwtSecretMixin to the login harness so warning count stays at baseline. Renamed the brief's
  `redact_secrets_semantics_are_unchanged` (missing `test_` prefix => never collected) to `test_...`.
- Re-run: 30 passed, 0 warnings. GREEN.

### Live-scan gates  [GREEN]
- Gate A branding+rbac+typesafe+feishu+runtime: 142 passed / 13 warnings / 206 subtests / 0 fail (baseline group was 140/13/203; +2 passed = branding's 2 methods, my edits add no new methods/subtests in that set).
- Gate B model_router_v23 + llm_egress_guard: 427 passed / 18 warnings / 452 subtests / 0 fail — EXACTLY baseline; D6 counts did NOT move.
- Gate C credentials + user_directory + authentication_leg + password_lifecycle: 267 passed / 101 subtests / 0 fail. Task 7 no-echo byte tests + Task 8 capacity pins + user_store structural + AST equality pins all intact after the record_login_event action-threading.

### Guards are real (in-process lifespan, never edited backend/.env)  [GREEN]
- enterprise + default JWT + CORS unset      -> REFUSED_TO_BOOT (2 violations)
- enterprise + default JWT + CORS '*'         -> REFUSED_TO_BOOT (2 violations)
- enterprise + strong JWT + explicit CORS     -> BOOTED
- dev (enterprise=false) + defaults           -> BOOTED clean (guard is a total no-op)

### Falsifications (revert line -> named RED test -> restore -> sha1)  [ALL RED + sha OK]
| mutation | red test | result |
| --- | --- | --- |
| M8 substring `token` in key check | test_persistence_redaction_does_not_collateral_damage_observability_keys | RED, restore sha OK |
| persistence blacklist applied to redact_secrets (response face) | test_redact_secrets_does_not_apply_the_persistence_key_blacklist | RED, restore sha OK |
| user_store imports a redactor (append `from app.security import`) | test_user_store_is_never_passed_through_a_redactor | RED, restore sha OK |
| JWT guard disabled while enterprise on (`if False:`) | test_the_three_guards_live_or_die_together | RED, restore sha OK |
| root_path comparison reverted to request.url.path | test_change_leg_stays_no_echo_under_nonempty_root_path | RED, restore sha OK |
- root_path divergence proven in-test: with scope path `/gw/api/auth/password/change`, root_path `/gw`: request.url.path=`/gw/...` (NOT matched => leak on revert), get_route_path=`/api/auth/password/change` (matched => no-echo). Test asserts they differ before asserting the guard.

### Rulings (brief vs code/spec)
- Brief parametrize row `(enterprise=True, DEFAULT_JWT_SECRET, "http://localhost:3000") -> 2` is internally inconsistent with the brief's OWN evaluate_startup_guards (valid CORS => only JWT guard fires => 1). Ruled for SPEC §8.5 (two independent guards): that row = 1. Added rows: valid CORS + default JWT =>1; enterprise+default+cors-empty=>2; enterprise+short+"*"=>2; enterprise+empty+""=>2; strong+explicit=>0; dev=>0. "All three fire together" is carried by the enterprise rows (both code guards) + demo-identity being structural (directory never loads users.demo.json under enterprise), not a code guard.
- Brief's helper `redact_secrets_semantics_are_unchanged` lacks the `test_` prefix => never collected. Prefixed it so it actually runs (SEC-A-006 pin).
- agent_trace.py is CRLF (92 lines) though the task's CRLF exception-list omits it; test_branding_contract.py is CRLF too though the task says tests are LF. Ruled for the actual bytes ("surgical edits, verify bytes"): preserved both as CRLF via byte-level edits; sha1/line-ending verified.

### Full suite, both cwds  [GREEN, equal counts, zero failures]
- `cd backend`            : 1260 passed / 36 warnings / 1117 subtests in 273s
- `cd /e/xiangmu/rag`     : 1260 passed / 36 warnings / 1117 subtests in 292s
- Delta vs entering baseline: +30 passed (my new test_secret_hygiene_contract.py), +0 warnings
  (login harness uses LongJwtSecretMixin so no InsecureKeyLengthWarning drift), +0 subtests.
  Both cwds identical => conftest's data-dir/relative-path guard holds; nothing of mine landed in backend/data/ (verified: no data/ changes in git status).

### Five carried obligations — status
1. §9.3 two domains + authorized-store exception: DONE. PERSISTENCE_SENSITIVE_KEYS (13 keys) + redact_for_persistence appended to security.py; redact_secrets untouched (28 sites / 8 response faces verified by count before/after). Only 4 persistence faces switched (audit write+read, agent_trace save+get). user_store structural pin green; bidirectional SECA-17 green.
2. record_login_event 503 fidelity: DONE via a new `action` kwarg (default "LOGIN"). Change/reset legs now pass action="PASSWORD" so capacity/throttle denials on those legs are distinguishable WITHOUT a new detail token (§9.1 value domain frozen — password_capacity/login_throttled still live in LOGIN_AUDIT_DETAILS, emitted via the single login writer). Login-leg denials unchanged. Pinned by AvailabilityEventAttributionTests.
3. Task 7 P0 root_path hole: DONE. Handler now compares get_route_path(request.scope) (routing's actual value) instead of request.url.path; divergence proven in-test; 4 root_path pins green.
4. §10 config/secret boundary: DONE. cors_allow_origins default "http://localhost:3000"; security_startup.py guard module wired as lifespan first call; SECA-18 direct-call parametrize green; in-process boot proof shows refuse/boots; .env.example got SECURITY_ENTERPRISE_MODE + CORS_ALLOW_ORIGINS with CREDENTIALS_PASSWORD-forbidden + Argon2 m/t/p-absent comments.
5. SECA-20 scan gate: DONE as a tracked-file pytest gate; EXEMPT_HITS (3) == hits; exemption-table-equality reverse pin green; real number 28 (not 51) used in comments.

### Files changed (mine, Task 9)
- app/security.py (append PERSISTENCE_SENSITIVE_KEYS + redact_for_persistence; LF)
- app/security_startup.py (NEW; LF)
- app/audit.py (import + 2 persistence calls; LF)
- app/agent_trace.py (import + 2 persistence calls; CRLF preserved, 92/92)
- app/config.py (cors_allow_origins; CRLF preserved)
- app/main.py (CORS from config, lifespan guard, root_path fix, availability-action; CRLF preserved 983)
- app/auth.py (record_login_event action kwarg; LF)
- .env.example (2 keys + comments; CRLF preserved)
- tests/test_branding_contract.py (tightened; CRLF preserved)
- tests/test_secret_hygiene_contract.py (NEW; LF)

### Self-review
- redact_secrets byte-identical: only appended below it; falsification #2 proves response face stays untouched.
- Persistence redactor never sniffs values (only dict KEYS by exact word); a value-only JWT under `detail` is not erased — matches §9.3; documented + pinned.
- Real login proof: token survives HTTP AND authenticates /api/auth/me (200), yet the same value is REDACTED through the real agent_trace persistence round-trip => an over-broad redactor would 401 the login (test would red).
- Comments are Chinese invariant prose; no task/plan/brief narration in product code.

### Concerns / hand-off to Task 10 (收口)
- SECA-20 gate scans `git ls-files` => SEC-A's own files are currently UNTRACKED and thus not gated yet. On commit the hit set grows to 8 (5 new):
  backend/app/cli.py:113 (`password = _password_from_env()` — false positive, a call not a literal),
  backend/tests/test_authentication_leg_contract.py:139, backend/tests/test_password_lifecycle_contract.py:127 (both test `SECRET` fixtures),
  (my test_secret_hygiene_contract.py was made self-hit-free). Task 10 must extend EXEMPT_HITS with those 3 (+ any others) so the equality pin stays green — this is by design the "豁免表==命中表，只增不减" discipline.
- Brief's guard parametrize row (valid CORS => 2) was wrong vs spec; ruled for spec (=1). Noted in Rulings.
