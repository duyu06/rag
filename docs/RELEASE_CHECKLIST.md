# Demo Release Checklist · P1.7

## CI gate

- [ ] `backend-contracts` → success
  - [ ] `python -m compileall -q backend/app scripts`
  - [ ] `python scripts/validate_demo_assets.py` passes
  - [ ] backend unittest suite passes, including P1.7 streaming contracts
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
  - [ ] P1.6 real-BGE recall quality gate passes unchanged
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

## P1.7 Native streaming gate

Executable local gate:

```bash
python scripts/release_smoke.py --stream
```

This command uses the real local `ornith-1.5:9b` + Qdrant path and must pass before the interview. It checks incremental SSE delivery, same-message persistence, Citation, Trace and conversation reload consistency.

Optional interview-machine TTFT SLA, after warming the model once:

```bash
python scripts/release_smoke.py --stream --max-ttft 8
```

`--max-ttft` is intentionally opt-in because GitHub CI and different local GPUs/CPUs are not comparable performance environments.

- [ ] `python scripts/release_smoke.py --stream` → PASS
- [ ] `backend/app/native_stream.py` sends Ollama `stream: true`
- [ ] final Local Fast Path synthesis uses `tools=[]`; Tool Routing stays buffered
- [ ] `/api/agent/query/stream` no longer slices a completed answer into fixed-size fake chunks
- [ ] `POST /api/conversations/{conversation_id}/messages/stream` returns SSE
- [ ] `POST /api/conversations/{conversation_id}/messages/{message_id}/retry/stream` returns SSE
- [ ] new assistant turn is persisted as `generating` before token delivery
- [ ] at least 2 non-empty token events are observed by the default smoke gate
- [ ] first visible Local-mode token arrives before the final `done` event
- [ ] token chunks append to one AI bubble rather than creating duplicate messages
- [ ] `done` replaces the same persisted assistant id with `completed` answer + Citation + Trace
- [ ] streamed answer text equals the final persisted assistant content
- [ ] stream failure replaces that same assistant id with `failed`
- [ ] Retry streaming keeps the original failed assistant id
- [ ] refresh after completion restores the exact answer and Citation from SQLite
- [ ] `timings.native_stream=true` on a successful Local Fast Path streamed synthesis
- [ ] persisted Agent Trace also records `native_stream=true`
- [ ] Auto/Web Tool Calling behavior is unchanged; SSE compatibility does not expose partial tool JSON

Recommended manual demo query:

```text
X200 能在零下 20 度工作吗？
```

Expected: Local mode retrieves the authorized X200 evidence first, then the AI bubble visibly grows while Ollama is still generating. After `done`, Citation / Trace are available and a page refresh keeps the answer.

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
- [ ] streaming sends only visible `message.content`, never hidden reasoning

## Interview freeze rule

After these gates pass, freeze features before the interview. Only fix blockers, retrieval regressions, streaming defects, copy, visual defects or reproducibility issues. Do not add ERP/CRM writes, MCP, Multi-Agent, GraphRAG, complex Workflow, multi-tenant SaaS or unrelated infrastructure before the demo.
