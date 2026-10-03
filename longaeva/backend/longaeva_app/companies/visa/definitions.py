"""Visa driver and accounting definitions (LON-2).

Canonical field names for the LON-14 parser and LON-19 engine. No dynamics and no
``register_company`` call live here.
"""

from __future__ import annotations

from dataclasses import dataclass

from longaeva_app.companies.base import FiscalCalendar

VISA_FISCAL_CALENDAR = FiscalCalendar(fiscal_year_end_month=9)

# Fixed vocabulary for observation.basis (LON-10 column is free text; no migration).
BASIS_VOCABULARY: frozenset[str] = frozenset(
    {
        "nominal",
        "constant_dollar",
        "gaap",
        "ex_special_items",
        "derived",
        "count",
    }
)

UNIT_VOCABULARY: frozenset[str] = frozenset(
    {
        "usd_millions",
        "usd_billions",
        "ratio",
        "percent",
        "index",
        "transactions_millions",
        "shares_millions",
        "usd_per_share",
    }
)

PERIOD_RULE_VOCABULARY: frozenset[str] = frozenset(
    {
        "current_quarter",
        "prior_quarter",
        "as_of_period_end",
        "trailing_twelve_months",
        "derived",
    }
)

SOURCE_VOCABULARY: frozenset[str] = frozenset(
    {
        "earnings_release",
        "form_10q",
        "form_10k",
        "derived",
    }
)

MODEL_ROLE_VOCABULARY: frozenset[str] = frozenset(
    {
        "state",
        "metric",
        "driver",
        "parameter_input",
        "scoring",
        "context",
        "valuation",
        "not_an_input",
    }
)


@dataclass(frozen=True, slots=True)
class Citation:
    """Primary-source citation for a definition or field."""

    form: str
    period_label: str
    accession: str
    primary_document: str
    section: str
    quote: str

    def url(self) -> str:
        nodash = self.accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/1403161/{nodash}/{self.primary_document}"


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    """Canonical observation / state field used by parser and engine."""

    name: str
    unit: str
    basis: str
    period_rule: str
    source: str
    first_period: str  # e.g. FY2017Q1
    last_period: str  # e.g. FY2026Q3
    model_role: str
    description: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class DefinitionChange:
    """Dated disclosure change across the FY2017–FY2026 window."""

    effective_period: str
    kind: str  # label_change | format_change | new_series | comparability_break
    summary: str
    citations: tuple[Citation, ...]


# Shared citations reused across fields
_CITE_FY2025_10K_PV = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions",
    quote=(
        "Payments volume represents the aggregate dollar amount of purchases made with cards "
        "and other form factors carrying the Visa, Visa Electron, V PAY and Interlink brands "
        "and excludes Europe co-badged volume."
    ),
)

_CITE_FY2025_10K_NOMINAL = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions",
    quote=(
        "Nominal payments volume is denominated in U.S. dollars and is calculated each quarter "
        "by applying an established U.S. dollar/foreign currency exchange rate for each local "
        "currency in which our volumes are reported."
    ),
)

_CITE_FY2025_10K_TXN = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions",
    quote=(
        "Processed transactions include payments and cash transactions, and represent "
        "transactions using cards and other form factors carrying the Visa, Visa Electron, "
        "V PAY, Interlink and PLUS brands processed on Visa’s networks."
    ),
)

_CITE_FY2025_10K_TOTAL_VOL = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions (footnotes)",
    quote=(
        "Total nominal volume is the sum of total nominal payments volume and cash volume. "
        "Total nominal volume is provided by our financial institution clients, subject to "
        "review by Visa."
    ),
)

_CITE_FY2025_10K_CONSTANT = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions (footnotes)",
    quote=(
        "Growth on a constant-dollar basis excludes the impact of foreign currency "
        "fluctuations against the U.S. dollar."
    ),
)

_CITE_FY2025_10K_SERVICE_LAG = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Payments volume and processed transactions (footnote 1)",
    quote=(
        "Service revenue in a given quarter is primarily assessed based on nominal payments "
        "volume in the prior quarter."
    ),
)

_CITE_FY2025_10K_CATEGORIES = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 1 — Our net revenue",
    quote=(
        "SERVICE REVENUE Earned for services provided in support of client usage of Visa’s "
        "payment services and value-added services related to certain Issuing Solutions"
    ),
)

_CITE_FY2025_10K_INTL = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 1 — Our net revenue",
    quote=(
        "INTERNATIONAL TRANSACTION REVENUE Earned for cross-border transaction processing "
        "and currency conversion activities"
    ),
)

_CITE_FY2025_10K_INCENTIVES = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 1 — Our net revenue",
    quote=(
        "CLIENT INCENTIVES Paid to financial institution clients, sellers and other business "
        "partners to grow payments volume; increase Visa product acceptance; encourage seller "
        "acceptance and use of Visa’s payment services; and drive innovation"
    ),
)

_CITE_FY2025_10K_FYEND = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Form 10-K cover",
    quote="For the fiscal year ended September 30 , 2025",
)

_CITE_FY2025_10K_AMORT = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Non-GAAP Financial Measures",
    quote=(
        "Amortization of acquired intangible assets consists of amortization of intangible "
        "assets such as technology and customer relationships acquired in connection with "
        "business combinations executed beginning in fiscal 2019."
    ),
)

_CITE_FY2025_10K_LITIGATION = Citation(
    form="10-K",
    period_label="FY2025",
    accession="0001403161-25-000089",
    primary_document="v-20250930.htm",
    section="Item 7 — Non-GAAP Financial Measures",
    quote=(
        "Litigation provision includes significant accruals related to certain legal matters "
        "that are not covered by the U.S. retrospective responsibility plan or the Europe "
        "retrospective responsibility plan (uncovered legal matters) and additional accruals "
        "associated with the interchange multidistrict litigation"
    ),
)

_CITE_FY2018_10K_FYEND = Citation(
    form="10-K",
    period_label="FY2018",
    accession="0001403161-18-000055",
    primary_document="v093018.htm",
    section="Form 10-K cover",
    quote="For the fiscal year ended September 30, 2018",
)

_CITE_REL_FY2026Q3_LAG = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2026Q3",
    accession="0001403161-26-000103",
    primary_document="q32026earningsrelease.htm",
    section="Fiscal Third Quarter 2026 — Financial Highlights",
    quote=(
        "Fiscal third quarter service revenue was $4.9 billion, an increase of 14% over the "
        "prior year, and is recognized based on payments volume in the prior quarter. All "
        "other revenue categories are recognized based on current quarter activity."
    ),
)

_CITE_REL_FY2026Q3_EX_IE = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2026Q3",
    accession="0001403161-26-000103",
    primary_document="q32026earningsrelease.htm",
    section="Key Business Drivers (footnote)",
    quote="Cross-border volume excluding transactions within Europe.",
)

_CITE_REL_FY2026Q3_DRIVER = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2026Q3",
    accession="0001403161-26-000103",
    primary_document="q32026earningsrelease.htm",
    section="Fiscal Third Quarter 2026 — Financial Highlights",
    quote=(
        "Cross-border volume excluding transactions within Europe, which drives our "
        "international transaction revenue, for the three months ended June 30, 2026, "
        "increased 12% on a constant-dollar basis over the prior year."
    ),
)

_CITE_REL_FY2026Q3_CN = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2026Q3",
    accession="0001403161-26-000103",
    primary_document="q32026earningsrelease.htm",
    section="KEY BUSINESS DRIVERS table",
    quote="KEY BUSINESS DRIVERS YoY Change Constant Nominal Payments volume 10% 11%",
)

_CITE_REL_FY2018Q3_LAG = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2018Q3",
    accession="0001403161-18-000030",
    primary_document="vex991earningsrelease630.htm",
    section="Fiscal Third Quarter 2018 — Financial Highlights",
    quote=(
        "Fiscal third quarter service revenues were $2.2 billion, an increase of 13% over "
        "the prior year, and are recognized based on payments volume in the prior quarter. "
        "All other revenue categories are recognized based on current quarter activity."
    ),
)

_CITE_REL_FY2019Q3_EX_IE_PROSE = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2019Q3",
    accession="0001403161-19-000026",
    primary_document="q19ex9912.htm",
    section="Fiscal Third Quarter 2019 — Financial Highlights",
    quote=(
        "Excluding cross- border transactions within Europe, which have revenue yields "
        "similar to Europe’s domestic volume, growth was 9% in the quarter."
    ),
)

_CITE_REL_FY2020Q3_EX_IE_TABLE = Citation(
    form="8-K Ex. 99.1",
    period_label="FY2020Q3",
    accession="0001403161-20-000043",
    primary_document="q32020ex991.htm",
    section="Q3 2020 Key Business Drivers",
    quote=(
        "Cross-Border Volume Excluding Intra-Europe(1): (47%) … (1) Cross-border volume "
        "excluding transactions within Europe."
    ),
)

_CITE_10Q_Q2FY2026_PV = Citation(
    form="10-Q",
    period_label="FY2026Q2",
    accession="0001403161-26-000079",
    primary_document="v-20260331.htm",
    section="MD&A — Payments Volume and Processed Transactions",
    quote=(
        "Payments volume represents the aggregate dollar amount of purchases made with cards "
        "and other form factors carrying the Visa, Visa Electron, V PAY and Interlink brands "
        "and excludes Europe co-badged volume."
    ),
)

_CITE_10Q_Q2FY2026_PRISMA = Citation(
    form="10-Q",
    period_label="FY2026Q2",
    accession="0001403161-26-000079",
    primary_document="v-20260331.htm",
    section="Note 2—Acquisitions",
    quote=(
        "In February 2026, Visa acquired 100 % of the equity interest of each of Prisma Medios "
        "de Pago S.A.U. (Prisma) and Newpay S.A.U. (Newpay) in Argentina"
    ),
)

_CITE_FY2022_10K_RUSSIA = Citation(
    form="10-K",
    period_label="FY2022",
    accession="0001403161-22-000081",
    primary_document="v-20220930.htm",
    section="Item 1A — Risk Factors",
    quote=(
        "As a result of U.S. and European sanctions against Russia, we suspended our "
        "operations in Russia in March 2022 and are no longer generating revenue from "
        "domestic and cross-border activities related to Russia."
    ),
)

_CITE_FY2019_10K_ASC606 = Citation(
    form="10-K",
    period_label="FY2019",
    accession="0001403161-19-000050",
    primary_document="v093019form10k.htm",
    section="Item 7 — Results of Operations",
    quote=(
        "Other revenues increased primarily due to changes in the classification and timing "
        "of recognition of revenue as a result of the adoption of the new revenue standard "
        "and an increase in revenues from value-added services."
    ),
)


FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="service_revenue",
        unit="usd_millions",
        basis="gaap",
        period_rule="prior_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description=(
            "Service revenue for quarter t; primarily assessed on nominal payments volume in t−1 (service-revenue lag)."
        ),
        citations=(_CITE_FY2025_10K_SERVICE_LAG, _CITE_REL_FY2026Q3_LAG, _CITE_REL_FY2018Q3_LAG),
    ),
    FieldDefinition(
        name="data_processing_revenue",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description="Data processing revenue; driven by current-quarter processed transactions.",
        citations=(_CITE_FY2025_10K_CATEGORIES, _CITE_REL_FY2026Q3_LAG),
    ),
    FieldDefinition(
        name="international_transaction_revenue",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description=(
            "International transaction revenue; driven by current-quarter cross-border volume "
            "excluding intra-Europe and currency-conversion activity."
        ),
        citations=(_CITE_FY2025_10K_INTL, _CITE_REL_FY2026Q3_DRIVER),
    ),
    FieldDefinition(
        name="other_revenue",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description=(
            "Other revenue (value-added services, license fees, account-holder services). "
            "Not a fifth activity bucket; value-added services sit inside reported categories."
        ),
        citations=(_CITE_FY2025_10K_CATEGORIES,),
    ),
    FieldDefinition(
        name="client_incentives",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description="Client incentives (contra-revenue); subtracted from category revenue to form net revenue.",
        citations=(_CITE_FY2025_10K_INCENTIVES,),
    ),
    FieldDefinition(
        name="net_revenue",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="scoring",
        description=(
            "GAAP net revenue (= service + data processing + international + other − client "
            "incentives). Primary revenue scoring basis."
        ),
        citations=(_CITE_FY2025_10K_CATEGORIES, _CITE_REL_FY2026Q3_LAG),
    ),
    FieldDefinition(
        name="operating_expenses_gaap",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="metric",
        description="GAAP total operating expenses as reported.",
        citations=(_CITE_FY2025_10K_LITIGATION,),
    ),
    FieldDefinition(
        name="operating_expenses_ex_special_items",
        unit="usd_millions",
        basis="ex_special_items",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="scoring",
        description=(
            "Operating expenses excluding identified special items and the recurring "
            "non-GAAP adjustments Visa lists (amortization of acquired intangibles from "
            "FY2019+, acquisition-related costs)."
        ),
        citations=(_CITE_FY2025_10K_AMORT, _CITE_FY2025_10K_LITIGATION),
    ),
    FieldDefinition(
        name="special_items",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description=(
            "Identified special items in the period (litigation provision, severance, "
            "Russia-Ukraine charges, lease consolidation, and similar one-time items)."
        ),
        citations=(_CITE_FY2025_10K_LITIGATION,),
    ),
    FieldDefinition(
        name="operating_profit_gaap",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="scoring",
        description="GAAP operating profit (= net_revenue − operating_expenses_gaap). Reported alongside primary basis.",
        citations=(_CITE_FY2025_10K_CATEGORIES,),
    ),
    FieldDefinition(
        name="operating_profit_ex_special_items",
        unit="usd_millions",
        basis="ex_special_items",
        period_rule="current_quarter",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="scoring",
        description=("Primary operating-profit scoring basis: net_revenue − operating_expenses_ex_special_items."),
        citations=(_CITE_FY2025_10K_AMORT, _CITE_FY2025_10K_LITIGATION),
    ),
    FieldDefinition(
        name="payments_volume_nominal_us",
        unit="usd_billions",
        basis="nominal",
        period_rule="prior_quarter",
        source="form_10q",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="state",
        description=(
            "Nominal payments-volume level (USD). 10-Q/10-K tables report the quarter before "
            "the form's period end; at earnings cutoff q the newest eligible level is for q−2."
        ),
        citations=(_CITE_FY2025_10K_PV, _CITE_FY2025_10K_NOMINAL, _CITE_10Q_Q2FY2026_PV),
    ),
    FieldDefinition(
        name="cash_volume_nominal_us",
        unit="usd_billions",
        basis="nominal",
        period_rule="prior_quarter",
        source="form_10q",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description="Nominal cash volume (cash access, balance access, balance transfers, convenience checks).",
        citations=(_CITE_FY2025_10K_TOTAL_VOL,),
    ),
    FieldDefinition(
        name="total_volume_nominal_us",
        unit="usd_billions",
        basis="nominal",
        period_rule="prior_quarter",
        source="form_10q",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description="Total nominal volume = payments volume + cash volume. Not a model activity driver.",
        citations=(_CITE_FY2025_10K_TOTAL_VOL,),
    ),
    FieldDefinition(
        name="processed_transactions_count",
        unit="transactions_millions",
        basis="count",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="state",
        description="Count of Visa-processed transactions (payments and cash; includes PLUS).",
        citations=(_CITE_FY2025_10K_TXN,),
    ),
    FieldDefinition(
        name="payments_volume_growth_constant",
        unit="percent",
        basis="constant_dollar",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="driver",
        description="YoY payments-volume growth on a constant-dollar basis (summary Key Business Drivers).",
        citations=(_CITE_FY2025_10K_CONSTANT, _CITE_REL_FY2026Q3_CN),
    ),
    FieldDefinition(
        name="payments_volume_growth_nominal",
        unit="percent",
        basis="nominal",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2018Q2",
        last_period="FY2026Q3",
        model_role="driver",
        description=(
            "YoY payments-volume growth on a nominal basis from the detailed KEY BUSINESS "
            "DRIVERS table (present FY2018Q2+)."
        ),
        citations=(_CITE_REL_FY2026Q3_CN, _CITE_FY2025_10K_NOMINAL),
    ),
    FieldDefinition(
        name="payments_volume_prior_quarter_growth_constant",
        unit="percent",
        basis="constant_dollar",
        period_rule="prior_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="driver",
        description=(
            "Constant-dollar YoY growth of payments volume for t−1, the quarter on which "
            "service revenue in t is recognized."
        ),
        citations=(_CITE_FY2025_10K_SERVICE_LAG, _CITE_REL_FY2026Q3_LAG),
    ),
    FieldDefinition(
        name="cross_border_ex_intra_europe_growth_constant",
        unit="percent",
        basis="constant_dollar",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2020Q1",
        last_period="FY2026Q3",
        model_role="driver",
        description=(
            "Constant-dollar YoY growth of cross-border volume excluding intra-Europe; "
            "primary driver of international transaction revenue. Prose-only before FY2020."
        ),
        citations=(_CITE_REL_FY2026Q3_EX_IE, _CITE_REL_FY2026Q3_DRIVER, _CITE_REL_FY2020Q3_EX_IE_TABLE),
    ),
    FieldDefinition(
        name="cross_border_ex_intra_europe_growth_nominal",
        unit="percent",
        basis="nominal",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2020Q3",
        last_period="FY2026Q3",
        model_role="driver",
        description="Nominal YoY growth of cross-border volume excluding intra-Europe (detailed table).",
        citations=(_CITE_REL_FY2026Q3_CN,),
    ),
    FieldDefinition(
        name="cross_border_total_growth_constant",
        unit="percent",
        basis="constant_dollar",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description=(
            "Constant-dollar YoY growth of total cross-border volume (includes intra-Europe). "
            "Context/share only; not the international-revenue driver."
        ),
        citations=(_CITE_REL_FY2026Q3_EX_IE, _CITE_REL_FY2019Q3_EX_IE_PROSE),
    ),
    FieldDefinition(
        name="cross_border_total_growth_nominal",
        unit="percent",
        basis="nominal",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2020Q3",
        last_period="FY2026Q3",
        model_role="context",
        description="Nominal YoY growth of total cross-border volume (detailed table).",
        citations=(_CITE_REL_FY2026Q3_CN,),
    ),
    FieldDefinition(
        name="processed_transactions_growth",
        unit="percent",
        basis="count",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="driver",
        description="YoY growth in processed-transaction count (currency-invariant).",
        citations=(_CITE_FY2025_10K_TXN, _CITE_REL_FY2026Q3_CN),
    ),
    FieldDefinition(
        name="payments_volume_index_nominal",
        unit="index",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="state",
        description=(
            "Nominal payments-volume activity index. Anchored on the newest eligible "
            "payments_volume_nominal_us level and rolled forward with release growth "
            "(prefer nominal; else constant-dollar growth plus a labeled currency adjustment)."
        ),
        citations=(_CITE_FY2025_10K_NOMINAL, _CITE_FY2025_10K_CONSTANT, _CITE_10Q_Q2FY2026_PV),
    ),
    FieldDefinition(
        name="cross_border_ex_intra_europe_index_nominal",
        unit="index",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2020Q1",
        last_period="FY2026Q3",
        model_role="state",
        description=(
            "Nominal cross-border ex-intra-Europe activity index (share/sub-index of "
            "payments volume; never sampled as additive spending)."
        ),
        citations=(_CITE_REL_FY2026Q3_DRIVER, _CITE_FY2025_10K_INTL),
    ),
    FieldDefinition(
        name="processed_transactions_index",
        unit="index",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="state",
        description="Processed-transactions activity index normalized from processed_transactions_count.",
        citations=(_CITE_FY2025_10K_TXN,),
    ),
    FieldDefinition(
        name="effective_yield_service",
        unit="ratio",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="parameter_input",
        description=(
            "Derived effective yield: service_revenue(t) / payments_volume_nominal(t−1). "
            "Not a contract fee; teaching fees are not an input."
        ),
        citations=(_CITE_FY2025_10K_SERVICE_LAG,),
    ),
    FieldDefinition(
        name="effective_yield_data_processing",
        unit="ratio",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="parameter_input",
        description="Derived effective yield: data_processing_revenue(t) / processed_transactions_count(t).",
        citations=(_CITE_FY2025_10K_TXN,),
    ),
    FieldDefinition(
        name="effective_yield_international",
        unit="ratio",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="parameter_input",
        description=(
            "Derived effective yield on cross-border ex-intra-Europe activity (includes currency-conversion effects)."
        ),
        citations=(_CITE_FY2025_10K_INTL, _CITE_REL_FY2026Q3_DRIVER),
    ),
    FieldDefinition(
        name="incentive_intensity",
        unit="ratio",
        basis="derived",
        period_rule="derived",
        source="derived",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="parameter_input",
        description="Derived: client_incentives / gross category revenue.",
        citations=(_CITE_FY2025_10K_INCENTIVES,),
    ),
    FieldDefinition(
        name="tax_rate",
        unit="ratio",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="valuation",
        description="Effective income-tax rate from the earnings release (valuation bridge).",
        citations=(_CITE_REL_FY2026Q3_LAG, _CITE_FY2025_10K_FYEND),
    ),
    FieldDefinition(
        name="net_interest_other",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="valuation",
        description="Net interest and other non-operating items from the earnings release (valuation bridge).",
        citations=(_CITE_REL_FY2026Q3_LAG, _CITE_FY2025_10K_FYEND),
    ),
    FieldDefinition(
        name="diluted_shares",
        unit="shares_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="valuation",
        description="Diluted class A share count used for EPS and the valuation bridge.",
        citations=(_CITE_REL_FY2026Q3_LAG,),
    ),
)

# Observation-only fields emitted by the LON-14 parser. Kept out of FIELDS so
# LON-3 starting-state fixtures keep their original key set.
REPORTED_FIELDS: tuple[FieldDefinition, ...] = (
    FieldDefinition(
        name="eps_diluted_gaap",
        unit="usd_per_share",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description="GAAP diluted class A earnings per share from the income statement summary.",
        citations=(_CITE_REL_FY2026Q3_LAG,),
    ),
    FieldDefinition(
        name="eps_diluted_ex_special_items",
        unit="usd_per_share",
        basis="ex_special_items",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description="Non-GAAP / adjusted diluted class A earnings per share from the income statement summary.",
        citations=(_CITE_REL_FY2026Q3_LAG,),
    ),
    FieldDefinition(
        name="special_item_operating_expense",
        unit="usd_millions",
        basis="gaap",
        period_rule="current_quarter",
        source="earnings_release",
        first_period="FY2017Q1",
        last_period="FY2026Q3",
        model_role="context",
        description=(
            "One operating-expense bridge line from the three-month non-GAAP reconciliation "
            "(item label stored in attributes.item)."
        ),
        citations=(_CITE_FY2025_10K_LITIGATION, _CITE_FY2025_10K_AMORT),
    ),
)


CHANGES: tuple[DefinitionChange, ...] = (
    DefinitionChange(
        effective_period="FY2017Q1",
        kind="comparability_break",
        summary=(
            "Visa Europe acquisition closed June 2016; FY2017 is the first full year with "
            "Europe in the consolidated perimeter. Integration costs appear in outlook notes "
            "through FY2018."
        ),
        citations=(_CITE_FY2018_10K_FYEND,),
    ),
    DefinitionChange(
        effective_period="FY2018Q2",
        kind="format_change",
        summary=(
            "Detailed KEY BUSINESS DRIVERS table begins reporting Constant and Nominal "
            "columns side by side (summary box remains constant-dollar)."
        ),
        citations=(_CITE_REL_FY2026Q3_CN,),
    ),
    DefinitionChange(
        effective_period="FY2019Q1",
        kind="comparability_break",
        summary=(
            "ASC 606 / Topic 606 adoption changes classification and timing of some other "
            "revenue; other_revenue series before/after need an explicit bridge."
        ),
        citations=(_CITE_FY2019_10K_ASC606,),
    ),
    DefinitionChange(
        effective_period="FY2019Q3",
        kind="format_change",
        summary=(
            "Cross-border volume excluding transactions within Europe appears in release "
            "prose (yields similar to Europe domestic); summary table still shows total "
            "cross-border only."
        ),
        citations=(_CITE_REL_FY2019Q3_EX_IE_PROSE,),
    ),
    DefinitionChange(
        effective_period="FY2019Q4",
        kind="label_change",
        summary=(
            "Non-GAAP reconciliations begin excluding amortization of acquired intangible "
            "assets from FY2019 business combinations (continues through FY2026)."
        ),
        citations=(_CITE_FY2025_10K_AMORT,),
    ),
    DefinitionChange(
        effective_period="FY2020Q1",
        kind="new_series",
        summary=(
            "Key Business Drivers and detailed tables split cross-border into excluding "
            "intra-Europe and (from FY2020Q3) total; excluding-intra-Europe is the "
            "international-revenue driver."
        ),
        citations=(_CITE_REL_FY2020Q3_EX_IE_TABLE, _CITE_REL_FY2026Q3_DRIVER),
    ),
    DefinitionChange(
        effective_period="FY2022Q2",
        kind="comparability_break",
        summary=(
            "Operations in Russia suspended March 2022; domestic and cross-border Russia "
            "activity drop out of reported volumes and revenue. Growth rates around the "
            "suspension need an explicit Russia note; definitions of the series do not change."
        ),
        citations=(_CITE_FY2022_10K_RUSSIA,),
    ),
    DefinitionChange(
        effective_period="FY2020Q2",
        kind="new_series",
        summary=(
            "Narrative growth metrics (consumer payments, commercial and money movement / "
            "new flows, value-added services) appear in CEO commentary. Context only; not "
            "model activity drivers and not comparable as a continuous series from FY2017."
        ),
        citations=(_CITE_FY2025_10K_CATEGORIES,),
    ),
    DefinitionChange(
        effective_period="FY2026Q2",
        kind="comparability_break",
        summary=(
            "February 2026 acquisitions of Prisma and Newpay in Argentina may shift "
            "category growth and processed-transaction counts; treat as a labeled mix "
            "shift when reconstructing FY2026Q2–Q3 states."
        ),
        citations=(_CITE_10Q_Q2FY2026_PRISMA,),
    ),
)
