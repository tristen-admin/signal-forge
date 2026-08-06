#!/usr/bin/env python3
"""Canonical-sync tool: extract the live card spec from the client HTML into catalog.json.
The CLIENT is the source of truth; this flattens its data literals so the server loads ONE spec.
Re-run whenever the client's cards change."""
import re, subprocess, os, tempfile, json, sys
CLIENT = "/Users/kotei/signal-forge/index.html"   # 8/5/26: was a dead session-scratchpad path from a past agent run -- this tool could not regenerate against the real client at all until this fix. index.html is the one true source; never point this anywhere else.
OUT = os.path.join(os.path.dirname(__file__), "catalog.json")
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
html = open(CLIENT, encoding="utf-8").read()

def _scan_braced(s, i):
    """From index i (which must be at a '[' or '{'), brace-match to the close, string/comment-aware."""
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
    if not m: sys.exit("no decl: "+name)
    i = m.end()
    while i < len(s) and s[i] not in '[{': i += 1
    out = _scan_braced(s, i)
    if out is None: sys.exit("unbalanced: "+name)
    return out

def find_function(s, name):
    """Brace-match a `function name(...){...}` body regardless of line count -- a fixed single-
    line regex silently breaks the moment a function grows past one line, which is exactly what
    happened here (conjureCost() split into baseCardCost()+conjureCost() and grew multi-line;
    the old regex just failed loudly instead, which is at least the honest outcome of the two)."""
    m = re.search(r'function\s+'+re.escape(name)+r'\s*\([^)]*\)\s*\{', s)
    if not m: sys.exit("no decl: "+name)
    i = s.index('{', m.start())
    out = _scan_braced(s, i)
    if out is None: sys.exit("unbalanced: "+name)
    return s[m.start():i] + out

def find_number(s, name):
    """A bare `const NAME = 15;` numeric literal -- too simple for brace-matching."""
    m = re.search(r'(?:const|let|var)\s+'+re.escape(name)+r'\s*=\s*(-?\d+(?:\.\d+)?)\s*;', s)
    if not m: sys.exit("no decl: "+name)
    return m.group(1)

names=['HAND_CARDS','DECK_POOL','OPP_CARDS','LINK_GROUPS','STARTER_SET','CALLED','CARD_RULES','COST_OVERRIDE',
       'CARD_RACE','REMNANT_POW','TRIGGERS','OPTIONAL_HAND_RETURN']   # 8/5/26 Milestone A: Bloodlines Clash
       # (camp-of-race) + Death Remnant power overrides + deck-trigger cards + optional hand-return rules
blocks=["var %s = %s;"%(n, find_literal(html,n)) for n in names]
# 8/5/26 Phase 4: Ascension data. Declaration order matters -- ASC_FOES* pools are referenced
# INSIDE the ASC_STORY/ASC_STORY_CH2 node object literals (a real TDZ, per the client's own
# 13057-13063/13081-13084 comments), and ASC_STORY/ASC_STORY_CH2 are referenced inside
# ASC_CHAPTERS's `beats:` fields -- extract in true dependency order, not alphabetical.
# ROOF_MAP/DM_ACTIVATED_ABILITY/DM_EXCLUSIVE have no ordering dependency on the Ascension arrays
# (only consumed by champion-eligibility/generic-ability Python logic, not by each other's literals).
_asc_names = ['ROOF_MAP','DM_ACTIVATED_ABILITY','DM_EXCLUSIVE','ASC_UNITS','ASC_PASSIVES',
              'ASC_MOVE_UNLOCK','ASC_MOVES_CAP','ASC_MOVES','ASC_BOSS_SIGS',
              'ASC_FOES','ASC_FOES_CADETS','ASC_FOES_WRIT','ASC_FOES_SORNVALLIS',
              'ASC_STORY','ASC_STORY_CH2','ASC_CHAPTERS']
blocks += ["var %s = %s;"%(n, find_literal(html,n)) for n in _asc_names]
# hashStr(): the deterministic per-card-name hash ascGenericBaseStats() uses for its stat jitter --
# a real function (h=(h*31+charCode)>>>0), not data, but harmless/cheap to carry through JSC here
# alongside everything else rather than a separate extraction pass; the *_apply_rules-equivalent
# Python port still needs its own exact reimplementation (unsigned 32-bit wrap, not the signed-then-
# abs of rules.py's _name_hash -- a DIFFERENT algorithm despite sharing the *31 core, confirmed by
# reading both real functions side by side, not assumed from the shared multiplier).
blocks.append(find_function(html, "hashStr"))
# 8/5/26: CONDITIONS' `rule` field string-concatenates CONDITION_VETERAN_CAP -- must be in scope
# before CONDITIONS is evaluated, or JSC throws a ReferenceError. Extract it first, as a number.
blocks.insert(0, "var CONDITION_VETERAN_CAP = %s;" % find_number(html, "CONDITION_VETERAN_CAP"))
# CONDITIONS (whole-duel modifiers) and TRAITS (Living-Card traits) are pure metadata for CONDITIONS
# (id/mech/icon/name/rule/strat/tag/prob, no functions) but TRAITS entries carry function-valued
# test/when/prog closures alongside the plain fields (id/name/icon/pow/cond/desc) -- JSON.stringify
# silently drops function values on its own, which is exactly the metadata-only slice the server
# needs; the actual test()/when() BEHAVIOR is fixed control-flow, ported as real Python code
# (Milestone A), not data -- same reasoning as Called/resolve()'s pipeline order, see the plan.
blocks.append("var CONDITIONS = %s;" % find_literal(html, "CONDITIONS"))
blocks.append("var TRAITS = %s;" % find_literal(html, "TRAITS"))
# 8/5/26: conjureCost(c) now wraps LIVE match state (dmZeroCostThisDuel, a per-instance
# _costDiscount) that doesn't exist in this static extraction context and shouldn't -- a catalog
# entry should record the card's BASE cost, with any in-duel modifier applied dynamically server-
# side too, mirroring the client's own baseCardCost()/conjureCost() split. Extract baseCardCost.
blocks.append(find_function(html, "baseCardCost"))
prog="\n".join(blocks)+r"""
var cards={}, starter=(typeof STARTER_SET!=='undefined'?STARTER_SET:[]);
function add(c,opp){ if(!c||c.uid||c.variant||cards[c.name])return;
  cards[c.name]={pow:c.pow,rarity:c.rarity,cost:baseCardCost(c),abil:c.abil||'',timing:c.timing||'on',starter:starter.indexOf(c.name)>=0,opp:!!opp}; }
HAND_CARDS.forEach(function(c){add(c,false)}); DECK_POOL.forEach(function(c){add(c,false)});
OPP_CARDS.forEach(function(c){ if(!cards[c.name]) add(c,true); });
var links={}; LINK_GROUPS.forEach(function(g){ links[g.id]={name:g.name,icon:g.icon,pow:g.pow,members:g.members}; });
var conditions=CONDITIONS.map(function(c){ return {id:c.id,mech:c.mech,tag:c.tag,prob:c.prob,rule:c.rule}; });
var traits=TRAITS.map(function(t){ return {id:t.id,name:t.name,pow:t.pow,cond:t.cond||null,desc:t.desc}; });
var dmNames={}; Object.keys(DM_ACTIVATED_ABILITY).forEach(function(k){dmNames[k]=true;}); Object.keys(DM_EXCLUSIVE).forEach(function(k){dmNames[k]=true;});
print(JSON.stringify({cards:cards, called:CALLED, rules:CARD_RULES, links:links, starter:starter, costOverride:COST_OVERRIDE, conditions:conditions, traits:traits, cardRace:CARD_RACE, remnantPow:REMNANT_POW, triggers:TRIGGERS, optionalHandReturn:OPTIONAL_HAND_RETURN,
  roofMap:ROOF_MAP, dmNames:dmNames,
  ascUnits:ASC_UNITS, ascPassives:ASC_PASSIVES, ascMoveUnlock:ASC_MOVE_UNLOCK, ascMovesCap:ASC_MOVES_CAP, ascMoves:ASC_MOVES,
  ascBossSigs:ASC_BOSS_SIGS, ascFoes:ASC_FOES, ascFoesCadets:ASC_FOES_CADETS, ascFoesWrit:ASC_FOES_WRIT, ascFoesSornvallis:ASC_FOES_SORNVALLIS,
  ascStory:ASC_STORY, ascStoryCh2:ASC_STORY_CH2, ascChapters:ASC_CHAPTERS.map(function(c){return {id:c.id,title:c.title,sub:c.sub,beatsLen:c.beats.length};})}));
"""
tf=tempfile.NamedTemporaryFile('w',suffix='.js',delete=False,encoding='utf-8'); tf.write(prog); tf.close()
r=subprocess.run([JSC,tf.name],capture_output=True,text=True); os.unlink(tf.name)
if r.returncode!=0: print("JSC ERR rc",r.returncode,"\nOUT:",r.stdout[:800],"\nERR:",r.stderr[:800]); sys.exit(1)
data=json.loads(r.stdout)
json.dump(data, open(OUT,'w',encoding='utf-8'), ensure_ascii=False, indent=1)
print("OK -> catalog.json | cards:%d starter:%d links:%d rules:%d called:%d conditions:%d traits:%d cardRace:%d remnantPow:%d triggers:%d optionalHandReturn:%d roofMap:%d dmNames:%d ascUnits:%d ascMoves:%d ascFoes:%d+%d+%d+%d ascStory:%d+%d chapters:%d"%(
    len(data['cards']), len(data['starter']), len(data['links']), len(data['rules']), len(data['called']),
    len(data['conditions']), len(data['traits']), len(data['cardRace']), len(data['remnantPow']),
    len(data['triggers']), len(data['optionalHandReturn']), len(data['roofMap']), len(data['dmNames']),
    len(data['ascUnits']), len(data['ascMoves']), len(data['ascFoes']), len(data['ascFoesCadets']),
    len(data['ascFoesWrit']), len(data['ascFoesSornvallis']), len(data['ascStory']), len(data['ascStoryCh2']), len(data['ascChapters'])))
