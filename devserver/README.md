# devserver — self-healing local dev server

Replaces the old manual loop of "cat a wrapper + the canonical HTML fragment
into a serve/ copy, then restart the preview server" every time the game file
changes.

`watch_serve.py` is stdlib-only Python (no installs, no network at runtime,
binds `127.0.0.1` only):

- Watches `watch_config.json`'s `source` file for changes (polls mtime, ~0.5s).
- On change, wraps it into a full document (adds `<!doctype>`/`<head>`/`<body>`
  — the fragment has neither) and serves it from memory.
- Injects a tiny poller into the served page that checks `/__mtime__` every
  second and calls `location.reload()` when it changes — edits show up in the
  browser with no manual reload.
- Self-healing: the HTTP server runs in an outer retry loop (restarts on crash),
  and the watcher loop catches per-iteration errors so one bad read doesn't
  kill it.
- Also drops a copy on disk at the historical `scratchpad/serve/index.html`
  path, best-effort, for anything else that expects it there.

Wired into `~/.claude/launch.json` under the `"signal-forge"` config — just
use `preview_start({name: "signal-forge"})` as before; it now runs this
instead of a bare `python3 -m http.server`.

## Re-pointing to a new source file

`watch_config.json`'s `source` path is the scratchpad canonical file from
whatever Claude Code session set this up — scratchpad paths are session-
specific, so if you're in a new session and the game file lives elsewhere,
just edit that one path (or point it straight at this repo's own `index.html`
if you're editing that directly). No restart-the-world needed — the next
poll cycle picks it up.
