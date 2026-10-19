"""
PLAN run for real in direct mode.

The terms are the only thing either side signs, so most of these are about
what cannot change once signed, and about who can sign what.
"""

import sys
from pathlib import Path

import pytest

from contracts.metering import epoch_seconds

BUNDLE = str(Path(__file__).resolve().parent.parent / "contracts" / "plan_bundle.py")

BUYER = b"\xa0" * 20
PROVIDER = b"\xb0" * 20
STRANGER = b"\xc0" * 20

NAME = "api"
PLAN_ID = "0x" + BUYER.hex() + ":" + NAME
HOST = "status.example.com"
PATH = "/health"
MARKER = "all systems operational"
FEE = 1_000_000

T0 = "2026-10-20T08:50:00Z"
T_ACCEPT = "2026-10-20T09:00:00Z"


def set_date(vm, stamp):
    vm.warp(stamp)
    message = sys.modules.get("genlayer.message")
    if message is not None and isinstance(getattr(message, "raw", None), dict):
        message.raw["datetime"] = stamp
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = stamp


@pytest.fixture
def book(direct_vm, direct_deploy):
    contract = direct_deploy(BUNDLE)
    direct_vm.strict_mocks = False
    set_date(direct_vm, T0)
    return contract


def propose(vm, book, who=BUYER, name=NAME, provider=None, host=HOST, path=PATH,
            marker=MARKER, fee=FEE, minutes=60):
    with vm.prank(who):
        return book.propose(name, provider or "0x" + PROVIDER.hex(), host, path, marker, fee, minutes)


def accept(vm, book, who=PROVIDER):
    set_date(vm, T_ACCEPT)
    with vm.prank(who):
        return book.accept(PLAN_ID)


# --------------------------------------------------------------------
# proposing
# --------------------------------------------------------------------


def test_a_proposal_fixes_every_term(direct_vm, book):
    got = propose(direct_vm, book)
    assert got["plan_id"] == PLAN_ID
    assert got["url"] == "https://status.example.com/health"
    assert got["marker"] == MARKER
    assert got["fee"] == str(FEE)
    assert got["window_seconds"] == "3600"
    assert got["state"] == "proposed"


def test_no_window_exists_before_the_provider_accepts(direct_vm, book):
    got = propose(direct_vm, book)
    assert got["opens_at"] == "-1"
    assert got["ends_at"] == "-1"


def test_terms_cannot_be_changed_once_proposed(direct_vm, book):
    propose(direct_vm, book)
    with direct_vm.expect_revert("cannot be changed"):
        propose(direct_vm, book, host="an-easier-page.example.com")


def test_a_buyer_cannot_be_their_own_provider(direct_vm, book):
    with direct_vm.expect_revert("different provider"):
        propose(direct_vm, book, provider="0x" + BUYER.hex())


def test_the_zero_address_is_not_a_provider(direct_vm, book):
    with direct_vm.expect_revert("real provider"):
        propose(direct_vm, book, provider="0x" + "00" * 20)


@pytest.mark.parametrize("host", ["https://status.example.com", "status.example.com/health", "localhost"])
def test_a_host_that_is_not_a_bare_hostname_is_refused(direct_vm, book, host):
    with direct_vm.expect_revert("bare hostname"):
        propose(direct_vm, book, host=host)


@pytest.mark.parametrize("path", ["health", "/a?b=1", "/../x"])
def test_a_path_that_could_leave_the_host_is_refused(direct_vm, book, path):
    with direct_vm.expect_revert("starts at /"):
        propose(direct_vm, book, path=path)


def test_a_marker_is_required(direct_vm, book):
    with direct_vm.expect_revert("healthy response contains"):
        propose(direct_vm, book, marker="  ")


def test_a_fee_must_be_positive(direct_vm, book):
    with direct_vm.expect_revert("more than zero"):
        propose(direct_vm, book, fee=0)


@pytest.mark.parametrize("minutes", [0, 59, 31 * 24 * 60 + 1])
def test_a_window_outside_an_hour_to_a_month_is_refused(direct_vm, book, minutes):
    with direct_vm.expect_revert("a window is"):
        propose(direct_vm, book, minutes=minutes)


def test_a_name_is_letters_digits_hyphen_or_underscore(direct_vm, book):
    with direct_vm.expect_revert("letters, digits"):
        propose(direct_vm, book, name="my api")


# --------------------------------------------------------------------
# accepting
# --------------------------------------------------------------------


def test_the_window_opens_at_the_moment_of_acceptance(direct_vm, book):
    """Nobody types a start date, so nobody can pick one that dodges an outage."""
    propose(direct_vm, book)
    got = accept(direct_vm, book)
    opened = epoch_seconds(T_ACCEPT)
    assert got["state"] == "live"
    assert got["accepted_at"] == T_ACCEPT
    assert got["opens_at"] == str(opened)
    assert got["ends_at"] == str(opened + 3600)


def test_only_the_named_provider_may_accept(direct_vm, book):
    propose(direct_vm, book)
    for who in (BUYER, STRANGER):
        with direct_vm.expect_revert("only the named provider"):
            accept(direct_vm, book, who=who)


def test_a_plan_cannot_be_accepted_twice(direct_vm, book):
    propose(direct_vm, book)
    accept(direct_vm, book)
    with direct_vm.expect_revert("that plan is live"):
        accept(direct_vm, book)


# --------------------------------------------------------------------
# withdrawing
# --------------------------------------------------------------------


def test_the_buyer_may_withdraw_before_acceptance(direct_vm, book):
    propose(direct_vm, book)
    with direct_vm.prank(BUYER):
        got = book.withdraw(PLAN_ID)
    assert got["state"] == "withdrawn"


def test_a_withdrawn_plan_cannot_then_be_accepted(direct_vm, book):
    propose(direct_vm, book)
    with direct_vm.prank(BUYER):
        book.withdraw(PLAN_ID)
    with direct_vm.expect_revert("that plan is withdrawn"):
        accept(direct_vm, book)


def test_nobody_can_withdraw_once_the_window_is_running(direct_vm, book):
    """Both sides are bound to whatever the window measures."""
    propose(direct_vm, book)
    accept(direct_vm, book)
    with direct_vm.prank(BUYER):
        with direct_vm.expect_revert("can no longer be withdrawn"):
            book.withdraw(PLAN_ID)


def test_only_the_buyer_may_withdraw(direct_vm, book):
    propose(direct_vm, book)
    for who in (PROVIDER, STRANGER):
        with direct_vm.prank(who):
            with direct_vm.expect_revert("only the buyer"):
                book.withdraw(PLAN_ID)


# --------------------------------------------------------------------
# reading
# --------------------------------------------------------------------


def test_asking_for_a_plan_that_does_not_exist_says_so(direct_vm, book):
    with direct_vm.expect_revert("no such plan"):
        book.get("0x00:nothing")


def test_the_list_holds_every_plan_proposed(direct_vm, book):
    propose(direct_vm, book)
    assert book.plan_list() == [PLAN_ID]


def test_a_plan_id_is_matched_regardless_of_case(direct_vm, book):
    propose(direct_vm, book)
    assert book.get(PLAN_ID.upper())["plan_id"] == PLAN_ID
