import json

from conftest import *


def test_deploys_and_runs_the_happy_path(direct_vm, direct_deploy, ledger):
    c = deploy(direct_deploy, direct_vm)
    a = reg(c, direct_vm, P.alice)
    b = reg(c, direct_vm, P.bob, text=HARBOUR, title="Harbour ledger", source=a, pass_bps=2000)
    assert (a, b) == (1, 2)
    buy(c, direct_vm, P.buyer, b, 3)
    row_a, row_b = wrow(c, a), wrow(c, b)
    assert int(row_b["accrued"]) == 24 * MILLI and int(row_a["accrued"]) == 6 * MILLI
    withdraw(c, direct_vm, P.alice, a, 6 * MILLI)
    assert ledger.to(P.alice) == 6 * MILLI
    assert books(c)["balanced"]
