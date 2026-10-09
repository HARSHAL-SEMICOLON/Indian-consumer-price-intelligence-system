"""Generate the Power BI project (PBIP) for Indian Consumer Price Intelligence.

    python powerbi/generate_powerbi_project.py

Output: powerbi/ConsumerPrice_Dashboard/
    ConsumerPrice.pbip               <- double-click to open in Power BI Desktop
    ConsumerPrice.SemanticModel/     <- TMDL model: CSV import tables, relationships, DAX measures
    ConsumerPrice.Report/            <- PBIR report: 7 pages, one JSON file per visual

The model reads powerbi/data/*.csv through the parameter `DataFolder`
(Power BI Desktop: Transform data > Edit parameters) - change it if the project moves.
After `python run_pipeline.py --extract`, just click Refresh in Power BI.
Format matches Power BI Desktop 2.158 (Sep 2026) with PBIR + TMDL preview features on.
"""
import json
import shutil
import uuid
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV_DIR = ROOT / "powerbi" / "data"
PBI_DIR = ROOT / "powerbi"
OUT = PBI_DIR / "ConsumerPrice_Dashboard"
NAME = "ConsumerPrice"
DEFAULT_DATA_FOLDER = r"E:\DA PROJECTS\Indian Consumer Price Intelligence\powerbi\data"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
THEME_FILE, THEME_NAME = "Report_Theme_Purple.json", "ConsumerPurple.json"
NS = uuid.UUID("2b4d8e10-7c55-4e8a-9b1f-5a6c7d8e9f01")          # stable GUIDs across rebuilds


def gid(*parts):
    return str(uuid.uuid5(NS, "|".join(parts)))


# =============================================================================
# 1. SEMANTIC MODEL
# =============================================================================
TABLES = [
    "dim_date", "dim_product", "dim_brand", "dim_category", "dim_location", "dim_source",
    "dim_cpi_item", "bridge_commodity_cpi",
    "fact_price", "fact_availability", "fact_cpi_benchmark",
    "dq_check_summary", "dq_issue_log", "etl_raw_file", "etl_run",
    "price_spikes", "history_depth",          # page 7 price-spike monitor (standalone tables)
]
DATE_COLS = {"full_date", "first_seen_date", "last_seen_date", "month_start", "collection_date"}
DATE_KEY_COL = "full_date"
TEXT_OVERRIDE = {("etl_run", "notes")}
KEY_COLS = {"price_id", "duplicate_of_price_id"}
SORT_BY = {("dim_date", "month_name"): "month"}
# Fixed types for the spike tables: they are empty until daily history exists, so types can't be inferred.
COL_TYPES = {
    **{("price_spikes", c): "double" for c in ("prev_price", "price", "pct_change", "normal_change", "sd_change", "z_score")},
    **{("price_spikes", c): "int64" for c in ("is_this_week", "n_steps")},
    **{("price_spikes", c): "dateTime" for c in ("obs_date", "prev_date")},
    **{("history_depth", c): "int64" for c in ("dated_points", "daily_steps")},
    **{("history_depth", c): "dateTime" for c in ("first_date", "last_date")},
}

RELATIONSHIPS = [  # (from table, from col, to table, to col, active)
    ("fact_price", "date_key", "dim_date", "date_key", True),
    ("fact_price", "collection_date_key", "dim_date", "date_key", False),
    ("fact_price", "product_key", "dim_product", "product_key", True),
    ("fact_price", "brand_key", "dim_brand", "brand_key", True),
    ("fact_price", "category_key", "dim_category", "category_key", True),
    ("fact_price", "location_key", "dim_location", "location_key", True),
    ("fact_price", "source_key", "dim_source", "source_key", True),
    ("fact_availability", "date_key", "dim_date", "date_key", True),
    ("fact_availability", "product_key", "dim_product", "product_key", True),
    ("fact_availability", "location_key", "dim_location", "location_key", True),
    ("fact_cpi_benchmark", "date_key", "dim_date", "date_key", True),
    ("fact_cpi_benchmark", "cpi_item_key", "dim_cpi_item", "cpi_item_key", True),
    ("bridge_commodity_cpi", "cpi_item_key", "dim_cpi_item", "cpi_item_key", True),
]

# ---- DAX measures: (name, expression, formatString, folder) --------------------------------
# From powerbi/DAX_MEASURES.md, with three fixes noted inline.
PCT, NUM2, INT, INR, TXT = "0.0%", "#,0.00", "#,0", "₹ #,0.00", None
EXCL_IMPLAUSIBLE = 'NOT CONTAINSSTRING ( fact_price[dq_flags] & "", "implausible_list_price" )'
MEASURES = [
    # ---------- core
    ("Observations", "COUNTROWS ( fact_price )", INT, "1 Core"),
    ("Avg Normalized Price", "AVERAGE ( fact_price[normalized_price] )", INR, "1 Core"),
    ("Median Normalized Price", "MEDIAN ( fact_price[normalized_price] )", INR, "1 Core"),
    ("Min Normalized Price", "MIN ( fact_price[normalized_price] )", INR, "1 Core"),
    ("Max Normalized Price", "MAX ( fact_price[normalized_price] )", INR, "1 Core"),
    ("Distinct Products", "DISTINCTCOUNT ( fact_price[product_key] )", INT, "1 Core"),
    ("Commodities Tracked", 'CALCULATE ( DISTINCTCOUNT ( fact_price[product_key] ), dim_source[source_code] = "DOCA_PMD" )', INT, "1 Core"),
    ("Branded Products Observed", 'CALCULATE ( DISTINCTCOUNT ( fact_price[product_key] ), dim_source[source_code] = "OPEN_PRICES" )', INT, "1 Core"),
    ("Cities Covered", 'CALCULATE ( COUNTROWS ( FILTER ( SUMMARIZE ( fact_price, dim_location[city] ), NOT ISBLANK ( dim_location[city] ) ) ), dim_location[location_level] = "outlet" )', INT, "1 Core"),
    # FIX 4: read the collection date from the fact table (MAX over dim_date returned the calendar's last day)
    ("Latest Collection Date", """VAR k = MAX ( fact_price[collection_date_key] )
RETURN IF ( NOT ISBLANK ( k ), DATE ( INT ( k / 10000 ), MOD ( INT ( k / 100 ), 100 ), MOD ( k, 100 ) ) )""", "dd-mmm-yyyy", "1 Core"),
    # ---------- time comparisons (DoCA: latest observation vs look-back observation)
    ("Latest Obs Date", "CALCULATE ( MAX ( fact_price[date_key] ), REMOVEFILTERS ( dim_date ) )", "0", "2 Time comparisons"),
    ("Price Latest", """VAR d = [Latest Obs Date]
RETURN CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ), fact_price[date_key] = d )""", INR, "2 Time comparisons"),
    # FIX 5: build the date arithmetically and skip rows with no price
    # (DATEVALUE(FORMAT(blank)) raised an error that broke every YoY/MoM visual).
    ("Price 1M Ago", """VAR k = [Latest Obs Date]
VAR t = IF ( NOT ISBLANK ( k ), EDATE ( DATE ( INT ( k / 10000 ), MOD ( INT ( k / 100 ), 100 ), MOD ( k, 100 ) ), -1 ) )
RETURN IF ( NOT ISBLANK ( t ), CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ),
    dim_date[full_date] >= t - 7, dim_date[full_date] <= t ) )""", INR, "2 Time comparisons"),
    ("Price 1Y Ago", """VAR k = [Latest Obs Date]
VAR t = IF ( NOT ISBLANK ( k ), EDATE ( DATE ( INT ( k / 10000 ), MOD ( INT ( k / 100 ), 100 ), MOD ( k, 100 ) ), -12 ) )
RETURN IF ( NOT ISBLANK ( t ), CALCULATE ( [Avg Normalized Price], REMOVEFILTERS ( dim_date ),
    dim_date[full_date] >= t - 7, dim_date[full_date] <= t ) )""", INR, "2 Time comparisons"),
    ("MoM Change %", "DIVIDE ( [Price Latest] - [Price 1M Ago], [Price 1M Ago] )", PCT, "2 Time comparisons"),
    ("YoY Change %", "DIVIDE ( [Price Latest] - [Price 1Y Ago], [Price 1Y Ago] )", PCT, "2 Time comparisons"),
    # FIX 1: the DoCA/retail filter is applied while each product's change is evaluated
    # (originally it only restricted the product list, so wholesale prices leaked in).
    ("Avg YoY Change % (DoCA)", """AVERAGEX ( VALUES ( dim_product[product_key] ),
    CALCULATE ( [YoY Change %], dim_source[source_code] = "DOCA_PMD", fact_price[price_type] = "retail" ) )""",
     PCT, "2 Time comparisons"),
    ("Avg MoM Change % (DoCA)", """AVERAGEX ( VALUES ( dim_product[product_key] ),
    CALCULATE ( [MoM Change %], dim_source[source_code] = "DOCA_PMD", fact_price[price_type] = "retail" ) )""",
     PCT, "2 Time comparisons"),
    ("Price CV %", "DIVIDE ( STDEVX.P ( fact_price, fact_price[normalized_price] ), [Avg Normalized Price] )", PCT, "2 Time comparisons"),
    # CPI benchmark for the commodity selected (through the bridge; CPI stays a separate methodology)
    ("CPI Index (mapped item)", """VAR items =
    CALCULATETABLE ( VALUES ( bridge_commodity_cpi[cpi_item_key] ),
        TREATAS ( VALUES ( dim_product[product_key] ), bridge_commodity_cpi[product_key] ) )
RETURN CALCULATE ( AVERAGE ( fact_cpi_benchmark[index_value] ), TREATAS ( items, fact_cpi_benchmark[cpi_item_key] ) )""",
     "0.0", "2 Time comparisons"),
    # ---------- brands
    ("Brands in Selection", "DISTINCTCOUNT ( fact_price[brand_key] )", INT, "3 Brands"),
    ("Sample Flag", 'IF ( [Observations] >= 3, "ok", "low sample (<3 obs)" )', TXT, "3 Brands"),
    # ---------- locations
    ("Cities for Product", "COUNTROWS ( FILTER ( SUMMARIZE ( fact_price, dim_location[city] ), NOT ISBLANK ( dim_location[city] ) ) )", INT, "4 Locations"),
    ("Min Pack Price", "MIN ( fact_price[price_paid] )", INR, "4 Locations"),
    ("Max Pack Price", "MAX ( fact_price[price_paid] )", INR, "4 Locations"),
    ("Location Spread %", "DIVIDE ( [Max Pack Price] - [Min Pack Price], [Min Pack Price] )", PCT, "4 Locations"),
    ("City Price Index", """VAR t =
    ADDCOLUMNS (
        fact_price,
        "@ref", CALCULATE ( AVERAGE ( fact_price[normalized_price] ), ALLEXCEPT ( fact_price, fact_price[product_key] ) ),
        "@cities", CALCULATE ( COUNTROWS ( FILTER ( SUMMARIZE ( fact_price, dim_location[city] ), NOT ISBLANK ( dim_location[city] ) ) ), ALLEXCEPT ( fact_price, fact_price[product_key] ) )
    )
RETURN IF ( NOT ISBLANK ( SELECTEDVALUE ( dim_location[city] ) ), 100 * AVERAGEX ( FILTER ( t, [@cities] >= 2 && NOT ISBLANK ( fact_price[normalized_price] ) ),
    DIVIDE ( fact_price[normalized_price], [@ref] ) ) )""", "0.0", "4 Locations"),
    # FIX 2: a measure cannot sit inside a CALCULATE column filter - capture it in a variable first.
    ("Retail Markup over Wholesale %", """VAR d = [Latest Obs Date]
VAR r = CALCULATE ( [Avg Normalized Price], fact_price[price_type] = "retail", fact_price[date_key] = d )
VAR w = CALCULATE ( [Avg Normalized Price], fact_price[price_type] = "wholesale" )
RETURN DIVIDE ( r - w, w )""", PCT, "4 Locations"),
    # ---------- discounts (exclude implausible list prices)
    ("% Observations Discounted", f"""DIVIDE (
    CALCULATE ( COUNTROWS ( fact_price ), fact_price[is_discounted] = 1, {EXCL_IMPLAUSIBLE} ),
    CALCULATE ( COUNTROWS ( fact_price ), {EXCL_IMPLAUSIBLE} ) )""", PCT, "5 Discounts & availability"),
    ("Avg Discount % (when discounted)", f"""CALCULATE ( AVERAGE ( fact_price[discount_pct] ) / 100, fact_price[is_discounted] = 1,
    FILTER ( fact_price, fact_price[price_list] > fact_price[price_paid] ), {EXCL_IMPLAUSIBLE} )""",
     PCT, "5 Discounts & availability"),
    ("Total Savings INR", f"""CALCULATE ( SUMX ( fact_price, fact_price[price_list] - fact_price[price_paid] ),
    fact_price[is_discounted] = 1, {EXCL_IMPLAUSIBLE} )""", "₹ #,0", "5 Discounts & availability"),
    ("Avg Normalized List Price", f"""CALCULATE ( AVERAGE ( fact_price[normalized_list_price] ), fact_price[is_discounted] = 1,
    {EXCL_IMPLAUSIBLE} )""", INR, "5 Discounts & availability"),
    ("Avg Normalized Effective Price", f"""CALCULATE ( AVERAGE ( fact_price[normalized_price] ), fact_price[is_discounted] = 1,
    {EXCL_IMPLAUSIBLE} )""", INR, "5 Discounts & availability"),
    ("Availability Status", "SELECTEDVALUE ( fact_availability[availability_status] )", TXT, "5 Discounts & availability"),
    ("Not Reported Gap Rate %", """DIVIDE (
    CALCULATE ( COUNTROWS ( fact_availability ), fact_availability[availability_status] = "not_reported" ),
    CALCULATE ( COUNTROWS ( fact_availability ), fact_availability[availability_status] <> "not_yet_tracked" ) ) + 0""",
     PCT, "5 Discounts & availability"),
    # ---------- data quality (page 6 has no include_in_analysis filter)
    ("Total Raw Records", "COUNTROWS ( fact_price )", INT, "6 Data quality"),
    ("Records Included", "CALCULATE ( COUNTROWS ( fact_price ), fact_price[include_in_analysis] = 1 )", INT, "6 Data quality"),
    ("Records Excluded", "CALCULATE ( COUNTROWS ( fact_price ), fact_price[include_in_analysis] = 0 ) + 0", INT, "6 Data quality"),
    ("Records Flagged", "CALCULATE ( COUNTROWS ( fact_price ), NOT ISBLANK ( fact_price[dq_flags] ) ) + 0", INT, "6 Data quality"),
    ("% Usable", "DIVIDE ( [Records Included], [Total Raw Records] )", PCT, "6 Data quality"),
    ("Rows Flagged (checks)", "SUM ( dq_check_summary[rows_flagged] )", INT, "6 Data quality"),
    ("Issues Logged", "COUNTROWS ( dq_issue_log )", INT, "6 Data quality"),
    # ---------- price-spike monitor (z-score of a commodity's daily change vs its own normal daily change)
    ("Spikes This Week", 'CALCULATE ( COUNTROWS ( price_spikes ), price_spikes[is_this_week] = 1, price_spikes[spike_type] = "spike up" ) + 0', INT, "7 Spike monitor"),
    ("Sharp Drops This Week", 'CALCULATE ( COUNTROWS ( price_spikes ), price_spikes[is_this_week] = 1, price_spikes[spike_type] = "sharp drop" ) + 0', INT, "7 Spike monitor"),
    ("Commodities Ready", 'CALCULATE ( COUNTROWS ( history_depth ), history_depth[spike_detection_status] = "ready" ) + 0', INT, "7 Spike monitor"),
    ("Daily History (days)", "MAX ( history_depth[daily_steps] ) + 0", INT, "7 Spike monitor"),
]
# FIX 3 (report): the build guide's filled map is replaced by a bar chart of observations by state -
# map visuals are often disabled in Power BI Desktop security settings and need Bing.


def q(name):
    """TMDL object name quoting."""
    if name.replace("_", "").isalnum() and not name[0].isdigit():
        return name
    return "'" + name.replace("'", "''") + "'"


def indent(text, n):
    return "\n".join(("\t" * n + line) if line.strip() else "" for line in text.splitlines())


def col_type(table, col, s):
    if (table, col) in COL_TYPES:
        return COL_TYPES[(table, col)]
    if (table, col) in TEXT_OVERRIDE:
        return "string"
    if col in DATE_COLS:
        return "dateTime"
    if pd.api.types.is_integer_dtype(s):
        return "int64"
    if pd.api.types.is_float_dtype(s):
        if s.dropna().empty:
            return "string"
        return "int64" if col in KEY_COLS and (s.dropna() % 1 == 0).all() else "double"
    return "string"


M_TYPE = {"int64": "Int64.Type", "double": "type number", "dateTime": "type date", "string": "type text"}


def table_tmdl(table):
    df = pd.read_csv(CSV_DIR / f"{table}.csv", low_memory=False, encoding="utf-8-sig")
    cols = [(c, col_type(table, c, df[c])) for c in df.columns]
    lines = [f"table {q(table)}", f"\tlineageTag: {gid('t', table)}"]
    if table == "dim_date":
        lines.append("\tdataCategory: Time")
    lines.append("")
    for c, t in cols:
        lines.append(f"\tcolumn {q(c)}")
        lines.append(f"\t\tdataType: {t}")
        if t == "dateTime":
            lines.append("\t\tformatString: yyyy-mm-dd")
        elif t == "int64":
            lines.append("\t\tformatString: 0")
        if table == "dim_date" and c == DATE_KEY_COL:
            lines.append("\t\tisKey")
        lines.append(f"\t\tlineageTag: {gid('c', table, c)}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {c}")
        if (table, c) in SORT_BY:
            lines.append(f"\t\tsortByColumn: {SORT_BY[(table, c)]}")
        lines.append("")
    types = ", ".join('{"%s", %s}' % (c, M_TYPE[t]) for c, t in cols)
    m = f'''let
    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Nulls = Table.TransformColumns(Promoted, List.Transform(Table.ColumnNames(Promoted), (c) => {{c, each if _ = "" then null else _}})),
    Typed = Table.TransformColumnTypes(Nulls, {{{types}}}, "en-US")
in
    Typed'''
    lines += [f"\tpartition {q(table)} = m", "\t\tmode: import", "\t\tsource =", indent(m, 4), ""]
    return "\n".join(lines) + "\n", {c for c, _ in cols}


def measures_tmdl():
    lines = ["table _Measures", f"\tlineageTag: {gid('t', '_Measures')}", ""]
    for name, expr, fmt, folder in MEASURES:
        if "\n" in expr:
            lines.append(f"\tmeasure {q(name)} =")
            lines.append(indent(expr, 3))
        else:
            lines.append(f"\tmeasure {q(name)} = {expr}")
        if fmt:
            lines.append(f"\t\tformatString: {fmt}")
        lines.append(f"\t\tdisplayFolder: {folder}")
        lines.append(f"\t\tlineageTag: {gid('m', name)}")
        lines.append("")
    lines += ["\tcolumn _", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {gid('c', '_Measures', '_')}",
              "\t\tsummarizeBy: none", "\t\tsourceColumn: _", "",
              "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
              indent('let\n    Source = #table(type table [_ = text], {})\nin\n    Source', 4), ""]
    return "\n".join(lines) + "\n"


def build_model(root):
    sm = root / f"{NAME}.SemanticModel"
    d = sm / "definition"
    (d / "tables").mkdir(parents=True)
    (sm / "definition.pbism").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "settings": {}}, indent=2))
    (sm / ".platform").write_text(json.dumps({
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": gid("sm")}}, indent=2))
    (d / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1567\n\n")
    model = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
             "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull",
             "", "annotation PBI_ProTooling = [\"DevMode\"]", "", "annotation __PBI_TimeIntelligenceEnabled = 0", ""]
    for t in ["_Measures"] + TABLES:
        model.append(f"ref table {q(t)}")
    (d / "model.tmdl").write_text("\n".join(model) + "\n")
    (d / "expressions.tmdl").write_text(
        f'expression DataFolder = "{DEFAULT_DATA_FOLDER}" meta [IsParameterQuery = true, Type = "Text", '
        f'IsParameterQueryRequired = true]\n\tlineageTag: {gid("e", "DataFolder")}\n\n'
        "\tannotation PBI_ResultType = Text\n\n")
    columns = {}
    for t in TABLES:
        text, cols = table_tmdl(t)
        columns[t] = cols
        (d / "tables" / f"{t}.tmdl").write_text(text)
    (d / "tables" / "_Measures.tmdl").write_text(measures_tmdl())
    rel = []
    for ft, fc, tt, tc, active in RELATIONSHIPS:
        assert fc in columns[ft] and tc in columns[tt], (ft, fc, tt, tc)
        rel += [f"relationship {gid('r', ft, fc, tt, tc)}", f"\tfromColumn: {q(ft)}.{q(fc)}",
                f"\ttoColumn: {q(tt)}.{q(tc)}"] + ([] if active else ["\tisActive: false"]) + [""]
    (d / "relationships.tmdl").write_text("\n".join(rel) + "\n")
    return columns


# =============================================================================
# 2. REPORT (PBIR)
# =============================================================================
V_SCHEMA = f"{SCHEMA}/item/report/definition/visualContainer/2.13.0/schema.json"
P_SCHEMA = f"{SCHEMA}/item/report/definition/page/2.1.0/schema.json"
MEASURE_NAMES = {m[0] for m in MEASURES}


def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def field(ref):
    """'table.column' -> column, 'Measure Name' (in MEASURES) -> measure."""
    if ref in MEASURE_NAMES:
        return ({"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": ref}},
                f"_Measures.{ref}", ref)
    t, c = ref.split(".", 1)
    return ({"Column": {"Expression": {"SourceRef": {"Entity": t}}, "Property": c}}, f"{t}.{c}", c)


def projections(refs):
    out = []
    for r in refs:
        r, display = (r if isinstance(r, tuple) else (r, None))
        f, qref, native = field(r)
        proj = {"field": f, "queryRef": qref, "nativeQueryRef": native}
        if display:
            proj["displayName"] = display
        out.append(proj)
    return {"projections": out}


class Page:
    def __init__(self, name, display, W=1280, H=720):
        self.name, self.display, self.W, self.H = name, display, W, H
        self.visuals, self.interactions, self.filters = [], [], []

    def add(self, vid, vtype, x, y, w, h, roles=None, title=None, objects=None, sort=None, container=None,
            title_size=None, filters=None):
        vid = f"{self.name}_{vid}"[:50]
        visual = {"visualType": vtype}
        if roles:
            visual["query"] = {"queryState": {role: projections(refs) for role, refs in roles.items()}}
            if sort:
                f, _, _ = field(sort[0])
                visual["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": sort[1]}],
                                                     "isDefaultSort": False}
        if vtype == "tableEx":
            objects = {"total": [{"properties": {"totals": lit(False)}}], **(objects or {})}
        if objects:
            visual["objects"] = objects
        vco = dict(container or {})
        if title:
            tprops = {"show": lit(True), "text": lit(title)}
            if title_size:
                tprops["fontSize"] = lit(title_size)
            vco["title"] = [{"properties": tprops}]
            vco["subTitle"] = [{"properties": {"show": lit(False)}}]
        if vco:
            visual["visualContainerObjects"] = vco
        v = {"$schema": V_SCHEMA, "name": vid,
             "position": {"x": x, "y": y, "z": len(self.visuals) * 100, "height": h,
                          "width": w, "tabOrder": len(self.visuals) * 100},
             "visual": visual}
        if filters:
            v["filterConfig"] = {"filters": filters}
        self.visuals.append(v)
        return vid

    def text(self, vid, x, y, w, h, text, size=10, bold=False, color="#3C434C"):
        style = {"fontSize": f"{size}pt", "color": color}
        if bold:
            style["fontWeight"] = "bold"
        return self.add(vid, "textbox", x, y, w, h,
                        objects={"general": [{"properties": {"paragraphs": [
                            {"textRuns": [{"value": text, "textStyle": style}]}]}}]})

    def no_filter(self, source, target):
        self.interactions.append({"source": source, "target": target, "type": "NoFilter"})


NO_SLICER_HEADER = {"header": [{"properties": {"show": lit(False)}}]}


def slicer_default(entity, column, value):
    """Saved slicer selection, in the format Power BI Desktop writes."""
    return {"general": [{"properties": {"filter": {"filter": {
        "Version": 2,
        "From": [{"Name": "s", "Entity": entity, "Type": 0}],
        "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": column}}],
            "Values": [[{"Literal": {"Value": "'" + value + "'"}}]]}}}]}}}}]}



# =============================================================================
# 3. PAGES (1280 x 720)
# =============================================================================
INK_DARK, INK_MID, MUTED = "#34117E", "#6631DB", "#5B6470"
FOOTER = ("Sources: DoCA Price Monitoring Division (All-India averages), Open Prices / Open Food Facts "
          "(crowd-sourced, ODbL), MoSPI CPI (benchmark only). Not an official inflation measure. "
          "Captured 2026-10-01; see docs/METHODOLOGY_AND_LIMITATIONS.md.")


def filt(entity, column, values, name, numeric=False):
    """Categorical filter (visual or page level) in Power BI's saved format."""
    lits = [f"{v}L" if numeric else "'" + str(v).replace("'", "''") + "'" for v in values]
    return {"name": name, "field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": column}},
            "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "f", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {
                           "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": column}}],
                           "Values": [[{"Literal": {"Value": v}}] for v in lits]}}}]}}


def measure_at_least(measure, minimum, name):
    return {"name": name, "field": {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": measure}},
            "type": "Advanced",
            "filter": {"Version": 2, "From": [{"Name": "m", "Entity": "_Measures", "Type": 0}],
                       "Where": [{"Condition": {"Comparison": {"ComparisonKind": 2,
                                  "Left": {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": measure}},
                                  "Right": {"Literal": {"Value": f"{minimum}D"}}}}}]}}


DOCA = lambda n: filt("dim_source", "source_code", ["DOCA_PMD"], f"fDoca{n}")
RETAIL = lambda n: filt("fact_price", "price_type", ["retail"], f"fRetail{n}")
OPEN = lambda n: filt("dim_source", "source_code", ["OPEN_PRICES"], f"fOpen{n}")
WRAP = {"values": [{"properties": {"wordWrap": lit(True), "fontSize": lit(9)}}],
        "columnHeaders": [{"properties": {"wordWrap": lit(True), "fontSize": lit(9)}}]}
DOT = {"categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(8)}}]}


def diverging(measure, lo=-0.2, hi=0.2):
    """Cell background: price fall = purple, rise = orange, no change = pale."""
    rule = {"FillRule": {
        "Input": {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": measure}},
        "FillRule": {"linearGradient3": {
            "min": {"color": {"Literal": {"Value": "'#6631DB'"}}, "value": {"Literal": {"Value": f"{lo}D"}}},
            "mid": {"color": {"Literal": {"Value": "'#F8F5FF'"}}, "value": {"Literal": {"Value": "0D"}}},
            "max": {"color": {"Literal": {"Value": "'#E8833A'"}}, "value": {"Literal": {"Value": f"{hi}D"}}},
            "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'noColor'"}}}}}}}
    return {"properties": {"backColor": {"solid": {"color": {"expr": rule}}}},
            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": f"_Measures.{measure}"}}


def header(p, title, subtitle):
    p.text("title", 16, 6, 1248, 36, title, size=18, bold=True, color=INK_DARK)
    p.text("subtitle", 16, 40, 1248, 28, subtitle, size=10)
    p.text("footer", 16, 676, 1248, 38, FOOTER, size=8, color=MUTED)


def card(p, vid, x, y, w, h, measure, title, size=20):
    return p.add(vid, "card", x, y, w, h, roles={"Values": [measure]}, title=title, title_size=10,
                 objects={"labels": [{"properties": {"fontSize": lit(size)}}],
                          "categoryLabels": [{"properties": {"show": lit(False)}}]})


def slicer(p, vid, x, y, w, h, ref, title, single=False, default=None, filters=None):
    entity, column = ref.split(".", 1)
    objs = {**NO_SLICER_HEADER, "data": [{"properties": {"mode": lit("Dropdown")}}]}
    if single:
        objs["selection"] = [{"properties": {"singleSelect": lit(True)}}]
    if default:
        objs.update(slicer_default(entity, column, default))
    return p.add(vid, "slicer", x, y, w, h, roles={"Values": [ref]}, title=title, title_size=10, objects=objs,
                 filters=filters)


IN_ANALYSIS = lambda: [filt("fact_price", "include_in_analysis", [1], "fIncl", numeric=True)]


def build_pages():
    pages = []

    # ---------------- Page 1: overview
    p = Page("p1_overview", "1 Price Overview")
    p.filters = IN_ANALYSIS()
    header(p, "Consumer price overview",
           "Snapshot of 1-Oct-2026. DoCA = official All-India averages for ~40 essentials; Open Prices = shop prices "
           "of branded packaged food. Prices are per kg / litre / unit.")
    slicer(p, "group", 16, 76, 300, 64, "dim_category.category_group", "Category group")
    slicer(p, "source", 324, 76, 340, 64, "dim_source.source_name", "Source")
    p.text("note", 676, 82, 588, 54, "Short official history: DoCA gives 6 dated points per commodity "
           "(today, 1 week, 1 month, 6 months, 1 and 2 years back). Daily runs build a real series.", size=9, color=MUTED)
    for i, (m, t) in enumerate([("Commodities Tracked", "DoCA commodities"), ("Branded Products Observed", "Branded products"),
                                ("Cities Covered", "Cities covered"), ("Latest Collection Date", "Latest collection"),
                                ("Avg YoY Change % (DoCA)", "Avg YoY (DoCA)"), ("Avg MoM Change % (DoCA)", "Avg MoM (DoCA)")]):
        card(p, f"k{i}", 16 + i * 210, 148, 202, 92, m, t, size=18)
    p.add("yoy", "clusteredBarChart", 16, 248, 520, 420,
          roles={"Category": [("dim_product.product_name", "Commodity")], "Y": [("YoY Change %", "YoY change")]},
          title="Year-on-year price change by commodity (DoCA retail, ranked)",
          sort=("YoY Change %", "Descending"), filters=[DOCA(1), RETAIL(1)])
    p.add("trend", "lineChart", 544, 248, 720, 420,
          roles={"Category": [("dim_date.full_date", "Date")], "Y": [("Avg Normalized Price", "Avg price")],
                 "Series": [("dim_category.category", "Category")]},
          title="Average DoCA retail price by category (₹ per kg / litre / unit)",
          objects={"lineStyles": [{"properties": {"showMarker": lit(True), "markerSize": lit(5)}}]},
          filters=[DOCA(2), RETAIL(2)])
    pages.append(p)

    # ---------------- Page 2: product trends
    p = Page("p2_trends", "2 Product Price Trends")
    p.filters = IN_ANALYSIS()
    header(p, "Product price trends",
           "Pick one commodity. Points are DoCA's official look-back prices; the table compares every commodity.")
    prod = slicer(p, "product", 16, 76, 320, 64, "dim_product.product_name", "Commodity", single=True,
                  default="Onion", filters=[filt("dim_product", "source_code", ["DOCA_PMD"], "fDocaProd")])
    p.text("hint", 350, 88, 914, 46, "Table colours: orange = price rose, purple = price fell. The CPI chart is a "
           "benchmark with a different method (monthly index, 2012 = 100), so compare direction, not level.",
           size=9, color=MUTED)
    p.add("line", "lineChart", 16, 148, 760, 262,
          roles={"Category": [("dim_date.full_date", "Date")], "Y": [("Avg Normalized Price", "Price (₹)")],
                 "Tooltips": [("fact_price.lookback_label", "Look-back")]},
          title="Selected commodity: DoCA retail price at each look-back point",
          objects={"lineStyles": [{"properties": {"showMarker": lit(True), "markerSize": lit(7)}}]},
          filters=[DOCA(3), RETAIL(3)])
    tbl = p.add("table", "tableEx", 784, 148, 480, 520,
                roles={"Values": [("dim_product.product_name", "Commodity"), ("Price Latest", "Latest ₹"),
                                  ("Price 1M Ago", "1M ago ₹"), ("Price 1Y Ago", "1Y ago ₹"),
                                  ("MoM Change %", "MoM"), ("YoY Change %", "YoY")]},
                title="All commodities: latest vs 1 month and 1 year ago",
                sort=("YoY Change %", "Descending"), filters=[DOCA(4), RETAIL(4)],
                objects={**WRAP, "values": WRAP["values"] + [diverging("MoM Change %"), diverging("YoY Change %")]})
    p.no_filter(prod, tbl)
    cat = p.add("cat", "clusteredColumnChart", 16, 418, 380, 250,
                roles={"Category": [("dim_category.category", "Category")], "Y": [("MoM Change %", "MoM change")]},
                title="Month-on-month change by category (DoCA retail)", filters=[DOCA(5), RETAIL(5)])
    p.no_filter(prod, cat)
    p.add("cpi", "lineChart", 404, 418, 372, 250,
          roles={"Category": [("dim_date.full_date", "Month")], "Y": [("CPI Index (mapped item)", "CPI index")]},
          title="MoSPI CPI for the matching item (2012 = 100) - benchmark only")
    pages.append(p)

    # ---------------- Page 3: brands
    p = Page("p3_brands", "3 Brand Comparison")
    p.filters = IN_ANALYSIS()
    header(p, "Brand comparison",
           "Open Prices shop prices of branded products, compared within ONE category and ONE unit.")
    slicer(p, "category", 16, 76, 320, 64, "dim_category.category", "Category", single=True,
           default="Biscuits, Bread & Bakery")
    slicer(p, "unit", 344, 76, 180, 64, "fact_price.normalized_unit", "Unit", single=True, default="INR/kg")
    p.add("kb", "card", 532, 76, 180, 64, roles={"Values": [("Brands in Selection", "Brands in selection")]},
          objects={"labels": [{"properties": {"fontSize": lit(16)}}],
                   "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(8)}}]})
    p.text("warn", 724, 82, 540, 54, "Compare within one category and one unit only. Many brands have just "
           "1-2 observations: check the Sample column before reading a gap as real.", size=9, color="#8A4B12")
    p.add("bar", "clusteredBarChart", 16, 148, 620, 520,
          roles={"Category": [("dim_brand.brand_name", "Brand")], "Y": [("Avg Normalized Price", "Avg price (₹)")]},
          title="Average normalised price by brand (cheapest first)", sort=("Avg Normalized Price", "Ascending"),
          filters=[filt("dim_brand", "is_branded", [1], "fBranded", numeric=True)])
    p.add("table", "tableEx", 644, 148, 620, 520,
          roles={"Values": [("dim_brand.brand_name", "Brand"), ("Observations", "Obs"), ("Distinct Products", "Products"),
                            ("Min Normalized Price", "Min ₹"), ("Max Normalized Price", "Max ₹"), ("Sample Flag", "Sample")]},
          title="Brand detail", sort=("Observations", "Descending"), objects=WRAP,
          filters=[filt("dim_brand", "is_branded", [1], "fBranded2", numeric=True)])
    pages.append(p)

    # ---------------- Page 4: locations
    p = Page("p4_locations", "4 Location Comparison")
    p.filters = IN_ANALYSIS()
    header(p, "Location comparison",
           "Location coverage is thin: only 6 barcodes were seen in 2+ cities. DoCA centre-wise data is "
           "CAPTCHA-protected and deliberately not used.")
    p.add("state", "clusteredBarChart", 16, 76, 400, 330,
          roles={"Category": [("dim_location.state", "State")], "Y": [("Observations", "Observations")]},
          title="Shop-price observations by state (Open Prices)", sort=("Observations", "Descending"),
          filters=[OPEN(1), filt("dim_location", "location_level", ["outlet"], "fOutlet1")])
    p.add("city", "clusteredBarChart", 424, 76, 420, 330,
          roles={"Category": [("dim_location.city", "City")], "Y": [("City Price Index", "Index")]},
          title="City price index, same products only (100 = their all-city average)",
          sort=("City Price Index", "Descending"),
          filters=[OPEN(2), filt("dim_location", "location_level", ["outlet"], "fOutlet2")])
    p.add("markup", "clusteredBarChart", 852, 76, 412, 592,
          roles={"Category": [("dim_product.product_name", "Commodity")],
                 "Y": [("Retail Markup over Wholesale %", "Retail over wholesale")]},
          title="DoCA: retail markup over wholesale", sort=("Retail Markup over Wholesale %", "Descending"),
          filters=[DOCA(6)])
    p.add("multi", "tableEx", 16, 414, 828, 254,
          roles={"Values": [("dim_product.product_name", "Product"), ("Cities for Product", "Cities"),
                            ("Min Pack Price", "Min pack ₹"), ("Max Pack Price", "Max pack ₹"),
                            ("Location Spread %", "Spread")]},
          title="Same product seen in 2+ cities: pack price spread", sort=("Location Spread %", "Descending"),
          objects=WRAP, filters=[OPEN(3), measure_at_least("Cities for Product", 2, "fTwoCities")])
    pages.append(p)

    # ---------------- Page 5: discounts & availability
    p = Page("p5_discounts", "5 Discounts & Availability")
    p.filters = IN_ANALYSIS()
    header(p, "Discounts and availability",
           "Discounts from Open Prices (implausible list prices excluded). 'Availability' = DoCA reported a price "
           "that day - not shelf stock.")
    for i, (m, t) in enumerate([("% Observations Discounted", "Obs discounted"),
                                ("Avg Discount % (when discounted)", "Avg discount"),
                                ("Total Savings INR", "Total savings (₹)"), ("Not Reported Gap Rate %", "DoCA not reported")]):
        card(p, f"k{i}", 16 + i * 314, 76, 306, 92, m, t)
    p.add("listeff", "clusteredBarChart", 16, 176, 620, 250,
          roles={"Category": [("dim_category.category", "Category")],
                 "Y": [("Avg Normalized List Price", "List price"), ("Avg Normalized Effective Price", "Paid price")]},
          title="Discounted items: list vs paid price by category (₹ per unit)",
          sort=("Avg Normalized List Price", "Descending"),
          filters=[OPEN(4), filt("dim_category", "in_scope", [1], "fScope", numeric=True)])
    p.add("pct", "clusteredBarChart", 644, 176, 620, 250,
          roles={"Category": [("dim_category.category", "Category")], "Y": [("% Observations Discounted", "Share discounted")]},
          title="Share of observations on discount, by category", sort=("% Observations Discounted", "Descending"),
          filters=[OPEN(5)])
    p.add("avail", "pivotTable", 16, 434, 1248, 234,
          roles={"Rows": [("dim_product.product_name", "Commodity")], "Columns": [("dim_date.full_date", "Date")],
                 "Values": [("Availability Status", "Status")]},
          title="DoCA reporting status by commodity and date (reported / not reported / not yet tracked)",
          objects={"subTotals": [{"properties": {"rowSubtotals": lit(False), "columnSubtotals": lit(False)}}],
                   "values": [{"properties": {"fontSize": lit(8)}}],
                   "columnHeaders": [{"properties": {"fontSize": lit(9)}}]})
    pages.append(p)

    # ---------------- Page 6: data quality (no include_in_analysis filter)
    p = Page("p6_quality", "6 Data Quality")
    header(p, "Data quality",
           "Every check and every excluded or flagged record is logged; raw files are kept untouched with their SHA-256.")
    for i, (m, t) in enumerate([("Total Raw Records", "Raw price records"), ("Records Excluded", "Excluded"),
                                ("Records Flagged", "Flagged"), ("% Usable", "Usable"), ("Issues Logged", "Issues logged")]):
        card(p, f"k{i}", 16 + i * 251, 76, 243, 92, m, t)
    p.add("checks", "clusteredBarChart", 16, 176, 620, 250,
          roles={"Category": [("dq_check_summary.check_name", "Check")], "Y": [("Rows Flagged (checks)", "Rows flagged")]},
          title="Rows flagged by each check", sort=("Rows Flagged (checks)", "Descending"),
          filters=[measure_at_least("Rows Flagged (checks)", 1, "fFlagged")])
    p.add("bysrc", "clusteredBarChart", 644, 176, 620, 250,
          roles={"Category": [("dim_source.source_name", "Source")],
                 "Y": [("Records Included", "Included"), ("Records Excluded", "Excluded")]},
          title="Price records kept vs excluded, by source")
    p.add("summary", "tableEx", 16, 434, 410, 234,
          roles={"Values": [("dq_check_summary.check_name", "Check"), ("dq_check_summary.source_code", "Source"),
                            ("dq_check_summary.rows_checked", "Checked"), ("dq_check_summary.rows_flagged", "Flagged"),
                            ("dq_check_summary.action", "Action")]},
          title="Check summary", objects=WRAP)
    p.add("issues", "tableEx", 434, 434, 420, 234,
          roles={"Values": [("dq_issue_log.check_name", "Check"), ("dq_issue_log.severity", "Severity"),
                            ("dq_issue_log.record_key", "Record"), ("dq_issue_log.action_taken", "Action taken")]},
          title="Issue log", objects=WRAP)
    p.add("files", "tableEx", 862, 434, 402, 234,
          roles={"Values": [("etl_raw_file.relative_path", "Raw file"), ("etl_raw_file.collection_date", "Collected"),
                            ("etl_raw_file.records_parsed", "Records"), ("etl_raw_file.sha256", "SHA-256")]},
          title="Raw file provenance", objects=WRAP)
    pages.append(p)

    # ---------------- Page 7: price-spike monitor
    p = Page("p7_spikes", "7 Price-Spike Monitor")
    header(p, "Price-spike monitor",
           "A spike = a commodity's daily price change more than 2 standard deviations above its own normal daily "
           "change (z > 2). Each commodity needs 10+ daily steps before it is judged.")
    for i, (m, t) in enumerate([("Spikes This Week", "Spikes this week"), ("Sharp Drops This Week", "Sharp drops this week"),
                                ("Commodities Ready", "Commodities with enough history"),
                                ("Daily History (days)", "Longest daily history (steps)")]):
        card(p, f"k{i}", 16 + i * 314, 76, 306, 92, m, t)
    p.add("week", "tableEx", 16, 176, 760, 250,
          roles={"Values": [("price_spikes.product_name", "Commodity"), ("price_spikes.obs_date", "Date"),
                            ("price_spikes.prev_price", "Previous ₹"), ("price_spikes.price", "Price ₹"),
                            ("price_spikes.pct_change", "Change %"), ("price_spikes.z_score", "z"),
                            ("price_spikes.spike_type", "Type")]},
          title="This week's spikes and sharp drops (empty until daily history builds up)", objects=WRAP,
          filters=[filt("price_spikes", "is_this_week", [1], "fWeek", numeric=True)])
    p.add("depth", "tableEx", 784, 176, 480, 492,
          roles={"Values": [("history_depth.product_name", "Commodity"), ("history_depth.daily_steps", "Daily steps"),
                            ("history_depth.last_date", "Last date"), ("history_depth.spike_detection_status", "Status")]},
          title="History collected per commodity (ready at 10 daily steps)", objects=WRAP)
    p.add("all", "tableEx", 16, 434, 760, 234,
          roles={"Values": [("price_spikes.product_name", "Commodity"), ("price_spikes.category", "Category"),
                            ("price_spikes.obs_date", "Date"), ("price_spikes.pct_change", "Change %"),
                            ("price_spikes.normal_change", "Normal %"), ("price_spikes.z_score", "z"),
                            ("price_spikes.spike_type", "Type")]},
          title="All detected spikes (history)", objects=WRAP)
    pages.append(p)
    return pages


BASE_THEME = "Fluent2-CY26SU09"


def build_report(root):
    rp = root / f"{NAME}.Report"
    d = rp / "definition"
    (d / "pages").mkdir(parents=True)
    (rp / "definition.pbir").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definitionProperties/1.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}}, indent=2))
    (rp / ".platform").write_text(json.dumps({
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": gid("rp")}}, indent=2))
    (d / "version.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"}, indent=2))
    # custom theme shipped with the report
    theme_src = PBI_DIR / THEME_FILE
    reg = rp / "StaticResources" / "RegisteredResources"
    reg.mkdir(parents=True)
    shutil.copy(theme_src, reg / THEME_NAME)
    # base theme exactly as Power BI Desktop (Sep 2026) writes it
    base = rp / "StaticResources" / "SharedResources" / "BaseThemes"
    base.mkdir(parents=True)
    shutil.copy(PBI_DIR / f"Base_Theme_{BASE_THEME}.json", base / f"{BASE_THEME}.json")
    (d / "report.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "type": "SharedResources",
                          "reportVersionAtImport": {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"}},
            "customTheme": {"name": THEME_NAME, "type": "RegisteredResources",
                            "reportVersionAtImport": {"visual": "2.13.0", "report": "3.4.0", "page": "2.3.1"}}},
        "objects": {"section": [{"properties": {"verticalAlignment": {"expr": {"Literal": {"Value": "'Top'"}}}}}]},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": THEME_NAME, "path": THEME_NAME, "type": "CustomTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True, "exportDataMode": "AllowSummarized", "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True}}, indent=2))
    pages = build_pages()
    (d / "pages" / "pages.json").write_text(json.dumps({
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.1.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name}, indent=2))
    n_vis = 0
    for p in pages:
        pd_ = d / "pages" / p.name
        (pd_ / "visuals").mkdir(parents=True)
        page = {"$schema": P_SCHEMA, "name": p.name, "displayName": p.display, "displayOption": "FitToPage",
                "height": p.H, "width": p.W}
        if p.filters:
            page["filterConfig"] = {"filters": p.filters}
        if p.interactions:
            page["visualInteractions"] = p.interactions
        (pd_ / "page.json").write_text(json.dumps(page, indent=2))
        for v in p.visuals:
            (pd_ / "visuals" / v["name"]).mkdir()
            (pd_ / "visuals" / v["name"] / "visual.json").write_text(json.dumps(v, indent=2, ensure_ascii=False))
            n_vis += 1
    return pages, n_vis


def check_fields(pages, columns):
    """Every column a visual uses must exist in the model."""
    for p in pages:
        for v in p.visuals:
            for role in v["visual"].get("query", {}).get("queryState", {}).values():
                for pr in role["projections"]:
                    f = pr["field"]
                    if "Column" in f:
                        t, c = f["Column"]["Expression"]["SourceRef"]["Entity"], f["Column"]["Property"]
                        assert c in columns[t], f"{p.name}/{v['name']}: {t}.{c} not in model"


def write_measures_dax():
    lines = ["// Generated by powerbi/generate_powerbi_project.py - the same measures are inside ConsumerPrice.SemanticModel.",
             "// Prices are normalised: INR per kg, per litre or per unit - never mix units in one visual.", ""]
    folder = None
    for name, expr, fmt, f in MEASURES:
        if f != folder:
            lines += ["", f"// ---------- {f} ----------"]
            folder = f
        lines += [f"{name} =", expr, f"// format: {fmt}" if fmt else "", ""]
    (PBI_DIR / "DAX_Measures_generated.dax").write_text("\n".join(lines), encoding="utf-8")


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / f"{NAME}.pbip").write_text(json.dumps({
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}}, indent=2))
    (OUT / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    columns = build_model(OUT)
    pages, n_vis = build_report(OUT)
    check_fields(pages, columns)
    write_measures_dax()
    print(f"PBIP written to {OUT}: {len(TABLES)} tables + _Measures ({len(MEASURES)} measures), "
          f"{len(RELATIONSHIPS)} relationships, {len(pages)} pages, {n_vis} visuals")


if __name__ == "__main__":
    main()
