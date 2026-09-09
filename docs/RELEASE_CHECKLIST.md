# Demo Release Checklist · P1.4

## CI gate

- [ ] `python -m compileall -q backend/app scripts`
- [ ] `python scripts/validate_demo_assets.py` passes
- [ ] RBAC / Agent / routing / web-security contract tests pass
- [ ] `npm install && npm run build` passes

## Base runtime gate (local machine)

- [ ] `python scripts/check_demo.py` → PASS
- [ ] admin login works
- [ ] Demo initialization → 20/20 ready
- [ ] `python scripts/demo_smoke.py` → PASS
- [ ] `python scripts/demo_smoke.py --retrieval` → PASS
- [ ] one enterprise answer returns Citation
- [ ] Citation source opens for an authorized role
- [ ] SALES receives 403 / no HR evidence
- [ ] HR receives 403 / no Sales evidence
- [ ] four-mode RAG evaluation completes

## P1.4 Agent gate

- [ ] `python scripts/agent_smoke.py` → PASS
- [ ] Local mode exposes only `enterprise_search`
- [ ] Auto/Web modes expose `enterprise_search` + `web_search`
- [ ] `python scripts/agent_smoke.py --agent` → PASS
- [ ] X100 internal query creates an `enterprise_search` Tool Call
- [ ] Local mode never produces `web_search` or Web evidence
- [ ] SALES Agent result contains no `kb_hr`
- [ ] HR Agent result contains no `kb_sales` / `kb_product` / `kb_service`
- [ ] Agent trace contains observable Tool events but no hidden reasoning fields
- [ ] Agent Debugger `/admin/agent` opens the latest trace
- [ ] audit shows `TOOL_CALL`, `TOOL_RESULT` and `QUERY`
- [ ] maximum Tool Call rounds is 3; loop exhaustion forces final synthesis

## External Web gate

Run this only when the machine has normal outbound internet access:

- [ ] `python scripts/agent_smoke.py --agent --web` → PASS
- [ ] public-current question selects `web_search`
- [ ] at least one public Web evidence item is returned with title/domain/url
- [ ] DDGS failure does not make enterprise RAG endpoints unavailable

## Security gate

- [ ] `localhost`, loopback and RFC1918 URLs rejected
- [ ] `169.254.169.254` rejected
- [ ] `file://` and `ftp://` rejected
- [ ] no arbitrary URL `web_fetch` tool exists in P1.4
- [ ] model-provided KB arguments cannot widen user-selected KB scope
- [ ] model never acts as the authorization component

## Interview freeze rule

After these runtime gates pass, freeze features before the interview. Only fix blockers, copy, visual defects, or reproducibility issues; do not add ERP/CRM writes, MCP, Multi-Agent or unrelated infrastructure.
