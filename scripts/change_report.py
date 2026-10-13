"""Weekly change report for the data refresh.

Computes headline numbers from the freshly built outputs, compares them with the last
committed copy (data/processed/headline.json at HEAD), and writes:

  data/processed/headline.json   the new headline numbers (committed with the refresh)
  commit_message.txt             a commit message that says what moved
  --summary FILE                 a Markdown table appended to FILE (the Actions run summary)
  --alert FILE                   written only when something moved beyond a threshold below;
                                 the workflow opens an issue from it

Run: PYTHONPATH=src python scripts/change_report.py [--summary FILE] [--alert FILE]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg.sessions import is_complete, label  # noqa: E402

HEAD_FILE = "data/processed/headline.json"

# Alert thresholds. Finished sessions should not move at all; the session in progress is
# expected to grow, so only reversals and large jumps are flagged.
CURRENT_RATE_POINTS = 2.0      # signed rate of the session in progress, percentage points
CURRENT_BILLS_DROP = 0         # any drop in the number of bills in the session in progress
MODEL_AUC = 0.02               # change in any accuracy figure
CALIBRATION_GAP = 0.08         # predicted vs actual signed rate on the held-out session
VETO_AGREEMENT_MIN = 0.75      # keyword veto labels vs the hand-read sample


def _js(path: Path) -> dict:
    t = path.read_text()
    return json.loads(t[t.index("{"): t.rstrip().rstrip(";").rindex("}") + 1])


def headline() -> dict:
    b = pd.read_csv(ROOT / "data/processed/bills_all.csv")
    m = pd.read_csv(ROOT / "data/processed/members_all.csv")
    u = b.drop_duplicates(["session", "bill_id"])
    sessions = {}
    for s, g in u.groupby("session"):
        nb = g[~g.is_budget] if "is_budget" in g else g
        sessions[str(int(s))] = {
            "complete": is_complete(int(s)),
            "bills": int(len(g)),
            "signed": int((g.outcome == "signed").sum()),
            "vetoed": int((g.outcome == "vetoed").sum()),
            "signed_pct": round(100 * float((nb.outcome == "signed").mean()), 2),
            "members": int((m.session == s).sum()),
        }
    met = json.loads((ROOT / "data/processed/model_metrics.json").read_text())
    st = met.get("stages", {})
    model = {"cv_auc": met.get("cv_auc"), "out_of_session_auc": met.get("out_of_session_auc"),
             "staged_cv_auc": st.get("cv_auc"), "staged_out_of_session_auc": st.get("out_of_session_auc"),
             "out_of_session_predicted": st.get("out_of_session_predicted_rate"),
             "out_of_session_actual": st.get("out_of_session_actual_rate"),
             "trained_on": met.get("sessions")}
    ins = _js(ROOT / "site/insights.js")
    rv = ins["trends"]["all"]["veto_reasons"].get("review", {})
    cm = pd.read_csv(ROOT / "data/processed/committee_membership.csv")
    nc = pd.read_csv(ROOT / "data/reference/name_changes.csv")
    changed = {p for p, g in m.dropna(subset=["member"]).groupby("person") if g.member.nunique() > 1}
    return {"date": dt.date.today().isoformat(), "sessions": sessions, "model": model,
            "veto_review": {"reviewed": rv.get("reviewed", 0), "agree": rv.get("agree", 0)},
            "committee_seats": int(len(cm)), "committee_years": sorted(int(y) for y in cm.year.unique()),
            "unreviewed_name_changes": sorted(changed - set(nc.person))}


def previous() -> dict | None:
    try:
        out = subprocess.run(["git", "show", f"HEAD:{HEAD_FILE}"], cwd=ROOT, capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        return None


def compare(new: dict, old: dict | None) -> tuple[list[str], list[str]]:
    """Return (changes, alerts) as Markdown lines."""
    changes, alerts = [], []
    if old is None:
        return ["First report: baseline recorded."], []
    for s, n in new["sessions"].items():
        o = old["sessions"].get(s)
        L = label(int(s))
        if o is None:
            changes.append(f"New session {L}: {n['bills']} bills, {n['members']} members.")
            alerts.append(f"A new session ({L}) appeared in the data. Check that the rollover worked: "
                          f"the scorecard, committees and outlook should show {L} as current.")
            continue
        diffs = {k: (o.get(k), n[k]) for k in ("bills", "signed", "vetoed", "signed_pct", "members") if o.get(k) != n[k]}
        if not diffs:
            continue
        changes.append(f"{L}: " + ", ".join(f"{k} {a} → {b}" for k, (a, b) in diffs.items()))
        if n["complete"] and o.get("complete"):
            alerts.append(f"{L} is finished, but its numbers changed: " + ", ".join(f"{k} {a} → {b}" for k, (a, b) in diffs.items())
                          + ". Finished sessions should not move; check the source download and the session archive.")
        elif n["complete"] and not o.get("complete"):
            changes.append(f"{L} is now complete (the Governor's deadline has passed): the model will train on it.")
        else:
            if "signed_pct" in diffs and o.get("signed_pct") is not None and abs(n["signed_pct"] - o["signed_pct"]) > CURRENT_RATE_POINTS:
                alerts.append(f"{L} signed rate moved {o['signed_pct']}% → {n['signed_pct']}% in one refresh.")
            if "bills" in diffs and o.get("bills") is not None and n["bills"] < o["bills"] - CURRENT_BILLS_DROP:
                alerts.append(f"{L} lost bills: {o['bills']} → {n['bills']}. The export should only grow during a session.")
    for s in old["sessions"]:
        if s not in new["sessions"]:
            alerts.append(f"Session {label(int(s))} disappeared from the data.")
    nm, om = new["model"], old.get("model", {})
    for k in ("cv_auc", "out_of_session_auc", "staged_cv_auc", "staged_out_of_session_auc"):
        a, b = om.get(k), nm.get(k)
        if a is not None and b is not None and a != b:
            changes.append(f"Model {k.replace('_', ' ')}: {a} → {b}")
            if abs(b - a) > MODEL_AUC:
                alerts.append(f"Model {k.replace('_', ' ')} moved {a} → {b} (more than {MODEL_AUC}).")
    if nm.get("trained_on") != om.get("trained_on"):
        changes.append(f"Model now trained on {', '.join(label(s) for s in nm.get('trained_on') or [])}.")
    p, a = nm.get("out_of_session_predicted"), nm.get("out_of_session_actual")
    if p is not None and a is not None and abs(p - a) > CALIBRATION_GAP:
        alerts.append(f"On the held-out session the model predicted {p:.1%} signed against {a:.1%} actual.")
    rv = new["veto_review"]
    if rv["reviewed"] and rv["agree"] / rv["reviewed"] < VETO_AGREEMENT_MIN:
        alerts.append(f"Veto reason labels agree with the hand-read sample on only {rv['agree']} of {rv['reviewed']} messages.")
    if new["committee_seats"] != old.get("committee_seats"):
        changes.append(f"Committee seats by year: {old.get('committee_seats')} → {new['committee_seats']}")
    if new["unreviewed_name_changes"]:
        alerts.append("Listed names changed for: " + ", ".join(new["unreviewed_name_changes"])
                      + ". Check each by hand and add it to data/reference/name_changes.csv (and person_aliases.csv if the person key changed).")
    return changes or ["No headline numbers changed."], alerts


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary")
    ap.add_argument("--alert")
    a = ap.parse_args(argv)
    new, old = headline(), previous()
    changes, alerts = compare(new, old)
    (ROOT / HEAD_FILE).write_text(json.dumps(new, indent=2) + "\n")
    cur = max(new["sessions"], key=int)
    n = new["sessions"][cur]
    title = f"Refresh data {new['date']}: {label(int(cur))} {n['bills']} bills, {n['signed']} signed, {n['vetoed']} vetoed"
    (ROOT / "commit_message.txt").write_text(title + "\n\n" + "\n".join(f"- {c}" for c in changes)
                                             + ("\n\nAlerts:\n" + "\n".join(f"- {x}" for x in alerts) if alerts else "") + "\n")
    md = [f"## {title}", "", "| Session | Bills | Signed | Vetoed | Signed % | Members | Finished |", "|---|---|---|---|---|---|---|"]
    md += [f"| {label(int(s))} | {v['bills']} | {v['signed']} | {v['vetoed']} | {v['signed_pct']} | {v['members']} | {'yes' if v['complete'] else 'no'} |"
           for s, v in sorted(new["sessions"].items())]
    md += ["", "### Changes since the last refresh", *[f"- {c}" for c in changes]]
    if alerts:
        md += ["", "### Alerts", *[f"- {x}" for x in alerts]]
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write("\n".join(md) + "\n")
    else:
        print("\n".join(md))
    if a.alert:
        p = Path(a.alert)
        if alerts:
            p.write_text("The weekly data refresh found changes beyond the alert thresholds in scripts/change_report.py.\n\n"
                         + "\n".join(f"- {x}" for x in alerts) + "\n\nAll changes:\n" + "\n".join(f"- {c}" for c in changes) + "\n")
        elif p.exists():
            p.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
