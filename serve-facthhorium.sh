#!/usr/bin/env sh
set -eu
export RATI0_LOOM_MODEL_ID=inkling-2-facthhorium
exec "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/serve.sh" "$@"
