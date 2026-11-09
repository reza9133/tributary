# Tributary

**A royalty registry for derivative works, with an AI judge, on GenLayer.**

People register short texts (a recipe, a pattern, a field guide, a poem, a spec). A work can name an older work as its
*source*, and then passes a share of every licence fee up to it, and the source passes a share of that up again, four
generations at most. Money flows up the family tree the moment a licence is bought.

The hard part is the work that *does not* admit where it came from. Anyone can challenge it with a bond. A copy
detector built into the contract, a language model and the validators of the network decide whether it is derived. The
contract then applies fixed, bounded consequences: the missing link is forced onto the work, the royalties the source
missed are paid back out of the work's own money, and the challenger earns a fine. If the judge cannot tell, nothing
changes.

The one rule behind the design: **the model never moves money.** It reads two texts and answers with one of three
words. What each word costs is written in the contract, in numbers that cannot be argued with.

```
 a licence fee is paid for work F, which declared E as its source, which declared D:

   F keeps 60% ──passes 40%──▶ E keeps 70% of that ──passes 30%──▶ D keeps all that arrives
```

---

## Why this is a GenLayer contract

* Whether one text is a paraphrase, a translation or an adaptation of another cannot be computed. It takes a reader.
  GenLayer lets every validator run the same reading and lets the contract decide *what counts as agreement*.
* Agreement is the interesting part. Two honest readings of a borderline case differ by a few points of "overlap", so
  the contract does not ask for equal answers. It asks that the leader's answer follows from its own numbers, that it
  is not further from the validator's reading than a fixed slack, and that it never *decides* a case the validator
  reads the other way. A leader that is more careful than the validator ("unsure") is accepted (while its overlap is
  near the validator's), because "unsure" changes nothing.
* Everything that does not need a model does not use one. A work that repeats most of another work word for word is
  found by the contract itself (see *Judging*), with no model call, no cost and no way to talk it out of the answer.

## What it is not

Tributary settles lineage *between works registered in the contract*. It cannot know who wrote a text first in the
world, only who registered it first here. See *Limitations* before relying on it for anything real.

---

## Roles

| Role | What they do |
| --- | --- |
| **Creator** | Registers works with a holdback, sets the fee and terms, names a source, withdraws royalties, retires a work. |
| **Licensee** | Buys licences. Anyone, paying exactly fee × quantity. |
| **Challenger** | Anyone but the creator of the accused work. Posts a bond and says "this work is derived from that older one". Often the source's own creator; can be a stranger who watches the registry and earns the fine. |
| **Source creator** | Can end any dispute about their own work with `waive`. |
| **Accused creator** | Can end a dispute against their work with `concede` (cheaper than losing). |
| **Anyone** | Runs `judge` and `lapse`. The judgement needs no permission. |

There is no owner, no admin and no upgrade key.

## Works, links and the cascade

A **work** has a creator, a title, a text (80 to 1500 characters, at least 20 words), a licence fee, an **asking share**
(`ask_bps`: what works built on it must pass up, 0 to 50%), open or closed terms, a **holdback** (the deposit behind
it, at least 0.02 GEN) and the money it has earned. Ids start at 1; `0` always means "none".

A work has two kinds of **link** to older works, kept apart on purpose:

* **declared source**: chosen by the creator at registration (or later with `declare_source`). The work passes
  `pass_bps` of every fee up (at least what the source asks, at most 50%). A declared link is an admission, not a
  verdict; nothing is owed for the past.
* **forced source**: imposed by a dispute. At most one per work. Its share is the rate the source asked when the
  dispute was filed, cut back if needed so that both links together never pass more than 75% of a fee.

Because the two are separate, **a copy cannot hide behind a decoy**: declaring an unrelated work as your source does not
protect you from a dispute about the work you really copied.

When a licence is bought, the fee travels up the links. Each work keeps what is left after passing its shares up;
rounding always favours the lower work, so the credits add up to the fee to the wei. A work reached along two paths
is credited once for both. After four generations the royalty stops: the fourth ancestor keeps everything that
reaches it and the fifth gets nothing. `preview_split(work, amount)` shows the split before anyone pays.

Rules that keep the family tree honest:

* a source must be **older** (a smaller id) than the work, which makes cycles impossible;
* the asking share **can only be lowered** after registration, so whoever builds on a work can rely on the rate, and
  a dispute can never charge more than the work asked when it was registered;
* links made earlier keep the share they were made with;
* a retired work takes no licences or new links, but still passes royalties along and earns from below.

## Disputes

```
open_dispute(work, source, reason) + bond 0.005 GEN
        │   the work's royalties are frozen (no withdraw, retire, reclaim or declare_source)
        ▼
     judge ──────────────┬───────────────────┬──────────────────────┐
        │ DERIVATIVE     │ INDEPENDENT       │ UNSURE               │  or: concede / waive / lapse
        ▼                ▼                   ▼
     UPHELD           DISMISSED          INCONCLUSIVE
```

| Outcome | What happens |
| --- | --- |
| **UPHELD** (judge says derivative) | The forced link is made. **Back royalties** = the rate × every fee the work ever collected, taken from its frozen royalties first, then its holdback, and paid up the source's line like a late licence fee. The challenger gets the bond back plus a **fine**: 25% of the work's holdback (taken before the back royalties). |
| **DISMISSED** (judge says independent) | The challenger's bond goes to the accused work's creator. Nothing else changes. |
| **INCONCLUSIVE** (judge cannot tell) | Nothing changes. The bond goes back. |
| **CONCEDED** (accused creator gives in) | Like UPHELD without the fine. The bond goes back. |
| **WAIVED** (source creator withdraws the claim) | Nothing changes. The bond goes back. |
| **LAPSED** (nobody judged within an hour) | Nothing changes. The bond goes back. `lapse` is the way out if the network can never agree. |

Limits: one open dispute at a time per work; a pair of works is disputed once, or twice if the first judgement
could not tell (INCONCLUSIVE or LAPSED), so that one noisy "unsure" does not kill a good claim while a lucky model
answer still cannot be farmed by filing the same claim again and again; never by its own creator, never for a source that already receives the work's royalties (anywhere in its four-generation
line), never for a source that asks for no royalty.

### Judging

`judge(dispute)` is public and runs three layers, in this order:

1. **The code.** It compares the two texts as sets of four-word runs (case, punctuation and hidden characters ignored)
   and measures how much of the shorter one is found, word for word, in the other, in either direction.
   **At 50% or more the work is derived, the model is not asked, and no validator round is needed.**
2. **The model.** Otherwise one model call reads the two texts, and nothing the challenger wrote, and answers
   `{"relation", "overlap", "reason"}`. The relation is one of `DERIVATIVE`, `INDEPENDENT`, `UNSURE`; the
   overlap is "how much of what is distinctive in B comes from A", 0 to 100.
3. **Settle.** The contract does not trust the label alone:
   * `DERIVATIVE` counts only with an overlap of **60 or more**;
   * `INDEPENDENT` counts only with an overlap of **25 or less**;
   * a label that its own number does not support, an unknown label or garbage is read as `UNSURE`;
   * and the model alone can **never clear** a work for which the code found **20% or more** of the wording repeated.

Every doubt resolves to "nothing changes". The model cannot make a copy independent, cannot make an unrelated text
derivative with a low number, and cannot touch an amount.

### Consensus

The leader's reading is accepted by a validator (its own, independent reading) when all of these hold:

* the leader's result is well formed (`OK`, known vocabulary, whole-number overlap from 0 to 100, plain short reason
  without angle brackets), its copy share equals the validator's own (the code computes it, there is nothing to
  disagree about) and its final relation really follows from its own raw label and number;
* the two overlaps are at most 25 points apart;
* and then one of: the same relation; the leader says `UNSURE` (more careful than the validator, fine); the
  leader says `DERIVATIVE` where the validator's own reading was `UNSURE` but leaned `DERIVATIVE` with an overlap of 45
  or more; or the leader says `INDEPENDENT` where the validator was `UNSURE` but leaned `INDEPENDENT` with an overlap
  of 40 or less and no repeated wording of note.

A leader that decides the opposite of the validator is never accepted. If the network cannot agree, the transaction
fails, the dispute stays open and nothing is lost: anyone can call `judge` again, or `lapse` after an hour.

### Text that talks to the judge

Texts, titles and reasons are cleaned (angle brackets are replaced, hidden characters dropped, look-alike letters
folded) and checked by a tripwire for phrases such as "ignore all previous instructions" or `"relation":
"independent"`. A text that trips it is refused at registration, so a recipe that says "ignore the previous step" has
to be worded differently. A dispute reason is stored for people to read; the model never sees it.

The tripwire is a best-effort filter, **not the defence**. The defence is that the model can only say one of three
words, that the numbers must agree with the word, that the code's own copy detector cannot be argued with, and that
both parties have a human exit.

## Money

All amounts are wei of GEN. Nothing is ever pushed to anyone except the single transfer a call is about
(`withdraw`, `reclaim`, a bond or a fine).

| What | Rule |
| --- | --- |
| Registration | Attach at least **0.02 GEN**: the holdback, the pool a dispute can draw on. Anyone can `top_up` it; only the creator can take it out, after `retire` and a five minute cool-down, and not while a dispute is open. |
| Licence | Exactly `fee × quantity` (fee at least 0.001 GEN, quantity 1 to 100). Split on the total, immediately. |
| Royalties | Pulled by the creator of each work with `withdraw`. Frozen while the work is under dispute. |
| Dispute bond | Exactly **0.005 GEN**. Returned, forfeited to the accused creator, or paid back with the fine, depending on the outcome. |

`solvency()` reports the books of the whole contract: everything ever paid in is either paid out, held as royalties
or holdbacks, or held as a bond, and the bonds held equal the bonds of the open disputes. The local tests and the
live run check this after every step.

## Interface

Write calls (14)

| Call | Who | Notes |
| --- | --- | --- |
| `register(title, text, fee, ask_bps, open_terms, source, pass_bps)` payable | anyone | The value is the holdback. Returns the id. |
| `declare_source(work, source, pass_bps)` | creator | Admit a source later. No back payment. |
| `set_fee(work, fee)` | creator | |
| `set_terms(work, ask_bps, open_terms)` | creator | The ask can only go down. |
| `top_up(work)` payable | anyone | Adds to the holdback of an active work. |
| `license(work, quantity)` payable | anyone | Exactly fee × quantity. |
| `withdraw(work, amount)` | creator | Not while frozen. |
| `retire(work)` / `reclaim(work)` | creator | Reclaim the holdback five minutes after retiring. |
| `open_dispute(work, source, reason)` payable | not the creator | Bond 0.005 GEN. Returns the dispute id. |
| `judge(dispute)` | anyone | The only call that can use the model. |
| `concede(dispute)` | accused creator | |
| `waive(dispute)` | source creator | |
| `lapse(dispute)` | anyone | An hour after the dispute was opened. |

Views (9, all return JSON text): `stats`, `solvency`, `get_work`, `list_works(offset, limit)`,
`works_of(address, offset, limit)`, `get_dispute`, `list_disputes(offset, limit)`, `lineage_of(work)` (the links a fee
travels along), `preview_split(work, amount)`. Lists are newest first, pages of at most 25.

## Limitations

Stated plainly, because a registry that hides them is worse than one that has them.

* **First registered is not first written.** The contract cannot tell an author from someone who registered another
  person's text first. Anyone can pre-register a well-known text, ask for a share and dispute later works that repeat
  it. The only protection is that the source creator can `waive`, and that all of this is public on a ledger.
  Tributary is a lineage ledger between registered works, not a proof of authorship.
* **Paraphrase detection is only as good as the model.** Verbatim and lightly edited copies are caught by the code
  alone. A good paraphrase or a translation depends on the model's reading and may end as `UNSURE`, which changes
  nothing (by design). Nobody is punished on a doubt, and some real derivatives will go unpunished.
* **The steering tripwire is a list.** A creative attacker can phrase around it. The numbers, thresholds, the copy
  detector and the human exits are what hold the line, and a text that fools the model can at worst produce a verdict
  with bounded consequences (the back royalties are capped by what the work holds, the fine by 25% of its holdback).
* **A bad leader can force an "unsure".** If the leader proposes `UNSURE` and the validators' own readings land within
  25 points of its overlap, the network accepts it, even when the case was clear to the validators. Nothing is lost
  (the bond goes back) and the pair can be tried once more, but not a third time.
* **At most one forced link per work**, and the line a fee travels is four generations deep.
* **Texts are public and on chain.** Registering costs storage; there is no deletion.
* **A dispute can freeze a work for an hour** if the network cannot agree and nobody retries. The accused can call
  `judge` or `concede` at once; `lapse` always ends it.
* **The time constants are demo-sized** (a five minute cool-down, a one hour judging window) so that a live run can
  wait them out. A real deployment would use days. The cool-down is part of the default live run, `lapse` is an
  opt-in scenario (`--only lapse`, it waits an hour).

## Running it

### Local, no network

```bash
bash scripts/setup.sh          # python packages (genlayer-test, genvm-linter) and node packages
genvm-lint check contracts/tributary.py
python3 -m pytest -q           # the whole suite: 406 tests, about seven minutes (the random stories are most of it)
FAST=1 bash scripts/run-all.sh # six random stories instead of thirty, about two minutes in all
```

The suite runs the **real contract** on the GenLayer SDK's local runner, with the model and the clock scripted.

| File | What it covers |
| --- | --- |
| `test_text.py` | cleaning, words, the content key, the copy detector, the tripwire (positives and false positives), `settle` threshold by threshold |
| `test_works.py` | registering (every refusal), links, terms, fees, top-up, retiring and reclaiming, every view and paging |
| `test_royalties.py` | licences, the cascade to the wei, four-generation limit, rounding, previews, withdrawals |
| `test_disputes.py` | opening (every refusal), freezing, the copy detector path, the model path, odd model output, concede, waive, lapse, decoys, two-path credit, the money of every outcome |
| `test_consensus.py` | the validator accept rule case by case and over a grid, forged leader results, a real validator round, pickled closures |
| `test_adversarial.py` | disguised steering, tag injection, absurd integers and strings, escapes from the freeze, griefing, playing both sides |
| `test_fuzz.py` | random stories (30 seeds × 140 steps) checked against a reference model written separately from the contract: every licence split, every dispute outcome, the books after every step, and that every refused call changes nothing |

`python3 scripts/mutation_check.py` damages the contract on purpose (88 deliberate bugs, one at a time) and checks that
the suite fails for each. A bug that survives is a rule that no test protects.

### Live on Studionet

```bash
npm run keys                   # creates three test accounts in .env and asks Studionet to fund them
bash scripts/run-all.sh        # static check, local tests, then the live run (deploys the contract first)
node scripts/e2e.mjs --only copy,exits       # only some scenarios; TRIBUTARY_ADDRESS=0x.. reuses a deployment
node scripts/e2e.mjs --dry-run               # the plan, no network
node scripts/deploy.mjs                      # only deploy (the address goes to .tributary-address)
```

In a GitHub Codespace, add `ALICE_KEY`, `BOB_KEY` and `CAROL_KEY` as Codespaces secrets (three funded Studionet
accounts), open the Codespace, and run `bash scripts/run-all.sh`.

The live run has seven scenarios (plus the opt-in `lapse`) and ends with `reports/tributary-e2e-<time>.html` (plus `.md` and `.json`), which
refreshes itself while the run is going.

| Scenario | What it proves on the real network |
| --- | --- |
| `basics` | register, declared source, licences split to the wei, withdraw, fee, lower terms, top-up, views |
| `adversarial` | about forty calls that must be refused, each decided as an error with no totals changed |
| `cascade` | six works in a line: 5, 3, 1.4, 0.48, 0.12 and 0 milli-GEN; the sixth gets nothing |
| `copy` | a copy hides behind a decoy; the code alone upholds the dispute; both links pay; back royalties and fine exact |
| `paraphrase` | the **real model** judges a paraphrase and an unrelated text; any verdict is followed to the end and its consequences checked |
| `exits` | concede (no fine), waive, and closed disputes stay closed |
| `lifecycle` | retire, refusals, the five minute cool-down on chain time, reclaim |
| `lapse` (opt-in) | an unjudged dispute lapses after the one hour window; the bond returns and the pair can be tried again |

The model's verdicts are not fixed, so the `paraphrase` scenario accepts any of them and checks what must hold for
all: that the books balance, that an upheld dispute has the clear numbers behind it and pays exactly the rule, that a
dismissed one hands over the bond and nothing else, and that an unsure one changes nothing. The report lists what the
judge said, with its overlap, the copy share and whether the code or the model decided.

### Rehearsal (offline)

```bash
bash rehearsal/run.sh                              # the model calls the paraphrase derivative
JUDGE_MODE=independent bash rehearsal/run.sh       # or: unsure
```

A stub plays `genlayer-js` and the network, the real contract runs behind it in the local runner, and
`scripts/e2e.mjs` runs against it **unchanged** (the chain clock runs 60 times faster so the cool-down takes seconds).
It checks the script and the contract on the exact calls of the live run. It does not check the real model.

### Troubleshooting

* *The first local test run fails with a 404 while downloading the GenVM runtime.* The newest GenVM release sometimes
  ships without the runtime file. `bash scripts/setup.sh` caches release v0.2.16, which is what the suite was run
  against, in `~/.cache/gltest-direct`.
* *The live run says an account is not funded.* `npm run keys` asks Studionet's simulator to fund the new accounts; if
  that is refused, fund the three addresses it printed from the Studio faucet.
* *A `judge` transaction ends as an error or undetermined.* The validators did not agree on the model's reading, or the
  model did not return JSON. Nothing changed; run it again (the live script retries three times), or let the dispute
  lapse after the hour.

## Layout

```
contracts/tributary.py      the intelligent contract
tests/direct/               the local suite (genlayer-test, direct mode)
scripts/e2e.mjs             live run on Studionet with the report
scripts/deploy.mjs          deploy to Studionet
scripts/keys.mjs            create and fund test accounts
scripts/receipt.mjs         reads the outcome of a transaction receipt
scripts/run-all.sh          static check + local tests + live run + summary
scripts/setup.sh            install everything
scripts/mutation_check.py   the mutation check
rehearsal/                  the offline rehearsal of the live run
.devcontainer/              GitHub Codespaces setup
```
