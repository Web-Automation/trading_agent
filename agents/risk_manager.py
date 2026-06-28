"""
Risk Manager Agent — the gatekeeper.
This agent has VETO power and runs LAST, after a price plan exists.
No LLM, no fuzziness: hard numeric thresholds only. If a trade fails
here, it is BLOCKED, full stop, regardless of how confident upstream
agents were.
"""
from __future__ import annotations
from datetime import datetime, time as dt_time

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    IST = None  # falls back to naive local time if zoneinfo unavailable (Python <3.9)

from core.models import RiskAssessment, Verdict, Bias


class RiskManagerAgent:
    MIN_RISK_REWARD = 2.0              # spec requirement: must be >= 1:2
    MIN_DISTANCE_TO_CIRCUIT_PCT = 1.0  # don't let entry sit right under a circuit

    # Square-off cutoff. Most Indian brokers' RMS auto-squares-off MIS
    # intraday positions starting ~15:15-15:20 IST, often at a worse price
    # than your own stop loss and with a penalty fee. A signal "approved"
    # at 15:14 can leave you no real time to place and confirm the order
    # before that window opens. Block fresh entries well before it.
    SQUARE_OFF_CUTOFF = dt_time(14, 45)   # 2:45 PM IST — no new entries after this
    MARKET_OPEN = dt_time(9, 15)
    MARKET_CLOSE = dt_time(15, 30)

    def _current_ist_time(self, override_time: dt_time | None = None) -> tuple[dt_time, str]:
        """
        Returns (current time-of-day, source description). Uses real IST
        via zoneinfo when available rather than trusting the host
        machine's local clock — a cloud VM or laptop set to a different
        timezone would otherwise silently gate trades against the wrong
        clock, which is worse than not gating at all.

        `override_time` lets tests and demos simulate a specific clock
        time deterministically, instead of every test run's outcome
        depending on what time it happens to be when pytest runs.
        """
        if override_time is not None:
            return override_time, "overridden (test/demo)"
        if IST is not None:
            now = datetime.now(IST)
            return now.time(), "Asia/Kolkata (zoneinfo)"
        now = datetime.now()
        return now.time(), "system local time (zoneinfo unavailable — verify this host is set to IST)"

    def _time_of_day_check(self, override_time: dt_time | None = None) -> list[str]:
        reasons = []
        current_time, source = self._current_ist_time(override_time)

        if current_time < self.MARKET_OPEN or current_time >= self.MARKET_CLOSE:
            reasons.append(
                f"Current time {current_time.strftime('%H:%M')} ({source}) is outside "
                f"NSE market hours ({self.MARKET_OPEN.strftime('%H:%M')}-"
                f"{self.MARKET_CLOSE.strftime('%H:%M')}) — no fresh entries"
            )
        elif current_time >= self.SQUARE_OFF_CUTOFF:
            reasons.append(
                f"Current time {current_time.strftime('%H:%M')} ({source}) is at or past "
                f"the {self.SQUARE_OFF_CUTOFF.strftime('%H:%M')} cutoff — brokers' RMS "
                "auto-square-off for MIS intraday positions typically begins around "
                "15:15-15:20 IST, often at a worse price plus a penalty fee. Blocking "
                "fresh entries this close to that window."
            )
        return reasons

    def assess(
        self,
        symbol: str,
        bias: Bias,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        lower_circuit: float,
        upper_circuit: float,
        override_time: dt_time | None = None,
    ) -> RiskAssessment:
        reasons = []

        # Time gate runs first and is non-negotiable — if it fails, no
        # amount of good R:R or distance-from-circuit matters, because
        # there may not be enough of the session left to safely exit
        # before forced square-off.
        time_reasons = self._time_of_day_check(override_time)
        if time_reasons:
            return RiskAssessment(
                symbol=symbol,
                verdict=Verdict.BLOCKED,
                risk_reward_ratio=None,
                distance_to_circuit_pct=None,
                margin_required=None,
                reasons=time_reasons,
            )

        if bias == Bias.BUY:
            risk = entry_price - stop_loss
            reward = target_price - entry_price
        elif bias == Bias.SHORT:
            risk = stop_loss - entry_price
            reward = entry_price - target_price
        else:
            return RiskAssessment(
                symbol=symbol,
                verdict=Verdict.BLOCKED,
                risk_reward_ratio=None,
                distance_to_circuit_pct=None,
                margin_required=None,
                reasons=["No directional bias — nothing to assess"],
            )

        if risk <= 0:
            reasons.append(f"Invalid stop loss: computed risk is {risk:.2f}, must be positive")
            rr = None
        else:
            rr = reward / risk
            if rr < self.MIN_RISK_REWARD:
                reasons.append(
                    f"Risk:Reward {rr:.2f}:1 is below the required {self.MIN_RISK_REWARD}:1 minimum"
                )

        relevant_circuit = upper_circuit if bias == Bias.BUY else lower_circuit
        dist_to_circuit_pct = abs((relevant_circuit - entry_price) / entry_price) * 100

        # For a BUY, the danger is the target running into the upper circuit before
        # it's reached. For a SHORT, the danger is the target running into the lower circuit.
        target_breaches_circuit = (
            (bias == Bias.BUY and target_price >= upper_circuit)
            or (bias == Bias.SHORT and target_price <= lower_circuit)
        )
        if target_breaches_circuit:
            reasons.append(
                f"Target price {target_price:.2f} is at or beyond the circuit limit "
                f"({relevant_circuit:.2f}) — unrealistic / unfillable target"
            )

        if dist_to_circuit_pct < self.MIN_DISTANCE_TO_CIRCUIT_PCT:
            reasons.append(
                f"Entry is only {dist_to_circuit_pct:.2f}% from the circuit limit — "
                "high risk of a freeze with no liquidity to exit"
            )

        verdict = Verdict.APPROVED if not reasons else Verdict.BLOCKED

        return RiskAssessment(
            symbol=symbol,
            verdict=verdict,
            risk_reward_ratio=rr,
            distance_to_circuit_pct=dist_to_circuit_pct,
            margin_required=None,  # wire up kite.margins() / order margin API if needed
            reasons=reasons,
        )
