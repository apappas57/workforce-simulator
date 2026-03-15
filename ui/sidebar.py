import streamlit as st


def render_sidebar():
    with st.sidebar:
        st.header("Core inputs")
        interval_minutes = st.number_input("Interval length (minutes)", min_value=5, max_value=60, value=15, step=5)
        aht_seconds = st.number_input("AHT (seconds)", min_value=30, max_value=3600, value=360, step=10)
        shrinkage = st.slider("Shrinkage %", 0.0, 0.6, 0.35)
        occupancy_cap = st.slider("Occupancy cap %", 0.5, 1.0, 0.85)

        st.divider()
        st.header("Service level target (Erlang C)")
        sl_target = st.slider("Target SL %", 0.0, 1.0, 0.60)
        sl_threshold = st.number_input("SL threshold (seconds)", min_value=5, max_value=3600, value=180, step=5)

        st.divider()
        st.header("Demand input")
        uploaded = st.file_uploader("Upload demand CSV", type=["csv"])
        use_synth = st.toggle("Use synthetic day instead", value=(uploaded is None))
        avg_calls = st.slider("Avg calls per interval (synthetic)", 0, 500, 120)

        st.divider()
        st.header("Staffing supply input")
        staffing_uploaded = st.file_uploader("Upload staffing CSV", type=["csv"], key="staffing_upload")

        st.divider()
        st.header("Randomness")
        seed = st.number_input("Seed", min_value=0, max_value=999999, value=42, step=1)

        st.divider()
        st.header("Time zone")

        input_tz = st.selectbox(
            "Input start_ts time zone",
            ["UTC", "Australia/Melbourne"],
            index=0,
            help="What timezone the CSV start_ts column is in."
        )

        model_tz = st.selectbox(
            "Model / display time zone",
            ["Australia/Melbourne", "UTC"],
            index=0,
            help="Timezone used for interval bucketing, charts, and roster alignment."
        )

    return {
        "interval_minutes": int(interval_minutes),
        "aht_seconds": float(aht_seconds),
        "shrinkage": float(shrinkage),
        "occupancy_cap": float(occupancy_cap),
        "sl_target": float(sl_target),
        "sl_threshold_seconds": float(sl_threshold),
        "uploaded": uploaded,
        "use_synth": use_synth,
        "avg_calls": float(avg_calls),
        "staffing_uploaded": staffing_uploaded,
        "seed": int(seed),
        "input_tz": input_tz,
        "model_tz": model_tz,
    }