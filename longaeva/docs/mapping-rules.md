# Mapping rules

Reviewed observations become a child parameter set only through a rule in the code
registry. The registry is `longaeva_app.review.rules.REGISTRY`. `sync_registry` inserts
missing `(rule_key, version)` rows. If a stored `definition_hash` differs from the code
definition, sync raises: edit the rule and bump `version`. Do not change a published
version in place.

`GET /mapping-rules` syncs, then lists. Preview does not sync and does not write.
Apply syncs, then writes.

## Registry

| Rule | Kind | Family | Input | Target | Constants | Value test | Fit today |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `booking_guidance_to_cross_border_premium` v1 | analyst range | booking | guidance, room nights, units, percent | `cross_border_growth_premium` | anchor 8%, betas 0.2–0.4, scale 1, cap ±4pp, priority 20 | `ablation_a_cross_border_error` | range (assumption) |
| `booking_room_nights_to_cross_border_premium` v1 | estimated | booking | measured, room nights, units, percent | `cross_border_growth_premium` | same range as the fallback; Visa field `cross_border_ex_intra_europe_growth_constant` | `ablation_a_cross_border_error` | fallback (fewer than 12 aligned quarters) |
| `census_retail_yoy_to_payments_volume_growth` v2 | estimated | census | measured SA `retail_food_services_total` `yoy_3m_pct` `three_month` | `payments_volume_growth` | anchor 3%, betas 0.25–0.75, scale 0.45, cap ±4pp | `ablation_a_us_payments_volume_error` | estimated when at least 12 unique eligible quarters exist; otherwise fallback |
| `airline_context` v1 | context | airline | any | none | none | `context_until_a_reviewed_rule` | context |
| `retailer_context` v1 | context | retailer | any | none | none | `context_until_a_reviewed_rule` | context |
| `processor_context` v1 | context | processor | any | none | none | `context_until_a_reviewed_rule` | context |

Gross bookings and qualitative statements match no transforming rule. They are listed
as context with reason `no_adopted_rule` so room nights are not counted twice.

The guidance rule applies only when the origin row has
`booking_guidance_covers_target=true`. It outranks the measured room-nights rule
(priority 20 vs 10). The measured observation is then context with reason `superseded`.

## Transforms

Analyst range. `signal = (observed − anchor) × scale`. Percent and `pct` inputs are
divided by 100 first. A guidance range uses its midpoint as the point and its
half-width to widen the recorded range. The point shift is the midpoint of the betas
times `signal`, capped by `max_abs_shift`, then clamped to the parameter bounds. The
update is an assumption. The recorded low and high cover both beta ends.

Estimated. Ordinary least squares of a Visa driver on the external series, with an
intercept, using pairs whose external print and Visa print were both published at or
before the cutoff. Pandemic-flagged Visa quarters are left out. The slope needs at
least 12 aligned quarters. The point update is `slope × (observed − mean external)`,
capped by the fallback's `max_abs_shift`. The recorded range is the slope ± 1.96
standard errors, times the same gap. Below 12 quarters, or if the external series has
no variance, the analyst-range fallback is used and `after_value.fallback` is true.
The fallback is an assumption. A successful fit is not.

Alignment:

- Booking room nights use `next_visa_quarter`: the Visa quarter that ends strictly
  after the Booking period end (a quarter ending March 31 is paired with the quarter
  ending June 30).
- Census retail growth uses `containing_visa_quarter`: the Visa fiscal quarter that
  contains the three-month period end.

History is read from retained Booking JSON, the verified Census archive and Visa
`observations.csv`. Census uses one SA trailing-three-month growth figure ending
March, June, September or December per Visa quarter. Only parsed, hash-verified,
`ok` releases enter; both sources must be available by the cutoff. The same
selector supplies evaluation observations. Census now has enough quarterly
history to fit when 12 eligible pairs exist; Booking remains sparse and uses the
explicit analyst-range fallback. Historical outcomes are not used to tune rules.

## Apply

`POST /parameter-sets/{id}/rule-preview` returns the proposed updates and context and
writes nothing.

`POST /parameter-sets/{id}/apply-rules` requires `decided_by` and `rationale`. It
returns 201 when it inserts a child set and 200 when the set is unchanged or an
existing child hash is reused.

Checks, all 422:

- The parameter set's company is `visa`.
- Explicit observation ids are accepted or corrected. Pending and rejected ids are
  refused. Auto-selection (omitted ids) skips them.
- The source `publication_ts` is at or before the set's cutoff. A later explicit id
  is refused. Auto-selection skips it. Retrieval time is not the cutoff.
- An explicit id whose family is outside `families` is refused.

When `families` is omitted, every registry family is eligible. Pass `families` to
rebuild a set without an external family.

Updates run in registry order. Each update's before-value is the previous update's
after-value. Evidence for an updated parameter is the union of the previous
observation ids and the new id. Ranged and fallback updates set `assumption=true`
and store the rule rationale on the evidence link. The reviewer name and rationale
are stored only on `parameter_update.rationale`, so the child hash does not depend
on who applied the rule. The first stored update row wins if the same child is
applied again.

If nothing in the values, ranges, evidence, or assumption flags changes, no child set
and no update rows are created. Context rows are stored on the base set. Otherwise
the child has `parent_id` set to the base set. Re-applying the same inputs reuses
that content hash and does not insert duplicate update or context rows.

`GET /parameter-sets/{id}/lineage` walks `parent_id` and returns the root first.

Context reasons:

| Reason | When |
| --- | --- |
| `no_adopted_rule` | No registry rule matched (qualitative text, gross bookings, or an unknown shape). |
| `context_only` | The matching rule is a context entry (airline, retailer, processor). |
| `superseded` | Another observation won the same family and target (higher priority, then a later period). |

## Assumptions that are not measurements

- Booking betas 0.2–0.4 discount Booking's global mix. Room nights are not Visa
  payments volume. The 8% anchor is a neutral print, not a fitted mean.
- Census scale 0.45 is an explicit assumption for the US share of Visa volume.
  Census covers the United States only. A `*_us` Visa field name means US dollars,
  not a parsed US share.
- Guidance half-width widens the recorded range. It is not a probability.
- No transform carries a `confidence` or `probability` field. A qualitative input
  cannot be an estimated rule.
