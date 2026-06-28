"""
Tape Reader / Momentum Agent.
Deterministic. Reads top-5 depth + recent volume to flag imbalance and
volume spikes. Be honest with yourself about what this can and can't see:
this is NOT full order-book / Level-2 data, so "institutional block
detection" here is a heuristic on a partial view, not a certainty.
"""
from __future__ import annotations
from datetime import datetime

import pandas as pd

from core.models import MarketDepth, TapeReading


class TapeReaderAgent:
    LARGE_ORDER_QTY_MULTIPLE = 5.0  # a single depth level >= 5x the avg level size

    def analyze(
        self,
        symbol: str,
        depth: MarketDepth,
        recent_1min_volumes: pd.Series,  # last ~20 one-minute volume bars
    ) -> TapeReading:
        notes = []

        total_bid_qty = sum(l.quantity for l in depth.buy)
        total_ask_qty = sum(l.quantity for l in depth.sell)
        denom = total_bid_qty + total_ask_qty
        imbalance = (total_bid_qty - total_ask_qty) / denom if denom else 0.0

        if imbalance > 0.3:
            notes.append(f"Bid-heavy book ({imbalance:+.0%}) — buyers in control at this depth snapshot")
        elif imbalance < -0.3:
            notes.append(f"Ask-heavy book ({imbalance:+.0%}) — sellers in control at this depth snapshot")

        avg_1min_vol = float(recent_1min_volumes.mean()) if len(recent_1min_volumes) else 0.0
        current_1min_vol = float(recent_1min_volumes.iloc[-1]) if len(recent_1min_volumes) else 0.0
        spike_ratio = (current_1min_vol / avg_1min_vol) if avg_1min_vol else 1.0

        if spike_ratio > 2.5:
            notes.append(f"Volume spike: {spike_ratio:.1f}x the 20-bar average")

        all_levels = [(l.quantity, "BUY") for l in depth.buy] + [(l.quantity, "SELL") for l in depth.sell]
        avg_level_qty = sum(q for q, _ in all_levels) / len(all_levels) if all_levels else 0.0
        large_order = False
        large_side = None
        if avg_level_qty:
            for qty, side in all_levels:
                if qty >= self.LARGE_ORDER_QTY_MULTIPLE * avg_level_qty:
                    large_order = True
                    large_side = side
                    notes.append(
                        f"Large {side} order detected: {qty} qty vs avg level size {avg_level_qty:.0f} "
                        "(heuristic only — top-5 depth, not full L2)"
                    )
                    break

        return TapeReading(
            symbol=symbol,
            timestamp=datetime.now(),
            bid_ask_imbalance=imbalance,
            volume_spike_ratio=spike_ratio,
            large_order_detected=large_order,
            large_order_side=large_side,
            notes=notes,
        )
