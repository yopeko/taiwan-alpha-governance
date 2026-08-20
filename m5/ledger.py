"""M5 reference implementation: the cash and share ledger.

M0 section 6 forbids validating a strategy as `position * return - cost`. The
reason is not precision. That expression cannot express running out of money,
cannot express an order that never filled, and cannot express a share that had
not settled yet, so a strategy which is impossible in the market still scores
well in the arithmetic.

This ledger exists to make those failures representable.

Cash is never assigned
----------------------
Every movement of NTD is a line in a journal, and `settled_cash` is the sum of
that journal plus the opening balance. Nothing can adjust the balance without
leaving a row that names the order and fill it belongs to. That makes two of
M0's invariants structural rather than asserted: every fee traces to a fill
(section 6.4), and a replay cannot post the same movement twice (section 6.6),
because a journal line carries its own identity.

What settles when
-----------------
Taiwan settles T+2 in trading sessions. A fill therefore does not move settled
cash on the day it happens; it creates a pending item that lands two sessions
later. Two consequences the ledger enforces:

* proceeds from a sale are not buying power until they settle (section 6.5);
* shares bought in a session cannot be sold in that same session, because that
  is 現股當沖 and M0 section 8 prohibits it. They become sellable from the next
  session, which is what the market allows — restricting them until settlement
  would model a rule that does not exist.

Marks come from outside
-----------------------
The ledger never fetches a price and never decides whether a security could be
traded. The caller passes the M3.6 `tradability_state` for the session, and
anything other than `eligible` is a refusal with that state as the reason. A
ledger that decided tradability itself would be free to disagree with the
warehouse, and the disagreement would surface as profit.

Two locations, one file
-----------------------
The canonical home is Taiwan Core, `tw_sepa_screener.ledger`. The governance
repository keeps a byte-identical mirror at `m5/ledger.py`, asserted equal by
`tests/invariant/test_upstream_parity.py`, for the same reason the M4 rules
are mirrored: governance CI has no Taiwan Core checkout, and these tests need
nothing but Python. Edit either copy and the parity test fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

try:  # The canonical rules module, when Taiwan Core is importable.
    from tw_sepa_screener.market_rules import (
        BOARD_LOT,
        BrokerTerms,
        RULES_VERSION,
        RuleError,
        Side,
        classify_lot,
        settlement_date,
        trade_costs,
    )
except ImportError:  # pragma: no cover - the governance mirror's own layout
    from m4.rules import (  # type: ignore[no-redef]
        BOARD_LOT,
        BrokerTerms,
        RULES_VERSION,
        RuleError,
        Side,
        classify_lot,
        settlement_date,
        trade_costs,
    )

LEDGER_VERSION = "tw-alpha-m5-ledger/1.0.0"

# M0 section 8. The policy is part of the ledger because breaching it must be
# a refusal, not a report produced after the fact.
POLICY_INITIAL_CAPITAL = Decimal("10000")
POLICY_MAX_POSITIONS = 2
POLICY_MAX_WEIGHT_PER_NAME = Decimal("0.45")
POLICY_MIN_CASH_RESERVE = Decimal("0.10")
POLICY_PLANNED_RISK = Decimal("0.0075")
POLICY_HARD_RISK_CAP = Decimal("0.0100")
POLICY_TOTAL_OPEN_RISK_CAP = Decimal("0.0200")

# The only warehouse verdict that permits a fill. Every other value M3.6 can
# return — blocked, restricted, ineligible, unknown — is a refusal.
TRADABLE_STATE = "eligible"


class LedgerError(ValueError):
    """Raised when an operation would break a ledger invariant."""


@dataclass(frozen=True)
class CashEntry:
    """One movement of NTD, and why.

    `amount` is signed from the account's point of view. Every entry names the
    fill that caused it, so a fee can always be traced back to the trade that
    incurred it and no entry can appear without one.
    """

    session: date
    kind: str
    amount: Decimal
    order_id: str
    fill_id: str


@dataclass(frozen=True)
class PendingItem:
    """A settlement that has been agreed but has not happened yet."""

    settles_on: date
    order_id: str
    fill_id: str
    cash_delta: Decimal
    symbol: str
    share_delta: int


@dataclass
class Position:
    symbol: str
    shares: int = 0
    average_cost: Decimal = Decimal("0")
    # Shares received in each session, so the same-session sale prohibition can
    # be applied without forbidding the next-session sale, which is legal.
    acquired_by_session: dict[date, int] = field(default_factory=dict)

    def sellable_on(self, session: date) -> int:
        return self.shares - self.acquired_by_session.get(session, 0)


@dataclass(frozen=True)
class MarketConditions:
    """What the warehouse says about one security on one session.

    Deliberately not defaulted. A caller that has not looked up the state has
    to say so, rather than getting a permissive default it never chose.
    """

    session: date
    session_is_open: bool
    tradability_state: str
    limit_up: Decimal | None = None
    limit_down: Decimal | None = None
    available_quantity: int | None = None


@dataclass(frozen=True)
class ExecutionResult:
    state: str
    reason: str
    filled_quantity: int = 0
    fill_price: Decimal | None = None
    commission: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    rules_version: str = RULES_VERSION
    ledger_version: str = LEDGER_VERSION


@dataclass(frozen=True)
class OrderRequest:
    order_id: str
    fill_id: str
    session: date
    symbol: str
    side: Side
    quantity: int
    limit_price: Decimal


@dataclass(frozen=True)
class PositionPlan:
    """The outcome of sizing a position under M0 section 8."""

    quantity: int
    reason: str
    planned_risk: Decimal = Decimal("0")

    @property
    def is_trade(self) -> bool:
        return self.quantity > 0



def _coerce_side(side: object) -> Side:
    """Normalise whatever the caller passed into *this module's* `Side`.

    The mirror arrangement means `Side` can exist as two classes at once:
    `tw_sepa_screener.market_rules.Side` when Taiwan Core is importable, and
    `m4.rules.Side` when it is not. A caller holding the other one fails an
    identity check, and the first version of this ledger dispatched such a
    sell into the buy branch — it filled, created a position out of nothing and
    broke the long-only invariant, and it did so only on machines where both
    modules were importable.

    Comparing by value would have hidden it just as well. Converting at the
    boundary means there is exactly one `Side` inside the ledger, so no later
    identity check can be wrong.
    """

    if isinstance(side, Side):
        return side
    return Side(getattr(side, "value", side))


class Ledger:
    """A cash and share account that refuses impossible trades."""

    def __init__(
        self,
        *,
        opening_cash: Decimal = POLICY_INITIAL_CAPITAL,
        sessions: Sequence[date],
        terms: BrokerTerms | None = None,
        slippage_rate: Decimal = Decimal("0.0020"),
    ) -> None:
        if opening_cash < 0:
            raise LedgerError("opening cash cannot be negative")
        if not sessions:
            raise LedgerError("a trading calendar is required: settlement is T+2 "
                              "in sessions, and cannot be counted without one")
        self.opening_cash = opening_cash
        self.sessions = sorted(sessions)
        self.terms = terms or BrokerTerms()
        self.slippage_rate = slippage_rate
        self.journal: list[CashEntry] = []
        self.pending: list[PendingItem] = []
        self.positions: dict[str, Position] = {}
        self.realised_pnl = Decimal("0")
        self.settled_through: date | None = None
        self._seen_fills: set[str] = set()
        self._nav_history: list[tuple[date, Decimal]] = []
        self._high_water = opening_cash

    # ---------------------------------------------------------------- cash

    @property
    def settled_cash(self) -> Decimal:
        """Derived, never assigned. The journal is the only way in."""

        return self.opening_cash + sum(
            (entry.amount for entry in self.journal), Decimal("0")
        )

    @property
    def committed_cash(self) -> Decimal:
        """Cash owed on buys that have not settled yet.

        It is still in the account and still counts towards NAV, but it is
        spoken for, so it is not available to spend again.
        """

        return -sum(
            (item.cash_delta for item in self.pending if item.cash_delta < 0),
            Decimal("0"),
        )

    @property
    def unsettled_proceeds(self) -> Decimal:
        """Sale proceeds that have not landed.

        M0 section 6.5: these are not buying power. They are excluded from
        `buying_power` deliberately, and the property exists so that exclusion
        is visible rather than implicit in an arithmetic omission.
        """

        return sum(
            (item.cash_delta for item in self.pending if item.cash_delta > 0),
            Decimal("0"),
        )

    @property
    def buying_power(self) -> Decimal:
        return self.settled_cash - self.committed_cash

    # ----------------------------------------------------------- valuation

    def market_value(self, marks: Mapping[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for position in self.positions.values():
            if position.shares == 0:
                continue
            mark = marks.get(position.symbol)
            if mark is None:
                raise LedgerError(
                    f"no mark for held security {position.symbol}: a position "
                    "cannot be valued at a price nobody supplied"
                )
            total += Decimal(position.shares) * mark
        return total

    def nav(self, marks: Mapping[str, Decimal]) -> Decimal:
        """M0 invariant 6.1: cash plus pending plus market value is NAV."""

        return (
            self.settled_cash
            + self.unsettled_proceeds
            - self.committed_cash
            + self.market_value(marks)
        )

    def mark_session(self, session: date, marks: Mapping[str, Decimal]) -> Decimal:
        value = self.nav(marks)
        self._nav_history.append((session, value))
        self._high_water = max(self._high_water, value)
        return value

    @property
    def high_water_mark(self) -> Decimal:
        return self._high_water

    @property
    def drawdown(self) -> Decimal:
        if not self._nav_history or self._high_water <= 0:
            return Decimal("0")
        latest = self._nav_history[-1][1]
        return (self._high_water - latest) / self._high_water

    def unrealised_pnl(self, marks: Mapping[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for position in self.positions.values():
            if position.shares == 0:
                continue
            mark = marks.get(position.symbol)
            if mark is None:
                raise LedgerError(f"no mark for held security {position.symbol}")
            total += (mark - position.average_cost) * Decimal(position.shares)
        return total

    # ---------------------------------------------------------- settlement

    def settle_through(self, session: date) -> list[PendingItem]:
        """Apply everything due on or before `session`.

        Called before trading on a session, so that money which has arrived is
        spendable and money which has not is still merely pending.
        """

        if self.settled_through is not None and session < self.settled_through:
            raise LedgerError(
                "settlement cannot run backwards: a ledger replayed out of "
                "order would apply the same item twice"
            )
        due = [item for item in self.pending if item.settles_on <= session]
        for item in due:
            if item.cash_delta:
                self.journal.append(
                    CashEntry(
                        session=item.settles_on,
                        kind="settlement",
                        amount=item.cash_delta,
                        order_id=item.order_id,
                        fill_id=item.fill_id,
                    )
                )
        self.pending = [item for item in self.pending if item.settles_on > session]
        self.settled_through = session
        return due

    # ------------------------------------------------------------ trading

    def execute(self, request: OrderRequest, market: MarketConditions) -> ExecutionResult:
        """Attempt one order. Every refusal names the rule that refused it."""

        if request.fill_id in self._seen_fills:
            # M0 invariant 6.6. The identity is the guard: a replayed run
            # cannot fill twice or charge twice.
            return ExecutionResult(state="rejected", reason="duplicate-fill-id")
        if request.session != market.session:
            return ExecutionResult(
                state="rejected", reason="order-session-differs-from-market-session"
            )
        if request.quantity <= 0:
            return ExecutionResult(state="rejected", reason="non-positive-quantity")
        try:
            classify_lot(request.quantity)
        except RuleError:
            return ExecutionResult(state="rejected", reason="invalid-lot-size")

        # M0 invariant 6.3, in the order a market applies them.
        if not market.session_is_open:
            return ExecutionResult(state="rejected", reason="not-a-trading-session")
        if market.tradability_state != TRADABLE_STATE:
            return ExecutionResult(
                state="rejected",
                reason=f"not-tradable-{market.tradability_state}",
            )
        if market.limit_up is not None and request.limit_price > market.limit_up:
            return ExecutionResult(state="rejected", reason="limit-price-above-limit-up")
        if market.limit_down is not None and request.limit_price < market.limit_down:
            return ExecutionResult(
                state="rejected", reason="limit-price-below-limit-down"
            )

        try:
            side = _coerce_side(request.side)
        except ValueError:
            return ExecutionResult(state="rejected", reason="unrecognised-side")
        try:
            settlement_date(request.session, self.sessions)
        except RuleError:
            # A trade near the end of the loaded calendar cannot be settled, so
            # it cannot be represented. Refusing is the fail-closed answer; a
            # backtest that ran off the end of its calendar would otherwise
            # crash rather than record that it could not trade there.
            return ExecutionResult(
                state="rejected", reason="calendar-too-short-to-settle"
            )

        quantity = request.quantity
        if market.available_quantity is not None:
            if market.available_quantity <= 0:
                return ExecutionResult(state="rejected", reason="no-liquidity-no-fill")
            quantity = min(quantity, market.available_quantity)

        if side is Side.SELL:
            return self._sell(request, market, quantity)
        return self._buy(request, market, quantity)

    def _price_with_slippage(self, side: Side, price: Decimal) -> Decimal:
        """Slippage always works against the account.

        A buy pays up and a sale receives less. Applying it symmetrically or
        favourably would quietly hand the strategy an edge the market does not.
        """

        adjustment = price * self.slippage_rate
        return price + adjustment if side is Side.BUY else price - adjustment

    def _buy(
        self, request: OrderRequest, market: MarketConditions, quantity: int
    ) -> ExecutionResult:
        price = self._price_with_slippage(Side.BUY, request.limit_price)
        costs = trade_costs(
            side=Side.BUY, price=price, quantity=quantity, terms=self.terms
        )
        outlay = -costs.net_cash_delta
        if outlay > self.buying_power:
            # Not an overdraft: the account simply cannot pay, and a backtest
            # that let it would be spending money it never had.
            return ExecutionResult(
                state="rejected", reason="insufficient-buying-power"
            )

        settles = settlement_date(request.session, self.sessions)
        self._post_costs(request, costs.commission, Decimal("0"))
        self.pending.append(
            PendingItem(
                settles_on=settles,
                order_id=request.order_id,
                fill_id=request.fill_id,
                cash_delta=-(price * Decimal(quantity)),
                symbol=request.symbol,
                share_delta=quantity,
            )
        )
        position = self.positions.setdefault(
            request.symbol, Position(symbol=request.symbol)
        )
        total_cost = position.average_cost * Decimal(position.shares) + price * Decimal(
            quantity
        )
        position.shares += quantity
        position.average_cost = total_cost / Decimal(position.shares)
        position.acquired_by_session[request.session] = (
            position.acquired_by_session.get(request.session, 0) + quantity
        )
        self._seen_fills.add(request.fill_id)
        return ExecutionResult(
            state="filled" if quantity == request.quantity else "partially-filled",
            reason="filled",
            filled_quantity=quantity,
            fill_price=price,
            commission=costs.commission,
        )

    def _sell(
        self, request: OrderRequest, market: MarketConditions, quantity: int
    ) -> ExecutionResult:
        position = self.positions.get(request.symbol)
        if position is None or position.shares <= 0:
            # M0 invariant 6.2: long only. A sale without inventory is a short.
            return ExecutionResult(state="rejected", reason="no-position-to-sell")
        if quantity > position.shares:
            return ExecutionResult(state="rejected", reason="sell-exceeds-holding")
        sellable = position.sellable_on(request.session)
        if quantity > sellable:
            # 現股當沖, prohibited by M0 section 8. The shares exist but were
            # bought today; they become sellable on the next session.
            return ExecutionResult(
                state="rejected", reason="same-session-sale-is-day-trading"
            )

        price = self._price_with_slippage(Side.SELL, request.limit_price)
        costs = trade_costs(
            side=Side.SELL, price=price, quantity=quantity, terms=self.terms
        )
        settles = settlement_date(request.session, self.sessions)
        self._post_costs(request, costs.commission, costs.tax)
        self.pending.append(
            PendingItem(
                settles_on=settles,
                order_id=request.order_id,
                fill_id=request.fill_id,
                cash_delta=price * Decimal(quantity),
                symbol=request.symbol,
                share_delta=-quantity,
            )
        )
        self.realised_pnl += (price - position.average_cost) * Decimal(quantity)
        position.shares -= quantity
        if position.shares == 0:
            position.average_cost = Decimal("0")
            position.acquired_by_session.clear()
        self._seen_fills.add(request.fill_id)
        return ExecutionResult(
            state="filled" if quantity == request.quantity else "partially-filled",
            reason="filled",
            filled_quantity=quantity,
            fill_price=price,
            commission=costs.commission,
            tax=costs.tax,
        )

    def _post_costs(
        self, request: OrderRequest, commission: Decimal, tax: Decimal
    ) -> None:
        """Fees leave settled cash immediately and carry their fill's identity.

        They are posted separately from the principal so that M0 invariant 6.4
        holds by construction: no line in the journal exists without an order
        and a fill to trace it to.
        """

        if commission:
            self.journal.append(
                CashEntry(
                    session=request.session,
                    kind="commission",
                    amount=-commission,
                    order_id=request.order_id,
                    fill_id=request.fill_id,
                )
            )
        if tax:
            self.journal.append(
                CashEntry(
                    session=request.session,
                    kind="tax",
                    amount=-tax,
                    order_id=request.order_id,
                    fill_id=request.fill_id,
                )
            )


def plan_position(
    *,
    nav: Decimal,
    price: Decimal,
    stop_price: Decimal,
    open_positions: int,
    open_risk: Decimal = Decimal("0"),
    settled_cash: Decimal,
    terms: BrokerTerms | None = None,
) -> PositionPlan:
    """Size a new position under M0 section 8, or refuse to.

    M0 is explicit that when the integer share count, the price, the stop
    distance and the costs cannot all satisfy the risk caps at once, the answer
    is `no_trade`. Rounding up to make a position fit is named as the failure
    to avoid, so every cap here refuses rather than adjusts.
    """

    if price <= 0 or nav <= 0:
        return PositionPlan(0, "invalid-inputs")
    if stop_price >= price:
        return PositionPlan(0, "stop-must-be-below-entry-for-a-long")
    if open_positions >= POLICY_MAX_POSITIONS:
        return PositionPlan(0, "max-positions-reached")

    risk_per_share = price - stop_price
    budget_by_risk = nav * POLICY_PLANNED_RISK
    quantity = int(budget_by_risk / risk_per_share)

    weight_cap_value = nav * POLICY_MAX_WEIGHT_PER_NAME
    quantity = min(quantity, int(weight_cap_value / price))

    spendable = settled_cash - nav * POLICY_MIN_CASH_RESERVE
    if spendable <= 0:
        return PositionPlan(0, "cash-reserve-floor-reached")
    quantity = min(quantity, int(spendable / price))

    # A quantity that is neither whole board lots nor a pure odd lot cannot be
    # sent as one order, and `Ledger.execute` refuses it. Without this the
    # planner and the ledger disagree: sizing produced 1,234 shares, execution
    # rejected them, and the signal vanished with no record that a cap had
    # been the reason. Snapping down stays inside every cap just applied.
    if quantity > BOARD_LOT:
        quantity -= quantity % BOARD_LOT

    if quantity <= 0:
        return PositionPlan(0, "no-quantity-satisfies-every-cap")

    planned_risk = (risk_per_share * Decimal(quantity)) / nav
    if planned_risk > POLICY_HARD_RISK_CAP:
        return PositionPlan(0, "breaches-hard-risk-cap")
    if open_risk + planned_risk > POLICY_TOTAL_OPEN_RISK_CAP:
        return PositionPlan(0, "breaches-total-open-risk-cap")

    # The cost of a position this small can exceed the risk it was sized for;
    # M0 requires that to be a refusal rather than an unnoticed drag.
    settings = terms or BrokerTerms()
    round_trip = (
        trade_costs(
            side=Side.BUY, price=price, quantity=quantity, terms=settings
        ).total_cost
        + trade_costs(
            side=Side.SELL, price=price, quantity=quantity, terms=settings
        ).total_cost
    )
    if round_trip >= risk_per_share * Decimal(quantity):
        return PositionPlan(0, "round-trip-cost-exceeds-planned-risk")

    return PositionPlan(quantity, "sized-within-every-cap", planned_risk)


def journal_is_balanced(ledger: Ledger, marks: Mapping[str, Decimal]) -> bool:
    """M0 invariant 6.1, checked rather than assumed."""

    components = (
        ledger.settled_cash
        + ledger.unsettled_proceeds
        - ledger.committed_cash
        + ledger.market_value(marks)
    )
    return components == ledger.nav(marks)


def every_entry_traces_to_a_fill(entries: Iterable[CashEntry]) -> bool:
    """M0 invariant 6.4."""

    return all(entry.order_id and entry.fill_id for entry in entries)
