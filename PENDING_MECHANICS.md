# Pending Mechanics

Cards whose ability/Called display **text** describes behavior the game engine doesn't actually implement yet. Nothing here is broken — the printed power/base effects still work — but the extra clause in the text is currently flavor only. Check this list before setting up a playtesting session; each entry needs real code before the described behavior is true in a match.

Standing practice: add an entry here any time a CALLED/CARD_RULES/ability text edit describes something the current schema/engine has no field or logic for, instead of only mentioning it in chat.

## Open

### Kotei — Called (support) effect
**Text says:** "your Fighter +2; if your fighter wins the battle with this unit supporting, gain +2 charge and instead of going to the winners circle the card returns to the player's hand."
**What actually fires today:** only the flat `+2` (`add:2`).
**Missing:** a post-resolution conditional — "if the supported Fighter wins this duel" isn't a field the CALLED schema evaluates (`add/oppadd/draw/chargeGain` only, no win/loss branch), and there's no existing mechanism for a card to be redirected away from the Winners Circle back to hand as a *support*-triggered outcome.
**To build:** a new conditional check in the support-resolution path (near `resolve()`'s support/Called handling) that, on a duel win where this card was the active support, grants `chargeGain:2` and diverts the Fighter to `hand` instead of `winnersCircle`.

### Uso Oso — Called (support) effect
**Text says:** "your Fighter +2; the lowest power card in your hand is automatically played as a death remnant."
**What actually fires today:** only the flat effect (`add:3` — note this doesn't match the `+2` written in the text; flagged, not resolved, when this was applied 7/19/26).
**Missing:** an "auto-select and play a card from hand" action — no field or engine hook exists for a support effect to reach into hand and force a card into remnant status.
**To build:** a new CALLED field (e.g. `autoRemnantLowest:true`) plus resolution logic that, when a support with that flag fires, finds the lowest-power card in hand and raises it as a Death Remnant (reusing the existing `deathRemnants`/`RAISE_REMNANT` machinery, just triggered from a support effect instead of an on-commit clause).

### Veronica — Called (support) effect
**Text says:** "your fighter gains +2, then scry 1."
**What actually fires today:** nothing — the CALLED entry has no `add` field at all (the export batch this came from, 7/19/26, specified the text with no accompanying numeric field, so none was invented).
**Missing:** both the flat `+2` (needs an explicit `add:2` once confirmed) and a `scry` mechanic — no field or resolution logic exists anywhere in CALLED for looking at and reordering/bottoming top-of-deck cards.
**To build:** confirm the intended `add` value, then a new CALLED field (e.g. `scry:1`) plus a UI/resolution hook that surfaces the top card of the deck with keep-on-top/bottom choices.

### Signal Diviner — Called (support) effect
**Text says:** "gain 1 Charge, or scry 1"
**What actually fires today:** only `chargeGain:3` (unchanged from before this batch — the text was rewritten 7/19/26 to describe a 1-Charge-or-scry choice, but the numeric field still grants a flat 3 Charge with no choice and no scry option).
**Missing:** both the "or" alternative-choice structure (CALLED has no branching/player-choice field — every effect fires unconditionally) and the `scry` mechanic itself (see Veronica above — same missing primitive).
**To build:** a `choice:[...]` CALLED field the player picks between at resolution, one arm being `chargeGain:1`, the other `scry:1` once scry exists.

### Hanse Waltz / Lagertha Waltz / Bixie Bee — race-conditional Called bonus (one generalizable feature, not 3 one-offs)
**Text says:** each grants a flat Fighter buff "plus an additional +2 if that unit is a [Nightclaw / Nightclaw / Wrothlan]" — Hanse Waltz and Lagertha Waltz use the identical Nightclaw wording verbatim; Bixie Bee mirrors the same structure for Wrothlan.
**What actually fires today:** only the flat base number (Hanse Waltz `add:5`, Lagertha Waltz `add:3`, Bixie Bee `add:3` — none apply the +2). Note Hanse Waltz's text says "+3" as the base while its real field is `add:5` — a text/number mismatch same as Uso Oso's, flagged not resolved.
**Missing:** a race-conditional CALLED bonus — no field lets a support's buff check the *supported Fighter's* `raceOf()` and add extra power conditionally. This is the third independent card asking for the same shape, which is a real signal to build ONE feature rather than three bespoke ones.
**To build:** a generic CALLED field, e.g. `raceBonus:{race:"Nightclaw", add:2}`, checked in the support-resolution path via the existing `raceOf(supportedFighter.name)` helper — one implementation serves all three (and any future card in this shape).

### Legend Reborn, Keawe Kel'rua — ability (Conjure) effect
**Text says:** "A Legend Reborn — Conjure (1⚡): add a card of power 15 or higher from your deck to your hand, and reduce its cost by 1."
**What actually fires today:** the tutor half only — `drawPile.findIndex(x => (x.pow||0)>=15)` correctly matches the "15 or higher" threshold and moves the card to hand (see the Conjure handler ~line 5482, toast fallback message just corrected from a stale "18+" to "15+" while verifying this batch). The "and reduce its cost by 1" clause has no corresponding code — the tutored card keeps its normal `conjureCost()`.
**Missing:** a per-instance cost discount applied to a specific tutored card (not a global `COST_OVERRIDE`, since that would discount every copy everywhere, not just this one tutored instance).
**To build:** likely a transient per-card-instance flag (e.g. `_tc.costDiscount=1`) checked wherever `conjureCost()` reads a card's cost, cleared once spent.

### Keawe Kel'rua — ability repeat-condition
**Text says:** "Rising Talent: on commit, +3 power if you lost your last duel. Repeat this effect if you have 1 or fewer support units this battle."
**What actually fires today:** only the single `+3 if lost last duel` check (`CARD_RULES["Keawe Kel'rua"]`, one clause, "⚡ Rising Talent: +3"). No repeat/doubling logic exists.
**Missing:** a repeat-condition primitive — nothing in the CARD_RULES schema lets a clause's effect apply twice based on a battle-wide support-count check (`support units this battle` isn't a tracked variable anywhere yet).
**To build:** first add support-unit-count tracking for the current battle if it doesn't already exist elsewhere, then a `repeatIf` clause type in CARD_RULES that re-applies the same `add` when the condition holds.

### Keawe Kel'rua — Called (support) effect
**Text says:** "your Fighter +3, if there have been at least 2 duels this match then draw 1"
**What actually fires today:** only the flat `add:3`.
**Missing:** a duel-count-conditional draw. Unlike the other gaps here, CARD_RULES already has a working precedent for match-progress-based conditions (`match_commits`-keyed `if` clauses, e.g. Darwin's), so this likely does NOT need a new primitive — it needs the CALLED schema extended to accept an `if`-gated `draw`, mirroring what CARD_RULES already does for `add`.
**To build:** extend CALLED's resolution to accept `{"if":{"v":"match_commits","op":">=","n":2},"draw":1}` shape, reusing the exact condition-evaluation code CARD_RULES already has rather than writing a second copy of it.

### Kravyn the Collector — ability (on-kill choice)
**Text says:** "When this unit kills its enemy unit, you may choose to return this unit to the hand instead of placing it in the winners circle."
**What actually fires today:** nothing — only the flat/tiered power (`CARD_RULES["Kravyn the Collector"]`, now 3 clauses: unconditional +3, +5 at 10+ kills, +2 more at 25+ kills for a combined +7 — see note below on this interpretation).
**Missing:** a post-kill player choice that redirects the winning card away from the Winners Circle into hand. No card in this engine currently does this from a *base ability* (the closest precedent is Kravyn's own existing CALLED text referencing "returned to hand via a card effect," which counts occurrences but doesn't cause them).
**To build:** a choice prompt at kill-resolution time, plus a hand-instead-of-winners-circle redirect path (likely shares plumbing with whatever eventually builds Kotei's Called-effect hand-return, see below).
**Note on Kill Escalation tiers:** the requested text ("+5 at 10+... +7 instead at 25+") was implemented as an *additive delta* — unconditional +3, +5 at 10+, +2 more at 25+ (netting +7 total at 25+) — because the engine's `if` schema has no true mutual-exclusion/range operator, and this delta pattern already matches how Lagertha Waltz, Wrathful Transformation's own CARD_RULES stack (unconditional base + conditional add-on). If "instead" was meant literally (25+ kills gets ONLY +7, not +3+5+2=+10 total), flag it back and the tiers will be restructured.

### Arch-Grim Korrin — ability (printed, on-commit)
**Text says:** "Look at the top 2 cards of your deck, place 1 in the support zone and 1 as a death remnant." (now the opening clause of his rewritten ability — his existing "+6 if opponent has fewer career kills" clause is unchanged and still real/working).
**Missing:** a deck-look-and-distribute-to-two-zones effect — no field for looking at multiple top cards and routing them to different zones (support vs. death-remnant) exists.

### Darwin — DM Activated ability, second clause not built
**Text says (second sentence):** "Whenever your hand is 2 or less cards after your draw phase, can draw 2 and banish 1."
**What's built (7/20/26):** the first sentence — supports add double their conjure cost to the Fighter this duel (`dmSupportDoubleCostThisDuel`).
**Missing:** this second clause is a *recurring* passive trigger ("whenever... after your draw phase"), not a one-time activation effect — architecturally different from the once-per-match `run:` function it was described alongside. Needs a hook into the draw-phase code itself, checked every turn, not just on DM-ability activation.

### Anorith Keeling — DM Activated ability, spell costs not covered
**Text says:** "During this turn, energy costs become zero for all spells and cards in your hand."
**What's built (7/20/26):** `dmZeroCostThisDuel` zeroes `conjureCost()` for every Fighter/Support card — covers "cards in your hand."
**Missing:** spell-cast costs (e.g. Draw Surge's "2⚡") aren't computed through `conjureCost()` — they're likely hardcoded per spell definition. Have not found the spell-cost deduction path yet to add the same override there.

### Tange Sazen — DM Activated ability, opponent-deck disruption not covered
**Text says (second half):** "...and make your opponent return 1 card to the bottom of the deck."
**What's built (7/20/26):** the draw-1-if-opponent-has-2+-round-wins half.
**Missing:** there is no real, populated "opponent's deck" array to manipulate — `oppDrawPileBot` is declared and reset but never actually populated or read anywhere in the engine (dead scaffolding from an unfinished feature). The bot's card selection isn't modeled as an orderable deck today, so "return a card to the bottom" has nothing to act on.

### Ghorruk "Gnarly" Judarr — ability (per-2-cards scaling) — FIXED, not actually pending
**Correction:** this was almost logged as text-only by mistake — the real mechanism lives in a separate `CARD_RULES['Ghorruk "Gnarly" Judarr']=[...]` statement outside the main `const CARD_RULES` object (a standalone "BALANCE PASS 2026-07-07" patch block, ~line 9395, that reassigns several cards' rules *after* the main object is declared — grep for `^CARD_RULES\['` to find all of them). It previously computed `addvar:"deck_len",x:1` (+1 per card, no divisor); updated to `x:0.5` so the math now matches the new "+1 per 2 cards" text. Flagging this pattern generically: any CARD_RULES lookup on this file must check for a later reassignment in that patch block too, not just the main object literal — it silently overwrote this session's first attempt at Kravyn the Collector's CARD_RULES edit before this was caught.

### Ghorruk "Gnarly" Judarr — Called (support) effect
**Text says:** "return 1 banished card to the bottom of the deck, scry 1, then +2 power" (destination changed from "to hand," which is what `recurBuff` actually does everywhere else it's used — e.g. Moro, The Regenerating Horror).
**Missing:** `recurBuff` has no "to bottom of deck" variant — every existing use returns to hand. Plus `scry`, same recurring gap.

### Conduit of Chaos, Kleydson — Called (support) effect
**Text says:** "gain 1 max charge for every round you have already won" (was a flat "gain 1 charge").
**Missing:** `chargeGain` is currently a flat number; there's no per-round-win scaling variant (would need something like an `addvar`-style multiplier applied to `chargeGain` specifically).

### Corvus — Called (support) effect
**Text says:** "your Fighter +3, scry 1" (the field stays `add:4` — text says +3, another text/number mismatch in this same family as Uso Oso/Hanse Waltz, flagged not resolved).
**Missing:** `scry` is now a real, working mechanic (`scryOne()`, built 7/20/26 for the DM abilities) but CALLED's own resolution doesn't call it yet — needs a CALLED field (e.g. `scry:1`) wired to invoke `scryOne()`.

### Darwin — Called: "play the top card of your deck into your open support circle" — no auto-conjure-from-deck-to-support field exists.
### Ourevos, the Golden Dragon — Called: "fill the other support slot with a copy of this card" — no card-duplication-into-a-zone field exists. Text also says +5 while `add` stays 2 (mismatch, flagged not resolved).
### Ahdorah Khaan, Determined Soul — Called: "nullify a random supporting unit from the opponent's field" — no field targets/removes an opposing support. Text says +2 while `add` stays 3 (mismatch, flagged not resolved).
### Tange Sazen — Called: "returns to hand instead of winners circle" — same missing hand-redirect primitive as Kravyn's on-kill ask above (his own base ability already unconditionally returns HIM to hand on win — see `resolve()`'s win-branch — but that's name-hardcoded, not a generic CALLED-triggerable redirect for arbitrary Fighters).
### Anorith Keeling — Called: "return this unit from the support circle to your deck," plus the described draw/charge, have no field/aren't in the given JSON (`banishOwn:1` is the only real field kept). Also confirmed with user: his `pow` field is inert (hardcoded per-name formula + always-"?" display) — not touched, working as intended.

### Grim Korrin bot — Death Remnant never accumulates on the bot's side (deliberately deferred, not built tonight)
**Context:** 7/22/26 AI-deck-completeness pass — flagged 10 days ago in [[project_signalforge_bot_identities]] as a known gap ("Korrin's tier-1 correctly no-ops bot-side... a pre-existing bot-AI gap"), re-confirmed still true and scoped precisely this pass rather than fixed.
**What actually fires today:** `oppEvalPow()`'s context hardcodes `remnant_count:0` always. There is no `oppDeathRemnants` array, no bot-side equivalent of `applyDeckMasterCommitEffects()` (the function that raises a player-side remnant via `raiseRemnant` when a tier-1 Deck Master card commits), and no point in `resolve()`'s win branch where the bot's defeated card (`oc`) is checked for `abil.includes('Death Remnant')` the way `isDeathRemnant` does for the player's `pc`.
**Missing, concretely:** (1) an `oppDeathRemnants` global + `oppRemnantPowSum()` helper, mirroring `deathRemnants`/`remnantPowSum()` exactly; (2) a bot-side commit-time hook (a `applyBotDeckMasterCommitEffects`-shaped function, since Korrin's `raiseRemnant` is a *commit-time stateful* effect per `DM_EXCLUSIVE`, not resolve-time power math — it lives in a different function than `applyBotDeckMasterResolveEffects`, which only does pure power math) called wherever the bot commits its card; (3) a win-branch check pushing to `oppDeathRemnants` when the bot's own card has `Death Remnant` in its `abil` text and loses; (4) wiring `oppRemnantPowSum()` into the bot's committed power the same way the player's `_cpBase` includes `remnantPowSum()` at stage time (likely inside `pickOppCard()`, right before the card is handed off); (5) a clear-on-bot-win, mirroring the `remnantCleared` branch; (6) feeding real `deathRemnants.length`-equivalent into `oppEvalPow`'s `remnant_count` field once the array exists.
**Why deferred rather than built:** this touches bot power math at several sites (commit-time raise, resolve-time read, stage-time inclusion, win-clear) — a wrong wire-up would silently distort bot difficulty across every match using this bot, not just fail to add a feature. This was flagged mid-session while working unsupervised (user asleep, explicit "don't wait" authorization for the rest of tonight's punch list) — the other AI-deck-completeness fixes shipped tonight are structurally safe (data sync, dead-code removal, a single-line draw-direction fix, an additive pre-commit estimate). This one is a genuine new stateful feature and deserves a live-verified pass with someone able to sanity-check bot behavior in real matches, not a solo overnight build. Ready to build directly from the "Missing, concretely" list above whenever picked back up — no further research needed first.

## Resolved

### DM Activated Abilities — 11 cards built as real `run:function()` code, shipped 7/20/26
Built real, working `DM_ACTIVATED_ABILITY` entries (not passive `DM_EXCLUSIVE` — every one of these plain-language asks described a one-time action sequence, matching the *activated*, once-per-match pattern already established for Kravyn/Sister Mire/Black Wings, not the always-on declarative `DM_EXCLUSIVE` pattern). New shared engine primitives added to support them:
- **`scryOne(onDone)`** — a real interactive modal: look at the top card of the deck, choose Keep on Top or Move to Bottom. Used by Keawe Kel'rua, Arch-Grim Korrin, and Corvus's new abilities.
- **Turn-scoped effect flags** (`dmUnitsReturnToHandThisDuel`, `dmSupportAddPowThisDuel`, `dmSupportDoubleCostThisDuel`, `dmNullifyOppSupportsThisDuel`, `dmZeroCostThisDuel`) — set on activation, read inside `resolve()`'s support loops / `conjureCost()`, cleared at the next duel-start reset (same pattern as the pre-existing `dmSupportBonusThisDuel`/`handBanishedThisTurn`).
- **`dmNextConjureDouble`** and **`dmAhdorahBonusPending`** — single-shot deferred flags, consumed and cleared at the same point as the pre-existing `dmNextConjureBonus`.
- **`card._dmScryDiscount`** — a per-card-instance cost discount, checked inside `conjureCost()`, set on a specific scried card object by reference (not a global override).

Card-by-card: **Kravyn the Collector** (replaced — shuffle banish into deck, next conjure +2, wins return to hand this duel), **Keawe Kel'rua** (new — draw 1, scry 1, conditional -1 cost on the scried card), **Kotei** (new — draw 2, bottom your highest card, supports add their own power this duel), **The Bronzed Beast, Hanse Waltz** (new — hand≤3 conditional draw 2 + Charge), ~~**Arch-Grim Korrin** (new, added alongside his existing passive)~~ **removed 7/23/26, see correction below**, **Ghorruk "Gnarly" Judarr** (new — raise a Remnant at hand+banish size), ~~**La "La" Ballora** (new, added alongside her existing passive)~~ **removed 7/23/26, see correction below**, **Conduit of Chaos, Kleydson** (replaced — permanently upgrades to the full 3-spell Chaos Trinity via the pre-existing `energyLoadoutOverride` mechanism, +2 Charge), **Sister Mire, Wailing Nightmare** (replaced — hand to deck bottom, Winners Circle back to hand, draw 3, next conjure +5), **Black Wings, Ossian Drell** (replaced — hand to banish, draw 5, next conjure scales by banish size), **Corvus** (new — banish top 2, draw 1, scry), **Darwin** (new, first clause only — see open entry above for the unbuilt recurring clause), **Ourevos, the Golden Dragon** (new — next conjure's power doubled), **Anorith Keeling** (new, hand/support costs only — see open entry above for spells), **Ahdorah Khaan** (new — nullify opponent's supports this duel, draw 2 if they called none), ~~**Tange Sazen** (new, draw-1 half only)~~ **removed 7/23/26, see correction below**.
_(move entries here once real code backs the described behavior, with the commit that did it)_

### Correction, 7/23/26 — 4 cards had BOTH a passive and an activated Deck Master ability; only one should exist
Direct report: "he has 2 deckmaster abilities, one activate and one passive. It shouldn't be that powerful, needs to only be one. The passive skill needs to overwrite the activated ability." Checked every `DM_EXCLUSIVE`/`DM_ACTIVATED_ABILITY` pair via the real runtime objects (not text search — two of the four have names containing embedded quotes/apostrophes that broke a first regex-based pass, so `Object.keys()` was used instead to be certain). Found **4** cards double-dipping, not just the one reported: **Arch-Grim Korrin**, **Bannerlord Cassian**, **Tange Sazen**, and **La "La" Ballora, the Broodqueen**. Removed each one's `DM_ACTIVATED_ABILITY` entry entirely — the passive `DM_EXCLUSIVE` stays as their one real Deck Master bonus. Verified live for two of the four (Korrin, Ballora): no activate button renders in the Instant Window strip, and the passive still fires correctly on commit/resolve (Korrin raises a self-power Remnant; Ballora's `+1 pow/Winners-Circle-card` still applies). The other two (Cassian, Tange Sazen) share the identical code shape and were verified via a zero-overlap check on the real objects, not re-tested individually in a live duel.
