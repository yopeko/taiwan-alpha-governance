"""The broker terms this project has actually seen, with their provenance.

Until now these numbers lived in prose. `docs/adr/0002` carries a sensitivity
table, `docs/evidence/m3-owner-decisions-d14-d15-2026-08-25.md` carries the
source register, and `docs/m5-fee-rebate-change-spec.md` carries the rebate
mechanics -- three documents, and the only executable copy was a set of
research defaults in `BrokerTerms` that belong to nobody.

Prose cannot be wired to a test. That is the whole reason this file exists,
and the reason it carries `evidence_state` on every set: M0 section 4.2 says
an assumption must not read as a verified fact, and a Decimal in a source file
reads as a verified fact unless something next to it says otherwise.

Three evidence states appear here, and they are not interchangeable:

    assumption              M0's research defaults. Nobody's terms.
    publisher-published-rate  On the broker's own page on a recorded date.
                            Not a signed agreement.
    owner-supplied          The Owner answered a question the page is silent
                            on. Weaker than the publisher stating it, and the
                            only reason it is not `assumption` is that a named
                            person answered on a recorded date.

M10 stays `blocked` regardless of what is in this file. None of these is a
signed broker agreement, and a canary trades real money.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from m4.rules import BrokerTerms  # noqa: E402

SOURCE_URL = "https://www.sinotrade.com.tw/newweb/Fee_Rate/?market=S"
SOURCE_INSTITUTION = "永豐金證券股份有限公司"
CAPTURED_ON = date(2026, 8, 25)

# The published schedule. Undated on purpose: it is the standing rate, and
# what it will be in 2028 is not something the capture can say.
SINOPAC_PUBLISHED = BrokerTerms(
    commission_rate=Decimal("0.001425"),
    minimum_commission=Decimal("20"),
    evidence_state="publisher-published-rate",
    source=f"{SOURCE_INSTITUTION} {SOURCE_URL} captured {CAPTURED_ON}",
)

# The 2026 promotion. Charged in full at execution and returned on the 15th of
# the following month, so one fill has two costs -- see the M5 fee rebate
# change spec.
#
# The window is the point. The promotion moves the minimum commission from
# NT$20 to NT$1, which on a NT$904 position is the difference between a 4.67%
# round trip and a 0.44% one. It runs for 2026 and then it does not.
#
# The end date is `owner-supplied`: the captured page said "2026 限時優惠" and
# named no closing date. Until the Owner answered on 2026-08-25 this was an
# expiry of unknown date, which is worse than a known one because nothing can
# be scheduled against it. Now something can, and
# `tests/unit/test_broker_terms_provenance.py` is that something.
PROMOTION_EXPIRES = date(2026, 12, 31)

SINOPAC_PROMOTIONAL_2026 = BrokerTerms(
    commission_rate=Decimal("0.001425"),
    minimum_commission=Decimal("20"),
    rebate_commission_rate=Decimal("0.000285"),
    rebate_minimum_commission=Decimal("1"),
    rebate_payment_day=15,
    effective_from=date(2026, 1, 1),
    effective_through=PROMOTION_EXPIRES,
    evidence_state="owner-supplied",
    source=(
        f"{SOURCE_INSTITUTION} {SOURCE_URL} captured {CAPTURED_ON}; "
        "promotion window and odd-lot billing owner-supplied 2026-08-25"
    ),
)

# The five odd-lot questions the captured page does not answer, and the
# answers given on 2026-08-25. Recorded as data because three of them are
# already load-bearing: the third decides whether a scale-out pays one minimum
# or several, and the fifth is why `_truncate_to_dollar` rounds down.
ODD_LOT_BILLING = {
    "intraday_odd_lots_use_the_listed_schedule": True,
    "promotional_minimum_applies_to_odd_lots": True,
    "minimum_is_charged_per_filled_order_not_aggregated_daily": True,
    "rebate_applies_to_odd_lots": True,
    "commission_fraction_is_truncated_down": True,
}

ODD_LOT_BILLING_EVIDENCE = "owner-supplied"
ODD_LOT_BILLING_ANSWERED_ON = date(2026, 8, 25)

# The four the captured page is silent on and the M5 fee-rebate spec listed as
# unresolved. Answered 2026-08-28, same evidence state as the odd-lot set.
#
# Two of them decide whether a modelling choice already made was right.
#
# `rebate_receivable_survives_account_closure`: the ledger counts an unpaid
# rebate towards NAV but never towards buying power. That is only defensible
# if the money actually arrives. Closing an account requires settling first --
# the branch will not complete a closure while a rebate is outstanding -- so
# it does.
#
# `statement_granularity_is_per_fill`: invariant 4 requires every fee to trace
# back to an order or fill, and the rebate arrives as one monthly lump. It is
# reconcilable because the broker's electronic statement itemises the rebate
# per fill, and the month's items sum to the lump.
REBATE_MECHANICS = {
    "statement_granularity_is_per_fill": True,
    "monthly_lump_reconciles_to_itemised_statement": True,
    "electronic_volume_cap_is_per_calendar_month": True,
    "over_cap_is_tiered_not_forfeited": True,
    "rebate_receivable_survives_account_closure": True,
    "rebate_survives_early_termination_for_fills_already_made": True,
}

REBATE_MECHANICS_EVIDENCE = "owner-supplied"
REBATE_MECHANICS_ANSWERED_ON = date(2026, 8, 28)

# The promotional tier ceiling, and what applies above it. Neither scale this
# project runs at can reach it -- the reference scale turns over roughly
# NT$385k a month against a NT$1m cap -- but "cannot reach" is not "does not
# exist", and a model that silently ignored the tier would be wrong for a
# larger account rather than merely inapplicable.
PROMOTION_MONTHLY_TURNOVER_CAP = Decimal("1000000")
PROMOTION_OVER_CAP_DISCOUNT = Decimal("0.38")

# What is still missing before M10 can stop being blocked. Not the fee rules
# -- those are answered, at the states above. These two are different things
# that the fee question kept getting confused with.
M10_OUTSTANDING = {
    "signed-broker-agreement": (
        "every set here is a published page or an answer, not a contract. "
        "M0 section 7.2 asks for terms confirmed against a signed agreement"
    ),
    "odd-lot-fill-evidence": (
        "whether an odd-lot order would have filled at all. Daily bars cannot "
        "say, and this is a question about the market rather than about fees "
        "-- see the M1 reuse audit. Answering the billing questions did not "
        "touch it"
    ),
}
