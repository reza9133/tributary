"""The validator side: when does the network accept a leader's reading, and do the closures travel?"""

import json
import sys

import pytest

from conftest import *
from test_disputes import RATE, duel


@pytest.fixture
def c(direct_vm, direct_deploy):
    return deploy(direct_deploy, direct_vm)


@pytest.fixture
def vm(direct_vm):
    return direct_vm


@pytest.fixture
def mod(c):
    return sys.modules[MODULE]


def settle(lean, overlap, copy):
    """The rule written out independently of the contract."""
    if lean == "DERIVATIVE" and overlap >= 60:
        final = "DERIVATIVE"
    elif lean == "INDEPENDENT" and overlap <= 25:
        final = "INDEPENDENT"
    else:
        final = "UNSURE"
    if final == "INDEPENDENT" and copy >= 20:
        final = "UNSURE"
    return final


def res(lean="UNSURE", overlap=50, copy=0, relation=None, reason="They share some details.", coded=False, kind="OK"):
    if kind != "OK":
        return {"kind": kind}
    return {
        "kind": "OK", "relation": relation if relation is not None else settle(lean, overlap, copy), "lean": lean,
        "overlap": overlap, "copy": copy, "coded": coded, "reason": reason,
    }


# ---- _accepts, case by case -----------------------------------------------------------------------------------------

ACCEPT = [
    ("same reading", res("UNSURE", 50), res("UNSURE", 50), True),
    ("same derivative", res("DERIVATIVE", 70), res("DERIVATIVE", 75), True),
    ("same independent", res("INDEPENDENT", 10), res("INDEPENDENT", 20), True),
    ("leader unsure, validator derivative", res("UNSURE", 50), res("DERIVATIVE", 70), True),
    ("leader unsure, validator independent", res("UNSURE", 30), res("INDEPENDENT", 20), True),
    ("leader is unsure even though its numbers lean derivative", res("DERIVATIVE", 40), res("DERIVATIVE", 80), False),  # 40 apart
    ("leader decides derivative, validator unsure but leaning that way", res("DERIVATIVE", 65), res("DERIVATIVE", 50), True),
    ("leader decides derivative, validator unsure at the border", res("DERIVATIVE", 60), res("DERIVATIVE", 45), True),
    ("leader decides derivative, validator unsure below the border", res("DERIVATIVE", 65), res("DERIVATIVE", 44), False),
    ("leader decides derivative, validator unsure and leaning unsure", res("DERIVATIVE", 65), res("UNSURE", 55), False),
    ("leader decides derivative, validator unsure leaning independent", res("DERIVATIVE", 65), res("INDEPENDENT", 40), False),
    ("leader decides independent, validator unsure but leaning that way", res("INDEPENDENT", 10), res("INDEPENDENT", 35), True),
    ("leader decides independent, validator unsure at the border", res("INDEPENDENT", 15), res("INDEPENDENT", 40), True),
    ("leader decides independent, validator unsure above the border", res("INDEPENDENT", 20), res("INDEPENDENT", 41), False),
    ("leader decides independent, validator unsure and leaning unsure", res("INDEPENDENT", 10), res("UNSURE", 30), False),
    ("opposite decisions", res("DERIVATIVE", 80), res("INDEPENDENT", 10), False),
    ("opposite decisions, close numbers", res("DERIVATIVE", 60), res("INDEPENDENT", 25), False),
    ("opposite the other way", res("INDEPENDENT", 5), res("DERIVATIVE", 90), False),
    ("overlap 25 apart", res("DERIVATIVE", 100), res("DERIVATIVE", 75), True),
    ("overlap 26 apart", res("DERIVATIVE", 100), res("DERIVATIVE", 74), False),
    ("overlap 25 apart the other way", res("UNSURE", 25), res("UNSURE", 50), True),
    ("overlap 26 apart the other way", res("UNSURE", 24), res("UNSURE", 50), False),
    ("different copy share", res("UNSURE", 50, copy=10), res("UNSURE", 50, copy=11), False),
    ("same copy share", res("UNSURE", 50, copy=30), res("UNSURE", 50, copy=30), True),
    ("leader claims the code decided", res("DERIVATIVE", 90, coded=True), res("DERIVATIVE", 90), False),
    ("coded flag missing", {k: v for k, v in res().items() if k != "coded"}, res(), False),
    ("coded flag is a string", dict(res(), coded="no"), res(), False),
    ("relation does not follow from the numbers", res("DERIVATIVE", 40, relation="DERIVATIVE"), res("DERIVATIVE", 50), False),
    ("independent although the copy detector found a fifth repeated", res("INDEPENDENT", 5, copy=25, relation="INDEPENDENT"), res("UNSURE", 30, copy=25), False),
    ("independent label capped to unsure by the copy share", res("INDEPENDENT", 5, copy=25), res("UNSURE", 30, copy=25), True),
    ("relation not in the vocabulary", res("UNSURE", 50, relation="MAYBE"), res(), False),
    ("relation in lower case", res("UNSURE", 50, relation="unsure"), res(), False),
    ("relation is a list", res("UNSURE", 50, relation=["UNSURE"]), res(), False),
    ("lean not in the vocabulary", res("PROBABLY", 50, relation="UNSURE"), res(), False),
    ("lean is a number", res(7, 50, relation="UNSURE"), res(), False),
    ("overlap above 100", res("UNSURE", 101), res("UNSURE", 100), False),
    ("overlap below 0", res("UNSURE", -1), res("UNSURE", 0), False),
    ("overlap is a float", res("UNSURE", 50.0), res("UNSURE", 50), False),
    ("overlap is a bool", res("UNSURE", True), res("UNSURE", 1), False),
    ("overlap is a string", res("UNSURE", "50"), res("UNSURE", 50), False),
    ("overlap missing", {k: v for k, v in res().items() if k != "overlap"}, res(), False),
    ("copy is a bool", dict(res(), copy=False), res(copy=0), False),
    ("copy is a float", dict(res(), copy=0.0), res(copy=0), False),
    ("reason with angle brackets", res(reason="<b>hi</b>"), res(), False),
    ("reason too long", res(reason="r" * 161), res(), False),
    ("reason at the limit", res(reason="r" * 160), res(), True),
    ("reason empty", res(reason=""), res(), True),
    ("reason is not text", res(reason=7), res(), False),
    ("reason missing", {k: v for k, v in res().items() if k != "reason"}, res(), False),
    ("kind is not OK", res(kind="ERROR"), res(), False),
    ("kind missing", {k: v for k, v in res().items() if k != "kind"}, res(), False),
    ("not a dict", "UNSURE", res(), False),
    ("none", None, res(), False),
    ("a list holding a result", [res()], res(), False),
    ("an empty dict", {}, res(), False),
]


@pytest.mark.parametrize("label,theirs,mine,expected", ACCEPT, ids=[x[0] for x in ACCEPT])
def test_accepts(mod, label, theirs, mine, expected):
    assert mod._accepts(theirs, mine) is expected


def test_accepts_never_raises_on_hostile_shapes(mod):
    junk = [None, 0, 1.5, "x", b"x", [], {}, {"kind": "OK"}, {"kind": "OK", "relation": "UNSURE"}, {"kind": ["OK"]}, {"kind": "OK", "relation": {}, "lean": [], "overlap": {}}, {"kind": "OK", "relation": "UNSURE", "lean": "UNSURE", "overlap": 5, "copy": 0}]
    for theirs in junk:
        assert mod._accepts(theirs, res()) is False


def test_the_accept_rule_agrees_with_the_written_out_rule_over_a_grid(mod):
    """For every pair of readings: the leader may only decide what the validator's own reading supports."""
    labels = ["DERIVATIVE", "INDEPENDENT", "UNSURE"]
    for copy in (0, 25):
        for ll in labels:
            for lo in range(0, 101, 5):
                for vl in labels:
                    for vo in range(0, 101, 5):
                        theirs, mine = res(ll, lo, copy), res(vl, vo, copy)
                        expected = (
                            abs(lo - vo) <= 25
                            and (
                                theirs["relation"] == mine["relation"]
                                or theirs["relation"] == "UNSURE"
                                or (theirs["relation"] == "DERIVATIVE" and mine["relation"] == "UNSURE" and vl == "DERIVATIVE" and vo >= 45)
                                or (theirs["relation"] == "INDEPENDENT" and mine["relation"] == "UNSURE" and vl == "INDEPENDENT" and vo <= 40 and copy < 20)
                            )
                        )
                        assert mod._accepts(theirs, mine) is expected, (theirs, mine)


def test_a_leader_is_never_accepted_when_it_decides_the_opposite_of_the_validator(mod):
    for lo in range(0, 101):
        for vo in range(0, 101):
            for a, b in (("DERIVATIVE", "INDEPENDENT"), ("INDEPENDENT", "DERIVATIVE")):
                theirs, mine = res(a, lo), res(b, vo)
                if theirs["relation"] == a and mine["relation"] == b:  # both actually decided, in opposite ways
                    assert mod._accepts(theirs, mine) is False, (theirs, mine)


# ---- _assess: one reading --------------------------------------------------------------------------------------------


def test_assess_reads_the_model_and_applies_settle(c, vm, mod):
    mock_judge(vm, "DERIVATIVE", 77, reason="Same sentences in other words.")
    out = mod._assess("Src", TIDE, "Work", TIDE_PARAPHRASE, 0)
    assert out == {"kind": "OK", "relation": "DERIVATIVE", "lean": "DERIVATIVE", "overlap": 77, "copy": 0, "coded": False, "reason": "Same sentences in other words."}
    mock_judge(vm, "INDEPENDENT", 3)
    assert mod._assess("Src", TIDE, "Work", HARBOUR, 25)["relation"] == "UNSURE"  # a repeated fifth caps the model


def test_the_model_is_asked_with_both_texts_and_never_sees_the_challengers_words(c, vm):
    a, b = duel(c, vm, licences=0)
    d = dispute(c, vm, P.watcher, b, a, reason="They tell the same story twice.")
    vm.clear_mocks()
    # this mock only answers a prompt that holds the source and then the accused work, and not the reason
    vm.mock_llm(
        r"(?s)\A(?!.*They tell the same story).*<work_a>Tide pools: At low tide.*</work_a>\s*<work_b>Shore notes: When the water drops.*</work_b>",
        json.dumps(reply("UNSURE", 50)),
    )
    act(vm, P.stranger)
    c.judge(d)
    assert drow(c, d)["state"] == INCONCLUSIVE and drow(c, d)["reason"] == "They tell the same story twice."


def test_the_prompt_ends_with_the_texts_and_asks_for_json_only(c, vm, mod):
    vm.clear_mocks()
    vm.mock_llm(r"(?s)</work_b>\s*A word-for-word comparison", json.dumps(reply()))
    assert mod._assess("A", TIDE, "B", TIDE_PARAPHRASE, 0)["relation"] == "UNSURE"


# ---- the real flow, with a second validator -------------------------------------------------------------------------


def judged(c, vm, relation="UNSURE", overlap=50, **kw):
    a, b = duel(c, vm, licences=2)
    d = dispute(c, vm, P.watcher, b, a)
    judge(c, vm, P.stranger, d, relation, overlap, **kw)
    return a, b, d


def test_a_validator_who_reads_the_same_thing_agrees(c, vm):
    judged(c, vm, "DERIVATIVE", 80)
    assert vm.run_validator() is True


def test_a_validator_accepts_a_more_careful_leader(c, vm):
    judged(c, vm, "UNSURE", 50)
    mock_judge(vm, "DERIVATIVE", 70)  # the validator would have decided
    assert vm.run_validator() is True
    mock_judge(vm, "DERIVATIVE", 80)  # ... but a reading 30 points away is not the same case
    assert vm.run_validator() is False


def test_a_validator_accepts_a_leader_at_the_border_of_its_own_reading(c, vm):
    judged(c, vm, "DERIVATIVE", 65)
    mock_judge(vm, "DERIVATIVE", 50)  # unsure, but leaning the same way
    assert vm.run_validator() is True
    mock_judge(vm, "DERIVATIVE", 44)
    assert vm.run_validator() is False
    mock_judge(vm, "UNSURE", 55)
    assert vm.run_validator() is False


def test_a_validator_refuses_a_leader_who_decided_the_opposite(c, vm):
    judged(c, vm, "DERIVATIVE", 80)
    mock_judge(vm, "INDEPENDENT", 10)
    assert vm.run_validator() is False


def test_a_validator_refuses_a_made_up_clearance(c, vm):
    judged(c, vm, "INDEPENDENT", 5)
    mock_judge(vm, "DERIVATIVE", 90)
    assert vm.run_validator() is False
    mock_judge(vm, "UNSURE", 60)
    assert vm.run_validator() is False  # the validator was unsure, leaning unsure


def test_a_validator_refuses_a_leader_whose_overlap_is_far_from_its_own(c, vm):
    judged(c, vm, "DERIVATIVE", 100)
    mock_judge(vm, "DERIVATIVE", 74)
    assert vm.run_validator() is False
    mock_judge(vm, "DERIVATIVE", 75)
    assert vm.run_validator() is True


def test_a_validator_refuses_when_the_leader_error_is_not_a_result(c, vm):
    judged(c, vm)
    assert vm.run_validator(leader_error=Exception("boom")) is False


@pytest.mark.parametrize("forged", ["DERIVATIVE", None, 5, [], {}, {"kind": "OK"}, {"relation": "DERIVATIVE", "overlap": 100}, res("DERIVATIVE", 100, coded=True), res("DERIVATIVE", 100, copy=99)])
def test_a_validator_refuses_a_forged_result(c, vm, forged):
    judged(c, vm, "DERIVATIVE", 100)
    assert vm.run_validator(leader_result=forged) is False
    assert vm.run_validator() is True


def test_a_forged_result_with_numbers_that_do_not_support_its_label_is_refused(c, vm):
    judged(c, vm, "DERIVATIVE", 100)
    assert vm.run_validator(leader_result=res("DERIVATIVE", 59, relation="DERIVATIVE")) is False


def test_a_validator_whose_own_model_call_fails_does_not_accept(c, vm):
    judged(c, vm)
    mock_judge(vm, raw="this is not json")
    with pytest.raises(Exception, match="LLM_ERROR"):
        vm.run_validator()


def test_a_copy_needs_no_validator_round_at_all(c, vm):
    a, b = duel(c, vm, copy=True)
    d = dispute(c, vm, P.watcher, b, a)
    n = len(vm._captured_validators)
    vm.clear_mocks()
    judge(c, vm, P.stranger, d)
    assert len(vm._captured_validators) == n  # the code decided; nothing was sent to the network


# ---- what travels to the validators ---------------------------------------------------------------------------------


def test_both_closures_can_be_pickled_with_only_plain_values(c, vm):
    import cloudpickle

    judged(c, vm)
    _, leader_fn, validator_fn = vm._captured_validators[-1]
    for fn in (leader_fn, validator_fn):
        blob = cloudpickle.dumps(fn)
        assert isinstance(blob, bytes) and len(blob) > 100
        cells = [cell.cell_contents for cell in (fn.__closure__ or ())]
        assert all(isinstance(v, (str, int, bool, list, dict, type(None))) or callable(v) for v in cells)


def test_the_closure_survives_a_round_trip(c, vm):
    import cloudpickle
    import genlayer.gl.vm as gl_vm

    judged(c, vm, "DERIVATIVE", 90)
    stored, leader_fn, validator_fn = vm._captured_validators[-1]
    again = cloudpickle.loads(cloudpickle.dumps(leader_fn))
    assert again() == stored and stored["relation"] == "DERIVATIVE" and stored["overlap"] == 90
    clone = cloudpickle.loads(cloudpickle.dumps(validator_fn))
    assert clone(gl_vm.Return(calldata=stored)) is True
