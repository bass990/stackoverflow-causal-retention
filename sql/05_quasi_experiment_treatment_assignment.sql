-- ──────────────────────────────────────────────────────────────────────────────
-- 05_quasi_experiment_treatment_assignment.sql
--
-- INSTRUMENT-STRENGTH LOOKUP FOR THE RETENTION QUASI-EXPERIMENT.
--
-- THE ANALYTICAL PROBLEM:
--   We want to estimate the CAUSAL effect of "got_answer_within_24h" on D30 /
--   D180 retention. But that treatment is endogenous: high-quality questions
--   are MORE likely to get fast answers AND those users would have retained
--   anyway. A naive treatment-vs-control comparison conflates the answer's
--   effect with the question-writer's underlying quality.
--
-- THE INSTRUMENT:
--   Hour-of-day-of-posting. The mechanism:
--     - Approximately exogenous to question quality: users post when they have
--       a problem; they don't strategically pick posting hours to maximize
--       answer probability.
--     - Strong on treatment: respondent online-presence varies sharply by
--       hour (Europe-afternoon / US-morning overlap at ~14 UTC is the peak).
--     - Exclusion restriction: hour-of-day only affects retention THROUGH its
--       effect on answer probability. (Defensible but not airtight — see
--       caveat below.)
--
--   The strategy: compute the GLOBAL answer-within-24h rate per posting hour
--   across all in-window questions (not just our cohort) to maximize the
--   precision of the hour-level baseline. Downstream, the notebook joins this
--   24-row lookup to features.parquet on hour_of_day_utc — giving each cohort
--   user an "expected answer probability" based purely on their posting hour.
--   That expected probability is the instrument for 2SLS.
--
-- EXCLUSION-RESTRICTION CAVEAT:
--   The cleanest threat to the IV: hour-of-day might also affect retention
--   directly through engagement habits (e.g., "users who post at 03 UTC are
--   night-owl hobbyists with different retention patterns from 14-UTC posters
--   regardless of whether they get answered"). The downstream analysis should
--   report both naive OLS and IV estimates and discuss whether the gap is
--   plausibly explained by selection vs. instrument validity.
--
-- WHY THE FULL QUESTION POPULATION (not just first-questions):
--   The instrument-strength estimate needs precision. The full question
--   population is 25× larger than our first-question cohort, which sharpens
--   the hour-level treatment-rate estimates roughly 5×. The instrument
--   strength we estimate here is then applied to our cohort downstream.
--
-- COST CONSIDERATION:
--   Same column-scan footprint as sql-03's first_answer_to_q CTE: id +
--   creation_date from posts_questions, parent_id + creation_date from
--   posts_answers. Expected ~1.5-2 GB. Run `make estimate-sql-05` to confirm.
-- ──────────────────────────────────────────────────────────────────────────────

DECLARE study_start_date DATE DEFAULT DATE '2018-01-01';
DECLARE study_end_date   DATE DEFAULT DATE '2023-12-31';

WITH question_population AS (
  -- ALL in-window questions, not just first-questions. We use the full
  -- population so the hour-level baseline-answer-rate estimates have maximum
  -- statistical power (each hour cell has ~1M+ questions vs ~75K in the
  -- cohort-only sample).
  SELECT
    id                                 AS question_id,
    creation_date                      AS question_ts,
    EXTRACT(HOUR FROM creation_date)   AS hour_of_day_utc
  FROM `bigquery-public-data.stackoverflow.posts_questions`
  WHERE DATE(creation_date) BETWEEN study_start_date AND study_end_date
),

first_answer_per_question AS (
  -- Earliest answer per in-window question. INNER JOIN to question_population
  -- so we only pull answers to questions we care about (same hash-join pattern
  -- as sql-03's first_answer_to_q CTE).
  SELECT
    a.parent_id          AS question_id,
    MIN(a.creation_date) AS first_answer_ts
  FROM `bigquery-public-data.stackoverflow.posts_answers` a
  INNER JOIN question_population q
    ON q.question_id = a.parent_id
  GROUP BY a.parent_id
),

question_outcomes AS (
  -- LEFT JOIN so questions that never got an answer keep first_answer_ts = NULL
  -- (they contribute 0 to the treatment-rate numerator, 1 to the denominator).
  SELECT
    q.question_id,
    q.hour_of_day_utc,
    fa.first_answer_ts,
    CAST(
      fa.first_answer_ts IS NOT NULL
      AND TIMESTAMP_DIFF(fa.first_answer_ts, q.question_ts, HOUR) <= 24
      AS INT64
    ) AS got_answer_within_24h
  FROM question_population q
  LEFT JOIN first_answer_per_question fa
    ON fa.question_id = q.question_id
)

SELECT
  hour_of_day_utc,
  COUNT(*)                                                AS n_questions,
  SUM(got_answer_within_24h)                              AS n_answered_24h,
  ROUND(AVG(got_answer_within_24h), 4)                    AS treatment_rate_24h,

  -- Standard error of the proportion estimate. With ~1M+ obs per hour cell
  -- this will be tiny (< 0.001 for most hours), confirming the instrument is
  -- precisely measured. SQRT(p(1-p)/n) is the binomial SE.
  ROUND(
    SQRT(AVG(got_answer_within_24h) * (1 - AVG(got_answer_within_24h))
         / COUNT(*)),
    5
  )                                                       AS treatment_rate_se

FROM question_outcomes
GROUP BY hour_of_day_utc
ORDER BY hour_of_day_utc;
