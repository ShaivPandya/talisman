# Agent reply costs

Completed Stan replies show a small USD estimate in the bottom-right corner. Hover or focus the amount for input/output token counts, cached input tokens, and the number of model calls. The server saves the estimate with the message, so History, reloads, and regenerated answer versions retain their own costs.

The estimate sums the recorded chat model calls, including discovery, structured passes, synthesis, and retries with reported usage. Each call uses its own model and cache read/write rates. It excludes fees incurred inside tools, background jobs (such as follow-up suggestions and summaries), regional premiums, and negotiated discounts. It is an estimate of model usage, not an invoice total.

Replies produced without model calls show $0.00. Unknown/custom model pricing or absent token usage shows “Cost unavailable”; a partially priced turn shows an amount followed by `+`. Older messages without cost metadata have no badge.

Rates live in `api/agent_costs.py` and were verified on October 29, 2026 against [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), and [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing). The Gemini Argon introductory-rate expiry is applied when calculating new replies. Saved estimates are never repriced.
