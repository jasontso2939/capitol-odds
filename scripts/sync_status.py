"""Copy each current-session bill's status to the accounts database, for watchlists and the
daily digest.

Reads the tracking file the site already publishes (site/data/tracking.js: title, author,
outcome, odds over time) and, when the session's raw export is on disk, the latest line of
each bill's official history. Writes one row per bill to the public bill_status table with
the service role key. The table's trigger moves changed_at only when something actually
changed, so the digest reports news and nothing else.

    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... python scripts/sync_status.py [YEAR]

Without the two variables it prints what it would send and exits cleanly, so the refresh
workflow keeps working before accounts are switched on.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = 500


def read_tracking(path: Path = ROOT / "site" / "data" / "tracking.js") -> dict:
    text = path.read_text()
    return json.loads(text[text.index("{"): text.rindex("}") + 1])


def latest_actions(raw: Path) -> dict[str, tuple[str, str]]:
    """{bill_id: (date, action)} from BILL_HISTORY_TBL, or {} when the export isn't on disk."""
    sys.path.insert(0, str(ROOT / "src"))
    from calleg.pipeline import table_path
    if not table_path(raw, "BILL_HISTORY_TBL").exists():
        return {}
    from calleg.tracking import read_history
    h = read_history(raw)
    return history_to_latest(h)


def history_to_latest(h) -> dict[str, tuple[str, str]]:
    """Latest action per bill. BILL_ID in the export looks like 202520260AB1."""
    if h.empty:
        return {}
    h = h.sort_values(["BILL_ID", "d"], kind="stable")
    last = h.groupby("BILL_ID").tail(1)
    out = {}
    for bid, d, a in zip(last.BILL_ID, last.d, last.a):
        short = str(bid)[9:] if len(str(bid)) > 9 else str(bid)
        out[short] = (d.strftime("%Y-%m-%d"), a.strip()[:500])
    return out


def build_rows(tracking: dict, actions: dict[str, tuple[str, str]]) -> list[dict]:
    session = int(tracking["session"])
    ci = {c: i for i, c in enumerate(tracking["cols"])}
    pcols = [f"p{k}" for k in tracking["checkpoints"]]
    rows, seen = [], set()
    for r in tracking["rows"]:
        bill = r[ci["bill_id"]]
        ps = [r[ci[c]] for c in pcols if c in ci and r[ci[c]] is not None]
        date, action = actions.get(bill, (None, None))
        rows.append({
            "session": session, "bill_id": bill, "title": r[ci["title"]], "author": r[ci["member"]],
            "outcome": r[ci["outcome"]] or "pending", "last_action": action, "last_action_date": date,
            "odds": round(ps[-1], 4) if ps else None, "odds_intro": round(ps[0], 4) if ps else None,
        })
        seen.add(bill)
    # Bills in the history but not yet tracked (just introduced) still get a row
    for bill, (date, action) in sorted(actions.items()):
        if bill not in seen:
            rows.append({"session": session, "bill_id": bill, "title": None, "author": None, "outcome": "pending",
                         "last_action": action, "last_action_date": date, "odds": None, "odds_intro": None})
    return rows


def upsert(rows: list[dict], url: str, key: str) -> None:
    endpoint = url.rstrip("/") + "/rest/v1/bill_status?on_conflict=session,bill_id"
    for i in range(0, len(rows), BATCH):
        req = urllib.request.Request(endpoint, data=json.dumps(rows[i:i + BATCH]).encode(), method="POST", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status >= 300:
                raise SystemExit(f"[sync_status] upsert failed: HTTP {resp.status}")


def main() -> None:
    tracking = read_tracking()
    year = int(sys.argv[1]) if len(sys.argv) > 1 else int(tracking["session"])
    actions = latest_actions(ROOT / "data" / "raw" / f"pubinfo_{year}") if year == int(tracking["session"]) else {}
    rows = build_rows(tracking, actions)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        print(f"[sync_status] {len(rows)} bills ready; SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set, nothing sent")
        return
    upsert(rows, url, key)
    print(f"[sync_status] sent {len(rows)} bills for {year}")


if __name__ == "__main__":
    main()
