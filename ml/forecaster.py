import os
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb

ARTIFACTS_DIR = "ml/artifacts"
QUANTILES = [0.10, 0.50, 0.90]

def pinball_loss(y_true, y_pred, alpha):
    """Calculates quantile (pinball) loss."""
    diff = y_true - y_pred
    return np.mean(np.maximum(alpha * diff, (alpha - 1) * diff))

def train_forecaster():
    csv_path = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Run data_loader.py first to generate {csv_path}")

    print("Loading M5 subset demand data...")
    df = pd.read_csv(csv_path, parse_dates=["date"])
    
    # Sort for rolling features
    df = df.sort_values(["store_id", "item_id", "date"]).reset_index(drop=True)

    print("Engineering features (lags, rolling stats, calendar)...")
    # Feature engineering per store-item series
    df["lag_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(7)
    df["lag_14"] = df.groupby(["store_id", "item_id"])["demand"].shift(14)
    df["lag_28"] = df.groupby(["store_id", "item_id"])["demand"].shift(28)
    
    df["rolling_mean_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(7).mean().reset_index(0, drop=True)
    df["rolling_std_7"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(7).std().reset_index(0, drop=True)
    df["rolling_mean_28"] = df.groupby(["store_id", "item_id"])["demand"].shift(1).rolling(28).mean().reset_index(0, drop=True)

    # Drop initial NaN rows created by lags
    df = df.dropna().reset_index(drop=True)

    features = [
        "lag_7", "lag_14", "lag_28", 
        "rolling_mean_7", "rolling_std_7", "rolling_mean_28",
        "sell_price", "is_promo", "is_holiday", "wday", "month"
    ]
    target = "demand"

    # Strict time-based split: Train on first ~10 months, Test on last 2 months
    split_date = df["date"].max() - pd.Timedelta(days=60)
    train_mask = df["date"] <= split_date
    test_mask = df["date"] > split_date

    X_train, y_train = df.loc[train_mask, features], df.loc[train_mask, target]
    X_test, y_test = df.loc[test_mask, features], df.loc[test_mask, target]

    print(f"Training samples: {len(X_train):,}, Test samples: {len(X_test):,}")

    models = {}
    metrics = {}

    for q in QUANTILES:
        q_name = f"p{int(q*100)}"
        print(f"Training LightGBM Quantile Regressor for {q_name} (alpha={q})...")
        
        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=q,
            n_estimators=150,
            learning_rate=0.04,
            num_leaves=31,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        model.fit(X_train, y_train)
        models[q_name] = model

        # Evaluate on test set
        preds = model.predict(X_test)
        loss = pinball_loss(y_test.values, preds, q)
        metrics[f"pinball_loss_{q_name}"] = float(loss)
        print(f"  -> {q_name} Pinball Loss: {loss:.4f}")

    # Calculate Prediction Interval Coverage for 80% interval (P10 to P90)
    p10_preds = models["p10"].predict(X_test)
    p90_preds = models["p90"].predict(X_test)
    coverage = np.mean((y_test.values >= p10_preds) & (y_test.values <= p90_preds))
    metrics["interval_coverage_80pct"] = float(coverage)
    print(f"80% Prediction Interval Coverage (P10-P90): {coverage * 100:.1f}%")

    # Save models and metadata
    model_out = os.path.join(ARTIFACTS_DIR, "forecaster_models.joblib")
    joblib.dump({"models": models, "features": features}, model_out)
    print(f"Saved forecaster bundle to {model_out}")

    metrics_out = os.path.join(ARTIFACTS_DIR, "forecaster_metrics.json")
    import json
    with open(metrics_out, "w") as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    train_forecaster()