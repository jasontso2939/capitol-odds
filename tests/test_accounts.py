"""Accounts: the database migration locks every table to its owner, the status sync sends
clean rows, and the daily digest only reports bills that changed."""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "migrations").glob("*_accounts.sql")
spec = importlib.util.spec_from_file_location("sync_status", ROOT / "scripts" / "sync_status.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_every_table_has_row_level_security():
    sql = next(SQL).read_text()
    tables = set(re.findall(r"create table if not exists public\.(\w+)", sql))
    secured = set(re.findall(r"alter table public\.(\w+)\s+enable row level security", sql))
    assert tables and tables == secured, tables ^ secured
    # Each personal table's policy is keyed to the signed-in person
    for t in tables - {"bill_status"}:
        pol = re.search(rf"create policy \"[^\"]+\" on public\.{t} .*?;", sql, re.S)
        assert pol and "auth.uid()" in pol.group(0), t
    # Nobody but the refresh job writes bill status: its only policy is a read
    assert re.findall(r"create policy \"[^\"]+\" on public\.bill_status for (\w+)", sql) == ["select"]


def test_status_rows_from_tracking_file():
    tracking = sync.read_tracking()
    rows = sync.build_rows(tracking, {})
    assert len(rows) == len(tracking["rows"]) > 1000
    for r in rows:
        assert re.fullmatch(r"[A-Z]{2,5}[0-9]{1,5}", r["bill_id"]), r["bill_id"]
        assert r["outcome"] in {"signed", "vetoed", "not_enacted", "pending"}
        assert r["odds"] is None or 0 <= r["odds"] <= 1
    assert len({r["bill_id"] for r in rows}) == len(rows)


def test_latest_action_per_bill_and_new_bills():
    h = pd.DataFrame({
        "BILL_ID": ["202720280AB5", "202720280AB5", "202720280SB9"],
        "d": pd.to_datetime(["2027-01-10", "2027-02-03", "2027-01-20"]),
        "a": ["Read first time.", "Referred to Com. on HEALTH.", "Introduced."],
    })
    latest = sync.history_to_latest(h)
    assert latest == {"AB5": ("2027-02-03", "Referred to Com. on HEALTH."), "SB9": ("2027-01-20", "Introduced.")}
    tracking = {"session": 2027, "cols": ["bill_id", "title", "member", "outcome", "p0"], "checkpoints": [0],
                "rows": [["AB5", "Health.", "Lee", None, 0.31]]}
    rows = {r["bill_id"]: r for r in sync.build_rows(tracking, latest)}
    assert rows["AB5"]["last_action"].startswith("Referred") and rows["AB5"]["odds"] == 0.31 and rows["AB5"]["outcome"] == "pending"
    assert rows["SB9"]["title"] is None and rows["SB9"]["last_action"] == "Introduced."


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_digest_reports_only_changed_bills(tmp_path):
    script = tmp_path / "t.mjs"
    script.write_text(f"""
import {{compose}} from {json.dumps(str(ROOT / "supabase/functions/digest/compose.js"))};
const st = [
  {{session: 2025, bill_id: "AB1", title: "Water.", outcome: "pending", last_action: "From committee: Do pass.", last_action_date: "2026-01-14", odds: 0.52, odds_intro: 0.40, changed_at: "2026-01-15T10:00:00Z"}},
  {{session: 2025, bill_id: "SB2", title: "Fire.", outcome: "pending", last_action: "Read first time.", last_action_date: "2025-12-02", odds: 0.30, odds_intro: 0.30, changed_at: "2025-12-03T10:00:00Z"}},
  {{session: 2025, bill_id: "AB3", title: "<script>", outcome: "signed", last_action: "Chaptered.", last_action_date: "2026-01-14", odds: 1, odds_intro: 0.5, changed_at: "2026-01-15T09:00:00Z"}},
];
const watch = [{{session: 2025, bill_id: "AB1"}}, {{session: 2025, bill_id: "SB2"}}, {{session: 2025, bill_id: "AB3"}}];
const d = compose({{name: "Pat", watch, status: st, since: new Date("2026-01-01"), unsubscribeUrl: "https://x/u"}});
const none = compose({{watch, status: st, since: new Date("2026-02-01"), unsubscribeUrl: "https://x/u"}});
const first = compose({{watch: [watch[1]], status: st, since: null, unsubscribeUrl: "https://x/u"}});
console.log(JSON.stringify({{d, none, first}}));
""")
    out = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)
    d = out["d"]
    assert d["count"] == 2 and d["subject"] == "2 of your bills moved"
    assert d["text"].index("AB 3") < d["text"].index("AB 1")      # finished bills lead
    assert "SB 2" not in d["text"].split("other watched")[0] and "1 other watched bill had no news" in d["text"]
    assert "+12 pts since introduction" in d["text"]
    assert "<script>" not in d["html"] and "&lt;script&gt;" in d["html"]
    assert "https://x/u" in d["text"] and "https://x/u" in d["html"]
    assert out["none"] is None                                      # nothing changed, no email
    assert out["first"]["count"] == 1                              # first digest covers everything watched
