# Bill outlook model

The Capitol Odds home page (`site/index.html`; the old `outlook.html` address redirects there) estimates the chance a proposed bill clears each step to the Governor's signature, using only what is known when it is introduced, and shows a likely range. The code is in `src/calleg/stages.py` (steps and ranges) and `src/calleg/predict.py` (inputs and the one-step model); features are in `src/calleg/features.py`.

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
| Author's track record | Signed rate on the author's bills in every finished session, shrunk toward the party average with a weight of 8 bills. In training, the bill's whole session is left out of its author's record (see below) |
| Subject line | Words in the introduced bill's subject line (TF-IDF unigrams and bigrams, 1,500 terms) |
| Fiscal committee | Whether the introduced bill is keyed to a fiscal committee |
| Double referral | Whether the first referral names two policy committees (known within days of introduction) |

## Method

One regularized logistic regression per step (scikit-learn, C = 0.5), each fit only on bills that reached the step. Every coefficient is exported to `site/data/model.js` and the browser computes each step by hand. A single model fit to the final outcome is kept as a cross-check; `tests/test_insights.py` checks that the hand computation matches scikit-learn.

**Training only on finished sessions.** A session's outcomes are final on October 1 of its second year. Before that, bills still moving would count as failures, so the model learns from finished sessions only and scores bills at the level of the latest one. When a new session starts, its roster is used for the author list and its committees once it has enough referred bills.

**The likely range.** 40 refits on bills resampled with replacement (Poisson weights). Each refit is scored at the level of one past session, cycling through the finished sessions other than 2019-20 (left out as atypical: the pandemic). The page shows the 10th to 90th percentile. It covers two things the single number hides: how much the fit depends on which past bills happened to be in the data, and how much a typical session differs from another. For 2025-26 bills the range is usually 6 to 11 points wide (median 8). It does not cover what the model cannot see (the bill's merits, opposition, amendments), which is why accuracy below is modest.

## Accuracy (2007-08 through 2025-26: 38,333 bills, 38.7% signed)

| Check | Staged model (on the page) | One-step model |
|---|---|---|
| Train on 2007-08 to 2023-24, test on 2025-26 (a session it never saw) | AUC 0.679; predicted 40.7% signed, actual 44.5% | AUC 0.681 |
| Five-fold cross-validated AUC, all sessions | 0.675 | 0.676 |
| Calibration (cross-validated) | Within 3 points in every band with 500+ bills | |

Before October 2026 (2017-18 to 2025-26 only, no subject line, fiscal-committee flag, double referral or recency weights) the staged model scored 0.659 on 2025-26.

The two rank bills equally well; the staged model is shown because its steps say where a bill's risk sits. Accuracy by step on 2025-26 (trained on earlier sessions): policy committee AUC 0.79, Appropriations 0.67, floor 0.72, second house 0.56, Governor 0.65. Whether a bill gets out of its first committee is fairly predictable from who carries it and where it goes; what happens in the second house is close to a coin flip on this information.

Earlier sessions tested the same way (train on all sessions before, test on the next): 2019-20 AUC 0.621, 2021-22 0.641, 2023-24 0.623, 2025-26 0.658. Ranking holds up across sessions; the overall level does not. Sessions differ: 2019-20 signed 24% of bills (the 2020 pandemic) against 37 to 42% in other sessions, so a model trained before it overestimated, and one anchored on it underestimated the next session. The model therefore includes a term for each session and scores new bills at the level of the latest session; the page says so.

AUC 0.66 means the model ranks a signed bill above an unsigned one about 66% of the time. That is useful for comparing scenarios and spotting risk factors. It is not a forecast for any single bill. Two inputs were added in October 2026 once five sessions of training data were available: the words in the introduced bill's subject line (TF-IDF unigrams and bigrams, 1,500 terms, computed the same way in the browser) and whether the introduced bill is keyed to a fiscal committee. Together they raised the staged model's AUC on 2025-26 (trained on earlier sessions) from 0.659 to 0.675 and its cross-validated AUC from 0.673 to 0.687. The gain came mostly at Appropriations (0.636 to 0.667) and the Governor (0.620 to 0.653). The final version's title was tested too and helped more, but it is left out because it reflects amendments made after introduction. Bill length, the author's bill count, committee party balance and a party-by-committee interaction added nothing; gradient-boosted trees did worse than the logistic models on later sessions. Weighting an author's recent sessions more than older ones changed AUC by less than 0.002, so all sessions count equally.

## Time and political climate (October 2026, ten sessions)

With 2007-08 through 2025-26 in the data, the model spans three Governors, a Republican Governor with a Democratic Legislature, the Democratic supermajority from 2013, the 2020 pandemic, and redistricting. Every check below trains on sessions before a test session and scores that session, the way the site is used. "Mean" is the average over the six test sessions 2015-16 to 2025-26.

| Change (logistic model, drafting inputs) | Mean AUC | 2025-26 |
|---|---|---|
| All sessions weighted equally | 0.660 | 0.678 |
| + Governor's party, Republican bill under a Republican Governor, last-term Governor, Democratic seat share | 0.662 | 0.679 |
| Recent sessions count more (weight 0.74 per session back) | 0.665 | 0.682 |
| Train on 2011-12 onward only (equal weights) | 0.660 | 0.678 |
| Recency + author's record in the prior session, tenure, chairs any committee, record in the same committee | 0.665 | 0.681 |
| Recency + committee's pass rate for the author's party in the prior session | 0.665 | 0.682 |
| Recency + subject similar to a bill in the prior session, and that bill's fate | 0.665 | 0.682 |
| All of the above + coauthor mix by party, a committee chair as coauthor, principal coauthors | 0.667 | 0.684 |
| All of the above + double referral and days from introduction to referral | 0.671 | 0.686 |
| Gradient-boosted trees on the same inputs (author record fixed as below) | 0.647 | 0.664 |

Political climate moves how many bills pass in a session far more than which bills pass: within any one session, the climate is the same for every bill, so it barely changes ranking. The model handles it two ways. A term for each session absorbs the level, and new bills are scored at the latest session's level. Recency weights (`predict.RECENCY`) let recent sessions count more, so the model follows how the Legislature works now. The site keeps recency weights and double referral; the other inputs above added less than 0.003 each and are left out to keep the model readable.

**A leak found and fixed.** The author's record used to be computed leave-one-out (every bill by the author except this one). That leaks the bill's own outcome: an author's signed bill sees a slightly lower record than the same author's failed bill. A logistic model mostly shrugs this off, but gradient-boosted trees learned it backwards (AUC 0.58). The record now leaves out the bill's whole session in training, which matches how a new session is scored.

**Older sessions in the data.** The 2007-10 histories word first-house passage differently ("Read third time, passed, and to Senate."), so `features.py` also counts a bill's arrival in the second house. The 2007-08 roll calls have no member order, so committee chairs are unknown for those two years.

**At introduction, about 0.68 is the ceiling with this data.** Every combination tested stayed between 0.67 and 0.69 on 2025-26. What the model cannot see at introduction (what the bill does, who supports and opposes it) is what decides most bills.

## Tracking a filed bill (`src/calleg/tracking.py`)

Once a bill is in print its history says a lot: whether the author set it for a hearing or canceled one, amended it, got it out of committee, or saw it sent to the suspense file. For each checkpoint (30, 60, 90, 120, 180, 270 and 365 days after introduction), a separate logistic model adds counts of those actions up to that day to the drafting inputs. Only actions dated on or before the checkpoint are used. Trained on 2007-08 to 2023-24 and tested on 2025-26:

| Days after introduction | 0 | 30 | 60 | 90 | 120 | 180 | 270 | 365 |
|---|---|---|---|---|---|---|---|---|
| AUC | 0.68 | 0.68 | 0.70 | 0.80 | 0.85 | 0.88 | 0.94 | 0.94 |

The same pattern holds when testing on each session from 2013-14 on (day 90: 0.79 to 0.83). The jump between day 60 and day 90 is the first round of policy committee hearings. On the site, the "Track a filed bill" view shows each bill's odds at every checkpoint. For a finished session the odds come from models trained only on earlier sessions, so they show what the model would have said at the time.

## Known limits

- Author records are thin for new members and anyone with few bills.
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
