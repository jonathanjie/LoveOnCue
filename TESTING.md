# Verification and testing

Recorded on 3 October 2026. This document separates local evidence from the external commissioning work still required. Detailed compact results are checked in under `docs/verification/`; temporary full test output is generated under ignored `artifacts/`.

## Observed results

| Check | Result | Boundary of evidence |
| --- | --- | --- |
| Pytest | **71 passed; 1 skipped** | Real SQLite database, API, worker, auth and controlled transport tests. PostgreSQL-only runtime test skipped. |
| Core coverage | **87.52% combined**, 91.27% statements, 75.89% branches | 2,097 statements; 676 branches. Configured package scope excludes `cli.py`; does not measure browser code or certify correctness. |
| TypeScript | Strict check and compilation passed | TypeScript 5.8.3; generated browser modules included in source. |
| API contracts | Generated successfully; checked against tracked files | Pydantic/OpenAPI commands, intent and permission snapshots. |
| Browser | 11 screens; 8 workflow groups; no JavaScript errors | Chromium offline bridge into the real ASGI API. Not browser-network, TLS or Telegram E2E. |
| Real HTTP | Passed isolated Uvicorn loopback smoke | Python HTTP client, real cookies and routing. Not a browser or a public HTTPS deployment. |
| SQLite migrations | Upgrade/check/downgrade and clean bootstrap passed | Actual local database operations. |
| PostgreSQL | DDL generation and unique constraint names passed | Server, psycopg execution, locks/concurrency and actual migrations not exercised here. |
| External systems | Not executed | Docker/Compose, hosted CI, live Telegram, live model provider, production TLS and real device Mini App behavior. |

No external messages were sent. All test and demo people are fictional. Successful local runs are not a security certification or a guarantee of event-day reliability.

## Reproduce the core suite

```bash
python -m pip install -r requirements-runtime.lock -r requirements-dev.txt -e .
pytest --cov=wedding_ops --cov-branch \
  --cov-report=term-missing --cov-report=json:artifacts/coverage.json \
  --junitxml=artifacts/pytest.xml
npm ci --ignore-scripts
npm run typecheck
npm run build
python scripts/export-contracts.py
git diff --exit-code -- web/dist docs/contracts
python scripts/http-smoke.py
```

The build environment used its installed TypeScript compiler through `TSC_PATH` because npm registry access was unavailable. A normal source checkout uses `npm ci`. Do not treat this environment's successful build as proof a clean registry installation has been performed on another platform.

`http-smoke.py` creates an isolated temporary demo database, starts its own Uvicorn process on an unused loopback port, checks requests and terminates the process. It does not target your configured production cell or inherit operational credentials.

## Tests that guard consequential behavior

`test_domain.py` covers role-scoped operations, report effects, stale/expired approvals, hard deadlines, duplicate commands, concurrent approval attempts and tenant-scoped foreign references. `test_integrations.py` covers session/CSRF/Origin checks, invitations, Telegram signatures/secrets and duplicate ingress, deterministic interpretation, malformed model responses, knowledge scope and worker delivery/retry behavior. The adversarial-text cases verify that untrusted input does not become a privileged command; they do not prove an LLM immune to prompt injection.

`test_guest_setup.py` covers reviewed guest edits, table capacity, family contacts, normalized role resolution, privacy and an existing guest becoming a helper without duplicate identity. `test_setup_and_migrations.py` checks empty-cell setup, migrations and SQL constraints. `test_operator_scripts.py` tests the Telegram setup helper with a controlled HTTP transport, including a wrong-bot identity refusal before any mutation.

## Browser checks

On a machine that permits browser access to loopback:

```bash
pip install -r requirements-browser.txt
playwright install chromium
python scripts/dev.py  # Keep this running in a separate terminal.
python scripts/ui-smoke.py --url http://127.0.0.1:8000
```

The target must be a disposable **demo** instance. The script checks demo configuration before performing fictional mutations. The ordinary network path was not run in this managed browser environment; it is included in the browser CI job.

For the offline test bridge used during this build:

```bash
python scripts/ui-smoke.py --bridge
```

Use `CHROMIUM_PATH=/path/to/chromium` when selecting an existing browser. The bridge routes every browser request (page, compiled modules and API) to an in-process ASGI app with its own test database. It verifies rendering, buttons, permissions and workflows without using a public server. It intentionally cannot validate browser cookie transport, reverse proxy headers, TLS, cross-site Telegram webviews or connection recovery. A separate Python HTTP smoke does not eliminate those limitations.

The smoke test runs at phone width (390 x 844) and covers: the coordinator's Home hub, tabs and sections; a helper's delay report and the coordinator's approval sheet; sending an update and seeing who read it; a helper's "Got it" on their next job; a problem report reaching the coordinator; seating lookup without dietary notes; venue notes search; a guest family-role edit; family-contact visibility by role; and no horizontal overflow. Each run must start from fresh demo data. Phone screenshots of each view are in `docs/screenshots/mini-app/`.

## PostgreSQL and deployment checks

Use only a **disposable database whose name ends in `_test`** and explicitly authorize test resets. Never point the test suite at an event database:

```bash
pip install -e '.[postgres]'
export WEDDINGOPS_TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/weddingops_test'
export WEDDINGOPS_ALLOW_TEST_DATABASE_RESET=yes
pytest -q
```

The fixture rejects unsafe database names/reset settings, but the operator must still verify the target. The PostgreSQL CI job defines a separate service database for these destructive tests. Run the full suite rather than only testing SQL compilation.

After server tests pass, execute `deploy/README.md` on an isolated cell, including TLS, browser-network UI checks, worker restart, duplicate/blocked Telegram delivery, proxy/venue-Wi-Fi load, actual Mini App sessions and backup restoration. Run the opt-in Mistral smoke with fictional inputs and record the result separately.

## Updating evidence

Record the source revision, environment, command, transport mode and skipped checks whenever updating `docs/verification/`. Do not commit guest databases, raw private messages, environment files, credentials or full provider traces. A source bundle preserves engineering work, not runtime guest data. Treat this document's original build results and the hosted CI runs as separate evidence.
