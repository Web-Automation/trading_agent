"""
Executive Trader Agent.
Deterministic consolidation + price math. This is the "Step 3: Precise
Pricing Strategy" from the spec. It does NOT call an LLM — entry/SL/target
are computed from market structure (pivots, swing points, ATR), and the
final go/no-go still passes through the Risk Manager before becoming a
TradeSignal.
"""
from __future__ import annotations
from datetime import datetime

from core.models import (
    Bias,
    LiquidityCheck,
    TechnicalReading,
    TapeReading,
    SentimentReading,
    RiskAssessment,
    TradeSignal,
    Verdict,
)
from agents.risk_manager import RiskManagerAgent


class ExecutiveTraderAgent:
    ATR_STOP_MULTIPLE = 1.0  # spec: SL = 1x ATR, or swing structure, whichever is tighter
    SENTIMENT_VETO_THRESHOLD = -0.6  # strongly negative news can override a technical BUY

    def __init__(self, risk_manager: RiskManagerAgent | None = None):
        self.risk_manager = risk_manager or RiskManagerAgent()

    def _compute_buy_levels(self, tech: TechnicalReading, intraday_atr: float) -> tuple[float, float, float]:
        """
        Buy entry: near a support bounce or VWAP pullback (spec).
        We use the higher of (VWAP, swing_low) as the support reference,
        entry = small buffer above that level, SL = tighter of (1x ATR, below swing low).
        """
        support_ref = max(tech.vwap, tech.swing_low)
        entry = round(support_ref * 1.001, 2)  # tiny buffer above support to confirm the bounce
        atr_stop = entry - (intraday_atr * self.ATR_STOP_MULTIPLE)
        structure_stop = tech.swing_low * 0.999
        stop_loss = round(max(atr_stop, structure_stop), 2)  # the tighter (higher) of the two stops
        target = round(entry + 2 * (entry - stop_loss), 2)   # baseline 1:2, refined by pivot R1 below
        if tech.pivot_r1 > entry:
            target = round(max(target, tech.pivot_r1), 2)
        return entry, stop_loss, target

    def _compute_short_levels(self, tech: TechnicalReading, intraday_atr: float) -> tuple[float, float, float]:
        """
        Short entry: near a resistance rejection or a break below the opening range (spec).
        """
        resistance_ref = min(tech.vwap, tech.swing_high)
        entry = round(resistance_ref * 0.999, 2)
        atr_stop = entry + (intraday_atr * self.ATR_STOP_MULTIPLE)
        structure_stop = tech.swing_high * 1.001
        stop_loss = round(min(atr_stop, structure_stop), 2)  # the tighter (lower) of the two stops
        target = round(entry - 2 * (stop_loss - entry), 2)
        if tech.pivot_s1 < entry:
            target = round(min(target, tech.pivot_s1), 2)
        return entry, stop_loss, target

    def decide(
        self,
        symbol: str,
        liquidity: LiquidityCheck,
        tech: TechnicalReading,
        tape: TapeReading,
        sentiment: SentimentReading,
        intraday_atr: float,
        lower_circuit: float,
        upper_circuit: float,
        override_time=None,  # dt_time, for tests/demos to simulate a specific clock time
    ) -> TradeSignal:
        rationale: list[str] = []
        blocking: list[str] = []

        # Step 1: liquidity gate — this stops everything downstream if failed
        if not liquidity.viable:
            return TradeSignal(
                symbol=symbol,
                timestamp=datetime.now(),
                verdict=Verdict.NOT_VIABLE,
                bias=Bias.NEUTRAL,
                entry_price=None,
                stop_loss=None,
                target_price=None,
                risk_reward_ratio=None,
                confidence=0.0,
                rationale=[],
                blocking_reasons=liquidity.rejection_reasons,
            )

        bias = tech.bias
        rationale.append(
            f"Technical bias: {bias.value} (strength {tech.bias_strength:.0%}, HTF trend {tech.htf_trend})"
        )

        # Tape confirmation nudges confidence but never flips bias on its own
        tape_agrees = (
            (bias == Bias.BUY and tape.bid_ask_imbalance > 0)
            or (bias == Bias.SHORT and tape.bid_ask_imbalance < 0)
        )
        if tape_agrees:
            rationale.append(f"Tape confirms: bid/ask imbalance {tape.bid_ask_imbalance:+.0%}")
        else:
            rationale.append(
                f"Tape does not clearly confirm bias (imbalance {tape.bid_ask_imbalance:+.0%}) — reduces confidence"
            )

        # Sentiment can veto a BUY or reinforce a SHORT, and vice versa, but only at high confidence
        sentiment_conflict = False
        if sentiment.confidence >= 0.3:
            if bias == Bias.BUY and sentiment.score <= self.SENTIMENT_VETO_THRESHOLD:
                sentiment_conflict = True
                blocking.append(
                    f"Strongly negative sentiment ({sentiment.score:.2f}, {sentiment.summary}) "
                    "conflicts with technical BUY bias"
                )
            elif bias == Bias.SHORT and sentiment.score >= -self.SENTIMENT_VETO_THRESHOLD:
                sentiment_conflict = True
                blocking.append(
                    f"Strongly positive sentiment ({sentiment.score:.2f}, {sentiment.summary}) "
                    "conflicts with technical SHORT bias"
                )
            else:
                rationale.append(f"Sentiment: {sentiment.score:+.2f} ({sentiment.summary})")

        if bias == Bias.NEUTRAL:
            blocking.append("No clean directional bias from VWAP/EMA/HTF alignment")

        if blocking:
            return TradeSignal(
                symbol=symbol, timestamp=datetime.now(), verdict=Verdict.BLOCKED, bias=bias,
                entry_price=None, stop_loss=None, target_price=None, risk_reward_ratio=None,
                confidence=0.0, rationale=rationale, blocking_reasons=blocking,
            )

        # Step 3: price levels
        if bias == Bias.BUY:
            entry, stop_loss, target = self._compute_buy_levels(tech, intraday_atr)
        else:
            entry, stop_loss, target = self._compute_short_levels(tech, intraday_atr)

        # Final gate: Risk Manager has veto power, runs last
        risk: RiskAssessment = self.risk_manager.assess(
            symbol=symbol, bias=bias, entry_price=entry, stop_loss=stop_loss,
            target_price=target, lower_circuit=lower_circuit, upper_circuit=upper_circuit,
            override_time=override_time,
        )

        if risk.verdict == Verdict.BLOCKED:
            return TradeSignal(
                symbol=symbol, timestamp=datetime.now(), verdict=Verdict.BLOCKED, bias=bias,
                entry_price=entry, stop_loss=stop_loss, target_price=target,
                risk_reward_ratio=risk.risk_reward_ratio, confidence=0.0,
                rationale=rationale, blocking_reasons=risk.reasons,
            )

        confidence = tech.bias_strength
        if tape_agrees:
            confidence = min(1.0, confidence + 0.15)
        if sentiment.confidence >= 0.3 and not sentiment_conflict:
            confidence = min(1.0, confidence + 0.1 * sentiment.confidence)

        return TradeSignal(
            symbol=symbol,
            timestamp=datetime.now(),
            verdict=Verdict.APPROVED,
            bias=bias,
            entry_price=entry,
            stop_loss=stop_loss,
            target_price=target,
            risk_reward_ratio=risk.risk_reward_ratio,
            confidence=round(confidence, 2),
            rationale=rationale,
            blocking_reasons=[],
        )
