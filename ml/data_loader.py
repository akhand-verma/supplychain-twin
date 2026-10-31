import os
import json
import numpy as np
import pandas as pd

RAW_DIR = "raw_m5"
ARTIFACTS_DIR = "ml/artifacts"
STORES = ["CA_1", "CA_2", "TX_1", "TX_2", "WI_1", "WI_2"]
DAYS_TO_KEEP = 365


def build_subset_and_network():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    # 1. Locate raw sales file
    eval_path = os.path.join(RAW_DIR, "sales_train_evaluation.csv")
    valid_path = os.path.join(RAW_DIR, "sales_train_validation.csv")
    sales_path = eval_path if os.path.exists(eval_path) else valid_path

    if not os.path.exists(sales_path):
        raise FileNotFoundError(f"Could not find M5 sales file in {RAW_DIR}/")

    print(f"Loading and filtering {sales_path} for stores {STORES}...")
    sales_df = pd.read_csv(sales_path)
    sales_df = sales_df[sales_df["store_id"].isin(STORES)].copy()

    # Identify the last 365 day columns (e.g., d_1549 to d_1913)
    day_cols = [c for c in sales_df.columns if c.startswith("d_")][-DAYS_TO_KEEP:]

    # 2. Select 8 high-volume items + 2 intermittent items (present across all 6 stores)
    sales_df["total_vol"] = sales_df[day_cols].sum(axis=1)
    sales_df["zero_rate"] = (sales_df[day_cols] == 0).mean(axis=1)

    item_stats = (
        sales_df.groupby(["item_id", "cat_id", "dept_id"])
        .agg(
            mean_vol=("total_vol", "mean"),
            mean_zero_rate=("zero_rate", "mean"),
            store_count=("store_id", "nunique"),
        )
        .reset_index()
    )
    item_stats = item_stats[item_stats["store_count"] == len(STORES)]

    # Top 8 steady high-volume items (zero_rate < 15%)
    high_vol_items = (
        item_stats[item_stats["mean_zero_rate"] < 0.15]
        .sort_values("mean_vol", ascending=False)
        .head(8)["item_id"]
        .tolist()
    )

    # 2 intermittent items (zero_rate between 45% and 70%, still actively sold)
    intermittent_items = (
        item_stats[
            (item_stats["mean_zero_rate"] >= 0.45)
            & (item_stats["mean_zero_rate"] <= 0.70)
        ]
        .sort_values("mean_vol", ascending=False)
        .head(2)["item_id"]
        .tolist()
    )

    selected_items = high_vol_items + intermittent_items
    print(f"Selected 8 High-Volume Items: {high_vol_items}")
    print(f"Selected 2 Intermittent Items: {intermittent_items}")

    # Filter down to 60 rows (6 stores x 10 items) BEFORE melting
    id_cols = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]
    filtered_sales = sales_df[sales_df["item_id"].isin(selected_items)][
        id_cols + day_cols
    ]

    # 3. Melt wide days into long format (21,900 rows)
    long_df = filtered_sales.melt(
        id_vars=id_cols, var_name="d", value_name="demand"
    )
    long_df["demand_type"] = np.where(
        long_df["item_id"].isin(intermittent_items),
        "intermittent",
        "high_volume",
    )

    # 4. Merge Calendar features
    print("Merging calendar and pricing data...")
    cal_cols = [
        "d",
        "date",
        "wm_yr_wk",
        "wday",
        "month",
        "year",
        "event_name_1",
        "event_type_1",
        "snap_CA",
        "snap_TX",
        "snap_WI",
    ]
    cal_df = pd.read_csv(os.path.join(RAW_DIR, "calendar.csv"), usecols=cal_cols)
    cal_df = cal_df[cal_df["d"].isin(day_cols)]
    long_df = long_df.merge(cal_df, on="d", how="left")

    # Map state-specific SNAP promotional flag and holiday events
    long_df["is_promo"] = np.select(
        [
            long_df["state_id"] == "CA",
            long_df["state_id"] == "TX",
            long_df["state_id"] == "WI",
        ],
        [long_df["snap_CA"], long_df["snap_TX"], long_df["snap_WI"]],
        default=0,
    )
    long_df["is_holiday"] = long_df["event_name_1"].notna().astype(int)

    # 5. Merge Sell Prices (filtered first to keep RAM footprint tiny)
    prices_df = pd.read_csv(os.path.join(RAW_DIR, "sell_prices.csv"))
    prices_df = prices_df[
        (prices_df["store_id"].isin(STORES))
        & (prices_df["item_id"].isin(selected_items))
    ]
    long_df = long_df.merge(
        prices_df, on=["store_id", "item_id", "wm_yr_wk"], how="left"
    )
    long_df["sell_price"] = long_df.groupby(["store_id", "item_id"])[
        "sell_price"
    ].bfill().ffill()

    # Clean and sort final dataset
    keep_cols = [
        "date",
        "d",
        "store_id",
        "state_id",
        "item_id",
        "cat_id",
        "demand_type",
        "demand",
        "sell_price",
        "is_promo",
        "is_holiday",
        "wday",
        "month",
    ]
    long_df = (
        long_df[keep_cols]
        .sort_values(["store_id", "item_id", "date"])
        .reset_index(drop=True)
    )

    csv_out = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
    long_df.to_csv(csv_out, index=False)
    print(f"Saved {len(long_df):,} rows to {csv_out}")

    # 6. Build Synthetic Supply Network Topology scaled to real item demand
    avg_store_daily = float(long_df.groupby(["store_id", "date"])["demand"].sum().mean())

    network_topology = {
        "nodes": [
            {
                "id": "SUP_1",
                "name": "Primary National Supplier",
                "type": "supplier",
                "capacity_units": int(avg_store_daily * 120),
                "reliability": 0.96,
            },
            {
                "id": "SUP_2",
                "name": "Regional Backup Supplier",
                "type": "supplier",
                "capacity_units": int(avg_store_daily * 80),
                "reliability": 0.92,
            },
            {
                "id": "WH_WEST",
                "name": "California Distribution Hub",
                "type": "warehouse",
                "capacity_units": int(avg_store_daily * 45),
                "holding_cost": 0.25,
            },
            {
                "id": "WH_CENTRAL",
                "name": "Central & Midwest Hub",
                "type": "warehouse",
                "capacity_units": int(avg_store_daily * 65),
                "holding_cost": 0.22,
            },
        ]
        + [
            {
                "id": store,
                "name": f"Retail Store {store}",
                "type": "store",
                "state": store.split("_")[0],
                "capacity_units": int(avg_store_daily * 14),
                "holding_cost": 0.50,
                "stockout_penalty": 5.00,
                "ordering_cost": 25.00,
            }
            for store in STORES
        ],
        "edges": [
            {"source": "SUP_1", "target": "WH_WEST", "lead_time_mean": 5.0, "lead_time_std": 1.2, "transport_cost": 0.80},
            {"source": "SUP_1", "target": "WH_CENTRAL", "lead_time_mean": 4.0, "lead_time_std": 1.0, "transport_cost": 0.75},
            {"source": "SUP_2", "target": "WH_WEST", "lead_time_mean": 3.0, "lead_time_std": 0.8, "transport_cost": 1.15},
            {"source": "SUP_2", "target": "WH_CENTRAL", "lead_time_mean": 3.0, "lead_time_std": 0.8, "transport_cost": 1.10},
            {"source": "WH_WEST", "target": "CA_1", "lead_time_mean": 2.0, "lead_time_std": 0.5, "transport_cost": 0.40},
            {"source": "WH_WEST", "target": "CA_2", "lead_time_mean": 2.0, "lead_time_std": 0.5, "transport_cost": 0.45},
            {"source": "WH_CENTRAL", "target": "TX_1", "lead_time_mean": 2.0, "lead_time_std": 0.6, "transport_cost": 0.45},
            {"source": "WH_CENTRAL", "target": "TX_2", "lead_time_mean": 2.0, "lead_time_std": 0.6, "transport_cost": 0.50},
            {"source": "WH_CENTRAL", "target": "WI_1", "lead_time_mean": 3.0, "lead_time_std": 0.7, "transport_cost": 0.55},
            {"source": "WH_CENTRAL", "target": "WI_2", "lead_time_mean": 3.0, "lead_time_std": 0.7, "transport_cost": 0.60},
        ],
        "metadata": {
            "stores": STORES,
            "high_volume_items": high_vol_items,
            "intermittent_items": intermittent_items,
            "all_items": selected_items,
        },
    }

    net_out = os.path.join(ARTIFACTS_DIR, "network_topology.json")
    with open(net_out, "w") as f:
        json.dump(network_topology, f, indent=2)
    print(f"Saved network topology to {net_out}")


if __name__ == "__main__":
    build_subset_and_network()