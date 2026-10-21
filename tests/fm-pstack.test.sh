#!/usr/bin/env bash
set -eu
# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
python3 "$ROOT/tests/pstack-cases.py" "$ROOT"
