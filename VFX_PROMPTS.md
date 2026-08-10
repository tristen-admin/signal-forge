Location/Condition banner

No image needed -- this is a code fix. The in-duel banner showing the active location (Tosa, Gnulfor, Sorn-Vallis, etc.) currently shows only an emoji, but real illustrated backdrops for these exact locations already exist in the game's LOCATION_ART table and are just never wired in outside Ascension.


Avatara activation -- SHIPPED 8/10/26

Done. Real footage generated, cut from 10s to 3.2s (trimmed the static open and the slow fade tail, sped up ~2.3x, audio pitch preserved), wired as a full-screen dismissable overlay firing from the real fireDeckMasterAvatara() trigger.


Pack-opening summon reveal -- SHIPPED 8/10/26

Done. Real footage generated, cut from 10s to 8.5s (trimmed the static hold at the end), replaces the old CSS-blob cluster during the roll phase, reveal() now fires on the video's real 'ended' event per this function's own pre-existing comment.


Login / create account screen -- SHIPPED 8/10/26

Done. Real footage generated (a closed gate creaking open onto a torchlit arena beyond), used in full as a one-shot backdrop reveal behind the sign-in/create-account panel, holding on its own last frame afterward.


Match-end win banner -- SHIPPED 8/10/26

Done. Real footage generated (storm clouds part, two banners unfurl, warm gold light rays break through), played once behind the WON screen then held on its final frame. Wired into both real match-end sites (bot matches and Staked PvP). Loss banner still not generated -- that branch keeps the plain dark gradient it always had.


Match-end loss banner

A somber downward composition -- a banner falling, embers drifting down, cool dark blue-grey, defeated but not cartoonish, darker toward the vertical center so overlaid text stays legible.


Maya transform flash

A cracking-open silhouette effect -- a card-shaped void breaking apart along jagged lines with bright light spilling from the cracks, mid-transformation, generic enough to overlay on any transforming card.


Deck Master conjure banner

An ornate gold-foil heraldic ribbon/banner shape, laurel and flourish details, designed to sit behind a centered line of text.


Resolution clash / battle impact burst

A jagged magical impact burst -- sharp rays of bright light radiating from a central point, warm gold-white core fading to transparent at the edges, energetic and sudden. Transparent background, no characters.


VS spotlight clash

A dramatic radial-ray backdrop for a face-off moment -- converging light rays toward the center, dark vignette at the corners, wide and cinematic.


Staked PvP wager screen

A tense, high-stakes arena backdrop -- two empty raised platforms or dueling stands facing each other across a shadowed pit, dramatic single-source lighting.


Camp crests and domain-god sigils

Six heraldic crest/sigil illustrations as one cohesive set -- three camp emblems (Amageras: sun-forged, warm; Omitsuki: moon/water, cool; Kitanoo: storm, cold) and three matching domain-god sigils for the same three. Circular medallion format, consistent line weight and framing across all six, painterly metallic gold/silver/bronze rendering.


Field-card death shatter

A radiating crack/fracture overlay -- glass-like crack lines spreading from a central point, jagged, dark-edged, transparent elsewhere.


Ascension frame-lite bezel

A lightweight per-camp corner ornament or edge-tint asset for framing character portraits in Ascension battles. Must stay simple/small -- it's re-rendered every turn, so an ornate heavy frame will get reverted for performance.


Keyword icon set

Not prompted yet -- 23 keywords (Charge, Called, Link, Rally, Trigger, Conjure, Bloodrage, Vajra, Astra, Nirmana, Bandha, Maya, and more) each need an icon. Deferred until ready to do as one consistent batch rather than piecemeal.


Keyword explainer diagrams

Not prompted yet -- lowest-visibility item on this list, only seen in tooltips. Leave as-is unless the keyword icon set above ships first.
