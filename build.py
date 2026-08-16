#!/usr/bin/env python3
"""
Signal Forge — static build.

De-embeds the base64 assets from the single-file HTML into a clean, installable,
deployable /dist folder. Output is a plain PWA (index.html + /assets + manifest)
that runs identically self-hosted (local/mesh) or on any static host later.
No build tooling, no dependencies (stdlib only).

Usage:
    python3 build.py [source.html]        # default source: ./index.html  ->  ./dist/

Local self-host:
    python3 -m http.server 8080 --directory dist   # http://127.0.0.1:8080
Public later (same dist/, one command):
    npx wrangler pages deploy dist    |    npx netlify deploy --dir dist --prod
"""
import re, os, sys, base64, hashlib, shutil, json

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "index.html")
OUT  = os.path.join(ROOT, "dist")

# Full <head> — title is set separately by rewriting the source's own <title>.
WRAP_HEAD = (
    '<!doctype html><html lang="en"><head>'
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    # 8/16/26 — the dev server (python -m http.server) sends no cache headers, so browsers applied
    # heuristic caching to a 1.6MB document and a plain refresh kept serving the OLD build. That
    # silently cost real debugging time on both sides: fixes were shipped, reloaded, and appeared
    # not to work because the page had not actually changed. Every reload this session needed a
    # manual ?v= buster. These make a refresh mean what it says.
    '<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">'
    '<meta http-equiv="Pragma" content="no-cache">'
    '<meta http-equiv="Expires" content="0">'
    '<meta name="description" content="KOTEI: The Trading Card Game — a living-card TCG where every card carries its permanent match history.">'
    '<meta name="theme-color" content="#0b0e14">'
    '<link rel="manifest" href="manifest.webmanifest">'
    '<link rel="icon" href="icon.svg" type="image/svg+xml">'
    '<link rel="apple-touch-icon" href="apple-touch-icon.jpg">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
    '<meta name="apple-mobile-web-app-title" content="KOTEI">'
    '</head><body>\n'
)

ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
    '<rect width="512" height="512" rx="104" fill="#0b0e14"/>'
    '<path d="M256 104 L392 256 L256 408 L120 256 Z" fill="#F5C24D"/>'
    '<path d="M256 168 L328 256 L256 344 L184 256 Z" fill="#0b0e14"/>'
    '</svg>'
)

MANIFEST = {
    "name": "KOTEI: The Trading Card Game",
    "short_name": "KOTEI",
    "description": "A living-card TCG where every card carries its permanent match history.",
    "start_url": "./",
    "scope": "./",
    "display": "standalone",
    "orientation": "any",
    "background_color": "#0b0e14",
    "theme_color": "#0b0e14",
    "icons": [
        {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}
    ],
}

EXT = {'image/jpeg': 'jpg', 'image/jpg': 'jpg', 'image/png': 'png', 'image/webp': 'webp',
       'image/gif': 'gif', 'image/svg+xml': 'svg', 'video/mp4': 'mp4', 'audio/mp4': 'm4a',
       'audio/mpeg': 'mp3'}
DATA_URI = re.compile(
    r'data:(image/(?:jpeg|jpg|png|webp|gif|svg\+xml)|video/mp4|audio/(?:mp4|mpeg));base64,([A-Za-z0-9+/]+={0,2})')


def main():
    if not os.path.isfile(SRC):
        sys.exit(f"source not found: {SRC}")
    html = open(SRC, encoding='utf-8').read()

    # Normalize the wrapper: strip any existing <!doctype..><body> shell, apply our full head.
    m = re.match(r'\s*<!doctype html>.*?<body[^>]*>\s*', html, flags=re.S | re.I)
    if m:
        html = html[m.end():]
    html = WRAP_HEAD + html

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "assets", "img"))
    os.makedirs(os.path.join(OUT, "assets", "video"))
    os.makedirs(os.path.join(OUT, "assets", "audio"))

    # 8/13/26: the source no longer carries base64 payloads -- they were de-embedded into a
    # committed ./assets tree so index.html stopped being a 54 MB blob that every art commit
    # rewrote in full (GitHub warned on the 50 MB limit on every push, and history grew by the
    # whole file each time). The de-embed used THIS script's own hashing, so the filenames are
    # identical to what it used to generate and dist/index.html comes out byte-for-byte unchanged.
    # The data-URI substitution below is intentionally KEPT: it is now a no-op for the normal
    # source, but it still handles any newly-pasted inline asset, so a card art dropped straight
    # into the HTML is de-embedded on the next build exactly as before, rather than silently
    # shipping a fresh multi-MB blob. Anything already external is copied through as-is.
    src_assets = os.path.join(ROOT, "assets")
    copied = 0
    if os.path.isdir(src_assets):
        for sub in ("img", "video", "audio"):
            d = os.path.join(src_assets, sub)
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                sp = os.path.join(d, fn)
                if os.path.isfile(sp):
                    shutil.copyfile(sp, os.path.join(OUT, "assets", sub, fn))
                    copied += 1

    seen = {}
    stats = {'img': 0, 'video': 0, 'audio': 0, 'bytes': 0, 'dedup': 0, 'fail': 0}

    def repl(mm):
        mime, b64 = mm.group(1), mm.group(2)
        try:
            raw = base64.b64decode(b64)
        except Exception:
            stats['fail'] += 1
            return mm.group(0)
        h = hashlib.sha1(raw).hexdigest()[:12]
        if h in seen:
            stats['dedup'] += 1
            return seen[h]
        sub = 'video' if mime.startswith('video') else 'audio' if mime.startswith('audio') else 'img'
        fn = f"{h}.{EXT.get(mime, 'bin')}"
        with open(os.path.join(OUT, "assets", sub, fn), 'wb') as f:
            f.write(raw)
        rel = f"assets/{sub}/{fn}"
        seen[h] = rel
        stats[sub] += 1
        stats['bytes'] += len(raw)
        return rel

    out_html = DATA_URI.sub(repl, html)
    out_html = re.sub(r'<title>.*?</title>', '<title>KOTEI: The Trading Card Game</title>', out_html, count=1, flags=re.S)

    with open(os.path.join(OUT, "index.html"), 'w', encoding='utf-8') as f:
        f.write(out_html)
    with open(os.path.join(OUT, "icon.svg"), 'w', encoding='utf-8') as f:
        f.write(ICON_SVG)
    with open(os.path.join(OUT, "manifest.webmanifest"), 'w', encoding='utf-8') as f:
        json.dump(MANIFEST, f, indent=2)

    # iOS home-screen icon: reuse a hero card image (iOS ignores SVG apple-touch-icon).
    apple = None
    for name in ("Kotei", "Akatosh, the Golden Dragon", "Ella Ballora"):
        mo = re.search(r"['\"]" + re.escape(name) + r"['\"]\s*:\s*['\"](assets/img/[^'\"]+)['\"]", out_html)
        if mo:
            apple = mo.group(1); break
    if apple and os.path.isfile(os.path.join(OUT, apple)):
        shutil.copyfile(os.path.join(OUT, apple), os.path.join(OUT, "apple-touch-icon.jpg"))

    leftover = len(re.findall(r'data:(?:image|video|audio)/[^;]+;base64,', out_html))
    print(f"source          : {SRC}  ({len(html)//1024//1024} MB)")
    print(f"dist/index.html : {len(out_html)//1024} KB")
    print(f"images extracted: {stats['img']}   videos: {stats['video']}   audio: {stats['audio']}   "
          f"deduped: {stats['dedup']}   failed: {stats['fail']}")
    print(f"assets copied   : {copied} files from ./assets")
    print(f"assets on disk  : {stats['bytes']//1024//1024} MB newly extracted")
    print(f"leftover data-URIs: {leftover}")
    print(f"pwa: manifest + icon.svg{' + apple-touch-icon.jpg' if apple else ' (no apple icon found)'}")
    print(f"OUTPUT          : {OUT}")


if __name__ == "__main__":
    main()
