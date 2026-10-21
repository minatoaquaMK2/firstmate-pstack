#!/usr/bin/env bash
# Usage: fm-pstack.sh --help
set -eu
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:-}" in
  accept|review)
    [ -z "${FM_TASK_ID:-}" ] || { echo "pstack: review and acceptance are host-side operations" >&2; exit 1; }
    ;;
esac
if [ "${1:-}" = accept ]; then
  # shellcheck source=bin/fm-wake-lib.sh
  . "$SCRIPT_DIR/fm-wake-lib.sh"
  [[ "${2:-}" =~ ^[a-zA-Z0-9][a-zA-Z0-9_-]*$ ]] || exit 2
  PIPELINE_HOME=${FM_HOME:-${FM_ROOT_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}}
  PIPELINE_STATE=${FM_STATE_OVERRIDE:-$PIPELINE_HOME/state}
  PIPELINE_CONTROL_LOCK="$PIPELINE_STATE/.control-$2.lock"
  fm_lock_acquire_wait "$PIPELINE_CONTROL_LOCK"
  trap 'fm_lock_release "$PIPELINE_CONTROL_LOCK"' EXIT
  python3 "$SCRIPT_DIR/fm-pstack.py" "$@"
else
  exec python3 "$SCRIPT_DIR/fm-pstack.py" "$@"
fi
