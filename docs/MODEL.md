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
| Author's track record | Signed rate on the author's other bills, shrunk toward the party average with a weight of 8 bills. Leave-one-out in training so a bill never sees its own outcome |

## Method

Regularized logistic regression (scikit-learn, C = 0.5). Every coefficient is exported to `site/insights.js` and the browser computes the logit by hand; `tests/test_insights.py` checks that the hand computation matches scikit-learn.

## Accuracy (2025-26, 3,697 bills, 44.5% signed)

| Check | Result |
|---|---|
| Five-fold cross-validated AUC | 0.651 |
| Train on bills introduced in 2025, test on 2026 | AUC 0.657 |
| Brier score | 0.229 (base rate alone: 0.247) |
| Calibration | Close in the middle; slightly overconfident above 50% (predicted 75%, actual 69% in the top band) |

AUC 0.65 means the model ranks a signed bill above an unsigned one about 65% of the time. That is useful for comparing scenarios and spotting risk factors. It is not a forecast for any single bill. Adding subject-line text (TF-IDF) did not help (cross-validated 0.661, temporal 0.652), so the model leaves it out.

## Known limits

- One session. Author records are thin for new members and anyone with few bills.
- The model sees no bill merits, opposition or support, the Governor's priorities, or amendments.
- Descriptive, not causal. A bill with a cross-party coauthor may do better because it was already a consensus bill.

## Roadmap: author, committee and member relationships

The goal is to model the relationship between a bill's subject, its author and the members of the committees it must pass. Next steps, in order:

1. **Committee votes.** Extract BILL_DETAIL_VOTE_TBL and BILL_SUMMARY_VOTE_TBL from the same export. These record how each member voted in each committee and floor vote, which supports features such as: author sits on the referral committee, coauthors on the committee, share of committee members who coauthored, and each member's past yes rate on bills by this author or party.
2. **Committee rosters and chairs.** Members and chairs by committee for each session, from the Assembly and Senate committee pages or the export's location codes.
3. **Earlier sessions.** 2021-22 and 2023-24 exports for longer author histories and a true out-of-session test.
4. **Bill content.** Topic features from the introduced text (not just the subject line) and the Legislative Counsel's digest.
5. **Staged models.** Separate estimates for each gate (policy committee, Appropriations, floor, second house, Governor), so the page can say where a bill is most likely to stop.
