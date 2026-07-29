# Signal Forge — Master Fix Sheet
*Compiled 2026-07-28. Full-systems audit: 4 parallel source-review passes (Deck Building/Collection, Hub/Game Modes, Ascension, Reference/Records/Market) plus direct review of the core duel/charge/resolve/bot-AI pipeline. Companion to `GAME_SYSTEMS_REFERENCE.md`, which explains how everything works; this is the actionable punch list.*

**Severity key:** 🔴 Blocking/incorrect gameplay · 🟡 Visible glitch or real inconsistency · 🟢 Minor polish · 📋 Open design question (not a bug — needs your call, not a fix)

---

## Fixed post-audit — user-reported (commits `af5064c`, `3cdc0a5`, `d32f368`)

🔴 **Coached tutorial: hand cards were unclickable from step 4 onward, no way to proceed except Skip.** `#coach-box` (the tutorial dialog, anchored `bottom:4.5%`) physically overlapped ~95% of every hand card's clickable area and had no `pointer-events` rule of its own — confirmed with `elementFromPoint()` that a click at a card's own center hit the dialog, not the card, before this fix. Fixed with the same cascading-pointer-events pattern used elsewhere in this file: `.coach-box` is now `pointer-events:none`, with `pointer-events:auto` explicitly restored on just its two real controls (Skip, Next).

🔴 **The tutorial script had no step for Confirm Selection**, a real, required button between staging a Fighter and Commit — so even with the click-blocking fixed, the coach jumped straight from "stage a Fighter" to a commit step with nothing valid to spotlight. Added a step gated on the real `confirmSelection()` call.

🟡 **The commit step's spotlight target, `#commit-btn`, is dead UI** — grep confirms it is only ever set to `display:none` everywhere in the file; the real button is `.rr-commit-btn` in the record-reveal panel (already fixed under task #300, just never updated here). The spotlight was silently falling back to a full-screen dim with nothing highlighted. Repointed to the real button.

🔴 **Bonus find while verifying the above: `commitCard()` crashed outright when conjuring Corvus, Grave-Tithe Acolyte, or Rhaess Korvain at 0 Charge.** Its self-banish-tax branch called `abilLog.push(...)`, but `abilLog` is a variable local to the separate `resolve()` function — a guaranteed `ReferenceError` that aborted the commit mid-mutation (the card was already removed from hand, phase already flipped to `'committed'`) any time a player tried to conjure one of those three cards while out of Charge. Replaced with the same `toast()` pattern already used one line above for an analogous message.

Verified live end-to-end (properly spaced calls, not batched, to avoid racing the tutorial's own 90ms advance hooks): a fresh tutorial run through all 10 steps — draw, reveal, stage, supports, confirm, commit, resolve — reaches a clean `endTutorial()` with zero console errors.

🔴 **Coached tutorial screen was too dim to read, on top of the click-blocking fix above.** Root cause was two-fold, not just the opacity value: (1) the ever-present "?" How to Play button has no awareness of the tutorial — a player who opens it during the tutorial's first two Hub-side steps carries it, still open, into the duel screen, stacking its own independent dim layer on top of the coach's own (a real, always-reachable path for any curious new player). `startTutorial()` now hides the button and force-closes the modal; `endTutorial()` restores it. (2) Even the correctly-isolated single overlay was 80% opacity black, heavy enough to make hand card names/condition text/Charge readouts hard to read — dropped to 58%.

🔴 **Kravyn the Collector — "you may choose" is now a real choice.** Owner's direction: build it properly and make it reusable, since Kravyn won't be the only card with this effect. Built `OPTIONAL_HAND_RETURN` (a plain data table — adding a future card is the whole integration point, no new branch needed) plus `renderHandReturnChoice()`/`resolveHandReturnChoice()`, which take over the result screen exactly the way the existing "round lost — take your pick" choice already does. The card still banks/recycles to its normal destination immediately; the choice offers to redirect it afterward. Verified live: forced both outcomes directly, confirmed both "Return to Hand" (pulls from Winners Circle/deck, increments `handReturnCount`) and "Leave It" (no-op) work correctly, and confirmed the close-loss check reads real post-modifier power, not a naive pre-modifier guess.

---

## Fixed this pass (commits `996ff9c`, `e59d3ca`, `d296e44`, `3452404`, `80c6439` — all verified live before deploy)

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

🔴 **Ascension: Crossroads nodes launched real combat instead of the built reward-picker.** `ascPickNode()`'s dispatcher special-cased `sanctum`/`merchant` but let every other node type — including `crossroads` — fall through to `ascEnterEncounter()`. `ascCrossroads()` (a complete, working no-combat reward-choice screen) existed and was simply never called. The map's own node-type promise was silently broken on every run. Added the missing `else if(node.type==='crossroads')` branch.

🟡 **Ascension Rite wins could never actually grant Forge, and overpaid Signal ~2x.** `ascEndRun(won)` added `forgeGain` — a value scaled and labeled as Forge everywhere else in the UI — directly into `signalPoints` instead of `forgeBalance`. Fixed the currency target and the reward-reveal text/icon to match. Verified live: a forced win now shows 525 Signal / 1140 Forge with no cross-contamination, matching the formulas exactly.

🟢 **6 dead `CARD_RULES` entries removed** (Kaelthar the Ascendant, Kessuae Tide of Ruin, Fifth Frequency Stormcaller, Envoy of Tyrants Ella Ballora, Trophy-Hunter Kessa, The Bronzed Beast Hanse Waltz) — each was silently shadowed by a later `CARD_RULES['Name']=[...]` assignment appended further down the file (plain JS last-write-wins). The live rule already matched printed card text in every case, so this is pure cleanup — but it closes a real trap where a future balance edit to the "obvious" first-found entry would have had zero effect.

🟢 **Three CALLED text corrections**, each brought in line with the already-correct working code: Corvus ("+3" → "+4", matching `add:4`), Uso Oso ("+2" → "+3", matching `add:3`), Muster-Sergeant Bryn (text now discloses its existing `perWCcap:8`).

🟢 **`transferToMe()` — a complete function, never called anywhere — wired into `acceptTrade()`.** The Growth Codex explicitly promises a card's owner-only K/D resets "when the card changes hands," but the reset function that does exactly this was dead code. A traded-in card silently kept its previous owner's K/D and showed a generic "Held in vault" Card DNA reason instead of "Traded." Verified live: forced a trade, confirmed `ok`/`od` reset to 0 and the chain's last entry reads `{owner:'@keanu', via:'Traded'}`.

---

## Confirmed still open (pre-existing tracking, re-verified this pass)

🟡 **Tange Sazen's DM Activated disruption clause has no target to act on** — the bot's card pool isn't modeled as a real ordered deck anywhere in the engine (`oppDrawPileBot` is dead scaffolding: declared and reset every match, never populated or read). *(`PENDING_MECHANICS.md`.)* Owner's direction (7/28/26): build it for real — this is a bot-AI architecture change (a real, orderable bot deck array, mirroring the player's `drawPile`), not a card-text fix, and other cards will want to target "the opponent's remaining deck" too once it exists. Scoped as its own dedicated pass, not bundled into a smaller batch.

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

*Fixed this pass — see above: Crossroads mis-dispatch, Forge/Signal misdirection, 6 dead CARD_RULES entries, 3 CALLED text corrections, transferToMe wire-up.*

🟡 **Legend Board's price estimate shows the wrong currency icon.** `buildLegendBoard()` prints every card's `legendPrice()` as `'≈ ❖ '+fmtPts(...)` (❖ = Forge), but the actual Marketplace it's estimating a value for (`buildMarket()`, `listCard()`, `buyMarket()`) transacts exclusively in ◈ Signal — the wallet, the floor price, every listing, every buy confirmation. A player comparing "what my card might sell for" against "what it actually costs to buy on the Marketplace" sees two different currency symbols for the same number. One-line icon fix once you confirm ❖ was a mistake and not a deliberate signal that Legend "value" and Marketplace price are different things.

🟢 **Marketplace's "30d volume" stat has a hardcoded +184,200 floor baked in permanently.** `buildMarket()`: `const vol = marketListings.reduce(...) + 184200;` — real sold-volume is added on top of a fixed number that never moves, rather than replacing it once real activity exists. Reads as a deliberate "the market looks alive" placeholder rather than a bug, but it means the stat can never honestly reflect a quiet market — flagging for your call on whether/when to retire the floor.

📋 **Two CALLED entries promise mechanics that don't exist anywhere in the engine:**
- **Ourevos, the Golden Dragon** (`CALLED`): text reads "your Fighter +5, **fill the other support slot with a copy of this card**, then draw a card" — only `add:2` is a real field. No "fill empty support slot with a duplicate" primitive exists in `applyCalled()` or anywhere else.
- **Anorith Keeling** (`CALLED`): text reads "**return this unit from the support circle to your deck**, banish 1 card from your hand, draw 2 and gain 1 charge" — only `banishOwn:1` is real. Self-return-to-deck for a support and the draw/charge grant are both unbuilt.
Both need either a real primitive (support-to-deck return, empty-slot-detection + card-copy insertion) or a text rewrite to match `add`/`banishOwn` alone — a scope call, not a quick patch, since the Ourevos case in particular is a genuinely new mechanic (nothing today lets a card duplicate itself into an empty slot).

🟡 **Kessuae, Tide of Ruin's CALLED text promises a "discard" that cannot exist.** Text: "your Fighter +3, draw 1 then discard 1" (`add:3` is the only real field). Confirmed via direct search: this engine has no discard-pile concept anywhere (already self-documented in a code comment at line ~9903 — "this file has no discard-pile concept"). Every other card that uses discard-flavored language ("Dredge," the Sift spell) actually banishes, it doesn't discard. Kessuae's text is the one place that promises a draw-then-discard cycle nothing backs — rewrite to describe the flat +3, or build the draw+banish pairing other cards already use as the real pattern to copy.

🟢 **Keawe Kel'rua's base CALLED text promises a condition it doesn't check.** Text: "your Fighter +3, if there have been at least 2 duels this match then draw 1" — the object literal is `{add:3}` only, no `if`/`draw` field. The bonus is unconditional and there is no draw, ever, regardless of duel count. (Note: his Legend Reborn variant's own DM Activated Ability *does* implement a real duel-count-gated scry/cost-discount elsewhere — this is specifically the base card's Called text that's unbacked.)

🟡 **The "Waltz Twins" support bonus text describes the wrong system — race, when the real gate is Link-group membership.** Lagertha Waltz's and Hanse Waltz's (base forms) CALLED text both read "add an additional +2 if that unit is a Nightclaw" — a `raceOf()`/`CARD_RACE` check. But the actual `+2` (`twinBuff:5`, applied at `index.html:7734`) only fires when `fieldLink()` finds the committed Fighter and this support in the **same LINK_GROUPS entry** ("Waltz Twins," `index.html:6721`) — a completely separate system from race. Worse, the two evolved forms (The Bronzed Beast Hanse Waltz, Lagertha Waltz Wrathful Transformation) carry the identical `twinBuff:5` mechanic but their CALLED text doesn't mention it at all. Net effect: 2 cards describe a condition that isn't the real one, 2 cards don't describe the real mechanic they have. One consistent rewrite ("+2 more if fielded alongside its Waltz Twins partner") would fix all 4 — a text-only fix once you confirm the Link-group gate (not race) is the intended design, which every other twinBuff card already assumes.

🟢 **`deckMasterRecord` is write-only — tracked, persisted, never shown.** Two call sites increment and save it (`index.html:7967`, `7980`, `lsSet('sf_dm_record', ...)`) every time your current Deck Master personally wins or dies, but no screen anywhere reads it back. Legend Board, Card DNA, and the Hub stat row all show *card* K/D, never this DM-specific ledger. Either surface it (a natural fit for the Hub stat row or Legend Board) or remove the tracking — right now it's pure overhead with no player-facing payoff.

🟢 **Dead-code hygiene** (verified non-visible to players, zero gameplay impact): roughly a dozen functions across the Reference/Records/Market screens and cross-cutting helpers are defined but never called from any live render path — superseded by later rewrites the same way the earlier-fixed `pickOppCard()` duplicate was. Noted for the next cleanup pass rather than itemized here individually, since none affect current behavior.

---

## Methodology note

Findings came from source-code review (grep + targeted reads, cross-referenced against real runtime values via direct function calls in the browser console where useful), not UI clicking — the four audit passes were explicitly kept off the shared browser tab to avoid racing each other. Everything marked "fixed this pass" was additionally verified live (forced the relevant game state, called the real function, checked the real output) before deploy, not just syntax-checked.
