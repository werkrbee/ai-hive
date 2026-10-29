"""The usage ledger and the monthly ceiling.

Entries use knowledge-hive's ledger format (hives/knowledge-hive/DESIGN.md), one JSON
object per line. The month's total is summed when the server starts and kept up to date
as entries are appended, so the ledger is read once.

Before a review runs, its worst-case cost (the contract budget's share it could use) is
reserved. A review is refused once the month's spending plus what is reserved reaches
the ceiling, so concurrent reviews can't jointly run past it. A call that reports its
usage is recorded at its metered tokens; one that doesn't (a timeout, a cancel, a provider
error after the request was sent, or the process dying mid-call) is recorded at its whole
reservation; calls in flight are kept in `<ledger>.pending` so a crash can't lose them. The
most the month can end over the ceiling is then one review's reservation, when the last
one runs from just below it, unless a reply runs past its estimate.

The total is kept in this process, so one server instance must own the ledger. Another
process that spends against the same ceiling, such as the weekly trust evaluation, keeps
its own ledger beside it, and each names the other as shared: at every reservation a
shared ledger is read afresh, with the calls it has in flight, and counted toward the
ceiling.
"""
import asyncio
import datetime
import json
import math
from dataclasses import dataclass
from pathlib import Path


class LedgerError(Exception):
    pass


@dataclass(frozen=True)
class Refusal:
    month: str
    spent_usd: float
    ceiling_usd: float
    resumes_on: str

    def text(self):
        return (f"Refused: the monthly spending ceiling of ${self.ceiling_usd:.2f} has been "
                f"reached (${self.spent_usd:.2f} spent or reserved in {self.month}). New reviews "
                f"are accepted again on {self.resumes_on}.")

    def data(self):
        return {"error": "monthly-ceiling-reached", "month": self.month,
                "spentUsd": round(self.spent_usd, 6), "ceilingUsd": self.ceiling_usd,
                "resumesOn": self.resumes_on}


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def month_of(at):
    return at.strftime("%Y-%m")


def next_month(at):
    first = at.date().replace(day=1)
    return (first.replace(year=first.year + 1, month=1) if first.month == 12
            else first.replace(month=first.month + 1)).isoformat()


def read_totals(path):
    """A ledger file's spending by month ("YYYY-MM"). Fails loud on an entry it can't sum:
    a ledger that can't be summed can't enforce the ceiling."""
    totals = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            entry = json.loads(line)
            at = datetime.datetime.fromisoformat(entry["at"].replace("Z", "+00:00"))
            if at.tzinfo is None:
                raise ValueError("at must carry a time zone (UTC)")
            usd = entry.get("usd", 0)
            if isinstance(usd, bool) or not isinstance(usd, (int, float)) or not math.isfinite(usd) or usd < 0:
                raise ValueError("usd must be a non-negative number")
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise LedgerError(f"{path}:{n}: can't read this entry ({e})")
        key = month_of(at.astimezone(datetime.timezone.utc))
        totals[key] = totals.get(key, 0.0) + usd
    return totals


def in_flight(path):
    """What a ledger's calls in flight could cost: the usd of each entry in its .pending."""
    pending = path.with_name(path.name + ".pending")
    try:
        leftover = json.loads(pending.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0.0
    except ValueError as e:
        raise LedgerError(f"{pending}: can't read the in-flight calls ({e})")
    if not isinstance(leftover, dict) or not all(isinstance(e, dict) for e in leftover.values()):
        raise LedgerError(f"{pending}: can't read the in-flight calls (expected an object of entries)")
    return sum(e.get("usd", 0) for e in leftover.values())


class Ledger:
    def __init__(self, path, ceiling_usd, clock=now, shared=()):
        self.path = Path(path)
        self.ceiling = ceiling_usd
        self.clock = clock
        # Other processes' ledgers that spend against the same ceiling, read at each
        # reservation.
        self.shared = [Path(p) for p in shared]
        self.reserved = 0.0
        self.totals = {}
        self.lock = asyncio.Lock()
        # Calls in flight, by task id: the entry to record if the process dies before the
        # call settles. Kept on disk so a crash or kill can't erase possibly billed calls.
        self.pending_path = self.path.with_name(self.path.name + ".pending")
        self.pending = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._load()
        self._recover()

    def _recover(self):
        """Record calls a previous process started and never settled."""
        if not self.pending_path.exists():
            return
        try:
            leftover = json.loads(self.pending_path.read_text(encoding="utf-8"))
            if not isinstance(leftover, dict) or not all(isinstance(e, dict) for e in leftover.values()):
                raise ValueError("expected an object of entries")
        except ValueError as e:
            raise LedgerError(f"{self.pending_path}: can't read the in-flight calls ({e})")
        for entry in leftover.values():
            self._append(entry)
        self.pending_path.unlink()

    def _write_pending(self):
        if not self.pending:
            self.pending_path.unlink(missing_ok=True)
            return
        tmp = self.pending_path.with_name(self.pending_path.name + ".tmp")
        tmp.write_text(json.dumps(self.pending), encoding="utf-8")
        tmp.replace(self.pending_path)

    def _append(self, entry):
        at = self.clock()
        entry = {"at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(", ", ": ")) + "\n")
        key = month_of(at)
        self.totals[key] = self.totals.get(key, 0.0) + entry.get("usd", 0)

    def _load(self):
        self.totals = read_totals(self.path)

    def spent(self, at=None):
        return self.totals.get(month_of(at or self.clock()), 0.0)

    def shared_spent(self, at):
        """What the shared ledgers have spent in at's month, or have in flight."""
        total = 0.0
        for path in self.shared:
            if path.exists():
                total += read_totals(path).get(month_of(at), 0.0)
            total += in_flight(path)
        return total

    async def reserve(self, usd):
        """Hold usd against the ceiling. Returns a Refusal instead when the ceiling is reached."""
        async with self.lock:
            at = self.clock()
            committed = self.spent(at) + self.reserved + self.shared_spent(at)
            if committed >= self.ceiling:
                return Refusal(month_of(at), committed, self.ceiling, next_month(at))
            self.reserved += usd
            return None

    async def start(self, key, entry):
        """A call is about to go out: if this process dies before it settles, record entry."""
        async with self.lock:
            self.pending[key] = entry
            self._write_pending()

    async def settle(self, reserved_usd, entry=None, key=None):
        """Release a reservation, and append the entry for what was actually used."""
        async with self.lock:
            self.reserved = max(0.0, self.reserved - reserved_usd)
            if entry is not None:
                self._append(entry)
            if key in self.pending:
                del self.pending[key]
                self._write_pending()
