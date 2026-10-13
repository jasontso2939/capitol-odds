"""Build the legislator pages' data: one small file per person plus an index.
Run: PYTHONPATH=src python3 scripts/build_people.py   (after build_committees.py)

  site/data/people_index.js      every legislator since 2017: name, party, seat, sessions
  site/data/people/<slug>.js     one legislator: record by session (with chamber ranks),
                                 every bill as lead author, committee seats by year, and
                                 committee votes cast

A person is followed across sessions by their person key (calleg.pipeline.person_keys), so
name changes such as Kamlager-Dove to Kamlager stay on one page."""
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg import scorecard  # noqa: E402
from calleg.pipeline import build, slug  # noqa: E402
from calleg.build import prepare_members  # noqa: E402
from calleg.sessions import available, raw_dir, CURRENT  # noqa: E402

OUT = ROOT / "site/data/people"
J = dict(separators=(",", ":"))

recs, bills_all, mem_all = [], [], []
for year in available():
    bills, members = build(raw_dir(year))
    members = prepare_members(bills, members)
    flat = bills.drop(columns=["author_house"])
    src = flat[~flat.is_budget]
    t = pd.concat([scorecard(src, members[members.chamber == ch], "all_leads", "session").assign(chamber=ch, chamber_size=(members.chamber == ch).sum())
                   for ch in ("Assembly", "Senate")], ignore_index=True)
    t = t.merge(members[["member", "person", "partial_term"]], on="member")
    t["budget_bills"] = t.member.map(flat[flat.is_budget].groupby("member").size()).fillna(0).astype(int)
    recs.append(t.assign(session=year))
    b = flat.merge(members[["member", "person"]], on="member")
    bills_all.append(b.assign(session=year))
    mem_all.append(members.assign(session=year))
R = pd.concat(recs, ignore_index=True)
B = pd.concat(bills_all, ignore_index=True)
B["house_order"] = B.bill_id.str.startswith("SB").astype(int)
B["number"] = B.bill_id.str.extract(r"(\d+)$")[0].astype(int)
for c in ["title", "introduced", "action_date"]:
    B[c] = B[c].fillna("").astype(str)
MEM = pd.concat(mem_all, ignore_index=True)

# Committee seats and votes: names on the roll calls are matched to authors within each session
cm = pd.read_csv(ROOT / "data/processed/committee_membership.csv")
cm["session"] = cm.year - (cm.year % 2 == 0)
key = MEM[["session", "member", "person"]].drop_duplicates(["session", "member"])
cm = cm.merge(key, on=["session", "member"], how="left")
# Roll calls sometimes use a name the author table does not have that session: members sworn in
# mid-session who carried no bills yet (Gabriel and Luz Rivas in 2018, Alvarez in 2022), or a
# name that changed (Kamlager in 2020, Boerner Horvath in 2023). Match these by seat and a
# shared surname, first within the session and then in the next one.
tok = lambda s: set(str(s).lower().replace("-", " ").split())
for i in cm.index[cm.person.isna()]:
    r = cm.loc[i]
    for s in (r.session, r.session + 2):
        c = MEM[(MEM.session == s) & (MEM.district == r.district) & MEM.member.map(lambda n: bool(tok(n) & tok(r.member)))]
        if c.person.nunique() == 1:
            cm.loc[i, "person"] = c.person.iloc[0]
            break
votes = pd.read_csv(ROOT / "data/processed/committee_votes.csv.gz", usecols=["committee", "year", "member", "vote", "session"])
vs = votes.groupby(["session", "year", "committee", "member"]).vote.value_counts().unstack(fill_value=0).reset_index()
for c in ["yes", "no", "absent or not voting"]:
    if c not in vs:
        vs[c] = 0
cm = cm.merge(vs, on=["session", "year", "committee", "member"], how="left").fillna({"yes": 0, "no": 0, "absent or not voting": 0})
unmatched = cm.person.isna().sum()

if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
index = []
for person, g in MEM.sort_values("session").groupby("person"):
    s = slug(person)
    last = g.iloc[-1]
    r = R[R.person == person].sort_values("session")
    rec = [{"session": int(x.session), "member": x.member, "full_name": x.full_name, "party": x.party,
            "chamber": x.chamber, "district": x.district, "partial_term": bool(x.partial_term),
            "introduced": int(x.introduced), "signed": int(x.signed), "vetoed": int(x.vetoed), "rate": float(x.rate),
            "rank_signed": int(x.rank_signed), "rank_rate": int(x.rank_rate), "chamber_size": int(x.chamber_size),
            "budget_bills": int(x.budget_bills)} for x in r.itertuples()]
    b = B[B.person == person].sort_values(["session", "house_order", "number"])
    bills = [[int(x.session), x.bill_id, x.title, x.introduced, x.outcome, x.action_date, int(x.is_joint), int(x.is_first_listed), int(x.is_budget)]
             for x in b.itertuples()]
    c = cm[cm.person == person].sort_values(["year", "committee"])
    comm = [[int(x.year), x.committee, x.name_then if isinstance(x.name_then, str) and x.name_then != x.committee else "",
             x.role, x.status, int(x.dates_on_roll), int(x.hearing_dates), int(x.yes), int(x.no), int(x["absent or not voting"])]
            for _, x in c.iterrows()]
    data = {"slug": s, "person": person, "name": last.full_name, "member": last.member, "party": last.party,
            "chamber": last.chamber, "district": last.district, "names": list(dict.fromkeys(g.member)),
            "current": bool((g.session == CURRENT).any()), "current_session": CURRENT, "record": rec,
            "bill_cols": ["session", "bill_id", "title", "introduced", "outcome", "action_date", "joint", "first_listed", "budget"],
            "bills": bills,
            "committee_cols": ["year", "committee", "name_then", "role", "status", "hearings_on_roll", "hearing_dates", "yes", "no", "absent"],
            "committees": comm}
    (OUT / f"{s}.js").write_text(f"(window.PEOPLE = window.PEOPLE || {{}})[{json.dumps(s)}] = " + json.dumps(data, **J) + ";\n")
    index.append([s, last.full_name, last.member, last.party, last.chamber, last.district,
                  [int(x) for x in g.session.unique()], int(sum(x["signed"] for x in rec)), int(sum(x["introduced"] for x in rec))])
(ROOT / "site/data/people_index.js").write_text(
    "window.PEOPLE_INDEX = " + json.dumps({"cols": ["slug", "name", "member", "party", "chamber", "district", "sessions", "signed", "introduced"],
                                           "rows": index, "current": CURRENT}, **J) + ";\n")
print(f"wrote {len(index)} legislator files; committee seats not matched to a legislator: {unmatched}")
