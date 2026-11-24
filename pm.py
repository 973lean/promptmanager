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

VERSION = "1.4.4"
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


# ---------------- log + errors (there's no console, so never fail silently) ----------------
def log(msg: str):
    try:
        with (HERE / "pm.log").open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def fatal(msg: str):
    log("FATAL " + msg)
    if os.name == "nt" and (FROZEN or sys.stdout is None):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "Prompt Manager", 0x10)
        except Exception:
            pass
    sys.exit(msg)


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
    if len(data) < 1_000_000 or (os.name == "nt" and data[:2] != b"MZ"):
        raise RuntimeError("the downloaded app looks broken; keeping the current one")
    new, old = exe.with_name(exe.stem + ".new.exe"), exe.with_name(exe.stem + ".old.exe")
    new.write_bytes(data)
    if os.name != "nt":
        os.chmod(new, 0o755)
    try:
        if old.exists():
            old.unlink()
    except OSError:  # an older leftover is still locked; use a fresh name
        old = exe.with_name(f"{exe.stem}.old{int(time.time())}.exe")
    os.replace(exe, old)
    try:
        os.replace(new, exe)
    except Exception:
        os.replace(old, exe)  # never leave you without an app
        raise
    App.swapped = old


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
    UPDATE.update(status="downloading" if auto_apply and UPDATE["status"] in ("available", "downloading") else "checking", error=None)
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
        log(f"update failed: {e}")
        UPDATE.update(status="error", error=str(e))


def restart():
    """Start the new copy, hand it the port, and only exit once it's answering.
    If it doesn't come up (antivirus, broken download), take the port back and keep running."""
    args = [a for a in sys.argv[1:] if a not in ("--no-open", "--restarted")] + ["--no-open", "--restarted"]
    cmd = [sys.executable, *args] if FROZEN else [sys.executable, str(HERE / "pm.py"), *args]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # the new .exe must unpack itself, not reuse our temp folder
    url = f"http://127.0.0.1:{App.port}/"
    try:
        proc = subprocess.Popen(cmd, env=env, creationflags=0x08000000 if os.name == "nt" else 0, close_fds=True)
    except Exception as e:
        return restart_failed(f"couldn't start the new version: {e}")
    App.restarting = True
    App.srv.shutdown()
    App.srv.server_close()
    for _ in range(60):  # up to ~15s
        time.sleep(0.25)
        if proc.poll() is not None:
            break
        if already_running(url):
            log("restarted into the new version")
            os._exit(0)
    try:
        proc.kill()
    except Exception:
        pass
    restart_failed("the new version didn't start (often antivirus); still running the previous one")


def restart_failed(why: str):
    log("restart failed: " + why)
    old = getattr(App, "swapped", None)
    if FROZEN and old and old.exists():  # put the working .exe back
        exe = Path(sys.executable)
        try:
            os.replace(exe, exe.with_name(exe.stem + ".bad.exe"))
            os.replace(old, exe)
            App.swapped = None
        except OSError as e:
            log(f"rollback failed: {e}")
    UPDATE.update(status="error", error=why)
    if getattr(App, "restarting", False):
        App.srv = bind(App.port, retries=40)
        App.restarting = False
        App.resume.set()


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


# ---------------- shortcuts (Windows) ----------------
def make_shortcuts() -> str:
    """Desktop + Start menu shortcuts that start the app itself (a Chrome shortcut only opens the page)."""
    target, args = (sys.executable, "") if FROZEN else (str(Path(sys.executable).with_name("pythonw.exe")), f'"{HERE / "pm.py"}"')
    ps = (
        "$w = New-Object -ComObject WScript.Shell; "
        "foreach ($d in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "$s = $w.CreateShortcut((Join-Path $d 'Prompt Manager.lnk')); "
        f"$s.TargetPath = '{target}'; $s.Arguments = '{args}'; $s.WorkingDirectory = '{HERE}'; "
        f"$s.IconLocation = '{target},0'; $s.Description = 'Prompt Manager'; $s.Save() }}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, timeout=20, creationflags=0x08000000)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300] or "PowerShell failed")
    return "Added Prompt Manager to your desktop and Start menu."


SW_JS = """// Shows a friendly page instead of Chrome's error when Prompt Manager isn't running.
const OFF = "/offline.html";
self.addEventListener("install", e => { e.waitUntil(caches.open("pm-v1").then(c => c.add(OFF))); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.mode === "navigate") e.respondWith(fetch(e.request).catch(() => caches.match(OFF)));
});
"""

OFFLINE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prompt Manager</title><style>
:root{--bg:#f4f5f7;--ink:#1b1d21;--muted:#6b7079;--accent:#2f6bff;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#111215;--ink:#e7e9ee;--muted:#9097a3;--accent:#5b8cff;color-scheme:dark}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:15px/1.6 ui-sans-serif,system-ui,"Segoe UI",sans-serif;padding:24px;box-sizing:border-box}
main{max-width:420px;text-align:center}h1{font-size:19px;margin:0 0 8px}p{color:var(--muted);margin:0 0 10px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--accent);margin-right:8px;animation:p 1.4s infinite}
@keyframes p{50%{opacity:.25}}</style></head><body><main>
<h1>Prompt Manager isn't running</h1>
<p>Open <b>PromptManager.exe</b> (or the Prompt Manager shortcut on your desktop). This page opens by itself as soon as it's running.</p>
<p><span class="dot"></span>Waiting…</p>
<p style="font-size:13px">Tip: Settings → <b>Start with Windows</b> keeps it ready in the background.</p>
</main><script>
setInterval(() => fetch("/", {cache: "no-store"}).then(r => r.ok && location.reload()).catch(() => {}), 1500);
</script></body></html>"""


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
    srv = None
    swapped = None
    restarting = False
    resume = threading.Event()
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
        if self.path == "/sw.js":
            return self.send(200, SW_JS, "text/javascript")
        if self.path == "/offline.html":
            return self.send(200, OFFLINE_HTML, "text/html")
        if self.path == "/icon.png":
            return self.send(200, (RES / "icon.png").read_bytes(), "image/png")
        if self.path == "/manifest.webmanifest":  # lets Chrome/Edge "Install" it as an app
            return self.send(200, json.dumps({
                "name": "Prompt Manager", "short_name": "Prompts", "start_url": "/", "display": "standalone",
                "background_color": "#f4f5f7", "theme_color": "#2f6bff",
                "icons": [{"src": "/icon.png", "sizes": "512x512", "type": "image/png"}],
            }), "application/manifest+json")
        if self.path == "/api/state":
            return self.send(200, self.state()) if self.authed() else self.send(403, {"error": "stale page"})
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
        if p == "/api/update/apply":  # runs in the background; the page polls for progress
            if UPDATE["status"] not in ("checking", "downloading"):
                UPDATE["status"] = "downloading" if UPDATE["status"] == "available" else "checking"
                threading.Thread(target=bg_check, args=(True,), daemon=True).start()
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
        if p == "/api/shortcut":
            return self.send(200, {"message": make_shortcuts()})
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
    port, open_browser, target, restarted, explicit_port = 7878, True, None, False, False
    it = iter(argv)
    for a in it:
        if a == "--port":
            port, explicit_port = int(next(it)), True
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
    # On Windows SO_REUSEADDR would let two copies share the port, so only use it elsewhere.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    srv = None
    try:
        srv = bind(port, retries=40 if restarted else 1)
    except OSError:
        if already_running(f"http://127.0.0.1:{port}/"):  # double-clicked again: just show the open one
            return open_ui(f"http://127.0.0.1:{port}/")
        if not explicit_port:  # something stuck holds the port: use the next free one
            for p in range(port + 1, port + 20):
                try:
                    srv = bind(p, retries=1)
                    log(f"port {port} was busy, using {p}")
                    port = p
                    break
                except OSError:
                    continue
        if srv is None:
            fatal(f"Port {port} is in use by another program, so Prompt Manager can't start.\n\nRestart your computer, or run it with --port 7900.")
    App.port, App.srv = port, srv
    url = f"http://127.0.0.1:{port}/"
    log(f"started {VERSION} on {url} ({'exe' if FROZEN else 'script'})")
    print(f"Prompt Manager {VERSION} → {url}\nfolder {App.dir}\nCtrl+C to quit")
    if FROZEN:  # tidy up after an .exe update
        for f in HERE.glob(Path(sys.executable).stem + ".old*.exe"):
            try:
                f.unlink()
            except OSError:
                pass
    if settings()["auto_update"] and not os.environ.get("PM_NO_UPDATE"):
        threading.Thread(target=bg_check, args=(True,), daemon=True).start()  # never delays startup
    if open_browser:
        open_ui(url)
    try:
        while True:
            App.srv.serve_forever()
            if not App.restarting:
                break
            App.resume.wait()  # a restart is handing over; resume here if it fails
            App.resume.clear()
    except KeyboardInterrupt:
        pass


def bind(port: int, retries: int = 1):
    for i in range(retries):
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), App)
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(0.25)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except SystemExit:
        raise
    except Exception:
        import traceback
        fatal("Prompt Manager hit an error and stopped:\n\n" + traceback.format_exc()[-1500:])
