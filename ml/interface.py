from ml.simulator import SupplyChainSimTwin
from ml.policies import InventoryPolicies

def run_simulation_experiment(policy_type="forecast_newsvendor", disruption=None, duration_days=60, seed=42):
    policies = InventoryPolicies()
    
    if policy_type == "forecast_newsvendor":
        policy_fn = policies.forecast_driven_newsvendor
    else:
        policy_fn = policies.baseline_fixed_order

    sim = SupplyChainSimTwin(
        policy_fn=policy_fn,
        disruption_config=disruption,
        seed=seed,
        duration_days=duration_days
    )
    results = sim.run()
    return results

if __name__ == "__main__":
    print("Running Baseline Fixed-Order Policy Experiment...")
    base_res = run_simulation_experiment(policy_type="baseline_fixed", duration_days=30)
    print("Baseline KPIs:", base_res["kpis"])

    print("\nRunning Forecast-Driven Newsvendor Policy Experiment...")
    ai_res = run_simulation_experiment(policy_type="forecast_newsvendor", duration_days=30)
    print("AI Forecast-Driven KPIs:", ai_res["kpis"])