"""Backend of the offline rehearsal: runs the real contract in the direct runner and answers line-JSON requests.

It is started by the stub of genlayer-js (through pytest, because the direct runner lives in pytest fixtures) and
talks to it over stdin and stdout. Nothing here touches a network."""

import json
import os
import sys
from datetime import datetime, timezone

from conftest import *  # noqa: F401,F403  (the same helpers as the unit tests)
from conftest import Wire, act, deploy

# the direct runner swaps file descriptor 0 for its own message, so keep a private copy of the real stdin first
_STDIN = os.fdopen(os.dup(0), "r")
MARK = "@@RPC "
JUDGE_MODE = os.environ.get("JUDGE_MODE", "derivative")  # derivative | independent | unsure | flaky (unsure the first time, derivative after)
DEFAULT_BALANCE = 10 * 10**18


def out(obj):
    sys.stdout.write(MARK + json.dumps(obj) + "\n")
    sys.stdout.flush()


def unbig(value):
    if isinstance(value, dict) and "$big" in value:
        return int(value["$big"])
    if isinstance(value, list):
        return [unbig(v) for v in value]
    return value


def verdict(relation, overlap, reason):
    return json.dumps({"relation": relation, "overlap": overlap, "reason": reason})


def set_mocks(vm, paraphrase_tries=1):
    vm.clear_mocks()
    # The unrelated text (the harbour ledger) is judged independent, whatever the mode says about the paraphrase.
    unrelated = verdict("UNSURE", 50, "I cannot tell.") if JUDGE_MODE == "unsure" else verdict("INDEPENDENT", 4, "The two texts share only the sea.")
    vm.mock_llm(r"(?s)<work_b>[^<]*the harbour master", unrelated)
    mode = {
        "derivative": verdict("DERIVATIVE", 85, "The second text retells the first one sentence by sentence."),
        "independent": verdict("INDEPENDENT", 6, "They only share the topic of tide pools."),
        "unsure": verdict("UNSURE", 50, "I cannot tell."),
        "flaky": verdict("UNSURE", 50, "I cannot tell.") if paraphrase_tries <= 1 else verdict("DERIVATIVE", 85, "The second text retells the first one sentence by sentence."),
    }[JUDGE_MODE]
    vm.mock_llm(r"judge of a royalty registry", mode)


def test_serve(direct_vm, direct_deploy):
    vm = direct_vm
    c = deploy(direct_deploy, vm)
    funded = {}
    tries = {"paraphrase": 0}
    out({"ready": True})
    for line in _STDIN:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        rid = req.get("id")
        try:
            now = int(req.get("now", 0))
            if now:
                vm.warp(datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            op = req["op"]
            if op == "fund":
                funded[req["address"].lower()] = funded.get(req["address"].lower(), 0) + int(req["amount"])
                out({"id": rid, "ok": True})
            elif op == "balance":
                addr = req["address"].lower()
                got = sum(v for a, v in Wire.sent if a == addr)
                out({"id": rid, "ok": True, "ret": str(funded.get(addr, DEFAULT_BALANCE) + got)})
            elif op == "view":
                set_mocks(vm)
                args = unbig(req["args"])
                out({"id": rid, "ok": True, "ret": getattr(c, req["fn"])(*args)})
            elif op == "call":
                args = unbig(req["args"])
                if req["fn"] == "judge":  # count how often the paraphrase pair has been judged (for the flaky mode)
                    row = json.loads(c.get_dispute(args[0])) if 1 <= args[0] <= stats(c)["disputes"] else None
                    if row and "Shore log" in json.loads(c.get_work(row["work"]))["title"]:
                        tries["paraphrase"] += 1
                set_mocks(vm, tries["paraphrase"])
                sender = bytes.fromhex(req["sender"][2:])
                act(vm, sender, int(req.get("value", 0)))
                try:
                    getattr(c, req["fn"])(*args)
                finally:
                    vm.value = 0
                out({"id": rid, "ok": True})
            else:
                out({"id": rid, "ok": False, "error": f"unknown op {op}"})
        except Exception as e:  # a refusal by the contract
            vm.value = 0
            out({"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"[:400]})
