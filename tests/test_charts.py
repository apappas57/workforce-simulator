"""tests/test_charts.py

Unit tests for ui/charts.py — Phase 21 chart utilities module.

These are pure-function tests that require plotly but no Streamlit runtime.

Covers:
  - PALETTE: 8 hex entries, semantic colour constants
  - apply_dark_theme(): transparent backgrounds, axis grid, height, legend flag
  - add_operating_hours_vrect(): band count for all edge cases
  - px_line / px_bar / px_area: return Figure with dark theme applied
"""

import unittest

import pandas as pd

try:
    import plotly.graph_objects as go
    _PLOTLY_AVAILABLE = True
except ImportError:
    _PLOTLY_AVAILABLE = False

# ui.charts imports plotly at module level — guard so the test file can at
# least be collected (and skipped gracefully) when plotly is absent.
try:
    from ui.charts import (
        PALETTE,
        C_REQUIREMENT,
        C_ROSTER,
        C_SIMULATION,
        C_FORECAST,
        C_COST,
        apply_dark_theme,
        add_operating_hours_vrect,
        px_line,
        px_bar,
        px_area,
    )
    _CHARTS_IMPORTABLE = True
except ImportError:
    _CHARTS_IMPORTABLE = False
    # Provide stubs so the class bodies can be parsed without error.
    PALETTE = []
    C_REQUIREMENT = C_ROSTER = C_SIMULATION = C_FORECAST = C_COST = "#000000"

    def apply_dark_theme(fig, **kw):  # pragma: no cover
        return fig

    def add_operating_hours_vrect(fig, *a, **kw):  # pragma: no cover
        return fig

    def px_line(df, **kw):  # pragma: no cover
        return None

    def px_bar(df, **kw):  # pragma: no cover
        return None

    def px_area(df, **kw):  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Palette and colour constants
# ---------------------------------------------------------------------------

@unittest.skipUnless(_CHARTS_IMPORTABLE, "ui.charts not importable (plotly missing)")
class TestPalette(unittest.TestCase):

    def test_palette_has_exactly_eight_entries(self):
        self.assertEqual(len(PALETTE), 8)

    def test_all_palette_entries_are_hex(self):
        for colour in PALETTE:
            self.assertTrue(
                colour.startswith("#") and len(colour) in (4, 7),
                f"Not a valid hex colour: {colour}",
            )

    def test_semantic_constants_are_hex(self):
        for name, val in [
            ("C_REQUIREMENT", C_REQUIREMENT),
            ("C_ROSTER",      C_ROSTER),
            ("C_SIMULATION",  C_SIMULATION),
            ("C_FORECAST",    C_FORECAST),
            ("C_COST",        C_COST),
        ]:
            self.assertTrue(
                val.startswith("#"),
                f"{name}={val!r} is not a hex colour",
            )

    def test_semantic_constants_are_in_palette_or_valid_hex(self):
        """Each semantic constant must be a 7-character hex colour."""
        for val in [C_REQUIREMENT, C_ROSTER, C_SIMULATION, C_FORECAST, C_COST]:
            self.assertEqual(len(val), 7, f"{val!r} is not a 6-digit hex colour")


# ---------------------------------------------------------------------------
# apply_dark_theme
# ---------------------------------------------------------------------------

@unittest.skipUnless(_PLOTLY_AVAILABLE and _CHARTS_IMPORTABLE, "plotly not installed")
class TestApplyDarkTheme(unittest.TestCase):

    def _fig(self):
        return go.Figure()

    def test_returns_figure_instance(self):
        result = apply_dark_theme(self._fig())
        self.assertIsInstance(result, go.Figure)

    def test_returns_same_figure_object(self):
        """Modifies in-place and returns the same reference."""
        fig = self._fig()
        result = apply_dark_theme(fig)
        self.assertIs(result, fig)

    def test_paper_bgcolor_is_transparent(self):
        fig = apply_dark_theme(self._fig())
        self.assertEqual(fig.layout.paper_bgcolor, "rgba(0,0,0,0)")

    def test_plot_bgcolor_is_transparent(self):
        fig = apply_dark_theme(self._fig())
        self.assertEqual(fig.layout.plot_bgcolor, "rgba(0,0,0,0)")

    def test_height_applied_when_provided(self):
        fig = apply_dark_theme(self._fig(), height=400)
        self.assertEqual(fig.layout.height, 400)

    def test_no_height_set_when_omitted(self):
        fig = apply_dark_theme(self._fig())
        # height should not be set to a specific integer value
        self.assertIsNone(fig.layout.height)

    def test_legend_hidden_when_false(self):
        fig = apply_dark_theme(self._fig(), legend=False)
        self.assertFalse(fig.layout.showlegend)

    def test_legend_shown_by_default(self):
        fig = apply_dark_theme(self._fig())
        self.assertTrue(fig.layout.showlegend)

    def test_works_on_figure_with_traces(self):
        fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[4, 5, 6])])
        result = apply_dark_theme(fig)
        self.assertIsInstance(result, go.Figure)
        self.assertEqual(len(result.data), 1)


# ---------------------------------------------------------------------------
# add_operating_hours_vrect
# ---------------------------------------------------------------------------

@unittest.skipUnless(_PLOTLY_AVAILABLE and _CHARTS_IMPORTABLE, "plotly not installed")
class TestAddOperatingHoursVrect(unittest.TestCase):

    def _fig(self):
        return go.Figure()

    def test_no_bands_when_close_equals_open(self):
        fig = add_operating_hours_vrect(self._fig(), 32, 32, 96)
        self.assertEqual(len(fig.layout.shapes), 0)

    def test_no_bands_when_close_less_than_open(self):
        fig = add_operating_hours_vrect(self._fig(), 48, 32, 96)
        self.assertEqual(len(fig.layout.shapes), 0)

    def test_two_bands_for_mid_day_window(self):
        """08:00–18:00 on a 96-interval day → pre-open + post-close band."""
        fig = add_operating_hours_vrect(self._fig(), 32, 72, 96)
        self.assertEqual(len(fig.layout.shapes), 2)

    def test_one_band_when_open_from_midnight(self):
        """Open=0 → no pre-open band, only post-close band."""
        fig = add_operating_hours_vrect(self._fig(), 0, 72, 96)
        self.assertEqual(len(fig.layout.shapes), 1)

    def test_one_band_when_close_at_end_of_day(self):
        """Close=total_intervals → no post-close band, only pre-open band."""
        fig = add_operating_hours_vrect(self._fig(), 32, 96, 96)
        self.assertEqual(len(fig.layout.shapes), 1)

    def test_no_bands_for_full_day_window(self):
        """Open=0, close=total → active all day, no bands needed."""
        fig = add_operating_hours_vrect(self._fig(), 0, 96, 96)
        self.assertEqual(len(fig.layout.shapes), 0)

    def test_returns_same_figure_object(self):
        fig = self._fig()
        result = add_operating_hours_vrect(fig, 32, 72, 96)
        self.assertIs(result, fig)


# ---------------------------------------------------------------------------
# px wrappers
# ---------------------------------------------------------------------------

@unittest.skipUnless(_PLOTLY_AVAILABLE and _CHARTS_IMPORTABLE, "plotly not installed")
class TestPxWrappers(unittest.TestCase):

    def _df(self):
        return pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})

    def test_px_line_returns_figure(self):
        self.assertIsInstance(px_line(self._df(), x="x", y="y"), go.Figure)

    def test_px_bar_returns_figure(self):
        self.assertIsInstance(px_bar(self._df(), x="x", y="y"), go.Figure)

    def test_px_area_returns_figure(self):
        self.assertIsInstance(px_area(self._df(), x="x", y="y"), go.Figure)

    def test_px_line_has_dark_theme(self):
        fig = px_line(self._df(), x="x", y="y")
        self.assertEqual(fig.layout.paper_bgcolor, "rgba(0,0,0,0)")

    def test_px_bar_has_dark_theme(self):
        fig = px_bar(self._df(), x="x", y="y")
        self.assertEqual(fig.layout.paper_bgcolor, "rgba(0,0,0,0)")

    def test_px_area_has_dark_theme(self):
        fig = px_area(self._df(), x="x", y="y")
        self.assertEqual(fig.layout.paper_bgcolor, "rgba(0,0,0,0)")


if __name__ == "__main__":
    unittest.main()
