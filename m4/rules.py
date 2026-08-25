"""M4 reference implementation: Taiwan common-stock trading rules.

Scope is M0's universe: TWSE and TPEx domestic common stock, long-only cash
equity. ETFs, bond ETFs, warrants and emerging-board securities are out of
scope and are rejected rather than silently priced with the wrong table.

Every constant here is either derived from captured official data or marked
as requiring broker confirmation. See
docs/contracts/m4-market-rules-contract.md for the evidence behind each.

This module is deliberately pure: no I/O, no network, no clock. Callers pass
in the trading calendar and the reference prices they already hold.

Two locations, one file
-----------------------
The canonical home is Taiwan Core, `tw_sepa_screener.market_rules`, because
that is where the trading system will call it from. The governance repository
keeps a byte-identical mirror at `m4/rules.py` and the two are asserted equal
by `tests/invariant/test_upstream_parity.py`.

The mirror exists for one reason: governance CI runs on a machine that has no
Taiwan Core checkout, and these are the only M4 tests that need nothing but
Python. Moving the file upstream and deleting it here would have removed 118
pure-logic tests from every automated run and left them checkable only on the
operator's own machine. A mirror whose identity is enforced costs nothing and
keeps them running.

Edit either copy and the parity test fails. Neither is a fork.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Sequence

RULES_VERSION = "tw-alpha-m4-rules/1.0.0"

# Verified against 406,445 official TWSE closing prices captured in M3.1b:
# the smallest observed gap between distinct common-stock closes in each band.
COMMON_STOCK_TICKS: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("10"), Decimal("0.01")),
    (Decimal("50"), Decimal("0.05")),
    (Decimal("100"), Decimal("0.1")),
    (Decimal("500"), Decimal("0.5")),
    (Decimal("1000"), Decimal("1")),
    (Decimal("Infinity"), Decimal("5")),
)

BOARD_LOT = 1000
ODD_LOT_MIN = 1
ODD_LOT_MAX = 999

PRICE_LIMIT_RATE = Decimal("0.10")
SETTLEMENT_DAYS = 2
# A newly listed security has no price limit for its first five sessions.
NEW_LISTING_EXEMPT_SESSIONS = 5


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class LotType(str, Enum):
    BOARD = "board"
    ODD = "odd"


class OrderValidity(str, Enum):
    ROD = "rod"
    IOC = "ioc"
    FOK = "fok"


class RuleError(ValueError):
    """Raised when an input violates a Taiwan market rule."""


def tick_size(price: Decimal) -> Decimal:
    """Tick applicable at `price` for domestic common stock."""

    if price <= 0:
        raise RuleError("price must be positive")
    for upper, tick in COMMON_STOCK_TICKS:
        if price < upper:
            return tick
    raise RuleError("no tick band matched")


def is_on_tick(price: Decimal) -> bool:
    return price % tick_size(price) == 0


def round_to_tick(price: Decimal, *, side: Side | None = None) -> Decimal:
    """Snap a price onto its tick grid.

    A buy limit rounds down and a sell limit rounds up, so rounding never
    invents a more aggressive price than the caller asked for. Without a side
    the nearest tick is used.
    """

    if price <= 0:
        raise RuleError("price must be positive")
    tick = tick_size(price)
    units = price / tick
    if side is Side.BUY:
        snapped = units.to_integral_value(rounding=ROUND_FLOOR) * tick
    elif side is Side.SELL:
        snapped = units.to_integral_value(rounding=ROUND_CEILING) * tick
    else:
        snapped = units.to_integral_value(rounding=ROUND_HALF_UP) * tick
    # Rounding can cross a band boundary; re-snap once on the new band.
    if snapped > 0 and tick_size(snapped) != tick:
        return round_to_tick(snapped, side=side)
    return snapped


def price_limits(reference_price: Decimal) -> tuple[Decimal, Decimal]:
    """Official limit-up and limit-down prices for a reference price.

    The exchange publishes limits already snapped to the tick grid. Both are
    rounded *inward*, towards the reference price: the limit-up floors and the
    limit-down ceilings, so neither ever exceeds ten percent.

    Verified against the captured TWT49U record for 2402 on 2025-08-01, where
    a reference of 39.12 yields 43.00 and 35.25. Flooring the limit-down would
    give 35.20, which is outside the legal band.
    """

    if reference_price <= 0:
        raise RuleError("reference price must be positive")
    raw_up = reference_price * (Decimal("1") + PRICE_LIMIT_RATE)
    raw_down = reference_price * (Decimal("1") - PRICE_LIMIT_RATE)
    up_tick = tick_size(raw_up)
    down_tick = tick_size(raw_down)
    limit_up = (raw_up / up_tick).to_integral_value(rounding=ROUND_FLOOR) * up_tick
    limit_down = (raw_down / down_tick).to_integral_value(
        rounding=ROUND_CEILING
    ) * down_tick
    return limit_up, limit_down


def resolve_price_limits(
    reference_price: Decimal,
    *,
    official_limit_up: Decimal | None = None,
    official_limit_down: Decimal | None = None,
    is_ex_rights_session: bool = False,
    ex_rights_reference_price: Decimal | None = None,
    dividend_only_reference_price: Decimal | None = None,
    is_reduction_resumption_session: bool = False,
    resumption_reference_price: Decimal | None = None,
) -> tuple[Decimal, Decimal, str]:
    """Prefer the publisher's own limit prices; compute only as a fallback.

    Returns (limit_up, limit_down, basis).

    On an ex-rights session the band is not symmetric around one price. TWSE
    publishes two reference prices — 除權息參考價, which removes the whole
    distribution, and 減除股利參考價, which removes only the dividend — and
    they diverge whenever the distribution includes a cash capital increase.
    The exchange sets the limit-up from the higher of the two and the
    limit-down from the lower, giving the wider band on each side.

    Measured against every ex-rights record in the M3 window, this reproduces
    the published limits on **1,649 of 1,649 common-stock rows**. Using a
    single reference price reproduces 94.5%, and the 77 rows that carry a cash
    capital increase are exactly where it fails. ETFs are excluded: they trade
    on a different tick table.

    Source: 營業細則第63條 (limit is ten percent of 當市開盤競價基準) and
    第58條之3第3項第3款 (on an ex-rights session that basis comes from the
    reference prices of 第59條 as processed under 第62條).

    A capital reduction is the opposite case: the standard rule works exactly,
    but only from the right base. On the resumption session the limits are set
    around the exchange's 恢復買賣參考價, which reflects the new share count,
    and not around the last close before the halt, which does not. Measured
    against the 20 reductions in the M3 window the standard rule reproduces
    every published limit from the resumption reference, and reproduces none of
    them from the prior close. Passing the prior close would therefore be
    wrong every single time, so this function refuses to guess which one it was
    handed and requires the resumption reference explicitly.
    """

    if official_limit_up is not None and official_limit_down is not None:
        return official_limit_up, official_limit_down, "publisher-exact"
    if is_ex_rights_session:
        if (
            ex_rights_reference_price is None
            or dividend_only_reference_price is None
        ):
            raise RuleError(
                "ex-rights session needs both 除權息參考價 and 減除股利參考價: "
                "the two differ whenever the distribution includes a cash "
                "capital increase, and each sets one side of the band"
            )
        up, _ = price_limits(
            max(ex_rights_reference_price, dividend_only_reference_price)
        )
        _, down = price_limits(
            min(ex_rights_reference_price, dividend_only_reference_price)
        )
        return up, down, "computed-official-ex-rights-formula"
    if is_reduction_resumption_session:
        if resumption_reference_price is None:
            raise RuleError(
                "capital-reduction resumption session without the published "
                "resumption reference price: the prior close belongs to the "
                "old share count and would misprice every limit"
            )
        up, down = price_limits(resumption_reference_price)
        return up, down, "computed-from-publisher-resumption-reference"
    up, down = price_limits(reference_price)
    return up, down, "computed-standard-10pct"


def sessions_since_listing(
    listing_date: date, as_of_session: date, sessions: Sequence[date]
) -> int | None:
    """Trading sessions elapsed since listing, or None if unknowable."""

    ordered = sorted(sessions)
    try:
        start = ordered.index(listing_date)
        current = ordered.index(as_of_session)
    except ValueError:
        return None
    return current - start


def has_price_limit(
    *,
    listing_date: date | None,
    as_of_session: date,
    sessions: Sequence[date],
    transferred_from_tpex: bool | None = None,
) -> tuple[bool, str]:
    """Whether the ordinary ten percent limit applies on this session.

    A newly listed security trades without a price limit for its first five
    sessions. Applying the limit anyway would reject orders the exchange would
    have accepted, so a backtest would silently miss those fills.

    營業細則第63條第2項carves out one case: 「初次上市普通股**除上櫃轉上市者
    外**」. A company moving up from TPEx already has a trading history and a
    price, so it keeps the ordinary limit from its first TWSE session. Whether
    this listing is such a transfer is therefore required, not optional — an
    unknown answer blocks rather than granting the exemption, because granting
    it wrongly hands a backtest a limitless day the exchange never allowed.

    Returns (applies, basis). An unknown listing date likewise yields
    `blocked`: the caller must not assume either answer.
    """

    if listing_date is None:
        return False, "blocked-unknown-listing-date"
    elapsed = sessions_since_listing(listing_date, as_of_session, sessions)
    if elapsed is None:
        return False, "blocked-session-not-in-calendar"
    if elapsed >= NEW_LISTING_EXEMPT_SESSIONS:
        return True, "ordinary-ten-percent-limit"
    if transferred_from_tpex is None:
        return False, "blocked-unknown-whether-transferred-from-tpex"
    if transferred_from_tpex:
        return True, "ordinary-limit-tpex-transfer-is-not-a-new-listing"
    return False, "exempt-new-listing-first-five-sessions"


def classify_lot(quantity: int) -> LotType:
    if quantity <= 0:
        raise RuleError("quantity must be positive")
    if quantity % BOARD_LOT == 0:
        return LotType.BOARD
    if ODD_LOT_MIN <= quantity <= ODD_LOT_MAX:
        return LotType.ODD
    raise RuleError(
        "mixed board and odd quantities must be split into separate orders"
    )


def settlement_date(trade_date: date, sessions: Sequence[date]) -> date:
    """T+2 in trading sessions, not calendar days.

    `sessions` must be the official trading calendar; the caller is
    responsible for its provenance. Settlement is never inferred when the
    calendar does not extend far enough.
    """

    ordered = sorted(sessions)
    try:
        index = ordered.index(trade_date)
    except ValueError as exc:
        raise RuleError(f"{trade_date} is not an official trading session") from exc
    target = index + SETTLEMENT_DAYS
    if target >= len(ordered):
        raise RuleError(
            "trading calendar does not extend far enough to settle this trade"
        )
    return ordered[target]


@dataclass(frozen=True)
class BrokerTerms:
    """Broker-specific commercial terms.

    Defaults are the conservative research assumptions frozen in the M0
    contract and are labelled `assumption`, not verified fact. A real canary
    requires terms confirmed against a signed broker agreement.
    """

    commission_rate: Decimal = Decimal("0.001425")
    commission_discount: Decimal = Decimal("1")
    minimum_commission: Decimal = Decimal("20")
    sell_tax_rate: Decimal = Decimal("0.003")
    slippage_rate: Decimal = Decimal("0.002")
    evidence_state: str = "assumption"
    source: str = "M0 contract research defaults; broker terms unconfirmed"

    # A discount that is refunded rather than applied. SinoPac's published
    # schedule reads "the full commission is charged in the month and returned
    # to the settlement account on the 15th of the next", so one fill has two
    # costs: the cash that leaves at execution, and what it finally cost.
    #
    # Leave these None and every existing caller keeps its current behaviour
    # exactly; a broker without a rebate needs no changes.
    rebate_commission_rate: Decimal | None = None
    rebate_minimum_commission: Decimal | None = None
    rebate_payment_day: int | None = None
    rebate_scope: str = "commission-only"

    def __post_init__(self) -> None:
        for name in (
            "commission_rate",
            "commission_discount",
            "minimum_commission",
            "sell_tax_rate",
            "slippage_rate",
        ):
            if getattr(self, name) < 0:
                raise RuleError(f"{name} must not be negative")
        if self.commission_discount > 1:
            raise RuleError("commission_discount must not exceed 1")

        rebate_fields = (
            self.rebate_commission_rate,
            self.rebate_minimum_commission,
            self.rebate_payment_day,
        )
        if any(f is not None for f in rebate_fields):
            if any(f is None for f in rebate_fields):
                raise RuleError(
                    "a rebate needs its rate, its minimum and its payment day; "
                    "a partial declaration would silently charge or refund the "
                    "wrong amount"
                )
            if self.rebate_commission_rate < 0 or self.rebate_minimum_commission < 0:
                raise RuleError("rebate terms must not be negative")
            if self.rebate_commission_rate > self.commission_rate:
                raise RuleError(
                    "the rebated rate exceeds the charged rate, which would "
                    "refund more than was taken"
                )
            if self.rebate_minimum_commission > self.minimum_commission:
                raise RuleError(
                    "the rebated minimum exceeds the charged minimum, which "
                    "would refund more than was taken"
                )
            if not 1 <= self.rebate_payment_day <= 28:
                raise RuleError("rebate_payment_day must be a day every month has")
        # The tax is statutory. A broker cannot discount it, so a rebate that
        # claimed to reach it would be describing something that cannot happen.
        if self.rebate_scope != "commission-only":
            raise RuleError("only commission-only rebates are modelled")

    @property
    def has_rebate(self) -> bool:
        return self.rebate_payment_day is not None


@dataclass(frozen=True)
class CostBreakdown:
    gross: Decimal
    commission: Decimal
    tax: Decimal
    total_cost: Decimal
    net_cash_delta: Decimal
    minimum_commission_applied: bool
    terms_evidence_state: str
    # What execution takes, and what the fill finally costs. Equal unless the
    # broker rebates; `commission` above is `commission_charged` under its old
    # name, kept so existing callers do not silently change meaning.
    commission_charged: Decimal = Decimal("0")
    commission_net: Decimal = Decimal("0")
    commission_rebate: Decimal = Decimal("0")
    rebate_due_on: date | None = None
    rules_version: str = RULES_VERSION


def _truncate_to_dollar(value: Decimal) -> Decimal:
    """Taiwan brokers bill whole NTD, truncating the fraction."""

    return value.to_integral_value(rounding=ROUND_DOWN)


def rebate_due_on(filled: date, terms: BrokerTerms) -> date | None:
    """When a fill's commission rebate reaches the settlement account.

    The published wording is "returned on the 15th of the following month,
    earlier if that is a holiday". Earlier, so the 15th is the latest a rebate
    can arrive, and modelling it there keeps the receivable outstanding for as
    long as it could possibly be. The error runs towards holding cash out of
    reach rather than towards spending it early, which is the same direction
    D9 chose for full-cash-delivery.

    A banking calendar would sharpen this. The trading calendar is not one and
    must not be borrowed for it.
    """

    if not terms.has_rebate:
        return None
    year, month = filled.year, filled.month + 1
    if month > 12:
        year, month = year + 1, 1
    return date(year, month, terms.rebate_payment_day)


def trade_costs(
    *,
    side: Side,
    price: Decimal,
    quantity: int,
    terms: BrokerTerms = BrokerTerms(),
    session: date | None = None,
) -> CostBreakdown:
    """Full NTD cost of one fill, including the minimum commission.

    `net_cash_delta` is negative for a buy (cash leaves) and positive for a
    sell (cash arrives), both already net of costs. Where the broker rebates,
    both use the amount actually charged: the refund has not arrived yet, and
    treating it as if it had would overstate buying power.

    `session` is only needed to date a rebate. Without it the rebate is still
    computed, but `rebate_due_on` is None and the caller must supply the date
    before booking a receivable.
    """

    if quantity <= 0:
        raise RuleError("quantity must be positive")
    if price <= 0:
        raise RuleError("price must be positive")

    gross = price * quantity

    def _commission(rate: Decimal, floor: Decimal) -> tuple[Decimal, bool]:
        amount = _truncate_to_dollar(gross * rate * terms.commission_discount)
        if amount < floor:
            return floor, True
        return amount, False

    charged, minimum_applied = _commission(
        terms.commission_rate, terms.minimum_commission
    )
    if terms.has_rebate:
        net_commission, _ = _commission(
            terms.rebate_commission_rate, terms.rebate_minimum_commission
        )
    else:
        net_commission = charged

    tax = (
        _truncate_to_dollar(gross * terms.sell_tax_rate)
        if side is Side.SELL
        else Decimal("0")
    )
    # Cash moves on the charged amount. The rebate is a separate, later event.
    total_cost = charged + tax
    net = -(gross + total_cost) if side is Side.BUY else gross - total_cost
    return CostBreakdown(
        gross=gross,
        commission=charged,
        tax=tax,
        total_cost=total_cost,
        net_cash_delta=net,
        minimum_commission_applied=minimum_applied,
        terms_evidence_state=terms.evidence_state,
        commission_charged=charged,
        commission_net=net_commission,
        commission_rebate=charged - net_commission,
        rebate_due_on=rebate_due_on(session, terms) if session else None,
    )


def cost_drag(
    *,
    price: Decimal,
    quantity: int,
    terms: BrokerTerms = BrokerTerms(),
) -> Decimal:
    """Round-trip cost as a fraction of the entry notional.

    Answers the M0 question of whether a trade's realistic all-in cost
    consumes the expected edge, which matters most at NT$10,000 where the
    minimum commission dominates.
    """

    buy = trade_costs(side=Side.BUY, price=price, quantity=quantity, terms=terms)
    sell = trade_costs(side=Side.SELL, price=price, quantity=quantity, terms=terms)
    return (buy.total_cost + sell.total_cost) / buy.gross


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal
    reference_price: Decimal
    validity: OrderValidity = OrderValidity.ROD


@dataclass(frozen=True)
class OrderCheck:
    accepted: bool
    reasons: tuple[str, ...] = field(default=())
    lot_type: LotType | None = None
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None


def validate_order(request: OrderRequest) -> OrderCheck:
    """Reject an order that the exchange itself would not accept.

    This is a rules check only. Tradability also depends on market status and
    point-in-time universe membership, which live in M3 and must be checked
    separately; passing here is not permission to trade.
    """

    reasons: list[str] = []
    lot_type: LotType | None = None
    try:
        lot_type = classify_lot(request.quantity)
    except RuleError as exc:
        reasons.append(str(exc))

    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    try:
        limit_up, limit_down = price_limits(request.reference_price)
    except RuleError as exc:
        reasons.append(str(exc))

    if limit_up is not None and limit_down is not None:
        if request.limit_price > limit_up:
            reasons.append("limit price above the official limit-up price")
        if request.limit_price < limit_down:
            reasons.append("limit price below the official limit-down price")

    try:
        if not is_on_tick(request.limit_price):
            reasons.append("limit price is not on the tick grid")
    except RuleError as exc:
        reasons.append(str(exc))

    if lot_type is LotType.ODD and request.validity is not OrderValidity.ROD:
        # Intraday odd-lot trading accepts limit ROD orders only.
        reasons.append("odd-lot orders must be limit ROD")

    return OrderCheck(
        accepted=not reasons,
        reasons=tuple(reasons),
        lot_type=lot_type,
        limit_up=limit_up,
        limit_down=limit_down,
    )
