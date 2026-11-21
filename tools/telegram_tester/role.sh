#!/usr/bin/env bash
# Switch which staging role the tester's Telegram account plays.
#   role.sh members          List active members and their roles.
#   role.sh ROLE             Link the tester account to the first member with ROLE.
#   role.sh --member ID      Link the tester account to a specific member.
# Runs the app's operator CLI, which refuses unless WEDDINGOPS_REHEARSAL=true.
set -euo pipefail

TESTER_DIR=/opt/loveoncue-tester
APP_DIR=/opt/weddingops/current
APP_ENV=/etc/weddingops/weddingops.env

if [[ $# -lt 1 ]]; then
  sed -n '2,6p' "$0"
  exit 2
fi

run_rehearsal() {
  (
    set -a
    # shellcheck disable=SC1090
    . "$APP_ENV"
    set +a
    cd "$APP_DIR"
    exec runuser -u weddingops -- "$APP_DIR/.venv/bin/python" -m wedding_ops.cli rehearsal "$@"
  )
}

if [[ $1 == members ]]; then
  run_rehearsal members
  exit
fi

tester_id=$("$TESTER_DIR/.venv/bin/python" "$TESTER_DIR/loveoncue_tester.py" whoami)
if [[ $1 == --member ]]; then
  run_rehearsal link --telegram-user "$tester_id" --member "$2"
else
  run_rehearsal link --telegram-user "$tester_id" --role "$1"
fi
