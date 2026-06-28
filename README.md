# Intraday Signal Agent (India) — Signal-Only

A multi-agent pipeline that takes an NSE/BSE stock symbol and produces a
BUY/SHORT/SKIP signal with entry, stop loss, and target — for **manual**
intraday trading decisions. It does not place orders.

**Broker: Groww API**

## Why this is "signal-only"

Because you click the actual buy/sell button in Groww yourself, this stays
outside SEBI's Feb 2025 algorithmic trading framework, which requires
broker/exchange registration for systems that **place orders automatically**.
If you ever convert this to auto-execution, you'd need to register the
strategy with your broker first.

## Architecture — what's an LLM and what isn't

Most of this pipeline is **deterministic Python**, not an LLM call:

| Agent | LLM? | Why |
|---|---|---|
| Data Fetcher | No | Pure I/O against the Groww API |
| Technical Analysis | No | VWAP/RSI/MACD/ATR/pivots — math must be exact, not "plausible" |
| Tape Reader | No | Order book math |
| Risk Manager | No | Hard numeric gates — this agent has veto power |
| Executive Trader | No | Entry/SL/target computed from market structure |
| Sentiment Analyst | Optional | Marketaux scores sentiment per ticker directly — no LLM call required. An LLM can optionally add plain-English narration on top |

The LLM is fully optional for sentiment — Marketaux's `sentiment_score`
per entity already does the scoring. Without a Marketaux token configured,
or if the request fails, `SentimentAnalystAgent` returns a neutral,
zero-confidence reading so the pipeline still runs (it never blocks a
signal on a missing news source — see Executive Trader logic). If you
want an LLM to add plain-English narration on top of Marketaux's scores
and highlights, pass a client into `SentimentAnalystAgent(llm_client=...)`
and extend `_aggregate` to call it.

## What this does NOT give you (be aware before trusting it with money)

- **Not full order-book depth.** Groww exposes only the top 5 bid/ask levels
  (same shape Kite gives — just price + quantity, no per-level order count).
  "Institutional block detection" in `tape_reader.py` is a heuristic on a
  partial view, not a guarantee — large icebergs and hidden orders are
  invisible to this.
- **News sourcing uses Marketaux, not scraping.** Scraping Moneycontrol/ET/
  Twitter pages directly breaks constantly and likely violates their ToS.
  Marketaux is purpose-built for ticker-level financial sentiment — it
  resolves articles to entities and returns a sentiment score per
  entity directly, so no separate LLM scoring call is needed. Free
  tier: 100 requests/day, real-time (not delayed). Get a token at
  `marketaux.com/register`. Coverage of India-listed small/mid-caps can
  be thin — the agent's `confidence` field reflects this when
  `headline_count` is low, and the Executive Trader already discounts
  low-confidence sentiment accordingly.
- **No backtest has been run yet.** This pipeline has been validated for
  *logical correctness* (the math matches a reference TA library, the risk
  gate correctly blocks bad trades) using synthetic data — NOT for
  *profitability* on real historical data. Do that before risking capital.
  See "Suggested next step" below. Groww's API conveniently has a
  dedicated Backtesting data endpoint (`get_historical_candles`) for this.
- **Circuit bands are fetched live**, not hardcoded to 10%. Groww's
  `get_quote` response includes `upper_circuit_limit` / `lower_circuit_limit`
  directly — confirmed in their own docs, no guessing needed here.
- **1-minute candle history is limited to the last 3 months** per Groww's
  documented data retention (longer history is available at coarser
  intervals — daily candles go back to 2020). This is plenty for the
  liquidity/ATR checks but worth knowing if you want a longer backtest.
- **Daily token refresh.** The API Key + Secret auth flow used here needs
  re-approval daily per Groww's docs. If that's annoying, switch to the
  TOTP flow (`pyotp`), which Groww states has no expiry — see Setup below.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in GROWW_API_KEY, GROWW_API_SECRET, MARKETAUX_API_TOKEN in .env
```

Get your Groww API key/secret from https://groww.in/trade-api/api-keys
(requires an active Trading API subscription, ₹499/month + GST).

### Try it without any API keys first

```bash
python demo_synthetic.py
```

This runs the full pipeline on synthetic data so you can see exactly how a
signal gets built and how the risk gate can block a trade — no broker
account needed.

### Run on a real symbol (requires Groww Trading API subscription)

```bash
python live_runner.py --symbol RELIANCE
```

No browser login step needed — the API Key + Secret flow exchanges
directly for an access token in code. Note: per Groww's docs this flow
needs daily re-approval. If you'd rather not deal with that, switch to
the TOTP flow:

```python
import pyotp
from growwapi import GrowwAPI

totp_gen = pyotp.TOTP("YOUR_TOTP_SECRET")  # from the Groww API Keys page
access_token = GrowwAPI.get_access_token(api_key="YOUR_TOTP_TOKEN", totp=totp_gen.now())
```

Groww states the TOTP flow has no expiry, which is more convenient for
a script you run repeatedly throughout the trading day.

## Project layout

```
core/
  models.py      — all data structures shared between agents
  pipeline.py     — orchestrator wiring the agents together
agents/
  data_fetcher.py        — Groww API wrapper (historical + live + depth)
  technical_analysis.py  — VWAP/EMA/RSI/MACD/ATR/pivots + liquidity filter
  tape_reader.py          — order book imbalance + volume spikes
  sentiment_analyst.py    — news fetch + LLM/heuristic scoring
  risk_manager.py          — the gatekeeper, hard numeric vetoes
  executive_trader.py     — consolidation + entry/SL/target math
tests/
  test_risk_manager.py    — safety-critical agent gets the most test coverage
demo_synthetic.py          — run the whole pipeline with fake data
live_runner.py              — run it against real Groww API
```

## Suggested next step: backtest before trusting this

Nothing here proves the *strategy* is profitable — only that the *code* is
correct. Before risking real capital:

1. Pull 60+ days of 5-min historical data for a basket of liquid stocks
   (Nifty 50 names are a reasonable start — high liquidity, sane circuit
   distance).
2. Run the Technical + Risk logic bar-by-bar over that history (skip the
   live-only tape/sentiment agents, or mock them).
3. Track hypothetical entries/exits and compute win rate, average R:R
   achieved, and max drawdown.
4. Only after that looks reasonable, move to paper-trading the signals
   live for a few weeks before using real money.

I can build this backtester next if you want — it reuses the exact same
`TechnicalAnalysisAgent` and `RiskManagerAgent` code, so you're testing the
real logic, not an approximation of it.

## Disclaimer

This is a decision-support tool, not financial advice. Intraday trading
carries substantial risk of loss. Past patterns in historical data do not
guarantee future results. You are solely responsible for any trades you
execute.