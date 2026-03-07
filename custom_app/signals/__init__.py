"""Signal infrastructure — news, funding rate, LLM sentiment gate."""

from custom_app.signals.funding_rate import FundingRateGate, FundingRateError
from custom_app.signals.llm_sentiment import LLMSentimentGate, SentimentResult, SentimentUnavailable
from custom_app.signals.news_fetcher import NewsFetcher

__all__ = [
    "FundingRateGate",
    "FundingRateError",
    "LLMSentimentGate",
    "SentimentResult",
    "SentimentUnavailable",
    "NewsFetcher",
]
