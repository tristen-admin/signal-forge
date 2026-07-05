"""
Signal Forge — Tier 0 authoritative store.
SQLite (stdlib, zero deps). Balances are mutable; the $FORGE/Signal ledger and the
card ownership chain are APPEND-ONLY, enforced by SQL triggers (real immutability).
"""
import sqlite3, os, threading, time, json

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "signalforge.db")
_lock = threading.Lock()
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

-- secondary market
CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, seller_id TEXT,
  seller_addr TEXT NOT NULL, price INTEGER NOT NULL, k INTEGER NOT NULL DEFAULT 0,
  d INTEGER NOT NULL DEFAULT 0, sold INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL);

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

def conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        _conn.commit()
    return _conn

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
