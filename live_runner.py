"""
Live runner — connects to REAL Groww API and runs one symbol through
the pipeline. This places NO orders; it only prints a signal for you to
act on manually (signal-only mode).

Setup:
1. cp .env fill in GROWW_API_KEY / GROWW_API_SECRET
   (get these from https://groww.in/trade-api/api-keys)
2. Run: python live_runner.py --symbol RELIANCE

Unlike Kite, there's no browser login/redirect step — Groww's API Key +
Secret flow exchanges directly for an access token in code. Note: this
flow needs daily re-approval per Groww's docs. If you want a token that
never expires, switch to the TOTP flow instead (see README.md).
"""
import argparse
import os
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv

from agents.data_fetcher import DataFetcherAgent
from core.pipeline import IntradaySignalPipeline

ENV_PATH = ".env"


def run_symbol(symbol: str, exchange: str = "NSE", segment: str = "CASH"):
    load_dotenv(ENV_PATH)
    api_key = os.environ["GROWW_API_KEY"]
    api_secret = os.environ["GROWW_API_SECRET"]

    fetcher = DataFetcherAgent(api_key=api_key, api_secret=api_secret)

    print(f"Fetching data for {symbol}...")
    daily_df = fetcher.fetch_historical(symbol, interval_minutes=1440, days_back=60, exchange=exchange, segment=segment)
    intraday_df = fetcher.fetch_historical(symbol, interval_minutes=5, days_back=5, exchange=exchange, segment=segment)
    hourly_df = fetcher.fetch_historical(symbol, interval_minutes=60, days_back=20, exchange=exchange, segment=segment)
    minute_df = fetcher.fetch_historical(symbol, interval_minutes=1, days_back=1, exchange=exchange, segment=segment)

    depth, lower_circuit, upper_circuit = fetcher.fetch_quote_circuit_and_depth(symbol, exchange=exchange, segment=segment)
    recent_1min_volumes = minute_df["volume"].tail(20)

    marketaux_api_token = os.environ.get("MARKETAUX_API_TOKEN")
    pipeline = IntradaySignalPipeline(marketaux_api_token=marketaux_api_token)

    signal = pipeline.run(
        symbol=symbol,
        company_name=symbol,  # replace with the actual company name for better news matching
        daily_df=daily_df,
        intraday_df=intraday_df,
        hourly_df=hourly_df,
        depth=depth,
        recent_1min_volumes=recent_1min_volumes,
        lower_circuit=lower_circuit,
        upper_circuit=upper_circuit,
    )

    print(f"\n{'='*60}\nSIGNAL: {symbol}\n{'='*60}")
    print(f"Verdict: {signal.verdict.value}")
    print(f"Bias: {signal.bias.value}")
    if signal.entry_price:
        print(f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | Target: {signal.target_price}")
        print(f"Risk:Reward: {signal.risk_reward_ratio} | Confidence: {signal.confidence}")
    for r in signal.rationale:
        print(f"  + {r}")
    for r in signal.blocking_reasons:
        print(f"  - BLOCKED: {r}")

    print(
        "\nThis is a signal only. No order has been placed. "
        "Verify independently before clicking buy/sell in Groww."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, required=True, help="NSE/BSE trading symbol, e.g. RELIANCE")
    parser.add_argument("--exchange", type=str, default="NSE")
    parser.add_argument("--segment", type=str, default="CASH")
    args = parser.parse_args()

    run_symbol(args.symbol, args.exchange, args.segment)
