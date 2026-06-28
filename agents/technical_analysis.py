"""
Technical Analysis Agent.
100% deterministic. No LLM calls. This is where VWAP, RSI, MACD,
ATR, pivots, and the buy/short bias actually get computed.
"""
from __future__ import annotations
from datetime import datetime

import numpy as np
import pandas as pd

from core.models import Bias, LiquidityCheck, TechnicalReading


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Session VWAP. Must reset every trading day — VWAP carried over from
    yesterday's close is meaningless for intraday decisions.
    df must have a DatetimeIndex and columns: high, low, close, volume.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df = df.copy()
    df["_tp_vol"] = typical_price * df["volume"]
    day = df.index.date
    cum_tp_vol = df.groupby(day)["_tp_vol"].cumsum()
    cum_vol = df.groupby(day)["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol.replace(0, np.nan)
    return vwap


def compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)  # neutral when undefined (e.g. flat early data)


def compute_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True range based ATR. Used both for the daily liquidity filter (20d ATR
    on daily candles) and for stop-loss sizing (intraday ATR on 5-min candles)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def compute_pivot_points(prev_day: pd.Series) -> dict:
    """Classic floor-trader pivots from the previous day's H/L/C."""
    h, l, c = prev_day["high"], prev_day["low"], prev_day["close"]
    pivot = (h + l + c) / 3
    r1 = 2 * pivot - l
    s1 = 2 * pivot - h
    r2 = pivot + (h - l)
    s2 = pivot - (h - l)
    return {"pivot": pivot, "r1": r1, "s1": s1, "r2": r2, "s2": s2}


def opening_range(intraday_df: pd.DataFrame, minutes: int = 15) -> tuple[float, float]:
    """High/low of the first N minutes of today's session."""
    today = intraday_df.index[-1].date()
    todays = intraday_df[intraday_df.index.date == today]
    if todays.empty:
        return float("nan"), float("nan")
    window = todays.iloc[: max(1, minutes // 5)]  # assumes 5-min bars; adjust for your bar size
    return float(window["high"].max()), float(window["low"].min())


class LiquidityFilter:
    """
    Step 1 of the spec: liquidity & volatility check.
    Runs BEFORE any bias/entry logic. If a stock fails here, we stop —
    no signal is generated, regardless of how good the technicals look.
    """

    MIN_AVG_DAILY_TURNOVER_CR = 5.0     # tune to your capital/slippage tolerance
    MIN_ATR_PCT_OF_PRICE = 0.3          # below this, the stock barely moves intraday
    MAX_ATR_PCT_OF_PRICE = 8.0          # above this, intraday moves are erratic/gappy
    MIN_DISTANCE_TO_CIRCUIT_PCT = 1.5   # don't trade names already hugging a circuit

    def check(
        self,
        symbol: str,
        daily_df: pd.DataFrame,
        ltp: float,
        lower_circuit: float,
        upper_circuit: float,
    ) -> LiquidityCheck:
        reasons = []

        atr_series = compute_atr(daily_df, period=20)
        atr_20d = float(atr_series.iloc[-1])
        atr_pct = (atr_20d / ltp) * 100 if ltp else 0.0

        avg_vol_20d = float(daily_df["volume"].tail(20).mean())
        avg_turnover_cr = (avg_vol_20d * ltp) / 1e7  # 1 crore = 1e7

        circuit_band_pct = ((upper_circuit - lower_circuit) / (2 * ltp)) * 100 if ltp else 0.0
        dist_upper = ((upper_circuit - ltp) / ltp) * 100 if ltp else 0.0
        dist_lower = ((ltp - lower_circuit) / ltp) * 100 if ltp else 0.0

        if avg_turnover_cr < self.MIN_AVG_DAILY_TURNOVER_CR:
            reasons.append(
                f"Avg daily turnover ₹{avg_turnover_cr:.1f}cr below "
                f"₹{self.MIN_AVG_DAILY_TURNOVER_CR}cr minimum — slippage risk"
            )
        if atr_pct < self.MIN_ATR_PCT_OF_PRICE:
            reasons.append(f"ATR {atr_pct:.2f}% of price is too low — insufficient intraday range")
        if atr_pct > self.MAX_ATR_PCT_OF_PRICE:
            reasons.append(f"ATR {atr_pct:.2f}% of price is too high — erratic/gappy moves")
        if min(dist_upper, dist_lower) < self.MIN_DISTANCE_TO_CIRCUIT_PCT:
            reasons.append(
                f"Only {min(dist_upper, dist_lower):.2f}% away from a circuit limit — too risky"
            )

        return LiquidityCheck(
            symbol=symbol,
            viable=(len(reasons) == 0),
            atr_20d=atr_20d,
            atr_pct_of_price=atr_pct,
            avg_daily_volume_20d=avg_vol_20d,
            avg_daily_turnover_cr=avg_turnover_cr,
            circuit_band_pct=circuit_band_pct,
            distance_to_upper_circuit_pct=dist_upper,
            distance_to_lower_circuit_pct=dist_lower,
            rejection_reasons=reasons,
        )


class TechnicalAnalysisAgent:
    """
    Step 2 of the spec: trend direction via VWAP + 20 EMA, confirmed by a
    higher timeframe (1h) trend, plus RSI/MACD as secondary confirmation —
    not primary signal generators. This avoids over-firing on RSI/MACD noise.
    """

    def htf_trend(self, hourly_df: pd.DataFrame) -> str:
        if len(hourly_df) < 21:
            return "SIDEWAYS"
        ema20 = compute_ema(hourly_df["close"], 20)
        last_close = hourly_df["close"].iloc[-1]
        last_ema = ema20.iloc[-1]
        prev_ema = ema20.iloc[-5] if len(ema20) > 5 else ema20.iloc[0]
        slope_up = last_ema > prev_ema
        if last_close > last_ema and slope_up:
            return "UP"
        if last_close < last_ema and not slope_up:
            return "DOWN"
        return "SIDEWAYS"

    def analyze(
        self,
        symbol: str,
        intraday_df: pd.DataFrame,   # 5-min bars, today + recent history
        hourly_df: pd.DataFrame,     # 1h bars for HTF confirmation
        daily_df: pd.DataFrame,      # daily bars for prior-day pivots
    ) -> TechnicalReading:
        notes = []

        vwap_series = compute_vwap(intraday_df)
        ema20_series = compute_ema(intraday_df["close"], 20)
        rsi_series = compute_rsi(intraday_df["close"], 14)
        macd_line, macd_signal, macd_hist = compute_macd(intraday_df["close"])

        ltp = float(intraday_df["close"].iloc[-1])
        vwap = float(vwap_series.iloc[-1])
        ema20 = float(ema20_series.iloc[-1])
        rsi = float(rsi_series.iloc[-1])

        trend = self.htf_trend(hourly_df)

        above_vwap = ltp > vwap
        above_ema = ltp > ema20
        htf_up = trend == "UP"
        htf_down = trend == "DOWN"

        bullish_votes = sum([above_vwap, above_ema, htf_up])
        bearish_votes = sum([not above_vwap, not above_ema, htf_down])

        if bullish_votes >= 2 and bullish_votes > bearish_votes:
            bias = Bias.BUY
            strength = bullish_votes / 3
        elif bearish_votes >= 2 and bearish_votes > bullish_votes:
            bias = Bias.SHORT
            strength = bearish_votes / 3
        else:
            bias = Bias.NEUTRAL
            strength = 0.0
            notes.append("VWAP/EMA/HTF trend not aligned — no clean directional bias")

        if rsi > 70:
            notes.append(f"RSI {rsi:.0f} is overbought — caution on fresh longs")
        elif rsi < 30:
            notes.append(f"RSI {rsi:.0f} is oversold — caution on fresh shorts")

        if macd_hist.iloc[-1] > 0 and bias == Bias.SHORT:
            notes.append("MACD histogram still positive — conflicts with SHORT bias")
        if macd_hist.iloc[-1] < 0 and bias == Bias.BUY:
            notes.append("MACD histogram still negative — conflicts with BUY bias")

        prev_day = daily_df.iloc[-2] if len(daily_df) >= 2 else daily_df.iloc[-1]
        pivots = compute_pivot_points(prev_day)

        swing_high = float(intraday_df["high"].tail(20).max())
        swing_low = float(intraday_df["low"].tail(20).min())
        or_high, or_low = opening_range(intraday_df, minutes=15)

        return TechnicalReading(
            symbol=symbol,
            timestamp=datetime.now(),
            ltp=ltp,
            vwap=vwap,
            ema_20=ema20,
            rsi_14=rsi,
            macd_line=float(macd_line.iloc[-1]),
            macd_signal=float(macd_signal.iloc[-1]),
            macd_hist=float(macd_hist.iloc[-1]),
            htf_trend=trend,
            bias=bias,
            bias_strength=strength,
            pivot_r1=float(pivots["r1"]),
            pivot_s1=float(pivots["s1"]),
            swing_high=swing_high,
            swing_low=swing_low,
            opening_range_high=or_high,
            opening_range_low=or_low,
            notes=notes,
        )
