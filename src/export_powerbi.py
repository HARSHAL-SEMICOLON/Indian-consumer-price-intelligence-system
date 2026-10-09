"""Export the star schema to CSV for Power BI (powerbi/data/*.csv).

Power BI can also read the SQLite file directly through an ODBC driver; CSV is the
zero-setup option. Re-run after every pipeline run, then press Refresh in Power BI.
"""
import sqlite3

import pandas as pd

from config import DB_PATH, POWERBI_DIR, PROCESSED

TABLES = {
    "dim_date": "SELECT * FROM dim_date",
    "dim_source": "SELECT source_key, source_code, source_name, publisher, base_url, extraction_method, licence, data_role, limitations FROM dim_source",
    "dim_product": "SELECT * FROM dim_product",
    "dim_brand": "SELECT * FROM dim_brand",
    "dim_category": "SELECT * FROM dim_category",
    "dim_location": "SELECT * FROM dim_location",
    "fact_price": "SELECT * FROM fact_price",
    "fact_availability": "SELECT * FROM fact_availability",
    "dim_cpi_item": "SELECT * FROM dim_cpi_item",
    "fact_cpi_benchmark": "SELECT f.*, d.full_date AS month_start FROM fact_cpi_benchmark f JOIN dim_date d USING(date_key)",
    "bridge_commodity_cpi": "SELECT * FROM bridge_commodity_cpi",
    "dq_issue_log": "SELECT * FROM dq_issue_log WHERE run_id = (SELECT MAX(run_id) FROM etl_run) OR price_id IS NULL",
    "dq_check_summary": "SELECT * FROM dq_check_summary WHERE run_id = (SELECT MAX(run_id) FROM dq_check_summary)",
    "etl_raw_file": "SELECT * FROM etl_raw_file",
    "etl_run": "SELECT * FROM etl_run",
}


def export():
    out = POWERBI_DIR / "data"
    out.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    for name, sql in TABLES.items():
        df = pd.read_sql(sql, con)
        if "full_date" in df.columns:
            df["full_date"] = pd.to_datetime(df["full_date"])
        df.to_csv(out / f"{name}.csv", index=False, encoding="utf-8-sig")
    con.close()
    # price-spike monitor (computed by analysis.py) -> its own table for the alerts page
    spikes = PROCESSED / "analysis" / "q9_price_spikes.csv"
    if spikes.exists():
        pd.read_csv(spikes).to_csv(out / "price_spikes.csv", index=False, encoding="utf-8-sig")
    depth = PROCESSED / "analysis" / "q9_history_depth.csv"
    if depth.exists():
        pd.read_csv(depth).to_csv(out / "history_depth.csv", index=False, encoding="utf-8-sig")
    return out


if __name__ == "__main__":
    print(export())
