# Card Art Needed — Gemini / Nano Banana Prompts

**Status as of 8/9/26**: 102 of 159 live `COLLECTION` cards have real art (`CARD_ART`/`CARD_ART_FULL`).
**60 do not** — they render with a generic sigil glyph (◈ or a role icon from `CARD_SIGIL`) over a
flat color fill instead of a real portrait, everywhere the card appears (Vault, Deck Builder,
in-duel card face, lightbox zoom, Ascension roster). This doc tracks all 60 with a ready-to-paste
Gemini image prompt for each. `SET2_POOL` (31 held-back Set 2 cards) is **not** included — not live
yet, lower priority, do a separate pass when Set 2 ships.

## House style (read this once, reuse for every prompt)

Every existing card is a **painterly digital fantasy illustration** — semi-realistic character
portraits, dramatic moody lighting, dark backgrounds with a lot of atmosphere (torchlight, mist,
graveyard fog, spectral glow). Not photographic, not flat/vector, not anime-cel. Think
Magic:-The-Gathering / Gwent card-art register.

- **Aspect ratio**: portrait, ~4:5 (existing art is 531×660 for the full-size version). Ask Gemini
  for a portrait image around **1024×1280**.
- **Palette**: desaturated overall with 1-2 saturated accent colors doing the work — cool
  blue/teal for anything spectral, magical, or cold-camp (Omitsuki-flavored); warm orange/red for
  fire, blood, or aggression; muted browns/greens/steel for plain martial cards.
- **Composition**: single character, 3/4 or full-body, dynamic action pose (not a static stiff
  portrait), background that's clearly *a place* (battlements, graveyard, forge-hall, camp tent
  row) not a gradient. Subtle dark vignette toward the edges — it's a card crop, not a poster.
- **When you generate**: if Gemini supports attaching reference images, attach 1-2 existing card
  arts as style anchors — good picks already in the game: **Kravyn the Collector** (armored
  warrior, trophy room), **Gravecaller Voss** (necromancer, graveyard), **Faye Quicksilver**
  (spectral rogue, gothic rooftops). Matching their rendering style matters more than matching any
  single subject.
- **After generating**: run through the existing art pipeline — compress + embed via `sips` (see
  `project_signalforge_art_pipeline` in memory) — then add to both `CARD_ART` (thumbnail) and
  `CARD_ART_FULL` (full-res) in `index.html`, keyed by the card's **exact** `name` string (copy it
  from this doc, don't retype — several names have apostrophes/commas that must match exactly).

Each entry below: **Card Name** *(rarity)* — printed ability, for context — then the prompt.

---

## Trophy Hall (7) — banking wins / filling the banish zone as a resource

A hall of ledgers, coffers, and banked trophies — cold, transactional, a counting-house feel
rather than a battlefield feel. Cooler, more architectural backgrounds than the rest of the pool.

**Hall of Champions** *(rare)* — +6 power if Winners Circle holds 2+ cards.
> A stern trophy-master standing in a vaulted stone hall lined with banked victor's laurels and
> engraved plaques on iron stands, torchlight glinting off gold-rimmed trophies behind her, arms
> crossed, cold appraising expression. Warm torchlight against cold stone.

**Ash Reckoning** *(rare)* — +7 power if banish zone holds 3+ cards.
> A robed reckoner standing over a pit of smoldering banished relics — broken blades, torn banners,
> cracked shields half-buried in ash and embers — one hand raised, drawing power up from the wreck.
> Orange ember-glow rising through grey ash-smoke.

**Twin Ledgers** *(rare)* — +1 power per WC card, +1 more per banished card.
> A gaunt accountant-mystic holding two open ledger-books that float and glow — one bound in gold
> leaf (trophies, warm light), one bound in ash-grey leather (the discarded, cold blue light) — the
> two glows meeting and mixing at his chest.

**Banked Interest** *(rare)* — +2 power per WC card, capped at +6.
> A calm coin-counter/banker figure at a stone counting-table stacked with three neat piles of
> banked trophy-coins, each pile glowing faintly brighter than the last, a ledger open beside her
> hand. Quiet, disciplined mood rather than aggressive.

**Coffer-Keeper** *(common)* — Called: banish 1 card from hand, Fighter +3.
> A hooded keeper standing before an iron-banded coffer, feeding a torn card/relic into its slot
> with one hand while the coffer's seams glow faintly — the generator of the archetype, a modest
> common-rarity support figure, not a hero pose.

**Victory Lap** *(common)* — Called: return 1 card from Winners Circle to hand.
> A quick, grinning runner sprinting back INTO the frame carrying a recovered trophy/banner under
> one arm, dust kicked up behind her, laurel-hall visible in the background she's running from —
> motion-blur energy, common-rarity, lighter and faster than the other Trophy Hall cards.

**The Long Reckoning** *(ultra)* — +2 power per card across WC + banish combined, uncapped, pow 14.
> The archetype's apex payoff: a towering robed Reckoner standing between twin torrents of
> light — gold trophy-light pouring in from one side, grey ash-light from the other — both
> streams converging into the figure, who is nearly overwhelmed by the combined glow. Should read
> as clearly the biggest, most dramatic card in this set of 7.

---

## Ahdor's Pride (8) — Squad 19 / the disciplined underdog camp

Working-camp / boot-camp military feel — leather and canvas rather than knight armor, tents and
drill-yards rather than castles. Grounded, human-scale, not magical.

**Ahdorah Khaan, Squad 19 Recruit** *(rare)* — an earlier, rawer printing of Ahdorah Khaan; +3
power if you lost your last duel.
> A younger, less-scarred version of a determined female soldier in half-fitted Squad 19 leathers,
> still adjusting her own strap buckles, jaw set, standing at the edge of a drill-yard at dawn —
> nervous but stubborn, not yet the hardened veteran. (If Ahdorah Khaan, Determined Soul's existing
> art is visible to you, keep this recognizably the same person, younger/rawer.)

**Squad 16 Veteran** *(rare)* — a disbanded squad's last member, forgotten; +3 once you've played
2+ duels.
> An older soldier in a faded, slightly mismatched uniform bearing a squad insignia that's been
> crudely patched over — standing alone at the edge of camp while younger Squad 19 recruits drill
> in the background, unnoticed, quietly weathered.

**Squad 19 Vanguard** *(common)* — Called: Fighter +3, "the squad holds the line."
> A front-line soldier planted shield-first in a drill-yard formation gap, shouting an order back
> over one shoulder, dust and motion around the boots.

**Squad 19 Medic** *(common)* — Called: Fighter +2, draw a card.
> A field medic kneeling beside a supply crate, wrapping a bandage with quick efficient hands,
> satchel of vials and rolled dressings open at her hip, calm focus rather than panic.

**Squad 19 Quartermaster** *(common)* — +4 power while hand ≤3 cards, "keeping the squad supplied."
> A quartermaster at a supply-tent counter, counting out the last few ration packs/arrow bundles
> onto a stretched-thin table, ledger in hand, faint worry at the low stock.

**Squad 19 Scout** *(common)* — Called: draw a card.
> A lean scout crouched at the treeline just outside camp at dusk, one hand signaling back, eyes
> fixed on something offscreen — quiet, watchful, low-key composition (this is a cheap common, keep
> it simple).

**Squad 19 Signalman** *(common)* — On commit: gain 1 Charge. [Tosa Pact]
> A signalman on a low watch-tower raising a lit signal-flare/flag against a dusk sky, the small
> warm glow of the flare the main light source in an otherwise cool-toned scene.

**Squad 19 Chronicler** *(common)* — Called: gain 1 Charge once 2+ duels played. [Tosa Pact]
> A young chronicler sitting cross-legged near a campfire, quill in hand, recording the match into
> a worn field-journal, firelight on the page — the "keeper of the record" note fits Ahdor's Pride's
> whole "earned, not given" theme.

---

## Keawe's Circle (7) — the cadet/rival corps, younger and hungrier than Ahdor's Pride

Same military-camp register as Ahdor's Pride but younger, scrappier, more personal rivalry energy —
sparring yards rather than drill formations.

**Barracks Drill Sergeant** *(common)* — Called: Fighter +2. [Tosa Pact]
> A barked-order drill sergeant mid-shout, one arm pointing hard at an unseen recruit, barracks row
> behind him, harsh midday light rather than the moodier dusk/night lighting elsewhere in the pool.

**Cadet Corps Recruit** *(common)* — +3 power on the 1st or 2nd duel. [Tosa Pact]
> A fresh-faced cadet in an ill-fitting uniform, gripping a training weapon too tightly, standing at
> the front of a cadet formation on their very first day — nervous energy, not yet battle-worn.

**Writ-Sergeant's Ledger** *(common)* — Called: gain 1 Charge. [Tosa Pact]
> A stack of official Writ-stamped papers/ledger bound in twine sitting on a weathered wooden desk,
> a wax-sealed stamp resting on top, a single candle burning beside it — an item-focused shot
> (support-only, cost-1 filler) rather than a character portrait.

**Fenrik Vench** *(rare)* — a causeway-lord's son, first rival in the yard; +3 if you've lost a
duel this match.
> A privileged, sharply-dressed young rival with an ornate (slightly too-fine-for-a-cadet) blade,
> smirking with confident entitlement in the sparring yard, causeway-city rooftops visible behind
> the yard wall marking him as an outsider money/status.

**Yard Sparring Partner** *(common)* — Called: Fighter +3.
> Two cadets mid-sparring-match with wooden practice swords in a dusty yard, a small crowd of
> other recruits watching from the rail — motion and energy for a common support card.

**Keawe Kel'rua** *(rare)* — Rising Talent: +3 if you lost your last duel, repeats if 1 or fewer
supports.
> A determined young heir-in-training, name-card of the whole archetype: standing mid-recovery
> after a hard fall in the sparring yard, pushing back up on one knee, blood at the lip, refusing
> to stay down — defiant rather than defeated. (Base printing — the transformed "Legend Reborn"
> version below should read as a clear escalation of this same person.)

**Legend Reborn, Keawe Kel'rua** *(ultra)* — Conjure: tutor a 15+ power card, cost −1.
> The escalated version of the card above: the same young heir now standing fully upright,
> confident, drawing a glowing legendary weapon/card up out of a beam of light from the ground at
> their feet — same face/identity as the base Keawe Kel'rua card, but triumphant instead of fallen,
> visually答 "the legend the recruit becomes."

---

## Broodswarm (2 tagged) + Broodswarm-flavored (7 more, untagged but same theme)

Insectoid/hive horror register — chitin, silk, swarming numbers. Cooler palette than the martial
archetypes; sickly pale greens and bone-white against near-black.

**Web-Tender Matron** *(rare)* — Called: draw 2 cards.
> A matriarchal broodmother figure tending glistening silk egg-sacs in a dark web-strung chamber,
> carefully turning one sac with clawed hands — nurturing rather than purely monstrous, unsettling
> tenderness.

**Venombrood Queen** *(rare)* — Broodswarm: +2 power per card in hand.
> A larger, more overtly monstrous queen figure with a swollen abdomen and too many limbs, perched
> atop a mound of hatched shells, swarm-children skittering at the edges of frame — the "hand size
> = power" flavor reads as "she commands more the bigger her brood."

**Skittering Drone** *(common)* — Swarm: +1 power per card in hand.
> A single low, insectoid drone-creature skittering along a web-strand in near-total darkness, only
> its faint bioluminescent markings visible — cheap common, minimal/moody rather than detailed.

**Hatchling Tide** *(common)* — +4 power while hand is full (4+).
> A tide of newly-hatched brood-young pouring out of a cracked egg-cluster all at once, small and
> numerous rather than one big threat — conveys "overwhelming numbers," matches the "full hand"
> trigger.

**Silk-Spinner Drone** *(common)* — Called: draw a card "to feed the brood."
> A drone spinning silk thread between its forelimbs, weaving a small cocoon-bundle, single subject,
> quiet industrious motion rather than aggression.

**Wingblade Scout** *(common)* — Wingblade: +1 power per banish-zone card.
> A winged insectoid scout with blade-edged wings perched on a pile of discarded husks/wreckage
> (the banish zone made literal), head cocked, alert.

**Feather-Marked Skirmisher** *(common)* — Called: banish from hand, Fighter +4.
> A lighter, feathered/plumed variant skirmisher-type mid-lunge with a barbed weapon, discarding a
> torn scrap of something as it moves — faster and more agile-looking than the heavier brood units.

**Squad-Captain Vesk** *(rare)* — Wing Commander: +2 power per banish-zone card.
> A commanding officer-type broodkin with visible rank markings (a chitin "insignia" motif) directing
> a small formation of drones from a raised vantage, wings half-spread — leadership pose distinct
> from the rank-and-file drones above.

**Sister Mire, Wailing Nightmare** *(ultra)* — draw 2, return 1, scale with hand size; support
draws too.
> The apex of this group: a wailing, veiled broodkin priestess-figure surrounded by a spiraling halo
> of drawn/discarded cards made ghostly and translucent, mouth open in a silent scream, swamp-mire
> setting (standing water, dead reeds) rather than a dry web-cave — should look like the strongest,
> most unsettling card in this cluster.

---

## Black Council / Radiance (2, one each — currently thin coverage in these camps)

**Court Cipher** *(rare, Black Council)* — Called: gain 1 Charge if the active condition is
locked this turn.
> A masked court informant/spy standing just inside a shadowed archway at the edge of a lit council
> chamber, one hand pressed flat against a sealed/locked door-rune that's glowing faintly — visually
> ties to "the condition is locked."

**Oathlit Vanguard** *(rare, Radiance)* — +5 power while undefeated this match, "gone the moment
you take your first loss."
> A radiant, gleaming vanguard knight lit from within/above by a warm holy glow, standing at the
> absolute front of a formation, untouched and pristine — should feel fragile-perfect, like the
> glow could be snuffed out, not indestructible.

---

## Māyā "Legend" transform variants (8, ultra) — escalated printings of existing base cards

These are the pay-a-cost **transformed** version of a character who already has base art in
`CARD_ART` (Keawe Kel'rua, Ahdorah Khaan/"Ahdor", Hanse Waltz, Lagertha Waltz, Uso Oso, Ruffius
Rufeldro, Tange Sazen, Kleydson). **Before generating, pull up that base card's existing art** (open
it in the Vault) so the transformed version reads as *the same character, escalated* — not a new
person. Keep face/silhouette/signature prop recognizable; escalate lighting, damage, aura, or scale.

**The Borrowed Green, Keawe Kel'rua** *(ultra)* — +9 power, opponent also gains +5 — "power without
aim."
> Keawe Kel'rua wreathed in an uncontrolled, spilling green-gold light that's clearly leaking past
> them onto everything nearby (including, ambiguously, the viewer/opponent's side of the frame) —
> raw power without the earlier discipline, slightly out of control rather than triumphant.

**The Kept Blade, Ahdor** *(ultra)* — +5, +3 more at 0 losses — "the earn-it vow kept."
> Ahdorah Khaan standing with a blade held low and steady in both hands, expression calm and
> resolved rather than fierce — a vow-keeping stillness, unbowed but not aggressive.

**The Nightmare's Toll, Hanse Waltz** *(ultra)* — +8, +4 more after a death this match — "the toll
already paid."
> Hanse Waltz visibly marked by battle-damage (a fresh scar, torn armor) with a faint pale
> death-toll glow around one hand, expression grim and paid-in-full rather than triumphant.

**The Claim, Lagertha Waltz** *(ultra)* — +6, +4 more after a career kill — "dibs collected."
> Lagertha Waltz planting a weapon into the ground beside a fallen foe's dropped standard/banner,
> claiming it with one boot — possessive, territorial pose.

**Throne of Bones, Uso Oso** *(ultra)* — +7, +5 more while commanding a Death Remnant —
"Grey-Giant mode."
> Uso Oso seated/standing on a rough throne assembled from bones and broken weapons, noticeably
> larger and more imposing than their base printing, a pale Death-Remnant spirit hovering attendant
> beside the throne.

**The Reliquary, Ruffius Rufeldro** *(ultra)* — +3, opponent −5 — "a blessing that isn't... the mask
holds."
> Ruffius Rufeldro in ornate reliquary-priest robes and a serene painted mask, hands raised in a
> gesture that looks like a blessing but casts a sickly light on whoever it's aimed at — benevolent
> surface, corrosive underneath.

**The Unending Flame, Tange Sazen** *(ultra)* — opponent −6, "cannot be healed... pinned outside of
time."
> Tange Sazen with a single unnaturally still flame burning on the edge of their blade that doesn't
> flicker or move at all — an eerie frozen-fire detail against Tange's normal dynamic action pose.

**The Between, Kleydson** *(ultra)* — +4, +6 more on 2nd+ duel — "chaos and order finding their
balance."
> Kleydson standing exactly on a visible dividing line where one half of the background is orderly
> geometric light and the other half is roiling chaotic distortion, perfectly balanced between both,
> arms out.

**Hanse, Rogue Fangs** *(rare)* — the base/starting printing of this Māyā pair. +2 power, +2 more
on the 1st or 2nd duel — "quick, vicious, not yet the Beast." Transforms into **The Bronzed Beast,
Hanse Waltz** (which already has art) once conjured twice in a match.
> A leaner, younger, rougher version of Hanse Waltz — feral energy, unrefined technique, moving
> fast and low rather than the Bronzed Beast's more composed power. Should read as clearly the
> same person's *earlier* stage, not a different character — check The Bronzed Beast's existing
> art for the face/identity to carry backward.

---

## Banish-pile revenants (2, ultra) — can only be conjured FROM the banish pile

**Ahdorah Khaan, Circle Unbroken** *(ultra)* — +4 power per banish-pile card.
> A ghostly, translucent echo of Ahdorah Khaan rising directly OUT of a heap of discarded
> banished cards/relics rather than standing on solid ground — unbroken determination even as a
> revenant.

**Kynaht, Ashen Return** *(ultra)* — opponent's Called supports contribute nothing this duel.
> A gaunt ash-grey revenant figure stepping out of drifting ash/cinders, one raised hand trailing a
> smothering grey mist that visibly snuffs out a small distant glow (representing the opponent's
> nullified supports) — a "silencer" visual, not a damage-dealer.

---

## Location control (2)

**Ridgeline Scout** *(rare)* — the duel's location effect applies only to you.
> A lone scout lying prone on a high ridgeline overlook, one hand marking a map, the wide valley
> battlefield below only partially visible/obscured by fog — "sees an angle the enemy can't."

**Ridgeline Warden** *(ultra)* — same effect, upgraded rarity.
> The escalated version of the scout above: now standing fully upright and commanding the same
> ridgeline in full view, cloak catching the wind, clearly the more experienced/senior version of
> the same role — keep visual continuity with Ridgeline Scout (same rocky ridge setting, same
> vantage-point concept).

---

## Instant tricks (3, common) — ⚡ played from the Instant Window, then return to deck/banish

Spell-effect framing rather than a static portrait — the character should be *caught mid-cast*.

**Fleeting Cipher** *(common, ⚡)* — returns to deck bottom; next conjure +6 this duel.
> A cloaked figure caught mid-motion flicking a rune-marked coin/token that's already fading into
> motion-blur as it leaves their fingers — the trick is already resolving, they're already turning
> away.

**Warden's Feint** *(common, ⚡)* — returns to deck bottom; blocks 1 opposing support zone.
> A warden-type figure making a sharp feinting gesture with a raised shield-arm, a faint
> shimmer-barrier snapping into place over an out-of-frame area — defensive misdirection, not an
> attack.

**Ashfall Tithe** *(common, ⚡)* — sent to banish; next conjure +7 this duel.
> A robed figure releasing a card/relic into a small rising column of ash that's already blowing
> away into embers — a willing sacrifice caught mid-tithe.

---

## Camp & trophy flavor, unaffiliated (3)

**Trilogy Ward** *(ultra)* — +5 if your camp beats the opponent's on the Skyward Trilogy wheel.
> A warded figure standing at the center of a three-pointed rune circle (Amageras/Omitsuki/Kitanoo
> — fire/water/earth-adjacent motifs are fine placeholders for the 3 camps), one point of the
> triangle glowing brighter than the other two — visually "the wheel favors me right now."

**Unbanked Victory** *(rare)* — +3 power if Winners Circle is empty.
> A lone fighter walking away from a battlefield without a single banner or trophy taken, empty-
> handed but standing tall — "the win that wasn't claimed is worth more," quiet dignity rather
> than triumph.

**Reclaim the Colors** *(common)* — +5 power if Winners Circle is empty.
> A standard-bearer raising a tattered, faded banner high before it's even been "won" anything —
> flying colors on faith, not on a banked record.

---

## Charge-economy support fodder, unaffiliated (4)

**Pyre-Keeper's Apprentice** *(common)* — Called: gain 1 Charge.
> A young apprentice tending a modest pyre/brazier, feeding it kindling, a small warm glow — the
> literal "keeps the fire/charge going" card.

**Lumen Acolyte** *(common)* — On commit: gain 1 Charge.
> A pale-robed acolyte cupping a small floating orb of soft light in both hands, eyes closed in
> quiet focus — gentle, novice-tier magic rather than dramatic combat.

**Oathlit Attendant** *(common)* — Called: gain 1 Charge.
> An attendant lighting a row of oath-candles down a temple aisle, one candle catching flame from
> the previous — methodical, ritual, unhurried.

**Trophy Runner** *(common)* — Called: gain 1 Charge if you've earned a kill this match.
> A courier sprinting between camp and field carrying a small banked trophy/token, motion-blurred
> legs, urgency — matches "runner" literally.

**Silk-Fed Hatchling** *(common, Broodswarm-adjacent)* — On commit: gain 1 Charge.
> A small newly-hatched brood-creature feeding on a strand of silk, low-key and non-threatening —
> the "starter" Charge card for the Broodswarm curve.

**Broodweb Keeper** *(common, Broodswarm-adjacent)* — Called: gain 1 Charge if hand ≥4.
> A caretaker-type broodkin tending and reinforcing a large web-structure, methodical rather than
> predatory.

---

## Death Remnant / support fodder, unaffiliated (2)

**Grave-Warden** *(common)* — Death Remnant: when it falls, +3 to your cards until an enemy dies.
> A weary graveyard warden standing watch over a single fresh grave-marker at dusk, lantern raised
> — the quiet dignity of "even in death, still on duty."

**Bone-Stitcher** *(common)* — Called: Fighter +3; draw a card if a Remnant is on the field.
> A field medic/mortician figure stitching a torn banner or binding a cracked bone-relic together
> with careful hands — mending rather than raising the dead, a subtler necromancer-adjacent read.

---

## Building order (suggested, not mandatory)

1. **Ultras first** (15 cards) — highest visibility, shown in Vault/Deck Builder hero slots and the
   lightbox zoom most often.
2. **Trophy Hall + the two rival camps** (22 cards) — a brand-new/recently-touched archetype and
   two heavily-played existing ones; finishing these makes 3 full decks feel complete.
3. **Everything else** (23 commons/rares) — fine to batch in any order.

When a batch is ready, ping to wire it into `CARD_ART`/`CARD_ART_FULL` and redeploy — that part's a
five-minute job on my end once the images exist.
