"""Streamlit Dashboard for NefteKod diesel fuel quality system."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
    page_title="NefteKod — Diesel Fuel Quality Control",
    page_icon="⛽",
    layout="wide",
)

st.title("NefteKod — Система управления качеством дизельного топлива")
st.caption("Мультиагентная система | АВТ → Гидроочистка → Блендинг")


# ── Helper functions ────────────────────────────────────────────

@st.cache_data
def load_audit_data():
    reports_dir = PROJECT_ROOT / "reports"
    audit_path = reports_dir / "data_audit.json"
    if audit_path.exists():
        with open(audit_path) as f:
            return json.load(f)
    return None

@st.cache_data
def load_metrics():
    reports_dir = PROJECT_ROOT / "reports"
    metrics_path = reports_dir / "ml_baseline_metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as f:
            return json.load(f)
    return None


# ── Sidebar ─────────────────────────────────────────────────────

page = st.sidebar.selectbox(
    "Страница",
    ["Overview", "Data Quality", "Models", "Recommendation", "Decision Trace", "Training"],
)

# ── Overview Page ───────────────────────────────────────────────

if page == "Overview":
    st.header("Обзор состояния системы")

    col1, col2, col3, col4 = st.columns(4)

    metrics = load_metrics()
    if metrics:
        with col1:
            st.metric("Набор данных", f"{metrics.get('dataset_info', {}).get('total_samples', 0):,} записей")
        with col2:
            st.metric("Признаки", metrics.get('dataset_info', {}).get('n_features', 0))
        with col3:
            catboost = metrics.get('chronological_split_metrics', {}).get('catboost', {})
            if isinstance(catboost, dict) and 'rmse' in catboost:
                st.metric("CatBoost RMSE", f"{catboost['rmse']:.3f}")
            else:
                st.metric("CatBoost RMSE", "N/A")
        with col4:
            if isinstance(catboost, dict) and 'r2' in catboost:
                st.metric("CatBoost R²", f"{catboost['r2']:.3f}")
            else:
                st.metric("CatBoost R²", "N/A")

    st.subheader("Архитектура системы")
    st.markdown("""
    ```
    DATA SOURCES (AVT / 24-2000 / LIMS / PAK)
        │
        ▼
    INGESTION SERVICE
        │
        ▼
    FEATURE SERVICE / STATE BUILDER
        │
        ▼
    PROCESS STATE
        │
        ├── DATA QUALITY AGENT
        ├── QUALITY AGENT (ML)
        └── RELIABILITY AGENT
                │
                ▼
        OPTIMIZATION AGENT
                │
                ▼
        SAFETY AGENT (deterministic)
                │
                ▼
        ORCHESTRATOR AGENT
                │
                ▼
        RECOMMENDATION / ABSTAIN
    ```
    """)

# ── Data Quality Page ───────────────────────────────────────────

elif page == "Data Quality":
    st.header("Качество данных")

    audit = load_audit_data()
    if audit:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("AVT теги")
            avt = audit.get("avt_tags", {})
            if "error" not in avt:
                st.write(f"**Записей:** {avt.get('rows', 0):,}")
                st.write(f"**Столбцов:** {avt.get('columns', 0)}")
                st.write(f"**Период:** {avt.get('date_range', {}).get('min', 'N/A')} – {avt.get('date_range', {}).get('max', 'N/A')}")
                st.write(f"**Пропуски:** {avt.get('total_missing_ratio', 0):.4%}")
                st.write(f"**Дубликаты:** {avt.get('duplicate_timestamps', 0)}")

        with col2:
            st.subheader("24-2000 теги")
            u24 = audit.get("unit_242000_tags", {})
            if "error" not in u24:
                st.write(f"**Записей:** {u24.get('rows', 0):,}")
                st.write(f"**Столбцов:** {u24.get('columns', 0)}")
                st.write(f"**Период:** {u24.get('date_range', {}).get('min', 'N/A')} – {u24.get('date_range', {}).get('max', 'N/A')}")
                st.write(f"**Пропуски:** {u24.get('total_missing_ratio', 0):.4%}")

        st.subheader("Сера (target)")
        sulfur = audit.get("sulfur_target", {}).get("pak_sulfur", {})
        if sulfur:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Среднее", f"{sulfur.get('mean', 0):.2f} мг/кг")
            with col2:
                st.metric("Медиана", f"{sulfur.get('median', 0):.2f} мг/кг")
            with col3:
                st.metric("Макс", f"{sulfur.get('max', 0):.2f} мг/кг")
            with col4:
                st.metric("Нарушений (>10)", f"{sulfur.get('count_above_10', 0)}")
    else:
        st.warning("Данные аудита не найдены. Запустите `uv run python scripts/data_audit.py`")

# ── Models Page ─────────────────────────────────────────────────

elif page == "Models":
    st.header("ML модели")

    metrics = load_metrics()
    if metrics:
        st.subheader("Результаты обучения (chronological split)")

        # Metrics table
        data = []
        for name, m in metrics.get("chronological_split_metrics", {}).items():
            if isinstance(m, dict) and "error" not in m:
                data.append({
                    "Модель": name,
                    "MAE": f"{m.get('mae', 0):.3f}",
                    "RMSE": f"{m.get('rmse', 0):.3f}",
                    "R²": f"{m.get('r2', 0):.3f}",
                    "Recall(viol)": f"{m.get('recall_violation', 0):.3f}",
                    "Precision(viol)": f"{m.get('precision_violation', 0):.3f}",
                    "FSR": f"{m.get('false_safe_rate', 0):.3f}",
                })

        if data:
            st.dataframe(pd.DataFrame(data), use_container_width=True)

        st.subheader("Walk-forward валидация")
        wf_data = []
        for name, m in metrics.get("walk_forward_metrics", {}).items():
            if isinstance(m, dict) and "error" not in m:
                wf_data.append({
                    "Fold": name,
                    "MAE": f"{m.get('mae', 0):.3f}",
                    "RMSE": f"{m.get('rmse', 0):.3f}",
                    "R²": f"{m.get('r2', 0):.3f}",
                })
        if wf_data:
            st.dataframe(pd.DataFrame(wf_data), use_container_width=True)

        # Feature importance
        imp_path = PROJECT_ROOT / "reports" / "catboost_feature_importance.csv"
        if imp_path.exists():
            st.subheader("Важность признаков (CatBoost)")
            imp = pd.read_csv(imp_path, index_col=0).head(20)
            st.bar_chart(imp)
    else:
        st.warning("Метрики не найдены. Запустите `uv run python scripts/run_pipeline.py`")

# ── Recommendation Page ─────────────────────────────────────────

elif page == "Recommendation":
    st.header("Рекомендация")
    st.info("Для получения рекомендации используйте API: `POST /decision`")
    st.code("""
curl -X POST http://localhost:8000/decision \\
  -H "Content-Type: application/json" \\
  -d '{
    "avt_telemetry": {"T1": 130.5, "T6": 234.2},
    "unit_242000_telemetry": {"T5": 365.1, "T6": 8.5}
  }'
    """)

# ── Decision Trace Page ─────────────────────────────────────────

elif page == "Decision Trace":
    st.header("Decision Trace")
    st.info("Логи решений будут отображаться здесь при работе системы в realtime.")

# ── Training Page ───────────────────────────────────────────────

elif page == "Training":
    st.header("Обучение моделей")

    metrics = load_metrics()
    if metrics:
        ds = metrics.get("dataset_info", {})
        st.write(f"**Период данных:** {ds.get('date_range', {}).get('start', 'N/A')} – {ds.get('date_range', {}).get('end', 'N/A')}")
        st.write(f"**Всего образцов:** {ds.get('total_samples', 0):,}")
        st.write(f"**Train:** {ds.get('train_samples', 0):,} | **Val:** {ds.get('val_samples', 0):,} | **Test:** {ds.get('test_samples', 0):,}")
        st.write(f"**Признаков:** {ds.get('n_features', 0)}")
        st.write(f"**Target:** {ds.get('target', 'N/A')}")
