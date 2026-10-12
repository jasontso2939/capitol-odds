"""Committee rosters, chairs and member votes, from the Legislature's own roll calls.

Every committee roll call in BILL_DETAIL_VOTE_TBL lists every member of the
committee on that date, including members who did not vote (code ABS). The roll
is printed in a fixed order: chair first, vice chair second, then the other
members. So the vote record is a dated, official history of who sat on each
committee and who chaired it. Website rosters (live pages and Internet Archive
snapshots, see data/reference/committee_rosters_web.csv) are used only to check it.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

VOTE_COLS = ("BILL_ID LOCATION_CODE LEGISLATOR_NAME VOTE_DATE_TIME VOTE_DATE_SEQ VOTE_CODE MOTION_ID "
             "TRANS_UID TRANS_UPDATE MEMBER_ORDER SESSION_DATE SPEAKER").split()
SUMMARY_COLS = ("BILL_ID LOCATION_CODE VOTE_DATE_TIME VOTE_DATE_SEQ MOTION_ID AYES NOES ABSTAIN VOTE_RESULT "
                "TRANS_UID TRANS_UPDATE FILE_ITEM_NUM FILE_LOCATION DISPLAY_LINES SESSION_DATE").split()
LOC_COLS = ("SESSION_YEAR LOCATION_CODE LOCATION_TYPE CONSENT_CALENDAR_CODE DESCRIPTION LONG_DESCRIPTION "
            "ACTIVE_FLG TRANS_UID TRANS_UPDATE INACTIVE_FILE_FLG").split()
MOTION_COLS = "MOTION_ID MOTION_TEXT TRANS_UID TRANS_UPDATE".split()
# Roll-call names that differ from LEGISLATOR_TBL.AUTHOR_NAME
NAME_ALIASES = {"Weber": "Weber Pierson"}
CORE_SHARE = 0.5   # a member present on at least half of a committee's hearing dates in a year is a regular member


def _read(raw: Path, name: str, cols: list[str]) -> pd.DataFrame:
    return pd.read_csv(Path(raw) / f"{name}.dat", sep="\t", quotechar="`", header=None, names=cols,
                       na_values=["NULL"], keep_default_na=False, dtype=str, engine="c",
                       encoding="utf-8", encoding_errors="replace")


def committee_names(raw: str | Path) -> pd.DataFrame:
    loc = _read(raw, "LOCATION_CODE_TBL", LOC_COLS)
    loc = loc[loc.LOCATION_CODE.str.match(r"^C[XS]\d")].copy()
    loc["house"] = loc.LOCATION_CODE.str[1].map({"X": "Assembly", "S": "Senate"})
    loc["committee"] = loc.house + " " + loc.LONG_DESCRIPTION.str.replace("&", "and", regex=False)
    return loc[["LOCATION_CODE", "house", "committee"]].drop_duplicates("LOCATION_CODE")


def committee_votes(raw: str | Path) -> pd.DataFrame:
    """One row per member per committee roll call (bill, motion, date)."""
    raw = Path(raw)
    v = _read(raw, "BILL_DETAIL_VOTE_TBL", VOTE_COLS)
    v = v[v.LOCATION_CODE.str.match(r"^C[XS]\d")].copy()
    v["member"] = v.LEGISLATOR_NAME.replace(NAME_ALIASES)
    v["vote_date"] = v.VOTE_DATE_TIME.str[:10]
    v["year"] = v.vote_date.str[:4].astype(int)
    v["roll_order"] = pd.to_numeric(v.MEMBER_ORDER, errors="coerce").astype("Int64")
    v["vote"] = v.VOTE_CODE.map({"AYE": "yes", "NOE": "no", "ABS": "absent or not voting"})
    mo = _read(raw, "BILL_MOTION_TBL", MOTION_COLS)[["MOTION_ID", "MOTION_TEXT"]]
    key = ["BILL_ID", "LOCATION_CODE", "VOTE_DATE_TIME", "VOTE_DATE_SEQ", "MOTION_ID"]
    s = _read(raw, "BILL_SUMMARY_VOTE_TBL", SUMMARY_COLS)[key + ["VOTE_RESULT"]]
    v = v.merge(mo, on="MOTION_ID", how="left").merge(s.drop_duplicates(key), on=key, how="left")
    v = v.merge(committee_names(raw), on="LOCATION_CODE", how="left")
    v["bill_id"] = v.BILL_ID.str.replace(r"^\d{9}", "", regex=True)
    v["result"] = v.VOTE_RESULT.str.strip("()").str.lower()
    return v[["bill_id", "BILL_ID", "house", "LOCATION_CODE", "committee", "vote_date", "year", "VOTE_DATE_TIME",
              "VOTE_DATE_SEQ", "MOTION_ID", "MOTION_TEXT", "result", "member", "roll_order", "vote"]].rename(
        columns={"LOCATION_CODE": "committee_code", "MOTION_TEXT": "motion", "VOTE_DATE_TIME": "vote_time",
                 "VOTE_DATE_SEQ": "vote_seq", "MOTION_ID": "motion_id"})


def hearing_rosters(votes: pd.DataFrame) -> pd.DataFrame:
    """The roster printed on each committee hearing date: one row per committee, date and member.

    A member's position is the order most often printed that day (chair 1, vice chair 2)."""
    g = (votes.groupby(["committee_code", "committee", "house", "vote_date", "member"])
         .roll_order.agg(lambda s: s.mode().iloc[0]).reset_index())
    g["role"] = g.roll_order.map({1: "Chair", 2: "Vice Chair"}).fillna("Member")
    return g


def membership_by_year(votes: pd.DataFrame, legislators: pd.DataFrame | None = None) -> pd.DataFrame:
    """Committee membership for each calendar year, with chair and vice chair.

    present_share is the share of the committee's hearing dates that year on which the
    member was on the roll. Members under CORE_SHARE are kept and marked as partial
    (joined or left mid-year, or sat in temporarily)."""
    r = hearing_rosters(votes)
    r["year"] = r.vote_date.str[:4].astype(int)
    dates = r.groupby(["committee_code", "year"]).vote_date.nunique().rename("hearing_dates")
    m = (r.groupby(["committee_code", "committee", "house", "year", "member"])
         .agg(dates_on_roll=("vote_date", "nunique"), first_on_roll=("vote_date", "min"), last_on_roll=("vote_date", "max"),
              chair_dates=("role", lambda s: (s == "Chair").sum()), vice_dates=("role", lambda s: (s == "Vice Chair").sum()))
         .reset_index().join(dates, on=["committee_code", "year"]))
    m["present_share"] = (m.dates_on_roll / m.hearing_dates).round(3)
    m["role"] = "Member"
    m.loc[m.vice_dates > 0, "role"] = "Vice Chair"
    m.loc[m.chair_dates > 0, "role"] = "Chair"
    both = (m.chair_dates > 0) & (m.vice_dates > 0)
    m.loc[both, "role"] = "Chair and Vice Chair (changed)"
    m["status"] = (m.present_share >= CORE_SHARE).map({True: "regular", False: "partial"})
    if legislators is not None:
        m = m.merge(legislators, on="member", how="left")
    return m.sort_values(["house", "committee", "year", "dates_on_roll"], ascending=[True, True, True, False])


def chair_history(votes: pd.DataFrame) -> pd.DataFrame:
    """Each stretch of hearings under one chair and vice chair, in date order."""
    r = hearing_rosters(votes)
    lead = (r[r.role != "Member"].pivot_table(index=["committee_code", "committee", "house", "vote_date"],
                                              columns="role", values="member", aggfunc="first").reset_index())
    for c in ["Chair", "Vice Chair"]:
        if c not in lead:
            lead[c] = None
    lead = lead.sort_values(["committee_code", "vote_date"])
    key = lead.Chair.fillna("") + "|" + lead["Vice Chair"].fillna("")
    lead["run"] = (key != key.groupby(lead.committee_code).shift()).cumsum()
    out = (lead.groupby(["committee_code", "committee", "house", "run"])
           .agg(chair=("Chair", "first"), vice_chair=("Vice Chair", "first"), from_date=("vote_date", "min"),
                to_date=("vote_date", "max"), hearing_dates=("vote_date", "nunique")).reset_index().drop(columns="run"))
    return out


def member_vote_summary(votes: pd.DataFrame) -> pd.DataFrame:
    """Per member and committee: roll calls, yes, no, absent, and yes rate among votes cast."""
    g = votes.pivot_table(index=["member", "house", "committee"], columns="vote", values="bill_id",
                          aggfunc="size", fill_value=0).reset_index()
    for c in ["yes", "no", "absent or not voting"]:
        if c not in g:
            g[c] = 0
    g["roll_calls"] = g[["yes", "no", "absent or not voting"]].sum(axis=1)
    g["yes_rate_of_votes_cast"] = (g.yes / (g.yes + g.no)).round(3)
    return g.sort_values(["member", "house", "committee"])


SUPPORT_K = 20   # votes of "prior" weight when shrinking a support rate toward the overall yes rate


def _smoothed(yes: float, cast: float, prior: float, k: float = SUPPORT_K) -> float:
    return (yes + k * prior) / (cast + k)


def relationship_features(m: pd.DataFrame, raw: str | Path, votes: pd.DataFrame,
                          membership: pd.DataFrame) -> pd.DataFrame:
    """Bill-level features linking the author, the first policy committee and its members.

    Rosters come from the year the bill was introduced. Support rates use only committee
    votes dated before the bill's introduction, so no feature sees the bill's own future."""
    from calleg.pipeline import read_table
    raw = Path(raw)
    reg = membership[membership.status.isin(["regular", "regular member"])]
    roster = reg.groupby(["committee_code", "year"]).member.agg(set)
    chair = membership[membership.role == "Chair"].sort_values("dates_on_roll").groupby(["committee_code", "year"]).member.last()
    party_of = membership.dropna(subset=["party"]).drop_duplicates("member").set_index("member").party
    au = read_table(raw, "BILL_VERSION_AUTHORS_TBL")
    au = au[(au.TYPE == "Legislator") & au.BILL_VERSION_ID.isin(m.intro_version)]
    sponsors = au.groupby("BILL_VERSION_ID").NAME.agg(set)

    cast = votes[votes.vote.isin(["yes", "no"])].copy()
    cast["yes"] = (cast.vote == "yes").astype(int)
    lead_of = m.set_index("bill_id").member
    cast["author"] = cast.bill_id.map(lead_of)
    cast["author_party"] = cast.author.map(party_of)
    overall = cast.yes.mean()
    by_author = {a: g.sort_values("vote_date") for a, g in cast.groupby("author")}
    by_party = {p: g.sort_values("vote_date") for p, g in cast.groupby("author_party")}

    rows = []
    for r in m.itertuples():
        code, y, a, p = r.first_policy_code, int(r.filed_year), r.member, r.party
        mem_set = roster.get((code, y), set())
        sp = sponsors.get(r.intro_version, set())
        ch = chair.get((code, y))
        d0 = str(r.intro_date)[:10]
        ga = by_author.get(a)
        prior_a = ga[(ga.vote_date < d0) & ga.member.isin(mem_set) & (ga.bill_id != r.bill_id)] if ga is not None else None
        gp = by_party.get(p)
        prior_p = gp[(gp.vote_date < d0) & gp.member.isin(mem_set)] if gp is not None else None
        party_rate = _smoothed(prior_p.yes.sum(), len(prior_p), overall) if prior_p is not None else overall
        rows.append({
            "BILL_ID": r.BILL_ID,
            "committee_size": len(mem_set),
            "author_on_committee": a in mem_set,
            "author_chairs_committee": a == ch,
            "chair_same_party": party_of.get(ch) == p if ch else False,
            "sponsors_on_committee": len((sp - {a}) & mem_set),
            "author_party_share": (sum(party_of.get(x) == p for x in mem_set) / len(mem_set)) if mem_set else float("nan"),
            "members_prior_votes_on_author": 0 if prior_a is None else len(prior_a),
            "members_support_author": _smoothed(prior_a.yes.sum(), len(prior_a), party_rate) if prior_a is not None else party_rate,
            "members_support_party": party_rate,
        })
    return pd.DataFrame(rows)
