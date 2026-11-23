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
gate v8 open items, live-play round v9 (26 players, Haiku and GPT-6-Luna) and its fixes
(sections "Live-play round v9" and "Built, after Fable's review"). Tools: `scripts/replay.py`
(tuned and held-out cases), `scripts/ab.py` with `WEDDING_OPS_SRC` (paired comparison),
`scripts/gate.py` and `simulate.py records|transcript|realtime` (live play; Luna players run as
`codex exec -m gpt-6-luna -s workspace-write -c sandbox_workspace_write.network_access=true
--add-dir <world>`). Next: a second live-play round on this build to look for new kinds of
failure; then decide on a staging deploy (message the Mini App session first, and tell it about
the neutral badge for "withdrawn"). Staging runs release 406bf7c; migrations 0007 and 0008 are
new since then.
