# Deputy claim check: model words must trace to a source

Status: reviewed by the Fable advisor; revised and built, 22 November 2026.
Branch: `claude/loveoncue-trust-roots` (PR #6).
Inputs: gate v5 transcripts (`sim-g5`, `sim-g5b` conversation turns), product
review §8, and `src/wedding_ops/deputy.py` at eec18ab.

## Problem

Gate v5 trust is 2.17 (round 1) and 2.71 (round 2), against a target of 3.5.
S1–S7 fixed the structure: fallback replies 0%, coordinator pushes 3–7. The
trust failures that remain are things the model writes that nothing checks.

## Evidence (gate v5, verbatim replies) → classes

| Class | Examples | How often (v5, ~140 replies) |
|---|---|---|
| **C1. The deputy narrates acts it cannot do.** It has no effect of its own; only a tapped draft acts. | "I'll flag it to the coordinator so they know…" (MC); "I'm flagging it to the coordinator now" (driver); "I'll ask the coordinator where guests should go" (usher, no draft); "I'll flag to them that you may be late" (MC, no draft); "tap it, then I'll draft the note" (family liaison); "Tap to apply it, then I'll draft Asha's message" (coordinator) | about 12 |
| **C2. Facts other than clock times are not checked.** `grounded()` checks only `HH:MM`. | "Let me check Noah Lim" when asked about Benjamin Wu; report details "No injury reported"; an invented "18:28" passed because 18:28 was the "Now" line; "Your 20-minute request is with Alex" (the person said they did not send it) | about 8 |
| **C3. Draft details are model prose.** The coordinator receives the model's paraphrase as the helper's report. | details with added facts ("No injury reported"); details merged from unrelated turns | 3–4 |
| **C4. Code-written text that is false.** | "Dinner service is already at that time" when the plan gave no time at all (`_change_item`) | 1 |
| **C5. Status polarity.** | "+15 not approved" just after the coordinator approved it | 1–2 |

C1 is the largest class, and it is not a single scenario: it is how an "eager
deputy" talks when its words are not tied to what code does.

## Root causes

1. **The model speaks for outcomes in the first person.** S1 made previews and
   history code-rendered, but the reply above a draft is still free prose, and
   nothing stops it describing acts ("I'll flag", "I'm sending") that only a tap
   or code can do.
2. **Grounding is a single token type against the whole context.** Times are
   checked against every trusted line, so any time on any line (including "Now")
   passes. Names, places, tables, counts and report references are not checked.
3. **The payload of a report is written by the model**, not by the person who
   reports. The coordinator cannot tell the helper's facts from the model's.
4. **Arguments are not traced to the person's words.** Lookup names and arrival
   names can come from older turns or be invented.

## Fable review (22 November 2026)

Verdict: revise before build. Taken from the review:
- **A cause was missing:** the prompt told the model to "say what to send next" and
  to "offer to ask the coordinator", and prose was the only place for a next step.
  So the model narrated acts because it was asked to.
- **K4 was a keyword patch.** It misses "Consider it flagged". The structural fix:
  the model writes only an answer, and code writes every outcome and next-step
  sentence. The first-person detector stays as a gate metric only.
- **Token checks miss statements.** Status claims ("Your 20-minute request is with
  Alex") need ownership: code states report status, bound to a reference.
- **Enforced citations would cause false repairs** with a Flash model. Support is
  all record lines, with quoted words removed, and without the "Now" line (an
  invented time could cite it).
- **Report content:** use the latest message by default; add earlier messages only
  when the plan quotes them and they are newer than the last sent draft.
- **No repair call** for v1: remove, then fall back. Add repair only if fact
  removals exceed 5%.
- Replay the v5 replies offline before the gate.

## Design (as built)

One principle: **the model writes the answer; code writes outcomes. Facts in the
answer trace to records; report content is the person's own words.**

### K1. Who writes what (schema split)
- `DeputyPlan.reply` became `answer` (may be empty). `details` is removed.
- New fields that code turns into words: `status_of` (references whose status code
  states from the record), `say_time` (code states the current time), `also` (a
  second thing; code writes "After that, tell me about: …"), and `quote` (earlier
  message numbers a report should carry).
- With a draft, code's introduction ("Check this report before I send it.") always
  follows the answer, and `render_reply` adds the preview and the tap line.
- The prompt says once, in general terms, that the system writes drafts, outcomes,
  status, time and seating, and that the model cannot act on its own. The two lines
  that caused narration are gone.

### K2. Facts (`claims.py`)
- Extracted: clock times (`18:40`, `6.40pm`, `7pm`; an hour without am or pm may be
  either half of the day), tables, counts (`44 of 180`), references (`R2`), and
  known names (places, members and first names, guests and family).
- Support: the context's grounding text (record lines; quoted words, the clock line,
  the pending draft and the brief removed), plus lookups run for this message, plus
  the latest message when the plan drafts. Names the person just used may be echoed.
- A sentence with an unsupported fact is removed. If nothing is left, code says
  "I can't confirm that from the records."

### K3. Status is code's
- A sentence that names a report (R1, request, report, question, alert, draft, note)
  together with a status word (sent, pending, approved, open, answered, …) is removed.
- Code states the status of the references in `status_of` and in removed sentences.
  With no reference, it states the pending draft, or else the latest report.

### K4. Report content and arguments are the person's words
- Reports carry the latest message, after any quoted earlier messages since the last
  sent draft, joined with " / ". The preview says "Your words, as sent"; coordinator
  notices say "Their words".
- The model's title is kept only if its facts are supported; otherwise the title is
  the person's message.
- Lookup names and arrival names must share a word with the person's messages since
  their last sent draft. Coordinator messages and run-sheet notes may not add facts
  beyond the records and the person's words.

### K5. Code text must be true
- `_change_item` says "already at HH:MM" only when the plan gave that time.

### Offline replay (v5 replies, approximate end-of-run context)
71 answers, 173 sentences. Removed: 14 status sentences (now stated by code), about
5 unsupported facts (for example "her seat is Table 18" from chat history, "Let me
check Noah Lim" when asked about Benjamin Wu) and a few replay artifacts. 9
first-person acts.

## Gate v6 (22 November, 26 raters: 2 runs per persona)

| Round | Ease / Clarity / Trust | Answers | Fact removals | Status sentences | First-person acts |
|---|---|---|---|---|---|
| R1 normal (12) | 3.08 / 2.75 / 2.75 | 99 | 4 (4%) | 1 | 8 |
| R2 rain (14) | 3.50 / 3.00 / 2.71 | 97 | 5 (5%) | 4 | 21 |

Fallback replies 0%. Trust is level with v4 and v5. What the raters found, and the
fix (commit 7858501):
- **"Okay." replies** (my regression): an empty answer with no action gave "Okay.".
  Now code says nothing was done.
- **Every unanswered question became a draft** (my prompt line). Now a coordinator
  question is drafted only when they need the answer to act.
- **First-person promises stayed at 15% of answers** with the prompt alone, so they
  are removed: the deputy has no future and no effect of its own. Any first-person
  future ("I'll", "let me") counts, whatever the verb.
- **The coordinator's messages came out empty.** Cause: one flat set of 16 optional
  fields shared by 13 actions. The model skipped a message's text and filled fields
  that did not apply. Now the model fills one object per action (only its fields,
  essentials required), and the parser flattens it. A probe of 9 messages × 2 runs
  scored flat 10/18, flat with core fields required 6/18, per action 10–11/18, and
  only per action reliably fills the message.
- **Acknowledge was chosen for questions after a check-in ping** in every schema.
  Acknowledging changes a record without a tap, so code now decides that a message
  is a confirmation (short, no question word or mark).

Residual (model judgment, all behind a tap): eager drafts (a coordinator question
for a seat lookup, a nudge when asked "who never ack"), and an occasional malformed
recipient, which code turns into a clarification. URGENT plus the emergency line on
non-emergencies (the model chooses the level) is unchanged.

## Gate v7 (22 November, 26 raters, code at e22cc4b)

Six round-2 raters could not start with the others (the session limit is 20 agents
at once), so they ran in a fresh world `r2c` with its own clock. The r2b banquet lead
ran alone in its world.

| | Round 1 (12) | Round 2 (14) |
|---|---|---|
| Ease / Clarity / Trust, v6 | 3.08 / 2.75 / 2.75 | 3.50 / 3.00 / 2.71 |
| Ease / Clarity / Trust, v7 | 3.25 / 3.17 / 2.67 | 3.50 / 3.21 / 2.43 |
| Fallback replies, v7 | 0 / 149 | 0 / 171 |
| Fact removals, v7 | 3 of 89 answers | 3 of 103 answers |
| First-person promises removed, v7 | 23 | 20 |
| Coordinator pushes, v7 | 10 and 9 (14 helper questions) | 15, 2 and 9 (18 helper questions) |

Clarity went up in both rounds. Trust did not move (the noise between runs is about
0.3). The claim check does its narrow job: about 3% of answers lose an unsupported
fact, and the promises and report-status claims are removed before anyone sees them.
The trust complaints that remain are of other kinds:

1. **Over-drafting.** Plain questions became coordinator reports with a preview and
   a Send tap ("Check this report before I send it", "Problem reports also go to
   your team", "Confirm only if this is a different problem"). Helper questions
   pushed to the coordinator rose from 2–6 per world to 7–11. The per-action schema
   makes the model choose an action more often (see the probe), and a question has
   no lighter path than a full report draft.
2. **"Your words, as sent" merged several messages** into one quote, which raters
   read as a misquote (driver, registration, banquet). This is K4's `quote`.
3. **Statement-level contradictions** that tokens cannot catch: "Noted, Robert Tan's
   arrival is recorded" before the tap; "I've taken back that urgent report" before
   the withdrawal; an answer saying "speeches stay at 19:45" above a preview that moves
   them; "0 of 1 acknowledged" after a message to one person, read as the count for
   the run-sheet change.
4. **Internal names in answers** ("tell_coordinator", "draft_arrival") and the
   "After that, tell me about:" line, which reads as a template leftover.
5. Not product defects: the simulated clock runs ahead of the persona's stated time;
   the emergency contact is a seeded placeholder; "the foyer's double doors" is real
   place data that raters cannot see.

Recommended next, in order:
- A question path lighter than a report: the answer says what is not known, and
  code adds one "Ask the coordinator" button that creates the question on tap, with
  no preview. Reports stay for problems.
- Carry only the latest message in a report (drop `quote`), as Fable first advised.
- Remove `also`, and remove sentences that name an internal action.
- Treat "recorded", "taken back", "withdrawn" and similar outcome words like report
  status: code states the outcome of a draft only after the tap.
- Review the plan schema choice with Fable: the per-action schema fills messages
  reliably but drafts more often than the flat one.

## Fable review of the gate v7 fixes (22 November)

Verdict: revise, then build. Two items change, one is cut, and the gate is fixed first.

| Recommended fix | Verdict |
|---|---|
| Lighter question path | **Keep, changed.** Same `ActionDraft`, light render, so a tap still commits code-rendered content: the person's latest message verbatim, no model title. Remove `level: question` from the model's `tell_coordinator`. |
| Drop `quote` | **Keep.** Also remove the U-numbering from the prompt; follow-ups use `about`. |
| Remove `also` | **Keep.** |
| Remove sentences that name an action | **Keep as a backstop**, built from the `DeputyAction` enum (a closed code vocabulary). The cause is the prose: the prompt and the CONTEXT line "Actions you may offer this person: tell_coordinator, …". The schema already carries the names, so take them out of the prose. |
| Outcome words ("recorded", "taken back") | **Cut.** A keyword patch like the first K4; "Consider it done" passes it. |

Further changes from the review:
- **Answer against preview:** when a draft exists, the model's answer is dropped and code's introduction and preview are the whole reply. This removes "recorded before the tap" and "speeches stay at 19:45" by construction, and the `text if drafting` support branch can go. Cost: a question asked together with an action request loses its answer; count that case in the v7 transcripts first.
- **"0 of 1 acknowledged"** is a defect in code text: the brief line must name the update it counts.
- **Question button:** the model sets one boolean (the CONTEXT does not answer this). Code decides whether to show the button: not for a coordinator, not with a draft in the same reply, not while this person has an open question, and under a cap. Code also offers it with "I can't confirm that from the records." The label says what it sends; the next message invalidates it; the confirmation quotes the words and offers Undo. One open question per person; later taps update it. The couple get the button but are never chased.
- **Schema:** keep per action. The likely causes of over-drafting are two prompt lines ("Drafting costs nothing … choose the action now" and "also choose tell_coordinator with level question") and the missing light path. Reword the first and delete the second; both are general rules. Extend the probe to about 30 messages, half needing no action, and measure false drafts, not field fill.
- **The gate is now the limit.** Trust moved 2.4–2.9 over five versions with noise of 0.3 and 12–14 raters, so it cannot detect these fixes. Before v8:
  - Remove the clock drift and the placeholder emergency contact.
  - Show raters the records and what the coordinator received.
  - Use one world per round.
  - Have raters score a hand-written ideal transcript, to find the ceiling.
  - Primary evidence: a labelled replay set of about 60 messages from the v5–v7 transcripts, run 3 times.
  - Compare versions as blind pairs on the same scripts, and count complaints per class.

Build order:
1. Replay set, gate repairs, ceiling calibration.
2. Deletions: the answer when a draft exists, `also`, `quote`, action names out of the prose, and the enum filter.
3. Question button, with `question` removed from the model's levels and the two prompt lines changed.
4. Extended probe, then gate v8.

Measure:
- False-draft rate on the replay set.
- Helper questions per world (target 2–6) and button tap-through.
- Replies with internal names (target 0).
- Complaints per class.
- Paired trust preference, v7 against v8.

## Step 1: replay set, gate repairs, ceiling (23 November)

Built (commits 4c57966 and the next one):
- **Replay set** (`scripts/replay_cases.py`): 63 messages from the gate v5–v7 chats, each
  labelled with the outcome a good reply has (answer, question, report, urgent, late,
  change, message, arrival, withdraw). Labels are judgments written before any replay.
- **Replay runner** (`scripts/replay.py --key K --out D --runs 3`): each case runs in a
  fresh copy of a stage world (r1 at 17:45, r2 at 18:25, r2-moved after the rain change),
  with any earlier steps the case needs. It scores the outcome, false drafts, internal
  names and template lines, and missing facts. 189 replies take about one minute.
- **Gate repairs** (`scripts/simulate.py`, `scripts/gate.py`):
  - `realtime`: the simulated clock runs at real speed from the persona's start time. No
    clock loop, so no drift.
  - A realistic fictional emergency contact replaces the seeded placeholder.
  - `records --as M`: what raters check the bot against after playing: run sheet, places,
    tasks, what reached the coordinator (with the teams that saw it), and which updates
    the member acknowledged.
  - `transcript --as M`: what the member saw, in order, with each action button.
  - `gate.py prompts --round r1|r2 --world D --out F`: the persona prompts, now in the
    repository. One cast per world; at most two casts at once (14 raters), so no rater
    waits for an agent slot.

### Replay baseline (code at 61ce8ea, 3 runs)

| Measure | Result |
|---|---|
| Outcome matches the label | 128 of 189 |
| False drafts (answer-only cases that drafted) | 40 of 90 |
| Replies with "After that, tell me about" (one also names an action) | 42 |
| Coordinator "tell X …" messages drafted (5 cases) | 1 of 15 |
| Replies missing a required fact | 0 |

Findings the replay adds:
- **The coordinator's context lists no people.** The model writes "Taylor isn't in the
  team list I have" and leaves `to` or `message` empty, so 14 of 15 "tell X …" runs
  end as "Who should get it?" or "What should the message say?". In the gate
  this was hidden because the person had usually appeared earlier in the chat.
- **Over-drafting is mostly question drafts** (62 of 189 replies), including plain
  questions the records answer ("when exactly I announce dinner", "where i put ppl now").
- **Escalation level:** "Can someone cover the welcome for me?" became an URGENT report
  in 3 of 3 runs, and "hello?? i sent already" an urgent update in 3 of 3.

Results per run are in `docs/plans/2026-11-23-gate-ceiling/replay-baseline-61ce8ea.jsonl`.

### Ceiling calibration

Three v7 chats (r2 usher, r2 driver, r1 MC) were exported with `transcript`, and I wrote
an ideal chat for each: the same messages and notices, with replies that answer from the
records, keep one urgent report, state status honestly, and offer a question button only
when the records cannot answer. Haiku raters read a chat and its records (blind, two per
chat), and other Haiku raters compared the two chats of a persona side by side, in both
orders. Materials: `docs/plans/2026-11-23-gate-ceiling/` (`key.json` maps the chats).

Run 1 had defects in my setup: the transcripts showed no buttons, and the records showed
no acknowledgements. Raters then read "tap Ask the coordinator" as a missing button. Run 2
fixed both:

| Run 2 | v7 chats | Ideal chats |
|---|---|---|
| Single ratings, ease / clarity / trust (6 each) | 3.0 / 3.0 / 2.5 | 3.0 / 3.0 / 3.5 |
| Paired, preferred (6 pairs, both orders) | 0 | 6 |
| Paired, ease / clarity / trust | 3.2 / 2.8 / 2.7 | 4.0 / 4.0 / 4.5 |

What this means for the gate:
1. **A single reader's ease and clarity do not discriminate**: every one of 12 single
   ratings gave 3 and 3. Only trust moved, by about 1 point.
2. **The old success line, trust ≥ 3.5, is the ceiling itself**: a hand-written ideal
   scored 3.5 from single raters. Read singly, raters always find a gap.
3. **Paired, blind comparison discriminates**: 6 of 6 preferred the ideal in both orders,
   with a trust gap of 1.8 and ease and clarity gaps of about 1.
4. So gate v8 uses: the replay metrics as primary evidence; paired blind comparison of
   v7 against v8 on the same scripts as the human-proxy measure; live persona play only
   to find new kinds of failure, not to pass or fail.

Defects the raters found in code-written text (both versions show them where they apply):
- "Problem reports also go to your team" after a question that no team sees.
- "Your words, as sent" on a draft that is not sent yet.
- The "Acknowledged" reply repeats the message and cuts it mid-word ("Speech o").
- Open items are not surfaced: an unacknowledged task or update, and a coordinator's
  instruction that asks the helper to act.

## Steps 2 to 4 and gate v8 (23 November)

Built (commits 2ecc5e0, 3ab5dea, 15de154 and the next one), reviewed by Fable before the gate.

What changed, and where the build departs from Fable's review, with the evidence:
- **Asking the coordinator is its own action**, rendered by code as one light button that
  sends the person's own message. Fable proposed a boolean; the model ignored it and filed
  62 of 189 replies as problem reports. Code still decides: never for the coordinator, never
  over a waiting draft, a cap of 12 open questions, at most 3 per person (then the message is
  added to their latest), Undo after sending, stale on the next message. Each tap is a new
  question: adding to the latest open thread filed unrelated items together (gate v8).
- **Action names stay in the system prompt.** Without them the model chose report_late for
  arrivals and questions (83 of 189). The per-role "Actions you may offer" context line is
  gone, and a backstop removes answer sentences that name an action or field. Leaks: 0.
- **The answer is dropped only beside a run-sheet change**, whose preview states the times.
  Dropping it beside every draft lost correct answers (13 false drafts; 6 lost a required fact
  such as the emergency contact). Offers to act ("I can flag", "want me to ask") are removed
  beside a draft or button; negations ("I have no record") are not acts.
- **Reports carry the person's words**: the latest message, plus the words of an unsent report
  it replaces, each quoted on its own line. Follow-ups to a sent report are updates; a different
  problem is a new report.
- **Numbers a draft states must be the person's** (minutes late, minutes later).
- **Code text is true**: who received a report, "Your words" before the tap, the acknowledged
  update named without cutting a word, each brief line naming the update it counts (all
  updates of the last hour, up to 8), a question never marks a task done.
- **The coordinator's context lists the people and teams they can message.**
- Draft offers are marked in the database (`action_drafts.offer`, migration 0006).

### Replay (63 tuned cases and 23 held-out cases, 3 runs each)

| Measure | Baseline 61ce8ea | Final |
|---|---|---|
| Outcome matches the label, tuned set | 135 of 189 | 163 of 189 |
| Outcome matches the label, held-out set | 55 of 69 (v7) | 64 of 69 |
| False full drafts in answer-only replies, tuned set | 7 of 72 | 3 of 72 |
| False question drafts or buttons, tuned set | 26 full reports | 15 buttons |
| Replies with internal names or template lines | 42 | 0 |
| Replies missing a required fact | 0 | 0 |

Labels: six coordinator questions accept a drafted message as well as an answer, because the
coordinator's context tells the model to offer messaging the right helper. The baseline is
rescored with the same labels (`replay.py --score`). Answers with a first-person act removed:
74 of 213, mostly offers beside a draft or button.

### Gate v8: paired blind comparison

`scripts/ab.py` replayed each of 13 v7 rater chats (one per persona; exact messages and taps,
from the rater logs) through v7 (61ce8ea) and v8 (15de154) code in identical stage worlds.
Haiku raters compared the two transcripts with each version's records, blind, in both orders
(26 raters). Materials: `docs/plans/2026-11-23-gate-v8/`.

| | v7 | v8 |
|---|---|---|
| Preferred | 2 of 26 | 24 of 26 |
| Paired ease / clarity / trust | 3.38 / 3.19 / 2.31 | 3.65 / 3.69 / 3.65 |

Every persona gave the same verdict in both orders: 12 preferred v8, and the round 1 banquet
captain preferred v7, because v8 filed the missing vegetarian meals under the dinner-delay
report. That is fixed (the model may link a report only for the same problem; the question
button never threads), and the replayed chat now files them separately in 3 of 3 runs.

What raters still found in v8 (all behind a tap, or honest gaps):
- A wrong recipient once: "Tell Taylor: cover is Priya Rao" drafted to Priya. The preview names
  the recipient before the tap.
- The bot does not raise open items unprompted: an unacknowledged task or update, or a
  coordinator instruction that asks the helper to act.
- Records show a withdrawn report as "resolved", which raters read as a contradiction of
  "Withdrawn". The records view should say withdrawn.

The v7 complaint classes that are gone in v8 transcripts: "Problem reports also go to your
team" after a question, "Your words, as sent" before the tap, cut-off acknowledgements, the
"After that" line, internal action names, merged quotes that included unrelated messages.

## Open items after gate v8: design (23 November)

### 1. A withdrawn report has its own status
Cause: `incidents.status` allows only open and resolved, so `_withdraw` stores "resolved".
Every reader then reports the wrong fact: the records say "resolved", and the deputy's
"Their reports" context says "answered" for an undone question (deputy.py `_reports`).
Fix: allow `withdrawn` in the check constraint (migration 0007, like 0003 for approvals),
and set it in `_withdraw`. The migration also marks earlier withdrawals: each left a
report_withdrawn audit event whose receipt names the incident. Readers that test
`== "open"` stay correct. The Mini App shows any status that is not open with the green
badge. It works, but green reads as success; a neutral badge is a Mini App change, for the
Mini App session.

### 2. What still waits on the person follows the reply
Cause: the context lists updates with "(not acknowledged yet)", but whether to mention them
is the model's choice, and it answers only what was asked. The heartbeat chases each
unacknowledged update once by ping, but only 5 minutes after it was sent, and never in
answer to a message the person sends.

First design: a code-written line in the reply, raised once, detected by finding the same
line in an earlier assistant turn. Fable's review (23 November) found it unsound:
- Memory keeps 10 turns and cuts replies at 2000 characters, so "once" did not hold.
- The line went back to the model as history, so the model could copy it.
- The instructions were not reliably true. "On it" in words acknowledges the latest update
  first (agent.py `acknowledge`). "Reply ok" acknowledges only the newest update. A task due
  in 40 minutes has no On it button.
- The snapshot is taken before the action, so a message that acknowledges an item would
  still raise it.

Built instead: after a reply to the person's message (not a slash command), with no draft,
the heartbeat runs at once for that person only (`Heartbeat.run(active=...)`):
- An unacknowledged update is chased without the 5-minute wait, because the person is in
  the chat now.
- Tasks keep the heartbeat's window (from 5 minutes before due). PING_GAP still limits
  chasing to once per 10 minutes. The coordinator and the couple are never chased.
The chase is the existing ping, so the existing parts apply:
- its button (Acknowledge, or On it for a task);
- the DeputyPing record, so each item is chased once;
- the answer and silence handling.
It is stamped just after the reply, so it is delivered after it. It runs after the action,
so an "ok" that acknowledges the update chases nothing. Beside a draft, a second button would
compete with the preview's, so the chase waits for the regular heartbeat.

Status labels: an incident's status reads through one function (`views.incident_status`),
used by the deputy and the menu's report list.

### 3. Wrong recipient: no code change
"Tell Taylor: cover is Priya Rao" was drafted to Priya. Both names are in the person's
words, so no grounding check can tell them apart without parsing the sentence. The preview
names the recipient first, and nothing is sent before the tap. A rule for this one sentence
shape would be a patch for a single case.

### Evidence (23 November)
- Tests: an undone question reads "withdrawn" in the deputy's context; migration 0007 marks
  a withdrawal that an earlier release stored as resolved; an unacknowledged update follows
  the reply at once and only once, with its Acknowledge button; no chase beside a draft or
  after an "ok" that acknowledged it; the coordinator is never chased. Suite: 263 passed.
- The 13 v7 rater chats replayed through v8 (254d714) and this build (`scripts/ab.py`; 0
  model fallbacks). The round 1 family liaison's records now say "withdrawn" for the report
  they took back. Of the 7 chats with a chase, 2 now get it right after their reply: the round 2
  banquet captain at 18:27, not 18:30, and the round 2 MC, who asked "What did I miss?", at
  18:29, and then tapped Acknowledge. In the other 5, the update was acknowledged, or a task
  ping a few minutes earlier holds the next chase back for PING_GAP (10 minutes), which is
  kept on purpose: two chases a minute apart is nagging.
- No blind rating: in these fixed scripts the two versions differ in 3 chats by a few
  minutes or one word, so raters would mostly measure model randomness. The prompt did not
  change, so the replay metrics do not move either.

## Live-play round v9 (23 November)

Build 574823d. Four casts played at the same time, each in its own world: round 1 and round 2
with Haiku players (Claude agents), and round 1 and round 2 with GPT-6-Luna players (Codex
`codex exec -m gpt-6-luna`, workspace-write sandbox with network). 26 players, same persona
prompts (`scripts/gate.py`). Live play finds new kinds of failure; it does not pass or fail.
Reports, transcripts and records: scratchpad `live-v9/` (not kept in the repository).

| Cast | Ease | Clarity | Trust |
|---|---|---|---|
| Haiku, 13 players | 3.8 | 3.6 | 2.5 |
| Luna, 13 players | 3.2 | 3.4 | 3.1 |

Luna players read tool output less closely: 6 reports say a reply "did not appear" where the
transcript shows it. Haiku players check the records harder. Both found the same classes.

### Findings, by cause
Code-written text that is not true (each checked in a transcript):
1. `is_confirmation` accepts any message of six words or fewer that asks nothing.
   "help car spoil!!" acknowledged the driver's task, and "Thanks ah" acknowledged the
   registration desk's task.
2. "Arrival recorded. The family liaison and photographer have been told." is fixed text.
   Only family members are announced, and only to family-cleared roles.
3. "Withdrawn … Everyone who was told has been told to ignore it." is fixed text.
4. "1 people get it with an Acknowledge button."
5. A question is called a report: "You already reported: <question>. Confirm only if this is
   a different problem", and "Withdraw your report: <question>".
6. "It's 17:46 now. It's 17:46 now." Code writes the time, and the answer repeats it
   (5 replies).
7. A question's title is the first sentence of the message: "ok thanks" for "ok thanks. i
   stand at entrance b till seating announce then i go where".
8. "Guest seating is for the registration team and ushers." under most of the family
   liaison's replies. The model fills find_guests to check parents' arrival, and code
   refuses a lookup the person never asked for.

Model statements:
9. Stale run sheet after a change. At 18:26, one minute after version 2 moved the
   ceremony, the usher was told "The run sheet still has the ceremony at 18:30 on the Garden
   terrace". The bot's own earlier replies in the history said so, and nothing marks them
   as older than the change.
10. "The context" in 4 replies ("Nothing in the context says how the kitchen is doing"). The
    prompt calls the records CONTEXT, so the model says that word to people.
11. "The run sheet still shows dinner service at 19:00, so tell the kitchen it's not
    approved." The request was pending. The status check needs a report noun beside the
    status word, and "it" has none.

Records tool (`simulate.py records`), which raters read as the truth:
12. "acknowledged by nobody; not yet by nobody".
13. "also shown to: Banquet" on an item under "What reached the coordinator". Two raters read
    it as "only Banquet".
14. `simulate.py transcript` replaces messages older than chat memory (10 turns) with
    "(taps a button)".

Not product faults: same-minute races with the coordinator's change; a persona premise
("Grace Tay" is not in the seed); untapped "Ask the coordinator" buttons (nothing is sent
without a tap, by design).

### Design
- 1: a confirmation is a message whose words all come from a small acknowledgement
  vocabulary (ok, noted, on it, got it, can, will do, roger, received, 👍 …, with particles
  such as lah, leh and liao), with at least one acknowledgement word. "thanks" alone is not
  one.
- 2, 3, 4: the reply names who was told, from the operation's result, as "Report sent"
  already does. The arrival result returns the roles notified (none for a regular guest). The
  withdrawal result returns the teams told to ignore it. The coordinator learns of a
  withdrawal in the next update.
- 5: the code text follows the record's kind: "Take back your question" for a question, and
  the duplicate warning counts only problem reports.
- 6: an answer sentence identical to a line code wrote in the same reply is dropped.
- 7: a question's title skips leading sentences that are confirmations (finding 1's test).
- 8: find_guests is in the plan schema only for roles that may look up seats, like actions.
- 9: in the history, a reply sent before the person's latest run-sheet update (a
  timeline_updated or schedule_info notice) carries a system note: it came before run sheet
  version N at HH:MM, so its times and places may be out of date.
- 10: the prompt calls the context RECORDS.
- 11: a status sentence is also one that applies a status word as a predicate ("is not
  approved", "still pending"), with or without a report noun. "approved times" and
  "coordinator-approved" stay.
- 12, 13, 14: records say "acknowledged by: …; not yet: …" and omit an empty side, and
  "Teams that also see it". The simulator logs each send and tap to the world folder, and
  the transcript uses that log.

### Built, after Fable's review (23 November)
Fable agreed with the causes and changed five fixes:
- 1: a closed set of confirmation phrases (with address words such as "boss"), and the
  model is offered `acknowledge` only for a message that passes it. Demoting the choice
  afterwards lost the report: "help car spoil!!" became no action at all. The intent path
  applies the same test.
- 2 to 4: operations return who was told (`told`), and one renderer writes it, for every
  reply that said it: arrivals (names, or "Nobody else is notified"), withdrawals
  (the coordinator in the next update, and named people told to ignore it), messages
  ("1 person gets it"), and approved changes (a count; "Everyone affected is being told" was
  also fixed text). The drafts before the tap say the same. Decision notices say
  "run-sheet request", not "report".
- 6: the time is compared as a fact: the code line is left out when the answer already
  states the current time.
- 9: each reply in memory keeps its run-sheet version (`conversation_turns.timeline_version`,
  migration 0008). A notice was the wrong marker: the coordinator who makes a change gets none.
- 11: the predicate form covers decision words only (approved, rejected, declined, pending,
  withdrawn, answered, unsent). "Registration is open" and "recorded as onsite" are not
  statuses.
- 8: find_guests guidance moved from the shared prompt into the RECORDS of roles that may
  look up seats; other roles read that they cannot.
Known gap (not fixed): "(moved from 18:30)" puts the old time in the grounding, so the claim
check alone cannot catch a stale time; the history note addresses the cause.

### Evidence for the v9 fixes (23 November)
- Replay, 3 runs per case, against 574823d's v8 numbers:

  | Measure | v8 | v9 |
  |---|---|---|
  | Outcome matches the label, tuned set | 163 of 189 | 169 of 189 |
  | Outcome matches the label, held-out set | 64 of 69 | 65 of 69 |
  | False full drafts, tuned set | 3 of 72 | 2 of 72 |
  | Internal names or template lines | 0 | 0 |
  | Missing a required fact | 0 | 0 |

- The first v9 replay found a new failure: without `acknowledge` to choose, the model drafted
  "Mark your task done" for "ok got it 👍 … the ceremony is inside now right" (6 of 6 runs of
  two cases). Two causes, both fixed: `asks()` missed "where's" and question tags ("… now
  right", "… anot"), and a task-done draft did not need the person to say anything was done
  (`says_done`, the same rule as names for arrivals). After the fix: 0 of 6.
- Tests: 274 passed. New: `tests/test_told.py`, `tests/test_deputy_live_play_v9.py`, the
  confirmation cases in `tests/test_claims.py`, and the simulator transcript log.

## Live-play round v10 (23 November)

Build 8c81ed1, same method as v9: four casts at once (rounds 1 and 2 with 13 Haiku players and
13 GPT-6-Luna players).

| Cast | Ease | Clarity | Trust |
|---|---|---|---|
| Haiku, 13 players (v9) | 3.8 | 3.6 | 2.5 |
| Haiku, 13 players (v10) | 3.6 | 3.5 | 2.6 |
| Luna, 13 players (v9) | 3.2 | 3.4 | 3.1 |
| Luna, 13 players (v10) | 3.6 | 3.3 | 3.1 |

Scores move about 0.3 between rounds with the same code, so they find failures; they do not
measure the fixes. Classes fixed in v9 did not come back: no task was acknowledged by a
non-confirmation, no "1 people", no repeated time, no "the context", no seat-refusal line under
unrelated replies, and code text named who was told.

### Findings, by cause (each checked in a transcript)
1. Stale run-sheet times passed the claim check. After version 2 moved dinner to 19:10, the
   coordinator was told "The run sheet I have shows dinner service at 19:00 … moved from
   19:00 — I don't have a version 2", and an usher "still lists the garden ceremony at 18:30".
   The context was right ("19:10 Dinner service (moved from 19:00)"), but the old time in
   that parenthesis, and in update notices ("19:00 → 19:10"), supported the sentence.
2. Half a sentence: "I don't have a seat listed for" above a lookup line. The model's
   sentence crossed a line break; the check split it there and removed only the second half.
3. "not yet lol going there now", in answer to a check-in, drafted "Jamie Lim is running
   late". Nothing in the person's words said late.
4. A question titled "Ok, saw the coordinator's message": the title skips only leading
   confirmations, and that sentence is not one.
5. A new draft silently replaced an unsent one: the coordinator's reply to Taylor was never
   sent, and nothing said so.
6. "tell Chris: … tell Taylor: …" made one draft; the answer then said the second part was
   "covered", which was false.
7. "Can undo the arrival for Grace Tan?" became a problem report, not a withdrawal: the
   prompt describes taking back "a report" only.
8. A helper's delay report reads as a schedule change: "Ask the coordinator to approve this
   run-sheet change:" above every later item ("I never say change the whole schedule";
   both rounds).

Model statements left as residuals (no general check exists): hearsay restated as fact ("Mei
Lee is here, just not at the foyer"), "Nothing in the records mentions a car" beside an urgent
car report, "Grace Tay is noted as arrived". Timing artefacts: a reply before a change in the
same minute, read against the final records.

### Design
- 1: in `Support`, a time that the records give only as an item's earlier time ("moved from
  19:00", "19:00 → 19:10") supports a sentence only when that sentence also states the
  item's current time. "Dinner moved from 19:00 to 19:10" passes; "dinner is still 19:00"
  is removed. (Built and tested.)
- 2: when the check removes a piece, the kept piece just before it goes too if it has no end
  punctuation. (Built.)
- 3: a lateness report needs the person to say they are late (a closed set: late, delay,
  stuck, jam, traffic, behind, lambat, "won't make it", minutes away), as a task-done draft
  needs "done".
- 4: a question's title is the first sentence that asks; else the first that is not a
  confirmation.
- 5: when a new draft replaces an unsent one, code adds "This replaces your unsent draft: …".
- 6: the prompt says: one action per message; when they ask for several, act on the first
  and say in the answer which one is still to do.
- 7: the prompt says withdraw_last also undoes an arrival they recorded.
- 8: a helper's plain delay reads "Report to the coordinator: <item> starts N minutes late.
  If they approve, the run sheet becomes:", with the button "Send to coordinator".

### Built, after Fable's review (v10)
- 1: as designed, plus: an earlier time is also supported as the past ("was at 19:00",
  "moved from 19:00"); after a second move, the older notice's new time is old too; a
  bracket in a title no longer hides "(moved from …)". Not covered: an old place ("was
  Garden terrace") is still a current place name, so it stays supported.
- 2: instead of dropping pieces, a line with no end punctuation is joined to the next line
  before the check, unless the next line is a list item.
- 3: `says_late` (late, delay, stuck, jam, traffic, lambat, ETA, "won't make it").
- 4: the title is the first sentence that asks.
- 5: `Operations.draft` returns the replaced unsent draft's first line, and the reply says
  "This replaces your unsent draft: …", except when a report carries the earlier report's words.
- 6: Fable: the prompt already says one action per message, and prompt-only rules failed 15% of
  the time (gate v6). Code instead names anyone the message names whom the draft does not
  reach: "This message is not to Taylor Ng. Send me what Taylor Ng should get next."
- 7: the action and field descriptions say withdraw_last also undoes an arrival.
- 8: keyed on the role, not the command: a helper's change reads "Report to the coordinator:
  Dinner service starts 20 minutes late. If they approve, the run sheet becomes: …", and its
  intro is "Check this before it goes to the coordinator."
- Found while building: the model answers before a guest lookup runs, so "Lucas Tan isn't on
  the guest list I can see" sat above "Lucas Tan: Table 3". The lookup line states seat facts;
  answer sentences that name a looked-up guest are removed, and no question button is offered
  under a lookup.
- Found by the replay: "what is Grace Tan status now? arrived or not" drafted her arrival
  (2 of 3 runs). A question never records an arrival, as it never marks a task done.

### Evidence for the v10 fixes (23 November)
| Measure | v8 | v9 | v10 |
|---|---|---|---|
| Outcome matches the label, tuned set | 163 of 189 | 169 of 189 | 165 of 189 |
| Outcome matches the label, held-out set | 64 of 69 | 65 of 69 | 65 of 69 |
| False full drafts, tuned set | 3 of 72 | 2 of 72 | 2 of 72 |
| Internal names or template lines | 0 | 0 | 0 |
| Missing a required fact | 0 | 0 | 0 |

The tuned score moves about ±4 between runs of the same code (162 to 169 in v9 runs). Two
intermediate v10 replays found regressions caused by the v9 status predicate, both fixed:
- "be approved" matched advice ("needs to be approved by the coordinator"). The couple's
  whole answer was removed and replaced by "You have no reports on record yet".
- "still pending" matched a task, which can truly be pending. The usher lost its due time
  (2 missing facts).
Now a status word counts only when it is said of something ("was sent", "request approved"),
the predicate form excludes "be" and "pending", and the "no reports" line appears only when a
removed sentence named a report. Tests: 283 passed.

## Live-play round v11 (23 November)

Build b692516, same method as v10: four casts at once (rounds 1 and 2 with 13 Haiku players and
13 GPT-6-Luna players).

| Cast | Ease | Clarity | Trust |
|---|---|---|---|
| Haiku, 13 players (v10) | 3.6 | 3.5 | 2.6 |
| Haiku, 13 players (v11) | 3.5 | 3.5 | 2.8 |
| Luna, 13 players (v10) | 3.6 | 3.3 | 3.1 |
| Luna, 13 players (v11) | 3.0 | 3.0 | 2.6 |

Some Luna scores are player artefacts: one player typed the world path wrongly ("no such table:
weddings"), and several reported "no visible reply" where the transcript shows a reply. The v10
fixes held: no stale "still 19:00" answer after a change, no half sentence, no lateness report
without "late", replaced drafts and left-out people were named.

### Findings, by cause (each checked in a transcript)
1. A code veto kept the answer written for the vetoed action, and the v10 arrival guard (any
   question mark vetoes an arrival) was too broad. "Grace Tan just arrived at the registration
   desk, can you log it and confirm?" drafted nothing and said "I've noted Grace Tan's arrival"
   (both registration players and one family liaison, in both casts); the undo then said
   "Nothing to withdraw".
2. The self-act check was a closed list of outbound verbs: "I've noted …" and "I've set that
   change for you to confirm" (no change existed) passed. Beside a draft, "Noted, Robert Tan is
   marked as arrived." passed (not first person).
3. Messages nobody asked for. "Who is late and what is the current car situation?" drafted a
   message to Chris and Asha that "answers Asha's question 'Has my Ah Ma Tan arrived yet?' and
   closes it". A helper's "did the coordinator get my message? Did you tell them already?" became
   a note quoting itself.
4. A run-sheet change sent as a message only: "garden ceremony move into Cedar Ballroom and start
   6:40 pm. Please announce this to everyone now." The run sheet, tasks and reminders kept 18:30
   at the Garden terrace; four raters flagged the contradiction.
5. A helper's +20 request, made on version 1, could never be approved after the coordinator's
   rain change: "The timeline changed. Regenerate this proposal before approval". The helper's
   chat still listed it as pending.
6. Code text: "10 people are told, with an Acknowledge button" (the couple's copy has no button);
   On it said "Thanks, marked as acknowledged" without naming the task (three raters read it as
   acknowledging the coordinator's message); "This replaces your unsent draft: Message to
   everyone:" (a heading); "would exceed its hard latest-end constraint"; a not-found guest
   lookup with no next step; a blocked helper delay with no way to send it.

Residuals (no general check): an unsent report keeps collecting later messages when the model
drafts it again with a new title ("Okay send that problem report now please" was added to the
MC's late report); "nothing is scheduled there now" for the garden terrace, which holds the
portrait alcove; the model's own word "incident".

### Built, after Fable's review (v11)
Fable: causes 1 to 3 share two roots. The answer is written for a state that code then
changes, and code tested the message's form ("does it ask?") instead of what the action rests on.
- 1: one helper, `stated(vocabulary, text)`: a word counts when it is not questioned right after
  it ("arrived or not", "done?") and not denied or put in the future by the three words before it
  ("haven't arrive", "will reach"); a request to record it states it ("mark him arrived pls").
  Arrival, done and late all use it, over the person's recent messages. When code vetoes an
  action, the model plans again without it and writes the answer for what is true (one more call
  on a rare path); the act check stays as the backstop.
- 2: any first-person completed act counts ("I've/I have/I just/I already" + any participle),
  with only an adverb between, except reading verbs (checked, found, seen, read …). Beside a
  draft, a passive done-claim ("is marked as arrived") counts only when it names the draft's own
  object, because "43 of 180 guests are recorded as onsite" is a true record.
- 3: Fable rejected a list of directive words (it breaks "Can Chris's team hold the food 10
  min?" and passes "What should I tell Chris?"). A message goes only to people the coordinator
  named (a person by first or full name, a team by name, everyone by a word for everyone), or to
  people from the records when the person asked for something to be sent ("nudge the 8 who never
  acked"); otherwise the model plans again with no action. A message closes a question only when the
  coordinator's words name the asker or share words with the question. A note made only of
  questions goes by the question button.
- 4: when a coordinator's message gives a run-sheet item a time that is in their message but not
  in the run sheet, the model plans again with only the run-sheet change offered, and the reply
  says "This changes the run sheet, so tasks and reminders follow it. To send a message only, say
  so." A message with no new time stays a message. Not covered: a place-only move.
- 5: Fable: closing every pending request on any version change would drop a kitchen delay when an
  unrelated item moves. A request is computed again on the current run sheet; it is approvable
  when it moves the same items from the same times to the same times, and its blockers are
  computed again. After any change is applied, the requests it no longer fits are closed, their
  requesters are told ("Check the new times, and tell me again if it still applies"), and the
  coordinator's reply names them.
- 6: two counts from the announcement ("9 people are told, with an Acknowledge button. The couple
  see the new times too."); On it names the task; the replaced line includes the line after a
  heading; blockers in plain words ("Couple's toast would run past its latest allowed end time");
  a not-found lookup says "Check the spelling, or ask for the name on the invitation"; a helper's
  blocked change becomes a problem report draft with their words.

### Evidence for the v11 fixes (23 November)
| Measure | v9 | v10 | v11 |
|---|---|---|---|
| Outcome matches the label, tuned set | 169 of 189 | 165 of 189 | 162 of 189 |
| Outcome matches the label, held-out set | 65 of 69 | 65 of 69 | 66 of 69 |
| False full drafts, tuned set | 2 of 72 | 2 of 72 | 3 of 72 |
| False full drafts, held-out set | | 1 of 24 | 0 of 24 |
| Internal names or template lines | 0 | 0 | 0 |
| Missing a required fact | 0 | 0 | 0 |

The tuned score moves about ±4 between runs of the same code (158 to 169 across v9 and v10
runs). The three false full drafts are the model's first choice for "is the ceremony still
outdoors? its raining. where do I send arriving guests" (a note to the coordinator), as in v10.
Three intermediate v11 replays found problems, all fixed:
- The first two runs had 24 and 68 connection timeouts: the model API's TLS handshake took 1.2 to
  1.9 seconds from this machine, against a 2-second connect limit. Later runs used
  a replay wrapper with a 10-second connect limit; the product setting is unchanged.
- A second plan offered every other action chose one anyway: "kitchen ok anot? dinner 7pm still
  on?" became a run-sheet change. Then, offered the answer and the question buttons, "ok got it,
  the ceremony is inside now right" became a report (v11c) or a question button in every run
  (v11d). The second plan now offers no action.
- "Ok nudge the 8 who never acked" was refused, because the recipients came from the records. A
  request to send now allows them.
Tests: 299 passed.

### Paired replay, v10 against v11 (24 November)
The v11 scores above came from runs at different times, so they could not show whether v11 was
worse than v10. The v10 (b692516) and v11 (a5b0f07) code ran the same cases at the same time:
2 rounds of 3 runs each, 6 runs per version. Each version used the same model and network.

| Measure (sum of 6 runs) | v10 | v11 |
|---|---|---|
| Outcome matches the label, tuned set | 323 of 378 | 325 of 378 |
| Outcome matches the label, held-out set | 128 of 138 | 131 of 138 |
| False full drafts, tuned and held-out | 10 | 4 |
| False question buttons, tuned and held-out | 51 | 54 |
| Internal names, template lines, missing facts | 0 | 0 |

v11 is not worse. It makes fewer false full drafts and is level on the rest. The question button
beside a complete answer is the largest remaining fault, unchanged in both versions: 47 of the 53
v11 tuned misses in the two rounds.

## The question button: the person decides (24 November)

### Cause (Fable's review)
`ask_coordinator` was the only action with no code-checked precondition. "The records do not answer
this" is a judgment about what the person needs, which the model cannot know, and the button cost
it nothing, so it used the button as a hedge. Two record faults fed the hedge: a task instruction
that a run-sheet change contradicts ("direct guests to the garden terrace"), and a person who
already had an open item with the coordinator on the same subject.

### First attempt: the action removed
Fable's design (d): every helper reply gets an Ask the coordinator button, and the model loses the
action. False question buttons went to 0, but the hedge moved to notes and problem reports, as
Fable had warned: 41 false full drafts in 6 runs, against 0 for v11, and the tuned set fell to 147
and 146 of 189. Most notes quoted the person's own question ("MC needs groom's family name
pronunciation").

### Built, after Fable's second review
- **The ask button.** Every helper reply without a draft has an Ask the coordinator button (`nav:ask`,
  `/ask`). Its tap offers the person's latest message as a question, with the same title rules and
  per-person limit as before; a second tap sends it. Beside a draft there is no ask button, and the
  coordinator gets none.
- **The question class has no effect.** The model may still class a message as `ask_coordinator`.
  Its description says that the person already has the button and nothing is drafted. Code draws
  nothing for it and logs it. The class gives the model's wish to escalate a harmless target: it
  chose it 66 to 68 times in 189 replies per round.
- **The inline offer only when the answer lost content.** As before: the person asked something,
  nothing else was done, and the claim check removed every sentence. Also when the model classed
  the message for the coordinator and wrote no answer (added after the replay below; a unit test
  covers it).
- **A note from a message that asks has no draft.** A note carries information; a question goes by
  the ask button. Before, only a note made entirely of questions was stopped.
- **A problem about an item with a waiting request.** If the report's title names a run-sheet item
  for which the person has a pending request, code drafts nothing and states the request's status.
  Urgent reports always go through.
- **A follow-up that only asks.** An update to an open report whose every sentence asks or confirms
  makes no update; code states the report's status.
- **Instructions that name a moved-from place.** A task-instruction sentence that names a place an
  applied run-sheet change moved an activity away from is left out of the model's records. Marked
  as outdated instead, it was still repeated ("your task note still says garden terrace").
- **Chat memory order.** Turns are ordered by time and IDs are random, so under a clock that does
  not move (tests, replay worlds) turns of the same instant came back in random order. Each saved
  turn now follows the person's last one.
- **Replay scoring.** A reply with no draft and the ask button under it also meets a "question"
  label. mc-cover also accepts `late`: the person says they cannot arrive in time.

### Evidence (paired replay, 2 rounds of 3 runs, run at the same time)
| Measure (sum of 6 runs) | v11 | This build |
|---|---|---|
| Outcome matches the label, tuned set | 328 of 378 | 372 of 378 |
| Outcome matches the label, held-out set | 131 of 138 | 138 of 138 |
| Answer-only cases matched, tuned set | 97 of 144 | 138 of 144 |
| Cases with "question" in the label matched, tuned set | 89 of 90 | 90 of 90 |
| False question buttons | 54 | 0 |
| False full drafts | 0 | 6 |
| Internal names or template lines | 0 | 0 |
| Missing a required fact | 3 | 1 |

The gain is in the answer-only cases; the question cases were matched by both versions, so the new
scoring rule does not explain it. The 6 false full drafts are problem reports in two cases:
"who i should call ah?? … boss not answering" (a report that the coordinator cannot be reached)
and "is the ceremony still outdoors? its raining" (a report about rain). Tests: 311 passed.

Not yet measured: whether people tap the ask button when they need it. Only live play shows that.

## Live-play round v12 (24 November)

Build 4de06af, same method as v11: four casts at once (rounds 1 and 2, 13 Haiku players and 13
GPT-6-Luna players). Reports, transcripts and records: scratchpad `live-v12/` (not kept in the
repository); `live-v12/verified.md` lists each finding with its transcript lines.

| Cast | Ease | Clarity | Trust |
|---|---|---|---|
| Haiku, 13 players (v11) | 3.5 | 3.5 | 2.8 |
| Haiku, 13 players (v12) | 3.8 | 3.4 | 2.8 |
| Luna, 13 players (v11) | 3.0 | 3.0 | 2.6 |
| Luna, 13 players (v12) | 2.8 | 3.1 | 3.0 |

Many Luna reports again say "no visible reply" or "records returned no output" where the
transcript shows both; Luna scores move with those artefacts.

### The ask button in use
12 replies in 9 chats sent the person to the coordinator. 4 players tapped Ask the coordinator;
2 questions arrived, both after two taps. One MC read the first tap as a failure, answered a notice
in between, and later retyped the request, which became a problem report. Another tapped the
button under the reply to "What did I miss?" and was offered that message, not the request they
typed next.

### Findings, by cause (each checked in a transcript)
1. The ask button needed two taps and acted on the latest message, not the reply it was under.
2. An action that code could not draft kept the answer written for it. "Grace Tay arrived, please
   log her" (Grace Tay is on no list): "Logging Grace Tay's arrival now." and "Grace Tay is
   recorded as arrived." above "I could not tell which guest or family member you mean. Send me
   their full name." (both registration players). The v11 re-plan ran only for a veto before
   acting. Name resolution had three wordings, and the arrival one merged "no match" with
   "several".
3. The coordinator's records gave an open report as a title and "Review this open incident in
   LoveOnCue". "What happened with the car" got "no details on the car's condition" (the driver
   wrote that it cannot move); Taylor's own lateness report was called "a note from the brief";
   "any open approvals or reports I must handle?" got only the coordinator's own change.
4. With no draft, any sentence that said "tap" replaced the whole answer with "I didn't make a
   draft for that": "got need to do anything else?" got only that line.
5. A request's status came from two channels (code's guard and the model's status_of) and was
   printed twice.
6. A name only asked about ("is Ryan on it now or not") was named as left out of a draft; and a
   message draft took its recipient from an earlier message.
7. The model repeated its earlier reply over newer records: "None of the nine have acknowledged"
   word for word, when the records said 2 of 9. The records came before the chat, so the stale
   reply was the newest text on the subject.

Not faults: "still 18:30 at the Garden terrace" and "0 of 9" were true when sent; "speeches
first" was the coordinator's own word; "Your draft is still unsent" was true.

### Built, after Fable's review (v12)
- 1: each helper reply without a draft carries its own one-tap offer (an `ActionDraft` with
  offer "button", kept as long as chat memory), so Ask the coordinator sends the message that
  reply answered, at once, with Undo. The offer never replaces a draft or is replaced by one. A
  second tap sends nothing new ("Already sent"). Typed `/ask` sends the latest message. The old
  two-step path, the inline offer and the separate `nav:ask` row are gone (`nav:ask` stays for
  buttons already in chats). When the model classes a message as the coordinator's and the
  answer sends them there, code adds "Tap Ask the coordinator to send them your message."
- 2: one re-plan path (`_answer_only`) for a veto and for an action whose result is a
  clarification; for the second, the model is told what happened and code's line follows. One
  wording for a name that matches nobody or several (`agent.unmatched_name`): "Nothing was
  recorded. Grace Tay: not on the guest list. Check the spelling. If they are not on the list:
  Ask …".
- 3: the coordinator's records list what waits for them: pending run-sheet requests (A), open
  reports (P) and questions (Q), each with who, when, and their quoted words; code prints an item
  when the model names its reference. Those items leave the brief lines; the coordinator's own
  decided change is no longer one of "their reports".
- 4: only a sentence that points at a button the reply does not show is removed.
- 5: code's guards return a reference, and every status line goes through `_status_lines`; the
  reply never prints a line twice.
- 6: a message's recipient must be named in this message (or the message asks to send); a name
  counts as left out only in a sentence that does not ask.
- 7: the RECORDS come after the chat ("RECORDS as of HH:MM, newer than every reply above"), and
  every earlier reply carries its time; this replaces the run-sheet-version note.

### Evidence (paired replay, 2 rounds of 3 runs, run at the same time)
| Measure (sum of 6 runs) | 4de06af | This build |
|---|---|---|
| Outcome matches the label, tuned set | 369 of 378 | 374 of 378 |
| Outcome matches the label, held-out set | 138 of 138 | 138 of 138 |
| False full drafts | 4 | 4 |
| False question buttons | 0 | 0 |

No regression. All 4 false drafts in this build are driver-who-call (a report made from "boss not
answering"). The replay does not exercise most v12 causes, which are reply texts; the tests in
`tests/test_deputy_live_play_v12.py` and `tests/test_ask_button.py` cover them. Not measured: a
count of verbatim repeated replies (Fable suggested logging it in the replay).

## Live-play round v13 (24 November)

Build a71aef5, same method. Reports, transcripts and records: scratchpad `live-v13/`;
`live-v13/verified.md` lists each finding with its transcript lines.

| Cast | Ease | Clarity | Trust |
|---|---|---|---|
| Haiku, 13 players (v12) | 3.8 | 3.4 | 2.8 |
| Haiku, 13 players (v13) | 3.7 | 3.5 | 2.7 |
| Luna, 13 players (v12) | 2.8 | 3.1 | 3.0 |
| Luna, 13 players (v13) | 3.7 | 3.8 | 3.5 |

Several Haiku trust scores of 2 rest on statements that were true when made (an answer before
the coordinator's change or approval arrived), and on the records view, which lists only what
reached the coordinator.

### The ask button in use
14 taps by 11 players made 14 questions, one tap each; the coordinator answered 10 during play
(v12: 4 taps, 2 questions). Two players could not tell which message a tap had sent.

### Findings, by cause (each checked in a transcript)
1. "Question sent" did not say what was sent; one usher sent "toilet where ah" meaning to ask about
   "Mr Lee".
2. The fixed "I didn't make a draft for that" line answered "sorry that was a guest lol".
3. "You have no reports on record yet." stood under four unrelated answers. Cause (Fable):
   "arrival" in REPORT_NOUN made task and attendance facts ("Your task to confirm the parents'
   arrival is pending") into report status; they were removed with no line in their place, and the
   fallback added that line. A status sentence was removed in 26 of 176 answers.
4. An arrival draft for someone already checked in ("Robert Tan already here, good good"); and a
   tap after another desk's check-in still said "Arrival recorded". The confirmation did not name
   who was recorded.
5. "The dinner delay and the missing veg meals are both with the coordinator now" above an unsent
   report. The act check's draft objects match the draft title as a whole string only.
6. "sorry that was a guest lol" drafted "Take back your note": withdraw_last had no check on the
   person's words.

### Built, after Fable's review (v13)
- Every removed sentence is logged with its reason (`wedding_ops.deputy.removed`, DEBUG; the
  simulator and the replay turn it on).
- 3: "arrival" leaves REPORT_NOUN (beside an arrival draft, PASSIVE_DONE still catches "is
  recorded").
- 4: an arrival for people already checked in drafts nothing and says so; a mix drafts only the
  others. The arrival result names who changed: "Arrival recorded: Grace Tan." then "Told: Priya
  Rao and Sam Koh."; a late tap says "Already checked in. Nothing changed".
- 1: "Question sent: “<their words>”", also for "Added to your question" and "Already sent".
- 2: the fixed line is gone; an empty answer gets `_compose`'s "I haven't done anything with that".
- 5: beside a helper's unsent draft (which goes to the coordinator), a statement that names the
  coordinator is removed; the draft text says who gets what. Questions stay. Not a list of
  delivery words, which never closes.
- 6: withdraw_last rests on the person's words, like every other write: a word that takes
  something back, stated (`says_retracted`), a report noun, or a word shared with one of their
  open reports or pending requests (`about_own_report`). Without the last, the paired replay lost
  "chef say only 10 minutes now lah, not 20" (2 of 6 runs drafted nothing); with it, 6 of 6.

### Evidence (paired replay, 2 rounds of 3 runs, run at the same time)
| Measure (sum of 6 runs) | a71aef5 | This build |
|---|---|---|
| Outcome matches the label, tuned set | 374 of 378 | 372 of 378 |
| Outcome matches the label, held-out set | 138 of 138 | 138 of 138 |
| False full drafts | 1 | 2 |
| Missing a required fact | 2 | 0 |

Within run-to-run noise. Two of this build's misses were banquet-correction, fixed after the run
by `about_own_report` (that case alone, 6 runs: 6 of 6). The rest are driver-anyone and
driver-who-call, known residuals. Re-plans after a veto: 24 send_message and 20 complete_task in
the tuned set's 378 replies.

Not built: Fable noted that 30 of 176 turns planned twice after a veto (17 send_message, 12
complete_task); stating each veto rule in ACTION_HELP would save the second call. And the ask
button could reply to the very message it sends, if the offer stored its Telegram message id.

## Checks
- Unit: extractor (each token type, Singlish time forms); `unsupported` with
  cited and uncited lines; quoted spans do not ground; self-acts with and without
  drafts and lookups; details from cited `U` turns; repair called once; removal
  and fallbacks; K7.
- Regression: all existing tests.
- Gate: same 13 personas, 2 runs per persona (26 raters), against v5. Primary
  evidence: fact removals, status sentences, first-person acts, fallbacks and
  coordinator pushes (`simulate.py metrics`). Persona trust is secondary, because
  it moves about 0.5 between runs with no code change.

Success: fact removals in under 5% of answers; first-person acts well below v5's 9
in 71; trust ≥ 3.5 with no fall in ease or clarity.

## Resume point
Read this file, then `git log` on the branch. Done: Fable's build order through gate v8, the
gate v8 open items, live-play rounds v9 to v13 (26 players each, Haiku and GPT-6-Luna)
and their fixes, and the one-tap ask button (the person, not the model, decides when to ask the
coordinator). Tools: `scripts/replay.py` (tuned and held-out cases), `scripts/ab.py` with
`WEDDING_OPS_SRC` (paired comparison), `scripts/gate.py` and
`simulate.py records|transcript|realtime` (live play; Luna players run as `codex exec -m
gpt-6-luna -s workspace-write -c sandbox_workspace_write.network_access=true --add-dir <world>`).
On a slow network the replay needs a longer connect limit than the product's 2 seconds.
Residual model behaviours with no general check: hearsay restated as fact, a missed record, a
problem report made from a question ("its raining, where do I send guests"), an unsent report that collects later
messages when the model drafts it again under a new title, and a place-only move sent as a
message (only a new time redirects to a run-sheet change), a chef's correction that makes a second
run-sheet request instead of revising the pending one, and miscounts in the model's own words.
One tap gets questions through (v13: 14 taps, 14 questions). Next: decide on a staging deploy (message the Mini App session first, and tell it about the neutral badge for
"withdrawn"). Staging runs release 406bf7c; migrations 0007 and 0008 are new
since then.
