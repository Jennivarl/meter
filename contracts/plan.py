# v0.3.0
# { "Depends": "py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng" }
"""
PLAN. What will be measured, for how long, and for how much.

The terms both sides agree to before anything is measured:

    propose(name, provider, host, path, marker, fee, window_minutes)
    accept(plan_id)      the provider agrees to be measured this way
    withdraw(plan_id)    the buyer walks away before the provider does

Nothing is measured or paid here. PLAN only fixes terms, and fixes them
completely: the URL, the marker that means healthy, the fee and the length
of the window are all immutable from the moment of proposal.

The window opens when the provider accepts, not at any time either side
types. Nobody can choose a start date that happens to miss a known outage,
and nothing can be measured before both sides have agreed to the terms.
"""

from dataclasses import dataclass

import genlayer as gl
from genlayer.types import *

from contracts.metering import (
    MAX_WINDOW,
    MIN_WINDOW,
    epoch_seconds,
    url_for,
    valid_host,
    valid_marker,
    valid_path,
)

STATE_PROPOSED = "proposed"
STATE_LIVE = "live"
STATE_WITHDRAWN = "withdrawn"


@gl.storage.allow
@dataclass
class Terms:
    buyer: Address
    provider: Address
    name: str
    host: str
    path: str
    marker: str
    fee: u256
    window_seconds: u256
    proposed_at: str
    accepted_at: str
    state: str


class PlanBook(gl.contract.Contract):
    plans: gl.storage.TreeMap[str, Terms]
    plan_ids: gl.storage.DynArray[str]

    def __init__(self):
        pass

    @gl.public.write
    def propose(
        self,
        name: str,
        provider: str,
        host: str,
        path: str,
        marker: str,
        fee: int,
        window_minutes: int,
    ) -> dict:
        """
        Put terms to a provider. The buyer's own commitment, fixed here.
        """
        label = name.strip().lower()
        if not label or len(label) > 40:
            raise gl.vm.UserError("name the plan")
        for ch in label:
            if not (("0" <= ch <= "9") or ("a" <= ch <= "z") or ch in "-_"):
                raise gl.vm.UserError("a name is letters, digits, hyphen or underscore")

        buyer = gl.message.sender_address
        seller = _address(provider)
        if seller.as_hex.lower() == buyer.as_hex.lower():
            raise gl.vm.UserError("a plan needs a buyer and a different provider")
        if seller.as_hex.lower() == "0x" + "00" * 20:
            raise gl.vm.UserError("name a real provider")

        if not valid_host(host):
            raise gl.vm.UserError("a host is a bare hostname, like status.example.com")
        if not valid_path(path):
            raise gl.vm.UserError("a path starts at / and has no query or traversal")
        if not valid_marker(marker):
            raise gl.vm.UserError("name the text a healthy response contains, in one line")

        amount = int(fee)
        if amount <= 0:
            raise gl.vm.UserError("the fee must be more than zero")
        seconds = int(window_minutes) * 60
        if seconds < MIN_WINDOW or seconds > MAX_WINDOW:
            raise gl.vm.UserError(
                f"a window is {MIN_WINDOW // 60} minutes to {MAX_WINDOW // 86400} days"
            )

        plan_id = buyer.as_hex.lower() + ":" + label
        if plan_id in self.plans:
            raise gl.vm.UserError("that plan already exists and cannot be changed")

        self.plans[plan_id] = Terms(
            buyer=buyer,
            provider=seller,
            name=label,
            host=host.strip().lower(),
            path=path.strip(),
            marker=marker.strip(),
            fee=amount,
            window_seconds=seconds,
            proposed_at=_stamp(),
            accepted_at="",
            state=STATE_PROPOSED,
        )
        self.plan_ids.append(plan_id)
        return _as_dict(plan_id, self.plans[plan_id])

    @gl.public.write
    def accept(self, plan_id: str) -> dict:
        """
        Agree to be measured on these terms. The named provider only.

        The billing window opens now, at this transaction's own time.
        """
        key = plan_id.strip().lower()
        terms = self._get(key)
        if terms.state != STATE_PROPOSED:
            raise gl.vm.UserError("that plan is " + terms.state)
        if gl.message.sender_address.as_hex.lower() != terms.provider.as_hex.lower():
            raise gl.vm.UserError("only the named provider may accept")
        terms.state = STATE_LIVE
        terms.accepted_at = _stamp()
        self.plans[key] = terms
        return _as_dict(key, terms)

    @gl.public.write
    def withdraw(self, plan_id: str) -> dict:
        """
        The buyer walks away, but only before the provider has accepted.

        After acceptance the window is running and both sides are bound to
        whatever it measures.
        """
        key = plan_id.strip().lower()
        terms = self._get(key)
        if terms.state != STATE_PROPOSED:
            raise gl.vm.UserError("that plan is " + terms.state + " and can no longer be withdrawn")
        if gl.message.sender_address.as_hex.lower() != terms.buyer.as_hex.lower():
            raise gl.vm.UserError("only the buyer may withdraw a plan")
        terms.state = STATE_WITHDRAWN
        self.plans[key] = terms
        return _as_dict(key, terms)

    @gl.public.view
    def get(self, plan_id: str) -> dict:
        return _as_dict(plan_id.strip().lower(), self._get(plan_id.strip().lower()))

    @gl.public.view
    def plan_list(self) -> list:
        return [p for p in self.plan_ids]

    def _get(self, key: str) -> Terms:
        if key not in self.plans:
            raise gl.vm.UserError("no such plan: " + key)
        return self.plans[key]


def _stamp() -> str:
    return str(gl.message.raw["datetime"])


def _address(value) -> Address:
    if hasattr(value, "as_hex"):
        return value
    return Address(str(value).strip())


def _as_dict(key: str, terms: Terms) -> dict:
    opened = epoch_seconds(terms.accepted_at) if terms.accepted_at else None
    ends = opened + int(terms.window_seconds) if opened is not None else -1
    return {
        "plan_id": key,
        "buyer": terms.buyer.as_hex,
        "provider": terms.provider.as_hex,
        "name": terms.name,
        "host": terms.host,
        "path": terms.path,
        "url": url_for(terms.host, terms.path),
        "marker": terms.marker,
        "fee": str(terms.fee),
        "window_seconds": str(terms.window_seconds),
        "proposed_at": terms.proposed_at,
        "accepted_at": terms.accepted_at,
        # Seconds since the epoch, or -1 while the window has not opened.
        "opens_at": str(opened if opened is not None else -1),
        "ends_at": str(ends),
        "state": terms.state,
    }
