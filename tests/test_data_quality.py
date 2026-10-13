"""Data-quality checks on the full 2025-26 build. Skipped without the raw export."""
from pathlib import Path

import pandas as pd
import pytest

from calleg.pipeline import build

from calleg.sessions import raw_dir

RAW = raw_dir(2025)   # full download while current, session archive afterwards
pytestmark = pytest.mark.skipif(not ((RAW / "BILL_TBL.dat").exists() or (RAW / "BILL_TBL.dat.gz").exists()),
                                reason="2025-26 data not downloaded")


@pytest.fixture(scope="module")
def built():
    return build(RAW)


def test_vetoes_cover_official_status_and_extras_are_senate(built):
    bills, _ = built
    v = bills[bills.outcome == "vetoed"].drop_duplicates("bill_id")
    assert len(v) >= 213  # every CURRENT_STATUS 'Vetoed' AB/SB (213 in the 2026-10-06 export)
    # Senate vetoes keep status "In Floor Process" until the override vote, so history adds ~30.
    # Assembly vetoes always carry the 'Vetoed' status.
    assert (v.bill_id.str.startswith("SB").sum()) > (v.bill_id.str.startswith("AB").sum()) * 0.3


def test_signed_bills_have_chapter_dates_in_session(built):
    bills, _ = built
    s = bills[bills.outcome == "signed"]
    assert s.action_date.dropna().between("2025-01-01", "2026-12-31").all()


def test_introduced_dates_in_session_window(built):
    bills, _ = built
    assert bills.introduced.dropna().between("2024-12-02", "2026-12-31").all()


def test_no_bill_both_signed_and_vetoed(built):
    bills, _ = built
    assert not bills.groupby("bill_id").outcome.nunique().gt(1).any()


def test_chamber_sizes(built):
    _, m = built
    m = m[m.member.notna()]
    assert 80 <= (m.chamber == "Assembly").sum() <= 83 and 38 <= (m.chamber == "Senate").sum() <= 41


def test_seat_change_reference_is_known(built):
    _, m = built
    ref = pd.read_csv(Path(__file__).resolve().parents[1] / "data/reference/seat_changes.csv")
    assert set(ref.member) <= set(m.member)


def test_seat_change_reference_parses_and_flags_members(built):
    from calleg.build import prepare_members
    bills, m = built
    ref = pd.read_csv(Path(__file__).resolve().parents[1] / "data/reference/seat_changes.csv")
    assert list(ref.columns[:4]) == ["session", "district", "chamber", "member"]
    flagged = set(prepare_members(bills, m).query("partial_term").member)
    assert flagged == set(ref[ref.session == 2025].member)


def test_budget_bills_flagged(built):
    bills, _ = built
    b = bills[bills.is_budget]
    assert b.title.str.startswith("Budget Act").all() and len(b) > 0
