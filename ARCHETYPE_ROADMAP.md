# Archetype Mechanics Roadmap

Forward-looking ideas only — nothing here is built. Written 7/22/26 per direct request: "a list of other archetype specific mechanics we should build out in the future based off the current styles and power scale of where we are now." Grounded in the real, current numbers (not invented ranges): flat Called/CARD_RULES bonuses run +2 to +5, conditional swings (Purity/Underdog/Fresh Blood-style) run +5 to +8, kill-escalation/threshold effects run +3 to +7 per tier, and tier-1 Deck Master exclusives currently top out around +8 to +10 under favorable conditions. Anything proposed below should land in those bands unless there's a specific reason to push higher.

## Part 1 — the 4 archetypes that already have a real tiered system

`ARCHETYPE_MEMBERS`/`ARCHETYPE_VANILLA`/`DM_EXCLUSIVE` currently cover Death Remnant, Muster, Broodswarm, and Warpath. Each already has a working tier-1 (Deck Master exclusive) and tier-2 (in-archetype vanilla) skill. Ideas below deepen what's there rather than replace it.

**Death Remnant (Arch-Grim Korrin).** The archetype's whole identity is "lingering power after a death" (`deathRemnants`/`remnantPowSum()`), but every remnant currently behaves the same regardless of source. A natural next layer: remnants that came from a *specific* card type stack differently — e.g. a remnant raised by an Ultra+ card is worth +1 more than a Common's, rewarding decks that can afford to sacrifice better cards into the stack rather than just accumulating count. Keeps the existing `{name, pow}` shape, just changes how `pow` gets set at raise time.

**Muster (Bannerlord Cassian / Ironsworn).** Currently rewards going wide with 1-cost bodies. An unbuilt but thematically obvious follow-up: a "banner" mechanic where the *first* 1-cost card committed each match marks itself, and every subsequent Muster card gets +1 while that banner-bearer is still in Winners Circle or on the field — gives the archetype a build-around target instead of pure width, without touching the existing `RALLY`/count-based math.

**Broodswarm (La Ballora).** Scales off hand size and Winners Circle size today. Missing piece: nothing currently punishes the *opponent* for the swarm being large, which is the archetype's own flavor text ("the longer you let her sit, the more the brood answers"). A conditional debuff — opponent's committed card takes -1 for every 3 Broodswarm cards banked — would give the archetype real match-defining pressure instead of just self-scaling.

**Warpath (Tange Sazen / Kravyn).** Kill Escalation and the empty-Winners-Circle bonus are both built; the empty-WC combo loop has no completion pieces yet (flagged separately in `PENDING_MECHANICS.md`). Once that loop exists, a real tier-3 follow-up: a Warpath card that converts a *kill* directly into a temporary Charge/energy burst, tying the archetype's two existing pillars (kills, empty WC) together into one payoff card instead of two parallel systems.

## Part 2 — camps with real flavor identity but no mechanical archetype yet

`ARCHETYPE_MEMBERS` doesn't cover these; they exist only as `deckPresets` (a themed starter list) with no `DM_EXCLUSIVE`/tier system. Each already has a clear enough identity from its centerpiece card's real ability text (all edited/confirmed this session) to design a first-draft tier-1/tier-2 kit without inventing new lore.

**Black Wings (Ossian Drell).** His real kit (this session's rewrite) is a disciplined, attritional teacher/veteran archetype. Tier-1 idea: Ossian's own conjure grants your NEXT commit +1 power for every card currently in your Winners Circle capped at +6 — "he's taught you to bank your wins into discipline." Tier-2: a shared "Cadet" bonus (+2 if you have 0 deaths on record this match) matching the "discipline over damage" read on the archetype.

**Black Council (Zerith Var).** Already narrowed to this camp only this session. His kit reads as a control/chaos-manipulation identity. Tier-1 idea: on commit, look at the top card of your deck (reusing the existing `scryOne()` primitive already built for DM abilities) and if it's a spell, its cost is reduced by 1 this turn — a "the council always sees the next move" flavor that's cheap to build since `scryOne()` already exists.

**Radiance (Kaelthar the Ascendant).** Kaelthar's real ability is already an inversion mechanic (power flips based on match lead/deficit). Tier-1 idea for the archetype broadly: a shared "Radiant" bonus that's strongest when the match is closest — +1 power for every point *under* 2 the current score differential is, capped at +4 — mirrors Kaelthar's own "punishes complacency, rewards close fights" identity without copying his exact mechanic onto every card.

**Keawe's Circle (Keawe Kel'rua).** His existing kit already keys off "lost your last duel" and duel-count thresholds — a comeback/resilience identity. Tier-1 idea: a shared "Circle" bonus of +2 power for every consecutive loss this match (capped at +6) — turns a losing streak into a genuine comeback mechanic rather than a single-card quirk, matching the archetype's name (a circle you return to, not a single hero carrying the deck).

**Ahdor's Pride (Ahdorah Khaan).** Her kit is Record Guard (loss becomes tie) plus an underdog hand bonus. Tier-1 idea: while Ahdorah is your named Deck Master, the FIRST time each match you'd take a loss, it becomes a tie automatically (mirrors her own printed ability, extended to be a match-wide safety net rather than just her own card's effect) — a defensive, "protect the pride" identity distinct from Death Remnant's more aggressive lingering-power read.

## Part 3 — a genuinely new cross-cutting idea, not tied to one camp

**"Rivalry" pairs.** Several cards already have a real narrative rivalry (Uso Oso vs. the boy he refused to fight in Sorn-Vallis; Keawe vs. Ella Ballora per the KOTEI story content). A new Called/CARD_RULES primitive keyed on "this card and card X have history" — a small flat bonus (+2, matching the existing flat-bonus band) when both are on the field/in Winners Circle simultaneously, reusing the exact same shape as the already-built Bond system (`fieldBond()`) but keyed on narrative rivalry pairs instead of Ascension fight history. Low build cost since the Bond lookup/application pattern already exists and works — this would just be a second table of pairs feeding the same function shape.

---

Nothing above is scoped for effort/build order — flag which ones land and they can get the same treatment as the DM Activated Abilities batch (shared primitives first, then card-by-card).
