# ADR 0002: a runnable typed service rather than untested framework scaffolding

Decision: Python 3.12+ / FastAPI / Pydantic / SQLAlchemy for the operations API;
TypeScript compiled to native browser modules for the lightweight UI; PostgreSQL
for deployment, SQLite with foreign keys/WAL for local demo and fast tests.

The suggested Next.js/Prisma stack was a default, not a hard requirement. The
build environment has no npm registry DNS access, but has the Python stack and a
TypeScript compiler installed. This choice allows the real workflows, HTTP auth,
database transactions and UI to be exercised here rather than shipping an
untested Next.js shell. OpenClaw's HTTP interface is language-independent.

No proprietary application framework is needed. Pydantic is the typed boundary;
SQLAlchemy models describe normalized operational state. Alembic records schema
migration history. No additional agent framework is added.

Production concurrency uses a per-wedding SELECT FOR UPDATE lock. SQLite writes
use BEGIN IMMEDIATE. This keeps receipts, audit events and notification outbox
entries atomic with each business transition. A single database per deployed
wedding cell is the V1 deployment model. Tenant-scoped queries and composite
foreign keys provide defense in depth, not an assertion of certified SaaS isolation.

SQLite tests do not prove PostgreSQL driver/locking behavior. A PostgreSQL CI job
and a separate database test mode are included; execution status is recorded in
HANDOFF.md. Do not describe an unexecuted CI job as passing.

The UI is framework-light deliberately. A later Next.js/React shell can use the
same OpenAPI contract; domain code must remain independent of the UI runtime.
