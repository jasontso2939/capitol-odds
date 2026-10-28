"""Staged bill outlook: the chance of clearing each step on the way to the Governor.

A bill is signed only if it clears, in order: its first policy committee, the Appropriations
committee of its house (if sent there), the floor of its house, the second house
(committees, floor and any concurrence vote), and the Governor. Each step gets its own
logistic model, fit only on bills that reached that step, with the same inputs as the
one-step model in calleg.predict. The chance of being signed is the product of the steps.

Step outcomes come from the committee roll calls and the bill's final status:
- policy committee: a passing "do pass" or "be adopted" roll call in the bill's first
  policy committee, or any later progress (sent to Appropriations and passed, or passed
  its house), since a bill cannot get further without clearing it
- Appropriations: among bills that cleared policy committee, not being held in the house of
  origin's Appropriations committee (bills never sent there clear this step; bills sent there
  clear it with a passing roll call or by passing the house). Whether a bill is sent is not
  known in advance: about 4 in 10 bills not marked fiscal when introduced are sent anyway.
- floor: passed the house of origin
- second house: reached the Governor (signed or vetoed)
- Governor: signed
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from . import predict

STAGES = [("policy", "Policy committee"), ("appropriations", "Appropriations"),
          ("floor", "Floor of the first house"), ("second_house", "Second house"), ("governor", "Governor")]
PASS_MOTION = re.compile(r"do pass|be adopted", re.I)


def stage_labels(d: pd.DataFrame, votes: pd.DataFrame) -> pd.DataFrame:
    """reached_<stage> and passed_<stage> columns for each bill in d (one session or several)."""
    ok = votes[(votes.result == "pass") & votes.motion.fillna("").str.contains(PASS_MOTION)]
    ok = ok.drop_duplicates(["BILL_ID", "committee_code"])
    passed_code = set(zip(ok.BILL_ID, ok.committee_code))
    appr_ok = set(zip(ok[ok.committee.fillna("").str.contains("Appropriations")].BILL_ID,
                      ok[ok.committee.fillna("").str.contains("Appropriations")].house))
    out = pd.DataFrame(index=d.index)
    sent_appr = np.where(d.origin == "Assembly", d.appr_Assembly, d.appr_Senate).astype(bool)
    appr_pass_vote = np.array([(b, h) in appr_ok for b, h in zip(d.BILL_ID, d.origin)])
    po = d.passed_origin.fillna(False).astype(bool).values
    pol_vote = np.array([(b, c) in passed_code for b, c in zip(d.BILL_ID, d.first_policy_code)])
    out["reached_policy"] = True
    out["passed_policy"] = pol_vote | po | (sent_appr & appr_pass_vote)
    out["sent_appropriations"] = out.passed_policy.values & sent_appr
    out["reached_appropriations"] = out.passed_policy
    out["passed_appropriations"] = out.passed_policy.values & (~sent_appr | po | appr_pass_vote)
    out["reached_floor"] = out.passed_appropriations
    out["passed_floor"] = out.reached_floor.values & po
    out["reached_second_house"] = out.passed_floor
    out["passed_second_house"] = out.reached_second_house.values & d.outcome.isin(["signed", "vetoed"]).values
    out["reached_governor"] = out.passed_second_house
    out["passed_governor"] = out.reached_governor.values & (d.outcome == "signed").values
    return out


def _fit(X: pd.DataFrame, y: np.ndarray, w: np.ndarray | None = None) -> LogisticRegression:
    return LogisticRegression(C=predict.C, max_iter=5000).fit(X.values, y, sample_weight=w)


def fit_stages(d: pd.DataFrame, lab: pd.DataFrame, X: pd.DataFrame, w: np.ndarray | None = None) -> dict:
    """One model per step, on bills that reached it. X is predict.design(d, d, leave_one_out=True).

    Recent sessions count more (predict.recency_weights); w, if given, multiplies those weights."""
    rw = predict.recency_weights(d)
    if rw is not None:
        w = rw if w is None else w * rw
    models = {}
    for s, _ in STAGES:
        r = lab[f"reached_{s}"].values
        ww = None if w is None else w[r]
        models[s] = _fit(X[r], lab[f"passed_{s}"].values[r].astype(int), ww)
    return models


def stage_probs(models: dict, X: pd.DataFrame) -> pd.DataFrame:
    """Per-step chances and their product, the chance of being signed."""
    P = pd.DataFrame({s: models[s].predict_proba(X.values)[:, 1] for s, _ in STAGES}, index=X.index)
    P["signed"] = P[[s for s, _ in STAGES]].prod(axis=1)
    return P


def evaluate(d: pd.DataFrame, votes: pd.DataFrame) -> dict:
    """Train on earlier sessions, test on the latest one (as predict.evaluate does)."""
    lab = stage_labels(d, votes)
    last = d.session.max()
    a, b = d.session < last, d.session == last
    da, db = d[a], d[b].assign(session=d.session[a].max())
    Xa = predict.design(da, da, leave_one_out=True)
    Xb = predict.design(da, db, columns=list(Xa.columns))
    models = fit_stages(da, lab[a].reset_index(drop=True).set_index(Xa.index), Xa)
    P = stage_probs(models, Xb)
    res = {"out_of_session_auc": round(float(roc_auc_score(db.signed, P.signed)), 3),
           "out_of_session_predicted_rate": round(float(P.signed.mean()), 3),
           "out_of_session_actual_rate": round(float(db.signed.mean()), 3), "steps": []}
    lb = lab[b].set_index(Xb.index)
    for s, name in STAGES:
        r = lb[f"reached_{s}"].values
        y = lb[f"passed_{s}"].values[r]
        auc = roc_auc_score(y, P[s].values[r]) if 0 < y.mean() < 1 else None
        res["steps"].append({"step": s, "name": name, "bills_reaching": int(r.sum()), "actual_pass_rate": round(float(y.mean()), 3),
                             "predicted_pass_rate": round(float(P[s].values[r].mean()), 3),
                             "auc": None if auc is None else round(float(auc), 3)})
    return res


def export(models: dict, columns: list[str]) -> dict:
    return {s: {"intercept": round(float(m.intercept_[0]), 4), "coef": dict(zip(columns, m.coef_[0].round(4)))}
            for s, m in models.items()}


# Sessions left out of the range on the outlook page. 2019-20 was cut short by the pandemic
# (24% of bills signed, against 35% to 45% in the other sessions).
ATYPICAL = {2019: "pandemic"}


def bootstrap(d: pd.DataFrame, lab: pd.DataFrame, X: pd.DataFrame, draws: int = 40, seed: int = 0) -> dict:
    """Refits of every step on resampled bills (Poisson weights, a standard bootstrap shortcut).

    Each draw is paired with one past session, cycling through the sessions in training other
    than ATYPICAL ones, and the browser scores the bill at that session's level. The spread of
    the results (10th to 90th percentile) is the range on the outlook page: it covers both how
    much the fit depends on which bills happened to be in the data and how much a typical
    session differs from another.

    Subject-line word weights (w_ columns) are left out of the draws to keep the download
    small; the browser adds them from the main fit, so the range reflects every other input."""
    rng = np.random.default_rng(seed)
    cols = list(X.columns)
    keep = [i for i, c in enumerate(cols) if not c.startswith("w_")]
    sess = [int(s) for s in sorted(d.session.unique()) if int(s) not in ATYPICAL]
    out = []
    for i in range(draws):
        w = rng.poisson(1.0, len(d)).astype(float)
        ms = fit_stages(d, lab, X, w)
        out.append({"session": sess[i % len(sess)],
                    **{s: [round(float(m.intercept_[0]), 3)] + [round(float(m.coef_[0][i]), 3) for i in keep] for s, m in ms.items()}})
    return {"columns": [cols[i] for i in keep], "draws": out}


def cross_validate(d: pd.DataFrame, lab: pd.DataFrame, folds: int = 5, seed: int = 0) -> dict:
    """Five-fold estimate of the product's accuracy and calibration, like predict.evaluate."""
    from sklearn.model_selection import StratifiedKFold
    y = d.signed.astype(int).values
    p = np.zeros(len(d))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=seed).split(d, y):
        a, b = d.iloc[tr], d.iloc[te]
        Xa = predict.design(a, a, leave_one_out=True)
        ms = fit_stages(a, lab.iloc[tr].set_index(Xa.index), Xa)
        p[te] = stage_probs(ms, predict.design(a, b, columns=list(Xa.columns))).signed.values
    cal = pd.DataFrame({"p": p, "y": y})
    cal["band"] = pd.cut(cal.p, [0, .2, .3, .4, .5, .6, .7, 1.0])
    calib = cal.groupby("band", observed=True).agg(bills=("y", "size"), predicted=("p", "mean"),
                                                    actual=("y", "mean")).reset_index()
    calib["band"] = calib.band.astype(str)
    return {"cv_auc": round(float(roc_auc_score(y, p)), 3), "calibration": calib.round(3).to_dict(orient="records")}
