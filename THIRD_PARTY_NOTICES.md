# Licensing and provenance

All WeddingOps implementation in this repository was written for this project.
No OSWP implementation, CSS, schema source or copyrighted product artwork was
copied. General wedding concepts were used as reference, not a code fork.

## OSWP discrepancy (reviewed 2026-10-03)
The public README at https://github.com/dccakes/SCV says PolyForm Noncommercial.
A connected GitHub read of the default-branch LICENSE returned GNU AGPL version 3.
The mismatch is unresolved; do not treat the README as the definitive licence or
assume commercial reuse is forbidden under AGPL. AGPL is not a noncommercial
licence; it has copyleft/network source obligations. Obtain maintainer/legal
clarification before reusing implementation. Our independent implementation
avoids making that licensing decision.

## Dependencies
FastAPI, Pydantic, SQLAlchemy, HTTPX, Uvicorn and TypeScript are permissively
licensed dependencies. PostgreSQL has its own PostgreSQL licence; SQLite is
public domain. Verify the exact locked transitive dependency licences before
release. Optional psycopg uses LGPL terms and must retain its applicable notices.
No third-party packages or font files are vendored in this repository.

Research notes paraphrase product claims and retain source URLs. They are not
independent audits or endorsements of the vendors' security/reliability claims.
