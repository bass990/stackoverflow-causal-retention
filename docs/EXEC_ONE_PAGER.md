# Does getting an answer keep a new Stack Overflow contributor on the platform?

**A causal-inference study on 1.77M new contributors, Jan 2018 to Sept 2022.**

## What we did

Built a five-step BigQuery pipeline (44 GB scan, $0.22 in cost) plus five analytic notebooks to estimate the causal effect of receiving an answer to your first question on whether you're still active 30 days and 180 days later. Four estimators applied in parallel: controlled OLS, IPW, propensity-score stratification, 2SLS with a posting-hour instrument.

## What we found

**Getting an answer within 24 hours of your first question is associated with +7.7 percentage points higher D30 retention, controlling for observable question quality.** The estimate is robust to method choice (OLS, IPW, PSM all within 0.06 pp of each other), specification (year FE, month FE, no time FE, all within 0.4 pp), and treatment definition (the same shrinkage logic across 1h / 24h / any answer). The effect shrinks to +1.5 pp at 180 days.

**The effect roughly doubled between 2018 and 2022.** Controlled estimate by cohort year: 2018 +5.96 pp, 2019 +6.65, 2020 +7.06, 2021 +7.99, 2022 +11.03. Consistent with alternative help sources (Copilot, ChatGPT) raising the value of an SO answer at the margin.

**The effect is highly heterogeneous by language.** R users +10.0 pp, Android +9.9, JavaScript +9.0, Python +8.4, Java +6.2, C# +5.2, C++ +3.7. A uniform product policy leaves value on the table for the high-effect communities.

## The honest caveat

The 2SLS estimate, which would have given a clean causal effect under the right assumptions, is strongly negative (-20.4 pp on D30). First-stage F is above 1000 so the instrument is not weak. The failure points to a violation of the exclusion restriction: posting hour correlates with unobserved user characteristics (timezone, hobbyist vs professional, urgency) that directly affect retention.

The implication is that I cannot fully rule out unobserved confounders biasing the +7.7 pp estimate. It's the best controlled association from the data, not a clean causal effect. A real product team should treat it as a strong lower bound on the actual product opportunity, since plausible unobservables would inflate not deflate the regression estimate.

## What this would mean if the regression estimate is right

If +7.7 pp at D30 is the true causal effect, the annual gain is roughly **29,000 additional D30-active new contributors per year** (1.77M cohort over 4.75 years = 373K per year, times the 0.077 lift). The 180-day version is about **5,600 additional D180-active new contributors per year** (373K times 0.015).

The roughly 5x decay from D30 to D180 (7.7 pp shrinking to 1.5 pp) suggests answering is necessary but not sufficient for long-term retention. Fast-track answering is a one-month bridge, not a six-month loyalty program. Sustained engagement requires a follow-up mechanism.

## Recommended product test

A real on-platform experiment would close every loophole the observational analysis can't. Randomize new questions at the posting-hour cell into two arms: control receives standard organic answering; treatment receives a "fast-track" pool of high-reputation answerers nudged within 4 hours. Measure D30 and D180 retention, plus secondary outcomes (second-question rate, accepted-answer rate, reputation gained).

Minimum detectable effect would land around 1-2 pp at D30 with the cohort sizes Stack Overflow sees. The experiment would identify the ATE cleanly without IV assumptions.

## What's in scope and what isn't

Scope: causal estimate of an observed treatment (got fast answer) on D30 / D180 retention, with the appropriate hedges given the failed IV. Out of scope: predicting which users will retain (notebook 05's ladder of four model variants tops out at AUC 0.6406, modest, mostly an exercise to show the structural ceiling), recommending content moderation policy, evaluating Stack Overflow's strategic positioning against AI alternatives.

## Tech stack and reproducibility

Python 3.12. BigQuery SQL plus statsmodels / linearmodels / scikit-learn / SHAP. Full code at github.com/bass990/stackoverflow-retention-causal. Streamlit dashboard launches with `make dashboard`. Total compute cost on free tier: $0.22 of BigQuery scan.

**Author:** Mamadou Bassirou Diallo, M.S. Business Analytics + AI, UT Dallas (May 2027). LinkedIn: linkedin.com/in/mamadou9905.
