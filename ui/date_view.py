import streamlit as st


def render_date_view_controls(df, key_prefix: str):
    """
    Returns:
        view_mode: "Full horizon" or "Selected day"
        selected_day: selected date_local value or None
    """
    if "date_local" not in df.columns or df["date_local"].dropna().empty:
        return "Full horizon", None

    days = sorted(df["date_local"].dropna().astype(str).drop_duplicates().tolist())

    c1, c2 = st.columns([1, 1])
    with c1:
        view_mode = st.radio(
            "View mode",
            ["Full horizon", "Selected day"],
            horizontal=True,
            key=f"{key_prefix}_view_mode",
        )

    selected_day = None
    if view_mode == "Selected day":
        with c2:
            selected_day = st.selectbox(
                "Select day",
                options=days,
                index=0,
                key=f"{key_prefix}_selected_day",
            )

    return view_mode, selected_day

def ensure_x_col(df, x_col):
    if x_col not in df.columns and "interval" in df.columns:
        df = df.copy()
        df[x_col] = df["interval"]
    return df

def apply_date_view(df, view_mode: str, selected_day):
    if (
        view_mode == "Selected day"
        and selected_day is not None
        and "date_local" in df.columns
    ):
        return df[df["date_local"].astype(str) == str(selected_day)].copy()
    return df.copy()