# yaoke P1.5 · Persistent Conversations & Local Fast Path

P1.5 turns the original single-turn RAG demo into a persistent enterprise knowledge conversation experience without weakening the retrieval authorization boundary.

## Runtime path

```text
Browser
  -> JWT user
  -> Conversation (SQLite)
  -> selected KB scope
  -> Local | Auto | Web

Local:
  backend-controlled enterprise_search
  -> Role ACL
  -> Qdrant filter + authorized BM25
  -> optional Rerank
  -> one Ornith synthesis call
  -> Citation + Agent Trace + timings

Auto/Web:
  Ornith native Tool Calling
  -> Tool Registry
  -> execution-time ACL
  -> Citation + Agent Trace
```

The model can choose a tool in Auto/Web mode, but it cannot grant itself access to a knowledge base.

## Conversation guarantees

- SQLite stores conversations, user/assistant messages and per-message Citation rows.
- Default path: `backend/data/conversations.db`.
- Docker bind-mounts `backend/data` to `/app/data`, so normal container rebuilds preserve history.
- A conversation belongs to one JWT username. Cross-user reads are rejected.
- Only the latest 8 completed user/assistant messages are sent as model history by default.
- Failed assistant turns can be retried in place: the user turn is not duplicated, the assistant message ID is preserved, and Citation/Trace are replaced on success.

## Local Fast Path

Local mode avoids an unnecessary model routing round:

```text
before: Ornith -> enterprise_search -> Ornith -> answer
P1.5:  ACL -> enterprise_search -> Ornith -> answer
```

This keeps Tool Registry execution, ACL filtering, Audit, Citation and Agent Trace while reducing the successful Local knowledge path to one Ornith synthesis call.

Short follow-ups such as `那 X200 呢？` reuse the previous user turn for retrieval context without adding a separate query-rewrite LLM call.

## Performance visibility

Local Fast Path Trace can include:

- `vector_ms`
- `bm25_ms`
- `fusion_ms`
- `rerank_ms`
- `retrieval_total_ms`
- `llm_ms`
- `total_ms`
- `bm25_cache_hit`
- `parallel_hybrid`

The Agent Debugger renders these values. They are diagnostic measurements from the current runtime, not benchmark promises.

## Deployment smoke

After the stack is running, first verify wiring without invoking the LLM:

```bash
python scripts/release_smoke.py
```

This checks API reachability, Qdrant, JWT login, ADMIN KB scope, Tool Registry modes, and a create/restore/delete SQLite conversation lifecycle.

Then verify the actual local model path:

```bash
python scripts/release_smoke.py --agent
```

`--agent` additionally requires the Demo corpus to be ready and checks:

```text
real Ornith
-> Local Fast Path
-> real Qdrant retrieval
-> Citation
-> detailed timings
-> persisted Agent Trace
```

If the default smoke passes but `--agent` fails, investigate Ollama/model runtime before changing retrieval or UI code.

## Recommended local acceptance sequence

```bash
git pull origin main
ollama --version
ollama list
ollama run ornith-1.5:9b
docker compose up --build
python scripts/check_demo.py
python scripts/demo_smoke.py
python scripts/release_smoke.py
python scripts/release_smoke.py --agent
python scripts/agent_smoke.py --agent
```

Web Search is a separate dependency. Validate it only after Local enterprise knowledge QA is stable:

```bash
python scripts/agent_smoke.py --agent --web
```

## Deliberately deferred

- true token streaming for Conversation API
- long-history summarization
- MCP / Multi-Agent
- ERP/CRM write actions
- arbitrary URL fetching

These are not required for the current interview/demo acceptance target.
