# Extraction error sample (LON-18)

Provider: openai / gpt-5.4; prompt: lon16-v1.
Review: reviewed; 10 of 85 labels reviewed by the user.
Passages: 18 succeeded, 1 failed, 0 missing of 19.
Labels: 23 exact matches, 71 matched, 80 scorable; 5 unavailable, 0 disputed.

## Overall

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 9 | 80 | 11.2% |
| unsupported | 3 | 74 | 4.1% |
| duplicate | 0 | 74 | 0.0% |
| invalid_quote | 0 | 74 | 0.0% |
| value_range | 2 | 71 | 2.8% |
| statement_type | 1 | 71 | 1.4% |
| activity_scope | 32 | 71 | 45.1% |
| unit_basis | 30 | 71 | 42.3% |
| period | 4 | 71 | 5.6% |
| geography | 26 | 71 | 36.6% |

## Family: airline

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 0 | 5 | 0.0% |
| unsupported | 0 | 5 | 0.0% |
| duplicate | 0 | 5 | 0.0% |
| invalid_quote | 0 | 5 | 0.0% |
| value_range | 0 | 5 | 0.0% |
| statement_type | 0 | 5 | 0.0% |
| activity_scope | 2 | 5 | 40.0% |
| unit_basis | 3 | 5 | 60.0% |
| period | 0 | 5 | 0.0% |
| geography | 0 | 5 | 0.0% |

## Family: booking

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 1 | 13 | 7.7% |
| unsupported | 0 | 12 | 0.0% |
| duplicate | 0 | 12 | 0.0% |
| invalid_quote | 0 | 12 | 0.0% |
| value_range | 1 | 12 | 8.3% |
| statement_type | 0 | 12 | 0.0% |
| activity_scope | 0 | 12 | 0.0% |
| unit_basis | 2 | 12 | 16.7% |
| period | 0 | 12 | 0.0% |
| geography | 0 | 12 | 0.0% |

## Family: census

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 1 | 15 | 6.7% |
| unsupported | 0 | 14 | 0.0% |
| duplicate | 0 | 14 | 0.0% |
| invalid_quote | 0 | 14 | 0.0% |
| value_range | 1 | 14 | 7.1% |
| statement_type | 1 | 14 | 7.1% |
| activity_scope | 14 | 14 | 100.0% |
| unit_basis | 10 | 14 | 71.4% |
| period | 2 | 14 | 14.3% |
| geography | 14 | 14 | 100.0% |

## Family: processor

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 3 | 10 | 30.0% |
| unsupported | 1 | 8 | 12.5% |
| duplicate | 0 | 8 | 0.0% |
| invalid_quote | 0 | 8 | 0.0% |
| value_range | 0 | 7 | 0.0% |
| statement_type | 0 | 7 | 0.0% |
| activity_scope | 1 | 7 | 14.3% |
| unit_basis | 2 | 7 | 28.6% |
| period | 0 | 7 | 0.0% |
| geography | 0 | 7 | 0.0% |

## Family: retailer

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 4 | 26 | 15.4% |
| unsupported | 0 | 22 | 0.0% |
| duplicate | 0 | 22 | 0.0% |
| invalid_quote | 0 | 22 | 0.0% |
| value_range | 0 | 22 | 0.0% |
| statement_type | 0 | 22 | 0.0% |
| activity_scope | 12 | 22 | 54.5% |
| unit_basis | 10 | 22 | 45.5% |
| period | 2 | 22 | 9.1% |
| geography | 12 | 22 | 54.5% |

## Family: visa

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 0 | 11 | 0.0% |
| unsupported | 2 | 13 | 15.4% |
| duplicate | 0 | 13 | 0.0% |
| invalid_quote | 0 | 13 | 0.0% |
| value_range | 0 | 11 | 0.0% |
| statement_type | 0 | 11 | 0.0% |
| activity_scope | 3 | 11 | 27.3% |
| unit_basis | 3 | 11 | 27.3% |
| period | 0 | 11 | 0.0% |
| geography | 0 | 11 | 0.0% |

## Category: contradiction

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 1 | 15 | 6.7% |
| unsupported | 0 | 30 | 0.0% |
| duplicate | 0 | 30 | 0.0% |
| invalid_quote | 0 | 30 | 0.0% |
| value_range | 0 | 14 | 0.0% |
| statement_type | 0 | 14 | 0.0% |
| activity_scope | 5 | 14 | 35.7% |
| unit_basis | 4 | 14 | 28.6% |
| period | 2 | 14 | 14.3% |
| geography | 4 | 14 | 28.6% |

## Category: geography

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 0 | 29 | 0.0% |
| unsupported | 0 | 40 | 0.0% |
| duplicate | 0 | 40 | 0.0% |
| invalid_quote | 0 | 40 | 0.0% |
| value_range | 1 | 29 | 3.4% |
| statement_type | 1 | 29 | 3.4% |
| activity_scope | 20 | 29 | 69.0% |
| unit_basis | 16 | 29 | 55.2% |
| period | 0 | 29 | 0.0% |
| geography | 20 | 29 | 69.0% |

## Category: numeric

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 7 | 74 | 9.5% |
| unsupported | 0 | 67 | 0.0% |
| duplicate | 0 | 67 | 0.0% |
| invalid_quote | 0 | 67 | 0.0% |
| value_range | 2 | 67 | 3.0% |
| statement_type | 1 | 67 | 1.5% |
| activity_scope | 29 | 67 | 43.3% |
| unit_basis | 30 | 67 | 44.8% |
| period | 4 | 67 | 6.0% |
| geography | 26 | 67 | 38.8% |

## Category: period

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 5 | 47 | 10.6% |
| unsupported | 0 | 58 | 0.0% |
| duplicate | 0 | 58 | 0.0% |
| invalid_quote | 0 | 58 | 0.0% |
| value_range | 1 | 42 | 2.4% |
| statement_type | 0 | 42 | 0.0% |
| activity_scope | 19 | 42 | 45.2% |
| unit_basis | 16 | 42 | 38.1% |
| period | 4 | 42 | 9.5% |
| geography | 16 | 42 | 38.1% |

## Category: qualitative

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 2 | 6 | 33.3% |
| unsupported | 3 | 7 | 42.9% |
| duplicate | 0 | 7 | 0.0% |
| invalid_quote | 0 | 7 | 0.0% |
| value_range | 0 | 4 | 0.0% |
| statement_type | 0 | 4 | 0.0% |
| activity_scope | 3 | 4 | 75.0% |
| unit_basis | 0 | 4 | 0.0% |
| period | 0 | 4 | 0.0% |
| geography | 0 | 4 | 0.0% |

## Category: range

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 0 | 7 | 0.0% |
| unsupported | 0 | 9 | 0.0% |
| duplicate | 0 | 9 | 0.0% |
| invalid_quote | 0 | 9 | 0.0% |
| value_range | 1 | 7 | 14.3% |
| statement_type | 0 | 7 | 0.0% |
| activity_scope | 0 | 7 | 0.0% |
| unit_basis | 1 | 7 | 14.3% |
| period | 0 | 7 | 0.0% |
| geography | 0 | 7 | 0.0% |

## Category: scope

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 1 | 45 | 2.2% |
| unsupported | 0 | 52 | 0.0% |
| duplicate | 0 | 52 | 0.0% |
| invalid_quote | 0 | 52 | 0.0% |
| value_range | 1 | 44 | 2.3% |
| statement_type | 0 | 44 | 0.0% |
| activity_scope | 14 | 44 | 31.8% |
| unit_basis | 17 | 44 | 38.6% |
| period | 0 | 44 | 0.0% |
| geography | 14 | 44 | 31.8% |

## Category: unit

| Error | Count | Denominator | Rate |
| --- | ---: | ---: | ---: |
| omission | 6 | 23 | 26.1% |
| unsupported | 0 | 32 | 0.0% |
| duplicate | 0 | 32 | 0.0% |
| invalid_quote | 0 | 32 | 0.0% |
| value_range | 1 | 17 | 5.9% |
| statement_type | 1 | 17 | 5.9% |
| activity_scope | 8 | 17 | 47.1% |
| unit_basis | 13 | 17 | 76.5% |
| period | 0 | 17 | 0.0% |
| geography | 6 | 17 | 35.3% |

## Call failures and missing outputs

- united-revenue-mix: invalid_response — Response did not match the extraction schema

## Disagreements

### visa-income-01: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "gaap_net_income",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 4.9,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "GAAP net income of $4.9B or $2.40 per share"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "gaap_net_income",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 4.9,
    "range_low": null,
    "range_high": null,
    "unit": "$B",
    "basis": null,
    "quote": "GAAP net income of $4.9B"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### visa-income-03: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "non_gaap_net_income",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 4.9,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "non-GAAP net income of $4.9B or $2.42 per share"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "non_gaap_net_income",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 4.9,
    "range_low": null,
    "range_high": null,
    "unit": "$B",
    "basis": null,
    "quote": "non-GAAP net income of $4.9B"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### visa-lag-05: activity_scope, unit_basis

[Original source, page 2](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "processed_transactions",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 59.3,
    "range_low": null,
    "range_high": null,
    "unit": "billions",
    "basis": null,
    "quote": "Total processed transactions, which represent transactions processed by Visa, for the three months ended June 30, 2024, were 59.3 billion, a 10% increase over the prior year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "total_processed_transactions",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 59.3,
    "range_low": null,
    "range_high": null,
    "unit": "billion",
    "basis": null,
    "quote": "Total processed transactions, which represent transactions processed by Visa, for the three months ended June 30, 2024, were 59.3 billion, a 10% increase over the prior year."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### visa-lag-06: activity_scope

[Original source, page 2](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "processed_transactions",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 10.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total processed transactions, which represent transactions processed by Visa, for the three months ended June 30, 2024, were 59.3 billion, a 10% increase over the prior year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "total_processed_transactions",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 10.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total processed transactions, which represent transactions processed by Visa, for the three months ended June 30, 2024, were 59.3 billion, a 10% increase over the prior year."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### visa-stable-01: activity_scope

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "qualitative",
    "activity_type": "business_drivers",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growth in payments volume, cross-border volume and processed transactions remained relatively stable"
  },
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "payments_volume_growth",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growth in payments volume, cross-border volume and processed transactions remained relatively stable"
  }
}
```

Relative stability is qualitative; there is no growth value in this passage.

### visa-stable: unsupported

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": null,
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "cross_border_volume_growth",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growth in payments volume, cross-border volume and processed transactions remained relatively stable"
  }
}
```

Unmatched original prediction.

### visa-stable: unsupported

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1403161/000140316124000040/q32024earningsrelease.htm)

```json
{
  "expected": null,
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "processed_transactions_growth",
    "geography": null,
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growth in payments volume, cross-border volume and processed transactions remained relatively stable"
  }
}
```

Unmatched original prediction.

### booking-growth-02: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "gross_bookings",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 14.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Gross bookings grew 14% compared to the third quarter of 2024, or 10% on a constant currency basis."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "gross_bookings",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 14.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "as_reported",
    "quote": "Gross bookings grew 14% compared to the third quarter of 2024"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### booking-growth-04: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "revenue",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 13.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Revenue grew 13% compared to the third quarter of 2024, or 8% on a constant currency basis."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "revenue",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 13.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "as_reported",
    "quote": "Revenue grew 13% compared to the third quarter of 2024"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### booking-outlook-02: value_range

[Original source, page 3](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "guidance",
    "activity_type": "room_nights",
    "geography": null,
    "period_start": "2025-01-01",
    "period_end": "2025-12-31",
    "value": 7.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Room Nights Growth 4% - 6% About 7%"
  },
  "actual": {
    "statement_type": "guidance",
    "activity_type": "room_nights",
    "geography": null,
    "period_start": "2025-01-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": 7.0,
    "range_high": 7.0,
    "unit": "percent",
    "basis": null,
    "quote": "Q4 2025 FY 2025 Room Nights Growth 4% - 6% About 7%"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### booking-demand-01: omission

[Original source, page 3](https://www.sec.gov/Archives/edgar/data/1075531/000107553125000050/q3-25bkngearningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "qualitative",
    "activity_type": "macro_geopolitical_conditions",
    "geography": null,
    "period_start": "2025-10-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "While there remains some uncertainty in the macroeconomic and geopolitical backdrop"
  },
  "actual": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-june24-01: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 704.3,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2024, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $704.3 billion, virtually unchanged \n(±0.5 percent)* from the previous month, but up 2.3 percent (±0.5 percent) above June 2023."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 704.3,
    "range_low": null,
    "range_high": null,
    "unit": "billion USD",
    "basis": null,
    "quote": "Advance estimates of U.S. retail and food services sales for June 2024, adjusted for seasonal variation and holiday and trading-day differences, but not for price changes, were $704.3 billion"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june24-02: value_range, statement_type, activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_mom",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 0.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2024, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $704.3 billion, virtually unchanged \n(±0.5 percent)* from the previous month, but up 2.3 percent (±0.5 percent) above June 2023."
  },
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "virtually unchanged (±0.5 percent)* from the previous month"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june24-03: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_yoy",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 2.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2024, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $704.3 billion, virtually unchanged \n(±0.5 percent)* from the previous month, but up 2.3 percent (±0.5 percent) above June 2023."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 2.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "up 2.3 percent (±0.5 percent) above June 2023"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june24-04: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_yoy",
    "geography": "US",
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 2.5,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Total sales \nfor the April 2024 through June 2024 period were up 2.5 percent (±0.5 percent) from the same period a \nyear ago."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2024-04-01",
    "period_end": "2024-06-30",
    "value": 2.5,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total sales for the April 2024 through June 2024 period were up 2.5 percent (±0.5 percent) from the same period a year ago."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-june24-05: omission

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_mom",
    "geography": "US",
    "period_start": "2024-05-01",
    "period_end": "2024-05-31",
    "value": 0.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "previous_estimate",
    "quote": "The April 2024 to May 2024 percent change was revised from up 0.1 percent (±0.4 percent)* to \nup 0.3 percent (±0.2 percent)."
  },
  "actual": null
}
```

Revision supersedes the prior estimate; both stated figures are retained with distinct estimate-status basis.

### census-june24-06: activity_scope, unit_basis, period, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_mom",
    "geography": "US",
    "period_start": "2024-05-01",
    "period_end": "2024-05-31",
    "value": 0.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "revised_estimate",
    "quote": "The April 2024 to May 2024 percent change was revised from up 0.1 percent (±0.4 percent)* to \nup 0.3 percent (±0.2 percent)."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2024-04-01",
    "period_end": "2024-05-31",
    "value": 0.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "The April 2024 to May 2024 percent change was revised from up 0.1 percent (±0.4 percent)* to up 0.3 percent (±0.2 percent)."
  }
}
```

Revision supersedes the prior estimate; both stated figures are retained with distinct estimate-status basis.

### census-june25-01: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2506.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales",
    "geography": "US",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 720.1,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2025, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $720.1 billion, up 0.6 percent (±0.5 \npercent) from the previous month, and up 3.9 percent (±0.5 percent) from June 2024."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 720.1,
    "range_low": null,
    "range_high": null,
    "unit": "billion_usd",
    "basis": null,
    "quote": "Advance estimates of U.S. retail and food services sales for June 2025, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $720.1 billion"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june25-02: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2506.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_mom",
    "geography": "US",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 0.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2025, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $720.1 billion, up 0.6 percent (±0.5 \npercent) from the previous month, and up 3.9 percent (±0.5 percent) from June 2024."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 0.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "up 0.6 percent (±0.5 \npercent) from the previous month"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june25-03: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2506.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_yoy",
    "geography": "US",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 3.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Advance estimates of U.S. retail and food services sales for June 2025, adjusted for seasonal variation and \nholiday and trading-day differences, but not for price changes, were $720.1 billion, up 0.6 percent (±0.5 \npercent) from the previous month, and up 3.9 percent (±0.5 percent) from June 2024."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2025-06-01",
    "period_end": "2025-06-30",
    "value": 3.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "up 3.9 percent (±0.5 percent) from June 2024"
  }
}
```

Headline point estimate; confidence-interval margins are uncertainty, not additional business observations.

### census-june25-04: activity_scope, unit_basis, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2506.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_yoy",
    "geography": "US",
    "period_start": "2025-04-01",
    "period_end": "2025-06-30",
    "value": 4.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "Total sales for the \nApril 2025 through June 2025 period were up 4.1 percent (±0.4 percent) from the same period a year ago."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2025-04-01",
    "period_end": "2025-06-30",
    "value": 4.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total sales for the \nApril 2025 through June 2025 period were up 4.1 percent (±0.4 percent) from the same period a year ago."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-june25-05: activity_scope, unit_basis, period, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2506.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_food_services_sales_mom",
    "geography": "US",
    "period_start": "2025-05-01",
    "period_end": "2025-05-31",
    "value": -0.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "seasonally_adjusted",
    "quote": "The April 2025 to May 2025 percent change was unrevised from down 0.9 percent (±0.2 percent)."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_and_food_services_sales",
    "geography": "U.S.",
    "period_start": "2025-04-01",
    "period_end": "2025-05-31",
    "value": -0.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "The April 2025 to May 2025 percent change was unrevised from down 0.9 percent (±0.2 percent)."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-sectors-01: activity_scope, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_trade_sales_mom",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": -0.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Retail trade sales were down 0.1 percent (±0.5 percent)* from May 2024, but up 2.0 percent (±0.5 \npercent) above last year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_trade_sales",
    "geography": null,
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": -0.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Retail trade sales were down 0.1 percent (±0.5 percent)* from May 2024"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-sectors-02: activity_scope, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "retail_trade_sales_yoy",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 2.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Retail trade sales were down 0.1 percent (±0.5 percent)* from May 2024, but up 2.0 percent (±0.5 \npercent) above last year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "retail_trade_sales",
    "geography": null,
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 2.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "but up 2.0 percent (±0.5 \npercent) above last year"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-sectors-03: activity_scope, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "nonstore_retail_sales_yoy",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 8.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Nonstore retailers were up 8.9 percent (±1.4 percent) from last year, while food \nservices and drinking places were up 4.4 percent (±2.1 percent) from June 2023."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "nonstore_retailers_sales",
    "geography": null,
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 8.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Nonstore retailers were up 8.9 percent (±1.4 percent) from last year"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### census-sectors-04: activity_scope, geography

[Original source, page 1](https://www2.census.gov/retail/releases/historical/marts/adv2406.pdf)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "food_services_sales_yoy",
    "geography": "US",
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 4.4,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Nonstore retailers were up 8.9 percent (±1.4 percent) from last year, while food \nservices and drinking places were up 4.4 percent (±2.1 percent) from June 2023."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "food_services_and_drinking_places_sales",
    "geography": null,
    "period_start": "2024-06-01",
    "period_end": "2024-06-30",
    "value": 4.4,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "food \nservices and drinking places were up 4.4 percent (±2.1 percent) from June 2023"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### united-eps-01: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "gaap_diluted_eps",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 2.9,
    "range_low": null,
    "range_high": null,
    "unit": "usd_per_share",
    "basis": null,
    "quote": "Q3 diluted earnings per share of $2.90; Q3 adjusted diluted earnings per share1 of $2.78, above the top end of guidance; Q4 adjusted diluted earnings per share guidance of $3.00 to $3.502"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "diluted_eps",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 2.9,
    "range_low": null,
    "range_high": null,
    "unit": "USD/share",
    "basis": null,
    "quote": "Q3 diluted earnings per share of $2.90"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### united-eps-02: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "adjusted_diluted_eps",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 2.78,
    "range_low": null,
    "range_high": null,
    "unit": "usd_per_share",
    "basis": null,
    "quote": "Q3 diluted earnings per share of $2.90; Q3 adjusted diluted earnings per share1 of $2.78, above the top end of guidance; Q4 adjusted diluted earnings per share guidance of $3.00 to $3.502"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "adjusted_diluted_eps",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 2.78,
    "range_low": null,
    "range_high": null,
    "unit": "USD/share",
    "basis": null,
    "quote": "Q3 adjusted diluted earnings per share1 of $2.78, above the top end of guidance"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### united-eps-03: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm)

```json
{
  "expected": {
    "statement_type": "guidance",
    "activity_type": "adjusted_diluted_eps",
    "geography": null,
    "period_start": "2025-10-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": 3.0,
    "range_high": 3.5,
    "unit": "usd_per_share",
    "basis": null,
    "quote": "Q3 diluted earnings per share of $2.90; Q3 adjusted diluted earnings per share1 of $2.78, above the top end of guidance; Q4 adjusted diluted earnings per share guidance of $3.00 to $3.502"
  },
  "actual": {
    "statement_type": "guidance",
    "activity_type": "adjusted_diluted_eps",
    "geography": null,
    "period_start": "2025-10-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": 3.0,
    "range_high": 3.5,
    "unit": "USD/share",
    "basis": null,
    "quote": "Q4 adjusted diluted earnings per share guidance of $3.00 to $3.50"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### united-demand-01: activity_scope

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm)

```json
{
  "expected": {
    "statement_type": "qualitative",
    "activity_type": "brand_loyal_customers",
    "geography": null,
    "period_start": "2025-01-01",
    "period_end": "2025-09-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growing base of brand-loyal customers boosted resilience through macro volatility during the first three quarters of the year"
  },
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "customer_loyalty_resilience",
    "geography": null,
    "period_start": "2025-01-01",
    "period_end": "2025-09-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "Growing base of brand-loyal customers boosted resilience through macro volatility during the first three quarters of the year"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### united-demand-02: activity_scope

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/100517/000010051725000190/ual_09302025erex991.htm)

```json
{
  "expected": {
    "statement_type": "qualitative",
    "activity_type": "demand_outlook",
    "geography": null,
    "period_start": "2025-10-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "is poised to fuel a strong Q4 as the demand environment strengthens with an expected meaningful improvement in unit revenue year-over-year compared to Q3"
  },
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "unit_revenue",
    "geography": null,
    "period_start": "2025-10-01",
    "period_end": "2025-12-31",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "is poised to fuel a strong Q4 as the demand environment strengthens with an expected meaningful improvement in unit revenue year-over-year compared to Q3"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-revenue-01: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_revenue",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 7.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Net revenues increased 7% to $8.4 billion; 6% currency-neutral (“FXN”)."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "net_revenues",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 7.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "as_reported",
    "quote": "Net revenues increased 7% to $8.4 billion"
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-revenue-02: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_revenue",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 8.4,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "Net revenues increased 7% to $8.4 billion; 6% currency-neutral (“FXN”)."
  },
  "actual": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-transactions-02: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "payment_transactions",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": 6.3,
    "range_low": null,
    "range_high": null,
    "unit": "billions",
    "basis": null,
    "quote": "Payment transactions decreased 5% to 6.3 billion. Excluding payment service provider transactions4 (“PSP”), payment transactions increased 7%."
  },
  "actual": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-tpa-02: unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "transactions_per_active_account",
    "geography": null,
    "period_start": "2024-10-01",
    "period_end": "2025-09-30",
    "value": 57.6,
    "range_low": null,
    "range_high": null,
    "unit": "transactions_per_account",
    "basis": null,
    "quote": "Payment transactions per active account (“TPA”) on a trailing 12-month basis decreased 6% to 57.6. TPA ex-PSP4 increased 5%."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "payment_transactions_per_active_account",
    "geography": null,
    "period_start": "2024-10-01",
    "period_end": "2025-09-30",
    "value": 57.6,
    "range_low": null,
    "range_high": null,
    "unit": "transactions_per_active_account",
    "basis": "units",
    "quote": "Payment transactions per active account (“TPA”) on a trailing 12-month basis decreased 6% to 57.6."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-tpa-03: activity_scope

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "transactions_per_active_account_ex_psp",
    "geography": null,
    "period_start": "2024-10-01",
    "period_end": "2025-09-30",
    "value": 5.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Payment transactions per active account (“TPA”) on a trailing 12-month basis decreased 6% to 57.6. TPA ex-PSP4 increased 5%."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "payment_transactions_per_active_account_ex_psp4",
    "geography": null,
    "period_start": "2024-10-01",
    "period_end": "2025-09-30",
    "value": 5.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "TPA ex-PSP4 increased 5%."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### paypal-position-01: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": {
    "statement_type": "qualitative",
    "activity_type": "competitive_position",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "This is a stronger company today than we were two years ago. With differentiated competitive advantages, clear strategic direction and building execution momentum, we believe we are exceptionally well-placed to win into the future.”"
  },
  "actual": null
}
```

One qualitative claim about competitive position; no measured growth rate is stated. Source reporting period is the default for undated present-tense commentary.

### paypal-position: unsupported

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/1633917/000163391725000194/pypl3q-25earningsrelease.htm)

```json
{
  "expected": null,
  "actual": {
    "statement_type": "qualitative",
    "activity_type": "business_positioning",
    "geography": null,
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "value": null,
    "range_low": null,
    "range_high": null,
    "unit": "text",
    "basis": null,
    "quote": "This is a stronger company today than we were two years ago. With differentiated competitive advantages, clear strategic direction and building execution momentum, we believe we are exceptionally well-placed to win into the future."
  }
}
```

Unmatched original prediction.

### costco-sales-01: period

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 8.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Net sales for the quarter increased 8.0 percent, to $84.4 billion, from $78.2 billion last year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2025-06-01",
    "period_end": "2025-08-31",
    "value": 8.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Net sales for the quarter increased 8.0 percent, to $84.4 billion, from $78.2 billion last year."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### costco-sales-02: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 84.4,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "Net sales for the quarter increased 8.0 percent, to $84.4 billion, from $78.2 billion last year."
  },
  "actual": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### costco-sales-03: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2024-05-13",
    "period_end": "2024-09-01",
    "value": 78.2,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "Net sales for the quarter increased 8.0 percent, to $84.4 billion, from $78.2 billion last year."
  },
  "actual": null
}
```

The comparison value belongs to the previous fiscal year, not the currently reported period.

### costco-sales-04: period

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 8.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Net sales for the fiscal year increased 8.1 percent, to $269.9 billion, from $249.6 billion last year."
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2024-09-01",
    "period_end": "2025-08-31",
    "value": 8.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Net sales for the fiscal year increased 8.1 percent, to $269.9 billion, from $249.6 billion last year."
  }
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### costco-sales-05: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 269.9,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "Net sales for the fiscal year increased 8.1 percent, to $269.9 billion, from $249.6 billion last year."
  },
  "actual": null
}
```

Use the stated figure and reporting period; do not infer unstated geography or accounting basis.

### costco-sales-06: omission

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "net_sales",
    "geography": null,
    "period_start": "2023-09-04",
    "period_end": "2024-09-01",
    "value": 249.6,
    "range_low": null,
    "range_high": null,
    "unit": "usd_billions",
    "basis": null,
    "quote": "Net sales for the fiscal year increased 8.1 percent, to $269.9 billion, from $249.6 billion last year."
  },
  "actual": null
}
```

The comparison value belongs to the previous fiscal year, not the currently reported period.

### costco-comparables-02: activity_scope, unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "US",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 6.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "U.S. | 5.1% | 6.0% | 6.2% | 7.3%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "U.S.",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 6.0,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "U.S. | 5.1% | 6.0% | 6.2% | 7.3%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-04: activity_scope, unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "US",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 7.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "U.S. | 5.1% | 6.0% | 6.2% | 7.3%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "U.S.",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 7.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "U.S. | 5.1% | 6.0% | 6.2% | 7.3%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-06: activity_scope, unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Canada",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 8.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Canada | 6.3% | 8.3% | 5.0% | 8.3%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Canada",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 8.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Canada | 6.3% | 8.3% | 5.0% | 8.3%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-08: activity_scope, unit_basis

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Canada",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 8.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Canada | 6.3% | 8.3% | 5.0% | 8.3%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Canada",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 8.3,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Canada | 6.3% | 8.3% | 5.0% | 8.3%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-09: geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "other_international",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 8.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Other International",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 8.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-10: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "other_international",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 7.2,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Other International",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 7.2,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-11: geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "other_international",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 4.8,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Other International",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 4.8,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-12: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "other_international",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 8.2,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Other International",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 8.2,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Other International | 8.6% | 7.2% | 4.8% | 8.2%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-13: geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 5.7,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Total Company",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 5.7,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-14: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 6.4,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Total Company",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 6.4,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-15: geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 5.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "Total Company",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 5.9,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-16: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 7.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "Total Company",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 7.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "Total Company | 5.7% | 6.4% | 5.9% | 7.6%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-17: activity_scope, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "ecommerce_comparable_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 13.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "E-commerce",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 13.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-18: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "ecommerce_comparable_sales",
    "geography": null,
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 13.5,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "E-commerce",
    "period_start": "2025-05-12",
    "period_end": "2025-08-31",
    "value": 13.5,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-19: activity_scope, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "ecommerce_comparable_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 15.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales",
    "geography": "E-commerce",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 15.6,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

### costco-comparables-20: activity_scope, unit_basis, geography

[Original source, page 1](https://www.sec.gov/Archives/edgar/data/909832/000090983225000093/costex9918-k92525.htm)

```json
{
  "expected": {
    "statement_type": "measured",
    "activity_type": "ecommerce_comparable_sales",
    "geography": null,
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 16.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": "gasoline_and_fx_adjusted",
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  },
  "actual": {
    "statement_type": "measured",
    "activity_type": "comparable_sales_adjusted",
    "geography": "E-commerce",
    "period_start": "2024-09-02",
    "period_end": "2025-08-31",
    "value": 16.1,
    "range_low": null,
    "range_high": null,
    "unit": "percent",
    "basis": null,
    "quote": "E-commerce | 13.6% | 13.5% | 15.6% | 16.1%"
  }
}
```

16-week quarter begins May 12; 52-week fiscal year begins September 2. Adjusted columns exclude both gasoline-price and FX effects.

## Limitations

- Assistant-curated sample; human review covers the selected ten labels, not the entire corpus.
- Short purposively selected passages are not a random sample of filing extraction quality.
- Contradictions include revisions and opposing or apparently conflicting figures resolved by scope or period.
- Rates for semantic fields use matched labels; omissions use labels in successful passages. Unavailable labels remain in coverage.
- Prediction errors by category inherit all tags of the passage; categories overlap and must not be summed.
- Fiscal-period defaults, uncertainty margins, and semantic aliases follow the documented labeling guide.
- These extraction errors are separate from forecast errors and do not establish predictive performance.

Corpus hash: `9542090a7509d18d3ec22a49e48cd8d5f95310c8ec23d5a20f19969f4d068d5a`
Report hash: `55360cd8d41f4db9b9f3974a744db87b86e0014d16f68c0f22743a64d7d953d5`
