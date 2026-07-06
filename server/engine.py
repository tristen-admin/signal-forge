"""
Signal Forge — authoritative match engine (server-side port of the client resolve()).
Faithful transcription of the client's duel resolution: on-commit abilities, the 8 power
conditions, Living-Card traits, and the resolution guards (Ahdor / Last Stand / Regen / Death
Remnant), plus best-of-7 match state. The server owns every outcome; the client only requests.

Parity note: this mirrors the client resolve() as of 2026-07-03. The client rules are hand-authored
imperative JS and still changing (parallel session) — keep this in sync, or (better) migrate both to
one data-driven rules spec. Formations are omitted here (server has no pairBonds table yet).
"""
import json, os, random
import rules

# ── CARD CATALOG (name → pow/kills/deaths/rarity/abil), ported from HAND_CARDS + DECK_POOL ──
CATALOG = {n: {"pow": c["pow"], "kills": 0, "deaths": 0, "rarity": c["rarity"], "abil": c["abil"]} for n, c in rules.CARD_FULL.items()}   # canonical (catalog.json)
CHAOS_CONDS = {"forceswap", "surge", "mirror"}
FORMATION_TIERS = [(15, "Legendary Duo", 3), (8, "Brothers-in-Arms", 2), (3, "Allied", 1)]
# power conditions resolve() acts on (others — noretreat/openbook/recall etc. — don't touch power)
POWER_CONDS = ["none","lowest","surge","mirror","forceswap","provingground","hollowreckoning","recordties","abilitylock"]

def card(name):
    c = CATALOG.get(name, {"pow": 8, "kills": 0, "deaths": 0, "rarity": "common", "abil": ""})
    return {"name": name, **c}

def new_match(deck_names):
    return {"deck": list(deck_names), "hand": list(deck_names[:4]), "winnersCircle": [],
            "playerScore": [0, 0], "lastResult": None, "matchCommits": 0, "skullchainKills": 0,
            "ragwingWins": 0, "deathRemnantPow": 0, "oppNextDebuff": 0,
            "glacialGuardUsed": False, "oppGuardUsed": False, "horrorRegenUsed": False,
            "untouchableUsed": False, "matchTraitPow": {}, "done": False, "log_last": [],
            "bonds": {}, "matchPlayed": set(), "charge": 0, "spellDiscount": 0,
            "spellOppPow": 0, "spellSelfPow": 0, "spellJam": False, "spellNullOpp": False,
            "spellHand": [], "spellShield": False, "charge": 0, "spellDiscount": 0}

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
def pick_condition():
    return random.choice(POWER_CONDS)

def opponent_pool():
    return [n for n in CATALOG if n not in ("Bixie Bee", "Melanie")]

# ── DATA-DRIVEN ABILITY SPEC (step 1 of the shared rules spec) ──
# Each card -> ordered rules. A rule fires if its "if" condition holds, then applies one op:
#   add:N  addvar:var,x:mult  mult:N  set:var  oppadd:N.  Conditions compare context vars.
RULES = rules._CAT["rules"]   # canonical rules from catalog.json (was stale rules.json)
SPELLS = json.load(open(os.path.join(os.path.dirname(__file__), "spells.json"), encoding="utf-8"))
SPELL_IDS = [s["id"] for s in SPELLS]

def _ctx(pc, oc, m, rec, cond_id):
    return {"opp_deaths":oc["deaths"],"opp_kills":oc["kills"],"pc_kills":rec["k"],"pc_deaths":rec["d"],
            "opp_pow":oc["pow"],"pc_pow":pc["pow"],"last_result":m["lastResult"],"match_commits":m["matchCommits"],
            "player_wins":m["playerScore"][0],"player_losses":m["playerScore"][1],"hand_len":len(m["hand"]),
            "wc_len":len(m["winnersCircle"]),"skullchain":m["skullchainKills"],"ragwing":m["ragwingWins"],
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
def _apply_rules(name, ctx, playerPow, oppPow, log):
    for rule in RULES.get(name, []):
        if not eval_cond(rule.get("if"), ctx): continue
        if "add" in rule: playerPow += rule["add"]
        elif "addvar" in rule: playerPow += ctx[rule["addvar"]] * rule.get("x", 1)
        elif "mult" in rule: playerPow *= rule["mult"]
        elif "set" in rule: playerPow = ctx[rule["set"]]
        elif "oppadd" in rule: oppPow += rule["oppadd"]
        if rule.get("log"): log.append(rule["log"])
    return playerPow, oppPow

# ── the faithful resolve() port ──
def resolve(m, pc, oc, cond_id, committed_pow=None, pc_record=None):
    """pc, oc: card dicts. pc_record: the player card's live DB record {k,d,ok,od} (drives traits +
    the pc.kills used by conditions). Returns dict with outcome/powers/log; mutates match state m."""
    playerPow = committed_pow if committed_pow is not None else pc["pow"]
    oppPow = oc["pow"]
    log = []
    rec = pc_record or {"k": pc["kills"], "d": pc["deaths"], "ok": 0, "od": 0}
    pcK, pcD = rec["k"], rec["d"]                    # player card's live record
    ocK, ocD = oc["kills"], oc["deaths"]             # opponent card's record
    hand_len = len(m["hand"])
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
    akatoshUnmakes = (pc["name"] == "Akatosh, the Golden Dragon") and not abilityLocked
    if akatoshUnmakes: log.append("🐉 Akatosh unmakes the arena — condition takes no effect")

    if m["oppNextDebuff"]:
        oppPow += m["oppNextDebuff"]; log.append(f"🧬 Darwin's Curse: opponent {m['oppNextDebuff']} power"); m["oppNextDebuff"] = 0

    # ── ON-COMMIT ABILITIES ──
    if not abilityLocked:
        n = pc["name"]
        if n == "Conduit Adept": m["charge"] = min(5, m.get("charge", 0) + 1); log.append("⚡ Conduit Adept: +1 Charge")
        if n == "Voltcaller": m["spellDiscount"] = m.get("spellDiscount", 0) + 2; log.append("⚡ Voltcaller: next Interrupt −2")
        ctx = _ctx(pc, oc, m, rec, cond_id)
        if n == "Veronica":
            if oc.get("abil"):
                log.append(f"🔄 Veronica copies {oc['name']}")
                playerPow, oppPow = _apply_rules(oc["name"], ctx, playerPow, oppPow, log)
            else:
                log.append("🔄 Veronica: opponent has no ability")
        else:
            playerPow, oppPow = _apply_rules(n, ctx, playerPow, oppPow, log)

    # ── APPLY CONDITION ──
    if not akatoshUnmakes:
        if cond_id == "lowest": playerPow, oppPow = -playerPow, -oppPow
        elif cond_id == "surge":
            if random.random() > 0.5: playerPow += 6; log.append("🌪️ Surge: +6 you")
            else: oppPow += 6; log.append("🌪️ Surge: +6 opponent")
        elif cond_id == "mirror": playerPow, oppPow = oc["pow"], pc["pow"]; log.append("🔄 Mirror")
        elif cond_id == "forceswap":
            if m["hand"]: sw = card(random.choice(m["hand"])); playerPow = sw["pow"]; log.append(f"🎲 Force Swap: → {sw['name']}")
            oppPow = card(random.choice(opponent_pool()))["pow"]; log.append("🎲 Force Swap: opp swapped")
        elif cond_id == "provingground":
            if pc["pow"] > oc["pow"]: playerPow = max(1, playerPow-5); log.append("⛰️ Proving Ground: you −5")
            elif oc["pow"] > pc["pow"]: oppPow = max(1, oppPow-5); log.append("⛰️ Proving Ground: opp −5")
        elif cond_id == "hollowreckoning": playerPow, oppPow = pcK, ocK; log.append(f"🌫️ Hollow Reckoning: {pcK} vs {ocK}")

    # ── DETERMINE WINNER ──
    if playerPow > oppPow: won = "win"
    elif playerPow < oppPow: won = "lose"
    else: won = "tie"
    if won == "tie" and cond_id == "recordties" and not akatoshUnmakes:
        if pcK > ocK: won = "win"; log.append("💀 Record Breaks Ties: win")
        elif pcK < ocK: won = "lose"; log.append("💀 Record Breaks Ties: lose")

    # ── RESOLUTION GUARDS ──
    ability = pc.get("abil", "")
    if won == "lose" and pc["name"] == "Ahdor" and not m["glacialGuardUsed"]:
        m["glacialGuardUsed"] = True; won = "tie"; log.append("🛡 Record Guard: loss blocked, tied")
    if won == "win" and not m["oppGuardUsed"] and not m.get("spellNullOpp") and "record guard" in (oc.get("abil", "").lower()):
        m["oppGuardUsed"] = True; won = "tie"; log.append(f"🛡 {oc['name']} Record Guard: tied")
    if won == "lose" and pc["name"] == "Hanse Waltz":
        if abs(abs(playerPow) - abs(oppPow)) <= 3: won = "tie"; log.append("🌙 Last Stand: tied (≤3)")
    if won == "lose" and pc["name"] == "The Regenerating Horror" and not m["horrorRegenUsed"]:
        m["horrorRegenUsed"] = True; won = "tie"; log.append("👁 Regeneration: tied, returns to hand")
    if won == "lose" and untouchable and not m["untouchableUsed"]:
        m["untouchableUsed"] = True; won = "tie"; log.append("🛡 Untouchable: loss refused, tied")
    if won == "lose" and m.get("spellShield"):
        won = "tie"; log.append("🛡 Ledger Ward: death blocked, tied")

    # ── STATE UPDATE ──
    if won == "win":
        m["playerScore"][0] += 1; m["lastResult"] = "win"; wc.append({"name": pc["name"]})
        if pc["name"] == "Tange Sazen": m["skullchainKills"] += 1
        if pc["name"] == "Kotei": m["ragwingWins"] += 1
        if bloodthirsty: m["matchTraitPow"][key] = m["matchTraitPow"].get(key, 0) + 1
        if pc["name"] == "Signal Diviner": m["charge"] = min(5, m.get("charge", 0) + 2)
    elif won == "lose":
        m["playerScore"][1] += 1; m["lastResult"] = "lose"
        m["spellHand"].append(random.choice(SPELL_IDS))   # lost the round -> draw a spell
    else:
        m["lastResult"] = "tie"
    m["matchCommits"] += 1
    m["charge"] = min(5, m.get("charge", 0) + 1)   # +1 Charge per turn
    m["spellJam"] = False; m["spellOppPow"] = 0; m["spellSelfPow"] = 0; m["spellNullOpp"] = False; m["spellShield"] = False
    m["log_last"] = log
    return {"outcome": won, "player_pow": playerPow, "opp_pow": oppPow, "log": log,
            "score": list(m["playerScore"]), "match_over": m["playerScore"][0] >= 4 or m["playerScore"][1] >= 4}

