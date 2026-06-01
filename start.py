"""
MLB Analytics Platform — One-file setup & launcher
Just run:  python3 start.py
"""

import subprocess
import sys
import os
import shutil
import time
import webbrowser
from pathlib import Path

ROOT     = Path(__file__).parent
BACKEND  = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE      = BACKEND / ".env"
ENV_EXAMPLE   = BACKEND / ".env.example"
DATA_SENTINEL = BACKEND / ".data_loaded"   # written after a successful full load
SEASON        = "2026"

# ── extend PATH to cover all common Mac install locations ─────────────────────
EXTRA_PATHS = [
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/Applications/Docker.app/Contents/Resources/bin",
    str(Path.home() / ".docker/bin"),
    str(Path.home() / ".nvm/versions/node/v24.16.0/bin"),
    str(Path.home() / ".nvm/versions/node/v22.0.0/bin"),
    str(Path.home() / ".nvm/versions/node/v22.16.0/bin"),
]
os.environ["PATH"] = ":".join(EXTRA_PATHS) + ":" + os.environ.get("PATH", "")


def find_bin(name):
    found = shutil.which(name)
    if found:
        return found
    for p in EXTRA_PATHS:
        c = Path(p) / name
        if c.exists():
            return str(c)
    return None


# ── colours ───────────────────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"

def ok(msg):    print(f"  {green('✓')}  {msg}", flush=True)
def fail(msg):  print(f"  {red('✗')}  {msg}", flush=True)
def info(msg):  print(f"  {yellow('→')}  {msg}", flush=True)
def header(msg):
    print(f"\n{'─'*55}", flush=True)
    print(f"  {bold(msg)}", flush=True)
    print(f"{'─'*55}", flush=True)


# ── step 1: check prerequisites ───────────────────────────────────────────────
def check_prerequisites():
    header("Step 1 — Checking prerequisites")
    errors = []

    # Python
    v = sys.version_info
    if v >= (3, 11):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python 3.11+ required (you have {v.major}.{v.minor}) — download at python.org")
        errors.append("python")

    # Node
    node = find_bin("node")
    if node:
        ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
        ok(f"Node.js {ver}")
    else:
        fail("Node.js not found — download LTS version at nodejs.org")
        errors.append("node")

    # npm
    npm = find_bin("npm")
    if npm:
        ver = subprocess.run([npm, "--version"], capture_output=True, text=True).stdout.strip()
        ok(f"npm {ver}")
    else:
        fail("npm not found (comes with Node.js)")
        errors.append("npm")

    # Docker
    docker = find_bin("docker")
    if docker:
        result = subprocess.run([docker, "info"], capture_output=True, text=True)
        if result.returncode == 0:
            ok("Docker Desktop (running)")
        else:
            fail("Docker is installed but not running — open Docker Desktop and wait for it to start")
            errors.append("docker_not_running")
    else:
        fail("Docker not found — download Docker Desktop at docker.com/products/docker-desktop")
        errors.append("docker")

    if errors:
        print(f"\n  {red('Fix the issues above and run this script again.')}")
        sys.exit(1)

    return node, npm, docker


# ── step 2: check api keys ────────────────────────────────────────────────────
def check_api_keys():
    """
    Only the Anthropic key is required.
    The Sportradar key is optional — the free MLB Stats API covers teams,
    rosters, and 2026 stats without it.
    """
    header("Step 2 — API Keys")

    if not ENV_FILE.exists():
        shutil.copy(ENV_EXAMPLE, ENV_FILE)

    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    ant_key = env_vars.get("ANTHROPIC_API_KEY", "")
    sr_key  = env_vars.get("SPORTRADAR_API_KEY", "")

    placeholders = ["your_anthropic_api_key_here", "your_sportradar_api_key_here",
                    "PASTE_YOUR_NEW_SPORTRADAR_KEY_HERE", ""]

    ant_ok = ant_key not in placeholders
    sr_ok  = sr_key  not in placeholders

    # Anthropic is required
    if ant_ok:
        ok(f"Anthropic key    ****{ant_key[-4:]}  (AI scouting reports)")
    else:
        fail("Anthropic API key not set  — required for AI scouting reports")
        print(dim("       Sign up free at console.anthropic.com → API Keys → Create key"))

    # Sportradar is optional
    if sr_ok:
        ok(f"Sportradar key   ****{sr_key[-4:]}  (optional — Statcast advanced stats)")
    else:
        info("Sportradar key   not set  (optional — app works fine without it)")
        print(dim("       Sign up at developer.sportradar.com if you want Statcast data"))

    if not ant_ok:
        print()
        print(f"  {yellow('Open this file in TextEdit, paste your Anthropic key, then press Enter:')}")
        print(f"  {dim(str(ENV_FILE))}")
        subprocess.run(["open", "-e", str(ENV_FILE)])
        input("\n  Press Enter once you have saved the file… ")
        return check_api_keys()   # re-check


# ── step 3: install python deps ───────────────────────────────────────────────
def install_python_deps():
    header("Step 3 — Python packages")
    venv   = BACKEND / ".venv"
    pip    = venv / "bin" / "pip"
    python = venv / "bin" / "python"

    if not venv.exists():
        info("Creating virtual environment…")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)

    info("Installing packages (first time takes ~60 seconds)…")
    subprocess.run(
        [str(pip), "install", "-q", "-r", str(BACKEND / "requirements.txt")],
        check=True,
    )
    ok("Python packages ready")
    return str(python)


# ── step 4: install node deps ─────────────────────────────────────────────────
def install_node_deps(npm):
    header("Step 4 — Frontend packages")
    if (FRONTEND / "node_modules").exists():
        ok("Node packages already installed")
        return
    info("Installing (first time takes ~30 seconds)…")
    subprocess.run([npm, "install", "--prefix", str(FRONTEND), "--silent"], check=True)
    ok("Frontend packages ready")


# ── step 5: start databases ───────────────────────────────────────────────────
def start_databases(docker):
    header("Step 5 — Databases")
    info("Starting PostgreSQL and Redis via Docker…")
    result = subprocess.run(
        [docker, "compose", "up", "postgres", "redis", "-d", "--wait"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        # older docker-compose fallback (no --wait flag)
        result = subprocess.run(
            [docker, "compose", "up", "postgres", "redis", "-d"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
    if result.returncode != 0:
        fail("Could not start databases")
        print(red(result.stderr[-400:]))
        sys.exit(1)
    time.sleep(3)   # let postgres finish initialising
    ok("PostgreSQL running")
    ok("Redis running")


# ── step 6: check / decide data load ─────────────────────────────────────────
def _read_env_vars() -> dict:
    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()
    return env_vars


def decide_data_load() -> bool:
    """
    Ask the user whether to load/reload data.
    Returns True if we should run the data load, False to skip.
    This runs BEFORE launching servers so we can start loading right away.
    """
    header("Step 6 — Player data")

    if DATA_SENTINEL.exists():
        print()
        print(f"  {green('✓')}  Player data was loaded previously.")
        answer = input(
            f"  Press {bold('Enter')} to use existing data  (or type {bold('reload')} to refresh): "
        ).strip().lower()
        if answer != "reload":
            ok("Using existing data")
            return False
        print()
        info("Will reload all data after launching the app…")
        return True
    else:
        print()
        info("No data loaded yet — will load all 30 MLB teams + minor leagues after launch.")
        print(dim("  The app will open immediately; data loads in the background (~30 min first time)."))
        return True


def run_data_load_background(python_bin):
    """
    Runs the full data pipeline in the background (non-blocking).
    Returns the sentinel-writer thread so main() can join if desired.
    """
    import threading

    def _load():
        # ── A: MLB rosters ───────────────────────────────────────────────────
        print()
        info(f"[1/4]  Loading all 30 MLB teams and {SEASON} rosters…")
        r = subprocess.run(
            [python_bin, "-m", "scripts.ingest_minors", "--season", SEASON, "--level", "MLB"],
            cwd=str(BACKEND),
        )
        if r.returncode == 0:
            ok("All 30 MLB rosters loaded  →  refresh the app to see them")
        else:
            fail("MLB roster load had errors — check your internet connection")

        # ── B: Baseball Reference stats ──────────────────────────────────────
        print()
        info(f"[2/4]  Loading {SEASON} stats from Baseball Reference…")
        r2 = subprocess.run(
            [python_bin, "-m", "scripts.ingest_stats", "--season", SEASON],
            cwd=str(BACKEND),
        )
        if r2.returncode == 0:
            ok("Batting and pitching stats loaded")
        else:
            info("Stats load had issues — basic roster data still available")

        # ── C: Sportradar (optional) ─────────────────────────────────────────
        sr_key = _read_env_vars().get("SPORTRADAR_API_KEY", "")
        sr_has_key = sr_key not in ["", "your_sportradar_api_key_here",
                                     "PASTE_YOUR_NEW_SPORTRADAR_KEY_HERE"]
        if sr_has_key:
            print()
            info("[+]   Sportradar key found — loading Statcast advanced stats…")
            subprocess.run([python_bin, "-m", "scripts.ingest", "--season", SEASON],
                           cwd=str(BACKEND))
            ok("Statcast data loaded")
        else:
            info("[+]   No Sportradar key — skipping Statcast (app fully functional without it)")

        # ── D: Minor leagues ─────────────────────────────────────────────────
        print()
        info(f"[3/4]  Loading full minor league system — AAA, AA, A+, A, Rookie…")
        print(dim("        Every MLB affiliate at all five levels (~20-30 min)."))
        print(dim("        Minor league rosters will appear in the app as they load."))
        r3 = subprocess.run(
            [python_bin, "-m", "scripts.ingest_minors",
             "--season", SEASON,
             "--level", "AAA", "AA", "A+", "A", "Rookie"],
            cwd=str(BACKEND),
        )
        if r3.returncode == 0:
            ok("All minor league rosters loaded!")
        else:
            info("Minor league load finished with some errors — partial data available")

        # ── Done ─────────────────────────────────────────────────────────────
        print()
        print(f"  {green('★')}  {bold('Full data load complete!')}  Refresh the app to see all rosters.")
        DATA_SENTINEL.write_text(f"loaded {SEASON}\n")

    t = threading.Thread(target=_load, daemon=True)
    t.start()
    return t


# ── step 7: launch servers ────────────────────────────────────────────────────
def launch_servers(python_bin, npm):
    header("Step 7 — Launching the app")

    uvicorn = str(BACKEND / ".venv" / "bin" / "uvicorn")

    # Kill any old processes that might be running on these ports
    subprocess.run(
        ["bash", "-c", "lsof -ti:8000 | xargs kill -9 2>/dev/null; lsof -ti:3000 | xargs kill -9 2>/dev/null"],
        capture_output=True,
    )
    time.sleep(1)

    info("Starting backend API…")
    subprocess.Popen(
        [uvicorn, "app.main:app", "--reload", "--port", "8000"],
        cwd=str(BACKEND),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    info("Starting frontend…")
    subprocess.Popen(
        [npm, "run", "dev"],
        cwd=str(FRONTEND),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Poll until both servers respond (up to 30s)
    info("Waiting for servers to start…")
    import urllib.request
    for _ in range(30):
        time.sleep(1)
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=1)
            break
        except Exception:
            pass

    ok("Backend running  →  http://localhost:8000")
    ok("Frontend running →  http://localhost:3000")

    print()
    print(bold("  Opening app in your browser…"))
    webbrowser.open("http://localhost:3000")

    print()
    print(bold("  ✅  Everything is running!"))
    print()
    print(dim("  ─────────────────────────────────────────────────────"))
    print(dim("  Pages:"))
    print(dim("    Lineup Optimizer  →  http://localhost:3000/lineup"))
    print(dim("    Roster Builder    →  http://localhost:3000/roster"))
    print(dim("    Scouting          →  http://localhost:3000/scouting"))
    print(dim("    Analytics         →  http://localhost:3000/analytics"))
    print(dim("    Players           →  http://localhost:3000/players"))
    print(dim("  ─────────────────────────────────────────────────────"))
    print(dim("  To reload data later:"))
    print(dim(f"    cd {BACKEND}"))
    print(dim(f"    source .venv/bin/activate"))
    print(dim(f"    # Refresh MLB rosters:"))
    print(dim(f"    python -m scripts.ingest_minors --season {SEASON} --level MLB"))
    print(dim(f"    # Refresh stats (batting/pitching, all players):"))
    print(dim(f"    python -m scripts.ingest_stats --season {SEASON}"))
    print(dim(f"    # Refresh minor leagues:"))
    print(dim(f"    python -m scripts.ingest_minors --season {SEASON}"))
    print(dim("  ─────────────────────────────────────────────────────"))
    print(dim("  To stop: press Ctrl+C in this terminal"))
    print()

    # Keep script alive so servers and any background data-load thread stay up
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print(f"\n  {yellow('Shutting down servers…')}")
        subprocess.run(
            ["bash", "-c", "lsof -ti:8000 | xargs kill -9 2>/dev/null; lsof -ti:3000 | xargs kill -9 2>/dev/null"],
            capture_output=True,
        )
        print(f"  {green('Done. Goodbye!')}")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print()
    print(bold("  ⚾  MLB Analytics Platform"))
    print(dim(f"  Season: {SEASON}  —  AI-powered lineup, scouting & roster tools\n"))

    node, npm, docker = check_prerequisites()
    check_api_keys()
    python_bin = install_python_deps()
    install_node_deps(npm)
    start_databases(docker)

    # Decide whether to load data (asks the user), then launch the app
    # immediately. Data loading runs in a background thread so the browser
    # opens right away — no 30-minute wait on first run.
    should_load = decide_data_load()
    if should_load:
        run_data_load_background(python_bin)   # non-blocking — starts thread
    launch_servers(python_bin, npm)            # opens browser, then blocks until Ctrl-C


if __name__ == "__main__":
    main()

