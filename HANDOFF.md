# LoveOnCue handoff

**Owner:** Jon. **Build review date:** 3 October 2026. **Status:** working local rehearsal foundation; not cleared to coordinate a real wedding without a supervised deployment rehearsal.

## Read this first

The requested research → product definition → implementation → testing work is present in this source tree. Start by running the demo, not rewriting the stack. The application owns identity, permissions, state, Telegram and message delivery. It can call Mistral directly for optional typed intent parsing.

The original release bundle preserves the full build history. See [docs/PERSISTENCE.md](docs/PERSISTENCE.md) for the release archives.

## First session on your machine

Clone the GitHub repository, then run the rehearsal:

```bash
git clone https://github.com/jonathanjie/LoveOnCue.git
cd LoveOnCue
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-runtime.lock -r requirements-dev.txt -e .
python scripts/dev.py
```

Visit `http://127.0.0.1:8000`. On Windows use the appropriate virtual-environment activation command. Browser assets are checked in; Node is not required merely to run the demo. Python 3.12+ is declared; Python 3.13 was exercised here. Dependency installation needs a reachable package registry/cache. Use a **source checkout**; installing only a wheel is not a supported standalone distribution of the browser/migration assets.

## What actually works

The default fixture contains 180 fictional guests at 18 tables, 11 operator memberships, teams, vendors, locations, tasks and a dependency-aware run sheet. It starts at 17:45 Singapore time on 14 November 2026. Demo mode is loopback-only and cannot send external notifications.

The responsive TypeScript interface has 11 working screens: overview, run sheet, tasks, guest desk, people/teams, issues, approvals, venue/vendors, knowledge, audit and setup. The demo-only role picker exercises the same backend permissions used by authenticated production requests. Coordinator setup supports creating the event's operational objects, importing guests through a reviewed CSV preview, correcting guest/table/family information, and attaching an operator membership to an existing guest identity. Existing task reassignment and a full timeline-editing experience remain future work.

The central slice is implemented end to end: identify a helper → retrieve authoritative assignments → interpret a report → show a confirmation draft → apply the confirmed report → calculate consequences → obtain coordinator approval when necessary → update the run sheet atomically → queue relevant notices → retain an audit trail. A model response alone cannot perform a write.

A 12-minute dinner delay produces a proposal without mutating the schedule. Approval shifts dinner by 12 minutes, speeches and dessert by 7, and the closing toast by 2 because existing gaps absorb some delay. Hard latest-end constraints block approval; concurrent or stale approvals cannot silently overwrite one another. This is a conservative gap-preserving algorithm, not a universal schedule optimizer.

A photographer can report a missing family member; a registration helper can confirm the corresponding arrival. Matching incidents resolve and relevant photography/family recipients receive notices. Asking whether somebody arrived does not mark them present. Ambiguous missing-parent reports ask for clarification rather than choosing a person.

Guest lookup is role-filtered. An usher gets seating information, not dietary notes or family phone numbers. Family contacts and private guest editing use explicit human-only endpoints with role checks and access auditing. Knowledge answers return reviewed, scope-filtered text excerpts with document revision and line references; unapproved text is not silently used as operational truth.

Deterministic workers generate reminders/escalations, claim durable notifications, retry transient failures, suppress obsolete task/timeline messages and recheck membership at delivery. Delivery is at-least-once, not exactly-once; a successful send is not proof a helper read it. The coordinator can work without any model.

## Verified in the original release

See `TESTING.md` and `docs/verification/` for the evidence and its limitations.

- 71 automated tests passed; one PostgreSQL runtime test was skipped because no PostgreSQL server was available.
- Coverage: 87.52% combined statement/branch metric, 91.27% statements and 75.89% branches for the configured core package. The CLI is excluded from this coverage denominator; separate tests exercise operator setup paths.
- Strict TypeScript checks and browser asset compilation passed. Typed API/intent/permission contract export is included.
- Chromium exercised all 11 screens and eight workflow groups with no JavaScript errors, including mobile overflow and role visibility checks. This used an offline browser-to-real-ASGI test bridge because this environment blocks browser navigation to local HTTP servers; it is **not browser-network/TLS/Telegram E2E**.
- A separate, real loopback HTTP smoke test passed against an isolated Uvicorn process, covering cookies, authorization, report confirmation, approval, idempotency and host rejection.
- SQLite migration upgrade/check/downgrade and empty-wedding bootstrap passed. PostgreSQL DDL generation/constraint naming were checked, but this does not replace PostgreSQL runtime testing.

No real wedding information, Telegram message, paid model request or production deployment was used for these checks. These results predate the hosted CI runs.

## Architecture and key files

| Area | Start here | Responsibility |
| --- | --- | --- |
| App entry and API | `src/wedding_ops/api.py`, `cli.py`, `config.py` | Routes, deployment guards, startup and demo/bootstrap commands |
| Persistence | `models.py`, `db.py`, `migrations/` | Normalized 24-table schema, transactions, migration history |
| Authorization | `policy.py`, `auth.py`, `views.py` | Server-bound actor, role/team checks, revocation, scoped output |
| Mutations | `schemas.py`, `operations.py` | Typed commands, idempotency, versions, atomic audit/outbox |
| Scheduling | `scheduling.py` | Dependency graph and conservative delay propagation |
| Agent boundary | `agent.py`, `AGENT_DESIGN.md` | Deterministic fallback and optional Mistral classifier |
| Messaging | `telegram.py`, `worker.py` | Verified private ingress, durable updates, reminders and retries |
| Ingestion | `imports.py` | Bounded CSV preview/apply and safe export |
| Browser | `web/src/app.ts`, `web/src/app.css`, `web/dist/` | Responsive operational UI; checked-in generated assets |
| Fixtures and tests | `seed.py`, `tests/`, `scripts/ui-smoke.py`, `scripts/http-smoke.py` | Rehearsal and reproducible checks |
| Operations | `deploy/README.md`, `compose.yaml` | Conditional commissioning instructions |
| Product and research | `PRODUCT.md`, `RESEARCH.md`, `ROADMAP.md` | Thesis, sourced findings and scope decisions |

The stack is FastAPI/Pydantic/SQLAlchemy/Alembic with a strict TypeScript UI. This differs from the provisional Next.js/Prisma suggestion because the chosen stack could be installed, run and verified in the available environment. Preserve a simple service architecture unless a measured limitation justifies a change.

## External configuration still required

Production needs a dedicated PostgreSQL database, owned HTTPS origin, durable deployment host, non-demo wedding ID and real coordinator onboarding. Start with deterministic mode and notifications disabled. `deploy/production.env.example` and `deploy/README.md` contain the complete configuration sequence. Do not promote the permissive demo login into production.

Telegram needs a new dedicated bot, token, exact username and strong webhook secret. `scripts/configure-telegram.py` is an opt-in helper that verifies the bot identity before changing its webhook/menu. It has mocked tests; it was **not executed against Telegram**. Verify private DMs and actual Telegram Mini App cookie/signature behavior on Android, iOS and Web before enabling sends.

Mistral needs an API key with access to the configured model. Commission it on fictional messages using [the deployment runbook](deploy/README.md#mistral-commissioning).

## Priority order for Codex

1. **Recover and publish the repository; run its existing checks unchanged.** Confirm a clean working tree, bundle history, source archive checksum and deterministic demo.
2. **Run PostgreSQL and Docker/CI for real.** Fix actual dialect, driver, migration, container and browser-network issues without weakening validation. Pin reviewed image/action digests, scan dependencies and test backup restoration into a new isolated cell.
3. **Commission Telegram in a disposable cell.** Exercise enrollment, private ingress, report confirmation, acknowledgements, revoked users, retries, worker restart and mobile Mini App sessions. Do not enable real recipients until this passes.
4. **Commission the Mistral adapter.** Record the model and fictional smoke results, review ambiguous inputs, and validate the fallback when the provider is unavailable. Deterministic mode remains a supported fallback.
5. **Add operational observability and pilot-critical edits.** Worker heartbeat/lag, failed-delivery visibility, measured venue-Wi-Fi/rate-limit behavior, supported task reassignment/timeline correction, and a printable current run sheet. Current in-process rate limits are not a distributed rate-limiting system.
6. **Run a timed tabletop rehearsal with a professional coordinator.** Measure missed instructions, unacknowledged notices, task lateness, time to approved correction and manual fallback. Obtain privacy/retention decisions before collecting real guest information.

Follow `docs/PILOT_RUNBOOK.md`; successful local tests are not permission to make this the sole coordinator of a live wedding.

## Known gaps and technical debt

There is no binary PDF/OCR ingestion, continual Drive/Sheets sync, semantic embedding index, full seating designer, transport optimizer, budgeting, payments, guest website, multi-wedding SaaS control plane, SSO/MFA, offline mobile cache or resource-reservation engine. A venue diagram is a schematic based on configured locations/tables, not an extracted building plan. Knowledge is reviewed text with lexical search, not a full document automation system.

Existing task ownership/schedule changes and relationship editing are narrower than a mature planner's needs; avoid direct database edits as a substitute for implementing typed commands. Archiving makes operational data read-only and cancels pending deliveries; it does **not** delete guest data, backups, provider logs or secrets. Retention and deletion procedures need commissioning. Provider logs may still contain names volunteered in messages despite the intentionally limited model context.

Hosted CI now exercises PostgreSQL. Production cookie behavior, real Telegram delivery and the live model contract require staging verification. Docker/CI files are useful scaffolding, not proof of a running service. Browser bridging verified UI-to-API behavior but bypassed actual browser networking. Package locks reflect versions installed during this build, not a completed vulnerability audit.

The independent implementation does not incorporate OSWP source. Its observed README/LICENSE disagreement is documented in the research and notices. Do not copy its implementation or treat its name as proof of a permissive commercial license. Project distribution licensing remains the owner's decision.

## Continuation instruction

Keep changes small and test consequential behavior. Read the root `AGENTS.md` before editing. Every new mutation must validate the real actor, scope all references to the wedding, use a short transaction, honor idempotency/versioning, and commit audit plus outbox atomically. Do not grant the model database, arbitrary HTTP, shell, broadcast or approval authority. Update this handoff and the verification record when external gates genuinely pass.
