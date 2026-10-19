"""
The pure part of METER. No chain, no network, no money.

Paying for a service usually means paying for a promise: a monthly fee for
"99.9% uptime", and a support ticket if it was not. METER pays for what was
measured instead. The buyer escrows the fee, the contract samples the
provider's own health URL across the billing window, and at the end the
provider is paid for the share of samples that found the service up. The
rest goes back to the buyer.

Everything here is a decision every validator re-derives identically:

    what a fetch result means          up, or down and why
    whether there is enough to bill     at least MIN_SAMPLES taken
    how the fee divides                 exactly, with nothing created or lost

Every sample consensus agrees on counts, and only a healthy answer is paid.
There is deliberately no third bucket for samples that "do not count". Any
such bucket is a lever for the provider: a server that goes dark after three
good samples would stand at three up out of three counted, and be paid in
full. A host the network cannot reach is a sample against the provider, who
chose the URL and agreed to be measured from it.

That is the opposite of how VIGIL treats the same fact, and on purpose. For
an inheritance, mistaking an unreachable host for silence hands over an
estate, so it must count for nothing. For a bill, ignoring it pays for an
outage. Which way an ambiguous reading falls is decided by who would be
hurt by getting it wrong.
"""

UP = "up"
DOWN = "down"

OUTCOMES = (UP, DOWN)

# Nothing is billed on fewer samples than this. Two samples cannot
# tell a flaky minute from a bad month, and billing on no evidence at all
# would mean paying for a promise again.
MIN_SAMPLES = 3

# Samples must be at least this far apart, measured across every caller.
# Without it a party could take a burst of samples in one good minute and
# call that a month.
MIN_SAMPLE_GAP = 600

# A billing window long enough to hold MIN_SAMPLES spaced samples, and no
# longer than a month.
MIN_WINDOW = 1800
MAX_WINDOW = 31 * 24 * 3600

# The share of samples that found the service up, in basis points.
FULL = 10000

_MAX_PATH = 120
_MAX_MARKER = 80


def valid_host(host: str) -> bool:
    """
    A bare hostname: letters, digits, dots and hyphens.

    No scheme, no slash, no port, no credentials. The contract builds the
    URL itself, so nothing in this value can smuggle in a second host.
    """
    h = (host or "").strip().lower()
    if not h or len(h) > 100 or h.startswith(".") or h.endswith(".") or ".." in h:
        return False
    for ch in h:
        if not (("0" <= ch <= "9") or ("a" <= ch <= "z") or ch in "-."):
            return False
    return "." in h


def valid_path(path: str) -> bool:
    """A path from the root. No traversal, no scheme, no query, no fragment."""
    p = (path or "").strip()
    if not p.startswith("/") or len(p) > _MAX_PATH:
        return False
    if ".." in p or "://" in p or "?" in p or "#" in p or "//" in p:
        return False
    for ch in p:
        if ch <= " " or ch == "\x7f":
            return False
    return True


def valid_marker(marker: str) -> bool:
    """
    The text a healthy response must contain, in the provider's own words.

    Required, because "the server answered" is not "the service works": a
    placeholder page, a maintenance banner or an error styled as a 200 all
    answer.
    """
    m = (marker or "").strip()
    return bool(m) and len(m) <= _MAX_MARKER and "\n" not in m and "\r" not in m


def url_for(host: str, path: str) -> str:
    """The only URL a sample ever fetches, built here and nowhere else."""
    return "https://" + host.strip().lower() + path.strip()


def classify(status: int, body: str, marker: str) -> dict:
    """
    One fetch reduced to an outcome and the reason for it.

    The reason is compared between validators as well as the outcome, so
    two cannot agree a sample was down while disagreeing about why. Only
    one answer is up; every other answer is down, with the reason kept so
    a reader can see what kind of down it was.

        2xx with the marker      up
        2xx without it           down: it answered, but not as itself
        any other status         down: the agreed URL did not serve the
                                 service, whatever the reason
    """
    code = int(status)
    if 200 <= code < 300:
        if marker.strip() in (body or ""):
            return {"outcome": UP, "note": "answered with the marker"}
        return {"outcome": DOWN, "note": "answered without the marker"}
    return {"outcome": DOWN, "note": "answered " + str(code)}


def unreached() -> dict:
    """
    The fetch itself failed: no DNS, no connection, no TLS, no answer.

    Down, not ignored. Consensus means the leader and the validators each
    failed on their own, and the one thing they share is the host.
    """
    return {"outcome": DOWN, "note": "could not be reached"}


def uptime_bp(up: int, samples: int) -> int:
    """Measured uptime in basis points, rounded down. 0 before any sample."""
    if samples <= 0:
        return 0
    return (int(up) * FULL) // int(samples)


def share(fee: int, up: int, samples: int) -> dict:
    """
    How the escrowed fee divides between the two sides.

    The provider is paid for the share of samples that found the service
    up, rounded down; the buyer gets everything else. The two parts always
    sum to exactly the fee, so no rounding can create or lose value, and
    any fraction left by rounding goes to the side that paid.

    Below MIN_SAMPLES the provider gets nothing and the buyer gets it all
    back: there is not enough evidence to bill on.
    """
    total = int(fee)
    up_n = int(up)
    taken = int(samples)
    if total < 0 or up_n < 0 or taken < 0 or up_n > taken:
        raise ValueError("an impossible tally")
    if taken < MIN_SAMPLES:
        return {"provider": 0, "buyer": total, "billed": False}
    provider = (total * up_n) // taken
    return {"provider": provider, "buyer": total - provider, "billed": True}


def epoch_seconds(stamp: str):
    """
    An ISO-8601 UTC timestamp as whole seconds, or None.

    Only the fixed "YYYY-MM-DDTHH:MM:SS" prefix is read, so the network's
    fractional seconds and a test's whole ones mean the same instant.
    """
    s = (stamp or "").strip()
    if len(s) < 19 or s[4] != "-" or s[7] != "-" or s[10] != "T" or s[13] != ":" or s[16] != ":":
        return None
    for i in (0, 1, 2, 3, 5, 6, 8, 9, 11, 12, 14, 15, 17, 18):
        if not ("0" <= s[i] <= "9"):
            return None
    year, month, day = int(s[0:4]), int(s[5:7]), int(s[8:10])
    hour, minute, second = int(s[11:13]), int(s[14:16]), int(s[17:19])
    if not (1 <= month <= 12) or day < 1 or day > _days_in_month(year, month):
        return None
    if hour > 23 or minute > 59 or second > 60:
        return None
    return _days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Integer only and no library, because every validator must agree."""
    y = year - (1 if month <= 2 else 0)
    era = (y if y >= 0 else y - 399) // 400
    year_of_era = y - era * 400
    day_of_year = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468
