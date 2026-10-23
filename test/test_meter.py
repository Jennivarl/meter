"""
METER run for real in direct mode, against a stand-in PLAN and a mocked
web.

The fetch is mocked so a test can make the service healthy, broken, or
gone. Half of these run the validator side, because what matters is not
what one leader read but whether an honest validator would agree with it,
and whether a dishonest leader would be caught.
"""

import sys
from pathlib import Path

import pytest

from test.stubs import MARKER, PLAN_AT, PLAN_ID, STRANGER, BUYER, PROVIDER, ENDS, Stubs, at

BUNDLE = str(Path(__file__).resolve().parent.parent / "contracts" / "meter_bundle.py")

URL = r"status\.example\.com/health"


def set_date(vm, stamp):
    vm.warp(stamp)
    message = sys.modules.get("genlayer.message")
    if message is not None and isinstance(getattr(message, "raw", None), dict):
        message.raw["datetime"] = stamp
    gl = sys.modules.get("genlayer.gl")
    if gl is not None and getattr(gl, "message_raw", None) is not None:
        gl.message_raw["datetime"] = stamp


def serve(vm, body=MARKER, status=200):
    vm.clear_mocks()
    vm.mock_web(URL, {"status": status, "body": body})


@pytest.fixture
def stubs(direct_vm):
    return Stubs().install(direct_vm)


@pytest.fixture
def meter(direct_vm, direct_deploy, stubs):
    contract = direct_deploy(BUNDLE, plan=PLAN_AT)
    direct_vm.strict_mocks = False
    set_date(direct_vm, at(0))
    return contract


def sample_at(vm, meter, minute, body=MARKER, status=200, who=BUYER):
    set_date(vm, at(minute))
    serve(vm, body, status)
    with vm.prank(who):
        return meter.sample(PLAN_ID)


# --------------------------------------------------------------------
# what a sample records
# --------------------------------------------------------------------


def test_a_healthy_service_is_recorded_up(direct_vm, meter):
    got = sample_at(direct_vm, meter, 1)
    assert got["up"] == "1"
    assert got["down"] == "0"
    assert got["samples"] == "1"
    assert meter.samples(PLAN_ID)[0] == {"at": at(1), "slot": "0", "outcome": "up"}


def test_a_maintenance_page_served_as_a_200_is_recorded_down(direct_vm, meter):
    got = sample_at(direct_vm, meter, 1, body="We'll be back soon")
    assert got["down"] == "1"


def test_a_server_error_is_recorded_down(direct_vm, meter):
    sample_at(direct_vm, meter, 1, status=503)
    assert meter.samples(PLAN_ID)[0] == {"at": at(1), "slot": "0", "outcome": "down"}


def test_only_the_outcome_is_stored_because_only_the_outcome_is_agreed(direct_vm, meter):
    """
    Consensus is asked whether the service was up, not why it was down, so
    a reason nobody agreed on is never written to the contract. The time
    and the slot come from the transaction itself.
    """
    sample_at(direct_vm, meter, 1, status=502)
    assert set(meter.samples(PLAN_ID)[0]) == {"at", "slot", "outcome"}


def test_a_status_that_might_be_about_the_route_still_counts_against_the_provider(direct_vm, meter):
    """
    A 403 is not set aside. If it were, a provider could serve one while
    broken and the bad hours would vanish from the denominator.
    """
    got = sample_at(direct_vm, meter, 1, status=403)
    assert got["down"] == "1"
    assert got["samples"] == "1"


def test_a_host_that_cannot_be_reached_counts_as_down_not_as_nothing(direct_vm, meter):
    set_date(direct_vm, at(1))
    direct_vm.clear_mocks()
    with direct_vm.prank(BUYER):
        got = meter.sample(PLAN_ID)
    assert got["down"] == "1"


def test_the_tally_reports_uptime_over_every_slot(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    sample_at(direct_vm, meter, 11)
    got = sample_at(direct_vm, meter, 21, status=502)
    assert got["up"] == "2"
    assert got["samples"] == "3"
    assert got["slots"] == "6"
    assert got["uptime_bp"] == "3333"
    assert got["enough"] is True


def test_every_reading_is_kept_in_order(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    sample_at(direct_vm, meter, 11, status=500)
    assert [r["outcome"] for r in meter.samples(PLAN_ID)] == ["up", "down"]


# --------------------------------------------------------------------
# which samples are allowed to exist
# --------------------------------------------------------------------


def test_each_slot_takes_one_reading(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    with direct_vm.expect_revert("slot 0 already has its reading"):
        sample_at(direct_vm, meter, 3)


def test_one_reading_per_slot_applies_across_every_caller(direct_vm, meter):
    """Otherwise the provider and a friend could take turns in one good minute."""
    sample_at(direct_vm, meter, 1, who=PROVIDER)
    with direct_vm.expect_revert("already has its reading"):
        sample_at(direct_vm, meter, 2, who=STRANGER)


def test_a_reading_late_in_a_slot_is_refused(direct_vm, meter):
    """Nobody can wait for the moment that suits them: the band is fixed."""
    with direct_vm.expect_revert("first 240 seconds"):
        sample_at(direct_vm, meter, 5)
    with direct_vm.expect_revert("first 240 seconds"):
        sample_at(direct_vm, meter, 19, who=PROVIDER)


def test_readings_are_recorded_with_their_slot(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    sample_at(direct_vm, meter, 32)
    assert [r["slot"] for r in meter.samples(PLAN_ID)] == ["0", "3"]


def test_slots_nobody_read_still_count_in_the_tally(direct_vm, meter):
    """Skipping the bad slots cannot raise the provider's uptime."""
    sample_at(direct_vm, meter, 1)
    sample_at(direct_vm, meter, 11)
    sample_at(direct_vm, meter, 21)
    set_date(direct_vm, at(60))
    got = meter.tally(PLAN_ID)
    assert got["samples"] == "3"
    assert got["slots"] == "6"
    assert got["uptime_bp"] == "5000"


def test_anyone_may_sample_because_the_reading_is_the_networks_not_theirs(direct_vm, meter):
    for i, who in enumerate((BUYER, PROVIDER, STRANGER)):
        sample_at(direct_vm, meter, 1 + i * 11, who=who)
    assert meter.tally(PLAN_ID)["samples"] == "3"


def test_nothing_is_sampled_before_the_window_opens(direct_vm, meter, stubs):
    stubs.proposed()
    with direct_vm.expect_revert("not live"):
        sample_at(direct_vm, meter, 1)


def test_nothing_is_sampled_after_the_window_closes(direct_vm, meter):
    """So the tally a settlement reads is final."""
    with direct_vm.expect_revert("the window has closed"):
        sample_at(direct_vm, meter, 60)


def test_a_withdrawn_plan_is_never_sampled(direct_vm, meter, stubs):
    stubs.set_terms(state="withdrawn")
    with direct_vm.expect_revert("not live"):
        sample_at(direct_vm, meter, 1)


def test_terms_about_another_plan_are_refused(direct_vm, meter, stubs):
    stubs.set_terms(plan_id="0x00:other")
    with direct_vm.expect_revert("different plan"):
        sample_at(direct_vm, meter, 1)


def test_the_url_comes_from_the_plan_and_nothing_else(direct_vm, meter, stubs):
    """`sample` takes only a plan id. A caller cannot point the meter elsewhere."""
    stubs.set_terms(host="elsewhere.example.com")
    set_date(direct_vm, at(1))
    direct_vm.clear_mocks()
    direct_vm.mock_web(URL, {"status": 200, "body": MARKER})
    with direct_vm.prank(BUYER):
        meter.sample(PLAN_ID)
    # The mock only answers the agreed URL, so a fetch of anything else
    # fails and is recorded down, rather than up from the mocked page.
    assert meter.samples(PLAN_ID)[0]["outcome"] == "down"


def test_the_tally_is_closed_once_the_window_has_ended(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    assert meter.tally(PLAN_ID)["closed"] is False
    set_date(direct_vm, at(60))
    assert meter.tally(PLAN_ID)["closed"] is True


def test_a_plan_never_sampled_has_an_empty_tally_not_an_error(direct_vm, meter):
    got = meter.tally(PLAN_ID)
    assert got["samples"] == "0"
    assert got["enough"] is False
    assert meter.samples(PLAN_ID) == []


# --------------------------------------------------------------------
# the validator side
# --------------------------------------------------------------------


def leader(outcome):
    return {"outcome": outcome}


def test_a_validator_agrees_when_it_reads_the_same_thing(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    assert direct_vm.run_validator() is True


def test_a_validator_rejects_a_leader_who_calls_an_outage_up(direct_vm, meter):
    """The lie that pays a provider for a broken service."""
    sample_at(direct_vm, meter, 1, status=503)
    assert direct_vm.run_validator(leader_result=leader("up")) is False


def test_a_validator_rejects_a_leader_who_calls_a_healthy_service_down(direct_vm, meter):
    """The lie that refunds a buyer for a service they got."""
    sample_at(direct_vm, meter, 1)
    assert direct_vm.run_validator(leader_result=leader("down")) is False


def test_validators_agree_an_outage_was_down_whatever_each_of_them_saw(direct_vm, meter):
    """
    The bias this prevents: one validator sees a 502, another a 503, a third
    a timeout. Demanding they agree on the reason would let real outages fail
    consensus while healthy samples never do, and bills would lean toward the
    provider. Here the validator saw a 503 and agrees with a leader who only
    says down.
    """
    sample_at(direct_vm, meter, 1, status=503)
    assert direct_vm.run_validator(leader_result=leader("down")) is True
    assert direct_vm.run_validator(leader_result={"outcome": "down", "note": "answered 502"}) is True


def test_a_validator_rejects_an_outcome_the_contract_does_not_define(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    assert direct_vm.run_validator(leader_result=leader("mostly")) is False


def test_a_validator_rejects_a_result_of_the_wrong_shape(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    assert direct_vm.run_validator(leader_result="up") is False


def test_a_validator_rejects_a_leader_that_errored(direct_vm, meter):
    sample_at(direct_vm, meter, 1)
    assert direct_vm.run_validator(leader_error=Exception("boom")) is False


def test_the_settings_are_published(direct_vm, meter):
    got = meter.settings()
    assert got["plan"].lower() == PLAN_AT
    assert got["slot_seconds"] == "600"
    assert got["read_within_seconds"] == "240"
    assert got["min_samples"] == "3"
