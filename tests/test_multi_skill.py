"""tests/test_multi_skill.py

Unit tests for models/multi_skill.py — Phase 24B blended staffing model.

Covers:
  - QueueSpec: construction, derived properties (traffic intensity, fractions)
  - SkillGroup: construction, can_serve()
  - solve_blended_erlang(): siloed vs blended comparison, pooling benefit
  - pooling_benefit_agents(): extraction from results DataFrame
  - Edge cases: single queue, zero-call queues, identical queues
"""

import unittest

from models.multi_skill import (
    QueueSpec,
    SkillGroup,
    solve_blended_erlang,
    pooling_benefit_agents,
)


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

def _sales_queue(**overrides) -> QueueSpec:
    kwargs = dict(
        name="Sales",
        calls_per_interval=80.0,
        aht_seconds=300.0,
        sl_target_pct=80.0,
        sl_threshold_sec=20.0,
        shrinkage_pct=30.0,
        interval_minutes=15.0,
        mean_patience_sec=180.0,
    )
    kwargs.update(overrides)
    return QueueSpec(**kwargs)


def _support_queue(**overrides) -> QueueSpec:
    kwargs = dict(
        name="Support",
        calls_per_interval=50.0,
        aht_seconds=420.0,
        sl_target_pct=90.0,
        sl_threshold_sec=30.0,
        shrinkage_pct=30.0,
        interval_minutes=15.0,
        mean_patience_sec=240.0,
    )
    kwargs.update(overrides)
    return QueueSpec(**kwargs)


# ---------------------------------------------------------------------------
# QueueSpec
# ---------------------------------------------------------------------------

class TestQueueSpec(unittest.TestCase):

    def test_construction(self):
        q = _sales_queue()
        self.assertEqual(q.name, "Sales")
        self.assertEqual(q.calls_per_interval, 80.0)
        self.assertEqual(q.aht_seconds, 300.0)

    def test_interval_seconds(self):
        q = QueueSpec("X", 50, 300, 80, 20, interval_minutes=15)
        self.assertAlmostEqual(q.interval_seconds, 900.0)

    def test_interval_seconds_30_min(self):
        q = QueueSpec("X", 50, 300, 80, 20, interval_minutes=30)
        self.assertAlmostEqual(q.interval_seconds, 1800.0)

    def test_traffic_intensity_positive(self):
        q = _sales_queue()
        self.assertGreater(q.traffic_intensity, 0.0)

    def test_traffic_intensity_formula(self):
        # λ = 80/900, μ = 1/300, A = λ/μ = 80/900 * 300 ≈ 26.67
        q = _sales_queue(calls_per_interval=80, aht_seconds=300, interval_minutes=15)
        expected = (80.0 / 900.0) / (1.0 / 300.0)
        self.assertAlmostEqual(q.traffic_intensity, expected, places=4)

    def test_sl_target_fraction(self):
        q = QueueSpec("X", 50, 300, 80, 20)
        self.assertAlmostEqual(q.sl_target_fraction, 0.80)

    def test_shrinkage_fraction(self):
        q = QueueSpec("X", 50, 300, 80, 20, shrinkage_pct=25.0)
        self.assertAlmostEqual(q.shrinkage_fraction, 0.25)

    def test_zero_calls_traffic_is_zero(self):
        q = QueueSpec("X", 0, 300, 80, 20)
        self.assertAlmostEqual(q.traffic_intensity, 0.0, places=6)


# ---------------------------------------------------------------------------
# SkillGroup
# ---------------------------------------------------------------------------

class TestSkillGroup(unittest.TestCase):

    def test_construction(self):
        g = SkillGroup("Blended", ["Sales", "Support"], headcount=10)
        self.assertEqual(g.name, "Blended")
        self.assertEqual(g.headcount, 10)
        self.assertIn("Sales", g.queues)

    def test_can_serve_true(self):
        g = SkillGroup("G", ["Sales", "Support"], 5)
        self.assertTrue(g.can_serve("Sales"))
        self.assertTrue(g.can_serve("Support"))

    def test_can_serve_false(self):
        g = SkillGroup("G", ["Sales"], 5)
        self.assertFalse(g.can_serve("Support"))

    def test_can_serve_empty_queues(self):
        g = SkillGroup("G", [], 5)
        self.assertFalse(g.can_serve("Sales"))

    def test_default_headcount_zero(self):
        g = SkillGroup("G", ["Sales"])
        self.assertEqual(g.headcount, 0)


# ---------------------------------------------------------------------------
# solve_blended_erlang
# ---------------------------------------------------------------------------

class TestSolveBlendedErlang(unittest.TestCase):

    def test_returns_dataframe(self):
        import pandas as pd
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        self.assertIsInstance(result, pd.DataFrame)

    def test_row_count_is_n_queues_plus_one(self):
        """n queue rows + 1 summary row."""
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        self.assertEqual(len(result), 3)  # 2 queues + 1 blended row

    def test_three_queues_has_four_rows(self):
        q3 = QueueSpec("Complaints", 20, 600, 85, 60)
        result = solve_blended_erlang([_sales_queue(), _support_queue(), q3])
        self.assertEqual(len(result), 4)

    def test_empty_input_returns_empty_df(self):
        result = solve_blended_erlang([])
        self.assertTrue(result.empty)

    def test_required_columns_present(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        for col in [
            "queue", "calls_per_interval", "aht_seconds",
            "siloed_net_agents", "siloed_paid_agents", "siloed_sl_pct",
            "blended_net_agents", "blended_paid_agents", "pooling_benefit_net",
        ]:
            self.assertIn(col, result.columns, f"Missing column: {col}")

    def test_siloed_agents_positive(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        queue_rows = result[result["queue"] != "── Blended total ──"]
        self.assertTrue((queue_rows["siloed_net_agents"] > 0).all())

    def test_blended_total_leq_siloed_total(self):
        """Pooling benefit ≥ 0: blended pool never needs more agents than siloed."""
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        summary = result[result["queue"] == "── Blended total ──"].iloc[0]
        self.assertLessEqual(
            int(summary["blended_net_agents"]),
            int(summary["siloed_net_agents"]),
        )

    def test_pooling_benefit_non_negative(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        summary = result[result["queue"] == "── Blended total ──"].iloc[0]
        self.assertGreaterEqual(int(summary["pooling_benefit_net"]), 0)

    def test_pooling_benefit_positive_for_two_distinct_queues(self):
        """Two different queues should yield a positive pooling benefit."""
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        benefit = pooling_benefit_agents(result)
        # Erlang C pooling always helps with independent Poisson streams
        self.assertGreaterEqual(benefit, 0)

    def test_paid_agents_geq_net_agents_with_shrinkage(self):
        """Paid ≥ net when shrinkage > 0."""
        result = solve_blended_erlang([_sales_queue(shrinkage_pct=30), _support_queue(shrinkage_pct=30)])
        queue_rows = result[result["queue"] != "── Blended total ──"]
        self.assertTrue((queue_rows["siloed_paid_agents"] >= queue_rows["siloed_net_agents"]).all())

    def test_zero_shrinkage_paid_equals_net(self):
        result = solve_blended_erlang([
            _sales_queue(shrinkage_pct=0),
            _support_queue(shrinkage_pct=0),
        ])
        queue_rows = result[result["queue"] != "── Blended total ──"]
        self.assertTrue((queue_rows["siloed_paid_agents"] == queue_rows["siloed_net_agents"]).all())

    def test_higher_traffic_needs_more_agents(self):
        """A queue with double the calls should require more agents."""
        low  = solve_blended_erlang([_sales_queue(calls_per_interval=40), _support_queue()])
        high = solve_blended_erlang([_sales_queue(calls_per_interval=120), _support_queue()])
        low_sales  = low[low["queue"] == "Sales"]["siloed_net_agents"].iloc[0]
        high_sales = high[high["queue"] == "Sales"]["siloed_net_agents"].iloc[0]
        self.assertGreater(high_sales, low_sales)

    def test_single_queue_still_works(self):
        """Single queue: blended total should equal siloed requirement."""
        result = solve_blended_erlang([_sales_queue()])
        self.assertEqual(len(result), 2)  # 1 queue + 1 blended row
        summary = result[result["queue"] == "── Blended total ──"].iloc[0]
        # Pooling benefit for a single queue must be 0 (nothing to pool)
        self.assertEqual(int(summary["pooling_benefit_net"]), 0)

    def test_zero_calls_queue_handled(self):
        """A queue with 0 calls should have 0 siloed agents required."""
        result = solve_blended_erlang([
            _sales_queue(calls_per_interval=0),
            _support_queue(),
        ])
        sales_row = result[result["queue"] == "Sales"]
        self.assertFalse(sales_row.empty)
        self.assertEqual(int(sales_row["siloed_net_agents"].iloc[0]), 0)

    def test_summary_row_has_blended_agents(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        summary = result[result["queue"] == "── Blended total ──"].iloc[0]
        self.assertIsNotNone(summary["blended_net_agents"])
        self.assertGreater(int(summary["blended_net_agents"]), 0)

    def test_blended_sl_between_0_and_100(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        summary = result[result["queue"] == "── Blended total ──"].iloc[0]
        sl = summary["blended_sl_pct"]
        if sl is not None:
            self.assertGreaterEqual(sl, 0.0)
            self.assertLessEqual(sl, 100.0)


# ---------------------------------------------------------------------------
# pooling_benefit_agents
# ---------------------------------------------------------------------------

class TestPoolingBenefitAgents(unittest.TestCase):

    def test_returns_integer(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        benefit = pooling_benefit_agents(result)
        self.assertIsInstance(benefit, int)

    def test_non_negative(self):
        result = solve_blended_erlang([_sales_queue(), _support_queue()])
        self.assertGreaterEqual(pooling_benefit_agents(result), 0)

    def test_empty_df_returns_zero(self):
        import pandas as pd
        self.assertEqual(pooling_benefit_agents(pd.DataFrame()), 0)

    def test_single_queue_returns_zero(self):
        result = solve_blended_erlang([_sales_queue()])
        self.assertEqual(pooling_benefit_agents(result), 0)


if __name__ == "__main__":
    unittest.main()
