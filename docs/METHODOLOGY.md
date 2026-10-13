# Methodology

## Sessions

Five two-year sessions: 2017-18, 2019-20, 2021-22, 2023-24 and 2025-26. The current session is read from the full leginfo download; earlier ones from compact archives packed once by `.github/workflows/archive-sessions.yml` (gzipped copies of the same tables, the veto message text, and introduced-text statistics, with the download's SHA-256 recorded). Each session is processed on its own: committee codes are reassigned between sessions, so committees are matched by name, never by code.

- **One name per person.** The export sometimes lists one legislator twice in a session under a spelling or married-name variant (Kamlager / Kamlager-Dove, Gonzalez / Gonzalez Fletcher). Two names for the same seat and first name are merged, keeping the name with more bills.
- **Partial terms.** Flagged when two members held the same seat in a session (a resignation and special election), plus the current session's documented changes in `data/reference/seat_changes.csv`.
- **Across sessions.** The model links an author's sessions by last and first name, since the short author name can belong to different people in different years.

These rules are implemented in `src/calleg/model.py` and checked by `tests/`.

## Roster
Every legislator in the official 2025-26 roster, by chamber. Ranks are computed within each chamber.

## Lead author
Anyone listed under "Lead Authors" on a bill's status page. Co-authors are excluded. Resolutions are listed separately and are not part of any rank.

## Two counting methods
- `all_leads` (default): every lead author gets credit. This is the official definition.
- `first_listed`: only the first-listed lead author gets credit. Bulk exports of bill data show only this author.

Joint lead authors are common, so the two methods rank some members differently.

## Periods
- Introduced is counted by the year the bill was filed. Bills pre-filed in December 2024, after the session opened on Dec 2, 2024, count as 2025. 
- Signed and vetoed are counted by the year of the Governor's action.
- Sent to the Governor = signed + vetoed.

## Success rate
signed / introduced, as a percent rounded to one decimal.
- Session scope: all signed bills over all introduced bills.
- Year scope: a cohort rate. Of the bills filed that year, the share signed at any point. A 2025 bill signed in 2026 counts toward the 2025 rate.

## Ranking
Competition ranking: ties share the best rank (1, 2, 2, 4). Rank by bills signed breaks display ties by success rate. Rates are compared at one decimal place. Republican rank is computed within Republicans only.

## Known limits
- Success rate favors members who file fewer bills, so counts are shown beside it.
- Members who joined or left mid-session have partial records and are flagged.
- Counts do not weigh a bill's importance.

## Pipeline
- Source: the Legislature's public pubinfo export (`scripts/fetch_raw.sh`). `python -m calleg.build` turns it into `data/processed/`.
- Scope: regular-session AB and SB only. Extraordinary-session bills reuse numbers (AB 3) and are excluded. Resolutions are not scored.
- Lead author: `LEAD_AUTHOR` rows on the bill's latest version. First-listed is the export's `PRIMARY_AUTHOR_FLG`.
- Outcome: signed if chaptered or "Approved by the Governor"; vetoed if status is Vetoed or history shows a veto. Senate vetoes keep status "In Floor Process" until the override vote, so history adds 30 bills to the 213 with a Vetoed status.
- Ranks are computed within each chamber, and Republican ranks within each chamber's Republicans.
- Partial terms are listed in `data/reference/seat_changes.csv` with sources (SD-36, AD-32, AD-63).
- Budget Act bills are introduced under the budget chairs' names (Gabriel 45, Laird 11, Wiener 7). They are excluded from counts and ranks by default (the dashboard has a toggle to include them) and shown in a `budget_bills` column.
- Validation: unit tests on the counting rules (`tests/test_model.py`) and data-quality checks on the full build (`tests/test_data_quality.py`).

## Trends and the bill outlook model

The Trends and Bill outlook pages use a bill-level table built in `src/calleg/features.py`. "Died in Appropriations" means the bill's final location is an Appropriations committee (Assembly CX25, Senate CS61). A bill's policy committee is its first referral outside Rules and Appropriations. Veto reasons come from keyword rules applied to the Governor's veto messages (VETO_MESSAGE_TBL), assigned in a fixed priority order; they approximate the main stated reason. The model, its inputs and its accuracy are documented in `docs/MODEL.md`.

## Committees

Committee rosters, chairs and member votes come from the committee roll calls, which list every member on each hearing date with the chair first. Rules and checks are in `docs/COMMITTEES.md`.
