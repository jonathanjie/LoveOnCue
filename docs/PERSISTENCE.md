# Source and documentation persistence

The original release archives are in the owner’s WeddingOps Build & Handoff folder.

## Final release files

The release is packaged as:

- `weddingops-v0.1.0.bundle` — complete local Git history and branches, preferred for Codex continuation.
- `weddingops-v0.1.0-source.zip` — tracked source/documentation/compiled UI snapshot under a `wedding-ops/` directory; no Git history.
- `weddingops-v0.1.0-docs.zip` — project Markdown, contracts, verification evidence, integration/deployment notes and screenshots for redundancy.
- `WeddingOps-Codex-Handoff.docx` — readable orientation, verification boundaries and next engineering steps.
- `weddingops-release-manifest.json` and `SHA256SUMS.txt` — exact release revision and archive/document hashes, generated after the final source commit.

The completed upload results and artifact URLs are recorded in the release delivery index next to these files. Checksums are deliberately outside the source tree to avoid a circular “commit contains its own archive hash” reference. Check them before unpacking/continuing. Do not treat a Drive folder link alone as proof every planned file was uploaded; use the verified delivery index and final task response.

The older `weddingops-core-milestone.bundle` ends at `d27d7dd`. The final release bundle ends at `3dd7f9c`.

## Privacy and backup scope

These artifacts contain independently written code, documentation and fictional fixtures only. They exclude `.env` files, runtime databases, credentials, provider traces, caches and dependencies. WeddingOps is all rights reserved. Dependencies retain their licenses.

The source bundle/ZIP is not an event-data backup. A deployed wedding requires its own encrypted database/configuration recovery procedure and retention plan, with a tested restore into an isolated cell. Drive is the durable redundancy available from this run, not a live code synchronization service.
