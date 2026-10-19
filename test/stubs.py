"""
Stand-ins for the contracts METER's suite reads.

Direct mode loads one contract per process, so METER, LEDGER and GRADE
cannot be tested against the real PLAN or the real METER in the same test.
This answers the cross-contract call with the protocol the chain uses,
dispatching on the method name exactly as separate contracts would, and
records every transfer so a test can assert on money rather than on log
lines.

What a stub buys is states that take an hour to produce for real: a window
mid-way, a window closed on a good month, and one closed on a bad one.
"""

from contracts.metering import epoch_seconds

BUYER = b"\xa0" * 20
PROVIDER = b"\xb0" * 20
STRANGER = b"\xc0" * 20

PLAN_AT = "0x" + ("dd" * 20)
METER_AT = "0x" + ("ee" * 20)

NAME = "api"
PLAN_ID = "0x" + BUYER.hex() + ":" + NAME
HOST = "status.example.com"
PATH = "/health"
MARKER = "all systems operational"

FEE = 1_000_000
WINDOW = 3600

# The window opens at 09:00 and closes at 10:00.
T_OPEN = "2026-10-20T09:00:00Z"
OPENS = epoch_seconds(T_OPEN)
ENDS = OPENS + WINDOW

# An EVM transfer, which is how value reaches a plain wallet.
EVM_PAY = "EmitExternalMessage"


def at(minute: int) -> str:
    """A timestamp `minute` minutes after the window opens."""
    total = 9 * 60 + minute
    return f"2026-10-20T{total // 60:02d}:{total % 60:02d}:00Z"


class Stubs:
    """One hook answering for PLAN and METER."""

    def __init__(self):
        self.terms = {
            "plan_id": PLAN_ID,
            "buyer": "0x" + BUYER.hex(),
            "provider": "0x" + PROVIDER.hex(),
            "name": NAME,
            "host": HOST,
            "path": PATH,
            "url": "https://" + HOST + PATH,
            "marker": MARKER,
            "fee": str(FEE),
            "window_seconds": str(WINDOW),
            "proposed_at": "2026-10-20T08:50:00Z",
            "accepted_at": T_OPEN,
            "opens_at": str(OPENS),
            "ends_at": str(ENDS),
            "state": "live",
        }
        self.reading = {
            "plan_id": PLAN_ID,
            "up": "0",
            "down": "0",
            "samples": "0",
            "uptime_bp": "0",
            "enough": False,
            "closed": False,
            "last_at": "",
        }
        self.transfers = []
        self.calls = []

    def set_terms(self, **changes):
        self.terms = {**self.terms, **changes}
        return self

    def proposed(self):
        """Before the provider has accepted: no window yet."""
        return self.set_terms(state="proposed", accepted_at="", opens_at="-1", ends_at="-1")

    def closed(self, up: int, down: int):
        """A window that has ended with this many readings."""
        taken = up + down
        self.reading = {
            **self.reading,
            "up": str(up),
            "down": str(down),
            "samples": str(taken),
            "uptime_bp": str((up * 10000) // taken if taken else 0),
            "enough": taken >= 3,
            "closed": True,
        }
        return self

    def install(self, vm):
        def hook(_vm, request):
            # Imported here rather than at install time: the SDK only
            # exists once a contract has been loaded.
            from gltest.direct.sdk_compat import import_calldata

            calldata = import_calldata()

            for kind in ("PostMessage", "EthSend", EVM_PAY):
                if kind in request:
                    msg = request[kind]
                    self.transfers.append(
                        {"to": bytes(msg["address"].as_bytes), "value": int(msg["value"]), "kind": kind}
                    )
                    return {"ok": None}

            if "CallContract" not in request:
                return None
            method = request["CallContract"]["calldata"][""]
            self.calls.append(method)
            answer = self.reading if method == "tally" else self.terms
            return bytes([0]) + calldata.encode(answer)

        vm._gl_call_hook = hook
        return self
