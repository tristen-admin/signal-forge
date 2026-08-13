# Signal Forge — TCG Prototype (Series 1)

A self-contained browser prototype. No build step, no dependencies — just open
`index.html` or serve it as a static site.

`index.html` is the whole game (~1.5 MB of markup + logic); its images, video and
audio live beside it in `assets/`, referenced by relative path. Keep the two
together and it runs straight off the filesystem, no server needed. Until
2026-08-13 the assets were inlined as base64 and the file was 54 MB — see
DEPLOY.md for why that changed and what it means when you add new art.

- Dashboard hub, Vault, Deck Builder (filters, presets, card backs)
- Best-of-7 matches vs bots, turn timers, reveal FX
- Marketplace (cosmetics + player card listings, prototype)
- Profile / emblems, on-chain provenance & Series 1 editions
