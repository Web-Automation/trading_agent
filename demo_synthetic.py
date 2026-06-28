"""
Runnable demo using SYNTHETIC data — no Groww API keys needed.
This proves the pipeline logic is wired correctly before you connect
real Groww credentials. Run: python demo_synthetic.py

Uses a fixed override_time (11:00 AM IST) for every scenario so results
are deterministic regardless of when you actually run this script — the
RiskManagerAgent's square-off time gate would otherwise block every
scenario after 2:45 PM IST and before 9:15 AM IST, which would make this
demo's output depend on wall-clock time rather than the trade logic
being demonstrated.
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, time as dt_time

from core.models import MarketDepth, MarketDepthLevel
from core.pipeline import IntradaySignalPipeline

DEMO_TIME = dt_time(11, 0)  # fixed mid-session time so demo output is reproducible


def make_synthetic_daily(days=40, start_price=2500.0, trend=0.0015, seed=42):
    rng = np.random.default_rng(seed)
    closes = [start_price]
    for _ in range(days - 1):
        ret = trend + rng.normal(0, 0.012)
        closes.append(closes[-1] * (1 + ret))
    closes = np.array(closes)
    n = len(closes)
    dates = pd.date_range(end=datetime.now().date() - timedelta(days=1), periods=n, freq="D")
    highs = closes * (1 + rng.uniform(0.002, 0.015, size=n))
    lows = closes * (1 - rng.uniform(0.002, 0.015, size=n))
    opens = closes * (1 + rng.normal(0, 0.004, size=n))
    volumes = rng.integers(800_000, 3_000_000, size=n)
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=dates
    )
    return df


def make_synthetic_intraday(daily_close: float, bars=75, freq="5min", trend_per_bar=0.0006, seed=7):
    """75 bars of 5-min data ~ one trading session (9:15 to 15:30)."""
    rng = np.random.default_rng(seed)
    today = datetime.now().replace(hour=9, minute=15, second=0, microsecond=0)
    timestamps = pd.date_range(start=today, periods=bars, freq=freq)
    closes = [daily_close]
    for _ in range(bars - 1):
        ret = trend_per_bar + rng.normal(0, 0.0015)
        closes.append(closes[-1] * (1 + ret))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0.0005, 0.003, size=bars))
    lows = closes * (1 - rng.uniform(0.0005, 0.003, size=bars))
    opens = np.roll(closes, 1)
    opens[0] = daily_close
    volumes = rng.integers(20_000, 120_000, size=bars)
    df = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=timestamps,
    )
    return df


def make_synthetic_hourly(intraday_df: pd.DataFrame) -> pd.DataFrame:
    h = intraday_df.resample("60min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    return h


def make_synthetic_depth(ltp: float, bullish=True, seed=3) -> MarketDepth:
    rng = np.random.default_rng(seed)
    tick = 0.05
    buy_levels, sell_levels = [], []
    for i in range(5):
        bid_qty = int(rng.integers(500, 5000) * (1.4 if bullish else 0.8))
        ask_qty = int(rng.integers(500, 5000) * (0.8 if bullish else 1.4))
        buy_levels.append(MarketDepthLevel(price=round(ltp - i * tick, 2), quantity=bid_qty, orders=rng.integers(1, 20)))
        sell_levels.append(MarketDepthLevel(price=round(ltp + i * tick, 2), quantity=ask_qty, orders=rng.integers(1, 20)))
    return MarketDepth(
        buy=buy_levels, sell=sell_levels, last_price=ltp,
        last_quantity=int(rng.integers(50, 500)), volume_traded=int(rng.integers(1_000_000, 5_000_000)),
        timestamp=datetime.now(),
    )


def run_scenario(name: str, trend: float, bullish_tape: bool, demo_time: dt_time = DEMO_TIME):
    print(f"\n{'='*70}\nSCENARIO: {name}\n{'='*70}")

    daily_df = make_synthetic_daily(days=40, start_price=2500.0, trend=trend / 20)
    last_daily_close = float(daily_df["close"].iloc[-1])
    intraday_df = make_synthetic_intraday(last_daily_close, bars=75, trend_per_bar=trend)
    hourly_df = make_synthetic_hourly(intraday_df)
    ltp = float(intraday_df["close"].iloc[-1])

    depth = make_synthetic_depth(ltp, bullish=bullish_tape)
    recent_1min_vol = pd.Series(np.random.default_rng(1).integers(5000, 40000, size=20))

    lower_circuit = round(last_daily_close * 0.90, 2)
    upper_circuit = round(last_daily_close * 1.10, 2)

    pipeline = IntradaySignalPipeline()  # no marketaux_api_token -> sentiment fetch fails gracefully, returns neutral
    signal = pipeline.run(
        symbol="DEMO", company_name="Demo Company Ltd",
        daily_df=daily_df, intraday_df=intraday_df, hourly_df=hourly_df,
        depth=depth, recent_1min_volumes=recent_1min_vol,
        lower_circuit=lower_circuit, upper_circuit=upper_circuit,
        override_time=demo_time,
    )

    print(f"LTP: {ltp:.2f} | Circuit band: {lower_circuit:.2f} - {upper_circuit:.2f}")
    print(f"Verdict: {signal.verdict.value}")
    print(f"Bias: {signal.bias.value}")
    if signal.entry_price:
        print(f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | Target: {signal.target_price}")
        print(f"Risk:Reward: {signal.risk_reward_ratio}")
        print(f"Confidence: {signal.confidence}")
    if signal.rationale:
        print("Rationale:")
        for r in signal.rationale:
            print(f"  - {r}")
    if signal.blocking_reasons:
        print("Blocking reasons:")
        for r in signal.blocking_reasons:
            print(f"  - {r}")


if __name__ == "__main__":
    run_scenario("Strong uptrend + bullish tape -> expect BUY", trend=0.0012, bullish_tape=True)
    run_scenario("Strong downtrend + bearish tape -> expect SHORT", trend=-0.0012, bullish_tape=False)
    run_scenario("Flat/choppy -> expect NEUTRAL/BLOCKED", trend=0.00005, bullish_tape=True)
    run_scenario(
        "Same strong uptrend, but at 3:10 PM IST -> expect BLOCKED (square-off gate)",
        trend=0.0012, bullish_tape=True, demo_time=dt_time(15, 10),
    )
