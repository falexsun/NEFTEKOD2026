"""
Streamlit dashboard for Q21 Advisory System.
Production-like demonstration interface for hackathon finale.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, timedelta
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.inference.advisory_system import Q21AdvisorySystem, AdvisoryRecommendation
from src.inference.state_detector import PlantState


# Page config
st.set_page_config(
    page_title="Q21 Advisory System",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .big-metric { font-size: 2.5rem; font-weight: bold; }
    .risk-low { color: #28a745; }
    .risk-medium { color: #ffc107; }
    .risk-high { color: #fd7e14; }
    .risk-critical { color: #dc3545; }
    .state-box { padding: 1rem; border-radius: 0.5rem; margin: 0.5rem 0; }
    .normal { background-color: #d4edda; border-left: 4px solid #28a745; }
    .warning { background-color: #fff3cd; border-left: 4px solid #ffc107; }
    .critical { background-color: #f8d7da; border-left: 4px solid #dc3545; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def load_advisory_system(lambda_penalty: int):
    """Load and cache advisory system."""
    models_dir = project_root / "eda" / "experiments" / "q21_target_asymmetric_v3_20260915" / "models"
    return Q21AdvisorySystem(models_dir, lambda_penalty=lambda_penalty)


def render_state_indicator(state: PlantState):
    """Render plant state indicator."""
    if state == PlantState.NORMAL:
        st.markdown('<div class="state-box normal">✅ <b>Plant State:</b> NORMAL - Advisory Active</div>',
                   unsafe_allow_html=True)
    elif state == PlantState.SHUTDOWN:
        st.markdown('<div class="state-box warning">⚠️ <b>Plant State:</b> SHUTDOWN - Advisory Suspended</div>',
                   unsafe_allow_html=True)
    elif state == PlantState.STARTUP:
        st.markdown('<div class="state-box warning">🔄 <b>Plant State:</b> STARTUP - Advisory Suspended</div>',
                   unsafe_allow_html=True)
    else:
        st.markdown('<div class="state-box critical">❌ <b>Plant State:</b> UNKNOWN - Advisory Not Available</div>',
                   unsafe_allow_html=True)


def render_risk_gauge(probability: float, risk_level: str):
    """Render risk probability gauge."""
    color_map = {
        "LOW": "green",
        "MEDIUM": "yellow",
        "HIGH": "orange",
        "CRITICAL": "red"
    }

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=probability * 100,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': "Exceedance Risk (Q21 > 10 ppm)"},
        number={'suffix': "%"},
        gauge={
            'axis': {'range': [None, 100]},
            'bar': {'color': color_map.get(risk_level, "gray")},
            'steps': [
                {'range': [0, 10], 'color': "lightgreen"},
                {'range': [10, 30], 'color': "lightyellow"},
                {'range': [30, 60], 'color': "orange"},
                {'range': [60, 100], 'color': "lightcoral"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': 50
            }
        }
    ))

    fig.update_layout(height=300, margin=dict(l=20, r=20, t=50, b=20))
    return fig


def render_q21_forecast(current: float, forecast: float):
    """Render Q21 current vs forecast comparison."""
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=['Current', 'Forecast (+1h)'],
        y=[current, forecast],
        marker_color=['lightblue', 'lightcoral' if forecast > 10 else 'lightgreen'],
        text=[f"{current:.1f} ppm", f"{forecast:.1f} ppm"],
        textposition='auto'
    ))

    # Add limit line
    fig.add_hline(y=10, line_dash="dash", line_color="red",
                  annotation_text="Spec Limit (10 ppm)")

    fig.update_layout(
        title="Q21 Sulfur Content",
        yaxis_title="Q21 (ppm)",
        height=300,
        showlegend=False,
        margin=dict(l=20, r=20, t=50, b=20)
    )

    return fig


def main():
    st.title("🛢️ Q21 Sulfur Advisory System")
    st.markdown("**Production-like advisory for kerosene sulfur monitoring**")
    st.markdown("---")

    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")

        lambda_penalty = st.selectbox(
            "Risk Penalty (λ)",
            options=[10, 25],
            index=1,
            help="λ=25: safety-oriented (high recall). λ=10: balanced trade-off."
        )

        st.markdown("---")
        st.markdown("### 📊 System Information")
        st.info("""
        **Model:** Q21 target h=1h
        **Training:** Sep 2026
        **Horizon:** 1 hour ahead
        **Status:** Demo/Shadow Pilot
        """)

        st.markdown("---")
        st.markdown("### ⚠️ Important Disclaimers")
        st.warning("""
        **NOT for automated control**

        This is an observational prediction system based on historical patterns, not validated causal relationships.

        Recommendations require expert review before action.
        """)

    # Load system
    try:
        advisory_system = load_advisory_system(lambda_penalty)
        st.success("✅ Advisory system loaded successfully")
    except Exception as e:
        st.error(f"❌ Failed to load advisory system: {e}")
        return

    # Main dashboard area
    col1, col2, col3 = st.columns(3)

    # Demo data selector
    demo_mode = st.checkbox("Use demo data", value=True)

    if demo_mode:
        # Generate demo telemetry
        telemetry = pd.DataFrame({
            'timestamp': pd.date_range(end=pd.Timestamp.now(), periods=12, freq='10min'),
            'Q21': [8.2, 8.5, 8.7, 9.1, 9.3, 9.5, 9.8, 10.2, 10.5, 10.8, 11.1, 11.3],
            'F30': [100.5] * 12,
            'F31': [45.2] * 12,
            'W70': [78.5] * 12,
            'T33': [285.3] * 12,
            'T55': [365.7] * 12
        })
        current_q21 = telemetry['Q21'].iloc[-1]

        # Generate advisory
        with st.spinner("Generating advisory..."):
            advisory = advisory_system.generate_advisory(telemetry, current_q21)

        # Render state
        render_state_indicator(advisory.plant_state)

        if advisory.plant_state == PlantState.NORMAL and advisory.reason_code == "OK":
            # Metrics row
            with col1:
                risk_class = f"risk-{advisory.exceedance_risk.lower()}"
                st.markdown(f'<div class="{risk_class}"><div class="big-metric">{advisory.q21_current:.1f}</div></div>',
                           unsafe_allow_html=True)
                st.caption("Current Q21 (ppm)")

            with col2:
                st.markdown(f'<div class="big-metric">{advisory.q21_forecast_1h:.1f}</div>',
                           unsafe_allow_html=True)
                st.caption("Forecast +1h (ppm)")

            with col3:
                st.markdown(f'<div class="big-metric">{advisory.exceedance_probability:.1%}</div>',
                           unsafe_allow_html=True)
                st.caption("Exceedance Risk")

            st.markdown("---")

            # Visualizations
            viz_col1, viz_col2 = st.columns(2)

            with viz_col1:
                st.plotly_chart(
                    render_q21_forecast(advisory.q21_current, advisory.q21_forecast_1h),
                    use_container_width=True
                )

            with viz_col2:
                st.plotly_chart(
                    render_risk_gauge(advisory.exceedance_probability, advisory.exceedance_risk),
                    use_container_width=True
                )

            st.markdown("---")

            # Recommendation
            st.subheader("💡 Advisory Recommendation")

            if advisory.action == "MONITOR":
                st.success(f"✅ **{advisory.action}**: {advisory.message}")
            elif advisory.action == "INVESTIGATE":
                st.warning(f"⚠️ **{advisory.action}**: {advisory.message}")
            else:
                st.info(f"ℹ️ **{advisory.action}**: {advisory.message}")

            # Confidence and details
            detail_col1, detail_col2 = st.columns(2)
            with detail_col1:
                st.metric("Confidence", advisory.confidence)
            with detail_col2:
                st.metric("Risk Level", advisory.exceedance_risk)

            # Model info expander
            with st.expander("📋 Model Information"):
                st.json({
                    "lambda_penalty": lambda_penalty,
                    "threshold": advisory.details.get('threshold'),
                    "horizon_hours": advisory.details.get('model_horizon_hours'),
                    "model_sha256": advisory_system.model_bundle.risk_meta.model_sha256[:16] + "...",
                    "training_date": "2026-09-15"
                })

        else:
            # No action state
            st.error(f"**{advisory.reason_code}**: {advisory.message}")
            if advisory.validation_failures:
                with st.expander("Validation Details"):
                    for failure in advisory.validation_failures:
                        st.warning(f"**{failure.reason_code}**: {failure.message}")

    else:
        st.info("Upload telemetry data or connect to live data source")

    # Footer
    st.markdown("---")
    st.markdown("""
    <small>
    **Q21 Advisory System v1.0** | NEFTECODE 2026 Hackathon
    Production-like advisory prototype | NOT for automated control
    Requires expert validation before operational use
    </small>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
