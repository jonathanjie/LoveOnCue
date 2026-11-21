# Changelog

## Unreleased

- Add operator-only rehearsal role switching (`WEDDINGOPS_REHEARSAL=true`) so one
  Telegram account can test every staging role.
- Add `photo` and `whoami` to the Telegram user tester, plus `role.sh`.
- Rename the project checkout and GitHub repository to LoveOnCue.
- Restore coordinator briefs, Telegram navigation, confirmation buttons, and
  explicit repeat-confirmation replies.
- Add optional read-only setup photo review and a local multi-role Telegram rehearsal.

- Pin the browser CI runner to Ubuntu 24.04.
- Run explicit chat commands locally and use a direct Mistral API adapter for optional free-form intent parsing.

## 0.1.0 — foundation build (2026-10-03)

Independent product/architecture groundwork; typed transactional domain; 180-guest fictional rehearsal; same-origin API and responsive TypeScript UI; server-enforced roles; one-use invitations and Telegram identity validation; guarded reports, delay approval and dependency propagation; durable ingress/outbox, reminders and acknowledgements; reviewed text knowledge and CSV imports; guest corrections/family contacts and dual guest/helper identity; frozen Alembic migration; local tests/browser evidence; private OpenClaw adapter and deployment/CI scaffolding; source/reference/security/pilot/Codex documentation.

GitHub hosting was blocked by absence of a repository-creation action. Source ZIP and full-history Git bundle are the persistence artifacts; see `docs/PERSISTENCE.md`. External integrations/deployment are not certified by this release.
