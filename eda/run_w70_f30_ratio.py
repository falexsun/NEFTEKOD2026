"""Standalone W70/F30 analysis.

From the repository root:
    uv run --project project python eda/run_w70_f30_ratio.py
"""

from pathlib import Path

import pandas as pd
import plotly.express as px


EDA_DIR = Path(__file__).resolve().parent
ROOT = EDA_DIR.parent
DATA_FILE = ROOT / "data" / "avt_tags.csv"
ARTIFACTS = EDA_DIR / "artifacts"

if not DATA_FILE.is_file():
    raise FileNotFoundError(f"Не найден исходный файл: {DATA_FILE}")

ARTIFACTS.mkdir(parents=True, exist_ok=True)

raw = pd.read_csv(DATA_FILE, parse_dates=["date"], low_memory=False)
raw = raw.drop(
    columns=[column for column in raw.columns if column.startswith("Unnamed:")],
    errors="ignore",
)

required = {"date", "F30", "W70"}
missing = required.difference(raw.columns)
if missing:
    raise ValueError(f"В CSV отсутствуют обязательные колонки: {sorted(missing)}")

raw["ratio"] = raw["W70"] / raw["F30"]

# Diagnostic data mask, not a process operating limit.
valid_mask = raw["F30"].between(10, 200) & raw["W70"].gt(0)
data = raw.loc[valid_mask, ["date", "F30", "W70", "ratio"]].copy()

median = data["ratio"].median()
mad = (data["ratio"] - median).abs().median()
quantiles = data["ratio"].quantile(
    [0.001, 0.005, 0.01, 0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975, 0.99, 0.995, 0.999]
)
p01, p99 = data["ratio"].quantile([0.01, 0.99])

summary = pd.DataFrame(
    [
        {
            "all_rows": len(raw),
            "working_rows": len(data),
            "working_share_pct": 100 * len(data) / len(raw),
            "mean": data["ratio"].mean(),
            "std": data["ratio"].std(),
            "coefficient_of_variation_pct": 100 * data["ratio"].std() / data["ratio"].mean(),
            "median": median,
            "MAD": mad,
            "robust_sigma": 1.4826 * mad,
            "robust_coefficient_of_variation_pct": 100 * 1.4826 * mad / median,
            "p01": p01,
            "p05": data["ratio"].quantile(0.05),
            "p95": data["ratio"].quantile(0.95),
            "p99": p99,
            "share_within_1pct": 100 * ((data["ratio"] / median - 1).abs() <= 0.01).mean(),
            "share_within_2pct": 100 * ((data["ratio"] / median - 1).abs() <= 0.02).mean(),
        }
    ]
)

yearly = (
    data.assign(year=data["date"].dt.year)
    .groupby("year")["ratio"]
    .agg(
        n="size",
        mean="mean",
        std="std",
        median="median",
        p01=lambda values: values.quantile(0.01),
        p99=lambda values: values.quantile(0.99),
    )
    .reset_index()
)

monthly = (
    data.set_index("date")["ratio"]
    .resample("MS")
    .agg(
        count="size",
        mean="mean",
        median="median",
        std="std",
        p01=lambda values: values.quantile(0.01),
        p99=lambda values: values.quantile(0.99),
    )
    .reset_index()
)

summary.to_csv(ARTIFACTS / "w70_f30_ratio_summary.csv", index=False)
quantiles.rename("ratio").rename_axis("quantile").reset_index().to_csv(
    ARTIFACTS / "w70_f30_ratio_quantiles.csv", index=False
)
yearly.to_csv(ARTIFACTS / "w70_f30_ratio_yearly.csv", index=False)
monthly.to_csv(ARTIFACTS / "w70_f30_ratio_monthly.csv", index=False)

central = data[data["ratio"].between(p01, p99)]
figure = px.histogram(
    central,
    x="ratio",
    nbins=120,
    title="W70/F30: центральные 98% рабочих наблюдений",
)
figure.write_html(
    ARTIFACTS / "w70_f30_ratio_distribution.html",
    include_plotlyjs="cdn",
)

print("\nW70/F30 — итоговая статистика")
print(summary.to_string(index=False))
print(f"\nРезультаты сохранены в: {ARTIFACTS}")
print("Интерактивный график: w70_f30_ratio_distribution.html")
