# WeddingOps: product foundation

Status: implementation foundation, not approved for an unsupervised live wedding.
Working name only. Initial owner: Jon. Brief read from the supplied Google Doc on
2026-10-03. This document records design decisions, not validated market demand.

## Thesis
A wedding is a temporary operating organization. Its coordinator needs a current
picture of people, timing, dependencies and exceptions. Helpers need a much
smaller picture: their next action, location, owner, and whom to notify.
WeddingOps is the chat-native execution layer over an existing plan, not another
budgeting, vendor marketplace, wedding website or twelve-month planning suite.

The promise: every helper can find what to do now, report what changed, and know
that the right people received the resulting instructions. Receipt and human
acknowledgement are different states. AI confidence is not operational certainty.

## Users and jobs
- Lead coordinator: review exceptions, approve consequential changes, verify that
  affected teams acknowledged them; retain manual authority throughout.
- Team lead: make the team's readiness visible and resolve local handoffs.
- Helper: find an assignment/location, acknowledge it, report completion or trouble.
- Vendor staff: see only relevant timing, contacts and assigned work.
- Family liaison: locate required relatives discreetly, without exposing private
  contact data to unrelated helpers.
- Couple: receive a calm summary only when opted in; not the default escalation target.

A single person may have multiple roles. Roles grant capabilities; team membership
narrows operational scope. Neither a name typed in chat nor a Telegram username
proves identity. Coordinator-issued invitations bind a pre-created member record.

## Journey
### Setup, approximately T-14 to T-1
Create the event, import a guest CSV in preview mode, reconcile ambiguous people,
review the timeline and explicit dependencies, add venue notes, verify source
revisions, assign owners and teams, issue invitations, and rehearse failures.
A coordinator must approve ingested knowledge before helpers can retrieve it.

### Event day
Open NOW/NEXT and the live timeline. Task reminders collect acknowledgements.
Reports become structured incidents or draft actions, never arbitrary DB writes.
A catering delay creates a proposed dependency-aware schedule change. The lead
reviews its diff, constraints, scope, expiry and version, then approves or rejects.
Only committed changes create role-targeted notifications in a durable outbox.

### Closeout
Export the run sheet and audit summary, close unresolved incidents, revoke helper
access, and archive the cell. A configurable retention policy must be agreed with
the customer before a live pilot. Deletion includes backups and agent transcripts;
no automatic destructive retention job is enabled in this foundation.

## Information architecture
Coordinator: command center, timeline, tasks, arrivals/seating, people/teams,
vendors/locations, incidents, approvals, knowledge, activity, setup/import.
Helper: NOW, NEXT, MY TASKS, relevant timeline, seat lookup where authorized,
venue notes, report issue. Chat complements buttons; it does not replace them.

## V1 boundary
Build a single event cell, one server-bound identity per request, Telegram direct
messages plus a same-origin web/Mini App surface. Preserve a deterministic mode
with no LLM credentials. Start with approved text documents and CSV guest imports.
All real personal data stays in the operational database, not the repository.

Non-goals: payments, contract negotiation, public guest social/chat groups,
autonomous emergency management, safety-critical medical advice, facial recognition,
passive location tracking, automatic scanning of people's existing chat groups,
complex seating optimization, full calendar/Drive/Gmail OAuth synchronization,
and an autonomous swarm of specialized agents.

## Key workflows and authority
Factual questions return permission-filtered DB results with an as-of time.
Missing-relative reports record that a location is unconfirmed, NOT that someone
has definitely failed to arrive. Arrival reports may resolve matching incidents
and notify only the responsible family and photography teams.

Schedule changes use explicit finish-to-start dependencies. The first version
shifts an item and only the downstream items that would otherwise violate those
dependencies. It does not silently compress speeches, renegotiate vendor hours,
or move fixed commitments. Violated hard deadlines block approval.

The model may interpret, retrieve and propose. It has no approval credential.
Mutations inferred from free text require the reporting human to confirm their
structured meaning. Coordinator decisions require a separate explicit UI action.

## Notification contract
A message has an intended recipient, purpose, source event, schedule version,
delivery state and optional acknowledgement. Do not equate Telegram API acceptance
with a human reading the message. Retry transient failures with a lease and bounded
backoff. Surface permanent failures. Supersede outdated schedule reminders.
Avoid broad broadcasts and notify only explicitly affected teams.

## Commercial hypothesis and research consequences
Existing tools already offer live timelines, role views and AI assistance. The
hypothesis to test is whether a low-install, bidirectional operations layer that
imports existing plans reduces relayed questions and unacknowledged changes more
than those products. This is NOT a claim of an empty competitive market.
Potential paying buyer: professional coordinator or venue with repeat events;
per-event pricing is a hypothesis, not a validated price recommendation.

## Pilot measures and gates
Observe one rehearsal before a real event. Measure time to answer factual
questions, fraction answered from a cited source, change-to-acknowledgement time,
missed critical instructions, wrong-person matches, permission denials and
coordinator interruption count. Suggested targets are provisional: zero
unauthorized disclosures/writes, every material change attributable to a named
approver, and a usable manual run sheet during model or network outages.

A pilot requires a coordinator in control, verified roster, venue connectivity
check, printed fallback, support owner, backup/restore drill, credential setup,
privacy review and signed-off transport/security tests. The build does not replace
a professional coordinator or venue emergency procedures.

## Assumptions and open questions
Singapore/English-first pilot, approximately 180 guests and 10–20 operators;
Asia/Singapore is the example timezone, not a hard-coded scheduling rule.
Are temporary helpers willing to use Telegram? Who enters live updates? What is
the acceptable number of notifications? Can planners provide clean dependencies?
Which updates must remain private even from the couple? Test with actual planners;
this research run contains no customer interviews or field validation.
