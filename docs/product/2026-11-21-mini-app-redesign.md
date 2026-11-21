# Mini App redesign — 21 November 2026

Status: **approved 21 November 2026**, with `GET /api/brief` (section 6) and two founder
changes: every main view must fit one phone screen, and a Home hub tab (section 3a). Branch `claude/loveoncue-miniapp-redesign`,
stacked on PR #4. Resume point: section 7.

## 1. The people and the job

| Person | Where they are | What they must do in the Mini App |
|---|---|---|
| **Coordinator** (Alex) | On their feet at the venue, phone in one hand, interrupted every minute. Chat is where things reach them. | 1. Decide a schedule change with full context, in under 60 seconds. 2. See who has not seen their job or the latest update. 3. See where the day is now and what changed. 4. See and close problems. 5. Send an update to teams. |
| **Helper** (Jamie, usher) | A friend or relative with one job, no training. Opens the app from the chat button. | 1. See my job now: what, where, when. 2. Say "Got it" and "Done". 3. Read updates sent to me. 4. Find a guest's table. 5. See the whole schedule. |

The chat deputy handles questions, reports and chasing. The Mini App covers what chat
is bad at: the whole picture at a glance, a decision with full context, and lists.

## 2. Audit of the current 11 screens (phone width, 390 px)

Current screenshots: `work/audit/current/` (not committed). Proposed design mockups: `docs/screenshots/mini-app/design/`.

| Screen | Problem on a phone | Decision |
|---|---|---|
| Overview | The header, role picker and rehearsal bar fill the first screen. Four equal metric boxes. "Command centre" and "a human in command" are jargon. | Replace with **Now** (coordinator) and **My jobs** (helper). |
| Run of show | Long cards. "Version 1", "planned times remain preserved". Delay uses a browser prompt. | Keep as **Schedule** with a timeline and a "now" line. Delay uses an in-app form. |
| My tasks | "Acknowledge", "Start", "Mark complete" have equal weight. State words are system words ("pending"). | Merge into **My jobs**. One main button at a time. |
| Guest desk | Works, but the coordinator's guest editor is a long form inside the result card. | Keep as **Guests**. Editor opens in a sheet. |
| People & teams | Roster only. No view of who has seen what. | Becomes **Crew**: each person's next job and whether they have seen it. Send an update from here. |
| Issues | Report form above the list. | Coordinator: in **Review**. Helper: "Report a problem" in **Help**. |
| Approvals | Table of changes is hard to read on a phone. No name of the person who asked. Approve is behind a browser confirm. | Becomes **Review**. Before-and-after cues, who asked and their words, plain blockers, an in-app confirm. |
| Venue & vendors | The schematic floor plan is too small to read on a phone. | **Places & vendors**: a list with directions and call links. Floor plan removed. |
| Knowledge | Mixes search with document approval. | **Venue notes**: search for everyone; approval stays for the coordinator. |
| Audit trail | Raw event types and JSON. | **Activity log**: plain sentences, JSON on request. |
| Setup & imports | Timestamps "including UTC offset". | **Set up**: time pickers in the wedding's time zone. Same commands. |
| Chat panel (all screens) | A second chat beside Telegram. Uses a slash command (`/now`). | Removed. Chat lives in Telegram. |

## 3. Information architecture

A bottom tab bar (thumb reach), chosen by role. No sidebar, no hidden menu.

**Coordinator:** `Home` · `Schedule` · `Review (n)` · `Crew` · `Guests`.
**Helper:** `Home` · `My jobs (n)` · `Schedule` · `Guests` (only with a guest permission).

### 3a. Home is a hub

Like the base screen of a strategy game such as Call of War: one screen shows the state
of the day, and large tiles take you anywhere. Each tile shows a live count.

- **Status strip:** Now and Next on the schedule, with a moved time struck through.
- **Alert bar:** the most urgent open problem, if there is one.
- **Coordinator tiles:** Review, Crew, Schedule, Guests (each with a count), then small
  tiles for Send an update, Places & vendors, Venue notes, Problems, Set up, Activity log.
- **Helper:** an unread update with a "Read" button, the next job with one main button,
  then tiles for Find a guest, Report a problem, Places, Venue notes.
- A section opened from a tile has a "‹ Home" back button.

### 3b. Fit one phone screen (390 × 844)

- Switch between lists with segmented chips instead of stacking sections
  (Review: Changes | Problems; Crew: Not seen | Got it | Everyone).
- One line per schedule cue: time, dot, title, place, and a flag ("+12 min").
  Finished cues fold into one "2 finished" row.
- Details open in a bottom sheet: eyebrow, title, the requester's words, the
  before-and-after times, and two pill buttons side by side.
- A row of two or three key numbers replaces stacked metric cards.

References studied: recent.design and designeer.xyz (interface category): stat rows,
segmented chips, bottom sheets over a list, pill buttons.

## 4. Visual direction

- **Feel:** calm and certain, like a well-run venue at dusk. Ivory linen, evergreen,
  brass candle light. Not a dashboard.
- **Colour:** linen page `#F7F4EE`, white cards, evergreen `#173D35` for the one main
  action, brass `#8A5E12` for "now" and changes. Status: clay red (urgent), amber
  (waiting), sage (done). All text pairs meet WCAG AA (4.5:1). Dark mode follows Telegram.
- **Type:** the phone's own sans-serif at 16 px (the same as Telegram, no web-font
  download). A serif only for the couple's name and screen titles, like a place card.
  Times use tabular numbers.
- **Signature, the cue line:** a vertical line with each cue as a dot. A brass "Now"
  line crosses it at the current time. A moved cue shows the old time struck through
  and a brass "+12 min" chip. The same line appears in Now, Schedule, the approval
  before-and-after, and the helper's job card.
- **Density:** 15 px body text, 52 px list rows, 4 px grid.
- **Touch:** every button is at least 48 px high, every row at least 52 px. Confirmations use an in-app sheet,
  not the browser's `confirm()`.

## 5. Plain words

| System word | Shown as |
|---|---|
| pending / acknowledged / in_progress / done | Not seen yet / Got it / Doing it / Done |
| overdue | Late |
| approval pending / approved / rejected / expired | Waiting for you / Approved / Not approved / Too late to decide |
| incident open / resolved, severity urgent | Open / Sorted, Urgent |
| notification acknowledged | Read |
| knowledge document draft / approved / retired | Not checked yet / In use / Retired |
| timeline_version, state_version | not shown |

## 6. What does not change

- The same endpoints, session cookie, CSRF header and `X-WeddingOps-Client` header.
- The same commands and permission checks. Buttons only show when the snapshot grants
  allow them, and the server checks again. No new admin shortcuts.
- Demo sign-in stays loopback-only. The rehearsal role picker stays visible in demo mode.

**One new read-only endpoint (approved):** `GET /api/brief` returns the coordinator brief
and the read status of the latest announcement or timeline update ("4 of 6 read").
It uses the same `timeline:approve` check as the Telegram brief. Helpers get 403.

## 7. Build and verification (21–22 November 2026)

Built on branch `claude/loveoncue-miniapp-redesign`, stacked on PR #4.

- `web/src/app.ts` is now the shell only. Each screen is in `web/src/screens/`. Shared
  pieces: `api.ts` (same endpoints, cookie and CSRF), `access.ts` (grants decide which
  buttons show; the server checks again), `format.ts` (plain words), `ui.ts` (sheets, rows, tiles).
- Removed: the chat panel (chat lives in Telegram), the floor plan, `window.confirm()` and `window.prompt()`.
- New server code: only `GET /api/brief` (read-only, coordinator-only, tests in `tests/test_integrations.py`).
- Checks run: `pytest` (172 passed, 1 PostgreSQL skip, 91.6% coverage), `npm run typecheck`,
  `npm run build`, `scripts/export-contracts.py`, `scripts/http-smoke.py`, and
  `scripts/ui-smoke.py` both over HTTP against a local demo server and with `--bridge`.
- Phone screenshots of each view: `docs/screenshots/mini-app/`.

Not verified: inside the real Telegram client (theme, back button, safe areas), and on staging.
Do not deploy to staging without asking.

**Follow-ups noticed, not in scope:** some server-written notice text still has system words
(for example "Coordinator-approved timeline v2"), and the assistant check-in switch
(`set_deputy_enabled`) has no state in the snapshot, so the app cannot show it yet.
