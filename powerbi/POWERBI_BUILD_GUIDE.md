# Power BI Build Guide — Indian Consumer Price & Market Intelligence

The pipeline exports the star schema to `powerbi/data/*.csv` (UTF-8). Build the report once;
afterwards each new collection only needs `python run_pipeline.py --extract` → **Refresh** in Power BI.

---

## 1. Load data

**Get Data → Text/CSV**, load these files from `powerbi/data/`:

| Table | Role |
|---|---|
| `fact_price` | main fact (one row per price observation) |
| `fact_availability` | DoCA reported / not-reported status per commodity-date |
| `fact_cpi_benchmark` | MoSPI CPI index (benchmark only) |
| `dim_date`, `dim_product`, `dim_brand`, `dim_category`, `dim_location`, `dim_source` | dimensions |
| `dim_cpi_item`, `bridge_commodity_cpi` | CPI benchmark mapping |
| `dq_issue_log`, `dq_check_summary`, `etl_raw_file`, `etl_run` | data-quality page |

Power Query fixes (Transform Data):
- `dim_date[full_date]` → type **Date**. Mark `dim_date` as date table (**Table tools → Mark as date table → full_date**).
- `fact_price[price_paid]`, `price_list`, `normalized_price`, `normalized_list_price`, `discount_pct` → **Decimal number**.
- `include_in_analysis`, `is_discounted`, `is_duplicate`, `is_provisional`, `is_valid_price` → **Whole number** (0/1).

## 2. Relationships (Model view) — single direction, many-to-one

```
fact_price[date_key]            → dim_date[date_key]          (active)
fact_price[collection_date_key] → dim_date[date_key]          (INACTIVE – use USERELATIONSHIP)
fact_price[product_key]         → dim_product[product_key]
fact_price[brand_key]           → dim_brand[brand_key]
fact_price[category_key]        → dim_category[category_key]
fact_price[location_key]        → dim_location[location_key]
fact_price[source_key]          → dim_source[source_key]
fact_availability[date_key]     → dim_date[date_key]
fact_availability[product_key]  → dim_product[product_key]
fact_availability[location_key] → dim_location[location_key]
fact_cpi_benchmark[date_key]    → dim_date[date_key]
fact_cpi_benchmark[cpi_item_key]→ dim_cpi_item[cpi_item_key]
bridge_commodity_cpi[cpi_item_key] → dim_cpi_item[cpi_item_key]
```
Do **not** relate `fact_cpi_benchmark` to `dim_product` directly — the CPI is a different
methodology and must stay a separate benchmark. Use the bridge only on the benchmark visual.

## 3. Measures

Create a blank table `_Measures` and paste the measures from `DAX_MEASURES.md`.

## 4. Report-level filter

Add **fact_price[include_in_analysis] = 1** as a *report-level* filter on pages 1–5
(Page 6 Data Quality must NOT have it).

Add a text box on every page footer:
> *Sources: DoCA Price Monitoring Division (All-India averages), Open Prices / Open Food Facts (crowd-sourced, ODbL), MoSPI CPI (benchmark only). Not an official inflation measure. Data captured 2026-10-01; see docs/METHODOLOGY_AND_LIMITATIONS.md.*

---

## Page 1 — Consumer Price Overview
| Visual | Fields |
|---|---|
| 4 KPI cards | `[Commodities Tracked]`, `[Branded Products Observed]`, `[Cities Covered]`, `[Latest Collection Date]` |
| 2 KPI cards | `[Avg YoY Change % (DoCA)]`, `[Avg MoM Change % (DoCA)]` |
| Clustered bar | Axis `dim_product[product_name]`, Value `[YoY Change %]`; filter source = DOCA_PMD; Top N 10 by value |
| Line chart | Axis `dim_date[full_date]`, Value `[Avg Normalized Price]`, Legend `dim_category[category]`, filter DOCA_PMD retail |
| Slicers | `dim_category[category_group]`, `dim_source[source_name]` |
| Text box | limitations note (short series; DoCA has 6 dated points per commodity in the first capture) |

## Page 2 — Product Price Trends
| Visual | Fields |
|---|---|
| Slicer | `dim_product[product_name]` (DoCA commodities) |
| Line + markers | Axis `dim_date[full_date]` (continuous), Value `[Avg Normalized Price]`, tooltip `fact_price[lookback_label]` |
| Table | product, latest price, `[Price 1M Ago]`, `[Price 1Y Ago]`, `[MoM Change %]`, `[YoY Change %]` with conditional formatting (red ↑ / green ↓) |
| Bar | `[MoM Change %]` by `dim_category[category]` |
| Benchmark line (optional) | `fact_cpi_benchmark[index_value]` by `dim_date[full_date]` for the CPI item mapped to the selected commodity (filter via `dim_cpi_item[cpi_item]`), clearly titled *"MoSPI CPI index (2012=100) – benchmark, not comparable in level"* |

## Page 3 — Brand Comparison
| Visual | Fields |
|---|---|
| Slicers | `dim_category[category]` (single select **required**), `fact_price[normalized_unit]` (single select) |
| Bar (sorted ascending) | Axis `dim_brand[brand_name]`, Value `[Avg Normalized Price]`; visual filter `dim_brand[is_branded]=1` |
| Table | brand, `[Observations]`, `[Distinct Products]`, `[Min Normalized Price]`, `[Max Normalized Price]`, `[Sample Flag]` |
| Card | `[Brands in Selection]` |
| Warning text | *"Compare within one category and one unit only. Many brands have 1–2 observations."* |

## Page 4 — Location Comparison
| Visual | Fields |
|---|---|
| Map / Filled map | Location `dim_location[state]`, Size `[Observations]`, tooltip `[City Price Index]` |
| Bar | `dim_location[city]` × `[City Price Index]` (product-matched method) |
| Table | Q6 — products in 2+ cities: `dim_product[product_name]`, `[Cities for Product]`, `[Min Pack Price]`, `[Max Pack Price]`, `[Location Spread %]` |
| Bar (DoCA) | `dim_product[product_name]` × `[Retail Markup over Wholesale %]` |
| Callout | *"Location coverage is thin: only 6 barcodes were seen in 2+ cities. Centre-wise DoCA data is CAPTCHA-protected and intentionally not used."* |

## Page 5 — Discount & Availability
| Visual | Fields |
|---|---|
| KPI cards | `[% Observations Discounted]`, `[Avg Discount % (when discounted)]`, `[Total Savings INR]` |
| Clustered bar | `dim_category[category]` × `[Avg Normalized List Price]` and `[Avg Normalized Effective Price]` |
| Bar | `dim_category[category]` × `[% Observations Discounted]` |
| Matrix (availability) | Rows `dim_product[product_name]`, Columns `dim_date[full_date]`, Value `[Availability Status]` with conditional colour (reported green / not_reported red / not_yet_tracked grey) |
| Card | `[Not Reported Gap Rate %]` |

## Page 7 — Price-Spike Monitor
Tables `price_spikes` and `history_depth` (standalone, no relationships). Cards: `[Spikes This Week]`,
`[Sharp Drops This Week]`, `[Commodities Ready]`, `[Daily History (days)]`; tables: this week's spikes,
history per commodity, all spikes. Empty until each commodity has 10+ daily steps.

## Page 6 — Data Quality
No `include_in_analysis` filter on this page.
| Visual | Fields |
|---|---|
| KPI cards | `[Total Raw Records]`, `[Records Excluded]`, `[Records Flagged]`, `[% Usable]` |
| Bar | `dq_check_summary[check_name]` × `dq_check_summary[rows_flagged]`, legend `dq_check_summary[action]` |
| Table | `dq_check_summary` (check, source, rows_checked, rows_flagged, action, description) |
| Table | `dq_issue_log` (record_key, check_name, severity, action_taken) with slicer on `check_name` |
| Table | `etl_raw_file` (relative_path, sha256, collection_date, records_parsed, loaded_at_utc) — provenance |
| Donut | `fact_price[include_in_analysis]` count by `dim_source[source_code]` |
