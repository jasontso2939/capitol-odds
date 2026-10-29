"""Checks on committee rosters, leadership and member votes.

The first group reads the committed outputs in data/processed and always runs. The second
rebuilds from the raw export and is skipped when it has not been downloaded.
"""
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/pubinfo_2025"
P = ROOT / "data/processed"


@pytest.fixture(scope="module")
def mem():
    return pd.read_csv(P / "committee_membership.csv")


@pytest.fixture(scope="module")
def chk():
    return pd.read_csv(P / "committee_roster_check.csv").fillna("")


def test_every_committee_year_has_one_regular_chair_at_a_time(mem):
    # The 2007-08 export has no roll order (MEMBER_ORDER is empty), so chairs cannot be read
    # from roll calls for those two years; every later year must have one.
    reg = mem[(mem.status == "regular member") & (mem.year >= 2009)]
    for (code, year), g in reg.groupby(["committee_code", "year"]):
        assert (g.role == "Chair").sum() >= 1, (code, year)


def test_rosters_agree_with_archived_web_pages(chk):
    explained = chk.difference.isin(["identical", "temporary substitute(s) sat in on that hearing date"])
    assert len(chk) >= 100
    assert explained.mean() >= 0.9
    assert chk.chair_match.mean() >= 0.95
    assert chk.vice_match.mean() >= 0.95


@pytest.mark.parametrize("committee,year,member,role", [
    # each confirmed on the committee's own web page (live or Internet Archive copy)
    ("Assembly Appropriations", 2025, "Sanchez", "Vice Chair"),
    ("Assembly Appropriations", 2026, "Hoover", "Vice Chair"),
    ("Assembly Appropriations", 2026, "Wicks", "Chair"),
    ("Senate Appropriations", 2025, "Caballero", "Chair"),
    ("Senate Appropriations", 2026, "Cervantes", "Chair"),
    ("Assembly Education", 2025, "Muratsuchi", "Chair"),
    ("Assembly Education", 2026, "Patel", "Chair"),
    ("Senate Budget and Fiscal Review", 2025, "Wiener", "Chair"),
    ("Senate Budget and Fiscal Review", 2026, "Laird", "Chair"),
    ("Assembly Appropriations", 2017, "Gonzalez Fletcher", "Chair"),
    ("Assembly Appropriations", 2022, "Holden", "Chair"),
    ("Senate Appropriations", 2017, "Lara", "Chair"),
    ("Senate Appropriations", 2019, "Portantino", "Chair"),
])
def test_known_chairs_by_year(mem, committee, year, member, role):
    row = mem[(mem.committee == committee) & (mem.year == year) & (mem.member == member)]
    assert len(row) == 1 and row.role.iloc[0] == role


def test_midyear_change_is_dated(mem):
    """Senate Appropriations changed chairs between its January and April 2026 hearings."""
    h = mem[(mem.committee == "Senate Appropriations") & (mem.year == 2026)].set_index("member").leadership.fillna("")
    assert "2026-01-22" in h["Caballero"] and "2026-04-13" in h["Cervantes"]


raw = pytest.mark.skipif(not (RAW / "BILL_DETAIL_VOTE_TBL.dat").exists(), reason="vote tables not extracted")


@raw
def test_member_votes_add_up_to_official_tallies():
    """Per-member rows must reproduce the AYES and NOES on every committee roll call."""
    from calleg import committees as C
    v = C.committee_votes(RAW)
    s = C._read(RAW, "BILL_SUMMARY_VOTE_TBL", C.SUMMARY_COLS)
    s = s[s.LOCATION_CODE.str.match(r"^C[XS]\d")]
    key = ["BILL_ID", "committee_code", "vote_time", "vote_seq", "motion_id"]
    got = (v.assign(y=v.vote == "yes", n=v.vote == "no").groupby(key)[["y", "n"]].sum().reset_index())
    s = s.rename(columns={"LOCATION_CODE": "committee_code", "VOTE_DATE_TIME": "vote_time",
                          "VOTE_DATE_SEQ": "vote_seq", "MOTION_ID": "motion_id"})
    j = got.merge(s, on=key)
    assert len(j) == len(got)   # every roll call has an official tally (13,863 in the 2026-10 export)
    agree = (j.y == j.AYES.astype(int)) & (j.n == j.NOES.astype(int))
    assert agree.all()


@raw
def test_each_roll_call_has_one_chair_slot():
    from calleg import committees as C
    v = C.committee_votes(RAW)
    first = v[v.roll_order == 1].groupby(["BILL_ID", "committee_code", "vote_time", "vote_seq", "motion_id"]).size()
    assert (first == 1).all()


def test_renamed_committees_keep_one_history(mem):
    """A renamed committee appears under its current name, with the old name for the years it applied.
    Each rename is a single code whose old name ends the year before the new one starts."""
    lin = pd.read_csv(ROOT / "data/reference/committee_lineage.csv")
    for r in lin[lin.relation == "renamed"].itertuples():
        g = mem[mem.committee == r.current_name]
        assert set(g.committee_code) == {r.code}, r
        old, new = g[g.name_then == r.name].year, g[g.name_then == r.current_name].year
        assert len(old) and len(new) and old.max() < new.min(), r
        assert not (mem.committee == r.name).any()          # never listed separately
