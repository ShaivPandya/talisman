-- Run with psql -X --set=ON_ERROR_STOP=1 against the target application database
-- as a Cloud SQL administrator. Do not give the application role admin rights.
DO $$
BEGIN
  IF NOT ('pg_stat_statements' = ANY(regexp_split_to_array(current_setting('shared_preload_libraries'), '\s*,\s*'))) THEN
    RAISE EXCEPTION 'pg_stat_statements is not preloaded; inspect Cloud SQL configuration before continuing';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_stat_statements') THEN
    RAISE EXCEPTION 'pg_stat_statements is not available in this database';
  END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT extversion FROM pg_extension WHERE extname = 'pg_stat_statements';
SHOW pg_stat_statements.track;
SHOW max_connections;
SELECT stats_reset FROM pg_stat_statements_info;

-- Cumulative statement statistics are not request latency percentiles. Save a
-- start/end snapshot to calculate deltas; do not reset production statistics.
-- Omit query text and parameters from shared exports.
SELECT queryid, calls, total_exec_time, mean_exec_time, rows,
       shared_blks_hit, shared_blks_read
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY total_exec_time DESC
LIMIT 20;
