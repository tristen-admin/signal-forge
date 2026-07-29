# Signal Economy — Earn-Rate Projection & the Ranked Raise/Fold Finding

*Compiled 2026-07-28. Every formula below is pulled from the live source, not estimated — the one deliberately-flagged exception is match pacing (seconds per duel), which isn't a hard game constant anywhere in the code and has to be assumed. Two pacing scenarios are given so the projection isn't hostage to that one guess.*

## What actually pays Signal (verified in `index.html`)

| Source | Formula | Notes |
|---|---|---|
| Public Server (casual) win | flat **+180** | loss: +30 |
| Ranked win, base stake | `round(rpAtStake/100 × 3000)` = **+600** at stakeMult ×1 (20 RP) | loss: ×0.3 → +180 |
| Ranked win, raised ×2 | **+1200** at stakeMult ×2 (40 RP) | scales linearly with RP at stake, caps at ×8 (160 RP → 4800 Signal) |
| Staked PvP win | flat **+50** (separate from the card wager itself) | |
| Daily Quests (real calendar day, not per-session) | Win 2 duels **+200** · Conjure 3 fighters **+150** · Check Marketplace **+100** | **+450/day**, hard-capped, resets at midnight regardless of playtime |
| Ascension (per node, ×`linkReward` multiplier, default ×1) | Common **+40** · Trial **+120** · Elite **+80** · Boss **+200** | plus a larger lump sum on full Rite completion |

Draft costs 2,500 Signal (10 picks, keep everything). Marketplace is player-to-player — it moves existing Signal around, it doesn't mint new Signal, so it's not in this model.

## The actual pack costs in the live Shop

| Pack | Price | Rarity odds |
|---|---|---|
| Legends Reborn Booster (Standard) | **500 ◈** | common 64% / uncommon 25% / rare 8% / ultra 2.3% / apex 0.8% |
| Legends Reborn Elite Cache | **1,500 ◈** | rare 78% / ultra 20% / apex 2% |

**A separate `PREMIUM_PACKS` array exists in the code** (Kindled Cache 2,000 / Forgemaster Vault 5,000 / Mythic Rite 12,000 — the "whale summon" tier, per its own code comment) **but is never rendered anywhere in the Shop UI.** `buildShop()`'s pack grid only maps over `PACKS` (the two above); `PREMIUM_PACKS` is only reachable through `openPack()`'s id lookup, which nothing in the UI ever calls with those three ids. It's dead content today, not a live purchase option — flagging because it matters a lot for the projection below.

## The Ranked raise/fold mechanic — this is what you're seeing at "40 Signal"

You're not imagining a hard "40" threshold — there isn't one in the code. What's actually happening:

- Base Ranked stake is 20 RP (stakeMult ×1). The bot only *initiates* a raise when it's behind (45% chance per turn); it only *declines* your raise when it's behind (45% chance — it always accepts if it's ahead or tied).
- **The first raise takes the stake from 20 RP to 40 RP if accepted.** If you're ahead (the normal moment to raise) and the bot is behind, it has a **45% chance to decline right at that first raise** — which is exactly the "folds at 40" pattern you're seeing, since that's the first number the stake ever shows once you've raised once.
- **Here's the part worth flagging: a decline doesn't just cap the stake, it ends the match immediately** — `retreat('bot')` sets `matchComplete=true` on the spot — **and pays out exactly half of what finishing the match at the *current* (pre-raise) stake would have paid.** Concretely: declining a first-raise attempt at base stake pays **300 Signal**; simply finishing that same match at base stake with no raise attempt at all pays **600**. Declining a second raise (already at ×2) pays **600**; finishing at ×2 pays **1,200**.

So **every folded raise is a strictly worse outcome, in raw Signal terms, than not raising at all** — the raise button only pays off when the bot *accepts*. It's not that the bots are unusually stingy; it's that the fold branch of this mechanic actively works against the player's Signal-per-hour rate close to half the time it triggers. If the goal is "raising should feel like a rewarded risk," the current fold penalty (half of pre-raise stake, plus an early match end) is arguably too harsh a punishment for a coin-flip-adjacent 45% chance — that's a real, quantified lever to pull, independent of anything below.

## Projection: Signal/day by playtime

Two pacing assumptions, shown side by side since this is the one number in this whole model that isn't pulled from code — everything else scales linearly with whichever one is closer to how you actually play:

- **Standard pace:** ~3.5 min/Ranked match (best-of-3, ~3 duels), ~5.5 min/Casual match (best-of-7, ~5–6 duels)
- **Fast pace:** roughly half that — ~1.75 min/Ranked, ~2.75 min/Casual

All rows assume **Ranked, base stake, no raising** (the reliable, non-trap baseline established above) at a neutral 50% win rate, plus the full +450 daily quest cap once per calendar day the pattern crosses a day boundary.

| Playtime pattern | Ranked matches (standard / fast pace) | Signal from matches | + Daily Quests | **Total Signal** |
|---|---|---|---|---|
| Light — 15 min/day | 4 / 8 | 1,560 / 3,120 | +450 | **2,010 / 3,570** |
| Moderate — 45 min/day | 13 / 26 | 5,070 / 10,140 | +450 | **5,520 / 10,590** |
| Heavy — 2 hr/day | 34 / 68 | 13,260 / 26,520 | +450 | **13,710 / 26,970** |
| Weekend binge — 4 hr, one sitting | 68 / 137 | 26,520 / 53,430 | +450 (one day) | **26,970 / 53,880** |

*(Per-match expected value at 50% win rate, no raise: 0.5×600 + 0.5×180 = 390 Signal/match.)*

## Days to afford a pack, against both pack tiers

| Playtime pattern | Standard (500) | Elite (1,500) | *If Premium existed:* Kindled (2,000) | *Forgemaster (5,000)* | *Mythic (12,000)* |
|---|---|---|---|---|---|
| Light — 15 min/day | same session | same session | ~1 day | ~2.5 days | ~6 days |
| Moderate — 45 min/day | same session | same session | same session | same session | ~2.2 days |
| Heavy — 2 hr/day | same session | same session | same session | same session | same session |

## What this actually says

At every playtime pattern tested — including the lightest, 15-minutes-a-day pattern — **a single session already covers both live packs several times over.** The 500/1,500 Signal price tags read as "scarce yet achievable" only if the intended earn rate were much lower than what Ranked's base-stake win currently pays, or if the intended *target* were the 2,000–12,000 tier instead. The Ranked win formula's own code comment says it was "sized so 25 base-stake wins = one premier summon" — 25 × 600 = 15,000, which lines up with the Mythic Rite's 12,000 price almost exactly, **not** the live 500/1,500 packs. That, plus `PREMIUM_PACKS` sitting fully built but never wired into the Shop UI, reads like the Signal-income rate was tuned against a pack tier that never shipped, leaving it wildly oversized against the tier that actually did.

Three independent, real levers here, your call on which (if any) to pull:
1. **Wire up `PREMIUM_PACKS`** in the Shop UI — gives Signal income somewhere to go that isn't trivially reachable in one sitting.
2. **Retune the Ranked win formula** (the 3000-per-100-RP multiplier) downward if 500/1,500 packs are meant to stay the ceiling of what's purchasable.
3. **Soften the raise/fold penalty** (currently: end the match early and pay only half) — independent of the scarcity question, but it's the direct mechanical cause of what you're observing at the table.
