"""
Shared data models for the intraday signal pipeline.
Every agent passes data around using these typed structures —
no raw dicts floating between agents.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Bias(str, Enum):
    BUY = "BUY"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class Verdict(str, Enum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    NOT_VIABLE = "NOT_VIABLE"  # failed liquidity/volatility check, never even got to a bias


@dataclass
class OHLCVBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class MarketDepthLevel:
    price: float
    quantity: int
    orders: Optional[int] = None  # Kite provides this per level; Groww does not


@dataclass
class MarketDepth:
    """Top-5 bid/ask. This is what Kite actually gives you — not full L2."""
    buy: list[MarketDepthLevel]
    sell: list[MarketDepthLevel]
    last_price: float
    last_quantity: int
    volume_traded: int
    timestamp: datetime


@dataclass
class LiquidityCheck:
    symbol: str
    viable: bool
    atr_20d: float
    atr_pct_of_price: float          # ATR as % of price — normalizes across price levels
    avg_daily_volume_20d: float
    avg_daily_turnover_cr: float     # in crores — what NSE/SEBI actually care about
    circuit_band_pct: float          # the ACTUAL applicable band, not a hardcoded 10%
    distance_to_upper_circuit_pct: float
    distance_to_lower_circuit_pct: float
    rejection_reasons: list[str] = field(default_factory=list)


@dataclass
class TechnicalReading:
    symbol: str
    timestamp: datetime
    ltp: float
    vwap: float
    ema_20: float
    rsi_14: float
    macd_line: float
    macd_signal: float
    macd_hist: float
    htf_trend: str            # "UP" / "DOWN" / "SIDEWAYS" from the 1h confirmation chart
    bias: Bias
    bias_strength: float      # 0-1, how convincingly aligned VWAP+EMA+HTF are
    pivot_r1: float
    pivot_s1: float
    swing_high: float
    swing_low: float
    opening_range_high: float
    opening_range_low: float
    notes: list[str] = field(default_factory=list)


@dataclass
class TapeReading:
    symbol: str
    timestamp: datetime
    bid_ask_imbalance: float   # (bid_qty - ask_qty) / (bid_qty + ask_qty), -1..+1
    volume_spike_ratio: float  # current 1-min volume / 20-bar average 1-min volume
    large_order_detected: bool
    large_order_side: Optional[str]
    notes: list[str] = field(default_factory=list)


@dataclass
class SentimentReading:
    symbol: str
    timestamp: datetime
    score: float               # -1 (very negative) to +1 (very positive)
    confidence: float          # 0-1, how much weight this should carry
    headline_count: int
    summary: str
    sources: list[str] = field(default_factory=list)
    has_breaking_news: bool = False


@dataclass
class RiskAssessment:
    symbol: str
    verdict: Verdict
    risk_reward_ratio: Optional[float]
    distance_to_circuit_pct: Optional[float]
    margin_required: Optional[float]
    reasons: list[str] = field(default_factory=list)


@dataclass
class TradeSignal:
    symbol: str
    timestamp: datetime
    verdict: Verdict
    bias: Bias
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target_price: Optional[float]
    risk_reward_ratio: Optional[float]
    confidence: float
    rationale: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
