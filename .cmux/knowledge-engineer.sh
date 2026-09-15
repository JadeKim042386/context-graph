#!/bin/sh
set -eu

CMUX_BIN="${CMUX_BIN:-/Applications/cmux.app/Contents/Resources/bin/cmux}"
SURFACE="${CMUX_KNOWLEDGE_ENGINEER_SURFACE:-surface:2}"
TAB_TITLE='Confirm knowledge-engineer role | context-graph'

usage() {
  echo "usage: $0 check | assign <work-id> <task> | heartbeat <work-id> | complete <work-id> <status> <report> | recover <work-id> <problem>" >&2
  exit 2
}

assert_target() {
  tree="$($CMUX_BIN tree --all --id-format both)"
  printf '%s\n' "$tree" | grep -F "surface $SURFACE " | grep -F "$TAB_TITLE" >/dev/null || {
    echo "knowledge-engineer surface not found: $SURFACE ($TAB_TITLE)" >&2
    exit 1
  }
}

send() {
  assert_target
  "$CMUX_BIN" send --surface "$SURFACE" "$1\\n"
}

case "${1:-}" in
  check)
    assert_target
    echo '--- health ---'
    "$CMUX_BIN" surface-health --surface "$SURFACE"
    echo '--- screen ---'
    "$CMUX_BIN" read-screen --surface "$SURFACE" --scrollback --lines 160
    ;;
  assign)
    [ "$#" -ge 3 ] || usage
    send "$(printf '%s\n' 'KE_ASSIGNMENT' "work_id: $2" 'owner: knowledge-engineer' "channel: cmux $SURFACE" "request: $3" 'protocol: report KE_HEARTBEAT every 60s; finish with KE_COMPLETION or stop with KE_BLOCKED; never silently stop.' 'completion_fields: work_id,status,changed,verification,unverified,next_action')"
    ;;
  heartbeat)
    [ "$#" -eq 2 ] || usage
    send "$(printf '%s\n' 'KE_HEARTBEAT' "work_id: $2" 'request: reply with current phase, last completed step, next step, and blocker (NONE if clear).')"
    ;;
  complete)
    [ "$#" -ge 4 ] || usage
    send "$(printf '%s\n' 'KE_COMPLETION' "work_id: $2" "status: $3" "report: $4" 'required: changed,verification,unverified,next_action')"
    ;;
  recover)
    [ "$#" -ge 3 ] || usage
    send "$(printf '%s\n' 'KE_BLOCKED' "work_id: $2" "problem: $3" 'request: do not restart or silently end; report the last safe checkpoint, exact blocker, recovery option, and required decision.')"
    ;;
  *) usage ;;
esac
