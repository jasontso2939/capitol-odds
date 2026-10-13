# California Legislative Scorecard

A transparent, reproducible scorecard for every member of the California Legislature over ten years (2017-18 through 2025-26), rebuilt from the Legislature's official bulk data. One command downloads the data, parses it, applies documented counting rules and publishes a searchable dashboard.

**Dashboard:** three static pages, hosted on GitHub Pages.

- `site/index.html`: the scorecard for any of the five sessions (search, chamber and party filters, per-member bill lists).
- `site/trends.html`: statewide trends. Where bills die, Appropriations outcomes by party, policy committees with the highest risk, fiscal flags, coauthors, timing, spot bills, and veto reasons.
- `site/committees.html`: committee rosters by year, chairs and vice chairs with dates, and every member's committee votes, from the official roll calls. See `docs/COMMITTEES.md`.
- `site/outlook.html`: bill outlook. Estimates a proposed bill's chance of being signed from its author, first policy committee, fiscal features, coalition and timing, with similar past bills. Trained on all five sessions; accuracy is stated on the page (AUC 0.66 on a session it had not seen); see `docs/MODEL.md`.

## The idea

Most legislative rankings hide their counting decisions. Here each decision is a switch you can see:

- **Joint lead authors.** The official record credits every lead author. Bulk exports list only the first. Flip the toggle and watch rankings move.
- **Budget bills.** Budget Act bills are introduced under the budget chairs' names and would swamp their totals. They are excluded by default and can be included.
- **Time period.** Any of five sessions since 2017-18, whole session or one year at a time.
- **Partial terms.** Members who joined or left mid-session are flagged, with sources.

Every number comes from small tested functions, and every bill links to its official history.

## Ten years at a glance (regular session, Assembly and Senate bills with a legislator author)

| Session | Bills | Signed | Vetoed |
| --- | --- | --- | --- |
| 2017-18 | 4,479 | 1,702 | 318 |
| 2019-20 | 4,576 | 1,103 | 228 |
| 2021-22 | 4,188 | 1,571 | 234 |
| 2023-24 | 4,522 | 1,771 | 344 |
| 2025-26 | 3,956 | 1,664 | 243 |

2019-20 is the outlier: the 2020 pandemic cut the calendar short. About 8% of bills have more than one lead author, which is why the counting method matters.

## Quick start

```bash
make setup     # virtualenv + dependencies
make fetch     # download the 2025-26 session export (~1.2 GB, logged in data/raw/MANIFEST.md)
make extract   # unpack the tables the pipeline reads
make archive   # earlier sessions (2017-18 to 2023-24), ~34 MB from the session-archive branch
make build     # data/processed/*.csv
make site      # site/data/scorecard_<year>.js, one per session
make committees  # committee rosters, chairs and member votes from the roll calls
make insights  # site/insights.js and site/committees.js: trends, committees and the outlook model
make test
python3 -m http.server -d site   # open http://localhost:8000
```

A weekly GitHub Action (`refresh.yml`) rebuilds everything from fresh data.

## Layout

| Path | What it is |
| --- | --- |
| `src/calleg/pipeline.py` | Parses the official export into one row per bill and lead author |
| `src/calleg/model.py` | The counting rules: `scorecard()` with `method` and `scope` arguments |
| `src/calleg/build.py` | One command from raw export to processed tables |
| `src/calleg/features.py` | One row per bill: committees, fiscal flags, coalition, timing, spot bills |
| `src/calleg/trends.py` | Statewide trend tables, including veto-reason classification |
| `src/calleg/committees.py` | Committee rosters, chairs and member votes from roll calls |
| `src/calleg/predict.py` | Bill outlook model: training, evaluation, export for the browser |
| `data/reference/` | Hand-sourced facts the export lacks (mid-session seat changes) |
| `data/processed/` | Pipeline output (bills, members, scorecards) |
| `tests/` | Unit tests for the rules and data-quality checks on the full build |
| `site/` | Static dashboard, no build step, no dependencies |
| `docs/` | Methodology, data dictionary, and the model (`MODEL.md`) |

## Limits, stated plainly

- Counts measure output, not the quality or importance of a bill.
- Success rate favors members who file fewer bills, so counts sit beside it.
- Resolutions and extraordinary-session bills are not scored.
- The Legislature's export is the source of record. Spot-check any bill with its linked status page.

## Roadmap

1. Staged estimates: chance of clearing each committee vote, the floor and the Governor, where committee relationships should matter most (details in `docs/MODEL.md`).
2. Sessions before 2017 (the export goes back further) and cross-session voting records between members and authors.
4. An MCP server so an AI assistant can answer questions about the data with source links.

## License and disclaimer

Code: MIT. The underlying legislative records are public. Not affiliated with any office or legislator.
