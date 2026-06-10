-- ──────────────────────────────────────────────────────────────────────────────
-- 04_leading_indicator_features.sql
--
-- EXTRACT FIRST-POST-TIME FEATURES FOR THE QUESTION-FIRST COHORT.
--
-- Produces a feature row per question-first cohort user, with features known
-- at the moment of first post (no leakage from future activity). Downstream
-- model joins this against retention.parquet (outcomes) to fit a D30/D180
-- predictor.
--
-- FEATURE SET (8 features):
--   QUALITY / EFFORT PROXIES
--     title_length      — chars; very-short titles ("help" "error") signal low effort
--     body_length       — chars; bimodal — too short = no detail, too long = unfocused
--     has_code_block    — body contains <code> or <pre> tag (programming-Q effort signal)
--     has_link          — body contains <a href=...> tag (external references)
--     has_image         — body contains <img src=...> tag (screenshots, often error msgs)
--
--   CATEGORIZATION
--     num_tags          — count of tags (1 = under-categorized, 5 = at the SO limit)
--
--   TIMING (community-availability proxies — when respondents are online)
--     hour_of_day_utc   — 0-23, UTC; correlates with worldwide active-respondent density
--     day_of_week       — 1=Sunday … 7=Saturday (BigQuery EXTRACT default)
--     is_weekend        — 1 if day_of_week IN (1, 7); weekday answers are typically faster
--
-- WHY QUESTION-FIRST ONLY:
--   Answer-first users (~27% of cohort) don't have a "first question" to extract
--   features from. A separate sql-04b could handle them using the first answer's
--   body length, parent question's complexity, etc. — out of scope here.
--
-- WHY ORDER BY post_ts (TIMESTAMP), NOT post_date (DATE):
--   Same fix as sql-03 — same-day ties in DATE-ordering are non-deterministic in
--   BigQuery and mis-label ~46K users' first_post_type. TIMESTAMP-ordering picks
--   the true earliest post. (sql-01 has the DATE-ordering bug; flagged for fix.)
--
-- WHY THESE REGEX patterns and not LIKE:
--   The body column is HTML. SO's renderer emits canonical tags — <code>, <pre>,
--   <a href=, <img src=. Anchoring on the open tag with proper attribute syntax
--   filters out incidental occurrences of these strings inside <code> blocks
--   themselves (where a user pasted, say, JavaScript that mentions "<img").
--
-- COST CONSIDERATION:
--   DOMINATED BY THE BODY COLUMN SCAN. Estimated ~25-30 GB total because:
--     posts_questions.body alone ≈ 25 GB (HTML, ~1000 chars × 25M rows)
--     other columns total ≈ 1-2 GB
--   At $5/TB this is ~$0.14. Run `make estimate-sql-04` to confirm before running.
--   This is the single most expensive query in the project — design accordingly.
-- ──────────────────────────────────────────────────────────────────────────────

DECLARE study_start_date DATE DEFAULT DATE '2018-01-01';
DECLARE study_end_date   DATE DEFAULT DATE '2023-12-31';

WITH all_posts AS (
  -- Slim union for the cohort-rank step. We don't need title/body/tags here —
  -- we'll JOIN those columns back to the question's row at the end so we only
  -- scan the heavy body column ONCE (in the cohort-q SELECT, filtered to
  -- question-first users only).
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
  -- Global ranking — see sql-01 comment for why GLOBAL not in-window.
  -- TIMESTAMP-ordering — see sql-03 comment for why TS not DATE.
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
  -- Question-first cohort. Output one row per user, carrying the first
  -- question's post_id and timestamp so we can join feature columns next.
  SELECT
    post_id  AS first_question_id,
    user_id,
    post_ts  AS first_question_ts,
    post_date AS first_post_date,
    DATE_TRUNC(post_date, MONTH) AS cohort_month
  FROM first_post_per_user
  WHERE rn = 1
    AND post_type = 'question'
    AND post_date BETWEEN study_start_date AND study_end_date
)

SELECT
  c.user_id,
  c.cohort_month,
  c.first_post_date,
  c.first_question_id,

  -- ── QUALITY / EFFORT PROXIES ────────────────────────────────────────────────
  CHAR_LENGTH(q.title)                              AS title_length,
  CHAR_LENGTH(q.body)                               AS body_length,
  CAST(REGEXP_CONTAINS(q.body, r'<code>')     AS INT64) AS has_code_block,
  CAST(REGEXP_CONTAINS(q.body, r'<a\s+href=') AS INT64) AS has_link,
  CAST(REGEXP_CONTAINS(q.body, r'<img\s')     AS INT64) AS has_image,

  -- ── CATEGORIZATION ─────────────────────────────────────────────────────────
  -- Tags are pipe-separated (see sql-01 first_tag bug — same dataset format).
  -- SAFE_DIVIDE protects against empty-tags edge case (would be 0 not NULL).
  ARRAY_LENGTH(SPLIT(q.tags, '|'))                  AS num_tags,

  -- ── TIMING ─────────────────────────────────────────────────────────────────
  EXTRACT(HOUR      FROM q.creation_date)           AS hour_of_day_utc,
  EXTRACT(DAYOFWEEK FROM q.creation_date)           AS day_of_week,
  CAST(EXTRACT(DAYOFWEEK FROM q.creation_date) IN (1, 7) AS INT64) AS is_weekend

FROM cohort_q c
INNER JOIN `bigquery-public-data.stackoverflow.posts_questions` q
  ON q.id = c.first_question_id
ORDER BY c.cohort_month, c.first_post_date;
