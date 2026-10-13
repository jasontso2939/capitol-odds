# Data dictionary

## data/processed/bills_all.csv
One row per bill and lead author (regular-session AB and SB).

| Column | Meaning |
| --- | --- |
| `session` | First year of the two-year session: 2017, 2019, 2021, 2023 or 2025 |
| `bill_id` | Bill number without a space, for example `AB460`. Unique within a session, reused across sessions |
| `member` | Author name as the Legislature lists it; matches `members_all.csv` |
| `author_house` | `ASSEMBLY` or `SENATE` |
| `is_first_listed` | True if this member is the bill's primary (first-listed) lead author |
| `is_joint` | True if the bill has more than one lead author |
| `introduced` | Date of the first history action (December 2024 pre-files keep their real date) |
| `outcome` | `signed`, `vetoed` or `not_enacted` |
| `action_date` | Date the Governor signed or vetoed. Empty if not enacted |
| `lead_authors` | All lead authors, joined with `+`, first-listed first |
| `title` | Subject line of the latest bill version |
| `filed_year` | Year the bill counts toward: 2025 or 2026 (pre-files count as 2025) |
| `action_year` | Year of the Governor's action. Empty if not enacted |
| `source_url` | Official bill status page |
| `is_budget` | True for Budget Act bills, which are introduced under the budget chairs' names |

## data/processed/members_all.csv
`member`, `full_name`, `party` (D, R or Other), `district`, `chamber`, `ACTIVE_FLG`, `person` (key that follows one legislator across sessions), `session`, `partial_term`, `first_bill_date`, `last_bill_date`.

## data/processed/scorecard_{all_leads,first_listed}.csv
One row per member: `introduced`, `sent`, `signed`, `vetoed`, `rate`, `rank_signed`, `rank_rate`, `rank_r_signed`, `rank_r_rate` (ranks are within chamber), `chamber`, `partial_term`, `budget_bills`. Budget bills are excluded from every count and rank.

## data/reference/seat_changes.csv
Hand-sourced mid-session membership changes: `session`, `district`, `chamber`, `member`, `status`, `effective_note`, `predecessor`, `source_url`.

## data/reference/name_changes.csv
Legislators listed under more than one name since 2017, each checked by hand: `person`, `names_by_session`, `full_names`, `districts`, `checked_basis`.

## data/reference/person_aliases.csv
Person keys to join when a legislator's first or last name changed in the export: `alias_key`, `person_key`, `note`.

## data/reference/committee_lineage.csv
Renamed, merged, split and new committees: `house`, `code`, `name`, `current_name`, `relation` (renamed, merged, split, created), `note`. Only `renamed` rows change how committees are grouped.

## data/reference/veto_review.csv
Veto messages read in full and labeled by hand to check the keyword rules: `review_id`, `sample` (tuning or held_out), `session`, `BILL_ID`, `reviewed_reason`, `reviewed_detail`. No message text is stored; it is in the session's export.

## data/processed/headline.json
Headline numbers from the last refresh (by session: bills, signed, vetoed, signed %, members; model accuracy; veto check), written by `scripts/change_report.py` and compared week to week.

## Site data (site/data)
`scorecard_<year>.js` ranked tables per session; `people_index.js` and `people/<slug>.js` one file per legislator (record by session, bills, committee seats and votes); `committees_index.js`, `committees_<year>.js` and `committee_pairs.js` committee data; `model.js` the outlook model (coefficients for each step and the bootstrap draws for ranges); `bills_index.js` bill titles for the similar-bills search, loaded only when used.

## Committee files
Committee rosters, leadership and member votes are described in `docs/COMMITTEES.md`, with one table per file. `data/reference/committee_rosters_web.csv` holds the archived committee web rosters used to check them, one row per member listed, with the Internet Archive URL.
