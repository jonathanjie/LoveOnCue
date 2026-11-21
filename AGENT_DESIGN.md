# Agent behavior and deterministic authority

## Implemented boundary

The optional Mistral adapter calls chat completions directly and validates the returned JSON as an `Intent` with `kind`, a short entity `query`, and optional bounded delay minutes. No actor IDs, roles, arbitrary tools, approval fields or database identifiers are accepted from the model.

Accepted kinds are now, guest, location, vendor, knowledge, family_status, arrival, missing_family, delay and unknown. Unsupported/administrative/safety requests return a handoff/help response. The model can still misclassify language; confirmation and permissions limit the consequences rather than pretending classification is infallible.

## Read path

Authenticate → reload current member/team access → get scoped snapshot → interpret the single message → resolve visible entities deterministically → return a factual DTO or approved source excerpt with time/provenance. No conversation memory or retrieved knowledge is sent back to the model. A query such as “Has the bride's father arrived?” cannot itself record an arrival.

Documented slash commands and a short list of common assignment questions run locally. Deterministic mode handles a limited English vocabulary. Model HTTP/protocol errors produce `deterministic_fallback` with `degraded=true`. Search can report no verified answer; it must not fabricate one.

## Report path

Interpret → resolve unambiguous allowed entity → prepare typed command → show exact draft → authenticated reporting human confirms within five real minutes → application reauthorizes and commits. A missing family member report records an unconfirmed location, never a definitive absence. Ambiguous multiple matches require clarification rather than choosing the first person.

For a delay, this confirmation creates a proposal only. A coordinator separately reviews the precise dependency diff, blockers, recipients and expiry, then approves/rejects through the protected UI. The agent has no approval tool or cookie. Consequential approvals cannot be invoked by an `Actor(source='agent')` even in-process.

## Tool surface

The actual application command schema is exported, including task actions, arrivals, incidents, proposals/decisions, notifications, reviewed knowledge, setup, vendor status, guest corrections, membership revocation and lifecycle. Not every human API command is exposed to the model. Conflating the public command API with the much smaller model intent schema would remove an important boundary.

Operational scheduling is a deterministic worker, not an LLM heartbeat. It handles unacknowledged upcoming/overdue tasks, coordinator escalation, proposal expiry, delivery retries and stale notice cancellation. Only approved committed schedule changes generate the corresponding role-specific instructions.

## Runtime protection

The application calls Mistral over HTTPS with a server-side key and provides no tools. It sends the intent schema and the current helper message. The database and Telegram credentials stay outside the model request. See [provider commissioning](deploy/README.md#mistral-commissioning).

The user message may itself contain a person's name or sensitive note. Provider retention and support access must be agreed before sending real guest data. Stateless routing is not a promise of no stored logs.

## Evaluation and expansion

Current tests check malformed JSON, disallowed intents, provider failure, report confirmation/expiry, negative arrival wording, role boundaries, cross-event references and a malicious document unable to cause a tool action. These are bounded regression cases, not a blanket prompt-injection guarantee.

`scripts/smoke-mistral.py` is an explicit opt-in live contract check with fictional messages. Before enabling a provider, add a reviewed test set spanning ambiguous names, negation, questions versus reports, relative timing, family roles, unsupported requests and adversarial wording. Measure wrong-action proposals separately from helpfulness. Any future semantic synthesis must preserve source citations, permission filtering and a read-only model context. Any future tool-calling agent must use server-bound capabilities, never a model-supplied actor ID.
