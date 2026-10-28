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
BINS = ["appropriation", "urgency", "taxlevy", "local_program", "supermajority", "fiscal_committee",
        "cross_party_coauthor", "cross_party_joint_lead", "spot_bill"]
REL = ["author_on_committee", "author_chairs_committee"]   # from committee roll calls (calleg.committees)
SMOOTH_K = 8   # bills of "prior" weight when shrinking an author's record toward the party average
C = 0.5
RECENCY = 0.3   # training weight exp(-RECENCY * sessions back): the Legislature of 2009 counts less than 2023's


def recency_weights(train: pd.DataFrame, target_session: int | None = None) -> np.ndarray | None:
    if "session" not in train or train.session.nunique() < 2:
        return None
    t = target_session if target_session is not None else int(train.session.max()) + 2
    return np.exp(-RECENCY * (t - train.session.values) / 2)
# Words in the introduced bill's subject line (the Legislative Counsel's short title), as
# TF-IDF unigrams and bigrams. The browser repeats the same steps (tokenize, idf, l2 norm).
TEXT = dict(min_df=10, ngram_range=(1, 2), sublinear_tf=True, max_features=1500, token_pattern=r"(?u)\b[a-z][a-z]+\b")


def subject_text(df: pd.DataFrame) -> pd.Series:
    return df.intro_subject.fillna("").str.lower()


def text_model(train: pd.DataFrame):
    from sklearn.feature_extraction.text import TfidfVectorizer
    return TfidfVectorizer(**TEXT).fit(subject_text(train))


def training_frame(m: pd.DataFrame) -> pd.DataFrame:
    d = m[~m.is_budget & m.policy_area.notna() & m.party.isin(["D", "R"])].copy()
    d["filing_window"] = d.filing_window.replace({"late (rule waiver)": "Feb 15-deadline"})
    return d.reset_index(drop=True)


def _key(df: pd.DataFrame) -> pd.Series:
    """Author identity across sessions: a person key when available, else the author name."""
    return df["person"] if "person" in df else df["member"]


def _author_logit(train: pd.DataFrame, target: pd.DataFrame, leave_one_out: bool) -> np.ndarray:
    """An author's signed rate, shrunk toward the party average, as a logit.

    leave_one_out (training rows): the bill's own session is left out of its author's record.
    Leaving out only the bill itself leaks its outcome (the record of an author's signed bill
    is lower than the record of the same author's failed bill), which a flexible model learns
    backwards; leaving out the whole session matches how a new session is scored."""
    prior = train.groupby("party").signed.mean()
    by_session = "session" in train and "session" in target and train.session.nunique() > 1
    k = _key(train)
    g = train.assign(_k=k).groupby("_k").signed.agg(["sum", "count"])
    gs = train.assign(_k=k).groupby(["_k", "session"]).signed.agg(["sum", "count"]) if by_session else None
    out = []
    sess = target.session if by_session else [None] * len(target)
    for mem, p, s, ss in zip(_key(target), target.party, target.signed, sess):
        pr = prior.get(p, train.signed.mean())
        if mem in g.index:
            S, N = g.loc[mem, "sum"], g.loc[mem, "count"]
            if leave_one_out:
                if by_session and (mem, ss) in gs.index:
                    S, N = S - gs.loc[(mem, ss), "sum"], N - gs.loc[(mem, ss), "count"]
                elif not by_session:
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
    if "session" in target and train.session.nunique() > 1:
        # session-level differences (a new Governor, the 2020 pandemic year); a new session is
        # scored at the level of the latest session in training
        for s in sorted(train.session.unique()):
            X[f"session_{s}"] = (target.session.values == s).astype(float)
    if all(c in target for c in REL):
        for c in REL:
            X[c] = target[c].astype(float).values
    if "double_referred" in target:
        X["double_referred"] = target.double_referred.fillna(False).astype(float).values
    if "intro_subject" in target and "intro_subject" in train:
        vec = text_model(train)
        T = vec.transform(subject_text(target)).toarray()
        X = pd.concat([X, pd.DataFrame(T, columns=["w_" + w for w in vec.get_feature_names_out()], index=X.index)], axis=1)
    if columns is not None:
        X = X.reindex(columns=columns, fill_value=0.0)
    return X


def evaluate(d: pd.DataFrame, folds: int = 5, seed: int = 0) -> dict:
    y = d.signed.astype(int).values
    p = np.zeros(len(d))
    for tr, te in StratifiedKFold(folds, shuffle=True, random_state=seed).split(d, y):
        Xtr = design(d.iloc[tr], d.iloc[tr], leave_one_out=True)
        Xte = design(d.iloc[tr], d.iloc[te], columns=list(Xtr.columns))
        clf = LogisticRegression(C=C, max_iter=5000).fit(Xtr.values, y[tr], sample_weight=recency_weights(d.iloc[tr]))
        p[te] = clf.predict_proba(Xte.values)[:, 1]
    def holdout(a, b):
        if "session" in b:
            b = b.assign(session=b.session.where(b.session.isin(a.session), a.session.max()))
        Xa = design(a, a, leave_one_out=True)
        q = LogisticRegression(C=C, max_iter=5000).fit(Xa.values, a.signed, sample_weight=recency_weights(a)).predict_proba(
            design(a, b, columns=list(Xa.columns)).values)[:, 1]
        return round(float(roc_auc_score(b.signed, q)), 3), round(float(q.mean()), 3), round(float(b.signed.mean()), 3)
    last = d.session.max() if "session" in d else None
    cur = d[d.session == last] if last is not None else d
    within, _, _ = holdout(cur[cur.filed_year == cur.filed_year.min()], cur[cur.filed_year == cur.filed_year.max()])
    oos = (holdout(d[d.session < last], d[d.session == last])
           if last is not None and (d.session < last).any() else (None, None, None))
    cal = pd.DataFrame({"p": p, "y": y})
    cal["band"] = pd.cut(cal.p, [0, .2, .3, .4, .5, .6, .7, 1.0])
    calib = cal.groupby("band", observed=True).agg(bills=("y", "size"), predicted=("p", "mean"),
                                                    actual=("y", "mean")).reset_index()
    calib["band"] = calib.band.astype(str)
    return {"bills": len(d), "base_rate": round(float(y.mean()), 3),
            "cv_auc": round(float(roc_auc_score(y, p)), 3),
            "cv_brier": round(float(brier_score_loss(y, p)), 3),
            "base_brier": round(float(brier_score_loss(y, np.full(len(y), y.mean()))), 3),
            "sessions": sorted(int(x) for x in d.session.unique()) if "session" in d else None,
            "within_session_auc": within,          # current session: train on its first year, test on its second
            "out_of_session_auc": oos[0],  # train on earlier sessions, test on the current one
            "out_of_session_predicted_rate": oos[1], "out_of_session_actual_rate": oos[2],
            "calibration": calib.round(3).to_dict(orient="records")}


def fit_export(d: pd.DataFrame, members: pd.DataFrame | None = None, current: pd.DataFrame | None = None,
               current_session: int | None = None) -> dict:
    """Fit on d (finished sessions) and export what the browser needs.

    members: the current session's roster (member, party, chamber, person), so authors who
    have not yet carried a bill can be scored. current: the current session's bills, used for
    the committee list when it has enough of them. A new session is scored at the level of
    the latest session in d (the reference session)."""
    X = design(d, d, leave_one_out=True)
    clf = LogisticRegression(C=C, max_iter=5000).fit(X.values, d.signed.astype(int), sample_weight=recency_weights(d))
    coef = dict(zip(X.columns, clf.coef_[0].round(4)))
    ref = int(d.session.max()) if "session" in d else None
    last = d[d.session == ref] if ref is not None else d
    cur = current if current is not None and len(current) else last
    if members is not None:
        authors = members[members.party.isin(["D", "R"])].rename(columns={"chamber": "origin"})
        authors = authors[["member", "party", "origin"] + (["person"] if "person" in authors else [])].drop_duplicates("member")
        authors["bills"] = authors.member.map(cur.groupby("member").size()).fillna(0).astype(int)
    else:
        keep = ["member", "party", "origin"] + (["person"] if "person" in d else [])
        authors = cur.groupby(keep).size().reset_index(name="bills")
    if "person" in d and "person" in authors:
        authors["bills_all_sessions"] = authors.person.map(d.groupby("person").size()).fillna(0).astype(int)
        authors["signed_all_sessions"] = authors.person.map(d.groupby("person").signed.sum()).fillna(0).astype(int)
        authors["sessions"] = authors.person.map(d.groupby("person").session.nunique()).fillna(0).astype(int)
    full_logit = _author_logit(d, authors.assign(signed=0), leave_one_out=False)
    authors["author_record"] = full_logit.round(4)
    # committees of the current session once it has a meaningful number of referred bills
    areas = sorted((cur if len(cur) >= 300 else last).policy_area.dropna().unique())
    prior = d.groupby("party").signed.mean().clip(1e-3, 1 - 1e-3)
    party_prior = {p: round(float(np.log(r / (1 - r))), 4) for p, r in prior.items()}
    return {"intercept": round(float(clf.intercept_[0]), 4), "coef": coef,
            "party_prior": party_prior,
            "authors": authors.to_dict(orient="records"),
            "policy_areas": areas, "filing_windows": sorted(d.filing_window.unique()),
            "base_rate": round(float(last.signed.mean()), 3),          # reference (latest finished) session
            "base_rate_all": round(float(d.signed.mean()), 3),
            "reference_session": ref,
            "current_session": int(current_session) if current_session is not None else ref}
