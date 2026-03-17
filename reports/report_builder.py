"""reports/report_builder.py

PDF report generation engine for Phase 12.

Uses reportlab Platypus for A4 layout (20 mm margins) and matplotlib
(non-interactive Figure class, Agg-safe) for chart-to-PNG rendering.
No kaleido / Plotly dependency required.

Public API
----------
ReportConfig : dataclass
build_report(config: ReportConfig, data: dict) -> bytes
"""

import datetime
import io
from dataclasses import dataclass, field

import matplotlib.figure
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

NAVY   = colors.HexColor("#1B2A4A")
BLUE   = colors.HexColor("#2C6FAC")
LTBLUE = colors.HexColor("#EBF5FB")
WHITE  = colors.white
GREY   = colors.HexColor("#F5F5F5")
DGREY  = colors.HexColor("#CCCCCC")
BLACK  = colors.black

# Page geometry constants (points)
_PAGE_W   = A4[0]
_MARGIN   = 20 * mm
_CONTENT_W = _PAGE_W - 2 * _MARGIN   # usable width in points
_CHART_W_IN = _CONTENT_W / 72.0       # convert points to inches
_CHART_H_IN = 2.8                     # standard chart height in inches


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class ReportConfig:
    """Configuration for the workforce simulation PDF report.

    Attributes
    ----------
    org_name : str
        Organisation name on the cover and document metadata.
    report_date : datetime.date
        Report date shown on the cover.
    include_demand : bool
        Include the Demand & Erlang C section.
    include_des : bool
        Include the DES Simulation Results section.
    include_roster : bool
        Include the Roster & Coverage Gaps section.
    include_workforce : bool
        Include the Workforce Planning & Hiring Optimisation section.
    """

    org_name: str = "Organisation"
    report_date: datetime.date = field(default_factory=datetime.date.today)
    include_demand: bool = True
    include_des: bool = True
    include_roster: bool = True
    include_workforce: bool = True


# ---------------------------------------------------------------------------
# Paragraph styles
# ---------------------------------------------------------------------------

def _make_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "cover_title", parent=base["Title"],
            fontName="Helvetica-Bold", fontSize=28,
            textColor=NAVY, spaceAfter=6,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", parent=base["Normal"],
            fontName="Helvetica", fontSize=14,
            textColor=BLUE, spaceAfter=4,
        ),
        "cover_meta": ParagraphStyle(
            "cover_meta", parent=base["Normal"],
            fontName="Helvetica", fontSize=11,
            textColor=colors.HexColor("#555555"), spaceAfter=6,
        ),
        "section_h1": ParagraphStyle(
            "section_h1", parent=base["Heading1"],
            fontName="Helvetica-Bold", fontSize=16,
            textColor=NAVY, spaceBefore=14, spaceAfter=6,
        ),
        "section_h2": ParagraphStyle(
            "section_h2", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=12,
            textColor=BLUE, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            leading=13, spaceAfter=4,
        ),
    }


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _fig_to_image(fig, chart_h_in: float = _CHART_H_IN) -> Image:
    """Render a matplotlib Figure to a reportlab Image flowable."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    img = Image(buf, width=_CONTENT_W, height=chart_h_in * 72)
    img.hAlign = "LEFT"
    return img


def _chart_calls_and_agents(df_erlang: pd.DataFrame) -> Image:
    """Dual-axis chart: calls offered (bar) + Erlang net agents (line)."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax1 = fig.add_subplot(111)
    x = np.arange(len(df_erlang))

    ax1.bar(x, df_erlang["calls_offered"].values,
            color="#AED6F1", label="Calls offered", zorder=2)
    ax1.set_ylabel("Calls offered", color="#5D8FAA", fontsize=8)
    ax1.tick_params(axis="y", labelcolor="#5D8FAA", labelsize=7)
    ax1.tick_params(axis="x", labelsize=7)
    ax1.set_xlabel("Interval", fontsize=8)
    ax1.grid(axis="y", alpha=0.3, zorder=1)

    ax2 = ax1.twinx()
    ax2.plot(x, df_erlang["erlang_required_net_agents"].values,
             color="#1B2A4A", linewidth=1.5, label="Erlang req. agents", zorder=3)
    ax2.set_ylabel("Required agents", color="#1B2A4A", fontsize=8)
    ax2.tick_params(axis="y", labelcolor="#1B2A4A", labelsize=7)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper right", fontsize=7)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_sl_occupancy(
    df_erlang: pd.DataFrame, sl_target: float, occ_cap: float
) -> Image:
    """Line chart: predicted SL% and occupancy% with target/cap reference lines."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax = fig.add_subplot(111)
    x = np.arange(len(df_erlang))

    sl  = df_erlang["erlang_pred_service_level"].values * 100
    occ = df_erlang["erlang_pred_occupancy"].values * 100

    ax.plot(x, sl, color="#2C6FAC", linewidth=1.5, label="Pred. SL %")
    ax.axhline(sl_target * 100, color="#2C6FAC", linestyle="--", linewidth=1,
               alpha=0.6, label=f"SL target ({sl_target*100:.0f}%)")
    ax.plot(x, occ, color="#E67E22", linewidth=1.5, label="Pred. Occupancy %")
    ax.axhline(occ_cap * 100, color="#E67E22", linestyle="--", linewidth=1,
               alpha=0.6, label=f"Occ cap ({occ_cap*100:.0f}%)")

    ax.set_ylim(0, 110)
    ax.set_xlabel("Interval", fontsize=8)
    ax.set_ylabel("%", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_des_daily(des_daily: pd.DataFrame) -> Image:
    """Dual-axis bar+line: DES daily calls handled and avg wait."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax = fig.add_subplot(111)

    if des_daily.empty or "date_local" not in des_daily.columns:
        ax.text(0.5, 0.5, "No DES data available",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        fig.tight_layout()
        return _fig_to_image(fig)

    labels = [str(d) for d in des_daily["date_local"]]
    x = np.arange(len(labels))

    if "sim_calls" in des_daily.columns:
        ax.bar(x, des_daily["sim_calls"].values,
               color="#2C6FAC", label="Calls (DES)")

    if "sim_asa_seconds" in des_daily.columns:
        ax2 = ax.twinx()
        ax2.plot(x, des_daily["sim_asa_seconds"].values,
                 color="#E67E22", linewidth=1.5, label="Avg wait (s)")
        ax2.set_ylabel("Avg wait (s)", color="#E67E22", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="#E67E22", labelsize=7)
        lines1, labels1 = ax.get_legend_handles_labels()
        lines2, labels2 = ax2.get_legend_handles_labels()
        ax.legend(lines1 + lines2, labels1 + labels2,
                  loc="upper right", fontsize=7)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Calls", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_roster_coverage(roster_daily: pd.DataFrame) -> Image:
    """Grouped bar chart: peak requirement vs peak roster per day."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax = fig.add_subplot(111)

    if roster_daily.empty:
        ax.text(0.5, 0.5, "No roster data available",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        fig.tight_layout()
        return _fig_to_image(fig)

    labels = [str(d) for d in roster_daily.get("date_local", roster_daily.index)]
    x = np.arange(len(labels))

    if "peak_requirement" in roster_daily.columns:
        ax.bar(x - 0.2, roster_daily["peak_requirement"].values,
               width=0.4, color="#AED6F1", label="Requirement")
    if "peak_roster" in roster_daily.columns:
        ax.bar(x + 0.2, roster_daily["peak_roster"].values,
               width=0.4, color="#1B2A4A", label="Rostered")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Agents", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_headcount_projection(planning: pd.DataFrame) -> Image:
    """Line chart: projected available FTE vs required FTE over planning horizon."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax = fig.add_subplot(111)

    if planning.empty:
        ax.text(0.5, 0.5, "No workforce planning data",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        fig.tight_layout()
        return _fig_to_image(fig)

    labels = [str(v) for v in planning.get("period_label", planning.index)]
    x = np.arange(len(planning))

    if "available_fte" in planning.columns:
        ax.plot(x, planning["available_fte"].values, color="#2C6FAC",
                linewidth=2, marker="o", markersize=4, label="Available FTE")
    if "required_fte" in planning.columns:
        ax.plot(x, planning["required_fte"].values, color="#E67E22",
                linewidth=2, linestyle="--", label="Required FTE")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("FTE", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_optimal_hires(optimisation: pd.DataFrame) -> Image:
    """Bar chart of optimal hires by month."""
    fig = matplotlib.figure.Figure(figsize=(_CHART_W_IN, _CHART_H_IN))
    ax = fig.add_subplot(111)

    if optimisation.empty or "optimal_hires" not in optimisation.columns:
        ax.text(0.5, 0.5, "No optimisation data",
                ha="center", va="center", transform=ax.transAxes, fontsize=9)
        fig.tight_layout()
        return _fig_to_image(fig)

    labels = [str(v) for v in optimisation.get("period_label", optimisation.index)]
    x = np.arange(len(optimisation))

    ax.bar(x, optimisation["optimal_hires"].values, color="#2C6FAC")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("New hires", fontsize=8)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    return _fig_to_image(fig)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

_BASE_TABLE_STYLE = TableStyle([
    ("BACKGROUND",    (0, 0), (-1, 0),  NAVY),
    ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
    ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0, 0), (-1, 0),  9),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LTBLUE]),
    ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE",      (0, 1), (-1, -1), 8),
    ("GRID",          (0, 0), (-1, -1), 0.4, DGREY),
    ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ("TOPPADDING",    (0, 0), (-1, -1), 4),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
])


def _metrics_table(pairs: list) -> Table:
    """4-column label/value/label/value metrics table.

    ``pairs`` is a list of (label, value) tuples; padded to even length.
    """
    if len(pairs) % 2 != 0:
        pairs = list(pairs) + [("", "")]

    rows = []
    for i in range(0, len(pairs), 2):
        l1, v1 = pairs[i]
        l2, v2 = pairs[i + 1]
        rows.append([l1, str(v1), l2, str(v2)])

    cw = _CONTENT_W / 4
    t = Table(rows, colWidths=[cw, cw, cw, cw])
    t.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (0, -1), NAVY),
        ("BACKGROUND",   (2, 0), (2, -1), NAVY),
        ("TEXTCOLOR",    (0, 0), (0, -1), WHITE),
        ("TEXTCOLOR",    (2, 0), (2, -1), WHITE),
        ("FONTNAME",     (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",     (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME",     (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME",     (3, 0), (3, -1), "Helvetica"),
        ("FONTSIZE",     (0, 0), (-1, -1), 9),
        ("GRID",         (0, 0), (-1, -1), 0.4, DGREY),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [GREY]),
        ("ROWBACKGROUNDS", (3, 0), (3, -1), [GREY]),
    ]))
    return t


def _dataframe_table(df: pd.DataFrame, max_rows: int = 25) -> Table:
    """Convert up to ``max_rows`` rows of a DataFrame to a styled Table."""
    display_df = df.head(max_rows).copy()
    for col in display_df.select_dtypes(include=[float]).columns:
        display_df[col] = display_df[col].apply(
            lambda v: f"{v:.2f}" if pd.notna(v) else ""
        )

    headers = list(display_df.columns)
    rows = [headers] + [[str(c) for c in row] for row in display_df.values.tolist()]

    n_cols = max(len(headers), 1)
    col_w  = _CONTENT_W / n_cols
    t = Table(rows, colWidths=[col_w] * n_cols, repeatRows=1)
    t.setStyle(_BASE_TABLE_STYLE)
    return t


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _cover_page(config: ReportConfig, styles: dict) -> list:
    story = [
        Spacer(1, 55 * mm),
        HRFlowable(width="100%", thickness=3, color=NAVY),
        Spacer(1, 8 * mm),
        Paragraph("Workforce Simulation Report", styles["cover_title"]),
        Paragraph(config.org_name, styles["cover_sub"]),
        Spacer(1, 4 * mm),
        Paragraph(
            f"Report date: {config.report_date.strftime('%d %B %Y')}",
            styles["cover_meta"],
        ),
        Spacer(1, 8 * mm),
        HRFlowable(width="100%", thickness=1, color=BLUE),
        Spacer(1, 10 * mm),
    ]

    sections = []
    if config.include_demand:    sections.append("1. Demand &amp; Erlang C Model")
    if config.include_des:       sections.append("2. DES Simulation Results")
    if config.include_roster:    sections.append("3. Roster &amp; Coverage Gaps")
    if config.include_workforce: sections.append("4. Workforce Planning &amp; Hiring Optimisation")

    for s in sections:
        story.append(Paragraph(s, styles["cover_meta"]))

    story.append(PageBreak())
    return story


def _section_demand(
    df_erlang: pd.DataFrame, cfg_dict: dict, styles: dict
) -> list:
    story = [
        Paragraph("1. Demand &amp; Erlang C Model", styles["section_h1"]),
        HRFlowable(width="100%", thickness=1, color=BLUE),
        Spacer(1, 3 * mm),
    ]

    if not df_erlang.empty:
        sl_target = cfg_dict.get("sl_target", 0.0)
        occ_cap   = cfg_dict.get("occupancy_cap", 0.85)

        total_calls = float(df_erlang["calls_offered"].sum())
        peak_net    = int(df_erlang["erlang_required_net_agents"].max())
        avg_sl      = float(df_erlang["erlang_pred_service_level"].mean()) * 100
        avg_occ     = float(df_erlang["erlang_pred_occupancy"].mean()) * 100
        peak_paid   = (
            int(df_erlang["erlang_required_paid_agents_ceil"].max())
            if "erlang_required_paid_agents_ceil" in df_erlang.columns
            else "—"
        )

        story.append(_metrics_table([
            ("Total calls offered",    f"{total_calls:,.0f}"),
            ("Intervals modelled",     str(len(df_erlang))),
            ("Peak Erlang net agents", str(peak_net)),
            ("Peak Erlang paid agents",str(peak_paid)),
            ("Avg predicted SL",       f"{avg_sl:.1f}%"),
            ("Avg occupancy",          f"{avg_occ:.1f}%"),
            ("SL target",              f"{sl_target*100:.0f}%"),
            ("Occupancy cap",          f"{occ_cap*100:.0f}%"),
        ]))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Call Volume &amp; Agent Requirements", styles["section_h2"]))
        story.append(_chart_calls_and_agents(df_erlang))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Predicted Service Level &amp; Occupancy", styles["section_h2"]))
        story.append(_chart_sl_occupancy(df_erlang, sl_target, occ_cap))
    else:
        story.append(Paragraph("No Erlang data available.", styles["body"]))

    story.append(PageBreak())
    return story


def _section_des(des_daily: pd.DataFrame, styles: dict) -> list:
    story = [
        Paragraph("2. DES Simulation Results", styles["section_h1"]),
        HRFlowable(width="100%", thickness=1, color=BLUE),
        Spacer(1, 3 * mm),
    ]

    if not des_daily.empty:
        pairs = [("Days simulated", str(len(des_daily)))]
        if "sim_calls" in des_daily.columns:
            pairs.append(("Total calls (DES)", f"{des_daily['sim_calls'].sum():,.0f}"))
        if "sim_answered_calls" in des_daily.columns:
            pairs.append(("Calls answered", f"{des_daily['sim_answered_calls'].sum():,.0f}"))
        if "sim_abandoned_calls" in des_daily.columns:
            pairs.append(("Calls abandoned", f"{des_daily['sim_abandoned_calls'].sum():,.0f}"))
        if "sim_asa_seconds" in des_daily.columns:
            pairs.append(("Avg wait time (s)", f"{des_daily['sim_asa_seconds'].mean():.1f}"))
        if "daily_service_level" in des_daily.columns:
            pairs.append(("Avg DES SL", f"{des_daily['daily_service_level'].mean()*100:.1f}%"))
        if "daily_abandon_rate" in des_daily.columns:
            pairs.append(("Avg abandon rate", f"{des_daily['daily_abandon_rate'].mean()*100:.1f}%"))
        if "staff_sim" in des_daily.columns:
            pairs.append(("Peak staff (DES)", str(int(des_daily["staff_sim"].max()))))

        story.append(_metrics_table(pairs))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("DES Daily Call Volume &amp; Avg Wait", styles["section_h2"]))
        story.append(_chart_des_daily(des_daily))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("DES Daily Summary Table", styles["section_h2"]))
        story.append(_dataframe_table(des_daily))
    else:
        story.append(Paragraph(
            "DES simulation has not been run. Navigate to the DES Validation "
            "tab and run the simulation to include results in this report.",
            styles["body"],
        ))

    story.append(PageBreak())
    return story


def _section_roster(roster_daily: pd.DataFrame, styles: dict) -> list:
    story = [
        Paragraph("3. Roster &amp; Coverage Gaps", styles["section_h1"]),
        HRFlowable(width="100%", thickness=1, color=BLUE),
        Spacer(1, 3 * mm),
    ]

    if not roster_daily.empty:
        pairs = [("Days in roster", str(len(roster_daily)))]
        if "total_calls" in roster_daily.columns:
            pairs.append(("Total calls", f"{roster_daily['total_calls'].sum():,.0f}"))
        if "peak_requirement" in roster_daily.columns:
            pairs.append(("Peak requirement (avg)", f"{roster_daily['peak_requirement'].mean():.1f}"))
        if "peak_roster" in roster_daily.columns:
            pairs.append(("Peak roster (avg)", f"{roster_daily['peak_roster'].mean():.1f}"))
        if "coverage_ratio" in roster_daily.columns:
            pairs.append(("Avg coverage ratio", f"{roster_daily['coverage_ratio'].mean():.3f}"))

        story.append(_metrics_table(pairs))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Roster Coverage vs Requirements", styles["section_h2"]))
        story.append(_chart_roster_coverage(roster_daily))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Roster Daily Summary Table", styles["section_h2"]))
        story.append(_dataframe_table(roster_daily))
    else:
        story.append(Paragraph(
            "No roster data available. Generate a roster in the "
            "Roster + Gaps + Optimiser tab.",
            styles["body"],
        ))

    story.append(PageBreak())
    return story


def _section_workforce(
    planning: pd.DataFrame, optimisation: pd.DataFrame, styles: dict
) -> list:
    story = [
        Paragraph("4. Workforce Planning &amp; Hiring Optimisation", styles["section_h1"]),
        HRFlowable(width="100%", thickness=1, color=BLUE),
        Spacer(1, 3 * mm),
    ]

    if not planning.empty:
        pairs = [("Planning periods", str(len(planning)))]
        if "available_fte" in planning.columns:
            pairs.append(("Final available FTE", f"{planning['available_fte'].iloc[-1]:.1f}"))
        if "required_fte" in planning.columns:
            pairs.append(("Final required FTE", f"{planning['required_fte'].iloc[-1]:.1f}"))
        if "new_hires" in planning.columns:
            pairs.append(("Total new hires", f"{planning['new_hires'].sum():.0f}"))
        if "surplus_deficit" in planning.columns:
            final_sd = planning["surplus_deficit"].iloc[-1]
            pairs.append(("Final surplus/deficit", f"{final_sd:+.1f}"))

        story.append(_metrics_table(pairs))
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Headcount Projection", styles["section_h2"]))
        story.append(_chart_headcount_projection(planning))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Workforce Projection Table", styles["section_h2"]))
        story.append(_dataframe_table(planning))
        story.append(Spacer(1, 6 * mm))
    else:
        story.append(Paragraph(
            "No workforce planning data. Run the projection in the "
            "Workforce Planning tab.",
            styles["body"],
        ))
        story.append(Spacer(1, 4 * mm))

    if not optimisation.empty:
        opt_pairs = [("Periods optimised", str(len(optimisation)))]
        if "optimal_hires" in optimisation.columns:
            opt_pairs.append(("Total optimal hires", str(int(optimisation["optimal_hires"].sum()))))
        if "period_total_cost" in optimisation.columns:
            opt_pairs.append(("Total cost", f"${optimisation['period_total_cost'].sum():,.0f}"))

        story.append(Paragraph("Hiring Optimisation", styles["section_h2"]))
        story.append(_metrics_table(opt_pairs))
        story.append(Spacer(1, 4 * mm))
        story.append(_chart_optimal_hires(optimisation))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Optimisation Results Table", styles["section_h2"]))
        story.append(_dataframe_table(optimisation))
    else:
        story.append(Paragraph(
            "No hiring optimisation data. Run the optimiser in the "
            "Hiring Optimisation tab.",
            styles["body"],
        ))

    return story


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_report(config: ReportConfig, data: dict) -> bytes:
    """Build a PDF report and return the raw bytes.

    Parameters
    ----------
    config : ReportConfig
        Cover page settings and section toggles.
    data : dict
        Data sources consumed by each section:

        - ``"df_erlang"``    : pd.DataFrame — output of ``solve_staffing_erlang()``
        - ``"des_daily"``    : pd.DataFrame — ``st.session_state["des_daily_summary"]``
        - ``"roster_daily"`` : pd.DataFrame — ``st.session_state["roster_daily_summary"]``
        - ``"planning"``     : pd.DataFrame — ``st.session_state["planning_projection"]``
        - ``"optimisation"`` : pd.DataFrame — ``st.session_state["optimisation_result"]``
        - ``"sl_target"``    : float
        - ``"occupancy_cap"``: float

    Returns
    -------
    bytes
        Raw PDF bytes, suitable for ``st.download_button(data=...)``.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title="Workforce Simulation Report",
        author=config.org_name,
    )

    styles = _make_styles()
    story  = []

    # Cover page
    story.extend(_cover_page(config, styles))

    cfg_dict = {
        "sl_target":    data.get("sl_target",    0.0),
        "occupancy_cap":data.get("occupancy_cap",0.85),
    }

    df_erlang    = data.get("df_erlang",    pd.DataFrame())
    des_daily    = data.get("des_daily",    pd.DataFrame())
    roster_daily = data.get("roster_daily", pd.DataFrame())
    planning     = data.get("planning",     pd.DataFrame())
    optimisation = data.get("optimisation", pd.DataFrame())

    if config.include_demand:
        story.extend(_section_demand(df_erlang, cfg_dict, styles))
    if config.include_des:
        story.extend(_section_des(des_daily, styles))
    if config.include_roster:
        story.extend(_section_roster(roster_daily, styles))
    if config.include_workforce:
        story.extend(_section_workforce(planning, optimisation, styles))

    doc.build(story)
    buf.seek(0)
    return buf.read()
