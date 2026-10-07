"""Check the counting rules against the real 2025-26 data.

`scorecard()` is recomputed here with plain Python loops (no pandas groupby, no shared code)
for every member, both methods and all three periods. Runs on the committed processed data,
so it needs no download.
"""
from pathlib import Path

import pandas as pd
import pytest

from calleg import scorecard

ROOT = Path(__file__).resolve().parents[1]
BILLS = pd.read_csv(ROOT / "data/processed/bills_all.csv", dtype={"action_year": "Int64"})
BILLS = BILLS[~BILLS.is_budget].drop(columns=["author_house"])
MEMBERS = pd.read_csv(ROOT / "data/processed/members_all.csv")


def oracle(method, scope):
    out = {}
    for m in MEMBERS.member:
        intro = signed = vetoed = cohort_signed = 0
        for r in BILLS.itertuples():
            if r.member != m or (method == "first_listed" and not r.is_first_listed):
                continue
            if scope == "session" or r.filed_year == scope:
                intro += 1
                cohort_signed += r.outcome == "signed"
            if scope == "session" or (pd.notna(r.action_year) and r.action_year == scope):
                signed += r.outcome == "signed"
                vetoed += r.outcome == "vetoed"
        out[m] = (intro, signed, vetoed, round(100 * cohort_signed / intro, 1) if intro else 0.0)
    return out


@pytest.mark.parametrize("method", ["all_leads", "first_listed"])
@pytest.mark.parametrize("scope", ["session", 2025, 2026])
def test_counts_match_independent_recount(method, scope):
    got = scorecard(BILLS, MEMBERS, method, scope).set_index("member")
    for m, (intro, signed, vetoed, rate) in oracle(method, scope).items():
        row = got.loc[m]
        assert (row.introduced, row.signed, row.vetoed, row.rate) == (intro, signed, vetoed, rate), m
        assert row.sent == signed + vetoed


def test_ranks_are_competition_ranks():
    t = scorecard(BILLS, MEMBERS)
    for _, r in t.iterrows():
        assert r.rank_signed == 1 + (t.signed > r.signed).sum()
        assert r.rank_rate == 1 + (t.rate > r.rate).sum()


def test_republican_rank_is_within_party():
    t = scorecard(BILLS, MEMBERS)
    rep = t[t.party == "R"]
    for _, r in rep.iterrows():
        assert r.rank_r_signed == 1 + (rep.signed > r.signed).sum()


def test_first_listed_never_exceeds_all_leads():
    a = scorecard(BILLS, MEMBERS, "all_leads").set_index("member")
    f = scorecard(BILLS, MEMBERS, "first_listed").set_index("member").loc[a.index]
    assert (f.introduced <= a.introduced).all() and (f.signed <= a.signed).all()


def test_invalid_arguments_raise():
    with pytest.raises(ValueError):
        scorecard(BILLS, MEMBERS, "nope")
    with pytest.raises(ValueError):
        scorecard(BILLS, MEMBERS, "all_leads", 1999)
