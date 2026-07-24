# Balance Proposals, Round 2 — shipped record

**Everything actionable in this file is now implemented and deployed.** Originally written for
line-by-line review; direct implementation was authorized ("make the changes") and completed
7/24/26, commit `<pending>`. Kept as a historical record of the reasoning, not as an open
checklist — §8 and §9 were explicitly flagged as open questions rather than proposals, and stay
open; nothing there was decided or implemented.

**One deviation from the original proposal, found during implementation:** §6's Signal Diviner
item recommended building the real "1 Charge, or scry 1" choice using `scryOne()`. Mid-build,
tracing `confirmSelection()`'s call sites found that its auto-timeout path (decision clock expires)
calls `confirmSelection()` then `commitCard()` back-to-back, synchronously, with no pause between
them — the exact same class of fragility already known to make `resolve()`/
`playResolutionCinematic()` unsafe to restructure for an async pause. Showing a choice modal at
that point would race visibly against the auto-commit already firing underneath it. Scaled back to
the safe half of the fix: `chargeGain:3` is unchanged, the text now honestly says "gain 3 Charge"
instead of the undeliverable "1 Charge, or scry 1" — a real, disclosed improvement (3x the
advertised number), just not the full interactive choice originally proposed.

**One real bug found and fixed that wasn't in the original proposal:** `conjureTierOf()` compared
`archetypeOf(card.name) === archetypeOf(deckMasterName)` to decide the tier-2 in-archetype bonus.
`archetypeOf()` returns only the FIRST `ARCHETYPE_MEMBERS` key (in object-insertion order) that
contains a card — so a card genuinely shared across two archetypes silently lost its bonus under
whichever archetype's Deck Master isn't first in iteration order. This already latently affected
Val Kreigh/Ruffius Rufeldro (Warpath vs. Radiance) and became load-bearing the moment Keawe's
Circle and Ahdor's Pride's own 5 shared commons (§9) needed tier-2 to work under EITHER Deck
Master. Fixed to a direct membership check against the Deck Master's own archetype list — a strict
superset of the old check, verified via `conjureTierOf`/`applyDeckMasterResolveEffects` calls
before and after (Val Kreigh under Ahdorah Khaan went from tier 3, no bonus, to tier 2, +2 — and
the pre-existing Warpath/Bram the Bulwark case was re-verified unaffected).

---

## 5. Charge economy — the two archetypes with genuinely zero access

**SHIPPED.** New Fighter common + new Called/support common per archetype, matching round 1's
Black Wings/Black Council/Radiance/Warpath pattern exactly.

- [x] **Broodswarm — Silk-Fed Hatchling** (pow6/cost1/common). On commit: gain 1 Charge, unconditional.
- [x] **Broodswarm — Broodweb Keeper** (pow5/cost1/common). Called: gain 1 Charge if hand size is
  4+ (new `chargeGainIfHandFull` field, reuses the archetype's own existing threshold).
- [x] **Ahdor's Pride — Squad 19 Signalman** (pow6/cost1/common). On commit: gain 1 Charge, unconditional.
- [x] **Ahdor's Pride — Squad 19 Chronicler** (pow5/cost1/common). Called: gain 1 Charge once
  you've played 2+ duels this match (new `chargeGainIfVeteran` field, reuses `match_commits` —
  the same ctx field Squad 16 Veteran already keys off individually).

Verified live: `applyRuleList`/`applyCalled` called directly, charge correctly increments by 1 for
each and correctly stays at 0 below each threshold.

---

## 6. Fix disclosed-vs-real mismatches (transparency bugs — same class flagged in round 1)

**SHIPPED**, all items, as proposed except Signal Diviner (see deviation note above).

- [x] **Ironsworn — Conduit Adept.** Text now discloses the real support-mode bonus (2 Charge + draw).
- [x] **Keawe's Circle / Ahdor's Pride — Bixie Bee.** Text now prints both real clauses (banish-zone
  scaling fighter-mode, +3 support-mode); the unbacked "+2 if Wrothlan" sub-clause dropped from text.
- [x] **Keawe's Circle — Melanie.** Text now discloses the real +5/draw-1 support bonus, flavor kept.
- [x] **Deathless — Ghorruk "Gnarly" Judarr.** Text fixed down to the real value: Death Remnant +6.
- [x] **Deathless — Uso Oso.** Text fixed up to the real, deliberately-tuned value: Death Remnant +10.
- [x] **Deathless / Keawe's Circle — Signal Diviner.** Scaled back to a text-only fix — see the
  deviation note above for why the full interactive choice wasn't safe to build here.
- [x] **Ahdor's Pride / Keawe's Circle — Conduit of Chaos, Kleydson.** Text fixed down to flat:
  "gain 1 Charge," matching the real `chargeGain:1` — no uncapped scaling built.
- [x] **Keawe's Circle — Kotei's Called entry.** Both halves now fire for real. The hand-return
  half is NOT `chargeGainIfWon` (that field checks cumulative match wins via `applyCalled()`'s
  pre-outcome ctx, not "did this specific duel resolve as a win") — it's a new, dedicated check
  inside `resolve()`'s own post-duel rear-guard cleanup loop, gated on `won==='win'` specifically,
  same family as the existing Skullchain Reaver/Kravyn/Bronzed Beast hand-return checks. Verified
  live via a full `commitCard()`→`resolve()` flow: Kotei-as-support on a won duel gains +2 Charge
  and returns to hand instead of recycling to the deck bottom; the Fighter's own Winners Circle
  routing is untouched.
- [x] **Ahdor's Pride — Ahdorah Khaan, Determined Soul.** Called entry rewired to the existing
  `snipeSupport` mechanism (was previously unbacked — no matching key existed at all). Also fixed
  the off-by-one on her disclosed number (text says +2, code was `add:3`; now both say +2).
  Verified live: fires and logs the snipe when an opposing support exists.
- [x] **Legend Reborn, Keawe Kel'rua's snipe fallback.** The printed "+3 instead" when there's
  nothing to snipe was a total no-op before this fix (no field backed it). New `snipeFailAdd` field
  plus a matching `else if` branch in the snipe pass, symmetric for both player and bot side.
  Verified live: fires and logs correctly when `pendingOppRears` has no matching entry.

---

## 7. Zero Deck Master coverage — Keawe's Circle and Ahdor's Pride

**SHIPPED.**

- [x] **Keawe's Circle — new `ARCHETYPE_VANILLA` rule.** +2 power once you've lost a duel this
  match (cumulative — stays true the rest of the match once earned, distinct from Lagertha
  Waltz/Keawe Kel'rua/Fenrik Vench's own last-duel-only swings). New `ctx.losses` field added to
  both `applyDeckMasterResolveEffects` and its bot mirror to support this.
- [x] **Ahdor's Pride — new `ARCHETYPE_VANILLA` rule.** +2 power once you've played 2+ duels this
  match, reusing `match_commits` (new `ctx.match_commits` field added to both ctx builders).
- [x] **Kotei — new `DM_EXCLUSIVE` entry.** +1 power per duel already played this match
  (`addvar:"match_commits"`) — compounds his own printed per-round-repeating effect rather than
  adding an unrelated kit.
- [x] **Ahdorah Khaan, Determined Soul — new `DM_EXCLUSIVE` entry.** +4 power once you've weathered
  a loss this match (reuses the same `losses` ctx field as Keawe's Circle's tier-2 rule, at tier-1
  magnitude) — ties directly to Record Guard's own point.
- [x] **Full-roster `ARCHETYPE_MEMBERS` entries for both**, not curated subsets — deliberately, to
  avoid the undocumented-gap pattern already present in the older Death Remnant/Broodswarm/Muster
  lists. This is what surfaced the `conjureTierOf()` bug above (see the note at the top of this
  file) once both archetypes' shared commons needed to resolve correctly under either Deck Master.

Verified live: `archetypeOf()`/`conjureTierOf()` called directly for cards under both new Deck
Masters (own-card tier 1, in-archetype tier 2, common-floor tier 4, off-archetype tier 3 all
correct), plus full `applyDeckMasterResolveEffects` calls confirming the actual power-math fires.

---

## 8. Genericness — not proposing to fix, flagging for your call

**Still open, not decided, nothing implemented.** Broodswarm's hand-size identity and Ironsworn's
Muster-template repetition are both flagged as-is in the original proposal below — no change
beyond §5's charge cards.

- **Broodswarm**: 12 of 17 members (71%) key off hand size in one of two shapes (flat per-card
  scaling, or a fixed threshold). This IS the archetype's identity, not accidental filler — "go
  wide, reward a full hand" is a coherent design and diluting it isn't obviously right.
- **Ironsworn**: 7 of 15 members (47%) are the same "Muster N: +N per 1-cost ally" template, 5 of
  those at the identical N=3. Real mechanical reinforcement already exists on top
  (`LINK_GROUPS['ironsworn']` at +2 Bond pow, covering 11/15 members). Its
  `ARCHETYPE_VANILLA['Muster']` slot is a deliberate empty `[]` with an existing code comment
  ("nothing new needed"). Open question: leave that tier-2 slot empty as originally reasoned, or
  give Ironsworn one small distinct tier-2 rule to match every other archetype having a real
  (non-empty) one?

---

## 9. Cross-archetype identity overlap — open question, not decided here

**Still open, not decided, nothing implemented.** Keawe's Circle and Ahdor's Pride share 5 members
verbatim (Conduit of Chaos Kleydson, Legend Reborn Keawe Kel'rua, Barracks Drill Sergeant, Cadet
Corps Recruit, Writ-Sergeant's Ledger) — the literal same `COLLECTION` entries, roughly a third of
each roster. Heir of Kaiga, Uso Oso, Bixie Bee, and Bronzed Beast Hanse Waltz are each claimed by
2-3 archetypes on top of that. Two honest options, your call: (a) leave it — the new tier-2 rules
in §7 now differentiate the archetypes regardless of shared commons; (b) some of the 5 shared cards
get a second, archetype-exclusive printing (mirrors the existing Ahdorah Khaan Rare→Apex and Keawe
Kel'rua Rare→Ultra sibling-printing pattern). Not recommending one over the other.

---

_§5, §6, §7 fully shipped. §8 and §9 remain open questions, exactly as originally flagged — no
default action was taken on either._
