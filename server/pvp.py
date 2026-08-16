"""Phase 5.1 (8/6/26) — real two-player PvP: a queue, a paired match session, and a duel
resolved from BOTH players' committed cards.

Why this module exists at all. Before it, every match endpoint in app.py was solo-vs-bot on the
server side too: h_match_start stamped a session with a single `user_id`, and h_match_commit drew
the opposing card with `random.choice(engine.opponent_pool())`. Wiring the client to those would
have produced a bot match played over HTTP. Nothing two-player existed to wire to.

THE HARD PART — joining two one-sided resolutions.
engine.resolve() owns ONE player's match state (their Charge, Winners Circle, Remnants, bonds,
rear-guards) and treats the opponent as a bare card dict with no state of its own. That is right
for a bot and wrong for a real person. Forking a parallel two-sided resolver would re-introduce
precisely the client/server drift this entire resync existed to eliminate, so instead this module
runs the SAME resolver once per side and joins the results:

  1. dry pass, each side, no override -> each player's TRUE power, computed from their own
     complete state (their rear-guards, their Remnants, their Charge, their card's rules).
  2. provisional pass, each side, on a deep copy, with opp_pow_override set to the other side's
     true power -> each side's locally-resolved outcome, with its own guards applied.
  3. reconcile. The resolution guards (Last Stand, Untouchable, Record Guard, Regenerating Horror,
     Ahdor, Bulwark of Bones, Ledger Ward) only ever convert a LOSS into a TIE — never into a win.
     So if the two passes disagree, exactly one thing happened: a defender's guard denied the
     attacker their win. The tie is the truthful joint outcome. Rule: if either side resolved to
     a tie, both are a tie; otherwise they are already mirror images.
  4. real pass, each side, with both opp_pow_override and forced_outcome -> state mutated once,
     consistently, on the joint result.

DETERMINISM. engine.resolve() contains real randomness (chaos Conditions at engine.py:489/529/
534-535, and the lost-a-duel spell draw at :660). Running it three times per side would otherwise
give three different answers and the reconciliation would be nonsense. Every call is therefore
wrapped in _seeded(), which seeds the global RNG from (match id, duel number, side) and restores
the previous generator state afterwards, so a side's dry/provisional/real passes are bit-identical
to each other while nothing else in the process has its random stream disturbed.

KNOWN APPROXIMATION, not a silent one: the Force Swap condition (engine.py:534-535) swaps the
opponent's card by drawing from engine.opponent_pool() — the whole catalog — rather than from the
real opposing player's hand. Under seeding both sides at least agree on what it swapped to, so the
match stays consistent; it is simply not yet faithful to a real opponent's hand. Fixing it means
teaching resolve() about a second real hand, which is the two-sided-resolver refactor this module
deliberately avoids for now.

Transport is short-interval polling, per the owner's decision — no WebSockets in v1. The server is
a stdlib ThreadingHTTPServer, so both players can be inside this module concurrently; _LOCK
serialises every read-modify-write of a game (both sides commit at genuinely the same moment).
"""
import copy, random, secrets, threading, time

import engine, rules, store

_LOCK = threading.RLock()

QUEUE = []       # [{"user_id","handle","best_of","joined"}] — FIFO, oldest first
GAMES = {}       # pid -> game dict (see _new_game)
CHALLENGES = {}  # code -> {"user_id","handle","owned","best_of","created"} — a pending private-match invite

QUEUE_TTL = 120.0       # a queue entry this old is stale (browser closed, tab killed); dropped on touch
GAME_TTL = 3600.0       # an untouched game is abandoned; dropped so GAMES cannot grow forever
# 8/16/26 (owner: "auto end the match when both players leave room"). GAME_TTL is a memory guard at
# an hour, far too slow to be a game rule. This is the real one: once BOTH sides have stopped
# polling for this long the match is over, so neither player can walk away leaving the other holding
# a live game -- and a stale match can never be re-entered later as if it were still running.
# Deliberately longer than the 2s poll by a wide margin so a reload, a tab switch or a brief network
# stall never ends a match somebody is still playing.
ABANDON_TTL = 45.0
CHALLENGE_TTL = 300.0   # longer than QUEUE_TTL -- sharing a code out-of-band (text/Discord) takes longer than auto-matching
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L -- easy to misread when typed from a screen or read aloud


def _seeded(seed, fn):
    """Run fn() with the global RNG seeded deterministically, then restore the previous state.
    Needed because a side's three passes must agree; see the module docstring."""
    st = random.getstate()
    random.seed(seed)
    try:
        return fn()
    finally:
        random.setstate(st)


def _new_side(user_id, handle, owned, best_of, deck_master=None):
    """`owned` is the player's real deck, already resolved by the caller (app.py owns deck_load and
    the uid->card mapping). Same shape as app.py's MATCHES session so the two stay recognisable."""
    m = engine.new_match([c["type"] for c in owned], best_of=best_of, lobby_mode=False)
    m["bonds"] = {r["pair"]: r["count"] for r in
                  store.conn().execute("SELECT pair,count FROM bonds WHERE user_id=?", (user_id,)).fetchall()}
    hand_cards, deck_cards = owned[:4], owned[4:]
    m["hand"] = [c["type"] for c in hand_cards]
    return {"user_id": user_id, "handle": handle, "m": m, "deck_master": deck_master, "seen": time.time(),
            "hand_cards": hand_cards, "deck_cards": deck_cards, "banish_cards": [],
            "winners_circle_cards": [], "commit": None, "last": None}


def _new_game(a, b, best_of):
    pid = "p_" + secrets.token_hex(8)
    g = {"id": pid, "a": a, "b": b, "bestOf": best_of, "duel": 0, "done": False,
         "winner": None, "seq": 0, "touched": time.time(),
         "condition": engine.pick_condition()}
    _reveal(g)
    GAMES[pid] = g
    return g


def _reveal(g):
    """Apply the shared Condition's reveal-time draw/discard to BOTH hands (app.py:_apply_reveal,
    same random-discard rule). One arena, one Condition — each side pays it against its own hand."""
    rv = engine.condition_reveal_effects(g["condition"])
    for s in (g["a"], g["b"]):
        for _ in range(rv.get("draw", 0)):
            if s["deck_cards"]: s["hand_cards"].append(s["deck_cards"].pop(0))
        for _ in range(rv.get("discard", 0)):
            if s["hand_cards"]: s["banish_cards"].append(s["hand_cards"].pop(random.randrange(len(s["hand_cards"]))))
        s["m"]["hand"] = [c["type"] for c in s["hand_cards"]]


def _sides(g, user_id):
    """-> (you, them) or (None, None) if this user is not in this game."""
    if g["a"]["user_id"] == user_id: return g["a"], g["b"]
    if g["b"]["user_id"] == user_id: return g["b"], g["a"]
    return None, None


# ── queue ────────────────────────────────────────────────────────────────────────────────────
def join(user_id, handle, owned, best_of, deck_master=None):
    """Pair with anyone already waiting, else take a place in the queue. Returns (status, body).

    8/7/26: Ranked (best_of==3) now prefers the closest-RP candidate already queued instead of pure
    FIFO -- at this population size there's usually 0-1 other person waiting anyway, so this mostly
    matters once it matters (multiple ranked queuers at once), and costs nothing when it doesn't
    (falls straight through to the only candidate). Casual (best_of==7) stays pure FIFO on purpose --
    it has no rank identity to honor, and speed-of-pairing is the whole point of "casual"."""
    with _LOCK:
        _sweep()
        for g in GAMES.values():
            if not g["done"] and (g["a"]["user_id"] == user_id or g["b"]["user_id"] == user_id):
                return 200, {"matched": True, "pvpId": g["id"], "already": True}
        QUEUE[:] = [q for q in QUEUE if q["user_id"] != user_id]
        my_rp = 1000
        if best_of == 3:
            row = store.conn().execute("SELECT rp FROM users WHERE id=?", (user_id,)).fetchone()
            if row: my_rp = row["rp"]
        candidates = [q for q in QUEUE if q["best_of"] == best_of]
        opp = None
        if candidates:
            opp = min(candidates, key=lambda q: abs(q.get("rp", 1000) - my_rp)) if best_of == 3 else candidates[0]
        if not opp:
            QUEUE.append({"user_id": user_id, "handle": handle, "owned": owned, "deck_master": deck_master,
                          "best_of": best_of, "joined": time.time(), "rp": my_rp})
            return 200, {"matched": False, "queued": True, "waiting": len(QUEUE)}
        QUEUE.remove(opp)
        # the player who waited is side A, so seating is by arrival and not by who called last
        g = _new_game(_new_side(opp["user_id"], opp["handle"], opp["owned"], best_of, opp.get("deck_master")),
                      _new_side(user_id, handle, owned, best_of, deck_master), best_of)
        return 200, {"matched": True, "pvpId": g["id"], "opponent": opp["handle"]}


def leave(user_id):
    with _LOCK:
        n = len(QUEUE)
        QUEUE[:] = [q for q in QUEUE if q["user_id"] != user_id]
        return 200, {"left": n != len(QUEUE)}


def _sweep():
    """Drop stale queue entries, expired challenges, and abandoned games. Called under _LOCK on
    every entry point."""
    now = time.time()
    QUEUE[:] = [q for q in QUEUE if now - q["joined"] < QUEUE_TTL]
    for code in [k for k, ch in CHALLENGES.items() if now - ch["created"] > CHALLENGE_TTL]:
        del CHALLENGES[code]
    # Both sides gone -> end it, rather than leaving a live game nobody is in.
    for g in GAMES.values():
        if g["done"]: continue
        a_seen = g["a"].get("seen", g["touched"]); b_seen = g["b"].get("seen", g["touched"])
        if now - a_seen > ABANDON_TTL and now - b_seen > ABANDON_TTL:
            g["done"] = True; g["winner"] = None; g["seq"] += 1; g["touched"] = now
            for side, other in ((g["a"], g["b"]), (g["b"], g["a"])):
                side["last"] = {"outcome": "tie", "log": ["\u23f8 match abandoned \u2014 both players left the room"]}
    for pid in [k for k, g in GAMES.items() if now - g["touched"] > GAME_TTL]:
        del GAMES[pid]


def _active_game_for(user_id):
    """-> the user's own in-progress game dict, if any, else None. A user already inside a live
    match can't also open a challenge or the random queue -- same rule join() already enforces."""
    for g in GAMES.values():
        if not g["done"] and (g["a"]["user_id"] == user_id or g["b"]["user_id"] == user_id):
            return g
    return None


def _new_code():
    while True:
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if code not in CHALLENGES:
            return code


# ── private challenges (direct invite by code, bypasses the random queue entirely) ─────────────
def create_challenge(user_id, handle, owned, best_of, target_user_id=None):
    with _LOCK:
        _sweep()
        g = _active_game_for(user_id)
        if g:
            opp = g["b"] if g["a"]["user_id"] == user_id else g["a"]
            return 200, {"matched": True, "pvpId": g["id"], "opponent": opp["handle"], "already": True}
        for code in [k for k, ch in CHALLENGES.items() if ch["user_id"] == user_id]:
            del CHALLENGES[code]   # one active challenge per user -- a new one replaces a forgotten stale one
        code = _new_code()
        CHALLENGES[code] = {"user_id": user_id, "handle": handle, "owned": owned, "best_of": best_of, "deck_master": deck_master,
                             "created": time.time(), "target_user_id": target_user_id}
        return 200, {"code": code}


def incoming_challenge(user_id):
    """-> the pending challenge (if any) a friend has aimed directly at this user, so their client
    can surface it without them ever typing a code (see h_pvp_challenge_direct in app.py)."""
    with _LOCK:
        _sweep()
        for code, ch in CHALLENGES.items():
            if ch.get("target_user_id") == user_id:
                return 200, {"code": code, "fromHandle": ch["handle"]}
        return 200, {"code": None}


def challenge_status(user_id, code):
    with _LOCK:
        _sweep()
        ch = CHALLENGES.get((code or "").strip().upper())
        if ch and ch["user_id"] == user_id:
            return 200, {"matched": False}
        # not pending any more -- either it was just joined (check for the resulting game) or expired
        g = _active_game_for(user_id)
        if g:
            opp = g["b"] if g["a"]["user_id"] == user_id else g["a"]
            return 200, {"matched": True, "pvpId": g["id"], "opponent": opp["handle"]}
        return 404, {"error": "challenge not found or expired"}


def cancel_challenge(user_id):
    with _LOCK:
        removed = False
        for code in [k for k, ch in CHALLENGES.items() if ch["user_id"] == user_id]:
            del CHALLENGES[code]
            removed = True
        return 200, {"cancelled": removed}


def join_challenge(user_id, handle, owned, code, deck_master=None):
    with _LOCK:
        _sweep()
        g = _active_game_for(user_id)
        if g:
            opp = g["b"] if g["a"]["user_id"] == user_id else g["a"]
            return 200, {"matched": True, "pvpId": g["id"], "opponent": opp["handle"], "already": True}
        key = (code or "").strip().upper()
        ch = CHALLENGES.get(key)
        if not ch: return 404, {"error": "no match found for that code"}
        if ch["user_id"] == user_id: return 400, {"error": "you can't join your own match"}
        if ch.get("target_user_id") and ch["target_user_id"] != user_id:
            return 404, {"error": "no match found for that code"}
        del CHALLENGES[key]
        g = _new_game(_new_side(ch["user_id"], ch["handle"], ch["owned"], ch["best_of"], ch.get("deck_master")),
                      _new_side(user_id, handle, owned, ch["best_of"], deck_master), ch["best_of"])
        return 200, {"matched": True, "pvpId": g["id"], "opponent": ch["handle"]}


# ── state ────────────────────────────────────────────────────────────────────────────────────
def state(user_id, pid):
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        g["touched"] = time.time()
        you["seen"] = time.time()      # per-side presence, drives the both-left rule in _sweep()
        return 200, _view(g, you, them)


def _hand_view(hand_cards):
    """Real per-card K/D on each hand card, not a display-only 0/0. The client's own kdOf() keys
    off a card's uid and falls through to 0/0 for any uid it doesn't recognise — which every online
    uid is, being a disjoint id space from the device's local save — so without this every online
    card would silently show as a fresh, untested copy regardless of its actual server record."""
    out = []
    for c in hand_cards:
        r = _record(c["uid"])
        out.append({**c, "k": r["k"], "d": r["d"]})
    return out


def _view(g, you, them):
    return {
        "pvpId": g["id"], "seq": g["seq"], "duel": g["duel"], "done": g["done"],
        "bestOf": g["bestOf"], "condition": g["condition"],
        "opponent": them["handle"],
        "you": {"score": you["m"]["playerScore"][0], "charge": you["m"]["charge"],
                "hand": _hand_view(you["hand_cards"]), "deckCount": len(you["deck_cards"]),
                "winnersCircleCount": len(you["winners_circle_cards"]),
                "spellHand": you["m"]["spellHand"], "committed": you["commit"] is not None,
                "rgSlots": engine.rg_slots(you["m"].get("matchCommits", 0))},
        "them": {"score": them["m"]["playerScore"][0], "charge": them["m"]["charge"],
                 "handCount": len(them["hand_cards"]), "deckCount": len(them["deck_cards"]),
                 "winnersCircleCount": len(them["winners_circle_cards"]),
                 "committed": them["commit"] is not None},
        "lastDuel": you["last"],
        "youWon": (g["winner"] == you["user_id"]) if g["done"] and g["winner"] else None,
        "lockedWithdraw": g["condition"] == "noretreat",
    }


# ── commit ───────────────────────────────────────────────────────────────────────────────────
def commit(user_id, pid, card_uid, rg_uids):
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        if g["done"]: return 400, {"error": "match already complete"}
        if you["commit"] is not None: return 400, {"error": "you already committed this duel"}
        g["touched"] = time.time()

        hc = next((c for c in you["hand_cards"] if c["uid"] == card_uid), None)
        if not hc: return 400, {"error": "that card is not in your hand"}
        rg_uids = [u for u in (rg_uids or []) if u != hc["uid"]]
        slots = engine.rg_slots(you["m"].get("matchCommits", 0))
        if len(rg_uids) > slots:
            return 400, {"error": f"only {slots} support slot(s) available this duel"}
        rg_cards = []
        for u in rg_uids:
            c = next((x for x in you["hand_cards"] if x["uid"] == u), None)
            if not c: return 400, {"error": f"rear-guard card {u} is not in your hand"}
            rg_cards.append(c)

        you["commit"] = {"card": hc, "rg": rg_cards}
        if them["commit"] is None:
            return 200, {"waiting": True, **_view(g, you, them)}
        _resolve_duel(g)
        return 200, {"waiting": False, **_view(g, you, them)}


def _record(uid):
    r = store.conn().execute("SELECT k,d,ok,od FROM records WHERE uid=?", (uid,)).fetchone()
    return dict(r) if r else {"k": 0, "d": 0, "ok": 0, "od": 0}


def _stage(side):
    """Remove fighter + rear-guards from hand BEFORE resolve() reads hand_len, matching the
    client's real order (index.html:6868) and app.py's own Milestone B fix."""
    cm = side["commit"]
    staged = {cm["card"]["uid"]} | {c["uid"] for c in cm["rg"]}
    side["hand_cards"] = [c for c in side["hand_cards"] if c["uid"] not in staged]
    side["m"]["hand"] = [c["type"] for c in side["hand_cards"]]
    side["m"]["banishPile"] = side["banish_cards"]


def _resolve_duel(g):
    """Both sides have committed. See the module docstring for why this is four passes."""
    a, b = g["a"], g["b"]
    n, cond = g["duel"], g["condition"]
    _stage(a); _stage(b)

    pa, pb = engine.card(a["commit"]["card"]["type"]), engine.card(b["commit"]["card"]["type"])
    ra, rb = _record(a["commit"]["card"]["uid"]), _record(b["commit"]["card"]["uid"])
    ga = [engine.card(c["type"]) for c in a["commit"]["rg"]]
    gb = [engine.card(c["type"]) for c in b["commit"]["rg"]]
    sa, sb = f'{g["id"]}:{n}:a', f'{g["id"]}:{n}:b'

    # Each side resolves with ITS OWN Deck Master (8/15/26). Passing it here rather than baking it
    # into the match dict keeps the deepcopy-per-call pattern above intact -- every call already
    # re-derives from a fresh copy, so the DM has to ride along with the call, not the state.
    def run(side, pc, oc, rec, rg, seed, dm=None, **kw):
        return _seeded(seed, lambda: engine.resolve(side, pc, oc, cond, pc_record=rec, rear_guards=rg,
                                                    deck_master=dm, **kw))

    # 1. true powers, each from its own complete state
    powA = run(copy.deepcopy(a["m"]), pa, pb, ra, ga, sa, dm=a.get("deck_master"))["player_pow"]
    powB = run(copy.deepcopy(b["m"]), pb, pa, rb, gb, sb, dm=b.get("deck_master"))["player_pow"]

    # 2. provisional outcomes against the real opposing power
    outA = run(copy.deepcopy(a["m"]), pa, pb, ra, ga, sa, dm=a.get("deck_master"), opp_pow_override=powB)["outcome"]
    outB = run(copy.deepcopy(b["m"]), pb, pa, rb, gb, sb, dm=b.get("deck_master"), opp_pow_override=powA)["outcome"]

    # 3. reconcile — a guard turning a loss into a tie denies the other side its win
    if "tie" in (outA, outB):
        outA = outB = "tie"

    # 4. real pass, joint outcome, state mutated exactly once
    resA = run(a["m"], pa, pb, ra, ga, sa, dm=a.get("deck_master"), opp_pow_override=powB, forced_outcome=outA)
    resB = run(b["m"], pb, pa, rb, gb, sb, dm=b.get("deck_master"), opp_pow_override=powA, forced_outcome=outB)

    _apply(a, resA, powA, powB, b["handle"])
    _apply(b, resB, powB, powA, a["handle"])
    _persist_records(a, resA)
    _persist_records(b, resB)

    g["duel"] += 1
    g["seq"] += 1
    a["commit"] = b["commit"] = None
    over = resA["match_over"] or resB["match_over"]
    if over:
        g["done"] = True
        sc_a, sc_b = a["m"]["playerScore"][0], b["m"]["playerScore"][0]
        g["winner"] = a["user_id"] if sc_a > sc_b else (b["user_id"] if sc_b > sc_a else None)
        _payout(g)
    else:
        g["condition"] = engine.pick_condition()
        _reveal(g)


def _apply(side, res, my_pow, opp_pow, opp_handle):
    """Post-duel list moves — the same lifecycle app.py performs for solo matches, over the real
    uid-keyed lists this module owns (engine.py only ever sees the bare type-name mirror)."""
    cm = side["commit"]
    hc, rg_cards = cm["card"], cm["rg"]

    dest = res["destination"]
    if dest == "winners_circle": side["winners_circle_cards"].append(hc)
    elif dest == "hand": side["hand_cards"].append(hc)
    else: side["deck_cards"].append(hc)

    for rgc, fate in zip(rg_cards, res.get("rear_guard_fates", [])):
        if fate == "hand": side["hand_cards"].append(rgc)
        elif fate == "deck_bottom": side["deck_cards"].append(rgc)
        # "remnant": consumed into m["deathRemnants"] inside resolve(), no list move

    for op in res.get("hand_ops", []):
        if op["op"] == "draw":
            for _ in range(op.get("n", 0)):
                if side["deck_cards"]: side["hand_cards"].append(side["deck_cards"].pop(0))
        elif op["op"] == "banish_random":
            for _ in range(op.get("n", 0)):
                if side["hand_cards"]: side["banish_cards"].append(side["hand_cards"].pop(random.randrange(len(side["hand_cards"]))))

    # lost-duel comeback trigger off the top of the deck (app.py:432, index.html:5997-6002)
    if res["outcome"] == "lose" and side["deck_cards"]:
        trig = rules.TRIGGERS.get(side["deck_cards"][0]["type"])
        if trig:
            top = side["deck_cards"].pop(0); side["hand_cards"].append(top)
            for _ in range(trig.get("draw", 0)):
                if side["deck_cards"]: side["hand_cards"].append(side["deck_cards"].pop(0))
            for _ in range(trig.get("recur", 0)):
                if side["banish_cards"]: side["hand_cards"].append(side["banish_cards"].pop())
            res["log"].append(f"✨ Trigger — {top['type']}: {trig['text']}")

    for _ in range(res.get("draw_self", 0)):
        if side["deck_cards"]: side["hand_cards"].append(side["deck_cards"].pop(0))
    while len(side["hand_cards"]) < 4 and side["deck_cards"]:
        side["hand_cards"].append(side["deck_cards"].pop(0))
    side["m"]["hand"] = [c["type"] for c in side["hand_cards"]]

    side["last"] = {"outcome": res["outcome"], "yourCard": hc["type"], "yourPow": my_pow,
                    "theirPow": opp_pow, "opponent": opp_handle, "log": res["log"],
                    "score": [side["m"]["playerScore"][0], side["m"]["playerScore"][1]]}


def _persist_records(side, res):
    """Real K/D on the committed card. PvP is never lobby_mode, so every duel is on the record.

    The missing-user branch is not hypothetical defensiveness: _resolve_duel has already mutated
    BOTH players' match state by the time this runs, so an exception here would wedge the game
    half-resolved (duel counter never advanced, commits never cleared, both clients polling a
    match that can no longer progress). A vanished user row costs one duel's payout; it must not
    cost the match."""
    uid = side["commit"]["card"]["uid"]
    with store.tx() as c:
        if res["outcome"] == "win":
            c.execute("UPDATE records SET k=k+1, ok=ok+1 WHERE uid=?", (uid,))
            row = c.execute("SELECT signal FROM users WHERE id=?", (side["user_id"],)).fetchone()
            if row:
                ns = row["signal"] + 40
                c.execute("UPDATE users SET signal=? WHERE id=?", (ns, side["user_id"]))
                store.ledger_add(c, side["user_id"], "SIGNAL", 40, "PvP duel won", ns)
        elif res["outcome"] == "lose":
            c.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (uid,))


def _payout(g):
    """Match-end: RP to the winner, bonds for both. Mirrors app.py's own match-over block."""
    with store.tx() as c:
        for side in (g["a"], g["b"]):
            if g["winner"] == side["user_id"]:
                row = c.execute("SELECT rp FROM users WHERE id=?", (side["user_id"],)).fetchone()
                if row: c.execute("UPDATE users SET rp=? WHERE id=?", (row["rp"] + 100, side["user_id"]))
            played = sorted(side["m"]["matchPlayed"])
            for i in range(len(played)):
                for j in range(i + 1, len(played)):
                    pair = "|".join(sorted([played[i], played[j]]))
                    c.execute("INSERT INTO bonds(user_id,pair,count) VALUES(?,?,1) "
                              "ON CONFLICT(user_id,pair) DO UPDATE SET count=count+1",
                              (side["user_id"], pair))


def forfeit(user_id, pid):
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        if g["done"]: return 400, {"error": "match already complete"}
        g["done"] = True
        g["winner"] = them["user_id"]
        g["seq"] += 1
        g["touched"] = time.time()
        you["last"] = {"outcome": "forfeit", "log": ["🏳 you withdrew — the match goes to your opponent"]}
        them["last"] = {"outcome": "opponent_forfeit", "log": [f"🏳 {you['handle']} withdrew — the match is yours"]}
        _payout(g)
        return 200, _view(g, you, them)
