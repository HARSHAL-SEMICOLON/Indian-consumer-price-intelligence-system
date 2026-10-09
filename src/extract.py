"""Repeatable extractors. Each run writes ONE new raw capture file per source:

    data/raw/<source>/<YYYY-MM-DD>/<source>_raw_<YYYY-MM-DD>[_HHMMSS].jsonl

Each line is an envelope {url, fetched_at_utc, http_status, content_type, body}
where `body` is the exact response text. Raw files are never edited afterwards.

Usage (from project root):
    python src/extract.py --source all
    python src/extract.py --source doca
    python src/extract.py --source cpi --years 2024 2025
"""
import argparse
import json
import time
from datetime import datetime, timezone

import requests

from config import RAW, USER_AGENT, REQUEST_DELAY_SEC

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


def _now():
    return datetime.now(timezone.utc)


def _get(url, params=None, retries=4):
    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r
            print(f"  HTTP {r.status_code} for {r.url}")
        except requests.RequestException as e:
            print(f"  error {e} (attempt {attempt + 1})")
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed after {retries} attempts: {url} {params}")


def _envelope(r):
    return json.dumps({
        "url": r.url,
        "fetched_at_utc": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "http_status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "body": r.text,
    }, ensure_ascii=False)


def _out_path(folder, prefix):
    d = _now().strftime("%Y-%m-%d")
    out_dir = RAW / folder / d
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{prefix}_raw_{d}.jsonl"
    if p.exists():  # never overwrite an existing raw capture
        p = out_dir / f"{prefix}_raw_{d}_{_now().strftime('%H%M%S')}.jsonl"
    return p


def extract_open_prices():
    url = "https://prices.openfoodfacts.org/api/v1/prices"
    lines, page, pages = [], 1, 1
    while page <= pages:
        r = _get(url, params={"currency": "INR", "size": 100, "order_by": "id", "page": page})
        pages = r.json().get("pages", 1)
        lines.append(_envelope(r))
        print(f"  open prices page {page}/{pages}")
        page += 1
        time.sleep(REQUEST_DELAY_SEC)
    p = _out_path("open_prices", "openprices_INR")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def extract_doca():
    lines = []
    for url in ["https://fcainfoweb.nic.in/Reports/DB/DBprices.aspx", "https://fcainfoweb.nic.in/"]:
        r = _get(url)
        if "captcha" in r.text.lower() and "DBprices" in url:
            raise RuntimeError("CAPTCHA detected - stop. This project never bypasses CAPTCHA.")
        lines.append(_envelope(r))
        time.sleep(REQUEST_DELAY_SEC * 2)
    p = _out_path("doca_dashboard", "doca_dashboard")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def extract_cpi(years):
    base = "https://api.mospi.gov.in/api/cpi/"
    # Lesson from the first capture: large paginated result sets from this API are not
    # stably ordered (rows repeat across pages and others are skipped). So we query small
    # slices (one month x one sector, <=3 pages) and verify the distinct-row count equals
    # meta_data.totalRecords, re-fetching the slice if it does not.
    jobs = []
    for y in years:
        for m in range(1, 13):
            jobs.append(("item", base + "getItemIndex",
                         {"base_year": 2012, "year": y, "month_code": m, "format": "JSON"}, "item"))
            for sc in (1, 2, 3):  # 1 Rural, 2 Urban, 3 Combined
                jobs.append(("group_allindia", base + "getCPIIndex",
                             {"base_year": 2012, "series": "Current", "year": y, "month_code": m,
                              "state_code": 99, "sector_code": sc, "format": "JSON"}, "subgroup"))
    lines = []
    for kind, url, params, name_field in jobs:
        for attempt in range(3):
            page, pages, slice_lines, seen, total = 1, 1, [], set(), 0
            while page <= pages:
                r = _get(url, params={**params, "page": page})
                j = r.json()
                meta = j.get("meta_data") or {}
                pages, total = meta.get("totalPages", 1), meta.get("totalRecords", 0)
                seen.update((d.get("group"), d.get(name_field), d.get("sector")) for d in j.get("data", []))
                env = json.loads(_envelope(r))
                env["kind"] = kind
                slice_lines.append(json.dumps(env, ensure_ascii=False))
                page += 1
                time.sleep(0.3)
            lines.extend(slice_lines)  # every fetched page is kept raw; duplicates removed in transform
            if len(seen) >= total:
                break
            print(f"  incomplete slice {params} ({len(seen)}/{total}) - retrying")
    p = _out_path("mospi_cpi", "mospi_cpi")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["all", "open_prices", "doca", "cpi"], default="all")
    ap.add_argument("--years", nargs="*", type=int, default=[2024, 2025])
    a = ap.parse_args()
    if a.source in ("all", "open_prices"):
        print("Open Prices ->", extract_open_prices())
    if a.source in ("all", "doca"):
        print("DoCA ->", extract_doca())
    if a.source == "cpi":  # CPI is monthly; only pull when asked
        print("MoSPI CPI ->", extract_cpi(a.years))
