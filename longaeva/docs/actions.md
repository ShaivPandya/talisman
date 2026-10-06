# Illustrative actions

LON-26 / FR-13. LON-28's benchmark results and synthetic scoring conventions are
documented in [portfolio-evaluation.md](portfolio-evaluation.md). Real Visa
strategy scoring remains not run under the LON-6 data gate.

The action table turns one saved run's valuation into four labeled choices for a
demo long position: hold, add, trim, and exit. Hold is the no-action outcome.
Nothing here is a recommendation, a probability, or a market price.

Sizing and costs are adapted from Talisman's `portfolio/scenario_simulator.py`
(`_apply_delta`, `_traded_notional`, `_execution_friction`, lines 357–518).
See [`reuse-notes.md`](reuse-notes.md). The ADV cap, policy gate, ontology
writeback, and scenario P&L were not copied. Funding, when it is on, applies
only to added notional.

## Decision rule

The rule is [`config/decision_rule.yaml`](../config/decision_rule.yaml). A
request can change the share count and the reference price. It cannot change
the rule. The hash is SHA-256 of the parsed values (`content_hash` in
`longaeva_app.hashing`). Comments and whitespace are not part of it.

```
rule_hash = d93e2e052b7dbc75f00c4691e8afa464ac54c8d5a9bde602037767ec9dbd3039
```

`tests/test_valuation_actions.py` pins that digest as `EXPECTED_RULE_HASH`.
Editing the YAML fails the test until the pin and this line move together.
LON-28 must record this hash before a scoring run and assert it was frozen.

| Field | Value |
| --- | --- |
| Transaction / slippage / impact | 1 / 3 / 5 bps of traded notional, per side |
| Funding | 0 bps/day (off) |
| Exit / trim / add | margin ≤ −25% / ≤ −10% / ≥ +15%, inclusive |
| Add / trim size | 25% of current shares |
| Holding period | 63 trading days |
| Demo position | 1,000 shares, long |

Exit is tested before trim, so −25% is exit rather than trim. Between −10% and
+15% the decision is hold.

```
value_p50 = p50 forward EPS × mid multiple
margin = value_p50 / reference_price − 1
```

`value_p50` is the earnings-driven p50 from the LON-25 bridge (the mid
multiple). It is the same number as multiple-driven mid.

## Reference price

Visa daily closes are blocked (LON-6). The default price is the latest fiscal
period whose **Average Purchase Price per Share** filing was accepted at or
before the run cutoff. That is the same Item 2 / Item 5 table the trailing P/E
uses. At the 2024-07-23 origin (`2024-07-23T20:05:38Z`) the FY2024Q3 10-Q is
not yet accepted, so the price is FY2024Q2, 280.80.

Label, returned on the price:

> quarterly buyback average, not a market close

A request may pass `reference_price` instead. That source is `request_override`
and the label still says it is not a market close. No cutoff with a missing
filing invents a number: the decision is hold and the reason says so.

Because the price and the multiple come from the same buyback series, the
margin is not a discount to a market close. It asks whether forward EPS,
capitalized at the historical median trailing multiple, sits above or below
the latest buyback average.

## Sizing and costs

Shares stay non-negative.

| Action | Target shares | Traded notional |
| --- | --- | --- |
| hold | current shares | 0 |
| add | current × (1 + add fraction) | the increase × price |
| trim | max(0, current × (1 − trim fraction)) | the decrease × price |
| exit | 0 | current shares × price |

```
transaction = traded × transaction_cost_bps / 10_000
slippage    = traded × slippage_bps / 10_000
impact      = traded × market_impact_bps / 10_000
funding     = traded × funding_bps_per_day / 10_000 × holding_period_trading_days
```

Funding is added only for `add`. Trim and exit pay the other three costs and
zero funding. Hold pays nothing. With the committed rule, funding is zero for
every action.

Each row also has a net value gap at five points. Earnings-driven p10, p50,
and p90 hold the mid multiple. Multiple-driven low and high hold p50 EPS.
Multiple-driven mid is the same point as earnings-driven p50, so it is not
repeated.

```
net_gap = target_shares × (value_per_share − reference_price) − total_cost
```

The gap label is `Illustrative. Not a probability.` It is a mark against the
model value on the target position, not a forecast of trading profit and not
the outer envelope from the bridge.

## Unsupported

The response is HTTP 200 with `status: "unsupported"`, `decision: "hold"`, a
reason, and no margin, value, costs, or gaps. Target shares are still filled
from the position. A real reference price is still returned when one exists.
Nothing is filled in to make the rule fire.

| Condition | Reason |
| --- | --- |
| Bridge status is `unsupported` | The bridge reason (non-positive forward EPS, short history, bad assumptions, unordered multiple). |
| Bridge is ok but no repurchase price was accepted by the cutoff, and the request did not pass one | No reference price is invented. |

An unknown run is HTTP 404. A run that has not succeeded is HTTP 409. A
non-positive `shares` or `reference_price` is HTTP 422.

## API

| Method | Path |
| --- | --- |
| POST | `/valuation/actions` `{run_id, shares?, reference_price?, tax_rate?, net_interest_other?, diluted_shares?, multiple_range?}` |
| GET | `/valuation/decision-rule` |

`POST /valuation/actions` embeds the bridge response, so a caller does not need
a second request to see why the value was refused. `GET /valuation/decision-rule`
returns the config and `rule_hash` with no run.

## Handoffs

- **LON-28.** Read `rule_hash` and `holding_period_trading_days` from
  `GET /valuation/decision-rule` before scoring. Assert the hash matches the
  frozen value. Do not refit thresholds on the scored sample. Visa buy-and-hold
  stays not run until a daily price exists (LON-6).
- **LON-36.** The actions table calls `POST /valuation/actions` once per saved
  run. Show four rows, the cost components, the no-action row, and the
  illustrative label. If status is `unsupported`, show the reason and do not
  draw a gap. Keep the buyback-average label on the reference price.
