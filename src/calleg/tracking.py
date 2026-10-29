"""Track a filed bill: the chance it is signed, given what has happened to it so far.

The drafting model (calleg.predict, calleg.stages) sees only what is known when a bill is
introduced. Once a bill is in print, its history adds a lot: whether the author set it for a
hearing or canceled one, amended it, got it out of committee, or saw it parked on the
suspense file. For each checkpoint (days since introduction) a separate model learns from
every finished session's bills as they stood that many days in. Only history actions dated
on or before the checkpoint are used, so no checkpoint model sees the bill's later fate.

Models are trained on earlier sessions and tested on the latest finished one, the same way
the drafting model is tested; recent sessions count more (RECENCY) so the models follow the
way the Legislature works now rather than fifteen years ago.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from . import predict

CHECKPOINTS = [30, 60, 90, 120, 180, 270, 365]
# Bill history actions counted up to each checkpoint (case-insensitive patterns)
ACTIONS = {
    "author_amend": r"author's amendments|amended and re-referred|Read second time and amended",
    "canceled": r"canceled at the request of author",
    "hearing_set": r"Set, first hearing|Set for first hearing",
    "passed_policy": r"From committee: Do pass",
    "to_appr": r"Com\. on APPR",
    "suspense": r"suspense file",
    "held": r"Held in committee|held under submission",
    "passed_house": r"Ordered to the (?:Senate|Assembly)|passed,? and to|^In (?:Senate|Assembly)\.",
    "failed": r"failed passage",
    "inactive": r"inactive file",
    "coauthors_rev": r"Coauthors revised|Principal coauthor",
}
C = predict.C


def read_history(raw: str | Path) -> pd.DataFrame:
    from .pipeline import read_table
    h = read_table(Path(raw), "BILL_HISTORY_TBL", ["BILL_ID", "ACTION_DATE", "ACTION", "ACTION_SEQUENCE"])
    h["d"] = pd.to_datetime(h.ACTION_DATE.str[:10])
    h["a"] = h.ACTION.fillna("").str.replace(r"\s+", " ", regex=True)
    return h[["BILL_ID", "d", "a"]]


def action_flags(h: pd.DataFrame) -> pd.DataFrame:
    """One column per action pattern, 1 where a history row matches (computed once)."""
    out = h[["BILL_ID", "d"]].copy()
    for k, p in ACTIONS.items():
        out[k] = h.a.str.contains(p, case=False, regex=True).astype(np.int16)
    return out


def double_referred(h: pd.DataFrame) -> pd.Series:
    """True when the first policy committee referral names two committees (known at referral)."""
    ref = h[h.a.str.contains(r"^(?:Re-)?[Rr]eferred to Coms?\.") & ~h.a.str.contains(r"Coms?\. on RLS\.?$")]
    first = ref.sort_values("d").groupby("BILL_ID").a.first()
    return first.str.contains(r"Coms\.| and ")


def checkpoint_features(flags: pd.DataFrame, intro: pd.Series, days: int) -> pd.DataFrame:
    """Counts of each action within `days` of introduction, log-scaled. intro: BILL_ID -> date."""
    age = (flags.d - flags.BILL_ID.map(intro)).dt.days
    f = flags[age <= days]
    g = f.groupby("BILL_ID")
    X = g[list(ACTIONS)].sum()
    X["n_actions"] = g.size()
    return np.log1p(X)


def weights(train: pd.DataFrame, target_session: int) -> np.ndarray:
    return predict.recency_weights(train, target_session)


def base(train: pd.DataFrame, target: pd.DataFrame, dbl: pd.Series, columns: list[str] | None = None) -> pd.DataFrame:
    """The drafting model's inputs plus double referral (computed once per train/target pair)."""
    X = predict.design(train, target, leave_one_out=columns is None)
    if "double_referred" not in X:
        X["double_referred"] = target.BILL_ID.map(dbl).fillna(False).astype(float).values
    if columns is not None:
        X = X.reindex(columns=columns, fill_value=0.0)
    return X.astype(np.float32)


def with_checkpoint(X: pd.DataFrame, target: pd.DataFrame, cp: pd.DataFrame | None) -> np.ndarray:
    if cp is None:
        return X.values
    C_ = cp.reindex(target.BILL_ID).fillna(0.0).astype(np.float32)
    return np.hstack([X.values, C_.reindex(columns=list(ACTIONS) + ["n_actions"], fill_value=0.0).values])


def _fit(X: np.ndarray, y, w):
    return LogisticRegression(C=C, max_iter=5000).fit(X, y, sample_weight=w)


def evaluate(d: pd.DataFrame, flags: pd.DataFrame, dbl: pd.Series) -> list[dict]:
    """Train on sessions before the latest finished one, test on it, at each checkpoint."""
    last = d.session.max()
    a, b = d[d.session < last], d[d.session == last]
    bb = b.assign(session=a.session.max())
    intro = d.set_index("BILL_ID").intro_date
    w = weights(a, last)
    Xa = base(a, a, dbl)
    Xb = base(a, bb, dbl, columns=list(Xa.columns))
    rows = []
    for k in [0] + CHECKPOINTS:
        cp = None if k == 0 else checkpoint_features(flags, intro, k)
        p = _fit(with_checkpoint(Xa, a, cp), a.signed, w).predict_proba(with_checkpoint(Xb, b, cp))[:, 1]
        rows.append({"days": k, "auc": round(float(roc_auc_score(b.signed, p)), 3),
                     "predicted_rate": round(float(p.mean()), 3), "actual_rate": round(float(b.signed.mean()), 3)})
    return rows


def fit_score(d: pd.DataFrame, score: pd.DataFrame, flags: pd.DataFrame, dbl: pd.Series,
              finished: bool = False) -> pd.DataFrame:
    """Fit each checkpoint model on d (finished sessions) and score the bills in `score`.

    Returns one row per bill in `score` with the chance of being signed at introduction
    (p0) and at each checkpoint (p30, p60, ...); a checkpoint not yet reached is left blank,
    unless the session is finished (every bill's history is then final)."""
    ref = d.session.max()
    intro = pd.concat([d, score]).drop_duplicates("BILL_ID").set_index("BILL_ID").intro_date
    w = weights(d, ref + 2)
    sc = score.assign(session=np.where(score.session.isin(d.session), score.session, ref))
    out = pd.DataFrame({"BILL_ID": score.BILL_ID.values}, index=score.index)
    age = np.full(len(score), 10_000) if finished else (flags.d.max() - score.intro_date).dt.days.values
    Xa = base(d, d, dbl)
    Xs = base(d, sc, dbl, columns=list(Xa.columns))
    for k in [0] + CHECKPOINTS:
        cp = None if k == 0 else checkpoint_features(flags, intro, k)
        p = _fit(with_checkpoint(Xa, d, cp), d.signed, w).predict_proba(with_checkpoint(Xs, score, cp))[:, 1]
        out[f"p{k}"] = np.where(age >= k, p.round(3), np.nan)
    return out


# Milestones shown on the tracking chart: what happened to a bill and when. Codes:
# pc passed policy committee, ap out of Appropriations, su suspense file, hd held in committee,
# pa passed the Assembly, ps passed the Senate, cc amendments concurred in, fl failed passage,
# gv sent to the Governor, sg signed, vt vetoed, in moved to the inactive file, cn hearing canceled
# at the author's request, dd died.
EVENT_PATTERNS = [
    ("sg", r"^Approved by the Governor|^Approved by Governor"),
    ("vt", r"^Vetoed by (?:the )?Governor"),
    ("gv", r"^Enrolled and presented to the Governor"),
    ("cc", r"amendments concurred in"),
    ("fl", r"failed passage|^Failed"),
    ("su", r"suspense file"),
    ("hd", r"Held in committee|held under submission"),
    ("in", r"inactive file"),
    ("cn", r"canceled at the request of author"),
    ("dd", r"^Died|Filed with the Chief Clerk pursuant to Joint Rule 56|Returned to Secretary of Senate pursuant to Joint Rule 56"),
]
VOTE = r"\(Ayes (\d+)\. Noes (\d+)\."


def bill_events(h: pd.DataFrame) -> dict:
    """{BILL_ID: [[date, code, ayes, noes], ...]} from history rows (BILL_ID, d, a) in action order."""
    import re
    pats = [(c, re.compile(p, re.I)) for c, p in EVENT_PATTERNS]
    vote = re.compile(VOTE)
    out: dict = {}
    for bid, g in h.groupby("BILL_ID", sort=False):
        ev, where = [], "policy"
        for d, a in zip(g.d, g.a):
            v = vote.search(a)
            ay, no = (int(v.group(1)), int(v.group(2))) if v else (None, None)
            code = None
            if a.startswith("From committee") and re.search(r"Do pass|Be ordered to second reading|Be adopted", a, re.I):
                code = "ap" if where == "appr" else "pc"
            elif re.search(r"Passed\.?.*Ordered to the (Senate|Assembly)", a) or re.search(r"^Read third time\.? Passed.*To (?:the )?(Senate|Assembly)", a):
                code = "pa" if re.search(r"Ordered to the Senate|To (?:the )?Senate", a) else "ps"
            else:
                for c, p in pats:
                    if p.search(a):
                        code = c
                        break
            if re.search(r"(?:Re-)?[Rr]eferred to Coms?\. on|To Coms?\. on", a):
                where = "appr" if re.search(r"Com\. on APPR", a) and not re.search(r"re-refer to Com\. on APPR", a) else where
                if re.search(r"(?:Re-)?[Rr]eferred to Coms?\. on (?!APPR)", a) and "APPR" not in a.split("on", 1)[-1][:6]:
                    where = "policy"
            if re.search(r"(?:Re-)?[Rr]eferred to Com\. on APPR|re-refer to Com\. on APPR", a):
                where = "appr"
            once = code in ("dd", "gv", "sg", "vt")
            if code and not (ev and ev[-1][1] == code and (once or ev[-1][0] == d)):
                ev.append([d, code, ay, no])
        if ev:
            out[bid] = ev
    return out
