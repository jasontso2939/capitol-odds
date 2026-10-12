"""Build committee rosters, leadership history and member votes from the official roll calls,
then check them against archived committee web pages.

Run: PYTHONPATH=src python3 scripts/build_committees.py
Needs data/raw/pubinfo_2025 with BILL_DETAIL_VOTE_TBL, BILL_SUMMARY_VOTE_TBL, BILL_MOTION_TBL and
LOCATION_CODE_TBL (scripts/extract_raw.sh unpacks them).

Writes to data/processed/:
  committee_votes.csv.gz        one row per member per committee roll call
  committee_membership.csv      who sat on each committee in each year, with chair and vice chair
  committee_chairs_by_year.csv  chair and vice chair of each committee in each year, with hearing dates
  committee_leadership.csv      each stretch of hearings under one chair and vice chair
  committee_member_votes.csv    per member and committee: yes, no, absent, yes rate
  committee_roster_check.csv    roll-call roster vs. the committee's web page on the nearest date
"""
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg import committees as C  # noqa: E402
from calleg.pipeline import read_table  # noqa: E402

RAW = ROOT / "data/raw/pubinfo_2025"
OUT = ROOT / "data/processed"
WEB = ROOT / "data/reference/committee_rosters_web.csv"

# committee web site -> location code in the export
SITE_CODE = {
    "agri": "CX01", "aedn": "CX03", "aelc": "CX04", "aesm": "CX05", "agov": "CX07", "ahea": "CX08", "ahed": "CX09",
    "ahcd": "CX10", "ahum": "CX11", "ajud": "CX13", "albr": "CX14", "alcl": "CX15", "antr": "CX16", "aper": "CX17",
    "apsf": "CX18", "arev": "CX19", "arul": "CX20", "atrn": "CX22", "autl": "CX23", "awpw": "CX24", "apro": "CX25",
    "abnk": "CX27", "ains": "CX28", "altc": "CX31", "apcp": "CX32", "abp": "CX33", "aedghi": "CX34", "aart": "CX37",
    "amva": "CX38", "acom": "CX39", "aem": "CX81",
    "sagri": "CS40", "sbp": "CS42", "sedn": "CS44", "selc": "CS45", "sgov": "CS48", "sjud": "CS53", "sntr": "CS55",
    "slper": "CS56", "stran": "CS59", "shea": "CS60", "sapro": "CS61", "sbud": "CS62", "senv": "CS64", "svet": "CS66",
    "sbnk": "CS69", "sins": "CS70", "seuc": "CS71", "spsf": "CS72", "shum": "CS74", "shou": "CS75", "slcl": "CS82",
    "srev": "CS83", "sem": "CS86", "spdtcp": "CS87",
}


def legislators() -> pd.DataFrame:
    lg = read_table(RAW, "LEGISLATOR_TBL")
    lg = lg[lg.AUTHOR_NAME.notna()].copy()
    lg["party"] = lg.PARTY.map({"DEM": "D", "REP": "R"}).fillna(lg.PARTY)
    return lg.rename(columns={"AUTHOR_NAME": "member", "DISTRICT": "district", "LAST_NAME": "last_name"})[
        ["member", "district", "party", "last_name"]]


def web_to_member(web: pd.DataFrame, lg: pd.DataFrame, vote_names: set[str]) -> pd.Series:
    """Match each web roster name to the roll-call name, using district first, then last name."""
    by_d = lg.groupby("district")
    out = []
    for nm, dist in zip(web.name, web.district):
        cands = by_d.get_group(dist) if dist in by_d.groups else lg.iloc[0:0]
        cands = cands[cands.member.isin(vote_names)]
        pick = None
        for m, ln in zip(cands.member, cands.last_name.fillna("")):
            if ln and ln.split()[-1].lower() in nm.lower():
                pick = m
        if pick is None and len(cands) == 1:
            pick = cands.member.iloc[0]
        out.append(pick)
    return pd.Series(out, index=web.index)


def roster_check(votes: pd.DataFrame, web: pd.DataFrame) -> pd.DataFrame:
    hr = C.hearing_rosters(votes)
    rows = []
    for (site, target, ts), w in web.groupby(["site", "snapshot_target", "snapshot_ts"]):
        code = SITE_CODE.get(site.split(".")[0])
        h = hr[hr.committee_code == code]
        if not len(h):
            continue
        snap = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        dates = sorted(h.vote_date.unique())
        same_year = [d for d in dates if d[:4] == snap[:4]]
        if not same_year:
            continue
        day = min(same_year, key=lambda d: abs((pd.Timestamp(d) - pd.Timestamp(snap)).days))
        roll = h[h.vote_date == day]
        wm = w[w.role.isin(["Chair", "Vice Chair", "Member"]) & w.member.notna()]
        web_set, roll_set = set(wm.member), set(roll.member)
        web_chair = set(wm[wm.role == "Chair"].member)
        web_vice = set(wm[wm.role == "Vice Chair"].member)
        rows.append({
            "committee_code": code, "committee": roll.committee.iloc[0], "site": site,
            "snapshot_date": snap, "nearest_hearing": day, "web_members": len(web_set), "roll_members": len(roll_set),
            "in_both": len(web_set & roll_set),
            "only_on_web": "; ".join(sorted(web_set - roll_set)), "only_on_roll": "; ".join(sorted(roll_set - web_set)),
            "chair_web": "; ".join(web_chair), "chair_roll": "; ".join(roll[roll.role == "Chair"].member),
            "vice_web": "; ".join(web_vice), "vice_roll": "; ".join(roll[roll.role == "Vice Chair"].member),
            "source_url": w.source_url.iloc[0]})
    r = pd.DataFrame(rows)
    # explain differences: a member on the roll that day who sat on fewer than half the committee's
    # hearings that year was a temporary substitute
    mem = C.membership_by_year(votes)
    share = {(c, y, m): s for c, y, m, s in zip(mem.committee_code, mem.year, mem.member, mem.present_share)}
    def explain(row):
        y = int(row.nearest_hearing[:4])
        extra = [m for m in row.only_on_roll.split("; ") if m]
        missing = [m for m in row.only_on_web.split("; ") if m]
        if not extra and not missing:
            return "identical"
        subs = [m for m in extra if share.get((row.committee_code, y, m), 0) < C.CORE_SHARE]
        if len(subs) == len(extra) and len(missing) == len(extra):
            return "temporary substitute(s) sat in on that hearing date"
        return "other difference; the roll call is the official record of who sat that day"
    r["difference"] = r.apply(explain, axis=1)
    r["roster_match"] = (r.only_on_web == "") & (r.only_on_roll == "")
    r["chair_match"] = r.chair_web == r.chair_roll
    r["vice_match"] = r.vice_web == r.vice_roll
    return r.sort_values(["committee_code", "snapshot_date"])


def leadership_with_notes(votes: pd.DataFrame) -> pd.DataFrame:
    ch = C.chair_history(votes)
    prev = ch.groupby("committee_code")[["chair", "vice_chair"]].shift()
    nxt = ch.groupby("committee_code")[["chair", "vice_chair"]].shift(-1)
    blip = (ch.hearing_dates == 1) & (prev.chair.eq(nxt.chair)) & (prev.vice_chair.eq(nxt.vice_chair))
    ch["note"] = ""
    ch.loc[blip, "note"] = "One hearing between identical stretches; roll order that day likely reflects a temporary seat change, not a new chair or vice chair"
    return ch


def assign_roles(mem: pd.DataFrame, lead: pd.DataFrame, votes: pd.DataFrame) -> pd.DataFrame:
    """Chair and vice chair come from leadership stretches, skipping one-hearing substitution days."""
    real = lead[lead.note == ""]
    hd = votes.groupby("committee_code").vote_date.unique().map(sorted)
    mem = mem.copy()
    mem["role"] = "Member"
    roles = {}
    for r in real.itertuples():
        for y in range(int(r.from_date[:4]), int(r.to_date[:4]) + 1):
            for who, title in [(r.chair, "Chair"), (r.vice_chair, "Vice Chair")]:
                if isinstance(who, str):
                    roles.setdefault((r.committee_code, y, who), [])
                    ds = [d for d in hd[r.committee_code] if r.from_date <= d <= r.to_date and d[:4] == str(y)]
                    if not ds:
                        continue
                    period = f"hearings {ds[0]} to {ds[-1]}"
                    roles[(r.committee_code, y, who)].append(f"{title} ({period})")
    key = list(zip(mem.committee_code, mem.year, mem.member))
    mem["leadership"] = ["; ".join(roles.get(k, [])) for k in key]
    mem.loc[mem.leadership.str.contains("Vice Chair"), "role"] = "Vice Chair"
    mem.loc[mem.leadership.str.contains(r"(?:^|; )Chair"), "role"] = "Chair"
    mem["status"] = mem.status.map({"regular": "regular member", "partial": "part of year or substitute"})
    return mem.drop(columns=["chair_dates", "vice_dates"])


def main():
    votes = C.committee_votes(RAW)
    lg = legislators()
    mem = C.membership_by_year(votes, lg[["member", "party", "district"]].drop_duplicates("member"))
    lead = leadership_with_notes(votes)
    mem = assign_roles(mem, lead, votes)
    OUT.mkdir(exist_ok=True, parents=True)
    votes.drop(columns=["BILL_ID"]).to_csv(OUT / "committee_votes.csv.gz", index=False, compression="gzip")
    mem.to_csv(OUT / "committee_membership.csv", index=False)
    lead_rows = mem[mem.role != "Member"]
    by_year = (lead_rows.assign(entry=lead_rows.member + " (" + lead_rows.party.fillna("?") + "): " + lead_rows.leadership)
               .groupby(["house", "committee_code", "committee", "year"]).entry.agg(" | ".join).reset_index()
               .rename(columns={"entry": "chair_and_vice_chair"}))
    by_year.to_csv(OUT / "committee_chairs_by_year.csv", index=False)
    lead.to_csv(OUT / "committee_leadership.csv", index=False)
    C.member_vote_summary(votes).to_csv(OUT / "committee_member_votes.csv", index=False)
    if WEB.exists():
        web = pd.read_csv(WEB, dtype=str)
        web["member"] = web_to_member(web, lg, set(votes.member))
        chk = roster_check(votes, web)
        chk.to_csv(OUT / "committee_roster_check.csv", index=False)
        print(f"roster check: {len(chk)} comparisons; rosters identical {chk.roster_match.sum()}, "
              f"chair agrees {chk.chair_match.sum()}, vice chair agrees {chk.vice_match.sum()}")
    print(f"{len(votes)} committee votes; {mem.committee_code.nunique()} committees; {len(lead)} leadership stretches")


if __name__ == "__main__":
    main()
