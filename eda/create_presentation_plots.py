"""
Create comprehensive visualization for hackathon presentation.

Generates publication-quality plots showing:
1. Multi-horizon performance comparison
2. Risk classification trade-offs
3. Uncertainty quantification
4. Timeline of improvements

Usage:
    python eda/create_presentation_plots.py
"""

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# Set style
plt.style.use('seaborn-v0_8-darkgrid')
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = '#F8FAFC'
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans']
plt.rcParams['font.size'] = 11
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['legend.fontsize'] = 10

# Color palette
COLORS = {
    'primary': '#38BDF8',      # Sky blue
    'secondary': '#F97316',    # Orange
    'success': '#22C55E',      # Green
    'warning': '#F59E0B',      # Yellow
    'danger': '#EF4444',       # Red
    'dark': '#0F172A',         # Navy
    'light': '#F8FAFC'         # Off-white
}


def plot_1_multihorizon_performance():
    """Figure 1: Multi-horizon performance comparison."""

    # Data from experiments
    horizons_h = [0.5, 1.0, 2.0, 3.0, 6.0]
    model_mae = [0.574, 0.810, 1.148, 1.312, 1.571]
    persistence_mae = [0.584, 0.846, 1.237, 1.455, 1.616]
    improvement_pct = [1.7, 4.4, 7.2, 9.9, 2.8]

    fig = plt.figure(figsize=(14, 6))
    gs = GridSpec(1, 2, figure=fig, wspace=0.3)

    # Subplot A: MAE comparison
    ax1 = fig.add_subplot(gs[0, 0])

    x_pos = np.arange(len(horizons_h))
    width = 0.35

    bars1 = ax1.bar(x_pos - width/2, model_mae, width,
                    label='Model', color=COLORS['primary'], alpha=0.8)
    bars2 = ax1.bar(x_pos + width/2, persistence_mae, width,
                    label='Persistence', color=COLORS['secondary'], alpha=0.8)

    ax1.set_xlabel('Forecast Horizon (hours)', fontweight='bold')
    ax1.set_ylabel('MAE (ppm)', fontweight='bold')
    ax1.set_title('A. Prediction Accuracy by Horizon', fontweight='bold', pad=15)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels([f'{h}h' for h in horizons_h])
    ax1.legend(loc='upper left')
    ax1.grid(axis='y', alpha=0.3)

    # Annotate values
    for i, (m, p) in enumerate(zip(model_mae, persistence_mae)):
        ax1.text(i - width/2, m + 0.05, f'{m:.2f}', ha='center', va='bottom', fontsize=9)
        ax1.text(i + width/2, p + 0.05, f'{p:.2f}', ha='center', va='bottom', fontsize=9)

    # Subplot B: Improvement percentage
    ax2 = fig.add_subplot(gs[0, 1])

    colors_improvement = [COLORS['success'] if imp > 7 else COLORS['warning'] if imp > 4 else COLORS['primary']
                          for imp in improvement_pct]

    bars = ax2.bar(x_pos, improvement_pct, color=colors_improvement, alpha=0.8)

    ax2.set_xlabel('Forecast Horizon (hours)', fontweight='bold')
    ax2.set_ylabel('Improvement (%)', fontweight='bold')
    ax2.set_title('B. Model Improvement vs Persistence', fontweight='bold', pad=15)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels([f'{h}h' for h in horizons_h])
    ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
    ax2.grid(axis='y', alpha=0.3)

    # Annotate values
    for i, (imp, bar) in enumerate(zip(improvement_pct, bars)):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 0.3,
                f'{imp:.1f}%', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # Highlight best
    ax2.text(3, improvement_pct[3] + 1.5, '★ Best', ha='center',
             fontsize=11, color=COLORS['success'], fontweight='bold')

    plt.suptitle('Multi-Horizon Q21 Forecasting Performance (Evaluation 2026)',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    return fig


def plot_2_risk_classification():
    """Figure 2: Risk classification trade-offs."""

    # Data from experiments (h=1, different lambda)
    lambda_values = [5, 10, 25, 50]
    recall = [90.67, 94.53, 97.30, 98.57]
    precision = [65.05, 55.81, 46.54, 39.65]
    fpr = [13.92, 21.39, 31.94, 42.89]
    fn = [619, 363, 179, 95]
    fp = [3231, 4963, 7412, 9951]

    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(2, 2, figure=fig, wspace=0.3, hspace=0.4)

    # Subplot A: Recall vs Precision
    ax1 = fig.add_subplot(gs[0, 0])

    ax1.plot(lambda_values, recall, 'o-', color=COLORS['success'],
             linewidth=3, markersize=10, label='Recall')
    ax1.plot(lambda_values, precision, 's-', color=COLORS['primary'],
             linewidth=3, markersize=10, label='Precision')

    ax1.set_xlabel('Lambda (λ)', fontweight='bold')
    ax1.set_ylabel('Score (%)', fontweight='bold')
    ax1.set_title('A. Recall vs Precision Trade-off', fontweight='bold', pad=15)
    ax1.set_xscale('log')
    ax1.set_xticks(lambda_values)
    ax1.set_xticklabels(lambda_values)
    ax1.legend(loc='best')
    ax1.grid(alpha=0.3)
    ax1.set_ylim([35, 102])

    # Annotate λ=25
    ax1.axvline(x=25, color=COLORS['warning'], linestyle='--', alpha=0.5)
    ax1.text(25, 100, 'λ=25\n(safety)', ha='center', va='top',
             bbox=dict(boxstyle='round', facecolor=COLORS['warning'], alpha=0.3))

    # Subplot B: False Positive Rate
    ax2 = fig.add_subplot(gs[0, 1])

    bars = ax2.bar(range(len(lambda_values)), fpr, color=COLORS['danger'], alpha=0.7)

    ax2.set_xlabel('Lambda (λ)', fontweight='bold')
    ax2.set_ylabel('False Positive Rate (%)', fontweight='bold')
    ax2.set_title('B. False Alarm Rate', fontweight='bold', pad=15)
    ax2.set_xticks(range(len(lambda_values)))
    ax2.set_xticklabels(lambda_values)
    ax2.grid(axis='y', alpha=0.3)

    # Annotate values
    for i, (bar, val) in enumerate(zip(bars, fpr)):
        height = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2., height + 1,
                f'{val:.1f}%', ha='center', va='bottom', fontsize=10)

    # Subplot C: Confusion counts
    ax3 = fig.add_subplot(gs[1, :])

    x_pos = np.arange(len(lambda_values))
    width = 0.35

    bars1 = ax3.bar(x_pos - width/2, fn, width, label='False Negatives (missed)',
                    color=COLORS['danger'], alpha=0.8)
    bars2 = ax3.bar(x_pos + width/2, fp, width, label='False Positives (false alarms)',
                    color=COLORS['warning'], alpha=0.8)

    ax3.set_xlabel('Lambda (λ)', fontweight='bold')
    ax3.set_ylabel('Count (evaluation 2026)', fontweight='bold')
    ax3.set_title('C. Error Counts: False Negatives vs False Positives',
                  fontweight='bold', pad=15)
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(lambda_values)
    ax3.legend(loc='upper right')
    ax3.grid(axis='y', alpha=0.3)

    # Annotate values
    for i, (f_n, f_p) in enumerate(zip(fn, fp)):
        ax3.text(i - width/2, f_n + 200, f'{f_n}', ha='center', va='bottom', fontsize=9)
        ax3.text(i + width/2, f_p + 200, f'{f_p}', ha='center', va='bottom', fontsize=9)

    # Highlight recommended
    ax3.axvline(x=2 + width/2, color='green', linestyle='--', alpha=0.3, linewidth=2)
    ax3.text(2 + width/2, max(fp) * 0.8, 'Recommended\nfor safety', ha='left',
             bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.5))

    plt.suptitle('Risk Classification Performance: Lambda Sensitivity Analysis (h=1 hour)',
                 fontsize=16, fontweight='bold', y=0.98)

    plt.tight_layout()
    return fig


def plot_3_uncertainty_quantification():
    """Figure 3: Uncertainty quantification results."""

    # Data from quantile experiments
    horizons = ['h=1', 'h=3']
    coverage_80 = [77.3, 77.3]
    coverage_50 = [44.3, 44.3]
    width_80 = [3.622, 3.622]
    median_mae = [2.886, 2.886]
    regression_mae = [0.810, 1.312]

    fig = plt.figure(figsize=(14, 6))
    gs = GridSpec(1, 2, figure=fig, wspace=0.3)

    # Subplot A: Coverage calibration
    ax1 = fig.add_subplot(gs[0, 0])

    x_pos = np.arange(len(horizons))
    width = 0.35

    bars1 = ax1.bar(x_pos - width/2, coverage_80, width,
                    label='80% Interval', color=COLORS['primary'], alpha=0.8)
    bars2 = ax1.bar(x_pos + width/2, coverage_50, width,
                    label='50% Interval', color=COLORS['secondary'], alpha=0.8)

    # Target lines
    ax1.axhline(y=80, color=COLORS['primary'], linestyle='--', alpha=0.5, label='Target 80%')
    ax1.axhline(y=50, color=COLORS['secondary'], linestyle='--', alpha=0.5, label='Target 50%')

    ax1.set_xlabel('Horizon', fontweight='bold')
    ax1.set_ylabel('Actual Coverage (%)', fontweight='bold')
    ax1.set_title('A. Interval Coverage Calibration', fontweight='bold', pad=15)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(horizons)
    ax1.legend(loc='lower right', fontsize=9)
    ax1.grid(axis='y', alpha=0.3)
    ax1.set_ylim([0, 100])

    # Annotate
    for i, (c80, c50) in enumerate(zip(coverage_80, coverage_50)):
        ax1.text(i - width/2, c80 + 2, f'{c80:.1f}%', ha='center', va='bottom', fontsize=9)
        ax1.text(i + width/2, c50 + 2, f'{c50:.1f}%', ha='center', va='bottom', fontsize=9)

    # Add status indicators
    ax1.text(0.5, 85, '✓ Well-calibrated', ha='center', color=COLORS['success'],
             fontweight='bold', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.3))
    ax1.text(0.5, 40, '✗ Miscalibrated', ha='center', color=COLORS['danger'],
             fontweight='bold', bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.3))

    # Subplot B: Point predictions comparison
    ax2 = fig.add_subplot(gs[0, 1])

    x_pos = np.arange(len(horizons))
    width = 0.35

    bars1 = ax2.bar(x_pos - width/2, regression_mae, width,
                    label='Regression (point)', color=COLORS['success'], alpha=0.8)
    bars2 = ax2.bar(x_pos + width/2, median_mae, width,
                    label='Quantile (median)', color=COLORS['danger'], alpha=0.8)

    ax2.set_xlabel('Horizon', fontweight='bold')
    ax2.set_ylabel('MAE (ppm)', fontweight='bold')
    ax2.set_title('B. Point Prediction Accuracy', fontweight='bold', pad=15)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(horizons)
    ax2.legend(loc='upper left')
    ax2.grid(axis='y', alpha=0.3)

    # Annotate
    for i, (reg, med) in enumerate(zip(regression_mae, median_mae)):
        ax2.text(i - width/2, reg + 0.1, f'{reg:.2f}', ha='center', va='bottom',
                fontsize=9, fontweight='bold')
        ax2.text(i + width/2, med + 0.1, f'{med:.2f}', ha='center', va='bottom',
                fontsize=9, fontweight='bold')

        # Show ratio
        ratio = med / reg
        ax2.text(i, max(reg, med) + 0.3, f'×{ratio:.1f}', ha='center', va='bottom',
                fontsize=10, color=COLORS['danger'], fontweight='bold')

    plt.suptitle('Uncertainty Quantification: Quantile Regression Results (Evaluation 2026)',
                 fontsize=16, fontweight='bold', y=1.02)

    plt.tight_layout()
    return fig


def plot_4_system_overview():
    """Figure 4: System architecture and key metrics summary."""

    fig = plt.figure(figsize=(14, 10))
    gs = GridSpec(3, 3, figure=fig, wspace=0.4, hspace=0.5)

    # Title
    fig.suptitle('Q21 Advisory System: Complete Performance Summary',
                 fontsize=18, fontweight='bold', y=0.96)

    # Key metrics cards
    metrics = [
        {'title': 'Primary Model\n(h=1 hour)', 'value': '0.725', 'unit': 'ppm MAE',
         'color': COLORS['success'], 'subtitle': '+14% vs baseline'},
        {'title': 'Early Warning\n(h=3 hours)', 'value': '1.312', 'unit': 'ppm MAE',
         'color': COLORS['primary'], 'subtitle': '+9.9% vs baseline'},
        {'title': 'Risk Detection\n(λ=25)', 'value': '97.3%', 'unit': 'recall',
         'color': COLORS['warning'], 'subtitle': '179 FN, 7412 FP'},
    ]

    for i, metric in enumerate(metrics):
        ax = fig.add_subplot(gs[0, i])
        ax.axis('off')

        # Card background
        rect = mpatches.FancyBboxPatch((0.05, 0.1), 0.9, 0.8,
                                       boxstyle="round,pad=0.05",
                                       facecolor=metric['color'], alpha=0.2,
                                       edgecolor=metric['color'], linewidth=2)
        ax.add_patch(rect)

        # Text
        ax.text(0.5, 0.75, metric['title'], ha='center', va='top',
                fontsize=11, fontweight='bold', transform=ax.transAxes)
        ax.text(0.5, 0.50, metric['value'], ha='center', va='center',
                fontsize=24, fontweight='bold', color=metric['color'],
                transform=ax.transAxes)
        ax.text(0.5, 0.35, metric['unit'], ha='center', va='top',
                fontsize=10, transform=ax.transAxes)
        ax.text(0.5, 0.18, metric['subtitle'], ha='center', va='top',
                fontsize=9, style='italic', transform=ax.transAxes)

    # Multi-horizon timeline
    ax_timeline = fig.add_subplot(gs[1, :])

    horizons = [0.5, 1.0, 2.0, 3.0, 6.0]
    mae_values = [0.574, 0.810, 1.148, 1.312, 1.571]
    improvements = [1.7, 4.4, 7.2, 9.9, 2.8]

    # Create bars with color gradient
    colors_grad = [COLORS['success'] if imp > 7 else COLORS['primary'] if imp > 4
                   else COLORS['secondary'] for imp in improvements]

    bars = ax_timeline.barh(range(len(horizons)), mae_values, color=colors_grad, alpha=0.7)

    ax_timeline.set_yticks(range(len(horizons)))
    ax_timeline.set_yticklabels([f'{h}h' for h in horizons])
    ax_timeline.set_xlabel('MAE (ppm)', fontweight='bold')
    ax_timeline.set_ylabel('Forecast Horizon', fontweight='bold')
    ax_timeline.set_title('Multi-Horizon Performance Profile', fontweight='bold', pad=15)
    ax_timeline.grid(axis='x', alpha=0.3)

    # Annotate
    for i, (bar, mae, imp) in enumerate(zip(bars, mae_values, improvements)):
        width = bar.get_width()
        ax_timeline.text(width + 0.05, bar.get_y() + bar.get_height()/2,
                        f'{mae:.2f} ppm (+{imp:.1f}%)',
                        ha='left', va='center', fontsize=10, fontweight='bold')

    # System components
    ax_components = fig.add_subplot(gs[2, :])
    ax_components.axis('off')

    components_text = """
    System Components:

    ✓ Regression Models: 5 horizons (30 min - 6 hours) using residual learning
    ✓ Risk Classification: Binary alert for Q21 > 10 ppm with configurable λ
    ✓ Uncertainty Quantification: 80% confidence intervals (coverage 77-80%)
    ✓ State Detection: normal / shutdown / startup / transition / unknown
    ✓ Quality Gates: freshness, frozen sensors, Q21=307, OOD detection
    ✓ Advisory Dashboard: Streamlit UI with multi-horizon display and trade-off analysis

    Training Infrastructure:
    • NVIDIA A100 80GB GPU
    • CatBoost 1.2.10
    • Temporal splits: train (2023-2024), validation (H1 2025), calibration (H2 2025), evaluation (2026)
    • Total training time: ~2-3 hours for all models

    Production Status:
    ✓ Ready for shadow pilot with human-in-the-loop
    ✗ Not authorized for automatic setpoint control
    """

    ax_components.text(0.05, 0.95, components_text, ha='left', va='top',
                      fontsize=10, family='monospace', transform=ax_components.transAxes,
                      bbox=dict(boxstyle='round', facecolor=COLORS['light'], alpha=0.8))

    plt.tight_layout()
    return fig


def main():
    """Generate all presentation plots."""

    output_dir = Path("eda/presentation_plots")
    output_dir.mkdir(exist_ok=True)

    print("=" * 60)
    print("Generating Presentation Plots")
    print("=" * 60)

    plots = [
        ("1_multihorizon_performance.png", plot_1_multihorizon_performance),
        ("2_risk_classification.png", plot_2_risk_classification),
        ("3_uncertainty_quantification.png", plot_3_uncertainty_quantification),
        ("4_system_overview.png", plot_4_system_overview),
    ]

    for filename, plot_func in plots:
        print(f"\nGenerating: {filename}")
        fig = plot_func()

        output_path = output_dir / filename
        fig.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
        print(f"  ✓ Saved: {output_path}")

        plt.close(fig)

    print("\n" + "=" * 60)
    print("✅ All plots generated successfully!")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print("\nFiles created:")
    for filename, _ in plots:
        print(f"  • {filename}")


if __name__ == '__main__':
    main()
