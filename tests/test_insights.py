"""Checks on the trends and the bill outlook model.

The first group reads the committed site/insights.js and always runs. The second
rebuilds from the raw export and is skipped when it has not been downloaded.
"""
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/pubinfo_2025"
JS = ROOT / "site/insights.js"


@pytest.fixture(scope="module")
def ins():
    t = JS.read_text()
    return json.loads(t[t.index("{"): t.rstrip().rstrip(";").rindex("}") + 1])


def test_insights_has_every_section(ins):
    assert {"session", "sessions", "trends", "model", "metrics"} <= ins.keys()
    assert {"all", "2017", "2019", "2021", "2023", "2025", "over_time"} <= ins["trends"].keys()
    assert {"appropriations_by_party", "where_failed_bills_died", "policy_area_risk", "fiscal_flags",
            "coalition", "timing", "second_house", "spot_bills", "veto_rate_by_area", "veto_reasons"} <= ins["trends"]["2025"].keys()


def test_appropriations_counts_add_up(ins):
    for r in ins["trends"]["all"]["appropriations_by_party"] + ins["trends"]["2017"]["appropriations_by_party"]:
        assert 0 <= r["died"] <= r["sent"]
        assert r["pct_died"] == pytest.approx(100 * r["died"] / r["sent"], abs=0.06)


def test_where_failed_bills_died_sums_to_100(ins):
    for p in ["D", "R"]:
        tot = sum(r["pct"] for r in ins["trends"]["all"]["where_failed_bills_died"] if r["party"] == p)
        assert tot == pytest.approx(100, abs=0.2)


def test_model_is_better_than_base_rate_and_reported_honestly(ins):
    m = ins["metrics"]
    assert 0.6 <= m["cv_auc"] <= 0.8          # if this jumps, look for leakage before celebrating
    assert m["cv_brier"] < m["base_brier"]
    assert m["within_session_auc"] > 0.6
    assert m["out_of_session_auc"] > 0.6           # trained on 2017-2024, tested on 2025-26
    assert abs(m["out_of_session_predicted_rate"] - m["out_of_session_actual_rate"]) < 0.08
    assert m["sessions"] == [2017, 2019, 2021, 2023, 2025]
    assert sum(c["bills"] for c in m["calibration"]) == m["bills"]


def test_every_model_category_has_a_coefficient(ins):
    mod = ins["model"]
    for a in mod["policy_areas"]:
        assert f"policy_area_{a}" in mod["coef"]
    for w in mod["filing_windows"]:
        assert f"filing_window_{w}" in mod["coef"]
    assert set(mod["party_prior"]) == {"D", "R"}


def test_no_office_specific_content_in_site():
    for f in ["index.html", "trends.html", "outlook.html"]:
        assert "Not affiliated with any office or legislator" in (ROOT / "site" / f).read_text()


raw = pytest.mark.skipif(not (RAW / "BILL_TBL.dat").exists(), reason="raw export not downloaded")


@raw
def test_exported_coefficients_reproduce_sklearn_predictions():
    """The browser computes the logit by hand from the export; it must match sklearn."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from calleg import predict
    from calleg.features import build_features
    m = build_features(RAW, RAW.parent / "pubinfo_2025.zip", ROOT / "data/processed/intro_text.csv")
    d = predict.training_frame(m[~m.is_budget])
    X = predict.design(d, d, leave_one_out=True)
    clf = LogisticRegression(C=predict.C, max_iter=5000).fit(X.values, d.signed.astype(int))
    exp = predict.fit_export(d)
    z = exp["intercept"] + sum(X[c].values * exp["coef"][c] for c in X.columns)
    p_js = 1 / (1 + np.exp(-z))
    assert np.abs(p_js - clf.predict_proba(X.values)[:, 1]).max() < 0.01


@raw
def test_author_record_is_shrunk_toward_party_average():
    from calleg import predict
    from calleg.features import build_features
    m = build_features(RAW, RAW.parent / "pubinfo_2025.zip", ROOT / "data/processed/intro_text.csv")
    exp = predict.fit_export(predict.training_frame(m[~m.is_budget]))
    for a in exp["authors"]:
        prior = exp["party_prior"][a["party"]]
        assert abs(a["author_record"] - prior) < 4  # bounded by smoothing
    lo = min(exp["authors"], key=lambda a: a["bills"])
    assert abs(lo["author_record"] - exp["party_prior"][lo["party"]]) < 1.5 or lo["bills"] > 8
    assert not math.isnan(exp["intercept"])
