"""
Signal Forge — Tier 0 authoritative rules.
The SERVER owns outcomes, rewards, traits, and appraisals. A subset of the client
rule-set, deliberately; bringing it to full parity with the client resolve() is a
tracked follow-up. Pure functions + catalog only (no I/O).
"""
import hashlib, secrets, json, os, random

# ── card catalog — LOADED from catalog.json (canonical; regen via extract_catalog.py) ──
_CAT = json.load(open(os.path.join(os.path.dirname(__file__), "catalog.json"), encoding="utf-8"))
CARD_CATALOG = {n: {"pow": c["pow"], "rarity": c["rarity"]} for n, c in _CAT["cards"].items() if not c.get("opp")}
CARD_FULL = _CAT["cards"]   # every card incl. opponent-only (for the engine)

# 8/5/26: client consolidated its 5-tier rarity scheme down to 4 (genesis -> apex, uncommon folded
# into common) some time ago -- confirmed via a fresh extract_catalog.py run against the real
# client: {'rare','apex','ultra','common'} are the only rarities in play, zero cards anywhere carry
# genesis/uncommon. Mapped 1:1 onto the new tier that inherited each old tier's role: apex takes
# genesis's numbers (it's now the rarest/most-exclusive tier), ultra/rare/common keep their own
# original numbers unchanged, uncommon is simply gone (dropped, not merged into common's number --
# common's own number is unchanged from before the consolidation).
EDITIONS = {"apex": 100, "ultra": 1000, "rare": 2500, "common": 5000}
RARITY_BASE = {"apex": 100, "ultra": 60, "rare": 30, "common": 4}

# STARTER SET — the fixed 10 cards every player begins with. Because everyone owns them,
# they are excluded from the market entirely (never listed, never sellable). Final list TBD by design.
STARTER_DECK = list(_CAT["starter"])   # from catalog.json
STARTER_SET = set(STARTER_DECK)
def is_starter(t): return t in STARTER_SET

# ── currency (final model) — Signal ◈ = card currency (earn/play + packs + market);
#    Forge ❖ = premium (real money → cosmetics), one-way convertible to Signal. NO cash-out. ──
FORGE_TO_SIGNAL = 100            # 1 ❖ Forge → 100 ◈ Signal (one-way)
FORGE_TIERS = {                  # real-money Forge purchase tiers (payment processor is a future step)
    "spark":   {"usd": 4.99,  "forge": 50},
    "ember":   {"usd": 9.99,  "forge": 120},
    "blaze":   {"usd": 24.99, "forge": 350},
    "inferno": {"usd": 49.99, "forge": 800},
    "crucible":{"usd": 99.99, "forge": 2000},
}

def card_pow(t):    return CARD_CATALOG.get(t, {}).get("pow", 8)
def card_rarity(t): return CARD_CATALOG.get(t, {}).get("rarity", "common")
def edition_of(t):  return EDITIONS.get(card_rarity(t), 1000)
def card_cost(t):   return _CAT["costOverride"].get(t, CARD_FULL.get(t, {}).get("cost", 2))

# 8/5/26 Milestone A: rarity ordinal ranking for 3 Conditions (Rarity Reckoning/Commons' Revolt/
# Legends' Clash). Hand-maintained here (not extracted) because it's a fixed design ranking, not
# per-card data -- same category as EDITIONS/RARITY_BASE above. Client's own RARITY_ORDER
# (index.html:10597) still carries the dead uncommon:3 key too; harmless (no card is ever uncommon).
RARITY_ORDER = {"apex": 0, "ultra": 1, "rare": 2, "common": 4}

# ── Bloodlines Clash camp system (client index.html:5386-5405) ──
# RACE_CAMP/CAMP_BEATS are fixed design constants (mirrors client exactly); CARD_RACE (72 explicit
# entries) comes from catalog.json (extract_catalog.py) since it's real per-card data. Cards with
# no CARD_RACE entry fall through to a deterministic hash-spread across the 3 camps -- ~80 of 152
# collection cards have no race lore yet, and treating them all as 'Human'/Amageras would make
# Bloodlines Clash a near no-op (see the client's own comment at the same spot). Ported faithfully,
# NOT reapproximated -- differential-verified against a live jsc run of the real campOf() for all
# 152 COLLECTION cards (server/verify_camp.py), 0 mismatches.
CARD_RACE = _CAT.get("cardRace", {})
REMNANT_POW = _CAT.get("remnantPow", {})
TRIGGERS = _CAT.get("triggers", {})                    # fire off the top of the deck on a LOST duel
OPTIONAL_HAND_RETURN = _CAT.get("optionalHandReturn", {})   # e.g. Kravyn the Collector: onWin/onCloseLoss
RACE_CAMP = {
    "Human": "Amageras", "Kaldrei": "Amageras", "Kaidrun": "Amageras", "Celestial": "Amageras", "Construct": "Amageras", "Dreikan": "Amageras",
    "Marrowen": "Omitsuki", "Nightclaw": "Omitsuki", "Undying": "Omitsuki", "Revenant": "Omitsuki",
    "Vysh'ra": "Kitanoo", "N'imkatta": "Kitanoo", "Wrothlan": "Kitanoo", "Dragonkin": "Kitanoo", "Beast": "Kitanoo",
    "Spirit": "Kitanoo", "Fae": "Kitanoo", "Dractyl": "Kitanoo", "Thennlar": "Kitanoo", "Xylotes": "Kitanoo",
}
CAMP_BEATS = {"Amageras": "Omitsuki", "Omitsuki": "Kitanoo", "Kitanoo": "Amageras"}
_CAMPS_FALLBACK = ["Amageras", "Omitsuki", "Kitanoo"]

def _name_hash(s):
    """Exact port of the client's _nameHash: h=(h<<5)-h+charCode, coerced to int32 each step, abs'd."""
    h = 0
    for ch in str(s or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        if h >= 0x80000000: h -= 0x100000000
    return abs(h)

def race_of(name): return CARD_RACE.get(name, "Human")
def camp_of(name):
    if name in CARD_RACE: return RACE_CAMP.get(race_of(name), "Amageras")
    return _CAMPS_FALLBACK[_name_hash(name) % 3]
def camp_beats(a, b): return CAMP_BEATS.get(a) == b

# ── auth ──
def new_salt():  return secrets.token_hex(16)
def new_token(): return secrets.token_urlsafe(32)
def new_uid(t):  return "sf-" + "".join(ch for ch in t if ch.isalnum())[:10] + "-" + secrets.token_hex(4)
def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()

# ── living-card traits (server mirror; capped, a subset of the client set) ──
def trait_power_bonus(rec):
    b = 0
    if rec["d"] >= 3:  b += 2   # Scarred
    if rec["ok"] >= 8: b += 1   # Loyal
    if rec["k"] + rec["d"] >= 25: b += 1  # Veteran
    return min(4, b)

def is_feared(rec):      return rec["k"] >= 15
def is_untouchable(rec): return rec["d"] == 0 and rec["k"] >= 8
def is_bloodthirsty(rec):return rec["k"] >= 25

# ── ONE ACTIVE TRAIT per card (server mirror of the client equip model — no stacking) ──
_ACTIVE_TRAITS = [   # (id, pow, earn-predicate, active-condition|None); pow 0 = effect trait
    ("scarred",      1, lambda r: r["d"] >= 3,            lambda x: x.get("lastLose") or x.get("losses",0) > x.get("wins",0)),
    ("loyal",        1, lambda r: r["ok"] >= 8,           lambda x: x.get("wins",0) > x.get("losses",0)),
    ("veteran",      1, lambda r: r["k"] + r["d"] >= 25,  lambda x: (x.get("wins",0)+x.get("losses",0)) >= 2),
    ("untouchable",  0, lambda r: r["d"] == 0 and r["k"] >= 8, None),
    ("bloodthirsty", 0, lambda r: r["k"] >= 25,           None),
    ("feared",       0, lambda r: r["k"] >= 15,           lambda x: x.get("oppDeaths",1)==0 or x.get("oppKills",0) < x.get("myKills",0)),
]
_ACTIVE_PRIORITY = {"scarred":6,"untouchable":5,"bloodthirsty":4,"loyal":3,"veteran":3,"feared":2}
def active_trait(rec, equipped=None, ctx=None):
    """The single conditional trait: {id, pow, active}. active = its situational condition is met now.
    With ctx, auto-selection prefers a currently-active trait; equipped choice is honored (dormant if unmet)."""
    ctx = ctx or {}
    def _act(cond): return True if cond is None else bool(cond(ctx))
    earned = [(tid, pw, cond) for tid, pw, test, cond in _ACTIVE_TRAITS if test(rec)]
    if not earned: return None
    if equipped:
        for tid, pw, cond in earned:
            if tid == equipped: return {"id": tid, "pow": pw, "active": _act(cond)}
    earned.sort(key=lambda e: (e[1], _ACTIVE_PRIORITY.get(e[0], 0)), reverse=True)
    for tid, pw, cond in earned:
        if _act(cond): return {"id": tid, "pow": pw, "active": True}
    tid, pw, cond = earned[0]
    return {"id": tid, "pow": pw, "active": False}

# ── authoritative duel resolution (server decides; client cannot) ──
def resolve_duel(base_pow, rec, opp_pow, equipped=None, ctx=None):
    at = active_trait(rec, equipped, ctx)      # ONE conditional trait (context-free call -> pow traits stay dormant)
    player, opp, untouchable = base_pow, opp_pow, False
    if at and at.get("active"):
        if at["pow"]:                        player += at["pow"]
        elif at["id"] == "feared":           opp -= 1
        elif at["id"] == "untouchable":      untouchable = True
    if player > opp:
        outcome = "win"
    elif player < opp:
        outcome = "tie" if untouchable else "lose"  # Untouchable saves a would-be loss
    else:
        outcome = "tie"
    reward = {"signal": 0, "rp": 0}
    if outcome == "win":
        reward = {"signal": 40, "rp": 20}
    return {"outcome": outcome, "player_pow": player, "opp_pow": opp, "reward": reward}

# ── legend appraisal (server-authoritative; subset of client legendScore) ──
def legend_score(t, rec, mast):
    k, d = rec["k"], rec["d"]
    tot = k + d
    wr = round(k / tot * 100) if tot else 0
    s = RARITY_BASE.get(card_rarity(t), 4)
    s += k * 2 + min(40, round(wr * 0.4))
    if d == 0 and k >= 5: s += 40
    if mast:
        s += mast.get("best_level", 1) * 8
        s += mast.get("wins", 0) * 18 + mast.get("flawless", 0) * 14
    s -= min(d, 10) * 3
    return max(0, round(s))

LEGEND_TIERS = [(550,"Mythic"),(320,"Legendary"),(180,"Renowned"),(80,"Notable"),(0,"Unproven")]
def legend_tier(score):
    for m, n in LEGEND_TIERS:
        if score >= m: return n
    return "Unproven"

# ── Phase 4: Ascension roster helpers ──
ROOF_MAP = _CAT.get("roofMap", {})
# index.html:12990-12993 ascHasDMAbility()/ascChampionEligible() -- the union of both DM tables'
# KEYS is all that's needed for eligibility (whether a card HAS a DM ability, not what it does --
# actually invoking a DM ability during a Rite is task #382, an open design question, still not built).
DM_NAMES = set(_CAT.get("dmNames", {}).keys())
def roof_of(name): return ROOF_MAP.get(name) or []
def asc_champion_eligible(name, is_avatar_bespoke=False):
    return bool(is_avatar_bespoke or name in DM_NAMES)

def hash_str(s):
    """Exact port of the client's hashStr() (index.html:10603): h=(h*31+charCode)>>>0, i.e.
    unsigned 32-bit wraparound every step. NOT the same algorithm as _name_hash() above (that one
    is signed-then-abs, `|0` + Math.abs) despite sharing the *31 core -- confirmed by reading both
    real client functions side by side, not assumed from the shared multiplier. Used by
    ascGenericBaseStats() for deterministic (non-random) per-card stat jitter."""
    h = 0
    for ch in str(s or ""):
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h

_ASC_RARITY_HP = {"common": 100, "rare": 112, "ultra": 122, "apex": 132}
_ASC_RARITY_SPD = {"common": 9, "rare": 10, "ultra": 10, "apex": 11}
def asc_generic_base_stats(name):
    """index.html:13000-13009 ascGenericBaseStats(), exact."""
    pow_ = card_pow(name)
    rarity = card_rarity(name)
    atk = max(14, min(40, round(16 + pow_ * 0.55)))
    h = hash_str(name)
    hp = max(60, _ASC_RARITY_HP.get(rarity, 108) + (h % 13) - 6)
    spd = max(6, _ASC_RARITY_SPD.get(rarity, 9) + ((h // 13) % 5) - 2)
    return {"hp": hp, "atk": atk, "spd": spd}

# index.html:13020-13027 ASC_ROOF_KIT/ASC_ROOFLESS_KIT -- one signature move per Roof keyword for
# generic units (never learns more; hand-maintained here like RALLY/LINGERING_SUPPORTS, small fixed
# design constants, not per-card data that needs extract_catalog.py).
ASC_ROOF_KIT = {
    "Vajra":   {"kind": "buff",  "power": 0.35, "dur": 2, "uses": 2, "name": "Surge",     "desc": "An ally strikes with +35% ATK for 2 turns."},
    "Astra":   {"kind": "dmg",   "power": 42,             "uses": 2, "name": "Reckoning", "desc": "A heavy strike on one foe."},
    "Nirmāṇa": {"kind": "heal",  "power": 36,             "uses": 2, "name": "Ward",      "desc": "Restore an ally's HP."},
    "Bandha":  {"kind": "vuln",  "power": 0.3,  "dur": 3, "uses": 2, "name": "Bind",      "desc": "A foe takes +30% damage for 3 turns."},
    "Māyā":    {"kind": "guard", "power": 0.3,  "dur": 2, "uses": 2, "name": "Shift",     "desc": "The party takes 30% less damage for 2 turns."},
}
ASC_ROOFLESS_KIT = {"kind": "dmg", "power": 32, "uses": 2, "name": "Strike", "desc": "A plain, dependable strike."}
_ASC_ROOF_ROLE = {"Vajra": "Empowered", "Astra": "Striker", "Nirmāṇa": "Warden", "Bandha": "Binder", "Māyā": "Shifter"}

def asc_generic_role(name):
    roofs = roof_of(name)
    return _ASC_ROOF_ROLE.get(roofs[0], "Wanderer") if roofs else "Wanderer"

def asc_generic_ability(name):
    roofs = roof_of(name)
    kit = ASC_ROOF_KIT.get(roofs[0], ASC_ROOFLESS_KIT) if roofs else ASC_ROOFLESS_KIT
    first = (name or "").split(",")[0].split(" ")[0] or name
    out = dict(kit)
    out["name"] = f"{first}'s {kit['name']}"
    return out

# ── Phase 4.3 (owner, 8/6/26): "more attack options... ideally status giving buff or debuffs
# moves... a way to swap attacks out per unit". Before this, EVERY non-bespoke unit (140+ of ~152
# cards) was permanently stuck at 1 move (ASC_ROOF_KIT's signature) forever, at any level --
# ASC_MOVES/ASC_MOVES_CAP only ever covered the 11 hand-authored ASC_UNITS, so "basic attack + one
# special move" wasn't a slow-leveling artifact, it was a hard ceiling for almost the whole roster.
# One extra 3-move kit + a capstone per Roof (mirrors ASC_MOVE_UNLOCK's 3/6/9/12 gates exactly like
# the bespoke units), deliberately mixing kinds so every generic unit gets real buff/debuff variety
# to build a loadout around, not just more damage.
#
# CORRECTION, same day: this was first shipped hand-invented server-side ONLY, with no client
# counterpart -- a real violation of "the client is truth" (confirmed: extract_catalog.py never
# had a source to pull these from, because index.html had nothing but the single-move ASC_ROOF_KIT).
# Fixed by authoring the identical values for real in index.html (ascGenericMoves(), right after
# ASC_ROOFLESS_KIT) and wiring them into the client's own ascUnitMoveList() as a generic-unit
# fallback -- these Python dicts are now a genuine, verified, byte-identical manual port of real
# client constants, following the SAME documented "small fixed design constant, no extraction
# pipeline needed" precedent already established for ASC_ROOF_KIT/ASC_ROOFLESS_KIT themselves
# (and RALLY/LINGERING_SUPPORTS in engine.py) -- not an invention anymore.
ASC_ROOF_EXTRA = {
    "Vajra": [
        {"kind": "dmg", "power": 40, "uses": 2, "name": "Overwhelm", "desc": "A forceful strike on one foe."},
        {"kind": "vuln", "power": 0.3, "dur": 2, "uses": 2, "name": "Expose", "desc": "A foe takes +30% damage for 2 turns."},
        {"kind": "guard", "power": 0.25, "dur": 2, "uses": 2, "name": "Brace", "desc": "The party takes 25% less damage for 2 turns."},
    ],
    "Astra": [
        {"kind": "buff", "power": 0.3, "dur": 2, "uses": 2, "name": "Focus", "desc": "An ally strikes with +30% ATK for 2 turns."},
        {"kind": "dot", "power": 10, "dur": 3, "uses": 2, "name": "Rend", "desc": "A foe bleeds 10/turn for 3 turns."},
        {"kind": "execute", "power": 46, "uses": 2, "name": "Finish", "desc": "A heavy strike, devastating against a weakened foe."},
    ],
    "Nirmāṇa": [
        {"kind": "guard", "power": 0.3, "dur": 2, "uses": 2, "name": "Aegis", "desc": "The party takes 30% less damage for 2 turns."},
        {"kind": "buff", "power": 0.25, "dur": 2, "uses": 2, "name": "Rally", "desc": "An ally strikes with +25% ATK for 2 turns."},
        {"kind": "vuln", "power": 0.25, "dur": 2, "uses": 2, "name": "Unveil", "desc": "A foe takes +25% damage for 2 turns."},
    ],
    "Bandha": [
        {"kind": "dot", "power": 12, "dur": 3, "uses": 2, "name": "Shackle", "desc": "A foe bleeds 12/turn for 3 turns."},
        {"kind": "dmg", "power": 38, "uses": 2, "name": "Crush", "desc": "A heavy strike on one foe."},
        {"kind": "buff", "power": 0.3, "dur": 2, "uses": 2, "name": "Fortify", "desc": "An ally strikes with +30% ATK for 2 turns."},
    ],
    "Māyā": [
        {"kind": "buff", "power": 0.3, "dur": 2, "uses": 2, "name": "Warp Strike", "desc": "An ally strikes with +30% ATK for 2 turns."},
        {"kind": "vuln", "power": 0.3, "dur": 2, "uses": 2, "name": "Unmake", "desc": "A foe takes +30% damage for 2 turns."},
        {"kind": "dmg", "power": 40, "uses": 2, "name": "Mirror Blow", "desc": "A forceful strike on one foe."},
    ],
}
ASC_ROOFLESS_EXTRA = [
    {"kind": "buff", "power": 0.25, "dur": 2, "uses": 2, "name": "Grit", "desc": "An ally strikes with +25% ATK for 2 turns."},
    {"kind": "vuln", "power": 0.25, "dur": 2, "uses": 2, "name": "Weaken", "desc": "A foe takes +25% damage for 2 turns."},
    {"kind": "dmg", "power": 36, "uses": 2, "name": "Heavy Strike", "desc": "A forceful strike on one foe."},
]
ASC_ROOF_CAPSTONE = {
    "Vajra": {"kind": "aoe", "power": 34, "uses": 1, "name": "Ascendant Surge", "desc": "A powerful blow to every foe."},
    "Astra": {"kind": "execute", "power": 60, "uses": 1, "name": "Killing Blow", "desc": "A devastating strike, lethal to a weakened foe."},
    "Nirmāṇa": {"kind": "heal", "power": 55, "uses": 1, "name": "Sanctuary", "desc": "A powerful restoration for one ally."},
    "Bandha": {"kind": "dot", "power": 20, "dur": 3, "uses": 1, "name": "Unbreakable Bind", "desc": "A foe bleeds heavily for 3 turns."},
    "Māyā": {"kind": "guard", "power": 0.4, "dur": 3, "uses": 1, "name": "Reality Shift", "desc": "The party takes 40% less damage for 3 turns."},
}
ASC_ROOFLESS_CAPSTONE = {"kind": "aoe", "power": 30, "uses": 1, "name": "Last Stand", "desc": "A powerful blow to every foe."}

# ── Phase 4.4 (owner, 8/6/26): Ascension companions are no longer "any owned card" -- a separate,
# persistent per-account pool, starting fixed and growing via summon or per-unit progression.
# "only deckmasters appearing as playable avatars" is already true (asc_champion_eligible above) --
# this table/pricing is companion-only, deliberately "separate yet intertwined" per the owner.
#
# Starting 5, owner-confirmed "fixed curated list": all 5 are bespoke ASC_UNITS (full hand-authored
# move kits, not the generic Roof-kit fallback) AND all 5 are in STARTER_SET (guaranteed-owned by
# every account) -- so a fresh account always has a real, working, ownership-luck-free companion
# pool from turn one.
ASC_ALLY_POOL_STARTERS = ["Hanse Waltz", "Uso Oso", "Veronica", "Lagertha Waltz", "King Joris"]
# Deliberately NOT set equal to len(ASC_ALLY_POOL_STARTERS) -- that would leave zero headroom to
# ever summon anything until a unit first grinds to the progression threshold below, a dead-on-
# arrival chicken-and-egg gap the owner's framing doesn't intend ("starting 5" + "summon for
# ascension allies" reads as summoning being immediately usable, not locked behind progression
# first). 10 leaves exactly 5 summonable slots open from day one; flagged as my own number, not
# owner-specified, since only the starting-pool-size and the growth-threshold CONCEPT were confirmed.
ASC_ALLY_POOL_BASE_CAP = 10

# Pricing, owner-confirmed "signal and forge": two Signal paths (a cheap random pull from your own
# not-yet-pooled owned cards, and a pricier targeted pick -- but ONLY for a card you own that's
# ALSO Deck-Master-eligible, matching the owner's "you can still summon a [DM] character... you
# don't have in your pool yet" carve-out) plus one Forge path (targeted, ANY owned not-yet-pooled
# unit, no DM requirement -- the harder currency buys the guarantee). None of these mint a tradeable
# asset (owner: "ascension units dont have secondary market tradeability... anything bought with
# forge needs to be variant rules") -- pool membership is just a row in asc_ally_pool, nothing to
# trade in the first place, on either currency path.
ASC_SUMMON_SIGNAL_RANDOM_PRICE = 500
ASC_SUMMON_SIGNAL_DM_TARGETED_PRICE = 800
ASC_SUMMON_FORGE_TARGETED_PRICE = 150

# Per-unit progression unlock, owner-confirmed "per unit as your own growth system implies": ONE
# extra pool-cap slot, granted once, the first time a SPECIFIC pooled unit crosses either threshold
# (asc_prog's existing level field, or its new kills counter -- see asc.py's kill-tally comment for
# how kills are counted). This is the vaguest clause in the owner's request ("unlock certain
# progression things when you need them") -- flagged explicitly in the report back, since a pool-cap
# reading is my best interpretation, not a confirmed spec.
ASC_POOL_GROWTH_LEVEL = 5
ASC_POOL_GROWTH_KILLS = 20

def asc_generic_moves(name):
    """The 3 extra moves + 1 capstone a generic unit can unlock at level 3/6/9/12 -- mirrors the
    bespoke ASC_MOVES/ASC_MOVES_CAP shape exactly, named after the unit like asc_generic_ability()."""
    roofs = roof_of(name)
    roof = roofs[0] if roofs else None
    extra = ASC_ROOF_EXTRA.get(roof, ASC_ROOFLESS_EXTRA)
    cap = ASC_ROOF_CAPSTONE.get(roof, ASC_ROOFLESS_CAPSTONE)
    first = (name or "").split(",")[0].split(" ")[0] or name
    return ([dict(m, name=f"{first}'s {m['name']}") for m in extra], dict(cap, name=f"{first}'s {cap['name']}"))

# ── Phase 3: card packs (index.html:9619-9627) — hand-maintained here, not extracted, because
# these are shop-config constants (price/odds), not per-card game data. All Signal-priced (the
# client's "Premium" tier is still Signal, not Forge -- Forge-priced summons are the cosmetic
# gacha/variant system, a separate mechanic not built server-side yet, deliberately: it mints
# skins of existing cards via its own serial-numbered variant system, not new base cards, and has
# its own independent pity (gachaPity, per-banner, cap 60) -- conflating it with card packs here
# would be the "don't conflate two similar-looking mechanics" mistake).
PACKS = [
    {"id": "std", "name": "Legends Reborn Booster", "price": 150, "tenX": True, "odds": {"common": 91.6, "rare": 7.6, "ultra": 0.8}},
    {"id": "elite", "name": "Legends Reborn Elite Cache", "price": 1500, "odds": {"rare": 77.7, "ultra": 20, "apex": 2.3}},
]
# 8/6/26: all 3 tiers were byte-identical odds despite a 2000/5000/6000 price spread -- fixed to
# match the client (index.html:9683), where price now actually buys better odds and Mythic Rite
# really does carry the best apex rate in the shop, matching its own printed blurb.
PREMIUM_PACKS = [
    {"id": "fkindle", "name": "Kindled Cache", "price": 2000, "odds": {"rare": 88, "ultra": 10, "apex": 2}},
    {"id": "fforge", "name": "Forgemaster Vault", "price": 5000, "odds": {"rare": 85, "ultra": 11.5, "apex": 3.5}},
    {"id": "fmythic", "name": "Mythic Rite", "price": 6000, "odds": {"rare": 80, "ultra": 15, "apex": 5}},
]
ALL_PACKS = {p["id"]: p for p in PACKS + PREMIUM_PACKS}
# index.html:9649: guaranteed Ultra+ within 20 pulls, guaranteed Apex within 80 -- both counters
# GLOBAL per account (not per-pack-id), exactly mirroring the client's single pair of module vars.
PITY_ULTRA, PITY_APEX = 20, 80
_RARITY_ORDER_FLOOR = {"apex": 0, "ultra": 1, "rare": 2, "common": 3}

CARDS_BY_RARITY = {}
for _n, _c in CARD_CATALOG.items():
    CARDS_BY_RARITY.setdefault(_c["rarity"], []).append(_n)

def roll_pack_rarity(pack, avail, pity_ultra, pity_apex):
    """Exact port of index.html:9649-9659 rollPackRarity(). avail: the subset of pack['odds']
    rarities that still have at least one mintable card (caller-computed, since only the server
    knows real mint state). Returns (rarity, new_pity_ultra, new_pity_apex)."""
    pity_ultra += 1; pity_apex += 1
    has_apex = "apex" in avail
    has_ultra = "ultra" in avail
    if has_apex and pity_apex >= PITY_APEX:
        rar = "apex"
    elif (has_ultra or has_apex) and pity_ultra >= PITY_ULTRA:
        rar = "apex" if (has_apex and random.random() < 0.08) else ("ultra" if has_ultra else "apex")
    else:
        total = sum(pack["odds"].get(r, 0) for r in avail)
        roll = random.random() * total
        rar = avail[-1] if avail else "common"
        for r in avail:
            roll -= pack["odds"].get(r, 0)
            if roll <= 0: rar = r; break
    if rar == "apex": pity_apex = 0; pity_ultra = 0
    elif rar == "ultra": pity_ultra = 0
    return rar, pity_ultra, pity_apex

def apply_bundle_floor(drawn, pack, is_premium, room_fn):
    """index.html:9679-9691 -- any multi-pack open guarantees >=1 Rare+ (basic) or >=1 Ultra+
    (premium), upgrading the single weakest roll in the batch if none met the floor. No-ops for a
    single pull (n==1) or a pack whose odds don't include the floor rarity at all."""
    if len(drawn) <= 1: return drawn
    floor = "ultra" if is_premium else "rare"
    if floor not in pack["odds"] or not room_fn(floor): return drawn
    if any(_RARITY_ORDER_FLOOR.get(r, 9) <= _RARITY_ORDER_FLOOR.get(floor, 9) for r in drawn): return drawn
    weakest = max(range(len(drawn)), key=lambda i: _RARITY_ORDER_FLOOR.get(drawn[i], 9))
    drawn[weakest] = floor
    return drawn
