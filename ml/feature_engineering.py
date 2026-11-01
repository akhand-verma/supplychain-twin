import numpy as np
import pandas as pd

FEATURES = [
    "lag_1", "lag_7", "lag_14", "lag_28",
    "rolling_mean_7", "rolling_std_7",
    "rolling_mean_14", "rolling_std_14",
    "rolling_mean_28", "rolling_std_28",
    "zero_rate_28",
    "sell_price", "price_norm", "price_momentum",
    "is_promo", "is_holiday", "wday", "month"
]


def engineer_m5_features(df: pd.DataFrame) -> pd.DataFrame:
    """Applies M5 1st-place price, calendar, lag, and rolling features."""
    df = df.sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)
    grp = df.groupby(["store_id", "item_id"])

    # Target Lags (Non-recursive & short-term recursive anchor)
    df["lag_1"] = grp["demand"].shift(1)
    df["lag_7"] = grp["demand"].shift(7)
    df["lag_14"] = grp["demand"].shift(14)
    df["lag_28"] = grp["demand"].shift(28)

    # Rolling statistics on shifted demand (strictly prevents data leakage)
    shifted = grp["demand"].shift(1)
    for w in [7, 14, 28]:
        df[f"rolling_mean_{w}"] = (
            shifted.rolling(w, min_periods=1).mean().reset_index(0, drop=True)
        )
        df[f"rolling_std_{w}"] = (
            shifted.rolling(w, min_periods=1).std().fillna(0).reset_index(0, drop=True)
        )

    # Intermittency tracker (for Level-12 empirical quantile blending)
    df["zero_rate_28"] = (
        shifted.apply(lambda x: 1.0 if x == 0 else 0.0)
        .rolling(28, min_periods=1)
        .mean()
        .reset_index(0, drop=True)
    )

    # M5 Winner Price Features: Price Normalization & Momentum
    item_mean_price = df.groupby(["store_id", "item_id"])["sell_price"].transform("mean")
    df["price_norm"] = df["sell_price"] / (item_mean_price + 1e-5)
    price_lag_7 = grp["sell_price"].shift(7).bfill()
    df["price_momentum"] = df["sell_price"] / (price_lag_7 + 1e-5)

    # Empirical Historical Quantiles (28d and 364d) for Nodalpoints Uncertainty Blending
    for q, q_label in [(0.10, "p10"), (0.50, "p50"), (0.90, "p90")]:
        q_28 = shifted.rolling(28, min_periods=7).quantile(q).reset_index(0, drop=True).fillna(0)
        q_364 = shifted.rolling(364, min_periods=28).quantile(q).reset_index(0, drop=True).fillna(q_28)
        # Winner's exact weight ratio: [1.0 for 364d, 1.75 for 28d] -> normalized: 0.3636 and 0.6364
        df[f"hist_{q_label}"] = (1.0 * q_364 + 1.75 * q_28) / 2.75

    return df