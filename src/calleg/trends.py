"""Statewide trend tables: where bills die, what predicts it, and why the Governor vetoes.

Input is the bill-level frame from features.build_features. Every table is plain
counts and percentages, so each figure can be checked by hand.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

VETO_REASONS = {
    "Cost or belongs in the budget": r"budget process|not accounted for|General Fund|unfunded|cost pressure|significant[^.]{0,40}costs|ongoing costs|costs? (?:that are )?not (?:included|accounted)|without (?:an identified|a clear) (?:funding )?source|fiscal",
    "Duplicative or unnecessary": r"duplicat|redundant|unnecessary|not (?:convinced|persuaded)[^.]{0,40}necessary|already (?:has|have|conducts|permits|maintain|includes|grants|in place|exist|established|provides|requires|underway)|existing law (?:already|appears sufficient|effectively)",
    "Defers to an agency, executive or bargaining process": r"collective bargaining|rulemaking|regulatory process|advisory group|working group|Collaborative|executive order|study is complete|ongoing work|work (?:is|remains) ongoing|premature|administratively|task force|stakeholder process",
    "Policy, legal or implementation concerns": r"concern|undermine|conflict|unintended|unworkable|burdensome|precedent|due process|weaken|unclear|confusion|disrupt",
}
REPEAT_VETO = r"vetoed (?:a |an )?(?:similar|nearly identical|identical|substantially similar)|(?:last year|two years ago|previously),? I vetoed|I vetoed[^.]{0,60}(?:last year|in 20\d\d|previously)"


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def _rec(df):
    return df.replace({np.nan: None}).to_dict(orient="records")


def appropriations_by_party(m: pd.DataFrame) -> list[dict]:
    rows = []
    for house in ["Assembly", "Senate"]:
        for stage, sel in [("House of origin", m.origin == house), ("Second house", m.origin != house)]:
            for party in ["D", "R"]:
                s = m[m[f"appr_{house}"] & sel & (m.party == party)]
                died = int((s.died_in == f"{house} Appropriations").sum())
                rows.append({"committee": f"{house} Appropriations", "stage": stage, "party": party,
                             "sent": len(s), "died": died, "pct_died": _pct(died, len(s))})
    return rows


def where_failed_bills_died(m: pd.DataFrame) -> list[dict]:
    rows = []
    for party in ["D", "R"]:
        f = m[(m.party == party) & (m.outcome == "not_enacted")]
        for place in ["Assembly Appropriations", "Senate Appropriations"]:
            n = int((f.died_in == place).sum())
            rows.append({"party": party, "where": place, "bills": n, "pct": _pct(n, len(f))})
        n = int(f.died_in.isna().sum())
        rows.append({"party": party, "where": "Elsewhere (policy committee, floor, desk)", "bills": n, "pct": _pct(n, len(f))})
    return rows


def policy_area_risk(m: pd.DataFrame, min_bills: int = 25) -> list[dict]:
    r = m[(m.appr_Assembly | m.appr_Senate) & m.policy_area.notna()]
    g = r.groupby("policy_area").agg(sent=("signed", "size"), died=("died_in", lambda s: s.notna().sum()),
                                     signed=("signed", "sum")).reset_index()
    g["pct_died"] = (100 * g.died / g.sent).round(1)
    g["pct_signed"] = (100 * g.signed / g.sent).round(1)
    return _rec(g[g.sent >= min_bills].sort_values("pct_died", ascending=False))


def fiscal_flags(m: pd.DataFrame) -> list[dict]:
    r = m[m.appr_Assembly | m.appr_Senate]
    rows = []
    for col, label in [("taxlevy_latest", "Tax levy"), ("appropriation_latest", "Makes an appropriation"),
                       ("local_program_latest", "State-mandated local program"),
                       ("urgency_latest", "Urgency clause"), ("supermajority_latest", "Two-thirds vote")]:
        for val in [True, False]:
            s = r[r[col] == val]
            rows.append({"flag": label, "has_flag": val, "bills": len(s),
                         "pct_died_appr": _pct(s.died_in.notna().sum(), len(s)), "pct_signed": _pct(s.signed.sum(), len(s))})
    return rows


def coalition(m: pd.DataFrame) -> dict:
    co = m.assign(bin=pd.cut(m.n_coauthors_latest, [-1, 0, 2, 5, 10, 1000], labels=["0", "1-2", "3-5", "6-10", "11+"]))
    by_n = co.groupby("bin", observed=True).signed.agg(["size", "sum"]).reset_index()
    by_n["pct_signed"] = (100 * by_n["sum"] / by_n["size"]).round(1)
    cross = m[m.party.isin(["D", "R"])].groupby(["party", "cross_party_coauthor_latest"]).signed.agg(["size", "sum"]).reset_index()
    cross["pct_signed"] = (100 * cross["sum"] / cross["size"]).round(1)
    leads = m.groupby(["party", "lead_structure_latest"]).signed.agg(["size", "sum"]).reset_index()
    leads["pct_signed"] = (100 * leads["sum"] / leads["size"]).round(1)
    ren = {"size": "bills", "sum": "signed"}
    return {"by_coauthors": _rec(by_n.rename(columns=ren | {"bin": "coauthors"})),
            "cross_party": _rec(cross.rename(columns=ren | {"cross_party_coauthor_latest": "has_other_party_coauthor"})),
            "lead_structure": _rec(leads.rename(columns=ren | {"lead_structure_latest": "structure"}))}


def timing(m: pd.DataFrame) -> list[dict]:
    g = m.groupby(["filed_year", "filing_window"]).signed.agg(["size", "sum"]).reset_index()
    g["pct_signed"] = (100 * g["sum"] / g["size"]).round(1)
    return _rec(g[g.filing_window != "late (rule waiver)"].rename(columns={"size": "bills", "sum": "signed"}))


def second_house(m: pd.DataFrame) -> list[dict]:
    rows = []
    for origin, other in [("Assembly", "Senate"), ("Senate", "Assembly")]:
        p = m[(m.origin == origin) & m.passed_origin]
        rows.append({"passed": origin, "bills": len(p), "pct_signed": _pct(p.signed.sum(), len(p)),
                     "pct_vetoed": _pct((p.outcome == "vetoed").sum(), len(p)),
                     "pct_died_other_appr": _pct((p.died_in == f"{other} Appropriations").sum(), len(p)),
                     "pct_died_other_elsewhere": _pct(((p.outcome == "not_enacted") & (p.died_in != f"{other} Appropriations")).sum(), len(p))})
    return rows


def spot_bills(m: pd.DataFrame) -> list[dict]:
    g = m.groupby(["party", "spot_bill"]).signed.agg(["size", "sum"]).reset_index()
    g["pct_signed"] = (100 * g["sum"] / g["size"]).round(1)
    return _rec(g.rename(columns={"size": "bills", "sum": "signed"}))


def veto_rate_by_area(m: pd.DataFrame, min_sent: int = 20) -> list[dict]:
    s = m[m.outcome.isin(["signed", "vetoed"])]
    g = s.groupby("policy_area").outcome.agg(sent="size", vetoed=lambda x: (x == "vetoed").sum()).reset_index()
    g["pct_vetoed"] = (100 * g.vetoed / g.sent).round(1)
    return _rec(g[g.sent >= min_sent].sort_values("pct_vetoed", ascending=False))


def veto_reasons(raw: str | Path, m: pd.DataFrame) -> dict:
    raw = Path(raw)
    v = pd.read_csv(raw / "VETO_MESSAGE_TBL.dat", sep="\t", header=None, quotechar="`",
                    names=["BILL_ID", "date", "lob", "uid", "ts"])
    v = v[v.BILL_ID.isin(m.BILL_ID)].copy()
    def body(lob):
        t = re.sub(r"\s+", " ", (raw / lob).read_text(errors="replace"))
        t = re.sub(r"^.*?without my signature\.", "", t)
        return re.sub(r"(For (these|this) reason.*|Sincerely.*)$", "", t).strip()
    v["body"] = v.lob.map(body)
    for k, pat in VETO_REASONS.items():
        v[k] = v.body.str.contains(pat, case=False, regex=True)
    cats = list(VETO_REASONS)
    v["primary"] = np.select([v[k] for k in cats], cats, "Policy disagreement (other)")
    v["repeat"] = v.body.str.contains(REPEAT_VETO, case=False, regex=True)
    v = v.merge(m[["BILL_ID", "bill_id", "party"]], on="BILL_ID", how="left")
    summary = [{"reason": c, "any_mention": int(v[c].sum()), "primary": int((v.primary == c).sum())} for c in cats]
    summary.append({"reason": "Policy disagreement (other)", "any_mention": None,
                    "primary": int((v.primary == "Policy disagreement (other)").sum())})
    return {"messages": len(v), "vetoed_bills": int((m.outcome == "vetoed").sum()), "summary": summary,
            "repeat": _rec(v[v.repeat][["bill_id", "party"]])}


def all_trends(m: pd.DataFrame, raw: str | Path) -> dict:
    return {
        "appropriations_by_party": appropriations_by_party(m),
        "where_failed_bills_died": where_failed_bills_died(m),
        "policy_area_risk": policy_area_risk(m),
        "fiscal_flags": fiscal_flags(m),
        "coalition": coalition(m),
        "timing": timing(m),
        "second_house": second_house(m),
        "spot_bills": spot_bills(m),
        "veto_rate_by_area": veto_rate_by_area(m),
        "veto_reasons": veto_reasons(raw, m),
    }
