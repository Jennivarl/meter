"""
GRADE run for real in direct mode, against a stand-in METER.

The reference consumer, and the tests are mostly about what it refuses.
A renewal that opens on the first good hour of a month that then failed
is worse than no gate: it reports a check that did not happen.
"""

import sys
from pathlib import Path

import pytest

from test.stubs import METER_AT, PLAN_ID, STRANGER, Stubs, at

BUNDLE = str(Path(__file__).resolve().parent.parent / "contracts" / "grade_bundle.py")

OPERATOR = b"\xa0" * 20
REQUIRED = 9900  # 99.00%


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
    return Stubs().install(direct_vm)


@pytest.fixture
def grade(direct_vm, direct_deploy, stubs):
    with direct_vm.prank(OPERATOR):
        contract = direct_deploy(BUNDLE, meter=METER_AT, plan_id=PLAN_ID, required_bp=REQUIRED)
    direct_vm.strict_mocks = False
    set_date(direct_vm, at(61))
    return contract


# --------------------------------------------------------------------
# what it refuses
# --------------------------------------------------------------------


def test_an_open_window_keeps_it_shut_however_good_it_looks(direct_vm, grade, stubs):
    stubs.reading = {**stubs.reading, "up": "5", "samples": "5", "uptime_bp": "10000", "enough": True}
    with direct_vm.expect_revert("still open"):
        grade.renew("renew for november")


def test_too_few_samples_keep_it_shut(direct_vm, grade, stubs):
    stubs.closed(up=2, down=0)
    with direct_vm.expect_revert("too few samples"):
        grade.renew("renew for november")


def test_uptime_below_the_bar_keeps_it_shut_and_says_by_how_much(direct_vm, grade, stubs):
    stubs.closed(up=9, down=1)
    with direct_vm.expect_revert("measured 9000 basis points, below the 9900 required"):
        grade.renew("renew for november")


def test_a_tally_about_another_plan_cannot_open_it(direct_vm, grade, stubs):
    stubs.closed(up=10, down=0)
    stubs.reading["plan_id"] = "0x00:other"
    with direct_vm.expect_revert("different plan"):
        grade.renew("renew for november")


@pytest.mark.parametrize("bar", [0, -1, 10001])
def test_a_bar_outside_the_possible_range_is_refused_at_deployment(direct_vm, direct_deploy, stubs, bar):
    with direct_vm.expect_revert("1 to 10000 basis points"):
        direct_deploy(BUNDLE, meter=METER_AT, plan_id=PLAN_ID, required_bp=bar)


def test_a_grade_must_name_its_plan(direct_vm, direct_deploy, stubs):
    with direct_vm.expect_revert("name the plan"):
        direct_deploy(BUNDLE, meter=METER_AT, plan_id="  ", required_bp=REQUIRED)


# --------------------------------------------------------------------
# what it allows
# --------------------------------------------------------------------


def test_a_closed_window_at_or_above_the_bar_renews(direct_vm, grade, stubs):
    stubs.closed(up=99, down=1)
    got = grade.renew("renew for november")
    assert got["renewed"] is True
    assert got["uptime_bp"] == "9900"
    assert grade.history()[0]["note"] == "renew for november"


def test_anyone_may_renew_once_the_measurement_allows_it(direct_vm, grade, stubs):
    stubs.closed(up=10, down=0)
    with direct_vm.prank(STRANGER):
        grade.renew("renew")
    assert grade.history()[0]["actor"].lower() == "0x" + STRANGER.hex()


def test_nothing_is_cached_so_a_lower_reading_shuts_it_again(direct_vm, grade, stubs):
    stubs.closed(up=10, down=0)
    grade.renew("renew")
    stubs.closed(up=1, down=9)
    with direct_vm.expect_revert("below the 9900 required"):
        grade.renew("renew again")
    assert len(grade.history()) == 1


def test_a_long_note_is_trimmed_rather_than_refused(direct_vm, grade, stubs):
    stubs.closed(up=10, down=0)
    grade.renew("x" * 500)
    assert len(grade.history()[0]["note"]) == 200


# --------------------------------------------------------------------
# reading
# --------------------------------------------------------------------


def test_standing_says_why_it_is_shut(direct_vm, grade, stubs):
    stubs.closed(up=9, down=1)
    got = grade.standing()
    assert got["open"] is False
    assert got["closed"] is True
    assert got["enough"] is True
    assert got["uptime_bp"] == "9000"
    assert got["required_bp"] == str(REQUIRED)


def test_standing_reports_an_open_gate_once_the_window_measured_high_enough(direct_vm, grade, stubs):
    stubs.closed(up=100, down=0)
    assert grade.standing()["open"] is True


def test_the_grade_reads_only_what_it_was_deployed_with(direct_vm, grade):
    got = grade.standing()
    assert got["meter"].lower() == METER_AT
    assert got["plan_id"] == PLAN_ID
    assert got["operator"].lower() == "0x" + OPERATOR.hex()
