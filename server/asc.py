"""
Signal Forge — authoritative Ascension (The Rite) run engine.
Server-side port of the client roguelike: anoint an avatar, travel a 6-tier branching map
(Duel/Elite/Sanctum/Relic Shrine/Boss), channel cards to break champions, claim boons, take scars.
Mastery (avatarBond) is written here so it can't be faked client-side; it feeds traits + Legend.
Runs are in-memory (lost on restart) — persistence is a tracked follow-up.
"""
import random
import engine

ASC_BOONS = [
    {"id": "might",    "name": "Warlord's Might", "desc": "+3 avatar power in every duel"},
    {"id": "full",     "name": "Full Channel",    "desc": "channeled cards give FULL power"},
    {"id": "aegis",    "name": "Aegis",           "desc": "first lost round each duel is negated"},
    {"id": "ferocity", "name": "Ferocity",        "desc": "+1 extra level per champion cleared"},
    {"id": "slayer",   "name": "Giant-Slayer",    "desc": "+4 power vs Elite & Boss"},
    {"id": "echo",     "name": "Echoing Rite",    "desc": "break a champion → ascend +2"},
    {"id": "mend",     "name": "Mending Light",   "desc": "restore 2 vitality"},
    {"id": "vigor",    "name": "Vigor",           "desc": "+2 max vitality"},
]
_CHAMP_POOL = [n for n in engine.CATALOG if n not in ("Bixie Bee", "Melanie")]

def _mk_node(t, tier):
    champ = random.choice(_CHAMP_POOL)
    pw = 8 + tier * 3 + (4 if t == "elite" else 0) + (9 if t == "boss" else 0)
    vit = 4 if t == "boss" else 3 if t == "elite" else 2
    return {"type": t, "champ": champ, "pow": pw, "vit": vit, "tier": tier}

def gen_map():
    TIERS, m = 6, []
    for t in range(TIERS):
        if t == TIERS - 1:
            m.append([_mk_node("boss", t)]); continue
        nodes = []
        for _ in range(2 + (t % 2)):
            if t == 0:
                ty = "duel"
            else:
                r = random.random()
                ty = "duel" if r < 0.5 else "elite" if r < 0.72 else "boon" if r < 0.88 else "sanctum"
            nodes.append(_mk_node(ty, t))
        if not any(n["type"] in ("duel", "elite") for n in nodes):
            nodes[0] = _mk_node("duel", t)
        m.append(nodes)
    return m

def new_run(avatar_type, base_pow):
    return {"avatar": avatar_type, "base": base_pow, "level": 1, "vit": 5, "maxVit": 5,
            "boons": [], "map": gen_map(), "tier": 0, "node": None, "champVit": 0,
            "aegisUsed": False, "flawless": True, "cleared": 0, "done": False,
            "result": None, "phase": "pick"}

def channel(run, card_pow):
    node = run["node"]
    full = "full" in run["boons"]
    my = run["base"] + (run["level"] - 1) * 3 + (card_pow if full else round(card_pow * 0.5))
    if "might" in run["boons"]: my += 3
    if "slayer" in run["boons"] and node["type"] in ("elite", "boss"): my += 4
    champ = node["pow"] + random.randint(0, 3)
    if my >= champ:
        run["champVit"] -= 1
        run["level"] += 2 if "echo" in run["boons"] else 1
        return {"won": True, "my": my, "champ": champ}
    if "aegis" in run["boons"] and not run["aegisUsed"]:
        run["aegisUsed"] = True
        return {"won": False, "my": my, "champ": champ, "aegis": True}
    run["vit"] -= 1; run["flawless"] = False
    return {"won": False, "my": my, "champ": champ}

def boon_choices(run):
    avail = [b for b in ASC_BOONS if b["id"] in ("mend", "vigor") or b["id"] not in run["boons"]]
    random.shuffle(avail)
    return avail[:3]

def apply_boon(run, bid):
    if bid == "mend": run["vit"] = min(run["maxVit"], run["vit"] + 2)
    elif bid == "vigor": run["maxVit"] += 2; run["vit"] += 2
    elif bid not in run["boons"]: run["boons"].append(bid)

def public(run):
    """Client-safe view of the run."""
    return {"avatar": run["avatar"], "level": run["level"], "vit": run["vit"], "maxVit": run["maxVit"],
            "boons": run["boons"], "tier": run["tier"], "cleared": run["cleared"], "flawless": run["flawless"],
            "phase": run["phase"], "done": run["done"], "result": run["result"],
            "map": [[{"type": n["type"], "champ": n["champ"], "pow": n["pow"], "vit": n["vit"]} for n in tier] for tier in run["map"]],
            "node": ({"type": run["node"]["type"], "champ": run["node"]["champ"], "pow": run["node"]["pow"],
                      "champVit": run["champVit"], "vit": run["node"]["vit"]} if run["node"] else None)}
