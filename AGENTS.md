# Instructions for Codex / future engineering agents

This file governs engineering work in this repository, not the deployed intent runtime.

Read HANDOFF.md first. The project is a real local vertical slice, not a blank scaffold.
Preserve the deterministic authority model. Do not replace working code with a framework
rewrite just because the original conversation mentioned Next.js or multiple agents.

Key invariants:
- Database is authoritative; roles come from authenticated membership, never model text.
- Consequential timing changes require a separate human coordinator approval.
- Commands are typed, scoped, version-checked, idempotent and auditable.
- Mutation, receipt, audit and outbox commit together; no network I/O inside transactions.
- One wedding cell per deployment. Isolate event data and service credentials.
- Generic guest DTOs omit private phones/dietary notes. Sensitive reads need explicit grants.
- No real event data, secrets, invitation links or credentials in git or test fixtures.
- Demo auth must remain loopback-only. Never expose it as a production shortcut.
- Treat model output as untrusted intent. Keep provider credentials on the server and do not give the model callable tools.

Test before claiming completion. Distinguish SQLite/ASGI/mock tests from PostgreSQL,
real HTTPS browser, Telegram and model-provider runs. Current external gates are documented
in TESTING.md and HANDOFF.md. Never say the app is production-ready because tests pass.

Useful commands:
  pip install -r requirements-runtime.lock -r requirements-dev.txt -e .
  pytest --cov=wedding_ops --cov-branch
  npm ci --ignore-scripts && npm run typecheck && npm run build
  python scripts/export-contracts.py
  python scripts/ui-smoke.py       # local demo server must already be running

The explicit --bridge browser mode is for an environment with browser localhost blocked;
it does not certify HTTP/cookie/TLS behavior. Do not bypass a managed browser policy.

Runtime modules: schemas/policy/models/db/operations/views/agent/auth/worker/telegram/api.
Record genuine open questions and blockers. Work through P0 commissioning before expanding
breadth. Update source docs and verification evidence after consequential changes.
