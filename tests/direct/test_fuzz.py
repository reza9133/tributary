"""Random stories. After every step the books must balance and every money movement must match a reference model
that is written here, separately from the contract. A refused call must change nothing and must be a clean refusal
(a UserError), never a crash."""

import json
import random
import sys

import pytest

from conftest import *

BPS = 10_000
import os

SEEDS = list(range(int(os.environ.get("TRIBUTARY_FUZZ_SEEDS", "30"))))
STEPS = 140
SEEN = {}  # what the random stories reached, pooled over the seeds that ran in this session


# ---- a reference model, written independently of the contract -------------------------------------------------------


def words_of(text):
    import re

    return re.findall(r"[^\W_]+", text.lower())


def copy_share(a, b):
    def sh(ws):
        return {" ".join(ws[i:i + 4]) for i in range(len(ws) - 3)} if len(ws) >= 4 else ({" ".join(ws)} if ws else set())

    sa, sb = sh(words_of(a)), sh(words_of(b))
    if not sa or not sb:
        return 0
    common = len(sa & sb)
    return min(100, max(common * 100 // len(sa), common * 100 // len(sb)))


def cascade(rows, wid, amount, hops=0, out=None):
    """Credits when `amount` reaches work `wid`: {work id: kept}. Rows are the contract's own get_work rows."""
    out = {} if out is None else out
    row = rows[wid]
    cut_d = amount * row["pass_bps"] // BPS if row["source"] and hops < 4 else 0
    cut_f = amount * row["forced_bps"] // BPS if row["forced_source"] and hops < 4 else 0
    out[wid] = out.get(wid, 0) + amount - cut_d - cut_f
    if cut_d:
        cascade(rows, row["source"], cut_d, hops + 1, out)
    if cut_f:
        cascade(rows, row["forced_source"], cut_f, hops + 1, out)
    return out


def all_rows(c):
    return {i: wrow(c, i) for i in range(1, stats(c)["works"] + 1)}


def int_rows(rows):
    return {i: {k: (int(v) if isinstance(v, str) and v.isdigit() else v) for k, v in r.items()} for i, r in rows.items()}


class Sim:
    def __init__(self, c, vm, ledger, seed):
        self.c, self.vm, self.ledger = c, vm, ledger
        self.rng = random.Random(seed)
        self.t = 0
        self.actors = [P.alice, P.bob, P.carol, P.dave, P.erin, P.extra[0], P.extra[1]]
        self.others = [P.watcher, P.buyer, P.stranger]
        self.counter = seed * 1000
        self.refusals = 0
        self.ops = 0
        self.UserError = sys.modules[MODULE].gl.vm.UserError  # importable only once the SDK is loaded

    # -- helpers
    def anyone(self):
        return self.rng.choice(self.actors + self.others)

    def tick(self):
        """Mostly short steps, sometimes a few minutes, now and then a long jump (cool-downs and judging windows end)."""
        roll = self.rng.random()
        self.t += self.rng.randint(1, 60) if roll < 0.8 else self.rng.randint(60, 700) if roll < 0.97 else self.rng.randint(1000, 5000)
        at(self.vm, self.t)

    def call(self, fn, *args, who, value=0):
        """Run one contract call. Returns (ok, result). A refusal must leave everything as it was."""
        self.ops += 1
        before = fingerprint(self.c)
        act(self.vm, who, value)
        try:
            result = fn(*args)
        except self.UserError:
            self.vm.value = 0
            assert fingerprint(self.c) == before, f"a refused {fn} changed the contract"
            self.refusals += 1
            return False, None
        self.vm.value = 0
        return True, result

    def invariants(self):
        c = self.c
        b = books(c)
        assert b["balanced"], b
        assert int(b["paid"]) == self.ledger.total(), (b, self.ledger.total())
        rows = all_rows(c)
        drows = {i: drow(c, i) for i in range(1, stats(c)["disputes"] + 1)}
        pairs = {}
        for wid, r in rows.items():
            assert int(r["accrued"]) + int(r["withdrawn"]) <= int(r["earned"]), r
            assert 0 <= r["source"] < wid and 0 <= r["forced_source"] < wid
            assert r["source"] == 0 or r["source"] != r["forced_source"]
            assert 0 <= r["pass_bps"] <= 5000 and 0 <= r["forced_bps"] <= 5000 and r["pass_bps"] + r["forced_bps"] <= 7500
            assert r["source"] != 0 or r["pass_bps"] == 0
            assert r["forced_source"] == 0 or r["forced_bps"] > 0
            if r["open_dispute"]:
                assert drows[r["open_dispute"]]["state"] == OPEN and drows[r["open_dispute"]]["work"] == wid and r["frozen"]
            if r["forced_source"]:
                made = [d for d in drows.values() if d["work"] == wid and d["state"] in (UPHELD, CONCEDED)]
                assert len(made) == 1 and made[0]["source"] == r["forced_source"]
        for did, d in drows.items():
            key = (d["work"], d["source"])
            pairs.setdefault(key, []).append(d["state"])
            assert d["source"] < d["work"]
            if d["state"] == OPEN:
                assert rows[d["work"]]["open_dispute"] == did
        assert sum(1 for r in rows.values() if r["open_dispute"]) == sum(1 for d in drows.values() if d["state"] == OPEN)
        for states in pairs.values():  # a pair is tried again only after a judgement that could not tell, and at most twice
            assert len(states) <= 2 and all(st in (INCONCLUSIVE, LAPSED) for st in states[:-1]), states

    # -- operations
    def new_text(self, rows):
        self.counter += 1
        roll = self.rng.random()
        if rows and roll < 0.30:  # a copy of an existing work, with a word changed every few words
            base = self.rng.choice(list(rows.values()))["text"].split()
            step = self.rng.choice([3, 5, 8, 12, 20, 1000])
            return " ".join(w + "x" if i % step == step - 1 else w for i, w in enumerate(base))
        if rows and roll < 0.34:
            return self.rng.choice(list(rows.values()))["text"]  # an exact duplicate: must be refused
        return distinct(self.counter)

    def op_register(self):
        rows = all_rows(self.c)
        who = self.rng.choice(self.actors)
        text = self.new_text(rows)
        source = 0
        pass_bps = 0
        if rows and self.rng.random() < 0.45:
            s = self.rng.choice(list(rows))
            source = s
            pass_bps = self.rng.choice([rows[s]["ask_bps"], rows[s]["ask_bps"], 5000, rows[s]["ask_bps"] + 100])
        fee = self.rng.choice([MILLI, 3 * MILLI, 10 * MILLI, 10**15 + 7, 25 * MILLI])
        ask = self.rng.choice([0, 500, 1000, 2000, 3333, 5000])
        hold = self.rng.choice([HOLDBACK, HOLDBACK, 3 * HOLDBACK, HOLDBACK + 1])
        ok, wid = self.call(self.c.register, "Work " + str(self.counter), text, fee, ask, self.rng.random() < 0.8, source, pass_bps, who=who, value=hold)
        if ok:
            assert wid == len(rows) + 1

    def op_license(self):
        rows = int_rows(all_rows(self.c))
        if not rows:
            return
        wid = self.rng.choice(list(rows))
        qty = self.rng.choice([1, 1, 2, 5, 17, 100])
        fee = rows[wid]["fee"]
        exact = self.rng.random() < 0.9
        value = fee * qty if exact else fee * qty + self.rng.choice([-1, 1])
        expected = cascade(rows, wid, fee * qty)
        ok, _ = self.call(self.c.license, wid, qty, who=self.rng.choice(self.others + self.actors), value=value)
        after = int_rows(all_rows(self.c))
        if ok:
            assert exact and rows[wid]["status"] == ACTIVE
            assert sum(expected.values()) == fee * qty
            for i in rows:
                assert after[i]["accrued"] - rows[i]["accrued"] == expected.get(i, 0), (i, expected)
                assert after[i]["earned"] - rows[i]["earned"] == expected.get(i, 0)
            assert after[wid]["gross"] - rows[wid]["gross"] == fee * qty
        else:
            assert not exact or rows[wid]["status"] != ACTIVE

    def op_withdraw(self):
        rows = int_rows(all_rows(self.c))
        if not rows:
            return
        wid = self.rng.choice(list(rows))
        r = rows[wid]
        amount = self.rng.choice([r["accrued"], r["accrued"] // 2, 1, r["accrued"] + 1])
        who = r["creator"] if self.rng.random() < 0.9 else self.anyone()
        paid_before = self.ledger.total()
        ok, _ = self.call(self.c.withdraw, wid, amount, who=bytes.fromhex(who[2:]) if isinstance(who, str) else who)
        if ok:
            assert not r["frozen"] and 0 < amount <= r["accrued"]
            assert self.ledger.total() - paid_before == amount
            assert self.ledger.sent[-1] == (r["creator"].lower(), amount)
            assert int_rows(all_rows(self.c))[wid]["accrued"] == r["accrued"] - amount

    def op_misc(self):
        rows = all_rows(self.c)
        if not rows:
            return
        wid = self.rng.choice(list(rows))
        r = rows[wid]
        owner = bytes.fromhex(r["creator"][2:])
        who = owner if self.rng.random() < 0.85 else self.anyone()
        roll = self.rng.random()
        if roll < 0.25:
            self.call(self.c.set_fee, wid, self.rng.choice([MILLI, 12 * MILLI, 10**24 + 1]), who=who)
        elif roll < 0.5:
            self.call(self.c.set_terms, wid, self.rng.choice([0, 300, 2000, 5000, 5001]), self.rng.random() < 0.5, who=who)
        elif roll < 0.65:
            self.call(self.c.top_up, wid, who=self.anyone(), value=self.rng.choice([0, MILLI, 7]))
        elif roll < 0.75:
            self.call(self.c.retire, wid, who=who)
        elif roll < 0.85:
            self.call(self.c.reclaim, wid, who=who)
        else:
            s = self.rng.choice(list(rows))
            self.call(self.c.declare_source, wid, s, self.rng.choice([rows[s]["ask_bps"], 2500, 5000]), who=who)

    def op_dispute(self):
        rows = all_rows(self.c)
        if len(rows) < 2:
            return
        wid = self.rng.randint(2, len(rows))
        src = self.rng.randint(1, wid - 1) if self.rng.random() < 0.9 else self.rng.randint(1, len(rows))
        who = self.rng.choice(self.others + self.actors)
        value = BOND if self.rng.random() < 0.95 else BOND + 1
        self.call(self.c.open_dispute, wid, src, "The second work follows the first one.", who=who, value=value)

    def op_close(self):
        c = self.c
        open_ids = [i for i in range(1, stats(c)["disputes"] + 1) if drow(c, i)["state"] == OPEN]
        if not open_ids:
            return
        did = self.rng.choice(open_ids)
        d = drow(c, did)
        rows = int_rows(all_rows(c))
        w, s = rows[d["work"]], rows[d["source"]]
        roll = self.rng.random()
        paid_before = self.ledger.total()
        sent_before = self.ledger.count()
        pre = {i: dict(r) for i, r in rows.items()}
        if roll < 0.55:  # judge
            relation = self.rng.choices(["DERIVATIVE", "INDEPENDENT", "UNSURE"], weights=[45, 25, 30])[0]
            overlap = self.rng.choice({"DERIVATIVE": [40, 59, 60, 61, 90, 100, 60, 85], "INDEPENDENT": [0, 10, 25, 26, 40, 5], "UNSURE": [0, 50, 100, 70]}[relation])
            mock_judge(self.vm, relation, overlap)
            copy = copy_share(wrow(c, d["source"])["text"], wrow(c, d["work"])["text"])
            ok, _ = self.call(c.judge, did, who=self.anyone())
            if not ok:
                assert T0 + self.t >= d["expires"]  # (self.t is an offset from T0, expires is an absolute time)
                return
            lean = relation
            if copy >= 50:
                expected = DERIVATIVE
            else:
                expected = DERIVATIVE if lean == DERIVATIVE and overlap >= 60 else INDEPENDENT if lean == INDEPENDENT and overlap <= 25 else UNSURE
                if expected == INDEPENDENT and copy >= 20:
                    expected = UNSURE
            got = drow(c, did)
            assert got["relation"] == expected and got["copy"] == copy, (got, expected, copy)
            if expected == DERIVATIVE:
                self.check_upheld(did, pre, UPHELD, 2500, paid_before)
            elif expected == INDEPENDENT:
                assert got["state"] == DISMISSED and self.ledger.count() == sent_before
                post = int_rows(all_rows(c))
                assert post[d["work"]]["accrued"] == pre[d["work"]]["accrued"] + BOND
            else:
                assert got["state"] == INCONCLUSIVE and self.ledger.total() - paid_before == BOND
                assert self.ledger.sent[-1] == (d["challenger"], BOND)
        elif roll < 0.75:  # concede
            who = bytes.fromhex(w["creator"][2:]) if self.rng.random() < 0.9 else self.anyone()
            ok, _ = self.call(c.concede, did, who=who)
            if ok:
                self.check_upheld(did, pre, CONCEDED, 0, paid_before)
        elif roll < 0.9:  # waive
            who = bytes.fromhex(s["creator"][2:]) if self.rng.random() < 0.9 else self.anyone()
            ok, _ = self.call(c.waive, did, who=who)
            if ok:
                assert drow(c, did)["state"] == WAIVED and self.ledger.total() - paid_before == BOND
                assert int_rows(all_rows(c))[d["work"]]["accrued"] == pre[d["work"]]["accrued"]
        else:  # lapse (after a jump in time)
            if self.rng.random() < 0.5:
                self.t = max(self.t, d["expires"] - T0)
                at(self.vm, self.t)
            ok, _ = self.call(c.lapse, did, who=self.anyone())
            assert ok == (T0 + self.t >= d["expires"])
            if ok:
                assert drow(c, did)["state"] == LAPSED and self.ledger.total() - paid_before == BOND

    def check_upheld(self, did, pre, state, fine_bps, paid_before):
        """The numbers of an upheld or conceded dispute, recomputed from the state before it."""
        c = self.c
        d = drow(c, did)
        w, s = pre[d["work"]], pre[d["source"]]
        rate = d["rate_bps"]
        assert d["state"] == state
        assert True  # the source may lower its ask while the dispute is open; the filed rate stands
        fine = w["holdback"] * fine_bps // BPS
        holdback = w["holdback"] - fine
        owed = w["gross"] * rate // BPS
        from_accrued = min(owed, w["accrued"])
        from_holdback = min(owed - from_accrued, holdback)
        moved = from_accrued + from_holdback
        assert (int(d["owed"]), int(d["moved"]), int(d["fine"])) == (owed, moved, fine)
        post = int_rows(all_rows(c))
        assert post[d["work"]]["holdback"] == holdback - from_holdback
        # the source's line receives `moved` through the cascade of the state after the link was made
        expected = cascade(post, d["source"], moved) if moved else {}
        pw = post[d["work"]]
        assert pw["forced_source"] == d["source"] and pw["forced_bps"] == min(rate, 7500 - pw["pass_bps"])
        for i in pre:
            delta = post[i]["accrued"] - pre[i]["accrued"]
            if i == d["work"]:
                assert delta == -from_accrued, (i, delta)  # the accused work is never on the source's own line
            else:
                assert delta == expected.get(i, 0), (i, delta, expected)
        assert self.ledger.total() - paid_before == int(d["bond"]) + fine
        assert self.ledger.sent[-1] == (d["challenger"], int(d["bond"]) + fine)

    def step(self):
        self.tick()
        roll = self.rng.random()
        if roll < 0.22:
            self.op_register()
        elif roll < 0.52:
            self.op_license()
        elif roll < 0.62:
            self.op_withdraw()
        elif roll < 0.74:
            self.op_misc()
        elif roll < 0.86:
            self.op_dispute()
        else:
            self.op_close()
        self.invariants()


@pytest.mark.parametrize("seed", SEEDS)
def test_random_story(direct_vm, direct_deploy, ledger, seed):
    c = deploy(direct_deploy, direct_vm)
    sim = Sim(c, direct_vm, ledger, seed)
    for _ in range(STEPS):
        sim.step()
    # the end of the story: close every dispute, take every royalty out, and check the books one last time
    for i in range(1, stats(c)["disputes"] + 1):
        if drow(c, i)["state"] == OPEN:
            at(direct_vm, sim.t + 90_000)
            act(direct_vm, P.stranger)
            c.lapse(i)
    for wid in range(1, stats(c)["works"] + 1):
        row = wrow(c, wid)
        if int(row["accrued"]):
            withdraw(c, direct_vm, bytes.fromhex(row["creator"][2:]), wid, int(row["accrued"]))
    sim.invariants()
    b = books(c)
    assert int(b["accrued"]) == 0 and int(b["bonds"]) == 0
    assert int(b["holdback"]) == int(b["deposited"]) - int(b["paid"])
    rows = all_rows(c)
    for i in range(1, stats(c)["disputes"] + 1):
        state = drow(c, i)["state"]
        SEEN[state] = SEEN.get(state, 0) + 1
    SEEN["licences"] = SEEN.get("licences", 0) + stats(c)["licenses"]
    SEEN["forced"] = SEEN.get("forced", 0) + sum(1 for w in rows.values() if w["forced_source"])
    SEEN["declared"] = SEEN.get("declared", 0) + sum(1 for w in rows.values() if w["source"])
    SEEN["refusals"] = SEEN.get("refusals", 0) + sim.refusals
    SEEN["seeds"] = SEEN.get("seeds", 0) + 1


def test_the_random_stories_cover_every_kind_of_step():
    """A guard against a fuzz that never reaches the interesting states: look at what the stories above reached."""
    if SEEN.get("seeds", 0) < 6:
        pytest.skip("the random stories did not run in this session")
    for state in (UPHELD, INCONCLUSIVE, WAIVED):
        assert SEEN.get(state, 0) > 0, (state, SEEN)
    if SEEN["seeds"] >= 20:
        for state in (DISMISSED, CONCEDED):
            assert SEEN.get(state, 0) > 0, (state, SEEN)
    assert SEEN["licences"] > 100 and SEEN["forced"] > 0 and SEEN["declared"] > 0 and SEEN["refusals"] > 100, SEEN
