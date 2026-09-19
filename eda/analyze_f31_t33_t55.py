"""Diagnostics for F31 flow and the temperatures T33/T55.

The analysis deliberately separates common operating state from short-term
dynamics.  It does not treat correlation as a causal or safe-control claim.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


EDA = Path(__file__).resolve().parent
ROOT = EDA.parent
OUT = EDA / "artifacts" / "f31_t33_t55"
OUT.mkdir(parents=True, exist_ok=True)
TAGS = ["F31", "T33", "T55"]


def corr_table(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    records = []
    for left, right in [("F31", "T33"), ("F31", "T55"), ("T33", "T55")]:
        x = frame[[left, right]].dropna()
        records.append(
            {
                "sample": label,
                "pair": f"{left}–{right}",
                "n": len(x),
                "pearson": x[left].corr(x[right], method="pearson"),
                "spearman": x[left].corr(x[right], method="spearman"),
            }
        )
    return pd.DataFrame(records)


def contiguous_differences(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep first differences only where timestamps remain 10 minutes apart."""
    d = frame[TAGS].diff()
    continuous = frame.index.to_series().diff().eq(pd.Timedelta(minutes=10))
    return d.loc[continuous]


def lag_table(diffs: pd.DataFrame, target: str, steps: int = 144) -> pd.DataFrame:
    """corr(ΔF31(t), Δtarget(t + lag)); positive lag means target follows."""
    rows = []
    for lag in range(-steps, steps + 1):
        aligned = pd.concat(
            [diffs["F31"], diffs[target].shift(-lag)], axis=1, keys=["F31", target]
        ).dropna()
        rows.append(
            {
                "target": target,
                "lag_steps_10min": lag,
                "lag_hours": lag / 6,
                "n": len(aligned),
                "pearson_change_corr": aligned["F31"].corr(aligned[target]),
                "spearman_change_corr": aligned["F31"].corr(
                    aligned[target], method="spearman"
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(
        ROOT / "data" / "avt_tags.csv", usecols=["date", *TAGS], parse_dates=["date"]
    ).set_index("date").sort_index()

    # Diagnostic cut, not an engineering operating envelope.  It removes the
    # obvious zero/near-zero shutdown segment before examining relationships.
    running = (df.F31 > 100) & (df.T33 > 250) & (df.T55 > 300)
    df["diagnostic_running"] = running

    profile = df[TAGS].describe(percentiles=[0.001, 0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 0.999]).T
    profile["nonpositive_n"] = (df[TAGS] <= 0).sum()
    profile["diagnostic_running_n"] = int(running.sum())
    profile.to_csv(OUT / "profile.csv")

    samples = {
        "all_records": df[TAGS],
        "diagnostic_running": df.loc[running, TAGS],
    }
    levels = pd.concat([corr_table(value, name) for name, value in samples.items()], ignore_index=True)

    # Dynamic signal: differencing suppresses slow shared season/regime drift.
    all_diffs = contiguous_differences(df)
    running_diffs = contiguous_differences(df.loc[running])
    changes = pd.concat(
        [corr_table(all_diffs, "all_records_10min_changes"), corr_table(running_diffs, "running_10min_changes")],
        ignore_index=True,
    )
    correlations = pd.concat([levels.assign(metric="levels"), changes.assign(metric="10min_changes")], ignore_index=True)
    correlations.to_csv(OUT / "correlations.csv", index=False)

    yearly = []
    for year, part in df.loc[running, TAGS].groupby(df.loc[running].index.year):
        yearly.append(corr_table(part, str(year)).assign(year=year))
    yearly = pd.concat(yearly, ignore_index=True)
    yearly.to_csv(OUT / "yearly_running_level_correlations.csv", index=False)

    # Quantile bins show the conditional median without forcing a straight line.
    bins = df.loc[running, TAGS].copy()
    bins["F31_bin"] = pd.qcut(bins.F31, q=20, duplicates="drop")
    conditional = (
        bins.groupby("F31_bin", observed=True)
        .agg(F31_median=("F31", "median"), n=("F31", "size"), T33_median=("T33", "median"), T33_mean=("T33", "mean"), T55_median=("T55", "median"), T55_mean=("T55", "mean"))
        .reset_index(drop=True)
    )
    conditional.to_csv(OUT / "conditional_temperature_by_f31_quantile.csv", index=False)

    lags = pd.concat([lag_table(running_diffs, target) for target in ["T33", "T55"]], ignore_index=True)
    lags.to_csv(OUT / "lagged_change_correlations.csv", index=False)
    strongest_lags = (
        lags.loc[lags.pearson_change_corr.abs().groupby(lags.target).transform("max").eq(lags.pearson_change_corr.abs())]
        .sort_values("target")
    )
    strongest_lags.to_csv(OUT / "strongest_lagged_change_correlations.csv", index=False)

    # Repeat at coarser medians.  If a material thermal relation is merely
    # hidden by 10-minute noise, it should become more visible here.
    coarse_rows = []
    for frequency in ["30min", "1h", "2h", "4h", "8h"]:
        coarse = df.loc[running, TAGS].resample(frequency).median().diff().dropna()
        for target in ["T33", "T55"]:
            coarse_rows.append(
                {"aggregation": frequency, "pair": f"F31–{target}", "n": len(coarse),
                 "pearson_change_corr": coarse.F31.corr(coarse[target]),
                 "spearman_change_corr": coarse.F31.corr(coarse[target], method="spearman")}
            )
    pd.DataFrame(coarse_rows).to_csv(OUT / "coarse_change_correlations.csv", index=False)

    # A deterministic time-stratified sample keeps interactive scatter usable.
    # Small stratified sample: the full record set remains in the CSV outputs.
    # This keeps the standalone HTML charts responsive in a notebook/browser.
    sample = df.loc[running, TAGS].iloc[::max(1, int(running.sum() / 1800))].reset_index()
    for temp in ["T33", "T55"]:
        fig = px.scatter(
            sample, x="F31", y=temp, color="date", opacity=0.45,
            title=f"{temp} versus F31: diagnostic running records",
            labels={"F31": "F31, расход нефтепродукта в П-3", temp: temp, "date": "Дата"},
            color_continuous_scale="Viridis",
        )
        fig.write_html(OUT / f"scatter_f31_{temp}.html", include_plotlyjs="cdn")

    long_cond = conditional.melt(
        id_vars=["F31_median", "n"], value_vars=["T33_median", "T55_median"],
        var_name="temperature", value_name="median_temperature",
    )
    fig = px.line(
        long_cond, x="F31_median", y="median_temperature", color="temperature", markers=True,
        title="Conditional temperature medians by F31 quantile",
        labels={"F31_median": "Медиана F31 в квантиле", "median_temperature": "Медиана температуры, °C", "temperature": "Параметр"},
    )
    fig.write_html(OUT / "conditional_temperature_by_f31.html", include_plotlyjs="cdn")

    fig = px.line(
        lags, x="lag_hours", y="pearson_change_corr", color="target",
        title="Lagged correlation of 10-minute changes: ΔF31(t) and ΔT(t + lag)",
        labels={"lag_hours": "Лаг, ч (положительный: температура после F31)", "pearson_change_corr": "Pearson r", "target": "Температура"},
    )
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.write_html(OUT / "lagged_change_correlations.html", include_plotlyjs="cdn")

    fig = go.Figure()
    for pair, part in yearly.groupby("pair"):
        fig.add_trace(go.Bar(name=pair, x=part.year.astype(str), y=part.pearson))
    fig.update_layout(
        barmode="group", title="Yearly Pearson correlations in diagnostic running records",
        xaxis_title="Год", yaxis_title="Pearson r",
    )
    fig.write_html(OUT / "yearly_running_correlations.html", include_plotlyjs="cdn")

    print("Running diagnostic share:", round(running.mean() * 100, 2), "%")
    print("\nLevel and dynamic correlations:\n", correlations.to_string(index=False))
    print("\nStrongest lagged change correlation:\n", strongest_lags.to_string(index=False))


if __name__ == "__main__":
    main()
