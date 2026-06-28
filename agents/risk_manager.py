"""
Risk Manager Agent — the gatekeeper.
This agent has VETO power and runs LAST, after a price plan exists.
No LLM, no fuzziness: hard numeric thresholds only. If a trade fails
here, it is BLOCKED, full stop, regardless of how confident upstream
agents were.
"""
from __future__ import annotations

from core.models import RiskAssessment, Verdict, Bias


class RiskManagerAgent:
    MIN_RISK_REWARD = 2.0              # spec requirement: must be >= 1:2
    MIN_DISTANCE_TO_CIRCUIT_PCT = 1.0  # don't let entry sit right under a circuit

    def assess(
        self,
        symbol: str,
        bias: Bias,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        lower_circuit: float,
        upper_circuit: float,
    ) -> RiskAssessment:
        reasons = []

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
