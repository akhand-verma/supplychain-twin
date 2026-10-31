"""MOCK engine. Replaced later by Person A's real simulator package.
Same function names and return shapes as the agreed contract."""
import numpy as np

BASE_SERVICE = {"fixed_order": 0.90, "s_S": 0.93, "newsvendor": 0.955, "newsvendor_milp": 0.965}
BASE_COST = {"fixed_order": 1000, "s_S": 900, "newsvendor": 800, "newsvendor_milp": 760}
RESILIENCE = {"fixed_order": 0.10, "s_S": 0.25, "newsvendor": 0.40, "newsvendor_milp": 0.65}
# scenario -> (severity, start_day, duration_days)
SCENARIO = {
    "baseline": (0.0, 0, 0),
    "supplier_outage": (0.35, 20, 10),
    "transport_delay": (0.20, 20, 8),
    "warehouse_down": (0.30, 20, 7),
    "demand_spike": (0.25, 20, 6),
    "compound": (0.50, 20, 12),
}
METRICS = ["total_cost", "fill_rate", "service_level", "unmet_units", "recovery_days"]


def run_simulation(policy: str, scenario: str, seed: int = 0, days: int = 60) -> dict:
    rng = np.random.default_rng(seed)
    sev, start, dur = SCENARIO[scenario]
    res = RESILIENCE[policy]
    base = BASE_SERVICE[policy]
    t = np.arange(days)
    end = start + dur

    dip = np.zeros(days)
    if sev > 0:
        amp = sev * (1 - res)
        during = (t >= start) & (t < end)
        after = t >= end
        dip[during] = amp * (t[during] - start + 1) / dur
        dip[after] = amp * np.exp(-(t[after] - end + 1) / (3.0 * (1 - 0.5 * res)))

    service = np.clip(base - 1.2 * dip + 0.01 * rng.standard_normal(days), 0, 1)
    inventory = np.clip(1000 * (1 + 0.04 * rng.standard_normal(days)) * (1 - dip), 0, None)
    demand = 300 * (1 + 0.1 * rng.standard_normal(days))
    unmet = demand * (1 - service)

    recovery = 0
    if sev > 0:
        ok = np.where(service[end:] >= base - 0.02)[0]
        recovery = int(ok[0]) if len(ok) else int(days - end)

    total_cost = BASE_COST[policy] * days * (1 + 0.03 * rng.standard_normal()) + 20 * unmet.sum()

    events = []
    if sev > 0:
        events = [
            {"day": start, "type": "disruption_start", "text": f"Disruption begins ({scenario})"},
            {"day": end, "type": "disruption_end", "text": "Disruption ends, recovery starts"},
        ]
    return {
        "policy": policy,
        "scenario": scenario,
        "seed": seed,
        "timeseries": {
            "day": t.tolist(),
            "inventory": [round(float(v), 1) for v in inventory],
            "service": [round(float(v), 4) for v in service],
            "unmet": [round(float(v), 1) for v in unmet],
        },
        "kpis": {
            "total_cost": round(float(total_cost), 1),
            "fill_rate": round(float(service.mean()), 4),
            "service_level": round(float((service >= 0.9).mean()), 4),
            "unmet_units": round(float(unmet.sum()), 1),
            "recovery_days": recovery,
        },
        "events": events,
    }


def run_monte_carlo(policy: str, scenario: str, n_runs: int = 100) -> dict:
    # Same seeds (0..n-1) for every policy = common random numbers = fair comparison
    runs = [run_simulation(policy, scenario, seed=i)["kpis"] for i in range(n_runs)]
    kpi_mean, kpi_ci = {}, {}
    for m in METRICS:
        v = np.array([r[m] for r in runs], dtype=float)
        mu = v.mean()
        half = 1.96 * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0
        kpi_mean[m] = round(float(mu), 4)
        kpi_ci[m] = [round(float(mu - half), 4), round(float(mu + half), 4)]
    return {"policy": policy, "scenario": scenario, "n_runs": n_runs,
            "kpi_mean": kpi_mean, "kpi_ci": kpi_ci}