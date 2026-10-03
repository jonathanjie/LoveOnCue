---
name: weddingops-intent
description: Reference policy for classifying one wedding helper request into a typed intent; not enabled as a runtime skill in the current adapter.
---

# WeddingOps intent reference

The executable source of truth for intent fields is docs/contracts/intent.schema.json.
The explicit classifier instruction is wedding_ops.agent.SYSTEM. This reference does not
register tools and must not be used to grant permissions.

Map "what should I be doing now" to now; a seating question to guest; a venue question to
knowledge or location; an arrival question to family_status; an explicit confirmed arrival
to arrival; an unconfirmed location to missing_family; an explicit activity delay with
minutes to delay. Resolve no identity yourself. Administrative requests, consequential
approvals, uncertain instructions and safety emergencies return unknown.

The caller's application validates the result, resolves allowed records and obtains a
human confirmation for reports. A proposed schedule delay still needs a separate
coordinator decision before any authoritative timing changes.
