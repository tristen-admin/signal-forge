# KOTEI: The Trading Card Game (formerly Signal Forge) — operating notes

Read this before touching PvP, deploy, or claiming something "isn't built yet."
The docs elsewhere in this repo (`GAME_SYSTEMS_REFERENCE.md`, `DEPLOY.md`) predate
real online multiplayer and are stale in places — this file is the corrected,
maintained reference for the two things every fresh session gets wrong first:
how online matches actually work, and how this thing actually deploys.

## What this project is

A single-file HTML/JS trading card game (`index.html`, ~1MB source, built via
`build.py` into `dist/`) plus a stdlib-only Python backend (`server/`) that is
**real and live**, not a stub. Single-player (Offline Play, Draft, Reincarnation)
is 100% client-side, `localStorage`-only, no server involved. Online accounts,
Ranked/casual PvP matchmaking, friends, trading, and the marketplace are real,
server-authoritative features backed by `server/*.py` + SQLite.

## Real online PvP — the part that keeps needing re-explaining

`server/pvp.py` is the authoritative real-time PvP engine. Transport is short-
interval HTTP polling (client polls `/api/pvp/state` every ~2s) — **not**
WebSockets, a deliberate choice for the stdlib `ThreadingHTTPServer` this runs
on. `_LOCK` (a `threading.RLock`) serializes every read-modify-write of a game
so two concurrent commits resolve correctly.

**This is real, working, deployed multiplayer between two real accounts.**
Verified repeatedly this project via live two-account tests against an isolated
throwaway server before every production deploy. If you're asked "does online
PvP actually work," the answer is yes — read the match lifecycle below before
assuming otherwise or before re-deriving it from scratch.

### Matchmaking

- `POST /api/pvp/queue` — joins the FIFO queue (casual/`bestOf=7`) or the
  closest-RP-first queue (ranked/`bestOf=3`, `mode:"ranked"`). Pairs immediately
  if someone compatible is already waiting.
- Private matches: `/api/pvp/challenge/create` mints a 6-character code
  (`_CODE_ALPHABET`, no `0/O/1/I/L`), `/challenge/join` redeems it,
  `/challenge/direct` challenges a friend by handle directly (surfaces via
  `/challenge/incoming`).
- A user already inside a live, undone game cannot queue or open a new
  challenge — `join()`'s first check returns `{matched:true, already:true,
  pvpId:<existing>}` so the client can rejoin instead of double-queueing.

### Per-duel lifecycle (the part that changed 8/16–8/17/26 — read this before
touching commit/withdraw/reveal logic)

1. **Deal.** `_new_side()` shuffles the real deck, deals `STARTING_HAND=5`,
   and **guarantees the Deck Master lands in the opening hand** (swaps, never
   inserts, so hand size is untouched) — matches offline's own guarantee.
2. **Stage.** `POST /api/pvp/commit {pvpId, cardUid, rearGuardUids}` — each
   side stages a fighter + supports. This does **not** resolve the duel by
   itself anymore (it did before 8/17/26 — see below). Once both sides have
   staged, `_view()`'s new `revealOpponentRecord` field populates with the
   *opponent's* real per-card k/d — **never their card's identity** — so each
   side can see whether they're about to risk their card's record against a
   proven opponent, exactly the offline `#record-reveal` panel's own promise,
   done honestly (offline can show the bot's identity because it already knows
   the bot's pick; a real opponent's card is genuinely secret until resolution,
   so only the record — not the card — is ever revealed).
3. **Confirm or withdraw.** `POST /api/pvp/confirm {pvpId, action}`,
   `action` = `"commit"` or `"withdraw"`. Only valid once both sides have
   staged. Withdrawing concedes the duel with **no K/D recorded on either
   card** (mirrors offline's `retreatCard()` exactly) — the opponent scores
   the duel, your card returns to hand untouched. Mutual withdraw is a tie.
   Blocked entirely (`400`) when the revealed Condition is `noretreat`
   (`lockedWithdraw` in the view). A side that lets the deadline expire here
   defaults to `"commit"`, never `"withdraw"` — silence must not be a free,
   riskless way to dodge a bad matchup.
4. **Resolve.** Only once both sides have confirmed `"commit"` does
   `_resolve_duel()` run: `engine.resolve()` executes once per side (dry pass
   for true power → provisional pass for outcome → reconcile guards that only
   ever convert a loss into a tie → real pass that mutates state once), see
   the long docstring at the top of `pvp.py` for why this two-sided-resolver
   shape exists instead of a single joint resolver.
5. **Draw for the next duel.** `_draw_for_turn()` — deck first, Winners Circle
   once the deck's empty, capped at `MAX_HAND=7`, `DRAW_PER_TURN=1`. This did
   **not exist** before 8/17/26 — there was no baseline per-duel draw online
   at all, only the Condition's own reveal-time draw/discard (`_reveal()`,
   still separate and still runs after this). If hands ever look like they're
   not refilling again, check this function first before assuming the whole
   deck system is broken — it was, once, for exactly that reason.

### Timers, stalling, and abandonment

- `TURN_SECONDS=60` per duel, covering both the stage step and the confirm
  step as one shared window — `_enforce_deadline()` scores a stalled duel
  (never voids the whole match) and is called from both `state()` and
  `_sweep()`, so it fires even if nobody is actively polling.
- `_sweep()` also ends a match if **one side goes silent past
  `ABANDON_TTL=45s` while the other is still present** — awarding the match to
  whoever stayed. Before 8/17/26 this required **both** sides silent, which a
  genuinely present, honestly-polling player could never satisfy on their own
  — a vanished opponent (e.g. via a client bug that exited without telling the
  server) trapped the present side in an endless "neither committed" loop
  forever. If a match ever seems stuck cycling skipped duels with a real
  human still there, this is the first place to check.
- The **only** correct way to concede a whole match client-side is
  `pvpForfeit()` → `POST /api/pvp/forfeit`. `hudFold()` now checks real
  `PVP.pvpId`/`pvpBoardOn` **first**, before any single-player branch, and
  delegates to `pvpForfeit()` — fixed at the function itself (8/17/26), not
  just at the button, because `exitMatch()` ("Exit to Lobby," the most
  prominent button on the whole screen) calls `hudFold()` directly and was
  still reaching `retreat('player')` (pure single-player, no server call)
  even after the button itself got hidden. If you ever add a new "leave/
  quit/fold" affordance anywhere in `v-turn`, make it call `pvpForfeit()`
  when `PVP.pvpId` is set — don't assume the existing single-player exit
  paths (`hudFold`, `retreat`, `exitMatch`) are safe to reuse as-is; they
  weren't, twice.

### `v-turn` is shared DOM — audit single-player leakage before assuming a
new PvP surface is safe

The PvP board renders into the SAME DOM as the offline duel (`#hand-row`,
`#player-field`, `#v-turn`'s whole toolbar), so every single-player-only
button already living in that markup is technically clickable during a real
match unless something explicitly neutralizes it. Confirmed instances found
by direct audit (8/17/26), beyond `hudFold()` above: `#draw-btn`
(`drawCard()`) and `#reveal-btn` (`revealCondition()`, which gates on the
single-player `phase` global and would overwrite the real server-provided
condition with a random offline one) both needed a defensive reset in
`pvpBoardEnter()`, and `#result-overlay` is a **descendant of `#v-turn`**,
not a sibling view — switching to the PvP board does not hide it the way
switching to a different top-level view would, so a stale offline win/lose
screen could render on top of a live match. All three are now reset in
`pvpBoardEnter()`, same pattern as the pre-existing
`confirm-btn`/`commit-btn`/`forfeit-round-btn`/`.wager-hud` hides. Before
adding anything new to `v-turn`'s static markup, check whether
`pvpBoardEnter()` needs to know about it too — don't assume "PvP doesn't use
this element" means "PvP can't reach it."

### What's real multiplayer vs. still bot-standin

- **Real, server-authoritative, two-real-accounts PvP**: Ranked Ladder, and
  the Online screen's "Find a match" (casual/public, `bestOf=7`).
- **Still single-player vs. an AI rival**, despite the name: **Staked PvP**
  (`enterOnlineMode('staked')` routes to the local `v-pvp` view, not
  `server/pvp.py`). Its own in-UI disclosure ("Rival AI stands in until
  networked play ships") is accurate. Don't assume it shares any code path
  with the real PvP system above.

### Client/server drift prevention

Card stats, Deck Master rules, Charged Spells, and starter decks are each
defined once on the **client** (the live game is the reference implementation)
and exported to a server-side JSON file via a one-off Node/`eval` pass whenever
they change: `server/dm_rules.json`, `server/energy_spells.json`,
`server/starter_decks.json`, `server/server_gifts.json`. If client and server
ever disagree about a card's stats or a spell's effect, check whether one of
these exports is stale before assuming the bug is in the resolution logic.

## Deploy — two genuinely separate things

**`git push` to `main` only updates the GitHub Pages client** (`docs/`,
built from `index.html` via `python3 build.py` then `rsync dist/ docs/`).
It does **not** touch the production server.

**Production server is a manually-managed DigitalOcean droplet**, not a git
checkout:

- Host: `root@198.199.122.144` (droplet `ubuntu-s-1vcpu-512mb-10gb-nyc1`),
  SSH key `~/.ssh/id_ed25519` already present locally. `root` works; `kotei@`
  does not.
- Code lives at `/root/server/` as a **plain file copy**, managed by the
  systemd unit `signalforge.service`
  (`ExecStart=/usr/bin/python3 /root/server/app.py`, `Restart=always`, runs
  as root).
- `/root/server/data/` is the **live SQLite DB with real accounts** — WAL
  mode, so recent writes live in `.db-wal`/`.db-shm` sidecars, not just the
  base `.db` file. Copying just the base file for a safe local test copy will
  silently miss recent data — copy all three files together.
- Public domain `play.koteitcg.com` resolves via a **Cloudflare Tunnel**
  (anycast IPs), not a direct A-record to the droplet.

**Safe update procedure, every time, no exceptions:**
1. `ssh root@198.199.122.144 "mkdir -p /root/server_backup_<date>_<label> && cp /root/server/<changed files> /root/server_backup_<date>_<label>/"`
2. `scp` only the explicitly-changed `.py` files by name — never a wholesale
   sync, never `--delete`, never touch `data/`.
3. `ssh root@198.199.122.144 "cd /root/server && python3 -m py_compile <changed files>"` — confirm clean **before** restarting the live service.
4. `ssh root@198.199.122.144 "systemctl restart signalforge && systemctl is-active signalforge"`.
5. Verify against the real production URL (`curl -s -o /dev/null -w '%{http_code}' https://play.koteitcg.com/`, plus whatever endpoint actually changed) and confirm existing accounts' data survived.

Restarting the service clears in-memory PvP match state (`GAMES = {}` is a
plain dict, not persisted) — any live match in progress at deploy time is
gone, not paused. Warn before deploying during active testing if that matters.

`DEPLOY.md` in this repo describes the **pre-multiplayer** state (`server/` as
"not-yet-wired," client as "`localStorage`-only") and is stale — trust this
section over it until someone rewrites it.

## Before claiming something isn't built

Grep `server/pvp.py` and `server/app.py` first. This project has been burned
before by an agent (and a stale doc) both asserting real multiplayer didn't
exist when it did — re-verify against the actual code, not against
`GAME_SYSTEMS_REFERENCE.md`'s PvP section, which needs a fuller pass than the
one line already corrected there.
