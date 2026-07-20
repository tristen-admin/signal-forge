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

### Kotei — DM Exclusive
**Text says:** "2 cards and return your highest card in hand to the bottom of your deck. During the turn a player activated this ability, all support cards called add their power to the conjured fighter's total value."
**Missing:** draw amount is ambiguous (not yet built either way), hand-card-to-bottom-of-deck movement (no field), and a temporary whole-turn combat-math change where support power adds to the fighter's total (no such aggregation hook exists — support power currently modifies the fighter directly via CALLED's own `add`, it doesn't get separately summed and re-applied).
**To build:** needs a turn-scoped rule type in the DM_EXCLUSIVE/resolution engine, well beyond the current flat/addvar/draw primitives.

### Keawe Kel'rua — DM Exclusive
**Text says:** "Draw 1 card, and scry 1. If that card is a cost 2 or higher, you may play that card for -1 cost next turn."
**Missing:** `scry` itself (tracked since Veronica/Signal Diviner — this is now a 4th card wanting it), plus a novel "conditional discount on a specific scried card, redeemable next turn" mechanic — a stateful, per-card-instance discount window that doesn't exist anywhere yet.

### The Bronzed Beast, Hanse Waltz — DM Exclusive
**Text says:** "When a player activates this ability, and their hand has 3 or less cards, draw 2 and gain 2 charge."
**Partially close to buildable:** the conditional half (`hand_len <= 3`) uses the same `if` comparator already proven elsewhere, and `draw` is a real DM_EXCLUSIVE-adjacent primitive — but `chargeGain` has never been confirmed to resolve inside `DM_EXCLUSIVE` specifically (every existing DM_EXCLUSIVE entry only uses `add`/`addvar`/`raiseRemnant`/`deathLingerBuffOverride`/log). Held back rather than guessing the resolver reads it.
**To build:** confirm (or add) `chargeGain` support in the DM_EXCLUSIVE resolver, then this one is a straightforward single-clause rule.

### Kravyn the Collector — DM Exclusive
**Text says:** "Shuffle your banished cards back into your deck and give your conjured unit +2. Units played on your field this turn return to your hand after the duel concludes."
**Missing:** shuffle-banish-into-deck (no field), and a whole-turn "played units return to hand after duel" effect (no field). The flat +2 alone would be trivial but the rest isn't.

### Arch-Grim Korrin — ability (printed, on-commit)
**Text says:** "Look at the top 2 cards of your deck, place 1 in the support zone and 1 as a death remnant." (now the opening clause of his rewritten ability — his existing "+6 if opponent has fewer career kills" clause is unchanged and still real/working).
**Missing:** a deck-look-and-distribute-to-two-zones effect — no field for looking at multiple top cards and routing them to different zones (support vs. death-remnant) exists.

### Arch-Grim Korrin — DM Exclusive (possible revision, not touched)
**Text says:** "During combat this turn, raise a death remnant of equal power to your lowest strength supporting unit, at the end of your turn scry 1."
**Note:** he already has a real, working `DM_EXCLUSIVE` entry (`raiseRemnant:"self_pow"` + `deathLingerBuffOverride:10`) — this new ask uses a *different* remnant-power source ("lowest strength supporting unit" instead of his own power) plus `scry`. Left his existing entry untouched since it's unclear whether this is meant to replace it or add to it — flag back which one.
**Missing regardless:** `raiseRemnant` only supports `"self_pow"` as a source today, not "lowest supporting unit's power"; `scry` doesn't exist.

### Ghorruk "Gnarly" Judarr — ability (per-2-cards scaling) — FIXED, not actually pending
**Correction:** this was almost logged as text-only by mistake — the real mechanism lives in a separate `CARD_RULES['Ghorruk "Gnarly" Judarr']=[...]` statement outside the main `const CARD_RULES` object (a standalone "BALANCE PASS 2026-07-07" patch block, ~line 9395, that reassigns several cards' rules *after* the main object is declared — grep for `^CARD_RULES\['` to find all of them). It previously computed `addvar:"deck_len",x:1` (+1 per card, no divisor); updated to `x:0.5` so the math now matches the new "+1 per 2 cards" text. Flagging this pattern generically: any CARD_RULES lookup on this file must check for a later reassignment in that patch block too, not just the main object literal — it silently overwrote this session's first attempt at Kravyn the Collector's CARD_RULES edit before this was caught.

### Ghorruk "Gnarly" Judarr — Called (support) effect
**Text says:** "return 1 banished card to the bottom of the deck, scry 1, then +2 power" (destination changed from "to hand," which is what `recurBuff` actually does everywhere else it's used — e.g. Moro, The Regenerating Horror).
**Missing:** `recurBuff` has no "to bottom of deck" variant — every existing use returns to hand. Plus `scry`, same recurring gap.

### La "La" Ballora, the Broodqueen — DM Exclusive (possible revision, not touched)
**Text says:** "For this turn, your conjured unit gains +2 power for each card in both players' winners circles. Then draw 1 and put a card from hand to the winners circle."
**Note:** she already has a real, working `DM_EXCLUSIVE` entry (`addvar:"wc_len",x:1` — her own Winners Circle only, +1 each). This new ask differs in scope (both players' WC, not just hers) and rate (+2, not +1) — left untouched pending which is intended.
**Missing regardless:** no variable currently sums both players' Winners Circle length together (only the player's own `wc_len` exists); no field moves a card from hand directly to Winners Circle.

### Conduit of Chaos, Kleydson — Called (support) effect
**Text says:** "gain 1 max charge for every round you have already won" (was a flat "gain 1 charge").
**Missing:** `chargeGain` is currently a flat number; there's no per-round-win scaling variant (would need something like an `addvar`-style multiplier applied to `chargeGain` specifically).

### Conduit of Chaos, Kleydson — DM Exclusive
**Text says:** "For the rest of the game, you have access to all 3 spell cards you have chosen, then gain 2 max charge."
**Missing:** a permanent, standing game-state change (not a per-conjure buff) — categorically different from every existing DM_EXCLUSIVE entry, which are all instantaneous or duration-scoped to a turn/match. The flat "+2 max charge" alone would be trivial in isolation.

### Sister Mire, Wailing Nightmare — DM Exclusive
**Text says:** "Return your hand to the bottom of your deck, then add your winners circle cards back to your hand, then draw 3 cards and your conjured fighter +5."
**Missing:** hand-to-bottom-of-deck, Winners-Circle-to-hand — neither exists as a field. `draw:3` and `add:5` alone would be trivial but the surrounding sequence isn't buildable piecemeal without misrepresenting what actually happens.

### Black Wings, Ossian Drell — DM Exclusive
**Text says:** "Banish your entire hand, and draw 5 cards, then give your conjured fighter +2 for every card in your banish zone."
**Partially close to buildable:** the "+2 per banish zone card" half maps directly to the existing `addvar:"banish_len"` pattern (see Web-Weaver's Return / Rhaess Korvain's real DM_EXCLUSIVE entries) — but "banish your entire hand" (a bulk hand-to-banish action) has no field, so the setup that feeds the banish count isn't buildable, only the scaling payoff is.

### Corvus — Called (support) effect
**Text says:** "your Fighter +3, scry 1" (the field stays `add:4` — text says +3, another text/number mismatch in this same family as Uso Oso/Hanse Waltz, flagged not resolved).
**Missing:** `scry`, same recurring gap.

### Corvus — DM Exclusive
**Text says:** "Banish the top 2 cards of your deck, draw 1 then scry 1."
**Missing:** deck-banish-from-top (distinct from hand-banish), plus `scry`.

## Resolved
_(move entries here once real code backs the described behavior, with the commit that did it)_
