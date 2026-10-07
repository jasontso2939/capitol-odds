"""Build site/data.js (all legislators) from the official export.
Run: PYTHONPATH=src python3 scripts/build_site.py"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg import scorecard, METHODS, SCOPES  # noqa: E402
from calleg.pipeline import build  # noqa: E402
from calleg.build import prepare_members  # noqa: E402

bills, members = build(ROOT / "data/raw/pubinfo_2025")
members = prepare_members(bills, members)
flat = bills.drop(columns=["author_house"])

bud = flat[flat.is_budget].groupby("member").size().rename("budget_bills").reset_index()
cards = {}
for excl in (True, False):  # budget bills excluded from ranks by default
    src = flat[~flat.is_budget] if excl else flat
    for m in METHODS:
        for s in SCOPES:
            parts = [scorecard(src, members[members.chamber == ch], m, s).assign(chamber=ch)
                     for ch in ("Assembly", "Senate")]
            t = pd.concat(parts, ignore_index=True).merge(members[["member", "partial_term"]], on="member")
            t = t.merge(bud, on="member", how="left").fillna({"budget_bills": 0})
            t["budget_bills"] = t.budget_bills.astype(int)
            cards[f"{m}|{s}|{'excl' if excl else 'incl'}"] = json.loads(t.to_json(orient="records"))

cols = ["bill_id", "member", "is_first_listed", "is_joint", "introduced", "outcome",
        "action_date", "lead_authors", "title", "filed_year", "action_year", "is_budget"]
data = {"cards": cards, "bills": json.loads(flat[cols].to_json(orient="records")),
        "source": "California Legislative Information (leginfo) public bulk export, 2025-26 session"}
(ROOT / "site" / "data.js").write_text("window.ALL = " + json.dumps(data, separators=(",", ":")) + ";\n")
print("wrote site/data.js", len(cards), "scorecards", len(flat), "bill rows")
