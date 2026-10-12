"""Build site/insights.js: statewide trends and the bill outlook model.
Run: PYTHONPATH=src python3 scripts/build_insights.py
Needs the raw export (make fetch extract) and, for spot-bill detection, the session zip
or the cached data/processed/intro_text.csv."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg.features import build_features  # noqa: E402
from calleg.trends import all_trends  # noqa: E402
from calleg import predict  # noqa: E402
from calleg import committees as C  # noqa: E402
import pandas as pd  # noqa: E402

RAW = ROOT / "data/raw/pubinfo_2025"
m = build_features(RAW, ROOT / "data/raw/pubinfo_2025.zip", ROOT / "data/processed/intro_text.csv")
m = m[~m.is_budget]
trends = all_trends(m, RAW)
d = predict.training_frame(m)
votes = C.committee_votes(RAW)
membership = pd.read_csv(ROOT / "data/processed/committee_membership.csv")
d = d.merge(C.relationship_features(d, RAW, votes, membership), on="BILL_ID", how="left")
metrics = predict.evaluate(d)
model = predict.fit_export(d)
bills = m[["bill_id", "title", "member", "party", "policy_area", "outcome"]].fillna("")
out = {"session": "2025-26", "trends": trends, "model": model, "metrics": metrics,
       "bills": bills.to_dict(orient="records")}
(ROOT / "site/insights.js").write_text("window.INSIGHTS = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")
(ROOT / "data/processed/model_metrics.json").write_text(json.dumps(metrics, indent=2))

# Committee data for the Committees page and the outlook's relationship panel
area_code = d.dropna(subset=["policy_area"]).groupby("policy_area").first_policy_code.agg(lambda s: s.mode().iloc[0])
mem = membership.copy()
lead = pd.read_csv(ROOT / "data/processed/committee_leadership.csv").fillna("")
cvotes = votes[votes.vote.isin(["yes", "no"])].copy()
cvotes["author"] = cvotes.bill_id.map(m.set_index("bill_id").member)
pairs = (cvotes.dropna(subset=["author"]).groupby(["author", "member"]).vote
         .agg(yes=lambda s: (s == "yes").sum(), no=lambda s: (s == "no").sum()).reset_index())
rolls = (votes.drop_duplicates(["bill_id", "committee_code", "vote_time", "vote_seq", "motion_id"])
         .groupby(["committee_code", "year"]).result.agg(roll_calls="size", passed=lambda s: (s == "pass").sum()).reset_index())
mv = (votes.groupby(["committee_code", "year", "member"]).vote.value_counts().unstack(fill_value=0))
committees = []
for code, g in mem.groupby("committee_code"):
    years = {}
    for y, gy in g.groupby("year"):
        r = rolls[(rolls.committee_code == code) & (rolls.year == y)]
        years[str(y)] = {
            "hearing_dates": int(gy.hearing_dates.iloc[0]),
            "roll_calls": int(r.roll_calls.sum()), "passed": int(r.passed.sum()),
            "members": [[x.member, x.party if isinstance(x.party, str) else "", x.role, x.status, int(x.dates_on_roll),
                         x.leadership if isinstance(x.leadership, str) else "",
                         *[int(mv.loc[(code, y, x.member)].get(k, 0)) for k in ("yes", "no", "absent or not voting")]]
                        for x in gy.itertuples()]}
    committees.append({"code": code, "name": g.committee.iloc[0], "house": g.house.iloc[0], "years": years,
                       "leadership": lead[lead.committee_code == code][["chair", "vice_chair", "from_date", "to_date",
                                                                         "hearing_dates", "note"]].values.tolist()})
chk = pd.read_csv(ROOT / "data/processed/committee_roster_check.csv")
check = {"total": len(chk), "explained": int(chk.difference.isin(["identical", "temporary substitute(s) sat in on that hearing date"]).sum()),
         "chair": int(chk.chair_match.sum()), "vice": int(chk.vice_match.sum())}
cm = {"committees": committees, "check": check, "area_code": area_code.to_dict(),
      "pairs": pairs.values.tolist(), "pair_cols": list(pairs.columns)}
(ROOT / "site/committees.js").write_text("window.COMMITTEES = " + json.dumps(cm, separators=(",", ":"), default=str) + ";\n")
print("wrote site/insights.js and site/committees.js;", "CV AUC", metrics["cv_auc"], "temporal AUC", metrics["temporal_auc_2025_to_2026"])
