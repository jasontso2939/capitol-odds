# Data dictionary

## data/processed/bills_all.csv
One row per bill and lead author (regular-session AB and SB).

| Column | Meaning |
| --- | --- |
| `bill_id` | Bill number without a space, for example `AB460` |
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
`member`, `full_name`, `party` (D, R or Other), `district`, `chamber`, `ACTIVE_FLG`, `partial_term`, `first_bill_date`, `last_bill_date`.

## data/processed/scorecard_{all_leads,first_listed}.csv
One row per member: `introduced`, `sent`, `signed`, `vetoed`, `rate`, `rank_signed`, `rank_rate`, `rank_r_signed`, `rank_r_rate` (ranks are within chamber), `chamber`, `partial_term`, `budget_bills`. Budget bills are excluded from every count and rank.

## data/reference/seat_changes.csv
Hand-sourced mid-session membership changes: `district`, `chamber`, `member`, `status`, `effective_note`, `predecessor`, `source_url`.
