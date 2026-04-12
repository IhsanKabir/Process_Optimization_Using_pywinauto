-- BigQuery DDL for GDS fare and tax data tables
-- Project: aeropulseintelligence
-- Dataset: aviation_intel
--
-- Run via:
--   bq query --use_legacy_sql=false < bigquery_schema.sql
-- Or paste into the BigQuery console.

-- ─────────────────────────────────────────────────────────────────────────────
-- fact_gds_fare_snapshot
--   One row per extraction run / airline / route / RBD / journey type.
--   Populated by bigquery_pusher.push_fare_snapshot() after every auto run.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `aeropulseintelligence.aviation_intel.fact_gds_fare_snapshot` (
    cycle_id          STRING    NOT NULL,   -- e.g. "gds_run_42"
    captured_at_utc   TIMESTAMP NOT NULL,   -- when the extraction ran
    airline           STRING    NOT NULL,   -- 2-3 char IATA code, e.g. "BG"
    origin            STRING    NOT NULL,   -- 3-char IATA airport, e.g. "DAC"
    destination       STRING    NOT NULL,   -- 3-char IATA airport, e.g. "MCT"
    route_key         STRING    NOT NULL,   -- "DAC-MCT"
    rbd               STRING    NOT NULL,   -- Reservation Booking Designator, e.g. "Y"
    cabin             STRING,               -- "Economy" | "Business" | "First" | "Premium Economy"
    fare_basis        STRING,               -- Fare basis code, e.g. "YOWBG"
    journey_type      STRING    NOT NULL,   -- "OW" | "RT"
    base_fare         FLOAT64,              -- Base fare in local currency
    total_taxes       FLOAT64,              -- Total taxes from FS breakdown
    total_fare        FLOAT64,              -- base_fare + total_taxes (0 if sold out)
    currency          STRING,               -- ISO 4217, e.g. "BDT"
    is_sold_out       BOOL,                 -- true when RBD shows sold-out status
    is_unsaleable     BOOL,                 -- true for unsaleable RBD entries
    source            STRING                -- always "gds_travelport"
)
PARTITION BY DATE(captured_at_utc)
CLUSTER BY airline, route_key, rbd
OPTIONS (
    description = 'GDS fare snapshots from Travelport Smartpoint extraction runs',
    require_partition_filter = false
);

-- ─────────────────────────────────────────────────────────────────────────────
-- fact_gds_change_event
--   One row per detected fare change (new / removed / price_change / sold_out).
--   Populated by bigquery_pusher.push_change_events() after every auto run.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `aeropulseintelligence.aviation_intel.fact_gds_change_event` (
    detected_at_utc   TIMESTAMP NOT NULL,
    report_day        DATE      NOT NULL,   -- date portion for easy filtering
    airline           STRING    NOT NULL,
    origin            STRING    NOT NULL,
    destination       STRING    NOT NULL,
    route_key         STRING    NOT NULL,
    rbd               STRING    NOT NULL,
    cabin             STRING,
    change_type       STRING    NOT NULL,   -- "new" | "removed" | "price_change" | "sold_out" | "available"
    old_ow_fare       FLOAT64,
    new_ow_fare       FLOAT64,
    old_rt_fare       FLOAT64,
    new_rt_fare       FLOAT64
)
PARTITION BY report_day
CLUSTER BY airline, route_key, change_type
OPTIONS (
    description = 'GDS fare change events detected between consecutive extraction runs'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- fact_gds_tax_snapshot
--   One row per extraction run / airport / tax code / section / rate.
--   Populated by bigquery_pusher.push_tax_snapshot() after every tax run.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `aeropulseintelligence.aviation_intel.fact_gds_tax_snapshot` (
    cycle_id          STRING    NOT NULL,   -- e.g. "gds_tax_run_17"
    captured_at_utc   TIMESTAMP NOT NULL,
    airport_code      STRING    NOT NULL,   -- 3-char IATA, e.g. "SIN"
    tax_code          STRING    NOT NULL,   -- e.g. "L7"
    tax_name          STRING,               -- e.g. "AIRPORT DEVELOPMENT LEVY"
    category          STRING,               -- e.g. "DEPARTURES FROM CHANGI SIN"
    subcategory       STRING,               -- e.g. "INTERNATIONAL DEPARTURES FROM TERMINAL 1 2 3"
    condition         STRING,               -- e.g. "TVL ON/AFTER 01APR25 AND ON/BEFORE 31MAR27"
    currency          STRING,               -- e.g. "SGD"
    amount            FLOAT64,              -- tax amount
    status            STRING,               -- "expired" | "current" | "future"
    source            STRING                -- always "gds_travelport"
)
PARTITION BY DATE(captured_at_utc)
CLUSTER BY airport_code, tax_code, status
OPTIONS (
    description = 'GDS airport tax rates from Travelport FTAX command extraction runs'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- ops_travelport_feedback
--   One row per feedback submission sent from the desktop GUI.
--   Read by the admin feedback page in the website/backend.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `aeropulseintelligence.aviation_intel.ops_travelport_feedback` (
    feedback_id       STRING    NOT NULL,
    submitted_at_utc  TIMESTAMP NOT NULL,
    category          STRING    NOT NULL,
    subject           STRING    NOT NULL,
    message           STRING    NOT NULL,
    status            STRING    NOT NULL,   -- new | reviewed | resolved
    app_version       STRING,
    device_id         STRING,
    device_name       STRING,
    hostname          STRING,
    os_version        STRING,
    source            STRING,               -- desktop_gui
    context_json      STRING,               -- serialized UI context for admin review
    admin_note        STRING
)
PARTITION BY DATE(submitted_at_utc)
CLUSTER BY status, category
OPTIONS (
    description = 'Desktop user feedback submitted from TravelportAuto and reviewed in admin'
);
