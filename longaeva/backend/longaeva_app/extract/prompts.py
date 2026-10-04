"""Passage-only extraction prompt (LON-16 / C29).

The user message carries one passage. It does not include other passages,
publication timestamps, or anything the model would have to know from outside
the selection.
"""

from __future__ import annotations

PROMPT_VERSION = "lon16-v1"

SYSTEM_PROMPT = """You extract structured observations from one supplied passage.
Rules:
- Use only the passage text. Do not use outside knowledge, other documents, or dates you were not given.
- Quote a verbatim substring of the passage that states the observation. When there is a number, the quote must contain that number.
- If the passage states nothing about results, outlook, or a qualitative business condition, return an empty observations list.
- Do not add confidence scores, probabilities, or fields that are not in the schema.
- statement_type is measured for a reported result, guidance for a company outlook or range, or qualitative when no number is stated.
- Qualitative observations must not include value, range_low, or range_high. Set unit to text.
- Measured and guidance observations need value or range_low and range_high.
- Percent values are the number as stated (8 for "8%"), not a fraction. Set unit to percent.
- activity_type is a short snake_case label such as room_nights or gross_travel_bookings.
- basis is units, as_reported, or constant_currency only when the passage says so.
- period_start and period_end are ISO dates (YYYY-MM-DD) for the period the statement is about.
"""


def user_message(
    *,
    company: str,
    doc_type: str,
    passage: str,
    period_label: str | None = None,
) -> str:
    """Build the only user turn. ``passage`` is the sole evidence text."""
    lines = [
        f"Company: {company}",
        f"Document type: {doc_type}",
    ]
    if period_label:
        lines.append(f"Reporting period: {period_label}")
    lines.append("Passage:")
    lines.append(passage)
    return "\n".join(lines)
