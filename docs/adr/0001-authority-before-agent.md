# ADR 0001: application authority and replaceable model provider

WeddingOps owns identity, roles, business rules, and the database. Both web and
Telegram requests enter through authenticated application routes. A helper can
report a delay and a coordinator separately approves the resulting change.

For optional free-form input, one direct Mistral chat request returns JSON that
WeddingOps validates against its intent schema. The request includes no tools,
retrieved data, identities, or conversation history. The application resolves
entities, checks permissions, and requests human confirmation before any report
changes state. Explicit commands use the local parser.

The original v0.1.0 used OpenClaw for intent interpretation. The direct adapter
replaces that gateway and its operator credentials while keeping the same authority
boundary.
