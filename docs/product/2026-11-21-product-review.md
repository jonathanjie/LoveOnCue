# LoveOnCue product review — 21 November 2026

Product Owner and PM review after the Telegram recovery, the staging tester work,
an independent advisor review (Fable model), and two rounds of simulated users
(Haiku model, 13 agent runs). Resume point: section 6.

## 1. Verdict

The foundation is right. The product around it is not yet usable by the people
it is for, and there is no customer evidence for the direction.

- **Right:** the database and role policy decide; the model only parses
  ([ADR 0001](../adr/0001-authority-before-agent.md)). Schedule changes need a
  human coordinator. In both simulation rounds, no user could change the
  schedule without approval, read a phone number, or leak data through a prompt
  injection. That trust model is the main asset.
- **Not usable yet:** simulated users scored ease of use 1.9/5 and clarity
  1.7/5. Most plain-language messages fell through to a generic command menu.
  Core wedding-day events had no path at all (section 3).
- **No evidence:** nobody has interviewed a coordinator or watched a real event
  (`ROADMAP.md`, `RESEARCH.md`). Engineering effort so far is far ahead of
  product evidence.

## 2. Advisor review (Fable), summarised

- **Buyer:** a professional coordinator business with repeat events. Couples buy
  once; venues are a later channel.
- **Strongest job:** "When the plan changes during the event, tell only the
  affected people and show me who acknowledged it." Seat lookup and venue
  answers are things competitors already have (EventSync, Coordon, Timeline Genius, Aisle Planner).
- **Over-built for the stage:** 12 roles, 11 web screens, 24 tables, photo review,
  heavy governance documents, and test tooling, all before a single user.
- **Under-built:** coordinator actions on a phone, run-sheet import, a printable
  run sheet or offline fallback, reassignment, language support, and an open
  question about Telegram versus WhatsApp in Singapore.
- **Adoption risks:** helper enrolment friction, coordinator approval load,
  splitting attention between two chat channels, venue connectivity, one
  wrong-person action in front of a client, personal-data handling, and
  founder time.
- **Recommendation:** two weeks without new features. Interview 5 to 8
  coordinators, then run a 60-minute tabletop with one coordinator. Stop rule:
  park the product if fewer than 2 coordinators agree to a tabletop.

I agree with the buyer, the job, and the stop rule. I partly disagree on
"no features". The simulations show that a tabletop today would fail on basics
in the first ten minutes. That would test the gaps, not the idea. A short,
strictly limited fix sprint should run alongside the interviews (section 5).

## 3. Simulation findings (verified)

**Setup.** `scripts/simulate.py` runs the real Telegram ingress, assistant,
worker and approval code on the fictional seed wedding (180 guests, 11 roles).
Free-form parsing used DeepSeek V4.1 Flash, as on staging. Each Haiku agent
played one person and did not see the source code.

- **Round 1** was a normal pre-ceremony hour, with 6 users.
- **Round 2** added confounding events, with 7 users: rain moving the ceremony
  indoors, a late MC, conflicting and duplicate kitchen reports, a wrong-person
  arrival, a guest's prompt injection, a couple trying to change the schedule,
  and a flat tyre on the bridal car.

I checked each claim below against the database or the source. Harness defects
are listed separately at the end and are not counted as product findings.

| # | Finding | Severity | Evidence |
|---|---|---|---|
| 1 | **No incident report from chat.** A flat tyre on the bridal car, sent five times, and missing vegetarian meals were never recorded. The bot said "contact the on-site team" but gave no contact. | Critical | The intent kinds in `agent.py` (`SYSTEM`) have no general incident type, so only a missing family member can be reported. |
| 2 | **No correction or withdrawal.** A wrong arrival stayed recorded (Grace Tan, not Grace Tay). "Locate Mei Lee" stayed open after she was found. Revised delays created new proposals instead of replacing old ones. | Critical | Three dinner proposals (+20, +20, +10) were all pending together. |
| 3 | **The coordinator cannot announce a change.** The rain move had no path: there is no broadcast in the bot or web app, and no location-change proposal. The timeline notice said only "Garden ceremony 18:40". | Critical | The `broadcast` command exists in `schemas.py` but has no UI. |
| 4 | **Approvals lack context, and the coordinator rejected a real delay.** A `/delay` report stores the raw text "/delay dinner 15" as its reason, with no requester. The coordinator rejected the kitchen's real delay because no reason was shown. Free-form reports do keep the helper's words. | High | Approval reasons in the round 1 database. |
| 5 | **Common questions get the help menu.** Examples: "when is dinner?", "speech order?", "was my delay approved?", "how many guests arrived?", "who hasn't confirmed?", "I'm 25 minutes late", "can someone cover?". | High | These are not intent kinds; the parser returns `unknown`. |
| 6 | **Helpers cannot acknowledge in Telegram.** Notices say "acknowledge this message", but acknowledgement exists only in the web app. This breaks the advisor's "who acknowledged" job. | High | `acknowledge_notification` is in `web/src/app.ts` only. |
| 7 | **Wording misleads people.** "Recorded family status" reads like a write but is a lookup; three users thought it saved data. The liaison's own report says "Ask the family liaison to…". The coordinator is told to "check with the coordinator". The bride is told "before taking on another role". | Medium | Strings in `agent.py`. |
| 8 | **Times are shown in UTC ISO format.** For example "due 2026-11-14T10:50:00Z" instead of "6:50 pm". | Medium | `/now` replies. |
| 9 | **Guest and location lookup is too literal.** "auntie sarah" and "Mr Lee" fail. Eight "Lee" results come with no way to choose one. "Ballroom Entrance B", named in the usher's own task, is not a known location. | Medium | `Queries.guests`; location seed. |

**What held up under stress:** the prompt injection returned no data, phone
numbers were withheld, the couple could not change the schedule, the bot never
made up an answer, delay, confirm, approve and targeted notices worked end to
end, and a hard constraint (the couple's toast latest end) correctly blocked an
unsafe dinner shift.

**Scores (mean of agent self-scores, 1 to 5):**

| Round | Ease | Clarity | Trust |
|---|---|---|---|
| Normal day (6 users) | 2.0 | 1.7 | 2.3 |
| Confounders (7 users) | 1.9 | 1.7 | 2.1 |

**Harness defects found and fixed (not product findings):**
- The desk view showed the planned time instead of the approved time, which misled the simulated coordinator.
- The `resolve` command used the wrong field name.
- The desk view did not show approval blockers.
- My brief used "|" between commands, and some agents treated it as a shell pipe.

## 4. Did we go in the right direction?

- **Yes:** the authority model, typed commands, the audit trail, and the testable
  staging loop (Telethon tester, role switching, simulation harness). These make
  later iteration cheap and safe.
- **No:** breadth before depth. We built photo review, many roles and a broad web
  desk, but the one loop that matters is incomplete: something changes,
  affected people are told, they acknowledge, and the coordinator sees who
  has not. Incident capture, correction, broadcast and acknowledgement are
  the missing parts of that loop. They matter more than any new feature.
- **Unknown:** the channel (Telegram or WhatsApp) and whether coordinators will
  pay. Only interviews can answer these.

## 5. Next steps

**Now: two weeks, run both tracks together**

| Track | Step | Measure of done |
|---|---|---|
| Discovery | Interview 5 to 8 Singapore coordinators. Ask which chat app their crews use and what their top-3 day-of pains are. | At least 3 name change relay as a top pain. At least 2 agree to a tabletop (stop rule). |
| Discovery | Shadow one real event, observing only. | A count of relayed questions and changes per hour. |
| Core loop | 1. Incident report intent (any issue, with severity) that reaches the coordinator. | The flat-tyre and missing-meals scenarios are recorded once and reach the coordinator. |
| Core loop | 2. Withdraw or correct my last report; a new delay for the same item replaces the pending one. | One live proposal per item. A wrong arrival can be reverted. |
| Core loop | 3. Coordinator broadcast from the phone (bot command plus confirm), with acknowledgement buttons on notices. | The rain scenario reaches every enrolled role. The acknowledgement count shows in the brief. |
| Core loop | 4. Approval cards show the requester and the helper's words; approve or reject from Telegram for the coordinator. | Report to decision in under 60 seconds on a phone. |
| Core loop | 5. Local times; fix the wording in finding 7; status questions ("was my delay approved", "when is X"). | No ISO timestamps in chat. |
| Freeze | Photo review, new roles, new web screens. | No PRs in these areas. |

**Gate before any tabletop:** rerun both simulation rounds with
`scripts/simulate.py`. Target: mean ease and clarity of at least 3.5, zero
unrecorded incidents, and zero conflicting pending proposals for one item.

**Next: only after at least 2 coordinators say yes**
- A 60-minute tabletop with one coordinator and 5 or 6 people, using the scripted failures in
  `docs/PILOT_RUNBOOK.md`.
- Run-sheet import from the coordinator's own spreadsheet, and a printable run sheet.
- A data retention and deletion procedure, and a backup restore drill.
- A decision on WhatsApp versus Telegram based on the interviews.

**Later: only after a successful shadow-mode wedding**
- A pricing test with one paid pilot.
- Multi-event setup, templates and Mandarin replies.
- The venue channel.

## 6. Core-loop sprint and simulation gate (later on 21 November)

PR #4 implements the five core-loop steps from section 5, test-first: 124
tests pass, migration 0003 is applied on staging, and live Telegram checks
pass on staging release `08a6fd0`. I then reran both simulation rounds with
the same personas on a fresh wedding.

| Round | Ease (before → after) | Clarity | Trust |
|---|---|---|---|
| Normal day (6 users) | 2.0 → 2.2 | 1.7 → 2.0 | 2.3 → 2.0 |
| Confounders (7 users) | 1.9 → 2.1 | 1.7 → 2.1 | 2.1 → 2.4 |

**Gate: not met.** The target of at least 3.5 for ease and clarity is still
far away.

**Critical findings 1 to 4 from section 3, all verified in the gate database:**
- The flat tyre and the missing meals were each recorded once, and both reached the coordinator.
- The wrong arrival and the missing-person report were withdrawn, and everyone told was told to ignore them.
- Revised delays never left two live proposals for one item.
- Approval requests showed the changes and the reporter's words.
- Blocked changes offered only Reject.
- Reporters were told decisions with the coordinator's note.
- Helpers acknowledged updates, and the brief showed "2 of 5 acknowledged".

**What still blocks the gate:**
1. **Understanding.** Mixed or vague messages still fall through to the
   fallback, for example "was my delay approved, should I hold the food",
   "I'm 25 minutes late", "who hasn't confirmed?" and "kitchen now 20, not 15".
   This is now the main gap. Next fixes:
   - a "late" intent for people
   - default a delay without an activity to the sender's last delay item
   - treat a combined question as several intents
2. **Discoverability.** The coordinator did not find `/announce` and sent the
   rain move as an incident instead. A coordinator-specific help is now live;
   a pinned command menu would help more.
3. **Dead ends.** Advice such as "ask registration" or "ask the coordinator"
   points people back at themselves, and a denial message gives no reason.
   Rejected reporters cannot reply with the reason the coordinator asked for.
4. **Location knowledge.** Places named in tasks (Ballroom Entrance B) and
   toilets are not in the seed data. That is a data gap more than a code gap.

**Security:** an automated review flagged five issues in this work, and all five are fixed with tests:
- the withdrawal window and permission are now enforced on the server
- a withdrawn arrival is not reverted if someone changed it since
- withdrawal notices keep the original notice's restrictions
- reporter text cannot imitate system sections of a notice
- reporter text stays quoted

A pre-fix withdrawal notice reached the couple in the gate run. It was created
before the restriction fix, and the round-2 notices were correctly restricted.

## 7. Resume point

- Code: `main`, plus PR #3 (rename, harness, this review) and PR #4 (core loop), which is stacked on #3.
- Staging: `loveoncue.jonathanjie.com` runs release `08a6fd0` (migration 0003), with
  DeepSeek V4.1 Flash for chat and photos, and `WEDDINGOPS_REHEARSAL=true`.
- Simulation: create a world with `scripts/simulate.py --dir <dir> init`. Put a model key in
  `<dir>/model.key` (mode 600) to turn on free-form parsing.
- Next to build: the understanding fixes in section 6, item 1. Then rerun the gate.
