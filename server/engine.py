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
def resolve(m, pc, oc, cond_id, committed_pow=None, pc_record=None):
    """pc, oc: card dicts. pc_record: the player card's live DB record {k,d,ok,od} (drives traits +
    the pc.kills used by conditions). Returns dict with outcome/powers/log/destination; mutates
    match state m. `destination` (winners_circle|hand|deck_bottom) and `draw_self` tell the caller
    (app.py, which owns the real uid-keyed hand/deck lists) what list-move to perform."""
    playerPow = committed_pow if committed_pow is not None else pc["pow"]
    oppPow = oc["pow"]
    log = []
    rec = pc_record or {"k": pc["kills"], "d": pc["deaths"], "ok": 0, "od": 0}
    pcK, pcD = rec["k"], rec["d"]                    # player card's live record
    ocK, ocD = oc["kills"], oc["deaths"]              # opponent card's record
    wc = m["winnersCircle"]

    # ── ENERGY SPELL EFFECTS (armed by the client Charge system; inert unless set) ──
    if m.get("spellJam"): cond_id = "jammed"; log.append("📡 Jammer: active condition negated")
    if m.get("spellOppPow"): oppPow += m["spellOppPow"]; log.append(f"⚡ Interrupt: opponent {m['spellOppPow']} power")
    if m.get("spellSelfPow"): playerPow += m["spellSelfPow"]; log.append(f"⚡ Amplify: +{m['spellSelfPow']} power")

    # ── LIVING-CARD TRAITS — ONE conditional trait per card (fires only in-context; mirrors client) ──
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
            "destination": destination, "draw_self": draw_self, "record_duel": not m.get("lobbyMode", False)}
