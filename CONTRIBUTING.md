# Engineering contribution guide

Read `AGENTS.md`, `HANDOFF.md` and the authority ADR first. Work on a branch; keep commits small enough to review. No real guest data, private run sheets, bot tokens, invitation links or production DB dumps belong in tests, issues or screenshots.

The supported development path is a source checkout with an editable Python install. Browser source is `web/src`; commit its generated `web/dist` counterpart. Do not hand-edit compiled JavaScript. Add schemas before new commands and regenerate `docs/contracts/`. Schema changes require a new Alembic migration; do not rewrite the initial migration after deployment.

Every mutating feature needs tests for allowed actor, forbidden actor, tenant scope, duplicate request, stale version and relevant rollback/audit/outbox behavior. Keep network I/O outside database transactions. Never accept a model-supplied actor or use an LLM decision as permission.

Run `pytest --cov=wedding_ops --cov-branch`, TypeScript checking/build, contract export/diff and the UI smoke test. For external behavior state exactly what was real, mocked or skipped. Add a regression test before fixing an operational failure. Keep `HANDOFF.md`, security notes and release evidence synchronized; do not mark unexecuted CI green.

Generated private documentation snapshots may be uploaded to the project's Drive folder, but code plus source Markdown remain the engineering source. Confirm the current bundle/repository revision before editing a stale snapshot. Licensing changes require the owner's decision; do not assume this private source is open source.
