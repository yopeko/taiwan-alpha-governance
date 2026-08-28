"""The broker terms, their evidence states, and a tripwire on the promotion.

Two jobs.

The first is ordinary: the numbers in `scripts/lib/broker_terms.py` must match
the source register in the D14/D15 decision record, and each set must carry an
evidence state that is not stronger than what was actually obtained. A Decimal
in a source file reads as a verified fact unless something says otherwise, and
M0 section 4.2 forbids letting an assumption read that way.

The second is unusual and deliberate: one test in this file goes red when the
calendar passes 2026-12-31. That is not a flaky test, it is the mechanism the
M5 fee rebate change spec asked for and could not have. When it was written
the promotion had "an expiry of unknown date, which is harder to manage than a
known one -- no recomputation can be scheduled against it". The Owner supplied
the date on 2026-08-25, so now one can be, and this is it.

What it protects. The promotion takes the minimum commission from NT$20 to
NT$1. On the NT$904 position M0's risk policy produces, that is a round-trip
cost of 0.44% instead of 4.67% -- a tenfold difference in the number that
decides whether any of this is viable. A cost model built on a promotion
carries its expiry, and the failure mode is not that the model breaks on the
day it expires. It is that nobody notices.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "lib"))

from broker_terms import (  # noqa: E402
    CAPTURED_ON,
    M10_OUTSTANDING,
    PROMOTION_MONTHLY_TURNOVER_CAP,
    PUBLISHED_PDF_PATH,
    PUBLISHED_PDF_SHA256,
    REPORTING_DEFAULT_TERMS,
    PROMOTION_OVER_CAP_DISCOUNT,
    REBATE_MECHANICS,
    ODD_LOT_BILLING,
    ODD_LOT_BILLING_EVIDENCE,
    PROMOTION_EXPIRES,
    SINOPAC_PROMOTIONAL_2026,
    SINOPAC_PUBLISHED,
    SOURCE_URL,
)
from m4.rules import Side, terms_cover, trade_costs  # noqa: E402

DECISION_RECORD = (
    REPO / "docs" / "evidence" / "m3-owner-decisions-d14-d15-2026-08-25.md"
)

# The window the research dataset covers. Named here so the assertion below
# reads as the claim it is making rather than as two magic dates.
BACKTEST_WINDOW = (date(2019, 1, 2), date(2026, 8, 3))


class TestTheNumbersMatchTheSourceRegister:
    """One copy is data, the other is the record. They have to agree."""

    def test_the_published_schedule_is_what_was_captured(self):
        assert SINOPAC_PUBLISHED.commission_rate == Decimal("0.001425")
        assert SINOPAC_PUBLISHED.minimum_commission == Decimal("20")

    def test_the_promotion_is_a_rebate_not_a_discount_at_execution(self):
        """The published wording is charge in full, return on the 15th.

        Modelled as a discount, the account would appear to hold cash it does
        not have for up to 45 days.
        """

        assert SINOPAC_PROMOTIONAL_2026.has_rebate
        assert SINOPAC_PROMOTIONAL_2026.minimum_commission == Decimal("20")
        assert SINOPAC_PROMOTIONAL_2026.rebate_minimum_commission == Decimal("1")
        assert SINOPAC_PROMOTIONAL_2026.rebate_payment_day == 15

    def test_the_source_register_names_the_same_endpoint(self):
        record = DECISION_RECORD.read_text(encoding="utf-8")
        assert SOURCE_URL in record
        assert str(CAPTURED_ON) in record


class TestNoSetClaimsMoreThanItHas:
    """M0 section 4.2. The states are ranked and not interchangeable."""

    def test_the_published_schedule_is_an_archived_document(self):
        """Upgraded 2026-08-29: the PDF is kept with its bytes and a hash, so
        the claim can be re-checked rather than re-read from a live page."""

        assert SINOPAC_PUBLISHED.evidence_state == "publisher-archived-pdf"

    def test_the_archived_pdf_is_present_and_unchanged(self):
        """A hash recorded without the file is a claim about nothing."""

        import hashlib

        pdf = REPO / PUBLISHED_PDF_PATH
        assert pdf.is_file(), f"{PUBLISHED_PDF_PATH} is missing"
        assert (
            hashlib.sha256(pdf.read_bytes()).hexdigest() == PUBLISHED_PDF_SHA256
        )

    def test_the_archived_pdf_does_not_carry_the_promotional_terms(self):
        """The half that matters is the half it does not contain.

        The cost model uses a NT$1 minimum, which makes a NT$904 round trip
        cost 0.44%. This document says NT$20, which makes it 4.67%. Archiving
        it upgrades the terms nobody was using and leaves the ones in use
        exactly where they were: owner-supplied, with no document behind them.

        The account-opening confirmation was expected to close that gap and,
        checked on 2026-08-29, repeats this same schedule.
        """

        text = (
            REPO / "docs" / "evidence" / "broker"
            / "sinopac-service-charge-2024-11-28.txt"
        ).read_text(encoding="utf-8")
        assert "千分之 1.425（低收 20 元）" in text
        assert "2 折" not in text
        assert "低收 1 元" not in text

    def test_the_archived_pdf_does_not_name_the_broker(self):
        """So its provenance still rests on the URL it came from, exactly as
        D14/D15 recorded. Archiving did not change that."""

        text = (
            REPO / "docs" / "evidence" / "broker"
            / "sinopac-service-charge-2024-11-28.txt"
        ).read_text(encoding="utf-8")
        assert "永豐" not in text and "SinoPac" not in text

    def test_the_rebate_clause_the_ledger_models_against_is_in_the_document(self):
        """M5 change spec section 3.4 models the 15th because the wording is
        "earlier if a holiday" -- the latest a rebate can arrive, so the
        receivable is held as long as it possibly could be. That reading now
        has a document rather than a web page."""

        text = (
            REPO / "docs" / "evidence" / "broker"
            / "sinopac-service-charge-2024-11-28.txt"
        ).read_text(encoding="utf-8")
        assert "次月 15 日退回至客戶交割帳戶" in text
        assert "遇假日則提早" in text

    def test_the_reporting_default_is_the_published_schedule(self):
        """D19. The published figure has an archived PDF behind it; the
        promotional one has a transcription of a screenshot and **no document
        connecting it to this account** -- the account-opening confirmation
        returns the same published schedule.

        A tenfold advantage with nothing tying it to this account is not a
        default. `BrokerTerms()` already behaved this way; nobody had said so.
        """

        from m4.rules import BrokerTerms

        assert REPORTING_DEFAULT_TERMS is SINOPAC_PUBLISHED
        assert not REPORTING_DEFAULT_TERMS.has_rebate
        assert REPORTING_DEFAULT_TERMS.minimum_commission == Decimal("20")
        assert BrokerTerms().minimum_commission == Decimal("20")
        assert not BrokerTerms().has_rebate

    def test_m0_names_the_published_schedule_as_the_reporting_basis(self):
        contract = (REPO / "docs" / "m0-project-contract.md").read_text(
            encoding="utf-8"
        )
        assert "m0-v1.4.0" in contract
        assert "預設成本基礎" in contract

    def test_m0_forbids_blockers_built_on_unread_documents(self):
        """The rule D19 added after making the same mistake twice.

        v1.2.0 assumed a signed agreement would carry the promotion; it does
        not. v1.3.0 assumed the account confirmation would state campaign
        rates; it repeats the published schedule. Different consequences, one
        cause: a condition written about a document nobody had opened.
        """

        contract = (REPO / "docs" / "m0-project-contract.md").read_text(
            encoding="utf-8"
        )
        assert "該前提必須先經檢視" in contract

    def test_the_promotion_now_has_publisher_wording_behind_it(self):
        """Upgraded by the fee-page transcription, and the archive says which
        parts were upgraded and which were not."""

        archive = (
            REPO / "docs" / "evidence" / "broker"
            / "sinopac-fee-page-promotion-2026-08-29.md"
        ).read_text(encoding="utf-8")
        assert "2 折 (0.285‰)" in archive
        assert "每筆不足 20 元以 20 元計" in archive
        assert "沒有寫到哪一天" in archive

    def test_the_transcription_states_its_own_weaker_chain(self):
        """Bytes with a hash can be re-checked; a transcription of a
        screenshot cannot. The state name says which one this is."""

        assert (
            SINOPAC_PROMOTIONAL_2026.evidence_state
            == "publisher-stated-via-owner-screenshot"
        )
        archive = (
            REPO / "docs" / "evidence" / "broker"
            / "sinopac-fee-page-promotion-2026-08-29.md"
        ).read_text(encoding="utf-8")
        assert "發布者頁面 → 截圖 → Owner → 轉錄" in archive

    def test_an_answer_the_page_is_silent_on_is_owner_supplied(self):
        """The promotion's end date and the odd-lot rules are both answers.

        Weaker than the publisher stating them. The only thing keeping them
        above `assumption` is that a named person answered on a recorded date.
        """

        assert ODD_LOT_BILLING_EVIDENCE == "owner-supplied"

    def test_the_cost_breakdown_carries_the_state_to_the_caller(self):
        """A number that travels without its provenance arrives as a fact."""

        costs = trade_costs(
            side=Side.BUY,
            price=Decimal("50"),
            quantity=18,
            terms=SINOPAC_PROMOTIONAL_2026,
        )
        assert (
            costs.terms_evidence_state
            == "publisher-stated-via-owner-screenshot"
        )


class TestTheOddLotAnswersAreRecordedNotRemembered:
    def test_all_five_questions_have_an_answer(self):
        assert len(ODD_LOT_BILLING) == 5
        assert all(v is not None for v in ODD_LOT_BILLING.values())

    def test_the_minimum_is_per_order_which_is_the_unfavourable_reading(self):
        """M0 section 7.2 wrote "per order or per session" and left it open.

        The answer is per filled order, so a scale-out pays the minimum on
        every leg. That is why the Phase 0 `consistent_returns` scenario had a
        39% refusal rate: a design meant to raise the win rate turned into a
        cost.
        """

        assert ODD_LOT_BILLING["minimum_is_charged_per_filled_order_not_aggregated_daily"]

    def test_truncation_is_downwards(self):
        """`_truncate_to_dollar` uses ROUND_DOWN, and this is why."""

        assert ODD_LOT_BILLING["commission_fraction_is_truncated_down"]


class TestTheRebateMechanicsAnswersAreRecorded:
    """The four the M5 fee-rebate spec listed as unresolved, answered
    2026-08-28. Two of them decide whether a modelling choice already made
    was right, which is why they are data rather than a paragraph.
    """

    def test_the_receivable_actually_arrives(self):
        """The ledger counts an unpaid rebate towards NAV, never towards
        buying power. That is only defensible if the money arrives.

        It does: closing an account requires settling first, and the branch
        will not complete a closure while a rebate is outstanding. Had the
        answer been the other way, `rebate_receivable` in `nav()` would have
        been an asset that could evaporate.
        """

        assert REBATE_MECHANICS["rebate_receivable_survives_account_closure"]
        assert REBATE_MECHANICS[
            "rebate_survives_early_termination_for_fills_already_made"
        ]

    def test_the_monthly_lump_can_be_traced_back_to_fills(self):
        """M0 invariant 4: every fee traces to an order or fill.

        The rebate arrives as one monthly credit, which would break that. It
        does not, because the broker's statement itemises the rebate per fill
        and the month's items sum to the credit.
        """

        assert REBATE_MECHANICS["statement_granularity_is_per_fill"]
        assert REBATE_MECHANICS["monthly_lump_reconciles_to_itemised_statement"]

    def test_the_volume_cap_is_tiered_rather_than_forfeited(self):
        """Over the cap the excess reverts; the month is not lost.

        The M5 spec had assumed the model should refuse outright above the
        cap. Tiered is a different rule, and neither scale here reaches the
        cap anyway -- which is a reason to record it, not to omit it.
        """

        assert REBATE_MECHANICS["electronic_volume_cap_is_per_calendar_month"]
        assert REBATE_MECHANICS["over_cap_is_tiered_not_forfeited"]

    def test_the_cap_is_out_of_reach_at_both_scales_this_project_uses(self):
        """Recorded as a fact with a margin, not as an absence.

        The reference scale turns over roughly NT$385k a month against a
        NT$1m cap. "Cannot reach" is not "does not exist": a model that
        ignored the tier would be wrong for a larger account.
        """

        monthly_turnover_at_reference = Decimal("385000")
        assert monthly_turnover_at_reference < PROMOTION_MONTHLY_TURNOVER_CAP
        assert PROMOTION_OVER_CAP_DISCOUNT > Decimal("0.20"), (
            "the over-cap discount must be worse than the promotional 2 折, "
            "or exceeding the cap would be an improvement"
        )


class TestTermsKnowWhenTheyWereInForce:
    def test_the_published_schedule_is_undated(self):
        """It is the standing rate; a capture cannot say what it will be."""

        assert terms_cover(SINOPAC_PUBLISHED, *BACKTEST_WINDOW) == "undated"

    def test_the_promotion_covers_only_part_of_the_research_window(self):
        """The claim this whole mechanism exists to make legible.

        Pricing 2019-2026 on the promotion asks "what if I had traded that
        history on today's terms", which is a fair question and a different
        one from what happened. It has to be labelled, not assumed.
        """

        assert (
            terms_cover(SINOPAC_PROMOTIONAL_2026, *BACKTEST_WINDOW)
            == "covers-part-of-window"
        )

    def test_a_window_inside_the_promotion_is_fully_covered(self):
        assert (
            terms_cover(SINOPAC_PROMOTIONAL_2026, date(2026, 3, 1), date(2026, 6, 30))
            == "covers-window"
        )

    def test_a_window_after_the_promotion_is_covered_by_none_of_it(self):
        assert (
            terms_cover(SINOPAC_PROMOTIONAL_2026, date(2027, 1, 1), date(2027, 6, 30))
            == "covers-none-of-window"
        )


class TestThePromotionExpiryTripwire:
    def test_the_expiry_is_recorded_as_a_date_not_as_a_sentence(self):
        assert PROMOTION_EXPIRES == date(2026, 12, 31)
        assert SINOPAC_PROMOTIONAL_2026.effective_through == PROMOTION_EXPIRES

    def test_the_promotion_has_not_expired_unnoticed(self):
        """DELIBERATELY DATED. Goes red on 2027-01-01. Not flaky.

        If you are reading this because it just failed, nothing is broken. The
        promotion ended and the cost model that half this repository's
        conclusions rest on has changed underneath them.

        What to do, in order:

        1. Re-capture the fee page. Record the new terms and the capture date
           the way `broker_terms.py` records the old ones.
        2. Decide whether the promotion was extended, replaced, or ended. If
           extended, move `PROMOTION_EXPIRES` and say in the commit where the
           new date came from -- do not delete this test.
        3. If it ended, the standing minimum is NT$20 again. Every report
           produced under the promotion was priced on terms that no longer
           exist. They do not become wrong, but they stop being current, and
           anything comparing an old report against a new one is comparing two
           cost regimes.
        4. ADR-0002 section 2 and the M5 fee rebate change spec both quote the
           0.44% figure. It is 4.67% without the rebate.

        Do not silence this by widening the date. The failure is the feature.
        """

        today = date.today()
        assert today <= PROMOTION_EXPIRES, (
            f"the SinoPac promotion expired on {PROMOTION_EXPIRES} and today "
            f"is {today}. The minimum commission is NT$20 again, which takes "
            "the round-trip cost of an M0-sized position from 0.44% to 4.67%. "
            "Read this test's docstring before changing anything."
        )


class TestM10StaysBlockedAndSaysWhy:
    """The fee questions are answered. That was never the whole blocker."""

    def test_the_outstanding_items_are_not_the_fee_rules(self):
        assert "signed-broker-agreement" in M10_OUTSTANDING
        assert "odd-lot-fill-evidence" in M10_OUTSTANDING

    def test_the_milestone_register_still_shows_m10_blocked(self):
        """Nothing in this file upgrades M10, and a test should say so.

        Recording the terms is not obtaining a contract, and answering how an
        odd lot is billed is not evidence that one would have filled.
        """

        register = (REPO / "docs" / "milestone-register.md").read_text(
            encoding="utf-8"
        )
        # The M10 row, not every line that mentions M10 -- the M4 row says in
        # prose that the broker rate blocks M10 rather than M4, and matching
        # on the bare string turned that sentence into a failure.
        rows = [
            line
            for line in register.splitlines()
            if line.lstrip().startswith("| M10")
        ]
        assert len(rows) == 1, (
            f"expected exactly one M10 row in the register, found {len(rows)}"
        )
        assert "`blocked`" in rows[0], (
            "M10 is no longer blocked in the register. If that is deliberate, "
            "it needs an Owner decision record, not a passing test suite"
        )


class TestTheContractNamesTheRightBlockers:
    """M0 section 7.2 as of m0-v1.2.0, Owner decision D17.

    Until 2026-08-27 the contract said the canary was blocked until the fee
    rate, the minimum and the odd-lot billing rules were obtained. All three
    were obtained on 2026-08-25, so read literally the clause had already
    released itself -- while the two things actually missing were named
    nowhere. A blocking condition that declares its own conditions met will
    eventually be taken at its word.
    """

    def test_the_contract_no_longer_blocks_on_the_fee_rules(self):
        contract = (REPO / "docs" / "m0-project-contract.md").read_text(
            encoding="utf-8"
        )
        assert "m0-v1.2.0" in contract
        assert (
            "真實 canary 在取得實際券商費率、最低費用及零股計費規則前為 `blocked`"
            not in contract
        ), "the superseded wording is back; D17 replaced it for a reason"

    def test_the_two_real_blockers_are_named(self):
        contract = (REPO / "docs" / "m0-project-contract.md").read_text(
            encoding="utf-8"
        )
        # v1.4.0 (D19): the second half is no longer "the confirmation letter"
        # -- that was checked and returns the published schedule. It is now
        # written as what is actually wanted, with the honest admission that
        # nobody knows whether such a document exists.
        for phrase in ("連起來的文件", "零股成交證據"):
            assert phrase in contract, f"M0 no longer names {phrase} as a blocker"

    def test_the_blocker_points_at_something_obtainable(self):
        """m0-v1.3.0, D18.

        v1.2.0 asked for "signed broker terms". A promotion is not written
        into the account-opening master agreement, so that document does not
        exist and the condition could never be met.

        A blocking condition pointing at a non-existent object is as bad as
        one that declares its own conditions met -- the first never lifts, the
        second lifts by accident, and v1.2.0 existed to fix the second.
        """

        contract = (REPO / "docs" / "m0-project-contract.md").read_text(
            encoding="utf-8"
        )
        assert "m0-v1.3.0" in contract
        assert "簽署的券商條款**。已發布的費率頁" not in contract, (
            "the superseded wording is back"
        )
        assert "可取得的證據上限" in contract, (
            "M0 must state that publisher notice plus account confirmation is "
            "the ceiling this market offers, not a contract"
        )

    def test_the_d18_record_exists(self):
        record = REPO / "docs" / "evidence" / "m3-owner-decision-d18-2026-08-28.md"
        assert record.is_file()
        assert "m0-v1.3.0" in record.read_text(encoding="utf-8")

    def test_the_decision_record_exists(self):
        """A contract version bump without its decision record is unsourced."""

        record = REPO / "docs" / "evidence" / "m3-owner-decision-d17-2026-08-27.md"
        assert record.is_file(), f"{record.name} is missing"
        text = record.read_text(encoding="utf-8")
        assert "m0-v1.2.0" in text


class TestTheseTermsAreNotSilentlyTheDefault:
    def test_the_research_defaults_remain_an_assumption(self):
        """Importing this module must not make anything believe it has terms."""

        from m4.rules import BrokerTerms

        assert BrokerTerms().evidence_state == "assumption"
        assert not BrokerTerms().has_rebate

    def test_a_rebate_cannot_be_declared_half_way(self):
        from m4.rules import BrokerTerms, RuleError

        with pytest.raises(RuleError):
            BrokerTerms(rebate_minimum_commission=Decimal("1"))

    def test_terms_that_end_before_they_begin_are_refused(self):
        from m4.rules import BrokerTerms, RuleError

        with pytest.raises(RuleError):
            BrokerTerms(
                effective_from=date(2026, 12, 31),
                effective_through=date(2026, 1, 1),
            )
