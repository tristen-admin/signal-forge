# Visual & Animation Gaps — Gemini / Nano Banana Prompts

Companion to [`ART_PROMPTS.md`](./ART_PROMPTS.md) (which covers missing *card* art specifically).
This tracks everything **else** in the game that currently renders as a CSS gradient, a plain
emoji, or typography-only, where a real generated image asset would read as a finished game instead
of a prototype. Full-game survey done 8/9/26 — extend this list over time as new gaps turn up.

**How this works differently from card art**: nothing here needs animating from scratch — the
motion (scale, fade, pulse, shake) already exists in CSS/JS. Each item below asks for one **static
illustrated asset** (a texture, a burst, a backdrop, an icon set) to drop *into* the existing
animation in place of the current flat-color/emoji stand-in. Treat these as PNG sprites with
transparent backgrounds unless noted otherwise.

**Style continuity**: match [`ART_PROMPTS.md`](./ART_PROMPTS.md)'s house style (painterly dark
fantasy, dramatic lighting) for anything illustrated/atmospheric. VFX textures (bursts, cracks,
energy) can be more abstract/painterly-effect than character-portrait-real, but should still read
as *hand-painted*, not a flat vector icon pack or a stock-photo lens-flare.

---

## Fix first, no art needed

**Location/Condition banner shows only an emoji — but the real illustrated backdrop already
exists.** `#cond-main` (the in-duel banner announcing e.g. Tosa/Gnulför/Sorn-Vallis) renders a bare
18px emoji + text. `LOCATION_ART` already has real painted backdrops for these exact named
locations — they're just wired into Ascension's `ascSetVista()` only, never into the core duel's
condition banner. **This is a five-minute code fix, not a generation task** — say the word and I'll
wire it in directly rather than spending a Nano Banana prompt on art that already exists.

---

## Highest priority — biggest gap relative to how often players see it

**Avatāra activation** — the Deck Master system's own doctrine calls this "the 1 apex keyword" of
the whole mechanic. Right now firing it (`fireDeckMasterAvatara()`) produces **zero dedicated
visual** — just a `toast()` line. This is the single largest gap found: the game's own most
important keyword has no moment at all.
> A full-screen dramatic "awakening" burst — a figure's silhouette breaking open with radiant
> divine light pouring through the cracks, color-matched to a domain (try warm gold/white for a
> sun-domain Deck Master, cool silver/blue for a moon-domain one, storm-purple for a storm-domain
> one — generate 3 variants if you can). Vertical/full-screen composition, painterly, no readable
> text in the image (text overlays separately in-app).

**Pack-opening "Summon" reveal** — the core gacha-pull excitement beat, seen every time a pack
opens. Currently: a blurred blob, a fake `conic-gradient` standing in for light rays, a plain white
flash, and a single "✦" glyph — no illustrated summoning circle at all.
> An ornate arcane summoning circle viewed head-on, concentric rings of runes and sigils glowing
> from within, radiant energy pouring upward from the center, dark background so the ring itself
> is the bright focal point. Should look powerful enough to justify a rare-pull moment.

**Login / Create Account screen** — the very first screen a new or returning player sees going
online, and currently the plainest screen in the whole app: a flat form panel, no background image
at all (every other major screen has at least the shared vista backdrop; this one has nothing).
> A grand, moody entrance/threshold to the arena — an ornate gate or archway at dusk, torches lit
> on either side, mist or light beyond suggesting the arena within — atmospheric establishing shot,
> no characters in frame, leaves the login form comfortably readable if placed over the lower-
> center.

**Match/Series-end win & loss banners** — the climactic payoff of every single match is currently
pure Cinzel-font typography ("YOU WON"/"YOU LOST") over a blurred gold circle. No illustration at
all behind the biggest emotional beat in the game.
> **Win**: a triumphant upward burst — banners unfurling, light breaking through clouds, warm
> gold/white, celebratory without any specific character (this sits behind existing text, keep the
> vertical center clear/darker so text stays legible).
> **Loss**: a somber downward composition — a banner falling, embers drifting down, cool dark
> blue-grey, defeated but not cartoonish — same legibility constraint.
> *(Ascension's own separate victory banner — `.asc-victory .vb`, same typography-only gap — can
> reuse the Win asset above; no separate prompt needed.)*

---

## Mid priority

**Māyā transform** — swapping a card into its transformed printing (e.g. Hanse, Rogue Fangs →
The Bronzed Beast) currently just pops the new art in on re-render, no transformation effect at
all despite the mechanic's own description ("a real identity change, not a stat buff").
> A cracking-open silhouette/chrysalis effect — a card-shaped void breaking apart along jagged
> lines with bright light spilling from the cracks, mid-transformation, generic enough to overlay
> on any transforming card rather than tied to one character.

**Deck Master conjure banner** — when your Deck Master takes the field, only a pulsing gold ring +
text ("★ NAME takes the field"). No banner/heraldry behind it.
> An ornate gold-foil heraldic ribbon/banner shape, laurel and flourish details, designed to sit
> behind a centered line of text — think a "achievement unlocked" ribbon rendered in the game's
> painterly style rather than a flat UI graphic.

**Resolution Cinematic clash flash** (core duel) **+ Ascension battle impact VFX** — both are the
same underlying gap (a plain radial-gradient circle standing in for a hit/clash) in two different
screens. **One asset can serve both** — no need to generate twice.
> A jagged magical impact burst — sharp rays of bright light radiating from a central point, warm
> gold-white core fading to transparent at the edges, energetic and sudden. Transparent background,
> no characters, sized to work as a screen-space overlay at the moment two things collide.

**VS spotlight clash** (Ascension) — plain gold "VS" text over a dark scrim pulling in both
portraits. Currently no framing behind the text.
> A dramatic radial-ray backdrop specifically for a face-off moment — converging light rays toward
> the center where "VS" text sits, dark vignette at the corners, similar register to the clash-burst
> above but wider/more cinematic rather than a tight point-burst.

**Staked PvP wager screen** — reuses the same generic shared vista as Vault/Shop/Profile, with only
a plain "⚔" emoji marking the actual stakes. Doesn't feel distinct from browsing a menu, despite
real cards being on the line.
> A tense, high-stakes arena backdrop — two empty raised platforms or dueling stands facing each
> other across a shadowed pit, dramatic single-source lighting, nothing generic-fantasy-landscape
> about it — should feel like walking up to a real wager table, not another menu screen.

**Camp crests + Domain-god sigils** — two parallel 3-faction emblem sets (`CAMP_ICON`:
Amageras/Omitsuki/Kitanoo, `DOMAIN_GOD_ICON`: the same three as gods) are both currently plain
Unicode emoji (☀️🌙🌊 / ☀⛈☾), used constantly as filter chips, card faction rows, and the Hub's own
top-of-screen camp banner (currently a 24px circle with one emoji in it — the single most-seen
per-player identity marker in the game).
> Six heraldic crest/sigil illustrations as one cohesive set: three **camp** emblems (Amageras =
> sun-forged/warm, Omitsuki = moon/water-cool, Kitanoo = storm/cold) and three matching but visually
> distinct **domain-god** sigils for the same three. Circular medallion/crest format, consistent
> line weight and framing across all six so they read as one family, painterly metallic
> gold/silver/bronze rendering rather than flat vector.

---

## Lower priority / batch later (real gaps, deliberately deferred, not dropped)

**Keyword icon set** (`KW_ICON`, 23 keywords: Charge, Called, Link, Rally, Trigger, Conjure,
Bloodrage, Vajra, Astra, Nirmāṇa, Bandha, Māyā, and more) — every one is currently a single emoji
badge, shown on nearly every card everywhere. Real gap, but 23 individual prompts is disproportionate
to write by hand right now. **When ready**: generate as one cohesive icon-set pass (same framing,
same line weight, same palette family) rather than one-off — a mismatched icon set would look worse
than the current honest emoji.

**Keyword explainer mini-diagrams** (`KW_DEMO`, in tooltips/glossary) — small "how it works"
diagrams built from styled text spans + emoji (e.g. Link: `A 🔗 B +3`). Functional and honestly kind
of charming; lowest-visibility item on this list (only seen if a player opens a tooltip). Leave as
text/emoji unless the keyword icon set above ships first, then reuse those icons here too.

**Field-card death "shatter"** — a killed card currently just wobbles and fades; the code even
calls the CSS class `fc-shatter` despite nothing shattering.
> A radiating crack/fracture overlay — glass-like crack lines spreading from a central point,
> jagged, dark-edged, transparent elsewhere — meant to lay over a dying card just before it fades.

**Ascension "frame-lite" portrait bezel** — the actual character/foe art here is real (confirmed,
not a gap); only the decorative frame around it is a deliberately simplified stand-in. The code
comment explains why: the game's real ornate `TEMP_FRAME` PNG is intentionally avoided here because
it's re-rendered every turn for filler foes and the heavier asset doesn't fit that performance
budget. **If you generate a replacement, it needs to stay lightweight** — a simple per-camp corner
ornament or edge-tint asset, not a full ornate frame — otherwise it'll get reverted for the same
performance reason it was avoided the first time.

---

## Building order (suggested)

1. Wire up the free `LOCATION_ART` fix (no art needed).
2. The 4 "Highest priority" items — Avatāra, pack-opening reveal, login screen, match-end
   banners. These are the moments every player hits constantly and none currently have real art.
3. The 6 "Mid priority" items.
4. Batch the keyword icon set (23-piece set) as its own dedicated pass whenever there's room —
   don't split it across multiple sessions, it needs to ship as one consistent family.

Same handoff as `ART_PROMPTS.md`: generate → compress via `sips` → wire in → ping me to deploy.
