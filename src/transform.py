"""Parse raw capture files into standardised observation records.

parse_capture(path) -> (records: list[dict], cpi_rows: list[dict], issues: list[dict])

Nothing is dropped here: every raw row becomes a record (or an issue explaining why
it could not be parsed). Filtering for analysis happens later via flags.
"""
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import normalize as N


def _iter_lines(path):
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                yield n, json.loads(line)


def capture_date_from_path(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(path).name)
    return m.group(1)


def _issue(source, key, check, severity, field, value, action, capture):
    return dict(source_code=source, record_key=str(key), check_name=check, severity=severity,
                field=field, observed_value=None if value is None else str(value)[:200],
                action_taken=action, capture_file=capture)


# ============================================================================ OPEN PRICES
def parse_open_prices(path):
    cap = Path(path).name
    cdate = capture_date_from_path(path)
    recs, issues = [], []
    for n, obj in _iter_lines(path):
        body = json.loads(obj["body"]) if "body" in obj else obj  # envelope or bare API page
        for it in body.get("items", []):
            p = it.get("product") or {}
            loc = N.parse_osm_location(it.get("location"))
            rid = it["id"]
            # ---- pack size
            qty = std = None
            pack_src = "missing"
            pq, pqu = p.get("product_quantity"), p.get("product_quantity_unit")
            if pq not in (None, "") and pqu:
                std, f = N.unit_to_std(pqu)
                if std:
                    qty, pack_src = float(pq) * f, "api_product_quantity"
            if qty is None:
                for field in ("quantity", "product_name"):
                    q, s, _ = N.parse_quantity(p.get(field))
                    if q:
                        qty, std, pack_src = q, s, f"parsed_{field}"
                        break
            if it.get("price_per") in ("KILOGRAM", "UNIT"):  # loose-item price already per kg/unit
                qty, std, pack_src = 1.0, ("kg" if it["price_per"] == "KILOGRAM" else "unit"), "price_per_field"
            (cgroup, cat), cat_src = N.off_category(p.get("categories_tags"), p.get("source"))
            brand, brand_rule = N.brand_std(p.get("brands"))
            name_std = N.product_name_std(p.get("product_name"))
            recs.append(dict(
                source_code="OPEN_PRICES", source_record_id=str(rid), capture_file=cap,
                collection_date=cdate, observation_date=it.get("date"),
                price_type="retail", currency=it.get("currency"),
                price=it.get("price"), price_without_discount=it.get("price_without_discount"),
                is_discounted=bool(it.get("price_is_discounted")), discount_type=it.get("discount_type"),
                product_code=it.get("product_code") or (f"CAT:{it.get('category_tag')}" if it.get("category_tag") else None),
                product_name_raw=p.get("product_name"), product_name_std=name_std,
                brand_raw=p.get("brands"), brand_std=brand, brand_rule=brand_rule,
                category_group=cgroup, category=cat, category_rule=cat_src,
                pack_qty_raw=pq, pack_unit_raw=pqu, quantity_text_raw=p.get("quantity"),
                qty_std=qty, std_unit=std, pack_size_source=pack_src,
                location_src_id=str(it.get("location_id")) if it.get("location_id") is not None else None,
                location_level="outlet", country_code=loc["country"], state=loc["state"],
                region=loc["region"], city=loc["city"], city_raw=loc["city_raw"], city_source=loc["city_source"],
                outlet_type=loc["outlet_type"], outlet_name=loc["outlet_name"], lat=loc["lat"], lon=loc["lon"],
                is_provisional=False, reported_status="reported",
                src_duplicate_of=it.get("duplicate_of"), proof_id=it.get("proof_id"),
            ))
    return recs, [], issues


# ============================================================================ DoCA
_VAL_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)")


def _doca_value(cell):
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return None, "missing_cell"
    s = str(cell).strip()
    if s in ("--", "-", "NR", "NA", ""):
        return None, "not_reported"
    m = _VAL_RE.match(s)
    return (float(m.group(1)), "reported") if m else (None, "unparseable")


def parse_doca(path):
    cap = Path(path).name
    cdate = capture_date_from_path(path)
    recs, issues = [], []
    pages = {o["url"].rstrip("/").split("/")[-1].lower(): o for _, o in _iter_lines(path)}
    dash = next((o for k, o in pages.items() if "dbprices" in k), None)
    home = next((o for k, o in pages.items() if "fcainfoweb.nic.in" in k or k == ""), None)

    dash_current = {}
    if dash is not None:
        tables = pd.read_html(io.StringIO(dash["body"]))
        t = max(tables, key=len)
        label_row, date_row = t.iloc[1].tolist(), t.iloc[2].tolist()
        col_dates = {}
        for j in range(2, t.shape[1]):
            try:
                col_dates[j] = (datetime.strptime(str(date_row[j]).strip(), "%d/%m/%Y").date(), str(label_row[j]).strip())
            except ValueError:
                issues.append(_issue("DOCA_PMD", f"col{j}", "unparseable_column_date", "high", "date_header",
                                     date_row[j], "column skipped", cap))
        for i in range(3, len(t)):
            raw_name, raw_unit = str(t.iat[i, 0]).strip(), str(t.iat[i, 1]).strip()
            info = N.doca_commodity(raw_name)
            if info is None:
                issues.append(_issue("DOCA_PMD", raw_name, "unknown_commodity_name", "medium", "commodity",
                                     raw_name, "kept with raw name; add to normalize.DOCA_COMMODITIES", cap))
                info = (raw_name, "Groceries", "Unmapped Commodity")
            std_name, cgroup, cat = info
            qty, std = N.doca_unit(raw_unit)
            if qty is None:
                issues.append(_issue("DOCA_PMD", raw_name, "unparseable_unit", "high", "unit", raw_unit,
                                     "normalised price left NULL", cap))
            for j, (d, label) in col_dates.items():
                val, status = _doca_value(t.iat[i, j])
                rec = dict(
                    source_code="DOCA_PMD", source_record_id=f"{N.commodity_code(std_name)}|{d.isoformat()}|retail",
                    capture_file=cap, collection_date=cdate, observation_date=d.isoformat(),
                    lookback_label=label, price_type="retail", currency="INR",
                    price=val, price_without_discount=None, is_discounted=False, discount_type=None,
                    product_code=N.commodity_code(std_name), product_name_raw=raw_name, product_name_std=std_name,
                    brand_raw=None, brand_std="Unbranded (commodity average)", brand_rule="commodity",
                    category_group=cgroup, category=cat, category_rule="doca_lookup",
                    pack_qty_raw=None, pack_unit_raw=raw_unit, quantity_text_raw=raw_unit,
                    qty_std=qty, std_unit=std, pack_size_source="doca_reporting_unit",
                    location_src_id="ALL_INDIA", location_level="national", country_code="IN", state=None,
                    region="All India", city="All India (average)", city_raw=None, city_source="national",
                    outlet_type="Average of reporting centres", outlet_name=None, lat=None, lon=None,
                    is_provisional=(d.weekday() >= 5 and (date.fromisoformat(cdate) - d).days <= 3),
                    reported_status=status, src_duplicate_of=None, proof_id=None,
                )
                recs.append(rec)
                if label == "Price As On" and val is not None:
                    dash_current[std_name] = (val, d)

    if home is not None:
        tables = pd.read_html(io.StringIO(home["body"]))
        body_txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", home["body"]))
        m_r = re.search(r"All India Average Retail Price\([^)]{0,20}\) As on (\d{2}/\d{2}/\d{4})", body_txt)
        m_w = re.search(r"All India Average Wholesale Price\([^)]{0,20}\) As on (\d{2}/\d{2}/\d{4})", body_txt)
        retail_tabs = [x for x in tables if list(x.columns)[:2] == ["Commodity", "Prices"]]
        # page layout: retail blocks first, then wholesale blocks (wholesale has no 'Additional' block)
        n_ret = 5 if len(retail_tabs) >= 9 else len(retail_tabs) // 2
        ret, whs = retail_tabs[:n_ret], retail_tabs[n_ret:]
        # cross-check: home-page retail vs dashboard 'Price As On'
        for tb in ret:
            for _, r in tb.iterrows():
                info = N.doca_commodity(str(r["Commodity"]))
                if not info:
                    continue
                hv, _ = _doca_value(r["Prices"])
                dv = dash_current.get(info[0])
                if dv and hv is not None and abs(hv - dv[0]) > 0.005:
                    issues.append(_issue("DOCA_PMD", info[0], "home_vs_dashboard_mismatch", "medium", "price",
                                         f"home={hv} dashboard={dv[0]}", "dashboard value kept", cap))
        issues.append(_issue("DOCA_PMD", "home_page_retail_header", "inconsistent_unit_label", "low", "unit",
                             "Home page labels all retail prices '₹/Kg' but dashboard units include 100 gm, 250 gm, "
                             "50 gm, 1 Dozen, 1 Ltr", "dashboard per-commodity unit used for normalisation", cap))
        if m_w and whs:
            wd = datetime.strptime(m_w.group(1), "%d/%m/%Y").date()
            for tb in whs:
                for _, r in tb.iterrows():
                    raw_name = str(r["Commodity"]).strip()
                    info = N.doca_commodity(raw_name) or (raw_name, "Groceries", "Unmapped Commodity")
                    val, status = _doca_value(r["Prices"])
                    is_milk = info[0] == "Milk"
                    recs.append(dict(
                        source_code="DOCA_PMD", source_record_id=f"{N.commodity_code(info[0])}|{wd.isoformat()}|wholesale",
                        capture_file=cap, collection_date=cdate, observation_date=wd.isoformat(),
                        lookback_label="Wholesale As On", price_type="wholesale", currency="INR",
                        price=val, price_without_discount=None, is_discounted=False, discount_type=None,
                        product_code=N.commodity_code(info[0]), product_name_raw=raw_name, product_name_std=info[0],
                        brand_raw=None, brand_std="Unbranded (commodity average)", brand_rule="commodity",
                        category_group=info[1], category=info[2], category_rule="doca_lookup",
                        pack_qty_raw=None, pack_unit_raw="1 Quintal" + (" (assumed 100 l for milk)" if is_milk else ""),
                        quantity_text_raw="Rs/Qtl", qty_std=100.0, std_unit=("l" if is_milk else "kg"),
                        pack_size_source="doca_wholesale_quintal",
                        location_src_id="ALL_INDIA", location_level="national", country_code="IN", state=None,
                        region="All India", city="All India (average)", city_raw=None, city_source="national",
                        outlet_type="Average of reporting centres", outlet_name=None, lat=None, lon=None,
                        is_provisional=(wd.weekday() >= 5), reported_status=status,
                        src_duplicate_of=None, proof_id=None, lookback_label_extra=None,
                    ))
                    if is_milk:
                        issues.append(_issue("DOCA_PMD", recs[-1]["source_record_id"], "ambiguous_wholesale_unit",
                                             "low", "unit", "Milk wholesale quoted per quintal",
                                             "treated as 100 litres; flagged", cap))
    for r in recs:
        r.pop("lookback_label_extra", None)
    return recs, [], issues


# ============================================================================ MoSPI CPI
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                       "August", "September", "October", "November", "December"], 1)}


def parse_cpi(path):
    cap = Path(path).name
    rows, issues, seen = [], [], set()
    for n, env in _iter_lines(path):
        body = json.loads(env["body"])
        kind = env.get("kind") or ("item" if "getItemIndex" in env["url"] else "group_allindia")
        kind = "item" if kind.startswith("item") else "group_allindia"   # '_backfill' captures -> same series
        for d in body.get("data", []):
            idx = d.get("index")
            try:
                idx_f = float(idx)
            except (TypeError, ValueError):
                idx_f = None
                issues.append(_issue("MOSPI_CPI", f"{d.get('item') or d.get('subgroup')}|{d.get('year')}|{d.get('month')}|{d.get('sector', '')}",
                                     "non_numeric_index", "low", "index", idx, "index stored as NULL (not published for this month)", cap))
            infl = d.get("inflation")
            try:
                infl_f = float(infl)
            except (TypeError, ValueError):
                infl_f = None
            k = (kind, d.get("group"), d.get("item") or d.get("subgroup"), d.get("sector"), d.get("year"), d.get("month"))
            if k in seen:
                issues.append(_issue("MOSPI_CPI", "|".join(map(str, k)), "api_pagination_duplicate", "low", "row",
                                     None, "duplicate row from unstable API paging ignored (first copy kept)", cap))
                continue
            seen.add(k)
            rows.append(dict(
                series_kind=kind, base_year=int(d.get("baseyear")), year=int(d["year"]),
                month=MONTHS.get(d["month"]), state=d.get("state", "All India"),
                sector=d.get("sector", "Combined"), cpi_group=d.get("group"),
                cpi_item=d.get("item") or d.get("subgroup"), index_value=idx_f, yoy_inflation_pct=infl_f,
                status=d.get("status"), capture_file=cap,
            ))
    return [], rows, issues


def parse_capture(path):
    p = str(path)
    if "open_prices" in p:
        return parse_open_prices(path)
    if "doca_dashboard" in p:
        return parse_doca(path)
    if "mospi_cpi" in p:
        return parse_cpi(path)
    raise ValueError(f"Unknown source for {path}")
