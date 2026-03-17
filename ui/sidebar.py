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
            min_value=5, max_value=60, step=5,
            key="sb_interval_minutes",
        )
        st.number_input(
            "AHT (seconds)",
            min_value=30, max_value=3600, step=10,
            key="sb_aht_seconds",
        )
        st.slider("Shrinkage %", 0.0, 0.6, key="sb_shrinkage")
        st.slider("Occupancy cap %", 0.5, 1.0, key="sb_occupancy_cap")

        st.divider()
        st.header("Service level target (Erlang C)")
        st.slider("Target SL %", 0.0, 1.0, key="sb_sl_target")
        st.number_input(
            "SL threshold (seconds)",
            min_value=5, max_value=3600, step=5,
            key="sb_sl_threshold_seconds",
        )

        st.divider()
        st.header("Demand input")
        with st.expander("CSV format", expanded=False):
            st.markdown(
                "**Option A — interval-indexed** *(single day)*\n\n"
                "| Column | Required | Notes |\n"
                "|---|---|---|\n"
                "| `interval` | ✅ | Integer index (0, 1, 2 …) |\n"
                "| `calls_offered` | ✅ | Calls in this interval |\n"
                "| `aht_seconds` | optional | Overrides sidebar AHT |\n\n"
                "**Option B — timestamp-indexed** *(single or multi-day)*\n\n"
                "| Column | Required | Notes |\n"
                "|---|---|---|\n"
                "| `start_ts` | ✅ | ISO 8601 timestamp |\n"
                "| `calls_offered` | ✅ | Calls in this interval |\n"
                "| `aht_seconds` | optional | Overrides sidebar AHT |\n\n"
                "Timezone is set by the Time Zone section below."
            )
        uploaded = st.file_uploader("Upload demand CSV", type=["csv"])
        use_synth = st.toggle("Use synthetic day instead", value=(uploaded is None))
        st.slider(
            "Avg calls per interval (synthetic)",
            0, 500,
            key="sb_avg_calls",
        )

        st.divider()
        st.header("Staffing supply input")
        with st.expander("CSV format", expanded=False):
            st.markdown(
                "**Required** (one of):\n\n"
                "| Column | Notes |\n"
                "|---|---|\n"
                "| `interval` | Integer index matching demand intervals |\n"
                "| `start_ts` | ISO 8601 timestamp (use with timezone below) |\n\n"
                "| `available_staff` | ✅ Always required |\n\n"
                "**Optional columns:**\n\n"
                "| Column | Notes |\n"
                "|---|---|\n"
                "| `activity` | Activity label — enables observed shrinkage calculation |\n"
                "| `team` | Team or queue identifier |\n"
                "| `queue` | Queue name |\n"
                "| `paid_hours` | Paid hours for this interval |\n\n"
                "Multiple rows per interval are supported (e.g. one row per activity)."
            )
        staffing_uploaded = st.file_uploader(
            "Upload staffing CSV", type=["csv"], key="staffing_upload"
        )

        st.divider()
        st.header("Finance & operations")
        st.caption(
            "Used by the Cost Analytics tab. All costs in local currency (£ by default)."
        )

        st.selectbox(
            "Agent cost rate type",
            ["Hourly (£/hr)", "Annualised (£/year)"],
            help=(
                "Hourly: direct cost per productive agent per hour.\n\n"
                "Annualised: total all-in annual cost (salary + on-costs). "
                "Divided by Annual working hours below to derive the effective hourly rate."
            ),
            key="sb_cost_rate_type",
        )

        _rate_label = (
            "Agent cost rate (£/hr)"
            if st.session_state.get("sb_cost_rate_type", "Hourly (£/hr)") == "Hourly (£/hr)"
            else "Agent cost rate (£/year)"
        )
        st.number_input(
            _rate_label,
            min_value=0.0,
            max_value=500_000.0,
            step=0.5,
            help="All-in cost per productive agent at the rate type selected above.",
            key="sb_agent_cost_rate",
        )

        if st.session_state.get("sb_cost_rate_type", "Hourly (£/hr)") == "Annualised (£/year)":
            st.number_input(
                "Annual working hours per FTE",
                min_value=100,
                max_value=3000,
                step=10,
                help=(
                    "Productive hours per FTE per year used to convert the annualised "
                    "rate to an effective hourly rate.\n\n"
                    "Common values: 1,820 (35 hr/wk), 1,950 (37.5 hr/wk), 2,080 (40 hr/wk)."
                ),
                key="sb_annual_working_hours",
            )

        st.number_input(
            "SLA breach penalty (£/abandoned call)",
            min_value=0.0,
            max_value=10_000.0,
            step=0.5,
            help=(
                "Financial cost assigned to each call that abandons before being answered. "
                "Acts as a proxy for re-contact cost, escalation cost, or SLA contractual penalty."
            ),
            key="sb_penalty_per_abandoned",
        )

        with st.expander("Advanced cost settings", expanded=False):
            st.slider(
                "Idle time cost fraction",
                min_value=0.0,
                max_value=1.0,
                step=0.05,
                help=(
                    "Fraction of the hourly rate applied to surplus (idle) agent-time. "
                    "1.0 = idle agents cost the same as busy agents (full wage). "
                    "0.5 = idle time is half-costed (e.g. agents have back-office tasks). "
                    "0.0 = idle time has no financial impact."
                ),
                key="sb_idle_rate_fraction",
            )

        st.divider()
        st.header("Randomness")
        st.number_input(
            "Seed",
            min_value=0, max_value=999999, step=1,
            key="sb_seed",
        )

        st.divider()
        st.header("Time zone")
        st.selectbox(
            "Input start_ts time zone",
            ["UTC", "Australia/Melbourne"],
            help="What timezone the CSV start_ts column is in.",
            key="sb_input_tz",
        )
        st.selectbox(
            "Model / display time zone",
            ["Australia/Melbourne", "UTC"],
            help="Timezone used for interval bucketing, charts, and roster alignment.",
            key="sb_model_tz",
        )

    # --- Cost config: convert annualised rate to hourly if needed ---------- #
    _rate_type  = st.session_state.get("sb_cost_rate_type", "Hourly (£/hr)")
    _raw_rate   = float(st.session_state.get("sb_agent_cost_rate", 30.0))
    _annual_hrs = float(st.session_state.get("sb_annual_working_hours", 1820))
    _hourly_rate = (
        _raw_rate / _annual_hrs
        if _rate_type == "Annualised (£/year)" and _annual_hrs > 0
        else _raw_rate
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
        # Phase 13: cost config
        "hourly_agent_cost":    _hourly_rate,
        "penalty_per_abandoned": float(st.session_state.get("sb_penalty_per_abandoned", 8.0)),
        "idle_rate_fraction":   float(st.session_state.get("sb_idle_rate_fraction", 1.0)),
    }
