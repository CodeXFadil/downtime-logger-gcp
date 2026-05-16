-- scripts/migrate_schema.sql
-- Run against: Cloud SQL PostgreSQL — downtime-db
-- Tool: psql or Cloud SQL Studio

-- 1. Create DowntimeRecords table
CREATE TABLE IF NOT EXISTS DowntimeRecords (
    id               SERIAL PRIMARY KEY,
    site_name        VARCHAR(100) NOT NULL,
    equipment_id     VARCHAR(100) NOT NULL,
    reason           VARCHAR(200) NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_time       TIMESTAMP DEFAULT NOW(),
    operator_name    VARCHAR(200),
    notes            TEXT,
    category         VARCHAR(20),
    shift            VARCHAR(20)
);

-- 2. Create Equipment table
CREATE TABLE IF NOT EXISTS Equipment (
    id           SERIAL PRIMARY KEY,
    site_name    VARCHAR(100) NOT NULL,
    equipment_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (site_name, equipment_id)
);

-- 3. Create DowntimeReasons table
CREATE TABLE IF NOT EXISTS DowntimeReasons (
    reason_id   SERIAL PRIMARY KEY,
    reason_name VARCHAR(200) NOT NULL UNIQUE,
    category    VARCHAR(20)  NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);

-- 4. Views for BigQuery / Power BI (created after Datastream replicates tables)
CREATE OR REPLACE VIEW vw_downtime_global AS
SELECT
    site_name,
    DATE(start_time)     AS event_date,
    COUNT(*)             AS total_events,
    SUM(duration_minutes) AS total_minutes,
    SUM(CASE WHEN category = 'Unplanned' THEN duration_minutes ELSE 0 END) AS unplanned_minutes,
    SUM(CASE WHEN category = 'Planned'   THEN duration_minutes ELSE 0 END) AS planned_minutes
FROM DowntimeRecords
GROUP BY site_name, DATE(start_time);

CREATE OR REPLACE VIEW vw_downtime_by_equipment AS
SELECT
    site_name,
    equipment_id,
    COUNT(*)              AS event_count,
    AVG(duration_minutes) AS avg_duration_minutes,
    SUM(duration_minutes) AS total_minutes
FROM DowntimeRecords
WHERE category = 'Unplanned'
GROUP BY site_name, equipment_id;

CREATE OR REPLACE VIEW vw_planned_vs_unplanned AS
SELECT
    site_name,
    category,
    COUNT(*)              AS event_count,
    SUM(duration_minutes) AS total_minutes
FROM DowntimeRecords
GROUP BY site_name, category;
