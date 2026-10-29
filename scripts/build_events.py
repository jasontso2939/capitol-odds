"""Milestones for every bill on the tracking page (site/data/events.js).

For each bill in site/data/tracking.js: committee votes, the suspense file, floor votes and the
Governor's action, as days after introduction with the vote count where there is one. The
outlook page loads this file when a bill is shown, to mark its odds chart and list what happened.
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from calleg import tracking as TK  # noqa: E402
from calleg.pipeline import read_table  # noqa: E402
from calleg.sessions import raw_dir  # noqa: E402


def main() -> None:
    t = (ROOT / "site/data/tracking.js").read_text()
    T = json.loads(t[t.index("{"): t.rstrip().rstrip(";").rindex("}") + 1])
    s, ci = T["session"], {c: i for i, c in enumerate(T["cols"])}
    intro = {f"{s}{s + 1}0{r[ci['bill_id']]}": pd.Timestamp(r[ci["introduced"]]) for r in T["rows"]}
    h = read_table(raw_dir(s), "BILL_HISTORY_TBL", ["BILL_ID", "ACTION_DATE", "ACTION", "ACTION_SEQUENCE"])
    h = h[h.BILL_ID.isin(intro)].copy()
    h["d"] = pd.to_datetime(h.ACTION_DATE.str[:10])
    h["a"] = h.ACTION.fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    h["seq"] = pd.to_numeric(h.ACTION_SEQUENCE, errors="coerce")
    h = h.sort_values(["BILL_ID", "d", "seq"], kind="stable")
    ev = TK.bill_events(h)
    rows = {bid[len(f"{s}{s + 1}0"):]: [[(d - intro[bid]).days, c] + ([a, n] if a is not None else []) for d, c, a, n in e]
            for bid, e in ev.items()}
    out = {"session": s, "asof": T["asof"], "events": rows}
    (ROOT / "site/data/events.js").write_text("window.EVENTS = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"wrote site/data/events.js: {len(rows)} bills, {sum(map(len, rows.values()))} events")


if __name__ == "__main__":
    main()
