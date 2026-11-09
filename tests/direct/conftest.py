"""Shared helpers for the direct-mode suite (genlayer-test fixtures)."""

import json
import sys
from datetime import datetime, timezone

import pytest

import os

CONTRACT = os.environ.get("TRIBUTARY_CONTRACT", "contracts/tributary.py")  # the variable lets the mutation check point at a damaged copy
MODULE = "_contract_" + os.path.splitext(os.path.basename(CONTRACT))[0]
GEN = 10**18
MILLI = 10**15  # 0.001 GEN, the smallest fee
HOLDBACK = 2 * 10**16  # the smallest holdback
BOND = 5 * 10**15
WINDOW = 3_600  # how long an open dispute can be judged, in seconds

ACTIVE, RETIRED = range(2)
OPEN, UPHELD, DISMISSED, CONCEDED, WAIVED, LAPSED, INCONCLUSIVE = range(7)
DERIVATIVE, INDEPENDENT, UNSURE = "DERIVATIVE", "INDEPENDENT", "UNSURE"

T0 = int(datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())

# Three short texts. TIDE is the original, TIDE_COPY repeats most of its words, TIDE_PARAPHRASE says the same things
# in other words (only a reader can tell), HARBOUR has nothing to do with them.
TIDE = (
    "At low tide the rock pools along the northern shore fill with small anemones, hermit crabs and patient "
    "limpets. Walk slowly, keep your shadow off the water, and lift each stone only a hand's width before "
    "putting it back exactly where it lay. The pools belong to the sea for twelve hours a day."
)
TIDE_COPY = (
    "At low tide the rock pools along the northern shore fill with small anemones, hermit crabs and patient "
    "limpets. Walk slowly, keep your shadow off the water, and lift each stone only a hand's width before "
    "putting it back where it lay. The pools belong to the ocean for twelve hours every day."
)
TIDE_PARAPHRASE = (
    "When the water drops, the northern coast's stone basins are crowded with tiny sea flowers, crabs that "
    "borrow shells and stubborn snails. Move gently, never let your silhouette fall across the surface, and "
    "raise every rock by no more than a palm before returning it to its exact spot. Half of every day the "
    "basins are the sea's, not ours."
)
HARBOUR = (
    "The harbour master keeps a ledger of every vessel that ties up at the long quay, noting the draught, "
    "the cargo and the hour of arrival in blue ink. Fees for the night are settled in the morning, and no "
    "ship may leave before its mooring lines have been inspected by the dock foreman."
)
SHIP_FEES = (
    "Seasonal mooring contracts for small fishing boats are renewed each spring after the berth inspection, "
    "and the committee publishes the new rate card on the first Monday of March together with a map of the "
    "free anchorages and the winter storm shelters."
)


def hx(a) -> str:
    """Lower-case 0x form of an address object, raw bytes or a hex string."""
    if isinstance(a, str):
        return a.lower()
    if hasattr(a, "as_hex"):
        return str(a.as_hex).lower()
    return "0x" + bytes(a).hex()


def at(vm, offset: int) -> None:
    """Move the chain clock to T0 + offset seconds."""
    vm.warp(datetime.fromtimestamp(T0 + offset, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def act(vm, who, value: int = 0):
    """The next call is made by `who` and carries `value`."""
    try:
        vm.deal(who, 1000 * GEN)
    except Exception:
        pass
    vm.sender = who
    vm.value = value


class Wire:
    """Stands in for the chain-level transfer so that payouts can be inspected."""

    sent = []

    def __init__(self, who):
        self.who = who

    def emit_transfer(self, **kw):
        Wire.sent.append((hx(self.who), int(kw["value"])))


class Ledger:
    def __init__(self):
        Wire.sent = []

    @property
    def sent(self):
        return Wire.sent

    def to(self, who) -> int:
        key = hx(who)
        return sum(v for a, v in Wire.sent if a == key)

    def total(self) -> int:
        return sum(v for _, v in Wire.sent)

    def count(self) -> int:
        return len(Wire.sent)


@pytest.fixture
def ledger():
    return Ledger()


def _forget_contract_class() -> None:
    """The SDK keeps one contract class per process; drop it so every test can deploy afresh."""
    for name in ("genlayer.gl.genvm_contracts", "genlayer.genvm_contracts"):
        registry = sys.modules.get(name)
        if registry is not None and hasattr(registry, "__known_contract__"):
            registry.__known_contract__ = None


def deploy(direct_deploy, direct_vm):
    at(direct_vm, 0)
    direct_vm.check_pickling = True  # the closures handed to the VM must be serializable
    _forget_contract_class()
    c = direct_deploy(CONTRACT)
    mod = sys.modules[MODULE]
    mod._Wire = Wire
    Wire.sent = []
    return c


def stats(c) -> dict:
    return json.loads(c.stats())


def books(c) -> dict:
    return json.loads(c.solvency())


def _lowered(row):
    """The contract reports checksummed addresses; the tests compare lower-case ones."""
    if isinstance(row, dict):
        for k, v in row.items():
            if k in ("creator", "challenger") and isinstance(v, str):
                row[k] = v.lower()
            elif k == "lineage":
                for step in v:
                    _lowered(step)
    return row


def wrow(c, work_id: int) -> dict:
    return _lowered(json.loads(c.get_work(work_id)))


def drow(c, dispute_id: int) -> dict:
    return _lowered(json.loads(c.get_dispute(dispute_id)))


def reg(
    c, vm, who, text=TIDE, title="Tide pools", fee=10 * MILLI, ask=2000, open_terms=True, source=0, pass_bps=0,
    holdback=HOLDBACK,
) -> int:
    """Register a work as `who` and return its id."""
    act(vm, who, holdback)
    wid = c.register(title, text, fee, ask, open_terms, source, pass_bps)
    vm.value = 0
    return wid


def buy(c, vm, who, work_id, quantity=1):
    fee = int(wrow(c, work_id)["fee"])
    act(vm, who, fee * quantity)
    c.license(work_id, quantity)
    vm.value = 0


def withdraw(c, vm, who, work_id, amount):
    act(vm, who)
    c.withdraw(work_id, amount)


def reply(relation="UNSURE", overlap=50, reason="The two works are alike in places."):
    return {"relation": relation, "overlap": overlap, "reason": reason}


def mock_judge(vm, relation="UNSURE", overlap=50, reason="The two works are alike in places.", raw=None):
    """The judge's answer. It only matches the judge prompt."""
    vm.clear_mocks()
    vm.mock_llm(r"judge of a royalty registry", raw if raw is not None else json.dumps(reply(relation, overlap, reason)))


def dispute(c, vm, who, work_id, source_id, reason="The second work follows the first one closely.", offset=None) -> int:
    if offset is not None:
        at(vm, offset)
    act(vm, who, BOND)
    did = c.open_dispute(work_id, source_id, reason)
    vm.value = 0
    return did


def judge(c, vm, who, dispute_id, relation=None, overlap=50, offset=None, **kw):
    """Run the judgement with the model saying `relation` (when None the mock is left as it is)."""
    if relation is not None:
        mock_judge(vm, relation, overlap, **kw)
    if offset is not None:
        at(vm, offset)
    act(vm, who)
    c.judge(dispute_id)


def fingerprint(c) -> str:
    """Everything observable about the contract, so that a refused call can be shown to change nothing."""
    s = stats(c)
    return json.dumps(
        [
            s, books(c), [wrow(c, i) for i in range(1, s["works"] + 1)],
            [drow(c, i) for i in range(1, s["disputes"] + 1)], list(Wire.sent),
        ],
        sort_keys=True,
    )


def refuse(c, vm, msg, fn, *args, who=None, value=0):
    """The call must be refused with `msg` in the error, and it must leave the contract exactly as it was."""
    if who is not None:
        act(vm, who, value)
    before = fingerprint(c)
    with vm.expect_revert(msg):
        fn(*args)
    vm.value = 0
    assert fingerprint(c) == before, "a refused call changed the contract"


def _actor(n: int) -> bytes:
    return bytes([0xB0, n]) + bytes(18)


class P:
    """Fixed actors, as raw 20-byte addresses."""

    alice = _actor(1)
    bob = _actor(2)
    carol = _actor(3)
    dave = _actor(4)
    erin = _actor(5)
    watcher = _actor(7)
    buyer = _actor(8)
    stranger = _actor(9)
    extra = [_actor(20 + i) for i in range(60)]


ZERO_ADDRESS = "0x" + "0" * 40


def split_of(fee, passes):
    """The expected credits for a fee paid at the bottom of a line: `passes` are the shares (basis points) every
    work on the line passes up to the next one, lowest work first. Returns the credits, lowest work first."""
    credits = []
    left = fee
    for i, bps in enumerate(passes[:4]):
        cut = left * bps // 10_000
        credits.append(left - cut)
        left = cut
        if cut == 0:
            return credits
    credits.append(left)
    return credits


_SYLLABLES = [a + b for a in "bdfgklmnprstvz" for b in ("a", "e", "i", "o", "u")]


def distinct(i: int, words: int = 30) -> str:
    """A text of `words` made-up words that shares no four-word run with the text of any other index."""
    import random

    rng = random.Random(10_000 + i)
    vocab = [rng.choice(_SYLLABLES) + rng.choice(_SYLLABLES) + rng.choice(_SYLLABLES) for _ in range(words)]
    return " ".join(vocab[:words]) + f" ledger{i}."
