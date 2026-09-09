# NexusKB P1.4 · Ornith Tool Calling Agent

P1.4 upgrades `ornith-1.5:9b` from passive RAG synthesis to a bounded tool-calling agent.

## Runtime

```text
User
  ↓
JWT / Role / selected KB scope
  ↓
Agent mode: local | auto | web
  ↓
ornith-1.5:9b (/api/chat + tools)
  ↓
Tool Registry
  ├─ enterprise_search
  │    └─ resolve_requested(role, kb) → Qdrant filter + authorized BM25 → optional rerank
  └─ web_search
       └─ DDGS → public HTTP(S) results only
  ↓
Tool result with citation_index
  ↓
Ornith final synthesis
  ↓
Answer + Evidence + Audit + Trace
```

## Three modes

| Mode | enterprise_search | web_search | Intended use |
|---|---|---|---|
| `local` | yes | **no** | sensitive/internal questions |
| `auto` | yes | yes, model decides | normal default |
| `web` | yes | yes, external/current info emphasized | public current information |

The UI stores the preference locally. `local` is the privacy-safe mode when a query must never reach a public search backend.

## Security invariants

1. The model chooses a tool; it never chooses authorization.
2. `enterprise_search` resolves the current JWT role again at tool execution time.
3. A selected KB scope cannot be widened by model-provided tool arguments.
4. `web_search` cannot be called in `local` mode even if the model tries.
5. Search-result URLs accept only public HTTP(S); localhost/private/link-local/reserved IPs and `file://`/`ftp://` are rejected.
6. There is no arbitrary `web_fetch(url)` tool in P1.4.
7. Tool-call arguments in Trace/Audit are reduced to a short query preview and non-sensitive control fields.
8. Hidden reasoning / `thinking` is never persisted or returned by the Agent Debugger.

## Bounded loop

Default:

```env
AGENT_MAX_TOOL_ROUNDS=3
```

If Ornith still asks for tools after the third round, NexusKB removes tools and requests a final synthesis from evidence already collected. This prevents accidental infinite tool loops.

## APIs

```text
GET  /api/tools?mode=auto
POST /api/agent/query
POST /api/agent/query/stream
GET  /api/agent/traces/{trace_id}
```

Example body:

```json
{
  "question": "今天 AI 行业有什么重要新闻？",
  "mode": "auto",
  "knowledge_base_id": null,
  "top_k": 5,
  "rerank": false
}
```

## Trace model

The debugger shows only observable execution events:

```text
user
model_decision      # tool names only, no reasoning text
tool_start
tool_end
final
```

Tool calls are also written to the normal audit stream as `TOOL_CALL` / `TOOL_RESULT`; completed Agent questions continue to emit `QUERY`, so the existing dashboard metrics stay meaningful.

## Acceptance matrix

- `X100 质保多久` → expected `enterprise_search`
- `今天 AI 新闻` → expected `web_search` in auto/web mode
- greeting → may answer without a tool
- SALES → `kb_hr` tool request is DENIED
- HR → sales/product/service KB requests are DENIED
- local mode → web tool is not exposed and execution has a second DENIED guard
- tool loop → maximum three rounds, then forced final synthesis
- web URL safety → localhost/private/link-local/metadata/file/ftp rejected
- trace → contains tool events, never chain-of-thought
- Web failure → appears as a failed tool result; Agent may use other evidence instead of crashing the whole FastAPI app

## Runtime verification still required locally

CI validates source contracts, URL safety, Python compilation and the Next.js production build. A real local E2E still requires Ollama + `ornith-1.5:9b`, Qdrant and network access for DDGS.
