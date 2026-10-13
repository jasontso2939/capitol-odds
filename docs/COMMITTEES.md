# Committee rosters, chairs and votes

Code: `src/calleg/committees.py`. Build: `make committees` (`scripts/build_committees.py`). Page: `site/committees.html`.

## Source of record: the roll calls

The leginfo export's `BILL_DETAIL_VOTE_TBL` has one row per member per roll call, for every committee and floor vote. On a committee roll call every member of the committee is listed, including members who did not vote (code `ABS`), in a fixed order: chair first, vice chair second, then the other members. That makes the vote record a dated history of who sat on each committee and who led it, for each year.

Checks that the rows are complete: the per-member yes and no counts reproduce the official AYES and NOES in `BILL_SUMMARY_VOTE_TBL` on all 13,863 committee roll calls in the October 2026 export (`tests/test_committees.py`).

## Rules

- **Years covered.** 2017 through 2026 (five sessions). Committees are matched across sessions by name, since codes are reassigned; renamed committees appear under each name they had.
- **Year.** Rosters are built per calendar year from the hearings held that year. Membership and chairs changed between 2025 and 2026 on many committees (for example Assembly Appropriations' vice chair, and the chairs of Senate Appropriations and Senate Budget), so 2025 and 2026 are kept separate.
- **Regular member.** On the roll for at least half of the committee's hearing dates that year. Anyone else is marked "part of year or substitute": they joined or left mid-year, or sat in for an absent member (both houses allow temporary substitutes).
- **Chair and vice chair.** The members listed first and second. A single hearing where the order differs, between two stretches with the same leaders, is treated as a substitution day, not a change, and is noted in `committee_leadership.csv`. Real changes during a year (such as Senate Appropriations' chair between January and April 2026) are kept with their hearing dates.

## Check against the committees' web pages (2025 and 2026)

Earlier years have no web check; their roll calls reproduce the official vote tallies (`tests/test_sessions.py`), and spot checks of known chairs pass (for example Assembly Appropriations: Gonzalez Fletcher 2017 to 2021, Holden 2022 to 2023, Wicks from 2024).


Each committee's members page was read from the Internet Archive near mid-June 2025 and mid-June 2026 (`data/reference/committee_rosters_web.csv`, with the archive URL for every row), then compared with the roll call on the nearest hearing date that year (`data/processed/committee_roster_check.csv`).

| Result | Comparisons |
| --- | --- |
| Roster identical | 78 of 106 |
| Differed only by a temporary substitute that day | 22 |
| Other difference | 6 |
| Chair agrees | 103 |
| Vice chair agrees | 102 |

The other differences and the leadership disagreements all fall on hearings where substitutes sat in, or where membership changed within weeks of the snapshot. Where the web page and the roll call disagree, the roll call is the official record of who sat that day.

## Gaps

- **No roll calls, no roster.** Assembly Budget and Senate Rules hold no committee roll calls in the export, so they have no vote-based roster. Their web rosters are in the reference file. Committees created in 2026 (Senate Emergency Management, Senate Privacy, Digital Technologies, and Consumer Protection) have no 2025 roster.
- **Archive coverage.** Two Assembly committee sites (Economic Development, Growth, and Household Impact; Water, Parks, and Wildlife) had no archived members page, and four Senate snapshots fell outside the target year (marked by their timestamp). The roll calls cover these committees.
- **Roll calls are not all decisions.** Bills held without a vote, such as those left on an Appropriations suspense file, have no roll call. Yes rates therefore describe votes taken, not every bill a committee handled.

## Outputs (data/processed)

| File | One row per |
| --- | --- |
| `committee_votes.csv.gz` | member per committee roll call: bill, committee, date, motion, result, roll position, vote |
| `committee_membership.csv` | committee, year and member: hearings on the roll, share, role, status, leadership dates |
| `committee_chairs_by_year.csv` | committee and year: chair and vice chair with hearing dates |
| `committee_leadership.csv` | stretch of hearings under one chair and vice chair |
| `committee_member_votes.csv` | member and committee: yes, no, absent, yes rate of votes cast |
| `committee_roster_check.csv` | comparison of a web roster with the roll call on the nearest hearing |
