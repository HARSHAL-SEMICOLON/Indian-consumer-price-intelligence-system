"""Data-quality pass over the whole fact table (cheap at this scale, so flags are always
consistent after each incremental load). Records are NEVER deleted: they are flagged,
and `include_in_analysis` decides whether analysis queries use them.
"""
import math
import re
from datetime import datetime, timezone

import pandas as pd

import normalize as N

CHECKS = {
    # name: (description, severity, excludes_from_analysis)
    "missing_price": ("Price field empty although the source reported the row", "high", True),
    "invalid_price": ("Price <= 0 or non-numeric", "high", True),
    "not_reported_by_source": ("DoCA shows '--' for this commodity/date (no price reported)", "info", True),
    "non_inr_currency": ("Currency other than INR", "high", True),
    "out_of_scope_location": ("Observation located outside India / no country", "high", True),
    "out_of_scope_category": ("Product is not a consumer grocery/household/personal-care item (electronics, alcohol)", "medium", True),
    "missing_date": ("No observation date", "high", True),
    "future_date": ("Observation date after collection date", "high", True),
    "exact_duplicate": ("Same product, outlet, date and price already recorded (crowd double submission)", "medium", True),
    "source_marked_duplicate": ("Source API marks the row as duplicate_of another price", "medium", True),
    "price_far_below_product_median": ("Price paid is more than 10x below the median price of the same product (likely typo, e.g. Rs 1 instead of 67)", "high", True),
    "missing_pack_size": ("Pack size/unit unknown -> normalised price not computable", "medium", False),
    "pack_size_from_name": ("Pack size parsed from product name/quantity text, not a structured field", "low", False),
    "quantity_without_unit": ("Quantity text has a number but no unit (e.g. '78.9')", "medium", False),
    "pack_size_name_mismatch": ("Pack size in product name differs from structured quantity by >10%", "medium", False),
    "missing_product_name": ("Product name missing in source", "low", False),
    "missing_brand": ("Brand missing in source", "low", False),
    "brand_alias_mapped": ("Brand spelling standardised via alias table", "info", False),
    "changed_product_name": ("Same barcode/commodity seen with more than one raw name", "low", False),
    "missing_city": ("Indian outlet with no resolvable city", "low", False),
    "discount_without_list_price": ("Marked discounted but pre-discount price missing", "medium", False),
    "invalid_discount": ("Pre-discount price lower than or equal to price paid", "medium", False),
    "implausible_list_price": ("Pre-discount price > 5x price paid (likely entry error) - excluded from discount analysis only", "high", False),
    "normalized_price_outlier": ("Normalised price > 3.5 robust z-scores from its category median (review)", "low", False),
    "provisional_weekend_value": ("DoCA weekend/holiday value - provisional until verified", "info", False),
    "value_revised_by_source": ("Source changed a previously captured value", "info", False),
    "unclassified_category": ("No category tags in source", "low", False),
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_quality(con, run_id):
    fp = pd.read_sql("""
        SELECT f.price_id, s.source_code, f.source_record_id, f.price_paid, f.price_list, f.is_discounted,
               f.currency, f.date_key, f.collection_date_key, f.product_key, f.location_key, f.normalized_price,
               f.pack_size_qty, f.is_provisional, f.revision_count, f.price_type,
               c.category_group, c.category, l.country_code, l.city, p.product_code,
               b.brand_name
        FROM fact_price f JOIN dim_source s USING(source_key) JOIN dim_category c USING(category_key)
        JOIN dim_location l USING(location_key) JOIN dim_product p ON p.product_key=f.product_key
        JOIN dim_brand b ON b.brand_key=f.brand_key""", con)
    stg = pd.read_sql("""SELECT source_code, source_record_id, reported_status, pack_size_source, quantity_text_raw,
                         product_name_raw, brand_rule, src_duplicate_of, qty_std, price_type
                         FROM stg_price_observation WHERE stg_id IN
                         (SELECT MAX(stg_id) FROM stg_price_observation GROUP BY source_code, source_record_id, price_type)""", con)
    stg["rid"] = stg["source_record_id"]
    df = fp.merge(stg.drop(columns=["source_record_id"]), left_on=["source_code", "source_record_id", "price_type"],
                  right_on=["source_code", "rid", "price_type"], how="left")
    flags = {pid: [] for pid in df.price_id}
    details = {}  # (price_id, check) -> (field, observed value) for the issue log

    def flag(mask, name):
        for pid in df.loc[mask.fillna(False), "price_id"]:
            flags[pid].append(name)

    is_op = df.source_code == "OPEN_PRICES"
    not_rep = df.reported_status == "not_reported"
    flag(not_rep, "not_reported_by_source")
    flag(df.price_paid.isna() & ~not_rep, "missing_price")
    flag(df.price_paid.notna() & (df.price_paid <= 0), "invalid_price")
    flag(df.currency.fillna("") != "INR", "non_inr_currency")
    flag(df.country_code.fillna("") != "IN", "out_of_scope_location")
    flag(df.category_group == "Out of scope", "out_of_scope_category")
    flag(df.category_group == "Unclassified", "unclassified_category")
    flag(df.date_key.isna(), "missing_date")
    flag(df.date_key > df.collection_date_key, "future_date")
    flag(is_op & df.src_duplicate_of.notna(), "source_marked_duplicate")
    flag(df.pack_size_qty.isna(), "missing_pack_size")
    flag(df.pack_size_source.fillna("").str.startswith("parsed_"), "pack_size_from_name")
    qt = df.quantity_text_raw.fillna("").astype(str)
    flag(is_op & qt.str.match(r"^\s*\d+(?:[.,]\d+)?\s*$"), "quantity_without_unit")
    flag(is_op & df.product_name_raw.isna(), "missing_product_name")
    flag(is_op & (df.brand_name == "Unknown brand"), "missing_brand")
    flag(is_op & (df.brand_rule == "alias_mapped"), "brand_alias_mapped")
    flag(is_op & df.city.isna() & (df.country_code == "IN"), "missing_city")
    flag((df.is_discounted == 1) & (df.price_list == df.price_paid), "discount_without_list_price")
    flag((df.is_discounted == 1) & (df.price_list < df.price_paid), "invalid_discount")
    flag((df.is_discounted == 1) & (df.price_list > 5 * df.price_paid), "implausible_list_price")
    flag((df.is_provisional == 1), "provisional_weekend_value")
    flag(df.revision_count > 0, "value_revised_by_source")

    # same product, price more than 10x below that product's median price (e.g. "Tahi ayam" Rs 1 vs Rs 67)
    priced = df[df.price_paid.notna() & (df.price_paid > 0)]
    grp = priced.groupby(["source_code", "product_key", "price_type"])["price_paid"]
    med = grp.transform("median")
    cnt = grp.transform("count")
    low = priced[(cnt >= 2) & (priced.price_paid * 10 < med)]
    flag(df.price_id.isin(low.price_id), "price_far_below_product_median")
    for pid, paid, m in zip(low.price_id, low.price_paid, med[low.index]):
        details[(pid, "price_far_below_product_median")] = ("price_paid", f"paid={paid:g} product_median={m:g}")

    # pack size stated in the name vs structured quantity
    def _mismatch(row):
        if row.source_code != "OPEN_PRICES" or not row.qty_std or row.pack_size_source != "api_product_quantity":
            return False
        q, _, _ = N.parse_quantity(row.product_name_raw)
        return bool(q) and abs(q - row.qty_std) / row.qty_std > 0.10
    flag(df.apply(_mismatch, axis=1), "pack_size_name_mismatch")

    # changed product names (same code, >1 raw name across captures)
    multi = pd.read_sql("""SELECT product_key FROM dim_product_name_history GROUP BY product_key
                           HAVING COUNT(DISTINCT product_name_raw) > 1""", con)
    flag(df.product_key.isin(multi.product_key), "changed_product_name")

    # exact duplicates: same product+outlet+date+price -> keep the lowest price_id
    key = ["source_code", "product_key", "location_key", "date_key", "price_paid", "price_type"]
    d = df[df.price_paid.notna()].sort_values("price_id")
    dup_mask = d.duplicated(subset=key, keep="first")
    first_id = d.groupby(key)["price_id"].transform("min")
    dup_of = dict(zip(d.loc[dup_mask, "price_id"], first_id[dup_mask]))
    flag(df.price_id.isin(dup_of.keys()), "exact_duplicate")

    # robust outliers of normalised price within category & unit (Open Prices only)
    op = df[is_op & df.normalized_price.notna() & (df.normalized_price > 0)].copy()
    op["lp"] = op.normalized_price.map(math.log)
    for _, g in op.groupby("category"):
        if len(g) < 5:
            continue
        med = g.lp.median()
        mad = (g.lp - med).abs().median() or 1e-9
        z = 0.6745 * (g.lp - med) / mad
        for pid in g.loc[z.abs() > 3.5, "price_id"]:
            flags[pid].append("normalized_price_outlier")

    now = _now()
    excl = {k for k, v in CHECKS.items() if v[2]}
    con.execute("UPDATE fact_price SET is_duplicate=0, duplicate_of_price_id=NULL")
    rows = []
    for pid, fl in flags.items():
        fl = sorted(set(fl))
        valid = int(not ({"missing_price", "invalid_price", "not_reported_by_source"} & set(fl)))
        include = int(not (excl & set(fl)))
        con.execute("""UPDATE fact_price SET dq_flags=?, is_valid_price=?, include_in_analysis=?,
                       is_duplicate=?, duplicate_of_price_id=? WHERE price_id=?""",
                    (";".join(fl) or None, valid, include, int(pid in dup_of), dup_of.get(pid), pid))
        for f in fl:
            fld, obs = details.get((pid, f), (None, None))
            rows.append((run_id, None, None, pid, f, CHECKS[f][1], fld, obs,
                         "excluded from analysis" if f in excl else "flagged, kept in analysis", None, now))
    # per-record issues (keep the record key for readability)
    rid = dict(zip(df.price_id, df.source_code + ":" + df.source_record_id.astype(str)))
    src = dict(zip(df.price_id, df.source_code))
    con.executemany("""INSERT INTO dq_issue_log(run_id, source_code, record_key, price_id, check_name, severity, field,
                       observed_value, action_taken, capture_file, logged_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [(r[0], src[r[3]], rid[r[3]]) + r[3:] for r in rows])
    # summary table
    for name, (desc, sev, ex) in CHECKS.items():
        for sc in ["OPEN_PRICES", "DOCA_PMD"]:
            n_checked = int((df.source_code == sc).sum())
            n_flag = sum(1 for pid, fl in flags.items() if name in fl and src[pid] == sc)
            con.execute("INSERT OR REPLACE INTO dq_check_summary VALUES (?,?,?,?,?,?,?)",
                        (run_id, name, desc, sc, n_checked, n_flag,
                         "exclude from analysis" if ex else "flag only"))
    return flags
