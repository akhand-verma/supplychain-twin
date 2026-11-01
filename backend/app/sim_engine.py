"""Adapter between Person A's ML simulator (ml/) and the backend/frontend contract.

Same two functions the mock had:
    run_simulation(policy, scenario, seed, days)  -> daily curves + KPIs + events
    run_monte_carlo(policy, scenario, n_runs)     -> mean and 95% CI per KPI

It calls the simulator directly (not ml.interface.run_simulation) so the MILP step
is not re-solved on every single run, which would make Monte Carlo far too slow.
"""
import os
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np


def _find_root() -> Path:
    """Folder that contains ml/ : the repo root locally, /srv in Docker."""
    env = os.getenv("ML_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "ml" / "artifacts").is_dir():
            return parent
    raise RuntimeError("Cannot find the ml/ folder. Set ML_ROOT to the folder that contains it.")


ROOT = _find_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml import forecaster, optimizer, policies, simulator  # noqa: E402
from ml.interface import POLICY_MAP, SCENARIO_MAP, get_policies  # noqa: E402

# The ML modules read "ml/artifacts" relative to the working directory.
# Make that absolute so it works no matter where uvicorn is started.
ARTIFACTS = str(ROOT / "ml" / "artifacts")
for _m in (simulator, policies, forecaster, optimizer):
    _m.ARTIFACTS_DIR = ARTIFACTS

METRICS = ["total_cost", "fill_rate", "service_level", "unmet_units", "recovery_days"]
DEFAULT_DAYS = 30


@lru_cache(maxsize=2048)
def _raw(mapped_policy: str, scenario: str, seed: int, days: int):
    """One real simulation. Cached: policies that map to the same ML policy share results."""
    pol = get_policies()
    fn = pol.forecast_driven_newsvendor if mapped_policy == "forecast_newsvendor" else pol.baseline_fixed_order
    sim = simulator.SupplyChainSimTwin(
        policy_fn=fn, disruption_config=SCENARIO_MAP.get(scenario),
        seed=seed, duration_days=days)
    res = sim.run()
    inv = np.zeros(days)
    dem = np.zeros(days)
    unmet = np.zeros(days)
    for r in res["timeseries"]:
        d = r["day"]
        inv[d] += r["inventory"]
        dem[d] += r["demand"]
        unmet[d] += r["unmet_demand"]
    return res["kpis"], inv, dem, unmet


def run_simulation(policy: str, scenario: str = "baseline", seed: int = 0, days: int = DEFAULT_DAYS) -> dict:
    mapped = POLICY_MAP.get(policy, "forecast_newsvendor")
    kp, inv, dem, unmet = _raw(mapped, scenario, int(seed), int(days))
    service = 1.0 - unmet / np.maximum(dem, 1.0)

    dis = SCENARIO_MAP.get(scenario)
    events, recovery = [], 0
    if dis:
        start, end = dis["start"], dis["start"] + dis["duration"]
        events = [
            {"day": start, "type": "disruption_start", "text": f"Disruption begins ({scenario})"},
            {"day": min(end, days), "type": "disruption_end", "text": "Disruption ends, recovery starts"},
        ]
        pre = service[:start] if start > 0 else service[:1]
        threshold = float(pre.mean()) - 0.02
        after = service[end:] if end < days else np.array([])
        ok = np.where(after >= threshold)[0]
        recovery = int(ok[0]) if len(ok) else int(max(0, days - end))

    return {
        "policy": policy,
        "scenario": scenario,
        "seed": int(seed),
        "timeseries": {
            "day": list(range(days)),
            "inventory": [round(float(v), 1) for v in inv],
            "service": [round(float(v), 4) for v in service],
            "unmet": [round(float(v), 1) for v in unmet],
        },
        "kpis": {
            "total_cost": round(float(kp["total_cost"]), 1),
            "fill_rate": round(float(kp["fill_rate_pct"]) / 100.0, 4),
            "service_level": round(float((service >= 0.9).mean()), 4),
            "unmet_units": round(float(kp["total_unmet"]), 1),
            "recovery_days": recovery,
        },
        "events": events,
    }


def run_monte_carlo(policy: str, scenario: str, n_runs: int = 20, days: int = DEFAULT_DAYS) -> dict:
    # Same seeds (0..n-1) for every policy = common random numbers = fair comparison
    runs = [run_simulation(policy, scenario, seed=i, days=days)["kpis"] for i in range(n_runs)]
    kpi_mean, kpi_ci = {}, {}
    for m in METRICS:
        v = np.array([r[m] for r in runs], dtype=float)
        mu = v.mean()
        half = 1.96 * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0
        kpi_mean[m] = round(float(mu), 4)
        kpi_ci[m] = [round(float(mu - half), 4), round(float(mu + half), 4)]
    return {"policy": policy, "scenario": scenario, "n_runs": n_runs,
            "kpi_mean": kpi_mean, "kpi_ci": kpi_ci}
