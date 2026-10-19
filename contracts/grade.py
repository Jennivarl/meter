# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
"""
GRADE. The whole of what it takes to use a measured window elsewhere.

Not part of the billing system: this is the reference consumer, here so
nobody has to read LEDGER to work out the pattern. It holds a renewal shut
until one plan's closed window measured at least the required uptime.

    renew(note)   anyone may, once the window has closed high enough
    standing()    where the measurement has got to, and why it is shut

The gate is three lines, and the order is the part worth copying:

    tally = gl.contract.get_at(self.meter).view().tally(self.plan_id)
    if not tally["closed"]: refuse      # a window in progress is not a result
    if not tally["enough"]: refuse      # two samples are not a month
    if int(tally["uptime_bp"]) < self.required_bp: refuse

A consumer that skipped the first check could renew on a good first hour
of a month that went on to fail.
"""

from dataclasses import dataclass

import genlayer as gl
from genlayer.types import *

from contracts.metering import FULL


@gl.storage.allow
@dataclass
class Renewal:
    actor: Address
    note: str
    at: str
    uptime_bp: u256


class Grade(gl.contract.Contract):
    operator: Address
    # All fixed at deployment. A caller who can name the meter, the plan or
    # the threshold has already renewed.
    meter: Address
    plan_id: str
    required_bp: u256
    renewals: gl.storage.DynArray[Renewal]

    def __init__(self, meter: str, plan_id: str, required_bp: int):
        self.operator = gl.message.sender_address
        self.meter = _address(meter)
        key = plan_id.strip().lower()
        if not key:
            raise gl.vm.UserError("name the plan this grade reads")
        self.plan_id = key
        bar = int(required_bp)
        if bar <= 0 or bar > FULL:
            raise gl.vm.UserError(f"required uptime is 1 to {FULL} basis points")
        self.required_bp = bar

    @gl.public.write
    def renew(self, note: str) -> dict:
        """Renew, once the closed window measured high enough. Asks live."""
        tally = gl.contract.get_at(self.meter).view().tally(self.plan_id)
        if str(tally["plan_id"]).lower() != self.plan_id:
            raise gl.vm.UserError("that tally is about a different plan")
        if not bool(tally["closed"]):
            raise gl.vm.UserError("the window is still open, so this stays shut")
        if not bool(tally["enough"]):
            raise gl.vm.UserError("too few samples were taken to grade the window")
        measured = int(str(tally["uptime_bp"]))
        if measured < int(self.required_bp):
            raise gl.vm.UserError(
                f"measured {measured} basis points, below the {int(self.required_bp)} required"
            )
        entry = Renewal(
            actor=gl.message.sender_address,
            note=note.strip()[:200],
            at=_stamp(),
            uptime_bp=measured,
        )
        self.renewals.append(entry)
        return {"renewed": True, "by": entry.actor.as_hex, "uptime_bp": str(measured), "at": entry.at}

    @gl.public.view
    def standing(self) -> dict:
        tally = gl.contract.get_at(self.meter).view().tally(self.plan_id)
        measured = int(str(tally["uptime_bp"]))
        closed = bool(tally["closed"])
        enough = bool(tally["enough"])
        return {
            "operator": self.operator.as_hex,
            "meter": self.meter.as_hex,
            "plan_id": self.plan_id,
            "required_bp": str(self.required_bp),
            "uptime_bp": str(measured),
            "samples": str(tally["samples"]),
            "closed": closed,
            "enough": enough,
            "open": closed and enough and measured >= int(self.required_bp),
        }

    @gl.public.view
    def history(self) -> list:
        return [
            {"actor": r.actor.as_hex, "note": r.note, "at": r.at, "uptime_bp": str(r.uptime_bp)}
            for r in self.renewals
        ]


def _stamp() -> str:
    return str(gl.message.raw["datetime"])


def _address(value) -> Address:
    if hasattr(value, "as_hex"):
        return value
    return Address(str(value).strip())
