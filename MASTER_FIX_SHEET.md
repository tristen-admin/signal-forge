# Signal Forge — Master Fix Sheet
*Compiled 2026-07-28. Full-systems audit: 4 parallel source-review passes (Deck Building/Collection, Hub/Game Modes, Ascension, Reference/Records/Market) plus direct review of the core duel/charge/resolve/bot-AI pipeline. Companion to `GAME_SYSTEMS_REFERENCE.md`, which explains how everything works; this is the actionable punch list.*

**Severity key:** 🔴 Blocking/incorrect gameplay · 🟡 Visible glitch or real inconsistency · 🟢 Minor polish · 📋 Open design question (not a bug — needs your call, not a fix)

---

## Fixed this pass (commits `996ff9c`, `e59d3ca`, `d296e44`, `3452404` — all verified live before deploy)

🔴 **Ascension: "Resume the Rite" silently wiped the whole run.** `ascParty`/`ascPartySel` were never persisted, only `ascRun` was — a reload mid-Rite left `ascParty` empty, which the wipe-check read as a full party wipe, permanently deleting the run. Both now save/restore correctly.

🔴 **"Exit to Lobby" dodged all Ranked RP loss and Staked PvP forfeiture.** Zero settlement logic — now routes through the same handler (`hudFold()`) every other quit path already used correctly.

🟡 **Ascension: Chapter 2's own finale scaled weaker than Chapter 1's mid-boss.** Per-node difficulty tier reset to 0 every chapter. Added a cumulative tier for difficulty scaling only, without touching the chapter-local field the "last node" check needs.

🟡 **Charge regen froze flat at 2/turn past duel 4** despite an ever-climbing cap — the escalating cap was never actually reachable under real play. Now ramps proportionally (~1/3 of current cap).

🟡 **resolve() stage order: support effects read stale hand size** before the committed Fighter's on-commit ability (which can draw) had even run. Reordered so on-commit abilities fully resolve first.

🟡 **Watchdog could skip a duel's resolution entirely** if an interactive banish-choice modal (Kiana, etc.) was still open when the "stuck cinematic" safety-net fired. Added the same kind of bail-out check the two prior instances of this bug class already used.

🟡 **Deck Master "all-Common hand" forced a false forfeit-or-redraw choice.** Rarity gates the Deck Master bonus tier, never whether a card can be conjured — removed the gate entirely.

🟡 **Two coin-flip conditions** (Fortune's Table, The Sundered Veil) replaced the real power comparison with pure randomness — removed; the design rule ("randomness may add to a real comparison, never replace it") is now in the reference doc.

🟡 **Ranked Ladder screen + global How-to-Play tutorial both said "best-of-7"** — Ranked has been best-of-3 since 7/15/26.

🟡 **Tange Sazen's signature ability + the match-point epic-VFX boost both hardcoded `>=3`**, silently unreachable in Ranked (threshold 2) for the mode's entire history. Now `matchWinThreshold()-1`.

🟡 **Staked PvP's "No Signal, no rank" promise contradicted its own result screen** (shows a flat +50 Signal on every win) — fixed the copy, left the reward alone.

🟡 **Deck Builder's ready-status pill only showed "ready" at exactly 20 cards**, disagreeing with the Hub's own correct "min 16 to play" — per the auditing pass, the single most likely-to-actually-confuse-a-player finding in the whole sweep. Now reflects the real 16-20 range.

🟡 **Renamed cards showed raw names in Deck Slots** while displaying correctly everywhere else on the same screen — added the missing display-name call.

🟡 **Deck Master ★ button still hidden for Commons; failure toast still said "must be AR/Ultra/Rare"** — both stale relative to the rarity gate already lifted 7/12/26. Same "rarity never gates capability" principle as the all-Common-hand fix above, a second UI spot that one didn't reach.

🟢 `ascHowTo()`'s "six-tier gauntlet" copy is wrong for Story Mode (4/3-node chapters) — reworded to honestly describe both structures, since the panel has no mode parameter and is shown before mode selection.

🟢 A ~1.9s window in `ascBattleWin()` meant a reload between two save calls could re-grant a win's rewards on re-clearing the same node — tier now advances before either save fires.

🟢 `autoSimPvp()` hygiene: hardcoded `4` → `matchWinThreshold()` (no behavior change today).

---

## Confirmed still open (pre-existing tracking, re-verified this pass)

🔴 **Kravyn the Collector — "you may choose" is not a real choice.** The code always auto-returns him to hand on any win (and separately on any close loss). *(`PENDING_MECHANICS.md`.)* Needs a decision: build the real choice modal, or simplify the text to match the deterministic behavior.

🟡 **Tange Sazen's DM Activated disruption clause has no target to act on** — the bot's card pool isn't modeled as a real ordered deck anywhere in the engine. *(`PENDING_MECHANICS.md`.)* Needs a bot-deck-modeling pass, not a quick patch.

📋 Broodswarm's hand-size identity (12/17 members) and Ironsworn's repeated Muster-N template (7/15, 5 at N=3) — flagged as deliberate identity, open question is whether Ironsworn's empty tier-2 slot should get one small distinct rule. *(`BALANCE_PROPOSALS_ROUND2.md` §8.)*

📋 Keawe's Circle / Circle of Life share 5 members verbatim, plus 4 more cards claimed by 2-3 archetypes each. *(`BALANCE_PROPOSALS_ROUND2.md` §9.)*

🟢 `ARCHETYPE_ROADMAP.md` is stale — its "no mechanical archetype yet" list (Black Wings, Black Council, Radiance, Keawe's Circle, Ahdor's Pride) has since fully shipped for all five. Needs a refresh pass or a superseded note.

---

## Newly found this pass — not yet fixed

### Deck Building / Collection
📋 **Public Server/Sandbox's "zero consequence / no mark on its record" promise is false.** `recordDuel()` fires unconditionally in every mode, silently stripping a card's Pristine status even in "practice" mode — a real, repeated, bolded promise across 3 screens that the code doesn't honor. Two directions: make the mode actually consequence-free, or admit in the copy that records still count (the match-end screen already does: "Casual match — no rank staked, records still count."). Touches core progression integrity — flagging for your call rather than picking a side.

📋 **Draft decks are 10 cards, under the 16-20 range enforced everywhere else**, with no top-up — won't crash (graceful fallback to Winners Circle then hand-only play) but a full Draft series will run out of fresh cards partway through. Changing `DRAFT_PICKS` changes session length/pacing — a real design call, not a bug fix.

🟡 **Three different, disagreeing definitions of "Pristine"** computed by three separate functions (0 deaths+1 kill / +2 kills / +5 kills), all surfacing the literal word "Pristine" in different parts of the same Card Detail Drawer. Needs one owner-picked definition, not three independently-evolved ones.

🟡 **Shield stat isn't shown everywhere the feature's own design intent says it should be** — visible on the Vault grid and hover preview, missing from the Deck Builder pool grid, the Deck Slots list, and the Card Detail Drawer (the single most detailed card-inspection screen in the game). Touches several render templates — worth a dedicated pass rather than a quick patch.

🟢 Cards acquired via Trade never get a `cardRecords` ledger entry — breaks "Newest" sort for traded-in cards and fabricates their Card DNA provenance (shows "Held in vault" instead of "Traded").

🟢 The fallback safety-net deck (`DEFAULT_DECK`) is 12 cards — smaller than the game's own 16-card legal minimum it's supposed to guarantee. Already self-flagged in-code as a deliberately deferred content decision.

🟢 Deck Builder's card-pool browser has fewer filters/sort options than the near-identical Vault grid (no Archetype filter, no Newest/Highest-Cost sort) — a capability gap between two screens a player will expect to behave the same.

🟢 71 of 173 collection cards (41%) have no unique art or sigil, including all 8 Squad 19 cards and several named Apex/Ultra characters — an ongoing content-production gap, not a code defect.

🟢 A few stale code comments reference outdated card/registry counts (zero player impact) — noted for the next session that touches those functions.

### Hub / Game Modes
🟢 Hub tile's "All cards · casual · zero consequence" subtitle conflates the default-deck Public Server lobby with its separate all-cards Sandbox sub-mode.

🟢 Dead-code hygiene (verified non-visible to players): an orphaned, permanently-hidden legacy sound-toggle button; a computed-but-never-attached "trust rating" variable on every Hub render; an unreachable placeholder headline string; one dead `SCREEN_TITLES` entry; a rival's PvP stake card is fully deterministic (same bot always offers the same specific card, zero variation).

### Reference / Records / Market / cross-cutting
*(Pending — the dedicated audit pass for this area was interrupted by a machine crash before it completed and is being re-run. This section will be filled in once it reports back.)*

---

## Methodology note

Findings came from source-code review (grep + targeted reads, cross-referenced against real runtime values via direct function calls in the browser console where useful), not UI clicking — the four audit passes were explicitly kept off the shared browser tab to avoid racing each other. Everything marked "fixed this pass" was additionally verified live (forced the relevant game state, called the real function, checked the real output) before deploy, not just syntax-checked.
