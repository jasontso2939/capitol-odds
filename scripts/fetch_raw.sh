#!/usr/bin/env bash
# Download raw files from the California Legislature's public data server and
# record each one in data/raw/MANIFEST.md. Resumable: safe to run again.
#   bash scripts/fetch_raw.sh docs      # data dictionary + table definitions (~400 KB)
#   bash scripts/fetch_raw.sh session   # the 2025-26 session database (~1.2 GB)
set -euo pipefail
BASE="https://downloads.leginfo.legislature.ca.gov"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$ROOT/data/raw"
mkdir -p "$RAW"

fetch() {
  local f="$1" url="$BASE/$1"
  echo "[fetch] $url"
  curl -fSL --retry 3 -C - -o "$RAW/$f" "$url"
  local bytes sha
  bytes=$(wc -c < "$RAW/$f" | tr -d ' ')
  sha=$(shasum -a 256 "$RAW/$f" | cut -d' ' -f1)
  echo "| $(date -u +%Y-%m-%d) | $url | $f | $bytes | $sha |" >> "$RAW/MANIFEST.md"
  echo "[fetch] ok: $f ($bytes bytes)"
}

need_kb=$((4 * 1024 * 1024))   # 4 GB free: 1.2 GB download plus working room
avail_kb=$(df -k "$RAW" | awk 'NR==2{print $4}')
if [ "${1:-}" = "session" ] && [ "$avail_kb" -lt "$need_kb" ]; then
  echo "[fetch] only $((avail_kb / 1024 / 1024)) GB free here; need about 4 GB. Free up space and run again."
  exit 1
fi

case "${1:-}" in
  docs)    fetch pubinfo_Readme.pdf; fetch pubinfo_load.zip ;;
  session) fetch pubinfo_2025.zip ;;
  *) echo "usage: $0 docs|session"; exit 1 ;;
esac
