"""Local ticker and conversation signals shared by chat routing and context packs."""

from __future__ import annotations

import re
from typing import Any

_COMPANY_TICKER_ALIASES = {
    "meta": "META",
    "facebook": "META",
    "uber": "UBER",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "apple": "AAPL",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "microsoft": "MSFT",
    "netflix": "NFLX",
}
_TICKER_STOP_WORDS = frozenset(
    "AND THE FOR MY ALL HOW CAN ARE HAS DO WHAT THIS THAT HERE WITH FROM ABOUT "
    "WHEN WHERE WHY WHICH WILL WOULD COULD SHOULD PLEASE SHOW GIVE DOES DID NOT "
    "CPI GDP PPI PCE PMI ISM NFP FOMC FED ECB BOJ BOE IMF OECD OPEC USD EUR GBP "
    "JPY CNY CAD AUD CHF AI CEO CFO COO CTO EPS FCF PE ROE ROIC EBITDA YOY QOQ "
    "YTD CAGR IPO ETF ETFS SEC IRS US USA UK EU API ESG DCF WACC ROI TAM "
    "FY Q TD TTM PNL FAQ ASAP OK YES NO BUY SELL HOLD LONG SHORT ADD TRIM EXIT RISK".split()
)
_TICKER_RX = re.compile(r"(?<![\w$])(?:\$([A-Za-z]{1,5})\b|([A-Z]{2,5})\b)")
_COMPANY_RX = re.compile(
    r"\b(" + "|".join(sorted(_COMPANY_TICKER_ALIASES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_SCREEN_REFERENCE_RX = re.compile(
    r"\b(?:this|that|the|my|our)\s+(?:(?:displayed|current|on[- ]screen)\s+)?"
    r"(?:stock|company|position|thesis|dossier|idea|pitch)\b|"
    r"\b(?:on (?:the|my) screen|on this page|shown here)\b|"
    r"\b(?:about|of|on|pressure[- ]?test|review|evaluate|buy|sell|short|add)\s+"
    r"(?:it|here|(?:this|that)(?=\s*(?:[?.!]|$)))\b|"
    r"\b(?:is|was)\s+(?:it|this|that)\s+(?:a\s+)?(?:buy|short|long)\b|"
    r"\bits\s+(?:thesis|valuation|price|catalysts?|risks?)\b|\bdossier\s+pressure[- ]?test\b",
    re.IGNORECASE,
)
_FOLLOWUP_RX = re.compile(
    r"^\s*(?:and\b|also\b|what about\b|how about\b)|"
    r"^\s*(?:why(?: not)?|tell me more|go on|continue)[?!.\s]*$|"
    r"\b(?:shorter|short version|longer version|more detail)\b|"
    r"\bshould\s+i\s+(?:buy|sell|add|short)\s+(?:it|this|that|the\s+(?:first|second|third|last)\s+one)\b|"
    r"\b(?:explain|summari[sz]e|clarify|expand on|elaborate on|compare|rank|show|give me)\s+"
    r"(?:(?:that|this|those|these|it|them)\b|the\s+(?:first|second|third|other|same|last)\b)|"
    r"\byou\s+(?:just\s+)?(?:said|mentioned|listed|showed|found|recommended)\b",
    re.IGNORECASE,
)


def extract_tickers(user_text: str) -> list[str]:
    """Keep symbols and company aliases in mention order; cashtags disambiguate acronyms."""
    mentions = [
        (match.start(), (match[1] or match[2]).upper())
        for match in _TICKER_RX.finditer(user_text or "")
        if match[1] or match[2] not in _TICKER_STOP_WORDS
    ]
    mentions.extend(
        (match.start(), _COMPANY_TICKER_ALIASES[match[0].lower()]) for match in _COMPANY_RX.finditer(user_text or "")
    )
    return list(dict.fromkeys(ticker for _offset, ticker in sorted(mentions)))


def extract_candidate_ticker(user_text: str, screen_context: dict[str, Any] | None = None) -> str | None:
    tickers = extract_tickers(user_text)
    if tickers:
        return tickers[0]
    if screen_context and _SCREEN_REFERENCE_RX.search(user_text or ""):
        ticker = str(screen_context.get("ticker") or "").strip().upper()
        return ticker or None
    return None


def previous_turn(recent_conversation: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Use the latest completed exchange, ignoring a retried/current turn's placeholder."""
    messages = recent_conversation or []
    for index in range(len(messages) - 1, -1, -1):
        assistant = messages[index]
        if (
            assistant.get("role") != "assistant"
            or assistant.get("is_streaming")
            or assistant.get("status") in {"failed", "stopped", "canceled"}
            or not assistant.get("content")
        ):
            continue
        for user in reversed(messages[:index]):
            if user.get("role") == "user":
                return [user, assistant]
    return []


def is_contextual_followup(user_text: str, recent_conversation: list[dict[str, Any]] | None) -> bool:
    return bool(previous_turn(recent_conversation) and _FOLLOWUP_RX.search(user_text or ""))
