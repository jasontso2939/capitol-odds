"""Bill outlook model: chance a bill is signed, from what is known when it is introduced.

A regularized logistic regression, chosen so every coefficient can be read and the
model can run in the browser. Inputs: author party and house, first policy committee,
filing window, fiscal features of the introduced bill, coauthors and joint leads at
introduction, spot-bill status, the author's own track record (smoothed toward
the party average), and the author's relationship to the committee: whether the author
sits on or chairs it. Bills never referred to a policy committee are left out, so the
output reads as "chance of being signed once referred to this committee".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold

CATS = ["party", "origin", "policy_area", "filing_window"]
BINS = ["appropriation", "urgency", "taxlevy", "local_program", "supermajority",
        "cross_party_coauthor", "cross_party_joint_lead", "spot_bill"]
REL = ["author_on_committee", "author_chairs_committee"]   # from committee roll calls (calleg.committees)
SMOOTH_K = 8   # bills of "prior" weight when shrinking an author's record toward the party average
C = 0.5


def training_frame(m: pd.DataFrame) -> pd.DataFrame:
    d = m[~m.is_budget & m.policy_area.notna() & m.party.isin(["D", "R"])].copy()
    d["filing_window"] = d.filing_window.replace({"late (rule waiver)": "Feb 15-deadline"})
    return d.reset_index(drop=True)


def _author_logit(train: pd.DataFrame, target: pd.DataFrame, leave_one_out: bool) -> np.ndarray:
    prior = train.groupby("party").signed.mean()
    g = train.groupby("member").signed.agg(["sum", "count"])
    out = []
    for mem, p, s in zip(target.member, target.party, target.signed):
        pr = prior.get(p, train.signed.mean())
        if mem in g.index:
            S, N = g.loc[mem, "sum"], g.loc[mem, "count"]
            if leave_one_out:
                S, N = S - s, N - 1
            rate = (S + SMOOTH_K * pr) / (N + SMOOTH_K)
        else:
            rate = pr
        out.append(rate)
    a = np.clip(np.array(out, dtype=float), 1e-3, 1 - 1e-3)
    return np.log(a / (1 - a))


def design(train: pd.DataFrame, target: pd.DataFrame, columns: list[str] | None = None,
           leave_one_out: bool = False) -> pd.DataFrame:
    X = pd.get_dummies(target[CATS]).astype(float)
    for b in BINS:
        X[b] = target[b].astype(float).values
    X["log1p_coauthors"] = np.log1p(target.n_coauthors_intro.values)
    X["joint_lead"] = (target.n_leads_intro.values > 1).astype(float)
    X["author_record"] = _author_logit(train, target, leave_one_out)
    if all(c in target for c in REL):
        for c in REL:
            X[c] = target[c].astype(float).values
    if columns is not None:
        X = X.reindex(columns=columns, fill_value=0.0)
    return X


def evaluate(d: pd.DataFrame, folds: int = 5, seed: int = 0) -> dict:
    y = d.signed.astype(int).values
    p = np.zeros(len(d))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=seed).split(d, y):
        Xtr = design(d.iloc[tr], d.iloc[tr], leave_one_out=True)
        Xte = design(d.iloc[tr], d.iloc[te], columns=list(Xtr.columns))
        clf = LogisticRegression(C=C, max_iter=5000).fit(Xtr.values, y[tr])
        p[te] = clf.predict_proba(Xte.values)[:, 1]
    a, b = d[d.filed_year == 2025], d[d.filed_year == 2026]
    Xa = design(a, a, leave_one_out=True)
    q = LogisticRegression(C=C, max_iter=5000).fit(Xa.values, a.signed).predict_proba(
        design(a, b, columns=list(Xa.columns)).values)[:, 1]
    cal = pd.DataFrame({"p": p, "y": y})
    cal["band"] = pd.cut(cal.p, [0, .2, .3, .4, .5, .6, .7, 1.0])
    calib = cal.groupby("band", observed=True).agg(bills=("y", "size"), predicted=("p", "mean"),
                                                    actual=("y", "mean")).reset_index()
    calib["band"] = calib.band.astype(str)
    return {"bills": len(d), "base_rate": round(float(y.mean()), 3),
            "cv_auc": round(float(roc_auc_score(y, p)), 3),
            "cv_brier": round(float(brier_score_loss(y, p)), 3),
            "base_brier": round(float(brier_score_loss(y, np.full(len(y), y.mean()))), 3),
            "temporal_auc_2025_to_2026": round(float(roc_auc_score(b.signed, q)), 3),
            "calibration": calib.round(3).to_dict(orient="records")}


def fit_export(d: pd.DataFrame) -> dict:
    X = design(d, d, leave_one_out=True)
    clf = LogisticRegression(C=C, max_iter=5000).fit(X.values, d.signed.astype(int))
    coef = dict(zip(X.columns, clf.coef_[0].round(4)))
    authors = (d.groupby(["member", "party", "origin"]).size().reset_index(name="bills"))
    full_logit = _author_logit(d, authors.assign(signed=0), leave_one_out=False)
    authors["author_record"] = full_logit.round(4)
    areas = sorted(d.policy_area.unique())
    prior = d.groupby("party").signed.mean().clip(1e-3, 1 - 1e-3)
    party_prior = {p: round(float(np.log(r / (1 - r))), 4) for p, r in prior.items()}
    return {"intercept": round(float(clf.intercept_[0]), 4), "coef": coef,
            "party_prior": party_prior,
            "authors": authors.to_dict(orient="records"),
            "policy_areas": areas, "filing_windows": sorted(d.filing_window.unique()),
            "base_rate": round(float(d.signed.mean()), 3)}
