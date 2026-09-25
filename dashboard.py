#!/usr/bin/env python3
"""ChloeOS God Mode Dashboard — stdlib only.
Serves a live status dashboard for all ChloeOS agents and services.
Binds to the Tailscale IP so Steve can reach it from his phone."""
import json, os, subprocess, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone

PORT = 8199
BIND = "0.0.0.0"  # this VM's Tailscale IP
PROXY = os.environ.get("HTTPS_PROXY", "")
proxy_host = PROXY.split("://")[-1].split("/")[0] if PROXY else ""
TUNNEL = proxy_host.rsplit(":", 1)[0] + ":3130" if proxy_host else ""

TV = "100.126.25.41"
PHONE = "100.109.199.2"

def via_tunnel(url, timeout=8, method="GET", data=None, headers=None):
    """Fetch a tailnet URL through the tunnel proxy using curl."""
    proxy = os.environ.get("HTTPS_PROXY", "")
    tunnel = proxy.rsplit(":", 1)[0] + ":3130" if ":" in proxy else ""
    # strip scheme from proxy for curl
    tunnel = tunnel.split("://")[-1]
    cmd = ["curl", "-s", "-m", str(timeout), "--proxy", tunnel, "-X", method, url]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    if headers:
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
    cmd += ["-w", "\n%{http_code}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    out = r.stdout.strip().rsplit("\n", 1)
    if len(out) == 2:
        body, code = out
    else:
        body, code = r.stdout, "0"
    return int(code), body

def check_opencode(ip, port=4096):
    try:
        # Just check if the port responds at all
        status, raw = via_tunnel(f"http://{ip}:{port}/session", timeout=6, method="POST", data={})
        if status == 200:
            try:
                d = json.loads(raw)
                return {"status": "online", "session": d.get("id", "?")[:20]}
            except:
                return {"status": "online", "detail": "responding"}
        return {"status": "degraded", "http": status}
    except Exception as e:
        return {"status": "offline", "error": str(e)[:60]}

def check_audio(ip, port=8099):
    try:
        status, raw = via_tunnel(f"http://{ip}:{port}/health", timeout=6)
        if status == 200:
            try:
                d = json.loads(raw)
                return {"status": "online", "queue": d.get("queue_depth", "?"), "playing": d.get("playing", "?")}
            except:
                return {"status": "online"}
        return {"status": "degraded", "http": status}
    except Exception as e:
        return {"status": "offline", "error": str(e)[:60]}

def pulse_status():
    """Get Pulse repo status: recent commits, inbox counts."""
    try:
        repo = os.path.expanduser("~/workspace/pulse-live")
        # Recent commits
        log = subprocess.run(["git", "-C", repo, "log", "--oneline", "-5", "--format=%h|%s|%ar"],
                           capture_output=True, text=True, timeout=10)
        commits = []
        for line in log.stdout.strip().split("\n"):
            if line:
                h, s, a = line.split("|", 2)
                commits.append({"hash": h, "subject": s[:60], "ago": a})
        # Inbox counts
        inboxes = {}
        inbox_dir = os.path.join(repo, "inbox")
        if os.path.isdir(inbox_dir):
            for agent in os.listdir(inbox_dir):
                ad = os.path.join(inbox_dir, agent)
                if os.path.isdir(ad):
                    files = [f for f in os.listdir(ad) if f.endswith(".json")]
                    inboxes[agent] = len(files)
        return {"status": "ok", "commits": commits, "inboxes": inboxes}
    except Exception as e:
        return {"status": "error", "error": str(e)[:60]}

def get_status():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "updated": now,
        "agents": {
            "chloe.tv": {"desc": "TV main agent (Pulse)", "via": "Pulse mailbox"},
            "neo.tv": {"desc": "TV opencode coder", "server": check_opencode(TV)},
            "chloe.phone": {"desc": "Phone main agent (Pulse)", "via": "Pulse mailbox"},
            "neo.phone": {"desc": "Phone opencode coder", "server": check_opencode(PHONE)},
        },
        "services": {
            "tv_audio": check_audio(TV),
            "phone_audio": check_audio(PHONE),
        },
        "pulse": pulse_status(),
    }

HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ChloeOS God Mode</title>
<style>
body{background:#0a0a0f;color:#e0e0e0;font-family:system-ui,sans-serif;margin:0;padding:16px}
h1{color:#c084fc;font-size:1.4em;margin:0 0 4px}
.sub{color:#666;font-size:.85em;margin-bottom:16px}
.card{background:#14141c;border:1px solid #2a2a3a;border-radius:12px;padding:14px;margin-bottom:12px}
.card h2{margin:0 0 8px;font-size:1em;color:#a78bfa}
.row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #1e1e2a}
.row:last-child{border:none}
.name{font-weight:600}
.desc{color:#888;font-size:.8em}
.badge{padding:3px 10px;border-radius:20px;font-size:.75em;font-weight:700}
.on{background:#14532d;color:#4ade80}
.off{background:#450a0a;color:#f87171}
.deg{background:#451a03;color:#fb923c}
.unk{background:#1e293b;color:#94a3b8}
.commit{font-size:.8em;color:#aaa;padding:3px 0}
.commit b{color:#c084fc}
button{background:#7c3aed;color:#fff;border:none;border-radius:8px;padding:10px 20px;font-size:1em;cursor:pointer;margin-top:8px}
#updated{color:#555;font-size:.75em;margin-top:12px;text-align:center}
</style></head><body>
<h1>⚡ ChloeOS God Mode</h1>
<div class="sub">Live status — all agents & services</div>
<div id="dash">Loading…</div>
<div style="text-align:center"><button onclick="load()">↻ Refresh</button></div>
<div id="updated"></div>
<script>
function badge(s){
  if(s==='online')return '<span class="badge on">ONLINE</span>';
  if(s==='offline')return '<span class="badge off">OFFLINE</span>';
  if(s==='degraded')return '<span class="badge deg">DEGRADED</span>';
  return '<span class="badge unk">UNKNOWN</span>';
}
function load(){
  fetch('/api/status').then(r=>r.json()).then(d=>{
    let h='';
    h+='<div class="card"><h2>🤖 Agents</h2>';
    for(const [k,v] of Object.entries(d.agents)){
      let st = v.server ? v.server.status : 'unknown';
      let extra = v.server ? JSON.stringify(v.server).slice(0,80) : v.via;
      h+=`<div class="row"><div><div class="name">${k}</div><div class="desc">${v.desc}</div></div><div>${badge(st)}</div></div>`;
    }
    h+='</div>';
    h+='<div class="card"><h2>🔊 Audio Servers</h2>';
    for(const [k,v] of Object.entries(d.services)){
      h+=`<div class="row"><div><div class="name">${k}</div><div class="desc">queue: ${v.queue??'?'} playing: ${v.playing??'?'}</div></div><div>${badge(v.status)}</div></div>`;
    }
    h+='</div>';
    h+='<div class="card"><h2>📬 Pulse Mailbox</h2>';
    h+='<div class="desc">Inbox counts:</div>';
    for(const [k,v] of Object.entries(d.pulse.inboxes||{})){
      h+=`<div class="row"><div class="name" style="font-size:.85em">${k}</div><div class="badge ${v>0?'deg':'on'}">${v}</div></div>`;
    }
    h+='<div class="desc" style="margin-top:8px">Recent:</div>';
    for(const c of (d.pulse.commits||[])){
      h+=`<div class="commit"><b>${c.hash}</b> ${c.subject} <span style="color:#555">${c.ago}</span></div>`;
    }
    h+='</div>';
    document.getElementById('dash').innerHTML=h;
    document.getElementById('updated').textContent='Updated '+new Date(d.updated).toLocaleString();
  }).catch(e=>{document.getElementById('dash').innerHTML='<div class="card">Error loading: '+e+'</div>'});
}
load(); setInterval(load, 30000);
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            body = json.dumps(get_status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass

if __name__ == "__main__":
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"God Mode dashboard on http://{BIND}:{PORT}", flush=True)
    srv.serve_forever()
