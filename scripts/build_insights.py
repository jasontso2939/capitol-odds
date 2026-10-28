"""Build site/insights.js (trends and the bill outlook model) and the committee data files
(site/data/committees_index.js, committees_<year>.js, committee_pairs.js).
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
from calleg import stages as STG  # noqa: E402
from calleg import committees as C  # noqa: E402
from calleg import tracking as TK  # noqa: E402
from calleg.pipeline import slug  # noqa: E402
from calleg.sessions import available, complete, raw_dir, intro_cache, zip_path, label, CURRENT  # noqa: E402

membership = pd.read_csv(ROOT / "data/processed/committee_membership.csv")
M, D, T, V, H = [], [], {}, [], []
for year in available():
    raw = raw_dir(year)
    m = build_features(raw, zip_path(year), intro_cache(year))
    m = m[~m.is_budget]
    T[str(year)] = all_trends(m, raw)
    d = predict.training_frame(m)
    votes = C.committee_votes(raw)
    d = d.merge(C.relationship_features(d, raw, votes, membership), on="BILL_ID", how="left")
    hist = TK.read_history(raw)
    hist = hist[hist.BILL_ID.isin(d.BILL_ID)]
    d["double_referred"] = d.BILL_ID.map(TK.double_referred(hist)).fillna(False).astype(bool)
    M.append(m), D.append(d), V.append(votes.assign(session=year)), H.append(TK.action_flags(hist))
    print(f"{label(year)}: {len(m)} bills, {len(d)} in model")
m, d, votes = pd.concat(M, ignore_index=True), pd.concat(D, ignore_index=True), pd.concat(V, ignore_index=True)
flags = pd.concat(H, ignore_index=True)

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
                        "summary": list(summ.values()), "repeat": [r for v in vs for r in v["repeat"]],
                        "review": {k: sum(v["review"][k] for v in vs) for k in vs[0]["review"]}}
T["all"] = allt

# Session-by-session summary for the "over time" charts
over = []
for s, g in m.groupby("session"):
    row = {"session": int(s), "label": label(int(s)), "complete": int(s) in complete(), "bills": len(g), "signed_pct": round(100 * g.signed.mean(), 1),
           "vetoed_pct_of_sent": round(100 * (g.outcome == "vetoed").sum() / g.outcome.isin(["signed", "vetoed"]).sum(), 1)}
    for p in ["D", "R"]:
        gp = g[g.party == p]
        row[f"signed_pct_{p}"] = round(100 * gp.signed.mean(), 1)
        for house in ["Assembly", "Senate"]:
            sent = gp[gp[f"appr_{house}"]]
            row[f"died_{house}_appr_pct_{p}"] = round(100 * (sent.died_in == f"{house} Appropriations").mean(), 1)
    over.append(row)
T["over_time"] = over

# The model learns only from finished sessions: in a session still under way, pending bills
# would count as failures. The current session's roster and bills are used for scoring.
done = complete()
train = d[d.session.isin(done)]
REF = max(done)
members_all = pd.read_csv(ROOT / "data/processed/members_all.csv")
metrics = predict.evaluate(train)
model = predict.fit_export(train, members=members_all[members_all.session == CURRENT],
                           current=d[d.session == CURRENT], current_session=CURRENT)
# Staged model: one model per step to the Governor; the outlook page shows the steps, the
# product (chance of being signed) and a range from bootstrap refits.
tv = votes[votes.session.isin(done)]
lab = STG.stage_labels(train, tv)
Xs = predict.design(train, train, leave_one_out=True)
stage_models = STG.fit_stages(train, lab, Xs)
model["stages"] = STG.export(stage_models, list(Xs.columns))
model["stage_names"] = dict(STG.STAGES)
model["stage_draws"] = STG.bootstrap(train, lab, Xs)
model["atypical_sessions"] = STG.ATYPICAL
# Subject-line words: vocabulary and idf, so the browser builds the same TF-IDF features
_vec = predict.text_model(train)
model["text"] = {"vocab": list(_vec.get_feature_names_out()), "idf": [round(float(x), 4) for x in _vec.idf_]}
metrics["stages"] = {**STG.evaluate(train, tv), **STG.cross_validate(train, lab),
                     "step_rates": [{"step": s, "name": n, "reached": int(lab[f"reached_{s}"].sum()),
                                     "passed": int(lab[f"passed_{s}"].sum())} for s, n in STG.STAGES],
                     "sent_to_appropriations": int(lab.sent_appropriations.sum())}
# Context for the outlook page, so it does not need the full bill list to describe a committee
# or an author: bills by first policy committee (current session and all sessions), and each
# current author's bills as first-listed lead this session.
cur_m = m[m.session == CURRENT]
model["area_stats"] = {a: [int((cur_m.policy_area == a).sum()), int(((cur_m.policy_area == a) & (cur_m.outcome == "signed")).sum()),
                           int((m.policy_area == a).sum()), int(((m.policy_area == a) & (m.outcome == "signed")).sum())]
                       for a in model["policy_areas"]}
lead_n, lead_s = cur_m.groupby("member").size(), cur_m[cur_m.outcome == "signed"].groupby("member").size()
for a in model["authors"]:
    a["lead_bills_current"] = int(lead_n.get(a["member"], 0))
    a["lead_signed_current"] = int(lead_s.get(a["member"], 0))
    a["slug"] = slug(a["person"]) if a.get("person") else ""
model["first_session"] = int(min(available()))
out = {"session": label(CURRENT), "current": CURRENT, "sessions": [label(y) for y in available()],
       "complete_sessions": [label(y) for y in done], "trends": T, "metrics": metrics}
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
(ROOT / "site/data/model.js").write_text("window.MODEL = " + json.dumps(model, separators=(",", ":"), default=str) + ";\n")

# Track a filed bill: chance of being signed given its history so far, at each checkpoint
dbl = d.set_index("BILL_ID").double_referred
metrics["tracking"] = TK.evaluate(train, flags[flags.BILL_ID.isin(train.BILL_ID)], dbl)
score = d[d.session == CURRENT]
# A finished session is scored by models trained only on earlier sessions, so the page shows
# what the model would have said at the time; a session under way uses every finished one.
fit_on = train[train.session < CURRENT] if CURRENT in done else train
tk = TK.fit_score(fit_on, score, flags, dbl, finished=CURRENT in done)
tk = tk.merge(score[["BILL_ID", "bill_id", "member", "party", "policy_area", "intro_date"]], on="BILL_ID")
tk = tk.merge(m[["BILL_ID", "title", "outcome"]], on="BILL_ID", how="left")
pcols = [c for c in tk if c.startswith("p") and c[1:].isdigit()]
asof = str(flags.d.max().date())
tracking = {"asof": asof, "session": CURRENT, "complete": CURRENT in done, "checkpoints": [0] + TK.CHECKPOINTS,
            "accuracy": metrics["tracking"],
            "cols": ["bill_id", "title", "member", "party", "policy_area", "introduced", "outcome"] + pcols,
            "rows": [[r.bill_id, (r.title or "").strip(), r.member, r.party, r.policy_area or "", str(r.intro_date)[:10],
                      r.outcome if CURRENT in done or r.outcome in ("signed", "vetoed") else "pending"]
                     + [None if pd.isna(getattr(r, c)) else float(getattr(r, c)) for c in pcols] for r in tk.itertuples()]}
(ROOT / "site/data/tracking.js").write_text("window.TRACKING = " + json.dumps(tracking, separators=(",", ":"), default=str) + ";\n")
(ROOT / "data/processed/model_metrics.json").write_text(json.dumps(metrics, indent=2))

# Committee data for the Committees page and the outlook's relationship panel.
# Committees are grouped by name, since codes are reassigned between sessions.
# Committee codes and author-member vote pairs come from the current session once it has
# committee roll calls; before then (a new session's first months) from the reference session.
LIVE = CURRENT if (votes.session == CURRENT).any() else REF
cur_d = d[d.session == LIVE]
area_code = cur_d.dropna(subset=["policy_area"]).groupby("policy_area").first_policy_code.agg(lambda s: s.mode().iloc[0])
lead = pd.read_csv(ROOT / "data/processed/committee_leadership.csv").fillna("")
cur_votes = votes[votes.session == LIVE]
cvotes = cur_votes[cur_votes.vote.isin(["yes", "no"])].copy()
cvotes["author"] = cvotes.bill_id.map(m[m.session == LIVE].set_index("bill_id").member)
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
            "name_then": gy.name_then.iloc[0] if "name_then" in gy and gy.name_then.iloc[0] != name else "",
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
lin = pd.read_csv(ROOT / "data/reference/committee_lineage.csv")
cm = {"lineage": lin[["name", "current_name", "relation", "note"]].values.tolist(), "committees": committees, "check": check, "area_code": area_code.to_dict(), "current": CURRENT, "pairs_session": LIVE,
      "pairs": pairs.values.tolist(), "pair_cols": list(pairs.columns)}
# Split for lighter pages: the index (names, leadership, year totals), one roster file per
# year, and the author-member vote pairs used only by the outlook page.
J = dict(separators=(",", ":"), default=str)
by_year = {}
for c in cm["committees"]:
    for y, yd in c["years"].items():
        by_year.setdefault(y, {})[c["name"]] = yd.pop("members")
for y, d in by_year.items():
    (ROOT / f"site/data/committees_{y}.js").write_text(f"(window.CMY = window.CMY || {{}})[{json.dumps(y)}] = " + json.dumps(d, **J) + ";\n")
pairs = {k: cm.pop(k) for k in ["pairs", "pair_cols", "pairs_session"]}
cm["years"] = sorted(by_year)
(ROOT / "site/data/committee_pairs.js").write_text("window.PAIRS = " + json.dumps(pairs, **J) + ";\n")
(ROOT / "site/data/committees_index.js").write_text("window.COMMITTEES = " + json.dumps(cm, **J) + ";\n")
old = ROOT / "site/committees.js"
if old.exists():
    old.unlink()
print("wrote site/insights.js and the committee files;", "CV AUC", metrics["cv_auc"],
      "out-of-session AUC", metrics["out_of_session_auc"], "within-session AUC", metrics["within_session_auc"])
