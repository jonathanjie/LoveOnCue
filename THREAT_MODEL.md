# Threat model

Scope: one wedding cell, its helper UI/DM channel, app/worker/database, optional private OpenClaw gateway, vendor APIs and human coordinator. No adversarial penetration test was performed; this is a design review with selected automated regressions.

Assets: correct timing/instructions, role-scoped guest/family information, credentials, availability, attribution and the coordinator's authority. Threat actors include an unauthenticated outsider, curious helper, compromised participant phone, malicious uploaded text, confused operator and compromised runtime/dependency.

| Threat | Implemented control | Residual / release check |
|---|---|---|
| Helper says “I am coordinator” | Server-bound membership; roles absent from intent schema; authorization on every command | Account/invitation theft still grants that account's legitimate rights |
| Cross-wedding ID substitution | Configured cell ID, scoped lookups, composite foreign keys, regression tests | Separate databases/gateways/secrets still required; no certified multitenancy |
| Confused deputy through OpenClaw | No app credential in model context; one typed intent; human-source mutation requirement | Operator gateway token is powerful; validate internal tool denial in the actual runtime |
| Prompt injection in a venue document | Human approval, audience filter, text-only reference return, no tool-capable synthesis loop | Human readers can still be misled; provenance review remains necessary |
| “Has father arrived?” becomes a check-in | Question/negative-wording tests; exact entity resolution; confirmation draft | Model can misclassify new wording; measure wrong-action proposals |
| Double/stale approval | Transaction lock, receipt hash, timeline base version, expiry and blockers | PostgreSQL runtime/concurrent worker execution still needs actual validation |
| Wrong table / duplicate guest | CSV preview, name/capacity checks, explicit versioned edit | Same-name guests and family conventions need careful human reconciliation |
| Private data exposed to usher | Explicit DTOs, field grants, family-contact restriction and audited detail access | Previously displayed data cannot be revoked from a device |
| Web CSRF / bad host / oversized body | SameSite cookie, CSRF+Origin, trusted host, body limit, safe text rendering | Validate actual HTTPS proxy and Telegram webview behavior |
| Telegram forged/replayed message | Header secret, strict private-chat matching, signed Mini App data, update receipts | Token compromise or forwarded invitation requires revoke/rotate response |
| Worker crash / repeated send | Durable lease/outbox, retry/backoff, receipt/version checks | At-least-once delivery can repeat after provider acceptance; human acknowledgement separate |
| Shared venue network / API abuse | Per-session buckets plus IP/login/anonymous ceilings | Single-process limiter; test real venue/load and distributed deployment |
| Coordinator mistake / emergency | Explicit diff, warnings, approval and manual fallback; no emergency action tool | The software cannot replace venue safety procedures or a trained coordinator |
| Database loss / admin tampering | Migration, export and documented backup/restore procedure | Backup infrastructure, restoration and audit integrity not independently operated/tested here |
| Supply-chain compromise | Small pinned dependency set, no vendored OSWP code, explicit deployment gate | Full SBOM/security scan and immutable image/action pinning remain open |

## Abuse rehearsals to retain in CI

Unauthenticated read/write; forged actor field; ordinary usher approval; missing/invalid CSRF; reused invite; revoked member replay; other-wedding references; stale guest edit; full table reassignment; malformed/wrong/multiple client tools; provider timeout; malicious approved reference; negative arrival; ambiguous parents; duplicate command with different body; concurrent approval; stale outbox notice; permanent provider failure.

## Incident procedure

For suspected account compromise, revoke the membership and rotate relevant invitations. For bot/gateway compromise, disable the corresponding integration and rotate its credential outside source control; use the deterministic web app/manual run sheet. Preserve minimum necessary incident metadata without copying guest PII to public support. For availability loss, stop making conflicting digital updates, use the named human incident lead, then reconcile timestamped paper/radio reports before resuming. Notify affected parties according to the event's agreed legal/operating plan.
