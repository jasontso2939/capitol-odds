#!/usr/bin/env bash
# Unpack only the tables the pipeline reads (skips ~1 GB of bill-text LOB files).
set -euo pipefail
# usage: bash scripts/extract_raw.sh [YEAR]   (defaults to the newest downloaded session)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YEAR="${1:-$(ls "$ROOT"/data/raw/pubinfo_*.zip | sed -E 's/.*pubinfo_([0-9]{4})\.zip/\1/' | sort | tail -1)}"
OUT="$ROOT/data/raw/pubinfo_$YEAR"
mkdir -p "$OUT"
unzip -o -q "$ROOT/data/raw/pubinfo_$YEAR.zip" \
  BILL_TBL.dat BILL_HISTORY_TBL.dat BILL_VERSION_TBL.dat BILL_VERSION_AUTHORS_TBL.dat \
  LEGISLATOR_TBL.dat VETO_MESSAGE_TBL.dat 'VETO_MESSAGE_TBL_*.lob' \
  BILL_DETAIL_VOTE_TBL.dat BILL_SUMMARY_VOTE_TBL.dat BILL_MOTION_TBL.dat LOCATION_CODE_TBL.dat -d "$OUT" \
  || [ $? -eq 11 ]   # 11 = some names not in the zip (a new session has no veto messages yet)
echo "[extract] ok: $OUT"
