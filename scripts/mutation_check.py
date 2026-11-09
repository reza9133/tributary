#!/usr/bin/env python3
"""Mutation check: damage the contract on purpose, one small change at a time, and see that the test suite notices.

Every mutant below is a deliberate bug. The suite (without the slow random stories) has to fail for each of them; a
mutant that survives means a rule that no test protects.

    python3 scripts/mutation_check.py                 all mutants
    python3 scripts/mutation_check.py fine_rate       only the mutants whose name contains the word
    python3 scripts/mutation_check.py --from=52       start at the 52nd mutant (to resume an interrupted run)
"""

import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SOURCE = os.path.join(ROOT, "contracts", "tributary.py")

MUTANTS = [
    ("fine_rate", "FINE_BPS = 2_500", "FINE_BPS = 2_000"),
    ("bond_size", "DISPUTE_BOND = 5 * 10**15", "DISPUTE_BOND = 6 * 10**15"),
    ("holdback_minimum", "MIN_HOLDBACK = 2 * 10**16", "MIN_HOLDBACK = 10**16"),
    ("hop_limit_loose", "            if hops < MAX_HOPS:\n                if int(w.source) != 0:", "            if hops <= MAX_HOPS:\n                if int(w.source) != 0:"),
    ("hop_limit_tight", "            if hops < MAX_HOPS:\n                if int(w.source) != 0:", "            if hops < MAX_HOPS - 1:\n                if int(w.source) != 0:"),
    ("round_up", "cut_declared = amt * int(w.pass_bps) // BPS", "cut_declared = (amt * int(w.pass_bps) + BPS - 1) // BPS"),
    ("forced_cut_ignored", "cut_forced = amt * int(w.forced_bps) // BPS", "cut_forced = 0"),
    ("merge_paths_lost", "row[0] += amt - cut_declared - cut_forced", "row[0] = amt - cut_declared - cut_forced"),
    ("in_line_depth", "        if hops >= MAX_HOPS:\n            return False\n        w = self._work(work_id)\n        for nxt", "        if hops > MAX_HOPS:\n            return False\n        w = self._work(work_id)\n        for nxt"),
    ("in_line_forced_skipped", "for nxt in (int(w.source), int(w.forced_source)):", "for nxt in (int(w.source),):"),
    ("withdraw_ignores_freeze", '        if int(w.dispute) != 0:\n            raise gl.vm.UserError("The work is under dispute; its royalties are frozen.")\n', ""),
    ("withdraw_any_amount", "if amount <= 0 or amount > int(w.accrued):", "if amount <= 0:"),
    ("retire_ignores_dispute", '        if int(w.dispute) != 0:\n            raise gl.vm.UserError("The work is under dispute.")\n        w.status = u8(RETIRED)', "        w.status = u8(RETIRED)"),
    ("reclaim_ignores_dispute", '        if int(w.dispute) != 0:\n            raise gl.vm.UserError("The work is under dispute.")\n        if _now() < int(w.retired_at) + COOLDOWN:', "        if _now() < int(w.retired_at) + COOLDOWN:"),
    ("reclaim_no_cooldown", "        if _now() < int(w.retired_at) + COOLDOWN:\n            raise gl.vm.UserError(\"The holdback stays for five minutes after retiring.\")\n", ""),
    ("reclaim_cooldown_off_by_one", "if _now() < int(w.retired_at) + COOLDOWN:", "if _now() <= int(w.retired_at) + COOLDOWN:"),
    ("retry_after_final_outcome", "tries > 0 and (int(self._dispute(int(self.pairs.get(pair, 0))).state) not in (INCONCLUSIVE, LAPSED) or tries >= MAX_PAIR_TRIES)", "tries > 0 and tries >= MAX_PAIR_TRIES"),
    ("retry_unbounded", "tries > 0 and (int(self._dispute(int(self.pairs.get(pair, 0))).state) not in (INCONCLUSIVE, LAPSED) or tries >= MAX_PAIR_TRIES)", "tries > 0 and int(self._dispute(int(self.pairs.get(pair, 0))).state) not in (INCONCLUSIVE, LAPSED)"),
    ("retry_never", "tries > 0 and (int(self._dispute(int(self.pairs.get(pair, 0))).state) not in (INCONCLUSIVE, LAPSED) or tries >= MAX_PAIR_TRIES)", "tries > 0"),
    ("pair_tries_not_counted", "        self.pair_tries[pair] = u32(tries + 1)\n", ""),
    ("pair_can_repeat", '        if tries > 0 and (int(self._dispute(int(self.pairs.get(pair, 0))).state) not in (INCONCLUSIVE, LAPSED) or tries >= MAX_PAIR_TRIES):\n            raise gl.vm.UserError("These two works have been disputed before.")\n', ""),
    ("reason_reaches_the_model", "res = _decide(str(s.title), str(s.text), str(w.title), str(w.text))", "res = _decide(str(s.title), str(s.text), str(d.reason), str(w.text))"),
    ("two_open_disputes", '        if int(w.dispute) != 0:\n            raise gl.vm.UserError("The work is already under dispute.")\n', ""),
    ("forced_twice", '        if int(w.forced_source) != 0:\n            raise gl.vm.UserError("The work was already forced onto a source.")\n', ""),
    ("source_may_be_in_line", '        if self._in_line(work_id, source):\n            raise gl.vm.UserError("The source is already in the line of this work.")\n        if w.creator == s.creator:', "        if w.creator == s.creator:"),
    ("same_creator_dispute", '        if w.creator == s.creator:\n            raise gl.vm.UserError("Both works have the same creator.")\n', ""),
    ("creator_disputes_self", '        if who == w.creator:\n            raise gl.vm.UserError("The creator of the work cannot dispute it.")\n', ""),
    ("zero_ask_disputable", '        if int(s.ask_bps) == 0:\n            raise gl.vm.UserError("That source asks for no royalty.")\n', ""),
    ("younger_source", '        if source >= work_id:\n            raise gl.vm.UserError("The source has to be older than the work.")\n', ""),
    ("bond_not_exact", "if int(gl.message.value) != DISPUTE_BOND:", "if int(gl.message.value) < DISPUTE_BOND:"),
    ("rate_not_snapshotted", "rate_bps=u32(int(s.ask_bps))", "rate_bps=u32(0)"),
    ("judge_after_expiry", '        if now >= int(d.expires):\n            raise gl.vm.UserError("The judging time is over. Call lapse.")\n', ""),
    ("lapse_too_early", '        if _now() < int(d.expires):\n            raise gl.vm.UserError("The judging time is not over yet.")\n', ""),
    ("waive_by_anyone", '        if gl.message.sender_address != s.creator:\n            raise gl.vm.UserError("Only the creator of the source can do that.")\n', ""),
    ("concede_by_anyone", "        self._creator_only(w)\n        if int(d.state) != OPEN:\n            raise gl.vm.UserError(\"The dispute is not open.\")\n        self._uphold(d, w, s, CONCEDED, 0,", "        if int(d.state) != OPEN:\n            raise gl.vm.UserError(\"The dispute is not open.\")\n        self._uphold(d, w, s, CONCEDED, 0,"),
    ("concede_with_fine", "self._uphold(d, w, s, CONCEDED, 0,", "self._uphold(d, w, s, CONCEDED, FINE_BPS,"),
    ("fine_after_back_royalties", "        fine = int(w.holdback) * fine_bps // BPS\n        w.holdback = u256(int(w.holdback) - fine)\n        owed = int(w.gross) * rate // BPS", "        owed = int(w.gross) * rate // BPS\n        fine = 0"),
    ("holdback_before_accrued", "        from_accrued = min(owed, int(w.accrued))", "        from_accrued = 0"),
    ("owed_on_earned", "owed = int(w.gross) * rate // BPS", "owed = int(w.earned) * rate // BPS"),
    ("forced_cap_lost", "w.forced_bps = u32(min(rate, MAX_TOTAL_PASS - int(w.pass_bps)))", "w.forced_bps = u32(rate)"),
    ("back_royalty_not_flowed", "        if moved > 0:\n            self._flow(int(d.source), moved)\n", ""),
    ("children_not_counted_on_force", "        w.forced_source = u32(int(d.source))\n        w.forced_bps = u32(min(rate, MAX_TOTAL_PASS - int(w.pass_bps)))\n        s.children = u32(int(s.children) + 1)", "        w.forced_source = u32(int(d.source))\n        w.forced_bps = u32(min(rate, MAX_TOTAL_PASS - int(w.pass_bps)))"),
    ("refund_keeps_bond_booked", "        bond = int(d.bond)\n        self.bonds = u256(int(self.bonds) - bond)\n        self.paid = u256(int(self.paid) + bond)\n        _Wire(d.challenger)", "        bond = int(d.bond)\n        self.paid = u256(int(self.paid) + bond)\n        _Wire(d.challenger)"),
    ("dismiss_loses_bond", "        w.accrued = u256(int(w.accrued) + bond)\n        w.earned = u256(int(w.earned) + bond)\n", ""),
    ("dismiss_pays_challenger", "        self._close(d, w, DISMISSED,", "        _Wire(d.challenger).emit_transfer(value=u256(bond))\n        self.paid = u256(int(self.paid) + bond)\n        self._close(d, w, DISMISSED,"),
    ("upheld_no_bond_back", "_Wire(d.challenger).emit_transfer(value=u256(bond + fine))", "_Wire(d.challenger).emit_transfer(value=u256(fine))"),
    ("close_keeps_freeze", "        d.note = _tidy(note, 220)\n        w.dispute = u32(0)", "        d.note = _tidy(note, 220)"),
    ("settle_uphold_exclusive", "if lean == DERIVATIVE and overlap >= UPHOLD_AT:", "if lean == DERIVATIVE and overlap > UPHOLD_AT:"),
    ("settle_clear_exclusive", "elif lean == INDEPENDENT and overlap <= CLEAR_AT:", "elif lean == INDEPENDENT and overlap < CLEAR_AT:"),
    ("settle_copy_cap_lost", "    if final == INDEPENDENT and copy >= SOME_COPY:\n        final = UNSURE\n", ""),
    ("settle_label_ignored", "if lean == DERIVATIVE and overlap >= UPHOLD_AT:", "if overlap >= UPHOLD_AT:"),
    ("copy_one_direction", "return min(100, max(common * 100 // len(a), common * 100 // len(b)))", "return min(100, common * 100 // len(b))"),
    ("hard_copy_threshold", "HARD_COPY = 50", "HARD_COPY = 51"),
    ("accepts_copy_unchecked", 'or copy != mine["copy"] or theirs.get("coded") is not False:', 'or theirs.get("coded") is not False:'),
    ("accepts_settle_unchecked", "    if relation != _settle(lean, overlap, copy):\n        return False\n", ""),
    ("accepts_slack_wide", "if abs(overlap - mine[\"overlap\"]) > OVERLAP_SLACK:", "if abs(overlap - mine[\"overlap\"]) > OVERLAP_SLACK + 10:"),
    ("accepts_lenient_leader", "        return mine[\"lean\"] == DERIVATIVE and mine[\"overlap\"] >= UPHOLD_AT - BORDER", "        return True"),
    ("accepts_coded_leader", 'or theirs.get("coded") is not False:', 'or False:'),
    ("accepts_html_reason", '    if not _plain(theirs.get("reason"), MAX_REASON):\n        return False\n', ""),
    ("ask_can_rise", '        if ask_bps > int(w.ask_bps):\n            raise gl.vm.UserError("The asking share can only be lowered.")\n', ""),
    ("duplicate_text_allowed", '        if int(self.used.get(key, 0)) != 0:\n            raise gl.vm.UserError("A work with the same text is already registered.")\n', ""),
    ("steering_title_allowed", "        if _steers(title) or _steers(text):", "        if _steers(text):"),
    ("steering_reason_allowed", '        if _steers(claim):\n            raise gl.vm.UserError("The reason tries to steer the judge.")\n', ""),
    ("brackets_kept", 'return " ".join(out.replace("<", "(").replace(">", ")").split())', 'return " ".join(out.split())'),
    ("joiners_dropped", 'ch if ch.isprintable() or ch in _JOINERS else " "', 'ch if ch.isprintable() else " "'),
    ("license_underpay", "if int(gl.message.value) != total:", "if int(gl.message.value) < total:"),
    ("license_quantity_cap", "if quantity < 1 or quantity > MAX_QTY:", "if quantity < 1:"),
    ("license_on_retired", '        if int(w.status) != ACTIVE:\n            raise gl.vm.UserError("The work is retired.")\n        if quantity < 1', "        if quantity < 1"),
    ("license_gross_missing", "        w.gross = u256(int(w.gross) + total)\n", ""),
    ("flow_earned_missing", "            w.earned = u256(int(w.earned) + keep)\n", ""),
    ("flow_passed_missing", "            w.passed = u256(int(w.passed) + cut)\n", ""),
    ("deposit_not_counted_topup", "        w.holdback = u256(int(w.holdback) + value)\n        self.deposited = u256(int(self.deposited) + value)", "        w.holdback = u256(int(w.holdback) + value)"),
    ("declare_without_cap", '        if pass_bps + int(w.forced_bps) > MAX_TOTAL_PASS:\n            raise gl.vm.UserError("Together the links would pass more than 75% of every fee.")\n', ""),
    ("declare_in_line_ok", '        if self._in_line(work_id, source):\n            raise gl.vm.UserError("The source is already in the line of this work.")\n        if pass_bps + int(w.forced_bps)', "        if pass_bps + int(w.forced_bps)"),
    ("declare_on_retired", '        if int(w.status) != ACTIVE:\n            raise gl.vm.UserError("The work is retired.")\n        if int(w.source) != 0:', "        if int(w.source) != 0:"),
    ("declare_during_dispute", '        if int(w.dispute) != 0:\n            raise gl.vm.UserError("The work is under dispute.")\n        if source == 0:', "        if source == 0:"),
    ("closed_terms_ignored", "if not bool(s.open_terms) and s.creator != creator:", "if False:"),
    ("retired_source_ok", '        if int(s.status) != ACTIVE:\n            raise gl.vm.UserError("The source is retired.")\n', ""),
    ("pass_below_ask_ok", "if pass_bps < int(s.ask_bps) or pass_bps > MAX_PASS_BPS:", "if pass_bps > MAX_PASS_BPS:"),
    ("work_cap_lost", "if mine is not None and len(mine) >= MAX_WORKS_PER_CREATOR:", "if False:"),
    ("holdback_too_small_ok", "if value < MIN_HOLDBACK or value > MAX_AMOUNT:", "if value > MAX_AMOUNT:"),
    ("fee_min_lost", "if fee < MIN_FEE or fee > MAX_FEE:\n            raise gl.vm.UserError(\"The fee is out of range (0.001 GEN or more).\")\n        if ask_bps", "if fee > MAX_FEE:\n            raise gl.vm.UserError(\"The fee is out of range (0.001 GEN or more).\")\n        if ask_bps"),
    ("lineage_unbounded", "            if hops >= MAX_HOPS:\n                return\n            w = self._work(wid)\n            for target", "            w = self._work(wid)\n            for target"),
    ("int_float_dropped", "        return int(round(value)) if value == value and abs(value) < 1e9 else default", "        return default"),
    ("int_percent_dropped", "            return int(round(float(found.group(1))))", "            return default"),
    ("missing_overlap_counts_as_certain", 'overlap = max(0, min(100, _int(res.get("overlap"), 50)))', 'overlap = max(0, min(100, _int(res.get("overlap"), 100)))'),
    ("paging_unbounded", "limit = max(0, min(limit, MAX_PAGE))\n        out = []\n        i = len(self.works) - max(0, offset)", "limit = max(0, limit)\n        out = []\n        i = len(self.works) - max(0, offset)"),
    ("solvency_always_true", '"balanced": deposited - paid == accrued + holdback + bonds and bonds == open_bonds,', '"balanced": True,'),
]


def run(name, old, new, only_fuzz=False):
    src = open(SOURCE).read()
    if src.count(old) != 1:
        return name, "BAD MUTANT", f"the original text occurs {src.count(old)} times"
    work = tempfile.mkdtemp(prefix=f"mut_{name}_")
    try:
        path = os.path.join(work, "tributary.py")
        open(path, "w").write(src.replace(old, new))
        env = dict(os.environ, TRIBUTARY_CONTRACT=path, TRIBUTARY_FUZZ_SEEDS="3")
        cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/direct"]
        if not only_fuzz:
            cmd += ["--ignore=tests/direct/test_fuzz.py"]
        res = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
        tail = [line for line in res.stdout.splitlines() if line.startswith(("FAILED", "ERROR"))][:1]
        return name, ("killed" if res.returncode != 0 else "SURVIVED"), (tail[0][:110] if tail else "")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    words = [a for a in sys.argv[1:] if not a.startswith("--")]
    only_fuzz = "--with-fuzz" in sys.argv
    first = next((int(a.split("=")[1]) for a in sys.argv[1:] if a.startswith("--from=")), 1)  # resume a long run
    chosen = [m for m in MUTANTS[first - 1:] if not words or any(w in m[0] for w in words)]
    survivors, bad = [], []
    for i, (name, old, new) in enumerate(chosen, 1):
        name, status, detail = run(name, old, new, only_fuzz)
        print(f"[{i:2}/{len(chosen)}] {status:10} {name:34} {detail}", flush=True)
        if status == "SURVIVED":
            survivors.append(name)
        if status == "BAD MUTANT":
            bad.append(name)
    print(f"\n{len(chosen) - len(survivors) - len(bad)} of {len(chosen)} mutants were caught by the tests.")
    if survivors:
        print("SURVIVED (no test protects these rules): " + ", ".join(survivors))
    if bad:
        print("Mutants that no longer apply to the contract: " + ", ".join(bad))
    sys.exit(1 if survivors or bad else 0)


if __name__ == "__main__":
    main()
