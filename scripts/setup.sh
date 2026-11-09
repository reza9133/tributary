#!/usr/bin/env bash
# Installs everything the tests and the live run need. Safe to run more than once.
cd "$(dirname "$0")/.." || exit 1
set -e
echo "== python packages"
python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -r requirements.txt
echo "== GenVM runtime for the local tests"
# The local runner downloads the newest GenVM release the first time it runs. When that release has no runtime file
# (this has happened with release candidates) the download fails with a 404, so a known good runtime is cached first.
cache="${HOME}/.cache/gltest-direct"
if ls "$cache"/genvm-universal-*.tar.xz >/dev/null 2>&1; then
  echo "already cached: $(ls "$cache" | head -1)"
else
  mkdir -p "$cache"
  if curl -fsSL -o "$cache/genvm-universal-v0.2.16.tar.xz" "https://github.com/genlayerlabs/genvm/releases/download/v0.2.16/genvm-universal.tar.xz"; then
    echo "cached GenVM v0.2.16"
  else
    rm -f "$cache/genvm-universal-v0.2.16.tar.xz"
    echo "could not cache the runtime now; the first test run will try to download it itself"
  fi
fi
echo "== node packages"
npm install --no-audit --no-fund
echo "== done. Next:  npm run keys   then   bash scripts/run-all.sh"
