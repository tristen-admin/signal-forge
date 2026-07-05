"""
Signal Forge — Tier 0 authoritative rules.
The SERVER owns outcomes, rewards, traits, and appraisals. A subset of the client
rule-set, deliberately; bringing it to full parity with the client resolve() is a
tracked follow-up. Pure functions + catalog only (no I/O).
"""
import hashlib, secrets

# ── card catalog (subset of the client's set; full import is a follow-up) ──
CARD_CATALOG = {
    # ── STARTER SET — every player is granted these; owned by all → never tradeable ──
    "Ruffius Rufeldro": {"pow": 5,  "rarity": "common"},
    "Bixie Bee":        {"pow": 1,  "rarity": "common"},
    "Malia":            {"pow": 10, "rarity": "common"},
    "Moro":             {"pow": 9,  "rarity": "common"},
    "Melanie":          {"pow": 1,  "rarity": "common"},
    "Heir of Kaiga":    {"pow": 3,  "rarity": "common"},
    "Tange Sazen":      {"pow": 15, "rarity": "rare"},
    "Forgemask":        {"pow": 14, "rarity": "rare"},
    "Valcarion":        {"pow": 13, "rarity": "rare"},
    "Ella Ballora":     {"pow": 14, "rarity": "ultra"},
    # ── non-starter — earnable / tradeable on the market ──
    "Kotei":                     {"pow": 18, "rarity": "genesis"},
    "Akatosh, the Golden Dragon":{"pow": 21, "rarity": "genesis"},
    "Ahdor":                     {"pow": 11, "rarity": "genesis"},
    "Darwin":                    {"pow": 15, "rarity": "genesis"},
    "Arch-Grim Korrin":          {"pow": 14, "rarity": "rare"},
    "Lagertha Waltz":            {"pow": 14, "rarity": "rare"},
    "Veronica":                  {"pow": 10, "rarity": "common"},
}
EDITIONS = {"genesis": 100, "ultra": 1000, "rare": 2500, "uncommon": 4000, "common": 5000}
RARITY_BASE = {"genesis": 100, "ultra": 60, "rare": 30, "uncommon": 12, "common": 4}

# STARTER SET — the fixed 10 cards every player begins with. Because everyone owns them,
# they are excluded from the market entirely (never listed, never sellable). Final list TBD by design.
STARTER_DECK = ["Ruffius Rufeldro", "Bixie Bee", "Malia", "Moro", "Melanie",
                "Heir of Kaiga", "Tange Sazen", "Forgemask", "Valcarion", "Ella Ballora"]
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
