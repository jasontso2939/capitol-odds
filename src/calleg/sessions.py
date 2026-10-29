"""The legislative sessions the project covers and where each one's data lives.

California sessions run two years and start in December of even years (the 2027-28
session convenes in December 2026). The current session is read from the full leginfo
download (data/raw/pubinfo_<year>); finished sessions come from compact archives
(data/archive/pubinfo_<year>) built by scripts/archive_session.py and stored on the
session-archive branch. Nothing here names a specific year except FIRST: when a new
session's download appears, it becomes current and the previous one is archived.
"""
from __future__ import annotations

import datetime as _dt
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRST = 2007   # first session covered (2007-08). Earlier archives lack committee locations (1999-2005) or bill histories (1989-97)


def label(year: int) -> str:
    return f"{year}-{str(year + 1)[2:]}"


def session_for(day: _dt.date) -> int:
    """First year of the session in progress on a given day."""
    y = day.year
    if y % 2:                      # odd year: first year of a session
        return y
    return y + 1 if day.month == 12 else y - 1


def full_dir(year: int) -> Path:
    return ROOT / f"data/raw/pubinfo_{year}"


def archive_dir(year: int) -> Path:
    return ROOT / f"data/archive/pubinfo_{year}"


def _has(path: Path) -> bool:
    return (path / "BILL_TBL.dat").exists() or (path / "BILL_TBL.dat.gz").exists()


def raw_dir(year: int) -> Path:
    return full_dir(year) if _has(full_dir(year)) else archive_dir(year)


def _latest_with_data() -> int:
    years = [y for y in range(FIRST, session_for(_dt.date.today()) + 2, 2) if _has(full_dir(y)) or _has(archive_dir(y))]
    if years:
        return max(years)
    # No downloads (a fresh clone or CI): use the sessions in the committed outputs
    built = ROOT / "data/processed/members_all.csv"
    if built.exists():
        import csv
        with open(built, newline="") as fh:
            s = [int(r["session"]) for r in csv.DictReader(fh) if r.get("session")]
        if s:
            return max(s)
    return session_for(_dt.date.today())


CURRENT = int(os.environ.get("CALLEG_CURRENT") or _latest_with_data())
SESSIONS = tuple(range(FIRST, CURRENT + 1, 2))


def is_complete(year: int, today: _dt.date | None = None) -> bool:
    """True once the Governor's last signing deadline of the session has passed.

    Bills must pass by August 31 of the second year and the Governor acts by September 30,
    so outcomes are final on October 1. Before that, pending bills would look like
    failures, so incomplete sessions are kept out of model training and ten-year totals."""
    return (today or _dt.date.today()) >= _dt.date(year + 1, 10, 1)


def intro_cache(year: int) -> Path:
    if year == CURRENT:
        return ROOT / f"data/processed/intro_text_{year}.csv"
    return archive_dir(year) / "intro_text.csv"


def zip_path(year: int) -> Path:
    return ROOT / f"data/raw/pubinfo_{year}.zip"


def available() -> list[int]:
    return [y for y in SESSIONS if _has(raw_dir(y))]


def complete() -> list[int]:
    return [y for y in available() if is_complete(y)]
