-- ──────────────────────────────────────────────────────────────────────────────
-- 02_retention_30d_180d.sql
--
-- COMPUTE D30 AND D180 RETENTION FLAGS PER COHORT USER.
--
-- For each new contributor in the 2018-2023 cohort window, compute two binary
-- retention outcomes plus their underlying post counts:
--
--   active_d30   = 1 if user posted ≥1 question or answer in days 1-30 after
--                  their first post (excluding the first post itself)
--   active_d180  = 1 if user posted ≥1 question or answer in days 180-210 after
--                  their first post (the 30-day window AFTER day 180, per
--                  the scope spec's retention definition)
--
-- WHY EXCLUDE THE FIRST POST FROM D30:
--   Every user has at least 1 post on day 0 by definition. "active_d30 = 1
--   counting day 0" would always be True. The interesting question is whether
--   they CAME BACK after their first post — hence days 1-30 exclusive of day 0.
--
-- WHY DAYS 180-210 (not "≥1 post any time after day 180"):
--   The 30-day-window-after-day-180 framing per the scope spec turns the
--   outcome into a clean binary that's interpretable as "still active around
--   the 6-month anniversary." A cumulative "ever posted after day 180" would
--   conflate users who posted once at day 200 with users who post weekly.
--
-- OBSERVATION-WINDOW CAVEAT:
--   Late-cohort users (first_post_date > snapshot_date - 210 days) will have
--   active_d180 = FALSE because the data simply doesn't extend far enough to
--   observe their day-180-210 window. We mark these users with
--   d180_observable = FALSE; downstream analysis MUST filter to
--   d180_observable = TRUE before computing retention rates. The snapshot
--   date is derived inside the query from the max post_date in the data.
--
-- COST CONSIDERATION:
--   Same columns as sql-01 minus the tags string — scan should be roughly
--   1.0 GB (smaller than sql-01's 1.54 GB). Run `make estimate-sql-02` to
--   confirm before running for real.
-- ──────────────────────────────────────────────────────────────────────────────

DECLARE study_start_date DATE DEFAULT DATE '2018-01-01';
DECLARE study_end_date   DATE DEFAULT DATE '2023-12-31';

WITH all_posts AS (
  -- Union question + answer post-date events per user. Same shape as sql-01
  -- but without the `tags` column (not needed for retention; saves scan cost).
  SELECT
    owner_user_id        AS user_id,
    DATE(creation_date)  AS post_date
  FROM `bigquery-public-data.stackoverflow.posts_questions`
  WHERE owner_user_id IS NOT NULL

  UNION ALL

  SELECT
    owner_user_id        AS user_id,
    DATE(creation_date)  AS post_date
  FROM `bigquery-public-data.stackoverflow.posts_answers`
  WHERE owner_user_id IS NOT NULL
),

snapshot AS (
  -- Use the max post_date in the data as the observation snapshot.
  -- A user's active_d180 is only OBSERVABLE if first_post_date + 210 days
  -- is ≤ this snapshot date. Users with later first posts have a censored
  -- observation window — we mark them with d180_observable = FALSE.
  SELECT MAX(post_date) AS snapshot_date FROM all_posts
),

first_post_per_user AS (
  -- Rank ALL posts per user (no in-window filter here — see sql-01 comment
  -- about why we need global ranking to correctly identify new contributors).
  SELECT
    user_id,
    post_date AS first_post_date,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY post_date ASC) AS rn
  FROM all_posts
),

cohort AS (
  -- Same cohort definition as sql-01: users whose FIRST post falls in
  -- the study window. Output one row per user.
  SELECT
    user_id,
    first_post_date,
    DATE_TRUNC(first_post_date, MONTH) AS cohort_month
  FROM first_post_per_user
  WHERE rn = 1
    AND first_post_date BETWEEN study_start_date AND study_end_date
)

SELECT
  c.user_id,
  c.cohort_month,
  c.first_post_date,

  -- D30 window: days 1-30 after first post (excluding day 0).
  -- `> 0` returns a BOOL; cast to INT64 for parquet/pandas convenience.
  CAST(
    COUNTIF(
      p.post_date BETWEEN DATE_ADD(c.first_post_date, INTERVAL 1 DAY)
                      AND DATE_ADD(c.first_post_date, INTERVAL 30 DAY)
    ) > 0 AS INT64
  ) AS active_d30,

  -- D180 outcome: posted ≥1 time in days 180-210 after first post.
  CAST(
    COUNTIF(
      p.post_date BETWEEN DATE_ADD(c.first_post_date, INTERVAL 180 DAY)
                      AND DATE_ADD(c.first_post_date, INTERVAL 210 DAY)
    ) > 0 AS INT64
  ) AS active_d180,

  -- Whether the D180 window is fully observable in the data. Downstream
  -- analysis MUST filter to this flag before computing retention rates.
  CAST(
    DATE_ADD(c.first_post_date, INTERVAL 210 DAY) <= s.snapshot_date AS INT64
  ) AS d180_observable,

  -- Underlying counts — useful as features in later models, and as
  -- sanity-check signals during analysis.
  COUNTIF(
    p.post_date BETWEEN DATE_ADD(c.first_post_date, INTERVAL 1 DAY)
                    AND DATE_ADD(c.first_post_date, INTERVAL 30 DAY)
  ) AS post_count_d1_d30,

  COUNTIF(
    p.post_date BETWEEN DATE_ADD(c.first_post_date, INTERVAL 180 DAY)
                    AND DATE_ADD(c.first_post_date, INTERVAL 210 DAY)
  ) AS post_count_d180_d210,

  s.snapshot_date AS data_snapshot_date

FROM cohort c
LEFT JOIN all_posts p
  ON p.user_id = c.user_id
CROSS JOIN snapshot s
GROUP BY c.user_id, c.cohort_month, c.first_post_date, s.snapshot_date
ORDER BY c.cohort_month, c.first_post_date;
