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

## Resolved
_(move entries here once real code backs the described behavior, with the commit that did it)_
