"""Pack one session's leginfo export into the compact files the pipeline reads.

Usage: python scripts/archive_session.py pubinfo_2023.zip data/archive/pubinfo_2023

Writes gzipped copies of the tables the pipeline uses, the Governor's veto messages as
one CSV (veto_text.csv.gz), and the introduced-text statistics used to spot intent-only
bills (intro_text.csv). Bill text itself is not kept. Older sessions never change, so
these files are built once and reused instead of downloading 1+ GB each week.
"""
import csv
import gzip
import io
import re
import sys
import zipfile
from pathlib import Path

TABLES = ["BILL_TBL", "BILL_HISTORY_TBL", "BILL_VERSION_TBL", "BILL_VERSION_AUTHORS_TBL", "LEGISLATOR_TBL",
          "VETO_MESSAGE_TBL", "BILL_DETAIL_VOTE_TBL", "BILL_SUMMARY_VOTE_TBL", "BILL_MOTION_TBL", "LOCATION_CODE_TBL"]
INTENT = re.compile(r"intent of the Legislature to (enact|subsequently enact)", re.I)


def main(zip_path: str, out_dir: str) -> None:
    z = zipfile.ZipFile(zip_path)
    names = set(z.namelist())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        member = f"{t}.dat"
        if member not in names:
            print(f"[archive] missing {member}")
            continue
        with z.open(member) as src, gzip.open(out / f"{member}.gz", "wb", compresslevel=9) as dst:
            while chunk := src.read(1 << 20):
                dst.write(chunk)

    # Veto messages: one row per message with the text
    rows = []
    if "VETO_MESSAGE_TBL.dat" in names:
        for line in z.read("VETO_MESSAGE_TBL.dat").decode("utf-8", "replace").splitlines():
            f = [c.strip("`") for c in line.split("\t")]
            if len(f) >= 3 and f[2] in names:
                rows.append((f[0], f[1], re.sub(r"\s+", " ", z.read(f[2]).decode("utf-8", "replace"))))
    with gzip.open(out / "veto_text.csv.gz", "wt", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["BILL_ID", "date", "body"])
        w.writerows(rows)

    # Introduced text length and intent-only flag (spot bills)
    stats = []
    reader = csv.reader(io.TextIOWrapper(z.open("BILL_VERSION_TBL.dat"), encoding="utf-8", errors="replace"),
                        delimiter="\t", quotechar="`")
    for f in reader:
        if len(f) < 15:
            continue
        bid, action, lob = f[1], f[4], f[14]
        if action != "Introduced" or not re.match(r"^\d{9}(AB|SB)\d+$", bid) or lob not in names:
            continue
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", z.read(lob).decode("utf-8", "replace"))).strip()
        stats.append((bid, len(body), int(bool(INTENT.search(body)))))
    with open(out / "intro_text.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["BILL_ID", "body_chars", "intent_only"])
        w.writerows(stats)
    print(f"[archive] {out}: {len(rows)} veto messages, {len(stats)} introduced bills")


if __name__ == "__main__":
    main(*sys.argv[1:3])
