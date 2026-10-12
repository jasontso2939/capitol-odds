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

RAW = ROOT / "data/raw/pubinfo_2025"
m = build_features(RAW, ROOT / "data/raw/pubinfo_2025.zip", ROOT / "data/processed/intro_text.csv")
m = m[~m.is_budget]
trends = all_trends(m, RAW)
d = predict.training_frame(m)
metrics = predict.evaluate(d)
model = predict.fit_export(d)
bills = m[["bill_id", "title", "member", "party", "policy_area", "outcome"]].fillna("")
out = {"session": "2025-26", "trends": trends, "model": model, "metrics": metrics,
       "bills": bills.to_dict(orient="records")}
(ROOT / "site/insights.js").write_text("window.INSIGHTS = " + json.dumps(out, separators=(",", ":"), default=str) + ";\n")
(ROOT / "data/processed/model_metrics.json").write_text(json.dumps(metrics, indent=2))
print("wrote site/insights.js;", "CV AUC", metrics["cv_auc"], "temporal AUC", metrics["temporal_auc_2025_to_2026"])
