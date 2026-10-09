# Methodology & Limitations

## What this project is — and is not
- **Is:** a historical price-monitoring pipeline that combines official All-India commodity price
  averages (DoCA) with crowd-sourced branded-product price observations (Open Prices), standardises
  them to comparable unit prices, quality-checks them, and stores them in a star schema for SQL and Power BI.
- **Is not:** an inflation index. No CPI methodology is applied (no fixed basket, no expenditure weights,
  no Laspeyres aggregation). Average-of-commodity changes shown here must **not** be called "inflation".
  MoSPI CPI is loaded separately and only shown side by side as a benchmark.

## Collection period (be explicit)
| Source | Observation dates actually available | How |
|---|---|---|
| DoCA | 6 dates per commodity: **2024-09-30, 2025-09-30, 2026-03-30, 2026-08-30, 2026-09-23, 2026-09-30** | official look-back columns of one capture on 2026-10-01 |
| Open Prices | 2023-11-23 → 2026-09-29, **sparse** (≈380 usable rows, 364 distinct barcodes; most barcodes seen once) | API history |
| MoSPI CPI | monthly, Jan-2024 → Dec-2025 | API |

The project's **own** collection so far is a single capture date (2026-10-01). Every later run of
`python run_pipeline.py --extract` adds a new capture; DoCA then contributes a new daily point per
commodity. No observations have been interpolated, imputed or back-filled from anything other than the
sources' own published values.

## Pipeline
```
extract.py  -> data/raw/<source>/<date>/*.jsonl      (immutable, SHA-256 registered)
transform.py-> standardised records (one per raw row, nothing dropped)
load.py     -> stg_price_observation -> dims (get-or-create) -> fact_price (upsert on natural key)
quality.py  -> flags on every fact row + dq_issue_log + dq_check_summary
analysis.py -> sql/analysis_queries.sql -> data/processed/analysis/*.csv
export_powerbi.py -> powerbi/data/*.csv
```
**Incremental:** a raw file whose SHA-256 is already in `etl_raw_file` is skipped; a raw file that
changed after loading stops the run (raw immutability). Facts are keyed on
`(source, source_record_id)` — for DoCA `COMMODITY|date|price_type` — so re-capturing a date updates
it; if the value changed (provisional weekend data being revised) the old value is kept in
`fact_price_revision`.

## Standardisation rules
| Field | Rule |
|---|---|
| Currency | INR only; non-INR rows flagged `non_inr_currency` and excluded. |
| Pack size / weight / volume | Converted to a canonical unit: **kg**, **l** or **unit** (g÷1000, ml÷1000, dozen×12). Source order: structured `product_quantity`+unit → parse quantity text → parse product name (flagged). |
| Normalised price | `price_paid ÷ pack_size_in_canonical_unit` → INR/kg, INR/l, INR/unit. Comparisons happen **only within the same normalised unit**; raw pack prices of different sizes are never compared. |
| DoCA units | Per commodity from the dashboard (`1 Kg`, `1 Ltr`, `100 gm`, `250 gm`, `50 gm`, `1 Dozen`). E.g. butter ₹60.55 / 100 g → ₹605.5/kg; eggs ₹83.73/dozen → ₹6.98/egg. Wholesale ₹/quintal ÷ 100 → ₹/kg. |
| Product names | Unicode-normalised, whitespace collapsed, ALL-CAPS/all-lower converted to Title Case; raw name kept in `dim_product_name_history` (detects renames). |
| Brands | First brand in OFF's comma list; alias table (`normalize.BRAND_ALIASES`, e.g. "Brotannica" → Britannia, "Dabur India Ltd." → Dabur); every raw spelling stored in `dim_brand_alias`. |
| Categories | 4 required groups — **Groceries, Packaged Food, Household, Personal Care** (+ "Out of scope", "Unclassified") — derived from OFF category tags by ordered rules, or a DoCA lookup table. |
| Locations | City from OSM address, else parsed from OSM display name; aliases (Bangalore→Bengaluru, Mumbai Suburban→Mumbai…); state → region. DoCA = "All India (average)". |
| Dates | ISO `YYYY-MM-DD`; `dim_date` key `yyyymmdd`; continuous calendar for Power BI. Two dates per fact: **observation date** and **collection date**. |
| Discounts | `price_paid` = effective price. `price_list` = `price_without_discount` if discounted else price_paid. `discount_pct = (list − paid)/list`. |

## Data-quality checks (records are never deleted)
See `dq_check_summary`. Checks that **exclude** a row from analysis: missing/invalid price, DoCA "not
reported", non-INR, location outside India, out-of-scope category (electronics, alcohol), missing or
future date, exact duplicate, source-marked duplicate, price more than 10x below the same
product's median (e.g. ₹1 logged against a ₹67 median). Checks that only **flag**: missing pack size,
pack size parsed from name, quantity without unit, name/quantity mismatch, missing brand/name, brand
alias applied, changed product name, missing city, discount anomalies, implausible list price
(excluded from discount metrics only), normalised-price outlier (excluded from brand/location
rankings only), provisional weekend value, value revised by source.

## Price-spike monitor
For each DoCA commodity, day-to-day % changes are computed between consecutive observations 1–4 days
apart (weekends allowed; the year/month look-back points are not daily steps). A day is a **spike** when
`z = (change − commodity's mean daily change) / its standard deviation > 2`, a **sharp drop** when z < −2.
A commodity is only judged after 10 daily steps (`q9_history_depth`). Output: `q9_price_spikes.csv`,
Power BI page 7. Tested on a synthetic series with one injected 8% jump (detected, z ≈ 4.3).

## Limitations (read before quoting any number)
1. **Short official history:** DoCA gives 6 unevenly spaced points per commodity from one capture. Volatility = coefficient of variation across those points, not a daily-series standard deviation.
2. **Location analysis is weak.** DoCA centre-wise data is CAPTCHA-protected and not used, so location comparison relies on Open Prices: only **6 barcodes** were observed in 2+ cities. The category-relative city index mixes different products and is indicative only.
3. **Brand comparison is small-sample.** 231 brands, most with 1–2 observations; only 12 brand-category pairs have ≥3 observations. Rank only within one category and one unit.
4. **"Availability" ≠ stock-outs.** No legitimate source here reports shelf availability. `fact_availability` records whether DoCA *reported* a price; leading gaps are classed `not_yet_tracked` (commodity added to monitoring later — Broken Rice, Ginger, Garlic) rather than "unavailable".
5. **Crowd-sourced bias:** Open Prices contributors are concentrated in a few cities and in packaged snacks/beverages; prices may come from receipts with entry errors (examples caught: list price ₹99,99,999 for milk powder; Nutella priced against a 15 g pack).
6. **DoCA averages** hide variety/quality differences between centres; weekend values are provisional.
7. **CPI** base-2012 series ends Dec-2025 at access time; base-2024 series not yet served by the API.
