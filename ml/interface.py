import numpy as np
from ml.simulator import SupplyChainSimTwin
from ml.policies import InventoryPolicies
from ml.optimizer import SupplyChainOptimizer

_POLICIES_INSTANCE = None

def get_policies():
    global _POLICIES_INSTANCE
    if _POLICIES_INSTANCE is None:
        _POLICIES_INSTANCE = InventoryPolicies()
    return _POLICIES_INSTANCE

SCENARIO_MAP = {
    "baseline": None,
    "normal": None,
    "supplier_strike": {"type": "supplier_strike", "target": "SUP_1", "start": 5, "duration": 14},
    "supplier_failure": {"type": "supplier_strike", "target": "SUP_1", "start": 5, "duration": 14},
    "transport_delay": {"type": "transport_delay", "target": "WH_WEST", "start": 8, "duration": 10},
    "demand_spike": {"type": "demand_spike", "target": "ALL", "start": 10, "duration": 7},
}

POLICY_MAP = {
    "newsvendor": "forecast_newsvendor",
    "forecast_newsvendor": "forecast_newsvendor",
    "sS": "forecast_newsvendor",
    "milp": "forecast_newsvendor",
    "baseline": "baseline_fixed",
    "fixed": "baseline_fixed",
    "baseline_fixed": "baseline_fixed",
}

def run_simulation_experiment(policy_type="forecast_newsvendor", disruption=None, duration_days=30, seed=42):
    policies = get_policies()
    mapped = POLICY_MAP.get(policy_type, "forecast_newsvendor")
    policy_fn = policies.forecast_driven_newsvendor if mapped == "forecast_newsvendor" else policies.baseline_fixed_order

    sim = SupplyChainSimTwin(
        policy_fn=policy_fn,
        disruption_config=disruption,
        seed=seed,
        duration_days=duration_days,
    )
    res = sim.run()

    # Aggregate daily logs for React frontend charts
    daily_agg = {}
    for row in res["timeseries"]:
        d = row["day"]
        if d not in daily_agg:
            daily_agg[d] = {
                "day": d,
                "date": row["date"],
                "inventory": 0,
                "demand": 0,
                "unmet_demand": 0,
                "daily_cost": 0.0,
            }
        daily_agg[d]["inventory"] += row["inventory"]
        daily_agg[d]["demand"] += row["demand"]
        daily_agg[d]["unmet_demand"] += row["unmet_demand"]
        daily_agg[d]["daily_cost"] = round(daily_agg[d]["daily_cost"] + row["daily_cost"], 2)

    # Run MILP optimizer on final day snapshot
    opt = SupplyChainOptimizer()
    last_day = max(daily_agg.keys()) if daily_agg else 0
    last_rows = [r for r in res["timeseries"] if r["day"] == last_day]
    curr_inv = {"WH_WEST": 500, "WH_CENTRAL": 600}
    curr_dem = {}
    for r in last_rows:
        s = r["store_id"]
        curr_inv[s] = curr_inv.get(s, 0) + r["inventory"]
        curr_dem[s] = curr_dem.get(s, 0) + max(20, r["demand"])
    opt_res = opt.optimize_redistribution(curr_inv, curr_dem)

    res["summary"] = res["kpis"]
    res["daily"] = list(daily_agg.values())
    res["redistribution"] = opt_res
    return res

def run_simulation(policy: str, scenario: str = "baseline", seed: int = 42, duration_days: int = 30):
    """Drop-in replacement for mock_engine.run_simulation called by routes_sim.py."""
    disruption = SCENARIO_MAP.get(scenario, None)
    res = run_simulation_experiment(
        policy_type=policy,
        disruption=disruption,
        duration_days=duration_days,
        seed=seed,
    )
    res["policy"] = policy
    res["scenario"] = scenario
    res["seed"] = seed
    return res

def run_monte_carlo(policy: str, scenario: str = "baseline", n_runs: int = 10, duration_days: int = 30):
    """Drop-in replacement for mock_engine.run_monte_carlo called by routes_sim.py."""
    disruption = SCENARIO_MAP.get(scenario, None)
    runs_kpis = []
    for i in range(n_runs):
        res = run_simulation_experiment(
            policy_type=policy,
            disruption=disruption,
            duration_days=duration_days,
            seed=42 + i * 7,
        )
        runs_kpis.append(res["kpis"])

    metrics = {}
    for k in runs_kpis[0].keys():
        vals = np.array([r[k] for r in runs_kpis], dtype=float)
        mean_val = float(np.mean(vals))
        se = float(np.std(vals) / max(1.0, np.sqrt(n_runs)))
        metrics[k] = {
            "mean": round(mean_val, 2),
            "ci_low": round(mean_val - 1.96 * se, 2),
            "ci_high": round(mean_val + 1.96 * se, 2),
        }

    return {
        "policy": policy,
        "scenario": scenario,
        "n_runs": n_runs,
        "kpis": metrics,
        "metrics": metrics,
    }

if __name__ == "__main__":
    print("Running Baseline Fixed-Order Policy Experiment...")
    base_res = run_simulation_experiment(policy_type="baseline_fixed", duration_days=30)
    print("Baseline KPIs:", base_res["kpis"])

    print("\nRunning Forecast-Driven Newsvendor Policy Experiment...")
    ai_res = run_simulation_experiment(policy_type="forecast_newsvendor", duration_days=30)
    print("AI Forecast-Driven KPIs:", ai_res["kpis"])