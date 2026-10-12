#!/usr/bin/env bash
# Unpack only the tables the pipeline reads (skips ~1 GB of bill-text LOB files).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/raw/pubinfo_2025"
mkdir -p "$OUT"
unzip -o -q "$ROOT/data/raw/pubinfo_2025.zip" \
  BILL_TBL.dat BILL_HISTORY_TBL.dat BILL_VERSION_TBL.dat BILL_VERSION_AUTHORS_TBL.dat \
  LEGISLATOR_TBL.dat VETO_MESSAGE_TBL.dat 'VETO_MESSAGE_TBL_*.lob' \
  BILL_DETAIL_VOTE_TBL.dat BILL_SUMMARY_VOTE_TBL.dat BILL_MOTION_TBL.dat LOCATION_CODE_TBL.dat -d "$OUT"
echo "[extract] ok: $OUT"
