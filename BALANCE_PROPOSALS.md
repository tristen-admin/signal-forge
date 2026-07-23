# Balance Proposals — shipped record

**Everything in this file is now implemented and deployed.** Originally written for line-by-line review; direct implementation was authorized and completed 7/24/26 across 3 commits: `9ec5968` (§1, §3, §4a, §4b), `cb826d1` (§4c). Kept as a historical record of the reasoning, not as an open checklist — see [[project_signalforge_balance_pass_shipped]] for the full session memory.

**Standing design rule, corrected a second time — Pristine is not a Radiance mechanic, period, not even in the reward-only direction:** the first draft of this rule only banned punishing the OPPONENT'S Pristine status. That was half the correction. The actual instruction was that Pristine should not be *central* to Radiance at all — a shared archetype-wide mechanic is central by definition, whether it rewards you or punishes them. Corrected rule: **Pristine-keyed effects (in either direction) are occasional one-off tech material only — a single UR, a single 1-cost common, a single niche support ability — never a shared/systemic mechanic applied across an archetype.** Elowen Dawnspear's own existing printed "Purity" text is exactly that kind of one-off and stays untouched as-is; nothing new was added to Radiance keyed on Pristine. Same tech-only treatment applies to Skyward Trilogy camp-vs-camp procs.

---

## 1. Charge economy — on-commit AND support-side, one of each per starved archetype

**SHIPPED, commit `9ec5968`.**

- [x] **Black Wings — Falk.** On commit, if your banish zone has 3+ cards, gain 1 Charge. (Added a new generic `chargeGain` action to the CARD_RULES engine itself — reusable, not a one-off hack.)
- [x] **Black Wings — new support card, "Pyre-Keeper's Apprentice"** (pow6/cost1/common). Called: gain 1 Charge. Shipped unconditional — the proposed "if your Fighter is banish-zone-scaling" check has no ctx field threading the current Fighter's identity into `applyCalled`; building that just for one common wasn't worth the risk under this pass.
- [x] **Black Council — Cletus Gwyndull.** Gain 1 Charge when you lock the condition (pre-commit). Hardcoded directly in `activatePre()` — he's a pre-commit card, a different code path than normal on-commit CARD_RULES entirely.
- [x] **Black Council — new support card, "Court Cipher"** (pow7/cost1/rare). Called: gain 1 Charge if the active condition is locked this turn. Shipped exactly as proposed (new `chargeGainIfLocked` CALLED field, checks the real `conditionLocked` global).
- [x] **Radiance — Elowen Dawnspear charge tie: stays withdrawn**, per the Pristine correction above.
- [x] **Radiance — new Fighter card, "Lumen Acolyte"** (pow7/cost1/common). On commit: gain 1 Charge, unconditional.
- [x] **Radiance — new support card, "Oathlit Attendant"** (pow6/cost1/common). Called: gain 1 Charge, unconditional.
- [x] **Warpath — Warpath Vanguard.** +1 MAX Charge on the 1st duel, reusing the exact `divinerBonusNext` mechanism Signal Diviner already uses (a real permanent-this-match resource increase, not a one-off).
- [x] **Warpath — new support card, "Trophy Runner"** (pow6/cost1/common). Called: gain 1 Charge if you've earned a kill this match (new `chargeGainIfWon` CALLED field, checks `ctx.wins>0`).

---

## 2. Ahdor's Pride / Keawe's Circle — Squad 19 + cadet-corps glue commons

**SHIPPED 7/23/26, commit `f833527`.** Authorized directly ("just make it") rather than routing through line-by-line approval, since this is additive roster-filling, not a rebalance of existing card numbers. Full detail in [[project_signalforge_squad19_cadet_batch]].

- [ ] **Still not resolved — need your call:** you mentioned "make squad 16 a temporary thing, as we can assume if Ahdor was in squad 19 there was an 18 and 20 as well." Do you mean: (a) a specific "Squad 16" card representing a disbanded/legacy predecessor unit, or (b) something else entirely? Still flagging rather than inventing a card off an unclear read.

---

## 3. Skyward Trilogy (camp wheel) — tech-card only, matching the Pristine rule above

**SHIPPED, commit `9ec5968`.** New UR "Trilogy Ward" (pow14/cost2): +5 power if your card's camp beats the opponent's (Amageras>Omitsuki>Kitanoo>Amageras), same camp on both sides = no bonus. Reuses `effectiveCampOf()`/`campBeats()` — the exact same logic the real Bloodlines Clash match condition already runs. Not bound to any archetype preset, per "not archetype-specific... a small set of commons / a single UR tech piece."

---

## 4a. Black Wings — real consequence lever

**SHIPPED, commit `9ec5968`.** Went with (a) direct taxes + (b) Charge cost, per the recommendation below; (c) separate discard zone and (d) decking-out-as-a-threat remain deferred, bigger separate initiatives.

- [x] **Corvus** — banishing the top 2 of your own deck on commit now costs 1 Charge. No Charge = the banish simply doesn't happen, never a forced negative.
- [x] **Rhaess Korvain** — same, 1 Charge for his single-card deck-banish.
- [x] **Grave-Tithe Acolyte** — same, 1 Charge for his single-card deck-banish.
- [x] **The Black Ledger** — banish 2 RANDOM cards from your hand, draw 1 (was draw 2). Explicit "random" is now a real, deliberate downgrade under the player-choice-by-default rule, not a restatement of default behavior.
- [x] **Black Wings, Ossian Drell's undisclosed second clause** (+2×hand-size if you banished from hand this turn) — now printed on his card face.

**Still not started — genuinely separate, bigger initiatives, not part of this pass:** the player-choice-by-default engine infrastructure (auditing every `banishOwn`/hand-affecting card to decide choice-vs-explicit-random), a separate discard zone, and decking-out as a real threat.

---

## 4b. Radiance — Moro as the true centerpiece

**SHIPPED, commit `9ec5968`.**

- [x] **Moro — rarity upgrade, common → apex (pow14→19), new "Royal Bearing" kit:** on commit, if your Deck Master's printed power is higher than Moro's current total, borrow it; then +3. Verified live: a pow30 Deck Master lifts Moro to 33; a pow8 Deck Master does not override his own 19+3=22.
- [x] **Kaelthar the Ascendant stays as-is** — not prioritized this round, per the original call.
- [x] **Shared Radiance spine, "Consecrated Reserve"** — +1 power per Charge held, capped at +4. Wired through `ARCHETYPE_VANILLA`/a new `ARCHETYPE_MEMBERS['Radiance']` key (Moro, Elowen Dawnspear, Kaelthar the Ascendant, Oathlit Vanguard — non-Common only, excludes King Joris/Ruffius Rufeldro/Bram the Bulwark since they're already claimed by Warpath's own entry). Verified live: capped correctly at +4 even with 7 Charge held.
- [x] **Oathlit Vanguard** — shipped as approved (pow12/cost2/rare, +5 while undefeated this match). "Gone for the rest of the match after your first loss" was simplified to "the bonus stops applying after your first loss" (`player_losses===0` gate) rather than a new card-removal-from-deck/hand mechanic — no confirmed primitive exists for removing one specific named card from wherever it might be (deck, hand, not yet drawn), and building one wasn't worth the risk for this one card's flavor text.
- [ ] Reconsider swapping Ruffius Rufeldro/Bram the Bulwark out of the Radiance preset now that it has real unique pieces (Moro, Oathlit Vanguard) — still open, not decided.

---

## 4c. Uso Oso / Deathless — the wall mechanic

**SHIPPED, commit `cb826d1`.**

- [x] **Stage 1 — Uso Oso, on commit: raises a +2 Remnant, no death needed** (added to the existing `RAISE_REMNANT` dict — Pale Gravedigger/Gravecaller Voss's exact mechanism).
- [x] **Stage 2 — "The Bulwark of Bones": while you hold 3+ Remnants, a loss becomes a tie instead.** Implemented as a forced-tie check (same family as Ahdor's Record Guard/Untouchable/Ledger Ward) rather than a separate remnant-preservation branch — forcing the tie means the win-branch clear and lose-branch push both never fire for that duel, so "Remnants persist" falls out of the existing structure for free. Verified live: fires only for Uso Oso specifically, only on a loss, only at 3+ remnants.
- [x] **Remnant board-visibility bug** — fixed separately, 7/24/26, commit `0104ea3` (a persistent `#remnant-indicator` chip, not gated on this proposal).

---

_All sections above are shipped. The two open items (Squad 16 in §2, the Ruffius/Bram swap in §4b) remain genuinely unresolved and are not guessed at._
