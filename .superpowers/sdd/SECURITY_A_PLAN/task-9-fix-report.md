# SEC-A Task 9 — review findings fix report (5 Important + minors)

Status: DONE. Entering suite 1260 passed / 36 warnings / 1117 subtests (both cwds) → post-state below.
Baseline snapshots: `snap-task9-fix-pre-app`, `snap-task9-fix-pre-test_secret_hygiene_contract.py`.
Spec anchors: §9.3 (two redaction scopes), §10 (secret/env boundary), §8.5 (dual mode + guard position),
SECA-18, SECA-20.

All scan-gate work is in `/e/xiangmu/rag/backend/tests/test_secret_hygiene_contract.py`.
No git command that mutates the index/HEAD/worktree was run; every simulation used
read-only `git ls-files` + a `/tmp` copy of the file list.

---

## Fix 1 (Important) — the gate went red the moment SEC-A is committed

**Root cause.** The shipped pattern keyed on `(?i)\b(?:api[_-]?key|secret|token|password|passwd)\b`
followed by an optional quote and `[A-Za-z0-9_\-]{16,}`. The value class accepted *identifiers*, so
`password = _password_from_env` (a call, no value) was a hit, and `docs/*.md` prose quoting that same
statement was a hit. The gate therefore demanded exemptions for text that is not credential material
at all, and its real targets were invisible (Fix 2).

**What changed.** The literal face now requires a **quoted, whitespace-free literal value**:

```
["']? (?:api[_-]?key|secret|token|pass(?:word|wd)) [\w-]* ["']?
(?:\s*:\s*[A-Za-z0-9_\[\], .|]*)?        # 注解写法：jwt_secret: str = "…"
\s*[:=]\s* (?P<quote>["']) [^"'\\ \t]{16,} (?P=quote)
```

Three deliberate details: the leading `\b` is gone (Fix 2); the value must be a literal, not an
identifier/call (this Fix); the annotated assignment form is on the face, otherwise
`config.py`'s `jwt_secret: str = "…"` would be a blind spot.

Old-vs-new on the shapes that matter (probe over the shipped `_occurrence_lines`):

| sample | old pattern | new faces |
| --- | --- | --- |
| `JWT_SECRET=<32 chars>` (env) | 0 | 1 |
| `APP_SECRET=<value>` (env) | 0 | 1 |
| `OPENAI_API_KEY=sk-<value>` (env) | 0 | 1 |
| `password = _password_from_env()` | **1 (false positive)** | 0 |
| `jwt_secret: str = "change-me-…"` | 0 | 1 |
| `JWT_SECRET="yaoke-ci-integration-secret-…"`, | 0 | 1 |
| bare `sk-abcdefghij0123456789` | 0 | 1 |

**Scope decision — two tiers, not 15 exemptions:**
* `*.md` **outside** `.superpowers/` (the delivery docs: `docs/**`, `README.md`) stays **on the
  material-shape face only**. Prose quotes code and fixture literals by construction
  (`docs/SECURITY_A_PLAN.md` alone holds 32 legitimate references → exempting them per line is the
  "15 exemptions" shape the review rejected), but a real provider key pasted into a doc
  (`sk-…` / `eyJ…` / PEM header) still reddens the gate. Measured today: **51 delivery markdown
  files, 0 material-shape hits** ⇒ this tier costs no exemptions and leaves no drift debt, and it
  closes the "secret exists only in a doc" hole instead of declaring it out of scope.
* `.superpowers/**` (SDD process artifacts: plans, reports, per-round `baseline-app/` copies) is off
  the surface entirely. Stronger reason than prose: those documents carry **deliberate canary**
  literals (`sk-CANARY-<16-hex>-not-in-any-message`) and byte-for-byte copies of `app/` sources, so
  every already-exempt item would appear a second time; and the directory is gitignored by default,
  force-added selectively as evidence. Binding the exemption counts to it is exactly the failure
  being fixed here — the next `snap-*` force-add reddens the gate for a reason that has nothing to do
  with credential material.

Residual risk, named on the gate: material that appears **only** inside process artifacts is out of
this gate's reach. That is the gitleaks-class whole-history scanner registered in spec §18 as
follow-up work; SEC-A explicitly adds no third-party scanner and no security job.

**Rebuilt `EXEMPTIONS`** (16 rows, 31 occurrences) — every row states *why that material is not
credential material* (factory default the startup guard refuses to boot on / audit enum token /
env-variable *name* / test decoy fixture / localStorage key name / local-only script fixture), and
`test_every_exemption_states_why_it_is_not_material` pins non-empty, specific justifications plus
file existence, so "just a test file" rows cannot be added.

**Commit-time proof, no index touched.** The shipped gate now scans
`git ls-files --cached --others --exclude-standard` = the surface that will enter the repo, so the
scanned file set is identical today and after Task 10 commits. Measured with the shipped scanner over
a `/tmp` file list (`git ls-files -c -o --exclude-standard`, 254 files; `*.md`/`.superpowers`/binary
dropped by the shipped scope rule):

BEFORE (pre-fix pattern, same file set) — 8 sites, and the 3-row exemption table could not cover them:

| site | matched text (key side only) | classification |
| --- | --- | --- |
| backend/tests/test_feishu_identity_contract.py:1856 | `SECRET ` | fake fixture (already exempt) |
| backend/tests/test_typesafe_api_runtime.py:126 | `secret ` | test decoy (already exempt) |
| backend/tests/test_typesafe_judgments.py:216 | `secret ` | test decoy (already exempt) |
| backend/app/cli.py:113 | `password ` | **a call, not a value** |
| backend/tests/test_authentication_leg_contract.py:139 | `SECRET ` | fake fixture |
| backend/tests/test_password_lifecycle_contract.py:127 | `SECRET ` | fake fixture |
| backend/tests/test_secret_hygiene_contract.py:356 | `password ` | **prose quoting the call** (the new face comment itself) |
| docs/SECURITY_A_PLAN.md:2637 | `password ` | **prose quoting the call** |

AFTER (shipped new faces, same file set) — 31 sites / 16 files, table == measured → gate GREEN, and
it stays green after the commit because the file set does not change:

| file | occurrences | file | occurrences |
| --- | --- | --- | --- |
| backend/.env.example | 1 | backend/tests/test_model_router_v23_contract.py | 10 |
| backend/app/auth.py | 2 | backend/tests/test_password_lifecycle_contract.py | 2 |
| backend/app/cli.py | 1 | backend/tests/test_secret_hygiene_contract.py | 4 |
| backend/app/config.py | 1 | backend/tests/test_typesafe_api_runtime.py | 1 |
| backend/app/security_startup.py | 1 | backend/tests/test_typesafe_judgments.py | 1 |
| backend/tests/test_authentication_leg_contract.py | 1 | frontend/src/lib/api.ts | 1 |
| backend/tests/test_feishu_identity_contract.py | 1 | frontend/src/lib/conversations.ts | 1 |
| scripts/conversation_p1_integration.py | 1 | scripts/deploy.ps1 | 2 |

Tracked-only (`--cached`) still measures 22 sites / 11 files, i.e. the 5 rows that SEC-A's untracked
files contribute are exactly the ones the old gate would have turned into unexplained red.

No laundering: every face that was *dropped* coverage on is a call/identifier or prose quoting one;
the newly covered shapes (env assignments, typed defaults, bare `sk-…`/`eyJ…`/PEM material) are all
additive, and two of them are proven live by `test_a_planted_credential_turns_the_gate_red`.

---

## Fix 2 (Important) — env-shaped leaks were structurally invisible

Verified with the pre-fix pattern: `JWT_SECRET=<value>`, `APP_SECRET=…`, `OPENAI_API_KEY=sk-…` all
produce **0 hits** (leading `\b` plus `_` being a word character). Consequences: the brief's
expectation that `.env.example:132` would hit was unachievable, and real material already sitting in
tracked files (`scripts/conversation_p1_integration.py:33`, `scripts/deploy.ps1:95,107`) was invisible.

Two changes:
1. the leading `\b` is gone from the literal face (and the key stem may carry prefixes/suffixes, so
   `JWT_SECRET`, `DEFAULT_JWT_SECRET`, `tenant_access_token` are all on-face);
2. a targeted **env face**, unquoted-native, scoped to `.env*`, compose and `scripts/`:

```
[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|APIKEY)[A-Z0-9_]* [ \t]*[:=][ \t]*
["']?[A-Za-z0-9_.\-/+~]{16,}
```

It is not applied repo-wide because an unanchored `UPPER_NAME=value` collides with regex literals and
comparisons everywhere else (`deploy.ps1` itself is the proof: its `(?m)^JWT_SECRET=…` *pattern* must
be on-face, while the same shape inside Python source would be noise). Its value class also excludes
`$`, so `JWT_SECRET=$secret` (an interpolation at `deploy.ps1:108`) is correctly not material.

Now-measured env sites: `.env.example:132` (factory default, as the brief expected),
`scripts/conversation_p1_integration.py:33`, `scripts/deploy.ps1:95` + `:107`. Faces are merged by
overlapping span, so a leak matched by both the literal and env face counts as **one** occurrence.

Exemptions rebuilt accordingly (16 rows above). The underscore-tolerant variant measured repo-wide
would have produced ~49 sites; the scoped design lands on 31 with every site individually justified,
and no whole-directory blind spot inside the delivery surface.

---

## Fix 3 (Important) — gate granularity: line-number keys could launder

`_scan_hits()` used to dedupe to a set of `file:line` and the offender loop skipped by site, so a
second credential placed on an already-exempt line was silenced, and any edit above an exempt line
moved the whole table.

Replaced with the sibling's shape (`tests/test_llm_egress_guard.py:111-129`): the key is
**(file → occurrence count, why)**, and `_gate_offenders()` compares counts in three directions —
unexempted file, count drift either way, dead table row. `test_a_second_credential_on_an_exempt_line_is_not_silenced`
proves the property end-to-end: it takes a real exempt line (`security_startup.py`'s default-constant
line), appends a **second** credential on that same line in a `/tmp` copy, and asserts the count
becomes `EXEMPTIONS[rel] + 1` *and* the gate reports that file. Old code would have reported nothing.

Failure messages now carry only path + counts; matched snippets are no longer printed (the pre-fix
offender message embedded the first 24 chars of the match, i.e. it copied credential material into CI
logs).

---

## Fix 4 (Important) — the startup guard's only enforcement point was unasserted

`main.py:87` is the repo's sole call to `assert_startup_safe()`, and `TestClient(app)` without `with`
never runs the lifespan: deleting that line left all 1260 tests green.

Added `StartupGuardLifespanTests`, which drives the **real** lifespan three ways under patched
enterprise settings:
* `SECURITY_ENTERPRISE_MODE=true` + default secret + empty CORS ⇒ `with TestClient(app)` raises
  `SecurityStartupError` out of startup (two of the three guards fire together — §8.5's
  "同生同死" on the execution point);
* dev default (`false` + default secret) ⇒ same lifespan starts clean and serves a request
  (kills "replaced the guard with an unconditional raise");
* enterprise fully configured ⇒ starts clean (kills "guard always refuses").

SECA-18's direct-call tests are kept unchanged — §8.5 requires a test that does *not* depend on the
lifespan; the lifespan test is additive coverage of the enforcement point.

---

## Fix 5 (Important) — `action="PASSWORD"` threading

**Invariant (now stated in `main.py`'s comment and pinned through the routes):** event attribution is
decided by the **route**, not by a helper default. `/api/auth/login` ⇒ every denial is `LOGIN`;
`/api/auth/password/change` (and the admin reset leg) ⇒ **every** denial is `PASSWORD` — policy 422,
throttle 429, capacity 503, wrong `current_password` 401. The change route validates the old password
through the same arbiter and the same counter as login, but mixing `LOGIN` into its audit stream makes
"someone is hammering the password endpoint" indistinguishable from "someone is hammering login".

* Code: `main.py:402` now records `action="PASSWORD"` for the wrong-`current_password` leg (CRLF
  preserved: 983 → 987 lines, no lone LF/CR).
* Tests: `PasswordLegActionAttributionTests` drives real HTTP on the route for all four denial legs
  plus the reverse pin that the login route keeps `LOGIN` for 401 and 503. Removing `action=` at
  either call site turns these red; the pre-existing helper-level tests stay (they pin the writer
  threading, which the route tests deliberately do not).

**Frontend decision (approved deviation, one list entry):** `frontend/src/views/OperationsView.tsx:114`
`logTypes` gains `"PASSWORD"` so the events are filterable instead of render-only-raw. Nothing else in
the frontend was touched: `ACTION_LABELS` (the display-name map) was deliberately left alone, since
SEC-A's scope said no frontend change and the review allowed "the one-word chip addition" only if it
is genuinely one list entry. Without the chip, `PASSWORD` events still render but cannot be filtered;
with it, the invariant above is operable. If the reviewer prefers zero frontend delta, the alternative
is to revert this line *and* drop `PASSWORD` back to `LOGIN` everywhere — which would undo Task 8's
"capacity denial must not masquerade as LOGIN" pin, so it was rejected.

---

## Minors folded in

* `其余 24 处（含 8 处响应面 return）` — replaced by structural pins; the response-face count is now
  asserted as **17** `redact_secrets(...)` call sites outside `security.py` (measured via AST; 7 of
  them are `return redact_secrets(...)`), so the stale "8" is gone rather than re-stated.
* Deny-set pinned: `EXPECTED_PERSISTENCE_DENY_SET == security.PERSISTENCE_SENSITIVE_KEYS` (dropping
  `current_password` / `credentials` / `secret` goes red) + a case-insensitivity pin (uppercase
  variants are redacted, uppercase observability keys are not) matching `security.py:319`'s
  `str(key).lower()`.
* `NOT_SECRETS` is now live: it drives the observability-collateral test (`set(payload) == set(NOT_SECRETS)`)
  and the disjointness pin `not set(NOT_SECRETS) & PERSISTENCE_SENSITIVE_KEYS`.
* `count("redact_for_persistence") >= 2` replaced by `_call_sites()` AST counting: audit 2, agent_trace
  2, 4 total outside the definition module.
* Vestigial `audit_module_detail_capacity()` wrapper deleted; the test reads
  `auth.AUDIT_PASSWORD_CAPACITY` directly.
* SECA-20 falsification added: `test_a_planted_credential_turns_the_gate_red` plants
  `JWT_SECRET="<26-char value>"` into a tracked-looking file under `tmp_path` (nothing touches the
  repo) and asserts the gate reports it. Planted fixtures are built by **concatenation** so this test
  file does not add hits of its own (its count stays 4, pinned in the table).
* `app/conversation_agent.py:478` — stale "唯一的兜底是 … `redact_secrets()`" now names
  `redact_for_persistence()` (形态脱敏 + 精确键名黑名单). Comment-only edit in a CRLF file
  (601 → 602 CRLF lines, 0 lone LF/CR); no code change.
* `.env.example` — the Argon2 `m/t/p` rationale appeared twice (line 143-144 and 146-147); the
  duplicate is collapsed into the single block that keeps the pointer to `app/credentials.py`
  (CRLF preserved: 200 → 199 lines, 0 lone LF/CR).

---

## Rulings against the spec letter (recorded, per the brief's conflict rule)

1. **SECA-20 wording "tracked-file 密钥扫描测试".** The gate now scans
   `git ls-files --cached --others --exclude-standard` — a *superset* of tracked (it also sweeps
   SEC-A's still-untracked files, which is the only way the gate can be green before and after the
   Task 10 commit), with process artifacts under `.superpowers/` off-surface and delivery markdown
   kept on the material-shape face. Rationale and residual named on the gate itself (§18 keeps
   gitleaks as the follow-up; no new CI job, no third-party scanner — spec-conformant).
2. **§9.3's "全部 28 处调用点".** That 28 is a textual-grep count (it includes `def redact_secrets`
   and in-body mentions). The AST-measured response-face call sites outside `security.py` are **17**
   (7 of them `return redact_secrets(...)`); that is what the new pin asserts. `redact_secrets`
   semantics and every one of its call sites are byte-identical — the number is a counting method,
   not a code change, and the reviewer's "8 returns" figure was likewise stale (measured 7).
3. **`action="PASSWORD"` → frontend display layer** (see Fix 5). This item's original wording
   ("one frontend list entry … everything else in the frontend is untouched, including
   `ACTION_LABELS`") is **superseded**: the controller subsequently ruled that the new audit token
   must be localized, adding `PASSWORD: "口令变更"` to `ACTION_LABELS` in `OperationsView.tsx` and
   `GovernanceView.tsx`. Full accounting in *Controller ruling — `PASSWORD` audit action localized*
   below (3 frontend lines total).

---

## Verification

Focused: `tests/test_secret_hygiene_contract.py` + `tests/test_branding_contract.py` → **45 passed**.

| gate | result |
| --- | --- |
| rbac + typesafe_security + feishu_identity + typesafe_api_runtime | **140 passed**, 13 warnings, 206 subtests |
| model_router_v23 + llm_egress_guard | **427 passed**, 18 warnings, 452 subtests |
| credentials + authentication_leg + password_lifecycle + user_directory | **267 passed**, 101 subtests |

Full suite (both cwds): **1273 passed / 36 warnings / 1117 subtests** in
`cd backend && python -m pytest -q`, and **the identical counts** from repo-root
`python -m pytest backend/tests -q`. Equal counts is the point — the cwd-sensitive failures found in
earlier rounds would surface as a delta between these two. Both runs were executed by the controller
and are attributed to those runs; they were not re-executed during this verification pass.

Falsifications (byte-exact restore + sha1): all five executed. Backups were taken by this pass
(`cp` into `.superpowers/sdd/SECURITY_A_PLAN/<file>.sha1-<digest>.bak`), **never from git**; no git
write command was run at any point. Every restore was verified against the pre-mutation sha1 **and**
against the per-file line-ending census (mutated files: `main.py` 987 CRLF / 0 lone LF / 0 lone CR /
46436 B; `security.py` 0 / 334 / 0 / 14011 B; `test_secret_hygiene_contract.py` 0 / 892 / 0 / 51222 B).
Final sweep after the last mutation: all three sha1s match their "before" values, no mutation marker
and no stray 0x08 byte anywhere.

| # | mutation (file) | focused command | red | restore sha1 | green after |
| --- | --- | --- | --- | --- | --- |
| F-A | drop `action="PASSWORD"` from the wrong-`current_password` audit call (`app/main.py` ~405-406, Fix 5) | `pytest tests/test_secret_hygiene_contract.py -q -k PasswordLegActionAttribution` | 1 failed / 4 passed — `PasswordLegActionAttributionTests::test_wrong_current_password_on_the_change_route_is_a_password_event` (`'PASSWORD' != 'LOGIN'`) | yes (4232af1b…) | yes (5 passed) |
| F-B | remove `security_startup.assert_startup_safe()` from the lifespan (`app/main.py:87`, the repo's only call site) | `… -q -k StartupGuardLifespan` | 1 failed / 2 passed — `StartupGuardLifespanTests::test_enterprise_default_secret_refuses_during_real_startup` (`DID NOT RAISE SecurityStartupError`) | yes (4232af1b…) | yes (8 passed, F-A+F-B together) |
| F-C | drop `"current_password"` from `PERSISTENCE_SENSITIVE_KEYS` (`app/security.py:303`) | `pytest tests/test_secret_hygiene_contract.py -q` | 2 failed / 41 passed — `test_the_persistence_deny_set_is_exactly_the_intended_key_set`, `test_the_persistence_deny_set_matches_case_insensitively` (`Current_Password` survives redaction) | yes (38811538…) | yes (43 passed) |
| F-D | re-add the leading `\b` to the literal-face key stem (`tests/test_secret_hygiene_contract.py:384`, the Fix 2 regression) | `pytest tests/test_secret_hygiene_contract.py -q` | 4 failed / 39 passed — `test_repository_tracked_files_hold_no_credential_material`, `test_the_exemption_table_matches_the_hit_set`, `test_a_planted_credential_turns_the_gate_red`, `test_a_second_credential_on_an_exempt_line_is_not_silenced` | yes (3ad48430…) | yes (43 passed) |
| F-E | `redact_for_persistence()` → passthrough (`return value` as first statement, `app/security.py:310`) | `pytest tests/test_secret_hygiene_contract.py -q` | 7 failed / 36 passed — see note below | yes (38811538…) | yes (43 passed) |

F-A and F-B each turn red exactly the test the fix round claims to protect, so both fixes are live
wires, not decorations. F-B in particular closes the review's finding that deleting the only call
site left the suite green.

**F-D result is stronger than "different hit set".** With `\b` restored, the gate does not merely
disagree with the exemption table — it goes *blind*: `test_a_planted_credential_turns_the_gate_red`
fails with `KeyError: 'backend/app/planted_secret_holder.py'`, i.e. the planted credential is no
longer reported at all, and `_occurrence_lines()` returns empty (`IndexError`) for the already-exempt
line. The stem without `\b` is what makes `current_password` / `api_key` inside longer identifiers
match, and the exemption table is pinned to that shipped face.

**F-E — 7 red, and one honest gap.** Red: `test_the_persistence_deny_set_matches_case_insensitively`,
`test_persistence_redaction_kills_sensitive_keys_by_exact_name`,
`test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample`,
`test_persistence_redaction_still_runs_shape_matching`,
`test_the_two_faces_differ_on_exactly_the_key_name_blacklist`,
`LoginResponseVsPersistenceBoundaryTests::test_historical_audit_row_with_token_key_is_erased_on_read`,
`LoginResponseVsPersistenceBoundaryTests::test_real_login_token_is_usable_yet_erased_in_a_persistence_row`.
**Gap:** the other test the brief expected here,
`test_the_four_persistence_faces_use_the_persistence_redactor`, did **not** go red. It is an AST
call-site counter (audit 2 / agent_trace 2 / 4 outside the definition module), so it pins that the
redactor is *called* on each face and cannot see a gutted body. The persistence face is still covered
— 7 behavioral tests catch the passthrough, including both boundary tests — but "the four faces use
it" is a presence pin, not an effect pin. Recorded as a residual, not fixed (verification-only pass).

**Partial-coverage nuance on F-C / F-E (informational, not a defect).**
`test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample` iterates the *live*
`PERSISTENCE_SENSITIVE_KEYS`, so it stays green when a key is removed from that set (F-C) and only
turns red when the redactor itself stops working (F-E). `current_password` is therefore guarded by
the deny-set pin (`EXPECTED_PERSISTENCE_DENY_SET`, independent of the live set) rather than by the
full-coverage behavior test. That is the intended division of labor, but it is worth naming.

**Process note (no code impact).** Two mutation attempts were aborted by this pass before ever
reaching a test: the first F-D pattern wrote a literal backspace byte (shell escaping) instead of the
two-character sequence, and the first F-E insertion duplicated the docstring terminator, leaving a
file that could not be imported. Both were caught by inspecting the written bytes, restored to their
recorded sha1, and re-applied correctly (F-D then verified to contain the real word-boundary stem;
F-E verified with `ast.parse` plus a direct behavioral probe showing the passthrough). No test was
ever run against a corrupt file, so the table above is unaffected.

### Controller ruling — `PASSWORD` audit action localized (frontend delta)

Recorded as the controller's decision, not this pass's.

SEC-A excluded frontend changes, but Fix 5 ships a new **display-layer** audit token (`PASSWORD`), and
`FilterChips` renders `ACTION_LABELS[t] ?? t` (`frontend/src/views/OperationsView.tsx:164`) — so an
unlocalized token would surface as raw English inside an otherwise fully Chinese-ized UI. Both
`ACTION_LABELS` maps previously covered every other action, which makes the gap a consistency defect
in the display layer rather than a new feature.

Verified present (read-only):
* `frontend/src/views/OperationsView.tsx:34` — `PASSWORD: "口令变更"` inside `ACTION_LABELS`;
  `:115` `logTypes` carries `"PASSWORD"` (from the fix round); `:75` `ACTION_LABELS[action.toUpperCase()] ?? action`.
* `frontend/src/views/GovernanceView.tsx:51` — `PASSWORD: "口令变更"`; `:86` same fallback lookup.

Scope-deviation accounting: **3 lines of frontend**, = 1 `logTypes` entry (`OperationsView.tsx:115`,
already landed in the fix round) + 2 label entries (`OperationsView.tsx:34`, `GovernanceView.tsx:51`).
No component logic, no API contract, no routing, no styling changed. The backend is unaffected:
the token itself was already spec'd, and no test asserts on frontend content.

`npm run build`: the controller's background log was not present on disk, so the build was run once
here — **exit 0**. Next.js 16.3.5 (Turbopack), compiled successfully in 1249 ms, TypeScript clean in
3.0 s, 6/6 static pages generated; routes `/`, `/_not-found`, `/admin/agent`, `/admin/audit`,
`/admin/evaluation`. `PASSWORD` is a display-layer-only token: no test asserts on frontend content.

### Re-measured numbers (this pass)

`test_the_persistence_deny_set_is_exactly_the_intended_key_set` and its companion
`test_the_persistence_deny_set_matches_case_insensitively` both go red on a single-key removal from
`PERSISTENCE_SENSITIVE_KEYS` (F-C), so the deny set is independently pinned. The whole-file focused
run `pytest tests/test_secret_hygiene_contract.py -q` was re-measured at **43 passed** after every
restore in this pass (it is the fast loop used for F-C / F-D / F-E); the **45 passed** figure in the
header above includes `tests/test_branding_contract.py` and was not re-run here.

---

# Fix round 2 — 复评（round 1）新增项的收口

**作者：控制器本人**（1 个函数 + 若干用例与注释，非派发实现方）。复评 round 1 的判定是 F1–F5 全 ADDRESSED、
四条"新增破坏"里 NB-1 是 Important。本轮处理 NB-1 的小写一半、NB-2、NB-3、NB-4，以及复评 round 2
自己提出的 Minor 1/2/3/4。评审对象：`task9-fix2-review-package.md`（base = sha1 `3ad48430…`）。

## NB-1 的完整闭合（复评 round 2 的 Minor 1：不对称只修了一半）

`_faces_for` 改成按**语法**分四档，而不是按目录：

| 档 | 覆盖面 | 变化 |
| --- | --- | --- |
| `*.md` | 材料形状 | 不变 |
| **配置档** = `.env*` + compose + `.yml/.yaml/.ini/.conf/.toml/.cfg/.properties` + `Dockerfile*`/`Containerfile*` | 字面量 + **大小写不敏感 env** + 材料 | 本轮从"只 `.env*`/compose/scripts"里把 `.env*`/compose **挪进**大小写不敏感档 |
| `scripts/` | 字面量 + **大小写敏感 env** + 材料 | 留在敏感档，理由见下 |
| 其余（代码/前端） | 字面量 + 材料 | 不变 |

分支顺序改成**先配置档、后 `scripts/`**，于是 `scripts/ci.yml` 不再比 `deploy/ci.yml` 少一面（复评点出的
第二条）。

**`scripts/` 为什么不同**：脚本里 `name=value` 是 Python 关键字参数与 PowerShell 参数的正常写法。实测把
大小写不敏感那枚并进去会多撞一枚纯误报（真实例子 `scripts/release_smoke.py:310`
`min_token_events=args.min_token_events`），并把这枚误报永久钉进 `(文件→处数)` 表。这个不对称现在有
用例托着：`test_scripts_keep_the_case_sensitive_env_face_and_why` 同时钉"真凭据在脚本里仍红"、"关键字
参数不红"、"同一小写形状在配置档必须红"。

**复评要求的形状超集钉**也补了：`set(_CODE_FACES) < set(_CONFIG_FACES)`，防止有人把 `_ENV_FACE_CI`
换回 `_ENV_FACE` 时顺带把代码档弄瞎。

## NB-1/NB-2/NB-3/NB-4 与本轮 Minor 的落点

- **NB-1**：三形状 + compose 小写键 = 四枚植入用例（`test_unquoted_config_file_assignments_are_on_the_face`），
  全部只落 `tmp_path`。实测拓宽**不产生新豁免行**：面 254 文件 / 16 命中文件 / 31 处、`_gate_offenders`
  空，与 base 同一批 31 处（无静默吸收）。焦点文件 43 → 44 → **45 passed**。
- **NB-2**：门注释改成诚实版——markdown 档关的是"现网密钥形状被贴进文档"，明写关不掉散文里的赋值形态
  （`OPENAI_API_KEY = "glpat-…"` 实测 0 命中，`glpat-` 不在材料字符集里）。
- **NB-3**：spec §2 那行的位置清单换成实测 7 处直返面并加"**行号会漂、判据是 AST 等式**"的限定；`:126`
  的"28 处"改口；§20.4 与 §2 复核更正段把"字节级 pin"更正为"行为探针 + AST 等式两枚不同性质的钉"，并
  改为**按测试名引用**（复评 round 2 Minor 4a：同一轮回写把自己引的 `:192` 因加了 4 行 docstring 而
  指错，这正是行号引用该淘汰的现场证据）；`test_redact_secrets_semantics_are_unchanged` 的 docstring
  不再自称 28 处，也不再让人以为它是字节比对。
- **NB-4**：canary 按 `路径:行号` 引用、不得抄进 `docs/**` 的规则写进门注释，并作为 T10-9 移交 Task 10。
  复评实测这一条的方向是安全的：`docs/**` 今天没有 `.md` 行，贴 canary ⇒ 门红 + 人判，** relocates
  friction, not blindness**。
- **复评 round 2 Minor 2**：`makefile`/`procfile` 从配置档剔出。理由不是"没测到"而是"主动招噪"：Make 的
  `:` 是规则分隔符，实测 `test-secrets: backend/tests/….py` 与 `VAULT_TOKEN_PATH = /var/run/secrets/…`
  都会命中，而仓内两类文件都不存在。`Modelfile.ornith-text` 同理留在代码档。
- **复评 round 2 Minor 3**：门注释补上"别把 0 读成结构性安全"——`ci.yml` 干净的耐久理由是 Actions 把
  token 写成 `${{ … }}` 且 `$` 不在值字符集；`TOKENIZERS_PARALLELISM: "false"` 今天躲过只因值短于 16。
  并写明这一档误差方向是**误报**（会红、要人判），不是漏报。
- **复评 round 2 的 OOO-1**：`backend/.env` 真实存在且被 `.gitignore:6` 挡在面外，这一格现在同时写在
  门注释与 spec §18 里（"本地门不做带历史的检索、也不做未跟踪/被忽略文件的运行时材料"），验收文档不得
  把它说成"仓内无凭据"。

## 判定

NB-1 完整闭合（含小写一半与分支顺序），NB-2/3/4 落地，round-2 的四条 Minor 全部给了动作或书面理由。
全套件两 cwd 逐位相等的终态数见 `progress.md` 的 Task 9 收口行。
