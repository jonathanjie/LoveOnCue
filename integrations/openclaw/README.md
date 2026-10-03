# OpenClaw integration: real adapter, live commissioning still required

The Python adapter in `src/wedding_ops/agent.py` calls OpenClaw's documented
`POST /v1/chat/completions` with exactly one client function, `interpret_wedding_intent`.
It accepts one valid structured tool call and rejects other shapes. HTTP transport,
malformed results, wrong tool names and model failure are covered by local mock tests.
**No OpenClaw installation or paid model call was available in this build.**

## Important departure from a shared bot gateway

WeddingOps owns Telegram enrollment, API sessions, roles, outbox and scheduler. OpenClaw
receives a single human message and returns an untrusted classification. It never receives
a session cookie, membership ID, guest directory, retrieved document or database token.
The message itself can contain personal data; provider/session retention still needs review.

The official OpenAI-compatible endpoint is gateway-operator access, not a restricted
per-helper endpoint. Keep it private. A pinned HTTP client function does NOT itself disable
OpenClaw's internal tools. Runtime policy must block those independently. See primary docs:
https://docs.openclaw.ai/gateway/openai-http-api and
https://docs.openclaw.ai/gateway/config-tools/tool-policy.

## Commission on a separate, disposable cell

1. Install an explicitly reviewed OpenClaw version on your own host/container. Record
   `openclaw --version`, package/commit hash, model and provider in the release evidence.
   Repository metadata observed during research was 2026.9.7; this is not an assertion
   that a published release with that version was installed here.
2. Review `openclaw.json.example` against that version's schema. Replace only the workspace
   path and configured provider/model target. Start from a NEW state directory; do not
   merge into a personal gateway that already has channels, secrets or plugins.
3. Set `OPENCLAW_GATEWAY_TOKEN` securely in the runtime. Keep provider credentials separate.
   Do not put keys in the repository, config example, workspace or screenshots.
4. Validate configuration with the installed CLI (`openclaw config validate`; check that
   version's help). Ensure the effective policy denies every internal tool. Keep `skills: []`,
   context injection disabled, no channels/plugins, no cron/heartbeat or shared sessions.
   This example is documentation-derived, NOT locally runtime-validated.
5. For a same-host test, bind loopback only. Containers must use a private network with no
   published gateway port; adjust binding deliberately, not by exposing operator access
   to helpers. Use authenticated TLS if crossing a host/network boundary.
6. Set the WeddingOps variables below. First run the explicit classifier smoke script
   with fictional text. Inspect runtime traces locally: no internal tool execution,
   unexpected network access, cross-session retrieval or automatic messages may occur.
7. Run adversarial tests and a provider outage rehearsal. If wildcard deny also blocks the
   caller-supplied client function on your version, leave deterministic mode on and repair
   the adapter/policy with a narrowly reviewed allowlist. Do not enable all tools to fix it.

```bash
export WEDDINGOPS_AGENT_MODE=openclaw
export WEDDINGOPS_OPENCLAW_URL=http://127.0.0.1:18789
export WEDDINGOPS_OPENCLAW_AGENT=weddingops-intent
# Load WEDDINGOPS_OPENCLAW_TOKEN from your secret manager; same gateway bearer value.
python scripts/smoke-openclaw.py --acknowledge-paid-provider-call
```

The script does not configure OpenClaw, start a server, change event data or send Telegram
messages. It tests the actual returned intent without silently accepting fallback results.
It cannot certify the gateway's tool policy; inspect the effective config and execution
traces separately. `AGENTS.md` and the skill file are reference policies, not security gates.

## Contract and acceptance

`model` targets `openclaw/weddingops-intent`, not a provider-model string. No `user` or
session header is sent. Sessionless request routing does not imply zero logging/retention.
A timeout, non-tool finish, multiple calls, invalid fields or wrong tool name falls back to
the explicitly labeled deterministic parser. No write occurs merely because parsing worked.

Sources: agent and workspace configuration
https://docs.openclaw.ai/gateway/config-agents ; heartbeat
https://docs.openclaw.ai/gateway/heartbeat ; CLI schema checks
https://docs.openclaw.ai/cli/config . Reviewed 2026-10-03; pin and re-check before deployment.
