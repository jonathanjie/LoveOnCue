# Architecture

Status: implemented local vertical slice with external commissioning gates. Decisions describe code that exists unless marked future.

## Boundaries

```text
Private helper web app / Telegram DM
              |
      Authenticated ingress
              |
  Query DTOs / typed command service <---- validated, untrusted intent
              |                                      ^
       Wedding database                  optional PRIVATE OpenClaw HTTP
              |
  transactional audit + notification outbox
              |
      deterministic worker ---> Telegram API
```

The same-origin FastAPI service serves compiled TypeScript/CSS and HTTP endpoints. No browser holds a bot token, gateway token or database credential. Telegram messages pass a secret-header check and strict private-chat identity validation; enrollment binds a numeric Telegram sender to a pre-created membership. A one-use invitation can instead create a web session. Helpers cannot self-assign their role.

OpenClaw runs outside the authority boundary. The application forwards one human message, accepts one typed classification, resolves visible entities, and creates a human-confirmation draft where appropriate. Only application code executes business commands. A guessed actor, role, wedding ID or arbitrary SQL field is not a valid command argument.

## Single-wedding cell

V1 deploys one API, one worker, one database, one bot credential and optionally one isolated gateway per wedding. Production settings require a unique non-demo wedding ID and PostgreSQL. Every read is scoped to that configured cell and every member is reloaded at authorization time. Composite foreign keys bind cross-table references to their wedding. This is defense in depth; no RLS, fleet scheduler or proven shared-SaaS isolation is claimed.

The example Compose file publishes only the HTTPS proxy. Database/API/gateway operator ports are not intended as public surfaces. Separate cells must also use separate Compose project names, volumes, networks and credentials. A future control plane may provision cells; it must not expose a cross-wedding super-agent.

## Transaction protocol

`Operations.execute` validates the discriminated command, rejects non-human mutation sources, reloads permissions, and checks the idempotency receipt. Inside one transaction it updates authoritative rows, increments versions, appends audit metadata and creates outbox notices. Reusing a request ID with changed content is a conflict. Replaying an old command still requires current access.

PostgreSQL uses a per-wedding row lock; read units take a shared lock and writes an exclusive lock. SQLite uses `BEGIN`/`BEGIN IMMEDIATE` with foreign keys, WAL and a busy timeout. This intentionally serializes writes within a small event. Database transactions never encompass HTTP calls. It is simpler than distributed sagas and sufficient as a design for the initial operator count; actual production throughput remains to be measured.

A separate `timeline_version` protects reviewed timing plans. General `state_version` changes on business state, notices and delivery outcomes. Task and guest versions reject stale edits. A delay approval records its base timeline version, exact diff, scope, blockers, expiry, proposer and approver. Stale or infeasible proposals cannot be approved.

## Timeline and task semantics

Timeline items have planned and current starts, duration, actual start/end, location, responsible teams and optional hard latest end. Finish-to-start dependency edges carry a lag. The delay planner shifts only downstream activities that would otherwise break their constraints; existing slack absorbs delay. It never autonomously shortens an activity or spends money. Activity completion is never inferred from time passing.

Tasks have independent owners, due times, prerequisites and acknowledgements. Seeded tasks can bind to a run-sheet item with an offset and move atomically with an approved schedule change. The current setup UI creates standalone tasks; editing links/reassigning existing tasks is a next-step feature.

## Messaging and recovery

Notifications are persisted with deduplication keys, recipient, audience/permission requirement, schedule/task versions and delivery state. The worker claims a lease, releases the transaction, calls the transport, then records the outcome only if it still owns the lease. It rechecks access and supersedes stale reminders before sending. Retryable provider/network failures receive bounded backoff; permanent failures remain visible.

Delivery is at least once, not exactly once: a crash after Telegram acceptance and before commit can repeat a message. Acknowledgement is separate from `sent`. Demo notices are `simulated`; unlinked live recipients are `undeliverable`. Only `live` events generate automatic task reminders. Draft mode does not suppress already queued direct reports; archived events cancel pending deliveries.

Telegram ingress also has an update-ID receipt, lease and retry state. Raw processed payloads are cleared. This reduces duplication risk; live crash/restart/429 tests remain required.

## Knowledge and imports

CSV ingestion previews before applying and refuses duplicates, unknown tables, capacity errors and stale previews. Exports escape spreadsheet formulas and exclude private notes. Reviewed guest changes preserve versions and do not put edited PII into command receipts/audit detail.

Knowledge currently accepts text/Markdown, not binary PDFs. A coordinator sets audience and approves a source. Search returns bounded lexical matches, hashes, revisions and line numbers. Retrieved text never loops back through a tool-capable model. That sharply narrows prompt-injection opportunity without claiming all language-model attacks are solved. Semantic embeddings, document extraction and Drive/Sheets sync are future adapters with explicit review gates.

## Degraded operation

The whole operational UI and commands work without an LLM. Provider failures fall back to a visibly labeled deterministic parser. There is no service-worker offline cache or offline write queue. Loss of network therefore requires the printed/exported run sheet and human escalation plan. Do not call this offline-capable simply because the model is optional.

## Technology choices and tradeoffs

FastAPI/Pydantic provide strict request boundaries; SQLAlchemy supports portable models; Alembic contains a frozen initial migration. Framework-light TypeScript removes a production bundler requirement and keeps the helper surface small, at the cost of hand-maintained view types. JSON contracts are exported for later typed client generation. The browser is not the source of permission enforcement.

Python dependencies and the TypeScript package are pinned. Containers/actions use reviewed major/minor tags, not immutable image/action digests yet. Pinning, vulnerability scanning, PostgreSQL runtime validation, HTTPS/Mini App behavior and operator load tests remain release gates. Source-layout installation is supported; a standalone wheel does not package the web assets.
