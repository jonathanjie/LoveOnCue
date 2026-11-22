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
Read this file, then `git log` on the branch. Built: K1–K5 (f1ac2bf) and the gate
v6 fixes (7858501), with tests in `tests/test_claims.py`. Not yet measured: the
gate v6 fixes. Next: gate v7 with the same 26 raters (prompts in the session
scratchpad `gate-v6/`; worlds by `simulate.py init --deputy`, `advance 40` for
round 2, a clock loop of `advance 1` every 15 s). Then decide on a repair call only
if fact removals exceed 5%.
