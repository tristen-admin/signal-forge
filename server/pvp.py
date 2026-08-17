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
import copy, json, os, random, secrets, threading, time

import engine, rules, store

_LOCK = threading.RLock()

QUEUE = []       # [{"user_id","handle","best_of","joined"}] — FIFO, oldest first
GAMES = {}       # pid -> game dict (see _new_game)
CHALLENGES = {}  # code -> {"user_id","handle","owned","best_of","created"} — a pending private-match invite

QUEUE_TTL = 120.0       # a queue entry this old is stale (browser closed, tab killed); dropped on touch
STARTING_HAND = 5       # matches index.html:12153; online was dealing 4
# 8/16/26 (owner-reported live: "new cards aren't being drawn, the whole deck system needs to be
# sure it's running correctly"). Real bug, not an exaggeration: _apply() below moves the committed
# card to its post-duel destination and _reveal() applies the Condition's own draw/discard, but
# nothing ever replaced the card that just left the hand with a fresh one from the deck -- there was
# no baseline per-duel draw step online AT ALL. Offline's is index.html:5201 drawCard() / the
# DRAW_PER_TURN constant; matching both values here so a duel online draws exactly what one does
# offline, not a separate, ad-hoc number.
MAX_HAND = 7            # matches index.html:12287
DRAW_PER_TURN = 1       # matches index.html:12284
# 8/16/26 — online had NO turn timer at all. Offline runs a forfeit clock on every decision
# (index.html startDecisionClock), so a stalling opponent online could hold a match open forever
# and the other player had no recourse but to quit. This has to be server-side: a client countdown
# is unenforceable and trivially bypassed by not running the client.
TURN_SECONDS = 60.0     # generous vs offline's 40/50 -- a network round trip and a human reading a
                        # new Condition both cost time that a local hotseat never pays.
# 8/16/26 — ONE Interrupt table. The client's ENERGY_SPELLS (sift/empower/hex/collapse/locus/
# drawsurge/godhand/sornshift) and engine.SPELLS (overclock/staticpulse/amplify/...) shared no ids
# at all, so offline and online were running different Interrupt games and the client could not even
# name a server spell. energy_spells.json is exported from the client's own table (the live game is
# the reference implementation, same call as dm_rules.json), so there is now a single source of
# truth and re-exporting keeps them identical.
_SPELL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "energy_spells.json")
try:
    with open(_SPELL_PATH, encoding="utf-8") as _f: SPELL_LIST = json.load(_f)
except Exception:
    SPELL_LIST = []
SPELLS = {sp["id"]: sp for sp in SPELL_LIST}
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
    # 8/16/26 — was `owned[:4], owned[4:]`: no shuffle at all, and a 4-card hand.
    # No shuffle meant the deal was a pure function of deck order, so the same deck produced the
    # same opening hand every single match, and two players on the same deck drew identically.
    # STARTING_HAND is 5 everywhere else (index.html:12153); online was quietly dealing 4.
    owned = list(owned)
    random.shuffle(owned)
    hand_cards, deck_cards = owned[:STARTING_HAND], owned[STARTING_HAND:]
    # 8/16/26 (owner-confirmed live: "Deckmasters not in opening hands") — offline GUARANTEES the
    # Deck Master swaps into the opening hand every match, in every mode except Sandbox
    # (index.html: "not a lottery, while still leaving the choice of WHEN to conjure it entirely up
    # to the player"). Online had no such guarantee -- the DM was shuffled in with the other 15-16
    # cards and had the same ~5/17 chance as anything else of landing in the first 5. The DM's
    # ABILITY was never gated on this (apply_deck_master fires on any conjured card, confirmed
    # separately), but never being ABLE to conjure your own Deck Master as your opening Fighter is a
    # real, confirmable difference from the offline design intent. Swaps rather than inserts, so
    # hand size is untouched, exactly mirroring the client's own splice/pop/push/shuffle.
    if deck_master:
        _dmi = next((i for i, c in enumerate(deck_cards) if c["type"] == deck_master), None)
        if _dmi is not None and not any(c["type"] == deck_master for c in hand_cards):
            _dm_card = deck_cards.pop(_dmi)
            deck_cards.append(hand_cards.pop())
            hand_cards.append(_dm_card)
            random.shuffle(deck_cards)
    m["hand"] = [c["type"] for c in hand_cards]
    return {"user_id": user_id, "handle": handle, "m": m, "deck_master": deck_master, "seen": time.time(),
            "hand_cards": hand_cards, "deck_cards": deck_cards, "banish_cards": [],
            "winners_circle_cards": [], "commit": None, "confirmed": None, "last": None}


def _new_game(a, b, best_of):
    pid = "p_" + secrets.token_hex(8)
    g = {"id": pid, "a": a, "b": b, "bestOf": best_of, "duel": 0, "done": False,
         "winner": None, "seq": 0, "touched": time.time(),
         "condition": engine.pick_condition()}
    _reveal(g)
    _duel_begin(g)
    GAMES[pid] = g
    return g


def _duel_begin(g):
    """Start the clock for a new duel. Called wherever a duel starts, so there is exactly one place
    the deadline is defined."""
    g["deadline"] = time.time() + TURN_SECONDS


def _draw_for_turn(side):
    """The baseline per-duel draw offline always had and online never did (see the note by
    DRAW_PER_TURN above). Deck first; Winners Circle only once the deck is genuinely empty, same
    fallback order as drawCard()'s useWC branch. Silently does nothing at the hand cap or with
    nothing left to draw from -- exactly offline's own two no-draw branches, not an error state."""
    for _ in range(DRAW_PER_TURN):
        if len(side["hand_cards"]) >= MAX_HAND: break
        if side["deck_cards"]: side["hand_cards"].append(side["deck_cards"].pop(0))
        elif side["winners_circle_cards"]: side["hand_cards"].append(side["winners_circle_cards"].pop())
        else: break
    side["m"]["hand"] = [c["type"] for c in side["hand_cards"]]


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
    # Time out stalled duels even when nobody is polling, so a match cannot sit mid-duel
    # indefinitely just because both clients happen to be idle at that instant.
    for g in list(GAMES.values()):
        if not g["done"]: _enforce_deadline(g)

    # Both sides gone -> end it, rather than leaving a live game nobody is in.
    for g in GAMES.values():
        if g["done"]: continue
        a_seen = g["a"].get("seen", g["touched"]); b_seen = g["b"].get("seen", g["touched"])
        a_gone, b_gone = now - a_seen > ABANDON_TTL, now - b_seen > ABANDON_TTL
        if a_gone and b_gone:
            g["done"] = True; g["winner"] = None; g["seq"] += 1; g["touched"] = now
            for side, other in ((g["a"], g["b"]), (g["b"], g["a"])):
                side["last"] = {"outcome": "tie", "log": ["\u23f8 match abandoned \u2014 both players left the room"]}
        elif a_gone or b_gone:
            # Real bug (8/17/26, reported live: "infinite loop on the broken opponent's end").
            # Ending a match used to require BOTH sides silent -- a genuinely present player,
            # politely polling every 2s, can never make that condition true on their own. One side
            # vanishing (e.g. via the since-fixed hudFold() bug, which exited the client without
            # ever telling the server) meant the PRESENT side's own honest, continued activity was
            # exactly what stopped this from ever resolving: every duel timed out "neither
            # committed" forever, because the present side wasn't going to stop polling just to
            # trigger an end condition, and the absent side obviously never would either. The side
            # that stayed did nothing wrong -- award them the match instead of trapping them in it.
            gone, present = (g["a"], g["b"]) if a_gone else (g["b"], g["a"])
            g["done"] = True; g["winner"] = present["user_id"]; g["seq"] += 1; g["touched"] = now
            present["last"] = {"outcome": "opponent_forfeit", "log": ["\U0001f6c8 opponent went silent \u2014 the match is yours"]}
            gone["last"] = {"outcome": "forfeit", "log": ["\U0001f6c8 you went silent \u2014 the match goes to your opponent"]}
            _payout(g)
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
def _enforce_deadline(g):
    """Time out the duel if someone stalled. Mirrors offline's rule -- missing the decision clock
    surrenders the ROUND, not the match -- so a stalled duel is scored rather than voided:
      one side committed  -> the committer wins the duel
      neither committed   -> the duel is a tie for both
    Called from state() and _sweep(), so it fires whether anyone is watching or not. A match cannot
    sit open forever because one player walked away mid-duel."""
    if g["done"] or not g.get("deadline"): return
    if time.time() < g["deadline"]: return
    a, b = g["a"], g["b"]
    ac, bc = a["commit"] is not None, b["commit"] is not None
    if ac and bc:
        # 8/16/26 (owner-requested feature) — both staged is no longer synonymous with resolved:
        # each side now separately confirms or withdraws after seeing the reveal, and THAT decision
        # can stall too. A side that never decides defaults to "commit" rather than "withdraw" --
        # defaulting to withdraw would let silence be a free, riskless dodge of a bad matchup, which
        # is exactly the incentive a decision clock exists to remove.
        if a["confirmed"] is not None and b["confirmed"] is not None: return   # both in; resolution already ran
        if a["confirmed"] is None: a["confirmed"] = "commit"
        if b["confirmed"] is None: b["confirmed"] = "commit"
        if a["confirmed"] == "commit" and b["confirmed"] == "commit":
            _resolve_duel(g)
        else:
            _resolve_withdraw(g)
        return
    if not ac and not bc:
        for s_, o_ in ((a, b), (b, a)):
            s_["last"] = {"outcome": "tie", "log": ["\u23f1 neither player committed in time \u2014 duel skipped"]}
        g["duel"] += 1; g["seq"] += 1
        g["condition"] = engine.pick_condition(); _reveal(g); _duel_begin(g)
        return
    winner, loser = (a, b) if ac else (b, a)
    winner["m"]["playerScore"][0] += 1
    winner["last"] = {"outcome": "win",  "log": ["\u23f1 your opponent ran out of time \u2014 duel awarded to you"]}
    loser["last"]  = {"outcome": "lose", "log": ["\u23f1 you ran out of time \u2014 the duel is forfeit"]}
    winner["commit"] = loser["commit"] = None
    g["duel"] += 1; g["seq"] += 1
    need = g["bestOf"] // 2 + 1
    if winner["m"]["playerScore"][0] >= need:
        g["done"] = True; g["winner"] = winner["user_id"]; _payout(g)
    else:
        g["condition"] = engine.pick_condition(); _reveal(g); _duel_begin(g)


def state(user_id, pid):
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        # Enforcement can advance the duel, end the match, or reveal a new condition, so the sides
        # are re-read afterwards rather than reused. _sides returns the SAME dict objects (it does
        # not copy), so this is belt-and-braces against a future _enforce_deadline that reassigns
        # them; the guard below is the part that actually matters, since a match ending here must
        # not fall through and build a view from a half-updated game.
        _enforce_deadline(g)
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
                # 8/16/26 — the piles were browsable offline and count-only online, because only
                # the counts were ever sent. YOUR OWN piles are yours to inspect, so the real lists
                # go out. The opponent's stay counts-only on purpose: their Winners Circle is live
                # information about what they still hold, and offline only ever showed you a number
                # for the bot too.
                "winnersCircle": _hand_view(you["winners_circle_cards"]),
                "banish": _hand_view(you["banish_cards"]),
                "banishCount": len(you["banish_cards"]),
                # Ship the spell METADATA alongside the ids. The tables are unified now (both
                # sides read the client's ENERGY_SPELLS via energy_spells.json), so this is no
                # longer papering over a divergence -- it just keeps the client from needing a
                # second lookup, and keeps the tray correct if the export ever runs ahead of a
                # client build.
                "spellHand": you["m"]["spellHand"],
                "spellInfo": [{"id": sp["id"], "name": sp.get("name", sp["id"]),
                               "cost": sp.get("cost", 0), "desc": sp.get("fx") or sp.get("desc") or ""}
                              for sp in SPELL_LIST if sp["id"] in (you["m"].get("spellHand") or [])],
                "deckMaster": you.get("deck_master"),
                "committed": you["commit"] is not None,
                "confirmed": you["confirmed"],
                "rgSlots": engine.rg_slots(you["m"].get("matchCommits", 0))},
        "them": {"score": them["m"]["playerScore"][0], "charge": them["m"]["charge"],
                 "handCount": len(them["hand_cards"]), "deckCount": len(them["deck_cards"]),
                 "winnersCircleCount": len(them["winners_circle_cards"]),
                 "banishCount": len(them["banish_cards"]),
                 "deckMaster": them.get("deck_master"),
                 "committed": them["commit"] is not None,
                 "confirmed": them["confirmed"] is not None},
        # 8/16/26 (owner-requested feature: "the withdraw phase only makes sense if it pops up once
        # both players commit a card -- that way you can see the win/loss record of your opponent
        # without seeing the card, and decide if you want to risk playing your KD against a proven
        # victor"). Populated only once BOTH sides have staged -- their card's real k/d, never its
        # identity, mirroring offline's own #record-reveal panel ("-- identity hidden --" on the
        # opponent's side). The client uses you.committed && them.committed as the signal to show
        # the reveal/withdraw screen; this is the payload it reveals once that's true.
        "revealOpponentRecord": (_record(them["commit"]["card"]["uid"])
                                  if you["commit"] is not None and them["commit"] is not None else None),
        "lastDuel": you["last"],
        "youWon": (g["winner"] == you["user_id"]) if g["done"] and g["winner"] else None,
        "lockedWithdraw": g["condition"] == "noretreat",
        "secondsLeft": max(0, int(g["deadline"] - time.time())) if g.get("deadline") and not g["done"] else None,
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

        # NOTE: do NOT deduct Charge here. engine.resolve() already spends it at engine.py:434
        # ("conjuring spends Charge equal to the fighter's own cost"). Deducting at commit as well
        # would charge twice for one conjure. The reported "charge not being spent" was a CLIENT
        # display bug -- the board printed the same number as both current and cap -- not a missing
        # deduction. Verified before changing the server.

        you["commit"] = {"card": hc, "rg": rg_cards}
        # 8/16/26 (owner-requested feature) — used to resolve the instant both sides had staged.
        # Now it just stages: once both are in, _view()'s revealOpponentRecord starts showing each
        # side the OTHER's real k/d (never their card), and the duel doesn't actually resolve until
        # both sides separately call confirm_or_withdraw() below, having seen it.
        return 200, {"waiting": them["commit"] is None, **_view(g, you, them)}


def confirm_or_withdraw(user_id, pid, action):
    """The decision made AFTER seeing the opponent's record (see the reveal note in _view()) --
    'commit' to actually play the duel out, or 'withdraw' to concede it. Withdrawing keeps your
    card's record clean: offline's own retreatCard() (index.html:7695) never records a K/D on
    either card when you retreat, it just hands the opponent the duel outright. Same rule here,
    across two real accounts instead of one human and a bot."""
    if action not in ("commit", "withdraw"):
        return 400, {"error": "action must be 'commit' or 'withdraw'"}
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        if g["done"]: return 400, {"error": "match already complete"}
        if you["commit"] is None or them["commit"] is None:
            return 400, {"error": "both sides must stage a card before you can commit or withdraw"}
        if action == "withdraw" and g["condition"] == "noretreat":
            return 400, {"error": "withdraw is locked this duel"}
        if you["confirmed"] is not None:
            return 400, {"error": "you already decided this duel"}
        g["touched"] = time.time()

        you["confirmed"] = action
        if them["confirmed"] is None:
            return 200, {"waiting": True, **_view(g, you, them)}

        if you["confirmed"] == "commit" and them["confirmed"] == "commit":
            _resolve_duel(g)
        else:
            _resolve_withdraw(g)
        return 200, {"waiting": False, **_view(g, you, them)}


def _resolve_withdraw(g):
    """At least one side withdrew. Neither card is staged (see _stage()'s docstring — it only runs
    inside _resolve_duel), so both simply stay in hand untouched: no K/D on either card, exactly
    offline's rule. Mutual withdraw is a tie (both sides equally declined the risk, so neither side
    is favored) -- there's no offline precedent for it since a bot never withdraws, so this is the
    most defensible reading of "no K/D on either card" extended to both sides at once."""
    a, b = g["a"], g["b"]
    a_in, b_in = a["confirmed"], b["confirmed"]

    if a_in == "withdraw" and b_in == "withdraw":
        outcome_a, outcome_b = "mutual_withdraw", "mutual_withdraw"
    elif a_in == "withdraw":
        a["m"]["playerScore"][1] += 1; b["m"]["playerScore"][0] += 1
        outcome_a, outcome_b = "withdraw", "opponent_withdrew"
    else:
        b["m"]["playerScore"][1] += 1; a["m"]["playerScore"][0] += 1
        outcome_a, outcome_b = "opponent_withdrew", "withdraw"

    a["last"] = {"outcome": outcome_a, "log": [_withdraw_log(outcome_a, b["handle"])]}
    b["last"] = {"outcome": outcome_b, "log": [_withdraw_log(outcome_b, a["handle"])]}

    a["commit"] = b["commit"] = None
    a["confirmed"] = b["confirmed"] = None
    g["duel"] += 1
    g["seq"] += 1

    threshold = a["m"].get("winThreshold", 4)
    sc_a, sc_b = a["m"]["playerScore"][0], b["m"]["playerScore"][0]
    if sc_a >= threshold or sc_b >= threshold:
        g["done"] = True
        g["winner"] = a["user_id"] if sc_a > sc_b else (b["user_id"] if sc_b > sc_a else None)
        _payout(g)
    else:
        _draw_for_turn(a); _draw_for_turn(b)
        g["condition"] = engine.pick_condition()
        _reveal(g)
    _duel_begin(g)


def _withdraw_log(outcome, opp_handle):
    if outcome == "withdraw": return "↩ You withdrew — no K/D recorded, " + opp_handle + " takes the duel."
    if outcome == "opponent_withdrew": return "↩ " + opp_handle + " withdrew — no K/D recorded, the duel is yours."
    return "↩ Both sides withdrew — no K/D recorded, the duel ties."


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
        _draw_for_turn(a); _draw_for_turn(b)
        g["condition"] = engine.pick_condition()
        _reveal(g)
    _duel_begin(g)


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


def cast_spell(user_id, pid, spell_id):
    """Cast an Interrupt in a PvP duel (8/16/26).

    spellHand has been in the state payload since PvP was written, but no endpoint ever existed to
    play one -- so a whole mechanic was visible and unusable online while being core offline. This
    mirrors app.py's h_spell_cast: same _SPELLS table, same cost/discount rules, same Charge check,
    same effect flags on the caster's own match state. It deliberately does NOT resolve anything --
    the flags (spellJam/spellOppPow/spellShield...) are read by engine.resolve() when the duel
    resolves, exactly as they are single-player."""
    with _LOCK:
        g = GAMES.get(pid)
        if not g: return 404, {"error": "match not found"}
        you, them = _sides(g, user_id)
        if not you: return 403, {"error": "not your match"}
        if g["done"]: return 400, {"error": "match already complete"}
        if you["commit"] is not None: return 400, {"error": "you already committed this duel"}
        m = you["m"]
        s = SPELLS.get(spell_id)
        if not s: return 400, {"error": "unknown spell"}
        if spell_id not in m.get("spellHand", []): return 400, {"error": "that Interrupt is not in your hand"}
        cost = max(0, s["cost"] - m.get("spellDiscount", 0))
        if m["charge"] < cost:
            return 402, {"error": f"not enough Charge (need {cost}, have {m['charge']})"}
        m["charge"] -= cost
        m["spellHand"] = [x for x in m["spellHand"] if x != spell_id]
        # Effects mirror the CLIENT's castSpell() (index.html), which is the live game's rule set.
        # The engine already honours spellSelfPow/spellOppPow at resolve (engine.py:438-439), so the
        # power spells need no engine change; the draw/banish ones ride the existing hand_ops
        # channel, and the two condition spells rewrite the SHARED condition -- which is a real
        # difference from single-player, where the condition is yours alone.
        hand_ops = []
        if spell_id == "empower":     m["spellSelfPow"] = m.get("spellSelfPow", 0) + 3
        elif spell_id == "godhand":   m["spellSelfPow"] = m.get("spellSelfPow", 0) + 10
        elif spell_id == "hex":       m["spellOppPow"] = m.get("spellOppPow", 0) - 3
        elif spell_id == "collapse":  m["spellHalveField"] = True
        elif spell_id == "sift":      hand_ops = [{"op": "draw", "n": 1}, {"op": "banish_random", "n": 1}]
        elif spell_id == "drawsurge": hand_ops = [{"op": "draw", "n": 3}, {"op": "banish_random", "n": 1}]
        elif spell_id == "locus":
            g["condition"] = engine.pick_condition()
            _reveal(g); _duel_begin(g)          # new condition, and the clock restarts for BOTH players
        elif spell_id == "sornshift":
            g["condition"] = "sornvallis" if "sornvallis" in getattr(engine, "CONDITION_IDS", ["sornvallis"]) else engine.pick_condition()
            _reveal(g); _duel_begin(g)
        for op in hand_ops:
            if op["op"] == "draw":
                for _ in range(op.get("n", 0)):
                    if you["deck_cards"]: you["hand_cards"].append(you["deck_cards"].pop(0))
            elif op["op"] == "banish_random":
                for _ in range(op.get("n", 0)):
                    if you["hand_cards"]:
                        you["banish_cards"].append(you["hand_cards"].pop(random.randrange(len(you["hand_cards"]))))
        you["m"]["hand"] = [c["type"] for c in you["hand_cards"]]
        m["spellDiscount"] = 0
        g["touched"] = time.time(); g["seq"] += 1
        return 200, _view(g, you, them)


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
