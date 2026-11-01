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
        self.disruption = disruption_config
        self.seed = seed
        self.duration_days = duration_days
        self.rng = random.Random(seed)
        self.np_rng = np.random.default_rng(seed)

        with open(os.path.join(ARTIFACTS_DIR, "network_topology.json"), "r") as f:
            self.topology = json.load(f)

        self.demand_df = pd.read_csv(
            os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv"), parse_dates=["date"]
        )

        self.stores = self.topology["metadata"]["stores"]
        self.items = self.topology["metadata"]["all_items"]

        # Map clustered lead times and store-specific costs from topology
        self.edge_params = {}
        for edge in self.topology.get("edges", []):
            if edge["target"] in self.stores:
                self.edge_params[edge["target"]] = (
                    edge["lead_time_mean"],
                    edge["lead_time_std"],
                    edge["transport_cost"],
                )

        self.node_costs = {}
        for node in self.topology.get("nodes", []):
            if node["type"] == "store":
                self.node_costs[node["id"]] = (
                    node.get("holding_cost", 0.50),
                    node.get("stockout_penalty", 5.00),
                )

        self.inventory = {store: {item: 150 for item in self.items} for store in self.stores}
        self.pipeline_orders = []
        self.logs = []

        self.total_cost = 0.0
        self.total_demand = 0
        self.total_unmet = 0
        self.stockout_incidents = 0

    def setup(self):
        self.env.process(self._simulation_loop())

    def _simulation_loop(self):
        unique_dates = sorted(self.demand_df["date"].unique())
        sim_dates = unique_dates[-self.duration_days:]

        for day_idx, current_date in enumerate(sim_dates):
            is_disrupted = False
            if self.disruption:
                start = self.disruption.get("start", 5)
                duration = self.disruption.get("duration", 10)
                if start <= day_idx < (start + duration):
                    is_disrupted = True

            arrived = [o for o in self.pipeline_orders if o["arrival_day"] <= day_idx]
            for order in arrived:
                self.inventory[order["store"]][order["item"]] += order["qty"]
            self.pipeline_orders = [o for o in self.pipeline_orders if o["arrival_day"] > day_idx]

            daily_holding = 0.0
            daily_penalty = 0.0

            day_demand_df = self.demand_df[self.demand_df["date"] == current_date]

            for store in self.stores:
                store_slice = day_demand_df[day_demand_df["store_id"] == store]
                h_cost_unit, p_cost_unit = self.node_costs.get(store, (0.50, 5.00))
                lt_mean, lt_std, _ = self.edge_params.get(store, (2.0, 0.5, 0.40))

                for item in self.items:
                    item_row = store_slice[store_slice["item_id"] == item]
                    if not item_row.empty:
                        true_demand = int(item_row["demand"].values[0])
                    else:
                        true_demand = int(self.np_rng.poisson(25))

                    self.total_demand += true_demand

                    available = self.inventory[store][item]
                    served = min(available, true_demand)
                    unmet = true_demand - served

                    self.inventory[store][item] -= served
                    self.total_unmet += unmet
                    if unmet > 0:
                        self.stockout_incidents += 1

                    holding_cost = self.inventory[store][item] * h_cost_unit
                    penalty_cost = unmet * p_cost_unit
                    daily_holding += holding_cost
                    daily_penalty += penalty_cost

                    self.logs.append({
                        "day": day_idx,
                        "date": str(current_date.date()),
                        "store_id": store,
                        "item_id": item,
                        "inventory": self.inventory[store][item],
                        "demand": true_demand,
                        "unmet_demand": unmet,
                        "daily_cost": round(holding_cost + penalty_cost, 2),
                    })

                    # Calculate in-transit pipeline stock for this store-item
                    pipeline_qty = sum(
                        o["qty"] for o in self.pipeline_orders
                        if o["store"] == store and o["item"] == item
                    )

                    order_qty = self.policy_fn(
                        store, item, self.inventory[store][item], day_idx, current_date, pipeline_qty
                    )
                    if order_qty > 0:
                        effective_lead = lt_mean * (3.0 if is_disrupted else 1.0)
                        actual_lead = max(1, int(round(self.np_rng.normal(effective_lead, lt_std))))

                        self.pipeline_orders.append({
                            "store": store,
                            "item": item,
                            "qty": order_qty,
                            "arrival_day": day_idx + actual_lead,
                        })

            self.total_cost += (daily_holding + daily_penalty)
            yield self.env.timeout(1)

    def run(self):
        self.setup()
        self.env.run(until=self.duration_days)

        fill_rate = ((self.total_demand - self.total_unmet) / max(1, self.total_demand)) * 100.0
        service_level = max(0.0, 100.0 - (self.stockout_incidents / max(1, len(self.logs)) * 100.0))

        return {
            "kpis": {
                "total_cost": round(float(self.total_cost), 2),
                "total_demand": int(self.total_demand),
                "total_unmet": int(self.total_unmet),
                "fill_rate_pct": round(float(fill_rate), 2),
                "service_level_pct": round(float(service_level), 2),
                "stockout_incidents": int(self.stockout_incidents),
            },
            "timeseries": self.logs,
        }