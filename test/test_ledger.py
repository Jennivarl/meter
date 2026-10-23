"""
LEDGER run for real in direct mode, against a stand-in PLAN and METER.

Every test here is about money: who can put it in, who can take it out,
when, and how much. The cases that matter most are the ones where the
answer is "nobody gets billed", because those are the ones a careless
escrow turns into somebody's loss.
"""

import sys
from pathlib import Path

import pytest

from test.stubs import (
    BUYER,
    EVM_PAY,
    FEE,
    METER_AT,
    PLAN_AT,
    PLAN_ID,
    PROVIDER,
    STRANGER,
    Stubs,
    at,
)

BUNDLE = str(Path(__file__).resolve().parent.parent / "contracts" / "ledger_bundle.py")


def set_date(vm, stamp):
    vm.warp(stamp)
    message = sys.modules.get("genlayer.message")
    if message is not None and isinstance(getattr(message, "raw", None), dict):
        message.raw["datetime"] = stamp
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = stamp


@pytest.fixture
def stubs(direct_vm):
    # Funding happens before acceptance, so the plan starts out proposed.
    return Stubs().install(direct_vm).proposed()


@pytest.fixture
def ledger(direct_vm, direct_deploy, stubs):
    contract = direct_deploy(BUNDLE, plan=PLAN_AT, meter=METER_AT)
    direct_vm.strict_mocks = False
    set_date(direct_vm, "2026-10-20T08:55:00Z")
    return contract


def fund(vm, ledger, who=BUYER, amount=FEE):
    vm.value = amount
    try:
        with vm.prank(who):
            return ledger.fund(PLAN_ID)
    finally:
        vm.value = 0


def go_live(stubs):
    """The provider accepts: the window opens at 09:00 and ends at 10:00."""
    from test.stubs import ENDS, OPENS, T_OPEN

    return stubs.set_terms(state="live", accepted_at=T_OPEN, opens_at=str(OPENS), ends_at=str(ENDS))


# --------------------------------------------------------------------
# funding
# --------------------------------------------------------------------


def test_the_buyer_escrows_exactly_the_fee(direct_vm, ledger):
    got = fund(direct_vm, ledger)
    assert got["state"] == "funded"
    assert got["amount"] == str(FEE)
    assert ledger.reserves()["committed"] == str(FEE)
    assert ledger.is_funded(PLAN_ID) is True


def test_the_fee_must_be_exact(direct_vm, ledger):
    for wrong in (FEE - 1, FEE + 1):
        with direct_vm.expect_revert("exactly the plan's fee"):
            fund(direct_vm, ledger, amount=wrong)


def test_only_the_buyer_funds_a_plan(direct_vm, ledger):
    for who in (PROVIDER, STRANGER):
        with direct_vm.expect_revert("only the buyer"):
            fund(direct_vm, ledger, who=who)


def test_a_plan_is_funded_once(direct_vm, ledger):
    fund(direct_vm, ledger)
    with direct_vm.expect_revert("already funded"):
        fund(direct_vm, ledger)


def test_a_plan_cannot_be_funded_after_the_provider_accepts(direct_vm, ledger, stubs):
    """
    Otherwise a buyer could watch the measurements and fund only a plan
    that was going to cost little.
    """
    go_live(stubs)
    with direct_vm.expect_revert("before the provider accepts"):
        fund(direct_vm, ledger)


def test_terms_about_another_plan_are_refused(direct_vm, ledger, stubs):
    stubs.set_terms(plan_id="0x00:other")
    with direct_vm.expect_revert("different plan"):
        fund(direct_vm, ledger)


# --------------------------------------------------------------------
# settling
# --------------------------------------------------------------------


def settle(vm, ledger, minute=60, who=STRANGER):
    set_date(vm, at(minute))
    with vm.prank(who):
        return ledger.settle(PLAN_ID)


def test_a_perfect_window_pays_the_provider_the_whole_fee(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=6, down=0)
    got = settle(direct_vm, ledger)
    assert got["state"] == "settled"
    assert got["provider_paid"] == str(FEE)
    assert got["buyer_paid"] == "0"
    assert stubs.transfers == [{"to": PROVIDER, "value": FEE, "kind": EVM_PAY}]
    assert ledger.reserves()["committed"] == "0"


def test_the_fee_divides_by_measured_uptime(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=3, down=1)
    got = settle(direct_vm, ledger)
    assert got["provider_paid"] == "750000"
    assert got["buyer_paid"] == "250000"
    assert got["uptime_bp"] == "7500"
    assert got["reason"] == "3 of 4 slots found the service up"
    assert stubs.transfers == [
        {"to": PROVIDER, "value": 750_000, "kind": EVM_PAY},
        {"to": BUYER, "value": 250_000, "kind": EVM_PAY},
    ]


def test_slots_nobody_read_are_not_paid(direct_vm, ledger, stubs):
    """Four of six slots read and all up: the provider is paid for four sixths."""
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=4, down=0, slots=6)
    got = settle(direct_vm, ledger)
    assert got["provider_paid"] == "666666"
    assert got["buyer_paid"] == "333334"
    assert got["slots"] == "6"
    assert got["reason"] == "4 of 6 slots found the service up, 2 not read"


def test_what_was_paid_out_is_exactly_what_was_escrowed(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=2, down=1)
    settle(direct_vm, ledger)
    assert sum(t["value"] for t in stubs.transfers) == FEE
    assert ledger.reserves()["committed"] == "0"


def test_a_dead_window_returns_the_whole_fee_to_the_buyer(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=0, down=5)
    got = settle(direct_vm, ledger)
    assert got["provider_paid"] == "0"
    assert stubs.transfers == [{"to": BUYER, "value": FEE, "kind": EVM_PAY}]


def test_too_few_samples_bill_nothing(direct_vm, ledger, stubs):
    """Two good samples are not a good month."""
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=2, down=0)
    got = settle(direct_vm, ledger)
    assert got["provider_paid"] == "0"
    assert got["buyer_paid"] == str(FEE)
    assert "3 are needed" in got["reason"]
    assert stubs.transfers == [{"to": BUYER, "value": FEE, "kind": EVM_PAY}]


def test_a_window_nobody_sampled_returns_the_fee(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=0, down=0)
    settle(direct_vm, ledger)
    assert stubs.transfers == [{"to": BUYER, "value": FEE, "kind": EVM_PAY}]


def test_nothing_settles_while_the_window_is_open(direct_vm, ledger, stubs):
    """A tally taken mid-window is a reading in progress, not a result."""
    fund(direct_vm, ledger)
    go_live(stubs)  # the stub tally is not closed
    with direct_vm.expect_revert("still open"):
        settle(direct_vm, ledger, minute=30)
    assert stubs.transfers == []


def test_a_plan_settles_once(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=3, down=0)
    settle(direct_vm, ledger)
    with direct_vm.expect_revert("already settled"):
        settle(direct_vm, ledger)
    assert len(stubs.transfers) == 1


def test_an_unfunded_plan_cannot_be_settled(direct_vm, ledger, stubs):
    go_live(stubs).closed(up=3, down=0)
    with direct_vm.expect_revert("never funded"):
        settle(direct_vm, ledger)


def test_a_tally_about_another_plan_is_refused(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=3, down=0)
    stubs.reading["plan_id"] = "0x00:other"
    with direct_vm.expect_revert("different plan"):
        settle(direct_vm, ledger)
    assert stubs.transfers == []


def test_anyone_may_settle_because_nothing_they_supply_changes_the_split(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs).closed(up=3, down=1)
    settle(direct_vm, ledger, who=STRANGER)
    assert [t["to"] for t in stubs.transfers] == [PROVIDER, BUYER]


# --------------------------------------------------------------------
# reclaiming
# --------------------------------------------------------------------


def test_the_buyer_reclaims_the_fee_from_a_withdrawn_plan(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    stubs.set_terms(state="withdrawn")
    with direct_vm.prank(BUYER):
        got = ledger.reclaim(PLAN_ID)
    assert got["state"] == "reclaimed"
    assert stubs.transfers == [{"to": BUYER, "value": FEE, "kind": EVM_PAY}]
    assert ledger.reserves()["committed"] == "0"


def test_the_fee_stays_while_a_provider_could_still_accept(direct_vm, ledger, stubs):
    """Withdraw first, which also stops a late acceptance."""
    fund(direct_vm, ledger)
    with direct_vm.prank(BUYER):
        with direct_vm.expect_revert("withdraw the plan first"):
            ledger.reclaim(PLAN_ID)
    assert stubs.transfers == []


def test_a_live_plan_cannot_be_reclaimed(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    go_live(stubs)
    with direct_vm.prank(BUYER):
        with direct_vm.expect_revert("withdraw the plan first"):
            ledger.reclaim(PLAN_ID)


def test_only_the_buyer_reclaims(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    stubs.set_terms(state="withdrawn")
    for who in (PROVIDER, STRANGER):
        with direct_vm.prank(who):
            with direct_vm.expect_revert("only the buyer"):
                ledger.reclaim(PLAN_ID)


def test_a_reclaimed_fee_cannot_be_reclaimed_again(direct_vm, ledger, stubs):
    fund(direct_vm, ledger)
    stubs.set_terms(state="withdrawn")
    with direct_vm.prank(BUYER):
        ledger.reclaim(PLAN_ID)
        with direct_vm.expect_revert("already reclaimed"):
            ledger.reclaim(PLAN_ID)
    assert len(stubs.transfers) == 1


# --------------------------------------------------------------------
# reading
# --------------------------------------------------------------------


def test_the_ledger_reads_only_the_contracts_it_was_deployed_with(direct_vm, ledger):
    got = ledger.settings()
    assert got["plan"].lower() == PLAN_AT
    assert got["meter"].lower() == METER_AT


def test_a_provider_can_check_funding_before_accepting(direct_vm, ledger):
    assert ledger.is_funded(PLAN_ID) is False
    fund(direct_vm, ledger)
    assert ledger.is_funded(PLAN_ID) is True


def test_asking_for_an_escrow_that_does_not_exist_says_so(direct_vm, ledger):
    with direct_vm.expect_revert("no such escrow"):
        ledger.get_escrow("0x00:nothing")
