"""Run once:  python -m app.make_kpi_seed   (from the backend folder)
Runs the real ML simulator for every scenario x policy and saves kpi_seed.json."""
import json
from pathlib import Path

from .seed import make_kpi_data

if __name__ == "__main__":
    data = make_kpi_data()
    out = Path(__file__).with_name("kpi_seed.json")
    out.write_text(json.dumps(data, indent=1))
    print(f"Wrote {len(data)} rows to {out}")
