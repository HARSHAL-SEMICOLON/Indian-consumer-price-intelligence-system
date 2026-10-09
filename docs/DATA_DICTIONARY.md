# Data Dictionary (main tables)

## fact_price — one row per price observation
| Column | Meaning |
|---|---|
| price_id | surrogate key |
| source_key → dim_source | DOCA_PMD or OPEN_PRICES |
| source_record_id | natural key: Open Prices price id; DoCA `DOCA-<COMMODITY>|<date>|<retail/wholesale>` |
| date_key → dim_date | observation date (when the price applied) |
| collection_date_key → dim_date | date our pipeline captured it |
| product_key / brand_key / category_key / location_key | dimensions |
| price_type | retail / wholesale |
| price_paid | effective price for the pack or reporting unit (INR) |
| price_list | pre-discount price (= price_paid if not discounted) |
| discount_amount, discount_pct, is_discounted, discount_type | discount fields |
| pack_size_qty, std_unit | pack in canonical unit (0.5 + kg = 500 g) |
| normalized_price / normalized_list_price | price ÷ pack_size_qty |
| normalized_unit | INR/kg, INR/l, INR/unit |
| lookback_label | DoCA column: Price As On, 1 Week back, … |
| is_provisional | DoCA weekend value captured within 3 days |
| is_duplicate, duplicate_of_price_id | exact duplicate marker (kept, not deleted) |
| is_valid_price | 0 if missing/invalid/not reported |
| include_in_analysis | 0 if any excluding DQ check fired |
| dq_flags | semicolon list of fired checks |
| revision_count | times the source changed this value |

## fact_availability
| Column | Meaning |
|---|---|
| availability_status | `reported`, `not_reported` (gap in live series), `not_yet_tracked` (before first reported value) |
| is_available | 1 = price reported. **Not** a shelf stock-out indicator. |

## dim_product
product_code (barcode or `DOCA-…`), product_name (standardised), brand_key, category_key, pack_size_qty,
std_unit, pack_size_label, pack_size_source (api_product_quantity / parsed_quantity / parsed_product_name /
doca_reporting_unit / missing), product_type (Branded product / Commodity average), first/last_seen_date.

## dim_location
location_level (outlet / national), outlet_name, outlet_type (OSM shop tag), city, state, region, country_code, lat/lon, city_source.

## dim_category
category_group (Groceries, Packaged Food, Household, Personal Care, Out of scope, Unclassified), category, in_scope.

## dim_date
date_key yyyymmdd, full_date, year, quarter, month, month_name, year_month, iso_week, day_name, is_weekend.

## fact_cpi_benchmark (benchmark only)
cpi_item_key → dim_cpi_item (series_kind item/group_allindia, cpi_group, cpi_item, sector), date_key (1st of month), base_year, index_value, yoy_inflation_pct, status.

## dq_issue_log / dq_check_summary
Per-record issues (record_key, check_name, severity, action_taken) and per-run counts per check and source.
