#!/usr/bin/env python3
"""Differential check: rules.camp_of() vs the real client campOf(), for every catalog card.
Run after any CARD_RACE/camp-system edit. Exits non-zero on any mismatch."""
import json, os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
import rules

CLIENT = "/Users/kotei/signal-forge/index.html"
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
html = open(CLIENT, encoding="utf-8").read()

def _scan_braced(s, i):
    """Brace-match from a '[' or '{' at i to its close, string/comment-aware.
    Inlined from extract_catalog.py rather than imported -- importing that module re-runs its
    top-level JSC/file-write side effect (it's a flat script, not function-wrapped), which a
    read-only verify script should never trigger implicitly."""
    depth=0; j=i; instr=None; esc=False; com=None
    while j < len(s):
        ch=s[j]
        if com=='line':
            if ch=='\n': com=None
        elif com=='block':
            if ch=='*' and s[j+1:j+2]=='/': com=None; j+=1
        elif instr:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch==instr: instr=None
        elif ch=='/' and s[j+1:j+2]=='/': com='line'; j+=1
        elif ch=='/' and s[j+1:j+2]=='*': com='block'; j+=1
        elif ch in '\'"`': instr=ch
        elif ch in '[{': depth+=1
        elif ch in ']}':
            depth-=1
            if depth==0: return s[i:j+1]
        j+=1
    return None

def find_literal(s, name):
    m = re.search(r'(?:const|let|var)\s+'+re.escape(name)+r'\s*=\s*', s)
    i = m.end()
    while s[i] not in '[{': i += 1
    return _scan_braced(s, i)

names = ["HAND_CARDS", "DECK_POOL", "OPP_CARDS", "CARD_RACE"]
blocks = ["var %s = %s;" % (n, find_literal(html, n)) for n in names]
prog = "\n".join(blocks) + r"""
var raceOverride={};
function _nameHash(s){ var h=0; s=String(s||''); for(var i=0;i<s.length;i++){ h=((h<<5)-h+s.charCodeAt(i))|0; } return Math.abs(h); }
function raceOf(name){ return (name && raceOverride[name]) || CARD_RACE[name] || 'Human'; }
const RACE_CAMP = {
  Human:'Amageras', Kaldrei:'Amageras', Kaidrun:'Amageras', Celestial:'Amageras', Construct:'Amageras', Dreikan:'Amageras',
  Marrowen:'Omitsuki', Nightclaw:'Omitsuki', Undying:'Omitsuki', Revenant:'Omitsuki',
  'Vysh\'ra':'Kitanoo', 'N\'imkatta':'Kitanoo', Wrothlan:'Kitanoo', Dragonkin:'Kitanoo', Beast:'Kitanoo', Spirit:'Kitanoo', Fae:'Kitanoo', Dractyl:'Kitanoo', Thennlar:'Kitanoo', Xylotes:'Kitanoo'
};
let campOverride={};
function campOf(name){
  if(name && campOverride[name]) return campOverride[name];
  if(name && (raceOverride[name] || CARD_RACE[name])) return RACE_CAMP[raceOf(name)] || 'Amageras';
  var _camps=['Amageras','Omitsuki','Kitanoo'];
  return _camps[_nameHash(name)%3];
}
var out={};
HAND_CARDS.concat(DECK_POOL).concat(OPP_CARDS).forEach(function(c){ if(c&&c.name&&!out[c.name]) out[c.name]=campOf(c.name); });
print(JSON.stringify(out));
"""
tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
tf.write(prog); tf.close()
r = subprocess.run([JSC, tf.name], capture_output=True, text=True)
os.unlink(tf.name)
if r.returncode != 0:
    print("JSC ERR:", r.stderr[:500]); sys.exit(1)
truth = json.loads(r.stdout)

mismatches = []
for name, expected in truth.items():
    got = rules.camp_of(name)
    if got != expected:
        mismatches.append((name, expected, got))

print(f"checked {len(truth)} cards")
if mismatches:
    print(f"MISMATCH: {len(mismatches)}")
    for name, expected, got in mismatches[:20]:
        print(f"  {name!r}: client={expected} server={got}")
    sys.exit(1)
print("OK -- 0 mismatches")
