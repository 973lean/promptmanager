#!/usr/bin/env python3
"""Prompt Manager: a tiny, instant editor for your espanso prompts.

    python3 pm.py                 open the editor on espanso's match folder
    python3 pm.py path/to/match   use another folder of espanso .yml files
    python3 pm.py --port 7900 --no-open

Each tab is one .yml file in espanso's match folder (base.yml = "General").
Edits save straight into those files; espanso reloads them on its own.
Standard library only. Optional: `pip install anthropic` + ANTHROPIC_API_KEY
enables "Refine with Claude".
"""
import json, os, platform, re, secrets, ssl, subprocess, sys, threading, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.1.0"
REPO_RAW = os.environ.get("PM_UPDATE_URL", "https://raw.githubusercontent.com/973lean/promptmanager/main/")
HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.json"
TOKEN = secrets.token_urlsafe(24)
MODEL = os.environ.get("PM_MODEL", "claude-opus-5-5")
NAME_OK = re.compile(r"^[A-Za-z0-9][\w\- ]{0,60}\.ya?ml$")
META = (
    "You are an expert prompt engineer. Rewrite the prompt below so it gets the best possible "
    "result from a modern LLM. Keep the author's intent, voice and any placeholders exactly "
    "($|$ marks the cursor position, keep it). Be clear, specific and concise; add structure "
    "only where it helps; cut filler. Return ONLY the final prompt text: no preamble, no code "
    "fences, no commentary."
)


# ---------------- settings ----------------
def settings() -> dict:
    try:
        return {"auto_update": True, **json.loads(SETTINGS.read_text())}
    except Exception:
        return {"auto_update": True}


def save_settings(s: dict):
    SETTINGS.write_text(json.dumps(s, indent=2))


# ---------------- espanso ----------------
def espanso_match_dir() -> Path:
    if os.environ.get("ESPANSO_DIR"):
        return Path(os.environ["ESPANSO_DIR"]).expanduser() / "match"
    try:
        out = subprocess.run(["espanso", "path", "config"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            return Path(out) / "match"
    except Exception:
        pass
    home = Path.home()
    base = {
        "Darwin": home / "Library/Application Support/espanso",
        "Windows": Path(os.environ.get("APPDATA", home)) / "espanso",
    }.get(platform.system(), home / ".config/espanso")
    return base / "match"


def atomic_write(f: Path, text: str):
    tmp = f.with_name("." + f.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, f)  # espanso never reads half a file


# ---------------- updates ----------------
def vtuple(v: str):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def fetch(path: str) -> bytes:
    req = urllib.request.Request(REPO_RAW + path, headers={"User-Agent": "promptmanager", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            raise RuntimeError("SSL certificates missing. On macOS run 'Install Certificates.command' from your Python folder.")
        raise


def check_update() -> dict:
    m = json.loads(fetch("manifest.json"))
    return {"current": VERSION, "latest": m["version"], "available": vtuple(m["version"]) > vtuple(VERSION), "manifest": m}


def apply_update(manifest: dict) -> str:
    """Download every file first, verify, then swap them in. Your prompts are never touched."""
    files = {}
    for rel in manifest["files"]:
        if ".." in rel or rel.startswith("/"):
            raise RuntimeError(f"bad path in manifest: {rel}")
        data = fetch(rel)
        if not data:
            raise RuntimeError(f"empty download: {rel}")
        if rel.endswith(".py"):
            compile(data, rel, "exec")  # refuse a broken download
        files[rel] = data
    for rel, data in files.items():
        dst = HERE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".new")
        tmp.write_bytes(data)
        if rel.endswith((".command", ".py")):
            os.chmod(tmp, 0o755)
        os.replace(tmp, dst)
    return manifest["version"]


UPDATE = {"status": "idle", "latest": None, "error": None}  # status: idle|checking|current|available|updated|error


def bg_check(auto_apply: bool):
    UPDATE.update(status="checking", error=None)
    try:
        info = check_update()
        UPDATE["latest"] = info["latest"]
        if not info["available"]:
            UPDATE["status"] = "current"
        elif auto_apply:
            apply_update(info["manifest"])
            UPDATE["status"] = "updated"
        else:
            UPDATE["status"] = "available"
    except Exception as e:
        UPDATE.update(status="error", error=str(e))


def restart():
    args = [a for a in sys.argv[1:] if a != "--no-open"] + ["--no-open"]
    os.execv(sys.executable, [sys.executable, str(HERE / "pm.py"), *args])


# ---------------- claude ----------------
def has_claude() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def refine(text: str) -> str:
    import anthropic

    r = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=16000, system=META,
        messages=[{"role": "user", "content": f"Prompt to improve:\n\n{text}"}],
    )
    if r.stop_reason == "refusal":
        raise RuntimeError("Claude declined to rewrite this prompt.")
    return "".join(b.text for b in r.content if b.type == "text").strip()


# ---------------- server ----------------
class App(BaseHTTPRequestHandler):
    dir: Path
    port: int
    backed_up: set = set()

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):  # blocks DNS rebinding
        return self.headers.get("Host") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def authed(self):  # blocks other websites from writing your files
        return self.host_ok() and secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN)

    def path_for(self, name) -> Path:
        if not isinstance(name, str) or not NAME_OK.match(name):
            raise ValueError("bad file name")
        return self.dir / name

    def file_state(self, f: Path):
        return {"name": f.name, "text": f.read_text(encoding="utf-8"), "mtime": str(f.stat().st_mtime_ns)}

    def state(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        base = self.dir / "base.yml"
        if not base.exists():
            base.write_text("matches: []\n", encoding="utf-8")
        files = sorted(
            (f for f in self.dir.iterdir() if f.is_file() and NAME_OK.match(f.name)),
            key=lambda f: (f.name != "base.yml", f.name.lower()),
        )
        return {
            "dir": str(self.dir), "files": [self.file_state(f) for f in files], "claude": has_claude(),
            "version": VERSION, "update": UPDATE, "auto_update": settings()["auto_update"],
        }

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        if self.path == "/":
            html = (HERE / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self.send(200, html, "text/html")
        if self.path == "/js-yaml.min.js":
            return self.send(200, (HERE / "vendor/js-yaml.min.js").read_bytes(), "text/javascript")
        if self.path == "/api/state" and self.authed():
            return self.send(200, self.state())
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.authed():
            return self.send(403, {"error": "forbidden"})
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            return self.route(b)
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:
            return self.send(500, {"error": str(e)})

    def route(self, b):
        p = self.path
        if p == "/api/save":
            f = self.path_for(b["name"])
            cur = str(f.stat().st_mtime_ns) if f.exists() else "0"
            if b.get("mtime") != cur:
                return self.send(409, self.state())  # changed on disk since the editor loaded it
            if f.exists() and f.name not in App.backed_up:
                f.with_name(f.name + ".bak").write_bytes(f.read_bytes())
                App.backed_up.add(f.name)
            atomic_write(f, b["text"])
            return self.send(200, {"mtime": str(f.stat().st_mtime_ns)})
        if p == "/api/rename":
            src, dst = self.path_for(b["from"]), self.path_for(b["to"])
            if src.name == "base.yml":
                raise ValueError("General (base.yml) can't be renamed")
            if dst.exists():
                raise ValueError("a tab with that name already exists")
            os.replace(src, dst)
            return self.send(200, self.state())
        if p == "/api/delete":
            f = self.path_for(b["name"])
            if f.name == "base.yml":
                raise ValueError("General (base.yml) can't be deleted")
            f.with_name(f.name + ".bak").write_bytes(f.read_bytes())
            f.unlink()
            return self.send(200, self.state())
        if p == "/api/refine":
            return self.send(200, {"text": refine(b.get("text", ""))})
        if p == "/api/update/check":
            bg_check(auto_apply=False)
            return self.send(200, UPDATE)
        if p == "/api/update/apply":
            bg_check(auto_apply=True)
            return self.send(200, UPDATE)
        if p == "/api/restart":
            self.send(200, {"ok": True})
            threading.Timer(0.3, restart).start()
            return
        if p == "/api/settings":
            s = settings()
            s["auto_update"] = bool(b.get("auto_update"))
            save_settings(s)
            return self.send(200, s)
        self.send(404, {"error": "not found"})


def main(argv):
    port, open_browser, target = 7878, True, None
    it = iter(argv)
    for a in it:
        if a == "--port":
            port = int(next(it))
        elif a == "--no-open":
            open_browser = False
        elif a in ("-h", "--help"):
            sys.exit(print(__doc__))
        elif a == "--version":
            sys.exit(print(VERSION))
        else:
            target = Path(a).expanduser().resolve()
    App.dir = target or espanso_match_dir()
    App.port = port
    ThreadingHTTPServer.allow_reuse_address = True
    srv = ThreadingHTTPServer(("127.0.0.1", port), App)
    url = f"http://127.0.0.1:{port}/"
    print(f"Prompt Manager {VERSION} → {url}\nfolder {App.dir}\nCtrl+C to quit")
    if settings()["auto_update"] and not os.environ.get("PM_NO_UPDATE"):
        threading.Thread(target=bg_check, args=(True,), daemon=True).start()  # never delays startup
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
