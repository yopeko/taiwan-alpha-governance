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

Four evidence states appear here, and they are not interchangeable:

    assumption              M0's research defaults. Nobody's terms.
    publisher-archived-privately
                            The publisher's own document, kept with its bytes
                            and a hash -- but kept in `private/`, not here.
                            The hash is published so a reader who fetches the
                            document can still check it has not changed; what
                            they cannot do is find it from this repository.
                            A real downgrade from the archived-and-published
                            state, named so it is visible in the type rather
                            than only in a document. See
                            docs/evidence/broker-terms-provenance-2026-08-29.md.
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

# The publisher's own fee-rate page, and the institution that publishes it.
# Both are withheld here: together with the account-opening date they form a
# personal financial profile, and this repository publishes the terms, not
# whose terms they are. The URL and the archive live in `private/`.
#
# What withholding costs, stated because it is a cost: provenance for the
# published schedule rested on the URL (the document does not name its own
# publisher -- checked, not assumed). With the URL withheld it rests on the
# sha256 below, which anyone can recompute against the document they fetch
# themselves. That is weaker for a reader who does not know where to fetch
# it, and `docs/evidence/broker-terms-provenance-2026-08-29.md` says so.
SOURCE_REF = "(withheld) publisher fee-rate page"
SOURCE_INSTITUTION = "(withheld)"
CAPTURED_ON = date(2026, 8, 25)

# The published schedule, archived 2026-08-29 with its bytes and a hash, kept
# at private/broker-evidence/ and deliberately not published. Dated
# 2024-11-28 by the document itself.
#
# What it proves: the standing rate of 1.425 per mille with a NT$20 minimum,
# and the rebate mechanism -- "charged in full, returned on the 15th of the
# following month, **earlier if that is a holiday**". That last clause is the
# one the ledger models against, and it now has a document instead of a
# reading of a web page.
#
# What it does not contain, checked rather than assumed:
#
#   the broker's name        (so nothing is lost by withholding the URL:
#                             the document never carried the identity)
#   the 2026 promotion       (no 2-tenths discount, no NT$1 minimum)
#   odd-lot commission       ("零股領回 40 元" is a withdrawal service fee,
#                             not a trading commission)
#   any expiry date
#
# So archiving it upgrades the terms that make a NT$904 round trip cost 4.67%,
# and leaves untouched the terms that make it 0.44% -- which are the ones the
# cost model has been using. The promotion still has no document behind it.
PUBLISHED_PDF_SHA256 = (
    "f95ddd8462b093cd2cbd7a3c7fe4d6519ec48713acde9593870dab4efbe44b30"
)
PUBLISHED_PDF_DOCUMENT_DATE = date(2024, 11, 28)
PUBLISHED_PDF_ARCHIVED_ON = date(2026, 8, 29)
PUBLISHED_PDF_PATH = "private/broker-evidence/published-service-charge-2024-11-28.pdf"

# The published schedule. Undated on purpose: it is the standing rate, and
# what it will be in 2028 is not something the capture can say.
BROKER_PUBLISHED = BrokerTerms(
    commission_rate=Decimal("0.001425"),
    minimum_commission=Decimal("20"),
    evidence_state="publisher-archived-privately",
    source=(
        f"{SOURCE_INSTITUTION} {SOURCE_REF}; archived PDF dated "
        f"{PUBLISHED_PDF_DOCUMENT_DATE}, sha256 {PUBLISHED_PDF_SHA256[:16]}…, "
        f"kept at {PUBLISHED_PDF_PATH}"
    ),
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

BROKER_PROMOTIONAL_2026 = BrokerTerms(
    commission_rate=Decimal("0.001425"),
    minimum_commission=Decimal("20"),
    rebate_commission_rate=Decimal("0.000285"),
    rebate_minimum_commission=Decimal("1"),
    rebate_payment_day=15,
    effective_from=date(2026, 1, 1),
    effective_through=PROMOTION_EXPIRES,
    evidence_state="publisher-stated-via-owner-screenshot",
    source=(
        f"{SOURCE_INSTITUTION} {SOURCE_REF}; page transcribed from an Owner "
        "screenshot 2026-08-29 (private/broker-evidence/"
        "published-fee-page-promotion-2026-08-29.md). The end date, odd-lot "
        "applicability and over-cap tiering remain owner-supplied"
    ),
)

# D19, 2026-08-29. The default cost basis for every report is the published
# schedule, not the promotion.
#
# At M0's risk policy a NT$904 round trip costs 4.67% published and 0.44%
# promotional. The published figure rests on an archived PDF with a hash; the
# promotional one rests on a transcription of a screenshot, and **no document
# connects that promotion to this account** -- the account-opening
# confirmation, checked on 2026-08-29, returns the same published schedule.
#
# A tenfold advantage with no document tying it to this account is not
# something a conclusion should assume by default.
#
# No code change was needed: `BrokerTerms()` already defaults to the published
# schedule with no rebate, and all sixteen trials ran under it. What was
# missing was anyone saying which one was the default.
REPORTING_DEFAULT_TERMS = BROKER_PUBLISHED

# D20, 2026-08-29: the archived PDF is not merely the default, it is the
# account's terms. No document connects the promotion to this account, and the
# Owner decided that absence settles it.
#
# What that costs, stated because it is a cost and not an improvement: the
# account was opened online, which is the promotion's own stated condition, so
# the promotion very likely applies economically. Pricing at the published
# schedule **overstates the economic cost of a NT$904 round trip by 4.22
# percentage points** -- 4.67% against 0.44%.
#
# Accepted for the direction of the error. Overstating cost makes a candidate
# harder to pass; it cannot make a strategy without an edge look viable. The
# reverse is asymmetric: pricing on a promotion that turns out not to apply
# builds every conclusion on a cost structure that does not exist, and nothing
# would signal it.
#
# So a candidate that fails under these terms may have been stopped by an
# overstated cost rather than by itself, and that has to be read with the
# result.
ACCOUNT_TERMS = BROKER_PUBLISHED
ACCOUNT_TERMS_SETTLED_ON = date(2026, 8, 29)

# The document that would let this be revisited, and it has a predictable
# date. Per D14/D15 the broker's statement is itemised per fill and names each
# fill's rebate, so the first month this account trades produces a document
# connecting it to the promotional terms -- available on the 15th of the
# following month.
#
# Not a blocker. A recorded path, so that "change the basis back" has a stated
# evidentiary bar rather than becoming a judgement call later.
PROMOTION_EVIDENCE_PATH_IF_REVISITED = (
    "the first monthly statement showing itemised rebate lines for this "
    "account, available on the 15th of the month after it first trades"
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
