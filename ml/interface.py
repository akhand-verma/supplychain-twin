import numpy as np
from ml.simulator import SupplyChainSimTwin
from ml.policies import InventoryPolicies
from ml.optimizer import SupplyChainOptimizer

# Singleton policy loader so FastAPI doesn't reload joblib on every Monte Carlo iteration
_POLICIES_INSTANCE = None


def get_policies():
    global _POLICIES_INSTANCE
    if _POLICIES_INSTANCE is None:
        _POLICIES_INSTANCE = InventoryPolicies()
    return _POLICIES_INSTANCE


def run_simulation_experiment(
    policy_type="forecast_newsvendor", disruption=None, duration_days=60, seed=42
):
    policies = get_policies()

    if policy_type in ("forecast_newsvendor", "newsvendor", "sS", "milp"):
        policy_fn = policies.forecast_driven_newsvendor
    else:
        policy_fn = policies.baseline_fixed_order

    sim = SupplyChainSimTwin(
        policy_fn=policy_fn,
        disruption_config=disruption,
        seed=seed,
        duration_days=duration_days,
    )
    return sim.run()


def run_monte_carlo_experiment(
    policy_type="forecast_newsvendor", disruption=None, n_runs=20, duration_days=30
):
    """Runs N stochastic replications across different seeds and computes 95% CIs."""
    metrics_list = []
    for i in range(n_runs):
        res = run_simulation_experiment(
            policy_type=policy_type,
            disruption=disruption,
            duration_days=duration_days,
            seed=42 + i * 7,
        )
        metrics_list.append(res["kpis"])

    summary = {}
    for k in metrics_list[0].keys():
        vals = np.array([m[k] for m in metrics_list], dtype=float)
        mean_val = float(np.mean(vals))
        std_err = float(np.std(vals) / max(1.0, np.sqrt(n_runs)))
        summary[k] = {
            "mean": round(mean_val, 2),
            "ci_low": round(mean_val - 1.96 * std_err, 2),
            "ci_high": round(mean_val + 1.96 * std_err, 2),
        }
    return {"policy": policy_type, "n_runs": n_runs, "kpis": summary}


if __name__ == "__main__":
    print("Running Baseline Fixed-Order Policy Experiment...")
    base_res = run_simulation_experiment(policy_type="baseline_fixed", duration_days=30)
    print("Baseline KPIs:", base_res["kpis"])

    print("\nRunning Forecast-Driven Newsvendor Policy Experiment...")
    ai_res = run_simulation_experiment(policy_type="forecast_newsvendor", duration_days=30)
    print("AI Forecast-Driven KPIs:", ai_res["kpis"])