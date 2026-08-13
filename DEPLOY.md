# Signal Forge — deploy

The game is a **single static site**. No server is required for the game as it
plays today (single-player vs bots + Ascension; all progress saved in the
browser's `localStorage`). The `server/` folder is a separate, not-yet-wired
authoritative backend — only needed later for cross-device accounts / real PvP /
a persistent marketplace.

## Build

`index.html` is the hand-edited source. Its assets are **not** inlined: they sit in
a committed `assets/` tree and are referenced by relative path, so the file is
~1.5 MB rather than the 54 MB it was when everything was base64.

**Why (2026-08-13):** a 54 MB `index.html` was rewritten in full by every art
change, so each such commit added ~54 MB to history permanently and GitHub warned
past its 50 MB file limit on every push. Assets now change as individual binary
files. Note this fixes growth from here on — the old blobs are still in history.

**Adding new art:** pasting a base64 `data:` URI straight into `index.html` still
works. `build.py` de-embeds any it finds, so nothing breaks — but the blob lives in
your source until you rebuild. Prefer dropping the file into `assets/img/` and
referencing it by path.

`build.py` copies `assets/` through, de-embeds anything still inline, and writes a
clean deployable folder:

```sh
python3 build.py          # reads ./index.html  ->  writes ./dist/
```

Output `dist/` is a plain static site:

```
dist/
  index.html          # ~660 KB (was ~13 MB inlined)
  assets/img/*.jpg    # 96 card/background images, content-hashed
  assets/video/*.mp4  # card animations, content-hashed
  _headers            # long-cache the hashed assets (Cloudflare/Netlify)
```

Asset filenames are content hashes, so they can be cached forever; only
`index.html` revalidates. Re-run `build.py` after changing the game.

## Run locally (self-host)

```sh
python3 -m http.server 8080 --directory dist
# open http://127.0.0.1:8080
```

Or on your LAN/mesh, bind the interface you want (default binds all):

```sh
python3 -m http.server 8080 --directory dist --bind 127.0.0.1
```

Any static server works the same (Caddy: `caddy file-server --root dist`).

## Install as an app (local, on your phone)

`dist/` is a PWA (manifest + icons + `display:standalone`). Over your LAN/mesh:

- **iPhone (Safari):** open `http://<your-mac-ip>:8080`, Share → **Add to Home Screen**.
  Launches fullscreen, own icon — no cloud, no App Store. Works over plain http.
- **Android (Chrome):** the install prompt needs a **secure context** (HTTPS or
  localhost). Easiest local HTTPS = `caddy file-server --root dist` with a
  `caddy` local cert, or `mkcert`. (iOS above needs no HTTPS.)

This is the LOCAL-ONLY way to ship: off the Claude artifact, on your own
hardware, installable — zero external cloud.

## When to go public (the gate — not yet)

Hold the public flip until **both**:
1. The client is wired to `server/` (today it's `localStorage`-only, so "public"
   = a single-player prototype, not the data/marketplace product), **and**
2. The game is stable enough that you won't need to wipe player state — going
   public locks in accounts / owned cards / market positions.

Going public is also a conscious exception to the LOCAL-ONLY doctrine; decide it
deliberately, don't drift into it.

## Go public later (no rework — same `dist/`)

Pick one; each is a single command and gives automatic HTTPS:

```sh
# Cloudflare Pages
npx wrangler pages deploy dist

# Netlify
npx netlify deploy --dir dist --prod

# GitHub Pages: push dist/ contents to a gh-pages branch (or point Pages at /dist)
```

Then point a domain at it in the host's dashboard. That's the whole job — the
folder that self-hosts is byte-for-byte what deploys publicly.

## Later: activate the backend (`server/`)

Only when you want accounts / real PvP / persistent marketplace:

1. Wire the client's state + duels to the server API (today it's `localStorage`-only).
2. Run `server/app.py` behind a real WSGI/ASGI server + Caddy/nginx for TLS
   (stdlib `http.server` is not safe to expose publicly as-is).
3. Move SQLite → Postgres if you go real-multiplayer / marketplace scale.
