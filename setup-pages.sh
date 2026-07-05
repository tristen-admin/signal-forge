#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
gh repo create signal-forge --public --source=. --remote=origin --push
OWNER=$(gh api user -q .login)
gh api -X POST "repos/$OWNER/signal-forge/pages" -f "source[branch]=main" -f "source[path]=/docs" \
  || gh api -X PUT "repos/$OWNER/signal-forge/pages" -f "source[branch]=main" -f "source[path]=/docs" || true
echo ""
echo "✅ Live shortly at:  https://$OWNER.github.io/signal-forge/"
echo "   (first build takes 1-2 min; then it's your permanent link)"
