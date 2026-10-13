"""One command: raw official export -> processed tables + all-member scorecard.

    python -m calleg.build [--out data/processed]   (every session in calleg.sessions)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .model import scorecard
from .pipeline import build


def prepare_members(bills: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    """Clean one session's roster: drop vacancies and spelling-variant twins, flag partial terms.

    A member is flagged as a partial term when listed in data/reference/seat_changes.csv, or when
    another member with bills held the same seat in the same session (a mid-session seat change)."""
    members = members[members.member.notna()].drop_duplicates("member")
    # The export lists some members twice under spelling variants (e.g. Avila Farias / Ávila Farías).
    # Drop a record with no bills when its seat has another record that does.
    has_bills = members.member.isin(bills.member)
    twin = members.duplicated("district", keep=False)
    members = members[~(twin & ~has_bills)]
    seat = pd.read_csv(Path(__file__).resolve().parents[2] / "data/reference/seat_changes.csv")
    shared_seat = members.duplicated("district", keep=False)
    key = set(zip(seat.session, seat.district, seat.member))
    listed = pd.Series([k in key for k in zip(members.session, members.district, members.member)], index=members.index)
    members["partial_term"] = shared_seat | listed
    first = bills.groupby("member").introduced.min().rename("first_bill_date")
    last = bills.groupby("member").introduced.max().rename("last_bill_date")
    members = members.join(first, on="member").join(last, on="member")
    return members


def build_session(raw: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    bills, members = build(raw)
    members = prepare_members(bills, members)
    flat = bills.drop(columns=["author_house"])
    bud = flat[flat.is_budget].groupby("member").size().rename("budget_bills")
    # Budget Act bills are introduced under the budget chairs' names; ranks exclude them.
    ranked = flat[~flat.is_budget]
    cards = {}
    for method in ("all_leads", "first_listed"):
        # Ranks are computed within each chamber (Assembly and Senate are separate contests).
        parts = [
            scorecard(ranked, members[members.chamber == ch], method).assign(chamber=ch)
            for ch in ("Assembly", "Senate")
        ]
        cards[method] = pd.concat(parts, ignore_index=True).merge(
            members[["member", "partial_term", "first_bill_date", "last_bill_date"]], on="member"
        ).join(bud, on="member").fillna({"budget_bills": 0}).assign(session=int(bills.session.iloc[0]))
    return bills, members, cards


def main(argv=None) -> int:
    from .sessions import available, raw_dir
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/processed")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    B, M, C = [], [], {"all_leads": [], "first_listed": []}
    for year in available():
        bills, members, cards = build_session(raw_dir(year))
        B.append(bills), M.append(members)
        for k, v in cards.items():
            C[k].append(v)
        print(f"{year}: bills rows={len(bills)} bills={bills.bill_id.nunique()} members={len(members)}")
    pd.concat(B, ignore_index=True).to_csv(out / "bills_all.csv", index=False)
    pd.concat(M, ignore_index=True).to_csv(out / "members_all.csv", index=False)
    for k, v in C.items():
        pd.concat(v, ignore_index=True).to_csv(out / f"scorecard_{k}.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
