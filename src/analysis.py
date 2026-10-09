"""Run sql/analysis_queries.sql block by block and save each result to data/processed/analysis/<name>.csv"""
import math
import re
import sqlite3

import pandas as pd

from config import ANALYSIS_SQL, DB_PATH, PROCESSED

OUT = PROCESSED / "analysis"


def blocks():
    text = ANALYSIS_SQL.read_text(encoding="utf-8")
    parts = re.split(r"^-- name: (\S+)\s*$", text, flags=re.M)
    return [(parts[i], parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def connect():
    """SQLite connection with SQRT registered (some Windows builds ship SQLite without math functions)."""
    con = sqlite3.connect(DB_PATH)
    con.create_function("SQRT", 1, lambda x: math.sqrt(x) if x is not None and x >= 0 else None)
    return con


def run_all(verbose=False):
    OUT.mkdir(parents=True, exist_ok=True)
    con = connect()
    results = {}
    for name, sql in blocks():
        if name.startswith("v_"):
            con.executescript(sql)
            continue
        df = pd.read_sql(sql, con)
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
        results[name] = df
        if verbose:
            print(f"\n=== {name} ({len(df)} rows)")
            print(df.head(15).to_string())
    con.commit()
    con.close()
    return results


if __name__ == "__main__":
    pd.set_option("display.width", 250, "display.max_columns", 30, "display.max_colwidth", 40)
    run_all(verbose=True)
