# Signal Forge — Overnight Update (2026-07-05)

Fresh link (cache-free): https://claude.ai/code/artifact/62781731-6ab8-42ff-9b98-83b5d106c3ba

## New
- **How to Play** — a clear 6-step core-loop guide (draw → reveal condition → conjure fighter → call supports → links → commit) with Energy / Records / Wager notes. Auto-shows once for new players; reopen via the **?** button or Settings.
- **Settings panel** (⚙) — Sound toggle + an in-app **Reduce Motion** switch (kills animations for a smoother phone experience) + How-to-Play shortcut. Consolidated the old floating sound button.

## Combat robustness
- **Self-healing watchdog** — a duel can no longer lock up: if it hangs in the committed state >12s it auto-advances. 
- **Tap anywhere on the result overlay to continue** (fixes the crowded-mobile Continue button being hard to hit); Continue is debounced so nothing double-advances.
- **Twisted Vivarium ("Force Swap") clarity** — it was logging "your card replaced by <other card>," which read like a swap glitch. Now honestly worded as a power scramble (your card stays; only its power is scrambled).

## Mobile
- **Touch drag fixed** — pointer capture keeps the drag tracked, and a forgiving drop means releasing anywhere in the play area deploys (no pixel-perfect drop needed).
- **Landscape combat** — hand no longer cut off; opponent panel + hand ability text hidden to fit the short height, field uses the wide space.
- **Hand card names** no longer clipped by the cost badge.
- Earlier this session: field-first mobile combat, transparent centered hand, and 4 view-overflow fixes (mastery / shop / DNA / replay).

## Also
- Purchase confirmations on every buy (packs, cards, marketplace, cosmetics, frames, mystery cache).
- Clickable lore-link names → a viewer showing every unit in that link group, with art.

## Known follow-ups (your call)
- Mobile nav is an unlabeled icon rail — could add labels or a bottom tab bar.
- Content depth (more Called effects / conditions / cards) — deferred to avoid changing balance right before you test.
