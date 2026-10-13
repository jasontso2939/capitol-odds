# Bill outlook model

The Bill outlook page (`site/outlook.html`) estimates the chance a proposed bill clears each step to the Governor's signature, using only what is known when it is introduced, and shows a likely range. The code is in `src/calleg/stages.py` (steps and ranges) and `src/calleg/predict.py` (inputs and the one-step model); features are in `src/calleg/features.py`.

## What it predicts

Whether a regular Assembly or Senate bill by a legislator is signed, as the product of five steps, each estimated for bills that reached it:

| Step | Cleared when | Bills reaching it | Cleared |
|---|---|---|---|
| Policy committee | A passing "do pass" or "be adopted" roll call in the first policy committee, or any later progress | 19,675 | 77% |
| Appropriations | Not sent to the first house's Appropriations committee, or sent and passed (roll call or passing the house) | 15,219 | 83% |
| Floor of the first house | Passed the house of origin | 12,630 | 97% |
| Second house | Reached the Governor (committees, floor and any concurrence vote) | 12,301 | 74% |
| Governor | Signed | 9,094 | 85% |

The steps multiply out to exactly the signed bills (7,730), which `tests/test_insights.py` checks. Whether a bill is sent to Appropriations cannot be read from its fiscal flag at introduction (about 4 in 10 bills not marked fiscal were sent anyway), so that step covers all bills that cleared policy committee. Budget bills and bills never referred to a policy committee are left out, so read the output as "chance of being signed once referred to this committee".

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
| Session | One term per session (2019-20 was far below the others). New bills are scored at the level of the latest finished session |
| Author on the committee | Whether the lead author is a regular member of the first policy committee that year, and whether they chair it, from committee roll calls (`docs/COMMITTEES.md`) |
| Author's track record | Signed rate on the author's other bills in all five sessions, shrunk toward the party average with a weight of 8 bills. Leave-one-out in training so a bill never sees its own outcome |

## Method

One regularized logistic regression per step (scikit-learn, C = 0.5), each fit only on bills that reached the step. Every coefficient is exported to `site/data/model.js` and the browser computes each step by hand. A single model fit to the final outcome is kept as a cross-check; `tests/test_insights.py` checks that the hand computation matches scikit-learn.

**Training only on finished sessions.** A session's outcomes are final on October 1 of its second year. Before that, bills still moving would count as failures, so the model learns from finished sessions only and scores bills at the level of the latest one. When a new session starts, its roster is used for the author list and its committees once it has enough referred bills.

**The likely range.** 40 refits on bills resampled with replacement (Poisson weights). Each refit is scored at the level of one past session, cycling through the finished sessions other than 2019-20 (left out as atypical: the pandemic). The page shows the 10th to 90th percentile. It covers two things the single number hides: how much the fit depends on which past bills happened to be in the data, and how much a typical session differs from another. For 2025-26 bills the range is usually 6 to 11 points wide (median 8). It does not cover what the model cannot see (the bill's merits, opposition, amendments), which is why accuracy below is modest.

## Accuracy (2017-18 through 2025-26: 19,675 bills, 39.3% signed)

| Check | Staged model (on the page) | One-step model |
|---|---|---|
| Train on 2017-18 to 2023-24, test on 2025-26 (a session it never saw) | AUC 0.659; predicted 40.7% signed, actual 44.5% | AUC 0.662; predicted 40.7%, actual 44.5% |
| Five-fold cross-validated AUC, all sessions | 0.673 | 0.674 |
| Calibration (cross-validated) | Within 2 points in every band with 500+ bills | Within 2 points |
| Brier score | | 0.217 (base rate alone: 0.239) |

The two rank bills equally well; the staged model is shown because its steps say where a bill's risk sits. Accuracy by step on 2025-26 (trained on earlier sessions): policy committee AUC 0.78, Appropriations 0.64, floor 0.59, second house 0.54, Governor 0.62. Whether a bill gets out of its first committee is fairly predictable from who carries it and where it goes; what happens in the second house is close to a coin flip on this information.

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

1. **Bill content.** Topic features from the introduced text and the Legislative Counsel's digest, matched to each committee member's record on similar bills.
2. **Support and opposition.** Registered positions from committee analyses (BILL_ANALYSIS_TBL holds the analysis documents).
