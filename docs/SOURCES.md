# Data Sources — research log

Access date for every capture below: **2026-10-01** (IST). Raw files are stored unmodified under
`data/raw/<source>/<date>/` and fingerprinted (SHA-256) in the `etl_raw_file` table.

## Sources USED

### 1. DoCA Price Monitoring Division — public dashboard (official, primary for commodities)
| Item | Detail |
|---|---|
| URL | https://fcainfoweb.nic.in/Reports/DB/DBprices.aspx (daily average retail prices, with look-backs) and https://fcainfoweb.nic.in/ (home page: retail + wholesale) |
| Publisher | Department of Consumer Affairs, Ministry of Consumer Affairs, Food & Public Distribution, GoI (site by NIC) |
| What it gives | All-India **average** retail price for ~42 essential commodities (rice, atta, dals, edible oils, sugar, milk, onion, tomato, spices, eggs…) on the latest date **and official values 1 week, 1 month, 6 months, 1 year, 2 years back**; home page adds All-India wholesale (₹/quintal). |
| Extraction | Plain HTTP GET of public pages (no login, no CAPTCHA, no form posts). HTML tables parsed with `pandas.read_html`. Raw HTML stored inside a JSON envelope `{url, fetched_at_utc, http_status, content_type, body}`. |
| Terms / limitations | GoI website content; reproduce with attribution ("Source: State Civil Supplies Deptt, via DoCA PMD"). No robots.txt was served (HTTP 404/"URL inaccessible"). Prices are averages over reporting centres; *quality/variety differs by centre*; weekend/holiday values are provisional until verified. **Centre-wise reports (`report_menu_web.aspx`) require a CAPTCHA and were deliberately NOT accessed.** Only All-India level is used. |

### 2. Open Prices (Open Food Facts) — branded product observations
| Item | Detail |
|---|---|
| URL | https://prices.openfoodfacts.org/api/v1/prices?currency=INR&size=100&order_by=id&page=N |
| Publisher | Open Food Facts (non-profit), project repo https://github.com/openfoodfacts/open-prices |
| What it gives | Individual price observations submitted by contributors from receipts/price-tag photos: barcode, product name, brand, pack quantity, price, `price_is_discounted`, `price_without_discount`, shop (OpenStreetMap place → city/state/lat-lon), date. |
| Extraction | Public JSON REST API, paginated (5 pages, 402 rows with currency INR; 390 located in India). No key needed. Polite 1 s delay, identifying User-Agent in `src/extract.py`. |
| Terms / limitations | Open data (Open Food Facts databases are under the **Open Database Licence (ODbL)** — attribute "Open Prices / Open Food Facts" and share derived databases alike; verify current terms on the repo). Contributor usernames are present in raw files but are **not** loaded into the database. Crowd-sourced → non-random, sparse, skewed to contributors' cities (Madurai, Hyderabad, Bengaluru dominate). No stock/availability field. |

### 3. MoSPI CPI API — benchmark only
| Item | Detail |
|---|---|
| URL | https://api.mospi.gov.in/api/cpi/getItemIndex (item level) and https://api.mospi.gov.in/api/cpi/getCPIIndex?state_code=99 (All-India group/sub-group, Rural/Urban/Combined); manual: https://api.mospi.gov.in/API/CPI%20API%20User%20Manual.pdf |
| Publisher | Ministry of Statistics & Programme Implementation (NSO), GoI |
| What it gives | Monthly CPI index (base 2012=100) and YoY inflation, Jan-2024 → Dec-2025 (base-2012 series; the API returned no data for base 2024 / year 2026 at access time). |
| Extraction | Public REST API; without registration it returns 10 rows/page, so 920 pages were fetched, plus a 78-page targeted backfill. No account was created. |
| Terms / limitations | Official statistics, reuse with attribution. **Index numbers, not prices** → kept in `fact_cpi_benchmark`, never merged into `fact_price`. Data-quality finding: large paginated queries are not stably ordered (85 group-index rows were returned twice and 85 others skipped); fixed by a backfill of small month×sector slices with completeness checks (see `dq_issue_log`, check `api_pagination_duplicate`). |

## Sources investigated and NOT used

| Source | Reason |
|---|---|
| DoCA centre-wise retail/wholesale reports (`fcainfoweb.nic.in/reports/report_menu_web.aspx`) | Protected by CAPTCHA → excluded (project rule: never bypass CAPTCHA). |
| BigBasket, Blinkit, Zepto, JioMart, Amazon, Flipkart, DMart Ready | Terms of use prohibit automated scraping; login/location walls and anti-bot measures. Not accessed. |
| NHB (National Horticulture Board) market price reports | Public ASP.NET form, no CAPTCHA, but the report request hung at "Please wait" repeatedly; dropped to avoid hammering the server. Candidate for later. |
| data.gov.in "Daily/weekly retail prices of milk" etc. | Last updated 2015 → too old for this project. |
| dataful.in repackaged DoCA datasets | Third-party repackaging (account/download gating); the official origin (DoCA) is preferred. |

## Benchmark vs product-price separation
`fact_price` contains only **prices** (DoCA averages + Open Prices observations).
`fact_cpi_benchmark` contains only **CPI index numbers**. They are compared side by side
(`bench_doca_vs_cpi_yoy`) but never added, averaged or charted on the same axis as if they were the same measure.
