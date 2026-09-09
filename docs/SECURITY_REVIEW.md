# NexusKB Demo Security Review

This document defines what the project demonstrates and what must **not** be presented as production-ready security.

## Demonstrated controls

1. JWT authentication for three seeded demo roles.
2. Role → allowed knowledge-base mapping.
3. Qdrant metadata filter applied before vector candidates are returned.
4. BM25 corpus constructed only from authorized chunks.
5. Source-document endpoint repeats KB authorization before returning the file.
6. Administrative write operations require ADMIN.
7. Access-denied and sensitive operations are written to the audit trail.
8. CI contract tests check the core RBAC mapping and retrieval-filter invariants.

## Demo-only limitations

- Password authentication is a local seeded user table, not an enterprise IdP.
- HS256 secret is environment configuration and must be replaced in production.
- No refresh token, session revocation list, MFA or device policy.
- No tenant isolation model.
- No row-level business data scope beyond knowledge-base ACL.
- JSONL audit is single-node and not tamper-evident.
- CORS is permissive for local demo convenience.
- No malware scanning / DLP pipeline for uploaded documents.
- No rate limiting or WAF.

## Production hardening order

1. Enterprise IdP (OIDC/SAML) + short-lived access tokens.
2. Tenant + department + document-level ABAC/data scopes.
3. Central audit with immutable retention and trace IDs.
4. Upload antivirus/DLP/content-type verification.
5. API gateway rate limits, origin policy, secret management.
6. Security tests for horizontal privilege escalation and document download paths.

## Interview wording

Safe claim:

> “I implemented retrieval-layer RBAC so unauthorized chunks are filtered before they enter the vector/BM25 candidate set, and I added runtime/CI checks to prevent regressions.”

Do not claim:

> “This authentication system is production-ready enterprise security.”
