# LoveOnCue Telegram recovery

The October 3 fictional rehearsal demonstrated Telegram navigation, coordinator
briefs, explicit report confirmation, duplicate handling, and read-only photo
review. The chat described DeepSeek via OpenCode Go for intent testing and
treated the Mini App and schedule approval as separate from that chat-only test.

## Product decisions

- Keep the current invite, role, and transaction model. Helpers can report
  changes. A human coordinator must review and approve schedule changes through
  the application. Telegram can confirm only a draft owned by the sender.
- Restore the coordinator brief and its expanded view. Use recorded tasks,
  dependencies, incidents, approvals, and delivery failures. Show unknown
  availability as unknown.
- Restore inline navigation and a Confirm report button. Apply the same role
  checks to commands and callbacks. Keep the text command available for every
  callback, and label a repeated confirmation as already recorded.
- Restore optional photo review. Use bounded Telegram downloads and send only
  the image with its caption to an explicitly configured vision model. Distinguish
  observations from uncertainty. Photo replies have no event mutation path.
  Keep live vision disabled until the app's API billing and data handling are
  approved.
- Keep the existing Mini App sign-in path. Give enrolled users an inline
  Mini App link when the deployment has an HTTPS origin.

## Development and testing decisions

- Use a disposable, fictional local database and separate synthetic Telegram
  senders to exercise roles. The rehearsal harness selects fixtures locally.
  No public chat command can switch a user's role or impersonate a member.
- Exercise permission denial, duplicate callbacks and confirmations, expiry,
  webhook scope, delivery, and read-only photo checks with controlled transports.
- Keep photo tests independent of provider credentials and test the disabled
  path before commissioning a live provider.

## Implementation order

1. Add role-scoped queries and Telegram reply tests in `tests/test_telegram_recovery.py`.
   Build briefs and navigation on the current ingress and durable outbox.
   Add a nullable draft reference to the outbox with an Alembic migration.
2. Add photo tests first. Wire an opt-in HTTP vision reviewer and bounded
   Telegram file retrieval through the worker. Keep image bytes out of storage.
3. Add a local Telegram rehearsal command. Verify with pytest, the HTTP and
   browser smoke checks, PostgreSQL CI, and then the fictional VPS staging cell.

## Rollout

Back up the staging database. Apply migration 0002 before starting the new
API and worker. Update both services before subscribing the Telegram webhook
to callback updates. The migration adds a nullable column, so the previous
release can still read the database during rollback. Leave the vision model
unset during deterministic staging.
