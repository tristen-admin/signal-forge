# Signal Forge — Systems Reference
*Compiled 2026-07-28. Grounded in the live source (`index.html`) — every number below was pulled from the running code, not recalled from memory. Companion to `MASTER_FIX_SHEET.md`, which lists what to change; this explains what exists today.*

---

## 1. Match structure

A **match** is a sequence of **duels**. Each duel is one card-vs-card power comparison. A player wins the match by reaching `matchWinThreshold()` duel-wins: **2 in Ranked, 4 everywhere else** (Public Server, Staked PvP). There is no fixed duel count — a match runs until one side crosses the threshold, so a "best of" framing describes the *maximum* possible duels, not a hard cap most matches reach. Ranked is deliberately shorter (best-2-of-3, since 7/15/26) than casual/PvP (best-4-of-7) — fewer, higher-stakes duels per ranked match.

Per-duel constants:
- **Starting hand:** 5 cards (`STARTING_HAND`)
- **Draw per turn:** 1 (`DRAW_PER_TURN`) — symmetric for player and bot
- **Max hand size:** 7 (`MAX_HAND`)
- **Deck size:** 16–20 cards (`MIN_DECK`–`DECK_SIZE`) — a range by design, not a bug; no deck-out stalling risk exists in this game
- **Rear-guard (support) slots:** 2 (`RG_SLOTS`)
- **Link power cap:** 4 power max per commit from active card-pair Links (`LINK_POW_CAP`)

## 2. The turn cycle

Each turn: `openTurn()` regenerates Charge (§3) → condition/location reveals (`revealCondition()`, drawn from the 32-entry `CONDITIONS` pool, uniformly at random) → the Deck Master ability strip and banish-conjure strip render if applicable → the player stages a card (`stageFighter()`) or activates an instant → `confirmSelection()` locks the choice → `commitCard()` fires, which:
1. Spends Charge equal to the card's `conjureCost()`
2. Runs the committed card's own hardcoded on-commit effects (a large `if(pc.name===X)` chain — draws, banishes, remnant-raises, etc.)
3. Resolves any interactive banish-choice queue (Kiana, Gravecaller Voss, any `CALLED.banishOwn` support) via `chooseBanishFromHand()` — blocks until the player clicks a card
4. Renders the field, picks the bot's response card
5. Schedules `resolve()` 600ms later

`resolve()` then runs the actual power computation across ordered stages (§4), and `playResolutionCinematic()` visualizes the result before the result overlay shows win/lose/tie.

## 3. Charge (Energy) economy

Both player and bot track a `charge`/`oppCharge` pool. Conjuring a Fighter spends Charge equal to its cost; supports are free to field but their Called effects can independently cost or grant Charge.

**The cap has no ceiling** — `duelEnergyCap()`: +1/duel through duel 4 (3,4,5,6), then +2/duel forever after (8,10,12,...30 by duel 16) — deliberate escalation.

**Regen is partial, not a full refill** — `energyRegenPerTurn()`: flat 1/turn through duel 4, then **as of 7/28/26, ~1/3 of the current cap** each turn after (was frozen flat at 2/turn forever, meaning the escalating cap was never actually reachable under real play — fixed this session). Leftover charge always carries between turns.

**Universal charge-gain sources are all card-specific**, not systemic. Every source is gated behind a specific card: `chargeGain` (flat), conditional variants (`chargeGainIfWon`/`chargeGainIfLocked`/`chargeGainIfHandFull`/`chargeGainIfVeteran`), Radiance's Consecrated Reserve (power payoff for banking, not a source itself), and one-shot Deck Master MAX-Charge bonuses (Signal Diviner +2, Warpath Vanguard +1).

## 4. The `resolve()` pipeline

As of 7/28/26 its stages run in this order:

1. **Stage 1 — Energy/Spell/Body effects.** Interrupt-spell power swings, plus hardcoded per-card checks that don't depend on anything else yet (Conduit Adept, Voltcaller, Warpath Vanguard, Trilogy Ward, Moro).
2. **Fire on-commit abilities** (moved here 7/28/26 — previously ran after stage 5, backwards). The committed Fighter's own `CARD_RULES` entry applies (both sides), then the Deck Master's conjure-tier bonus via `applyDeckMasterResolveEffects()` — the "conjure skill."
3. **Rear-guard (support) effects.** Each fielded support's `CALLED` entry applies via `applyCalled()`, using a context snapshot (`hand_len`, `wc_len`, etc.) taken *after* stage 2, so a support reading hand size sees any draw the on-commit stage just produced.
4. **Rally** — flat per-one-cost-ally bonus (Muster-style archetypes).
5. **Living Card Traits** — one conditional trait per card, only if that card is your *current Deck Master*.
6. **Apply condition** — the revealed location's effect, unless neutralized or unmade.
7. **Determine winner**, then **resolution effects** (Winners Circle banking, K/D updates, etc.).

### The Deck Master conjure-tier system (`conjureTierOf()`)
Every conjure is scored 1–4 based on *what was conjured*:
- **Tier 1** — conjured your Deck Master itself → `DM_EXCLUSIVE` (9 cards carry a real one)
- **Tier 2** — conjured a non-common card in your Deck Master's own archetype → `ARCHETYPE_VANILLA`
- **Tier 3** — conjured a non-common, off-archetype card → universal splash bonus
- **Tier 4** — conjured a **Common**-rarity card, full stop → **no Deck Master bonus fires**

This last rule is exactly why an all-Common hand used to force a forfeit-or-redraw dead end (removed this session). Rarity governs ability strength and this tier system, never legality — a principle confirmed still holding everywhere except one leftover UI spot (the Deck Master ★ button in Deck Slots, also fixed this session).

### DM Passive vs DM Activated Ability
- **DM Passive** — the tier-1 `DM_EXCLUSIVE` bonus, fires automatically on conjure.
- **DM Activated Ability** (16 entries) — a manually-triggered, once-per-*match* button, built on shared primitives (`scry(n)`, turn-scoped effect flags, hand/deck/WC/banish movement helpers).

## 5. Card systems

**134 cards** in `DECK_POOL`, across 5 rarity tiers with a defined print-run supply cap: Apex/AR (100), Ultra/UR (1000), Rare/R (2500), Uncommon/UC (4000), Common/C (5000). Uncommon is normalized into Common at boot and no longer meaningfully exists at runtime.

**Cost** (`baseCardCost()`): inline `c.cost` wins; else `COST_OVERRIDE` (23 named exceptions); else a pow-tier default (pow≥19→4, ≥14→3, ≥10→2, else→1). Max normal cost is **4**.

**Two declarative effect systems**, both consumed by `applyRuleList()`:
- **`CARD_RULES`** — a Fighter's own on-commit conditional bonuses. Vocabulary: `if`/`add`/`addvar`/`mult`/`set`/`oppadd`/`chargeGain`/`energyCost`/`log`.
- **`CALLED`** — what a card does as a fielded support (fires unconditionally). Vocabulary: `text`/`add`/`draw`/`chargeGain` and its conditional siblings/`banishOwn`/`twinBuff`/`snipeSupport`/`snipeFailAdd`/`recurPlain`/`recurBuff`/`conjureTopToSupport`/`deckBanishIfEmpty`/`deckBanishAdd`/`scry`, plus a few bespoke one-offs.

**Shield** (`shield(c)`): `Math.max(2, 10 - 2*baseCardCost(c))`, keyed to fixed base cost so a temporary discount can't warp the printed stat. Replaced an older mechanic where a support's cost silently added to power with no on-card indication. **Not yet consistently shown everywhere** — visible on the Vault grid and hover preview, but missing from the Deck Builder's pool grid, the Deck Slots list, and the Card Detail Drawer (see fix sheet).

**`NAME_OVERRIDE`** — a pure display-name remap (`dispName()`), 3 entries (Corvus, Arch-Grim Korrin, Kiana), correctly applied in the Vault/Deck Builder pool/Card Detail Drawer, and (as of this session's fix) the Deck Slots list too.

**Rarity governs ability strength, never legality or base power.**

## 6. Archetypes

Nine built archetypes (`ARCHETYPE_PRESETS`): **Black Wings** (banish-for-power), **Deathless** (Death Remnant stack-and-draw, Grim Korrin), **Warpath** (kill-count escalation, Tange Sazen/Kravyn), **Broodswarm** (hand-size payoff), **Ironsworn** (Muster/Rally, cheap-bodies-go-wide — the most forgiving onboarding archetype), **Black Council** (Zerith Var), **Radiance** (Consecrated Reserve charge-banking, Moro/Kaelthar/Ourevos), **Keawe's Circle**, and **Circle of Life** (formerly Ahdor's Pride — conjure-from-banish, gated behind `banishOnly` cards unplayable from hand). Three of these (Ironsworn, Broodswarm, Black Wings) are the starter paths offered to new players.

A separate, deliberately narrower registry (`ARCHETYPE_MEMBERS`) exists purely to gate Deck Master tier-2 bonus eligibility, so editing a deck preset can never accidentally change bonus eligibility.

**Known overlap, not yet decided:** Keawe's Circle and Circle of Life share 5 members verbatim; Broodswarm's hand-size identity (12/17 members) and Ironsworn's repeated Muster-N template (7/15, 5 at N=3) are flagged as deliberate identity, not filler — open design questions, see fix sheet.

## 7. Conditions (Locations)

32 entries in `CONDITIONS`, selected **uniformly at random** each duel — the `prob` field is **display-only** and does not weight the actual draw.

**Design rule enforced this session:** a condition may add real randomness *on top of* the power comparison (a bonus, a random pick from your own cards) — deck quality still matters. It may never **replace** the comparison with something disconnected from either side's actual cards (a coin flip, independent rolls). Two conditions that violated this (Fortune's Table, The Sundered Veil) were removed 7/28/26.

Conditions have a live dev-editor (Shift+D → 📍 Locations) for name/icon/mechanic-label/tag/prob/rule/strategy text, since a condition's real behavior is hand-coded per-`id` inside `resolve()` rather than a generic interpreter.

## 8. Banish-zone mechanics (three distinct systems)

1. **Tannis-blueprint instants** — cost-1 instants that trade themselves (return to deck or banish) for a one-time power surge or disruption effect.
2. **Player-choice banish** — Kiana/Gravecaller Voss/`CALLED.banishOwn` supports let the player pick which card to banish via an interactive modal, never random.
3. **Circle of Life conjure-from-banish** — `banishOnly:true` cards (currently 2: Ahdorah Khaan Circle Unbroken, Kynaht Ashen Return) can only be conjured from the banish pile, gating a strong effect behind actually filling it first.

## 9. Bot AI

The bot mirrors most player-facing systems: its own Charge pool (same cap/regen rules), its own Deck Master identity with tier-1/2/3 conjure bonuses, its own rear-guard supports, its own Death Remnant stack (built for Korrin specifically, 7/24/26). Known, deliberate asymmetries: bots skip the tier-3 universal splash bonus (would raise difficulty broadly beyond what was asked); Korrin's tier-1 bonus depends on a Death-Remnant mechanic only the *player's* own losses currently populate.

## 10. Hub, Game Modes & Navigation

**Hub**: Camp Banner (reflects the named Deck Master's camp), welcome/chapter headline ("Chapter 1 · Rebirth"), a stat row (Ladder Rank, Cards in Vault + Pristine count, Season Record), Daily Quests (Win 2 duels/Conjure 3 fighters/Check the Marketplace — all three tracking hooks confirmed internally consistent), an "AR Featured" showcase card, and five mode-launch buttons.

**Public Server**: 5 bots (`BOT_OPPONENTS`, difficulty 1-4), each with a named signature card. Picking a bot enables a normal match (your built deck, or the 12-card `DEFAULT_DECK` fallback if under `MIN_DECK`); a separate Sandbox button deals a fully random 20-card pool from the whole collection. Casual: best-of-7 (first to 4), Signal-only rewards, no RP change.

**Ranked Ladder**: 6 tiers (Bronze <800 through Master 2400+ RP), opponent difficulty scales with tier. Best-of-3 (first to 2). RP moves by `matchWager × stakeMult` (base 20, doubled per successful in-match Raise, capped at ×8). Wins also convert staked RP into Signal (3000/100RP) and rank-scaled Bounty.

**Staked PvP**: player sets a stake floor, picks a rival (stake auto-derived from the rival's difficulty), picks a card to stake, both sides approve, then it's best-of-7. Either side can Raise (stake a whole additional card, up to 4/side) between duels — the AI auto-matches or folds. At series end the winner mints the loser's *entire final pot*, not just the original stake — "winner takes them" means the whole escalated pot.

**Draft**: costs 2,500 Signal, 10 picks from 4-card rows (rarity-weighted, excludes starter-set cards), kept cards mint and are usable immediately, no follow-up step. Fully repeatable via "Redraft," despite framing as a one-time onboarding mechanic.

**Navigation**: Hub · Play (Public Server/Ranked/Staked) · Limited Events (Draft + a weekend-only Tournament addon) · Collection (Vault/Deck Builder/Mastery & Bonds/Trade/Side Stories/Expeditions) · Ascension · Market (Shop/Marketplace) · Reference (Conditions/Abilities/Card Growth) · Records (Legend Board/Match Arc/Card DNA/Match Replay). Every sidebar entry routes to a real view — no dead links found in the base sidebar.

**Settings**: Sound/Music/Reduce Motion toggles, all persisted, all functioning — Reduce Motion in particular blankets every element on the page via a single CSS rule, not a hand-picked subset.

**STALE until 8/17/26 — corrected below.** This line used to say neither mode had real networked
play. That's no longer true for one of the two, and was never quite true for how they're split:

- **Ranked Ladder and the Online screen's Public/Casual matchmaking (`Find a match`) ARE real
  networked PvP**, server-authoritative via `server/pvp.py` — a real queue (`/api/pvp/queue`,
  FIFO for casual/best-of-7, closest-RP-first for ranked/best-of-3), real per-duel commit/resolve
  between two real accounts (`server/engine.py` run once per side and reconciled), a 60s per-duel
  decision timer enforced server-side even if nobody is polling (`_enforce_deadline`/`_sweep`),
  real per-duel card draw, private-match challenge codes, and (added 8/17/26) a records-revealed
  step: once both sides stage a card, each sees the OTHER's real win/loss record — never their
  card's identity — before independently choosing to commit or withdraw. Verified working via
  live two-account tests and deployed to production (play.koteitcg.com) as of this correction.
- **Staked PvP is still bot-only** — `enterOnlineMode('staked')` routes to the single-player
  `v-pvp` view (a real card wagered against an AI rival), not `server/pvp.py`. Its own "(Rival AI
  stands in until networked play ships.)" disclosure is accurate as written; only Ranked's copy of
  that line was ever describing something that has since shipped.

## 11. Deck Building & Collection

**Vault**: renders all 134 base cards plus dynamically-minted instances (wins, variants, ascendant mints), split into fresh/veteran buckets. Filters: Rarity, Keyword, Archetype, Owned-only toggle, plus the cost-curve histogram itself acts as a click-to-filter. Sort: Rarity/Newest/Most Kills/Fewest Deaths/Highest Cost.

**Cost-curve histogram** (shared by Vault and Deck Builder): buckets by `conjureCost()`, overlays a "recommended range" — cost ≤3 should be ≥50% of the pool, grounded in the hypergeometric odds of an all-cost-4+ opening hand given a 3-Charge start and a 5-card hand from a 16-20 card deck. Descriptive only, never enforced.

**"Pristine" status has three different, disagreeing definitions** computed by three separate functions (0 deaths+1 kill / +2 kills / +5 kills), all surfacing the literal word "Pristine" in different parts of the same Card Detail Drawer — needs a single definition, not three (see fix sheet).

**Card DNA**: career K/D, K/D *since this copy was acquired*, a full Ownership Chain (each entry: owner, date, `via` reason), and a flavor-only "Provenance" block (deterministic pseudo-mint-index from a hash of the card's name — no real backing store, purely cosmetic but stable).

**Deck Builder**: `DECK_SIZE=20` max, `MIN_DECK=16` min — any size in between is equally legal (the ready-status pill now correctly reflects this, fixed this session). Adding/removing funnels through `rebuildDeckPool()`, keeping the slots list, pool grid, cost curve, and power-average readout in sync. Saved presets have no size validation at save/load — only checked at match start.

**Deck Master picker**: a single global (not per-preset) value. `setDeckMaster()` requires the card be in the active deck — no rarity requirement since 7/12/26 (confirmed, and the one remaining stale UI gate + toast copy were fixed this session). Starter paths auto-assign a path-specific Deck Master.

**Starter deck chooser**: one-time "Choose Your Path" modal, exactly 3 options (Ironsworn/Broodswarm/Black Wings), no preview of the actual card list before committing. No in-UI way to re-open and switch later (by design).

**Art/asset pipeline**: `CARD_ART`/`CARD_ART_FULL`/`CARD_SIGIL`/`VIDEO_*`, all inline base64. Resolution order: video > static image > sigil-on-gradient. **71 of 173 collection cards (41%) currently have no unique art or sigil** — an active, ongoing content-production gap, not a code defect (includes all 8 Squad 19 cards and several named Apex/Ultra characters).

## 12. Reference, Records & Market

**Reference** (sidebar group): three static-lookup screens, none of them affect live play — **Conditions** (the 32-entry `CONDITIONS` table, §7, with its live Shift+D dev-editor), **Abilities** (`buildAbilView()`, the `KEYWORDS` glossary — 15+ entries like Instant/Rally/Death Remnant/Record Guard/Kill Escalation/Last Stand/Banish Surge — one plain-English paragraph per keyword, shown wherever a card carries that tag), and **Card Growth** (`buildGrowthCodex()`, the living-card doctrine: K/D tracking, the Ownership Chain, Pristine status, and the trade-transfer promise, see below).

**Records** (sidebar group): four screens reading the same underlying data from different angles.
- **Legend Board** (`buildLegendBoard()`): every collection card ranked by `legendScore()` (a weighted fusion of match record, mastery, and bonds, `legendBreakdown()`), bucketed into tiers by `legendTier()`, with an estimated `legendPrice()` (`marketPrice(c) * legendMultiplier(c)`) shown per row. **This estimate is displayed with the ❖ Forge icon, but the real Marketplace it's estimating a value for transacts exclusively in ◈ Signal** — a live icon/currency mismatch (see fix sheet).
- **Match Arc**: per-match narrative/turn-by-turn log.
- **Card DNA**: per-card career K/D, K/D *since this copy was acquired* (resets via `transferToMe()`, wired into trades this session — previously dead code, see fix sheet), the full Ownership Chain (`{owner, date, via}` per entry), and a flavor-only deterministic "Provenance" index (hash of the card's name, no real backing store).
- **Match Replay**: step-through visual reconstruction of a completed match's turn sequence.

**Market** (sidebar group): two screens, two different economies.
- **Shop**: the mock-purchase Forge storefront (packs, cosmetics) — no real payment processing exists anywhere in this file.
- **Marketplace** (`buildMarket()`): peer-to-peer style card listings, ◈ Signal only ("◈ only / No cash-out" is a permanent, correct stat tile). Floor price, active-listing count, and a "30d volume" figure are all computed live from `marketListings` — **except volume, which has a hardcoded `+184200` floor added on top of real sold totals every time** (`index.html:8389`), so the stat can never honestly read as a quiet/dead market. Selling (`listCard()`) and buying (`buyMarket()`) both move `signalPoints` directly and call `saveState()`; a bought card is minted as a fresh instance via `mintWon()` carrying the seller's `k`/`d` record forward, not reset — by design, since the Marketplace's whole pitch is "the buyer takes its full record."
- **`deckMasterRecord`** (`{k,d}`, `sf_dm_record` in storage) tracks wins/deaths specifically *while a card was your active Deck Master* — incremented and persisted at two call sites (`index.html:7967`, `7980`) but **never read back by any screen**. Currently pure overhead with no player-facing payoff (see fix sheet).

### Cross-cutting: CALLED text vs. real mechanism (a recurring bug class)

Several cards' printed `CALLED` support text describes behavior beyond what their object literal's real fields execute — the text was written aspirationally and the code caught up partially, or not at all. Confirmed instances this pass (full detail in the fix sheet): **Ourevos, the Golden Dragon** (promises a slot-fill-with-copy that has no primitive), **Anorith Keeling** (promises self-return-to-deck + draw/charge that aren't wired), **Kessuae, Tide of Ruin** (promises a "discard" — this engine has no discard-pile concept anywhere, only banish), **Keawe Kel'rua** base card (promises a duel-count condition on its draw that isn't checked — the bonus is unconditional and the draw never fires), and the **Waltz Twins** support pair (Lagertha Waltz / Hanse Waltz base forms describe their bonus as race-gated ("if that unit is a Nightclaw") when the real gate is Link-group membership via `fieldLink()` — a different system entirely, and the two evolved Waltz forms have the identical mechanic with no text describing it at all). None of these are guesses — each was confirmed by reading the card's live object literal against `applyCalled()`'s actual vocabulary.

---

## Open items (see MASTER_FIX_SHEET.md for the full, prioritized list)

The fix sheet captures everything found across a 5-pass audit (this document's own core-systems section, plus dedicated passes over Deck Building/Collection, Hub/Game Modes, Ascension, and Reference/Records/Market) — split into what was auto-fixed, what's flagged as a genuine design decision awaiting your call, and what's a larger undertaking worth its own dedicated pass.
