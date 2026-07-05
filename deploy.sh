#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python3 build.py
rm -rf docs && cp -r dist docs && touch docs/.nojekyll
git add -A && git commit -m "deploy $(date '+%Y-%m-%d %H:%M')" && git push
OWNER=$(gh api user -q .login 2>/dev/null || echo YOURNAME)
echo "Pushed — Pages updates in ~1 min:  https://$OWNER.github.io/signal-forge/"
