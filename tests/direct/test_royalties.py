"""Licences, the cascade of royalties up the line of sources, rounding, previews and withdrawals."""

import json

import pytest

from conftest import *
from test_works import text_n


@pytest.fixture
def c(direct_vm, direct_deploy):
    return deploy(direct_deploy, direct_vm)


@pytest.fixture
def vm(direct_vm):
    return direct_vm


def chain(c, vm, passes, fee=10 * MILLI, ask=0):
    """A line of works. The first id is the top source; passes[i] is what work i+2 passes up to work i+1.
    Every work has a different creator. Returns the ids, top first."""
    ids = [reg(c, vm, P.extra[0], text=text_n(0), ask=ask, fee=fee)]
    for i, bps in enumerate(passes, start=1):
        ids.append(reg(c, vm, P.extra[i], text=text_n(i), ask=ask, fee=fee, source=ids[-1], pass_bps=bps))
    return ids


def accrued(c, ids):
    return [int(wrow(c, i)["accrued"]) for i in ids]


# ---- buying a licence -----------------------------------------------------------------------------------------------


def test_a_licence_on_a_work_without_a_source_goes_entirely_to_its_creator(c, vm):
    a = reg(c, vm, P.alice, fee=10 * MILLI)
    buy(c, vm, P.buyer, a, 3)
    row = wrow(c, a)
    assert (row["accrued"], row["gross"], row["earned"], row["passed"], row["licenses"]) == (str(30 * MILLI), str(30 * MILLI), str(30 * MILLI), "0", 3)
    s = stats(c)
    assert (s["licenses"], s["volume"], s["deposited"]) == (3, str(30 * MILLI), str(HOLDBACK + 30 * MILLI))
    assert books(c)["balanced"]


def test_the_creator_may_buy_a_licence_of_their_own_work(c, vm):
    a = reg(c, vm, P.alice)
    buy(c, vm, P.alice, a, 1)
    assert wrow(c, a)["accrued"] == str(10 * MILLI)


LICENSE_BAD = [
    ("quantity zero", dict(quantity=0), "between 1 and 100"),
    ("quantity negative", dict(quantity=-1), "between 1 and 100"),
    ("quantity above 100", dict(quantity=101), "between 1 and 100"),
    ("too little", dict(value=10 * MILLI - 1), "exactly the fee"),
    ("too much", dict(value=10 * MILLI + 1), "exactly the fee"),
    ("nothing", dict(value=0), "exactly the fee"),
    ("one fee for two licences", dict(quantity=2, value=10 * MILLI), "exactly the fee"),
]


@pytest.mark.parametrize("label,kw,msg", LICENSE_BAD, ids=[x[0] for x in LICENSE_BAD])
def test_a_licence_is_refused_unless_the_value_is_exactly_fee_times_quantity(c, vm, label, kw, msg):
    a = reg(c, vm, P.alice, fee=10 * MILLI)
    quantity = kw.get("quantity", 1)
    value = kw.get("value", 10 * MILLI * quantity)
    refuse(c, vm, msg, c.license, a, quantity, who=P.buyer, value=value)


def test_a_licence_of_an_unknown_work_is_refused(c, vm):
    refuse(c, vm, "No such work", c.license, 1, 1, who=P.buyer, value=10 * MILLI)


def test_up_to_a_hundred_licences_can_be_bought_in_one_call(c, vm):
    a = reg(c, vm, P.alice, fee=MILLI)
    buy(c, vm, P.buyer, a, 100)
    assert wrow(c, a)["licenses"] == 100 and wrow(c, a)["accrued"] == str(100 * MILLI)


# ---- the cascade ----------------------------------------------------------------------------------------------------


def test_a_derivative_passes_its_share_to_its_source(c, vm):
    a, b = chain(c, vm, [2500])
    buy(c, vm, P.buyer, b, 2)
    assert accrued(c, [a, b]) == [5 * MILLI, 15 * MILLI]
    rb, ra = wrow(c, b), wrow(c, a)
    assert (rb["passed"], rb["earned"], rb["gross"]) == (str(5 * MILLI), str(15 * MILLI), str(20 * MILLI))
    assert (ra["passed"], ra["earned"], ra["gross"]) == ("0", str(5 * MILLI), "0")  # income from below is not licence volume
    assert books(c)["balanced"]


def test_a_licence_of_the_source_does_not_flow_down(c, vm):
    a, b = chain(c, vm, [2500])
    buy(c, vm, P.buyer, a, 1)
    assert accrued(c, [a, b]) == [10 * MILLI, 0]


def test_the_royalty_travels_up_four_generations_and_each_generation_takes_its_share(c, vm):
    ids = chain(c, vm, [1000, 2000, 3000, 4000])  # five works
    buy(c, vm, P.buyer, ids[-1], 1)
    expected = split_of(10 * MILLI, [4000, 3000, 2000, 1000])  # lowest first
    assert accrued(c, ids) == list(reversed(expected))
    assert sum(accrued(c, ids)) == 10 * MILLI and books(c)["balanced"]


def test_a_sixth_work_stops_the_royalty_at_the_fourth_ancestor(c, vm):
    ids = chain(c, vm, [1000, 1000, 1000, 1000, 1000])  # six works; the lowest is ids[5]
    buy(c, vm, P.buyer, ids[5], 1)
    got = accrued(c, ids)
    assert got[0] == 0  # the fifth ancestor gets nothing
    assert got[1] > 0 and sum(got) == 10 * MILLI
    # hop 0 is ids[5]; hops 1..4 are ids[4], ids[3], ids[2], ids[1]; ids[1] keeps what reaches it
    left = 10 * MILLI
    for hop, wid in enumerate([ids[5], ids[4], ids[3], ids[2]]):
        cut = left * 1000 // 10_000
        assert got[wid - 1] == left - cut, hop
        left = cut
    assert got[ids[1] - 1] == left


def test_rounding_dust_stays_with_the_lower_work_and_nothing_is_lost(c, vm):
    fee = 10**15 + 7
    ids = chain(c, vm, [3333, 3333, 3333], fee=fee)
    buy(c, vm, P.buyer, ids[-1], 1)
    assert accrued(c, ids) == list(reversed(split_of(fee, [3333, 3333, 3333])))
    assert sum(accrued(c, ids)) == fee and books(c)["balanced"]


def test_a_tiny_amount_that_rounds_to_nothing_stays_with_the_work(c, vm):
    a, b = chain(c, vm, [1])  # one basis point of one wei is less than one wei
    split = json.loads(c.preview_split(b, 1))
    assert len(split) == 1 and (split[0]["work"], split[0]["credit"], split[0]["passed_up"]) == (b, "1", "0")


def test_a_licence_is_split_on_the_total_not_per_unit(c, vm):
    fee = 10**15 + 1
    a, b = chain(c, vm, [3333], fee=fee)
    buy(c, vm, P.buyer, b, 7)
    total = fee * 7
    cut = total * 3333 // 10_000
    assert accrued(c, [a, b]) == [cut, total - cut]


def test_a_zero_share_passes_nothing(c, vm):
    a, b = chain(c, vm, [0])
    buy(c, vm, P.buyer, b, 1)
    assert accrued(c, [a, b]) == [0, 10 * MILLI]


def test_the_maximum_share_passes_half(c, vm):
    a, b = chain(c, vm, [5000])
    buy(c, vm, P.buyer, b, 1)
    assert accrued(c, [a, b]) == [5 * MILLI, 5 * MILLI]


def test_two_derivatives_pay_the_same_source(c, vm):
    a = reg(c, vm, P.alice, ask=1000, fee=10 * MILLI)
    b = reg(c, vm, P.bob, text=HARBOUR, source=a, pass_bps=1000, fee=10 * MILLI)
    d = reg(c, vm, P.carol, text=SHIP_FEES, source=a, pass_bps=4000, fee=20 * MILLI)
    buy(c, vm, P.buyer, b, 1)
    buy(c, vm, P.buyer, d, 1)
    assert accrued(c, [a, b, d]) == [1 * MILLI + 8 * MILLI, 9 * MILLI, 12 * MILLI]
    assert wrow(c, a)["children"] == 2 and books(c)["balanced"]


def test_a_creator_who_owns_two_levels_is_paid_for_both_in_their_own_works(c, vm):
    a = reg(c, vm, P.alice, ask=2000)
    b = reg(c, vm, P.alice, text=HARBOUR, source=a, pass_bps=2000)
    buy(c, vm, P.buyer, b, 1)
    assert accrued(c, [a, b]) == [2 * MILLI, 8 * MILLI]


def test_a_declared_link_made_later_changes_where_future_fees_go(c, vm):
    a = reg(c, vm, P.alice, ask=2000)
    b = reg(c, vm, P.bob, text=HARBOUR)
    buy(c, vm, P.buyer, b, 1)
    act(vm, P.bob)
    c.declare_source(b, a, 2000)
    buy(c, vm, P.buyer, b, 1)
    assert accrued(c, [a, b]) == [2 * MILLI, 10 * MILLI + 8 * MILLI]


def test_a_retired_middle_work_still_passes_royalties_along(c, vm):
    ids = chain(c, vm, [2000, 2000])
    act(vm, P.extra[1])
    c.retire(ids[1])
    buy(c, vm, P.buyer, ids[2], 1)
    assert accrued(c, ids) == list(reversed(split_of(10 * MILLI, [2000, 2000])))


# ---- preview --------------------------------------------------------------------------------------------------------


def test_the_preview_matches_what_a_licence_really_does(c, vm):
    ids = chain(c, vm, [1500, 2500, 3500])
    fee = 10 * MILLI
    preview = json.loads(c.preview_split(ids[-1], fee))
    assert [p["work"] for p in preview] == list(reversed(ids))
    assert sum(int(p["credit"]) for p in preview) == fee
    buy(c, vm, P.buyer, ids[-1], 1)
    assert [int(p["credit"]) for p in preview] == list(reversed(accrued(c, ids)))
    assert [p["creator"].lower() for p in preview] == [hx(P.extra[i]) for i in (3, 2, 1, 0)]


def test_the_preview_of_an_amount_of_zero_and_of_the_maximum(c, vm):
    a, b = chain(c, vm, [2000])
    assert json.loads(c.preview_split(b, 0))[0]["credit"] == "0"
    big = json.loads(c.preview_split(b, 10**27))
    assert sum(int(p["credit"]) for p in big) == 10**27
    for bad in (-1, 10**27 + 1):
        with vm.expect_revert("out of range"):
            c.preview_split(b, bad)


def test_the_preview_changes_nothing(c, vm):
    ids = chain(c, vm, [2000, 2000])
    before = fingerprint(c)
    c.preview_split(ids[-1], 123456789)
    assert fingerprint(c) == before


# ---- withdrawing ----------------------------------------------------------------------------------------------------


def test_the_creator_withdraws_royalties_in_parts(c, vm, ledger):
    a, b = chain(c, vm, [2000])
    buy(c, vm, P.buyer, b, 5)  # a earns 10 MILLI
    withdraw(c, vm, P.extra[0], a, 4 * MILLI)
    withdraw(c, vm, P.extra[0], a, 6 * MILLI)
    row = wrow(c, a)
    assert (row["accrued"], row["withdrawn"]) == ("0", str(10 * MILLI)) and row["earned"] == str(10 * MILLI)
    assert ledger.to(P.extra[0]) == 10 * MILLI and ledger.count() == 2
    assert stats(c)["paid"] == str(10 * MILLI) and books(c)["balanced"]


WITHDRAW_BAD = [
    ("not the creator", dict(who=P.stranger, amount=MILLI), "Only the creator"),
    ("zero", dict(who=P.alice, amount=0), "positive"),
    ("negative", dict(who=P.alice, amount=-1), "positive"),
    ("more than earned", dict(who=P.alice, amount=10 * MILLI + 1), "positive and not more"),
]


@pytest.mark.parametrize("label,kw,msg", WITHDRAW_BAD, ids=[x[0] for x in WITHDRAW_BAD])
def test_bad_withdrawals_are_refused_and_change_nothing(c, vm, ledger, label, kw, msg):
    a = reg(c, vm, P.alice)
    buy(c, vm, P.buyer, a, 1)
    refuse(c, vm, msg, c.withdraw, a, kw["amount"], who=kw["who"])
    assert ledger.count() == 0


def test_withdrawing_from_an_unknown_work_is_refused(c, vm):
    refuse(c, vm, "No such work", c.withdraw, 4, 1, who=P.alice)


def test_the_holdback_cannot_be_withdrawn_as_royalties(c, vm):
    a = reg(c, vm, P.alice)
    refuse(c, vm, "positive and not more", c.withdraw, a, 1, who=P.alice)


def test_a_withdrawal_goes_to_the_creator_of_that_work_only(c, vm, ledger):
    a, b = chain(c, vm, [2000])
    buy(c, vm, P.buyer, b, 1)
    withdraw(c, vm, P.extra[1], b, 8 * MILLI)
    assert ledger.to(P.extra[1]) == 8 * MILLI and ledger.to(P.extra[0]) == 0
    assert accrued(c, [a, b]) == [2 * MILLI, 0]


def test_everything_ever_credited_is_accounted_for(c, vm):
    ids = chain(c, vm, [1000, 2000, 3000])
    for wid in ids:
        buy(c, vm, P.buyer, wid, 2)
    withdraw(c, vm, P.extra[1], ids[1], 5 * MILLI)
    for wid in ids:
        row = wrow(c, wid)
        assert int(row["earned"]) == int(row["accrued"]) + int(row["withdrawn"])
    total_earned = sum(int(wrow(c, w)["earned"]) for w in ids)
    assert total_earned == int(stats(c)["volume"])  # every fee paid was credited to somebody, nothing more
