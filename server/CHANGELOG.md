# Signal Forge Backend — Changelog

## Traits: one active trait per card (equip model) · 2026-07-03

Playtest feedback: a maxed 99-5 card stacked +cap self **and** Feared −1 on the
opponent — a 4-point swing on ~8 base power that flattened the base-power
hierarchy (a "powerhouse" card no longer felt like one). Fixed to mirror the
client's new equip model.

- **`rules.active_trait(rec, equipped=None)`** — selects ONE trait: the equipped
  one if still earned, else the strongest (by power, then priority). No more
  summing/stacking.
- **`engine.py` resolve** + **`resolve_duel`** now apply only that single trait.
  Max self-buff drops from +4 (cap) to +2; Feared / Untouchable / Bloodthirsty
  compete for the one slot instead of compounding. Maxed card on base 8 vs 8:
  was 11 vs 7 (4-pt gap), now 10 vs 8 (2-pt gap) — matches the client.
- `equippedTrait` on a card is honored server-side (foundation for the client's
  equip picker). Old `trait_power_bonus` / `is_*` helpers kept for reference.
- KNOWN GAP (unchanged): server still applies traits to the player card only; the
  client's symmetric opponent-trait application is not yet mirrored (pre-existing).

## Build step + server spell system · 2026-07-03

The two remaining follow-ups, done.

- **`sync_rules.py`** — regenerates the client's inline `CARD_RULES` from `server/rules.json` (single
  source of truth). Idempotent, validates JSON first; verified the client `CARD_RULES` deep-equals
  `rules.json` (27 cards).
- **Charge/Interrupt spells on the server** (`engine.py` + `app.py` + `spells.json`): a charge economy
  (+1/turn, plus Conduit Adept / Voltcaller / Signal Diviner), lost-round spell draw, and
  `POST /api/spell/cast` (validates charge, spends it, arms the effect). 8 spells (`spells.json`,
  mirroring the client's `ENERGY_SPELLS`): Overclock / Static Pulse / Amplify / Overload / Jammer /
  Recall / Nullwave / Ledger Ward. The engine applies armed effects — Amplify (+self), Static Pulse /
  Overload (−opp), Jammer (negate condition), Nullwave (negate opp guard), Ledger Ward (block a death).
  `charge` + `spellHand` are exposed in match responses.
- Verified: charge builds +1/turn; a lost round drew Overclock; casting it spent 1 + added 2 (2→3);
  power-spell arming + application confirmed.

Note: `spells.json` mirrors the client's `ENERGY_SPELLS` (kept aligned; the client's spell UI stays
the parallel session's — the server now validates + applies casts authoritatively). Recall is
simplified server-side (the Winners-Circle→hand model differs).

## Shared rules spec — client adopted (big-one step 2) · 2026-07-03

The **client** now computes on-commit abilities from the same spec as the server — parity drift is
closed. (Client change lives in the game file / `index.html`; recorded here for the full picture.)

- Client `resolve()`'s ~27 hardcoded ability branches replaced by an inline `CARD_RULES` table (a copy
  of `server/rules.json`, server = canonical) + a JS interpreter (`evalRuleCond` / `applyCardRules`),
  mirroring `engine.py`. Veronica copies via the opponent's rules, same as the server.
- Behavior-preserving: traits, formations, conditions, resolution guards, Charge/spell hooks, and
  win-state trackers unchanged; only the on-commit power branches moved to data.
- Verified live: CARD_RULES = 27 cards; Kotei → "🔥 Kotei: +3" (DUEL WON); Forgemask-after-loss →
  "Reforged +3" + "Tempered +4"; zero console errors.

Only follow-up left: a tiny **build step** to regenerate the client's `CARD_RULES` from
`server/rules.json` (they're identical now; keep them so), and the full spell-casting flow.

## Persistence · rules.json · hardening · 2026-07-03

Finished the server-side Tier-0 work — everything that doesn't require touching the client.

- **Persistent sessions** (`store.py` + `app.py`): matches + Ascension runs persist to a
  `game_sessions` table (JSON state, sets encoded), with load-from-DB fallback in `_get_match` /
  `_asc_sess` and router-level save after every mutating POST. **Verified: a match resumed after a
  full server restart** (score [2,0] loaded from DB, continued to [2,1]).
- **`rules.json`** (`engine.py`): the ability `RULES` table is now an external data file the engine
  loads — the shared-spec artifact the client can adopt (step 2). 27 cards / 36 rules; parity unchanged.
- **Hardening** (`app.py`): 30-day session-token expiry (checked + pruned in `auth_user`) + a lenient
  per-token/IP rate limiter (300 req / 60 s → 429). Verified: limiter blocks past 300; old tokens rejected.

Remaining (coordination-gated with the parallel session): the **client** reading `rules.json` so both
sides share one rules definition; the full spell-casting flow.

## Data-driven rules — server interpreter (the "big one", step 1) · 2026-07-03

Converted `engine.py`'s ~27 hardcoded card abilities into a **`RULES` data table + a small interpreter**
(`eval_cond` / `_apply_rules`), the first step toward one shared rules spec so parity stops drifting.

- Each card → ordered rules: `{if: <condition>, add/addvar/mult/set/oppadd, log}`. Conditions compare
  context vars (opp_deaths, opp_pow vs pc_pow, last_result, match_commits, player_wins/losses, hand_len,
  wc_len, skullchain, ragwing, chaos, wc_has) with and/or nesting.
- Veronica now copies via the same table (applies the opponent card's rules) — cleaner than the old
  hand-picked subset.
- **Behavior-preserving**: the 7 parity unit tests reproduce the hardcoded engine's results exactly
  (Kotei 21, Lowest flip, Ruffius 14, Untouchable tie, Ability Lock 18, Ahdor tie, Feared −1);
  full match (3/3 commits) + Rite channel smoke-test pass.

Step 2 (coordinated): have the **client** read the same data so both sides share one rules definition.
Also still pending: persistent match/run sessions, full spell-casting flow.

## Rule gaps closed — Formations · spell hooks · Ascension+mastery · 2026-07-03

Closed the three parity gaps the match-engine port flagged.

- **Formations** (`engine.py` + `store.py` + `app.py`): new per-user `bonds` table; cards that play
  together accrue pair-bonds at match end; `best_formation()` grants +power (Allied/Brothers/Legendary
  at 3/8/15) when both are in the deck. Verified: Kotei+Ahdor @8 → +2 in resolve.
- **Charge/spell hooks** (`engine.py`): `resolve()` now applies armed spell effects (Jammer negates the
  condition, Interrupt/Amplify power) + Conduit Adept / Voltcaller charge gains, cleared per duel. The
  spell-*casting* flow stays client-side — that's the parallel session's evolving Stage-1 system.
- **Ascension + mastery** (`asc.py` + `app.py`): server-authoritative Rite — 6-tier map (Duel/Elite/
  Sanctum/Relic Shrine/Boss), channel combat, 8 boons, scars. Endpoints `asc/start|pick|channel|boon|
  state`. **Mastery (`avatarBond` wins/flawless/best_level) is written to the `mastery` table
  server-side**, feeding traits + Legend; a won run pays Signal (300 + 25/level + 150 flawless), a
  defeat records a **scar** (a death) on the avatar. Verified: full run to a flawless boss kill at
  Lv 18 → +900 Signal, mastery {wins:2, flawless:1, best:18}, avatar Legend → 224 (Renowned).

Remaining before the "big one" (data-driven rules): persistent match/run sessions (in-memory today),
the full spell-casting flow, and any ongoing client rule drift.

## Rules parity — authoritative match engine · 2026-07-03

Ported the client `resolve()` to a server-authoritative match engine. The server now **plays the real
game** — all on-commit abilities, the 8 power conditions, Living-Card traits, and the resolution guards.

- **`server/engine.py`** — faithful port: 42-card `CATALOG` (pow/kills/deaths/rarity/abil); `resolve()`
  with ~30 name-keyed abilities (Kotei, Veronica-copy, Malia, Ruffius ×2, Darwin, Tange Kill-Escalation,
  Alucard, Ella, Kiana, King Joris, Broodmother, Forgemask, the Series-1 / Werewolf / True-Form set…);
  conditions (lowest/surge/mirror/forceswap/provingground/hollowreckoning/recordties/abilitylock);
  traits applied **before** abilities (matches client order); resolution guards (Ahdor Record Guard,
  Last Stand, Regenerating Horror, Untouchable, opponent Record Guard); best-of-7 match state.
- **`rules.py`** — added `is_bloodthirsty`.
- **`app.py`** — in-memory match sessions + endpoints `match/start`, `match/commit` (server picks the
  opponent + condition, resolves, applies the outcome to the committed instance's record, awards +40
  Signal/win and +100 RP on match win), `match/state`; GET routes now parse query params.

Verified: 7 engine unit tests (Kotei +3 vs pristine; Lowest flip; Ruffius ×2 = (5+Scarred 2)×2 = 14 —
matches client trait→ability order; Untouchable ties a loss; Ability Lock suppresses; Ahdor guard;
Feared −1). Live best-of-7 through the API: full match to 1-4 with Hollow Reckoning / Force Swap /
Malia / Ahdor / Ability Lock / Forgemask all firing; records updated server-side; +40 Signal/win.

Parity caveats (tracked): **formations** omitted (no server `pairBonds` yet); the **Charge/Interrupt
spell system** + instant/pre-commit windows not ported (client UX layer); opponent is a catalog-random
bot; matches are **in-memory** (lost on restart). Durable fix for drift: one shared data-driven rules spec.

## Step 2 — thin client on the authoritative server · 2026-07-03

Wired a browser client to the API, proving the full client↔server loop. Served **same-origin** (the
server serves the client at `/`), so there are no CORS/localhost issues. Note: the published cloud
artifact can't call `localhost`, so this is the **local-first client** — separate from the showcase
artifact by design.

- **`server/client.html`** — zero-dep single-file client: register/login, authoritative vault (from
  `/state`), server-decided duels, market buy/sell in Signal, Forge buy + convert, activity log.
  Balances/records/outcomes all come from the server; the client only renders + requests.
- **`app.py`** — serves `client.html` at `/` (+ `/favicon.ico` → 204); `PORT` now reads from env so
  the preview harness's autoPort works.
- **`.claude/launch.json`** (outside the repo) — added an `sf-server` config for the preview harness.

Verified live in-browser: register → 10-card starter vault + 5,000◈ / 200❖; duel → server-decided
**LOSE** logged (Bixie 0-0 → 0-1); buy **Veronica 420◈** → Signal 5,000→4,580, vault 10→11, the bought
card carries its **5-1** record; starters render "NOT TRADEABLE" (no Sell control), Veronica (non-starter)
has a Sell control.

## Economy aligned to the finalized model · 2026-07-03

Brought the server in sync with the finalized client economy: **Signal (◈) = card currency**,
**Forge (❖) = premium**, **no cash-out**. (The server was previously built with the older
"$FORGE-as-card-currency" naming.)

- **`rules.py`** — added `FORGE_TO_SIGNAL = 100` and `FORGE_TIERS` (5 real-money tiers $4.99→$99.99).
- **`app.py`**:
  - Market **buy/sell now use Signal** (was `forge`). `market/buy` checks/deducts Signal; `market/sell`
    credits Signal.
  - New **`/api/shop/forge-tiers`** (tiers + rate), **`/api/shop/buy-forge`** (SIMULATED real-money
    Forge purchase — no charge), **`/api/forge/convert`** (one-way Forge→Signal at 1:100).
  - Register grants **5,000 Signal + 200 Forge** (was a 12,000 "airdrop"); ledger reasons relabeled.
  - Dropped the `0x…` crypto wallet framing — ownership addresses are now `@handles` (`addr_of()`),
    market address is `@market`.
  - **No cash-out route exists** (Signal/Forge never convert back to money) — the legal shield.
- Verified: register → Signal 5000 / Forge 200 / 10 starters; buy Veronica 420 **Signal** (5000→4580);
  sell 300 Signal (→4880); `buy-forge [blaze]` → +350 Forge (simulated); convert 100 Forge → **+10,000
  Signal**; `POST /api/forge/cashout` → **404** (no such route).

## Starter deck → 10 cards, never tradeable · 2026-07-03

Per design: every player starts with a fixed set that, because everyone owns it, never touches the market.

- **`rules.py`** — expanded `CARD_CATALOG` to 17 types. `STARTER_DECK` is now the fixed **10-card set**
  (Ruffius Rufeldro, Bixie Bee, Malia, Moro, Melanie, Heir of Kaiga, Tange Sazen, Forgemask,
  Valcarion, Ella Ballora — placeholder until the final list is outlined). Added `STARTER_SET` +
  `is_starter(t)`. Tradeable pool = non-starters (Kotei, Akatosh, Ahdor, Darwin, Arch-Grim Korrin,
  Lagertha Waltz, Veronica).
- **`app.py`** — register grants all 10 starters. Starters are **excluded from the market**: seed
  listings are non-starters only (sellers → `@handles`); `market/sell` rejects any starter.
- Verified: register → 10 starters (all `is_starter`); sell-a-starter → 400; listings 6/6 non-starter;
  buy a non-starter → 200.
- ⚠ Server market still denominated in the old `forge` field — **out of sync** with the finalized
  client economy (Signal = card currency, Forge = premium). Alignment pending.

## Tier 0 — Authoritative server foundation · 2026-07-03

First backend for Signal Forge. Implements my recommended first step from the Backend Blueprint —
build server-authority before anything real. Decisions applied: **D1** Path B, Tier 0 first · **D2**
closed-loop $FORGE (not real crypto) · **D3** self-host on `127.0.0.1` · **D4** reuse the
`.claude/plans` auth/session/anti-cheat/immutable-ledger design (dropped its consent/data parts).

### Added
- **`server/store.py`** — SQLite store (stdlib, zero deps). Tables: `users`, `sessions`, `cards`
  (per-instance), `records`, `mastery`, `mint` (global scarcity), `listings`, `ledger`,
  `ownership_chain`. The `ledger` and `ownership_chain` are **append-only, enforced by SQL triggers**
  (any UPDATE/DELETE aborts). WAL mode; write-lock for thread safety.
- **`server/rules.py`** — authoritative game logic (pure functions): pbkdf2 password hashing, card
  catalog + edition sizes, starter deck, capped living-card trait bonus, `resolve_duel`, reward
  emission, `legend_score`/`legend_tier`.
- **`server/app.py`** — stdlib `ThreadingHTTPServer` API on `127.0.0.1:8787`. Endpoints:
  `auth/register`, `auth/login`, `state`, `match/resolve`, `market/listings|buy|sell`, `ledger`,
  `health`. Bearer-token sessions; permissive CORS for local dev.
- **`server/README.md`** — architecture, run instructions, endpoint table, real-vs-stubbed, roadmap.
- **`server/CHANGELOG.md`** — this file.

### Guarantees now enforced server-side
- Client can only **read** state and **request** validated actions — no route writes balances/records directly.
- Duel outcomes, opponent power, and Signal/RP rewards are computed on the **server**.
- $FORGE is **closed-loop**: buy deducts + delivers the card with its record; sell credits + releases it.
- Every value change → an immutable `ledger` row; every ownership transfer → an immutable `ownership_chain` row.
- Global `mint` ledger enforces true edition scarcity.

### Verified end-to-end (stdlib `urllib`, live server)
- `register` → 6-card starter vault, 5,000 Signal, 12,000 FORGE.
- 5 server-resolved duels → record 1–4, Signal 5000 → 5040 (server-emitted, not client-set).
- `buy` Moro for 420 FORGE (12,000 → 11,580); `sell` Ella Ballora for 2,000 FORGE (→ 13,580).
- Anti-cheat: foreign-card resolve → **404**; no-token read → **401**; a `set-balance` route → **404**
  (does not exist); direct `UPDATE ledger` and `DELETE ownership_chain` → **ABORT** (append-only).

### Not yet (tracked)
- Wire the browser client (`index.html`) to the API; `localStorage` → cache. *(Tier 0 step 2.)*
- Full rules parity with the client `resolve()` (abilities/conditions/formations/Ascension + mastery writes).
- Real matchmaking + PvP (opponent is a server RNG placeholder).
- Session expiry, rate limiting, migrations, backups.
- Real-money $FORGE (blueprint Option 2/3) — deferred behind the legal gate.
