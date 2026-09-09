# Demo Release Checklist

## CI gate

- [ ] `python -m compileall -q backend/app scripts`
- [ ] unit/contract tests pass
- [ ] `python scripts/validate_demo_assets.py` passes
- [ ] `npm install && npm run build` passes

## Runtime gate (local machine)

- [ ] `python scripts/check_demo.py` → PASS
- [ ] admin login works
- [ ] Demo initialization → 20/20 ready
- [ ] `python scripts/demo_smoke.py` → PASS
- [ ] `python scripts/demo_smoke.py --retrieval` → PASS
- [ ] one AI answer returns Citation
- [ ] Citation source opens for authorized role
- [ ] sales role receives 403 for HR KB
- [ ] HR role receives 403 for sales KB
- [ ] audit shows QUERY and ACCESS/DENIED
- [ ] four-mode evaluation completes

## Interview freeze rule

After all runtime gates pass, do not add Agent/MCP/multi-tenant features before the interview. Only fix blockers, copy, or visual defects.
