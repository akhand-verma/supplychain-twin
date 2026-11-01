"""Run from the backend folder with:  python -m app.seed
WARNING: wipes and recreates all tables. Stop the API first."""
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from . import models, sim_engine
from .catalog import POLICIES, SCENARIOS
from .database import Base, SessionLocal, engine

HISTORY_DAYS = 60
KPI_RUNS = 20


def make_kpi_data(n: int = KPI_RUNS) -> list[dict]:
    rows = []
    for sc in SCENARIOS:
        for p in POLICIES:
            r = sim_engine.run_monte_carlo(p["key"], sc["key"], n)
            for m, mean in r["kpi_mean"].items():
                lo, hi = r["kpi_ci"][m]
                rows.append({"policy_key": p["key"], "scenario_key": sc["key"], "metric": m,
                             "mean": mean, "ci_low": lo, "ci_high": hi, "n_runs": n})
    return rows
PRODUCTS = [("Milk 1L", "Dairy", 1.2), ("Bread", "Bakery", 0.9), ("Rice 5kg", "Staples", 6.5),
            ("Cooking Oil 1L", "Staples", 3.1), ("Eggs (12)", "Dairy", 2.4),
            ("Detergent", "Household", 4.8)]


def simulate_history(mu, days, rng, stressed=False):
    """Simple (s,S) store history. Stressed stores reorder too late, so they stock out."""
    s, S, lead = (mu * 2.5, mu * 7, 3) if stressed else (mu * 4.5, mu * 10, 3)
    on_hand, pipeline, rows = S, {}, []
    for d in range(days):
        on_hand += pipeline.pop(d, 0)
        dem = int(rng.poisson(mu * (1 + 0.2 * math.sin(2 * math.pi * d / 7))))
        stockout = dem > on_hand
        on_hand -= min(on_hand, dem)
        position = on_hand + sum(pipeline.values())
        if position <= s:
            pipeline[d + lead] = pipeline.get(d + lead, 0) + int(S - position)
        rows.append((float(on_hand), float(dem), bool(stockout)))
    return rows


def main():
    rng = np.random.default_rng(42)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    today = date.today()

    # ---- catalog tables
    db.add_all([models.Policy(**p) for p in POLICIES])
    db.add_all([models.Scenario(**s) for s in SCENARIOS])
    prods = [models.Product(name=n, category=c, unit_cost=u) for n, c, u in PRODUCTS]
    db.add_all(prods)

    # ---- locations (layered layout: suppliers | warehouses | stores)
    suppliers = [models.Location(name=f"Supplier {c}", type="supplier", capacity=0, x=8, y=y)
                 for c, y in (("A", 30), ("B", 70))]
    warehouses = [models.Location(name=f"Warehouse {i}", type="warehouse", capacity=5000, x=45, y=y)
                  for i, y in ((1, 25), (2, 75))]
    stores = [models.Location(name=f"Store {i + 1}", type="store", capacity=800,
                              x=88, y=8 + i * 12) for i in range(8)]
    db.add_all(suppliers + warehouses + stores)
    db.flush()  # assigns ids

    # ---- edges
    edges, lead_by_store = [], {}
    for sup in suppliers:
        for wh in warehouses:
            edges.append(models.NetworkEdge(
                src_id=sup.id, dst_id=wh.id,
                lead_time_mean=round(float(rng.uniform(5, 8)), 1),
                lead_time_std=1.5, cost_per_unit=2.0))
    for i, st in enumerate(stores):
        wh = warehouses[0] if i < 4 else warehouses[1]
        lt = round(float(rng.uniform(2, 4)), 1)
        lead_by_store[st.id] = lt
        edges.append(models.NetworkEdge(src_id=wh.id, dst_id=st.id,
                                        lead_time_mean=lt, lead_time_std=0.8, cost_per_unit=1.0))
    edges.append(models.NetworkEdge(src_id=warehouses[0].id, dst_id=warehouses[1].id,
                                    lead_time_mean=1.5, lead_time_std=0.5, cost_per_unit=1.5))
    edges.append(models.NetworkEdge(src_id=warehouses[1].id, dst_id=warehouses[0].id,
                                    lead_time_mean=1.5, lead_time_std=0.5, cost_per_unit=1.5))
    db.add_all(edges)

    # ---- inventory history, forecasts
    wh_acc = {}  # (warehouse_id, product_id) -> daily [on_hand, demand] sums + summed mu
    now_stock, fc_cache = {}, {}
    for i, st in enumerate(stores):
        wh = warehouses[0] if i < 4 else warehouses[1]
        for p in prods:
            mu = float(rng.uniform(20, 60))
            rows = simulate_history(mu, HISTORY_DAYS, rng, stressed=(i in (2, 6)))
            acc = wh_acc.setdefault((wh.id, p.id),
                                    {"days": [[0.0, 0.0] for _ in range(HISTORY_DAYS)], "mu": 0.0})
            acc["mu"] += mu
            for d, (oh, dem, so) in enumerate(rows):
                day = today - timedelta(days=HISTORY_DAYS - 1 - d)
                db.add(models.InventorySnapshot(product_id=p.id, location_id=st.id, date=day,
                                                on_hand=oh, demand=dem, days_cover=oh / mu, stockout=so))
                acc["days"][d][0] += oh
                acc["days"][d][1] += dem
            now_stock[(st.id, p.id)] = rows[-1][0]

            # forecasts: 14 days of backtest + 14 days ahead
            fc = {}
            for off in range(-13, 15):
                h = max(off, 0)
                base = mu * (1 + 0.2 * math.sin(2 * math.pi * (HISTORY_DAYS - 1 + off) / 7))
                f = (base * (0.72 - 0.005 * h), base, base * (1.30 + 0.01 * h))
                fc[off] = f
                db.add(models.Forecast(product_id=p.id, location_id=st.id,
                                       date=today + timedelta(days=off),
                                       p10=f[0], p50=f[1], p90=f[2]))
            fc_cache[(st.id, p.id)] = fc

    # warehouse snapshots (aggregate of their stores)
    for (wh_id, p_id), acc in wh_acc.items():
        for d, (oh, dem) in enumerate(acc["days"]):
            day = today - timedelta(days=HISTORY_DAYS - 1 - d)
            stock = oh * 3
            db.add(models.InventorySnapshot(product_id=p_id, location_id=wh_id, date=day,
                                            on_hand=stock, demand=dem,
                                            days_cover=stock / acc["mu"], stockout=False))

    # ---- alerts
    prod_name = {p.id: p.name for p in prods}
    store_name = {s.id: s.name for s in stores}
    for (st_id, p_id), oh in now_stock.items():
        lt = max(1, round(lead_by_store[st_id]))
        fc = fc_cache[(st_id, p_id)]
        need50 = sum(fc[o][1] for o in range(1, lt + 1))
        need90 = sum(fc[o][2] for o in range(1, lt + 1))
        sev = "high" if oh < need50 else ("medium" if oh < need90 else None)
        if sev:
            qty = max(1, math.ceil(need90 - oh))
            db.add(models.Alert(
                product_id=p_id, location_id=st_id, date=today, severity=sev,
                recommended_qty=qty,
                message=(f"{prod_name[p_id]} at {store_name[st_id]}: {round(oh)} units on hand "
                         f"vs ~{round(need50)} expected demand over the next {lt} days.")))

    # ---- precomputed Monte Carlo KPIs (real ML simulator).
    # Computed once with `python -m app.make_kpi_seed` and stored in kpi_seed.json,
    # so starting the stack does not re-run hundreds of simulations.
    kpi_file = Path(__file__).with_name("kpi_seed.json")
    if kpi_file.exists():
        data = json.loads(kpi_file.read_text())
    else:
        print("kpi_seed.json not found, computing it now (a few minutes)...")
        data = make_kpi_data()
    for row in data:
        db.add(models.KpiResult(**row))

    db.commit()
    db.close()
    print("Seeded: 6 products, 12 locations, history, forecasts, alerts, KPI results.")


if __name__ == "__main__":
    main()