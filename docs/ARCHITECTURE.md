# yaoke Architecture

## Runtime path

```text
Browser / User
  ↓ JWT
Next.js UI
  ↓ Authorization: Bearer <token>
FastAPI
  ├─ Auth / RBAC
  ├─ Knowledge Base ACL
  ├─ Ingestion
  ├─ Retrieval Debugger
  ├─ Evaluation
  └─ Audit
       ↓
Role → Allowed KB IDs
       ↓
Qdrant metadata filter ─┐
Authorized BM25 corpus ├─→ Hybrid → optional Cross-Encoder → Top-K
                       ┘
       ↓
LLM Context
       ↓
Answer + Citation
```

## Data boundary

The central enterprise rule is: **authorization happens before retrieval candidate construction**.

- Vector search receives a Qdrant filter for allowed `knowledge_base_id` values.
- BM25 builds its corpus only from authorized chunks.
- Citation source-file access performs the same KB ACL check again.
- The LLM is never treated as an authorization component.

## Storage

- Qdrant: chunk vectors + retrieval metadata.
- `backend/data/documents/<kb_id>/`: source documents for the demo.
- `backend/data/audit.jsonl`: local single-node audit trail.
- `demo-data/`: bundled deterministic interview corpus.

## Why JSONL audit in this demo

The goal is to demonstrate observable enterprise behavior without adding PostgreSQL/ClickHouse only for a five-minute interview demo. A production deployment should replace JSONL with centralized durable logging and add `trace_id`, retention policy, redaction, and multi-instance aggregation.

## Production replacement points

| Demo component | Production direction |
|---|---|
| local demo users + JWT HS256 | OIDC / SAML / enterprise IdP |
| local document directory | S3/OSS/MinIO + lifecycle policy |
| JSONL audit | PostgreSQL/ClickHouse/OpenTelemetry logging |
| single Qdrant collection | managed Qdrant or pgvector, tenant/data-scope filters |
| synchronous ingestion | task queue / workflow engine for large corpora |
| Ollama default | approved hosted/self-hosted inference service |

## Deliberately out of scope

Multi-Agent, MCP, GraphRAG, Kubernetes, ERP/CRM write actions and SaaS multi-tenancy are intentionally excluded until the RAG retrieval/authorization/evaluation baseline is stable.
