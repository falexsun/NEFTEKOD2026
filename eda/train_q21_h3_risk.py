"""
Risk classification для h=3: предсказание Q21 > 10 ppm через 3 часа.

Сравнить:
1. Residual features classifier
2. Persistence classifier (если Q21(t) > 10, то Q21(t+3h) > 10)
3. Ensemble
"""
import pandas as pd
import numpy as np
from catboost import CatBoostClassifier, Pool
from pathlib import Path
from datetime import datetime
import json
from sklearn.metrics import (
    average_precision_score, roc_auc_score,
    precision_recall_curve, confusion_matrix,
    classification_report
)

def load_data(root):
    df = pd.read_csv(root / 'data' / '242000_tags.csv')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
    mask = (df['Q21'] > 0) & (df['Q21'] < 50)
    df = df[mask].copy()
    return df

def build_features(df, horizon_steps=18):
    """Features для h=3 risk"""
    features = []

    # Target
    df['Q21_h3'] = df['Q21'].shift(-horizon_steps)
    df['risk_h3'] = (df['Q21_h3'] > 10).astype(int)
    df['risk_current'] = (df['Q21'] > 10).astype(int)

    # Persistence signal
    df['Q21_persistence'] = df['Q21']

    # Базовые controls
    for col in df.columns:
        if col in ['date', 'Q21_h3', 'risk_h3', 'risk_current', 'Q21_persistence']:
            continue
        if df[col].dtype in ['float64', 'int64']:
            features.append(col)

    # Q21 history
    for lag in [1, 2, 3, 6, 12, 18]:
        df[f'Q21_lag{lag}'] = df['Q21'].shift(lag)
        features.append(f'Q21_lag{lag}')

    # Trend features
    for window in [6, 18, 36]:
        df[f'Q21_mean_{window}'] = df['Q21'].rolling(window, min_periods=1).mean()
        df[f'Q21_std_{window}'] = df['Q21'].rolling(window, min_periods=1).std()
        df[f'Q21_min_{window}'] = df['Q21'].rolling(window, min_periods=1).min()
        df[f'Q21_max_{window}'] = df['Q21'].rolling(window, min_periods=1).max()
        features.extend([
            f'Q21_mean_{window}', f'Q21_std_{window}',
            f'Q21_min_{window}', f'Q21_max_{window}'
        ])

    # Velocity
    df['Q21_diff1'] = df['Q21'].diff(1)
    df['Q21_diff6'] = df['Q21'].diff(6)
    df['Q21_diff18'] = df['Q21'].diff(18)
    features.extend(['Q21_diff1', 'Q21_diff6', 'Q21_diff18'])

    # Volatility
    df['Q21_abs_diff_mean_18'] = df['Q21'].diff(1).abs().rolling(18, min_periods=1).mean()
    features.append('Q21_abs_diff_mean_18')

    # Distance to threshold
    df['Q21_distance_to_10'] = 10 - df['Q21']
    features.append('Q21_distance_to_10')

    # Controls lags
    controls = ['F1', 'P8', 'T11', 'F19', 'F25']
    for col in controls:
        if col in df.columns:
            for lag in [0, 1, 3, 6]:
                df[f'{col}_lag{lag}'] = df[col].shift(lag)
                features.append(f'{col}_lag{lag}')

    return df, features

def split_data(df):
    train = df[df['date'] <= '2023-12-28'].copy()
    val = df[(df['date'] >= '2024-01-01') & (df['date'] <= '2024-06-27')].copy()
    cal = df[(df['date'] >= '2024-07-01') & (df['date'] <= '2025-12-28')].copy()
    eval_data = df[df['date'] >= '2026-01-01'].copy()
    return train, val, cal, eval_data

def train_risk_classifier(X_train, y_train, X_val, y_val, class_weights=None):
    """Обучить risk classifier"""

    # Auto class weights если не заданы
    if class_weights is None:
        n_pos = y_train.sum()
        n_neg = len(y_train) - n_pos
        weight = n_neg / n_pos
        class_weights = {0: 1.0, 1: weight}

    model = CatBoostClassifier(
        loss_function='Logloss',
        iterations=1500,
        learning_rate=0.02,
        depth=5,
        l2_leaf_reg=10,
        class_weights=class_weights,
        random_seed=42,
        verbose=False,
        early_stopping_rounds=150,
        task_type="GPU",
        devices="0"
    )

    model.fit(X_train, y_train, eval_set=(X_val, y_val), use_best_model=True)
    return model

def evaluate_risk(y_true, y_prob, y_pers, split_name, threshold=0.5):
    """Оценить risk classifier"""

    # Метрики
    ap = average_precision_score(y_true, y_prob)
    roc_auc = roc_auc_score(y_true, y_prob)

    # Persistence baseline
    ap_pers = average_precision_score(y_true, y_pers)
    roc_auc_pers = roc_auc_score(y_true, y_pers)

    # Confusion matrix at threshold
    y_pred = (y_prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    prevalence = y_true.mean()

    return {
        'split': split_name,
        'n': len(y_true),
        'prevalence': float(prevalence),
        'ap': float(ap),
        'roc_auc': float(roc_auc),
        'ap_persistence': float(ap_pers),
        'roc_auc_persistence': float(roc_auc_pers),
        'ap_improvement': float(ap - ap_pers),
        'threshold': threshold,
        'tp': int(tp),
        'fp': int(fp),
        'tn': int(tn),
        'fn': int(fn),
        'precision': float(precision),
        'recall': float(recall),
        'f1': float(f1),
    }

def find_optimal_threshold(y_true, y_prob, lambda_miss=10):
    """
    Найти оптимальный порог минимизирующий:
    cost = FP + lambda * FN
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_prob)

    best_threshold = 0.5
    best_cost = float('inf')

    for thresh in thresholds:
        y_pred = (y_prob >= thresh).astype(int)
        tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
        cost = fp + lambda_miss * fn

        if cost < best_cost:
            best_cost = cost
            best_threshold = thresh

    return best_threshold

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=str, required=True)
    args = parser.parse_args()

    root = Path(args.root)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    run_id = f"q21_h3_risk_{timestamp}"
    output_dir = root / 'eda' / 'experiments' / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Risk classification h=3 experiment: {run_id}\n")

    # Load
    print("Loading data...")
    df = load_data(root)
    print(f"Loaded {len(df):,} samples")

    # Features
    print("\nBuilding risk features...")
    df, feature_cols = build_features(df, horizon_steps=18)
    df = df.dropna(subset=['risk_h3'] + feature_cols)
    print(f"Valid samples: {len(df):,}")
    print(f"Features: {len(feature_cols)}")

    # Split
    print("\nSplitting...")
    train, val, cal, eval_data = split_data(df)

    # Prepare
    X_train = train[feature_cols]
    y_train = train['risk_h3']
    y_train_pers = train['risk_current']

    X_val = val[feature_cols]
    y_val = val['risk_h3']
    y_val_pers = val['risk_current']

    X_cal = cal[feature_cols]
    y_cal = cal['risk_h3']
    y_cal_pers = cal['risk_current']

    X_eval = eval_data[feature_cols]
    y_eval = eval_data['risk_h3']
    y_eval_pers = eval_data['risk_current']

    print(f"  Train: {len(train):,} (prevalence={y_train.mean()*100:.1f}%)")
    print(f"  Val: {len(val):,} (prevalence={y_val.mean()*100:.1f}%)")
    print(f"  Cal: {len(cal):,} (prevalence={y_cal.mean()*100:.1f}%)")
    print(f"  Eval: {len(eval_data):,} (prevalence={y_eval.mean()*100:.1f}%)")

    print("\n" + "="*60)
    print("RISK CLASSIFICATION h=3")
    print("="*60)

    # Train
    print("\nTraining risk classifier...")
    model = train_risk_classifier(X_train, y_train, X_val, y_val)

    # Predict probabilities
    print("\nEvaluating...")

    # Default threshold = 0.5
    results_train = evaluate_risk(
        y_train, model.predict_proba(X_train)[:, 1],
        train['Q21_persistence'], 'train', threshold=0.5
    )
    results_val = evaluate_risk(
        y_val, model.predict_proba(X_val)[:, 1],
        val['Q21_persistence'], 'validation', threshold=0.5
    )
    results_cal = evaluate_risk(
        y_cal, model.predict_proba(X_cal)[:, 1],
        cal['Q21_persistence'], 'calibration', threshold=0.5
    )
    results_eval = evaluate_risk(
        y_eval, model.predict_proba(X_eval)[:, 1],
        eval_data['Q21_persistence'], 'evaluation', threshold=0.5
    )

    print("\nResults (threshold=0.5):")
    print(f"{'Split':12s} {'AP':>8s} {'AP_pers':>8s} {'Δ':>8s} {'AUC':>8s} {'Prec':>8s} {'Rec':>8s} {'F1':>8s}")
    print("-" * 80)
    for r in [results_train, results_val, results_cal, results_eval]:
        print(f"{r['split']:12s} "
              f"{r['ap']:>8.3f} {r['ap_persistence']:>8.3f} {r['ap_improvement']:>+8.3f} "
              f"{r['roc_auc']:>8.3f} {r['precision']:>8.3f} {r['recall']:>8.3f} {r['f1']:>8.3f}")

    # Optimal threshold на calibration
    print("\nFinding optimal threshold on calibration (λ=10)...")
    y_cal_prob = model.predict_proba(X_cal)[:, 1]
    optimal_thresh = find_optimal_threshold(y_cal, y_cal_prob, lambda_miss=10)
    print(f"Optimal threshold: {optimal_thresh:.3f}")

    # Evaluate с optimal threshold
    results_eval_opt = evaluate_risk(
        y_eval, model.predict_proba(X_eval)[:, 1],
        eval_data['Q21_persistence'], 'evaluation_optimized', threshold=optimal_thresh
    )

    print(f"\nEvaluation with optimal threshold ({optimal_thresh:.3f}):")
    print(f"  Precision: {results_eval_opt['precision']:.3f}")
    print(f"  Recall: {results_eval_opt['recall']:.3f}")
    print(f"  F1: {results_eval_opt['f1']:.3f}")
    print(f"  FP: {results_eval_opt['fp']}, FN: {results_eval_opt['fn']}")

    # Save
    model_path = output_dir / "risk_h3_classifier.cbm"
    model.save_model(str(model_path))
    print(f"\nSaved: {model_path}")

    # Metadata
    metadata = {
        'run_id': run_id,
        'approach': 'risk_classification',
        'horizon': 3,
        'optimal_threshold': float(optimal_thresh),
        'results_default': {
            'train': results_train,
            'validation': results_val,
            'calibration': results_cal,
            'evaluation': results_eval,
        },
        'results_optimized': results_eval_opt,
        'n_features': len(feature_cols),
    }

    with open(output_dir / 'risk_results.json', 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\n✅ Risk classification complete: {output_dir}")

if __name__ == '__main__':
    main()
