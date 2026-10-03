# ADR 0001: application authority, replaceable agent runtime

Decision: use a single WeddingOps application as the authenticated ingress and
source of truth. OpenClaw is an optional private, stateless intent interpreter.
Telegram does not connect helpers to an omnipotent OpenClaw agent.

Reason: OpenClaw's official trust model says users of a tool-enabled agent share
its delegated tool authority. Per-wedding isolation alone does not separate an
usher from a coordinator inside that wedding. No model-supplied role or actor ID
can authorize an operation. Client-function arguments are untrusted proposals.

The dedicated OpenClaw agent must have no shell, file, session, browser, messaging,
approval or DB tools. It returns a narrow structured intent to the application.
The application resolves identities, enforces capability and team scope, asks
for human confirmation where needed, and commits through deterministic handlers.
The example runtime policy remains a live commissioning gate. No retrieved document text is fed back into an agent capable of writing state.

Use fresh HTTP sessions: omit the OpenAI-compatible `user` field and explicit
session headers. Keep the Gateway on private ingress. This is a reduced-trust
embedding, not a claim that OpenClaw becomes a hostile multi-tenant service.
Do not use its Control UI as the helper Mini App.

Sources: https://docs.openclaw.ai/gateway/security/trust-model and
https://docs.openclaw.ai/gateway/openai-http-api (reviewed 2026-10-03).
