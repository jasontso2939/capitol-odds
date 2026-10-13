"""Print the first year of the session in progress today (e.g. 2027 from December 2026).
Used by the refresh workflow to pick which leginfo download to fetch."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from calleg.sessions import session_for  # noqa: E402

print(session_for(datetime.date.today()))
