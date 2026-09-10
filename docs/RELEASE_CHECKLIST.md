# Demo Release Checklist · P1.6

## CI gate

- [ ] `backend-contracts` → success
  - [ ] `python -m compileall -q backend/app scripts`
  - [ ] `python scripts/validate_demo_assets.py` passes
  - [ ] backend unittest suite passes
  - [ ] Docker Compose configuration validates
  - [ ] Windows deployment script syntax validates
- [ ] `backend-integration` → success
  - [ ] real Qdrant API / RBAC / retrieval integration passes
  - [ ] Conversation persistence + ownership + Citation passes
  - [ ] multi-turn context + Local Fast Path passes
  - [ ] warm BM25 cache passes
  - [ ] P1.6 metadata / RRF / query-enrichment / Ollama policy passes
- [ ] `backend-quality` → success
  - [ ] real `BAAI/bge-small-zh-v1.5` loads successfully
  - [ ] P1.6 real-BGE recall quality gate passes
  - [ ] P1.6 Hybrid Hit@3 remains `1.0000` on the bundled 30-question evaluation set
- [ ] `frontend-build` → success
  - [ ] `npm install`
  - [ ] `npm run build`
- [ ] PR merge后 `main` push CI 再次全绿，不只依赖 PR merge ref

## Base runtime gate（本机）

- [ ] `python scripts/check_demo.py` → PASS
- [ ] admin login works
- [ ] Demo initialization → 20/20 ready
- [ ] retrieval schema is `p16-metadata-rrf-v2`
- [ ] `python scripts/demo_smoke.py` → PASS
- [ ] `python scripts/demo_smoke.py --retrieval` → PASS
- [ ] one enterprise answer returns Citation
- [ ] Citation source opens for an authorized role
- [ ] SALES receives 403 / no HR evidence
- [ ] HR receives 403 / no Sales evidence
- [ ] four-mode RAG evaluation completes

## P1.5 Conversation / Agent gate

- [ ] Conversation can be created, restored, renamed and deleted
- [ ] follow-up question reuses bounded conversation context
- [ ] Local mode uses Local Fast Path for enterprise Q&A
- [ ] failed assistant answer can Retry in place
- [ ] successful Retry keeps the same assistant message id and rewrites Citation / Trace
- [ ] Agent Debugger exposes observable execution events and timings, not hidden reasoning
- [ ] `python scripts/agent_smoke.py` → PASS
- [ ] Local mode exposes only `enterprise_search`
- [ ] Auto/Web modes expose `enterprise_search` + `web_search`
- [ ] `python scripts/agent_smoke.py --agent` → PASS
- [ ] X100 internal query can create an `enterprise_search` Tool Call
- [ ] Local mode never produces `web_search` or Web evidence
- [ ] SALES Agent result contains no `kb_hr`
- [ ] HR Agent result contains no `kb_sales` / `kb_product` / `kb_service`
- [ ] audit contains `TOOL_CALL`, `TOOL_RESULT` and `QUERY`
- [ ] maximum Tool Call rounds is 3; loop exhaustion forces final synthesis

## P1.6 Retrieval regression gate

- [ ] Markdown child chunks preserve parent heading hierarchy
- [ ] adjacent parent/child headings do not create heading-only evidence chunks
- [ ] small / homogeneous BM25 corpora retain lexically matching candidates even when raw or normalized score is non-positive
- [ ] short follow-up query enrichment preserves unrelated identifier families
- [ ] example: `X100 支持 IP65 吗？` → `那 IP67 呢？` still keeps `X100` in retrieval context
- [ ] Vector / BM25 / Hybrid / Hybrid+Rerank all return valid results on the bundled evaluation set
- [ ] P1.6 Hybrid Hit@1 / Hit@3 / MRR are reviewed before release
- [ ] known single-query vector rank movement is treated as diagnostic, not tuned at the expense of overall recall

## External Web gate

Only run when the machine has normal outbound internet access:

- [ ] `python scripts/agent_smoke.py --agent --web` → PASS
- [ ] public-current question selects `web_search`
- [ ] at least one public Web evidence item is returned with title/domain/url
- [ ] DDGS failure does not make enterprise RAG endpoints unavailable

## Security gate

- [ ] `localhost`, loopback and RFC1918 URLs rejected
- [ ] `169.254.169.254` rejected
- [ ] `file://` and `ftp://` rejected
- [ ] no arbitrary URL `web_fetch` tool exists
- [ ] model-provided KB arguments cannot widen user-selected KB scope
- [ ] model never acts as the authorization component
- [ ] Citation source access re-checks KB ACL

## Interview freeze rule

After these gates pass, freeze features before the interview. Only fix blockers, retrieval regressions, copy, visual defects or reproducibility issues. Do not add ERP/CRM writes, MCP, Multi-Agent, GraphRAG, complex Workflow, multi-tenant SaaS or unrelated infrastructure before the demo.
