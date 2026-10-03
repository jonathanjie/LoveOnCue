#!/usr/bin/env bash
# Run explicitly from your own authenticated machine; this build did not create a remote.
set -euo pipefail
cd "$(dirname "$0")/.."
OWNER="${GITHUB_OWNER:-jonathanjie}"
REPO="${GITHUB_REPO:-wedding-ops}"
command -v gh >/dev/null || { echo 'Install GitHub CLI and run gh auth login first.' >&2; exit 1; }
git rev-parse --is-inside-work-tree >/dev/null
if [[ -n "$(git status --porcelain)" ]]; then echo 'Commit or stash changes before publishing.' >&2; exit 1; fi
LOGIN="$(gh api user --jq .login)"
if [[ "$LOGIN" != "$OWNER" ]]; then echo "Authenticated as $LOGIN, expected $OWNER. Review GITHUB_OWNER before continuing." >&2; exit 1; fi
if git remote get-url origin >/dev/null 2>&1; then echo 'An origin already exists; review it and push manually. Nothing changed.' >&2; exit 1; fi
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then echo 'Repository already exists. Refusing to overwrite or repurpose it.' >&2; exit 1; fi
gh repo create "$OWNER/$REPO" --private --source=. --remote=origin --push
echo "Published private repository $OWNER/$REPO"
