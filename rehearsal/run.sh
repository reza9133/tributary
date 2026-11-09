#!/usr/bin/env bash
# Offline rehearsal of the live run: the real contract runs in the local test runner, a stub plays genlayer-js and
# the network, and scripts/e2e.mjs runs against it unchanged. It checks the script's logic and the contract's
# behaviour on the exact calls of the live run, not the real AI.
#   bash rehearsal/run.sh                                  all scenarios, the model calls the paraphrase derivative
#   JUDGE_MODE=independent bash rehearsal/run.sh --only paraphrase
#   JUDGE_MODE=unsure bash rehearsal/run.sh --only paraphrase,exits
# JUDGE_MODE: derivative | independent | unsure | flaky   (what the scripted model answers about the paraphrase;
#   flaky says unsure the first time and derivative the second, to exercise the second try)
# The chain clock of the stub runs REHEARSAL_SPEED times faster than real time (default 60), so that the five minute
# cool-down of the lifecycle scenario takes seconds.
set -e
here="$(cd "$(dirname "$0")/.." && pwd)"
work="$here/.rehearsal-tmp"
rm -rf "$work"
mkdir -p "$work"
cp -r "$here/scripts" "$work/scripts"
ln -s "$here/contracts" "$work/contracts"
mkdir -p "$work/node_modules"
cp -r "$here/rehearsal/stub/genlayer-js" "$work/node_modules/genlayer-js"
cp "$here/package.json" "$work/package.json"
export REHEARSAL_ROOT="$here"
export ALICE_KEY=0x$(printf '1%.0s' $(seq 1 64))
export BOB_KEY=0x$(printf '2%.0s' $(seq 1 64))
export CAROL_KEY=0x$(printf '3%.0s' $(seq 1 64))
unset TRIBUTARY_ADDRESS OUTSIDER_KEY
export REPORT_DIR="$here/reports/rehearsal"
cd "$work"
node scripts/e2e.mjs "$@"
