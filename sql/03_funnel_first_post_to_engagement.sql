-- ──────────────────────────────────────────────────────────────────────────────
-- 03_funnel_first_post_to_engagement.sql
--
-- FUNNEL FROM FIRST POST → COMMUNITY ENGAGEMENT.
--
-- For the QUESTION-FIRST sub-cohort (users whose first post was a question),
-- measure how the community responded:
--
--   got_answer_within_1h    = 1 if any answer was posted ≤ 1 hour  after first Q
--   got_answer_within_24h   = 1 if any answer was posted ≤ 24 hours after first Q
--   got_any_answer          = 1 if any answer was EVER posted before snapshot
--
-- Plus continuous metric:
--   hours_to_first_answer   = TIMESTAMP_DIFF in hours; NULL if no answer
--
-- WHY QUESTION-FIRST ONLY:
--   An answer-first user is BY DEFINITION engaging with someone else's question
--   — they don't have a "received first answer" funnel of their own. The
--   answer-first sub-cohort (≈27% of cohort) gets a different engagement signal
--   in sql-04: the score on their first answer.
--
-- WHY THE "UPVOTE" STAGE FROM THE SCOPE SPEC WAS DROPPED:
--   The `votes` table is ~200M rows. Scanning it filtered to our cohort's
--   ~1.7M question_ids would cost ~15-30 GB — 10× the cost of the answer
--   funnel for marginal extra insight. The time-bucketed answer funnel
--   (1h / 24h / ever) captures "did the community engage?" at 1/10 the
--   scan cost. We can revisit the upvote stage later if budget allows
--   and the analysis would meaningfully change with it.
--
-- WHY SUB-QUERY → INNER JOIN (NOT IN-clause):
--   `WHERE parent_id IN (SELECT first_question_id FROM cohort_q)` would push a
--   1.7M-element subquery into the planner. INNER JOIN on parent_id is the
--   idiomatic BigQuery pattern — the planner builds a hash set from cohort_q
--   and filters posts_answers in one pass.
--
-- COST CONSIDERATION:
--   Scans owner_user_id + creation_date + id from posts_questions (~3 columns)
--   and parent_id + creation_date + owner_user_id + id from posts_answers
--   (~4 columns). Expected ~3-5 GB. Run `make estimate-sql-03` to confirm.
-- ──────────────────────────────────────────────────────────────────────────────

DECLARE study_start_date DATE DEFAULT DATE '2018-01-01';
DECLARE study_end_date   DATE DEFAULT DATE '2023-12-31';

WITH all_posts AS (
  -- Union question + answer events per user. We need:
  --   id        — to know WHICH post is the user's first (for joining answers later)
  --   post_ts   — full timestamp for sub-day granularity on "time to first answer"
  --   post_date — DATE for cohort bucketing
  --   post_type — to filter to question-first users only
  SELECT
    id                   AS post_id,
    owner_user_id        AS user_id,
    creation_date        AS post_ts,
    DATE(creation_date)  AS post_date,
    'question'           AS post_type
  FROM `bigquery-public-data.stackoverflow.posts_questions`
  WHERE owner_user_id IS NOT NULL

  UNION ALL

  SELECT
    id                   AS post_id,
    owner_user_id        AS user_id,
    creation_date        AS post_ts,
    DATE(creation_date)  AS post_date,
    'answer'             AS post_type
  FROM `bigquery-public-data.stackoverflow.posts_answers`
  WHERE owner_user_id IS NOT NULL
),

first_post_per_user AS (
  -- Global ranking (see sql-01 comment for why GLOBAL not in-window).
  SELECT
    post_id,
    user_id,
    post_ts,
    post_date,
    post_type,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY post_ts ASC) AS rn
  FROM all_posts
),

cohort_q AS (
  -- Question-first cohort. Carry forward the question's post_id so we can
  -- join answers to it. Restrict to users whose first post is a question
  -- AND falls in the study window.
  SELECT
    post_id AS first_question_id,
    user_id,
    post_ts  AS first_question_ts,
    post_date AS first_post_date,
    DATE_TRUNC(post_date, MONTH) AS cohort_month
  FROM first_post_per_user
  WHERE rn = 1
    AND post_type = 'question'
    AND post_date BETWEEN study_start_date AND study_end_date
),

first_answer_to_q AS (
  -- For each cohort user's first question, find the earliest answer to it.
  -- INNER JOIN (not IN-clause) so the BigQuery planner uses a hash join
  -- rather than materializing a 1.7M-element subquery.
  SELECT
    a.parent_id          AS question_id,
    MIN(a.creation_date) AS first_answer_ts
  FROM `bigquery-public-data.stackoverflow.posts_answers` a
  INNER JOIN cohort_q c
    ON c.first_question_id = a.parent_id
  GROUP BY a.parent_id
)

SELECT
  c.user_id,
  c.cohort_month,
  c.first_post_date,
  c.first_question_id,

  -- Time-to-first-answer in hours. NULL if the question never got an answer.
  -- TIMESTAMP_DIFF with HOUR granularity is sub-day precision but small enough
  -- to fit in INT64 even for multi-year gaps.
  TIMESTAMP_DIFF(fa.first_answer_ts, c.first_question_ts, HOUR)
    AS hours_to_first_answer,

  -- Funnel flag: got ANY answer ever (before snapshot).
  CAST(fa.first_answer_ts IS NOT NULL AS INT64) AS got_any_answer,

  -- Funnel flag: got an answer within 1 hour (community-was-fast signal).
  CAST(
    fa.first_answer_ts IS NOT NULL
    AND TIMESTAMP_DIFF(fa.first_answer_ts, c.first_question_ts, HOUR) <= 1
    AS INT64
  ) AS got_answer_within_1h,

  -- Funnel flag: got an answer within 24 hours (normal-speed signal).
  -- The "good question" question on SO usually gets answered within a day.
  CAST(
    fa.first_answer_ts IS NOT NULL
    AND TIMESTAMP_DIFF(fa.first_answer_ts, c.first_question_ts, HOUR) <= 24
    AS INT64
  ) AS got_answer_within_24h

FROM cohort_q c
LEFT JOIN first_answer_to_q fa
  ON fa.question_id = c.first_question_id
ORDER BY c.cohort_month, c.first_post_date;
