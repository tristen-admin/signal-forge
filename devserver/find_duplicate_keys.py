#!/usr/bin/env python3
"""
Detect duplicate top-level keys in Signal Forge's CALLED / CARD_RULES object
literals in index.html. A duplicate key in a JS object literal silently
resolves to whichever definition appears LAST -- the earlier one becomes
dead code with no syntax error and no runtime warning. Run this before every
deploy that touches either object.

Usage: python3 devserver/find_duplicate_keys.py [path/to/index.html]
Exit code: 0 if clean, 1 if any duplicate found.
"""
import sys
from collections import Counter


def scan_object_literal(text, brace_pos):
    """
    text[brace_pos] must be '{'. Walks forward tracking combined {}/[] depth,
    skipping quoted strings (single or double, backslash-escaped) and //
    and /* */ comments so neither can be mistaken for structural characters.
    Collects every quoted string sitting at depth == 1 that is immediately
    followed (after optional whitespace) by ':' -- a real top-level key, not
    a nested one, not an array element, not a comment.

    Returns (keys, end_pos): keys is a list of (name, char_offset) in file
    order; end_pos is the index of the matching closing '}'.
    """
    depth = 0
    i = brace_pos
    n = len(text)
    keys = []
    in_string = False
    string_char = ''
    string_start = 0
    escape = False
    while i < n:
        c = text[i]
        if in_string:
            if escape:
                escape = False
            elif c == '\\':
                escape = True
            elif c == string_char:
                in_string = False
                if depth == 1:
                    j = i + 1
                    while j < n and text[j] in ' \t\r\n':
                        j += 1
                    if j < n and text[j] == ':':
                        keys.append((text[string_start:i], string_start))
            i += 1
            continue
        if c == '/' and text[i + 1:i + 2] == '/':
            nl = text.find('\n', i)
            i = nl if nl != -1 else n
            continue
        if c == '/' and text[i + 1:i + 2] == '*':
            close = text.find('*/', i + 2)
            i = close + 2 if close != -1 else n
            continue
        if c in '"\'':
            in_string, string_char, string_start, escape = True, c, i + 1, False
            i += 1
            continue
        if c in '{[':
            depth += 1
            i += 1
            continue
        if c in '}]':
            depth -= 1
            i += 1
            if depth == 0:
                return keys, i - 1
            continue
        i += 1
    raise ValueError("unbalanced braces: reached EOF before depth returned to 0")


def find_block(text, const_name):
    marker = f'const {const_name} = {{'
    idx = text.find(marker)
    if idx == -1:
        raise ValueError(f"'const {const_name} = {{' not found")
    brace_pos = idx + len(marker) - 1
    keys, end_pos = scan_object_literal(text, brace_pos)
    return keys, idx, end_pos


def line_of(text, pos):
    return text.count('\n', 0, pos) + 1


def check(text, const_name):
    keys, start_pos, end_pos = find_block(text, const_name)
    counts = Counter(name for name, _ in keys)
    dupes = {name: n for name, n in counts.items() if n > 1}
    print(f"=== {const_name} (lines {line_of(text, start_pos)}-{line_of(text, end_pos)}) "
          f"=== {len(keys)} keys, {len(counts)} unique")
    for name, n in dupes.items():
        lines = [line_of(text, pos) for k, pos in keys if k == name]
        print(f"  DUPLICATE x{n}: {name!r} at lines {lines}")
    if not dupes:
        print("  clean, no duplicates")
    return len(dupes)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'index.html'
    with open(path, encoding='utf-8') as f:
        text = f.read()
    total = sum(check(text, name) for name in ('CALLED', 'CARD_RULES'))
    sys.exit(1 if total else 0)


if __name__ == '__main__':
    main()
