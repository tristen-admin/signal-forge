#!/usr/bin/env python3
"""Self-healing local dev server for Signal Forge.

Watches the canonical source HTML fragment for changes, wraps it into a
servable document in memory, and serves it with a tiny live-reload poller
injected — no manual "sync + restart preview" cycle needed. Stdlib only:
no installs, no network at runtime, binds 127.0.0.1 only.

Re-point at a different source file by editing watch_config.json (one line) —
useful across sessions, since the scratchpad path is session-specific.
"""
import http.server, socketserver, threading, time, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "watch_config.json")
BUILT_COPY_PATH = "/private/tmp/claude-501/-Users-kotei/97cae9eb-fc1a-4872-a2b6-a367e92660a6/scratchpad/serve/index.html"
DEFAULT_CONFIG = {
    "source": "/private/tmp/claude-501/-Users-kotei/97cae9eb-fc1a-4872-a2b6-a367e92660a6/scratchpad/gameplay-systems.html",
    "port": 8813
}
WRAPPER_HEAD = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
LIVE_RELOAD_SNIPPET = """
<script>
(function(){
  var last=null;
  function poll(){
    fetch('/__mtime__',{cache:'no-store'}).then(function(r){return r.text();}).then(function(t){
      if(last===null) last=t;
      else if(t!==last){ location.reload(); }
    }).catch(function(){}).finally(function(){ setTimeout(poll, 1000); });
  }
  poll();
})();
</script>
"""

def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[devwatch] config read failed, using defaults: {e}", flush=True)
    else:
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass
    return cfg

STATE = {"mtime": 0, "built": None, "last_err": None}

def rebuild(cfg):
    src = cfg["source"]
    try:
        mtime = os.path.getmtime(src)
    except FileNotFoundError:
        if STATE["last_err"] != "missing":
            print(f"[devwatch] source not found: {src}", flush=True)
            STATE["last_err"] = "missing"
        return
    if mtime == STATE["mtime"] and STATE["built"] is not None:
        return
    with open(src, "r", encoding="utf-8", errors="replace") as f:
        body = f.read()
    STATE["built"] = WRAPPER_HEAD + body + LIVE_RELOAD_SNIPPET + "</body></html>"
    STATE["mtime"] = mtime
    STATE["last_err"] = None
    print(f"[devwatch] rebuilt from source change ({time.strftime('%H:%M:%S')}, {len(body)} bytes)", flush=True)
    # also drop a copy on disk at the historical serve path, best-effort (compat / manual diffing)
    try:
        os.makedirs(os.path.dirname(BUILT_COPY_PATH), exist_ok=True)
        with open(BUILT_COPY_PATH, "w", encoding="utf-8") as f:
            f.write(STATE["built"])
    except Exception:
        pass

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet — avoid spamming stdout on every poll request

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            pass  # client disconnected mid-response — harmless, don't log noise

    def do_GET(self):
        if self.path == "/__mtime__":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(str(STATE["mtime"]).encode())
            return
        if self.path in ("/", "/index.html"):
            body = STATE["built"] or "<h1>waiting for source…</h1>"
            data = body.encode("utf-8", errors="replace")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(404)
        self.end_headers()

def watcher_loop(cfg, stop_evt):
    while not stop_evt.is_set():
        try:
            rebuild(cfg)
        except Exception as e:
            print(f"[devwatch] rebuild error (will retry): {e}", flush=True)
        time.sleep(0.5)

def main():
    cfg = load_config()
    rebuild(cfg)
    stop_evt = threading.Event()
    t = threading.Thread(target=watcher_loop, args=(cfg, stop_evt), daemon=True)
    t.start()
    port = int(os.environ.get("PORT", cfg["port"]))
    while True:
        try:
            with socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler) as httpd:
                print(f"[devwatch] serving http://127.0.0.1:{port}  (watching {cfg['source']})", flush=True)
                httpd.serve_forever()
        except Exception as e:
            print(f"[devwatch] server crashed, restarting in 1s: {e}", flush=True)
            time.sleep(1)

if __name__ == "__main__":
    main()
