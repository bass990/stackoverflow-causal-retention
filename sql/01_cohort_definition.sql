-- ──────────────────────────────────────────────────────────────────────────────
-- 01_cohort_definition.sql
--
-- DEFINE NEW-CONTRIBUTOR COHORTS BY FIRST-POST MONTH.
--
-- A "new contributor" = a user whose FIRST POST (question OR answer) was within
-- the study window. Lurkers who only voted or commented are NOT in the cohort,
-- the project's question is about contributor retention, not visitor retention.
--
-- WHY first-post-date and not account-creation-date as the cohort anchor:
--   A user can create an account, never post, and "expire" without ever being a
--   contributor. Anchoring on first-post-date filters them out cleanly. It also
--   matches how a real Stack Overflow product team would think about a "new
--   contributor" cohort.
--
-- WHY the WHERE rn = 1 AND post_date BETWEEN... pattern:
--   We MUST identify each user's first post across THEIR ENTIRE post history,
--   not just within the study window. Otherwise a user whose real first post was
--   2010 but who posted again in 2018 would be wrongly classified as a 2018 new
--   contributor. So we rank globally, then filter to in-window first posts.
--
-- WHY ROW_NUMBER ORDERS BY creation_date (TIMESTAMP) NOT post_date (DATE):
--   Same-day-tied posts (user posted both a question and an answer on day 0)
--   need to be broken deterministically by actual time-of-day, not by the
--   non-deterministic tie-breaking BigQuery applies to same-DATE rows. With
--   TIMESTAMP ordering, ~46K users in the question-first cohort get their
--   first_post_type correctly identified (previously this was non-deterministic
--   between runs). first_post_DATE is still emitted as a DATE, since cohort
--   bucketing is monthly and downstream queries do DATE arithmetic against it.
--
-- WHY SPLIT(tags, '|') AND NOT THE ANGLE-BRACKET PATTERN:
--   The BigQuery public dataset stores tags pipe-separated like
--   "python|numpy|pandas", NOT angle-bracketed like "<python><numpy><pandas>".
--   The angle-bracket form is what stackexchange.com renders externally, but
--   the BQ table uses pipes. SPLIT(tags, '|')[SAFE_OFFSET(0)] returns the
--   first language tag cleanly.
--
-- COST CONSIDERATION:
--   Scans owner_user_id + creation_date + tags from posts_questions (~25 M rows)
--   and owner_user_id + creation_date from posts_answers (~36 M rows). BigQuery
--   bills by column-bytes-scanned, so this is ~2-3 GB per run depending on the
--   snapshot. Well under the 1 TB/month free tier. Run `make estimate-sql-01`
--   to confirm before running for real.
--
-- INTENDED USAGE:
--   Run ONCE; output is saved to data/processed/cohort.parquet via `make sql-01`.
--   All downstream SQL files read from that materialized cohort, not from this
--   query, so we don't re-scan the public dataset on every iteration.
-- ──────────────────────────────────────────────────────────────────────────────

DECLARE study_start_date DATE DEFAULT DATE '2018-01-01';
DECLARE study_end_date   DATE DEFAULT DATE '2023-12-31';

WITH all_posts AS (
  -- Union all posts (questions + answers) to find each user's first post overall.
  -- Tag question-posts with the first tag from the pipe-separated tags string.
  -- Tag answer-posts with NULL, resolving the parent question's tag would require
  -- an expensive JOIN at this stage; a downstream enrichment query can fill it in
  -- if needed.

  -- creation_date is TIMESTAMP. We carry it forward as post_ts for ROW_NUMBER
  -- ordering (sub-day precision) and also emit DATE(creation_date) AS post_date
  -- for cohort bucketing (monthly granularity is sufficient there).

  SELECT
    owner_user_id                       AS user_id,
    creation_date                       AS post_ts,
    DATE(creation_date)                 AS post_date,
    'question'                          AS post_type,
    SPLIT(tags, '|')[SAFE_OFFSET(0)]    AS first_tag_if_question
  FROM `bigquery-public-data.stackoverflow.posts_questions`
  WHERE owner_user_id IS NOT NULL

  UNION ALL

  SELECT
    owner_user_id                       AS user_id,
    creation_date                       AS post_ts,
    DATE(creation_date)                 AS post_date,
    'answer'                            AS post_type,
    CAST(NULL AS STRING)                AS first_tag_if_question
  FROM `bigquery-public-data.stackoverflow.posts_answers`
  WHERE owner_user_id IS NOT NULL
),

first_post_per_user AS (
  -- Rank all posts per user by full TIMESTAMP, keep the earliest one.
  -- Global ranking (not in-window) is critical, see top-of-file comment.
  SELECT
    user_id,
    post_date,
    post_type              AS first_post_type,
    first_tag_if_question,
    ROW_NUMBER() OVER (
      PARTITION BY user_id
      ORDER BY post_ts ASC
    ) AS rn
  FROM all_posts
)

SELECT
  user_id,
  DATE_TRUNC(post_date, MONTH) AS cohort_month,
  post_date                    AS first_post_date,
  first_post_type,
  first_tag_if_question        AS first_tag
FROM first_post_per_user
WHERE rn = 1
  AND post_date BETWEEN study_start_date AND study_end_date
ORDER BY cohort_month, first_post_date;
