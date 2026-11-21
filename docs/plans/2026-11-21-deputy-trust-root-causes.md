# Deputy trust: fix the root causes, not the symptoms

Status: reviewed by the Fable advisor; revised, 21 November 2026.
Branch: `claude/loveoncue-trust-roots` (from `origin/main` at 5e20c51).
Inputs: gate v3 results (`docs/product/2026-11-21-product-review.md` §7–8), the
round 2 transcripts (`sim-g3b`), and the current code.

## Problem

The Haiku gate scores trust at 2.4–2.7 out of 5 (target 3.5). Ease and clarity
are near 3.4. The founder's instruction: fix the underlying reasons, with no
prompt patches for single scenarios.

## Evidence → root cause

| What users saw (gate v3) | Root cause in code |
|---|---|
| Coordinator: "change the run sheet: ceremony moves to Cedar Ballroom at 18:40, make it a proposal". Deputy: "I can't." The coordinator sent a free-text announcement instead. The run sheet still said "Garden 18:30", so the bride, the usher and the MC got the old answer. | **R1. The domain cannot represent the change.** The only run-sheet change is `propose_delay` (shift by minutes). Place and notes cannot change. So truth moves into free-text announcements, and state and messages split. |
| "the flat tyre is already logged"; "your 18:50 arrival is already in your open late report"; "the urgent report is waiting for your tap" (it was sent); the deputy denied an approval the coordinator had just made. | **R2. The context is a patchwork, not a ledger.** `_context` builds ad-hoc lists: the run sheet has no places, the coordinator sees no recent decisions, drafts waiting for a tap are not shown, and sent and unsent things look alike. The model fills gaps by guessing. |
| "Meanwhile keep guests in the foyer"; "Send guests through the foyer's double doors"; "Details that will be sent: …" under an arrival, which sends no details. | **R3. Model prose carries facts and outcomes, and only times are checked.** `grounded()` checks clock times only. The draft preview mixes the model's `details` with the real command. Nothing checks names, places, directives or claims such as "already logged". |
| The couple was offered an announcement. Michelle: "I can only look up one guest per message." Coordinator: "Ask Jordan to reply now" → "I can't message Jordan." Taylor: "tell Alex I'm reaching 6.50" → "I can't message Alex." Registration cannot check in a regular guest by chat. | **R4. Capabilities live in prose, and the vocabulary is report types, not operations.** `allowed_actions` is a context line; the JSON schema allows every action. Lookups are "actions", so one per message. There is no "message a person" operation. The arrival path searches the family roster only. |
| 16 coordinator interruptions in the confounder round (target ≤ 6/hour). | **R5. No attention policy.** Every source calls `notify()` for coordinators directly: incidents, silence notes, escalations, digests, approval requests. Nothing decides what deserves a push. |
| "ask Alex Morgan", said to Alex; "call the on-site team now" with no name or number; the greeting "hi… what do i do here" got the rigid help menu. | **R6. Rendering does not know the viewer, contacts are not data, and guard failures degrade to the old intent bot.** `coordinator_contact()` ignores who reads it. The wedding has no emergency contact field. When a guard trips, `Deputy.ask` drops to `Assistant.ask`, whose `unknown` answer is the menu. |

## Advisor review (Fable, 21 November 2026)

Verdict: the direction is right; D3 and D4 were overbuilt, and three root causes
were missing. Changes taken from the review:

- **R1 is wider:** there is no amend operation of any kind. Chris had to withdraw
  and resend to change +20 to +10; follow-ups on an open problem became new urgent
  reports.
- **R2 has a second source of truth: chat history.** `_remember` stores the drafted
  text as an assistant turn with no outcome, so unsent drafts read as facts later.
- **R3 is mostly R2.** The "foyer double doors" line is seed data. Only "keep
  guests in the foyer" was invented.
- **R7 (new): facts have no source or precedence.** Free-text announcements enter
  the trusted context, the model copies them into report details, and the
  coordinator is told a change is "already logged in the open incident".
- **R8 (new): open questions bounce to the coordinator.** About 12 replies end in
  "ask Alex". Nothing records the question or brings the answer back.
- **R9 (new): one action per message, and severity chosen by the model.** A late MC
  got "call the on-site team now"; Alex was offered an urgent report to himself.
- **R5 is per event, not per subject:** one silent task makes an escalation and a
  silence note.
- Cut for now: the verifier call and multi-round tools. Keep one-shot plans.

## Design (revised after review)

The authority rule from ADR 0001 and ADR 0003 stays: the model reads, writes
messages and drafts; only a human tap or deterministic code commits a change.

### S1. Code speaks for outcomes; history tells the truth (R2, R3, R9)
- Draft previews are rendered only from the command payload. Free-text fields
  that are in the payload (problem details, change reason) are shown because they
  will be sent; arrivals show none.
- Conversation memory keeps the model's words, not the draft text, and links the
  draft. When history is read back, each linked draft is annotated by code:
  SENT at hh:mm, EXPIRED (not sent), or WAITING for their tap.
- A new draft replaces the person's earlier pending draft (one pending draft per
  person), so a repeated message cannot make two drafts.
- The urgent safety line comes only from code, never from the prompt.

### S2. A sourced context (R2, R7)
- `_context` adds: place and note on each run-sheet item; the person's pending
  draft; the status of each of their reports; for coordinators, decisions made in
  the last hour and by whom.
- Each fact line is tagged with its source: `[run sheet]`, `[record]`,
  `[coordinator said hh:mm]`, `[helper reported hh:mm]`. One general rule in the
  prompt: records and the run sheet are facts; "said" and "reported" lines are
  someone's words and are relayed as such.
- The model does not repeat reminders about pending items; code reminds (S6).

### S3. The run sheet can change, and reports can be amended (R1)
- New command `change_item`: `item_id`, optional `new_start`, optional
  `location_id`, optional `note` (max 300), `reason`. `propose_delay` stays as an
  alias for a minute shift. The approval change record carries place and note.
- Apply: time changes cascade as today. A place change moves the item and only the
  open tasks linked to the item that were at the item's old place. The note is
  stored on the item (`timeline_items.change_note`).
- A coordinator's own confirmed draft applies at once, under three conditions: the
  preview is the code-rendered diff with the cascade and affected teams; the same
  checks as `decide_approval` run; the approval and decision are written in one
  transaction.
- The notice to affected teams is generated from the diff (`timeline_updated`, with
  Acknowledge).
- Amend: a new delay for the same item already replaces the pending one; the
  preview now says so. A follow-up about an open problem report adds an update to
  that report (`report_incident.updates`, by the report's short reference) instead
  of opening a new one.

### S4. Capabilities from policy; one "tell the coordinator" path; lookups (R4, R8, R9)
- Plan actions are generated from the capability map, and the per-person JSON
  schema lists only those actions; code checks again before acting.
- Helpers: `tell_coordinator` with a level (`fyi`, `question`, `problem`,
  `urgent`), one path for notes, questions and problems (an incident record with
  kind `question` or `other`). The level is shown in the preview; the person can
  see it before tapping.
- Coordinator: `send_message` to a named member, a team, or everyone (replaces
  `draft_announcement`). Answering a helper's question by name closes it and the
  answer goes to that helper.
- Read-only lookups move out of `action` into a `lookups` list (kind + query, at
  most 5). Code runs and renders them, so "Chloe and Ethan?" works in one message
  and table numbers come from code.
- One person resolver for arrivals: the guests and family members the actor may
  record (registration may check in regular guests).

### S5. Coordinator attention by subject (R5)
- Coordinator-bound items that are not pushes become digest items keyed by subject
  (`task:<id>`, `incident:<id>`, `question:<id>`); a newer item for the same subject
  replaces the older one. Each item shows its age.
- Push now only what needs a decision before the next digest: approval requests,
  urgent problems, and questions marked as needing an answer.
- One digest at most every 10 minutes, only when it has news.

### S6. Eager, not noisy (review §5)
- The heartbeat also chases unacknowledged announcements and run-sheet updates,
  under the same ping budget as tasks.

### S7. Viewer-aware rendering and real contacts (R6)
- Contact text knows the viewer; the coordinator is never told to ask themself.
- `weddings.emergency_contact` (set by the coordinator; seeded for rehearsal) is
  used in the urgent safety line; when unset, the brief says so.

### Deferred
- The claim verifier: measure after S1–S2, then decide. If needed, add a `sources`
  field (ledger line ids) that code checks, not a second model call.
- Multi-round tools, the repair loop, and a shared `describe()` for the brief.

## What we will not do

- No new prompt rules for single cases (foyer, rain, MC, flat tyre).
- No model commits. No model-chosen recipients for unprompted messages.
- No new Mini App work (separate session).

## Order of work and checks

1. S1 + S2. Tests: preview equals payload; history annotation; one pending draft;
   sourced lines; coordinator sees decisions.
2. S3. Migration (`change_note`). Tests: place change moves only matching tasks;
   coordinator tap applies with audit; notice from the diff; incident update.
3. S4. Tests: schema enum per role; tell_coordinator levels; send_message to a
   person; lookups; registration checks in a regular guest.
4. S5. Migration (`digest_items`). Tests: push vs digest; merge by subject; ages.
5. S6 + S7. Migration (`emergency_contact`). Tests.
6. Full suite, security review, PR, staging deploy, Haiku gate (same 2 rounds).

Success: trust ≥ 3.5 in both rounds, fallback ≤ 3%, coordinator pushes ≤ 6/hour
of event time in round 1 with no urgent item delayed, no prompt-injection leak.

## Resume point

If this work stops, read this file, then `git log origin/main..HEAD` on the
branch. The step list above is in dependency order; each step has its own tests.
