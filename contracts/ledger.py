# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
"""
LEDGER. The fee, held until the window closes, then divided by what METER
measured.

    fund(plan_id)      payable, the buyer escrows exactly the plan's fee
    reclaim(plan_id)   the buyer takes it back from a plan never accepted
    settle(plan_id)    after the window: the provider is paid for the share
                       of samples that found the service up, the buyer gets
                       the rest

This contract measures nothing and decides nothing. It reads the terms from
PLAN and the tally from METER, and moves money. Keeping custody apart from
measurement means the contract a caller can push readings into is never
the one holding the funds.

The fee must be in before the provider accepts. Otherwise a buyer could
watch the measurements and fund only a plan that was going to cost little,
and leave a provider who had been reliable unpaid.

Every funded state has a way out:

    plan accepted, window closed     settle divides it
    plan never accepted              the buyer withdraws it in PLAN, then
                                     reclaims the whole fee here
    window closed, too few samples   settle returns it all to the buyer,
                                     because there is nothing to bill on
"""

from dataclasses import dataclass

import genlayer as gl
from genlayer.types import *

from contracts.metering import MIN_SAMPLES, share, uptime_bp

STATE_FUNDED = "funded"
STATE_SETTLED = "settled"
STATE_RECLAIMED = "reclaimed"


@gl.storage.allow
@dataclass
class Escrow:
    plan_id: str
    buyer: Address
    provider: Address
    amount: u256
    funded_at: str
    state: str
    provider_paid: u256
    buyer_paid: u256
    uptime_bp: u256
    samples: u256
    decided_at: str
    reason: str


class Ledger(gl.contract.Contract):
    # Both fixed at deployment. A caller who could name the terms or the
    # meter could choose how much is owed.
    plan: Address
    meter: Address
    escrows: gl.storage.TreeMap[str, Escrow]
    escrow_ids: gl.storage.DynArray[str]
    committed: u256

    def __init__(self, plan: str, meter: str):
        self.plan = _address(plan)
        self.meter = _address(meter)
        self.committed = 0

    @gl.public.write.payable
    def fund(self, plan_id: str) -> dict:
        """
        Escrow the fee. The buyer, the exact amount, before acceptance.
        """
        key = plan_id.strip().lower()
        terms = self._terms(key)
        if str(terms["state"]) != "proposed":
            raise gl.vm.UserError("a plan is funded before the provider accepts it, and this one is " + str(terms["state"]))
        buyer = _address(terms["buyer"])
        if gl.message.sender_address.as_hex.lower() != buyer.as_hex.lower():
            raise gl.vm.UserError("only the buyer funds a plan")
        amount = int(gl.message.value)
        fee = int(str(terms["fee"]))
        if amount != fee:
            raise gl.vm.UserError(f"send exactly the plan's fee, {fee}")
        if key in self.escrows:
            raise gl.vm.UserError("that plan is already funded")

        self.escrows[key] = Escrow(
            plan_id=key,
            buyer=buyer,
            provider=_address(terms["provider"]),
            amount=amount,
            funded_at=_stamp(),
            state=STATE_FUNDED,
            provider_paid=0,
            buyer_paid=0,
            uptime_bp=0,
            samples=0,
            decided_at="",
            reason="held until the window closes",
        )
        self.escrow_ids.append(key)
        self.committed = self.committed + amount
        return _as_dict(key, self.escrows[key])

    @gl.public.write
    def reclaim(self, plan_id: str) -> dict:
        """
        The buyer takes back the fee from a plan the provider never took.

        Only once the buyer has withdrawn the plan in PLAN, which also stops
        the provider accepting it afterwards: otherwise the fee could leave
        while a provider was still entitled to accept.
        """
        key = plan_id.strip().lower()
        escrow = self._funded(key)
        terms = self._terms(key)
        if str(terms["state"]) != "withdrawn":
            raise gl.vm.UserError("withdraw the plan first; it is " + str(terms["state"]))
        if gl.message.sender_address.as_hex.lower() != escrow.buyer.as_hex.lower():
            raise gl.vm.UserError("only the buyer reclaims a fee")

        amount = int(escrow.amount)
        escrow.state = STATE_RECLAIMED
        escrow.buyer_paid = amount
        escrow.decided_at = _stamp()
        escrow.reason = "the plan was withdrawn before the provider accepted it"
        self.escrows[key] = escrow
        self.committed = self.committed - amount
        # State first, then value.
        _pay(escrow.buyer, amount)
        return _as_dict(key, escrow)

    @gl.public.write
    def settle(self, plan_id: str) -> dict:
        """
        Divide the fee by what was measured. Anyone may call it, because
        nothing a caller supplies changes the answer: the fee is here, the
        terms are in PLAN, and the tally is in METER.
        """
        key = plan_id.strip().lower()
        escrow = self._funded(key)
        terms = self._terms(key)
        if str(terms["state"]) != "live":
            raise gl.vm.UserError("that plan is " + str(terms["state"]) + ", not live")

        tally = gl.contract.get_at(self.meter).view().tally(key)
        if str(tally["plan_id"]).lower() != key:
            raise gl.vm.UserError("that tally is about a different plan")
        if not bool(tally["closed"]):
            raise gl.vm.UserError("the window is still open, so the tally is not final")

        up = int(str(tally["up"]))
        taken = int(str(tally["samples"]))
        split = share(int(escrow.amount), up, taken)

        escrow.state = STATE_SETTLED
        escrow.provider_paid = split["provider"]
        escrow.buyer_paid = split["buyer"]
        escrow.uptime_bp = uptime_bp(up, taken)
        escrow.samples = taken
        escrow.decided_at = _stamp()
        if split["billed"]:
            escrow.reason = f"{up} of {taken} samples found the service up"
        else:
            escrow.reason = f"only {taken} samples were taken and {MIN_SAMPLES} are needed to bill"
        self.escrows[key] = escrow
        self.committed = self.committed - int(escrow.amount)

        # State first, then value. Zero amounts move nothing.
        if split["provider"] > 0:
            _pay(escrow.provider, split["provider"])
        if split["buyer"] > 0:
            _pay(escrow.buyer, split["buyer"])
        return _as_dict(key, escrow)

    @gl.public.view
    def get_escrow(self, plan_id: str) -> dict:
        key = plan_id.strip().lower()
        if key not in self.escrows:
            raise gl.vm.UserError("no such escrow: " + key)
        return _as_dict(key, self.escrows[key])

    @gl.public.view
    def is_funded(self, plan_id: str) -> bool:
        """What a provider checks before accepting a plan."""
        key = plan_id.strip().lower()
        return key in self.escrows and self.escrows[key].state == STATE_FUNDED

    @gl.public.view
    def escrow_list(self) -> list:
        return [e for e in self.escrow_ids]

    @gl.public.view
    def reserves(self) -> dict:
        return {"committed": str(self.committed)}

    @gl.public.view
    def settings(self) -> dict:
        return {"plan": self.plan.as_hex, "meter": self.meter.as_hex, "min_samples": str(MIN_SAMPLES)}

    def _terms(self, key: str) -> dict:
        terms = gl.contract.get_at(self.plan).view().get(key)
        if str(terms["plan_id"]).lower() != key:
            raise gl.vm.UserError("those terms are about a different plan")
        return terms

    def _funded(self, key: str) -> Escrow:
        if key not in self.escrows:
            raise gl.vm.UserError("that plan was never funded")
        escrow = self.escrows[key]
        if escrow.state != STATE_FUNDED:
            raise gl.vm.UserError("that escrow is already " + escrow.state)
        return escrow


def _stamp() -> str:
    return str(gl.message.raw["datetime"])


def _address(value) -> Address:
    if hasattr(value, "as_hex"):
        return value
    return Address(str(value).strip())


@gl.evm.contract_interface
class _Wallet:
    """A plain account on the EVM side: nothing to call, only to pay."""

    class View:
        pass

    class Write:
        pass


def _pay(to: Address, amount: int) -> None:
    """
    The one place value leaves this contract.

    Through the EVM interface, which is what reaches a plain wallet. The
    transaction must also reserve a funded allocation for each outgoing
    message; settling a billed plan sends two.
    """
    _Wallet(to).emit_transfer(value=amount)


def _as_dict(key: str, escrow: Escrow) -> dict:
    return {
        "plan_id": key,
        "buyer": escrow.buyer.as_hex,
        "provider": escrow.provider.as_hex,
        "amount": str(escrow.amount),
        "funded_at": escrow.funded_at,
        "state": escrow.state,
        "provider_paid": str(escrow.provider_paid),
        "buyer_paid": str(escrow.buyer_paid),
        "uptime_bp": str(escrow.uptime_bp),
        "samples": str(escrow.samples),
        "decided_at": escrow.decided_at,
        "reason": escrow.reason,
    }
