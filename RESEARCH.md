# Research dossier and reference collection

This records the original October 2026 research. The current direct Mistral adapter is described in [AGENT_DESIGN.md](AGENT_DESIGN.md).

Reviewed during the 2026-10-03 build. Primary vendor documentation and public repository metadata were used where available. This is desk research, not customer interviewing, procurement testing or an independent security audit. Product marketing is labeled as such. Source URLs are retained so Codex can re-check capabilities and licensing before changing the implementation.

## Conclusions that changed the build

**Do not expose a shared OpenClaw operator gateway to wedding helpers.** Its HTTP compatibility endpoint carries gateway-level operator authority; a client-pinned function is not a blanket restriction on internal runtime tools. WeddingOps therefore owns authenticated ingress and returns narrow, validated intents from a private gateway. Application permissions and the transactional database remain authoritative. [R1, R2]

**A skills file is not a security boundary.** Runtime policies, private deployment and server-side authorization must enforce what the model is allowed to cause. The current code does not grant the model a general WeddingOps API token. Automatic reminders are deterministic database work, not an LLM heartbeat. [R2–R5]

**AI wedding coordination is not an empty market.** Live run sheets, role-dependent views, AI planning assistance and schedule-change handling already appear in vendor offerings. The defensible hypothesis is reduced relay/acknowledgement delay for a temporary team using existing plans, not “first AI wedding planner.” This requires a measured field comparison. [R8–R12]

**OSWP is reference material, not our foundation code.** Its README describes noncommercial terms, while the default-branch LICENSE fetched through GitHub returned AGPL-3.0. Those are materially different terms. Do not say AGPL prohibits commercial use; clarify the repository's intended licensing with its maintainer before reuse. No code, stylesheet, schema implementation or artwork was copied into WeddingOps. [R6, R7]

## Runtime/platform findings

| Area | Observed evidence | Consequence |
|---|---|---|
| OpenClaw HTTP | Agent-target model IDs, client function calls, operator-authenticated endpoint, new session by default without an explicit user/session key | A real optional HTTP adapter; omit helper IDs/cookies/history; keep gateway private |
| OpenClaw tools/config | Global/per-agent policy, explicit deny rules, evolving defaults, agent entries and workspace controls | Ship a deny-all reference configuration; validate the exact installed version and traces before enabling |
| OpenClaw proactive behavior | Heartbeat/automation facilities exist | Useful infrastructure, but insufficient as the event's authoritative clock/queue; use the app worker |
| Telegram | Bots, private messages, Mini App launch/authentication and webhook management are documented | One bot per cell, numeric sender binding, signed initData and private DM-only V1 |
| OSWP | Planning-oriented guest/vendor/event concepts; conflicting README/LICENSE signals | Independent operational model; no source reuse pending clarification |

OpenClaw repository metadata observed through the connector was `version: 2026.9.7`, `license: MIT`, package blob SHA `653bba853fe6b8de4c3c679cb1f53062787e4424`. The `openai-http.ts` file was sampled at blob SHA `7ceefa39774aa084b96f70dd28fae05d3cb7d0c6`. These are retrieval observations, not proof of the newest published package, full source audit or an installed runtime. Documentation pages and translated variants can disagree about defaults; explicit settings and version-pinned validation matter more than assumptions.

## Wedding/event products

| Product | What the retrieved vendor material supports | Product consequence / uncertainty |
|---|---|---|
| EventSync Day-Of | Advertises live wedding-day coordination, role-specific views, AI assistant and planner-reviewed schedule recovery | Direct overlap; benchmark operational acknowledgements and failure recovery, not just chat answers |
| Colara | Public positioning around wedding operations/context; retrieved page was thin | Relevant lead, but no detailed feature/security validation; request a demo before a firm comparison |
| Coordon | Planner/vendor/task/timeline organization and mobile event-day operations | Planning data may already be organized elsewhere; import/reconcile rather than recreate a full planner suite |
| Timeline Genius / Genie | Official support describes an assistant grounded in timeline/event documents | Document-aware Q&A is not unique; differentiate verified live state and helper-specific actions |
| Aisle Planner | Official planner platform and collaborative planning/timeline positioning | Established planner workflows are integration constraints; do not compete first on budgeting/CRM |
| WeddingPlan Telegram Mini App | A third-party directory describes Telegram wedding planning functionality | Discovery lead only; not primary proof of a current product, license, adoption or live coordination quality |

No competitor account was purchased, live event was observed, private feature was inspected, or price/adoption claim was established. Earlier conversational labels and numbers should not be treated as verified market facts. The official Aisle Planner source used here is **aisleplanner.com**; similarly named sites should not be assumed to be the same vendor.

## Framework relevance rather than a “forefront” ranking

| Framework | Primary-source category | Choice for this build |
|---|---|---|
| LangGraph | Stateful/durable agent workflow orchestration | A reasonable future choice for complex resumable agent control; unnecessary for the current transactional service |
| CrewAI | Multi-agent crews and event-driven flows | No evidence that role-named AI agents improve this one-authority operational workflow; not included |
| n8n | Integration/automation platform with commercial-use conditions | Possible import/connectivity glue later; not the mission-critical execution core; review exact licensing use case |
| PydanticAI | Typed agent framework | Relevant alternative, but Pydantic validation plus one HTTP adapter is sufficient here; PydanticAI is not installed |
| Mastra | TypeScript agents/workflows/application framework | Relevant for a later TS-native agent backend; no reason to layer it over the current working service |
| OpenAI Agents SDK | Lightweight agents/tools/handoffs/tracing | Alternative runtime if the private OpenClaw contract proves unsuitable; not an additional dependency |

This is not a popularity/stars ranking or a claim that one framework is universally more advanced. The categories solve different problems. The initial build adds no orchestration framework because ordinary typed code already supplies authorization, state transitions, approval and persistence.

## Reference register

All accessed/reviewed for this build on 2026-10-03 unless the description explicitly says discovery-only. Links identify the specific source, not a guarantee that its content will remain unchanged.

- **R1 — OpenClaw HTTP compatibility contract:** https://docs.openclaw.ai/gateway/openai-http-api . Primary technical documentation; operator boundary, agent routing, stateless default and client-tool distinction.
- **R2 — OpenClaw tool policy:** https://docs.openclaw.ai/gateway/config-tools/tool-policy and https://docs.openclaw.ai/gateway/config-tools . Primary; deny/profile policy and explicit runtime controls.
- **R3 — OpenClaw agent/workspace configuration:** https://docs.openclaw.ai/gateway/config-agents . Primary; entries, workspace, model and context settings.
- **R4 — OpenClaw heartbeat:** https://docs.openclaw.ai/gateway/heartbeat . Primary; proactive scheduling facility, not application business-state authority.
- **R5 — OpenClaw repository/CLI:** https://github.com/openclaw/openclaw/blob/main/package.json ; https://github.com/openclaw/openclaw/blob/main/src/gateway/openai-http.ts ; https://docs.openclaw.ai/cli/config . Primary source/metadata, sampled rather than fully audited.
- **R6 — OSWP README:** https://github.com/dccakes/SCV . Primary repository, planning/domain reference and README license wording.
- **R7 — OSWP LICENSE:** https://github.com/dccakes/SCV/blob/main/LICENSE . Primary text fetched via GitHub connector; returned GNU Affero GPL v3, in conflict with README wording.
- **R8 — EventSync:** https://geteventsync.app/ ; https://geteventsync.app/wedding-day-assistant . Vendor claims, not independently tested capability.
- **R9 — Colara:** https://colara.co/ . Vendor positioning; limited retrieved detail.
- **R10 — Coordon:** https://www.coordon.com/en . Vendor product material.
- **R11 — Timeline Genius:** https://support.timelinegenius.com/en/articles/13187867-introducing-genie-your-new-timeline-genius-ai-assistant . Official support article describing Genie.
- **R12 — Aisle Planner:** https://aisleplanner.com/ . Official planner platform.
- **R13 — Telegram:** https://core.telegram.org/bots/webapps ; https://core.telegram.org/bots/api . Primary authentication/channel/API contracts. Device/webhook behavior still requires real tests.
- **R14 — Telegram wedding discovery lead:** https://www.findmini.app/weddingplanappbot/ . Third-party directory, not independently verified or used as a technical authority.
- **R15 — LangGraph:** https://docs.langchain.com/oss/python/langgraph/overview . Primary orchestration overview.
- **R16 — CrewAI:** https://docs.crewai.com/v1.15.14/en/concepts/flows . Version-specific official flow documentation; not a latest-version assertion.
- **R17 — n8n license guidance:** https://support.n8n.io/article/can-i-use-your-license-for-my-use-case . Primary vendor guidance; embedding/hosted use needs case-specific review.
- **R18 — PydanticAI:** https://pydantic.dev/docs/ai/overview/ . Primary framework overview.
- **R19 — Mastra:** https://mastra.ai/docs . Primary framework documentation.
- **R20 — OpenAI Agents SDK:** https://openai.github.io/openai-agents-python/ . Official SDK documentation; alternative considered, not integrated.
- **R21 — psycopg packaging/licensing:** https://pypi.org/project/psycopg/ . Publisher-maintained package metadata used for the optional pinned driver; installation/runtime not available in this environment.

## Unanswered product questions

Who supplies live updates when the lead is busy? Will temporary helpers use Telegram? How many notifications are tolerated? Does a professional planner already have an effective radio workflow? How much pre-event cleanup is needed before a useful run sheet exists? What information should be withheld from the couple or from particular relatives? How do accessibility/language/device differences change onboarding?

The build makes these assumptions visible; it does not answer them with invented interviews. Observe a rehearsal, compare with current workflows, measure factual answer and acknowledgement delay, and only then decide which integrations/AI capabilities justify further scope.
