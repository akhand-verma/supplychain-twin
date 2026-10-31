import os
import json
import random
import simpy
import numpy as np
import pandas as pd

ARTIFACTS_DIR = "ml/artifacts"

class SupplyChainSimTwin:
    def __init__(self, policy_fn, disruption_config=None, seed=42, duration_days=60):
        self.env = simpy.Environment()
        self.policy_fn = policy_fn
        self.disruption = disruption_config  # e.g., {'type': 'supplier_strike', 'target': 'SUP_1', 'start': 10, 'duration': 14}
        self.seed = seed
        self.duration_days = duration_days
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        # Load Topology & Demand
        with open(os.path.join(ARTIFACTS_DIR, "network_topology.json"), "r") as f:
            self.topology = json.load(f)
            
        self.demand_df = pd.read_csv(os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv"), parse_dates=["date"])
        
        # Initialize state
        self.stores = self.topology["metadata"]["stores"]
        self.items = self.topology["metadata"]["all_items"]
        
        # Inventory per store-item: start with 150 units each
        self.inventory = {store: {item: 150 for item in self.items} for store in self.stores}
        self.pipeline_orders = [] # list of dicts: arrival_day, store, item, qty
        self.logs = []
        
        # Metrics tracking
        self.total_cost = 0.0
        self.total_demand = 0
        self.total_unmet = 0
        self.stockout_incidents = 0

    def setup(self):
        self.env.process(self._simulation_loop())

    def _simulation_loop(self):
        # Filter demand to the evaluation test period (last duration_days)
        unique_dates = sorted(self.demand_df["date"].unique())
        sim_dates = unique_dates[-self.duration_days:]

        for day_idx, current_date in enumerate(sim_dates):
            # 1. Check Disruption Status
            is_disrupted = False
            if self.disruption:
                start = self.disruption.get("start", 5)
                duration = self.disruption.get("duration", 10)
                if start <= day_idx < (start + duration):
                    is_disrupted = True

            # 2. Receive Arrived Shipments
            arrived = [o for o in self.pipeline_orders if o["arrival_day"] <= day_idx]
            for order in arrived:
                self.inventory[order["store"]][order["item"]] += order["qty"]
            self.pipeline_orders = [o for o in self.pipeline_orders if o["arrival_day"] > day_idx]

            # 3. Process Daily Demand & Replenishment per Store & Item
            daily_holding = 0.0
            daily_penalty = 0.0

            # Get demand slice for this date
            day_demand_df = self.demand_df[self.demand_df["date"] == current_date]

            for store in self.stores:
                store_slice = day_demand_df[day_demand_df["store_id"] == store]
                
                for item in self.items:
                    item_row = store_slice[store_slice["item_id"] == item]
                    if not item_row.empty:
                        true_demand = int(item_row["demand"].values[0])
                    else:
                        true_demand = int(self.np_rng.poisson(25)) # fallback

                    self.total_demand += true_demand

                    # Fulfill demand from available inventory
                    available = self.inventory[store][item]
                    served = min(available, true_demand)
                    unmet = true_demand - served
                    
                    self.inventory[store][item] -= served
                    self.total_unmet += unmet
                    if unmet > 0:
                        self.stockout_incidents += 1

                    # Costs
                    holding_cost = self.inventory[store][item] * 0.50
                    penalty_cost = unmet * 5.00
                    daily_holding += holding_cost
                    daily_penalty += penalty_cost

                    # Log state
                    self.logs.append({
                        "day": day_idx,
                        "date": str(current_date.date()),
                        "store_id": store,
                        "item_id": item,
                        "inventory": self.inventory[store][item],
                        "demand": true_demand,
                        "unmet_demand": unmet,
                        "daily_cost": holding_cost + penalty_cost
                    })

                    # 4. Trigger Policy Order Decision
                    order_qty = self.policy_fn(store, item, self.inventory[store][item], day_idx, current_date)
                    if order_qty > 0:
                        base_lead = 3 # default days
                        lead_time = base_lead * (3 if is_disrupted else 1)
                        # Add stochastic noise to lead time
                        actual_lead = max(1, int(self.np_rng.normal(lead_time, 0.5)))
                        
                        self.pipeline_orders.append({
                            "store": store,
                            "item": item,
                            "qty": order_qty,
                            "arrival_day": day_idx + actual_lead
                        })

            self.total_cost += (daily_holding + daily_penalty)
            yield self.env.timeout(1)

    def run(self):
        self.setup()
        self.env.run(until=self.duration_days)
        
        fill_rate = ((self.total_demand - self.total_unmet) / max(1, self.total_demand)) * 100.0
        service_level = max(0.0, 100.0 - (self.stockout_incidents / max(1, len(self.logs)) * 100.0))

        results = {
            "kpis": {
                "total_cost": round(float(self.total_cost), 2),
                "total_demand": int(self.total_demand),
                "total_unmet": int(self.total_unmet),
                "fill_rate_pct": round(float(fill_rate), 2),
                "service_level_pct": round(float(service_level), 2),
                "stockout_incidents": int(self.stockout_incidents)
            },
            "timeseries": self.logs
        }
        return results

if __name__ == "__main__":
    # Quick sanity test with a dummy policy
    dummy_policy = lambda store, item, stock, day: 40 if stock < 30 else 0
    sim = SupplyChainSimTwin(policy_fn=dummy_policy, duration_days=30)
    res = sim.run()
    print("SimPy Simulation Sanity Test Results:")
    print(json.dumps(res["kpis"], indent=2))