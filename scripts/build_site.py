"""Build the scorecard data for the site, one file per session: site/data/scorecard_<year>.js.
Run: PYTHONPATH=src python3 scripts/build_site.py"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg import scorecard, METHODS  # noqa: E402
from calleg.pipeline import build  # noqa: E402
from calleg.build import prepare_members  # noqa: E402
from calleg.sessions import available, raw_dir, label  # noqa: E402

out_dir = ROOT / "site" / "data"
out_dir.mkdir(parents=True, exist_ok=True)
index = []
for year in available():
    bills, members = build(raw_dir(year))
    members = prepare_members(bills, members)
    flat = bills.drop(columns=["author_house"])
    bud = flat[flat.is_budget].groupby("member").size().rename("budget_bills").reset_index()
    cards = {}
    for excl in (True, False):  # budget bills excluded from ranks by default
        src = flat[~flat.is_budget] if excl else flat
        for m in METHODS:
            for s in ("session", year, year + 1):
                parts = [scorecard(src, members[members.chamber == ch], m, s).assign(chamber=ch)
                         for ch in ("Assembly", "Senate")]
                t = pd.concat(parts, ignore_index=True).merge(members[["member", "partial_term"]], on="member")
                t = t.merge(bud, on="member", how="left").fillna({"budget_bills": 0})
                t["budget_bills"] = t.budget_bills.astype(int)
                cards[f"{m}|{s}|{'excl' if excl else 'incl'}"] = json.loads(t.to_json(orient="records"))
    cols = ["bill_id", "member", "is_first_listed", "is_joint", "introduced", "outcome",
            "action_date", "lead_authors", "title", "filed_year", "action_year", "is_budget"]
    data = {"session": year, "label": label(year), "cards": cards,
            "bills": json.loads(flat[cols].to_json(orient="records")),
            "source": f"California Legislative Information (leginfo) public bulk export, {label(year)} session"}
    (out_dir / f"scorecard_{year}.js").write_text(
        f"(window.ALLS = window.ALLS || {{}})[{year}] = " + json.dumps(data, separators=(",", ":")) + ";\n")
    index.append({"year": year, "label": label(year), "bills": int(flat.bill_id.nunique())})
    print(f"wrote site/data/scorecard_{year}.js", len(flat), "bill rows")
(out_dir / "sessions.js").write_text("window.SESSIONS = " + json.dumps(index) + ";\n")
old = ROOT / "site" / "data.js"
if old.exists():
    old.unlink()
