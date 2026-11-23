#!/usr/bin/env sh
set -eu
export RATI0_LOOM_LIGHT=1
exec python3 "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/server.py" "${1:?loopback port required}"
