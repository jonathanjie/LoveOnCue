# Security and privacy

**This build is not security-certified or approved for unsupervised production use.** Report issues privately to the project owner through the repository's private discussion/channel. Do not publish real guest records, tokens or exploit-bearing logs in public issues.

## Enforced controls

Production requires PostgreSQL, HTTPS origin and a unique non-demo event ID. The passwordless role picker is local-demo-only; CLI refuses public binding in demo mode. All business writes require an authenticated human source, same-origin request, CSRF token, valid membership and relevant capability. Membership revocation invalidates sessions and is rechecked before command replay and message delivery.

Coordinator-generated invitations bind a pre-created member and expire after 24 hours; they are one-use, bearer secrets stored as hashes. Web sessions last 12 hours and use HttpOnly, SameSite=Strict cookies with Secure in production. Telegram Mini App identity is checked from signed `initData`, including timestamp and replay checks; `initDataUnsafe`, usernames and chat text cannot grant access. The Telegram webhook requires its configured secret header and only accepts private numeric user/chat matches.

Scoped DTOs exclude private guest phone/dietary fields by default. Banquet can request dietary service notes; family liaison can request designated family contacts; coordinator-only detailed access is separately audited without recording the values. Vendor business contacts are scoped by team. No guest-public portal is included.

Mutations have strict schemas, explicit errors, idempotency and transactional audit/outbox. SQL access uses bound ORM queries. Rendering uses text nodes rather than unsanitized innerHTML. CSP, same-origin policy, trusted-host checks, request-size bounds, per-session/anonymous/login limits and a shared-IP ceiling are present. Session hashes used for traffic buckets are not treated as authentication. Limits are single-process controls, not a DDoS solution.

## Data-handling boundaries

Structured guest data belongs in the database, not repository fixtures or model memory. Documents are untrusted reference content even after human review. Only approved/audience-scoped text is searchable, and it is not passed into a tool-capable model. The optional classifier sends one user message to the provider; that text may contain personal data. Obtain suitable customer/provider handling terms and review gateway transcript retention.

Bot/gateway/database credentials are explicit environment values. They must never reach a browser, be embedded in skills, appear in screenshots, or be committed. Error records use safe provider error codes, not Telegram URLs containing credentials. `.env*`, database files, runtime artifacts and caches are ignored by git. Ignore rules are not a secret scanner: inspect every release archive.

## Trust and residual risks

A deployment operator/database administrator remains trusted. Audit rows are useful attribution, not a tamper-proof ledger. A coordinator account has broad legitimate authority. One-use invitation possession proves access to the invitation, not legal identity; share privately and verify enrollment before the event. A compromised helper phone can act within its granted role until revoked.

Outbound delivery is at least once. A provider may accept a message before the worker records success, resulting in a repeat after a crash. A sent message cannot reliably be recalled from a recipient device. Revocation and retirement cannot retract previously viewed data. The UI has no offline cache or offline mutation queue.

A single wedding database is the deployment boundary; cross-cell tests are defense in depth, not evidence that a shared gateway or shared host is secure. OpenClaw internal tools must be denied independently of the client function contract. Never distribute its operator bearer to helpers.

## Required before a live pilot

Complete the PostgreSQL/driver/migration/locking test job, build the Docker image, test HTTPS/CSRF/cookies behind the actual proxy, and validate Telegram Android/iOS/Web Mini App enrollment and reconnect behavior. Confirm expected traffic from a shared venue IP does not block users; distributed/multi-process limiting and proper trusted-proxy address handling require review before scaling.

Run dependency vulnerability/license scanning and pin images/actions by digest. Exercise worker restarts, transient provider failure, permanent delivery errors, stale updates, revocation, backup restoration and model outage. Review handling of confidential family notes and who may see them. No medical/safety decisions or broad emergency automation is included.

## Retention and deletion proposal, not an automated claim

Agree a written event-specific retention schedule before collecting real data. Proposed starting policy: revoke temporary helper access at closeout; archive operational writes after reconciliation; remove private contact/dietary data once its service purpose ends; retain only agreed incident/audit material for a bounded period. The customer must decide lawful purpose, notices, access/export expectations and backup retention with appropriate advice.

The foundation does not implement an automatic expiry/deletion job or claim PDPA/GDPR compliance. Deletion must cover the event DB, backups, imported text, pending drafts/notifications, gateway transcripts, provider retention where controllable and support exports. The printed fallback is also personal data. Archive alone is not deletion. See `deploy/README.md` for backup/restore discipline and `THREAT_MODEL.md` for concrete cases.
