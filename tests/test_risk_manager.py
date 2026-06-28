"""
Tests for the Risk Manager — this is the safety-critical agent, so it
gets the most thorough test coverage. Run: python -m pytest tests/ -v

All non-time-focused tests pin `override_time=SAFE_TIME` (mid-morning,
well clear of both the market-open and square-off gates). Without this,
test outcomes would silently depend on what wall-clock time pytest
happens to run at — a test suite that only fails between 2:45pm and
9:15am IST is worse than no test suite, since CI run time is invisible
in the failure message.
"""
import sys
from datetime import time as dt_time

sys.path.insert(0, ".")

from agents.risk_manager import RiskManagerAgent
from core.models import Bias, Verdict

SAFE_TIME = dt_time(11, 0)  # 11:00 AM IST — clear of both gates


def test_buy_with_good_rr_approved():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=104.0,  # risk=2, reward=4 -> RR=2.0
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.APPROVED
    assert result.risk_reward_ratio == 2.0


def test_buy_with_bad_rr_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=101.0,  # risk=2, reward=1 -> RR=0.5
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("Risk:Reward" in r for r in result.reasons)


def test_short_with_good_rr_approved():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.SHORT, entry_price=100.0, stop_loss=102.0,
        target_price=96.0,  # risk=2, reward=4 -> RR=2.0
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.APPROVED
    assert result.risk_reward_ratio == 2.0


def test_entry_too_close_to_circuit_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=119.5, stop_loss=117.0,
        target_price=124.0,
        lower_circuit=80.0, upper_circuit=120.0,  # entry is 0.4% from upper circuit
        override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("circuit limit" in r for r in result.reasons)


def test_target_beyond_circuit_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=121.0,  # target is past the upper circuit of 120
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("circuit limit" in r for r in result.reasons)


def test_invalid_stop_loss_blocked():
    rm = RiskManagerAgent()
    # For a BUY, stop loss above entry is invalid (risk <= 0)
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=101.0,
        target_price=105.0,
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("Invalid stop loss" in r for r in result.reasons)


def test_neutral_bias_always_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.NEUTRAL, entry_price=100.0, stop_loss=98.0,
        target_price=104.0,
        lower_circuit=80.0, upper_circuit=120.0, override_time=SAFE_TIME,
    )
    assert result.verdict == Verdict.BLOCKED


# ---- Time-of-day gate tests --------------------------------------------
# A trade that would otherwise be perfectly approvable (good R:R, safe
# distance from circuit) must still get blocked purely on clock time.

GOOD_TRADE = dict(
    symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
    target_price=104.0, lower_circuit=80.0, upper_circuit=120.0,
)


def test_blocked_after_square_off_cutoff():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(14, 45))  # exactly at cutoff
    assert result.verdict == Verdict.BLOCKED
    assert any("cutoff" in r for r in result.reasons)


def test_blocked_well_after_square_off_cutoff():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(15, 10))  # 3:10pm, near RMS square-off
    assert result.verdict == Verdict.BLOCKED
    assert any("cutoff" in r for r in result.reasons)


def test_blocked_before_market_open():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(8, 30))
    assert result.verdict == Verdict.BLOCKED
    assert any("outside" in r and "market hours" in r for r in result.reasons)


def test_blocked_after_market_close():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(16, 0))
    assert result.verdict == Verdict.BLOCKED
    assert any("outside" in r and "market hours" in r for r in result.reasons)


def test_approved_just_before_cutoff():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(14, 44))  # 1 minute before cutoff
    assert result.verdict == Verdict.APPROVED


def test_approved_at_market_open():
    rm = RiskManagerAgent()
    result = rm.assess(**GOOD_TRADE, override_time=dt_time(9, 15))
    assert result.verdict == Verdict.APPROVED


def test_time_gate_runs_before_other_checks():
    """
    Even a trade with a BAD risk:reward should report the time-gate
    reason, not the R:R reason, when both would fail — the time gate
    is checked first and short-circuits everything else, since there's
    no point computing R:R for a trade that can't be placed at all.
    """
    rm = RiskManagerAgent()
    bad_rr_trade = dict(GOOD_TRADE)
    bad_rr_trade["target_price"] = 100.5  # terrible R:R
    result = rm.assess(**bad_rr_trade, override_time=dt_time(15, 0))
    assert result.verdict == Verdict.BLOCKED
    assert any("cutoff" in r for r in result.reasons)
    assert result.risk_reward_ratio is None  # never computed, time gate short-circuited first


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
