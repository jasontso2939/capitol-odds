"""Bill-level features for trend analysis and outcome prediction.

One row per regular-session Assembly or Senate bill. Prediction features are limited
to what is known at introduction or first committee referral, so the model never sees
the outcome it is predicting.
"""
from __future__ import annotations

import csv
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from .pipeline import read_table, build

def committee_codes(raw: Path) -> pd.DataFrame:
    """Committee codes for one session with full names, from that session's LOCATION_CODE_TBL.

    Codes are reassigned between sessions, so names (not codes) are what carry across years."""
    from .committees import committee_names
    c = committee_names(raw)
    c["kind"] = "policy"
    c.loc[c.committee.str.endswith(" Appropriations"), "kind"] = "appropriations"
    c.loc[c.committee.str.endswith(" Rules"), "kind"] = "rules"
    return c


def intro_text_stats(raw: Path, zip_path: Path, out_csv: Path) -> pd.DataFrame:
    """Length of each bill's introduced text and whether it is intent language only (a spot bill).

    Reads only the introduced versions from the session zip. Cached to out_csv.
    """
    if out_csv.exists():
        return pd.read_csv(out_csv)
    v = read_table(raw, "BILL_VERSION_TBL", ["BILL_ID", "BILL_VERSION_ACTION", "BILL_XML"])
    v = v[v.BILL_ID.str.match(r"^\d{9}(AB|SB)\d+$") & (v.BILL_VERSION_ACTION == "Introduced")]
    z = zipfile.ZipFile(zip_path)
    names = set(z.namelist())
    rows = []
    for bid, lob in zip(v.BILL_ID, v.BILL_XML):
        if lob not in names:
            continue
        x = z.read(lob).decode("utf-8", "replace")
        body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
        intent = bool(re.search(r"intent of the Legislature to (enact|subsequently enact)", body, re.I))
        rows.append((bid, len(body), int(intent)))
    df = pd.DataFrame(rows, columns=["BILL_ID", "body_chars", "intent_only"])
    df.to_csv(out_csv, index=False)
    return df


def filing_window(d: pd.Timestamp) -> str:
    if pd.isna(d):
        return "unknown"
    m, day = d.month, d.day
    if m in (12, 1):   # December pre-files and January
        return "early (Dec-Jan)"
    if m == 2 and day <= 14:
        return "Feb 1-14"
    if m == 2:
        return "Feb 15-deadline"
    return "late (rule waiver)"


def build_features(raw: str | Path, zip_path: str | Path | None = None,
                   intro_cache: str | Path | None = None) -> pd.DataFrame:
    raw = Path(raw)
    author_rows, members = build(raw)
    bt = read_table(raw, "BILL_TBL")
    bt = bt[bt.MEASURE_TYPE.isin(["AB", "SB"]) & (bt.SESSION_NUM == "0")].copy()
    bt["bill_id"] = bt.MEASURE_TYPE + bt.MEASURE_NUM
    bt["origin"] = bt.MEASURE_TYPE.map({"AB": "Assembly", "SB": "Senate"})

    h = read_table(raw, "BILL_HISTORY_TBL")
    h = h[h.BILL_ID.isin(bt.BILL_ID)].copy()
    h["d"] = pd.to_datetime(h.ACTION_DATE.str[:10])
    h["seq"] = pd.to_numeric(h.ACTION_SEQUENCE, errors="coerce")
    h["a"] = h.ACTION.fillna("").str.replace(r"\s+", " ", regex=True)
    h = h.sort_values(["BILL_ID", "d", "seq"])

    cc = committee_codes(raw)
    name_of = cc.set_index("LOCATION_CODE").committee
    appr = {house: cc[(cc.kind == "appropriations") & (cc.house == house)].LOCATION_CODE.tolist()
            for house in ("Assembly", "Senate")}
    non_policy = set(cc[cc.kind != "policy"].LOCATION_CODE)

    loc = h.TERNARY_LOCATION.fillna("")
    f = pd.DataFrame(index=bt.BILL_ID)
    for house, codes in appr.items():
        inA = h[loc.isin(codes)]
        f[f"appr_{house}"] = f.index.isin(inA.BILL_ID)
        f[f"susp_{house}"] = f.index.isin(inA[inA.a.str.contains("suspense")].BILL_ID)
    pol = h[h.TERNARY_LOCATION.str.match(r"^C[SX]\d+$", na=False) & ~h.TERNARY_LOCATION.isin(non_policy)]
    first_pol = pol.groupby("BILL_ID").TERNARY_LOCATION.first()
    f["first_policy_code"] = first_pol
    f["policy_area"] = first_pol.map(name_of)
    f["passed_origin"] = f.index.isin(h[h.a.str.contains(r"Passed\..*Ordered to the (?:Senate|Assembly)")].BILL_ID)
    f = f.reset_index()

    m = bt[["BILL_ID", "bill_id", "origin", "CURRENT_LOCATION"]].merge(f, on="BILL_ID", how="left")
    first = author_rows[author_rows.is_first_listed][["session", "bill_id", "member", "outcome", "introduced",
                                                      "filed_year", "action_year", "title", "is_budget"]]
    m = m.merge(first, on="bill_id", how="inner")  # legislator-authored only
    mem = members[members.member.notna()].drop_duplicates("member")[["member", "party", "chamber"]]
    mem = mem.assign(party=mem.party.map({"DEM": "D", "REP": "R"}).fillna(mem.party))
    m = m.merge(mem, on="member", how="left")
    # person key that carries across sessions (the short author name alone can be shared by different people)
    lg = read_table(raw, "LEGISLATOR_TBL", ["AUTHOR_NAME", "FIRST_NAME", "LAST_NAME"]).dropna(subset=["AUTHOR_NAME"])
    norm = lambda s: s.fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.lower().str.strip()
    lg["person"] = norm(lg.LAST_NAME).str.split().str[0] + "|" + norm(lg.FIRST_NAME).str.split().str[0]
    m["person"] = m.member.map(lg.drop_duplicates("AUTHOR_NAME").set_index("AUTHOR_NAME").person).fillna(m.member)
    m["signed"] = m.outcome == "signed"
    m["died_in"] = np.where((m.outcome == "not_enacted") & m.CURRENT_LOCATION.isin(appr["Assembly"]), "Assembly Appropriations",
                    np.where((m.outcome == "not_enacted") & m.CURRENT_LOCATION.isin(appr["Senate"]), "Senate Appropriations", None))

    # introduced-version flags and authors (known at introduction)
    v = read_table(raw, "BILL_VERSION_TBL", ["BILL_VERSION_ID", "BILL_ID", "BILL_VERSION_ACTION", "SUBJECT",
                                             "APPROPRIATION", "FISCAL_COMMITTEE", "LOCAL_PROGRAM",
                                             "URGENCY", "TAXLEVY", "VOTE_REQUIRED"])
    vi = v[v.BILL_VERSION_ACTION == "Introduced"].drop_duplicates("BILL_ID")
    for c in ["APPROPRIATION", "FISCAL_COMMITTEE", "LOCAL_PROGRAM", "URGENCY", "TAXLEVY"]:
        vi[c.lower()] = vi[c].fillna("").str.lower().eq("yes")
    vi["supermajority"] = vi.VOTE_REQUIRED.fillna("").str.contains("Two Thirds|Four Fifths|Seventy")
    vi = vi.rename(columns={"SUBJECT": "intro_subject", "BILL_VERSION_ID": "intro_version"})
    m = m.merge(vi[["BILL_ID", "intro_version", "intro_subject", "appropriation", "fiscal_committee",
                    "local_program", "urgency", "taxlevy", "supermajority"]], on="BILL_ID", how="left")

    # latest-version flags (used for descriptive trends, not for prediction)
    latest = bt[["BILL_ID", "LATEST_BILL_VERSION_ID"]].merge(
        v.drop(columns=["BILL_ID"]), left_on="LATEST_BILL_VERSION_ID", right_on="BILL_VERSION_ID")
    for c in ["APPROPRIATION", "LOCAL_PROGRAM", "URGENCY", "TAXLEVY"]:
        latest[c.lower() + "_latest"] = latest[c].fillna("").str.lower().eq("yes")
    latest["supermajority_latest"] = latest.VOTE_REQUIRED.fillna("").str.contains("Two Thirds|Four Fifths|Seventy")
    m = m.merge(latest[["BILL_ID", "LATEST_BILL_VERSION_ID"] + [c for c in latest if c.endswith("_latest")]],
                on="BILL_ID", how="left")

    au_all = read_table(raw, "BILL_VERSION_AUTHORS_TBL")
    au_all = au_all[au_all.TYPE == "Legislator"]
    au_all["party"] = au_all.NAME.map(mem.set_index("member").party)
    co_l = au_all[au_all.BILL_VERSION_ID.isin(m.LATEST_BILL_VERSION_ID) & au_all.CONTRIBUTION.isin(["COAUTHOR", "PRINCIPAL_COAUTHOR"])]
    ld_l = au_all[au_all.BILL_VERSION_ID.isin(m.LATEST_BILL_VERSION_ID) & (au_all.CONTRIBUTION == "LEAD_AUTHOR")]
    m["n_coauthors_latest"] = m.LATEST_BILL_VERSION_ID.map(co_l.groupby("BILL_VERSION_ID").size()).fillna(0).astype(int)
    cpl = co_l.groupby("BILL_VERSION_ID").party.agg(lambda s: set(s.dropna()))
    m["cross_party_coauthor_latest"] = [bool(cpl.get(vid, set()) - {p}) if p in ("D", "R") else False
                                        for vid, p in zip(m.LATEST_BILL_VERSION_ID, m.party)]
    lpl = ld_l.groupby("BILL_VERSION_ID").party.agg(lambda s: set(s.dropna()))
    m["n_leads_latest"] = m.LATEST_BILL_VERSION_ID.map(ld_l.groupby("BILL_VERSION_ID").size()).fillna(1).astype(int)
    m["lead_structure_latest"] = np.select(
        [m.n_leads_latest == 1, [len(lpl.get(v_, set())) > 1 for v_ in m.LATEST_BILL_VERSION_ID]],
        ["Solo lead author", "Bipartisan joint leads"], "Same-party joint leads")

    au = au_all[au_all.BILL_VERSION_ID.isin(m.intro_version)]
    leads = au[au.CONTRIBUTION == "LEAD_AUTHOR"]
    co = au[au.CONTRIBUTION.isin(["COAUTHOR", "PRINCIPAL_COAUTHOR"])]
    m["n_coauthors_intro"] = m.intro_version.map(co.groupby("BILL_VERSION_ID").size()).fillna(0).astype(int)
    m["n_leads_intro"] = m.intro_version.map(leads.groupby("BILL_VERSION_ID").size()).fillna(1).astype(int)
    co_parties = co.groupby("BILL_VERSION_ID").party.agg(lambda s: set(s.dropna()))
    lead_parties = leads.groupby("BILL_VERSION_ID").party.agg(lambda s: set(s.dropna()))
    m["cross_party_coauthor"] = [bool(co_parties.get(vid, set()) - {p}) if p in ("D", "R") else False
                                 for vid, p in zip(m.intro_version, m.party)]
    m["cross_party_joint_lead"] = [len(lead_parties.get(vid, set())) > 1 for vid in m.intro_version]

    m["intro_date"] = pd.to_datetime(m.introduced)
    m["filing_window"] = m.intro_date.map(filing_window)
    if zip_path is not None and Path(zip_path).exists() or (intro_cache and Path(intro_cache).exists()):
        it = intro_text_stats(raw, Path(zip_path) if zip_path else None, Path(intro_cache))
        m = m.merge(it, on="BILL_ID", how="left")
        m["spot_bill"] = (m.intent_only == 1) & (m.body_chars < 3000)
    else:
        m["spot_bill"] = False
    return m.drop(columns=["CURRENT_LOCATION"])
