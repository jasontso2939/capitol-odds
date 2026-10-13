# Bill outlook model

The Bill outlook page (`site/outlook.html`) estimates the chance a proposed bill is signed, using only what is known when it is introduced. The code is in `src/calleg/predict.py`; features are in `src/calleg/features.py`.

## What it predicts

Whether a regular Assembly or Senate bill by a legislator is signed by the Governor in the 2025-26 session. Budget bills and bills never referred to a policy committee are left out, so read the output as "chance of being signed once referred to this committee".

## Inputs (all known at introduction)

| Input | Source |
|---|---|
| Author's party and house | LEGISLATOR_TBL, first-listed lead author |
| First policy committee | First referral in BILL_HISTORY_TBL (TERNARY_LOCATION), excluding Rules and Appropriations |
| Introduction window | Early (Dec to Jan), Feb 1 to 14, Feb 15 to the deadline. Late rule-waiver bills are grouped with the last window |
| Fiscal flags | Introduced version in BILL_VERSION_TBL: APPROPRIATION, URGENCY, TAXLEVY, LOCAL_PROGRAM, VOTE_REQUIRED = "Two Thirds" |
| Coauthors | Count at introduction (log scale), any coauthor from the other party |
| Joint leads | More than one lead author; a joint lead from the other party |
| Spot bill | Introduced text under 3,000 characters containing "intent of the Legislature to enact" |
| Session | One term per session (2019-20 was far below the others). New bills are scored at the latest session's level |
| Author on the committee | Whether the lead author is a regular member of the first policy committee that year, and whether they chair it, from committee roll calls (`docs/COMMITTEES.md`) |
| Author's track record | Signed rate on the author's other bills in all five sessions, shrunk toward the party average with a weight of 8 bills. Leave-one-out in training so a bill never sees its own outcome |

## Method

Regularized logistic regression (scikit-learn, C = 0.5). Every coefficient is exported to `site/insights.js` and the browser computes the logit by hand; `tests/test_insights.py` checks that the hand computation matches scikit-learn.

## Accuracy (2017-18 through 2025-26: 19,675 bills, 39.3% signed)

| Check | Result |
|---|---|
| Train on 2017-18 to 2023-24, test on 2025-26 (a session it never saw) | AUC 0.661; predicted 40.8% signed on average, actual 44.5% |
| Five-fold cross-validated AUC, all sessions | 0.674 |
| Within 2025-26 only: train on 2025 bills, test on 2026 | AUC 0.657 (the earlier one-session model scored 0.653 to 0.657) |
| Brier score | 0.217 (base rate alone: 0.239) |
| Calibration | Within 2 points in every band (cross-validated) |

Earlier sessions tested the same way (train on all sessions before, test on the next): 2019-20 AUC 0.621, 2021-22 0.641, 2023-24 0.623, 2025-26 0.658. Ranking holds up across sessions; the overall level does not. Sessions differ: 2019-20 signed 24% of bills (the 2020 pandemic) against 37 to 42% in other sessions, so a model trained before it overestimated, and one anchored on it underestimated the next session. The model therefore includes a term for each session and scores new bills at the level of the latest session; the page says so.

AUC 0.66 means the model ranks a signed bill above an unsigned one about 66% of the time. That is useful for comparing scenarios and spotting risk factors. It is not a forecast for any single bill. Adding subject-line text (TF-IDF) did not help in the one-session version (cross-validated 0.661, temporal 0.652), so the model leaves it out. Weighting an author's recent sessions more than older ones changed AUC by less than 0.002, so all sessions count equally.

## Known limits

- Five sessions. Author records are thin for new members and anyone with few bills.
- The model sees no bill merits, opposition or support, the Governor's priorities, or amendments.
- Descriptive, not causal. A bill with a cross-party coauthor may do better because it was already a consensus bill.

## Committee relationships: what the roll calls added

Tested when the model covered 2025-26 only, with cross-validation and a 2025-to-2026 split:

| Feature | CV AUC | 2025 to 2026 AUC |
|---|---|---|
| Model without committee features | 0.651 | 0.657 |
| + author sits on the committee | 0.652 | 0.656 |
| + author chairs the committee | 0.653 | 0.658 |
| + other authors who sit on the committee | 0.650 | 0.658 |
| + committee's party balance, chair's party | 0.650 to 0.651 | 0.657 |
| + members' past yes rate on the author's bills (votes before introduction only) | 0.650 | 0.654 |

The model keeps the two author-committee flags (together: CV 0.653, temporal 0.657). The others are left out: they added nothing, and the coauthor count on the committee took a negative sign once total coauthors were in, which would mislead. Members' voting history on an author is shown on the outlook page as context, not used in the estimate, because committee roll calls mostly record bills already headed for passage (yes rates near 95%) and bills held without a vote leave no roll call.

The committee itself (already a model input) and the author's party carry most of what roster relationships could add within one session.

## Roadmap

1. **Staged models.** Predict each gate separately (policy committee vote, Appropriations, floor, second house, Governor). Roll calls give a clean target for each committee vote, where relationship features should matter more than for final signature.
2. **Bill content.** Topic features from the introduced text and the Legislative Counsel's digest, matched to each committee member's record on similar bills.
3. **Support and opposition.** Registered positions from committee analyses (BILL_ANALYSIS_TBL holds the analysis documents).
