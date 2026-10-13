"""Build site/insights.js (trends and the bill outlook model) and site/committees.js.
Run: PYTHONPATH=src python3 scripts/build_insights.py   (after scripts/build_committees.py)

Covers every session in calleg.sessions: the current one from the full download and
earlier ones from the session archive (scripts/archive_session.py)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd  # noqa: E402
from calleg.features import build_features  # noqa: E402
from calleg.trends import all_trends  # noqa: E402
from calleg import predict  # noqa: E402
from calleg import committees as C  # noqa: E402
from calleg.sessions import available, raw_dir, intro_cache, zip_path, label, CURRENT  # noqa: E402

membership = pd.read_csv(ROOT / "data/processed/committee_membership.csv")
M, D, T, V = [], [], {}, []
for year in available():
    raw = raw_dir(year)
    m = build_features(raw, zip_path(year), intro_cache(year))
    m = m[~m.is_budget]
    T[str(year)] = all_trends(m, raw)
    d = predict.training_frame(m)
    votes = C.committee_votes(raw)
    d = d.merge(C.relationship_features(d, raw, votes, membership), on="BILL_ID", how="left")
    M.append(m), D.append(d), V.append(votes.assign(session=year))
    print(f"{label(year)}: {len(m)} bills, {len(d)} in model")
m, d, votes = pd.concat(M, ignore_index=True), pd.concat(D, ignore_index=True), pd.concat(V, ignore_index=True)

# Trends for all sessions together. Veto reasons are summed from the per-session tables.
from calleg import trends as TR  # noqa: E402
allt = {k: f(m) for k, f in [("appropriations_by_party", TR.appropriations_by_party),
                             ("where_failed_bills_died", TR.where_failed_bills_died),
                             ("policy_area_risk", TR.policy_area_risk), ("fiscal_flags", TR.fiscal_flags),
                             ("coalition", TR.coalition), ("second_house", TR.second_house),
                             ("spot_bills", TR.spot_bills), ("veto_rate_by_area", TR.veto_rate_by_area)]}
allt["timing"] = TR.timing(m)
vs = [T[s]["veto_reasons"] for s in T]
summ = {}
for v in vs:
    for r in v["summary"]:
        e = summ.setdefault(r["reason"], {"reason": r["reason"], "any_mention": 0, "primary": 0})
        e["primary"] += r["primary"]
        e["any_mention"] = None if r["any_mention"] is None else (e["any_mention"] or 0) + r["any_mention"]
allt["veto_reasons"] = {"messages": sum(v["messages"] for v in vs), "vetoed_bills": sum(v["vetoed_bills"] for v in vs),
                        "summary": list(summ.values()), "repeat": [r for v in vs for r in v["repeat"]]}
T["all"] = allt

# Session-by-session summary for the "over time" charts
over = []
for s, g in m.groupby("session"):
    row = {"session": int(s), "label": label(int(s)), "bills": len(g), "signed_pct": round(100 * g.signed.mean(), 1),
           "vetoed_pct_of_sent": round(100 * (g.outcome == "vetoed").sum() / g.outcome.isin(["signed", "vetoed"]).sum(), 1)}
    for p in ["D", "R"]:
        gp = g[g.party == p]
        row[f"signed_pct_{p}"] = round(100 * gp.signed.mean(), 1)
        for house in ["Assembly", "Senate"]:
            sent = gp[gp[f"appr_{house}"]]
            row[f"died_{house}_appr_pct_{p}"] = round(100 * (sent.died_in == f"{house} Appropriations").mean(), 1)
    over.append(row)
T["over_time"] = over

metrics = predict.evaluate(d)
model = predict.fit_export(d)
out = {"session": label(CURRENT), "sessions": [label(y) for y in available()], "trends": T, "model": model,
       "metrics": metrics}
# Bill list for the outlook page (context and title search), stored compactly as columns
b = m[["session", "bill_id", "title", "member", "party", "policy_area", "outcome"]].fillna("")
members_ix, areas_ix = sorted(b.member.unique()), sorted(b.policy_area.unique())
mi, ai = {n: i for i, n in enumerate(members_ix)}, {n: i for i, n in enumerate(areas_ix)}
compact = {"members": members_ix, "areas": areas_ix,
           "cols": ["session", "bill_id", "title", "member", "party", "area", "outcome (s/v/n)"],
           "rows": [[int(r.session), r.bill_id, r.title.strip(), mi[r.member], r.party, ai[r.policy_area], r.outcome[0]]
                    for r in b.itertuples()]}
(ROOT / "site/data").mkdir(exist_ok=True)
(ROOT / "site/data/bills_index.js").write_text("window.BILLS = " + json.dumps(compact, separators=(",", ":")) + ";\n")
(ROOT / "site/insights.js").write_text("window.INSIGHTS = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")
(ROOT / "data/processed/model_metrics.json").write_text(json.dumps(metrics, indent=2))

# Committee data for the Committees page and the outlook's relationship panel.
# Committees are grouped by name, since codes are reassigned between sessions.
cur_d = d[d.session == CURRENT]
area_code = cur_d.dropna(subset=["policy_area"]).groupby("policy_area").first_policy_code.agg(lambda s: s.mode().iloc[0])
lead = pd.read_csv(ROOT / "data/processed/committee_leadership.csv").fillna("")
cur_votes = votes[votes.session == CURRENT]
cvotes = cur_votes[cur_votes.vote.isin(["yes", "no"])].copy()
cvotes["author"] = cvotes.bill_id.map(m[m.session == CURRENT].set_index("bill_id").member)
pairs = (cvotes.dropna(subset=["author"]).groupby(["author", "member"]).vote
         .agg(yes=lambda s: (s == "yes").sum(), no=lambda s: (s == "no").sum()).reset_index())
rolls = (votes.drop_duplicates(["bill_id", "session", "committee_code", "vote_time", "vote_seq", "motion_id"])
         .groupby(["committee", "year"]).result.agg(roll_calls="size", passed=lambda s: (s == "pass").sum()).reset_index())
mv = votes.groupby(["committee", "year", "member"]).vote.value_counts().unstack(fill_value=0)
committees = []
for name, g in membership.groupby("committee"):
    years = {}
    for y, gy in g.groupby("year"):
        r = rolls[(rolls.committee == name) & (rolls.year == y)]
        years[str(y)] = {
            "code": gy.committee_code.iloc[0],
            "hearing_dates": int(gy.hearing_dates.max()),
            "roll_calls": int(r.roll_calls.sum()), "passed": int(r.passed.sum()),
            "members": [[x.member, x.party if isinstance(x.party, str) else "", x.role, x.status, int(x.dates_on_roll),
                         x.leadership if isinstance(x.leadership, str) else "",
                         *[int(mv.loc[(name, y, x.member)].get(k, 0)) for k in ("yes", "no", "absent or not voting")]]
                        for x in gy.itertuples()]}
    cur_code = g[g.year >= CURRENT].committee_code.mode()
    committees.append({"code": cur_code.iloc[0] if len(cur_code) else g.committee_code.iloc[-1],
                       "name": name, "house": g.house.iloc[0], "years": years,
                       "leadership": lead[lead.committee == name][["chair", "vice_chair", "from_date", "to_date",
                                                                   "hearing_dates", "note"]].values.tolist()})
chk = pd.read_csv(ROOT / "data/processed/committee_roster_check.csv")
check = {"total": len(chk), "explained": int(chk.difference.isin(["identical", "temporary substitute(s) sat in on that hearing date"]).sum()),
         "chair": int(chk.chair_match.sum()), "vice": int(chk.vice_match.sum())}
cm = {"committees": committees, "check": check, "area_code": area_code.to_dict(), "current": CURRENT,
      "pairs": pairs.values.tolist(), "pair_cols": list(pairs.columns)}
(ROOT / "site/committees.js").write_text("window.COMMITTEES = " + json.dumps(cm, separators=(",", ":"), default=str) + ";\n")
print("wrote site/insights.js and site/committees.js;", "CV AUC", metrics["cv_auc"],
      "out-of-session AUC", metrics["out_of_session_auc"], "within-session AUC", metrics["within_session_auc"])
