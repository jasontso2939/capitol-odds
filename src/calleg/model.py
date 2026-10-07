"""Counting rules for the scorecard.

Every rule lives in this file so the numbers can be audited and tested.
See docs/METHODOLOGY.md for the reasoning behind each choice.

Input is one row per (bill, lead author). A bill with two lead authors has
two rows. `is_first_listed` marks the author listed first on the bill.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# all_leads: every lead author gets credit (leginfo's "Lead Authors" field).
# first_listed: only the first-listed author gets credit (what bulk exports show).
METHODS = ("all_leads", "first_listed")
# session: whole 2025-26 session. 2025 / 2026: one calendar slice of it.
SCOPES = ("session", 2025, 2026)


def load_bills(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"action_year": "Int64"})
    for col in ("is_first_listed", "is_joint"):
        df[col] = df[col].astype(bool)
    return df


def load_members(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _competition_rank(s: pd.Series) -> pd.Series:
    """1, 2, 2, 4 style ranking: ties share the best rank. Higher value ranks first."""
    return s.rank(ascending=False, method="min").astype(int)


def scorecard(
    bills: pd.DataFrame,
    members: pd.DataFrame,
    method: str = "all_leads",
    scope: str | int = "session",
) -> pd.DataFrame:
    """Return one row per member with counts, success rate and ranks.

    Definitions
    - introduced: bills where the member is a counted lead author. In a
      year scope, only bills filed that year (Dec 2024 pre-files count as 2025).
    - signed / vetoed: outcome of those bills. In a year scope, by the year
      of the Governor's action.
    - sent: signed + vetoed. Every bill presented was acted on.
    - rate: signed / introduced, as a percent rounded to 1 decimal. In a year
      scope it is a cohort rate: of the bills filed that year, the share
      signed at any point.
    """
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")

    b = bills[bills["is_first_listed"]] if method == "first_listed" else bills

    rows = []
    for m in members.itertuples():
        mine = b[b["member"] == m.member]
        filed = mine if scope == "session" else mine[mine["filed_year"] == scope]
        acted = mine if scope == "session" else mine[mine["action_year"] == scope]
        introduced = len(filed)
        signed = int((acted["outcome"] == "signed").sum())
        vetoed = int((acted["outcome"] == "vetoed").sum())
        cohort_signed = int((filed["outcome"] == "signed").sum())
        rows.append(
            {
                "member": m.member,
                "full_name": m.full_name,
                "party": m.party,
                "district": m.district,
                "introduced": introduced,
                "sent": signed + vetoed,
                "signed": signed,
                "vetoed": vetoed,
                "rate": round(100 * cohort_signed / introduced, 1) if introduced else 0.0,
            }
        )
    t = pd.DataFrame(rows)
    t["rank_signed"] = _competition_rank(t["signed"])
    t["rank_rate"] = _competition_rank(t["rate"])
    for key in ("signed", "rate"):
        r = t[t["party"] == "R"][key]
        t.loc[t["party"] == "R", f"rank_r_{key}"] = _competition_rank(r)
    return t.sort_values(["rank_signed", "rank_rate", "member"]).reset_index(drop=True)


def party_summary(t: pd.DataFrame) -> pd.DataFrame:
    g = t.groupby("party").agg(
        members=("member", "count"),
        introduced=("introduced", "sum"),
        signed=("signed", "sum"),
        vetoed=("vetoed", "sum"),
    )
    g["avg_signed"] = (g["signed"] / g["members"]).round(1)
    g["combined_rate"] = (100 * g["signed"] / g["introduced"]).round(1)
    return g
