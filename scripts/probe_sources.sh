#!/usr/bin/env bash
# Lists what the California Legislature publishes, read-only, so the pipeline
# can be written against real file names. Run from the repo root:
#   bash scripts/probe_sources.sh
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/raw/_probe"
mkdir -p "$OUT"
say() { echo "[probe] $*"; }

for p in "" "bill/" "bill/pubinfo/" "bill/pubinfo_daily/"; do
  name="ftp_pub_$(echo "$p" | tr '/' '_')"
  say "FTP listing: ftp://leginfo.public.ca.gov/pub/$p"
  curl -sS -m 40 "ftp://leginfo.public.ca.gov/pub/$p" > "$OUT/${name}_long.txt" 2> "$OUT/${name}_err.txt" || say "  failed (see ${name}_err.txt)"
done

for u in \
  "https://downloads.leginfo.legislature.ca.gov/" \
  "https://leginfo.legislature.ca.gov/faces/codes.xhtml" ; do
  say "HEAD $u"
  curl -sIL -m 30 "$u" 2>&1 | head -8 >> "$OUT/https_heads.txt"
  echo "---" >> "$OUT/https_heads.txt"
done

date -u +"%Y-%m-%dT%H:%M:%SZ" > "$OUT/probed_at.txt"
say "done. Results are in data/raw/_probe/"
