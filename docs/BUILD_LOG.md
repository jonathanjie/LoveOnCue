# Build log

Source mandate: the Google Doc supplied in the conversation; read through the connected Drive action. Date of this build: 2026-10-03. All fixture people/venue/vendor records are fictional.

1. Research and authority decisions: verified OpenClaw operator boundary and HTTP client-tool contract; identified OSWP README/LICENSE discrepancy; chose independent implementation and a single-wedding cell.
2. Local engineering base: FastAPI/Pydantic/SQLAlchemy with strict TypeScript browser modules. SQLite demo; PostgreSQL deployment design. Chosen to execute and test the slice rather than produce an untested npm-framework scaffold.
3. Domain and integration boundaries: schema, scoped roles, transactions, idempotency, task/timeline dependency handling, approvals, audit, outbox, imports, auth, Telegram and model adapters.
4. UI: eleven role-aware screens and a mobile helper experience. Browser testing found and fixed unsupported crypto.randomUUID use; secure random IDs now use getRandomValues. Managed browser policy blocks localhost navigation here, so UI evidence uses the explicitly documented offline ASGI bridge.
5. Regression hardening: stale/concurrent approvals, negative arrival wording, parent disambiguation, private field access, dependency graph constraints, secret-safe errors, durable delivery state and schema naming for PostgreSQL portability.
6. Empty-event setup: create teams/members/locations/tables/tasks/activities/vendors, preview/import guests, edit guest/family details and reuse guest identities as helpers. Controlled activation of reminder generation.
7. Delivery groundwork: Docker/Compose, CI jobs for core/PostgreSQL/browser, locked dependencies, exported contracts, private OpenClaw config/policy and live smoke script. These external environments were not run here.
8. Persistence: a core Git-history checkpoint was uploaded to the actual Drive project folder. No new GitHub repository could be created through the exposed connector. Final archives, source docs, a Word-readable handoff and handoff links are recorded in docs/PERSISTENCE.md and the release delivery index.

Final verification status and exact executed counts belong in TESTING.md and docs/verification, not this narrative. No customer interviews, actual wedding pilot, live Telegram delivery, paid model call, PostgreSQL server test or Docker deployment are implied.
