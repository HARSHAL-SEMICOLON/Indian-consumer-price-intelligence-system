"""Run the whole pipeline from the project root.

    python run_pipeline.py                 # load any new raw files -> data quality -> analysis -> Power BI export
    python run_pipeline.py --extract       # first collect a NEW snapshot (Open Prices + DoCA), then the above
    python run_pipeline.py --extract-cpi   # also refresh the MoSPI CPI benchmark (monthly is enough)
    python run_pipeline.py --rebuild       # rebuild the database from every raw file (raw files are never touched)

The notebooks in notebooks/ walk through the same steps one at a time.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import analysis  # noqa: E402
import export_powerbi  # noqa: E402
import load  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Indian Consumer Price & Market Intelligence pipeline")
    ap.add_argument("--extract", action="store_true", help="collect a new snapshot first")
    ap.add_argument("--extract-cpi", action="store_true", help="refresh the CPI benchmark")
    ap.add_argument("--rebuild", action="store_true", help="drop and rebuild the database from raw files")
    args = ap.parse_args()

    if args.extract or args.extract_cpi:
        import extract
        if args.extract:
            print("Open Prices ->", extract.extract_open_prices())
            print("DoCA        ->", extract.extract_doca())
        if args.extract_cpi:
            print("MoSPI CPI   ->", extract.extract_cpi([2024, 2025]))

    run_id, n_files, n_new, n_upd, missing = load.run(rebuild=args.rebuild)
    print(f"Run {run_id}: {n_files} new raw file(s), {n_new} new price rows, {n_upd} updated rows")
    if missing:
        print("CPI items not found for the commodity bridge:", missing)
    analysis.run_all()
    export_powerbi.export()
    print("Done. Open powerbi/ and press Refresh in Power BI.")
