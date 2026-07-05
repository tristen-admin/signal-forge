#!/usr/bin/env python3
"""
Regenerate the client's inline CARD_RULES from the canonical server/rules.json.

server/rules.json is the single source of truth for card abilities. The self-contained client
can't fetch it at runtime (CSP), so it carries an inline copy. Run this whenever rules.json changes
to keep the two identical:

    python3 server/sync_rules.py [path/to/client.html]

Default target is ../index.html (the git-tracked client). Idempotent + safe: it only rewrites the
CARD_RULES literal, leaves everything else untouched, and no-ops if the client hasn't adopted the spec.
"""
import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, "rules.json")
TARGET = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "index.html")
MARK_A, MARK_B = "const CARD_RULES = ", ";\nfunction evalRuleCond"

def main():
    rules_text = open(RULES, encoding="utf-8").read().strip()
    json.loads(rules_text)  # validate it's real JSON before touching the client
    g = open(TARGET, encoding="utf-8").read()
    if MARK_A not in g or MARK_B not in g:
        print(f"— {os.path.basename(TARGET)}: no CARD_RULES block found (client hasn't adopted the spec) — nothing to do")
        return 0
    start = g.index(MARK_A) + len(MARK_A)
    end = g.index(MARK_B)
    if g[start:end].strip() == rules_text:
        print(f"✓ {os.path.basename(TARGET)}: CARD_RULES already matches rules.json — no change")
        return 0
    open(TARGET, "w", encoding="utf-8").write(g[:start] + rules_text + g[end:])
    n = len(json.loads(rules_text))
    print(f"✓ {os.path.basename(TARGET)}: CARD_RULES regenerated from rules.json ({n} cards)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
