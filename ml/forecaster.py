import os
import json
import joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from ml.feature_engineering import engineer_m5_features, FEATURES

ARTIFACTS_DIR = "ml/artifacts"
QUANTILES = [0.10, 0.50, 0.90]


def pinball_loss(y_true, y_pred, alpha):
    diff = y_true - y_pred
    return float(np.mean(np.maximum(alpha * diff, (alpha - 1) * diff)))


def predict_winner_quantiles(bundle: dict, df_slice: pd.DataFrame) -> dict:
    """
    Combines:
    1. 1st-Place Store-wise Tweedie Point Model + EWM(com=0.04) smoothing
    2. Direct LightGBM Quantile Models
    3. Nodalpoints Level-12 Blending: Coefficient Multipliers + Historical Sales Quantiles
    """
    feat_df = df_slice[FEATURES].fillna(0)
    stores = df_slice["store_id"].values

    # 1. Store-specific Tweedie point forecast
    tweedie_preds = np.zeros(len(df_slice))
    store_models = bundle["store_tweedie_models"]
    global_tweedie = bundle["global_tweedie"]

    for s in np.unique(stores):
        mask = stores == s
        model = store_models.get(s, global_tweedie)
        tweedie_preds[mask] = np.maximum(0.0, model.predict(feat_df.loc[mask]))

    # Apply Nodalpoints EWM smoothing across series if multiple time steps present
    if len(tweedie_preds) > 1:
        tweedie_preds = pd.Series(tweedie_preds).ewm(com=0.04).mean().values

    # 2. Direct Quantile LGB predictions
    q_models = bundle["models"]
    lgb_p10 = np.maximum(0.0, q_models["p10"].predict(feat_df))
    lgb_p50 = np.maximum(0.0, q_models["p50"].predict(feat_df))
    lgb_p90 = np.maximum(0.0, q_models["p90"].predict(feat_df))

    # 3. Nodalpoints Skew-Normal Multipliers & Empirical Quantiles
    mults = bundle["multipliers"]
    hist_p10 = df_slice["hist_p10"].values if "hist_p10" in df_slice else lgb_p10
    hist_p50 = df_slice["hist_p50"].values if "hist_p50" in df_slice else lgb_p50
    hist_p90 = df_slice["hist_p90"].values if "hist_p90" in df_slice else lgb_p90

    # Winner's Level-12 formula:
    # Median = 0.8 * accuracy_anchor + 0.2 * hist_p50
    base_median = 0.65 * tweedie_preds + 0.35 * lgb_p50
    p50 = 0.80 * base_median + 0.20 * hist_p50

    # Outer Quantiles = 0.2 * coeff_tuning + 0.5 * lgb_quantile + 0.3 * hist_sales_quantiles
    # Plus 1.025 right-skewness amplification on P90
    # Snap P10 to 0 when expected low-quantile demand is fractional (< 0.5 units) or zero-inflated
    p10 = 0.25 * (p50 * mults["p10"]) + 0.45 * lgb_p10 + 0.30 * hist_p10
    zero_rate = df_slice["zero_rate_28"].values if "zero_rate_28" in df_slice else np.zeros(len(p10))
    p10 = np.where((p10 < 0.5) | (zero_rate >= 0.30), 0.0, p10)
    p90 = np.maximum(p50 + 1.0, (0.25 * (p50 * mults["p90"]) + 0.45 * lgb_p90 + 0.30 * hist_p90) * 1.025)

    return {"p10": p10, "p50": p50, "p90": p90}


def train_forecaster():
    csv_path = os.path.join(ARTIFACTS_DIR, "m5_subset_demand.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Run data_loader.py first to generate {csv_path}")

    print("Loading M5 subset demand data...")
    raw_df = pd.read_csv(csv_path, parse_dates=["date"])

    print("Engineering M5 Winner features (price momentum, multi-lags, empirical quantiles)...")
    df = engineer_m5_features(raw_df)
    df = df.dropna(subset=["lag_28"]).reset_index(drop=True)

    target = "demand"

    # 1st-Place Strategy: Multi-window time-based CV (3 rolling 28-day windows)
    max_date = df["date"].max()
    cv_losses = []
    for fold in range(1, 4):
        val_end = max_date - pd.Timedelta(days=28 * (fold - 1))
        val_start = val_end - pd.Timedelta(days=28)
        tr_mask = df["date"] <= val_start
        va_mask = (df["date"] > val_start) & (df["date"] <= val_end)
        if tr_mask.sum() > 500 and va_mask.sum() > 100:
            cv_model = lgb.LGBMRegressor(
                objective="tweedie", tweedie_variance_power=1.1,
                n_estimators=120, learning_rate=0.04, num_leaves=31,
                random_state=42, n_jobs=-1, verbose=-1
            )
            cv_model.fit(df.loc[tr_mask, FEATURES], df.loc[tr_mask, target])
            val_preds = cv_model.predict(df.loc[va_mask, FEATURES])
            rmse = float(np.sqrt(np.mean((df.loc[va_mask, target].values - val_preds) ** 2)))
            cv_losses.append(rmse)

    print(f"3-Fold Rolling Time-Series CV RMSE -> Mean: {np.mean(cv_losses):.3f}, Std: {np.std(cv_losses):.3f}")

    # Final Train/Test Split (Last 60 days held out for evaluation & simulation)
    split_date = max_date - pd.Timedelta(days=60)
    train_df = df[df["date"] <= split_date].copy()
    test_df = df[df["date"] > split_date].copy()

    X_train, y_train = train_df[FEATURES], train_df[target]
    X_test, y_test = test_df[FEATURES], test_df[target]

    print(f"Training samples: {len(X_train):,}, Test samples: {len(X_test):,}")

    # 1. Train Store-Specific Tweedie Models (1st Place Accuracy Strategy)
    print("Training Store-wise LightGBM Tweedie Models (variance_power=1.1)...")
    global_tweedie = lgb.LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.1,
        n_estimators=180, learning_rate=0.04, num_leaves=31,
        subsample=0.8, colsample_bytree=0.8, random_state=42, n_jobs=-1, verbose=-1
    )
    global_tweedie.fit(X_train, y_train)

    store_tweedie_models = {}
    for store_id, s_df in train_df.groupby("store_id"):
        s_model = lgb.LGBMRegressor(
            objective="tweedie", tweedie_variance_power=1.1,
            n_estimators=160, learning_rate=0.04, num_leaves=15,
            random_state=42, n_jobs=-1, verbose=-1
        )
        s_model.fit(s_df[FEATURES], s_df[target])
        store_tweedie_models[store_id] = s_model

    # 2. Train Direct Quantile Regressors (Calibrated for 80% coverage)
    models = {}
    alpha_map = {"p10": 0.06, "p50": 0.50, "p90": 0.94}  # Slightly widened for 80% calibration
    for q_name, alpha_val in alpha_map.items():
        print(f"Training LightGBM Quantile Regressor for {q_name} (calibrated alpha={alpha_val})...")
        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=alpha_val,
            n_estimators=180,
            learning_rate=0.04,
            num_leaves=31,
            min_child_samples=15,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        model.fit(X_train, y_train)
        models[q_name] = model

    # 3. Calibrate Skew-Normal Multipliers on Training Residuals (Nodalpoints Strategy)
    train_tweedie_pred = np.maximum(0.1, global_tweedie.predict(X_train))
    ratios = y_train.values / train_tweedie_pred
    multipliers = {
        "p10": float(np.quantile(ratios, 0.10)) * 0.995,  # 0.5% spread amplification
        "p90": float(np.quantile(ratios, 0.90)) * 1.005,
    }

    bundle = {
        "models": models,
        "global_tweedie": global_tweedie,
        "store_tweedie_models": store_tweedie_models,
        "multipliers": multipliers,
        "features": FEATURES,
    }

    # Evaluate blended predictions on Test Set
    blended_preds = predict_winner_quantiles(bundle, test_df)
    metrics = {
        "cv_rmse_mean": round(float(np.mean(cv_losses)), 4),
        "cv_rmse_std": round(float(np.std(cv_losses)), 4),
    }

    for q, q_name in [(0.10, "p10"), (0.50, "p50"), (0.90, "p90")]:
        loss = pinball_loss(y_test.values, blended_preds[q_name], q)
        metrics[f"pinball_loss_{q_name}"] = round(loss, 4)
        print(f"  -> Blended {q_name} Pinball Loss: {loss:.4f}")

    coverage = float(np.mean((y_test.values >= blended_preds["p10"]) & (y_test.values <= blended_preds["p90"])))
    metrics["interval_coverage_80pct"] = round(coverage, 4)
    print(f"80% Prediction Interval Coverage (P10-P90): {coverage * 100:.1f}%")

    # Breakdown High-Volume vs Intermittent for Mandatory Checklist
    for dtype in ["high_volume", "intermittent"]:
        d_mask = test_df["demand_type"] == dtype
        if d_mask.any():
            d_cov = float(np.mean(
                (y_test.values[d_mask] >= blended_preds["p10"][d_mask]) &
                (y_test.values[d_mask] <= blended_preds["p90"][d_mask])
            ))
            d_p50 = pinball_loss(y_test.values[d_mask], blended_preds["p50"][d_mask], 0.50)
            metrics[f"{dtype}_coverage_80pct"] = round(d_cov, 4)
            metrics[f"{dtype}_pinball_p50"] = round(d_p50, 4)
            print(f"  -> [{dtype.upper()}] P50 Pinball: {d_p50:.4f} | 80% Coverage: {d_cov*100:.1f}%")

    model_out = os.path.join(ARTIFACTS_DIR, "forecaster_models.joblib")
    joblib.dump(bundle, model_out)
    print(f"Saved M5 Winner forecaster bundle to {model_out}")

    metrics_out = os.path.join(ARTIFACTS_DIR, "forecaster_metrics.json")
    with open(metrics_out, "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    train_forecaster()