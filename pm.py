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
import json, os, platform, re, secrets, ssl, subprocess, sys, threading, time, urllib.parse, urllib.request, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.4.1"
REPO_RAW = os.environ.get("PM_UPDATE_URL", "https://raw.githubusercontent.com/973lean/promptmanager/main/")
RELEASE = os.environ.get("PM_RELEASE_URL", "https://github.com/973lean/promptmanager/releases/latest/download/")
FROZEN = getattr(sys, "frozen", False)  # running as PromptManager.exe
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent  # where settings live
RES = Path(getattr(sys, "_MEIPASS", HERE))  # where index.html and vendor/ live
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
DEFAULTS = {"auto_update": True, "app_window": True}

def settings() -> dict:
    try:
        return {**DEFAULTS, **json.loads(SETTINGS.read_text())}
    except Exception:
        return dict(DEFAULTS)


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


def fetch(path: str, base: str = REPO_RAW) -> bytes:
    req = urllib.request.Request(base + urllib.parse.quote(path), headers={"User-Agent": "promptmanager", "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except urllib.error.URLError as e:
        if isinstance(e.reason, ssl.SSLError):
            raise RuntimeError("SSL certificates missing. On macOS run 'Install Certificates.command' from your Python folder.")
        raise


def check_update() -> dict:
    # The .exe follows GitHub Releases (published once the build finishes); the script follows main.
    m = json.loads(fetch("manifest.json", RELEASE if FROZEN else REPO_RAW))
    return {"current": VERSION, "latest": m["version"], "available": vtuple(m["version"]) > vtuple(VERSION), "manifest": m}


def apply_exe_update() -> None:
    """Windows lets you rename a running .exe, so: rename ours aside, drop the new one in its place."""
    exe = Path(sys.executable)
    data = fetch("PromptManager.exe", RELEASE)
    if len(data) < 1_000_000 or data[:2] != b"MZ":
        raise RuntimeError("the downloaded app looks broken; keeping the current one")
    new, old = exe.with_name(exe.stem + ".new.exe"), exe.with_name(exe.stem + ".old.exe")
    new.write_bytes(data)
    if old.exists():
        old.unlink()
    os.replace(exe, old)
    os.replace(new, exe)


def apply_update(manifest: dict) -> str:
    """Download every file first, verify, then swap them in. Your prompts are never touched."""
    if FROZEN:
        apply_exe_update()
        return manifest["version"]
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
    """Start a fresh copy (it waits for the port to free up), then exit."""
    args = [a for a in sys.argv[1:] if a not in ("--no-open", "--restarted")] + ["--no-open", "--restarted"]
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no console pops up
    cmd = [sys.executable, *args] if FROZEN else [sys.executable, str(HERE / "pm.py"), *args]
    subprocess.Popen(cmd, creationflags=flags, close_fds=True)
    os._exit(0)


# ---------------- start with Windows ----------------
def startup_file() -> Path:
    folder = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
    return folder / ("Prompt Manager.vbs" if FROZEN else "Prompt Manager.pyw")


def set_startup(on: bool):
    f = startup_file()
    if not on:
        return f.unlink() if f.exists() else None
    if FROZEN:  # run the .exe hidden at login
        f.write_text(f'CreateObject("WScript.Shell").Run """{sys.executable}"" --no-open", 0\n', encoding="utf-8")
    else:
        f.write_text(
            "import runpy, sys\n"
            f"sys.argv = [{str(HERE / 'pm.py')!r}, '--no-open']\n"
            f"runpy.run_path({str(HERE / 'pm.py')!r}, run_name='__main__')\n",
            encoding="utf-8",
        )


# ---------------- open the window ----------------
def find_browser():
    """Chrome first, then Edge. Returns ("win", exe path) / ("mac", app name) / None."""
    if os.name == "nt":
        env = os.environ.get
        for p in (
            Path(env("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            Path(env("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
            Path(env("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
            Path(env("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
            Path(env("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        ):
            if p.is_file():
                return ("win", str(p))
    elif sys.platform == "darwin":
        for app in ("Google Chrome", "Microsoft Edge"):
            if Path(f"/Applications/{app}.app").exists():
                return ("mac", app)
    return None


def open_ui(url: str, mode: str = ""):
    """mode "window": app window (no tabs/address bar). mode "tab": a normal Chrome tab. "" = the saved setting."""
    mode = mode or ("window" if settings()["app_window"] else "tab")
    b = find_browser()
    try:
        if b and b[0] == "win":
            return subprocess.Popen([b[1], f"--app={url}"] if mode == "window" else [b[1], url])
        if b and b[0] == "mac":
            return subprocess.Popen(["open", "-na", b[1], "--args", f"--app={url}"] if mode == "window" else ["open", "-a", b[1], url])
    except Exception:
        pass
    webbrowser.open(url)


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
            "windows": os.name == "nt", "startup": os.name == "nt" and startup_file().exists(),
            "app_window": settings()["app_window"], "exe": FROZEN,
        }

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        if self.path == "/":
            html = (RES / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN)
            return self.send(200, html, "text/html")
        if self.path == "/js-yaml.min.js":
            return self.send(200, (RES / "vendor/js-yaml.min.js").read_bytes(), "text/javascript")
        if self.path == "/icon.png":
            return self.send(200, (RES / "icon.png").read_bytes(), "image/png")
        if self.path == "/manifest.webmanifest":  # lets Chrome/Edge "Install" it as an app
            return self.send(200, json.dumps({
                "name": "Prompt Manager", "short_name": "Prompts", "start_url": "/", "display": "standalone",
                "background_color": "#f4f5f7", "theme_color": "#2f6bff",
                "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}],
            }), "application/manifest+json")
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
            if not f.exists():
                App.backed_up.add(f.name)  # brand-new tab: nothing to back up
            elif f.name not in App.backed_up:
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
            for k in ("auto_update", "app_window"):
                if k in b:
                    s[k] = bool(b[k])
            save_settings(s)
            if "startup" in b and os.name == "nt":
                set_startup(bool(b["startup"]))
            return self.send(200, s)
        if p == "/api/library":  # your prompt library, from library/ in the GitHub repo
            idx = json.loads(fetch("library/index.json"))
            return self.send(200, {"tabs": [{**t, "text": fetch("library/" + t["file"]).decode("utf-8")} for t in idx["tabs"]]})
        if p == "/api/open":  # also remembered for next launch
            st = settings(); st["app_window"] = b.get("mode") == "window"; save_settings(st)
            open_ui(f"http://127.0.0.1:{self.port}/", "window" if b.get("mode") == "window" else "tab")
            return self.send(200, {"ok": True, "browser": (find_browser() or ("", "your browser"))[1]})
        if p == "/api/quit":
            self.send(200, {"ok": True})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        self.send(404, {"error": "not found"})


def already_running(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return b"Prompt Manager" in r.read(4096)
    except Exception:
        return False


def main(argv):
    port, open_browser, target, restarted = 7878, True, None, False
    it = iter(argv)
    for a in it:
        if a == "--port":
            port = int(next(it))
        elif a == "--no-open":
            open_browser = False
        elif a in ("-h", "--help"):
            sys.exit(print(__doc__))
        elif a == "--restarted":
            restarted = True
        elif a == "--version":
            sys.exit(print(VERSION))
        else:
            target = Path(a).expanduser().resolve()
    App.dir = target or espanso_match_dir()
    App.port = port
    # On Windows SO_REUSEADDR would let two copies share the port, so only use it elsewhere.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    url = f"http://127.0.0.1:{port}/"
    for attempt in range(40):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), App)
            break
        except OSError:
            if restarted:  # the old copy is still shutting down
                time.sleep(0.25)
                continue
            if already_running(url):  # double-clicked again: just show the open one
                open_ui(url)
                return
            sys.exit(f"Port {port} is in use. Try: pm.py --port 7900")
    else:
        sys.exit(f"Port {port} is still in use.")
    print(f"Prompt Manager {VERSION} → {url}\nfolder {App.dir}\nCtrl+C to quit")
    if settings()["auto_update"] and not os.environ.get("PM_NO_UPDATE"):
        threading.Thread(target=bg_check, args=(True,), daemon=True).start()  # never delays startup
    if FROZEN:  # tidy up after an .exe update
        try:
            (HERE / (Path(sys.executable).stem + ".old.exe")).unlink()
        except OSError:
            pass
    if open_browser:
        open_ui(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main(sys.argv[1:])
