import os
import json
import joblib
import numpy as np
import pandas as pd
from ml.feature_engineering import engineer_m5_features, FEATURES
from ml.forecaster import predict_winner_quantiles

ARTIFACTS_DIR = "ml/artifacts"


class InventoryPolicies:
    def __init__(self):
        model_path = os.path.join(ARTIFACTS_DIR, "forecaster_models.joblib")
        self.bundle = joblib.load(model_path) if os.path.exists(model_path) else None

        topo_path = os.path.join(ARTIFACTS_DIR, "network_topology.json")
        self.store_lead_times = {}
        self.store_costs = {}
        if os.path.exists(topo_path):
            with open(topo_path, "r") as f:
                topo = json.load(f)
            for edge in topo.get("edges", []):
                if edge["target"] in topo["metadata"]["stores"]:
                    self.store_lead_times[edge["target"]] = edge["lead_time_mean"]
            for node in topo.get("nodes", []):
                if node["type"] == "store":
                    self.store_costs[node["id"]] = (
                        node.get("holding_cost", 0.50),
                        node.get("stockout_penalty", 5.00),
                    )

        # Precompute blended quantiles for O(1) lookup during SimPy simulation
        csv_path = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
        self.lookup = {}
        if os.path.exists(csv_path) and self.bundle is not None:
            raw_df = pd.read_csv(csv_path, parse_dates=["date"])
            df = engineer_m5_features(raw_df)
            q_preds = predict_winner_quantiles(self.bundle, df)
            df["pred_p10"] = q_preds["p10"]
            df["pred_p50"] = q_preds["p50"]
            df["pred_p90"] = q_preds["p90"]

            for row in df.itertuples():
                d_str = str(row.date.date())
                self.lookup[(row.store_id, row.item_id, d_str)] = (
                    row.pred_p10,
                    row.pred_p50,
                    row.pred_p90,
                    row.demand_type,
                )

    def baseline_fixed_order(self, store, item, current_stock, day, *args, **kwargs):
        """Blind baseline: static reorder point of 30, orders 45 units."""
        if current_stock <= 30:
            return 45
        return 0

    def forecast_driven_newsvendor(self, store, item, current_stock, day, current_date=None, pipeline_qty=0):
        """
        M5 Winner Forecast-Driven Newsvendor Policy:
        Uses Tweedie + Quantile + Empirical Level-12 blended quantiles
        scaled over the clustered warehouse-to-store lead time.
        """
        if not self.lookup or current_date is None:
            return self.baseline_fixed_order(store, item, current_stock, day)

        d_str = str(pd.to_datetime(current_date).date())
        q_info = self.lookup.get((store, item, d_str))
        if q_info is None:
            return self.baseline_fixed_order(store, item, current_stock, day)

        p10, p50, p90, demand_type = q_info

        # Clustered lead time & node-specific cost parameters
        lead_time = self.store_lead_times.get(store, 2.0)
        holding_cost, stockout_penalty = self.store_costs.get(store, (0.50, 5.00))
        critical_ratio = stockout_penalty / (holding_cost + stockout_penalty)

        # Expected demand over lead time + review period (L + 1 days)
        horizon = lead_time + 1.0
        lt_expected_demand = p50 * horizon

        # Uncertainty spread scaled by sqrt(horizon)
        uncertainty_spread = max(1.5, (p90 - p50) * np.sqrt(horizon))
        if demand_type == "intermittent":
            # Extra cushion for intermittent Level-12 skew
            uncertainty_spread *= 1.15

        safety_stock = uncertainty_spread * critical_ratio
        reorder_point = lt_expected_demand + safety_stock
        target_inventory = reorder_point + p50 * 1.5

        inventory_position = current_stock + pipeline_qty
        if inventory_position <= reorder_point:
            order_qty = max(1, int(np.ceil(target_inventory - inventory_position)))
            return order_qty
        return 0