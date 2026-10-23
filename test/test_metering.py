"""
The pure core, tested without a chain, a network or money.

These are the decisions every validator re-derives: what a fetch means,
how the fee divides, and when there is enough to bill on. The division is
the one to be paranoid about, because it is where value could be created
or lost by rounding.
"""

import datetime
import random

import pytest

from contracts.metering import (
    DOWN,
    FULL,
    MAX_WINDOW,
    MIN_SAMPLES,
    MIN_WINDOW,
    READ_WITHIN,
    SLOT_SECONDS,
    UP,
    classify,
    epoch_seconds,
    share,
    slot_at,
    slot_count,
    unreached,
    uptime_bp,
    url_for,
    valid_host,
    valid_marker,
    valid_path,
)

MARKER = "all systems operational"


# --------------------------------------------------------------------
# what a fetch means
# --------------------------------------------------------------------


def test_a_healthy_answer_with_the_marker_is_up():
    assert classify(200, "status: all systems operational", MARKER) == {
        "outcome": UP,
        "note": "answered with the marker",
    }


@pytest.mark.parametrize("status", [200, 201, 204, 299])
def test_any_success_status_with_the_marker_is_up(status):
    assert classify(status, MARKER, MARKER)["outcome"] == UP


def test_an_answer_without_the_marker_is_down():
    """A maintenance banner served as a 200 is not the service working."""
    assert classify(200, "<h1>We'll be back soon</h1>", MARKER) == {
        "outcome": DOWN,
        "note": "answered without the marker",
    }


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_server_error_is_down(status):
    assert classify(status, MARKER, MARKER) == {"outcome": DOWN, "note": "answered " + str(status)}


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 410, 429])
def test_every_other_status_is_down_too(status):
    """
    No status is ignored. A not-counted bucket would be a lever the
    provider controls: serve a 403 while broken and the bad hours vanish
    from the denominator.
    """
    assert classify(status, MARKER, MARKER)["outcome"] == DOWN


def test_a_marker_in_an_error_page_does_not_make_it_up():
    """A 503 whose body happens to repeat the marker is still a 503."""
    assert classify(503, MARKER, MARKER)["outcome"] == DOWN


def test_a_fetch_that_failed_entirely_is_down_and_says_so():
    assert unreached() == {"outcome": DOWN, "note": "could not be reached"}


def test_the_reason_differs_between_kinds_of_down_so_validators_must_agree_on_it():
    reasons = {
        classify(200, "nope", MARKER)["note"],
        classify(503, "", MARKER)["note"],
        classify(404, "", MARKER)["note"],
        unreached()["note"],
    }
    assert len(reasons) == 4


# --------------------------------------------------------------------
# how the fee divides
# --------------------------------------------------------------------


def test_a_perfect_window_pays_the_provider_everything():
    assert share(1_000_000, 6, 6, 6) == {"provider": 1_000_000, "buyer": 0, "billed": True}


def test_a_dead_window_pays_the_provider_nothing():
    assert share(1_000_000, 0, 6, 6) == {"provider": 0, "buyer": 1_000_000, "billed": True}


def test_the_fee_divides_by_the_share_of_slots_that_were_up():
    assert share(1_000_000, 3, 4, 4) == {"provider": 750_000, "buyer": 250_000, "billed": True}


def test_a_slot_nobody_read_is_not_paid():
    """Four of six slots read, all up: four sixths, not four fourths."""
    assert share(600, 4, 4, 6) == {"provider": 400, "buyer": 200, "billed": True}


def test_skipping_the_bad_slots_cannot_raise_the_providers_share():
    """Reading only the good slots pays the same as reading the bad ones as down."""
    assert share(600, 4, 4, 6)["provider"] == share(600, 4, 6, 6)["provider"]


def test_rounding_goes_to_the_side_that_paid():
    """1000 over 3 slots, 2 up: 666.66 rounds down to 666, the 334 goes back."""
    got = share(1000, 2, 3, 3)
    assert got["provider"] == 666
    assert got["buyer"] == 334


def test_the_two_parts_always_sum_to_exactly_the_fee():
    """No rounding anywhere can create or lose value. Checked broadly."""
    rng = random.Random(20261020)
    for _ in range(5000):
        fee = rng.randrange(0, 10**24)
        slots = rng.randrange(MIN_SAMPLES, 5000)
        taken = rng.randrange(MIN_SAMPLES, slots + 1)
        up = rng.randrange(0, taken + 1)
        got = share(fee, up, taken, slots)
        assert got["provider"] + got["buyer"] == fee
        assert 0 <= got["provider"] <= fee


def test_more_uptime_never_pays_the_provider_less():
    fee, taken = 999_983, 17
    paid = [share(fee, up, taken, taken)["provider"] for up in range(taken + 1)]
    assert paid == sorted(paid)


def test_too_few_samples_bill_nothing_and_return_it_all():
    for taken in range(MIN_SAMPLES):
        assert share(1_000_000, taken, taken, 6) == {"provider": 0, "buyer": 1_000_000, "billed": False}


def test_exactly_the_minimum_is_enough_to_bill():
    assert share(900, MIN_SAMPLES, MIN_SAMPLES, MIN_SAMPLES)["billed"] is True


@pytest.mark.parametrize(
    "fee,up,taken,slots",
    [(-1, 1, 3, 3), (100, -1, 3, 3), (100, 4, 3, 3), (100, 1, -1, 3), (100, 3, 4, 3)],
)
def test_an_impossible_tally_is_refused_rather_than_paid(fee, up, taken, slots):
    with pytest.raises(ValueError):
        share(fee, up, taken, slots)


def test_uptime_is_reported_in_basis_points_rounded_down():
    assert uptime_bp(3, 4) == 7500
    assert uptime_bp(4, 6) == 6666
    assert uptime_bp(2, 3) == 6666
    assert uptime_bp(5, 5) == FULL
    assert uptime_bp(0, 0) == 0


# --------------------------------------------------------------------
# what a plan may name
# --------------------------------------------------------------------


@pytest.mark.parametrize("host", ["status.example.com", "api.example.co.uk", "x-1.example.io"])
def test_a_bare_hostname_is_accepted(host):
    assert valid_host(host) is True


@pytest.mark.parametrize(
    "host",
    ["", "localhost", "https://example.com", "example.com/health", "user@example.com",
     "example.com:8080", ".example.com", "example..com", "exa mple.com"],
)
def test_anything_that_could_smuggle_another_host_or_path_is_refused(host):
    assert valid_host(host) is False


@pytest.mark.parametrize("path", ["/", "/health", "/api/v1/status", "/status.json"])
def test_a_plain_path_is_accepted(path):
    assert valid_path(path) is True


@pytest.mark.parametrize("path", ["health", "/../etc", "/a?b=1", "/a#b", "//evil.com", "/a b", "/x\x00"])
def test_a_path_that_could_leave_the_host_is_refused(path):
    assert valid_path(path) is False


def test_a_marker_is_required_and_one_line():
    assert valid_marker(MARKER) is True
    assert valid_marker("   ") is False
    assert valid_marker("two\nlines") is False
    assert valid_marker("x" * 81) is False


def test_the_url_is_always_https_and_built_from_the_parts():
    assert url_for("Status.Example.com", "/health") == "https://status.example.com/health"


def test_the_shortest_window_holds_enough_slots_to_bill():
    assert MIN_WINDOW // SLOT_SECONDS >= MIN_SAMPLES * 2
    assert MAX_WINDOW == 31 * 24 * 3600


def test_the_reading_band_is_shorter_than_a_slot():
    assert 0 < READ_WITHIN < SLOT_SECONDS


# --------------------------------------------------------------------
# when a reading may be taken
# --------------------------------------------------------------------

OPENS = 1_000_000
ENDS = OPENS + 3600


def test_a_window_is_cut_into_fixed_slots():
    assert slot_count(OPENS, ENDS) == 6
    assert slot_count(-1, -1) == 0


def test_a_reading_early_in_a_slot_belongs_to_it():
    assert slot_at(OPENS, ENDS, OPENS) == 0
    assert slot_at(OPENS, ENDS, OPENS + READ_WITHIN - 1) == 0
    assert slot_at(OPENS, ENDS, OPENS + 2 * SLOT_SECONDS + 30) == 2


def test_a_reading_late_in_a_slot_belongs_to_none():
    """So nobody can wait out a slot for the moment that suits them."""
    assert slot_at(OPENS, ENDS, OPENS + READ_WITHIN) == -1
    assert slot_at(OPENS, ENDS, OPENS + SLOT_SECONDS - 1) == -1


def test_nothing_belongs_to_a_slot_outside_the_window():
    assert slot_at(OPENS, ENDS, OPENS - 1) == -1
    assert slot_at(OPENS, ENDS, ENDS) == -1
    assert slot_at(-1, -1, OPENS) == -1


def test_a_partial_last_slot_is_not_a_slot():
    ends = OPENS + 3600 + 300
    assert slot_count(OPENS, ends) == 6
    assert slot_at(OPENS, ends, OPENS + 3600 + 10) == -1


# --------------------------------------------------------------------
# the clock
# --------------------------------------------------------------------


def test_fractional_seconds_do_not_change_the_instant():
    assert epoch_seconds("2026-10-20T09:00:00Z") == epoch_seconds("2026-10-20T09:00:00.81234+00:00")


@pytest.mark.parametrize("stamp", ["", "2026-10-20", "2026-13-01T00:00:00Z", "2026-02-30T00:00:00Z"])
def test_an_unreadable_timestamp_is_none(stamp):
    assert epoch_seconds(stamp) is None


def test_the_clock_agrees_with_the_standard_library_across_a_leap_day():
    day = datetime.date(2024, 2, 29) - datetime.timedelta(days=800)
    for _ in range(1600):
        expected = int(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc).timestamp())
        assert epoch_seconds(day.isoformat() + "T00:00:00Z") == expected
        day += datetime.timedelta(days=1)
