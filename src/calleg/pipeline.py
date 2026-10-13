"""Official-data pipeline: leginfo pubinfo export -> bill-author rows.

Input : data/raw/pubinfo_<year>/*.dat (tab-delimited, backtick-enclosed, NULL literal)
Output: one row per (bill, lead author) see docs/DATA_DICTIONARY.md for the schema
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

COLS = {
    "BILL_TBL": "BILL_ID SESSION_YEAR SESSION_NUM MEASURE_TYPE MEASURE_NUM MEASURE_STATE CHAPTER_YEAR CHAPTER_TYPE CHAPTER_SESSION_NUM CHAPTER_NUM LATEST_BILL_VERSION_ID ACTIVE_FLG TRANS_UID TRANS_UPDATE CURRENT_LOCATION CURRENT_SECONDARY_LOC CURRENT_HOUSE CURRENT_STATUS DAYS_31ST_IN_PRINT",
    "BILL_HISTORY_TBL": "BILL_ID BILL_HISTORY_ID ACTION_DATE ACTION TRANS_UID TRANS_UPDATE_DT ACTION_SEQUENCE ACTION_CODE ACTION_STATUS PRIMARY_LOCATION SECONDARY_LOCATION TERNARY_LOCATION END_STATUS",
    "BILL_VERSION_AUTHORS_TBL": "BILL_VERSION_ID TYPE HOUSE NAME CONTRIBUTION COMMITTEE_MEMBERS ACTIVE_FLG TRANS_UID TRANS_UPDATE PRIMARY_AUTHOR_FLG",
    "BILL_VERSION_TBL": "BILL_VERSION_ID BILL_ID VERSION_NUM BILL_VERSION_ACTION_DATE BILL_VERSION_ACTION REQUEST_NUM SUBJECT VOTE_REQUIRED APPROPRIATION FISCAL_COMMITTEE LOCAL_PROGRAM SUBSTANTIVE_CHANGES URGENCY TAXLEVY BILL_XML ACTIVE_FLG TRANS_UID TRANS_UPDATE",
    "LEGISLATOR_TBL": "DISTRICT SESSION_YEAR LEGISLATOR_NAME HOUSE_TYPE AUTHOR_NAME FIRST_NAME LAST_NAME MIDDLE_INITIAL NAME_SUFFIX NAME_TITLE WEB_NAME_TITLE PARTY ACTIVE_FLG TRANS_UID TRANS_UPDATE ACTIVE_LEGISLATOR",
}
VETO_RE = re.compile(r"^Vetoed by (the )?Governor", re.I)
SIGN_RE = re.compile(r"^Approved by the Governor", re.I)
SRC = "https://leginfo.legislature.ca.gov/faces/billStatusClient.xhtml?bill_id="


def table_path(raw: Path, name: str) -> Path:
    """A table as a plain .dat file (full download) or .dat.gz (session archive)."""
    p = Path(raw) / f"{name}.dat"
    return p if p.exists() else p.with_name(p.name + ".gz")


def read_table(raw: Path, name: str, usecols=None) -> pd.DataFrame:
    cols = COLS[name].split()
    path = table_path(raw, name)
    if not path.exists() or path.stat().st_size == 0:   # e.g. no votes yet early in a session
        df = pd.DataFrame(columns=cols, dtype=str)
    else:
        try:
            df = pd.read_csv(
                path, sep="\t", quotechar="`", header=None, names=cols,
                na_values=["NULL"], keep_default_na=False, dtype=str, engine="python",
                encoding="utf-8", encoding_errors="replace",
            )
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=cols, dtype=str)
    return df[usecols] if usecols else df


def _norm(s: pd.Series) -> pd.Series:
    return s.fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.lower().str.strip()


def person_keys(lg: pd.DataFrame) -> pd.Series:
    """A key for one person across sessions: first word of last name | first word of first name.

    The short author name ("Weber", "Rodriguez") can belong to different people in different
    sessions; a hand-checked list in data/reference/person_aliases.csv links people whose
    names changed."""
    key = _norm(lg.LAST_NAME).str.split().str[0].fillna("") + "|" + _norm(lg.FIRST_NAME).str.split().str[0].fillna("")
    alias_file = Path(__file__).resolve().parents[2] / "data/reference/person_aliases.csv"
    if alias_file.exists():
        al = pd.read_csv(alias_file)
        key = key.replace(dict(zip(al.alias_key, al.person_key)))
    return key


def slug(person: str) -> str:
    """File-safe form of a person key, used for the legislator pages (e.g. "weber|akilah" -> "weber-akilah")."""
    return re.sub(r"[^a-z0-9]+", "-", str(person).lower()).strip("-")


def name_aliases(raw: Path, bill_counts: pd.Series) -> dict[str, str]:
    """Map spelling or married-name variants of one legislator to a single name.

    The export sometimes lists one person twice in a session (Avila Farias / Ávila Farías,
    Kamlager / Kamlager-Dove). Two names for the same seat and first name are one person;
    the name with more bills is kept."""
    lg = read_table(raw, "LEGISLATOR_TBL").dropna(subset=["AUTHOR_NAME"])
    lg["first"] = lg.FIRST_NAME.fillna("").str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii").str.lower()
    alias = {}
    for _, g in lg.groupby(["DISTRICT", "first"]):
        names = g.AUTHOR_NAME.unique().tolist()
        if len(names) > 1:
            keep = max(names, key=lambda n: bill_counts.get(n, 0))
            alias.update({n: keep for n in names if n != keep})
    return alias


def build(raw: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = Path(raw)
    bills = read_table(raw, "BILL_TBL")
    # Regular session only (SESSION_NUM 0). Extraordinary-session bills (SESSION_NUM 1+)
    # reuse numbers like AB 3 and are not part of the scorecard.
    bills = bills[bills.MEASURE_TYPE.isin(["AB", "SB"]) & (bills.SESSION_NUM == "0")].copy()
    bills["bill_id"] = bills.MEASURE_TYPE + bills.MEASURE_NUM

    hist = read_table(raw, "BILL_HISTORY_TBL", ["BILL_ID", "ACTION_DATE", "ACTION"])
    hist["d"] = pd.to_datetime(hist.ACTION_DATE.str[:10], errors="coerce")
    intro = hist.groupby("BILL_ID").d.min().rename("introduced")
    sign = hist[hist.ACTION.fillna("").str.match(SIGN_RE)].groupby("BILL_ID").d.max().rename("signed_on")
    veto = hist[hist.ACTION.fillna("").str.match(VETO_RE)].groupby("BILL_ID").d.max().rename("vetoed_on")
    bills = bills.join(intro, on="BILL_ID").join(sign, on="BILL_ID").join(veto, on="BILL_ID")

    signed = (bills.CHAPTER_TYPE == "CHP") | bills.signed_on.notna()
    vetoed = ((bills.CURRENT_STATUS == "Vetoed") | bills.vetoed_on.notna()) & ~signed
    bills["outcome"] = "not_enacted"
    bills.loc[vetoed, "outcome"] = "vetoed"
    bills.loc[signed, "outcome"] = "signed"
    bills["action_date"] = bills.signed_on.where(signed, bills.vetoed_on.where(vetoed))
    # December pre-files count toward the session's first year
    start = int(bills.SESSION_YEAR.dropna().iloc[0][:4])
    bills["session"] = start
    bills["filed_year"] = bills.introduced.dt.year.clip(lower=start)
    bills["action_year"] = bills.action_date.dt.year.astype("Int64")

    ver = read_table(raw, "BILL_VERSION_TBL", ["BILL_VERSION_ID", "SUBJECT"]).rename(columns={"SUBJECT": "title"})
    bills = bills.merge(ver, left_on="LATEST_BILL_VERSION_ID", right_on="BILL_VERSION_ID", how="left")

    au = read_table(raw, "BILL_VERSION_AUTHORS_TBL")
    au = au[(au.TYPE == "Legislator") & (au.CONTRIBUTION == "LEAD_AUTHOR")]
    au = au.merge(bills[["BILL_ID", "bill_id", "LATEST_BILL_VERSION_ID"]],
                  left_on="BILL_VERSION_ID", right_on="LATEST_BILL_VERSION_ID")
    au = au.rename(columns={"NAME": "member", "HOUSE": "author_house"})
    alias = name_aliases(raw, au.member.value_counts())
    au["member"] = au.member.replace(alias)
    # first-listed = PRIMARY_AUTHOR_FLG; fall back to file order if a bill has none
    au["is_first_listed"] = au.PRIMARY_AUTHOR_FLG == "Y"
    nofirst = ~au.groupby("bill_id").is_first_listed.transform("any")
    au.loc[nofirst & ~au.duplicated("bill_id"), "is_first_listed"] = True
    n_leads = au.groupby("bill_id").member.transform("count")
    au["is_joint"] = n_leads > 1
    order = au.sort_values("is_first_listed", ascending=False, kind="stable")
    leads = order.groupby("bill_id").member.agg("+".join).rename("lead_authors")
    au = au.join(leads, on="bill_id")

    rows = au.merge(bills[["bill_id", "session", "introduced", "outcome", "action_date", "filed_year",
                           "action_year", "title", "BILL_ID", "CURRENT_STATUS"]],
                    on=["bill_id", "BILL_ID"])
    rows["source_url"] = SRC + rows.BILL_ID
    rows["introduced"] = rows.introduced.dt.strftime("%Y-%m-%d")
    rows["action_date"] = rows.action_date.dt.strftime("%Y-%m-%d")
    out = rows[["session", "bill_id", "member", "author_house", "is_first_listed", "is_joint", "introduced",
                "outcome", "action_date", "lead_authors", "title", "filed_year", "action_year",
                "source_url"]].copy()
    # Budget Act bills (AB/SB 100-199 spot bills) are introduced under the budget chairs' names.
    out["is_budget"] = out.title.fillna("").str.match(r"^Budget Acts?\b")
    out = out.sort_values(["bill_id", "member"]).reset_index(drop=True)

    lg = read_table(raw, "LEGISLATOR_TBL")
    lg = lg[~lg.AUTHOR_NAME.isin(alias)].copy()
    lg["person"] = person_keys(lg)
    lg["chamber"] = lg.HOUSE_TYPE.map({"A": "Assembly", "S": "Senate"})
    members = lg.rename(columns={"AUTHOR_NAME": "member", "LEGISLATOR_NAME": "full_name",
                                 "PARTY": "party", "DISTRICT": "district"})
    members["party"] = members.party.map({"DEM": "D", "REP": "R"}).fillna("Other")
    members = members[
        ["member", "full_name", "party", "district", "chamber", "ACTIVE_FLG", "person"]].assign(session=start)
    return out, members
