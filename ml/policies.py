import os
import joblib
import pandas as pd

ARTIFACTS_DIR = "ml/artifacts"

class InventoryPolicies:
    def __init__(self):
        # Load LightGBM forecaster bundle
        model_path = os.path.join(ARTIFACTS_DIR, "forecaster_models.joblib")
        if os.path.exists(model_path):
            bundle = joblib.load(model_path)
            self.models = bundle["models"]
            self.features = bundle["features"]
        else:
            self.models = None

        # Load historical dataset and engineer lag features for lookup
        csv_path = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path, parse_dates=["date"])
            df = df.sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)
            
            # Engineer features so policy lookup matches training features
            df["lag_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(7)
            df["lag_14"] = df.groupby(["store_id", "item_id"])["demand"].shift(14)
            df["lag_28"] = df.groupby(["store_id", "item_id"])["demand"].shift(28)
            
            df["rolling_mean_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(7).mean().reset_index(0, drop=True)
            df["rolling_std_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(7).std().reset_index(0, drop=True)
            df["rolling_mean_28"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(28).mean().reset_index(0, drop=True)
            
            self.demand_df = df
        else:
            self.demand_df = None

    def baseline_fixed_order(self, store, item, current_stock, day, *args, **kwargs):
        """Blind baseline: static reorder point of 30, orders 45 units."""
        if current_stock <= 30:
            return 45
        return 0

    def forecast_driven_newsvendor(self, store, item, current_stock, day, current_date=None):
        """
        Forecast-driven policy: queries P10, P50, P90 quantiles 
        for the exact simulation date and sets reorder points dynamically.
        """
        if not self.models or self.demand_df is None:
            return self.baseline_fixed_order(store, item, current_stock, day)

        # Filter by store, item, and exact simulation date
        sub = self.demand_df[
            (self.demand_df["store_id"] == store) & 
            (self.demand_df["item_id"] == item)
        ]
        
        if current_date is not None:
            row = sub[sub["date"] == pd.to_datetime(current_date)]
        else:
            row = sub.iloc[[min(day, len(sub) - 1)]]

        if row.empty:
            return self.baseline_fixed_order(store, item, current_stock, day)
        
        feat_row = row[self.features].fillna(0)

        # Predict quantiles
        p10 = max(0.0, float(self.models["p10"].predict(feat_row)[0]))
        p50 = max(0.0, float(self.models["p50"].predict(feat_row)[0]))
        p90 = max(0.0, float(self.models["p90"].predict(feat_row)[0]))

        # Newsvendor critical ratio: Penalty / (Holding + Penalty)
        holding_cost = 0.50
        stockout_penalty = 5.00
        critical_ratio = stockout_penalty / (holding_cost + stockout_penalty)

        # Dynamic safety stock driven by P90 uncertainty band
        safety_stock = max(2.0, p90 - p50)
        reorder_point = p50 + safety_stock
        target_inventory = p90 + (safety_stock * critical_ratio)

        if current_stock <= reorder_point:
            order_qty = max(10, int(target_inventory - current_stock))
            return order_qty
        return 0