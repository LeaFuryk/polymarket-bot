#!/usr/bin/env bash
# Quick stats for the collection database.
DB="${1:-data/collection.db}"

sqlite3 -header -column -readonly "$DB" "
SELECT
    (SELECT COUNT(*) FROM candles) AS total_candles,
    (SELECT COUNT(*) FROM snapshots) AS total_snapshots,
    (SELECT datetime(MIN(start_time), 'unixepoch', 'localtime') FROM candles) AS first_candle,
    (SELECT datetime(MAX(start_time), 'unixepoch', 'localtime') FROM candles) AS last_candle,
    (SELECT COUNT(*) FROM candles WHERE candle_id NOT IN (SELECT DISTINCT candle_id FROM snapshots)) AS missing_snapshots,
    (SELECT COUNT(*) FROM candles WHERE outcome != (CASE WHEN close >= open THEN 'UP' ELSE 'DOWN' END)) AS outcome_mismatches;
"
