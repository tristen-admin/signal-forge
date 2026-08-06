"""
Signal Forge — authoritative Ascension ("The Rite") engine. Full rewrite, 8/5/26.

The previous asc.py implemented a completely different, much simpler game (channel cards to
break a champion's "vitality" counter) that has no relationship to what the client actually runs.
This is a faithful port of the client's REAL system: a JRPG-style party of 1 Champion (avatar,
never fights directly) + 2-3 companions, a speed-sorted turn queue, HP/ATK/SPD stats, a 4-slot
move loadout gated by level, a 100-point Ultimate gauge, and a 2-chapter linear story mode.

Scope of Phase 4.1 (see the memory file for the full history):
  IN:  unified roster (11 bespoke + every other base card via a generic-stats formula), champion
       eligibility (a real Deck-Master ability), full turn-queue combat (damage/heal/status/move-
       kind execution, foe AI incl. boss enrage+signature AoE), the Ultimate, per-unit level/xp
       progression, the 2 real chapters' 7 story nodes (with their real prose) resolved via
       duel/elite/boss/sanctum, real Signal/XP rewards, and a real mastery write (fixing a
       client-side bug where mastery is currently dead code).
  OUT (at the time): gear, consumables, Crossroads, Merchant, Trial nodes, bounties, skins, spec
       points, Arena mode, Endless Rite mode, Ascension-specific "lore link" party auras (always
       neutral here), DM abilities firing in a Rite (task #382, an open design question).

Phase 4.2 adds items + gear, per owner request:
  - Items (ASC_ITEMS: potion/elixir/revive) and Gear (ASC_GEAR: 5 pieces, flat hp/atk/spd bonuses)
    are real now. BUT the client's own acquisition path for both is the Merchant node + Crossroads
    "gear"/"provision" offers -- and neither node type appears ANYWHERE in the real Chapter 1/2
    story data (confirmed: all 7 real nodes are duel/elite/boss/sanctum only). Rather than invent
    Merchant-as-a-story-node the client itself never uses there, items/gear are bought as PART OF
    `asc/start` (a pre-Rite provisioning step, spending account Signal) -- same prices, same
    run-scoped-not-persistent-across-runs model as the client's `ascRun.inv`/`ascRun.gear`, just
    moved to before the Rite instead of at a mid-run shop node Story mode doesn't have.
  - Phase 4.2 also shipped a companions-basic-attack-only gate here, per an initial misreading of
    the owner's next request -- corrected immediately in Phase 4.3 below once the owner clarified
    they wanted the OPPOSITE (more attack options, not fewer). Removed entirely; no trace left
    beyond this note, since a stale toggle for a rejected design would just mislead the next read.

Phase 4.3 (owner correction, 8/6/26): "i want more attack options... an ability [to] gain another
attack option (ideally status giving buff or debuffs moves)... a way to swap attacks out per unit
to create your ideal combo." Root cause of "only ever a basic attack and one special move": NOT a
slow-leveling artifact -- ASC_MOVES/ASC_MOVES_CAP only ever covered the 11 hand-authored ASC_UNITS,
so every other unit (140+ of ~152 cards) was permanently ceilinged at 1 move (their Roof-kit
signature) at ANY level. Fixed via rules.asc_generic_moves(): every generic unit now gets the same
real 3-extra+capstone shape as the bespoke units (unlock levels 3/6/9/12, mirroring ASC_MOVE_UNLOCK
exactly), Roof-themed and deliberately mixing dmg/buff/debuff kinds so there's a real kit to build a
loadout around. Loadout swapping (h_asc_loadout in app.py) lets the player choose which unlocked
moves occupy the 4 active slots -- the data model (`prog[name]["load"]`) already supported this;
only the endpoint to actually set it was missing.

Mastery fix: the client's own `ascEndRun()` (the only writer of `avatarBond`, the client-side
mastery ledger) is reachable ONLY via Abandon-run, always with won=False, and reads a field
(`ascRun.avatarKey`) no run constructor ever sets -- confirmed by direct research this mastery
system is currently disconnected from real play entirely. The formulas are well-defined and
clearly the intended design, just mis-wired. This server writes them for real, at true run end
(win the final boss, or lose/abandon), using the server's own `mastery` table (already exists,
already used by the TCG's card-mastery path) keyed by the champion's card type name.
"""
import json, os, random
import rules

_CAT = rules._CAT

# ── data (extracted from the client via extract_catalog.py — see server/catalog.json) ──
ASC_UNITS = _CAT["ascUnits"]                    # 11 bespoke units
ASC_PASSIVES = _CAT["ascPassives"]              # champion patron passives, keyed by unit id
ASC_MOVE_UNLOCK = _CAT["ascMoveUnlock"]         # [1,3,6,9,12]
ASC_MOVES_CAP = _CAT["ascMovesCap"]             # Lv-12 capstone move, keyed by unit id
ASC_MOVES = _CAT["ascMoves"]                    # 3 unlockable extras per unit, keyed by unit id
ASC_BOSS_SIGS = _CAT["ascBossSigs"]
ASC_ITEMS = _CAT["ascItems"]                    # potion/elixir/revive -- Signal-priced consumables
ASC_GEAR = _CAT["ascGear"]                      # 5 flat hp/atk/spd-boost pieces -- Signal-priced
ASC_FOES = _CAT["ascFoes"]                      # global fallback pool
_STORY_CH = [_CAT["ascStory"], _CAT["ascStoryCh2"]]
ASC_CHAPTERS = [
    {"id": "ch1", "title": "Chapter 1: The Ceiling", "beats": _STORY_CH[0]},
    {"id": "ch2", "title": "Chapter 2: Queen Crimson", "beats": _STORY_CH[1]},
]

_UNITS_BY_ID = {u["id"]: u for u in ASC_UNITS}
_UNITS_BY_NAME = {u["name"]: u for u in ASC_UNITS}
_ITEMS_BY_ID = {it["id"]: it for it in ASC_ITEMS}
_GEAR_BY_ID = {g["id"]: g for g in ASC_GEAR}

# ── roster resolution (index.html:13038-13056 ascResolveUnit/ascUnifiedRoster) ──
def resolve_unit(key):
    if key is None: return None
    if key in _UNITS_BY_ID: return _UNITS_BY_ID[key]
    if key in _UNITS_BY_NAME: return _UNITS_BY_NAME[key]
    if key not in rules.CARD_CATALOG: return None
    st = rules.asc_generic_base_stats(key)
    ab = rules.asc_generic_ability(key)
    return {"id": key, "name": key, "art": key, "role": rules.asc_generic_role(key),
            "avatar": False, "generic": True, "hp": st["hp"], "atk": st["atk"], "spd": st["spd"], "ability": ab}

def champion_eligible(key):
    u = resolve_unit(key)
    return bool(u) and rules.asc_champion_eligible(u["name"], u.get("avatar") is True)

# ── move list / loadout (index.html:12930-12938 ascUnitMoveList/ascUnitLoadout) ──
def unit_move_list(base):
    """Phase 4.3: generic (non-bespoke) units used to dead-end here -- ASC_MOVES/ASC_MOVES_CAP only
    ever covered the 11 hand-authored ASC_UNITS, so every other unit (140+ of ~152 cards) was
    permanently stuck at 1 move regardless of level. rules.asc_generic_moves() now gives every
    generic unit the same real 3-extra+capstone shape, Roof-themed and buff/debuff-varied."""
    sig = dict(base.get("ability") or {}); sig.setdefault("unlock", 1)
    extra = []
    for i, m in enumerate(ASC_MOVES.get(base["id"], [])):
        mm = dict(m); mm["unlock"] = ASC_MOVE_UNLOCK[i+1] if i+1 < len(ASC_MOVE_UNLOCK) else 10
        extra.append(mm)
    cap = []
    if base["id"] in ASC_MOVES_CAP:
        mm = dict(ASC_MOVES_CAP[base["id"]]); mm["unlock"] = ASC_MOVE_UNLOCK[4] if len(ASC_MOVE_UNLOCK) > 4 else 12
        cap.append(mm)
    if not extra and base.get("generic"):
        gen_extra, gen_cap = rules.asc_generic_moves(base["name"])
        extra = [dict(m, unlock=ASC_MOVE_UNLOCK[i+1] if i+1 < len(ASC_MOVE_UNLOCK) else 10) for i, m in enumerate(gen_extra)]
        cap = [dict(gen_cap, unlock=ASC_MOVE_UNLOCK[4] if len(ASC_MOVE_UNLOCK) > 4 else 12)]
    return [sig] + extra + cap

def unit_level(prog, name):
    p = prog.get(name)
    return (p or {}).get("level", 1)

def unit_loadout(base, prog):
    lv = unit_level(prog, base["name"])
    full = unit_move_list(base)
    unlocked = [i for i, m in enumerate(full) if lv >= m.get("unlock", 1)]
    p = prog.get(base["name"]) or {}
    load = [i for i in (p.get("load") or []) if i in unlocked]
    if not load: load = unlocked[:4]
    return load[:4]

def unit_stats(base, prog):
    """index.html:13168 ascUnitStats() -- level scales hp +12%/lvl, atk +10%/lvl. SPD does not scale."""
    lv = unit_level(prog, base["name"])
    return {"hp": round(base["hp"]*(1+(lv-1)*0.12)), "atk": round(base["atk"]*(1+(lv-1)*0.10)), "lv": lv}

def _mk_combatant(base, is_avatar, hp_bonus, atk_bonus, spd_bonus, prog):
    st = unit_stats(base, prog)
    maxhp = st["hp"] + hp_bonus
    atk = st["atk"] + atk_bonus
    spd = base["spd"] + spd_bonus
    full = unit_move_list(base)
    load = unit_loadout(base, prog)
    moves = [dict(full[i], left=full[i].get("uses", 0)) for i in load]
    return {"id": base["id"], "name": base["name"], "art": base.get("art", base["name"]), "avatar": bool(is_avatar),
            "maxhp": maxhp, "hp": maxhp, "atk": atk, "spd": spd, "lv": st["lv"],
            "moves": moves, "abilLeft": (moves[0]["left"] if moves else 2),
            "st": {"atk": 0, "atkT": 0, "def": 0, "defT": 0, "vuln": 0, "vulnT": 0, "dot": 0, "dotT": 0}}

def instantiate_party(champion_key, companion_keys, prog, equip=None):
    """index.html:13132-13134 mkA/mkC -- HP persists across the whole run once instantiated;
    moves/uses/statuses refresh per battle (see refresh_for_battle).

    `equip`: optional {unit_name: gear_id} map, gear bonuses stack additively onto the passive
    bonus exactly like index.html:13627 ascRecomputeAll() -- both are skipped for the avatar
    (`if(u.avatar) return;` in the client), since the Champion never fights and the bonus would be
    inert. spd bonus applies on top of BASE spd, unscaled by level -- matching ascUnitStats(), which
    never scales SPD, and ascRecomputeAll(), which adds `g.spd` straight onto `base.spd`."""
    equip = equip or {}
    champ_base = resolve_unit(champion_key)
    if not champ_base: return None
    pas = ASC_PASSIVES.get(champ_base["id"], {})
    party = [_mk_combatant(champ_base, True, 0, 0, 0, prog)]
    for key in companion_keys:
        base = resolve_unit(key)
        if not base: continue
        g = _GEAR_BY_ID.get(equip.get(base["name"]), {})
        party.append(_mk_combatant(base, False, pas.get("hp", 0) + g.get("hp", 0),
                                    pas.get("atk", 0) + g.get("atk", 0), g.get("spd", 0), prog))
    return party

def refresh_for_battle(party, prog):
    """New battle: moves/uses/statuses reset, HP/maxHP carried over from the run-persistent party."""
    for u in party:
        base = resolve_unit(u["id"])
        full = unit_move_list(base)
        load = unit_loadout(base, prog)
        u["moves"] = [dict(full[i], left=full[i].get("uses", 0)) for i in load]
        u["abilLeft"] = u["moves"][0]["left"] if u["moves"] else 2
        u["st"] = {"atk": 0, "atkT": 0, "def": 0, "defT": 0, "vuln": 0, "vulnT": 0, "dot": 0, "dotT": 0}

# ── XP / progression (index.html:13187-13189 ascGrantXP) ──
def new_prog_entry():
    """The full asc_prog row shape -- one place so every construction site (grant_xp, and app.py's
    handful of .setdefault() call sites) stays in sync as fields get added (kills/poolBonusGranted,
    Phase 4.4)."""
    return {"level": 1, "xp": 0, "rites": 0, "bosses": 0, "kills": 0, "poolBonusGranted": False, "load": []}

def grant_xp(prog, name, amount):
    p = prog.setdefault(name, new_prog_entry())
    p["xp"] += amount
    need = p["level"] * 60
    while p["xp"] >= need:
        p["xp"] -= need; p["level"] += 1; need = p["level"] * 60
    return p

# ── foe stats (index.html:13636-13651 ascFoeStats, boss/elite/trial branches; trial deferred) ──
def foe_stats(node):
    node_type = node["type"]
    count = 1 if node_type == "boss" else 3 if node_type == "elite" else 2
    mult = 1 + (node.get("globalTier", node.get("tier", 0))) * 0.22
    pool = node.get("foes") or ASC_FOES
    foes = []
    for i in range(count):
        lead = (i == 0)
        if node_type == "boss":
            tmpl = {"name": node.get("champName", "Boss"), "art": node.get("champArt") or node.get("champName"), "hp": 150, "atk": 26, "spd": 9}
        else:
            tmpl = random.choice(pool)
        hp = round(tmpl["hp"] * mult * (1.55 if node_type == "boss" else 1))
        name = node.get("champName") if (lead and node_type == "boss") else tmpl["name"]
        rank = "boss" if (lead and node_type == "boss") else "elite" if (lead and node_type in ("elite", "trial")) else "normal"
        foes.append({"name": name, "art": tmpl.get("art", tmpl["name"]), "maxhp": hp, "hp": hp,
                      "atk": round(tmpl["atk"] * mult), "spd": tmpl["spd"], "rank": rank, "t": 0,
                      "st": {"vuln": 0, "vulnT": 0, "dot": 0, "dotT": 0, "def": 0, "defT": 0}})
    return foes

# ── chapters / story map (index.html:13097-13126) ──
def chapter_unlocked(idx, prog):
    """index.html:13102 -- one accumulated boss-or-rite credit ANYWHERE unlocks every later chapter."""
    if idx <= 0: return True
    return sum((p.get("bosses", 0) + p.get("rites", 0)) for p in prog.values()) > 0

def story_map(chapter_idx):
    chapter_idx = chapter_idx if 0 <= chapter_idx < len(ASC_CHAPTERS) else 0
    beats = ASC_CHAPTERS[chapter_idx]["beats"]
    prior = sum(len(ASC_CHAPTERS[c]["beats"]) for c in range(chapter_idx))
    nodes = []
    for i, sn in enumerate(beats):
        nodes.append({"id": f"story{i}", "type": sn["type"], "champName": sn.get("champ"), "champArt": sn.get("art"),
                      "tier": i, "globalTier": prior+i, "loc": sn.get("loc"), "beat": sn.get("beat"),
                      "title": sn.get("title"), "foes": sn.get("foes")})
    return nodes

# ── combat math (index.html:13660-13787) ──
def apply_damage(target, dmg):
    st = target.get("st") or {}
    mult = (1 + st.get("vuln", 0)) * (1 - min(0.75, st.get("def", 0) + target.get("linkDef", 0)))
    d = max(1, round(dmg * mult * (0.85 + random.random() * 0.3)))
    target["hp"] = max(0, target["hp"] - d)
    return d

def out_power(actor, base):
    """index.html:13725 ascOut() -- waltz-rally link bonus deliberately omitted (Ascension lore-
    link party auras are out of scope this pass, see module docstring)."""
    b = 1 + (actor.get("st", {}).get("atk", 0) or 0)
    return round(base * b)

def heal_amt(target, amt):
    target["hp"] = min(target["maxhp"], target["hp"] + amt)

def tick_statuses(ent, log):
    st = ent.get("st") or {}
    if st.get("dotT", 0) > 0 and ent["hp"] > 0:
        dd = max(1, round(st.get("dot", 0)))
        ent["hp"] = max(0, ent["hp"] - dd)
        st["dotT"] -= 1
        if st["dotT"] <= 0: st["dot"] = 0
        log.append(f"{ent['name']} takes {dd} lingering damage")
    for k in ("atk", "def", "vuln"):
        tk = k + "T"
        if st.get(tk, 0) > 0:
            st[tk] -= 1
            if st[tk] <= 0: st[k] = 0

def battle_over(battle):
    if not any(f["hp"] > 0 for f in battle["foes"]): return "win"
    if not any(u["hp"] > 0 for u in battle["party"] if not u.get("avatar")): return "lose"
    return None

def build_queue(battle):
    """index.html:13663-13681 ascBattleNext()'s queue-rebuild -- the avatar never gets a turn
    (Champion never fights, confirmed: `summoned` is never set true anywhere in the client)."""
    order = []
    for i, u in enumerate(battle["party"]):
        if u["hp"] > 0 and not u.get("avatar"): order.append({"side": "party", "i": i, "spd": u["spd"]})
    for i, f in enumerate(battle["foes"]):
        if f["hp"] > 0: order.append({"side": "foe", "i": i, "spd": f["spd"]})
    order.sort(key=lambda t: -t["spd"])
    return order

def foe_act(battle, fi, log):
    """index.html:13682-13705 ascFoeAct(). Also grants +9 gauge (index.html:13702 -- inside
    ascFoeAct itself, not a separate call site)."""
    fo = battle["foes"][fi]
    fo["t"] = fo.get("t", 0) + 1
    gauge_add(battle, 9)
    targets = [u for u in battle["party"] if u["hp"] > 0 and not u.get("avatar")]
    if not targets: return
    enraged = (fo["rank"] == "boss" and fo["hp"] <= fo["maxhp"] * 0.35)
    mult = 1.5 if enraged else 1.15 if fo["rank"] == "elite" else 1
    if fo["rank"] == "boss" and fo["t"] % 3 == 0:
        pw = round(fo["atk"] * 0.8 * mult)
        sig = random.choice(ASC_BOSS_SIGS) if ASC_BOSS_SIGS else "a signature attack"
        log.append(f"☠ {fo['name']} unleashes {sig}!")
        for u in targets: apply_damage(u, pw)
    elif fo["rank"] in ("boss", "elite"):
        tgt = min(targets, key=lambda u: u["hp"])
        d = apply_damage(tgt, round(fo["atk"] * mult))
        log.append(f"{fo['name']} strikes {tgt['name']} for {d}")
    else:
        tgt = random.choice(targets)
        d = apply_damage(tgt, fo["atk"])
        log.append(f"{fo['name']} strikes {tgt['name']} for {d}")

def advance_to_party_turn(battle, log, max_steps=200):
    """Runs the turn queue forward (auto-resolving foe turns, matching the client's setTimeout-
    chained ascBattleNext()) until it's a living party member's turn, or the battle ends. Returns
    the outcome ('win'|'lose'|None) and sets battle['actor'] to the next party-turn index, or None
    if the battle ended."""
    steps = 0
    while steps < max_steps:
        steps += 1
        outcome = battle_over(battle)
        if outcome: battle["actor"] = None; return outcome
        if not battle.get("queue") or battle.get("qptr", 0) >= len(battle["queue"]):
            battle["queue"] = build_queue(battle); battle["qptr"] = 0; battle["round"] = battle.get("round", 0) + 1
        turn = battle["queue"][battle["qptr"]]; battle["qptr"] += 1
        ent = (battle["party"][turn["i"]] if turn["side"] == "party" else battle["foes"][turn["i"]])
        if ent["hp"] <= 0: continue
        tick_statuses(ent, battle["log"])
        if turn["side"] == "party":
            battle["actor"] = turn["i"]; return None
        foe_act(battle, turn["i"], battle["log"])
        outcome = battle_over(battle)
        if outcome: battle["actor"] = None; return outcome

# ── move kinds (index.html:13732-13779 ascUseMove/ascApplyMoveFoe/ascTarget) ──
_SELF_KINDS = {"aoe", "guard"}
_FOE_TARGET_KINDS = {"dmg", "vuln", "dot", "execute"}
_ALLY_TARGET_KINDS = {"heal", "buff"}

def use_move(battle, actor_i, move_i, target_i, log):
    actor = battle["party"][actor_i]
    if move_i >= len(actor["moves"]): return False, "no such move"
    mv = actor["moves"][move_i]
    if mv.get("left", 0) <= 0: return False, "no uses left"
    kind = mv.get("kind", "dmg")
    mv["left"] -= 1
    if kind == "aoe":
        pw = out_power(actor, mv.get("power", 0))
        for f in battle["foes"]:
            if f["hp"] > 0: apply_damage(f, pw)
        log.append(f"{actor['name']} uses {mv['name']} — heavy damage to every foe")
    elif kind == "guard":
        for u in battle["party"]:
            if u["hp"] > 0 and not u.get("avatar"):
                u["st"]["def"] = max(u["st"].get("def", 0), mv.get("power", 0))
                u["st"]["defT"] = max(u["st"].get("defT", 0), mv.get("dur", 1))
        log.append(f"{actor['name']} uses {mv['name']} — the party braces")
    elif kind in _FOE_TARGET_KINDS:
        if target_i is None or target_i >= len(battle["foes"]) or battle["foes"][target_i]["hp"] <= 0:
            return False, "invalid target"
        fo = battle["foes"][target_i]
        if kind == "vuln":
            fo["st"]["vuln"] = max(fo["st"].get("vuln", 0), mv.get("power", 0)); fo["st"]["vulnT"] = max(fo["st"].get("vulnT", 0), mv.get("dur", 1))
            log.append(f"{actor['name']} uses {mv['name']} on {fo['name']}")
        elif kind == "dot":
            fo["st"]["dot"] = max(fo["st"].get("dot", 0), mv.get("power", 0)); fo["st"]["dotT"] = max(fo["st"].get("dotT", 0), mv.get("dur", 1))
            log.append(f"{actor['name']} uses {mv['name']} on {fo['name']}")
        else:
            base = mv.get("power", 0)
            if kind == "execute" and fo["hp"] <= fo["maxhp"] * 0.35: base = round(base * 1.6)
            d = apply_damage(fo, out_power(actor, base))
            log.append(f"{actor['name']} uses {mv['name']} on {fo['name']} for {d}")
    elif kind in _ALLY_TARGET_KINDS:
        allies = [u for u in battle["party"] if u["hp"] > 0 and not u.get("avatar")]
        if target_i is None or target_i >= len(battle["party"]) or battle["party"][target_i] not in allies:
            return False, "invalid target"
        al = battle["party"][target_i]
        if kind == "buff":
            al["st"]["atk"] = max(al["st"].get("atk", 0), mv.get("power", 0)); al["st"]["atkT"] = max(al["st"].get("atkT", 0), mv.get("dur", 1))
        else:
            heal_amt(al, mv.get("power", 0))
        log.append(f"{actor['name']} uses {mv['name']} on {al['name']}")
    else:
        return False, "unknown move kind"
    return True, None

def use_item(battle, inv, actor_i, item_id, target_i, log):
    """index.html:13606-13608/13773-13775 ascPickItem()/ascTarget()'s item branch. `inv` is the
    run's {item_id: count} dict -- mutated in place on a successful use, same as the client
    decrementing `ascRun.inv[id]` directly. healall (Elixir) has no target -- it hits every living
    non-avatar party member in one call, matching the client's separate no-target-selection branch."""
    it = _ITEMS_BY_ID.get(item_id)
    if not it: return False, "unknown item"
    if inv.get(item_id, 0) <= 0: return False, "none left"
    actor = battle["party"][actor_i]
    if it["kind"] == "healall":
        for u in battle["party"]:
            if u["hp"] > 0 and not u.get("avatar"): heal_amt(u, it["power"])
        log.append(f"{it['icon']} {it['name']} restores the party (+{it['power']} HP each)")
        inv[item_id] -= 1
        return True, None
    if target_i is None or target_i >= len(battle["party"]): return False, "invalid target"
    al = battle["party"][target_i]
    if al.get("avatar"): return False, "invalid target"
    if it["kind"] == "revive":
        if al["hp"] > 0: return False, "target is not downed"
        al["hp"] = round(al["maxhp"] * it["power"])
        log.append(f"{actor['name']} revives {al['name']} (+{al['hp']} HP)")
    else:
        if al["hp"] <= 0: return False, "target is downed"
        heal_amt(al, it["power"])
        log.append(f"{actor['name']} uses {it['name']} on {al['name']} (+{it['power']} HP)")
    inv[item_id] -= 1
    return True, None

def basic_attack(battle, actor_i, target_i, log):
    actor = battle["party"][actor_i]
    if target_i is None or target_i >= len(battle["foes"]) or battle["foes"][target_i]["hp"] <= 0:
        return False, "invalid target"
    fo = battle["foes"][target_i]
    d = apply_damage(fo, out_power(actor, actor["atk"]))
    log.append(f"{actor['name']} attacks {fo['name']} for {d}")
    return True, None

GAUGE_MAX = 100
def gauge_add(battle, n):
    battle["gauge"] = min(GAUGE_MAX, battle.get("gauge", 0) + n)

def ultimate(battle, log):
    """index.html:13866-13888 ascUltimate() -- 6 kind branches. linkUlt multiplier fixed at 1.0
    (Ascension lore-link auras deferred, see module docstring). Percentage kinds must NOT reuse the
    rounded flat-damage `pw` -- same 8/3/26 fix the client itself needed (Math.round(0.35*1.4)==0
    would zero out every percentage ultimate if reused)."""
    av = next((u for u in battle["party"] if u.get("avatar")), None)
    if not av or battle.get("gauge", 0) < GAUGE_MAX: return False, "gauge not full"
    battle["gauge"] = 0
    ult = av.get("ability") or {}
    pw = round((ult.get("power", 30)) * 1.4)
    kind = ult.get("kind", "dmg")
    log.append(f"✦ {av['name'].split(',')[0]} unleashes {ult.get('name','their Ultimate')}!")
    allies = [u for u in battle["party"] if u["hp"] > 0 and not u.get("avatar")]
    if kind == "heal":
        for u in allies: heal_amt(u, pw)
    elif kind == "aoe":
        for f in battle["foes"]:
            if f["hp"] > 0: apply_damage(f, pw)
    elif kind == "buff":
        pct = ult.get("power", 0.3) * 1.4
        for u in allies:
            u["st"]["atk"] = max(u["st"].get("atk", 0), pct); u["st"]["atkT"] = max(u["st"].get("atkT", 0), ult.get("dur", 3))
    elif kind == "guard":
        pct = ult.get("power", 0.3) * 1.4
        for u in allies:
            u["st"]["def"] = max(u["st"].get("def", 0), pct); u["st"]["defT"] = max(u["st"].get("defT", 0), ult.get("dur", 3))
    elif kind == "vuln":
        pct = ult.get("power", 0.3) * 1.4
        for f in battle["foes"]:
            if f["hp"] > 0:
                f["st"]["vuln"] = max(f["st"].get("vuln", 0), pct); f["st"]["vulnT"] = max(f["st"].get("vulnT", 0), ult.get("dur", 3))
    else:
        alive = [f for f in battle["foes"] if f["hp"] > 0]
        if alive: apply_damage(max(alive, key=lambda f: f["hp"]), pw)
    return True, None

# rewards per node type (index.html:13798-13800)
_NODE_XP = {"duel": 45, "elite": 75, "trial": 90, "boss": 130}
_NODE_SIGNAL = {"duel": 40, "elite": 80, "trial": 120, "boss": 200}
