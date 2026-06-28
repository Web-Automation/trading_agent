"""
Orchestrator — wires the agents into the pipeline shown in the architecture
diagram: Data -> [Technical, Tape, Sentiment] -> Executive (+ Risk) -> Signal.

This intentionally has NO LLM orchestration framework (no CrewAI/LangGraph)
at this stage. The "multi-agent" structure here is just well-factored
Python classes — that's enough until you actually need an LLM to decide
dynamically which agent to call next, which this pipeline doesn't, since
the control flow is fixed and known in advance. Add CrewAI/LangGraph later
ONLY if you outgrow a fixed pipeline (e.g. needing the system to decide
when to re-fetch data, branch over multiple instruments adaptively, etc.).
"""
from __future__ import annotations
import pandas as pd

from agents.technical_analysis import LiquidityFilter, TechnicalAnalysisAgent, compute_atr
from agents.tape_reader import TapeReaderAgent
from agents.sentiment_analyst import SentimentAnalystAgent
from agents.executive_trader import ExecutiveTraderAgent
from core.models import MarketDepth, TradeSignal


class IntradaySignalPipeline:
    def __init__(self, marketaux_api_token: str | None = None, llm_client=None):
        self.liquidity_filter = LiquidityFilter()
        self.technical_agent = TechnicalAnalysisAgent()
        self.tape_agent = TapeReaderAgent()
        self.sentiment_agent = SentimentAnalystAgent(api_token=marketaux_api_token, llm_client=llm_client)
        self.executive_agent = ExecutiveTraderAgent()

    def run(
        self,
        symbol: str,
        company_name: str,
        daily_df: pd.DataFrame,
        intraday_df: pd.DataFrame,   # 5-min bars
        hourly_df: pd.DataFrame,
        depth: MarketDepth,
        recent_1min_volumes: pd.Series,
        lower_circuit: float,
        upper_circuit: float,
    ) -> TradeSignal:
        ltp = float(intraday_df["close"].iloc[-1])

        liquidity = self.liquidity_filter.check(
            symbol=symbol, daily_df=daily_df, ltp=ltp,
            lower_circuit=lower_circuit, upper_circuit=upper_circuit,
        )
        if not liquidity.viable:
            # Short-circuit: don't waste time/API calls on the other agents
            from core.models import TradeSignal as TS, Verdict, Bias
            from datetime import datetime
            return TS(
                symbol=symbol, timestamp=datetime.now(), verdict=Verdict.NOT_VIABLE,
                bias=Bias.NEUTRAL, entry_price=None, stop_loss=None, target_price=None,
                risk_reward_ratio=None, confidence=0.0, rationale=[],
                blocking_reasons=liquidity.rejection_reasons,
            )

        tech = self.technical_agent.analyze(
            symbol=symbol, intraday_df=intraday_df, hourly_df=hourly_df, daily_df=daily_df,
        )
        tape = self.tape_agent.analyze(symbol=symbol, depth=depth, recent_1min_volumes=recent_1min_volumes)
        sentiment = self.sentiment_agent.analyze(symbol=symbol, company_name=company_name)

        intraday_atr = float(compute_atr(intraday_df, period=14).iloc[-1])

        signal = self.executive_agent.decide(
            symbol=symbol, liquidity=liquidity, tech=tech, tape=tape, sentiment=sentiment,
            intraday_atr=intraday_atr, lower_circuit=lower_circuit, upper_circuit=upper_circuit,
        )
        return signal
