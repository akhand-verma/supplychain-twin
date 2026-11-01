import os
import json
import numpy as np
import pandas as pd

RAW_DIR = "data/raw" if os.path.exists("data/raw") else "raw_m5"
ARTIFACTS_DIR = "ml/artifacts"
STORES = ["CA_1", "CA_2", "TX_1", "TX_2", "WI_1", "WI_2"]
DAYS_TO_KEEP = 365

# Approximate real geographical coordinates for stores and suppliers
STORE_COORDS = {
    "CA_1": (34.05, -118.24),  # Los Angeles, CA
    "CA_2": (37.77, -122.41),  # San Francisco, CA
    "TX_1": (29.76, -95.36),   # Houston, TX
    "TX_2": (32.77, -96.79),   # Dallas, TX
    "WI_1": (43.03, -87.90),   # Milwaukee, WI
    "WI_2": (43.07, -89.40),   # Madison, WI
}

SUPPLIER_COORDS = {
    "SUP_1": (39.73, -104.99), # Denver National Hub
    "SUP_2": (35.14, -90.04),  # Memphis Regional Hub
}


def euclidean_km(coord1, coord2):
    """Approximates distance in km between two (lat, lon) points."""
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * np.cos(np.radians((lat1 + lat2) / 2.0))
    return float(np.sqrt(dlat**2 + dlon**2))


def cluster_stores_to_warehouses(store_demands: dict, k: int = 2, iterations: int = 15):
    """
    Demand-weighted K-Means clustering:
    Finds optimal warehouse centers for store clusters and computes distance-based costs.
    """
    store_ids = list(STORE_COORDS.keys())
    coords = np.array([STORE_COORDS[s] for s in store_ids])
    weights = np.array([max(1.0, store_demands.get(s, 100.0)) for s in store_ids])

    # Initialize centroids using West vs Central/Midwest split
    centroids = np.array([
        coords[0],  # Seed 0 near CA
        coords[2],  # Seed 1 near TX/WI
    ], dtype=float)

    labels = np.zeros(len(store_ids), dtype=int)

    for _ in range(iterations):
        # Assign each store to closest warehouse centroid
        dists = np.linalg.norm(coords[:, None, :] - centroids[None, :, :], axis=2)
        labels = np.argmin(dists, axis=1)

        # Update centroids weighted by store demand
        for idx in range(k):
            mask = labels == idx
            if np.any(mask):
                w = weights[mask][:, None]
                centroids[idx] = np.sum(coords[mask] * w, axis=0) / np.sum(w)

    wh_names = ["WH_WEST", "WH_CENTRAL"]
    warehouses = {}
    assignments = {}

    for idx in range(k):
        wh_id = wh_names[idx]
        warehouses[wh_id] = (float(centroids[idx][0]), float(centroids[idx][1]))

    for s_idx, s_id in enumerate(store_ids):
        wh_id = wh_names[labels[s_idx]]
        assignments[s_id] = wh_id

    return warehouses, assignments


def build_subset_and_network():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    eval_path = os.path.join(RAW_DIR, "sales_train_evaluation.csv")
    valid_path = os.path.join(RAW_DIR, "sales_train_validation.csv")
    sales_path = eval_path if os.path.exists(eval_path) else valid_path

    if not os.path.exists(sales_path):
        raise FileNotFoundError(f"Could not find M5 sales file in {RAW_DIR}/")

    print(f"Loading and filtering {sales_path} for stores {STORES}...")
    sales_df = pd.read_csv(sales_path)
    sales_df = sales_df[sales_df["store_id"].isin(STORES)].copy()

    day_cols = [c for c in sales_df.columns if c.startswith("d_")][-DAYS_TO_KEEP:]

    # Stratified selection: 8 high-volume + 2 intermittent items
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

    high_vol_items = (
        item_stats[item_stats["mean_zero_rate"] < 0.15]
        .sort_values("mean_vol", ascending=False)
        .head(8)["item_id"]
        .tolist()
    )

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

    id_cols = ["item_id", "dept_id", "cat_id", "store_id", "state_id"]
    filtered_sales = sales_df[sales_df["item_id"].isin(selected_items)][id_cols + day_cols]

    long_df = filtered_sales.melt(id_vars=id_cols, var_name="d", value_name="demand")
    long_df["demand_type"] = np.where(
        long_df["item_id"].isin(intermittent_items), "intermittent", "high_volume"
    )

    print("Merging calendar and pricing data...")
    cal_cols = [
        "d", "date", "wm_yr_wk", "wday", "month", "year",
        "event_name_1", "event_type_1", "snap_CA", "snap_TX", "snap_WI"
    ]
    cal_df = pd.read_csv(os.path.join(RAW_DIR, "calendar.csv"), usecols=cal_cols)
    cal_df = cal_df[cal_df["d"].isin(day_cols)]
    long_df = long_df.merge(cal_df, on="d", how="left")

    long_df["is_promo"] = np.select(
        [long_df["state_id"] == "CA", long_df["state_id"] == "TX", long_df["state_id"] == "WI"],
        [long_df["snap_CA"], long_df["snap_TX"], long_df["snap_WI"]],
        default=0,
    )
    long_df["is_holiday"] = long_df["event_name_1"].notna().astype(int)

    prices_df = pd.read_csv(os.path.join(RAW_DIR, "sell_prices.csv"))
    prices_df = prices_df[
        (prices_df["store_id"].isin(STORES)) & (prices_df["item_id"].isin(selected_items))
    ]
    long_df = long_df.merge(prices_df, on=["store_id", "item_id", "wm_yr_wk"], how="left")
    long_df["sell_price"] = long_df.groupby(["store_id", "item_id"])["sell_price"].bfill().ffill()

    keep_cols = [
        "date", "d", "store_id", "state_id", "item_id", "cat_id",
        "demand_type", "demand", "sell_price", "is_promo", "is_holiday", "wday", "month"
    ]
    long_df = long_df[keep_cols].sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)

    csv_out = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
    long_df.to_csv(csv_out, index=False)
    print(f"Saved {len(long_df):,} rows to {csv_out}")

    # Cluster stores to position warehouses and derive costs/lead times
    store_daily_demands = long_df.groupby(["store_id", "date"])["demand"].sum().groupby("store_id").mean().to_dict()
    avg_store_daily = float(np.mean(list(store_daily_demands.values())))

    wh_coords, cluster_assignments = cluster_stores_to_warehouses(store_daily_demands, k=2)
    print(f"Clustered Warehouses (Lat, Lon): {wh_coords}")
    print(f"Store -> Warehouse Cluster Assignments: {cluster_assignments}")

    edges = []
    # 1. Supplier -> Warehouse edges based on centroid distances
    for sup_id, s_coord in SUPPLIER_COORDS.items():
        for wh_id, w_coord in wh_coords.items():
            dist_km = euclidean_km(s_coord, w_coord)
            lead_mean = round(max(2.0, 1.5 + dist_km / 650.0), 2)
            lead_std = round(max(0.4, lead_mean * 0.22), 2)
            t_cost = round(max(0.45, 0.30 + dist_km * 0.00045), 2)
            edges.append({
                "source": sup_id,
                "target": wh_id,
                "distance_km": round(dist_km, 1),
                "lead_time_mean": lead_mean,
                "lead_time_std": lead_std,
                "transport_cost": t_cost
            })

    # 2. Warehouse -> Store edges based on cluster centroid distances
    for store_id, wh_id in cluster_assignments.items():
        dist_km = euclidean_km(wh_coords[wh_id], STORE_COORDS[store_id])
        lead_mean = round(max(1.0, 1.0 + dist_km / 500.0), 2)
        lead_std = round(max(0.3, lead_mean * 0.25), 2)
        t_cost = round(max(0.25, 0.20 + dist_km * 0.0005), 2)
        edges.append({
            "source": wh_id,
            "target": store_id,
            "distance_km": round(dist_km, 1),
            "lead_time_mean": lead_mean,
            "lead_time_std": lead_std,
            "transport_cost": t_cost
        })

    # 3. Pairwise Store <-> Store & Warehouse <-> Store transfer cost matrix for MILP
    all_locs = {**wh_coords, **STORE_COORDS}
    transfer_cost_matrix = {}
    for src, c1 in all_locs.items():
        transfer_cost_matrix[src] = {}
        for dst, c2 in STORE_COORDS.items():
            if src != dst:
                dist = euclidean_km(c1, c2)
                transfer_cost_matrix[src][dst] = round(0.20 + dist * 0.00045, 3)

    network_topology = {
        "nodes": [
            {
                "id": "SUP_1",
                "name": "Primary National Supplier",
                "type": "supplier",
                "lat": SUPPLIER_COORDS["SUP_1"][0],
                "lon": SUPPLIER_COORDS["SUP_1"][1],
                "capacity_units": int(avg_store_daily * 120),
                "reliability": 0.96,
            },
            {
                "id": "SUP_2",
                "name": "Regional Backup Supplier",
                "type": "supplier",
                "lat": SUPPLIER_COORDS["SUP_2"][0],
                "lon": SUPPLIER_COORDS["SUP_2"][1],
                "capacity_units": int(avg_store_daily * 80),
                "reliability": 0.92,
            },
            {
                "id": "WH_WEST",
                "name": "West Cluster Centroid Hub",
                "type": "warehouse",
                "lat": round(wh_coords["WH_WEST"][0], 4),
                "lon": round(wh_coords["WH_WEST"][1], 4),
                "capacity_units": int(avg_store_daily * 45),
                "holding_cost": 0.25,
            },
            {
                "id": "WH_CENTRAL",
                "name": "Central Cluster Centroid Hub",
                "type": "warehouse",
                "lat": round(wh_coords["WH_CENTRAL"][0], 4),
                "lon": round(wh_coords["WH_CENTRAL"][1], 4),
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
                "cluster_warehouse": cluster_assignments[store],
                "lat": STORE_COORDS[store][0],
                "lon": STORE_COORDS[store][1],
                "capacity_units": int(store_daily_demands.get(store, avg_store_daily) * 14),
                "holding_cost": round(0.45 + 0.05 * (1.0 if store.startswith("CA") else 0.0), 2),
                "stockout_penalty": round(4.50 + 0.50 * (store_daily_demands.get(store, avg_store_daily) / avg_store_daily), 2),
                "ordering_cost": 25.00,
            }
            for store in STORES
        ],
        "edges": edges,
        "transfer_cost_matrix": transfer_cost_matrix,
        "metadata": {
            "stores": STORES,
            "cluster_assignments": cluster_assignments,
            "high_volume_items": high_vol_items,
            "intermittent_items": intermittent_items,
            "all_items": selected_items,
        },
    }

    net_out = os.path.join(ARTIFACTS_DIR, "network_topology.json")
    with open(net_out, "w") as f:
        json.dump(network_topology, f, indent=2)
    print(f"Saved clustered network topology to {net_out}")


if __name__ == "__main__":
    build_subset_and_network()