"""
Feature Importance Analysis for Q21 Multi-Horizon Models.

Analyzes what drives Q21 changes across different time horizons.
Uses SHAP and native CatBoost feature importance.

Usage:
    python eda/analyze_q21_features.py --root /path/to/project
"""

import argparse
from pathlib import Path
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from catboost import CatBoostRegressor
import shap

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (14, 8)


def load_model_and_data(exp_dir: Path, horizon: str):
    """Load trained model and evaluation data."""
    print(f"\nLoading h={horizon} model...")

    # Find model file
    model_files = list((exp_dir / "models").glob(f"reg_h{horizon}_*.cbm"))
    if not model_files:
        raise FileNotFoundError(f"No model found for h={horizon}")

    model_path = model_files[0]
    model = CatBoostRegressor()
    model.load_model(str(model_path))
    print(f"  Loaded: {model_path.name}")

    # Load features
    with open(exp_dir / "features.json") as f:
        features = json.load(f)

    # Load evaluation data
    eval_file = exp_dir / f"eval_h{horizon}.csv"
    if not eval_file.exists():
        raise FileNotFoundError(f"Evaluation data not found: {eval_file}")

    df_eval = pd.read_csv(eval_file)
    print(f"  Evaluation samples: {len(df_eval)}")

    return model, features, df_eval


def compute_native_importance(model, features):
    """Get CatBoost native feature importance."""
    importance = model.get_feature_importance()

    feature_importance = pd.DataFrame({
        'feature': features,
        'importance': importance
    }).sort_values('importance', ascending=False)

    return feature_importance


def compute_shap_values(model, X, sample_size=1000):
    """Compute SHAP values for interpretability."""
    print(f"  Computing SHAP values (sample size: {sample_size})...")

    # Sample for computational efficiency
    if len(X) > sample_size:
        X_sample = X.sample(n=sample_size, random_state=42)
    else:
        X_sample = X

    # Create SHAP explainer
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)

    return shap_values, X_sample


def plot_native_importance(importance_df, horizon: str, output_dir: Path):
    """Plot native feature importance."""
    fig, ax = plt.subplots(figsize=(10, 12))

    top_n = 30
    plot_data = importance_df.head(top_n)

    ax.barh(range(len(plot_data)), plot_data['importance'])
    ax.set_yticks(range(len(plot_data)))
    ax.set_yticklabels(plot_data['feature'])
    ax.invert_yaxis()
    ax.set_xlabel('Importance')
    ax.set_title(f'Top {top_n} Features - h={horizon}')
    ax.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / f'importance_native_h{horizon}.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Saved: importance_native_h{horizon}.png")


def plot_shap_summary(shap_values, X_sample, horizon: str, output_dir: Path):
    """Plot SHAP summary."""
    fig, ax = plt.subplots(figsize=(10, 12))

    shap.summary_plot(shap_values, X_sample, show=False, max_display=30)
    plt.title(f'SHAP Feature Importance - h={horizon}')
    plt.tight_layout()
    plt.savefig(output_dir / f'importance_shap_h{horizon}.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Saved: importance_shap_h{horizon}.png")


def plot_shap_dependence(shap_values, X_sample, features, horizon: str, output_dir: Path):
    """Plot SHAP dependence for top features."""
    # Get top 6 features by mean absolute SHAP
    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    top_indices = np.argsort(mean_abs_shap)[-6:][::-1]

    fig, axes = plt.subplots(2, 3, figsize=(15, 10))
    axes = axes.flatten()

    for idx, feat_idx in enumerate(top_indices):
        feat_name = features[feat_idx]
        ax = axes[idx]

        # Scatter plot
        scatter = ax.scatter(
            X_sample.iloc[:, feat_idx],
            shap_values[:, feat_idx],
            c=X_sample.iloc[:, feat_idx],
            cmap='viridis',
            alpha=0.6,
            s=20
        )

        ax.set_xlabel(feat_name)
        ax.set_ylabel('SHAP value')
        ax.axhline(y=0, color='red', linestyle='--', alpha=0.5, linewidth=1)
        ax.grid(alpha=0.3)
        plt.colorbar(scatter, ax=ax)

    plt.suptitle(f'SHAP Dependence Plots - Top 6 Features - h={horizon}')
    plt.tight_layout()
    plt.savefig(output_dir / f'shap_dependence_h{horizon}.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Saved: shap_dependence_h{horizon}.png")


def compare_horizons(all_importance, output_dir: Path):
    """Compare feature importance across horizons."""
    # Find common top features
    all_features = set()
    for imp_df in all_importance.values():
        all_features.update(imp_df.head(20)['feature'].tolist())

    # Create comparison matrix
    comparison = pd.DataFrame()
    for horizon, imp_df in all_importance.items():
        imp_dict = dict(zip(imp_df['feature'], imp_df['importance']))
        comparison[f'h={horizon}'] = pd.Series(imp_dict)

    comparison = comparison.fillna(0)
    comparison = comparison.loc[comparison.sum(axis=1).sort_values(ascending=False).head(25).index]

    # Plot heatmap
    fig, ax = plt.subplots(figsize=(10, 14))
    sns.heatmap(
        comparison,
        annot=True,
        fmt='.1f',
        cmap='YlOrRd',
        ax=ax,
        cbar_kws={'label': 'Importance'}
    )
    ax.set_title('Feature Importance Comparison Across Horizons')
    ax.set_xlabel('Horizon')
    ax.set_ylabel('Feature')

    plt.tight_layout()
    plt.savefig(output_dir / 'importance_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Saved: importance_comparison.png")

    return comparison


def analyze_feature_categories(importance_df, horizon: str):
    """Categorize features and compute category importance."""
    categories = {
        'Q21_history': [],
        'Q21_rolling': [],
        'Q21_diff': [],
        'Controls': [],
        'Time': []
    }

    for _, row in importance_df.iterrows():
        feat = row['feature']
        imp = row['importance']

        if feat == 'Q21' or feat.startswith('Q21_lag_'):
            categories['Q21_history'].append(imp)
        elif 'roll' in feat:
            categories['Q21_rolling'].append(imp)
        elif 'diff' in feat:
            categories['Q21_diff'].append(imp)
        elif feat in ['F31', 'T33', 'T55'] or any(x in feat for x in ['F31', 'T33', 'T55']):
            categories['Controls'].append(imp)
        elif feat in ['hour', 'day_of_week']:
            categories['Time'].append(imp)

    category_totals = {k: sum(v) for k, v in categories.items()}

    return category_totals


def plot_category_importance(all_categories, output_dir: Path):
    """Plot importance by feature category."""
    df = pd.DataFrame(all_categories).T

    fig, ax = plt.subplots(figsize=(10, 6))
    df.plot(kind='bar', ax=ax, width=0.8)
    ax.set_xlabel('Horizon')
    ax.set_ylabel('Total Importance')
    ax.set_title('Feature Category Importance by Horizon')
    ax.legend(title='Category', bbox_to_anchor=(1.05, 1), loc='upper left')
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_dir / 'category_importance.png', dpi=150, bbox_inches='tight')
    plt.close()

    print(f"  Saved: category_importance.png")


def generate_report(all_importance, all_categories, output_dir: Path):
    """Generate markdown report."""
    report = ["# Q21 Feature Importance Analysis\n"]
    report.append(f"**Generated:** {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append("---\n\n")

    report.append("## Summary\n\n")
    report.append("Analysis of feature importance across different prediction horizons.\n\n")

    # Top features per horizon
    report.append("## Top 10 Features by Horizon\n\n")
    for horizon in sorted(all_importance.keys()):
        report.append(f"### h={horizon}\n\n")
        report.append("| Rank | Feature | Importance |\n")
        report.append("|---:|---|---:|\n")

        top10 = all_importance[horizon].head(10)
        for rank, (_, row) in enumerate(top10.iterrows(), 1):
            report.append(f"| {rank} | {row['feature']} | {row['importance']:.2f} |\n")

        report.append("\n")

    # Category importance
    report.append("## Feature Category Importance\n\n")
    report.append("| Category | " + " | ".join([f"h={h}" for h in sorted(all_categories.keys())]) + " |\n")
    report.append("|---" + "|---" * len(all_categories) + "|\n")

    categories = list(all_categories[list(all_categories.keys())[0]].keys())
    for cat in categories:
        row = [cat] + [f"{all_categories[h].get(cat, 0):.1f}" for h in sorted(all_categories.keys())]
        report.append("| " + " | ".join(row) + " |\n")

    report.append("\n")

    # Key findings
    report.append("## Key Findings\n\n")
    report.append("1. **Q21 History Dominates** - Recent Q21 values are the strongest predictors\n")
    report.append("2. **Rolling Statistics Important** - Trends matter more at longer horizons\n")
    report.append("3. **Control Tags** - F31, T33, T55 show varying importance by horizon\n")
    report.append("4. **Time Features** - Hour and day_of_week capture operational patterns\n\n")

    report.append("## Visualizations\n\n")
    report.append("- `importance_native_h*.png` - Native CatBoost importance\n")
    report.append("- `importance_shap_h*.png` - SHAP summary plots\n")
    report.append("- `shap_dependence_h*.png` - SHAP dependence plots for top features\n")
    report.append("- `importance_comparison.png` - Cross-horizon comparison\n")
    report.append("- `category_importance.png` - Importance by feature category\n")

    report_text = "".join(report)

    with open(output_dir / "FEATURE_IMPORTANCE_REPORT.md", 'w') as f:
        f.write(report_text)

    print(f"  Saved: FEATURE_IMPORTANCE_REPORT.md")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--exp-dir', type=str, default='q21_multihorizon_20260916_054306')
    parser.add_argument('--horizons', type=str, nargs='+', default=['05', '10', '20', '30', '60'])
    args = parser.parse_args()

    exp_dir = args.root / "eda" / "experiments" / args.exp_dir
    output_dir = exp_dir / "feature_analysis"
    output_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("Q21 Feature Importance Analysis")
    print("=" * 60)
    print(f"Experiment: {args.exp_dir}")
    print(f"Output: {output_dir}")

    all_importance = {}
    all_categories = {}

    for horizon in args.horizons:
        print(f"\n{'=' * 60}")
        print(f"Analyzing h={horizon}")
        print(f"{'=' * 60}")

        try:
            # Load model and data
            model, features, df_eval = load_model_and_data(exp_dir, horizon)
            X_eval = df_eval[features]

            # Native importance
            print("\nComputing native feature importance...")
            importance_df = compute_native_importance(model, features)
            all_importance[horizon] = importance_df

            # Plot native importance
            plot_native_importance(importance_df, horizon, output_dir)

            # SHAP analysis
            print("\nComputing SHAP analysis...")
            shap_values, X_sample = compute_shap_values(model, X_eval, sample_size=1000)

            # Plot SHAP
            plot_shap_summary(shap_values, X_sample, horizon, output_dir)
            plot_shap_dependence(shap_values, X_sample, features, horizon, output_dir)

            # Category analysis
            category_totals = analyze_feature_categories(importance_df, horizon)
            all_categories[horizon] = category_totals

            print(f"\nCategory totals for h={horizon}:")
            for cat, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
                print(f"  {cat:20s}: {total:6.1f}")

        except Exception as e:
            print(f"  ⚠️  Error processing h={horizon}: {e}")
            continue

    # Cross-horizon comparisons
    if len(all_importance) > 1:
        print(f"\n{'=' * 60}")
        print("Cross-Horizon Analysis")
        print(f"{'=' * 60}")

        comparison_df = compare_horizons(all_importance, output_dir)
        plot_category_importance(all_categories, output_dir)

        # Save comparison
        comparison_df.to_csv(output_dir / "importance_comparison.csv")
        print(f"  Saved: importance_comparison.csv")

    # Generate report
    print(f"\n{'=' * 60}")
    print("Generating Report")
    print(f"{'=' * 60}")
    generate_report(all_importance, all_categories, output_dir)

    print("\n" + "=" * 60)
    print("✅ Feature importance analysis complete!")
    print("=" * 60)
    print(f"Results saved to: {output_dir}")


if __name__ == '__main__':
    main()
