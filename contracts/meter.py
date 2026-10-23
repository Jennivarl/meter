# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
"""
METER. The measurements, taken from the live service under consensus.

    sample(plan_id)   one fetch of the agreed URL, by every validator
    tally(plan_id)    up, down, samples, and whether the window has closed
    samples(plan_id)  every reading, oldest first

Each sample is one consensus round over a real HTTP fetch. Every validator
fetches the plan's URL itself, reduces the answer to up or down, and agrees
with the leader only if the outcome matches. Only the outcome is compared,
and only the outcome is stored: a real outage looks different from
different places, and requiring agreement on why it was down would let
outages fail consensus while healthy samples never do. Nothing a caller
passes reaches the fetch: the URL and the marker come from PLAN.

When a sample may be taken is fixed in advance, so neither side can pick
its moment:

    fixed slots                 the window is cut into SLOT_SECONDS slots
                                from the provider's acceptance
    one reading per slot        across every caller
    only early in the slot      within READ_WITHIN seconds of its start, a
                                band set before anyone knows how the service
                                will behave in it
    every slot is billed        a slot nobody read is not paid, so skipping
                                the bad slots cannot raise the provider's share
    anyone may take one         buyer, provider, or a stranger, because
                                every sample is the network's reading of
                                the same URL, not the caller's
"""

from dataclasses import dataclass

import genlayer as gl
from genlayer.types import *

from contracts.metering import (
    MIN_SAMPLES,
    OUTCOMES,
    READ_WITHIN,
    SLOT_SECONDS,
    UP,
    classify,
    epoch_seconds,
    slot_at,
    slot_count,
    unreached,
    uptime_bp,
    url_for,
)

@gl.storage.allow
@dataclass
class Reading:
    at: str
    slot: u256
    outcome: str


@gl.storage.allow
@dataclass
class Tally:
    up: u256
    down: u256
    last_at: str


class Meter(gl.contract.Contract):
    # The one plan book this meter believes. Fixed at deployment: whoever
    # can name the source of the terms can choose which URL gets measured.
    plan: Address
    tallies: gl.storage.TreeMap[str, Tally]
    readings: gl.storage.TreeMap[str, gl.storage.DynArray[Reading]]
    # plan_id + "#" + slot number, for every slot that has its reading.
    taken: gl.storage.TreeMap[str, bool]

    def __init__(self, plan: str):
        self.plan = _address(plan)

    @gl.public.write
    def sample(self, plan_id: str) -> dict:
        """
        One reading of the live service.

        Refused outside a slot's reading band and in a slot already read, so
        every reading that exists is one the schedule allowed, and none can
        be added after the window closes and the bill is settled.
        """
        key = plan_id.strip().lower()
        terms = gl.contract.get_at(self.plan).view().get(key)
        if str(terms["plan_id"]).lower() != key:
            raise gl.vm.UserError("those terms are about a different plan")
        if str(terms["state"]) != "live":
            raise gl.vm.UserError("that plan is " + str(terms["state"]) + ", not live")

        now = epoch_seconds(_stamp())
        if now is None:
            raise gl.vm.UserError("the clock could not be read")
        opens = int(str(terms["opens_at"]))
        ends = int(str(terms["ends_at"]))
        if opens < 0 or now < opens:
            raise gl.vm.UserError("the window has not opened")
        if now >= ends:
            raise gl.vm.UserError("the window has closed")

        slot = slot_at(opens, ends, now)
        if slot < 0:
            raise gl.vm.UserError(
                f"a reading counts only in the first {READ_WITHIN} seconds of each {SLOT_SECONDS}-second slot"
            )
        slot_key = key + "#" + str(slot)
        if slot_key in self.taken:
            raise gl.vm.UserError(f"slot {slot} already has its reading")
        tally = self.tallies[key] if key in self.tallies else Tally(up=0, down=0, last_at="")

        url = url_for(str(terms["host"]), str(terms["path"]))
        marker = str(terms["marker"])

        def leader_fn():
            return _read(url, marker)

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            leader = leaders_res.calldata
            if not isinstance(leader, dict):
                return False
            # The outcome only. Two validators can see the same outage as a
            # 502 and a timeout, and both are right that it was down.
            return leader.get("outcome") == _read(url, marker)["outcome"]

        agreed = gl.vm.run_nondet(leader_fn, validator_fn)
        outcome = str(agreed["outcome"])
        # Only an outcome this contract defines is ever written down.
        if outcome not in OUTCOMES:
            raise gl.vm.UserError("a reading no fetch could produce")

        stamp = _stamp()
        if outcome == UP:
            tally.up = tally.up + 1
        else:
            tally.down = tally.down + 1
        tally.last_at = stamp
        self.tallies[key] = tally
        self.taken[slot_key] = True
        self.readings.get_or_insert_default(key).append(Reading(at=stamp, slot=slot, outcome=outcome))
        return _tally_dict(key, tally, opens, ends, now)

    @gl.public.view
    def tally(self, plan_id: str) -> dict:
        """
        What the window measured.

        `closed` says whether more samples can still arrive. A consumer
        that settles money must wait for it, because a tally taken while
        the window is open is a reading in progress, not a result.
        """
        key = plan_id.strip().lower()
        terms = gl.contract.get_at(self.plan).view().get(key)
        opens = int(str(terms["opens_at"]))
        ends = int(str(terms["ends_at"]))
        tally = self.tallies[key] if key in self.tallies else Tally(up=0, down=0, last_at="")
        return _tally_dict(key, tally, opens, ends, epoch_seconds(_stamp()))

    @gl.public.view
    def samples(self, plan_id: str) -> list:
        key = plan_id.strip().lower()
        if key not in self.readings:
            return []
        return [{"at": r.at, "slot": str(r.slot), "outcome": r.outcome} for r in self.readings[key]]

    @gl.public.view
    def settings(self) -> dict:
        return {
            "plan": self.plan.as_hex,
            "slot_seconds": str(SLOT_SECONDS),
            "read_within_seconds": str(READ_WITHIN),
            "min_samples": str(MIN_SAMPLES),
        }


def _read(url: str, marker: str) -> dict:
    """Fetch once and reduce it to the one thing consensus is asked about."""
    try:
        resp = gl.nondet.web.get(url)
        status = int(resp.status)
        body = (resp.body or b"").decode("utf-8", errors="replace")
    except Exception:
        return {"outcome": unreached()["outcome"]}
    return {"outcome": classify(status, body, marker)["outcome"]}


def _stamp() -> str:
    return str(gl.message.raw["datetime"])


def _address(value) -> Address:
    if hasattr(value, "as_hex"):
        return value
    return Address(str(value).strip())


def _tally_dict(key: str, tally: Tally, opens: int, ends: int, now) -> dict:
    up = int(tally.up)
    down = int(tally.down)
    taken = up + down
    slots = slot_count(opens, ends)
    closed = ends >= 0 and now is not None and now >= ends
    return {
        "plan_id": key,
        "up": str(up),
        "down": str(down),
        "samples": str(taken),
        "slots": str(slots),
        "uptime_bp": str(uptime_bp(up, slots)),
        "enough": taken >= MIN_SAMPLES,
        "closed": closed,
        "last_at": tally.last_at,
    }
