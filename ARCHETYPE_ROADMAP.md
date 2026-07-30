# Archetype Mechanics Roadmap

Forward-looking ideas only — nothing marked "idea" below is built. Written 7/22/26 per direct request: "a list of other archetype specific mechanics we should build out in the future based off the current styles and power scale of where we are now." Grounded in the real, current numbers (not invented ranges): flat Called/CARD_RULES bonuses run +2 to +5, conditional swings (Purity/Underdog/Fresh Blood-style) run +5 to +8, kill-escalation/threshold effects run +3 to +7 per tier, and tier-1 Deck Master exclusives currently top out around +8 to +10 under favorable conditions. Anything proposed below should land in those bands unless there's a specific reason to push higher.

## Status check, 7/30/26 — corrected against the real code

This doc's original Part 2 (below) claimed Black Wings, Black Council, Radiance, Keawe's Circle, and Ahdor's Pride had "no mechanical archetype yet." That's now false — verified directly against `ARCHETYPE_MEMBERS`/`ARCHETYPE_VANILLA`/`DM_EXCLUSIVE` in index.html (~line 6933 on). All 9 of the game's real archetypes now carry a tier-2 vanilla bonus, and 7 of 9 also carry at least one tier-1 Deck-Master-exclusive:

| Archetype | Tier-2 vanilla | Tier-1 DM exclusive |
|---|---|---|
| Death Remnant | yes | yes — Arch-Grim Korrin |
| Muster | yes (empty rule; 4/5 members already carry Muster 3 in their own text) | yes — Bannerlord Cassian, Chieftain Reyva Vosh |
| Broodswarm | yes | yes — La Ballora, Web-Weaver's Return |
| Warpath | yes | yes — Tange Sazen |
| Black Wings | yes | yes — Rhaess Korvain |
| Keawe's Circle | yes | yes — Kotei |
| Ahdor's Pride | yes | yes — Ahdorah Khaan, Determined Soul |
| Radiance | yes | **none yet — real open gap** |
| Black Council | yes | **none yet — real open gap** |

**Important nuance:** what actually shipped for Black Wings/Black Council/Radiance/Keawe's Circle/Ahdor's Pride during the 7/24–7/25/26 balance-audit passes (per `BALANCE_PROPOSALS.md` and the code's own inline comments) is **not** the specific "Tier-1 idea" text originally written per-archetype in Part 2 below — a separate, later design pass picked different concrete mechanics for every one of the 5. For example, this doc proposed a Black Council tier-1 built on `scryOne()` (peek top card, discount a spell); what actually shipped as its tier-2 vanilla is an unrelated flat "+2 power while behind on committed power" (Court's Advantage). Likewise Radiance shipped a Charge-based "Consecrated Reserve" (+1 per Charge held, capped +4) rather than the score-differential idea below, and Keawe's Circle/Ahdor's Pride/Black Wings each shipped a simpler flat-threshold trigger than what's proposed below. **Read everything in Part 2 as still-live design ideas for a deeper layer on top of what's real now — not a description of current behavior.**

The two genuinely open items today are narrower than the old framing: **Radiance and Black Council have no tier-1 DM_EXCLUSIVE splash card yet** (every other archetype has at least one). Their "Tier-1 idea" entries in Part 2 are the closest thing to real unbuilt work in this document right now — everything else in Part 2 is a "deepen an existing simple mechanic" idea, same category as Part 1.

## Part 1 — the archetypes with the deepest existing tiered systems

`ARCHETYPE_MEMBERS`/`ARCHETYPE_VANILLA`/`DM_EXCLUSIVE` cover Death Remnant, Muster, Broodswarm, and Warpath most thoroughly (multiple tier-1 cards apiece, or long-standing single exclusives). Ideas below deepen what's there rather than replace it.

**Death Remnant (Arch-Grim Korrin).** The archetype's whole identity is "lingering power after a death" (`deathRemnants`/`remnantPowSum()`), but every remnant currently behaves the same regardless of source. A natural next layer: remnants that came from a *specific* card type stack differently — e.g. a remnant raised by an Ultra+ card is worth +1 more than a Common's, rewarding decks that can afford to sacrifice better cards into the stack rather than just accumulating count. Keeps the existing `{name, pow}` shape, just changes how `pow` gets set at raise time.

**Muster (Bannerlord Cassian / Ironsworn).** Currently rewards going wide with 1-cost bodies. An unbuilt but thematically obvious follow-up: a "banner" mechanic where the *first* 1-cost card committed each match marks itself, and every subsequent Muster card gets +1 while that banner-bearer is still in Winners Circle or on the field — gives the archetype a build-around target instead of pure width, without touching the existing `RALLY`/count-based math. (Note: Ironsworn's own 1-cost roster gap — 3 identical Muster clones with nothing to do if conjured first — was separately identified and fixed 7/30/26 by reworking 2 of the 3 into non-Muster identities; see `project_signalforge_ironsworn_1cost_rework` memory. This banner idea still applies to the archetype's remaining Muster payoff card, Shieldwall Recruit, and to Bannerlord Cassian/Warden of the Wall/Oathkeeper Sena.)

**Broodswarm (La Ballora).** Scales off hand size and Winners Circle size today. Missing piece: nothing currently punishes the *opponent* for the swarm being large, which is the archetype's own flavor text ("the longer you let her sit, the more the brood answers"). A conditional debuff — opponent's committed card takes -1 for every 3 Broodswarm cards banked — would give the archetype real match-defining pressure instead of just self-scaling.

**Warpath (Tange Sazen / Kravyn).** Kill Escalation and the empty-Winners-Circle bonus are both built; the empty-WC combo loop has no completion pieces yet (flagged separately in `PENDING_MECHANICS.md`). Once that loop exists, a real tier-3 follow-up: a Warpath card that converts a *kill* directly into a temporary Charge/energy burst, tying the archetype's two existing pillars (kills, empty WC) together into one payoff card instead of two parallel systems.

## Part 2 — further ideas for the 5 archetypes whose base tier shipped later (7/24–7/25/26)

Each of these now has real `ARCHETYPE_MEMBERS` + tier-2 `ARCHETYPE_VANILLA` coverage (see status table above), built with simpler flat-threshold mechanics than what's proposed here. The ideas below are a deeper/alternate layer, not a description of what shipped — treat each as a "further idea," same category as Part 1.

**Black Wings (Ossian Drell).** Shipped tier-2 is a flat "+2 once you've banished a card this match" (Wings in Shadow) and a tier-1 on Rhaess Korvain (+1 power per banish-zone card). Further idea, still unbuilt: Ossian's own conjure grants your NEXT commit +1 power for every card currently in your Winners Circle, capped at +6 — "he's taught you to bank your wins into discipline." A second layer: a shared "Cadet" bonus (+2 if you have 0 deaths on record this match), matching the "discipline over damage" read on the archetype.

**Black Council (Zerith Var).** Shipped tier-2 is a flat "+2 power while behind on committed power this duel" (Court's Advantage) — no tier-1 yet, one of the 2 real remaining gaps. Idea for a real tier-1: on commit, look at the top card of your deck (reusing the existing `scryOne()` primitive already built for DM abilities) and if it's a spell, its cost is reduced by 1 this turn — a "the council always sees the next move" flavor that's cheap to build since `scryOne()` already exists.

**Radiance (Kaelthar the Ascendant).** Shipped tier-2 is Charge-based, "+1 power per Charge held, capped +4" (Consecrated Reserve) — no tier-1 yet, the other real remaining gap. Kaelthar's own printed ability is already an inversion mechanic (power flips based on match lead/deficit); idea for a real tier-1 in that spirit: a shared "Radiant" bonus that's strongest when the match is closest — +1 power for every point *under* 2 the current score differential is, capped at +4 — mirrors Kaelthar's own "punishes complacency, rewards close fights" identity without copying his exact mechanic onto every card.

**Keawe's Circle (Keawe Kel'rua).** Shipped tier-2 is a flat "+2 power once you've lost a duel this match" (Found Family), tier-1 on Kotei scales +1 per duel already played (The Unbroken Reign). Further idea, still unbuilt: scale the tier-2 bonus per CONSECUTIVE loss instead of a flat one-time flip — +2 power for every consecutive loss this match, capped at +6 — turns a losing streak into a genuine comeback mechanic rather than a single flip, closer to the archetype's name (a circle you return to, not a single hero carrying the deck).

**Ahdor's Pride (Ahdorah Khaan).** Shipped tier-2 is a flat "+2 once you've played 2+ duels this match" (Squad Discipline), tier-1 on Ahdorah Khaan is +4 once you've weathered a loss (Determined Soul) — both already thematically close to Record Guard (loss becomes tie). Further idea, still unbuilt: while Ahdorah is your named Deck Master, the FIRST time each match you'd take a loss, it becomes a tie automatically — a match-wide extension of her own printed card effect, a defensive "protect the pride" safety net distinct from what's shipped.

## Part 3 — a genuinely new cross-cutting idea, not tied to one camp

**"Rivalry" pairs.** Several cards already have a real narrative rivalry (Uso Oso vs. the boy he refused to fight in Sorn-Vallis; Keawe vs. Ella Ballora per the KOTEI story content). A new Called/CARD_RULES primitive keyed on "this card and card X have history" — a small flat bonus (+2, matching the existing flat-bonus band) when both are on the field/in Winners Circle simultaneously, reusing the exact same shape as the already-built Bond system (`fieldBond()`) but keyed on narrative rivalry pairs instead of Ascension fight history. Low build cost since the Bond lookup/application pattern already exists and works — this would just be a second table of pairs feeding the same function shape.

---

Nothing above is scoped for effort/build order — flag which ones land and they can get the same treatment as the DM Activated Abilities batch (shared primitives first, then card-by-card). The 2 real gaps to prioritize first if picking one: Radiance and Black Council tier-1 DM_EXCLUSIVE cards, since every other archetype already has at least one and these two don't.
