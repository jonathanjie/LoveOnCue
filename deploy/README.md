# Deployment and operations runbook

Commission a fictional wedding on an isolated staging instance before any real event. CI covers the core app, PostgreSQL, and the browser workflow. Verify HTTPS and external integrations on the target deployment.

## Local development versus production

The zero-credential rehearsal is SQLite and loopback-only (`python scripts/dev.py`). Production settings reject SQLite, non-HTTPS public origins and the demo event ID. Do not bypass those guards. Use a source checkout/editable package; browser assets are served from the repository's `web` directory.

## Shared VPS with Caddy and PostgreSQL

On a VPS with working Caddy and PostgreSQL, run the API and worker directly
under systemd. Use Python 3.12 or newer, a dedicated PostgreSQL database and
login role, and a dedicated unprivileged `weddingops` system user. Install
the locked runtime plus the PostgreSQL driver in a release-specific virtual
environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-runtime.lock -e '.[postgres]'
```

Use a root-owned release under `/opt/weddingops/releases/<revision>` and
point `/opt/weddingops/current` to it. Copy the two units from [systemd/](systemd/)
into the system unit directory. Set the required `WEDDINGOPS_` values in
`/etc/weddingops/weddingops.env` (root owner, mode 0600). Use
`WEDDINGOPS_MODE=production`, a non-demo wedding ID, the HTTPS public URL, and
a PostgreSQL connection scoped to the dedicated role. Keep the classifier in
deterministic mode and notifications disabled until commissioning.

Run `weddingops migrate` followed by `weddingops bootstrap` as a one-shot under
the service identity with the same environment. Capture the bootstrap
invitation in a private file. Start the API and worker and verify loopback
readiness with the configured hostname in the Host header. The API binds to
loopback port 8768. Route only the selected hostname through the existing Caddy
installation:

```caddyfile
wedding.example.invalid {
    reverse_proxy 127.0.0.1:8768
}
```

Validate Caddy's full configuration before reloading, then check `/health`
and `/ready` over HTTPS from outside the VPS. Do not publish API or database
ports.

## One-cell Compose setup

Install Docker with Compose on the target machine, point an owned domain at it, and review firewall/TLS/networking requirements. Only proxy ports 80/443 should be published. Copy `deploy/production.env.example` to `.env.production` at the repository root. Generate a unique hex database password, set `DOMAIN` and a non-demo wedding ID. Keep `SEND_NOTIFICATIONS=false` and `AGENT_MODE=deterministic` for initial commissioning.

Run from the repository root:

```bash
# This validates/interpolates configuration; keep resolved output private.
docker compose --env-file .env.production config --quiet
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d db
docker compose --env-file .env.production --profile tools run --rm migrate

# The bootstrap output contains a private one-use invitation. Store outside git.
umask 077
docker compose --env-file .env.production run --rm api weddingops bootstrap \
  --name 'Example wedding' --date 2026-11-14 --venue 'Example venue' \
  --coordinator 'Named coordinator' --timezone Asia/Singapore \
  > ../weddingops-bootstrap.private.json

docker compose --env-file .env.production up -d api worker caddy
```

Use the actual date/names for the intended cell, after privacy approval; the command above is a fictional example. Bootstrap refuses an existing cell. Redeem the private initial coordinator invitation, then remove or protect the output file. Check `/health` and `/ready` over HTTPS and complete a full setup from the UI. Never expose the demo role picker.

The API and worker run as a non-root user with a read-only filesystem and temporary `/tmp`; the database volume is separate. Caddy terminates HTTPS. Image/action tags are not immutable digests yet—pin and scan after the first verified build. API healthchecks exist, but worker heartbeat/lag monitoring is still a release task. Do not equate a running container with correct message processing.

## Telegram commissioning

Create a dedicated development bot with BotFather; do not repurpose a personal/production bot. Load its token, exact username and a random webhook secret through the environment/secret manager. The webhook secret must match `[A-Za-z0-9_-]{24,256}`. Keep separate bot credentials per wedding cell.

From a configured source checkout (or its container), explicitly configure the target:

```bash
python scripts/configure-telegram.py --confirm-bot-username YourExactDevelopmentBot
```

This opt-in script verifies `getMe` first, registers the HTTPS `/api/telegram/webhook` with private text-message updates, and sets the Mini App menu URL. It does not send messages or discard pending updates. If the menu call fails after webhook registration, registration may already have succeeded; inspect the bot state and retry deliberately. The helper only uses private DMs; group/edited/channel messages are ignored by the app.

Activate `WEDDINGOPS_SEND_NOTIFICATIONS=true` only in the disposable test cell after checking recipients, then recreate API/worker so both use identical settings. Simulated notices are not replayed automatically when sending is enabled. Create a fresh test interaction instead of resetting delivery state indiscriminately.

Issue one personal invitation, open its Telegram link and start the bot. Test `/now`, `/guest Sarah Tan`, explicit report confirmation, Mini App login, task acknowledgement, revocation, missing secret headers, duplicate updates, blocked bot delivery and worker restart. Verify Android/iOS/Web separately. Browser-cookie behavior in Telegram was not exercised here. Do not weaken CSRF/HMAC checks to make a webview work.

Official reference: https://core.telegram.org/bots/api and https://core.telegram.org/bots/webapps . They describe API behavior; the local mocked tests do not certify deployment.

## Mistral commissioning

Keep `WEDDINGOPS_AGENT_MODE=deterministic` through initial setup. Set
`WEDDINGOPS_MISTRAL_API_KEY` in the service environment and select
`WEDDINGOPS_MISTRAL_MODEL` (default: `deepseek-v4-1-flash-1017`). Set
`WEDDINGOPS_AGENT_MODE=mistral` when running the smoke test:

```bash
python scripts/smoke-mistral.py --acknowledge-paid-provider-call
```

The script sends a fixed set of fictional messages to Mistral. It reports
classifications and latency without printing credentials or provider bodies.
After a passing smoke test, reload both service processes with the same settings.
Explicit slash commands run locally. Free-form messages use at most one model
request and fall back to the deterministic parser on provider failure. Confirm
model access, usage allowance, and provider retention before real-event use.

## Backups and restoration

The UI guest CSV and `weddingops export` are useful operational exports, **not full backups**. A complete backup must preserve the event database and its schema; configuration and secret-manager recovery are separate. Encrypt off-host backups, restrict access and agree retention. Do not commit them or place them beside public artifacts.

Example backup from a running Compose cell:

```bash
umask 077
mkdir -p ../private-weddingops-backups
docker compose --env-file .env.production exec -T db \
  pg_dump -U weddingops -d weddingops -Fc \
  > ../private-weddingops-backups/event.dump
```

Choose a unique output filename so shell redirection does not overwrite a previous backup. A real release must restore a backup into a **new isolated staging database/cell** with external messaging disabled, then verify row counts, versions, pending approvals and access controls. Do not run `pg_restore --clean` against a live wedding to “test” recovery. The bundle/ZIP in Drive backs up source code and documentation, not guest/event runtime data.

## Operations / shutdown

Check readiness, worker lag, failed/undeliverable notices, clock synchronization and current backup status before doors open. Keep a printed run sheet and a named manual escalation lead. Activating `live` starts task reminder generation; returning to `draft` pauses new task reminders but does not cancel queued reports. Archive cancels pending deliveries and makes operational data read-only; it does not delete guest data or secrets.

For a suspected credential leak, disable the integration, rotate credentials through the owning service, revoke affected memberships and use the deterministic/manual route. Avoid logging Telegram request URLs because they contain the bot token. Do not use destructive `down -v` or database reset commands on an active cell. After closeout, follow the agreed deletion policy across databases, backups, gateway/provider logs and exported/printed documents.
