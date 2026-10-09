"""Incremental loader: raw captures -> staging -> star schema, then data-quality pass.

Only raw files whose SHA-256 is not yet in etl_raw_file are parsed, so adding a new
collection date appends to the database instead of rebuilding it.
"""
import hashlib
import sqlite3
from datetime import date, datetime, timezone

import pandas as pd

from config import DB_PATH, RAW, ROOT, SOURCES, SCHEMA_SQL
import transform as T
import quality as Q

STG_COLS = [
    "source_code", "source_record_id", "capture_file", "collection_date", "observation_date", "lookback_label",
    "price_type", "currency", "price", "price_without_discount", "is_discounted", "discount_type",
    "product_code", "product_name_raw", "product_name_std", "brand_raw", "brand_std", "brand_rule",
    "category_group", "category", "category_rule", "pack_qty_raw", "pack_unit_raw", "quantity_text_raw",
    "qty_std", "std_unit", "pack_size_source", "location_src_id", "location_level", "country_code", "state",
    "region", "city", "city_raw", "city_source", "outlet_type", "outlet_name", "lat", "lon",
    "is_provisional", "reported_status", "src_duplicate_of", "proof_id",
]
OUT_OF_SCOPE = {"Electronics", "Alcohol"}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    for code, s in SOURCES.items():
        con.execute("""INSERT INTO dim_source(source_code, source_name, publisher, base_url, extraction_method,
                       licence, granularity, data_role, limitations) VALUES (?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_code) DO UPDATE SET source_name=excluded.source_name,
                       publisher=excluded.publisher, base_url=excluded.base_url,
                       extraction_method=excluded.extraction_method, licence=excluded.licence,
                       granularity=excluded.granularity, data_role=excluded.data_role,
                       limitations=excluded.limitations""",
                    (code, s["source_name"], s["publisher"], s["base_url"], s["extraction_method"],
                     s["licence"], s["granularity"], s["data_role"], s["limitations"]))
    return con


# ----------------------------------------------------------------------------- dimension helpers
def date_key(con, iso):
    if not iso:
        return None
    d = date.fromisoformat(str(iso)[:10])
    k = int(d.strftime("%Y%m%d"))
    con.execute("""INSERT OR IGNORE INTO dim_date VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (k, d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month, d.strftime("%B"),
                 d.strftime("%Y-%m"), d.isocalendar()[1], d.day, d.strftime("%A"), int(d.weekday() >= 5)))
    return k


def fill_date_range(con):
    """Make dim_date a continuous calendar (needed for Power BI time intelligence)."""
    lo, hi = con.execute("SELECT MIN(full_date), MAX(full_date) FROM dim_date").fetchone()
    if not lo:
        return
    lo = date(date.fromisoformat(lo).year, 1, 1)
    hi = date(date.fromisoformat(hi).year, 12, 31)
    for d in pd.date_range(lo, hi, freq="D"):
        date_key(con, d.date().isoformat())


def get_or_create(con, table, keycols, keyvals, extra=None):
    where = " AND ".join(f"{c} IS ?" for c in keycols)
    pk = {"dim_brand": "brand_key", "dim_category": "category_key", "dim_location": "location_key",
          "dim_product": "product_key", "dim_cpi_item": "cpi_item_key"}[table]
    row = con.execute(f"SELECT {pk} FROM {table} WHERE {where}", keyvals).fetchone()
    if row:
        return row[0]
    cols = list(keycols) + list((extra or {}).keys())
    vals = list(keyvals) + list((extra or {}).values())
    cur = con.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    return cur.lastrowid


def pack_label(qty, unit, raw_unit=None, raw_qty=None):
    if raw_unit and raw_qty in (None, ""):
        return raw_unit
    if qty is None or unit is None:
        return None
    if unit == "kg":
        return f"{qty * 1000:g} g" if qty < 1 else f"{qty:g} kg"
    if unit == "l":
        return f"{qty * 1000:g} ml" if qty < 1 else f"{qty:g} l"
    return f"{qty:g} unit(s)"


# ----------------------------------------------------------------------------- loading
def register_files(con, run_id, rebuild=False):
    files = sorted(p for p in RAW.rglob("*.jsonl"))  # rglob follows the source/date sub-folders
    new = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        h = sha256(p)
        known = con.execute("SELECT sha256 FROM etl_raw_file WHERE relative_path=?", (rel,)).fetchone()
        if known and known[0] != h:
            raise RuntimeError(f"RAW FILE MODIFIED after loading: {rel}. Raw files are immutable - restore it.")
        if known:
            continue
        if con.execute("SELECT 1 FROM etl_raw_file WHERE sha256=?", (h,)).fetchone():
            print(f"  skip {rel}: identical bytes already loaded under another name")
            continue
        new.append((p, rel, h))
    return new


def load_capture(con, run_id, path, rel, h):
    recs, cpi_rows, issues = T.parse_capture(path)
    source = "MOSPI_CPI" if cpi_rows else (recs[0]["source_code"] if recs else "UNKNOWN")
    cur = con.execute("""INSERT INTO etl_raw_file(source_code, relative_path, sha256, bytes, collection_date,
                         records_parsed, loaded_at_utc, run_id) VALUES (?,?,?,?,?,?,?,?)""",
                      (source, rel, h, path.stat().st_size, T.capture_date_from_path(path),
                       len(recs) + len(cpi_rows), utcnow(), run_id))
    raw_id = cur.lastrowid
    for i in issues:
        con.execute("""INSERT INTO dq_issue_log(run_id, source_code, record_key, check_name, severity, field,
                       observed_value, action_taken, capture_file, logged_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, i["source_code"], i["record_key"], i["check_name"], i["severity"], i["field"],
                     i["observed_value"], i["action_taken"], i["capture_file"], utcnow()))
    new_rows = upd_rows = 0
    if recs:
        df = pd.DataFrame(recs).reindex(columns=STG_COLS)
        df.insert(0, "raw_file_id", raw_id)
        df.astype(object).where(df.notna(), None).to_sql("stg_price_observation", con, if_exists="append", index=False)
        n, u = load_prices(con, recs)
        new_rows += n
        upd_rows += u
    if cpi_rows:
        load_cpi(con, cpi_rows)
    return new_rows, upd_rows


def load_prices(con, recs):
    src_keys = dict(con.execute("SELECT source_code, source_key FROM dim_source").fetchall())
    new_rows = upd = 0
    now = utcnow()
    for r in recs:
        sk = src_keys[r["source_code"]]
        branded = r["brand_rule"] != "commodity"
        brand_name = r["brand_std"] or ("Unknown brand" if branded else "Unbranded (commodity average)")
        bk = get_or_create(con, "dim_brand", ["brand_name"], [brand_name], {"is_branded": int(branded and r["brand_std"] is not None)})
        if r["brand_raw"]:
            con.execute("INSERT OR IGNORE INTO dim_brand_alias VALUES (?,?,?)", (r["brand_raw"], bk, r["brand_rule"]))
        ck = get_or_create(con, "dim_category", ["category_group", "category"], [r["category_group"], r["category"]],
                           {"in_scope": int(r["category_group"] not in ("Out of scope", "Unclassified"))})
        lk = get_or_create(con, "dim_location", ["source_code", "location_src_id"],
                           [r["source_code"], r["location_src_id"] or "UNKNOWN"],
                           {"location_level": r["location_level"], "outlet_name": r["outlet_name"],
                            "outlet_type": r["outlet_type"], "city": r["city"], "state": r["state"],
                            "region": r["region"], "country_code": r["country_code"], "latitude": r["lat"],
                            "longitude": r["lon"], "city_source": r["city_source"]})
        pcode = r["product_code"] or f"NOCODE:{r['source_record_id']}"
        pk = get_or_create(con, "dim_product", ["source_code", "product_code"], [r["source_code"], pcode],
                           {"product_name": r["product_name_std"], "brand_key": bk, "category_key": ck,
                            "pack_size_qty": r["qty_std"], "std_unit": r["std_unit"],
                            "pack_size_label": pack_label(r["qty_std"], r["std_unit"],
                                                          r["pack_unit_raw"] if r["source_code"] == "DOCA_PMD" else None),
                            "pack_size_source": r["pack_size_source"],
                            "product_type": "Branded product" if branded else "Commodity average",
                            "first_seen_date": r["observation_date"], "last_seen_date": r["observation_date"]})
        if r["price_type"] == "retail":  # wholesale quintal unit must not overwrite the retail pack size
            con.execute("""UPDATE dim_product SET
                   product_name = COALESCE(?, product_name),
                   pack_size_qty = COALESCE(pack_size_qty, ?), std_unit = COALESCE(std_unit, ?),
                   first_seen_date = MIN(COALESCE(first_seen_date, ?), ?),
                   last_seen_date  = MAX(COALESCE(last_seen_date, ?), ?)
                   WHERE product_key = ?""",
                        (r["product_name_std"], r["qty_std"], r["std_unit"], r["observation_date"],
                         r["observation_date"], r["observation_date"], r["observation_date"], pk))
        if r["product_name_raw"]:
            con.execute("""INSERT INTO dim_product_name_history VALUES (?,?,?,?)
                           ON CONFLICT(product_key, product_name_raw) DO UPDATE SET last_capture=excluded.last_capture""",
                        (pk, r["product_name_raw"], r["capture_file"], r["capture_file"]))
        dk = date_key(con, r["observation_date"])
        cdk = date_key(con, r["collection_date"])

        price = r["price"]
        plist = r["price_without_discount"] if (r["is_discounted"] and r["price_without_discount"]) else price
        qty = r["qty_std"]
        unit = {"kg": "INR/kg", "l": "INR/l", "unit": "INR/unit"}.get(r["std_unit"])
        norm = (price / qty) if (price is not None and qty) else None
        norm_list = (plist / qty) if (plist is not None and qty) else None
        disc_amt = (plist - price) if (r["is_discounted"] and plist is not None and price is not None) else 0.0
        disc_pct = (disc_amt / plist * 100) if (plist and disc_amt) else 0.0

        existing = con.execute("SELECT price_id, price_paid FROM fact_price WHERE source_key=? AND source_record_id=?",
                               (sk, r["source_record_id"])).fetchone()
        vals = dict(date_key=dk, collection_date_key=cdk, product_key=pk, brand_key=bk, category_key=ck,
                    location_key=lk, price_type=r["price_type"], currency=r["currency"], price_paid=price,
                    price_list=plist, discount_amount=disc_amt, discount_pct=disc_pct,
                    is_discounted=int(bool(r["is_discounted"])), discount_type=r["discount_type"],
                    pack_size_qty=qty, std_unit=r["std_unit"], normalized_price=norm,
                    normalized_list_price=norm_list, normalized_unit=unit, lookback_label=r.get("lookback_label"),
                    is_provisional=int(bool(r["is_provisional"])))
        if existing:
            pid, old = existing
            if old is not None and price is not None and abs(old - price) > 1e-9:
                con.execute("INSERT INTO fact_price_revision VALUES (?,?,?,?,?,?)",
                            (pid, old, price, None, r["capture_file"], now))
                con.execute("UPDATE fact_price SET revision_count = revision_count + 1 WHERE price_id=?", (pid,))
            if price is None and old is not None:
                continue  # never overwrite a reported value with a later blank
            sets = ", ".join(f"{k}=?" for k in vals)
            con.execute(f"UPDATE fact_price SET {sets}, last_updated_utc=? WHERE price_id=?",
                        list(vals.values()) + [now, pid])
            upd += 1
        else:
            cols = ["source_key", "source_record_id"] + list(vals) + ["first_loaded_utc", "last_updated_utc"]
            con.execute(f"INSERT INTO fact_price({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [sk, r["source_record_id"]] + list(vals.values()) + [now, now])
            new_rows += 1
        if r["source_code"] == "DOCA_PMD":
            con.execute("""INSERT INTO fact_availability(source_key, product_key, location_key, date_key,
                           collection_date_key, price_type, availability_status, is_available)
                           VALUES (?,?,?,?,?,?,?,?)
                           ON CONFLICT(source_key, product_key, location_key, date_key, price_type)
                           DO UPDATE SET availability_status=CASE WHEN excluded.is_available=1 THEN excluded.availability_status
                                         ELSE availability_status END,
                                         is_available=MAX(is_available, excluded.is_available),
                                         collection_date_key=excluded.collection_date_key""",
                        (sk, pk, lk, dk, cdk, r["price_type"], r["reported_status"],
                         int(r["reported_status"] == "reported")))
    return new_rows, upd


def load_cpi(con, rows):
    for r in rows:
        ik = get_or_create(con, "dim_cpi_item", ["series_kind", "cpi_group", "cpi_item", "sector"],
                           [r["series_kind"], r["cpi_group"], r["cpi_item"], r["sector"]])
        dk = date_key(con, f"{r['year']:04d}-{r['month']:02d}-01")
        con.execute("""INSERT INTO fact_cpi_benchmark VALUES (?,?,?,?,?,?,?)
                       ON CONFLICT(cpi_item_key, date_key, base_year) DO UPDATE SET index_value=excluded.index_value,
                       yoy_inflation_pct=excluded.yoy_inflation_pct, status=excluded.status,
                       capture_file=excluded.capture_file""",
                    (ik, dk, r["base_year"], r["index_value"], r["yoy_inflation_pct"], r["status"], r["capture_file"]))


def finalize_availability(con):
    """A 'not_reported' DoCA point that precedes the commodity's first reported value
    means the series had not started yet - not that the product was unavailable."""
    con.execute("""
        UPDATE fact_availability SET availability_status='not_yet_tracked'
        WHERE is_available=0 AND date_key < (
            SELECT MIN(a2.date_key) FROM fact_availability a2
            WHERE a2.product_key=fact_availability.product_key AND a2.location_key=fact_availability.location_key
              AND a2.price_type=fact_availability.price_type AND a2.is_available=1)""")


CPI_BRIDGE = {  # DoCA commodity -> exact MoSPI item label (base 2012), match quality
    "Rice": [("Rice – Other Sources", "close")],
    "Wheat": [("Wheat/ Atta – Other Sources", "approximate")],
    "Atta (Wheat)": [("Wheat/ Atta – Other Sources", "close")],
    "Maida (Wheat)": [("Maida", "close")],
    "Suji": [("Suji, Rawa", "close")],
    "Bajra": [("Bajra & its Products", "close")],
    "Jowar": [("Jowar & its Products", "close")],
    "Ragi": [("Ragi & its Products", "close")],
    "Gram Dal": [("Gram: Split", "close")],
    "Tur/Arhar Dal": [("Arhar, Tur", "close")],
    "Urad Dal": [("Urd", "close")],
    "Moong Dal": [("Moong", "close")],
    "Masoor Dal": [("Masur", "close")],
    "Besan": [("Besan", "close")],
    "Sugar": [("Sugar - Other Sources", "close")],
    "Gur": [("Gur", "close")],
    "Milk": [("Milk: Liquid (litre)", "close")],
    "Groundnut Oil (Packed)": [("Groundnut Oil", "close")],
    "Mustard Oil (Packed)": [("Mustard Oil", "close")],
    "Vanaspati (Packed)": [("Vanaspati, Margarine", "close")],
    "Sunflower Oil (Packed)": [("Refined Oil [sunflower, Soyabean, Saffola, Etc.]", "approximate")],
    "Soya Oil (Packed)": [("Refined Oil [sunflower, Soyabean, Saffola, Etc.]", "approximate")],
    "Desi Ghee": [("Ghee", "close")],
    "Butter (Pasteurised)": [("Butter", "close")],
    "Eggs": [("Eggs (no.)", "close")],
    "Potato": [("Potato", "close")],
    "Onion": [("Onion", "close")],
    "Tomato": [("Tomato", "close")],
    "Brinjal": [("Brinjal", "close")],
    "Ginger": [("Ginger (gm)", "close")],
    "Garlic": [("Garlic (gm)", "close")],
    "Banana": [("Banana (no.)", "close")],
    "Tea (Loose)": [("Tea: Leaf (gm)", "close")],
    "Salt (Iodised, Packed)": [("Salt", "close")],
    "Black Pepper": [("Black Pepper (gm)", "close")],
    "Coriander (Whole)": [("Dhania (gm)", "close")],
    "Cumin Seed": [("Jeera (gm)", "close")],
    "Red Chillies (Whole)": [("Dry Chillies (gm)", "close")],
    "Turmeric (Powder)": [("Turmeric (gm)", "close")],
}


def build_cpi_bridge(con):
    items = {}
    for k, name in con.execute("SELECT cpi_item_key, cpi_item FROM dim_cpi_item WHERE series_kind='item'"):
        items[name.strip().lower()] = k
    missing = []
    for pk, pname in con.execute("SELECT product_key, product_name FROM dim_product WHERE source_code='DOCA_PMD'").fetchall():
        for cpi_name, q in CPI_BRIDGE.get(pname, []):
            k = items.get(cpi_name.lower())
            if k:
                con.execute("INSERT OR IGNORE INTO bridge_commodity_cpi VALUES (?,?,?)", (pk, k, q))
            else:
                missing.append((pname, cpi_name))
    return missing


def run(rebuild=False):
    if rebuild and DB_PATH.exists():
        DB_PATH.unlink()
    con = connect()
    run_id = con.execute("INSERT INTO etl_run(started_utc) VALUES (?)", (utcnow(),)).lastrowid
    new_files = register_files(con, run_id)
    tot_new = tot_upd = 0
    for p, rel, h in new_files:
        n, u = load_capture(con, run_id, p, rel, h)
        print(f"  loaded {rel}: +{n} new fact rows, {u} updated")
        tot_new += n
        tot_upd += u
    finalize_availability(con)
    fill_date_range(con)
    missing = build_cpi_bridge(con) if con.execute("SELECT COUNT(*) FROM dim_cpi_item").fetchone()[0] else []
    Q.run_quality(con, run_id)
    con.execute("UPDATE etl_run SET finished_utc=?, new_files=?, new_fact_rows=?, updated_fact_rows=?, notes=? WHERE run_id=?",
                (utcnow(), len(new_files), tot_new, tot_upd,
                 ("unmapped CPI bridge: " + "; ".join(f"{a}->{b}" for a, b in missing)) if missing else None, run_id))
    con.commit()
    con.close()
    return run_id, len(new_files), tot_new, tot_upd, missing
