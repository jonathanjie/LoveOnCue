# ADR 0003: The assistant becomes a deputy that reads, drafts and chases

Status: proposed, 21 November 2026. Supersedes the "no tools, no conversation
history" rule in [ADR 0001](0001-authority-before-agent.md) and `AGENTS.md`.
The authority rules in ADR 0001 stay.

## Context

- Today the model only classifies each message into a fixed intent list, and
  code answers with canned text.
- The Haiku simulation gate scored ease and clarity at about 2 out of 5
  (`docs/product/2026-11-21-product-review.md` §6). Anything outside the list
  gets a help menu, and adding more intents will not close the gap.
- The founder's direction: an agent that partners with the coordinator, like
  an eager deputy. It can see the schedule, contact people and chase them for
  updates, and keep the coordinator informed of what happens on the ground.
- An independent advisor review (Fable model) agreed with the direction and
  drew the autonomy line used below.

## Decision

**The rule:** the model may read, write messages, and draft commands. Only a
human or deterministic code commits a change. `require_human` keeps rejecting
`agent` and `worker` actors in `Operations.execute` and `confirm`.

### 1. Conversational replies with tools
- Each message gets one model turn. The input is the person's role-scoped
  snapshot (`Queries.snapshot`, plus `coordinator_brief` for coordinators) and
  their last few turns of conversation.
- The model returns a validated plan: a reply text plus at most one tool call
  from a small allow-list.
- **Read tools** run at once: tasks, schedule, guest seating, places,
  knowledge, and the sender's own reports.
- **Write tools** only create existing drafts through `Operations.draft`:
  delay, incident, arrival and withdrawal. The person still taps Confirm.
- Admin commands are never tools.
- A **grounding check** rejects a reply that states a time, name or status
  that is not in the snapshot. It then falls back to a plain answer built
  from the snapshot.

### 2. The deputy heartbeat
Modelled on OpenClaw's heartbeat (see Prior art):
- **When it runs:** every 3 minutes of event time during the event window,
  and at once when a watched change happens (`state_version` changes, or a
  task or cue deadline passes). It is skipped when nothing has changed and no
  deadline is near, and when the inbound queue is busy.
- **What it checks:** deterministic code builds a short situation digest:
  - unacknowledged or overdue tasks, and cues coming up soon
  - silent helpers and their unanswered pings
  - open urgent incidents and blocked proposals
  - missing acknowledgements
- **Standing orders:** each wedding has a short checklist the coordinator can
  edit, for example "chase anyone who has not acknowledged 5 minutes before
  their task" or "tell me straight away about any kitchen delay". It works
  like OpenClaw's `HEARTBEAT.md`, kept small and free of secrets.
- **Silent by default:** the model returns `NOTHING_TO_REPORT` when nothing
  needs attention. Code drops that reply, so a quiet day stays quiet.
- **Code chooses who is contacted and why; the model only writes the wording.**
  A ping always goes to the owner of the task it concerns.

### 3. The autonomy line

| The deputy does it alone (rate-limited, audited as actor `agent`) | A human must tap |
|---|---|
| Reply to the sender from their own snapshot | Any change to records |
| Ask a task owner about their own task | Creating a proposal (sender), approving it (coordinator) |
| Ask a clarifying question | Broadcasts, and any message to more than one person |
| Send the coordinator digests and suggested actions as buttons | Carrying one person's free text to another |
| Tell the coordinator when someone stays silent | Reassignment; anything to the couple, vendors or guests |

### 4. Rules that apply everywhere
- An answer to a ping is a **claim**. It shows as "Jamie says he is at
  Entrance B (18:42)" until a typed command records it.
- **Rate limits:** at most 1 ping per person per item, and at most 1
  unprompted message per helper every 10 minutes. Repeated silence goes to
  the coordinator, not into more pings.
- The coordinator gets one rolling digest of at most 3 items, sent when
  something changes. Only urgent items interrupt.
- Every autonomous message is audited with its trigger and snapshot version,
  and labelled "Assistant" in chat.
- **Off switches:** the coordinator can turn the deputy off with `/deputy off`.
  Any helper can say "stop pinging me" (or send `/quiet`), and that stops
  their unprompted messages for the rest of the event, except for urgent items.
- **Nothing hidden:** every autonomous ping and digest appears in the
  coordinator's `/brief` under "Assistant activity". Questions such as "what
  did you do?" are answered from the audit log, never from the model's memory.
- **Fallback:** if the model is unavailable, the slash commands and the
  existing reminders in `Worker.schedule` keep working.

### 5. Data
- Conversation memory keeps the last 5 turns per person for 12 hours, then
  deletes them. Raw inbound payloads stay minimised.
- A new `deputy_pings` table pairs each ping with its answer or its expiry.

## Prior art

| Product | What we copy | What we avoid |
|---|---|---|
| OpenClaw heartbeat | A periodic agent turn plus waking on events; a small standing checklist; silent unless something needs attention (`HEARTBEAT_OK`); active hours; skip when busy; a cheaper model for heartbeat turns | Nothing in particular; it is a general pattern for one person's assistant |
| OpenAI Dots (Sept 2026) | Proactive work limited to safe actions: background research is read-only and cannot message people or change data | Its unseen memory, and the lack of a documented action log |
| Grok Bot "automatic check-ins" (Nov 2026) | — | Check-ins on by default that kept going after users declined four times; background actions invisible in chat; the bot denying calls it had made. Only an external gateway logged them. |

Sources:
- the local OpenClaw docs (`docs/gateway/heartbeat.md`, `docs/automation/cron-vs-heartbeat.md`)
- [Search Engine Journal on Dots](https://www.searchenginejournal.com/openai-dots-read-only-proactive-research/591565/)
- [TechCrunch on Dots](https://techcrunch.com/2026/09/29/openai-launches-dots-its-bubbly-agentic-avatar/)
- [NewCore on Grok Bot](https://newcore.com/newsroom/newcore-research-grok-bot-agents-reached-for-corporate-data-unprompted). NewCore sells agent gateways, so its research has a commercial interest.

We go further than Dots, because chasing people is the deputy's job. That is
why its pings are limited to task owners, capped in number, visible to the
coordinator, and stop when the person opts out.

## Out of scope for the first spike

- Routing requests between people.
- Model-suggested timeline rearrangements.
- Model-written broadcasts.
- Photo review changes.

## Success criteria (measured with `scripts/simulate.py` and the evals)

1. Mean ease and clarity of at least 3.5 in both simulation rounds, scored with
   the anchored rubric, using the same personas as before.
2. Zero ungrounded factual claims across about 40 grounded-answer eval cases.
3. Zero state changes or cross-person messages without a human tap, and zero
   data leaks, across at least 10 injection cases plus the round-2 injection.
4. At most 3 unprompted messages per helper per hour, at most 6 coordinator
   interruptions per hour, and at least 90% of pings to the right person at
   the right time.
5. Median reply under 4 seconds, cost per simulated wedding reported, and a
   run with the model off that still passes the existing tests.

## Consequences

- `Assistant._answer`'s intent ladder, its canned strings and the keyword
  rules in `DeterministicParser` go away over time. Slash-command parsing stays.
- `MistralParser` needs a tool-plan adapter.
- Prompt-injection risk rises with tools. The allow-list, the permission
  re-check in `Operations.authorize`, quoting helper text as data, and the
  confirm tap contain it.
- Model cost per message rises. This should be measured, not assumed.
- The deputy is a product hypothesis. It goes into the coordinator interview
  script, and the stop rule in the product review still applies.

## Review notes (plan-review, 21 November 2026)

No blocking findings. These mitigations are part of the design:

- **Context instead of read tools:** each turn gets the role-scoped context
  directly (tasks, schedule, places, the sender's reports, and the brief for
  coordinators). Only a guest lookup needs a second model call, so a message
  costs at most two calls.
- **Heartbeat budget:** heartbeat turns get their own time budget in the
  worker, so a slow model call cannot hold back the outbox. If needed, they
  can move to a separate process later.
- **Data in the prompt:** phones and dietary notes never enter the prompt
  unless the role may see them. Memory is capped at 5 turns per person and
  deleted after 12 hours.
- **Helper claims:** a helper's claim in a coordinator digest is quoted and
  collapsed onto one line, as in the existing notices.
- **Indexes:** `deputy_pings` is indexed on (wedding, recipient, created_at)
  for the rate-limit checks.
- **Evals still to write:** grounded-answer cases and injection cases.
