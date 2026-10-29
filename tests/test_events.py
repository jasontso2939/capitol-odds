"""Milestones on the tracking chart (site/data/events.js) must agree with each bill's outcome."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js(name):
    t = (ROOT / "site/data" / name).read_text()
    return json.loads(t[t.index("{"): t.rstrip().rstrip(";").rindex("}") + 1])


def test_outcomes_match_governor_events():
    T, E = _js("tracking.js"), _js("events.js")["events"]
    ci = {c: i for i, c in enumerate(T["cols"])}
    for r in T["rows"]:
        codes = [e[1] for e in E.get(r[ci["bill_id"]], [])]
        if r[ci["outcome"]] == "signed":
            assert "sg" in codes, r[:2]
        if r[ci["outcome"]] == "vetoed":
            assert "vt" in codes, r[:2]
        if r[ci["outcome"]] in ("not_enacted", "pending"):
            assert "sg" not in codes and "vt" not in codes, r[:2]


def test_events_in_order_with_votes():
    E = _js("events.js")["events"]
    for b, ev in E.items():
        days = [e[0] for e in ev]
        assert days == sorted(days), b
        for e in ev:
            if len(e) == 4:
                assert e[2] >= 0 and e[3] >= 0, (b, e)


def test_sb40_2025_history():
    """Checked against SB 40's history on leginfo: Senate Health 11-0, suspense, Senate floor 37-0,
    Assembly floor 79-0, signed."""
    E = _js("events.js")
    if E["session"] != 2025:
        return
    ev = E["events"]["SB40"]
    assert [e[1] for e in ev] == ["pc", "su", "ap", "ps", "pc", "ap", "pa", "cc", "gv", "sg"]
    assert ev[0][2:] == [11, 0] and ev[3][2:] == [37, 0] and ev[6][2:] == [79, 0]
