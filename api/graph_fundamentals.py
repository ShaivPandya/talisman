"""Comparable fundamental histories. Values use native reported currencies, never FX conversion.

The chart is a descriptive history, not a point-in-time backtest. Filing selection
matches Financials (period-owned filings and explicit amendments). All calculations
are pure after load_company: no network access per field or per observation.
"""

from __future__ import annotations

import calendar
import logging
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from functools import cache, lru_cache
from typing import Any

from portfolio.momentum.fundamental_momentum import _edgar_periods as periods
from portfolio.momentum.fundamental_momentum.edgar_fetcher import (
    build_filing_url,
    fetch_companyfacts_by_cik,
    get_cik_for_ticker,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    category: str
    unit: str
    formula: str
    concepts: tuple[str, ...] = ()
    kind: str = "flow"
    estimates: bool = False


# The enumerated issue catalog contains 40 fields. Internal inputs are deliberately
# excluded from the public catalog; raw XBRL browsing is not a supported interface.
FIELDS = [
    Field(
        "revenue",
        "Revenue",
        "Highlights",
        "currency",
        "Reported revenue",
        (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        estimates=True,
    ),
    Field(
        "eps",
        "Diluted EPS (GAAP)",
        "Highlights",
        "per_share",
        "Reported diluted EPS; otherwise net income / diluted weighted-average shares",
        ("EarningsPerShareDiluted",),
        "eps",
        True,
    ),
    Field("net_income", "Net Income", "Highlights", "currency", "Reported net income", ("NetIncomeLoss", "ProfitLoss")),
    Field("fcf", "Free Cash Flow", "Highlights", "currency", "Cash from operations − capex"),
    Field(
        "gross_profit",
        "Gross Profit",
        "Income statement",
        "currency",
        "Reported gross profit; otherwise revenue − cost of revenue",
        ("GrossProfit",),
    ),
    Field(
        "operating_income",
        "Operating Income",
        "Income statement",
        "currency",
        "Reported operating income",
        ("OperatingIncomeLoss",),
    ),
    Field("ebitda", "EBITDA", "Income statement", "currency", "Operating income + depreciation and amortization"),
    Field("gross_margin", "Gross Margin", "Income statement", "percent", "Gross profit / revenue × 100"),
    Field("operating_margin", "Operating Margin", "Income statement", "percent", "Operating income / revenue × 100"),
    Field("net_margin", "Net Margin", "Income statement", "percent", "Net income / revenue × 100"),
    Field("sga_pct", "SG&A % of Revenue", "Income statement", "percent", "SG&A / revenue × 100"),
    Field("rd_pct", "R&D % of Revenue", "Income statement", "percent", "R&D / revenue × 100"),
    Field("assets", "Total Assets", "Balance sheet", "currency", "Reported period-end assets", ("Assets",), "stock"),
    Field(
        "cash",
        "Cash & Equivalents",
        "Balance sheet",
        "currency",
        "Reported period-end cash and equivalents; includes restricted cash if only a combined total is reported",
        ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        "stock",
    ),
    Field(
        "debt",
        "Total Debt",
        "Balance sheet",
        "currency",
        "Total interest-bearing debt; otherwise non-overlapping current + noncurrent debt",
        kind="stock",
    ),
    Field("net_debt", "Net Debt", "Balance sheet", "currency", "Total debt − cash", kind="stock"),
    Field(
        "equity",
        "Shareholders' Equity",
        "Balance sheet",
        "currency",
        "Reported shareholders' equity",
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        "stock",
    ),
    Field(
        "book_value",
        "Book Value per Share",
        "Balance sheet",
        "per_share",
        "Shareholders' equity / period-end common shares",
        kind="stock",
    ),
    Field(
        "shares",
        "Shares Outstanding",
        "Balance sheet",
        "count",
        "Reported period-end common shares, not today's share count",
        ("CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"),
        "stock",
    ),
    Field(
        "cfo",
        "Cash from Operations",
        "Cash flow",
        "currency",
        "Reported cash from operations",
        ("NetCashProvidedByUsedInOperatingActivities",),
    ),
    Field(
        "capex",
        "Capex",
        "Cash flow",
        "currency",
        "Cash paid for property, plant and equipment (positive outflow)",
        ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"),
    ),
    Field("capex_pct", "Capex % of Revenue", "Cash flow", "percent", "Capex / revenue × 100"),
    Field(
        "sbc",
        "Stock-Based Compensation",
        "Cash flow",
        "currency",
        "Reported stock-based compensation",
        ("ShareBasedCompensation",),
    ),
    Field(
        "dividends",
        "Dividends Paid",
        "Cash flow",
        "currency",
        "Cash dividends paid (positive outflow)",
        ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    ),
    Field(
        "buybacks",
        "Buybacks",
        "Cash flow",
        "currency",
        "Cash paid to repurchase common stock (positive outflow)",
        ("PaymentsForRepurchaseOfCommonStock",),
    ),
    Field(
        "roic",
        "ROIC",
        "Ratios",
        "percent",
        "Operating income × (1 − effective tax rate) / average invested capital × 100; capital = equity + debt − cash; tax rate must be 0–100%",
    ),
    Field("roe", "ROE", "Ratios", "percent", "Net income / average shareholders' equity × 100"),
    Field("roa", "ROA", "Ratios", "percent", "Net income / average total assets × 100"),
    Field("net_debt_ebitda", "Net Debt / EBITDA", "Ratios", "ratio", "Period-end net debt / trailing EBITDA"),
    Field("interest_coverage", "Interest Coverage", "Ratios", "ratio", "Operating income / absolute interest expense"),
    Field("asset_turnover", "Asset Turnover", "Ratios", "ratio", "Revenue / average total assets"),
    Field("fcf_margin", "FCF Margin", "Ratios", "percent", "Free cash flow / revenue × 100"),
    Field(
        "market_cap", "Market Cap", "Market", "currency", "Period-end price × period-end reported shares", kind="stock"
    ),
    Field("enterprise_value", "Enterprise Value", "Market", "currency", "Market cap + debt − cash", kind="stock"),
    Field("pe", "P/E", "Market", "ratio", "Market cap / trailing net income (positive earnings only)"),
    Field("ev_ebitda", "EV/EBITDA", "Market", "ratio", "Enterprise value / trailing EBITDA (positive EBITDA only)"),
    Field("pb", "P/B", "Market", "ratio", "Market cap / positive period-end equity"),
    Field("ps", "P/S", "Market", "ratio", "Market cap / trailing revenue"),
    Field("fcf_yield", "FCF Yield", "Market", "percent", "Trailing free cash flow / market cap × 100"),
    Field("dividend_yield", "Dividend Yield", "Market", "percent", "Trailing cash dividends paid / market cap × 100"),
]
CATALOG = {f.id: f for f in FIELDS}
INTERNAL = [
    Field(
        "cost",
        "Cost of revenue",
        "",
        "currency",
        "",
        ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    ),
    Field("sga", "SG&A", "", "currency", "", ("SellingGeneralAndAdministrativeExpense",)),
    Field("rd", "R&D", "", "currency", "", ("ResearchAndDevelopmentExpense",)),
    Field(
        "da",
        "D&A",
        "",
        "currency",
        "",
        (
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
        ),
    ),
    Field(
        "interest",
        "Interest expense",
        "",
        "currency",
        "",
        (
            "InterestExpenseNonOperating",
            "InterestExpenseNonoperating",
            "InterestExpenseBorrowings",
            "InterestAndDebtExpense",
            "InterestExpense",
        ),
    ),
    Field("depreciation", "Depreciation", "", "currency", "", ("Depreciation", "DepreciationNonproduction")),
    Field("amortization", "Intangible amortization", "", "currency", "", ("AmortizationOfIntangibleAssets",)),
    Field("tax", "Income tax", "", "currency", "", ("IncomeTaxExpenseBenefit",)),
    Field(
        "pretax",
        "Pretax income",
        "",
        "currency",
        "",
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
    ),
    Field(
        "diluted_shares",
        "Diluted weighted-average shares",
        "",
        "count",
        "",
        ("WeightedAverageNumberOfDilutedSharesOutstanding",),
        "average",
    ),
    Field(
        "debt_total",
        "Debt",
        "",
        "currency",
        "",
        (
            "LongTermDebtAndFinanceLeaseObligationsIncludingCurrentMaturities",
            "LongTermDebtCurrentAndNoncurrent",
            "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
            "LongTermDebt",
        ),
        "stock",
    ),
    Field(
        "debt_current",
        "Current debt",
        "",
        "currency",
        "",
        (
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
            "DebtCurrent",
        ),
        "stock",
    ),
    Field(
        "debt_noncurrent",
        "Noncurrent debt",
        "",
        "currency",
        "",
        (
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
        ),
        "stock",
    ),
    Field(
        "short_debt",
        "Short-term borrowings",
        "",
        "currency",
        "",
        ("ShortTermBorrowings", "ShortTermDebtCurrent"),
        "stock",
    ),
]
YF_KEYS = {
    "revenue": ["Total Revenue"],
    "eps": ["Diluted EPS"],
    "net_income": ["Net Income"],
    "gross_profit": ["Gross Profit"],
    "operating_income": ["Operating Income"],
    "assets": ["Total Assets"],
    "cash": ["Cash And Cash Equivalents"],
    "debt_total": ["Total Debt"],
    "equity": ["Stockholders Equity"],
    "shares": ["Ordinary Shares Number"],
    "cfo": ["Operating Cash Flow"],
    "capex": ["Capital Expenditure"],
    "sbc": ["Stock Based Compensation"],
    "dividends": ["Common Stock Dividend Paid", "Cash Dividends Paid"],
    "buybacks": ["Repurchase Of Capital Stock"],
    "cost": ["Cost Of Revenue"],
    "sga": ["Selling General And Administration"],
    "rd": ["Research And Development"],
    "da": ["Depreciation And Amortization", "Reconciled Depreciation"],
    "interest": ["Interest Expense"],
    "tax": ["Tax Provision"],
    "pretax": ["Pretax Income"],
    "diluted_shares": ["Diluted Average Shares"],
}
OUTFLOWS = {"capex", "dividends", "buybacks"}


def catalog() -> list[dict]:
    return [{k: v for k, v in asdict(f).items() if k not in {"concepts", "kind"}} for f in FIELDS]


def number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def shift_year(day: date, years: int) -> date:
    return day.replace(year=day.year + years, day=min(day.day, calendar.monthrange(day.year + years, day.month)[1]))


def _currency(facts: dict) -> str:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    candidates = []
    for concept in CATALOG["revenue"].concepts:
        for unit, rows in gaap.get(concept, {}).get("units", {}).items():
            if len(unit) == 3 and rows:
                candidates.append((max(str(r.get("end", "")) for r in rows), len(rows), unit))
    return max(candidates)[2] if candidates else "USD"


def _extract(facts: dict, currency: str, frequency: str) -> dict[str, dict[str, dict]]:
    namespaces = facts.get("facts", {})
    gaap = {**namespaces.get("dei", {}), **namespaces.get("us-gaap", {})}
    output: dict[str, dict[str, dict]] = {}
    for field in [*FIELDS, *INTERNAL]:
        if not field.concepts:
            continue
        unit = "shares" if field.unit == "count" else f"{currency}/shares" if field.kind == "eps" else currency
        raw_extractor = (
            periods._annual_fact_entries
            if frequency == "annual"
            else (
                periods._quarterly_average_entries
                if field.kind == "average"
                else periods._quarterly_direct_entries
                if field.kind == "eps"
                else periods._quarterly_flow_entries
            )
        )
        if field.kind == "stock":
            # Instant facts have no start/duration. Select the period's own filing,
            # never a future report-date share count carried backward.
            def raw_extractor(rows):
                return rows

        # Prefer vetted concepts per period, filling gaps from the next concept.
        # A later DEI cover-page date must not displace a GAAP period-end share
        # history simply because its most recent observation is newer.
        selected: dict[str, dict] = {}
        units = (unit, f"{currency}-per-shares") if field.kind == "eps" else (unit,)
        for concept in field.concepts:
            for candidate_unit in units:
                entries = periods._pick_best_concept_entries(gaap, (concept,), candidate_unit, raw_extractor)
                by_end: dict[str, list] = {}
                for entry in entries:
                    if periods._is_valid_fact_row(entry):
                        by_end.setdefault(entry["end"], []).append(entry)
                for end, rows in by_end.items():
                    if end not in selected:
                        picked = (
                            periods._pick_best_for_target(
                                rows,
                                4 if frequency == "annual" else 1,
                                "annual" if frequency == "annual" else "quarterly",
                                date.fromisoformat(end).year,
                            )
                            or rows[0]
                        )
                        selected[end] = {**picked, "concept": concept}
        output[field.id] = selected
    for end in set(output.get("depreciation", {})) & set(output.get("amortization", {})):
        if end not in output.get("da", {}):
            depreciation = output["depreciation"][end]
            amortization = output["amortization"][end]
            output.setdefault("da", {})[end] = {
                **depreciation,
                "val": depreciation["val"] + amortization["val"],
                "concept": "Depreciation + AmortizationOfIntangibleAssets",
            }
    return output


def _yf_statements(ticker: Any, frequency: str, currency: str) -> dict:
    output: dict = {}
    for getter in ("get_income_stmt", "get_balance_sheet", "get_cashflow"):
        try:
            frame = getattr(ticker, getter)(freq="yearly" if frequency == "annual" else "quarterly")
            for field, keys in YF_KEYS.items():
                for key in keys:
                    if key not in frame.index:
                        continue
                    for timestamp, raw in frame.loc[key].items():
                        value = number(raw)
                        if value is None:
                            continue
                        end = str(timestamp.date())
                        output.setdefault(field, {})[end] = {
                            "end": end,
                            "val": abs(value) if field in OUTFLOWS else value,
                            "fp": "FY" if frequency == "annual" else f"Q{timestamp.quarter}",
                            "fy": timestamp.year,
                            "source": "yfinance statements",
                            "currency": currency,
                        }
                    break
        except Exception:
            log.info("No %s %s statements", frequency, getter)
    return output


def _estimates(ticker: Any, as_of: str) -> dict:
    result: dict = {}
    for field, getter in (("eps", "get_earnings_estimate"), ("revenue", "get_revenue_estimate")):
        try:
            if field == "eps":
                try:
                    frame = getattr(ticker, getter)(methodology="gaap")
                except TypeError:  # Installed yfinance versions without methodology selection.
                    frame = getattr(ticker, getter)()
            else:
                frame = getattr(ticker, getter)()
            result[field] = {
                str(index): {
                    "value": number(row.get("avg")),
                    "analysts": number(row.get("numberOfAnalysts")),
                    "currency": row.get("currency"),
                    "basis": str(row.get("methodology") or "Yahoo consensus; accounting basis unspecified"),
                    "as_of": as_of,
                }
                for index, row in frame.iterrows()
            }
        except Exception:
            result[field] = {}
    return result


def load_company(ticker: str) -> dict:
    """One SEC request, one reusable Yahoo object; bounded by the route's ticker cache."""
    import yfinance as yf

    as_of = datetime.now(UTC).isoformat()
    cik = get_cik_for_ticker(ticker)
    facts = fetch_companyfacts_by_cik(cik, force_refresh=True) if cik else None
    currency = _currency(facts) if facts else "USD"
    quarterly = _extract(facts, currency, "quarters") if facts else {}
    annual = _extract(facts, currency, "annual") if facts else {}
    usable = bool(quarterly.get("revenue") or annual.get("revenue"))
    yt = yf.Ticker(ticker)
    quote_currency = None
    if not usable:
        try:
            info = yt.get_info()
        except Exception:
            info = {}
        currency = info.get("financialCurrency") or info.get("currency") or currency
        quote_currency = info.get("currency")
        quarterly = _yf_statements(yt, "quarters", currency)
        annual = _yf_statements(yt, "annual", currency)
    prices = []
    try:
        frame = yt.history(period="max", auto_adjust=False, actions=True, timeout=10)
        # Yahoo Close is split-adjusted even with auto_adjust=False. Undo future
        # splits so that price and SEC's period-owned share count use the same basis.
        future_splits = 1.0
        for timestamp, row in reversed(list(frame.iterrows())):
            close = number(row.get("Close"))
            if close is not None:
                prices.append({"date": str(timestamp.date()), "value": close * future_splits})
            split = number(row.get("Stock Splits"))
            if split and split > 0:
                future_splits *= split
        prices.reverse()
        meta = yt.get_history_metadata()
        quote_currency = meta.get("currency") or quote_currency
    except Exception:
        log.info("No price history for %s", ticker)
    if not quarterly.get("revenue") and not annual.get("revenue"):
        raise ValueError("No usable SEC companyfacts or yfinance statements for this ticker.")
    return {
        "ticker": ticker,
        "name": (facts or {}).get("entityName", ticker),
        "cik": cik,
        "currency": currency,
        "quote_currency": quote_currency,
        "quarters": quarterly,
        "annual": annual,
        "prices": prices,
        "estimates": _estimates(yt, as_of),
        "source": "SEC EDGAR" if usable else "yfinance statements (limited history)",
        "as_of": as_of,
    }


def _contiguous(ends: list[str]) -> bool:
    return all(
        60 <= (date.fromisoformat(b) - date.fromisoformat(a)).days <= 130 for a, b in zip(ends, ends[1:], strict=False)
    )


def compute_company(company: dict, frequency: str) -> dict[str, dict]:
    """Compute all fields once, retaining the full grid and warm-up history."""
    data = company["annual" if frequency == "annual" else "quarters"]
    ends = sorted(set(data.get("revenue", {})) | set(data.get("net_income", {})))
    annual = company["annual"]
    qdata = company["quarters"]
    prices = company.get("prices", [])

    def raw(key, end, src=data):
        return number(src.get(key, {}).get(end, {}).get("val"))

    def add(a, b):
        return None if a is None or b is None else a + b

    def sub(a, b):
        return None if a is None or b is None else a - b

    def divide(a, b, positive=False):
        return None if a is None or b is None or b == 0 or (positive and b <= 0) else a / b

    @cache
    def flow(key, end, trailing=False):
        if frequency == "annual":
            return raw(key, end)
        if frequency != "ltm" and not trailing:
            return raw(key, end)
        candidates = sorted(e for e in qdata.get(key, {}) if e <= end)[-4:]
        if len(candidates) == 4 and candidates[-1] == end and _contiguous(candidates):
            vals = [raw(key, e, qdata) for e in candidates]
            if all(v is not None for v in vals):
                return sum(vals)
        return raw(key, end, annual)

    def debt(end):
        total = raw("debt_total", end)
        if total is not None:
            short = raw("short_debt", end)
            return total + short if short is not None and company["source"] == "SEC EDGAR" else total
        long_term = add(raw("debt_current", end), raw("debt_noncurrent", end))
        short = raw("short_debt", end)
        current_concept = data.get("debt_current", {}).get(end, {}).get("concept")
        return add(long_term, short) if short is not None and current_concept != "DebtCurrent" else long_term

    def capital(end):
        return sub(add(raw("equity", end), debt(end)), raw("cash", end))

    def avg(key, end):
        # Quarter ROIC/ROE/ROA use the quarter's opening and closing capital;
        # LTM/Annual use endpoints one year apart. No averaging missing periods.
        pos = ends.index(end)
        lag = 1 if frequency in {"quarters", "annual"} else 4
        if pos < lag:
            return None
        before = ends[pos - lag]
        gap = (date.fromisoformat(end) - date.fromisoformat(before)).days
        if not (60 <= gap <= 130 if frequency == "quarters" else 330 <= gap <= 400):
            return None
        a = capital(before) if key == "capital" else raw(key, before)
        b = capital(end) if key == "capital" else raw(key, end)
        combined = add(a, b)
        return combined / 2 if combined is not None else None

    prices_by_end = {}
    for end in ends:
        eligible = [
            p
            for p in prices
            if p["date"] <= end and (date.fromisoformat(end) - date.fromisoformat(p["date"])).days <= 7
        ]
        prices_by_end[end] = number(eligible[-1]["value"]) if eligible else None
    output: dict[str, dict] = {}
    for field in FIELDS:
        points = []
        for end in ends:
            rev = flow("revenue", end)
            ni = flow("net_income", end)
            op = flow("operating_income", end)
            capex = flow("capex", end)
            cfo = flow("cfo", end)
            fcf = sub(cfo, capex)
            da = flow("da", end)
            ebitda = add(op, da)
            gross = flow("gross_profit", end)
            if gross is None:
                gross = sub(rev, flow("cost", end))
            net_debt = sub(debt(end), raw("cash", end))
            # At most seven calendar days backward; never use a future close.
            price = prices_by_end[end]
            if company.get("quote_currency") and company["quote_currency"] != company["currency"]:
                price = None  # FX and ADR ratios are deliberately not inferred.
            shares = raw("shares", end)
            market_cap = price * shares if price is not None and shares is not None else None
            ev = add(market_cap, net_debt)
            trailing_ni = flow("net_income", end, True)
            trailing_fcf = sub(flow("cfo", end, True), flow("capex", end, True))
            trailing_ebitda = add(flow("operating_income", end, True), flow("da", end, True))
            tax_rate = divide(flow("tax", end), flow("pretax", end), True)
            nopat = op * (1 - tax_rate) if op is not None and tax_rate is not None and 0 <= tax_rate <= 1 else None
            values = {
                "fcf": fcf,
                "gross_profit": gross,
                "ebitda": ebitda,
                "debt": debt(end),
                "net_debt": net_debt,
                "book_value": divide(raw("equity", end), shares, True),
                "gross_margin": divide(gross, rev, True),
                "operating_margin": divide(op, rev, True),
                "net_margin": divide(ni, rev, True),
                "sga_pct": divide(flow("sga", end), rev, True),
                "rd_pct": divide(flow("rd", end), rev, True),
                "capex_pct": divide(capex, rev, True),
                "roic": divide(nopat, avg("capital", end), True),
                "roe": divide(ni, avg("equity", end), True),
                "roa": divide(ni, avg("assets", end), True),
                "asset_turnover": divide(rev, avg("assets", end), True),
                "net_debt_ebitda": divide(net_debt, trailing_ebitda, True),
                "interest_coverage": divide(
                    op, abs(flow("interest", end)) if flow("interest", end) is not None else None
                ),
                "fcf_margin": divide(fcf, rev, True),
                "market_cap": market_cap,
                "enterprise_value": ev,
                "pe": divide(market_cap, trailing_ni, True),
                "ev_ebitda": divide(ev, trailing_ebitda, True),
                "pb": divide(market_cap, raw("equity", end), True),
                "ps": divide(market_cap, flow("revenue", end, True), True),
                "fcf_yield": divide(trailing_fcf, market_cap, True),
                "dividend_yield": divide(flow("dividends", end, True), market_cap, True),
            }
            if field.id in values:
                value = values[field.id]
                if field.unit == "percent" and value is not None:
                    value *= 100
            elif field.kind == "stock":
                value = raw(field.id, end)
            else:
                value = flow(field.id, end)
            if field.id == "eps" and (value is None or frequency == "ltm"):
                if frequency == "ltm":
                    share_ends = sorted(e for e in qdata.get("diluted_shares", {}) if e <= end)[-4:]
                    share_values = [raw("diluted_shares", e, qdata) for e in share_ends]
                    average_shares = (
                        sum(share_values) / 4
                        if len(share_values) == 4
                        and share_ends[-1] == end
                        and _contiguous(share_ends)
                        and all(v is not None for v in share_values)
                        else None
                    )
                else:
                    average_shares = raw("diluted_shares", end)
                value = divide(ni, average_shares, True)
            value = number(value)
            entry = data.get(field.id, {}).get(end) or data.get("revenue", {}).get(end, {})
            accn = str(entry.get("accn") or "")
            points.append(
                {
                    "date": end,
                    "value": value,
                    "period_label": f"FY{entry.get('fy', end[:4])}"
                    if frequency == "annual"
                    else f"{entry.get('fp', '')} {entry.get('fy', end[:4])}".strip(),
                    "filed": entry.get("filed"),
                    "filing_url": build_filing_url(company["cik"], accn) if company.get("cik") and accn else None,
                    "estimate": False,
                    "reason": None
                    if value is not None
                    else f"Missing or incompatible inputs for {field.label}: {field.formula}.",
                }
            )
        output[field.id] = {
            "ticker": company["ticker"],
            "field": field.id,
            "unit": field.unit,
            "currency": company["currency"] if field.unit in {"currency", "per_share"} else None,
            "source": company["source"],
            "as_of": company["as_of"],
            "formula": field.formula,
            "computed": not field.concepts or field.category == "Market",
            "points": points,
            "estimate_coverage": {
                "supported": field.estimates,
                "reason": "Only EPS and revenue have yfinance consensus coverage."
                if not field.estimates
                else "Only supplied forward periods are shown; LTM estimates are unavailable.",
            },
        }
    # Match each consensus period to the company's own fiscal calendar. Never
    # synthesize LTM estimates, years of quarters, or a provider publication date.
    for forecast_field in ("eps", "revenue"):
        if frequency == "ltm":
            continue
        estimates = company.get("estimates", {}).get(forecast_field, {})
        grid = sorted(
            company["annual" if frequency == "annual" else "quarters"].get(forecast_field, {})
            or data.get("revenue", {})
        )
        if not grid:
            continue
        last = date.fromisoformat(grid[-1])
        now = date.today()
        if (now - last).days > (550 if frequency == "annual" else 200):
            continue
        # 0q/0y refers to the current, not necessarily first unreported, period.
        current = shift_year(last, 1) if frequency == "annual" else _next_quarter(last)
        while current < now:
            current = shift_year(current, 1) if frequency == "annual" else _next_quarter(current)
        for key in ["0y", "+1y"] if frequency == "annual" else ["0q", "+1q"]:
            row = estimates.get(key, {})
            estimate_currency = row.get("currency")
            if row.get("value") is not None and (not estimate_currency or estimate_currency == company["currency"]):
                output[forecast_field]["points"].append(
                    {
                        "date": current.isoformat(),
                        "value": row["value"],
                        "period_label": f"{key} estimate",
                        "estimate": True,
                        "analysts": row.get("analysts"),
                        "as_of": row.get("as_of"),
                        "basis": row.get("basis"),
                        "source": "yfinance consensus",
                        "reason": None,
                    }
                )
            current = shift_year(current, 1) if frequency == "annual" else _next_quarter(current)
    return output


def _next_quarter(day: date) -> date:
    month = day.month + 3
    year = day.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    # Keep calendar month ends at month end; preserve 52/53-week dates otherwise.
    last_day = calendar.monthrange(year, month)[1]
    dom = last_day if day.day == calendar.monthrange(day.year, day.month)[1] else min(day.day, last_day)
    return date(year, month, dom)
