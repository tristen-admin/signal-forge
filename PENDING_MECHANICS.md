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

## Resolved
_(move entries here once real code backs the described behavior, with the commit that did it)_
