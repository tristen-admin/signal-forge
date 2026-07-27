#!/usr/bin/env python3
"""Structured query CLI for the Signal Forge game file.

Replaces the ad-hoc grep + hand-written escape-aware Python parser that got
rewritten from scratch, imperfectly, many times over this project — every
card-name apostrophe/quote edge case, every "the bracket scanner tripped on a
']' inside an ability string" bug, has already been paid for once, here.

Usage:
  sf_query.py card "Bram the Bulwark"       # full parsed record: def + every
                                             # reference (CARD_RULES, CALLED,
                                             # LINK_GROUPS, REMNANT_POW, RALLY,
                                             # NAME_OVERRIDE, CARD_STYLE)
  sf_query.py cards --rarity rare           # name/pow/cost/rarity, one per line
  sf_query.py cards --filter muster         # same, filtered by name+abil text
  sf_query.py func resolve                  # exact line range + body of a
                                             # top-level `function name(...)` —
                                             # brace-depth-aware, not regex-guessed
  sf_query.py grep "Kessuae"                # raw grep fallback, but strips any
                                             # embedded data: URI it would
                                             # otherwise vomit into the result

Defaults to the file at devserver/watch_config.json's "source" (whatever the
devserver is currently watching); override with --file.
No deps, stdlib only. Every function here is written ONCE — call it, don't
re-derive it under pressure.
"""
import sys, os, re, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_URI_RE = re.compile(r'data:[^\s"\'\)]+')

def default_source():
    cfg_path = os.path.join(HERE, "watch_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path) as f:
                return json.load(f).get("source")
        except Exception:
            pass
    return None

def strip_data_uris(s):
    return DATA_URI_RE.sub('[data-uri omitted]', s)

def iter_code_chars(text, start):
    """Yield (pos, char) for text[start:], skipping over the CONTENTS of
    single/double-quoted strings and template literals — but correctly
    re-entering real-code context for a template literal's `${...}`
    expressions, including when THOSE expressions themselves contain nested
    template literals or object/array literals (arbitrary depth, via a stack).

    A single-flag quote tracker gets this wrong: this codebase builds a lot of
    UI HTML via template literals with nested `${cond ? `...` : '...'}`-style
    expressions, and naively treating the whole backtick literal as opaque
    text misses braces that are genuinely part of the code (or, as happened
    once, silently stays "inside a string" forever, throwing off every bracket
    count for the rest of the file)."""
    stack = []  # 'squote' | 'dquote' | 'tmpl' | ['texpr', depth]  (list = mutable depth)
    esc = False
    n = len(text)
    j = start
    while j < n:
        c = text[j]
        top = stack[-1] if stack else None
        if top == 'squote' or top == 'dquote':
            qc = "'" if top == 'squote' else '"'
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == qc: stack.pop()
            j += 1
            continue
        if top == 'tmpl':
            if esc: esc = False
            elif c == '\\': esc = True
            elif c == '`': stack.pop()
            elif c == '$' and j + 1 < n and text[j + 1] == '{':
                stack.append(['texpr', 0])
                j += 2
                continue
            j += 1
            continue
        if isinstance(top, list) and top[0] == 'texpr':
            if c == "'": stack.append('squote')
            elif c == '"': stack.append('dquote')
            elif c == '`': stack.append('tmpl')
            elif c in '{[(':
                top[1] += 1
                yield (j, c)
            elif c in '}])':
                if c == '}' and top[1] == 0:
                    stack.pop()  # closes this ${ ... }, not a code brace
                else:
                    top[1] -= 1
                    yield (j, c)
            else:
                yield (j, c)
            j += 1
            continue
        # genuine top-level code
        if c == '/' and j + 1 < n and text[j + 1] == '/':
            # line comment -- none of this is real code, and this codebase's dev comments are
            # full of English contractions (Ahdor's, doesn't, wasn't...); a bare tracker that
            # doesn't know comments exist will read that apostrophe as a real string open and
            # desync everything after it. Skip straight to the newline.
            k = text.find('\n', j)
            j = k if k >= 0 else n
            continue
        if c == '/' and j + 1 < n and text[j + 1] == '*':
            k = text.find('*/', j + 2)
            j = k + 2 if k >= 0 else n
            continue
        if c == "'": stack.append('squote')
        elif c == '"': stack.append('dquote')
        elif c == '`': stack.append('tmpl')
        else:
            yield (j, c)
        j += 1

def find_balanced_block(s, start_idx, open_ch, close_ch):
    """From the first open_ch at/after start_idx, scan to its matching close_ch,
    counting brackets only in genuine code context (see iter_code_chars).
    Returns (open_pos, close_pos_inclusive) or None."""
    i = s.find(open_ch, start_idx)
    if i < 0:
        return None
    depth = 0
    for j, c in iter_code_chars(s, i):
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return (i, j)
    return None

def parse_object_array(text, const_name):
    """Parse `const NAME = [ {...}, {...}, ... ];` into a list of raw object
    substrings. Splits on genuine top-level braces only, via iter_code_chars
    -- so comments and quoted/template text (including escaped quotes like
    'Ghorruk \\"Gnarly\\" Judarr', and this codebase's abundant English
    contractions inside dev comments -- "Ahdor's", "doesn't" -- which a
    bare quote-tracker would misread as real string delimiters) never
    affect the brace count.

    Real regression this once was (7/27/26): a `//` dev comment with an ODD
    number of apostrophes ("Ahdor's Pride", "Keawe's Circle", "session's")
    left an earlier hand-rolled tracker here believing it was still inside a
    string by the time real code resumed, silently swallowing the next
    card's opening `{` and truncating the whole array parse a few objects
    later once brace depth went negative. iter_code_chars now skips both
    `//` and `/* */` comments entirely, so this can't recur here or in any
    other caller."""
    marker = "const %s = [" % const_name
    start = text.find(marker)
    if start < 0:
        marker2 = "const %s=[" % const_name
        start = text.find(marker2)
        if start < 0:
            return []
    block = find_balanced_block(text, start, '[', ']')
    if not block:
        return []
    arr = text[block[0]:block[1] + 1]
    objs = []
    depth, obj_start = 0, None
    for j, c in iter_code_chars(arr, 0):
        if c == '{':
            if depth == 0:
                obj_start = j
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                objs.append(arr[obj_start:j + 1])
    return objs

def get_field(obj_src, key, as_str=True):
    """Extract a `key:'...'` / `key:"..."` / `key:123` field from a raw object
    substring, unescaping \\' and \\" so the returned value is the real string."""
    if as_str:
        m = re.search(r"%s:(['\"])((?:\\.|(?!\1).)*)\1" % re.escape(key), obj_src)
        if m:
            return m.group(2).replace("\\'", "'").replace('\\"', '"').replace('\\\\', '\\')
        m2 = re.search(r"%s:(\d+)" % re.escape(key), obj_src)
        return m2.group(1) if m2 else None
    m = re.search(r"%s:(\d+)" % re.escape(key), obj_src)
    return m.group(1) if m else None

def all_cards(text):
    """Every collectible card as {name, pow, cost, rarity, timing, abil, raw}."""
    out = []
    for const in ("HAND_CARDS", "DECK_POOL"):
        for raw in parse_object_array(text, const):
            name = get_field(raw, "name")
            if not name:
                continue
            out.append({
                "name": name,
                "pow": get_field(raw, "pow"),
                "cost": get_field(raw, "cost"),
                "rarity": get_field(raw, "rarity"),
                "timing": get_field(raw, "timing"),
                "abil": get_field(raw, "abil"),
                "raw": raw,
            })
    return out

def find_map_entry(text, const_name, card_name):
    """For a `const NAME = {...}` map keyed by card name, find that card's raw
    value substring (handles both quote styles + escaped quotes in the key)."""
    start = text.find("const %s" % const_name)
    if start < 0:
        return None
    block = find_balanced_block(text, start, '{', '}')
    if not block:
        return None
    seg = text[block[0]:block[1] + 1]
    for q in ("'", '"'):
        esc_name = card_name.replace('\\', '\\\\').replace(q, '\\' + q)
        key = q + esc_name + q + ":"
        ki = seg.find(key)
        if ki < 0:
            continue
        vstart = ki + len(key)
        # value could be an object {...}, array [...], or a scalar up to the next top-level comma
        if seg[vstart:vstart + 1] == '{':
            b = find_balanced_block(seg, vstart, '{', '}')
            return seg[vstart:b[1] + 1] if b else None
        if seg[vstart:vstart + 1] == '[':
            b = find_balanced_block(seg, vstart, '[', ']')
            return seg[vstart:b[1] + 1] if b else None
        # scalar: read to the next comma/closing brace at depth 0
        depth, quote, esc, j = 0, None, False, vstart
        while j < len(seg):
            c = seg[j]
            if quote:
                if esc: esc = False
                elif c == '\\': esc = True
                elif c == quote: quote = None
            else:
                if c in ("'", '"'): quote = c
                elif c in '{[': depth += 1
                elif c in '}]':
                    if depth == 0: break
                    depth -= 1
                elif c == ',' and depth == 0:
                    break
            j += 1
        return seg[vstart:j].strip()
    return None

def find_overrides(text, const_name, card_name):
    """Find later imperative reassignments — `CONST['exact name']=value;` —
    ANYWHERE in the file, outside the initial object literal. This codebase's
    balance-pass pattern does exactly this (e.g. a REMNANT_POW override block
    runs after the const literal to bump a value at load time), so a lookup
    that only reads the initializer can report a value that's stale at
    runtime. Returns [(line_no, statement), ...]."""
    hits = []
    for q in ("'", '"'):
        esc_name = card_name.replace('\\', '\\\\').replace(q, '\\' + q)
        pat = re.escape(const_name) + r"\[" + re.escape(q + esc_name + q) + r"\]\s*=\s*[^;]+;"
        for m in re.finditer(pat, text):
            line_no = text.count('\n', 0, m.start()) + 1
            hits.append((line_no, m.group(0)))
    return hits

def find_array_membership(text, const_name, card_name):
    """LINK_GROUPS is `const LINK_GROUPS = [ {id:'x', name:.., members:[...]}, ... ]`
    — an ARRAY of group objects, not a map. (There's also an unrelated
    `STARTER_DECKS = {ironsworn:[...], blackwings:[...], ...}` object elsewhere
    that looks similar at a glance but is a different feature — the starter-deck
    sampler, not the in-combat Link-bonus mechanism. Don't conflate them.)
    Finds the true extent of `const NAME`'s value (object OR array, whichever it
    actually is) and, if it's an array of {id, members:[...]} group objects,
    reports which group id(s) actually list this card as a member."""
    hits = []
    m = re.search(r"const\s+%s\s*=\s*([\[{])" % re.escape(const_name), text)
    if not m:
        return hits
    open_ch = m.group(1)
    close_ch = ']' if open_ch == '[' else '}'
    b = find_balanced_block(text, m.start(), open_ch, close_ch)
    if not b:
        return hits
    seg = text[b[0]:b[1] + 1]
    for gm in re.finditer(r"id:\s*'(\w+)'", seg):
        obj_start = seg.rfind('{', 0, gm.start())
        if obj_start < 0:
            continue
        ob = find_balanced_block(seg, obj_start, '{', '}')
        if not ob:
            continue
        gseg = seg[ob[0]:ob[1] + 1]
        mm = re.search(r"members:\s*\[([^\]]*)\]", gseg)
        member_seg = mm.group(1) if mm else gseg
        if ("'%s'" % card_name) in member_seg or ('"%s"' % card_name) in member_seg:
            hits.append(gm.group(1))
    return hits

def cmd_card(args):
    text = read_source(args)
    cards = all_cards(text)
    match = next((c for c in cards if c["name"].lower() == args.name.lower()), None)
    if not match:
        fuzzy = [c["name"] for c in cards if args.name.lower() in c["name"].lower()]
        print(json.dumps({"error": "not found", "did_you_mean": fuzzy[:8]}, indent=2))
        return 1
    out = {k: match[k] for k in ("name", "pow", "cost", "rarity", "timing", "abil")}
    out["def_raw"] = match["raw"]
    for const in ("CARD_RULES", "CALLED", "RALLY", "REMNANT_POW", "COST_OVERRIDE",
                  "NAME_OVERRIDE", "CARD_STYLE", "CARD_ART"):
        v = find_map_entry(text, const, match["name"])
        if v is not None:
            out[const] = strip_data_uris(v) if const == "CARD_ART" else v
        overrides = find_overrides(text, const, match["name"])
        if overrides:
            # a later imperative reassignment exists — the initializer value above
            # (if any) is stale at runtime; this is the value that actually applies
            out[const + "_RUNTIME_OVERRIDE"] = [
                {"line": ln, "statement": stmt} for ln, stmt in overrides
            ]
    memberships = find_array_membership(text, "LINK_GROUPS", match["name"])
    if memberships:
        out["LINK_GROUPS_membership"] = memberships
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0

def cmd_cards(args):
    text = read_source(args)
    cards = all_cards(text)
    if args.rarity:
        cards = [c for c in cards if (c["rarity"] or "").lower() == args.rarity.lower()]
    if args.filter:
        f = args.filter.lower()
        cards = [c for c in cards if f in c["name"].lower() or f in (c["abil"] or "").lower()]
    for c in sorted(cards, key=lambda c: (-(int(c["pow"] or 0)))):
        print("%-8s p%-4s c%-3s %s" % (c["rarity"] or "?", c["pow"] or "?", c["cost"] or "-", c["name"]))
    print("-- %d cards --" % len(cards), file=sys.stderr)
    return 0

def cmd_func(args):
    text = read_source(args)
    for pat in (r"function\s+%s\s*\(" % re.escape(args.name),
                r"const\s+%s\s*=\s*function\s*\(" % re.escape(args.name),
                r"let\s+%s\s*=\s*function\s*\(" % re.escape(args.name)):
        m = re.search(pat, text)
        if m:
            b = find_balanced_block(text, m.end(), '{', '}')
            if not b:
                continue
            line_start = text.count('\n', 0, m.start()) + 1
            line_end = text.count('\n', 0, b[1]) + 1
            body = text[m.start():b[1] + 1]
            print(json.dumps({
                "name": args.name, "line_start": line_start, "line_end": line_end,
                "chars": len(body), "body": strip_data_uris(body)
            }, indent=2, ensure_ascii=False))
            return 0
    print(json.dumps({"error": "function not found: %s" % args.name}))
    return 1

def cmd_grep(args):
    text = read_source(args)
    hits = []
    for i, line in enumerate(text.split('\n'), 1):
        if args.pattern.lower() in line.lower() if args.i else args.pattern in line:
            hits.append("%d: %s" % (i, strip_data_uris(line)[:300]))
        if len(hits) >= args.max:
            hits.append("... (truncated at --max %d)" % args.max)
            break
    print('\n'.join(hits) if hits else "(no matches)")
    return 0

def read_source(args):
    path = args.file or default_source()
    if not path or not os.path.exists(path):
        print(json.dumps({"error": "source file not found", "tried": path}), file=sys.stderr)
        sys.exit(2)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="override the source file (default: devserver/watch_config.json's 'source')")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("card"); p.add_argument("name"); p.set_defaults(fn=cmd_card)
    p = sub.add_parser("cards"); p.add_argument("--rarity"); p.add_argument("--filter"); p.set_defaults(fn=cmd_cards)
    p = sub.add_parser("func"); p.add_argument("name"); p.set_defaults(fn=cmd_func)
    p = sub.add_parser("grep"); p.add_argument("pattern"); p.add_argument("--max", type=int, default=40); p.add_argument("-i", action="store_true"); p.set_defaults(fn=cmd_grep)

    args = ap.parse_args()
    sys.exit(args.fn(args))

if __name__ == "__main__":
    main()
