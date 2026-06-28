"""
Tests for technical_analysis.py — focused on the htf_trend lookback fix.
The bug: the original code compared the current hourly EMA to the EMA
5 bars back, which on a ~6.25hr NSE session mostly measures "since the
open" rather than a responsive intraday slope. Fixed to a 3-bar lookback.
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from agents.technical_analysis import TechnicalAnalysisAgent


def _make_hourly_df(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2026-06-01 09:15", periods=n, freq="60min")
    closes = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes * 1.001,
            "low": closes * 0.999,
            "close": closes,
            "volume": np.full(n, 100_000),
        },
        index=idx,
    )


def test_lookback_is_3_bars_not_5():
    agent = TechnicalAnalysisAgent()
    assert agent.HTF_SLOPE_LOOKBACK == 3


def test_recent_reversal_detected_within_3_bars():
    """
    Build a series that trends up for a long stretch, then reverses
    sharply in just the last few bars. A 3-bar lookback should be able
    to register the reversal; a 5-bar lookback (the old bug) would still
    be comparing against the tail of the uptrend and could mask it.
    """
    agent = TechnicalAnalysisAgent()
    uptrend = [100 + i * 0.5 for i in range(25)]       # steady climb to 112
    sharp_drop = [112 - i * 1.5 for i in range(1, 4)]   # drops hard for 3 bars
    closes = uptrend + sharp_drop
    df = _make_hourly_df(closes)

    trend = agent.htf_trend(df)
    # With a tight 3-bar lookback the recent sharp drop should be
    # reflected — at minimum it should not report a confident UP trend
    # while price is actively reversing.
    assert trend in ("DOWN", "SIDEWAYS")


def test_insufficient_data_returns_sideways():
    agent = TechnicalAnalysisAgent()
    df = _make_hourly_df([100 + i for i in range(10)])  # fewer than 21 bars
    assert agent.htf_trend(df) == "SIDEWAYS"


def test_steady_uptrend_returns_up():
    agent = TechnicalAnalysisAgent()
    closes = [100 + i * 0.8 for i in range(30)]  # consistent climb, no reversal
    df = _make_hourly_df(closes)
    assert agent.htf_trend(df) == "UP"


def test_steady_downtrend_returns_down():
    agent = TechnicalAnalysisAgent()
    closes = [130 - i * 0.8 for i in range(30)]  # consistent decline, no reversal
    df = _make_hourly_df(closes)
    assert agent.htf_trend(df) == "DOWN"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
