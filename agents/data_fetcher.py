"""
Data Fetcher Agent — Groww API version.

Swapped from Kite Connect to Groww's `growwapi` SDK. The rest of the
pipeline (technical analysis, tape reader, risk manager, executive
trader) is untouched — they only consume the standardized OHLCVBar /
MarketDepth objects defined in core/models.py, not raw broker payloads.

Auth: uses the API Key + Secret flow (groww.GrowwAPI.get_access_token).
This generates a session token directly with no browser redirect step,
unlike Kite. Note this flow requires daily re-approval per Groww's docs —
if you want a no-expiry token instead, switch to the TOTP flow (see
README) using pyotp.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta

import pandas as pd

try:
    from growwapi import GrowwAPI
except ImportError:
    GrowwAPI = None  # allows the rest of the package to import without growwapi installed

from core.models import OHLCVBar, MarketDepth, MarketDepthLevel


# Groww's own documented rate limits (requests per second / per minute).
# These are enforced server-side per "type" — Orders, Live Data, Non Trading —
# not per individual method, so throttling one throttles all in that group.
RATE_LIMITS = {
    "live_data": {"rps": 10, "rpm": 300},
    "non_trading": {"rps": 20, "rpm": 500},  # historical data falls under here
}


class DataFetcherAgent:
    """
    Wraps Groww's get_quote / get_historical_candles / get_instrument_by_*
    methods. Kept deliberately dumb — no analysis happens here.
    """

    # Max lookback per single call, by candle interval, per Groww's
    # "Backtesting Data Limits" table. Used to auto-chunk longer requests.
    MAX_DAYS_PER_REQUEST = {
        "1": 30, "2": 30, "3": 30, "5": 30,      # 1-5 min candles: 30 days/request
        "10": 90, "15": 90, "30": 90,             # 10-30 min candles: 90 days/request
        "60": 180, "240": 180, "1440": 180, "10080": 180,  # 1h+ candles: 180 days/request
    }

    def __init__(self, api_key: str, api_secret: str):
        if GrowwAPI is None:
            raise RuntimeError("growwapi not installed. pip install growwapi")
        access_token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
        self.groww = GrowwAPI(access_token)
        self._last_live_call = 0.0
        self._last_data_call = 0.0

    # ---- rate limiting -------------------------------------------------
    def _throttle_live(self):
        elapsed = time.time() - self._last_live_call
        if elapsed < 0.11:  # stay under 10 rps with margin
            time.sleep(0.11 - elapsed)
        self._last_live_call = time.time()

    def _throttle_data(self):
        elapsed = time.time() - self._last_data_call
        if elapsed < 0.06:  # stay under 20 rps with margin
            time.sleep(0.06 - elapsed)
        self._last_data_call = time.time()

    # ---- instrument resolution ------------------------------------------
    def resolve_groww_symbol(self, symbol: str, exchange: str = "NSE") -> str:
        """
        Groww doesn't need a numeric token lookup like Kite — the groww_symbol
        is just "{EXCHANGE}-{TRADING_SYMBOL}" for equities/indices. This
        confirms the instrument actually exists and is tradable before we
        waste a historical-data call on a typo'd symbol.
        """
        info = self.groww.get_instrument_by_exchange_and_trading_symbol(
            exchange=exchange, trading_symbol=symbol
        )
        return info["groww_symbol"]

    # ---- historical data -------------------------------------------------
    def fetch_historical(
        self,
        symbol: str,
        interval_minutes: int,   # 1, 5, 10, 15, 30, 60, 240, 1440, 10080
        days_back: int,
        exchange: str = "NSE",
        segment: str = "CASH",
    ) -> pd.DataFrame:
        """
        Returns a DataFrame indexed by timestamp with columns:
        open, high, low, close, volume

        Auto-chunks requests that exceed Groww's per-request max duration
        for the given interval (see MAX_DAYS_PER_REQUEST).
        """
        groww_symbol = self.resolve_groww_symbol(symbol, exchange)
        max_chunk = self.MAX_DAYS_PER_REQUEST.get(str(interval_minutes), 30)

        end = datetime.now()
        overall_start = end - timedelta(days=days_back)
        frames = []

        cursor_end = end
        while cursor_end > overall_start:
            cursor_start = max(overall_start, cursor_end - timedelta(days=max_chunk))
            self._throttle_data()
            try:
                resp = self.groww.get_historical_candles(
                    exchange=exchange,
                    segment=segment,
                    groww_symbol=groww_symbol,
                    start_time=cursor_start.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=cursor_end.strftime("%Y-%m-%d %H:%M:%S"),
                    candle_interval=str(interval_minutes),
                )
            except Exception as e:
                raise RuntimeError(f"Historical fetch failed for {symbol}: {e}") from e

            candles = resp.get("candles", [])
            if candles:
                frames.append(pd.DataFrame(
                    candles, columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"]
                ))
            cursor_end = cursor_start

        if not frames:
            raise ValueError(f"No historical data returned for {symbol}")

        df = pd.concat(frames)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        df = df[~df.index.duplicated(keep="first")]

        # Defensive check: chunks are fetched newest-first and appended in
        # that order, so correctness here depends entirely on sort_index()
        # sorting by timestamp VALUE (which it does) rather than by chunk
        # position. Assert it explicitly instead of trusting it silently —
        # if Groww ever returns an unparseable/duplicate timestamp that
        # slips through, this fails loudly here instead of producing a
        # silently mis-ordered series that corrupts every indicator
        # downstream (VWAP, EMA, RSI all assume index order == time order).
        if not df.index.is_monotonic_increasing:
            raise RuntimeError(
                f"Historical data for {symbol} is not chronologically sorted after "
                "concat+sort — this would corrupt every downstream indicator. "
                "Aborting rather than computing on bad data."
            )

        return df[["open", "high", "low", "close", "volume"]].astype(
            {"open": float, "high": float, "low": float, "close": float, "volume": int}
        )

    # ---- live quote + depth ----------------------------------------------
    def fetch_quote_and_depth(self, symbol: str, exchange: str = "NSE", segment: str = "CASH") -> MarketDepth:
        """
        Groww's get_quote returns everything in one call: last price, top-5
        depth, AND the circuit limits — no separate call needed, unlike Kite
        where circuit limits required digging through a slightly different
        response shape.
        """
        self._throttle_live()
        quote = self.groww.get_quote(exchange=exchange, segment=segment, trading_symbol=symbol)

        buy_levels = [
            MarketDepthLevel(price=float(l["price"]), quantity=int(l["quantity"]))
            for l in quote["depth"]["buy"]
        ]
        sell_levels = [
            MarketDepthLevel(price=float(l["price"]), quantity=int(l["quantity"]))
            for l in quote["depth"]["sell"]
        ]
        return MarketDepth(
            buy=buy_levels,
            sell=sell_levels,
            last_price=float(quote["last_price"]),
            last_quantity=int(quote.get("last_trade_quantity", 0)),
            volume_traded=int(quote.get("volume", 0)),
            timestamp=datetime.now(),
        )

    def circuit_limits(self, symbol: str, exchange: str = "NSE", segment: str = "CASH") -> tuple[float, float]:
        """
        Returns (lower_circuit, upper_circuit). Groww exposes these directly
        as `lower_circuit_limit` / `upper_circuit_limit` in get_quote — no
        fallback/uncertainty needed here, unlike the Kite version.
        """
        self._throttle_live()
        quote = self.groww.get_quote(exchange=exchange, segment=segment, trading_symbol=symbol)
        return float(quote["lower_circuit_limit"]), float(quote["upper_circuit_limit"])

    def fetch_quote_circuit_and_depth(
        self, symbol: str, exchange: str = "NSE", segment: str = "CASH"
    ) -> tuple[MarketDepth, float, float]:
        """
        Convenience method: one get_quote call returns depth AND circuit
        limits together, instead of two separate API calls (which would
        burn 2x the rate-limit budget for the same data).
        """
        self._throttle_live()
        quote = self.groww.get_quote(exchange=exchange, segment=segment, trading_symbol=symbol)

        buy_levels = [
            MarketDepthLevel(price=float(l["price"]), quantity=int(l["quantity"]))
            for l in quote["depth"]["buy"]
        ]
        sell_levels = [
            MarketDepthLevel(price=float(l["price"]), quantity=int(l["quantity"]))
            for l in quote["depth"]["sell"]
        ]
        depth = MarketDepth(
            buy=buy_levels,
            sell=sell_levels,
            last_price=float(quote["last_price"]),
            last_quantity=int(quote.get("last_trade_quantity", 0)),
            volume_traded=int(quote.get("volume", 0)),
            timestamp=datetime.now(),
        )
        return depth, float(quote["lower_circuit_limit"]), float(quote["upper_circuit_limit"])
