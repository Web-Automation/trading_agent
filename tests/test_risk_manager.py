"""
Tests for the Risk Manager — this is the safety-critical agent, so it
gets the most thorough test coverage. Run: python -m pytest tests/ -v
"""
import sys
sys.path.insert(0, ".")

from agents.risk_manager import RiskManagerAgent
from core.models import Bias, Verdict


def test_buy_with_good_rr_approved():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=104.0,  # risk=2, reward=4 -> RR=2.0
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.APPROVED
    assert result.risk_reward_ratio == 2.0


def test_buy_with_bad_rr_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=101.0,  # risk=2, reward=1 -> RR=0.5
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("Risk:Reward" in r for r in result.reasons)


def test_short_with_good_rr_approved():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.SHORT, entry_price=100.0, stop_loss=102.0,
        target_price=96.0,  # risk=2, reward=4 -> RR=2.0
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.APPROVED
    assert result.risk_reward_ratio == 2.0


def test_entry_too_close_to_circuit_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=119.5, stop_loss=117.0,
        target_price=124.0,
        lower_circuit=80.0, upper_circuit=120.0,  # entry is 0.4% from upper circuit
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("circuit limit" in r for r in result.reasons)


def test_target_beyond_circuit_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=98.0,
        target_price=121.0,  # target is past the upper circuit of 120
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("circuit limit" in r for r in result.reasons)


def test_invalid_stop_loss_blocked():
    rm = RiskManagerAgent()
    # For a BUY, stop loss above entry is invalid (risk <= 0)
    result = rm.assess(
        symbol="TEST", bias=Bias.BUY, entry_price=100.0, stop_loss=101.0,
        target_price=105.0,
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.BLOCKED
    assert any("Invalid stop loss" in r for r in result.reasons)


def test_neutral_bias_always_blocked():
    rm = RiskManagerAgent()
    result = rm.assess(
        symbol="TEST", bias=Bias.NEUTRAL, entry_price=100.0, stop_loss=98.0,
        target_price=104.0,
        lower_circuit=80.0, upper_circuit=120.0,
    )
    assert result.verdict == Verdict.BLOCKED


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
