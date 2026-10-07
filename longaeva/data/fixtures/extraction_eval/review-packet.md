# LON-18: 10-label review packet

Please check each label against its quoted source. Reply `All 10 labels are correct`, or give corrections by label ID and field. This review is required before freezing the gold labels and capturing evaluation outputs.

Labels were prepared by an AI assistant. The reported human review coverage will be 10 labels, not the whole corpus.

Conventions: unstated geography/basis = null; percent is 8 for 8%; qualitative values = null. Source reporting period supplies context when commentary is undated. Apparent contradictions are kept with their period/scope distinctions. Census confidence-interval margins are not standalone activity facts.

## 1. visa-lag-01

Source: [visa, page 2](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm). Categories: numeric, period, contradiction.

> Payments volume for the three months ended March 31, 2024, on which fiscal third quarter service revenue is recognized, increased 8% over the prior year on a constant-dollar basis.

```json
{
  "statement_type": "measured",
  "activity_type": "payments_volume",
  "geography": null,
  "period_start": "2024-01-01",
  "period_end": "2024-03-31",
  "value": 8,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": "constant_currency"
}
```

Service-revenue recognition lag: this figure concerns Jan-Mar, although the release reports Apr-Jun.

## 2. visa-stable-01

Source: [visa, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm). Categories: qualitative.

> Growth in payments volume, cross-border volume and processed transactions remained relatively stable

```json
{
  "statement_type": "qualitative",
  "activity_type": "business_drivers",
  "geography": null,
  "period_start": "2024-04-01",
  "period_end": "2024-06-30",
  "value": null,
  "range_low": null,
  "range_high": null,
  "unit": "text",
  "basis": null
}
```

Relative stability is qualitative; there is no growth value in this passage.

## 3. booking-growth-03

Source: [booking, page 1](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm). Categories: numeric, scope, contradiction.

> Gross bookings grew 14% compared to the third quarter of 2024, or 10% on a constant currency basis.

```json
{
  "statement_type": "measured",
  "activity_type": "gross_bookings",
  "geography": null,
  "period_start": "2025-07-01",
  "period_end": "2025-09-30",
  "value": 10,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": "constant_currency"
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

## 4. booking-outlook-01

Source: [booking, page 3](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm). Categories: numeric, period, range, scope.

> Room Nights Growth 4% - 6% About 7%

```json
{
  "statement_type": "guidance",
  "activity_type": "room_nights",
  "geography": null,
  "period_start": "2025-10-01",
  "period_end": "2025-12-31",
  "value": null,
  "range_low": 4,
  "range_high": 6,
  "unit": "percent",
  "basis": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

## 5. census-june24-06

Source: [census, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf). Categories: numeric, contradiction, period.

> The April 2024 to May 2024 percent change was revised from up 0.1 percent (±0.4 percent)* to  up 0.3 percent (±0.2 percent).

```json
{
  "statement_type": "measured",
  "activity_type": "retail_food_services_sales_mom",
  "geography": "US",
  "period_start": "2024-05-01",
  "period_end": "2024-05-31",
  "value": 0.3,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": "revised_estimate"
}
```

Revision supersedes the prior estimate; both stated figures are retained with distinct estimate-status basis.

## 6. census-sectors-01

Source: [census, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf). Categories: numeric, geography, contradiction.

> Retail trade sales were down 0.1 percent (±0.5 percent)* from May 2024, but up 2.0 percent (±0.5  percent) above last year.

```json
{
  "statement_type": "measured",
  "activity_type": "retail_trade_sales_mom",
  "geography": "US",
  "period_start": "2024-06-01",
  "period_end": "2024-06-30",
  "value": -0.1,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

## 7. united-eps-03

Source: [united, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm). Categories: numeric, period, range.

> Q3 diluted earnings per share of $2.90; Q3 adjusted diluted earnings per share1 of $2.78, above the top end of guidance; Q4 adjusted diluted earnings per share guidance of $3.00 to $3.502

```json
{
  "statement_type": "guidance",
  "activity_type": "adjusted_diluted_eps",
  "geography": null,
  "period_start": "2025-10-01",
  "period_end": "2025-12-31",
  "value": null,
  "range_low": 3,
  "range_high": 3.5,
  "unit": "usd_per_share",
  "basis": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

## 8. paypal-transactions-01

Source: [paypal, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm). Categories: numeric, contradiction, scope.

> Payment transactions decreased 5% to 6.3 billion. Excluding payment service provider transactions4 (“PSP”), payment transactions increased 7%.

```json
{
  "statement_type": "measured",
  "activity_type": "payment_transactions",
  "geography": null,
  "period_start": "2025-07-01",
  "period_end": "2025-09-30",
  "value": -5,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

## 9. costco-comparables-01

Source: [costco, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm). Categories: numeric, geography, period, scope.

> U.S. | 5.1% | 6.0% | 6.2% | 7.3%

```json
{
  "statement_type": "measured",
  "activity_type": "comparable_sales",
  "geography": "US",
  "period_start": "2025-05-12",
  "period_end": "2025-08-31",
  "value": 5.1,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": null
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

## 10. costco-comparables-03

Source: [costco, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm). Categories: numeric, geography, period, scope.

> U.S. | 5.1% | 6.0% | 6.2% | 7.3%

```json
{
  "statement_type": "measured",
  "activity_type": "comparable_sales",
  "geography": "US",
  "period_start": "2024-09-02",
  "period_end": "2025-08-31",
  "value": 6.2,
  "range_low": null,
  "range_high": null,
  "unit": "percent",
  "basis": null
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.
