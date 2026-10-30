"""Build the static site (GitHub Pages) in site/: the dashboard page plus the files the in-browser analysis engine loads.

    python3 scripts/build_pages.py [output_dir]

site/index.html            the generated dashboard page (src/build_dashboard.py)
site/engine_worker.js      web worker that starts Pyodide (Python in WebAssembly) and answers the page's /api/... requests
site/files.json            the files the worker copies into Pyodide's file system
site/engine/src/*.py       the server code, unchanged (the worker imports it through src/browser_backend.py)
site/engine/data/...       the reference tables that code reads, and the review's gauge/unit/objective list (data/results is too big to
                           ship; custom_ewr.review_context only needs six of its columns, so a de-duplicated copy of those is written)
"""

import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import build_dashboard  # noqa: E402

RESULT_COLUMNS = {"Gauge", "PlanningUnitName", "EcoObj", "FlowRegime", "EWR", "State"}  # what custom_ewr.review_context reads
REFERENCE_FILES = ("parameter_sheet.csv", "objective_reference.csv", "northern_connectivity_stations.csv", "bom_quality_codes.json")


def main(out: Path) -> None:
    build_dashboard.ensure_built()
    if out.exists():
        shutil.rmtree(out)
    engine = out / "engine"
    (engine / "src").mkdir(parents=True)
    (engine / "data" / "reference").mkdir(parents=True)
    (engine / "data" / "results").mkdir(parents=True)

    shutil.copy(ROOT / "ewr_analysis_dashboard.html", out / "index.html")
    shutil.copy(ROOT / "src" / "engine_worker.js", out / "engine_worker.js")
    (out / ".nojekyll").touch()

    for source in sorted((ROOT / "src").glob("*.py")):
        shutil.copy(source, engine / "src" / source.name)
    for name in REFERENCE_FILES:
        shutil.copy(ROOT / "data" / "reference" / name, engine / "data" / "reference" / name)
    for name in ("frequency_ratio.csv", "etp.csv"):
        frame = pd.read_csv(ROOT / "data" / "results" / name, dtype=str, usecols=lambda c: c in RESULT_COLUMNS).fillna("")
        frame.drop_duplicates().to_csv(engine / "data" / "results" / name, index=False)

    files = sorted(p.relative_to(out).as_posix() for p in engine.rglob("*") if p.is_file())
    (out / "files.json").write_text(json.dumps(files, indent=1) + "\n")
    engine_mb = sum((out / f).stat().st_size for f in files) / 1e6
    print(f"{len(files)} engine files, {engine_mb:.1f} MB; page {(out / 'index.html').stat().st_size / 1e6:.1f} MB -> {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "site")
