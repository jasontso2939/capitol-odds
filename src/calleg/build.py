"""One command: raw official export -> processed tables + all-member scorecard.

    python -m calleg.build [--raw data/raw/pubinfo_2025] [--out data/processed]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .model import scorecard
from .pipeline import build


def prepare_members(bills: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Clean the roster: drop vacancies and spelling-variant twins, flag partial terms."""
    members = members[members.member.notna()].drop_duplicates("member")
    # The export lists some members twice under spelling variants (e.g. Avila Farias / Ávila Farías).
    # Drop a record with no bills when its seat has another record that does.
    has_bills = members.member.isin(bills.member)
    twin = members.duplicated("district", keep=False)
    members = members[~(twin & ~has_bills)]
    seat = pd.read_csv(Path(__file__).resolve().parents[2] / "data/reference/seat_changes.csv")
    members["partial_term"] = members.member.isin(seat.member)
    first = bills.groupby("member").introduced.min().rename("first_bill_date")
    last = bills.groupby("member").introduced.max().rename("last_bill_date")
    members = members.join(first, on="member").join(last, on="member")
    return members


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw/pubinfo_2025")
    ap.add_argument("--out", default="data/processed")
    a = ap.parse_args(argv)
    bills, members = build(a.raw)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    members = prepare_members(bills, members)
    bills.to_csv(out / "bills_all.csv", index=False)
    members.to_csv(out / "members_all.csv", index=False)
    flat = bills.drop(columns=["author_house"])
    bud = flat[flat.is_budget].groupby("member").size().rename("budget_bills")
    # Budget Act bills are introduced under the budget chairs' names; ranks exclude them.
    ranked = flat[~flat.is_budget]
    for method in ("all_leads", "first_listed"):
        # Ranks are computed within each chamber (Assembly and Senate are separate contests).
        parts = [
            scorecard(ranked, members[members.chamber == ch], method).assign(chamber=ch)
            for ch in ("Assembly", "Senate")
        ]
        pd.concat(parts, ignore_index=True).merge(
            members[["member", "partial_term", "first_bill_date", "last_bill_date"]], on="member"
        ).join(bud, on="member").fillna({"budget_bills": 0}).to_csv(out / f"scorecard_{method}.csv", index=False)
    print(f"bills rows={len(bills)} bills={bills.bill_id.nunique()} members={len(members)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
