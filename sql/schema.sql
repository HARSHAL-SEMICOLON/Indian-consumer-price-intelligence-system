-- Indian Consumer Price & Market Intelligence System - SQLite star schema
-- Created idempotently (IF NOT EXISTS) so new collection dates are appended
-- without rebuilding the database.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- ETL control
CREATE TABLE IF NOT EXISTS etl_raw_file (
    raw_file_id     INTEGER PRIMARY KEY,
    source_code     TEXT NOT NULL,
    relative_path   TEXT NOT NULL UNIQUE,
    sha256          TEXT NOT NULL UNIQUE,      -- same bytes never loaded twice
    bytes           INTEGER,
    collection_date TEXT NOT NULL,             -- date the raw file was captured
    records_parsed  INTEGER,
    loaded_at_utc   TEXT NOT NULL,
    run_id          INTEGER
);
CREATE TABLE IF NOT EXISTS etl_run (
    run_id        INTEGER PRIMARY KEY,
    started_utc   TEXT, finished_utc TEXT,
    new_files     INTEGER, new_fact_rows INTEGER, updated_fact_rows INTEGER, notes TEXT
);

-- ---------------------------------------------------------------- staging (one row per raw record, never deleted)
CREATE TABLE IF NOT EXISTS stg_price_observation (
    stg_id INTEGER PRIMARY KEY,
    raw_file_id INTEGER REFERENCES etl_raw_file(raw_file_id),
    source_code TEXT, source_record_id TEXT, capture_file TEXT, collection_date TEXT,
    observation_date TEXT, lookback_label TEXT, price_type TEXT, currency TEXT,
    price REAL, price_without_discount REAL, is_discounted INTEGER, discount_type TEXT,
    product_code TEXT, product_name_raw TEXT, product_name_std TEXT,
    brand_raw TEXT, brand_std TEXT, brand_rule TEXT,
    category_group TEXT, category TEXT, category_rule TEXT,
    pack_qty_raw TEXT, pack_unit_raw TEXT, quantity_text_raw TEXT,
    qty_std REAL, std_unit TEXT, pack_size_source TEXT,
    location_src_id TEXT, location_level TEXT, country_code TEXT, state TEXT, region TEXT,
    city TEXT, city_raw TEXT, city_source TEXT, outlet_type TEXT, outlet_name TEXT, lat REAL, lon REAL,
    is_provisional INTEGER, reported_status TEXT, src_duplicate_of TEXT, proof_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_stg_key ON stg_price_observation(source_code, source_record_id);

-- ---------------------------------------------------------------- dimensions
CREATE TABLE IF NOT EXISTS dim_source (
    source_key INTEGER PRIMARY KEY, source_code TEXT UNIQUE, source_name TEXT, publisher TEXT,
    base_url TEXT, extraction_method TEXT, licence TEXT, granularity TEXT, data_role TEXT, limitations TEXT
);
CREATE TABLE IF NOT EXISTS dim_date (
    date_key INTEGER PRIMARY KEY,               -- yyyymmdd
    full_date TEXT UNIQUE, year INTEGER, quarter INTEGER, month INTEGER, month_name TEXT,
    year_month TEXT, iso_week INTEGER, day_of_month INTEGER, day_name TEXT, is_weekend INTEGER
);
CREATE TABLE IF NOT EXISTS dim_brand (
    brand_key INTEGER PRIMARY KEY, brand_name TEXT UNIQUE, is_branded INTEGER
);
CREATE TABLE IF NOT EXISTS dim_brand_alias (           -- every raw spelling seen -> standard brand
    brand_raw TEXT PRIMARY KEY, brand_key INTEGER REFERENCES dim_brand(brand_key), rule TEXT
);
CREATE TABLE IF NOT EXISTS dim_category (
    category_key INTEGER PRIMARY KEY, category_group TEXT, category TEXT,
    in_scope INTEGER, UNIQUE(category_group, category)
);
CREATE TABLE IF NOT EXISTS dim_location (
    location_key INTEGER PRIMARY KEY, source_code TEXT, location_src_id TEXT,
    location_level TEXT, outlet_name TEXT, outlet_type TEXT, city TEXT, state TEXT, region TEXT,
    country_code TEXT, latitude REAL, longitude REAL, city_source TEXT,
    UNIQUE(source_code, location_src_id)
);
CREATE TABLE IF NOT EXISTS dim_product (
    product_key INTEGER PRIMARY KEY, source_code TEXT, product_code TEXT,
    product_name TEXT,                       -- latest standardised name
    brand_key INTEGER REFERENCES dim_brand(brand_key),
    category_key INTEGER REFERENCES dim_category(category_key),
    pack_size_qty REAL,                      -- quantity in std_unit (e.g. 0.5 for 500 g)
    std_unit TEXT,                           -- kg | l | unit
    pack_size_label TEXT,                    -- human-readable e.g. '500 g', '1 Kg', '1 Dozen'
    pack_size_source TEXT,
    product_type TEXT,                       -- 'Branded product' | 'Commodity average'
    first_seen_date TEXT, last_seen_date TEXT,
    UNIQUE(source_code, product_code)
);
CREATE TABLE IF NOT EXISTS dim_product_name_history (   -- detects changed product names
    product_key INTEGER REFERENCES dim_product(product_key), product_name_raw TEXT,
    first_capture TEXT, last_capture TEXT, PRIMARY KEY(product_key, product_name_raw)
);

-- ---------------------------------------------------------------- facts
CREATE TABLE IF NOT EXISTS fact_price (
    price_id INTEGER PRIMARY KEY,
    source_key INTEGER REFERENCES dim_source(source_key),
    source_record_id TEXT NOT NULL,
    date_key INTEGER REFERENCES dim_date(date_key),          -- observation date
    collection_date_key INTEGER REFERENCES dim_date(date_key),
    product_key INTEGER REFERENCES dim_product(product_key),
    brand_key INTEGER REFERENCES dim_brand(brand_key),
    category_key INTEGER REFERENCES dim_category(category_key),
    location_key INTEGER REFERENCES dim_location(location_key),
    price_type TEXT NOT NULL,              -- retail | wholesale
    currency TEXT,
    price_paid REAL,                       -- effective price actually charged (per pack / reporting unit)
    price_list REAL,                       -- pre-discount price if discounted, else = price_paid
    discount_amount REAL, discount_pct REAL, is_discounted INTEGER, discount_type TEXT,
    pack_size_qty REAL, std_unit TEXT,
    normalized_price REAL,                 -- price_paid / pack_size_qty  -> Rs per kg | litre | unit
    normalized_list_price REAL,
    normalized_unit TEXT,                  -- 'INR/kg' | 'INR/l' | 'INR/unit'
    lookback_label TEXT,                   -- DoCA: 'Price As On', '1 Year back', ...
    is_provisional INTEGER DEFAULT 0,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_of_price_id INTEGER,
    is_valid_price INTEGER DEFAULT 1,
    include_in_analysis INTEGER DEFAULT 1,
    dq_flags TEXT,                         -- semicolon list of check names
    revision_count INTEGER DEFAULT 0,
    first_loaded_utc TEXT, last_updated_utc TEXT,
    UNIQUE(source_key, source_record_id)
);
CREATE INDEX IF NOT EXISTS ix_fp_prod_date ON fact_price(product_key, date_key);

CREATE TABLE IF NOT EXISTS fact_price_revision (       -- provisional values later revised by source
    price_id INTEGER REFERENCES fact_price(price_id), old_price REAL, new_price REAL,
    old_capture TEXT, new_capture TEXT, revised_at_utc TEXT
);

CREATE TABLE IF NOT EXISTS fact_availability (
    availability_id INTEGER PRIMARY KEY,
    source_key INTEGER REFERENCES dim_source(source_key),
    product_key INTEGER REFERENCES dim_product(product_key),
    location_key INTEGER REFERENCES dim_location(location_key),
    date_key INTEGER REFERENCES dim_date(date_key),
    collection_date_key INTEGER REFERENCES dim_date(date_key),
    price_type TEXT,
    availability_status TEXT,     -- reported | not_reported | not_yet_tracked
    is_available INTEGER,         -- 1 reported, 0 not reported (NOT a shelf stock-out)
    UNIQUE(source_key, product_key, location_key, date_key, price_type)
);

CREATE TABLE IF NOT EXISTS dim_cpi_item (
    cpi_item_key INTEGER PRIMARY KEY, series_kind TEXT, cpi_group TEXT, cpi_item TEXT, sector TEXT,
    UNIQUE(series_kind, cpi_group, cpi_item, sector)
);
CREATE TABLE IF NOT EXISTS fact_cpi_benchmark (       -- BENCHMARK ONLY - never joined into fact_price
    cpi_item_key INTEGER REFERENCES dim_cpi_item(cpi_item_key),
    date_key INTEGER REFERENCES dim_date(date_key),   -- 1st of month
    base_year INTEGER, index_value REAL, yoy_inflation_pct REAL, status TEXT, capture_file TEXT,
    PRIMARY KEY(cpi_item_key, date_key, base_year)
);
CREATE TABLE IF NOT EXISTS bridge_commodity_cpi (    -- maps DoCA commodity -> closest CPI item (context only)
    product_key INTEGER REFERENCES dim_product(product_key), cpi_item_key INTEGER REFERENCES dim_cpi_item(cpi_item_key),
    match_quality TEXT, PRIMARY KEY(product_key, cpi_item_key)
);

-- ---------------------------------------------------------------- data quality
CREATE TABLE IF NOT EXISTS dq_issue_log (
    issue_id INTEGER PRIMARY KEY, run_id INTEGER, source_code TEXT, record_key TEXT, price_id INTEGER,
    check_name TEXT, severity TEXT, field TEXT, observed_value TEXT, action_taken TEXT, capture_file TEXT,
    logged_at_utc TEXT
);
CREATE TABLE IF NOT EXISTS dq_check_summary (
    run_id INTEGER, check_name TEXT, description TEXT, source_code TEXT, rows_checked INTEGER,
    rows_flagged INTEGER, action TEXT, PRIMARY KEY(run_id, check_name, source_code)
);
