"""
Signal Forge — Tier 0 authoritative store.
SQLite (stdlib, zero deps). Balances are mutable; the $FORGE/Signal ledger and the
card ownership chain are APPEND-ONLY, enforced by SQL triggers (real immutability).
"""
import sqlite3, os, threading, time, json

# SF_DB points the whole server at a different database file. Same env-override pattern as app.py's
# HOST/PORT, and the reason it exists: an end-to-end test that registers accounts and plays matches
# must be structurally incapable of writing into the real database, not merely careful about it.
# Default is unchanged, so nothing about a normal run differs.
DB_PATH = os.environ.get("SF_DB") or os.path.join(os.path.dirname(__file__), "data", "signalforge.db")
# RLock, not Lock: tx() holds this for its whole `with` block, and conn().execute() (wrapped
# below) takes it too -- a write inside `with tx() as c: c.execute(...)` must be able to
# re-acquire on the same thread without deadlocking against the lock tx() itself is holding.
_lock = threading.RLock()
_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, handle TEXT UNIQUE NOT NULL, pass_hash TEXT NOT NULL,
  salt TEXT NOT NULL, created TEXT NOT NULL,
  signal INTEGER NOT NULL DEFAULT 5000, forge INTEGER NOT NULL DEFAULT 12000, rp INTEGER NOT NULL DEFAULT 1000);

CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT NOT NULL, created TEXT NOT NULL);

-- card instances (each is a distinct individual)
CREATE TABLE IF NOT EXISTS cards(
  uid TEXT PRIMARY KEY, owner_id TEXT NOT NULL, type TEXT NOT NULL,
  mint_index INTEGER NOT NULL, edition INTEGER NOT NULL, created TEXT NOT NULL);

-- per-instance biography (mutable via validated server logic only)
CREATE TABLE IF NOT EXISTS records(
  uid TEXT PRIMARY KEY, k INTEGER NOT NULL DEFAULT 0, d INTEGER NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 0, od INTEGER NOT NULL DEFAULT 0);

-- per-card mastery (Ascension bond)
CREATE TABLE IF NOT EXISTS mastery(
  owner_id TEXT NOT NULL, card_key TEXT NOT NULL, wins INTEGER NOT NULL DEFAULT 0,
  flawless INTEGER NOT NULL DEFAULT 0, best_level INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(owner_id, card_key));

-- global scarcity: how many of each type have ever been minted
CREATE TABLE IF NOT EXISTS mint(type TEXT PRIMARY KEY, supply INTEGER NOT NULL, minted INTEGER NOT NULL DEFAULT 0);

-- Bonds & Formations: per-user pair play counts (cards that fought together)
CREATE TABLE IF NOT EXISTS bonds(user_id TEXT NOT NULL, pair TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(user_id, pair));

-- match/Ascension run sessions (JSON state) so they survive a restart
CREATE TABLE IF NOT EXISTS game_sessions(id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, updated TEXT NOT NULL);

-- 8/5/26 Milestone A: the player's saved deck (ordered card uids, JSON). One active build per
-- user for now -- match/start reads this; falls back to owned[:4] when a user has never saved one
-- (new accounts, or anyone who played before this table existed) so nothing breaks for them.
CREATE TABLE IF NOT EXISTS decks(user_id TEXT PRIMARY KEY, card_uids TEXT NOT NULL, updated TEXT NOT NULL);

-- 8/5/26 Phase 3: per-account pack pity (index.html:9649-9659 packPityUltra/packPityApex -- GLOBAL
-- on the client's single localStorage save, but each server account needs its own, same reasoning
-- as decks above).
CREATE TABLE IF NOT EXISTS pity(user_id TEXT PRIMARY KEY, pack_ultra INTEGER NOT NULL DEFAULT 0, pack_apex INTEGER NOT NULL DEFAULT 0);

-- 8/5/26 Phase 3: real P2P trades (client's own trade UI is confirmed-simulated against fake
-- partners, index.html:12817 TRADE_PARTNERS -- not a spec for real P2P, so this is a fresh design:
-- propose/accept/decline between two real accounts, not a port).
-- 8/5/26 Phase 4: Ascension per-unit progression (index.html's ascUnitProg, client-localStorage-
-- only there). Persists ACROSS runs (a unit's level/xp/rites/bosses/loadout survive between Rites)
-- -- distinct from the in-progress run state itself, which rides the existing game_sessions/
-- ASC_RUNS persistence already wired for match sessions. Keyed by unit NAME (matches the client's
-- own ascUnitProg[u.name] keying), not uid -- Ascension doesn't care which specific owned copy.
CREATE TABLE IF NOT EXISTS asc_prog(
  user_id TEXT NOT NULL, unit_name TEXT NOT NULL, level INTEGER NOT NULL DEFAULT 1,
  xp INTEGER NOT NULL DEFAULT 0, rites INTEGER NOT NULL DEFAULT 0, bosses INTEGER NOT NULL DEFAULT 0,
  kills INTEGER NOT NULL DEFAULT 0, pool_bonus_granted INTEGER NOT NULL DEFAULT 0,
  load_json TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(user_id, unit_name));

-- 8/6/26 Phase 4.4: the Ascension companion roster is no longer "every owned card" -- it's a
-- separately-unlocked pool, starting at a fixed 5 (rules.ASC_ALLY_POOL_STARTERS) and growing via
-- summon (spend Signal/Forge) or per-unit progression (see asc_prog.kills/pool_bonus_granted
-- above). Avatars stay gated by the existing Deck-Master-ability check, untouched by this table --
-- this is a companion-only restriction, "separate yet intertwined" per the owner's own framing.
CREATE TABLE IF NOT EXISTS asc_ally_pool(
  user_id TEXT NOT NULL, unit_name TEXT NOT NULL, source TEXT NOT NULL, unlocked_at TEXT NOT NULL,
  PRIMARY KEY(user_id, unit_name));

CREATE TABLE IF NOT EXISTS trades(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_user TEXT NOT NULL, to_user TEXT NOT NULL,
  offer_uid TEXT NOT NULL, want_uid TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
  created TEXT NOT NULL);

-- 8/7/26: friends list. Same shape as trades above (a two-user relationship row with a status
-- enum) since that precedent already fits perfectly -- a friend request IS a pending two-user
-- relationship until accepted, same as a trade is. 'pending' means from_user asked, awaiting
-- to_user; 'accepted' is mutual. Declines/removals are hard-deleted rather than tombstoned --
-- there's no need to remember a friendship that never happened or that ended, and a fresh request
-- after a decline should just start clean rather than resurrecting a dead row.
CREATE TABLE IF NOT EXISTS friendships(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_user TEXT NOT NULL, to_user TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', created TEXT NOT NULL);

-- secondary market
CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, seller_id TEXT,
  seller_addr TEXT NOT NULL, price INTEGER NOT NULL, k INTEGER NOT NULL DEFAULT 0,
  d INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);

-- 8/16/26: server-side mailbox claims. The client's SERVER_GIFTS table (mirrored to
-- server_gifts.json, same export-from-client pattern as dm_rules/energy_spells/starter_decks)
-- is the only source of truth for what a gift ID is worth -- the amount is looked up here, never
-- trusted from the request, and the PRIMARY KEY makes a double-claim a constraint violation
-- rather than something application logic has to remember to check.
CREATE TABLE IF NOT EXISTS mailbox_claims(
  user_id TEXT NOT NULL, gift_id TEXT NOT NULL, claimed TEXT NOT NULL,
  PRIMARY KEY(user_id, gift_id));

-- APPEND-ONLY: the $FORGE + Signal ledger
CREATE TABLE IF NOT EXISTS ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, user_id TEXT NOT NULL,
  cur TEXT NOT NULL, amt INTEGER NOT NULL, reason TEXT NOT NULL, balance INTEGER NOT NULL);

-- APPEND-ONLY: the card ownership chain (the real "on-chain record")
CREATE TABLE IF NOT EXISTS ownership_chain(
  id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT NOT NULL, from_addr TEXT,
  to_addr TEXT NOT NULL, ts TEXT NOT NULL, via TEXT NOT NULL);

-- immutability triggers: no UPDATE / DELETE on the two ledgers, ever
CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT,'ledger is append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_no_update BEFORE UPDATE ON ownership_chain BEGIN SELECT RAISE(ABORT,'ownership chain is append-only'); END;
CREATE TRIGGER IF NOT EXISTS chain_no_delete BEFORE DELETE ON ownership_chain BEGIN SELECT RAISE(ABORT,'ownership chain is append-only'); END;
"""

class _FetchedRows:
    """Stand-in for a cursor whose rows are already pulled: lets _LockedConnection override
    .execute() without touching any of this codebase's ~50 existing `conn().execute(...)
    .fetchone()/.fetchall()` call sites. Only .fetchone()/.fetchall()/.lastrowid are shimmed
    because those are the only cursor members app.py/pvp.py actually call afterward (checked via
    grep -- no .executemany()/.rowcount()/.description/.cursor() use anywhere on this connection)."""
    def __init__(self, cursor):
        self._rows = cursor.fetchall()
        self.lastrowid = cursor.lastrowid
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None

class _LockedConnection(sqlite3.Connection):
    """ThreadingHTTPServer hands every request its own thread, and every one of them shares this
    one connection (check_same_thread=False only turns off Python's same-thread assertion -- the
    underlying C-level sqlite3 handle still isn't safe for concurrent use by two threads at once).
    tx() already serializes writes through _lock; overriding .execute() here closes the matching
    hole on the read side, which every authenticated request hits via app.py's auth_user(). Two
    concurrent reads/writes racing on the unguarded connection were confirmed (8/7/26) to produce
    either a dropped connection (client sees net::ERR_EMPTY_RESPONSE) or a spurious no-row 401 on
    a token that store.py still has on file -- reproduced live via a friends-panel poll firing two
    parallel GETs, differential-confirmed with curl (same token, 200 OK) seconds after the
    browser's 401. A plain instance-attribute monkeypatch (`conn.execute = ...`) can't do this --
    sqlite3.Connection has no instance __dict__ -- so this subclasses via connect()'s factory=
    instead, the mechanism sqlite3 actually provides for it. Applied once at connect() time, not
    per-callsite, so it covers every existing read (and any future one) without a 50-site sweep."""
    def execute(self, sql, params=()):
        with _lock:
            return _FetchedRows(super().execute(sql, params))

def conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, factory=_LockedConnection)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()
    return _conn

def _migrate(c):
    """CREATE TABLE IF NOT EXISTS can't add a column to a table that already exists on disk (this
    server's DB predates asc_prog.kills/pool_bonus_granted, added 8/6/26) -- ALTER TABLE ADD COLUMN,
    idempotent via a duplicate-column-error catch since SQLite has no ADD COLUMN IF NOT EXISTS."""
    for stmt in [
        "ALTER TABLE asc_prog ADD COLUMN kills INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE asc_prog ADD COLUMN pool_bonus_granted INTEGER NOT NULL DEFAULT 0",
        # 8/16/26 (owner: "patches and hotfixes will force players to reset" — this is the actual
        # fix for that). The chosen starter path was read once at registration and discarded, so a
        # card added to CARD_CATALOG after an account existed could never reach that account short
        # of a fresh registration. Persisting it lets h_login backfill on every sign-in: any catalog
        # card belonging to the recorded path that the account does not yet own gets minted then.
        # NULL for every account that predates this column (nothing to backfill against — the path
        # was never recorded and cannot be recovered), which is a one-time, unavoidable gap for
        # existing accounts only; every account from here on self-heals automatically.
        "ALTER TABLE users ADD COLUMN starter_path TEXT",
    ]:
        try: c.execute(stmt)
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e): raise

def tx():
    """Context: acquire the write lock; commit on success, rollback on error."""
    class _T:
        def __enter__(self):
            _lock.acquire(); return conn()
        def __exit__(self, et, ev, tb):
            try:
                if et is None: conn().commit()
                else: conn().rollback()
            finally:
                _lock.release()
            return False
    return _T()

def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def today():
    return time.strftime("%Y-%m-%d", time.gmtime())

# ── append-only writers (the ONLY way value/ownership changes are recorded) ──
def ledger_add(c, user_id, cur, amt, reason, balance):
    c.execute("INSERT INTO ledger(ts,user_id,cur,amt,reason,balance) VALUES(?,?,?,?,?,?)",
              (now(), user_id, cur, amt, reason, balance))

def chain_add(c, uid, from_addr, to_addr, via):
    c.execute("INSERT INTO ownership_chain(uid,from_addr,to_addr,ts,via) VALUES(?,?,?,?,?)",
              (uid, from_addr, to_addr, today(), via))

# ── game-session persistence (sets are JSON-encoded as {'__set__': [...]}) ──
def _ser(o):
    if isinstance(o, set): return {'__set__': list(o)}
    raise TypeError
def _deser(d):
    return set(d['__set__']) if '__set__' in d else d
def session_save(sid, kind, obj):
    st = json.dumps(obj, default=_ser)
    with tx() as c:
        c.execute("INSERT INTO game_sessions(id,kind,state,updated) VALUES(?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET state=?,updated=?", (sid, kind, st, now(), st, now()))
def session_load(sid):
    r = conn().execute("SELECT state FROM game_sessions WHERE id=?", (sid,)).fetchone()
    return json.loads(r['state'], object_hook=_deser) if r else None

# ── saved deck (Milestone A: real deck persistence, replacing the owned[:4] match/start stub) ──
def deck_save(user_id, uids):
    js = json.dumps(list(uids))
    with tx() as c:
        c.execute("INSERT INTO decks(user_id,card_uids,updated) VALUES(?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET card_uids=?,updated=?", (user_id, js, now(), js, now()))
def deck_load(user_id):
    r = conn().execute("SELECT card_uids FROM decks WHERE user_id=?", (user_id,)).fetchone()
    return json.loads(r["card_uids"]) if r else None

def pity_load(user_id):
    r = conn().execute("SELECT pack_ultra, pack_apex FROM pity WHERE user_id=?", (user_id,)).fetchone()
    return {"pack_ultra": r["pack_ultra"], "pack_apex": r["pack_apex"]} if r else {"pack_ultra": 0, "pack_apex": 0}
def pity_save(c, user_id, pack_ultra, pack_apex):
    c.execute("INSERT INTO pity(user_id,pack_ultra,pack_apex) VALUES(?,?,?) "
              "ON CONFLICT(user_id) DO UPDATE SET pack_ultra=?,pack_apex=?", (user_id, pack_ultra, pack_apex, pack_ultra, pack_apex))

# ── Ascension per-unit progression (persists across runs; see asc_prog schema above) ──
def asc_prog_load(user_id):
    rows = conn().execute("SELECT unit_name,level,xp,rites,bosses,kills,pool_bonus_granted,load_json FROM asc_prog WHERE user_id=?", (user_id,)).fetchall()
    return {r["unit_name"]: {"level": r["level"], "xp": r["xp"], "rites": r["rites"], "bosses": r["bosses"],
                             "kills": r["kills"], "poolBonusGranted": bool(r["pool_bonus_granted"]),
                             "load": json.loads(r["load_json"])} for r in rows}
def asc_prog_save(c, user_id, prog):
    for name, p in prog.items():
        lj = json.dumps(p.get("load") or [])
        pbg = 1 if p.get("poolBonusGranted") else 0
        c.execute("INSERT INTO asc_prog(user_id,unit_name,level,xp,rites,bosses,kills,pool_bonus_granted,load_json) VALUES(?,?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(user_id,unit_name) DO UPDATE SET level=?,xp=?,rites=?,bosses=?,kills=?,pool_bonus_granted=?,load_json=?",
                  (user_id, name, p.get("level",1), p.get("xp",0), p.get("rites",0), p.get("bosses",0), p.get("kills",0), pbg, lj,
                   p.get("level",1), p.get("xp",0), p.get("rites",0), p.get("bosses",0), p.get("kills",0), pbg, lj))

# ── Ascension ally pool (persists across runs; see asc_ally_pool schema above) -- pure read/write,
# no seeding logic here (that's app.py's job, same layering as everything else in this module) ──
def ally_pool_load(user_id):
    rows = conn().execute("SELECT unit_name FROM asc_ally_pool WHERE user_id=?", (user_id,)).fetchall()
    return {r["unit_name"] for r in rows}
def ally_pool_add(c, user_id, unit_name, source):
    c.execute("INSERT OR IGNORE INTO asc_ally_pool(user_id,unit_name,source,unlocked_at) VALUES(?,?,?,?)",
              (user_id, unit_name, source, now()))
