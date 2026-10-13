"""The legislative sessions the project covers and where each one's data lives.

The current session is read from the full leginfo download (data/raw/pubinfo_<year>).
Earlier sessions come from compact archives (data/archive/pubinfo_<year>) built by
scripts/archive_session.py and stored on the session-archive branch.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SESSIONS = (2017, 2019, 2021, 2023, 2025)   # first year of each two-year session: 2017-18 ... 2025-26
CURRENT = SESSIONS[-1]


def label(year: int) -> str:
    return f"{year}-{str(year + 1)[2:]}"


def raw_dir(year: int) -> Path:
    full = ROOT / f"data/raw/pubinfo_{year}"
    if (full / "BILL_TBL.dat").exists():
        return full
    return ROOT / f"data/archive/pubinfo_{year}"


def intro_cache(year: int) -> Path:
    if year == CURRENT:
        return ROOT / "data/processed/intro_text.csv"
    return ROOT / f"data/archive/pubinfo_{year}/intro_text.csv"


def zip_path(year: int) -> Path:
    return ROOT / f"data/raw/pubinfo_{year}.zip"


def available() -> list[int]:
    return [y for y in SESSIONS if (raw_dir(y) / "BILL_TBL.dat").exists() or (raw_dir(y) / "BILL_TBL.dat.gz").exists()]
