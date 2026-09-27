# SEC-A Task 10b — 19-mutation bench — **COMPLETE**

Verdict: **19 / 19 KILLED**, 0 TARGET-NOT-FOUND, 0 ANCHOR-NOT-UNIQUE, 0 unattackable.
One SURVIVED on the first pass (M16) → closed by adding a test (M16 now killed by that
test alone). All 19 rows restored byte-for-byte (`sha1` re-verified in the `finally` of
every row; the harness `raise SystemExit(3)`s the whole run on a mismatch).

Deliverables:

- `.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py` — the harness
  (`--check` verifies all 19 anchors without touching the tree).
- `.superpowers/sdd/SECURITY_A_PLAN/task-10b-mutations-run.txt` — raw stdout of the
  authoritative 19/19 run (per-row `pytest` summary + every `FAILED` line + restore OK).
- One test added: `backend/tests/test_credentials_contract.py` (test files may gain
  tests; nothing else in the tree changed — see §6).

## 1. Result table

Killed-node column is capped at 3 names in the harness table; the full set is in
`task-10b-mutations-run.txt`. "Δ" = the row's `N failed, M passed` from the focused node.

| Code | §13 property | SECA row | Verdict | Δ | Killed node(s) | Re-anchored | restore |
| --- | --- | --- | --- | --- | --- | --- | --- |
| M1 | Argon2 → `hashlib.sha256` | SECA-01 | KILLED | 2F/3P | `Argon2ProfileTests::test_hashed_password_is_a_verifiable_argon2id_phc_string`, `::test_a_wrong_password_does_not_verify` | cosmetic (needle was a suffix of an 8-space line) | OK |
| M2 | must_change 门去掉 | SECA-10 | KILLED | 1F/5P | `SelfServiceChangeTests::test_changing_password_logs_in_clears_the_gate_and_kills_old_tokens` | no | OK |
| M3 | `require_user` 不再比对 cv | SECA-09 | KILLED | 2F/7P | `TokenRevocationTests::test_a_bumped_version_invalidates_the_previously_issued_token`, `::test_a_forged_cv_does_not_outlive_the_table` | **yes — snippet absent** | OK |
| M4 | 未知账号早退（删哑校验） | SECA-13 | KILLED | 1F/4P | `UnifiedFailureTests::test_all_four_states_consume_exactly_one_argon2_run_each` | **yes — needle hit 2×** | OK |
| M5 | 锁定响应体带锁定字样 | SECA-14 | KILLED | 1F/1P | `LockedHttpFaceTests::test_locked_wrong_password_and_unknown_account_are_the_same_http_face` | **yes — needle 2×, replacement uncompilable, CRLF** | OK |
| M6 | throttle 键去掉 client_ip | SECA-16a | KILLED | 3F/5P | `ThrottleLayerTests::test_two_source_addresses_on_the_same_username_have_independent_buckets` (+2 bucket-table tests) | no | OK |
| M7 | lockout 计数键改按 ip | SECA-16b | KILLED | 1F/7P | `ThrottleLayerTests::test_many_source_addresses_on_one_username_share_the_account_lock` | **yes — plan snippet attacked a different property** | OK |
| M8 | redact 子串匹配 `token` | SECA-17 | KILLED | 6F/39P | `test_the_persistence_deny_set_matches_case_insensitively`, `test_persistence_redaction_kills_sensitive_keys_by_exact_name`, `test_persistence_redaction_covers_the_full_deny_set_not_just_the_spec_sample` (+3) | no | OK |
| M9 | redactor 扩到 `user_store` | SECA-17 + SECA-03 | KILLED | 1F/4P | `UserStoreSchemaTests::test_created_rows_are_always_argon2id` | **yes — needle hit 3×** | OK |
| M10 | cv bump 拆成独立事务 | SECA-11 | KILLED | 1F/4P | `UserStoreTransactionTests::test_password_change_bumps_version_and_clears_lock_state_together` | **yes — re-expressed as the §13 attack (2 edits)** | OK |
| M11 | 重置不清 lock | SECA-12 | KILLED | 1F/8P | `AdminResetTests::test_admin_reset_clears_a_stale_lock_in_the_same_transaction` | no | OK |
| M12 | 身份 schema 放开 `extra` | SECA-07 | KILLED | 1F/52P | `IdentityFileTests::test_unknown_extra_fields_are_rejected_not_ignored` | no | OK |
| M13 | 业务代码新增一处口令 hashlib | SECA-05 | KILLED | 2F/3P+9sub | `CentralisationScanTests::test_only_credentials_module_hashes_passwords`, `::test_the_exemption_table_is_equal_to_the_hit_set` | **yes — snippet absent** | OK |
| M14 | 重哈希写盘失败改为拒绝登录 | SECA-21 | KILLED | 3F/11P | `LegacyUpgradeTests::test_a_rehash_write_failure_still_logs_in_and_records_degraded`, `::test_capacity_loss_at_the_rehash_hop_degrades_instead_of_refusing_the_login`, `::test_a_rehash_that_loses_the_version_race_leaves_the_concurrent_winner_alone` | **yes — snippet absent (comment inserted)** | OK |
| M15 | 凭据材料写进 `config/` | SECA-07 / SECA-04 扫描面 | KILLED | 3F/51P+46sub | `ShippedIdentityFilesTests::test_both_files_ship_and_pass_their_own_validator`, `::test_demo_mode_ships_exactly_the_demo_accounts` (+1) | no | OK |
| M16 | `m/t/p` 改从 env 读取 | SECA-19 / SEC-A-008 | **SURVIVED → KILLED** | 1F/4P | `Argon2ProfileTests::test_the_profile_does_not_budge_when_the_environment_is_poisoned` (**new test, §4**) | **yes — needed `import os` added** | OK |
| M17 | cv 缺失即放行 | SECA-09b | KILLED | 2F/8P+4sub | `TokenRevocationTests::test_a_pre_seca_token_without_cv_is_rejected_not_allowed` | **yes — snippet absent** | OK |
| M18 | demo 静默覆盖企业身份 | SECA-23 | KILLED | 3F/50P+47sub | `IdentityFileTests::test_duplicate_username_across_files_fails_instead_of_letting_demo_override`, `MergeInvariantTests::test_duplicates_inside_one_file_are_rejected_too`, `::test_the_conflict_message_names_the_clashing_identity_and_who_tried` | no | OK |
| M19 | 全新安装缺行时自动导入 legacy | SECA-04b | KILLED | 1F/7P+7sub | `SourceRemovalTests::test_a_missing_credential_row_never_imports_the_upgrade_artifact` | **yes — needle hit 2×** | OK |

## 2. Snippet drift log (plan text → current code text)

Governing rule (`task-10-brief.md` Step 4): a drifted snippet is fixed **against the code
as it stands**; the SECA row a mutation backs and the property under attack do not move.
Line numbers below are the current tree.

| Row | Plan snippet (as written in Step 4) | Current code | What I changed and why |
| --- | --- | --- | --- |
| M1 | `"    return _HASHER.hash(plain)"` (4 sp) | `credentials.py:76` is `        return _HASHER.hash(plain)` (8 sp) **inside** `with argon2_slot():` | Wrote the needle at real indentation. The plan's 4-space form only matched as a *suffix* — it happened to work; leaving it means the next edit to that line silently turns the row into a no-op. Injection body unchanged (`hashlib.sha256(plain.encode('utf-8')).hexdigest()`); the slot wrapper is deliberately **kept**, because M1 attacks the primitive, not the gate (destroying the gate is Task 8's P6 row, and mixing them would misattribute the kill). |
| M3 | `"if not isinstance(claimed, int) or claimed != record.credentials_version:"` | `auth.py:435` + `:437` — the single condition was split into a **type gate** (`isinstance(claimed, bool) or not isinstance(claimed, int)`) and a **version gate** during Task 5/6 | TARGET-NOT-FOUND. Re-anchored to the version gate only: `if claimed != record.credentials_version:` → `if False and …`. This is *narrower and stricter* than the plan's form: the plan's mutation would also have switched off the type gate, i.e. it would have attacked M3 **and** M17 in one blow. M3 now attacks exactly "cv 不再比对" (SECA-09) and leaves M17's arm intact. |
| M4 | `"credentials.verify_dummy(password)"` → `pass` | `auth.py:305` (unknown/disabled/no-row dummy leg) **and** `:322` (wrong-password-on-legacy leg) | Needle hit 2×; the plan's `replace(…,1)` would have been betting on source order. Added the `if identity is None …` line above as context so the mutation lands on the SECA-13 leg (the four-state equal-cost claim), which is what §13's M4 names ("未知账号早退"). |
| M5 | `"raise HTTPException(status_code=401, detail=\"用户名或密码错误\")"` → `… if result.audit_detail != auth.AUDIT_LOGIN_LOCKED else \"账号已锁定，请稍后再试\"` | `main.py:342` (login leg) **and** `:407` (self-service change leg); `main.py` has **no** `import app.auth as auth` — only `from app.auth import (…)`, and `AUDIT_LOGIN_LOCKED` is not in that import list | Two drifts. (a) Needle hit 2× → added the following `if result.audit_detail:` line as context, pinning the login leg (M5 is a login-face mutation; the change leg shares the copy but not the criterion). (b) The plan's replacement body would `NameError` → 500, i.e. red for the wrong reason; `auth.` prefix dropped and the token written as the literal `"AUTH_LOGIN_LOCKED"` (value identical to `auth.AUDIT_LOGIN_LOCKED`). Also: `main.py` is entirely CRLF (measured 987 LF / 987 CRLF) so both needle lines carry `\r\n`. |
| M6 | — | `login_throttle.py:39` | Plan snippet matches verbatim. |
| M7 | `"app/user_store.py"`, `"WHERE username = ?"` → `"WHERE locked_until IS NULL AND username = ?"` | `WHERE username = ?` occurs **8×** in `user_store.py` (`get_record`, `set_password_argon2`, `_bump_and_clear`, `apply_rehash`, `record_login_failure` ×3, `clear_login_failures`, `delete_record`) | Two drifts, the second one material. (a) Mechanically the row is ANCHOR-NOT-UNIQUE. (b) More importantly that injection does **not** implement §13's M7: adding `locked_until IS NULL` to `get_record` makes a locked row read as "no row at all", which attacks SECA-14's unified-failure face, not "lockout 计数键改按 ip" (SECA-16b). §13 and the test file agree on the intended target — `ThrottleLayerTests`' own docstring says 「账号锁只看 username（M7 唯一可杀处）」, and `task8_proofs.py` P2 already ran this row at that site. Re-anchored to the counting write: `user_store.record_login_failure(username, …)` → `record_login_failure(f"{username}|{client_ip}", …)`, i.e. one counter per source address ⇒ the account lock never trips. SECA row and property unchanged. |
| M8 / M11 / M12 / M15 / M18 | — | — | All four match verbatim and hit exactly once. |
| M9 | `"    encoded = credentials.hash_password(plain_password)"` (comment: 只改第一处 create_argon2) | Same line occurs **3×** (`create_argon2:188`, `set_password_argon2:244`, `apply_rehash:293`) | "First occurrence" is source order, not intent. Pinned with the `create_argon2` docstring line above it. Replacement body kept as the plan wrote it (`encoded = "[REDACTED]"`). |
| M10 | `"def _bump_and_clear("` → `"def _bump_and_clear_disabled("` | Helper exists at `user_store.py:264`, called at `:246` | The plan's rename is legal Python-wise but it attacks the wrong thing: after the rename the call site raises `NameError` and the whole password change fails, so the state §11/SECA-11 forbids — *new hash committed, cv still old* — is never produced. The rename does get red (cross-checked below), purely because `test_a_failing_version_bump_rolls_back_the_new_hash` patches `_bump_and_clear` by name. Re-expressed as §13's actual attack in two edits: (A) `credentials_version = credentials_version + 1,` removed from `_bump_and_clear`'s UPDATE; (B) `set_password_argon2` re-opens `with closing(_connect()) as connection, connection:` and performs the bump in a **second transaction** after the hash write has committed. That commits the forbidden intermediate state, and `test_password_change_bumps_version_and_clears_lock_state_together` goes red because the epoch handed back to the caller (1) no longer equals the row's (2). Cross-check of the plan's literal form: `2 failed, 3 passed` (both `test_a_failing_version_bump_rolls_back_the_new_hash` via `AttributeError` on the patch target and the epoch pin) — so the re-anchored form is not a softer row, it is the same verdict reached through the property instead of through a name. **Residual gap worth naming:** no test observes "new hash + old cv" *as a DB state*, because in the real implementation hash and bump are one SQL statement, so the state is unrepresentable — that is the strongest available form of SECA-11, and M10 is what shows a refactor splitting them would stop being invisible. |
| M13 | `"from app import credentials, directory, user_store"` | `auth.py:11` is `from app import credentials, directory, login_throttle, user_store` | TARGET-NOT-FOUND (member added in Task 5). Re-anchored to the current import line; injected body (`import hashlib` + `_m13_probe(password) → sha256`) is the plan's, character for character. |
| M14 | `"if forced and not wrote:\n            detail = AUDIT_REHASH_DEGRADED"` | `auth.py:352-355` — two comment lines now sit between the `if` and the assignment (added in the Task 6/7 audit-attribution rounds) | TARGET-NOT-FOUND. Included the comment lines in the needle; replacement body is the plan's (`return LoginResult(None, AUDIT_INVALID_CREDENTIALS, False)`). |
| M16 | `"ARGON2_MEMORY_COST = 19456"` → `int(os.environ.get('ARGON2_MEMORY_COST', 19456))` | Line present; **`credentials.py` does not import `os`** (imports are hashlib/hmac/re/contextlib/dataclasses/threading/argon2/app.config) | As written the injection `NameError`s at import time and the node dies in collection — red that belongs to no criterion. Second edit adds `import os` so the mutation contributes exactly one new thing: an env channel. |
| M17 | same needle as M3, replacement `if claimed is not None and claimed != record.credentials_version:` | cv gate is now two statements (see M3), so the plan's replacement has nothing to sit on | TARGET-NOT-FOUND. Re-anchored one line up, at `claimed = payload.get(CREDENTIAL_VERSION_CLAIM)`, inserting `if claimed is None: claimed = record.credentials_version` — semantically §13's `if cv is None: allow()`, and literally the shape Task 6's bench used (`task-6-mutations.py` `m17-none-allows`). |
| M19 | `"if identity is None or not identity.enabled or record is None:"` | Identical line at `auth.py:304` (login leg) **and** `:425` (`_user_from_token`, token leg) | Needle hit 2× → pinned with the following `credentials.verify_dummy(password)` line, i.e. the login leg, which is where "缺凭据行就顺手导入升级工件" (§8.2's separation) actually lives. Injection body is the plan's, unchanged. |

## 3. Harness deviations from the Step 4 skeleton

Both deviations are precision/robustness only; neither can turn a red row green.

1. **`-x` removed** (`-q --tb=line -p no:cacheprovider` instead of `-q -x`). With `-x`
   the reported "killer" is whichever test sorts first, not the one owning the criterion:
   M6's first run died on `ThrottleLayerTests::test_reaping_does_not_depend_on_the_clock_…`
   (bucket key collapse shrinks the sweep table) and the run stopped **before** reaching
   the SECA-16a pin that §13 designates as M6's only kill site. Running the whole node
   costs a few extra seconds (fixed cost is module collection + session fixtures, and a
   node is one class or one file) and every red judge now signs itself.
2. **Anchors must hit exactly once** (skeleton required ≥1). 0 hits → `TARGET-NOT-FOUND`;
   >1 hits → `ANCHOR-NOT-UNIQUE`; neither touches the tree. Six plan needles were
   ambiguous (M4/M5/M7/M9/M19 and — as a suffix — M1); all six were pinned down rather
   than left to `replace(…,1)`'s source-order bet.
3. Multi-edit injections added (M10, M16) — a single substring cannot express "moved into
   a second transaction" or "constant now read from env in a module that has no `os`".
4. Restore check upgraded: the skeleton `assert sha1 == before` inside `finally`; here an
   explicit mismatch path prints `RESTORE-FAILED` and `raise SystemExit(3)`, aborting the
   remaining rows rather than mutating a second file on a dirty tree.

## 4. Tests added

**One.** `backend/tests/test_credentials_contract.py::Argon2ProfileTests::test_the_profile_does_not_budge_when_the_environment_is_poisoned`
plus the `import importlib.util` it needs (46 added lines; file stays LF, 0 CRLF).

- Why it is the mutation and not the test's own bug — RED evidence chain:
  1. **Before adding it, M16 was SURVIVED** on the plan's own node: the focused
     `Argon2ProfileTests` run returned rc=0 with **zero** failures while the env-tunable
     profile was in the tree. That is exactly the "decorative test" case §13 exists to
     catch, and it is why the row is listed as `SURVIVED → KILLED` rather than KILLED.
  2. The pre-existing pin `test_profile_is_the_owasp_minimum_baseline_and_is_a_code_constant`
     cannot see M16: it asserts `credentials.ARGON2_MEMORY_COST == 19456`, and
     `int(os.environ.get('ARGON2_MEMORY_COST', 19456))` **is** 19456 with no env set.
     Same for `test_hasher_exposes_one_shared_instance_at_that_profile` (asserts the live
     hasher matches the constant — both move together).
  3. With the new test present and **no mutation**: `5 passed in 1.30s` (so the test is
     green on the real tree; it is not red-by-construction).
  4. With the new test and **M16 injected**: `1 failed, 4 passed`, and the single failure
     is the new test — `Argon2ProfileTests::test_the_profile_does_not_budge_when_the_environment_is_poisoned`.
  5. Isolation check (the test re-executes `app/credentials.py` under a poisoned env, so
     the risk is leakage): `python -m pytest tests/test_credentials_contract.py
     tests/test_secret_hygiene_contract.py -q` → `137 passed, 44 subtests passed`. The
     probe module is built with `spec_from_file_location`, registered in `sys.modules`
     only for the duration of `exec_module` (dataclasses resolve their module through
     `sys.modules`), and popped in a `finally`; `importlib.reload` of the live module is
     deliberately **not** used (`app.main` binds `PasswordCapacityError` at import time —
     swapping that class object would silently break the 503 legs, which is the tax
     `sec_a_fixtures.py` warns about at the top of the file).
- What the test asserts: with `ARGON2_TIME_COST=1`, `ARGON2_MEMORY_COST=1`,
  `ARGON2_PARALLELISM=4` in the environment, a fresh execution of the module still yields
  `2 / 19456 / 1` **and** the constructed `PasswordHasher` still reports
  `time_cost=2, memory_cost=19456, parallelism=1` (constants agreeing with themselves is
  not enough — the profile that ships is the one on the hasher instance), and the live
  `credentials.hasher()` is untouched.

No other row needed a new test.

## 5. What I could not attack

**Nothing.** All 19 §13 rows have a live injection site on the current tree. Three rows
needed a translation rather than a re-anchor, and the translations are the ones a reviewer
should look at hardest: M7 (plan snippet pointed at `get_record`, §13 points at the
counting key), M10 (plan snippet renamed a helper, §13 points at the transaction
boundary), M3/M17 (one condition became two gates, so the two rows now attack different
arms — M3 the comparison, M17 the presence of the claim).

## 6. Tree settled: 103-file manifest re-verification

`snap-task10b-pre-sha1.txt` (103 files under `backend/app`, `backend/tests`,
`backend/config`) re-hashed after the last bench row:

- checked 103, mismatches **1** — and it is the intentional one:

| File | pre | post |
| --- | --- | --- |
| `backend/tests/test_credentials_contract.py` | `39aa928f7ad2c0494b32800c42714e598389a30f` | `aaad67cc3ce9f7d3e25d632e1309978632447fd0` |

102/103 byte-identical; the one delta is a test file gaining the M16 pin (§4), which the
task brief permits. Every mutated file (`app/credentials.py`, `app/auth.py`,
`app/main.py`, `app/login_throttle.py`, `app/user_store.py`, `app/security.py`,
`app/directory.py`, `config/users.demo.json`) was restored by the harness and re-verified
against the manifest by this pass — no file needed a manual restore.

`git status --short` (read-only) shows no stray artifacts from the bench: the
`M`/`??` entries are Tasks 1–10 work that predates this task (HEAD is stale in this
repo), and the only files this task added are
`.superpowers/sdd/SECURITY_A_PLAN/{task-10b-report.md,task-10b-mutations-run.txt}` and
`.superpowers/sdd/SECURITY_A_PLAN/mutations/sec_a_mutations.py`. No git write command was
run; `model-router-v2.3-rc1` untouched; no file restored from git; `backend/data/` never
written; no full-suite run (19 focused nodes only).

## 7. For the acceptance document (Step 7)

The 19-row table in §1 above is the §13 evidence, and
`task-10b-mutations-run.txt` is its raw backing. One sentence worth carrying into the
acceptance doc: **18 of 19 rows killed the tree they were aimed at on the first try; the
one that did not (M16) exposed that SECA-19's "强度参数不可 env 调" half had no judge at
all** — §12's SECA-19 row is written as a container benchmark, and the constant pins in
`Argon2ProfileTests` read as if they covered SEC-A-008 while being blind to exactly the
env channel SEC-A-008 forbids. That is now pinned behaviorally.
