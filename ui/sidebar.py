import streamlit as st


def render_sidebar():
    """Render the global sidebar and return all input values.

    Phase 9: every persistent widget uses a key= prefixed with sb_ so that
    values saved by state_manager are automatically picked up on reload.
    The value= args serve as documentation of factory defaults; on subsequent
    loads the pre-populated session state takes precedence.
    """
    with st.sidebar:
        st.header("Core inputs")
        st.number_input(
            "Interval length (minutes)",
            min_value=5, max_value=60, value=15, step=5,
            key="sb_interval_minutes",
        )
        st.number_input(
            "AHT (seconds)",
            min_value=30, max_value=3600, value=360, step=10,
            key="sb_aht_seconds",
        )
        st.slider("Shrinkage %", 0.0, 0.6, 0.35, key="sb_shrinkage")
        st.slider("Occupancy cap %", 0.5, 1.0, 0.85, key="sb_occupancy_cap")

        st.divider()
        st.header("Service level target (Erlang C)")
        st.slider("Target SL %", 0.0, 1.0, 0.60, key="sb_sl_target")
        st.number_input(
            "SL threshold (seconds)",
            min_value=5, max_value=3600, value=180, step=5,
            key="sb_sl_threshold_seconds",
        )

        st.divider()
        st.header("Demand input")
        uploaded = st.file_uploader("Upload demand CSV", type=["csv"])
        use_synth = st.toggle("Use synthetic day instead", value=(uploaded is None))
        st.slider(
            "Avg calls per interval (synthetic)",
            0, 500, 120,
            key="sb_avg_calls",
        )

        st.divider()
        st.header("Staffing supply input")
        staffing_uploaded = st.file_uploader(
            "Upload staffing CSV", type=["csv"], key="staffing_upload"
        )

        st.divider()
        st.header("Randomness")
        st.number_input(
            "Seed",
            min_value=0, max_value=999999, value=42, step=1,
            key="sb_seed",
        )

        st.divider()
        st.header("Time zone")
        st.selectbox(
            "Input start_ts time zone",
            ["UTC", "Australia/Melbourne"],
            index=0,
            help="What timezone the CSV start_ts column is in.",
            key="sb_input_tz",
        )
        st.selectbox(
            "Model / display time zone",
            ["Australia/Melbourne", "UTC"],
            index=0,
            help="Timezone used for interval bucketing, charts, and roster alignment.",
            key="sb_model_tz",
        )

    return {
        "interval_minutes":     int(st.session_state["sb_interval_minutes"]),
        "aht_seconds":          float(st.session_state["sb_aht_seconds"]),
        "shrinkage":            float(st.session_state["sb_shrinkage"]),
        "occupancy_cap":        float(st.session_state["sb_occupancy_cap"]),
        "sl_target":            float(st.session_state["sb_sl_target"]),
        "sl_threshold_seconds": float(st.session_state["sb_sl_threshold_seconds"]),
        "uploaded":             uploaded,
        "use_synth":            use_synth,
        "avg_calls":            float(st.session_state["sb_avg_calls"]),
        "staffing_uploaded":    staffing_uploaded,
        "seed":                 int(st.session_state["sb_seed"]),
        "input_tz":             st.session_state["sb_input_tz"],
        "model_tz":             st.session_state["sb_model_tz"],
    }
