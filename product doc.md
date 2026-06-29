# Intraday Signal Agent — Product Documentation

**INTRADAY SIGNAL AGENT**

**Indian Equity Markets — NSE / BSE**

*Technical & Product Documentation*

Signal-only decision support · Multi-agent architecture · Groww API

**Version 1.1 · June 2026**

---

## Table of Contents

1. [Vision & Product Intent](#1-vision--product-intent)
2. [System Architecture](#2-system-architecture)
3. [Why This System Does Not Use an LLM for Trading Logic](#3-why-this-system-does-not-use-an-llm-for-trading-logic)
4. [Agent-by-Agent Mechanism](#4-agent-by-agent-mechanism)
5. [End-to-End Data Flow](#5-end-to-end-data-flow)
6. [External APIs & Their Role](#6-external-apis--their-role)
7. [Safety, Compliance & Known Limitations](#7-safety-compliance--known-limitations)
8. [Suggested Roadmap](#8-suggested-roadmap)

---

## 1. Vision & Product Intent

This system exists to answer one narrow, well-defined question for a single Indian-listed stock, on a single trading day: given everything observable right now — price structure, order book, liquidity, recent news — is an intraday trade justified, and if so, at exactly what price should it be entered, protected, and exited?

It is deliberately **not** a black box that says "buy" or "sell." Every signal is the output of a fixed, inspectable sequence of checks, each of which can independently veto the trade. The product philosophy is closer to a flight pre-check than to a prediction engine: the system's job is to refuse bad setups at least as much as it is to find good ones.

### 1.1 Design Principles

- **Signal-only, never autonomous.** The system never places an order. It produces a recommendation — direction, entry, stop loss, target — that a human reviews and executes manually in the Groww app. This is a deliberate product boundary, not a limitation: it keeps the system outside SEBI's algorithmic-trading registration requirements, which apply specifically to systems that place orders without a human in the loop.

- **Math must be exact, not plausible.** Every number that feeds into a trading decision — VWAP, RSI, ATR, entry price, stop loss — is computed by deterministic, testable Python. Nothing about the price plan is generated or approximated by a language model.

- **Veto-based safety, not advisory safety.** The Risk Manager agent does not advise caution — it has the unilateral power to block a trade outright, and runs after every other agent, so it always has final say.

- **Each agent does one job and trusts typed data, not raw broker responses, from its neighbours.**

### 1.2 Who This Is For

An individual intraday trader on the Indian markets who wants a structured, repeatable second opinion before placing an MIS (intraday margin) trade — not a replacement for judgment, but a way to remove emotional and inconsistent decision-making from the entry/exit math.

---

## 2. System Architecture

The system is a **fixed-sequence pipeline** of six specialised agents. "Agent" here means a well-scoped Python class with a single typed input contract and a single typed output contract — not an autonomous LLM agent that decides its own next action. The sequence is known in advance and never branches dynamically, which is why no agent-orchestration framework (CrewAI, LangGraph, etc.) is used.

### 2.1 Pipeline Flow

1. **Data Fetcher Agent** pulls historical OHLCV candles, the live quote, top-5 market depth, and circuit limits from the Groww API.

2. **Liquidity Filter** (inside the Technical Analysis agent) runs first and can stop the entire pipeline before any other agent executes, if the stock is too illiquid or too volatile to trade safely.

3. **Technical Analysis Agent**, **Tape Reader Agent**, and **Sentiment Analyst Agent** run independently on the same fetched data, each producing a typed reading.

4. **Executive Trader Agent** consolidates all three readings, computes entry / stop loss / target from market structure, and calls the Risk Manager.

5. **Risk Manager Agent** has final veto power: time-of-day, risk:reward, and circuit-distance checks. Any failure blocks the trade regardless of upstream confidence.

6. The pipeline returns one `TradeSignal` object: a verdict, a direction, three prices, a confidence score, and a plain-language rationale.

### 2.2 Why Not an LLM-Orchestrated Multi-Agent Framework

Frameworks like CrewAI or LangGraph earn their complexity when an LLM needs to decide, at runtime, which agent to call next, whether to retry, or how to branch. This system never needs that: the sequence — fetch, analyse, consolidate, gate — is identical on every single run. Adding a framework here would add orchestration overhead without adding any actual flexibility. The architecture is intentionally simple Python composition: each agent is directly callable, directly testable, and directly replaceable.

---

## 3. Why This System Does Not Use an LLM for Trading Logic

This is the single most important design decision in the system, and it is worth stating plainly: **no language model computes, approves, or influences any price in this pipeline.** Every entry, stop loss, and target is produced by deterministic Python arithmetic on real market data.

### 3.1 The Core Argument

- **LLMs are not reliable calculators.** A language model predicts plausible-sounding tokens; it does not guarantee correct arithmetic. Asking an LLM to compute a VWAP or a stop-loss price introduces a non-zero chance of a confidently wrong number — unacceptable when real capital is on the line.

- **LLMs are not consistent rule-followers.** A hard rule like "risk:reward must be ≥ 2:1, no exceptions" needs to fire identically every single time. A deterministic `if`-statement does this perfectly; an LLM call can drift, especially under prompt variation or model updates.

- **LLMs are slow and probabilistic relative to the task.** An API round trip costs hundreds of milliseconds to seconds. Indicator math over a few thousand rows of price data costs single-digit milliseconds in pandas/numpy. For a tool meant to be checked repeatedly through a trading session, this matters.

- **Auditability.** Every threshold in this system — the 2:1 minimum risk:reward, the 1.5% minimum distance from a circuit limit, the 2:45 PM IST square-off cutoff — is a named constant in source code that can be read, tested, and changed with full confidence in what it will do next. An LLM-derived decision cannot be inspected this way.

### 3.2 Where an LLM Is Actually Used

Sentiment scoring is fetched directly from the Marketaux news API, which already returns a numeric `sentiment_score` per company per article — no LLM call is required in the default configuration. The codebase leaves an optional `llm_client` hook in the Sentiment Analyst agent purely for plain-English narration on top of Marketaux's own scoring (for example, summarising why a stock's sentiment is negative in a sentence) — this narration layer never feeds back into any price computation. If used at all, an LLM in this system **explains; it never decides.**

### 3.3 When an LLM Might Earn a Place Later

If the system evolves to need genuinely dynamic judgment — reconciling conflicting unstructured signals, deciding which of many stocks to even examine, or summarising a multi-stock daily report in natural language — an LLM becomes appropriate for that narrow slice. The architecture is built to allow this as an additive layer without touching the deterministic core.

---

## 4. Agent-by-Agent Mechanism

### 4.1 Data Fetcher Agent

**File:** `agents/data_fetcher.py`

The only component that talks to the Groww API. Exchanges an API key and secret for an access token, then exposes three operations:

- **Historical candle retrieval** — auto-chunked across Groww's per-call date-range limits and re-assembled into one chronologically sorted DataFrame.
- **Combined live quote + depth + circuit-limit fetch.**
- **Instrument-symbol resolution.**

This agent performs no analysis — it is intentionally "dumb" I/O, which keeps the rest of the system broker-agnostic.

### 4.2 Technical Analysis Agent (with embedded Liquidity Filter)

**File:** `agents/technical_analysis.py`

Fully deterministic; the mathematical core of the system.

#### Liquidity Filter (runs first, can halt the whole pipeline)

| Check | Threshold | Rationale |
|-------|-----------|-----------|
| Average daily turnover (20d) | ≥ ₹5 crore | Below this, slippage risk on entry/exit is too high |
| ATR as % of price | 0.3% – 8.0% | Too low = no intraday range to trade; too high = erratic/gappy |
| Distance to nearest circuit limit | ≥ 1.5% | Avoids names already hugging a circuit band |

#### Trend & Bias Computation

Computes session VWAP (resets daily, never carries over from the prior close), a 20-period EMA, RSI(14), and MACD(12,26,9) on 5-minute intraday candles. A higher-timeframe (1-hour) trend is computed separately using a 20-period EMA with a **3-bar slope lookback** — short enough to react within a single ~6.25-hour NSE session (9:15 AM–3:30 PM) rather than effectively measuring "since this morning's open."

Bias is decided by a **3-way vote:**

- Price above VWAP
- Price above the 20 EMA
- An UP higher-timeframe trend

Two or more bullish votes with no greater bearish count → **BUY**; the mirror condition → **SHORT**; otherwise → **NEUTRAL**, which guarantees the trade is blocked downstream. RSI and MACD are computed and reported but are deliberately advisory — they annotate the bias with caution notes (e.g. overbought/oversold, histogram conflict) rather than independently triggering trades, which avoids over-firing on short-term oscillator noise.

Pivot points (classic floor-trader formula from the prior day's high/low/close), the last 20-bar swing high/low, and the opening 15-minute range are also computed here, feeding directly into the Executive Trader's price-level math.

### 4.3 Tape Reader Agent

**File:** `agents/tape_reader.py`

Computes bid/ask quantity imbalance across the visible top-5 depth levels, and a 1-minute volume-spike ratio against the trailing 20-bar average. Also flags when any single depth level holds quantity ≥ 5× the average level size, as a heuristic indicator of a large resting order.

> **Note:** This is explicitly documented in-code as a heuristic on a partial view of the book — Groww (like most retail Indian broker APIs) exposes only the top five price levels per side, not full Level-2 depth, so genuine institutional iceberg detection is out of scope.

### 4.4 Sentiment Analyst Agent

**File:** `agents/sentiment_analyst.py`

Queries the Marketaux news API filtered by ticker symbol and country (India), retrieving articles where the symbol was identified as a financial entity along with a pre-computed `sentiment_score` per entity. The agent:

- Averages these scores across all matching articles.
- Flags "breaking" if any single article carries a strongly polarised score.
- Reports a **confidence value** proportional to how many corroborating articles were found — a thinly covered small-cap will produce a low-confidence reading, which downstream logic treats as a weaker input rather than discarding it entirely.

### 4.5 Executive Trader Agent

**File:** `agents/executive_trader.py`

Consolidates the Technical, Tape, and Sentiment readings, and computes the actual trade plan.

#### Entry Logic

- **BUY entry:** a small buffer above the higher of (VWAP, recent swing low) — i.e. confirmation of a bounce off support, not a guess at the exact low.
- **SHORT entry:** a small buffer below the lower of (VWAP, recent swing high) — confirmation of rejection at resistance.

#### Stop-Loss Logic

The tighter (closer to entry) of two independent stops:

1. 1× the intraday ATR(14) computed on 5-minute candles.
2. Just beyond the recent swing structure.

Using the tighter of the two avoids placing a stop so wide that a single adverse print can absorb most of the allowed risk.

#### Target Logic

A baseline **1:2 risk:reward** extension from entry, refined upward (for BUY) or downward (for SHORT) toward the nearest pivot level (R1/S1) if that pivot sits beyond the baseline target — anchoring the target to an actual structural level rather than an arbitrary multiple.

#### Confirmation & Veto Logic

- **Tape agreement** (bid/ask imbalance pointing the same direction as the technical bias) adds to confidence but never flips the bias on its own.
- **Sentiment can veto a trade outright** — a strongly negative sentiment score (≤ −0.6) at sufficient confidence (≥ 0.3) blocks an otherwise-valid BUY, and the mirror condition blocks a SHORT — reflecting that fresh, strongly polarised news can invalidate a purely technical setup.

### 4.6 Risk Manager Agent — The Gatekeeper

**File:** `agents/risk_manager.py`

Runs last. Has **unconditional veto power**: if any check below fails, the trade is BLOCKED regardless of every other agent's confidence.

| Check | Rule | Runs |
|-------|------|------|
| Time of day | Block before 9:15 AM IST, at/after 2:45 PM IST, or after 3:30 PM IST | First — short-circuits all other checks |
| Risk : Reward | Must be ≥ 2 : 1 | Second |
| Distance to circuit | Entry must be ≥ 1.0% from the relevant circuit limit | Third |
| Target realism | Target must not be at or beyond the circuit limit | Third |

> **On the time-of-day check:** Most Indian brokers' risk-management systems begin auto-square-off of MIS (intraday) positions around 3:15–3:20 PM IST, often at a worse price than a trader's own stop loss and sometimes with a penalty fee. A signal approved at 3:14 PM could leave no real window to safely exit. This check uses the IANA `Asia/Kolkata` timezone explicitly via Python's `zoneinfo`, rather than trusting the host machine's local clock, so a misconfigured server timezone cannot silently disable the protection.

### 4.7 Pipeline Orchestrator

**File:** `core/pipeline.py`

A plain Python class, `IntradaySignalPipeline`, that calls the six agents above in fixed order and returns one `TradeSignal`. No dynamic branching, no LLM-driven control flow — the sequence is identical on every invocation, which is precisely why a heavier agent-orchestration framework was not used (see Section 2.2).

---

## 5. End-to-End Data Flow

A single run, in the order data actually moves through the system:

1. **User** (or `live_runner.py`) provides a stock symbol, e.g. `RELIANCE`.

2. **Data Fetcher** resolves the Groww symbol, then fetches:
   - ~60 days of daily candles
   - ~5 days of 5-minute candles
   - ~20 days of hourly candles
   - The most recent day of 1-minute candles (for volume-spike comparison)
   - One combined live-quote call returning price, depth, and circuit limits.

3. **Liquidity Filter** evaluates the daily candles and live price against the three thresholds in Section 4.2. If any fail, the pipeline returns a `NOT_VIABLE` signal immediately — no further API calls or computation occur.

4. **Technical Analysis Agent** computes VWAP/EMA/RSI/MACD on the 5-minute candles, the HTF trend on the hourly candles, and pivot/swing/opening-range levels from the daily and 5-minute candles, producing a `TechnicalReading` with a bias and strength score.

5. **Tape Reader Agent** computes imbalance and volume-spike readings from the live depth snapshot and the 1-minute volume series, producing a `TapeReading`.

6. **Sentiment Analyst Agent** calls Marketaux for the symbol, producing a `SentimentReading` with a score, confidence, and headline count.

7. **Executive Trader Agent** receives all three readings plus the liquidity check, decides the final bias, computes entry/stop-loss/target from market structure, and calls the Risk Manager with the proposed trade.

8. **Risk Manager Agent** runs its four checks in order (Section 4.6) and returns `APPROVED` or `BLOCKED` with explicit reasons.

9. The pipeline returns one `TradeSignal`: verdict, bias, entry, stop loss, target, risk:reward ratio, confidence score, and a list of plain-language rationale and/or blocking reasons. The user reviews this and, if approved, manually places the trade in the Groww app.

---

## 6. External APIs & Their Role

| API | Used For | Why Chosen |
|-----|----------|------------|
| **Groww Trading API** (`growwapi` SDK) | Historical OHLCV candles, live quote, market depth (top-5), and circuit limits | Direct API-key auth (no browser login flow); one call returns quote + depth + circuit limits together; symbols resolved directly without a separate token-lookup step |
| **Marketaux** (`api.marketaux.com`) | Per-ticker financial news with pre-computed sentiment scores | Real-time (unlike NewsAPI/NewsData.io free tiers, which delay results 12–24 hours); ticker-aware querying; sentiment scoring built in, removing the need for an LLM call |
| **Anthropic API** (optional) | Optional plain-English narration of Marketaux's sentiment findings | Never required for the pipeline to run; never used to compute a price or a bias |

> **No web scraping is used anywhere in the system.** Early design discussions considered scraping Moneycontrol, Economic Times, and Twitter/X directly; this was rejected because scraping rendered pages breaks on every markup change and very likely violates those sites' Terms of Service. Marketaux was selected specifically to avoid this class of fragility.

---

## 7. Safety, Compliance & Known Limitations

### 7.1 Regulatory Posture

The system is **signal-only by design**: it never calls an order-placement endpoint. Because a human reviews and manually executes every trade, the system sits outside SEBI's February 2025 algorithmic-trading framework, which applies specifically to systems that place orders without that human-in-the-loop step. Converting this system to auto-execution in the future would require registering the strategy with the broker and exchange first.

### 7.2 Known Limitations (stated plainly, not buried)

- **Top-5 depth only.** Neither Groww nor most retail Indian broker APIs expose full Level-2 order book data, so "large order detection" is a heuristic on a partial view, not a guarantee — hidden and iceberg orders are invisible to this system.

- **No backtest has been run yet.** The codebase has been verified for logical correctness (indicator math matches a reference library; the risk gate correctly blocks bad trades in unit tests) using synthetic data — this is not the same as demonstrated historical profitability. A backtest against real historical data is the recommended next step before committing real capital.

- **Marketaux coverage of India-listed small/mid-caps can be thin.** The agent's confidence score reflects this automatically, and the Executive Trader discounts low-confidence sentiment rather than treating silence as neutral conviction.

- **1-minute candle history** is limited to roughly the last 3 months per Groww's documented retention; daily candles extend back to 2020.

### 7.3 Testing

22 automated tests currently cover the two safety-critical surfaces of the system:

- The **Risk Manager's veto logic** (risk:reward thresholds, circuit-distance checks, and the full time-of-day square-off gate, including a test confirming the time gate short-circuits before any risk:reward math runs).
- The **Technical Analysis agent's higher-timeframe trend lookback**.

A synthetic end-to-end demo (`demo_synthetic.py`) exercises the full pipeline without requiring live API credentials.

---

## 8. Suggested Roadmap

1. **Backtest** the deterministic core (Technical Analysis + Risk Manager) against real historical candles for a basket of liquid NSE names, tracking win rate, achieved risk:reward, and maximum drawdown.

2. **Paper-trade** the approved signals for several weeks before committing real capital, to validate that live conditions match backtested assumptions.

3. **Optionally add an LLM narration layer** over Marketaux's sentiment output, strictly for human-readable explanation — never feeding back into price computation.

4. **Optionally extend to a basket-scan mode** that runs the pipeline across a configurable watchlist and surfaces only APPROVED signals, rather than checking one symbol at a time.

---

> *This document describes a decision-support tool, not financial advice. Intraday trading carries substantial risk of loss. Historical and structural patterns do not guarantee future results.*
