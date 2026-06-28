"""
Sentiment Analyst Agent — Marketaux version.

Switched from NewsAPI + custom LLM scoring to Marketaux, which is
purpose-built for ticker-level financial sentiment: it resolves articles
to entities (symbol, exchange, country) and returns a sentiment_score
per entity directly, computed from the specific passages that mention
it (returned as `highlights`). This removes the need for an LLM call
to do sentiment scoring — the LLM's role here shrinks to optional
plain-English narration of what Marketaux already scored.

Why Marketaux over the original NewsAPI pick:
- Real-time (NewsAPI's free tier delays results ~24h; NewsData.io's
  free tier delays 12h — both are unusable for same-day intraday signals)
- Ticker-aware: query by `symbols=RELIANCE` directly, no separate
  "does this headline actually mention my stock" step needed
- Sentiment is pre-computed per entity, not per whole article — useful
  when one article discusses two companies positively/negatively
- Supports country filtering (`countries=in`) to bias toward Indian
  sources/context

Caveat: India-listed companies may have lower headline volume on
Marketaux than US large-caps (it indexes ~5,000 global sources, weighted
toward English-language coverage). For thinly-covered small/mid-caps,
expect `headline_count` to be low or zero — this is reflected in the
`confidence` field, which the Executive Trader agent already treats as
a dampener on how much weight to give the sentiment reading.

Free tier: 100 requests/day. For a tool that checks a handful of
symbols a few times during market hours, this is normally sufficient —
batch symbols into a single call (comma-separated) rather than calling
once per symbol to stretch the quota further.
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta

import requests

from core.models import SentimentReading


class SentimentAnalystAgent:
    NEWS_ENDPOINT = "https://api.marketaux.com/v1/news/all"

    def __init__(self, api_token: str | None = None, llm_client=None):
        self.api_token = api_token or os.environ.get("MARKETAUX_API_TOKEN")
        # llm_client is optional now — Marketaux already scores sentiment.
        # Kept only so you can plug in Claude/GPT for a plain-English
        # narration layer on top of Marketaux's highlights, if you want one.
        self.llm_client = llm_client

    def fetch_entity_news(
        self, symbol: str, hours_back: int = 12, country: str = "in", limit: int = 20
    ) -> list[dict]:
        """
        Fetch recent articles where `symbol` was identified as an entity,
        with per-entity sentiment already computed by Marketaux.
        """
        if not self.api_token:
            raise RuntimeError("MARKETAUX_API_TOKEN not set — sentiment agent cannot fetch news")

        published_after = (datetime.utcnow() - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%S")
        params = {
            "api_token": self.api_token,
            "symbols": symbol,
            "filter_entities": "true",   # only return entities matching our symbol, not every entity in the article
            "must_have_entities": "true",
            "countries": country,
            "language": "en",
            "published_after": published_after,
            "limit": limit,
        }
        resp = requests.get(self.NEWS_ENDPOINT, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def _aggregate(self, symbol: str, articles: list[dict]) -> tuple[float, str, bool, list[str]]:
        """
        Aggregate Marketaux's per-entity sentiment scores into a single
        reading. No LLM call needed for this — Marketaux already did
        the NLP scoring; this just averages it for the symbol.
        """
        if not articles:
            return 0.0, "No recent headlines found.", False, []

        scores = []
        sources = []
        for article in articles:
            for entity in article.get("entities", []):
                if entity.get("symbol", "").upper() != symbol.upper():
                    continue
                scores.append(entity.get("sentiment_score", 0.0))
                sources.append(article.get("source", "unknown"))

        if not scores:
            return 0.0, "No matching entity sentiment found.", False, []

        avg_score = sum(scores) / len(scores)
        # Flag "breaking" if any single article carries a strongly
        # polarized score, even if the average is muted by older/neutral articles
        breaking = any(abs(s) >= 0.6 for s in scores)

        if avg_score >= 0.3:
            tone = "predominantly positive"
        elif avg_score <= -0.3:
            tone = "predominantly negative"
        else:
            tone = "mixed/neutral"
        summary = f"{len(scores)} articles, {tone} sentiment (avg {avg_score:+.2f})"

        return avg_score, summary, breaking, sources[:5]

    def analyze(self, symbol: str, company_name: str | None = None, country: str = "in") -> SentimentReading:
        # company_name kept in the signature for interface compatibility
        # with the pipeline — Marketaux only needs the symbol itself.
        try:
            articles = self.fetch_entity_news(symbol, country=country)
        except Exception as e:
            return SentimentReading(
                symbol=symbol,
                timestamp=datetime.now(),
                score=0.0,
                confidence=0.0,
                headline_count=0,
                summary=f"News fetch failed: {e}",
                sources=[],
                has_breaking_news=False,
            )

        score, summary, breaking, sources = self._aggregate(symbol, articles)
        confidence = min(1.0, len(articles) / 8)  # more corroborating articles = more confidence

        return SentimentReading(
            symbol=symbol,
            timestamp=datetime.now(),
            score=score,
            confidence=confidence,
            headline_count=len(articles),
            summary=summary,
            sources=sources,
            has_breaking_news=breaking,
        )
