#!/usr/bin/env python3
"""
Signal Forge — Tier 0 authoritative server (stdlib only, local-only).
Run:  python3 server/app.py         → binds 127.0.0.1:8787
The client may only READ state and REQUEST validated actions. It can never set its
own balances, records, or outcomes — every mutation is computed and applied here.
"""
import json, secrets, os, time, calendar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
import store, rules, engine, asc

MATCHES = {}   # in-memory match sessions: match_id -> {user_id, m, hand_cards, deck_cards, condition}
_SESSION_TTL_DAYS = 30
_RL = {}   # naive per-key sliding window: key -> (window_start, count)
def _rate_ok(key, limit=300, window=60):
    t = time.time(); w, cnt = _RL.get(key, (t, 0))
    if t - w > window: _RL[key] = (t, 1); return True
    if cnt >= limit: return False
    _RL[key] = (w, cnt + 1); return True
ASC_RUNS = {}  # in-memory Ascension runs: run_id -> {user_id, run, avatarUid}
_SPELLS = {s['id']: s for s in engine.SPELLS}

HOST, PORT = "127.0.0.1", int(os.environ.get("PORT") or 8787)
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
        c.execute("INSERT INTO users(id,handle,pass_hash,salt,created,signal,forge,rp) VALUES(?,?,?,?,?,5000,0,1000)",
                  (uid, handle, rules.hash_pw(pw, salt), salt, store.now()))
        for t in rules.STARTER_DECK: mint_card(c, uid, t, via="Starter grant")
        store.ledger_add(c, uid, "SIGNAL", 5000, "Welcome grant (play currency)", 5000)
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

def h_resolve(user_id, body):
    c = store.conn()
    card = c.execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (body.get("cardUid"), user_id)).fetchone()
    if not card: return 404, {"error": "you do not own that card"}
    rec = dict(c.execute("SELECT k,d,ok,od FROM records WHERE uid=?", (card["uid"],)).fetchone())
    opp_pow = 8 + secrets.randbelow(17)   # SERVER always picks the opponent — client-supplied oppPow is IGNORED (was an authority hole: a client could send a low value to farm guaranteed wins)
    res = rules.resolve_duel(rules.card_pow(card["type"]), rec, opp_pow)
    with store.tx() as cc:
        if res["outcome"] == "win":
            cc.execute("UPDATE records SET k=k+1, ok=ok+1 WHERE uid=?", (card["uid"],))
            u = cc.execute("SELECT signal,rp FROM users WHERE id=?", (user_id,)).fetchone()
            ns, nr = u["signal"] + res["reward"]["signal"], u["rp"] + res["reward"]["rp"]
            cc.execute("UPDATE users SET signal=?, rp=? WHERE id=?", (ns, nr, user_id))
            store.ledger_add(cc, user_id, "SIGNAL", res["reward"]["signal"], "Duel won", ns)
        elif res["outcome"] == "lose":
            cc.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (card["uid"],))
    return 200, {"result": res, "state": user_state(user_id)}

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

def _load_bonds(user_id):
    return {r["pair"]: r["count"] for r in store.conn().execute("SELECT pair,count FROM bonds WHERE user_id=?", (user_id,)).fetchall()}
def _owned_cards(user_id):
    return [{"uid": r["uid"], "type": r["type"]} for r in
            store.conn().execute("SELECT uid,type FROM cards WHERE owner_id=? ORDER BY type", (user_id,)).fetchall()]

def h_match_start(user_id, body):
    owned = _owned_cards(user_id)
    if len(owned) < 4: return 400, {"error": "need at least 4 cards to start a match"}
    m = engine.new_match([c["type"] for c in owned])
    m["bonds"] = _load_bonds(user_id)
    mid = "m_" + secrets.token_hex(8)
    hand_cards, deck_cards = owned[:4], owned[4:]
    m["hand"] = [c["type"] for c in hand_cards]
    MATCHES[mid] = {"user_id": user_id, "m": m, "hand_cards": hand_cards, "deck_cards": deck_cards,
                    "condition": engine.pick_condition()}
    return 200, {"matchId": mid, "hand": hand_cards, "condition": MATCHES[mid]["condition"], "score": m["playerScore"]}

def h_match_commit(user_id, body):
    sess = _get_match(user_id, body.get("matchId"))
    if not sess: return 404, {"error": "match not found"}
    if sess["m"]["done"]: return 400, {"error": "match already complete"}
    hc = next((c for c in sess["hand_cards"] if c["uid"] == body.get("cardUid")), None)
    if not hc: return 400, {"error": "that card is not in your hand"}
    c = store.conn()
    r = c.execute("SELECT k,d,ok,od FROM records WHERE uid=?", (hc["uid"],)).fetchone()
    rec = dict(r) if r else {"k": 0, "d": 0, "ok": 0, "od": 0}
    pc = engine.card(hc["type"]); oc = engine.card(__import__("random").choice(engine.opponent_pool()))
    sess["m"]["hand"] = [x["type"] for x in sess["hand_cards"]]
    res = engine.resolve(sess["m"], pc, oc, sess["condition"], pc_record=rec)
    # apply the duel outcome to the committed card's live record; award Signal on a win
    with store.tx() as cc:
        if res["outcome"] == "win":
            cc.execute("UPDATE records SET k=k+1, ok=ok+1 WHERE uid=?", (hc["uid"],))
            ns = cc.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()["signal"] + 40
            cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
            store.ledger_add(cc, user_id, "SIGNAL", 40, "Duel won", ns)
        elif res["outcome"] == "lose":
            cc.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (hc["uid"],))
    # draw: remove committed, pull next from deck; roll a fresh condition
    sess["hand_cards"] = [x for x in sess["hand_cards"] if x["uid"] != hc["uid"]]
    if sess["deck_cards"]: sess["hand_cards"].append(sess["deck_cards"].pop(0))
    sess["condition"] = engine.pick_condition()
    out = {"result": res, "opponent": oc["name"], "condition": sess["condition"],
           "hand": sess["hand_cards"], "score": sess["m"]["playerScore"], "match_over": res["match_over"],
           "charge": sess["m"]["charge"], "spellHand": sess["m"]["spellHand"]}
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
                 "done": sess["m"]["done"], "charge": sess["m"]["charge"], "spellHand": sess["m"]["spellHand"]}

def asc_end(user_id, sess, won):
    run = sess["run"]; run["done"] = True; run["result"] = "won" if won else "lost"; run["phase"] = "done"
    atype, lvl, flawless = run["avatar"], run["level"], run["flawless"]
    with store.tx() as cc:
        row = cc.execute("SELECT wins,flawless,best_level FROM mastery WHERE owner_id=? AND card_key=?", (user_id, atype)).fetchone()
        wins = row["wins"] if row else 0; fl = row["flawless"] if row else 0; best = row["best_level"] if row else 1
        if won:
            wins += 1
            if flawless: wins += 1; fl += 1
        if lvl > best: best = lvl
        cc.execute("INSERT INTO mastery(owner_id,card_key,wins,flawless,best_level) VALUES(?,?,?,?,?) "
                   "ON CONFLICT(owner_id,card_key) DO UPDATE SET wins=?,flawless=?,best_level=?",
                   (user_id, atype, wins, fl, best, wins, fl, best))
        sig = 0
        if won:
            sig = 300 + lvl * 25 + (150 if flawless else 0)
            ns = cc.execute("SELECT signal FROM users WHERE id=?", (user_id,)).fetchone()["signal"] + sig
            cc.execute("UPDATE users SET signal=? WHERE id=?", (ns, user_id))
            store.ledger_add(cc, user_id, "SIGNAL", sig, "Rite won", ns)
        else:
            cc.execute("UPDATE records SET d=d+1, od=od+1 WHERE uid=?", (sess["avatarUid"],))
    return {"won": won, "signal": sig, "mastery": {"wins": wins, "flawless": fl, "best_level": best}}

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

def h_asc_start(user_id, body):
    card = store.conn().execute("SELECT * FROM cards WHERE uid=? AND owner_id=?", (body.get("avatarUid"), user_id)).fetchone()
    if not card: return 404, {"error": "you do not own that card"}
    run = asc.new_run(card["type"], engine.card(card["type"])["pow"])
    rid = "r_" + secrets.token_hex(8)
    ASC_RUNS[rid] = {"user_id": user_id, "run": run, "avatarUid": card["uid"]}
    return 200, {"runId": rid, "run": asc.public(run)}

def h_asc_pick(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "pick": return 400, {"error": "not choosing a node"}
    tier, idx = int(body.get("tier", -1)), int(body.get("node", -1))
    if tier != run["tier"] or not (0 <= idx < len(run["map"][tier])): return 400, {"error": "invalid node"}
    node = run["map"][tier][idx]
    if node["type"] == "boon":
        run["phase"] = "boon"; return 200, {"run": asc.public(run), "boons": asc.boon_choices(run)}
    if node["type"] == "sanctum":
        before = run["vit"]; run["vit"] = min(run["maxVit"], run["vit"] + 2); run["tier"] += 1
        return 200, {"run": asc.public(run), "healed": run["vit"] - before}
    run["node"] = node; run["champVit"] = node["vit"]; run["aegisUsed"] = False; run["phase"] = "channel"
    return 200, {"run": asc.public(run)}

def h_asc_channel(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "channel": return 400, {"error": "no active encounter"}
    cp = engine.card(body.get("cardType", ""))["pow"]
    res = asc.channel(run, cp)
    out = {"round": res}
    if run["champVit"] <= 0:
        run["cleared"] += 1
        if "ferocity" in run["boons"]: run["level"] += 1
        if run["node"]["type"] == "boss":
            out["end"] = asc_end(user_id, sess, True); out["run"] = asc.public(run); out["state"] = user_state(user_id); return 200, out
        run["node"] = None; run["tier"] += 1; run["phase"] = "pick"
    elif run["vit"] <= 0:
        out["end"] = asc_end(user_id, sess, False); out["run"] = asc.public(run); out["state"] = user_state(user_id); return 200, out
    out["run"] = asc.public(run)
    return 200, out

def h_asc_boon(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    run = sess["run"]
    if run["done"] or run["phase"] != "boon": return 400, {"error": "not at a shrine"}
    asc.apply_boon(run, body.get("boonId", "")); run["tier"] += 1; run["phase"] = "pick"
    return 200, {"run": asc.public(run)}

def h_asc_state(user_id, body):
    sess = _asc_sess(user_id, body)
    if not sess: return 404, {"error": "run not found"}
    return 200, {"run": asc.public(sess["run"])}

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
    if sid == "overclock": m["charge"] = min(5, m["charge"] + 2)
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
    ("POST","/api/match/resolve"): (h_resolve, True),
    ("POST","/api/match/start"):   (h_match_start, True),
    ("POST","/api/match/commit"):  (h_match_commit, True),
    ("POST","/api/spell/cast"):    (h_spell_cast, True),
    ("GET", "/api/match/state"):   (h_match_state, True),
    ("POST","/api/asc/start"):     (h_asc_start, True),
    ("POST","/api/asc/pick"):      (h_asc_pick, True),
    ("POST","/api/asc/channel"):   (h_asc_channel, True),
    ("POST","/api/asc/boon"):      (h_asc_boon, True),
    ("GET", "/api/asc/state"):     (h_asc_state, True),
    ("GET", "/api/market/listings"):(h_listings, True),
    ("POST","/api/market/buy"):    (h_buy, True),
    ("POST","/api/market/sell"):   (h_sell, True),
    ("GET", "/api/ledger"):        (h_ledger, True),
    ("GET", "/api/shop/forge-tiers"):(h_forge_tiers, True),
    ("POST","/api/shop/buy-forge"): (h_buy_forge, True),
    ("POST","/api/forge/convert"): (h_convert, True),
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
    print(f"  listening on http://{HOST}:{PORT}  (local-only)")
    print(f"  DB: {store.DB_PATH}")
    print(f"  currency: Signal ◈ = cards (earn/play + market) · Forge ❖ = premium (buy + convert 1:100, no cash-out)")
    print(f"  endpoints: /api/auth/register|login  /api/state  /api/match/resolve  /api/market/listings|buy|sell")
    print(f"             /api/shop/forge-tiers|buy-forge  /api/forge/convert  /api/ledger  /api/health")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    main()
