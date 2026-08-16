"""
Signal Forge — authoritative match engine (server-side port of the client resolve()).
Faithful transcription of the client's Fighter-only duel resolution: on-commit abilities (both
sides), all 32 real whole-duel Conditions, Living-Card traits, resolution guards (Ahdor / generic
Record Guard / Last Stand / Regenerating Horror / Untouchable / Ledger Ward / Uso Oso's Bulwark),
Death Remnants, win/lose/tie card-lifecycle routing, and the real charge/energy economy. The
server owns every outcome; the client only requests.

Milestone A scope (rear-guard/Called/Link/Deck-Master-tier effects are Milestone B — see the
per-mechanic comments below for exactly what's deferred and why). Parity verified against
index.html as of 2026-08-05 via direct source reads + server/verify_camp.py + stress_test.py.
"""
import json, os, random
import rules

# ── CARD CATALOG (name → pow/kills/deaths/rarity/abil), ported from HAND_CARDS + DECK_POOL ──
CATALOG = {n: {"pow": c["pow"], "kills": 0, "deaths": 0, "rarity": c["rarity"], "abil": c["abil"]} for n, c in rules.CARD_FULL.items()}   # canonical (catalog.json)

# Client's own top-level const (index.html:3493), read directly since catalog.json's static
# extraction doesn't surface it (it's only consumed at extraction-time to let CONDITIONS' rule-text
# string-concatenate it). Caps the 3 veteran-scaling Conditions -- see the 2026-08-01 fix history.
CONDITION_VETERAN_CAP = 15

# 8/5/26 Milestone A: full real tag set from catalog.json's CONDITIONS metadata (not hand-guessed).
# The interpreter's chaos-check (_ctx's "chaos" key, read by CARD_RULES entries like {"chaos":true})
# was silently wrong before this: CHAOS_CONDS only listed 3 ids (forceswap/surge/mirror) when the
# client's real tag:'chaos' set is 7 (also hollowreckoning/highroller/dredge/wildpit) -- any card
# whose ability checks the chaos flag was silently misjudging "is this a chaos condition" for 4 of
# the 7 real cases. Sourced directly from the extracted data, not maintained by hand, so it can't
# drift again the same way.
CHAOS_CONDS = {c["id"] for c in rules._CAT["conditions"] if c.get("tag") == "chaos"}
FORMATION_TIERS = [(15, "Legendary Duo", 3), (8, "Brothers-in-Arms", 2), (3, "Allied", 1)]

# 8/5/26 Milestone A: real weighted condition selection. Was `random.choice(POWER_CONDS)` over a
# hand-picked 9-item subset (the only ones the old resolve() knew how to apply at all) -- now draws
# from all 32 real conditions, weighted by their real printed probabilities (catalog.json's
# CONDITIONS, which mirrors the client's own CONDITIONS array byte-for-byte via extract_catalog.py).
CONDITIONS = rules._CAT["conditions"]
def _parse_prob(s):
    try: return float(str(s).rstrip("%"))
    except (TypeError, ValueError): return 1.0
_COND_IDS = [c["id"] for c in CONDITIONS]
_COND_WEIGHTS = [_parse_prob(c["prob"]) for c in CONDITIONS]
def pick_condition():
    return random.choices(_COND_IDS, weights=_COND_WEIGHTS, k=1)[0]

# 8/5/26 Milestone A: reveal-time effects. Reinforce/Dredge/Wild Pit fire the MOMENT the condition
# is picked -- before either side commits a fighter (index.html:5163-5166) -- not during resolve().
# The server's pick_condition() call sites (match/start, end of match/commit) own the real uid-keyed
# hand/deck lists engine.py never sees (m["hand"] is a bare type-name mirror, refreshed each commit
# for CARD_RULES ctx purposes only) -- so this returns instructions, and app.py performs the actual
# list moves, same separation as `destination` below. Wild Pit's OTHER effect (locking rear-guard
# support zones) is a no-op until Milestone B's rear-guard slots exist -- nothing to lock yet.
def condition_reveal_effects(cond_id):
    if cond_id == "reinforce": return {"draw": 1, "discard": 0}
    if cond_id == "dredge": return {"draw": 2, "discard": 2}
    if cond_id == "wildpit": return {"draw": 1, "discard": 0}
    return {"draw": 0, "discard": 0}

def card(name):
    c = CATALOG.get(name, {"pow": 8, "kills": 0, "deaths": 0, "rarity": "common", "abil": ""})
    return {"name": name, **c}

# ══════════════════════════════════════════════════════════════════════════════════════════
# MILESTONE B — rear-guard depth: staged support cards (Called/Shield/Link/Bond/Muster).
# Deck-Master ambient-flag plumbing (dmSupportBonusThisDuel, dmNullifyOppSupportsThisDuel, the
# fighter-vs-Deck-Master Bond, Kravyn's handReturnCount rear-guard bonus) stays deferred: none of
# it can exist until the server has a "who is my Deck Master for this match" concept at all,
# which is a bigger, separate piece (Milestone B.2) than rear-guard slots themselves.
# The OPPONENT never fields rear-guards here -- the server's opponent is a fresh random card per
# duel (see opponent_pool()), not a persistent bot session with its own hand/support choices.
# That's the same simplification Milestone A already made for on-commit abilities; it means any
# rear-guard's snipeSupport always "fails to find a target" (hits snipeFailAdd if present) below.
# ══════════════════════════════════════════════════════════════════════════════════════════
LINK_GROUPS = rules._CAT["links"]   # {id: {name,icon,pow,members}}
LINK_POW_CAP = 4                     # index.html:7472
CALLED = rules._CAT["called"]        # {cardName: {text, add/oppadd/draw/chargeGain/... }}
# index.html:4213 -- MUSTER: +N power per 1-cost ally (rear-guards this duel + Winners Circle).
RALLY = {"Bannerlord Cassian": 5, "Ironsworn Vanguard": 3, "Warden of the Wall": 3, "Oathkeeper Sena": 3, "Shieldwall Recruit": 3}
# index.html:4214 -- a spent rear-guard becomes a Death Remnant instead of recycling to the deck.
LINGERING_SUPPORTS = ["Uso Oso", 'Ghorruk "Gnarly" Judarr', "Sister Mire", "Kiba", "Grave-Fed Ghoul", "Bone Choirmaster", "Gravecaller Voss", "Uso Oso's Skeletal Summons"]

def rg_slots(match_commits):
    """index.html:5328 RG_SLOTS(): 2 support slots normally, 3 from the 4th duel on."""
    return 3 if (match_commits or 0) >= 4 else 2

def shield(name):
    """index.html:5857 shield(): SHIELD_OVERRIDE[name] || max(2, 10-2*cost). SHIELD_OVERRIDE is
    confirmed EMPTY by design (0 entries) -- a per-card hand-tuning table with nothing in it yet."""
    return max(2, 10 - 2*rules.card_cost(name))

def card_link_groups(name):
    return [dict(g, id=gid) for gid, g in LINK_GROUPS.items() if name in g.get("members", [])]

def active_links(fighter_name, hand_names):
    """index.html:7488 activeLinks(): HAND-based Link -- fighter + a same-group ally still sitting
    in hand (not committed, not fielded as rear-guard). Fires every duel unconditionally, separate
    from field_link() below. This was a genuine Milestone A gap: it doesn't depend on rear-guard at
    all, so it should have shipped there -- fixed now that it surfaced during this deeper pass."""
    out = []
    for g in card_link_groups(fighter_name):
        partner = next((h for h in hand_names if h != fighter_name and h in g["members"]), None)
        if partner: out.append({"id": g["id"], "name": g["name"], "pow": g["pow"], "partner": partner})
    return out

def field_link(fighter_name, support_name):
    """index.html:6334 fieldLink(): REAR-GUARD-based Link -- fighter + a same-group support
    actually fielded this duel. Distinct mechanic from active_links() above, not a duplicate --
    same LINK_GROUPS table, two different membership checks (hand vs fielded)."""
    fg, sg = card_link_groups(fighter_name), card_link_groups(support_name)
    for f in fg:
        for s in sg:
            if f["id"] == s["id"]: return f
    return None

def field_bond(fighter_name, support_name, bonds):
    """index.html:6344 fieldBond(): the same Ascension-earned pairBonds/formation-tier system as
    best_formation(), just checked against ONE specific fielded rear-guard instead of scanned
    across the whole deck."""
    if not fighter_name or not support_name or fighter_name == support_name: return None
    count = bonds.get("|".join(sorted([fighter_name, support_name])), 0)
    t = formation_tier(count)
    return {"name": t[0], "bonus": t[1], "count": count} if t else None

def _project_called(e, ctx):
    """index.html:6003 projectCalled(): the pure power-math layer EVERY Called entry runs through
    (14 op-codes). Covers `add` alone in 83 of the 111 real entries -- by far the most common case."""
    dp = dop = 0
    mc = ctx.get("match_commits", 0)
    if e.get("add"): dp += e["add"]
    if e.get("oppadd"): dop += e["oppadd"]
    if e.get("add1st") and mc <= 1: dp += e["add1st"]
    if e.get("addLate") and mc >= 2: dp += e["addLate"]
    if e.get("addLate3") and mc >= 3: dp += e["addLate3"]
    if e.get("addIfLost") and ctx.get("last_result") == "lose": dp += e["addIfLost"]
    if e.get("addIfWon") and ctx.get("last_result") == "win": dp += e["addIfWon"]
    if e.get("addIfBehind") and ctx.get("wins", 0) < ctx.get("losses", 0): dp += e["addIfBehind"]
    if e.get("addIfAhead") and ctx.get("wins", 0) > ctx.get("losses", 0): dp += e["addIfAhead"]
    if e.get("addChaos") and ctx.get("chaos"): dp += e["addChaos"]
    if e.get("perHand"): dp += min(e.get("perHandCap", 99), e["perHand"] * ctx.get("hand_len", 0))
    if e.get("perOppDeath"): dp += e["perOppDeath"] * ctx.get("opp_deaths", 0)
    if e.get("perWC"): dp += min(e.get("perWCcap", 99), e["perWC"] * ctx.get("wc_len", 0))
    if e.get("perWin"): dp += e["perWin"] * ctx.get("wins", 0)
    return dp, dop

# Ops this pass implements, beyond _project_called's 14. Anything else on a fielded rear-guard's
# CALLED entry is named explicitly in the log (not silently dropped, not a crash -- see the
# apply_called docstring for why this differs from CARD_RULES' loud-raise-on-unknown-op pattern).
KNOWN_CALLED_EXTRA_OPS = {"energyCost", "chargeGain", "chargeGainIfWon", "chargeGainIfHandFull",
    "chargeGainIfVeteran", "draw", "drawIfRemnant", "banishOwn", "addPerHand", "addPerBanish",
    "bothBanish", "doubleShield", "twinBuff", "text",
    "add", "oppadd", "add1st", "addLate", "addLate3", "addIfLost", "addIfWon", "addIfBehind",
    "addIfAhead", "addChaos", "perHand", "perHandCap", "perOppDeath", "perWC", "perWCcap", "perWin"}

def apply_called(support_name, ctx, playerPow, oppPow, log, m, hand_ops):
    """index.html:6100 applyCalled(), player-side only (see the module docstring on why). Ops NOT
    yet ported here (recurBuff/recurPlain/scry/conjureTopToSupport/duplicateSelfToSupport/
    returnSelfToDeck/autoRemnantLowest/unbankNextWin/reclaimWC/spellDiscountGain/
    chargeGainIfLocked) are each individually rare (1-3 of 111 real entries) and need either
    interactive choice, rear-guard-slot-filling mid-resolution, or WC-reclaim/spell-economy hooks
    this pass doesn't build -- CARD_RULES' "raise loudly on any unknown op" doesn't fit here: that
    interpreter was already ~complete and stable, so an unknown op meant real drift. This one is
    being built for the first time against a 20+-op vocabulary; treating "not yet ported" as a
    crash would take down a match every time ANY of those dozen rarer ops appears on a fielded
    rear-guard, on day one. So: implement the common ops for real, and for anything else NAME it
    in the log (visible, not silently faked) rather than pretend the card did nothing at all."""
    e = CALLED.get(support_name)
    if not e:
        return playerPow, oppPow
    if "energyCost" in e:
        if m.get("charge", 0) < e["energyCost"]:
            log.append(f"📣 {support_name} called — not enough energy, support fizzles")
            return playerPow, oppPow
        m["charge"] -= e["energyCost"]
    dp, dop = _project_called(e, ctx)
    playerPow += dp; oppPow += dop
    cap = duel_energy_cap(m.get("matchCommits", 0))
    if e.get("chargeGain"): m["charge"] = min(cap, m.get("charge", 0) + e["chargeGain"])
    if e.get("chargeGainIfWon") and ctx.get("wins", 0) > 0: m["charge"] = min(cap, m.get("charge", 0) + e["chargeGainIfWon"])
    if e.get("chargeGainIfHandFull") and ctx.get("hand_len", 0) >= 4: m["charge"] = min(cap, m.get("charge", 0) + e["chargeGainIfHandFull"])
    if e.get("chargeGainIfVeteran") and ctx.get("match_commits", 0) >= 2: m["charge"] = min(cap, m.get("charge", 0) + e["chargeGainIfVeteran"])
    if e.get("draw"): hand_ops.append({"op": "draw", "n": e["draw"]})
    if e.get("drawIfRemnant") and m.get("deathRemnants"):
        hand_ops.append({"op": "draw", "n": 1}); log.append(f"☠ {support_name} — a Remnant stirs: draw a card")
    if e.get("banishOwn"):
        hand_ops.append({"op": "banish_random", "n": e["banishOwn"]}); log.append(f"☠ Banished {e['banishOwn']} from your hand — into the Order")
    if e.get("addPerHand"):
        bonus = ctx.get("hand_len", 0) * e["addPerHand"]
        if bonus: playerPow += bonus; log.append(f"🎴 {support_name}: +{bonus} ({ctx.get('hand_len',0)} in hand)")
    if e.get("addPerBanish"):
        bl = ctx.get("banish_len", 0); bonus = bl * e["addPerBanish"]
        if bonus: playerPow += bonus; log.append(f"🪶 {support_name}: +{bonus} ({bl} banished)")
    if e.get("bothBanish"):
        n = e["bothBanish"]; hand_ops.append({"op": "banish_random", "n": n}); oppPow -= 2*n
        log.append(f"☠ Both discard — you banish {n}, opponent −{2*n}")
    if e.get("doubleShield"):
        sv = shield(support_name)
        if sv: playerPow += sv; log.append(f"🛡️ {support_name} — Called doubles its own Shield: +{sv}")
    unknown = set(e.keys()) - KNOWN_CALLED_EXTRA_OPS
    if unknown:
        log.append(f"📣 {support_name} — Called effect partially supported server-side (not yet ported: {', '.join(sorted(unknown))})")
    log.append(f"📣 Called — {support_name}: {e.get('text','')}")
    return playerPow, oppPow

def new_match(deck_names, best_of=7, lobby_mode=False):
    # 8/5/26: dual match-length (Milestone A) -- Public/Draft is Best-of-7-win-4, Ranked is
    # Best-of-3-win-2 (was hardcoded >=4 forever, no way to run the Ranked format at all).
    win_threshold = (best_of + 1) // 2
    return {"deck": list(deck_names), "hand": list(deck_names[:4]), "winnersCircle": [],
            "playerScore": [0, 0], "lastResult": None, "matchCommits": 0, "skullchainKills": 0,
            "ragwingWins": 0, "deathRemnantPow": 0, "oppNextDebuff": 0,
            "glacialGuardUsed": False, "oppGuardUsed": False, "horrorRegenUsed": False,
            "untouchableUsed": False, "matchTraitPow": {}, "done": False, "log_last": [],
            "bonds": {}, "matchPlayed": set(), "banishPile": [], "charge": duel_energy_cap(0), "spellDiscount": 0,
            "spellOppPow": 0, "spellSelfPow": 0, "spellJam": False, "spellNullOpp": False,
            "spellHand": [], "spellShield": False, "deathRemnants": [],
            "bestOf": best_of, "winThreshold": win_threshold, "lobbyMode": lobby_mode}

def formation_tier(count):
    for n, name, bonus in FORMATION_TIERS:
        if count >= n: return (name, bonus)
    return None
def best_formation(card_name, deck_types, bonds):
    best = None
    for other in deck_types:
        if other == card_name: continue
        t = formation_tier(bonds.get("|".join(sorted([card_name, other])), 0))
        if t and (not best or t[1] > best[1]): best = (t[0], t[1], other)
    return best

def opponent_pool():
    return [n for n in CATALOG if n not in ("Bixie Bee", "Melanie")]

# ── DATA-DRIVEN ABILITY SPEC ──
# Each card -> ordered rules. A rule fires if its "if" condition holds, then applies one op:
#   add:N  addvar:var,x:mult  mult:N  set:var  oppadd:N  chargeGain:N.  Conditions compare context vars.
RULES = rules._CAT["rules"]   # canonical rules from catalog.json
SPELLS = json.load(open(os.path.join(os.path.dirname(__file__), "spells.json"), encoding="utf-8"))
SPELL_IDS = [s["id"] for s in SPELLS]

def _ctx(pc, oc, m, rec, cond_id):
    # 8/5/26: banish_len/rear_count/remnant_count/hand_banished are honest 0s -- no real rear-guard/
    # Called/banish-pile state exists server-side yet (Milestone B). Not faked; will wire for free
    # once that state exists, same reasoning as everywhere else in this file.
    return {"opp_deaths":oc["deaths"],"opp_kills":oc["kills"],"pc_kills":rec["k"],"pc_deaths":rec["d"],
            "opp_pow":oc["pow"],"pc_pow":pc["pow"],"last_result":m["lastResult"],"match_commits":m["matchCommits"],
            "player_wins":m["playerScore"][0],"player_losses":m["playerScore"][1],"hand_len":len(m["hand"]),
            # 8/15/26: the Deck Master tables exported from the client use the short forms `wins`/
            # `losses` where CARD_RULES uses player_wins/player_losses. Same numbers, two names in
            # the source data -- aliased here rather than rewriting the exported rules, so a
            # re-export from the client cannot silently break them again.
            "wins":m["playerScore"][0],"losses":m["playerScore"][1],
            "wc_len":len(m["winnersCircle"]),"skullchain":m["skullchainKills"],"ragwing":m["ragwingWins"],
            "banish_len":len(m.get("banishPile") or []),
            "rear_count":0, "remnant_count":len(m.get("deathRemnants") or []), "hand_banished":0,
            "chaos":cond_id in CHAOS_CONDS,"wc_names":[c["name"] for c in m["winnersCircle"]]}
def _cmp(a, op, b):
    if op == "==": return a == b
    if op == "!=": return a != b
    if a is None or b is None: return False   # ordering vs None -> False (matches the client's JS leniency)
    if op == ">":  return a > b
    if op == "<":  return a < b
    if op == ">=": return a >= b
    if op == "<=": return a <= b
    return False
def eval_cond(cond, ctx):
    if cond is None: return True
    if "or" in cond:  return any(eval_cond(c, ctx) for c in cond["or"])
    if "and" in cond: return all(eval_cond(c, ctx) for c in cond["and"])
    if "chaos" in cond:  return ctx["chaos"] == cond["chaos"]
    if "wc_has" in cond: return cond["wc_has"] in ctx["wc_names"]
    rhs = cond["n"] if "n" in cond else cond["s"] if "s" in cond else ctx[cond["v2"]]
    return _cmp(ctx[cond["v"]], cond["op"], rhs)
# 8/5/26: op-code whitelist, versioned + loud-failure -- the actual anti-drift mechanism for the
# interpreter itself. A silent skip on an unrecognized key is exactly how chargeGain drifted
# unnoticed once already; raising here means a third undetected drift is now impossible.
RULES_SCHEMA_VERSION = 1
KNOWN_RULE_OPS = {"add", "addvar", "mult", "set", "oppadd", "chargeGain"}

def duel_energy_cap(match_commits):
    """Exact server-side mirror of the client's duelEnergyCap(): d=matchCommits+1; d<=4 ? d+2 : 2d-2."""
    d = (match_commits or 0) + 1
    return d + 2 if d <= 4 else 2*d - 2

def energy_regen_per_turn(match_commits):
    """Exact mirror of the client's energyRegenPerTurn(): d=matchCommits+1; d<5 -> 1, else
    max(2, round(duelEnergyCap()/3)). Was a flat +1 forever server-side -- correct through duel 4,
    silently under-regenerating every turn after (the client ramps regen alongside the rising cap;
    a flat 1 falls further behind the cap every turn past the 4th)."""
    d = (match_commits or 0) + 1
    if d < 5: return 1
    return max(2, round(duel_energy_cap(match_commits) / 3))

# ── DECK MASTER (8/15/26, owner: "deck master abilities need to work, it's integral") ──────────
# PvP had no deck-master concept at all: the client never sent one and the server never modelled
# one, so every online duel resolved as if nobody had a Deck Master. These tables are exported from
# the client's own DM_EXCLUSIVE / DM_VANILLA_OVERRIDE / ARCHETYPE_VANILLA / ARCHETYPE_MEMBERS by
# sync_dm_rules.py, and use the SAME rule schema as CARD_RULES, so the interpreter below is the
# existing one rather than a second dialect that could drift from it.
#
# Resolution order mirrors the client (applyDeckMasterResolveEffects): a named per-card exclusive
# wins outright; otherwise a per-card vanilla override; otherwise the shared rule for the
# archetype the DM belongs to. Only one tier ever fires.
_DM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dm_rules.json")
try:
    with open(_DM_PATH, encoding="utf-8") as _f: _DM = json.load(_f)
except Exception:
    _DM = {"DM_EXCLUSIVE": {}, "DM_VANILLA_OVERRIDE": {}, "ARCHETYPE_VANILLA": {}, "ARCHETYPE_MEMBERS": {}}
DM_EXCLUSIVE        = _DM.get("DM_EXCLUSIVE", {})
DM_VANILLA_OVERRIDE = _DM.get("DM_VANILLA_OVERRIDE", {})
ARCHETYPE_VANILLA   = _DM.get("ARCHETYPE_VANILLA", {})
ARCHETYPE_MEMBERS   = _DM.get("ARCHETYPE_MEMBERS", {})

def dm_archetype_of(dm_name):
    """Which archetype a Deck Master belongs to, for the shared-rule tier."""
    for arch, members in ARCHETYPE_MEMBERS.items():
        if dm_name in members: return arch
    return None

def dm_rules_for(dm_name, pc_name):
    """The one rule list that applies, in the client's own precedence order."""
    if not dm_name: return []
    if dm_name in DM_EXCLUSIVE: return DM_EXCLUSIVE[dm_name]
    if pc_name in DM_VANILLA_OVERRIDE: return DM_VANILLA_OVERRIDE[pc_name]
    arch = dm_archetype_of(dm_name)
    return ARCHETYPE_VANILLA.get(arch, []) if arch else []

def apply_deck_master(dm_name, pc_name, ctx, playerPow, oppPow, log, m=None, hand_ops=None, pc=None):
    """Same interpreter as CARD_RULES. Ops this build cannot evaluate server-side (raiseRemnant and
    friends, which need board state PvP does not track) are SKIPPED rather than raised on, so an
    unsupported DM degrades to no bonus instead of failing the whole duel — and is reported."""
    rules = dm_rules_for(dm_name, pc_name)
    skipped = []
    # `behind` is the only ctx key the DM tables want that _ctx cannot precompute: it is a live
    # comparison of the two powers AS THEY STAND at this point in resolution, not a match-level
    # stat, so it is layered on here rather than baked into _ctx where it would be stale.
    ctx = dict(ctx); ctx["behind"] = max(0, oppPow - playerPow)
    for rule in rules:
        # A rule whose condition references context this build does not compute must be SKIPPED, not
        # fatal. eval_cond raises KeyError on an unknown ctx key, and a Deck Master is chosen long
        # before a duel starts -- letting that kill resolve() would take the whole match down over a
        # cosmetic bonus. Reported through `skipped` so it surfaces in the log instead of vanishing.
        try:
            if not eval_cond(rule.get("if"), ctx): continue
        except KeyError as ex:
            skipped.append(["ctx:" + str(ex).strip("'")]); continue
        # Ops this evaluator handles = the shared CARD_RULES set PLUS the three the Deck Master
        # tables use that CARD_RULES never needed. The guard has to know about them or it rejects
        # them before the branches below ever run -- which is exactly what it did on first write,
        # silently no-opping every draw and every raised Remnant while reporting success.
        ops = set(rule.keys()) - {"if", "log", "x"}
        handled = KNOWN_RULE_OPS | {"draw", "raiseRemnant", "deathLingerBuffOverride"}
        if not ops or not ops.issubset(handled):
            skipped.append(sorted(ops - handled) or ["(empty)"])
            continue
        if "add" in rule: playerPow += rule["add"]
        elif "addvar" in rule: playerPow += ctx.get(rule["addvar"], 0) * rule.get("x", 1)
        elif "mult" in rule: playerPow = int(playerPow * rule["mult"])
        elif "set" in rule: playerPow = ctx.get(rule["set"], playerPow)
        elif "oppadd" in rule: oppPow += rule["oppadd"]
        # draw: emitted as a hand_op, the same instruction channel apply_called already uses, so the
        # caller (pvp.py / app.py) performs the real deck->hand move and the engine stays pure.
        elif "draw" in rule:
            if hand_ops is None: skipped.append(["draw(no hand_ops)"]); continue
            hand_ops.append({"op": "draw", "n": rule["draw"]})
        # raiseRemnant: the server DOES model Death Remnants (m["deathRemnants"]), so this raises one
        # the same way a natural Death Remnant is raised at the bottom of resolve() -- same shape,
        # same REMNANT_POW lookup, so it disperses on a win with the rest of them.
        elif "raiseRemnant" in rule:
            if m is None or pc is None: skipped.append(["raiseRemnant(no match state)"]); continue
            rp = pc["pow"] if rule["raiseRemnant"] == "self_pow" else rules.REMNANT_POW.get(pc["name"], pc["pow"])
            m.setdefault("deathRemnants", []).append({"name": pc["name"], "pow": rp})
        # deathLingerBuffOverride is a modifier on how long a raised Remnant lingers. The server has
        # no per-remnant lifetime -- they disperse wholesale on a win -- so there is nothing to
        # override. Recorded rather than pretended.
        elif "deathLingerBuffOverride" in rule:
            skipped.append(["deathLingerBuffOverride(no per-remnant lifetime)"]); continue
        else: continue
        if rule.get("log"): log.append(rule["log"])
    return playerPow, oppPow, skipped

def _apply_rules(name, ctx, playerPow, oppPow, log, m=None):
    for rule in RULES.get(name, []):
        if not eval_cond(rule.get("if"), ctx): continue
        unknown = set(rule.keys()) - KNOWN_RULE_OPS - {"if", "log", "x"}
        if unknown:
            raise ValueError(f"CARD_RULES[{name!r}] has op-code(s) {unknown} this interpreter (schema v{RULES_SCHEMA_VERSION}) doesn't know -- extend KNOWN_RULE_OPS + _apply_rules, bump RULES_SCHEMA_VERSION, before this card can resolve server-side.")
        if "add" in rule: playerPow += rule["add"]
        elif "addvar" in rule: playerPow += ctx[rule["addvar"]] * rule.get("x", 1)
        elif "mult" in rule: playerPow *= rule["mult"]
        elif "set" in rule: playerPow = ctx[rule["set"]]
        elif "oppadd" in rule: oppPow += rule["oppadd"]
        elif "chargeGain" in rule and m is not None:
            m["charge"] = min(duel_energy_cap(m.get("matchCommits", 0)), m.get("charge", 0) + rule["chargeGain"])
        if rule.get("log"): log.append(rule["log"])
    return playerPow, oppPow

# ── the faithful resolve() port ──
def resolve(m, pc, oc, cond_id, committed_pow=None, pc_record=None, rear_guards=None,
            opp_pow_override=None, forced_outcome=None, deck_master=None):
    """pc, oc: card dicts. pc_record: the player card's live DB record {k,d,ok,od} (drives traits +
    the pc.kills used by conditions). rear_guards: list of card dicts staged alongside pc this duel
    (Milestone B — RG_SLOTS()-capped, validated by the caller). Returns dict with outcome/powers/
    log/destination/hand_ops/rear_guard_fates; mutates match state m. `destination` (winners_circle|
    hand|deck_bottom) and `draw_self`/`hand_ops` tell the caller (app.py, which owns the real
    uid-keyed hand/deck lists) what list-moves to perform.

    8/6/26 Phase 5.1 — the two PvP hooks. This function is structurally one-sided: it owns ONE
    player's match state and treats `oc` as a bare card with no state of its own, which is correct
    for the bot but not for a real opponent who has their own Charge, rear-guards and Remnants.
    Rather than fork a parallel two-sided resolver (and re-introduce exactly the drift this whole
    resync existed to kill), PvP runs this same function once per side and joins the two with:
      opp_pow_override — force `oppPow` to the value the OTHER side's own pass computed, so each
        player's power is derived from their own complete state and the comparison is symmetric.
      forced_outcome   — overwrite the outcome after the resolution guards have run. Guards only
        ever convert a loss into a tie, never into a win, so when the two passes disagree (A wins
        while B's Last Stand ties) the tie is the truthful joint result; pvp.py reconciles and
        replays with this set. Applied AFTER the guards on purpose: the guards must still fire
        naturally so their once-per-match flags are spent by the side they actually saved."""
    rear_guards = rear_guards or []
    hand_ops = []
    playerPow = committed_pow if committed_pow is not None else pc["pow"]
    oppPow = oc["pow"]
    log = []
    rec = pc_record or {"k": pc["kills"], "d": pc["deaths"], "ok": 0, "od": 0}
    pcK, pcD = rec["k"], rec["d"]                    # player card's live record
    ocK, ocD = oc["kills"], oc["deaths"]              # opponent card's record
    wc = m["winnersCircle"]

    # 8/5/26 Milestone B: conjuring spends Charge equal to the fighter's own cost (index.html:6855,
    # `charge=Math.max(0,charge-conjureCost(pc))`) -- a genuine Milestone A miss, found while
    # re-deriving the exact client pipeline order for the rear-guard stage below. Without this,
    # Charge only ever goes UP from normal play, which makes the whole resource meaningless.
    m["charge"] = max(0, m.get("charge", 0) - rules.card_cost(pc["name"]))

    # ── ENERGY SPELL EFFECTS (armed by the client Charge system; inert unless set) ──
    if m.get("spellJam"): cond_id = "jammed"; log.append("📡 Jammer: active condition negated")
    if m.get("spellOppPow"): oppPow += m["spellOppPow"]; log.append(f"⚡ Interrupt: opponent {m['spellOppPow']} power")
    if m.get("spellSelfPow"): playerPow += m["spellSelfPow"]; log.append(f"⚡ Amplify: +{m['spellSelfPow']} power")

    abilityLocked = (cond_id == "abilitylock")
    if abilityLocked: log.append("⚡ Ability Lock — all card effects suppressed")
    # 8/5/26: fixed stale hardcoded name -- client renamed this card 'Ourevos, the Golden Dragon'
    # (task #166); server still checked the old 'Akatosh, the Golden Dragon', a dead guard nobody
    # had noticed silently never firing.
    akatoshUnmakes = (pc["name"] == "Ourevos, the Golden Dragon") and not abilityLocked
    if akatoshUnmakes: log.append("🐉 Ourevos unmakes the arena — the active condition takes no effect this duel.")

    if m["oppNextDebuff"]:
        oppPow += m["oppNextDebuff"]; log.append(f"🧬 Darwin's Curse: opponent {m['oppNextDebuff']} power"); m["oppNextDebuff"] = 0

    # ── ON-COMMIT ABILITIES (both fighters — client fires both, index.html:8568-8584) ──
    if not abilityLocked:
        n = pc["name"]
        if n == "Conduit Adept": m["charge"] = min(duel_energy_cap(m.get("matchCommits", 0)), m.get("charge", 0) + 1); log.append("⚡ Conduit Adept: +1 Charge")
        if n == "Voltcaller": m["spellDiscount"] = m.get("spellDiscount", 0) + 2; log.append("⚡ Voltcaller: next Interrupt −2")
        ctx = _ctx(pc, oc, m, rec, cond_id)
        if n == "Veronica":
            if oc.get("abil"):
                log.append(f"🔄 Veronica copies {oc['name']}")
                playerPow, oppPow = _apply_rules(oc["name"], ctx, playerPow, oppPow, log, m)
            else:
                log.append("🔄 Veronica: opponent has no ability")
        else:
            playerPow, oppPow = _apply_rules(n, ctx, playerPow, oppPow, log, m)

        # Deck Master fires after the fighter's own rules, same order as the client's
        # applyDeckMasterResolveEffects. Skipped op-codes are surfaced in the duel log rather than
        # silently dropping the bonus -- a DM that cannot resolve server-side should be visible.
        if deck_master:
            playerPow, oppPow, _dm_skipped = apply_deck_master(deck_master, n, ctx, playerPow, oppPow, log, m, hand_ops, pc)
            if _dm_skipped:
                log.append(f"\u2605 {deck_master}: part of this Deck Master's ability needs board state "
                           f"online play doesn't track yet ({', '.join(sorted({o for g in _dm_skipped for o in g}))}) \u2014 not applied")

        # 8/5/26 Milestone A: opponent's OWN on-commit ability now fires too (client fires BOTH
        # fighters' CARD_RULES every duel; engine.py only ever fired the player's side, leaving any
        # opponent card with a self-buff/debuff CARD_RULES entry — 99 real entries exist across the
        # catalog — silently inert server-side, a systematic opponent-underpower bug). Bot-only
        # stat fields the client reads from its own persistent bot-hand/WC/banish/deck simulation
        # have no server equivalent (the server's opponent is a fresh random card per duel, not a
        # persistent bot session — see opponent_pool()) and honestly default to 0/False, same
        # pattern as the player's own rear_count/remnant_count above. m=None on this call:
        # chargeGain in an opponent card's rules has no server-side opponent-charge target to add
        # to, so it silently no-ops rather than incorrectly crediting the PLAYER's own charge.
        if oc.get("name") and RULES.get(oc["name"]):
            octx = {"opp_deaths": pcD, "opp_kills": pcK, "pc_kills": ocK, "pc_deaths": ocD,
                    "opp_pow": pc["pow"], "pc_pow": oc["pow"],
                    "last_result": {"win": "lose", "lose": "win"}.get(m["lastResult"], m["lastResult"]),
                    "match_commits": m["matchCommits"], "player_wins": m["playerScore"][1], "player_losses": m["playerScore"][0],
                    "hand_len": 0, "wc_len": 0, "skullchain": 0, "ragwing": 0,
                    "banish_len": 0, "rear_count": 0, "remnant_count": 0, "hand_banished": 0,
                    "chaos": cond_id in CHAOS_CONDS, "wc_names": []}
            oppPow, playerPow = _apply_rules(oc["name"], octx, oppPow, playerPow, log, None)

    # ── REAR-GUARD (Milestone B): Called + Shield + Link + Bond per staged support, then Muster.
    # Exact client stage position (index.html:8586-8619) — AFTER on-commit abilities, BEFORE Living
    # Traits, so a card with a `mult`/`set` CARD_RULES op (Ruffius Rufeldro / Malia / Mirror Shade —
    # rare, but real) sees the same accumulated total the client does. No opposing rear-guard exists
    # (see the module-level Milestone B docstring), so snipeSupport always "fails to find a target".
    rear_guard_fates = []
    if pc["name"] != "Kaelthar the Ascendant":
        rgc = {"match_commits": m["matchCommits"], "last_result": m["lastResult"], "hand_len": len(m["hand"]),
               "opp_deaths": ocD, "opp_kills": ocK, "wins": m["playerScore"][0], "losses": m["playerScore"][1],
               "wc_len": len(wc), "chaos": cond_id in CHAOS_CONDS, "banish_len": len(m.get("banishPile") or [])}
        for rg in rear_guards:
            kc = CALLED.get(rg["name"])
            if kc and kc.get("snipeSupport") and kc.get("snipeFailAdd"):
                playerPow += kc["snipeFailAdd"]; log.append(f"🎯 {rg['name']}: no opposing support to snipe — +{kc['snipeFailAdd']} instead")
            playerPow, oppPow = apply_called(rg["name"], rgc, playerPow, oppPow, log, m, hand_ops)
            sv = shield(rg["name"])
            if sv: playerPow += sv; log.append(f"🛡️ {rg['name']} called — +{sv} (Shield)")
            lk = field_link(pc["name"], rg["name"])
            if lk:
                playerPow += lk["pow"]; log.append(f"🔗 {lk['name']} Link — {pc['name']} + {rg['name']}: +{lk['pow']}")
                tb = (CALLED.get(rg["name"]) or {}).get("twinBuff", 0)
                if tb: playerPow += tb; log.append(f"🐺 {rg['name']} rallies the twins — {pc['name']} +{tb}")
            bd = field_bond(pc["name"], rg["name"], m.get("bonds", {}))
            if bd: playerPow += bd["bonus"]; log.append(f"🤝 {bd['name']} Bond — {pc['name']} + {rg['name']}: +{bd['bonus']} ({bd['count']} fought together)")
        if pc["name"] in RALLY:
            allies = len([rg for rg in rear_guards if rules.card_cost(rg["name"]) == 1]) + len([c for c in wc if rules.card_cost(c["name"]) == 1])
            bonus = RALLY[pc["name"]] * allies
            if bonus > 0: playerPow += bonus; log.append(f"🤝 Muster — {pc['name']}: +{bonus} ({allies} one-cost all{'y' if allies==1 else 'ies'} × {RALLY[pc['name']]})")
    elif rear_guards:
        log.append("🐉 Kaelthar the Ascendant fights alone — support effects don't apply this duel")

    # ── LIVING-CARD TRAITS — ONE conditional trait per card (fires only in-context; mirrors client).
    # Moved here (was before on-commit abilities in the initial Milestone A port) to match the
    # client's real order once the rear-guard stage between them made the gap concrete. ──
    _tctx = {"wins": m["playerScore"][0], "losses": m["playerScore"][1], "lastLose": (m["lastResult"] == "lose"),
             "oppDeaths": oc["deaths"], "oppKills": oc["kills"], "myKills": pc.get("kills", 0)}
    at = rules.active_trait(rec, pc.get("equippedTrait"), _tctx)
    bloodthirsty = False; untouchable = False
    if at and at.get("active"):
        if at["pow"]:                        playerPow += at["pow"]; log.append(f"🎖 {at['id'].capitalize()}: +{at['pow']} power")
        elif at["id"] == "feared":           oppPow -= 1; log.append("😤 Feared: opponent −1 power")
        elif at["id"] == "untouchable":      untouchable = True; log.append("🛡 Untouchable: first loss becomes a tie")
        elif at["id"] == "bloodthirsty":     bloodthirsty = True; log.append("⚔️ Bloodthirsty: +1 power per win this match")
    elif at:                                 log.append(f"🎖 {at['id'].capitalize()} — dormant")
    key = pc.get("uid") or pc["name"]
    if bloodthirsty and m["matchTraitPow"].get(key): playerPow += m["matchTraitPow"][key]; log.append(f"⚔️ Bloodthirsty momentum: +{m['matchTraitPow'][key]}")
    m["matchPlayed"].add(pc["name"])
    bf = best_formation(pc["name"], m.get("deck", []), m.get("bonds", {}))
    if bf: playerPow += bf[1]; log.append(f"🤝 {bf[0]} with {bf[2]}: +{bf[1]}")
    # 8/5/26 Milestone B: activeLinks() -- HAND-based Link (fighter + a same-group ally still in
    # hand), unconditional, no rear-guard dependency at all. A genuine Milestone A gap: this should
    # have shipped there since it doesn't need anything rear-guard-specific; fixed now.
    _lp = 0
    for l in active_links(pc["name"], m["hand"]):
        if _lp >= LINK_POW_CAP: break
        add = min(l["pow"], LINK_POW_CAP - _lp)
        if add > 0: playerPow += add; _lp += add; log.append(f"🔗 {l['name']} (with {l['partner']}): +{add}")

    # ── APPLY CONDITION — all 26 power/tiebreak conditions (the other 6 — noretreat/openbook/
    # reinforce/dredge/wildpit's lock/abilitylock — don't touch power; see condition_reveal_effects
    # and the abilityLocked gate above) ──
    if not akatoshUnmakes:
        if cond_id == "veteranedge":
            cap = CONDITION_VETERAN_CAP
            if (pc["pow"] or 0) < (oc["pow"] or 0):
                v = min(cap, (pcK or 0)//5); playerPow += v
                log.append(f"🎖️ Veteran's Edge: your weaker card +{v}" + (", capped" if v >= cap else ""))
            elif (oc["pow"] or 0) < (pc["pow"] or 0):
                v = min(cap, (ocK or 0)//5); oppPow += v
                log.append(f"🎖️ Veteran's Edge: their weaker card +{v}" + (", capped" if v >= cap else ""))
            else: log.append("🎖️ Veteran's Edge: equal base power — no edge")
        elif cond_id == "freshblood":
            if (pcK or 0) == 0: playerPow += 10
            if (ocK or 0) == 0: oppPow += 10
            log.append("🌱 Fresh Blood: unproven cards (0 kills) +10")
        elif cond_id == "puritytrial":
            if (pcD or 0) == 0 and (pcK or 0) >= 1: playerPow += 5
            if (ocD or 0) == 0 and (ocK or 0) >= 1: oppPow += 5
            log.append("✨ Purity Trial: Pristine (0 deaths, 1+ kill) +5")
        elif cond_id == "puritydrain":
            if (pcD or 0) == 0 and (pcK or 0) >= 1: playerPow = max(1, playerPow-5)
            if (ocD or 0) == 0 and (ocK or 0) >= 1: oppPow = max(1, oppPow-5)
            log.append("🕷️ Purity Drain: Pristine cards are hunted −5")
        elif cond_id == "bloodreckoning":
            playerPow = max(1, playerPow - (pcD or 0)//2); oppPow = max(1, oppPow - (ocD or 0)//2)
            log.append("💀 Blood Reckoning: −1 power per 2 deaths on record")
        elif cond_id == "deathwish":
            dw1 = min(CONDITION_VETERAN_CAP, pcD or 0); dw2 = min(CONDITION_VETERAN_CAP, ocD or 0); playerPow += dw1; oppPow += dw2
            log.append(f"☠️ Deathwish: scars fuel fury — you +{dw1}, opp +{dw2}")
        elif cond_id == "underdog":
            if (pc["pow"] or 0) < (oc["pow"] or 0): playerPow += 3
            elif (oc["pow"] or 0) < (pc["pow"] or 0): oppPow += 3
            log.append("📉 Underdog Rising: the weaker base power +3")
        elif cond_id == "rarityreckoning":
            rp, ro = rules.RARITY_ORDER.get(pc["rarity"], 4), rules.RARITY_ORDER.get(oc["rarity"], 4)
            if rp < ro: playerPow += 3
            elif ro < rp: oppPow += 3
            log.append("💎 Rarity Reckoning: the rarer card +3")
        elif cond_id == "commonsrevolt":
            rp, ro = rules.RARITY_ORDER.get(pc["rarity"], 4), rules.RARITY_ORDER.get(oc["rarity"], 4)
            if rp > ro: playerPow += 5
            elif ro > rp: oppPow += 5
            log.append("✊ Commons' Revolt: the lower rarity +5")
        elif cond_id == "giantslayer":
            if abs((pc["pow"] or 0) - (oc["pow"] or 0)) >= 10:
                if (pc["pow"] or 0) < (oc["pow"] or 0): playerPow = oppPow + 1; log.append("🗡️ Giant Slayer: your underdog fells the giant")
                else: oppPow = playerPow + 1; log.append("🗡️ Giant Slayer: their underdog fells the giant")
            else: log.append("🗡️ Giant Slayer: no giant to slay (gap < 10)")
        elif cond_id == "highroller":
            a, b = 5 + random.randint(0, 5), 5 + random.randint(0, 5)
            playerPow += a; oppPow += b; log.append(f"🎲 High Roller: +{a} you, +{b} opponent")
        elif cond_id == "momentumtide":
            if m["playerScore"][0] < m["playerScore"][1]: playerPow += 3; log.append("🌊 Momentum's Tide: you are behind — +3")
            elif m["playerScore"][1] < m["playerScore"][0]: oppPow += 3; log.append("🌊 Momentum's Tide: opponent behind — +3")
            else: log.append("🌊 Momentum's Tide: even match — no swing")
        elif cond_id == "eldersreach":
            er1 = min(CONDITION_VETERAN_CAP, ((pcK or 0)+(pcD or 0))//4); er2 = min(CONDITION_VETERAN_CAP, ((ocK or 0)+(ocD or 0))//4)
            playerPow += er1; oppPow += er2; log.append(f"📜 Elder's Reach: +1 power per 4 duels fought (you +{er1}, opp +{er2})")
        elif cond_id == "doubleedged":
            playerPow += 5; oppPow += 5; log.append("⚔️ Twin Surge: both conjured units +5 power")
        elif cond_id == "legendsclash":
            playerPow = max(1, playerPow + (2 if pc["rarity"] == "apex" else -2))
            oppPow = max(1, oppPow + (2 if oc["rarity"] == "apex" else -2))
            log.append("👑 Legends' Clash: Apex +2, all others −2")
        elif cond_id == "woundedbeast":
            if (pcD or 0) >= 3: playerPow += 2
            if (ocD or 0) >= 3: oppPow += 2
            log.append("🐺 Wounded Beast: 3+ deaths veterans +2")
        elif cond_id == "survivorsground":
            if (pcD or 0) < (ocD or 0): playerPow += 3
            elif (ocD or 0) < (pcD or 0): oppPow += 3
            log.append("⚰️ Survivor's Ground: fewer deaths +3")
        elif cond_id == "purereflection":
            playerPow = rules.card_cost(pc["name"]) * 10; oppPow = rules.card_cost(oc["name"]) * 10
            log.append(f"🪞 Pure Reflection: power becomes Charge cost ×10 (you {playerPow} vs opp {oppPow})")
        elif cond_id == "bloodlinesclash":
            # 8/5/26: uses the card's OWN camp only -- client's effectiveCampOf() lets a set Deck
            # Master's camp override the committed card's own (index.html:5412-5419), but the
            # server has no Deck-Master-identity concept for the current match at all yet
            # (Deck-Master-tier resolve effects are the same gap — Milestone B). Simplification is
            # honest and narrow: only matters for a match with a Deck Master set, and only changes
            # which side of THIS one condition's +6 fires, not whether it fires.
            campP, campO = rules.camp_of(pc["name"]), rules.camp_of(oc["name"])
            if campP != campO and rules.camp_beats(campP, campO): playerPow += 6; log.append(f"🔱 Bloodlines Clash: {campP} overwhelms {campO} — +6")
            elif campP != campO and rules.camp_beats(campO, campP): oppPow += 6; log.append(f"🔱 Bloodlines Clash: {campO} overwhelms {campP} — +6")
            else: log.append(f"🔱 Bloodlines Clash: same camp ({campP}) — no swing")
        elif cond_id == "lowest":
            playerPow, oppPow = -playerPow, -oppPow
        elif cond_id == "surge":
            if random.random() > 0.5: playerPow += 6; log.append("🌪️ Surge: +6 you")
            else: oppPow += 6; log.append("🌪️ Surge: +6 opponent")
        elif cond_id == "mirror":
            playerPow, oppPow = oc["pow"], pc["pow"]; log.append("🔄 Mirror")
        elif cond_id == "forceswap":
            if m["hand"]: sw = card(random.choice(m["hand"])); playerPow = sw["pow"]; log.append(f"🎲 Force Swap: → {sw['name']}")
            oppPow = card(random.choice(opponent_pool()))["pow"]; log.append("🎲 Force Swap: opp swapped")
        elif cond_id == "wildpit":
            log.append("🎲 Wild Pit: support zones stayed locked all duel — pure fighter power stands")
        elif cond_id == "provingground":
            if pc["pow"] > oc["pow"]: playerPow = max(1, playerPow-5); log.append("⛰️ Proving Ground: you −5")
            elif oc["pow"] > pc["pow"]: oppPow = max(1, oppPow-5); log.append("⛰️ Proving Ground: opp −5")
            else: log.append("⛰️ Proving Ground: evenly matched — no penalty")
        elif cond_id == "hollowreckoning":
            if (pc["pow"] or 0) < pcK: playerPow = pcK; log.append(f"🌫️ Hollow Reckoning: your power → career kills ({pcK})")
            if (oc["pow"] or 0) < ocK: oppPow = ocK; log.append(f"🌫️ Hollow Reckoning: opponent power → career kills ({ocK})")
            if (pc["pow"] or 0) >= pcK and (oc["pow"] or 0) >= ocK: log.append("🌫️ Hollow Reckoning: both already outpace their kills — no swing")

    # ── DETERMINE WINNER ──
    # PvP: the opponent is a real player whose power was computed by their own pass over their own
    # state. Substitute it here — after every opponent-ability adjustment above, before the compare.
    if opp_pow_override is not None: oppPow = opp_pow_override
    if playerPow > oppPow: won = "win"
    elif playerPow < oppPow: won = "lose"
    else: won = "tie"
    if won == "tie" and cond_id == "recordties" and not akatoshUnmakes:
        if pcK > ocK: won = "win"; log.append("💀 Record Breaks Ties: win")
        elif pcK < ocK: won = "lose"; log.append("💀 Record Breaks Ties: lose")
        else: log.append("💀 Record Breaks Ties: kills equal — true tie")

    # ── RESOLUTION GUARDS (exact client order, index.html:8738-8799) ──
    forced_tie = False
    # Ahdor Record Guard: block loss, force tie, return to hand (once per match). The client also
    # grants +3 pow to 1-2 OTHER random hand cards -- deferred: the server's hand is a bare
    # {uid,type} list with no per-instance power-modifier slot (power is always looked up fresh
    # from CATALOG), so "a specific hand card is permanently +3 for the rest of this match" has
    # nowhere to live yet. That's real new plumbing (a temp-bonus field threaded through hand
    # storage + wherever a hand card's pow gets resolved at commit), not a one-line port -- the
    # guard's CORE behavior (survive the loss, tie, return to hand) is faithfully ported below;
    # only the bonus-power flourish is scoped out.
    if won == "lose" and pc["name"] == "Ahdorah Khaan, Determined Soul" and not m["glacialGuardUsed"]:
        m["glacialGuardUsed"] = True; forced_tie = True; won = "tie"
        log.append("🛡 Record Guard: death blocked — Ahdor returns to hand (guard spent; +3 hand-card bonus not yet modeled server-side)")
    # Opponent Record Guard — any opposing card with "record guard" ability text ties instead of losing (once per match)
    if won == "win" and not m["oppGuardUsed"] and not m.get("spellNullOpp") and "record guard" in (oc.get("abil", "") or "").lower():
        m["oppGuardUsed"] = True; won = "tie"
        log.append(f"🛡 {oc['name']} Record Guard: tied")
    # Last Stand: text-pattern match, NOT a hardcoded single name -- was hardcoded to literal
    # name=='Hanse Waltz' server-side. Verified against the live catalog (not the client's own
    # stale code-comment, which names 2 cards that no longer exist under those names): the real
    # current carriers are Bram the Bulwark, Hanse Waltz (base printing), and Oathbound Shield.
    # "The Bronzed Beast, Hanse Waltz" (the transformed variant) does NOT carry this text anymore
    # -- it has its own distinct Blood Moon ability, handled separately in the destination logic below.
    if won == "lose" and "last stand" in (pc.get("abil", "") or "").lower():
        if abs(abs(playerPow) - abs(oppPow)) <= 3:   # faithful to the client's own abs(x)-abs(y) margin, not a plain diff
            won = "tie"; log.append("🌙 Last Stand: lost by ≤3 — duel tied, no death recorded")
    # The Regenerating Horror — regrows the first time it would lose (once per match)
    if won == "lose" and pc["name"] == "The Regenerating Horror" and not m["horrorRegenUsed"]:
        m["horrorRegenUsed"] = True; forced_tie = True; won = "tie"
        log.append("👁 Regeneration: severed and regrown — duel tied, no death, returns to your hand (spent this match)")
    # Untouchable trait — a flawless record refuses the first loss (once per match)
    if won == "lose" and untouchable and not m["untouchableUsed"]:
        m["untouchableUsed"] = True; forced_tie = True; won = "tie"
        log.append("🛡 Untouchable: a flawless record refuses this loss — duel tied, returns to hand (once per match)")
    if won == "lose" and m.get("spellShield"):
        forced_tie = True; won = "tie"; log.append("🛡 Ledger Ward: death negated — no loss written")
    # Uso Oso's Bulwark of Bones — 3+ Death Remnants held denies the loss (Milestone A: Death
    # Remnants are fighter-level, not rear-guard-dependent, so this fires correctly here already)
    if won == "lose" and pc["name"] == "Uso Oso" and len(m.get("deathRemnants") or []) >= 3:
        forced_tie = True; won = "tie"; log.append("🦴 The Bulwark of Bones: 3+ Remnants held — the loss is denied, duel ties instead")

    # PvP reconciliation (see docstring). Deliberately placed after every guard so their
    # once-per-match flags are already spent, and before the Remnant/destination/state blocks so
    # every downstream consequence follows the joint outcome rather than this side's local view.
    if forced_outcome is not None and forced_outcome != won:
        if won == "win": log.append("🤝 the opposing card survived the clash — duel tied")
        won = forced_outcome
        if won == "tie": forced_tie = True

    # ── DEATH REMNANTS (fighter-level: a card with "Death Remnant" in its own ability text becomes
    # a boosted-power echo on loss; any win disperses whatever remnants you're currently holding) ──
    if won == "win" and m.get("deathRemnants"):
        log.append("☠ your Remnants disperse — an enemy card was killed")
        m["deathRemnants"] = []
    if won == "lose" and "death remnant" in (pc.get("abil", "") or "").lower():
        rp = rules.REMNANT_POW.get(pc["name"], pc["pow"])
        m.setdefault("deathRemnants", []).append({"name": pc["name"], "pow": rp})
        log.append(f"☠ {pc['name']} falls — Death Remnant active (+{rp}, {len(m['deathRemnants'])} on field)")

    # ── CARD-LIFECYCLE DESTINATION (app.py performs the real hand/deck/winners-circle list move) ──
    draw_self = 0
    if won == "win":
        if pc["name"] == "Skullchain Reaver" or (pc["name"] == "The Bronzed Beast, Hanse Waltz" and m["playerScore"][1] >= m["playerScore"][0]):
            destination = "hand"
            log.append(("💀 Skullchain Reaver" if pc["name"] == "Skullchain Reaver" else "🌑 Bronzed Beast (behind) — Blood Moon") + " returns to your hand instead of the Winners Circle")
        else:
            destination = "winners_circle"
        if pc["name"] == "Bone Choirmaster": draw_self += 1; log.append("☠ Bone Choirmaster — the win feeds the choir: draw a card")
    elif won == "lose":
        destination = "deck_bottom"
        ohr = rules.OPTIONAL_HAND_RETURN.get(pc["name"])
        if ohr and ohr.get("onCloseLoss") is not None and abs(playerPow - oppPow) <= ohr["onCloseLoss"]:
            log.append(f"💰 {pc['name']} — lost by {round(abs(playerPow-oppPow))}: recycles to the bottom of your deck (close enough to reclaim)")
        else:
            log.append(f"↩ {pc['name']} recycles to the bottom of your deck")
    else:  # tie
        if forced_tie:
            destination = "hand"
        elif "record guard" in (pc.get("abil", "") or "").lower():
            destination = "hand"; log.append(f"🛡 Record Guard: tie — {pc['name']} bounces back to your hand")
        else:
            destination = "deck_bottom"; log.append(f"↩ {pc['name']} — tie, recycles to the bottom of your deck")

    # 8/5/26 Milestone B: post-duel rear-guard fate, parallel array to the `rear_guards` input
    # (index.html:8900-8916) -- default recycle to deck bottom; LINGERING_SUPPORTS become a Death
    # Remnant instead; Kotei/Tange Sazen specifically return to hand on a WIN (+2 Charge for Kotei).
    for rg in rear_guards:
        if rg["name"] in ("Kotei", "Tange Sazen") and won == "win":
            rear_guard_fates.append("hand")
            if rg["name"] == "Kotei":
                m["charge"] = min(duel_energy_cap(m.get("matchCommits", 0)), m.get("charge", 0) + 2)
                log.append("👑 Kotei — the sovereign returns: +2 Charge, back to your hand instead of the deck")
            else:
                log.append("⚔ Tange Sazen — returns to your hand instead of the deck")
        elif rg["name"] in LINGERING_SUPPORTS:
            rp = rules.REMNANT_POW.get(rg["name"], rg["pow"])
            m.setdefault("deathRemnants", []).append({"name": rg["name"], "pow": rp})
            rear_guard_fates.append("remnant")
            log.append(f"☠ {rg['name']} lingers as a Remnant (+{rp} to your commits until an enemy dies)")
        else:
            rear_guard_fates.append("deck_bottom")
            log.append(f"↩ {rg['name']} (support) → deck bottom")

    # ── STATE UPDATE ──
    if won == "win":
        m["playerScore"][0] += 1; m["lastResult"] = "win"; wc.append({"name": pc["name"]})
        if pc["name"] == "Tange Sazen": m["skullchainKills"] += 1
        if pc["name"] == "Kotei": m["ragwingWins"] += 1
        if bloodthirsty: m["matchTraitPow"][key] = m["matchTraitPow"].get(key, 0) + 1
        if pc["name"] == "Signal Diviner": m["charge"] = min(duel_energy_cap(m.get("matchCommits", 0)), m.get("charge", 0) + 2)
    elif won == "lose":
        m["playerScore"][1] += 1; m["lastResult"] = "lose"
        m["spellHand"].append(random.choice(SPELL_IDS))   # lost the round -> draw a spell
    else:
        m["lastResult"] = "tie"
    m["matchCommits"] += 1
    # 8/5/26: real regen formula (was flat +1 forever) plus the client's separate lose-branch
    # comeback bonus (+1 MORE specifically on a loss, index.html:8855) -- two distinct sources,
    # each capped at each addition point (matches the client's own per-call Math.min chaining
    # rather than summing first and capping once).
    regen = energy_regen_per_turn(m["matchCommits"])
    m["charge"] = min(duel_energy_cap(m["matchCommits"]), m.get("charge", 0) + regen)
    if won == "lose":
        m["charge"] = min(duel_energy_cap(m["matchCommits"]), m["charge"] + 1)
    m["spellJam"] = False; m["spellOppPow"] = 0; m["spellSelfPow"] = 0; m["spellNullOpp"] = False; m["spellShield"] = False
    m["log_last"] = log
    win_threshold = m.get("winThreshold", 4)
    return {"outcome": won, "player_pow": playerPow, "opp_pow": oppPow, "log": log,
            "score": list(m["playerScore"]), "match_over": m["playerScore"][0] >= win_threshold or m["playerScore"][1] >= win_threshold,
            "destination": destination, "draw_self": draw_self, "record_duel": not m.get("lobbyMode", False),
            "hand_ops": hand_ops, "rear_guard_fates": rear_guard_fates}
