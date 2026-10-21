#!/usr/bin/env bash
# fm_pipeline_selection <pipeline> <kind> <mode> [harness backend yolo]
# fm_pipeline_gate <state> <task-id> <captured-meta> [candidate]
# Gate failures print one reason on stdout, matching fm_dod_accept_ship_done.

fm_pipeline_selection() {
  local pipeline=$1 kind=$2 mode=$3 harness=${4:-codex} backend=${5:-herdr} yolo=${6:-off}
  [ -n "$pipeline" ] || return 0
  if [ "$pipeline" != pstack ] || [ "$kind" != ship ] || [ "$mode" != local-only ] ||
    [ "$harness" != codex ] || [ "$backend" != herdr ] || [ "$yolo" != off ]; then
    echo "error: pstack currently requires Ship, local-only, Codex, Herdr, and yolo=off" >&2
    return 1
  fi
}

fm_pipeline_gate() {
  local state=$1 id=$2 meta=$3 candidate=${4:-} script_dir home data selected live reason
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  home=${FM_HOME:-${FM_ROOT_OVERRIDE:-$(cd "$script_dir/.." && pwd)}}
  data=${FM_DATA_OVERRIDE:-$home/data}
  selected=$(sed -n 's/^pipeline=//p' "$meta" 2>/dev/null || true)
  live=$(sed -n 's/^pipeline=//p' "$state/$id.meta" 2>/dev/null || true)
  if [ -z "$selected$live" ] && [ ! -e "$data/$id/pipeline/contract.json" ]; then
    return 0
  fi
  if [ "$selected" != pstack ] || [ "$live" != pstack ]; then
    printf '%s\n' 'pipeline metadata is missing, unknown, or conflicts with the captured task'
    return 1
  fi
  if [ "$(sed -n 's/^spawn_gen=//p' "$meta")" != "$(sed -n 's/^spawn_gen=//p' "$state/$id.meta")" ]; then
    printf '%s\n' 'pipeline task generation changed during observation'
    return 1
  fi
  local -a args=(gate "$id")
  [ -z "$candidate" ] || args+=(--candidate "$candidate")
  if reason=$(FM_HOME="$home" FM_STATE_OVERRIDE="$state" FM_DATA_OVERRIDE="$data" \
    "$script_dir/fm-pstack.sh" "${args[@]}" 2>&1); then
    return 0
  fi
  printf '%s\n' "$reason"
  return 1
}
