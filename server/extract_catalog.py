#!/usr/bin/env python3
"""Canonical-sync tool: extract the live card spec from the client HTML into catalog.json.
The CLIENT is the source of truth; this flattens its data literals so the server loads ONE spec.
Re-run whenever the client's cards change."""
import re, subprocess, os, tempfile, json, sys
CLIENT = "/private/tmp/claude-501/-Users-kotei/97cae9eb-fc1a-4872-a2b6-a367e92660a6/scratchpad/gameplay-systems.html"
OUT = os.path.join(os.path.dirname(__file__), "catalog.json")
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
html = open(CLIENT, encoding="utf-8").read()

def find_literal(s, name):
    m = re.search(r'(?:const|let|var)\s+'+re.escape(name)+r'\s*=\s*', s)
    if not m: sys.exit("no decl: "+name)
    i = m.end()
    while i < len(s) and s[i] not in '[{': i += 1
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
    sys.exit("unbalanced: "+name)

names=['HAND_CARDS','DECK_POOL','OPP_CARDS','LINK_GROUPS','STARTER_SET','CALLED','CARD_RULES','COST_OVERRIDE']
blocks=["var %s = %s;"%(n, find_literal(html,n)) for n in names]
cc=re.search(r'function conjureCost\(c\)\{[^\n]*\}', html); 
if not cc: sys.exit("no conjureCost")
blocks.append(cc.group(0))
prog="\n".join(blocks)+r"""
var cards={}, starter=(typeof STARTER_SET!=='undefined'?STARTER_SET:[]);
function add(c,opp){ if(!c||c.uid||c.variant||cards[c.name])return;
  cards[c.name]={pow:c.pow,rarity:c.rarity,cost:conjureCost(c),abil:c.abil||'',timing:c.timing||'on',starter:starter.indexOf(c.name)>=0,opp:!!opp}; }
HAND_CARDS.forEach(function(c){add(c,false)}); DECK_POOL.forEach(function(c){add(c,false)});
OPP_CARDS.forEach(function(c){ if(!cards[c.name]) add(c,true); });
var links={}; LINK_GROUPS.forEach(function(g){ links[g.id]={name:g.name,icon:g.icon,pow:g.pow,members:g.members}; });
print(JSON.stringify({cards:cards, called:CALLED, rules:CARD_RULES, links:links, starter:starter, costOverride:COST_OVERRIDE}));
"""
tf=tempfile.NamedTemporaryFile('w',suffix='.js',delete=False,encoding='utf-8'); tf.write(prog); tf.close()
r=subprocess.run([JSC,tf.name],capture_output=True,text=True); os.unlink(tf.name)
if r.returncode!=0: print("JSC ERR rc",r.returncode,"\nOUT:",r.stdout[:800],"\nERR:",r.stderr[:800]); sys.exit(1)
data=json.loads(r.stdout)
json.dump(data, open(OUT,'w',encoding='utf-8'), ensure_ascii=False, indent=1)
print("OK -> catalog.json | cards:%d starter:%d links:%d rules:%d called:%d"%(
    len(data['cards']), len(data['starter']), len(data['links']), len(data['rules']), len(data['called'])))
