"""Checks across all five sessions (2017-18 to 2025-26).

The first group reads committed outputs. The second needs the session archive
(data/archive, from the session-archive branch) and is skipped without it.
"""
from pathlib import Path

import pandas as pd
import pytest

from calleg.sessions import SESSIONS, raw_dir, is_complete

ROOT = Path(__file__).resolve().parents[1]
BILLS = pd.read_csv(ROOT / "data/processed/bills_all.csv")
MEMBERS = pd.read_csv(ROOT / "data/processed/members_all.csv")


def test_every_session_is_present():
    assert sorted(BILLS.session.unique()) == list(SESSIONS)
    assert sorted(MEMBERS.session.unique()) == list(SESSIONS)


@pytest.mark.parametrize("session", [s for s in SESSIONS if is_complete(s)])
def test_session_sizes_are_plausible(session):
    b = BILLS[BILLS.session == session].drop_duplicates("bill_id")
    assert 3500 <= len(b) <= 5500                     # AB and SB introduced per session
    assert 100 <= (MEMBERS.session == session).sum() <= 130   # 120 seats plus mid-session changes
    assert set(b.filed_year) == {session, session + 1}
    signed = (b.outcome == "signed").mean()
    assert 0.2 <= signed <= 0.5


def test_one_name_per_person_within_a_session():
    """Spelling or married-name variants are merged (e.g. Kamlager / Kamlager-Dove in 2019-20)."""
    m = MEMBERS[MEMBERS.member.notna()]
    for (s, d), g in m.groupby(["session", "district"]):
        assert len(g) <= 2 or g.partial_term.all(), (s, d, list(g.member))


# Different people who share a seat's first name across sessions (not name changes)
DIFFERENT_PEOPLE = {("AD06", "kevin"),   # Kevin Kiley, then Kevin McCarty after redistricting
                   ("AD02", "jim"),     # Jim Nielsen (2008-12), then Jim Wood (2014-24)
                   ("AD36", "steve"),   # Steve Knight, then Steve Fox
                   ("AD49", "mike"),    # Mike Eng, then Mike Fong
                   ("AD63", "bill"),    # Bill Emmerson, then Bill Essayli
                   ("AD77", "brian"),   # Brian Jones, then Brian Maienschein
                   ("SD29", "bob"),     # Bob Margett, then Bob Huff
                   ("SD37", "john")}    # John Benoit, then John Moorlach


def test_name_changes_are_linked():
    """One person keeps one key across sessions even when the listed name changes
    (data/reference/name_changes.csv, checked by hand; person_aliases.csv links the keys)."""
    m = MEMBERS[MEMBERS.member.notna()].copy()
    m["first"] = m.full_name.str.split(",").str[-1].str.strip().str.split().str[0].str.lower()
    for (d, f), g in m.groupby(["district", "first"]):
        assert g.person.nunique() == 1 or (d, f) in DIFFERENT_PEOPLE, (d, f, sorted(g.person.unique()))
    nc = pd.read_csv(ROOT / "data/reference/name_changes.csv")
    changed = {p for p, g in m.groupby("person") if g.member.nunique() > 1}
    assert changed <= set(nc.person), f"new name change to check by hand: {changed - set(nc.person)}"
    for p in ["kamlager|sydney", "padilla|stephen", "weber|akilah", "boerner|tasha"]:
        assert m[m.person == p].session.nunique() >= 2


def test_pandemic_session_is_the_low_point():
    u = BILLS.drop_duplicates(["session", "bill_id"])
    rate = u.groupby("session").outcome.apply(lambda s: (s == "signed").mean())
    assert rate.idxmin() == 2019


archive = pytest.mark.skipif(not (ROOT / "data/archive/pubinfo_2017").exists(), reason="session archive not fetched")


def test_rollover_dates():
    import datetime as dt
    from calleg.sessions import session_for
    assert session_for(dt.date(2026, 11, 30)) == 2025
    assert session_for(dt.date(2026, 12, 7)) == 2027     # new session convenes in December
    assert session_for(dt.date(2027, 6, 1)) == 2027
    assert session_for(dt.date(2028, 9, 30)) == 2027
    assert not is_complete(2027, dt.date(2028, 9, 30)) and is_complete(2027, dt.date(2028, 10, 1))


@archive
@pytest.mark.parametrize("session", [s for s in SESSIONS if is_complete(s) and s < max(SESSIONS)])
def test_archived_votes_add_up_to_official_tallies(session):
    from calleg import committees as C
    raw = raw_dir(session)
    v = C.committee_votes(raw)
    s = C._read(raw, "BILL_SUMMARY_VOTE_TBL", C.SUMMARY_COLS)
    s = s[s.LOCATION_CODE.str.match(r"^C[XS]\d")].rename(columns={
        "LOCATION_CODE": "committee_code", "VOTE_DATE_TIME": "vote_time", "VOTE_DATE_SEQ": "vote_seq", "MOTION_ID": "motion_id"})
    key = ["BILL_ID", "committee_code", "vote_time", "vote_seq", "motion_id"]
    got = v.assign(y=v.vote == "yes", n=v.vote == "no").groupby(key)[["y", "n"]].sum().reset_index()
    j = got.merge(s, on=key)
    assert len(j) / len(got) > 0.99
    assert ((j.y == j.AYES.astype(int)) & (j.n == j.NOES.astype(int))).mean() > 0.99
