# Signal Forge — Tier 0 Authoritative Server

The self-hosted, **zero-dependency** backend that makes game state trustworthy. Built as the first
step of the [Backend Blueprint](../../) (decisions: **Path B / Tier 0 first**, **closed-loop $FORGE**,
**self-host**, reuse the `.claude/plans` base).

Today the game is one HTML file where the client owns (and can edit) everything. This server flips
that: **the client may only READ state and REQUEST validated actions — it can never set its own
balances, records, or outcomes.**

## Run

```bash
python3 server/app.py        # no install; binds http://127.0.0.1:8787  (local-only)
```

Requires Python 3 (uses only the standard library: `http.server`, `sqlite3`, `hashlib`, `secrets`).

## Architecture

| File | Role |
|------|------|
| `store.py` | SQLite store. Balances are mutable; the **$FORGE/Signal ledger** and the **card ownership chain** are APPEND-ONLY, enforced by SQL triggers (UPDATE/DELETE abort). |
| `rules.py` | Auth/currency/trait constants + helpers — password hashing, card catalog + editions, Forge tiers, trait predicates, Legend appraisal. Pure functions. |
| `engine.py` | **Authoritative match engine** — faithful port of the client `resolve()`: 42-card catalog, ~30 abilities, 8 conditions, traits, **formations**, spell hooks, resolution guards, best-of-7 state. |
| `asc.py` | **Ascension (The Rite) run engine** — 6-tier map, channel combat, 8 boons, scars; mastery written server-side. |
| `rules.json` | **Shared ability spec** — the data table `engine.py` interprets (the client can adopt this too). |
| `app.py`  | Stdlib HTTP API (`ThreadingHTTPServer`), Bearer-token sessions, routing (POST bodies + GET query params). |

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|:----:|---------|
| POST | `/api/auth/register` | – | create account, seed starter vault, return token + state |
| POST | `/api/auth/login` | – | return token + state |
| GET | `/api/state` | ✓ | authoritative state (balances, cards+records, legend) |
| POST | `/api/match/resolve` | ✓ | single-duel resolve (legacy stub) |
| POST | `/api/match/start` | ✓ | begin a best-of-7 match (deals hand + condition) |
| POST | `/api/match/commit` | ✓ | commit a card → **server** resolves the full duel (abilities/conditions/traits/guards), updates records, awards Signal |
| GET | `/api/match/state` | ✓ | current match score / hand / condition |
| POST | `/api/asc/start` | ✓ | begin an Ascension Rite on an owned card (avatar) |
| POST | `/api/asc/pick` | ✓ | choose a map node (duel/elite/boon/sanctum/boss) |
| POST | `/api/asc/channel` | ✓ | channel a card → **server** resolves the round |
| POST | `/api/asc/boon` | ✓ | claim a relic at a shrine |
| GET | `/api/asc/state` | ✓ | current run state |
| GET | `/api/market/listings` | ✓ | active secondary listings (non-starters only) |
| POST | `/api/market/buy` | ✓ | spend **Signal**, receive the card + its record |
| POST | `/api/market/sell` | ✓ | release a card, receive **Signal** |
| GET | `/api/shop/forge-tiers` | ✓ | Forge purchase tiers + Forge→Signal rate |
| POST | `/api/shop/buy-forge` | ✓ | **simulated** real-money Forge purchase |
| POST | `/api/forge/convert` | ✓ | one-way **Forge → Signal** (no cash-out) |
| GET | `/api/ledger` | ✓ | append-only ledger + ownership chain |
| GET | `/api/health` | – | liveness |

**Currency model (matches the finalized client economy):** **Signal (◈)** is the card currency —
earned by play, spent on the market. **Forge (❖)** is premium — bought with real money (simulated
here), spent on cosmetics, and one-way convertible to Signal (1 ❖ = 100 ◈). **Nothing converts back
to money** — no cash-out is the legal shield.

## What's real now (verified)

- **Accounts + auth** (pbkdf2 password hashing, token sessions).
- **Server-authoritative state** — nothing client-writable; no "set balance" route exists.
- **Server-decided matches** — full best-of-7 with the real rules (30+ abilities, 8 conditions, Living-Card traits, resolution guards) computed in `engine.py`; outcome, opponent, condition, records, and rewards all decided server-side.
- **Closed-loop economy** — market buy/sell in **Signal**; **Forge** (premium) buys via simulated tiers and converts one-way to Signal; no cash-out.
- **Immutable ledger + ownership chain** — every value change and transfer is an append-only row; direct UPDATE/DELETE is blocked by triggers.
- **Global mint ledger** — true edition scarcity across all players.

## Not yet (next steps)

1. **Wire the browser client** (`index.html`) to this API — `saveState`/`loadState`, `resolve`, rewards, and market all become API calls; `localStorage` becomes a cache. *(Tier 0 step 2 — the client is still standalone.)*
2. **Rules parity — done** (`engine.py` + `asc.py`): abilities, conditions, traits, **formations**, resolution guards, best-of-7, and **Ascension + authoritative mastery**. Rules are now **data-driven** (`rules.json`) and **sessions persist** across restart. Remaining (coordination-gated): the **client** adopting `rules.json` so both sides share one spec, and the full **spell-casting flow** (engine hooks exist; casting is the client's evolving Stage-1 system).
3. **Real matchmaking + PvP** — the opponent is a server-side RNG placeholder, not another player.
4. **Hardening** — session expiry, rate limiting, migrations, backups.
5. **Real payment processor** for Forge purchases (the tiers are **simulated** today — no charge). Closed-loop only, behind the legal gate.

## Doctrine

Local-only: binds `127.0.0.1`, single SQLite file, zero external dependencies or cloud. No cash-out
anywhere — Signal/Forge never convert back to money; a real payment processor for Forge purchases is
a separate, legally-gated future step.
