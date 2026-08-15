#!/usr/bin/env python3
"""
Signal Forge — Tier 0 authoritative server (stdlib only).
Run:  python3 server/app.py                    → binds 127.0.0.1:8787 (local dev default)
      HOST=0.0.0.0 python3 server/app.py       → binds all interfaces (real deployment)
The client may only READ state and REQUEST validated actions. It can never set its
own balances, records, or outcomes — every mutation is computed and applied here.
"""
import json, secrets, os, time, calendar, random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
import store, rules, engine, asc, pvp

MATCHES = {}   # in-memory match sessions: match_id -> {user_id, m, hand_cards, deck_cards, condition}
# 8/7/26: friends-list presence. In-memory, not persisted -- same call as QUEUE/GAMES/CHALLENGES in
# pvp.py (all ephemeral, all in-memory): "was this account seen recently" doesn't need to survive a
# restart, and writing it to SQLite on every single request would be real, pointless write load.
# Refreshed in auth_user() below, so it's free -- every authenticated request already proves the
# account is active right now, no separate heartbeat endpoint needed.
PRESENCE = {}      # user_id -> last-seen unix ts
ONLINE_WINDOW = 45.0   # seconds; comfortably wider than the client's ~20s friends-panel poll
_SESSION_TTL_DAYS = 30
_RL = {}   # naive per-key sliding window: key -> (window_start, count)
def _rate_ok(key, limit=300, window=60):
    t = time.time(); w, cnt = _RL.get(key, (t, 0))
    if t - w > window: _RL[key] = (t, 1); return True
    if cnt >= limit: return False
    _RL[key] = (w, cnt + 1); return True
ASC_RUNS = {}  # in-memory Ascension runs: run_id -> {user_id, run, avatarUid}
_SPELLS = {s['id']: s for s in engine.SPELLS}

HOST, PORT = os.environ.get("HOST") or "127.0.0.1", int(os.environ.get("PORT") or 8787)
MARKET_ADDR = "@market"
CLIENT_PATH = os.path.join(os.path.dirname(__file__), "client.html")

def addr_of(c, user_id):
    row = c.execute("SELECT handle FROM users WHERE id=?", (user_id,)).fetchone()
    return "@" + row["handle"] if row else "@player"

# ── one-time seeds ──
def seed():
    with store.tx() as c:
        for t in rules.CARD_CATALOG:
            c.execute("INSERT OR IGNORE INTO mint(type,supply,minted) VALUES(?,?,0)", (t, rules.edition_of(t)))
        n = c.execute("SELECT COUNT(*) n FROM listings").fetchone()["n"]
        if n == 0:
            demo = [  # AI-seeded secondary listings — NON-STARTER cards only (starters never hit the market)
                ("Akatosh, the Golden Dragon", 8400000, 512, 0, "@ApexCollector"),
                ("Kotei",                       6900000, 447, 0, "@GenesisZero"),
                ("Ahdor",                       4250000, 318, 0, "@TheWhale"),
                ("Darwin",                         3800,  41, 3, "@VoidRunner"),
                ("Arch-Grim Korrin",               2600,  28, 7, "@GrimCollector"),
                ("Veronica",                        420,   5, 1, "@BargainBin"),
            ]
            for t, price, k, d, addr in demo:
                if rules.is_starter(t): continue  # safety: starters are never listed
                c.execute("INSERT INTO listings(type,seller_id,seller_addr,price,k,d,sold,created) VALUES(?,?,?,?,?,?,0,?)",
                          (t, None, addr, price, k, d, store.now()))

# Bounds on what a registering client may claim from its local save. Deliberately generous
# rather than tight -- the point is to stop absurd claims, not to punish a real player who
# ground out a big offline collection before making an account.
MIGRATE_SIGNAL_CAP = 250000
MIGRATE_CARD_CAP   = 400

def mint_card(c, owner_id, t, k=0, d=0, via="Fresh mint"):
    row = c.execute("SELECT minted,supply FROM mint WHERE type=?", (t,)).fetchone()
    minted = (row["minted"] if row else 0) + 1
    c.execute("INSERT INTO mint(type,supply,minted) VALUES(?,?,?) ON CONFLICT(type) DO UPDATE SET minted=?",
              (t, rules.edition_of(t), minted, minted))
    uid = rules.new_uid(t)
    c.execute("INSERT INTO cards(uid,owner_id,type,mint_index,edition,created) VALUES(?,?,?,?,?,?)",
              (uid, owner_id, t, minted, rules.edition_of(t), store.now()))
    c.execute("INSERT INTO records(uid,k,d,ok,od) VALUES(?,?,?,0,0)", (uid, k, d))
    store.chain_add(c, uid, None, addr_of(c, owner_id), via)
    return uid

# ── authoritative state read ──
def user_state(user_id):
    c = store.conn()
    u = c.execute("SELECT handle,signal,forge,rp FROM users WHERE id=?", (user_id,)).fetchone()
    cards = []
    for r in c.execute("SELECT * FROM cards WHERE owner_id=? ORDER BY type", (user_id,)).fetchall():
        rec = c.execute("SELECT k,d,ok,od FROM records WHERE uid=?", (r["uid"],)).fetchone()
        rec = dict(rec) if rec else {"k":0,"d":0,"ok":0,"od":0}
        mast = c.execute("SELECT wins,flawless,best_level FROM mastery WHERE owner_id=? AND card_key=?",
                         (user_id, r["type"])).fetchone()
        mast = dict(mast) if mast else None
        sc = rules.legend_score(r["type"], rec, mast)
        cards.append({"uid": r["uid"], "type": r["type"], "pow": rules.card_pow(r["type"]),
                      "rarity": rules.card_rarity(r["type"]), "mint_index": r["mint_index"],
                      "edition": r["edition"], **rec, "legend_score": sc, "legend_tier": rules.legend_tier(sc)})
    return {"user": dict(u), "cards": cards}

# ── endpoint handlers (return (status, body)) ──
def h_register(uid_none, body):
    handle = (body.get("handle") or "").strip()
    pw = body.get("password") or ""
    if len(handle) < 2 or len(pw) < 4: return 400, {"error": "handle ≥2 chars, password ≥4 chars"}
    with store.tx() as c:
        if c.execute("SELECT 1 FROM users WHERE handle=?", (handle,)).fetchone():
            return 409, {"error": "handle taken"}
        uid = "u_" + secrets.token_hex(8); salt = rules.new_salt()

        # ── Save migration (8/14/26, owner) ────────────────────────────────────────────────
        # Registering used to hard-code signal=5000 + a fresh STARTER_DECK and ignore the client
        # entirely, so a player who finished the tutorial and then made an account silently lost
        # everything they had just earned. The account is now seeded FROM the local save.
        #
        # ⚠ This necessarily trusts the client: offline progress is client-authoritative, so there
        # is no server-side record to check it against. Everything below is therefore bounded --
        # currency is capped, card names must exist in the real catalog, the card count is capped,
        # and it can only ever happen at REGISTRATION (h_login never migrates). The ledger records
        # it explicitly so a migrated account is auditable and distinguishable from an earned one.
        mig = body.get("migrate") or {}
        mig_signal = mig.get("signal")
        mig_cards  = mig.get("cards")
        migrated   = False
        signal = 5000
        if isinstance(mig_signal, (int, float)) and mig_signal >= 0:
            signal = int(min(mig_signal, MIGRATE_SIGNAL_CAP)); migrated = True
        c.execute("INSERT INTO users(id,handle,pass_hash,salt,created,signal,forge,rp) VALUES(?,?,?,?,?,?,0,1000)",
                  (uid, handle, rules.hash_pw(pw, salt), salt, store.now(), signal))

        minted = 0
        if isinstance(mig_cards, list) and mig_cards:
            for entry in mig_cards[:MIGRATE_CARD_CAP]:
                if not isinstance(entry, dict): continue
                t = entry.get("type")
                if t not in rules.CARD_CATALOG: continue          # unknown/forged name -> dropped
                k = max(0, min(int(entry.get("k") or 0), 9999))
                d = max(0, min(int(entry.get("d") or 0), 9999))
                mint_card(c, uid, t, k=k, d=d, via="Migrated from local play")
                minted += 1
            migrated = migrated or minted > 0
        if minted == 0:
            for t in rules.STARTER_DECK: mint_card(c, uid, t, via="Starter grant")

        store.ledger_add(c, uid, "SIGNAL", signal,
                         ("Migrated from local play (%d cards)" % minted) if migrated else "Welcome grant (play currency)",
                         signal)
        tok = rules.new_token()
        c.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, uid, store.now()))
    return 200, {"token": tok, "state": user_state(uid)}

def h_login(uid_none, body):
    c = store.conn()
    u = c.execute("SELECT * FROM users WHERE handle=?", (body.get("handle","").strip(),)).fetchone()
    if not u or rules.hash_pw(body.get("password",""), u["salt"]) != u["pass_hash"]:
        return 401, {"error": "bad credentials"}
    tok = rules.new_token()
    with store.tx() as cc:
        cc.execute("INSERT INTO sessions(token,user_id,created) VALUES(?,?,?)", (tok, u["id"], store.now()))
    return 200, {"token": tok, "state": user_state(u["id"])}

def h_state(user_id, body):
    return 200, {"state": user_state(user_id)}

# 8/5/26 Phase 3: h_resolve (POST /api/match/resolve, a single-card duel predating match/start+
# commit) removed. Confirmed dead: the real game (index.html) calls no /api/ endpoint at all yet
# (client and server are still unwired -- separate systems); the ONLY caller anywhere in the tree
# was server/client.html's throwaway duel() button, which is removed in the same change. Fully
# superseded by h_match_start/h_match_commit's real best-of-N flow (abilities/conditions/traits/
# rear-guard/spells, real hand+deck, real match length) -- nothing lost, only a legacy stub gone.

def h_listings(user_id, body):
    rows = store.conn().execute("SELECT id,type,seller_addr,price,k,d FROM listings WHERE sold=0 ORDER BY price DESC").fetchall()
    return 200, {"listings": [dict(r) for r in rows]}

def h_buy(user_id, body):
    c = store.conn()
    l = c.execute("SELECT * FROM listings WHERE id=? AND sold=0", (body.get("listingId"),)).fetchone()
    if not l: return 404, {"error": "listing not found"}
    u = c.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()
    if u["signal"] < l["price"]: return 402, {"error": f"insufficient Signal (need {l['price']}, hold {u['signal']})"}
    with store.tx() as cc:
        ns = u["signal"] - l["price"]
        cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
        store.ledger_add(cc, user_id, "SIGNAL", -l["price"], f"Bought {l['type']} on market", ns)
        mint_card(cc, user_id, l["type"], k=l["k"], d=l["d"], via=f"Bought from {l['seller_addr']}")
        cc.execute("UPDATE listings SET sold=1 WHERE id=?", (l["id"],))
    return 200, {"bought": l["type"], "price": l["price"], "state": user_state(user_id)}

def h_sell(user_id, body):
    c = store.conn()
    card = c.execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (body.get("cardUid"), user_id)).fetchone()
    price = int(body.get("price") or 0)
    if not card: return 404, {"error": "you do not own that card"}
    if rules.is_starter(card["type"]): return 400, {"error": "starter cards are owned by every player — not tradeable"}
    if price < 1: return 400, {"error": "price ≥ 1"}
    with store.tx() as cc:
        u = cc.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()
        ns = u["signal"] + price
        cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
        store.ledger_add(cc, user_id, "SIGNAL", price, f"Sold {card['type']} on market", ns)
        store.chain_add(cc, card["uid"], addr_of(cc, user_id), MARKET_ADDR, f"Sold for {price} Signal")
        cc.execute("DELETE FROM records WHERE uid=?", (card["uid"],))
        cc.execute("DELETE FROM cards WHERE uid=?", (card["uid"],))
    return 200, {"sold": card["type"], "price": price, "state": user_state(user_id)}

def h_ledger(user_id, body):
    c = store.conn()
    led = [dict(r) for r in c.execute("SELECT ts,cur,amt,reason,balance FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 50", (user_id,)).fetchall()]
    chain = [dict(r) for r in c.execute(
        "SELECT oc.uid,oc.from_addr,oc.to_addr,oc.ts,oc.via FROM ownership_chain oc "
        "LEFT JOIN cards ca ON ca.uid=oc.uid WHERE ca.owner_id=? ORDER BY oc.id DESC LIMIT 50", (user_id,)).fetchall()]
    return 200, {"ledger": led, "ownership_chain": chain}

def h_forge_tiers(user_id, body):
    return 200, {"tiers": rules.FORGE_TIERS, "rate": rules.FORGE_TO_SIGNAL}

def h_buy_forge(user_id, body):   # simulated real-money purchase (payment processor is a future step)
    t = rules.FORGE_TIERS.get(body.get("tier"))
    if not t: return 400, {"error": "unknown Forge tier"}
    c = store.conn()
    with store.tx() as cc:
        nf = cc.execute("SELECT forge FROM users WHERE id=?", (user_id,)).fetchone()["forge"] + t["forge"]
        cc.execute("UPDATE users SET forge=? WHERE id=?", (nf, user_id))
        store.ledger_add(cc, user_id, "FORGE", t["forge"], f"Purchased [{body.get('tier')}] ${t['usd']} — SIMULATED", nf)
    return 200, {"purchased": body.get("tier"), "forge_added": t["forge"], "simulated": True, "state": user_state(user_id)}

def h_convert(user_id, body):     # one-way Forge -> Signal (no cash-out anywhere)
    amt = int(body.get("forge") or 0)
    if amt < 1: return 400, {"error": "convert ≥ 1 Forge"}
    c = store.conn()
    u = c.execute("SELECT signal,forge FROM users WHERE id=?", (user_id,)).fetchone()
    if u["forge"] < amt: return 402, {"error": f"insufficient Forge (need {amt}, hold {u['forge']})"}
    gain = amt * rules.FORGE_TO_SIGNAL
    with store.tx() as cc:
        nf, ns = u["forge"] - amt, u["signal"] + gain
        cc.execute("UPDATE users SET forge=?, signal=? WHERE id=?", (nf, ns, user_id))
        store.ledger_add(cc, user_id, "FORGE", -amt, "Converted to Signal", nf)
        store.ledger_add(cc, user_id, "SIGNAL", gain, f"Converted from {amt} Forge", ns)
    return 200, {"converted": amt, "signal_gained": gain, "state": user_state(user_id)}

# ── Phase 3: packs (server-authoritative RNG against the real finite mint + real per-account pity) ──
def _rarity_has_room(c, rarity):
    names = rules.CARDS_BY_RARITY.get(rarity) or []
    if not names: return False
    rows = c.execute(f"SELECT minted,supply FROM mint WHERE type IN ({','.join('?'*len(names))})", names).fetchall()
    return any(r["minted"] < r["supply"] for r in rows)

def _pick_mintable_card(c, rarity):
    names = rules.CARDS_BY_RARITY.get(rarity) or []
    if not names: return None
    rows = c.execute(f"SELECT type FROM mint WHERE type IN ({','.join('?'*len(names))}) AND minted<supply", names).fetchall()
    avail = [r["type"] for r in rows]
    return random.choice(avail) if avail else None

def h_pack_open(user_id, body):
    pack = rules.ALL_PACKS.get(body.get("packId"))
    if not pack: return 400, {"error": "unknown pack"}
    n = int(body.get("n") or 1)
    if n not in (1, 5, 10) or (n == 10 and not pack.get("tenX")):
        return 400, {"error": "invalid bundle size for this pack"}
    c = store.conn()
    u = c.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()
    cost = pack["price"] * n
    if u["signal"] < cost: return 402, {"error": f"insufficient Signal (need {cost}, have {u['signal']})"}
    pr = store.pity_load(user_id)
    pity_ultra, pity_apex = pr["pack_ultra"], pr["pack_apex"]
    is_premium = pack["id"] != "std"   # matches the client's basic(std/elite)-vs-premium(f*) bundle-floor split
    drawn = []
    for _ in range(n):
        avail = [r for r in pack["odds"] if _rarity_has_room(c, r)]
        if not avail: break   # every rarity this pack offers is fully minted out server-wide
        rar, pity_ultra, pity_apex = rules.roll_pack_rarity(pack, avail, pity_ultra, pity_apex)
        drawn.append(rar)
    drawn = rules.apply_bundle_floor(drawn, pack, is_premium, lambda r: _rarity_has_room(c, r))
    minted = []
    with store.tx() as cc:
        ns = u["signal"] - cost
        cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
        store.ledger_add(cc, user_id, "SIGNAL", -cost, f"Opened {pack['name']} x{n}", ns)
        for rar in drawn:
            name = _pick_mintable_card(cc, rar)
            if not name: continue   # exhausted mid-batch (rare: pre-batch room checks were per-rarity, not reserved)
            uid = mint_card(cc, user_id, name, via=f"{pack['name']} pull")
            minted.append({"uid": uid, "type": name, "rarity": rar, "pow": rules.card_pow(name)})
        store.pity_save(cc, user_id, pity_ultra, pity_apex)
    return 200, {"pack": pack["id"], "n": n, "cost": cost, "cards": minted,
                 "pity": {"ultra": pity_ultra, "apex": pity_apex}, "state": user_state(user_id)}

def h_pack_catalog(user_id, body):
    pr = store.pity_load(user_id)
    return 200, {"packs": rules.PACKS, "premiumPacks": rules.PREMIUM_PACKS,
                 "pity": {"ultra": pr["pack_ultra"], "apex": pr["pack_apex"],
                          "ultraFloor": rules.PITY_ULTRA, "apexFloor": rules.PITY_APEX}}

# ── Phase 3: real P2P trades. The client's own trade UI (index.html:12817 TRADE_PARTNERS) is
# confirmed-simulated against fake partner names with no second-party state at all ("Partners are
# simulated until online play launches" — the client's own words) — not a spec to port, since the
# whole point of this server is to BE the real online-play backend. Fresh design: propose/accept/
# decline between two real accounts, same starter-exemption + provenance-chain (transferToMe
# equivalent: reset owner-only K/D, append a real ownership_chain entry) as the client intended.
def h_trade_propose(user_id, body):
    c = store.conn()
    offer = c.execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (body.get("offerUid"), user_id)).fetchone()
    if not offer: return 404, {"error": "you do not own that card"}
    if rules.is_starter(offer["type"]): return 400, {"error": "starter cards are owned by every player — not tradeable"}
    want = c.execute("SELECT * FROM cards WHERE uid=?", (body.get("wantUid"),)).fetchone()
    if not want: return 404, {"error": "target card not found"}
    if want["owner_id"] == user_id: return 400, {"error": "you already own that card"}
    if rules.is_starter(want["type"]): return 400, {"error": "starter cards are owned by every player — not tradeable"}
    with store.tx() as cc:
        cur = cc.execute("INSERT INTO trades(from_user,to_user,offer_uid,want_uid,status,created) VALUES(?,?,?,?,'pending',?)",
                          (user_id, want["owner_id"], offer["uid"], want["uid"], store.now()))
        tid = cur.lastrowid
    return 200, {"tradeId": tid}

def h_trade_list(user_id, body):
    c = store.conn()
    rows = c.execute("SELECT * FROM trades WHERE (from_user=? OR to_user=?) AND status='pending' ORDER BY id DESC", (user_id, user_id)).fetchall()
    out = []
    for r in rows:
        offer = c.execute("SELECT type FROM cards WHERE uid=?", (r["offer_uid"],)).fetchone()
        want = c.execute("SELECT type FROM cards WHERE uid=?", (r["want_uid"],)).fetchone()
        out.append({"id": r["id"], "fromMe": r["from_user"] == user_id,
                    "offerType": offer["type"] if offer else None, "wantType": want["type"] if want else None})
    return 200, {"trades": out}

def h_trade_accept(user_id, body):
    c = store.conn()
    t = c.execute("SELECT * FROM trades WHERE id=? AND status='pending'", (body.get("tradeId"),)).fetchone()
    if not t: return 404, {"error": "trade not found or already resolved"}
    if t["to_user"] != user_id: return 403, {"error": "only the recipient can accept this trade"}
    offer = c.execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (t["offer_uid"], t["from_user"])).fetchone()
    want = c.execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (t["want_uid"], user_id)).fetchone()
    if not offer or not want:
        with store.tx() as cc: cc.execute("UPDATE trades SET status='cancelled' WHERE id=?", (t["id"],))
        return 400, {"error": "one of the traded cards has moved since this trade was proposed"}
    with store.tx() as cc:
        cc.execute("UPDATE cards SET owner_id=? WHERE uid=?", (user_id, offer["uid"]))
        cc.execute("UPDATE cards SET owner_id=? WHERE uid=?", (t["from_user"], want["uid"]))
        cc.execute("UPDATE records SET ok=0, od=0 WHERE uid=?", (offer["uid"],))
        cc.execute("UPDATE records SET ok=0, od=0 WHERE uid=?", (want["uid"],))
        store.chain_add(cc, offer["uid"], addr_of(cc, t["from_user"]), addr_of(cc, user_id), "Traded")
        store.chain_add(cc, want["uid"], addr_of(cc, user_id), addr_of(cc, t["from_user"]), "Traded")
        cc.execute("UPDATE trades SET status='accepted' WHERE id=?", (t["id"],))
    return 200, {"traded": True, "state": user_state(user_id)}

def h_trade_decline(user_id, body):
    t = store.conn().execute("SELECT * FROM trades WHERE id=? AND status='pending'", (body.get("tradeId"),)).fetchone()
    if not t: return 404, {"error": "trade not found or already resolved"}
    if user_id not in (t["from_user"], t["to_user"]): return 403, {"error": "not your trade"}
    with store.tx() as cc: cc.execute("UPDATE trades SET status='declined' WHERE id=?", (t["id"],))
    return 200, {"declined": True}

def h_user_tradeables(user_id, body):
    """Lets a proposer discover a target account's tradeable (non-starter) cards by handle --
    without this, trade/propose has no way to learn a real wantUid to request."""
    row = store.conn().execute("SELECT id FROM users WHERE handle=?", (body.get("handle") or "",)).fetchone()
    if not row: return 404, {"error": "no such account"}
    cards = store.conn().execute("SELECT uid,type FROM cards WHERE owner_id=? ORDER BY type", (row["id"],)).fetchall()
    return 200, {"cards": [dict(c) for c in cards if not rules.is_starter(c["type"])]}

# ── friends list (8/7/26) ──────────────────────────────────────────────────────────────────────
def h_friend_request(user_id, body):
    handle = (body.get("handle") or "").strip()
    if not handle: return 400, {"error": "enter a handle"}
    c = store.conn()
    target = c.execute("SELECT id, handle FROM users WHERE handle=?", (handle,)).fetchone()
    if not target: return 404, {"error": "no such account"}
    if target["id"] == user_id: return 400, {"error": "you can't friend yourself"}
    existing = c.execute(
        "SELECT * FROM friendships WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)",
        (user_id, target["id"], target["id"], user_id)).fetchone()
    if existing:
        if existing["status"] == "accepted": return 400, {"error": target["handle"] + " is already your friend"}
        if existing["from_user"] == user_id: return 400, {"error": "request already sent — waiting on them"}
        # they'd already sent YOU a pending request -- requesting them back just completes it,
        # matching how a mutual add works everywhere else (no need to make them click Accept on
        # a request that's now moot).
        with store.tx() as cc:
            cc.execute("UPDATE friendships SET status='accepted' WHERE id=?", (existing["id"],))
        return 200, {"accepted": True, "handle": target["handle"]}
    with store.tx() as cc:
        cc.execute("INSERT INTO friendships(from_user,to_user,status,created) VALUES(?,?,'pending',?)",
                   (user_id, target["id"], store.now()))
    return 200, {"requested": True, "handle": target["handle"]}

def h_friend_accept(user_id, body):
    c = store.conn()
    f = c.execute("SELECT * FROM friendships WHERE id=? AND status='pending'", (body.get("id"),)).fetchone()
    if not f: return 404, {"error": "request not found or already resolved"}
    if f["to_user"] != user_id: return 403, {"error": "only the recipient can accept this request"}
    with store.tx() as cc:
        cc.execute("UPDATE friendships SET status='accepted' WHERE id=?", (f["id"],))
    return 200, {"accepted": True}

def h_friend_decline(user_id, body):
    """Also used to remove an existing friend -- declining a pending request and ending an accepted
    friendship are the same action from either side (delete the row), no separate endpoint needed."""
    c = store.conn()
    f = c.execute("SELECT * FROM friendships WHERE id=?", (body.get("id"),)).fetchone()
    if not f: return 404, {"error": "request not found"}
    if f["to_user"] != user_id and f["from_user"] != user_id: return 403, {"error": "not your request"}
    with store.tx() as cc:
        cc.execute("DELETE FROM friendships WHERE id=?", (f["id"],))
    return 200, {"removed": True}

def h_friend_list(user_id, body):
    c = store.conn()
    rows = c.execute("SELECT * FROM friendships WHERE from_user=? OR to_user=?", (user_id, user_id)).fetchall()
    friends, incoming, outgoing = [], [], []
    now = time.time()
    for r in rows:
        other_id = r["to_user"] if r["from_user"] == user_id else r["from_user"]
        h = c.execute("SELECT handle FROM users WHERE id=?", (other_id,)).fetchone()
        handle = h["handle"] if h else "(deleted account)"
        if r["status"] == "accepted":
            game = pvp._active_game_for(other_id)
            online = (now - PRESENCE.get(other_id, 0)) < ONLINE_WINDOW
            friends.append({"id": r["id"], "handle": handle, "online": online, "inMatch": game is not None})
        elif r["status"] == "pending" and r["to_user"] == user_id:
            incoming.append({"id": r["id"], "handle": handle})
        elif r["status"] == "pending" and r["from_user"] == user_id:
            outgoing.append({"id": r["id"], "handle": handle})
    friends.sort(key=lambda f: (not f["online"], f["handle"].lower()))
    return 200, {"friends": friends, "incoming": incoming, "outgoing": outgoing}

def _load_bonds(user_id):
    return {r["pair"]: r["count"] for r in store.conn().execute("SELECT pair,count FROM bonds WHERE user_id=?", (user_id,)).fetchall()}
def _owned_cards(user_id):
    return [{"uid": r["uid"], "type": r["type"]} for r in
            store.conn().execute("SELECT uid,type FROM cards WHERE owner_id=? ORDER BY type", (user_id,)).fetchall()]

def _apply_reveal(hand_cards, deck_cards, banish_cards, reveal):
    """Reinforce/Dredge/Wild Pit's reveal-time draw+discard (engine.condition_reveal_effects).
    Discard is RANDOM from hand, matching the client's own banishFromHand() (index.html:6062) --
    not last-N, not player-choice (no interactive discard-picker exists server-side yet)."""
    for _ in range(reveal.get("draw", 0)):
        if deck_cards: hand_cards.append(deck_cards.pop(0))
    for _ in range(reveal.get("discard", 0)):
        if hand_cards: banish_cards.append(hand_cards.pop(random.randrange(len(hand_cards))))

def h_match_start(user_id, body):
    # 8/5/26 Milestone A: real deck persistence. Falls back to owned[:4]/[4:] (the original stub)
    # only when the user has never saved a deck -- so accounts that predate deck/set still work.
    saved = store.deck_load(user_id)
    all_owned = _owned_cards(user_id)
    if saved:
        by_uid = {c["uid"]: c for c in all_owned}
        owned = [by_uid[u] for u in saved if u in by_uid]   # drop any uid no longer owned (sold/traded since save)
    else:
        owned = all_owned
    if len(owned) < 4: return 400, {"error": "need at least 4 cards in your deck to start a match"}
    # 8/5/26: dual match-length -- {"mode":"ranked"} plays Best-of-3-win-2, anything else (Public/
    # Draft default) plays the original Best-of-7-win-4. lobby_mode mirrors the client's Public
    # Server/Sandbox: signal still pays out, but records/win-loss are never written (resolve()'s
    # own record_duel flag, read below in match/commit).
    best_of = 3 if body.get("mode") == "ranked" else 7
    lobby_mode = bool(body.get("lobby_mode", False))
    m = engine.new_match([c["type"] for c in owned], best_of=best_of, lobby_mode=lobby_mode)
    m["bonds"] = _load_bonds(user_id)
    mid = "m_" + secrets.token_hex(8)
    hand_cards, deck_cards, banish_cards = owned[:4], owned[4:], []
    m["hand"] = [c["type"] for c in hand_cards]
    cond = engine.pick_condition()
    _apply_reveal(hand_cards, deck_cards, banish_cards, engine.condition_reveal_effects(cond))
    MATCHES[mid] = {"user_id": user_id, "m": m, "hand_cards": hand_cards, "deck_cards": deck_cards,
                    "banish_cards": banish_cards, "winners_circle_cards": [], "condition": cond}
    return 200, {"matchId": mid, "hand": hand_cards, "condition": cond, "score": m["playerScore"],
                 "charge": m["charge"], "bestOf": best_of, "locked_withdraw": cond == "noretreat"}

def _exec_hand_ops(sess, ops):
    """Execute the draw/banish instructions engine.resolve() returns (Called effects, e.g.
    Squad 19 Medic's `draw:1`) against the real uid-keyed lists engine.py never sees."""
    for op in ops:
        if op["op"] == "draw":
            for _ in range(op.get("n", 0)):
                if sess["deck_cards"]: sess["hand_cards"].append(sess["deck_cards"].pop(0))
        elif op["op"] == "banish_random":
            for _ in range(op.get("n", 0)):
                if sess["hand_cards"]: sess.setdefault("banish_cards", []).append(sess["hand_cards"].pop(random.randrange(len(sess["hand_cards"]))))

def h_match_commit(user_id, body):
    sess = _get_match(user_id, body.get("matchId"))
    if not sess: return 404, {"error": "match not found"}
    if sess["m"]["done"]: return 400, {"error": "match already complete"}
    hc = next((c for c in sess["hand_cards"] if c["uid"] == body.get("cardUid")), None)
    if not hc: return 400, {"error": "that card is not in your hand"}
    # 8/5/26 Milestone B: rear-guard staging. Up to rg_slots(matchCommits) OTHER hand cards, staged
    # alongside the fighter (index.html:6850 rearGuards, RG_SLOTS() 2->3 at the 4th duel).
    rg_uids = [u for u in (body.get("rearGuardUids") or []) if u != hc["uid"]]
    slots = engine.rg_slots(sess["m"].get("matchCommits", 0))
    if len(rg_uids) > slots: return 400, {"error": f"only {slots} support slot(s) available this duel"}
    rg_cards = []
    for u in rg_uids:
        rgc = next((c for c in sess["hand_cards"] if c["uid"] == u), None)
        if not rgc: return 400, {"error": f"rear-guard card {u} is not in your hand"}
        rg_cards.append(rgc)
    c = store.conn()
    r = c.execute("SELECT k,d,ok,od FROM records WHERE uid=?", (hc["uid"],)).fetchone()
    rec = dict(r) if r else {"k": 0, "d": 0, "ok": 0, "od": 0}
    pc = engine.card(hc["type"]); oc = engine.card(random.choice(engine.opponent_pool()))
    rear_guards = [engine.card(rgc["type"]) for rgc in rg_cards]

    # 8/5/26 Milestone B: fighter + rear-guards leave the hand BEFORE resolve() runs (matches the
    # client's real order, index.html:6868 -- the splice happens before resolve() ever reads
    # hand.length) -- Milestone A synced m["hand"] with the committed card still counted, an
    # off-by-however-many-rear-guards error in every hand_len-dependent CARD_RULES/Called check.
    staged_uids = {hc["uid"]} | set(rg_uids)
    sess["hand_cards"] = [x for x in sess["hand_cards"] if x["uid"] not in staged_uids]
    sess["m"]["hand"] = [x["type"] for x in sess["hand_cards"]]
    sess["m"]["banishPile"] = sess.get("banish_cards") or []   # real count now that rear-guard/Called can reference it

    res = engine.resolve(sess["m"], pc, oc, sess["condition"], pc_record=rec, rear_guards=rear_guards)

    # apply the duel outcome to the committed card's live record; award Signal on a win.
    # lobbyMode (Public Server/Sandbox) writes neither -- res["record_duel"] gates it, matching the
    # client's own "signal pays out, but K/D + Deck Master record never move here" contract.
    if res["record_duel"]:
        with store.tx() as cc:
            if res["outcome"] == "win":
                cc.execute("UPDATE records SET k=k+1, ok=ok+1 WHERE uid=?", (hc["uid"],))
                ns = cc.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()["signal"] + 40
                cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
                store.ledger_add(cc, user_id, "SIGNAL", 40, "Duel won", ns)
            elif res["outcome"] == "lose":
                cc.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (hc["uid"],))

    # 8/5/26 Milestone A: real card-lifecycle routing. engine.resolve()'s `destination`
    # (winners_circle|hand|deck_bottom) drives the real move; app.py performs it since it's the one
    # holding the real uid-keyed lists. (Fighter + rear-guards already left hand_cards above.)
    dest = res["destination"]
    if dest == "winners_circle": sess.setdefault("winners_circle_cards", []).append(hc)
    elif dest == "hand": sess["hand_cards"].append(hc)
    else: sess["deck_cards"].append(hc)   # deck_bottom -- deck_cards[0] is the TOP (next draw), so bottom = append

    # 8/5/26 Milestone B: rear-guard post-duel fate, parallel to rear_guards/rg_cards. "remnant"
    # means the card was converted into an m["deathRemnants"] entry inside resolve() already -- the
    # physical card is consumed, it does NOT also go to hand or deck.
    for rgc, fate in zip(rg_cards, res.get("rear_guard_fates", [])):
        if fate == "hand": sess["hand_cards"].append(rgc)
        elif fate == "deck_bottom": sess["deck_cards"].append(rgc)
        # fate == "remnant": consumed, no list move

    _exec_hand_ops(sess, res.get("hand_ops", []))

    # TRIGGERS: on a LOST duel, peek the top of the deck for a comeback-aid card (index.html:5997-
    # 6002 -- Faye Quicksilver/Val Kreigh/Josef/Old Garrick). Needs the real ordered deck_cards
    # app.py owns; engine.py only sees the bare type-name mirror, so this lives here, not there.
    if res["outcome"] == "lose" and sess["deck_cards"]:
        top = sess["deck_cards"][0]
        trig = rules.TRIGGERS.get(top["type"])
        if trig:
            sess["deck_cards"].pop(0); sess["hand_cards"].append(top)
            for _ in range(trig.get("draw", 0)):
                if sess["deck_cards"]: sess["hand_cards"].append(sess["deck_cards"].pop(0))
            for _ in range(trig.get("recur", 0)):
                if sess.get("banish_cards"): sess["hand_cards"].append(sess["banish_cards"].pop())
            res["log"].append(f"✨ Trigger — {top['type']}: {trig['text']}")

    for _ in range(res.get("draw_self", 0)):   # e.g. Bone Choirmaster's win-draw
        if sess["deck_cards"]: sess["hand_cards"].append(sess["deck_cards"].pop(0))
    # top up to a 4-card hand (only draws if the destination/trigger/draw_self/hand_ops logic above
    # didn't already refill it -- e.g. a forced-tie hand-return needs no extra draw)
    while len(sess["hand_cards"]) < 4 and sess["deck_cards"]:
        sess["hand_cards"].append(sess["deck_cards"].pop(0))

    sess["condition"] = engine.pick_condition()
    _apply_reveal(sess["hand_cards"], sess["deck_cards"], sess.setdefault("banish_cards", []),
                  engine.condition_reveal_effects(sess["condition"]))
    out = {"result": res, "opponent": oc["name"], "condition": sess["condition"],
           "hand": sess["hand_cards"], "score": sess["m"]["playerScore"], "match_over": res["match_over"],
           "charge": sess["m"]["charge"], "spellHand": sess["m"]["spellHand"],
           "locked_withdraw": sess["condition"] == "noretreat",
           "winnersCircleCount": len(sess.get("winners_circle_cards") or []), "deckCount": len(sess["deck_cards"])}
    if res["match_over"]:
        sess["m"]["done"] = True
        won_match = sess["m"]["playerScore"][0] > sess["m"]["playerScore"][1]
        with store.tx() as cc:
            if won_match:
                nr = cc.execute("SELECT rp FROM users WHERE id=?", (user_id,)).fetchone()["rp"] + 100
                cc.execute("UPDATE users SET rp=? WHERE id=?", (nr, user_id))
            played = sorted(sess["m"]["matchPlayed"])
            for i in range(len(played)):
                for j in range(i + 1, len(played)):
                    pair = "|".join(sorted([played[i], played[j]]))
                    cc.execute("INSERT INTO bonds(user_id,pair,count) VALUES(?,?,1) ON CONFLICT(user_id,pair) DO UPDATE SET count=count+1", (user_id, pair))
        out["match_won"] = won_match
        out["state"] = user_state(user_id)
    return 200, out

def h_match_state(user_id, body):
    sess = _get_match(user_id, body.get("matchId"))
    if not sess: return 404, {"error": "match not found"}
    return 200, {"score": sess["m"]["playerScore"], "hand": sess["hand_cards"], "condition": sess["condition"],
                 "done": sess["m"]["done"], "charge": sess["m"]["charge"], "spellHand": sess["m"]["spellHand"],
                 "locked_withdraw": sess["condition"] == "noretreat",
                 "winnersCircleCount": len(sess.get("winners_circle_cards") or []), "deckCount": len(sess["deck_cards"])}

# ── PvP (Phase 5.1, 8/6/26) — real two-player matches. app.py builds each side's deck using the
# helpers it already owns (deck_load + the uid->card mapping); pvp.py owns pairing, the joint duel
# resolution and the per-player state views. See pvp.py's docstring for the resolution design.
def _pvp_deck(user_id):
    saved = store.deck_load(user_id)
    all_owned = _owned_cards(user_id)
    if not saved: return all_owned
    by_uid = {c["uid"]: c for c in all_owned}
    return [by_uid[u] for u in saved if u in by_uid]

def h_pvp_queue(user_id, body):
    owned = _pvp_deck(user_id)
    if len(owned) < 4: return 400, {"error": "need at least 4 cards in your deck to queue"}
    handle = store.conn().execute("SELECT handle FROM users WHERE id=?", (user_id,)).fetchone()["handle"]
    return pvp.join(user_id, handle, owned, 3 if body.get("mode") == "ranked" else 7)

def h_pvp_leave(user_id, body):   return pvp.leave(user_id)
def h_pvp_state(user_id, body):   return pvp.state(user_id, body.get("pvpId"))
def h_pvp_forfeit(user_id, body): return pvp.forfeit(user_id, body.get("pvpId"))

# Direct-invite private matches (8/6/26) -- the random queue needs both friends to hit "Find Match"
# at the same moment in the same mode; a shareable code lets one side create, the other join, on
# their own schedule. Fully additive: CHALLENGES is its own dict in pvp.py, untouched QUEUE/join()
# logic still backs the random-pairing path.
def h_pvp_challenge_create(user_id, body):
    owned = _pvp_deck(user_id)
    if len(owned) < 4: return 400, {"error": "need at least 4 cards in your deck to play"}
    handle = store.conn().execute("SELECT handle FROM users WHERE id=?", (user_id,)).fetchone()["handle"]
    return pvp.create_challenge(user_id, handle, owned, 3 if body.get("mode") == "ranked" else 7)

def h_pvp_challenge_status(user_id, body): return pvp.challenge_status(user_id, body.get("code"))
def h_pvp_challenge_cancel(user_id, body): return pvp.cancel_challenge(user_id)

def h_pvp_challenge_join(user_id, body):
    owned = _pvp_deck(user_id)
    if len(owned) < 4: return 400, {"error": "need at least 4 cards in your deck to play"}
    handle = store.conn().execute("SELECT handle FROM users WHERE id=?", (user_id,)).fetchone()["handle"]
    return pvp.join_challenge(user_id, handle, owned, body.get("code"))

# 8/7/26: challenging a friend straight from the Friends panel -- same CHALLENGES mechanism as the
# code-sharing flow above, just targeted at a specific account instead of handed out as a code to
# share out-of-band. The challenger still gets a code back (join_challenge's plumbing expects one)
# but never needs to show it anywhere; the target discovers the challenge by polling
# h_pvp_challenge_incoming instead of typing a code in.
def h_pvp_challenge_direct(user_id, body):
    target_handle = (body.get("handle") or "").strip()
    if not target_handle: return 400, {"error": "missing target handle"}
    c = store.conn()
    target = c.execute("SELECT id FROM users WHERE handle=?", (target_handle,)).fetchone()
    if not target: return 404, {"error": "no such account"}
    f = c.execute(
        "SELECT 1 FROM friendships WHERE status='accepted' AND ((from_user=? AND to_user=?) OR (from_user=? AND to_user=?))",
        (user_id, target["id"], target["id"], user_id)).fetchone()
    if not f: return 403, {"error": "you can only direct-challenge a friend"}
    owned = _pvp_deck(user_id)
    if len(owned) < 4: return 400, {"error": "need at least 4 cards in your deck to play"}
    handle = c.execute("SELECT handle FROM users WHERE id=?", (user_id,)).fetchone()["handle"]
    return pvp.create_challenge(user_id, handle, owned, 3 if body.get("mode") == "ranked" else 7, target_user_id=target["id"])

def h_pvp_challenge_incoming(user_id, body):
    return pvp.incoming_challenge(user_id)
def h_pvp_commit(user_id, body):
    return pvp.commit(user_id, body.get("pvpId"), body.get("cardUid"), body.get("rearGuardUids"))

def h_deck_set(user_id, body):
    uids = body.get("cards")
    if not isinstance(uids, list) or len(uids) < 4:
        return 400, {"error": "deck must be a list of at least 4 card uids"}
    owned = {c["uid"] for c in _owned_cards(user_id)}
    bad = [u for u in uids if u not in owned]
    if bad: return 400, {"error": f"you do not own {len(bad)} of those cards"}
    store.deck_save(user_id, uids)
    return 200, {"saved": len(uids)}

def h_deck_get(user_id, body):
    return 200, {"cards": store.deck_load(user_id) or []}

def _owned_type_names(user_id):
    return {r["type"] for r in store.conn().execute("SELECT DISTINCT type FROM cards WHERE owner_id=?", (user_id,)).fetchall()}

def _get_match(user_id, mid):
    s = MATCHES.get(mid)
    if not s:
        obj = store.session_load(mid)
        if obj: MATCHES[mid] = obj; s = obj
    return s if s and s.get("user_id") == user_id else None
def _asc_sess(user_id, body):
    rid = body.get("runId"); s = ASC_RUNS.get(rid)
    if not s:
        obj = store.session_load(rid)
        if obj: ASC_RUNS[rid] = obj; s = obj
    return s if s and s.get("user_id") == user_id else None
def _persist_session(path, body, out):
    try:
        if path.startswith("/api/match/"):
            mid = body.get("matchId") or (out.get("matchId") if isinstance(out, dict) else None)
            if mid in MATCHES: store.session_save(mid, "match", MATCHES[mid])
        elif path.startswith("/api/spell/"):
            mid = body.get("matchId")
            if mid in MATCHES: store.session_save(mid, "match", MATCHES[mid])
        elif path.startswith("/api/asc/"):
            rid = body.get("runId") or (out.get("runId") if isinstance(out, dict) else None)
            if rid in ASC_RUNS: store.session_save(rid, "asc", ASC_RUNS[rid])
    except Exception: pass

def _asc_unit_public(u, run, owned):
    d = {"name": u["name"], "art": u["art"], "avatar": u["avatar"], "hp": u["hp"], "maxhp": u["maxhp"],
         "atk": u["atk"], "spd": u["spd"], "lv": u["lv"], "owned": u["name"] in owned,
         "moves": [{"name": m["name"], "kind": m["kind"], "left": m["left"], "uses": m.get("uses", 0)} for m in u["moves"]]}
    if not u["avatar"]:
        # Phase 4.3: everything a companion has UNLOCKED (not just their active 4), so a client can
        # render a real swap-your-loadout UI without extra round-trips -- see h_asc_loadout.
        base = asc.resolve_unit(u["id"])
        full = asc.unit_move_list(base)
        lvl = asc.unit_level(run["prog"], u["name"])
        d["unlocked"] = [{"idx": i, "name": m["name"], "kind": m["kind"], "unlock": m.get("unlock", 1)}
                          for i, m in enumerate(full) if lvl >= m.get("unlock", 1)]
    return d

def _asc_public(run, user_id):
    owned = _owned_type_names(user_id)
    node = run["map"][run["tier"]] if run["tier"] < len(run["map"]) else None
    return {"chapterIdx": run["chapterIdx"], "tier": run["tier"], "totalNodes": len(run["map"]),
            "phase": run["phase"], "done": run["done"], "result": run["result"], "flawless": run["flawless"],
            "party": [_asc_unit_public(u, run, owned) for u in run["party"]],
            "node": ({"type": node["type"], "title": node.get("title"), "loc": node.get("loc"), "beat": node.get("beat")} if node else None),
            "battle": _battle_public(run["battle"]) if run["battle"] else None,
            "inv": run.get("inv", {}), "gear": run.get("gear", []), "equip": run.get("equip", {})}

def _battle_public(battle):
    return {"gauge": battle.get("gauge", 0), "gaugeMax": asc.GAUGE_MAX, "round": battle.get("round", 0),
            "actor": battle.get("actor"), "log": battle.get("log", [])[-30:],
            "party": [{"name": u["name"], "avatar": u["avatar"], "hp": u["hp"], "maxhp": u["maxhp"],
                       "moves": [{"name": m["name"], "kind": m["kind"], "left": m["left"]} for m in u["moves"]]} for u in battle["party"]],
            "foes": [{"name": f["name"], "hp": f["hp"], "maxhp": f["maxhp"], "rank": f["rank"]} for f in battle["foes"]]}

def _ensure_ally_pool(user_id):
    """Phase 4.4: lazily seeds the fixed starting 5 (rules.ASC_ALLY_POOL_STARTERS) on first access,
    so every account has a working companion pool with zero ownership-luck dependency (all 5 are
    starter-set cards, guaranteed-owned)."""
    pool = store.ally_pool_load(user_id)
    if not pool:
        with store.tx() as cc:
            for name in rules.ASC_ALLY_POOL_STARTERS:
                store.ally_pool_add(cc, user_id, name, "starter")
        pool = store.ally_pool_load(user_id)
    return pool

def _ally_pool_cap(prog):
    return rules.ASC_ALLY_POOL_BASE_CAP + sum(1 for p in prog.values() if p.get("poolBonusGranted"))

def h_asc_ally_pool(user_id, body):
    """What's in your Ascension companion pool, its current cap, and what you could summon into it
    next (a random Signal pull, a targeted Signal pick IF the target is Deck-Master-eligible -- the
    owner's 'you can still summon a [DM] character... you don't have in your pool yet' carve-out --
    or a targeted Forge pick for anything else you own)."""
    pool = _ensure_ally_pool(user_id)
    prog = store.asc_prog_load(user_id)
    cap = _ally_pool_cap(prog)
    owned = _owned_type_names(user_id)
    not_pooled_owned = sorted(n for n in owned if n not in pool and asc.resolve_unit(n))
    dm_targets = [n for n in not_pooled_owned if rules.asc_champion_eligible(n)]
    return 200, {"pool": sorted(pool), "cap": cap, "size": len(pool),
                 "summon": {
                     "signalRandom": {"price": rules.ASC_SUMMON_SIGNAL_RANDOM_PRICE, "available": len(not_pooled_owned)},
                     "signalDmTargeted": {"price": rules.ASC_SUMMON_SIGNAL_DM_TARGETED_PRICE, "options": dm_targets},
                     "forgeTargeted": {"price": rules.ASC_SUMMON_FORGE_TARGETED_PRICE, "options": not_pooled_owned},
                 }}

def h_asc_ally_summon(user_id, body):
    pool = _ensure_ally_pool(user_id)
    prog = store.asc_prog_load(user_id)
    cap = _ally_pool_cap(prog)
    if len(pool) >= cap:
        return 400, {"error": f"ally pool is full ({len(pool)}/{cap}) -- grow it by leveling a pooled unit to "
                               f"{rules.ASC_POOL_GROWTH_LEVEL} or {rules.ASC_POOL_GROWTH_KILLS} kills"}
    method = body.get("method")
    owned = _owned_type_names(user_id)
    not_pooled_owned = [n for n in owned if n not in pool and asc.resolve_unit(n)]
    target = None
    if method == "signal_random":
        if not not_pooled_owned: return 400, {"error": "every eligible owned unit is already in your pool"}
        price, cur = rules.ASC_SUMMON_SIGNAL_RANDOM_PRICE, "signal"
        target = random.choice(not_pooled_owned)
    elif method == "signal_dm":
        target = body.get("unitName")
        if target not in not_pooled_owned: return 400, {"error": f"{target} isn't an owned, not-yet-pooled unit"}
        if not rules.asc_champion_eligible(target): return 400, {"error": f"{target} has no Deck Master ability -- use forge_targeted instead"}
        price, cur = rules.ASC_SUMMON_SIGNAL_DM_TARGETED_PRICE, "signal"
    elif method == "forge_targeted":
        target = body.get("unitName")
        if target not in not_pooled_owned: return 400, {"error": f"{target} isn't an owned, not-yet-pooled unit"}
        price, cur = rules.ASC_SUMMON_FORGE_TARGETED_PRICE, "forge"
    else:
        return 400, {"error": "unknown summon method -- use signal_random, signal_dm, or forge_targeted"}
    row = store.conn().execute("SELECT signal, forge FROM users WHERE id=?", (user_id,)).fetchone()
    balance = row[cur]
    if balance < price: return 402, {"error": f"insufficient {cur.capitalize()} (need {price}, have {balance})"}
    with store.tx() as cc:
        new_balance = balance - price
        if cur == "signal": cc.execute("UPDATE users SET signal=? WHERE id=?", (new_balance, user_id))
        else: cc.execute("UPDATE users SET forge=? WHERE id=?", (new_balance, user_id))
        store.ledger_add(cc, user_id, cur.upper(), -price, f"Ascension ally summon: {target} ({method})", new_balance)
        store.ally_pool_add(cc, user_id, target, method)
    pool2 = store.ally_pool_load(user_id)
    return 200, {"summoned": target, "method": method, "cost": price, "currency": cur, "pool": sorted(pool2), "cap": cap}

def h_asc_shop(user_id, body):
    """Phase 4.2: what asc/start's buyItems/buyGear/equip params can spend Signal on -- the real
    Merchant's items/gear/prices, surfaced before the Rite since Story mode has no Merchant node
    to browse them at mid-run (see asc.py module docstring)."""
    return 200, {"items": asc.ASC_ITEMS, "gear": asc.ASC_GEAR}

def h_asc_loadout(user_id, body):
    """Phase 4.3: choose which of a companion's UNLOCKED moves occupy their 4 active slots. The
    data model (prog[name]["load"], read by asc.unit_loadout()) already supported this -- only the
    endpoint to actually set it was missing. Scoped to between fights (not mid-battle) so combat
    state (uses-left counters, current moves list) never has to be reconciled mid-turn; a change
    here takes effect starting the run's next asc/enter (which calls refresh_for_battle)."""
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"]: return 400, {"error": "this run has ended"}
    if run["phase"] == "battle": return 400, {"error": "can't change loadouts mid-battle -- wait until between fights"}
    unit_name = body.get("unitName")
    move_idxs = list(body.get("moveIdxs") or [])
    party_unit = next((u for u in run["party"] if u["name"] == unit_name and not u["avatar"]), None)
    if not party_unit: return 400, {"error": f"{unit_name} is not a companion in this party"}
    base = asc.resolve_unit(unit_name)
    full = asc.unit_move_list(base)
    lvl = asc.unit_level(run["prog"], unit_name)
    unlocked = [i for i, m in enumerate(full) if lvl >= m.get("unlock", 1)]
    if not (1 <= len(move_idxs) <= 4): return 400, {"error": "choose 1-4 moves"}
    if len(set(move_idxs)) != len(move_idxs): return 400, {"error": "duplicate move index"}
    for i in move_idxs:
        if not isinstance(i, int) or i not in unlocked:
            return 400, {"error": f"move index {i} isn't unlocked yet for {unit_name} (level {lvl})"}
    p = run["prog"].setdefault(unit_name, asc.new_prog_entry())
    p["load"] = move_idxs
    with store.tx() as cc:
        store.asc_prog_save(cc, user_id, run["prog"])
    return 200, {"unitName": unit_name, "load": move_idxs,
                 "available": [{"idx": i, "name": full[i]["name"], "kind": full[i]["kind"], "unlock": full[i].get("unlock", 1)} for i in unlocked]}

def h_asc_start(user_id, body):
    champion = body.get("championName")
    companions = list(body.get("companionNames") or [])
    chapter_idx = int(body.get("chapterIdx") or 0)
    if not (2 <= len(companions) <= 3): return 400, {"error": "choose 2-3 companions"}
    if not asc.champion_eligible(champion): return 400, {"error": "that unit has no Deck Master ability -- not eligible as Champion"}
    for name in [champion] + companions:
        if not asc.resolve_unit(name): return 400, {"error": f"unknown unit: {name}"}
    # Phase 4.4: companions must be in the account's Ascension ally pool -- no longer "any owned
    # card." Avatars are untouched (still gated by champion_eligible above, not the pool).
    pool = _ensure_ally_pool(user_id)
    for name in companions:
        if name not in pool: return 400, {"error": f"{name} is not in your ascension ally pool yet -- summon them first via /api/asc/ally-summon"}
    prog = store.asc_prog_load(user_id)
    if not asc.chapter_unlocked(chapter_idx, prog): return 400, {"error": "that chapter isn't unlocked yet"}

    # Phase 4.2: pre-Rite provisioning -- real Merchant prices, spent before the Rite starts rather
    # than at a mid-run shop node Story mode doesn't have (see asc.py module docstring). Optional;
    # omitting all three params behaves exactly like the pre-4.2 endpoint.
    buy_items = dict(body.get("buyItems") or {})
    buy_gear = list(body.get("buyGear") or [])
    equip = dict(body.get("equip") or {})
    cost = 0
    for item_id, qty in buy_items.items():
        it = asc._ITEMS_BY_ID.get(item_id)
        if not it: return 400, {"error": f"unknown item: {item_id}"}
        qty = int(qty)
        if qty < 0: return 400, {"error": "item quantity cannot be negative"}
        cost += it["price"] * qty
    seen_gear = set()
    for gear_id in buy_gear:
        g = asc._GEAR_BY_ID.get(gear_id)
        if not g: return 400, {"error": f"unknown gear: {gear_id}"}
        if gear_id in seen_gear: return 400, {"error": f"{gear_id} listed twice in buyGear"}
        seen_gear.add(gear_id); cost += g["price"]
    for name, gear_id in equip.items():
        if name not in companions: return 400, {"error": f"cannot equip gear on {name} -- not a companion in this party"}
        if gear_id not in seen_gear: return 400, {"error": f"must include {gear_id} in buyGear before equipping it"}
    if len(set(equip.values())) != len(equip): return 400, {"error": "the same gear piece cannot be equipped on two companions"}

    c = store.conn()
    u = c.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()
    if u["signal"] < cost: return 402, {"error": f"insufficient Signal (need {cost}, have {u['signal']})"}

    party = asc.instantiate_party(champion, companions, prog, equip)
    if not party: return 400, {"error": "could not build a party"}
    inv = {"potion": 0, "elixir": 0, "revive": 0}
    for item_id, qty in buy_items.items(): inv[item_id] += int(qty)

    rid = "r_" + secrets.token_hex(8)
    with store.tx() as cc:
        ns = u["signal"] - cost
        cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
        if cost: store.ledger_add(cc, user_id, "SIGNAL", -cost, "Ascension: pre-Rite provisioning", ns)
    run = {"chapterIdx": chapter_idx, "map": asc.story_map(chapter_idx), "tier": 0,
           "avatarName": champion, "companionNames": companions, "party": party, "prog": prog,
           "inv": inv, "gear": list(seen_gear), "equip": equip,
           "battle": None, "flawless": True, "done": False, "phase": "pick", "result": None}
    ASC_RUNS[rid] = {"user_id": user_id, "run": run}
    return 200, {"runId": rid, "run": _asc_public(run, user_id)}

def h_asc_pick(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "pick": return 400, {"error": "not choosing a node"}
    tier = int(body.get("tier", -1))
    if tier != run["tier"] or tier >= len(run["map"]): return 400, {"error": "invalid node"}
    node = run["map"][tier]
    if node["type"] == "sanctum":
        # index.html:13913-13918 ascSanctum() -- downed companions revive at 40% max HP, living ones heal 50%.
        for u in run["party"]:
            if u.get("avatar"): continue
            u["hp"] = min(u["maxhp"], u["hp"] + round(u["maxhp"] * 0.5)) if u["hp"] > 0 else round(u["maxhp"] * 0.4)
        run["tier"] += 1
        if run["tier"] >= len(run["map"]): run["phase"] = "done"; run["done"] = True; run["result"] = "won"
        return 200, {"run": _asc_public(run, user_id)}
    run["phase"] = "beat"   # story-beat interstitial -- client shows the node's prose; asc/enter actually starts combat
    return 200, {"run": _asc_public(run, user_id)}

def h_asc_enter(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "beat": return 400, {"error": "no node ready to enter"}
    node = run["map"][run["tier"]]
    foes = asc.foe_stats(node)
    asc.refresh_for_battle(run["party"], run["prog"])
    battle = {"party": run["party"], "foes": foes, "gauge": 0, "queue": None, "qptr": 0, "round": 0, "actor": None, "log": []}
    run["battle"] = battle; run["phase"] = "battle"
    outcome = asc.advance_to_party_turn(battle, battle["log"])
    if outcome: return 200, _resolve_node_outcome(user_id, sess, outcome)
    return 200, {"run": _asc_public(run, user_id)}

def h_asc_act(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "battle" or not run["battle"]: return 400, {"error": "no active battle"}
    battle = run["battle"]
    if battle.get("actor") is None: return 400, {"error": "not your turn"}
    action = body.get("action"); log = battle["log"]; actor_i = battle["actor"]
    if action == "attack":
        ok, err = asc.basic_attack(battle, actor_i, body.get("targetIdx"), log)
    elif action == "move":
        ok, err = asc.use_move(battle, actor_i, int(body.get("moveIdx", 0)), body.get("targetIdx"), log)
    elif action == "item":
        ok, err = asc.use_item(battle, run["inv"], actor_i, body.get("itemId"), body.get("targetIdx"), log)
    elif action == "ultimate":
        # Doesn't consume the actor's turn slot (no gauge add, no queue advance) -- BUT it can still
        # be the killing blow, so battle_over() must be checked here too. A real bug this pass:
        # returning immediately on `ok` without that check left a won/lost battle reporting phase
        # 'battle' forever, since neither gauge_add nor advance_to_party_turn ran to notice it --
        # confirmed via a seeded repro (Keawe's Ultimate finishing the last foe, then the client's
        # next action failing with "invalid target" against an already-dead battle).
        ok, err = asc.ultimate(battle, log)
        if ok:
            outcome = asc.battle_over(battle)
            if outcome: return 200, _resolve_node_outcome(user_id, sess, outcome)
            return 200, {"run": _asc_public(run, user_id)}
    elif action == "flee":
        if random.random() < 0.7:
            run["phase"] = "pick"; run["battle"] = None
            return 200, {"run": _asc_public(run, user_id), "fled": True}
        ok, err = True, None; log.append("The escape attempt fails!")
    else:
        return 400, {"error": "unknown action"}
    if not ok: return 400, {"error": err}
    asc.gauge_add(battle, 16)
    outcome = asc.battle_over(battle) or asc.advance_to_party_turn(battle, log)
    if outcome: return 200, _resolve_node_outcome(user_id, sess, outcome)
    return 200, {"run": _asc_public(run, user_id)}

def _resolve_node_outcome(user_id, sess, outcome):
    run = sess["run"]; node = run["map"][run["tier"]]; owned = _owned_type_names(user_id)
    if outcome == "lose":
        run["flawless"] = False
        return _end_run(user_id, sess, won=False)
    xp = asc._NODE_XP.get(node["type"], 45); sig = asc._NODE_SIGNAL.get(node["type"], 40)
    # Phase 4.4: kill tally (a per-node proxy, not per-kill attribution -- every surviving owned
    # party member gets credit for the whole node's foe count) feeds the per-unit pool-growth
    # threshold below (rules.ASC_POOL_GROWTH_KILLS), alongside the existing level threshold.
    n_foes = len(run["battle"]["foes"]) if run["battle"] else 0
    for u in run["party"]:
        if u["hp"] > 0 and u["name"] in owned:
            asc.grant_xp(run["prog"], u["name"], xp)
            p = run["prog"].setdefault(u["name"], asc.new_prog_entry())
            p["kills"] = p.get("kills", 0) + n_foes
            if node["type"] == "boss":
                p["bosses"] = p.get("bosses", 0) + 1
            if not p.get("poolBonusGranted") and (p.get("level", 1) >= rules.ASC_POOL_GROWTH_LEVEL or p["kills"] >= rules.ASC_POOL_GROWTH_KILLS):
                p["poolBonusGranted"] = True
    with store.tx() as cc:
        u = cc.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()
        ns = u["signal"] + sig
        cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
        store.ledger_add(cc, user_id, "SIGNAL", sig, f"Ascension: cleared {node.get('title') or node['type']}", ns)
        store.asc_prog_save(cc, user_id, run["prog"])
    run["battle"] = None
    is_last = (run["tier"] >= len(run["map"]) - 1)
    if node["type"] == "boss" and is_last:
        return _end_run(user_id, sess, won=True)
    run["tier"] += 1; run["phase"] = "pick"
    return {"run": _asc_public(run, user_id), "outcome": "win", "xpAwarded": xp, "signalAwarded": sig}

def _end_run(user_id, sess, won):
    """index.html's ascEndRun()/ascBattleRunEnd() intent, fixed and unified: the client's real
    mastery write is dead code (only reachable via Abandon, always won=False, keyed off a field no
    run ever sets -- confirmed by research) even though its formulas are clearly the intended
    design. This writes them for real, at true run end, and grants FORGE (not Signal) as the base
    Rite-completion reward -- matching the client's own 7/28/26 fix comment ("forgeGain was being
    added to signalPoints") rather than the pre-fix behavor the OLD server code here still had."""
    run = sess["run"]; champion = run["avatarName"]
    lvl = asc.unit_level(run["prog"], champion)
    flawless = won and run["flawless"]
    if won:
        for u in run["party"]:
            if not u.get("avatar") and u["hp"] > 0 and u["name"] in _owned_type_names(user_id):
                p = run["prog"].setdefault(u["name"], asc.new_prog_entry())
                p["rites"] = p.get("rites", 0) + 1
    with store.tx() as cc:
        row = cc.execute("SELECT wins,flawless,best_level FROM mastery WHERE owner_id=? AND card_key=?", (user_id, champion)).fetchone()
        wins = row["wins"] if row else 0; fl = row["flawless"] if row else 0; best = row["best_level"] if row else 1
        if won:
            wins += 1
            if flawless: wins += 1; fl += 1
        if lvl > best: best = lvl
        cc.execute("INSERT INTO mastery(owner_id,card_key,wins,flawless,best_level) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(owner_id,card_key) DO UPDATE SET wins=?,flawless=?,best_level=?",
                   (user_id, champion, wins, fl, best, wins, fl, best))
        forge_gain = 0
        if won:
            forge_gain = 300 + lvl * 80 + (600 if flawless else 0)
            uu = cc.execute("SELECT forge FROM users WHERE id=?", (user_id,)).fetchone()
            nf = uu["forge"] + forge_gain
            cc.execute("UPDATE users SET forge=? WHERE id=?", (nf, user_id))
            store.ledger_add(cc, user_id, "FORGE", forge_gain, "Rite completed", nf)
        else:
            crow = cc.execute("SELECT uid FROM cards WHERE owner_id=? AND type=? LIMIT 1", (user_id, champion)).fetchone()
            if crow: cc.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (crow["uid"],))
        store.asc_prog_save(cc, user_id, run["prog"])
    run["done"] = True; run["result"] = "won" if won else "lost"; run["phase"] = "done"; run["battle"] = None
    return {"run": _asc_public(run, user_id), "outcome": run["result"],
            "mastery": {"wins": wins, "flawless": fl, "best_level": best}, "forgeGained": forge_gain, "state": user_state(user_id)}

def h_asc_state(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    return 200, {"run": _asc_public(sess["run"], user_id)}

def h_spell_cast(user_id, body):
    sess = _get_match(user_id, body.get("matchId"))
    if not sess: return 404, {"error": "match not found"}
    m = sess["m"]
    if m["done"]: return 400, {"error": "match complete"}
    s = _SPELLS.get(body.get("spellId"))
    if not s: return 400, {"error": "unknown spell"}
    sid = s["id"]
    if sid not in m.get("spellHand", []): return 400, {"error": "that spell is not in your hand"}
    cost = max(0, s["cost"] - m.get("spellDiscount", 0))
    if m["charge"] < cost: return 402, {"error": f"not enough Charge (need {cost}, have {m['charge']})"}
    m["charge"] -= cost
    # 8/5/26: was a flat cap of 5 forever -- the real cap scales with match progress (duel_energy_cap),
    # same bug class as the 3 flat-5 caps already fixed in engine.py this pass.
    if sid == "overclock": m["charge"] = min(engine.duel_energy_cap(m.get("matchCommits", 0)), m["charge"] + 2)
    elif sid == "staticpulse": m["spellOppPow"] = m.get("spellOppPow", 0) - 3
    elif sid == "overload": m["spellOppPow"] = m.get("spellOppPow", 0) - 6
    elif sid == "amplify": m["spellSelfPow"] = m.get("spellSelfPow", 0) + 3
    elif sid == "jammer": m["spellJam"] = True
    elif sid == "nullwave": m["spellNullOpp"] = True
    elif sid == "ledgerward": m["spellShield"] = True
    # recall: WC->hand model differs server-side; charge is spent, effect simplified
    m["spellDiscount"] = 0
    m["spellHand"].remove(sid)
    return 200, {"cast": sid, "charge": m["charge"], "spellHand": m["spellHand"],
                 "armed": {"oppPow": m.get("spellOppPow",0), "selfPow": m.get("spellSelfPow",0),
                           "jam": m.get("spellJam",False), "nullOpp": m.get("spellNullOpp",False), "shield": m.get("spellShield",False)}}

ROUTES = {
    ("POST","/api/auth/register"): (h_register, False),
    ("POST","/api/auth/login"):    (h_login, False),
    ("GET", "/api/state"):         (h_state, True),
    ("POST","/api/match/start"):   (h_match_start, True),
    ("POST","/api/match/commit"):  (h_match_commit, True),
    ("POST","/api/deck/set"):      (h_deck_set, True),
    ("GET", "/api/deck/get"):      (h_deck_get, True),
    ("POST","/api/spell/cast"):    (h_spell_cast, True),
    ("GET", "/api/match/state"):   (h_match_state, True),
    ("POST","/api/pvp/queue"):     (h_pvp_queue, True),
    ("POST","/api/pvp/leave"):     (h_pvp_leave, True),
    ("GET", "/api/pvp/state"):     (h_pvp_state, True),
    ("POST","/api/pvp/commit"):    (h_pvp_commit, True),
    ("POST","/api/pvp/forfeit"):   (h_pvp_forfeit, True),
    ("POST","/api/pvp/challenge/create"): (h_pvp_challenge_create, True),
    ("GET", "/api/pvp/challenge/status"): (h_pvp_challenge_status, True),
    ("POST","/api/pvp/challenge/cancel"): (h_pvp_challenge_cancel, True),
    ("POST","/api/pvp/challenge/join"):   (h_pvp_challenge_join, True),
    ("POST","/api/pvp/challenge/direct"):   (h_pvp_challenge_direct, True),
    ("GET", "/api/pvp/challenge/incoming"): (h_pvp_challenge_incoming, True),
    ("POST","/api/friends/request"): (h_friend_request, True),
    ("POST","/api/friends/accept"):  (h_friend_accept, True),
    ("POST","/api/friends/decline"): (h_friend_decline, True),
    ("GET", "/api/friends/list"):    (h_friend_list, True),
    ("GET", "/api/asc/shop"):      (h_asc_shop, True),
    ("POST","/api/asc/loadout"):   (h_asc_loadout, True),
    ("GET", "/api/asc/ally-pool"): (h_asc_ally_pool, True),
    ("POST","/api/asc/ally-summon"):(h_asc_ally_summon, True),
    ("POST","/api/asc/start"):     (h_asc_start, True),
    ("POST","/api/asc/pick"):      (h_asc_pick, True),
    ("POST","/api/asc/enter"):     (h_asc_enter, True),
    ("POST","/api/asc/act"):       (h_asc_act, True),
    ("GET", "/api/asc/state"):     (h_asc_state, True),
    ("GET", "/api/market/listings"):(h_listings, True),
    ("POST","/api/market/buy"):    (h_buy, True),
    ("POST","/api/market/sell"):   (h_sell, True),
    ("GET", "/api/ledger"):        (h_ledger, True),
    ("GET", "/api/shop/forge-tiers"):(h_forge_tiers, True),
    ("POST","/api/shop/buy-forge"): (h_buy_forge, True),
    ("POST","/api/forge/convert"): (h_convert, True),
    ("GET", "/api/pack/catalog"):  (h_pack_catalog, True),
    ("POST","/api/pack/open"):     (h_pack_open, True),
    ("POST","/api/trade/propose"): (h_trade_propose, True),
    ("POST","/api/trade/accept"):  (h_trade_accept, True),
    ("POST","/api/trade/decline"): (h_trade_decline, True),
    ("GET", "/api/trade/list"):    (h_trade_list, True),
    ("POST","/api/trade/tradeables"): (h_user_tradeables, True),
}

def auth_user(headers):
    a = headers.get("Authorization", "")
    if not a.startswith("Bearer "): return None
    row = store.conn().execute("SELECT user_id, created FROM sessions WHERE token=?", (a[7:],)).fetchone()
    if not row: return None
    try:
        age = time.time() - calendar.timegm(time.strptime(row["created"], "%Y-%m-%dT%H:%M:%SZ"))
        if age > _SESSION_TTL_DAYS * 86400:
            with store.tx() as c: c.execute("DELETE FROM sessions WHERE token=?", (a[7:],))
            return None
    except Exception: pass
    PRESENCE[row["user_id"]] = time.time()
    return row["user_id"]

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, status, obj):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization,Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self._send(204, {})
    def do_GET(self):  self._route("GET")
    def do_POST(self): self._route("POST")
    def _route(self, method):
        path = self.path.split("?")[0]
        if method == "GET" and path in ("/", "/index.html", "/client.html"):
            try:
                with open(CLIENT_PATH, "rb") as f: b = f.read()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers(); self.wfile.write(b); return
            except Exception: return self._send(404, {"error": "client.html not found"})
        if method == "GET" and path == "/favicon.ico": return self._send(204, {})
        if path == "/api/health": return self._send(200, {"ok": True, "service": "signal-forge tier0"})
        if path.startswith("/api/"):
            rlkey = self.headers.get("Authorization", "") or self.client_address[0]
            if not _rate_ok(rlkey): return self._send(429, {"error": "rate limit — slow down"})
        entry = ROUTES.get((method, path))
        if not entry: return self._send(404, {"error": "no such route"})
        handler, needs_auth = entry
        body = {}
        if method == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                try: body = json.loads(self.rfile.read(n) or b"{}")
                except Exception: return self._send(400, {"error": "bad json"})
        elif "?" in self.path:
            body = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
        user_id = None
        if needs_auth:
            user_id = auth_user(self.headers)
            if not user_id: return self._send(401, {"error": "auth required"})
        try:
            status, out = handler(user_id, body)
        except Exception as e:
            return self._send(500, {"error": str(e)})
        if status == 200 and method == "POST": _persist_session(path, body, out)
        self._send(status, out)

def main():
    store.conn(); seed()
    print(f"⬢ Signal Forge — Tier 0 authoritative server")
    print(f"  listening on http://{HOST}:{PORT}  ({'local-only' if HOST == '127.0.0.1' else 'network-accessible'})")
    print(f"  DB: {store.DB_PATH}")
    print(f"  currency: Signal ◈ = cards (earn/play + market) · Forge ❖ = premium (buy + convert 1:100, no cash-out)")
    print(f"  endpoints: /api/auth/register|login  /api/state  /api/pack/open  /api/trade/propose|accept|decline|list  /api/market/listings|buy|sell")
    print(f"             /api/shop/forge-tiers|buy-forge  /api/forge/convert  /api/ledger  /api/health")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
