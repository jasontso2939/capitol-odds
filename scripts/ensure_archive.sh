#!/usr/bin/env bash
# Make sure every finished session before the current one is in data/archive.
# Fetches the session-archive branch, then downloads and packs any session that is missing
# (after a rollover, the session that just ended). Prints "changed" if it packed anything.
# usage: bash scripts/ensure_archive.sh CURRENT_YEAR
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CUR="$1"
cd "$ROOT"
if git fetch --depth 1 origin session-archive 2>/dev/null; then
  git archive FETCH_HEAD data/archive | tar x
fi
changed=""
for y in $(seq 2017 2 $((CUR - 2))); do
  if [ ! -f "data/archive/pubinfo_$y/BILL_TBL.dat.gz" ]; then
    echo "[archive] packing missing session $y" >&2
    zip="data/raw/pubinfo_$y.zip"
    [ -f "$zip" ] || curl -fSL --retry 3 -o "$zip" "https://downloads.leginfo.legislature.ca.gov/pubinfo_$y.zip"
    python3 scripts/archive_session.py "$zip" "data/archive/pubinfo_$y" >&2
    sha256sum "$zip" > "data/archive/pubinfo_$y/SOURCE_SHA256.txt"
    date -u +%F > "data/archive/pubinfo_$y/DOWNLOADED.txt"
    changed="changed"
  fi
done
echo "$changed"
