"""M4 reference implementation: Taiwan common-stock trading rules.

Scope is M0's universe: TWSE and TPEx domestic common stock, long-only cash
equity. ETFs, bond ETFs, warrants and emerging-board securities are out of
scope and are rejected rather than silently priced with the wrong table.

Every constant here is either derived from captured official data or marked
as requiring broker confirmation. See
docs/contracts/m4-market-rules-contract.md for the evidence behind each.

This module is deliberately pure: no I/O, no network, no clock. Callers pass
in the trading calendar and the reference prices they already hold.
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
) -> tuple[Decimal, Decimal, str]:
    """Prefer the publisher's own limit prices; compute only as a fallback.

    Returns (limit_up, limit_down, basis).

    Validation against 1,665 official ex-right records showed the plain ten
    percent rule reproduces the published limits on 94.5% of them. The
    remaining cases are ex-rights sessions whose limits follow a separate
    official formula that this module does not implement. On such a session
    without published limits the result is `blocked` rather than a computed
    guess, because a wrong limit silently changes what an order engine
    believes is executable.
    """

    if official_limit_up is not None and official_limit_down is not None:
        return official_limit_up, official_limit_down, "publisher-exact"
    if is_ex_rights_session:
        raise RuleError(
            "ex-rights session without published limit prices: the special "
            "official formula is not implemented, so limits are blocked"
        )
    up, down = price_limits(reference_price)
    return up, down, "computed-standard-10pct"


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


@dataclass(frozen=True)
class CostBreakdown:
    gross: Decimal
    commission: Decimal
    tax: Decimal
    total_cost: Decimal
    net_cash_delta: Decimal
    minimum_commission_applied: bool
    terms_evidence_state: str
    rules_version: str = RULES_VERSION


def _truncate_to_dollar(value: Decimal) -> Decimal:
    """Taiwan brokers bill whole NTD, truncating the fraction."""

    return value.to_integral_value(rounding=ROUND_DOWN)


def trade_costs(
    *,
    side: Side,
    price: Decimal,
    quantity: int,
    terms: BrokerTerms = BrokerTerms(),
) -> CostBreakdown:
    """Full NTD cost of one fill, including the minimum commission.

    `net_cash_delta` is negative for a buy (cash leaves) and positive for a
    sell (cash arrives), both already net of costs.
    """

    if quantity <= 0:
        raise RuleError("quantity must be positive")
    if price <= 0:
        raise RuleError("price must be positive")

    gross = price * quantity
    raw_commission = gross * terms.commission_rate * terms.commission_discount
    commission = _truncate_to_dollar(raw_commission)
    minimum_applied = False
    if commission < terms.minimum_commission:
        commission = terms.minimum_commission
        minimum_applied = True

    tax = (
        _truncate_to_dollar(gross * terms.sell_tax_rate)
        if side is Side.SELL
        else Decimal("0")
    )
    total_cost = commission + tax
    net = -(gross + total_cost) if side is Side.BUY else gross - total_cost
    return CostBreakdown(
        gross=gross,
        commission=commission,
        tax=tax,
        total_cost=total_cost,
        net_cash_delta=net,
        minimum_commission_applied=minimum_applied,
        terms_evidence_state=terms.evidence_state,
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
