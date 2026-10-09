"""Project configuration: paths and the source registry.

Every path is relative to the project root so the project can be moved
(e.g. E:\\DA PROJECTS\\Indian Consumer Price Intelligence) without edits.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
DB_PATH = ROOT / "database" / "consumer_prices.db"
FIGURES = ROOT / "reports" / "figures"
SQL_DIR = ROOT / "sql"
POWERBI_DIR = ROOT / "powerbi"
DOCS = ROOT / "docs"
SCHEMA_SQL = SQL_DIR / "schema.sql"
ANALYSIS_SQL = SQL_DIR / "analysis_queries.sql"

USER_AGENT = (
    "IndianConsumerPriceIntelligence/1.0 (student portfolio project; "
    "contact: harshalagre1234@gmail.com)"
)
REQUEST_DELAY_SEC = 1.0  # polite delay between HTTP requests

# Source registry -> loaded into dim_source. Keep in sync with docs/SOURCES.md
SOURCES = {
    "OPEN_PRICES": {
        "source_name": "Open Prices (Open Food Facts)",
        "publisher": "Open Food Facts (non-profit)",
        "base_url": "https://prices.openfoodfacts.org/api/v1/prices",
        "extraction_method": "Public REST API (JSON), paginated, filter currency=INR; India rows kept by location country code",
        "licence": "Database: ODbL 1.0; proof images CC BY-SA (not downloaded)",
        "granularity": "Single crowd-sourced price observation: product (barcode) x shop x date",
        "data_role": "PRODUCT_PRICE",
        "limitations": "Crowd-sourced, non-random, sparse (hundreds of rows for all of India); "
                       "no stock/availability field; city coverage skewed to contributors' cities.",
    },
    "DOCA_PMD": {
        "source_name": "Dept. of Consumer Affairs - Price Monitoring Division (public dashboard)",
        "publisher": "Ministry of Consumer Affairs, Food & Public Distribution, GoI (hosted by NIC)",
        "base_url": "https://fcainfoweb.nic.in/Reports/DB/DBprices.aspx",
        "extraction_method": "HTTP GET of public dashboard HTML (no login, no CAPTCHA); HTML tables parsed with pandas.read_html",
        "licence": "Government of India website content; reuse with attribution (see SOURCES.md)",
        "granularity": "All-India daily average retail price per commodity, with official look-back values "
                       "(1 week, 1 month, 6 months, 1 year, 2 years); home page also gives wholesale (Rs/quintal)",
        "data_role": "COMMODITY_PRICE",
        "limitations": "All-India average only (centre-wise reports are CAPTCHA-protected and were NOT used); "
                       "weekend/holiday values provisional; quality/variety differs by centre.",
    },
    "MOSPI_CPI": {
        "source_name": "MoSPI CPI API (base 2012)",
        "publisher": "Ministry of Statistics & Programme Implementation, GoI",
        "base_url": "https://api.mospi.gov.in/api/cpi/",
        "extraction_method": "Public REST API (JSON), getItemIndex + getCPIIndex(state_code=99 All India), 10 rows/page without token",
        "licence": "Official statistics, free reuse with attribution",
        "granularity": "Monthly index (2012=100) and YoY inflation by item / subgroup",
        "data_role": "BENCHMARK_ONLY",
        "limitations": "Index numbers, not prices. Used ONLY as an external benchmark; never mixed into fact_price. "
                       "Base-2012 series available to Dec 2025.",
    },
}
