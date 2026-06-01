"""
MLB Analytics Platform — One-file setup & launcher
Run this from the mlb-analytics/ folder:  python3 start.py
"""

import subprocess
import sys
import os
import shutil
import platform
from pathlib import Path

ROOT = Path(__file__).parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
ENV_FILE = BACKEND / ".env"
ENV_EXAMPLE = BACKEND / ".env.example"

# ── extend PATH to cover all common Mac install locations ─────────────────────
EXTRA_PATHS = [
    "/usr/local/bin",
    "/opt/homebrew/bin",          # Apple Silicon Homebrew
    "/opt/homebrew/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/Applications/Docker.app/Contents/Resources/bin",
    str(Path.home() / ".docker/bin"),
    str(Path.home() / ".nvm/versions/node/v24.16.0/bin"),
    str(Path.home() / ".nvm/versions/node/v22.0.0/bin"),
]
os.environ["PATH"] = ":".join(EXTRA_PATHS) + ":" + os.environ.get("PATH", "")


def find_bin(name: str) -> str | None:
    """Like shutil.which but also checks our extra paths explicitly."""
    found = shutil.which(name)
    if found:
        return found
    for p in EXTRA_PATHS:
        candidate = Path(p) / name
        if candidate.exists():
            return str(candidate)
    return None

# ── colour helpers ────────────────────────────────────────────────────────────

def green(s):  return f"\033[92m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"

def ok(msg):   print(f"  {green('✓')}  {msg}")
def fail(msg): print(f"  {red('✗')}  {msg}")
def info(msg): print(f"  {yellow('→')}  {msg}")
def header(msg):
    print(f"\n{'─'*55}")
    print(f"  {bold(msg)}")
    print(f"{'─'*55}")


# ── prerequisite checks ───────────────────────────────────────────────────────

def check_python():
    v = sys.version_info
    if v >= (3, 11):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
        return True
    fail(f"Python 3.11+ required — you have {v.major}.{v.minor}")
    print(dim("    Download: https://python.org/downloads"))
    return False


def check_node():
    node = find_bin("node")
    if not node:
        fail("Node.js not found")
        print(dim("    Download: https://nodejs.org  (LTS version)"))
        return False
    result = subprocess.run([node, "--version"], capture_output=True, text=True)
    ver = result.stdout.strip()
    try:
        major = int(ver.lstrip("v").split(".")[0])
    except ValueError:
        major = 0
    if major >= 18:
        ok(f"Node.js {ver}  ({node})")
        return True
    fail(f"Node.js 18+ required — you have {ver}")
    print(dim("    Download: https://nodejs.org  (LTS version)"))
    return False


def check_npm():
    npm = find_bin("npm")
    if npm:
        result = subprocess.run([npm, "--version"], capture_output=True, text=True)
        ok(f"npm {result.stdout.strip()}  ({npm})")
        return True
    fail("npm not found (usually installed with Node.js)")
    return False


def check_docker():
    docker = find_bin("docker")
    if not docker:
        fail("Docker not found")
        print(dim("    Download: https://docker.com/products/docker-desktop"))
        return False
    result = subprocess.run([docker, "info"], capture_output=True, text=True)
    if result.returncode != 0:
        fail("Docker is installed but not running — open Docker Desktop first")
        return False
    ok(f"Docker (running)  ({docker})")
    return True


def check_git():
    git = find_bin("git")
    if git:
        ok("git")
        return True
    info("git not found (optional)")
    return True   # not blocking


# ── .env setup ────────────────────────────────────────────────────────────────

def setup_env():
    header("Step 2 — API Keys (.env)")

    if not ENV_FILE.exists():
        import shutil as sh
        sh.copy(ENV_EXAMPLE, ENV_FILE)
        info("Created backend/.env from template")

    env_vars = {}
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env_vars[k.strip()] = v.strip()

    sportradar_key = env_vars.get("SPORTRADAR_API_KEY", "")
    anthropic_key  = env_vars.get("ANTHROPIC_API_KEY", "")

    missing = []

    if not sportradar_key or sportradar_key == "your_sportradar_api_key_here":
        fail("SPORTRADAR_API_KEY not set")
        print(dim("    Sign up at: https://developer.sportradar.com"))
        print(dim("    Choose the MLB Trial or paid plan → copy your API key"))
        missing.append("SPORTRADAR_API_KEY")
    else:
        ok(f"SPORTRADAR_API_KEY  {'*' * 20}{sportradar_key[-4:]}")

    if not anthropic_key or anthropic_key == "your_anthropic_api_key_here":
        fail("ANTHROPIC_API_KEY not set")
        print(dim("    Sign up at: https://console.anthropic.com"))
        print(dim("    Create an API key → copy it"))
        missing.append("ANTHROPIC_API_KEY")
    else:
        ok(f"ANTHROPIC_API_KEY   {'*' * 20}{anthropic_key[-4:]}")

    if missing:
        print()
        print(f"  {yellow('Open backend/.env in any text editor and paste your keys:')}  ")
        print(f"  {dim(str(ENV_FILE))}")
        print()
        fix = input("  Have you added the keys? Press Enter to re-check, or type 'skip' to continue anyway: ").strip()
        if fix.lower() != "skip":
            return setup_env()   # re-check

    return len(missing) == 0


# ── install dependencies ──────────────────────────────────────────────────────

def install_python_deps():
    header("Step 3 — Python Dependencies")
    venv = BACKEND / ".venv"
    pip  = venv / ("Scripts" if platform.system() == "Windows" else "bin") / "pip"

    if not venv.exists():
        info("Creating Python virtual environment…")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        ok("Virtual environment created")
    else:
        ok("Virtual environment already exists")

    info("Installing Python packages (this takes ~60 seconds the first time)…")
    subprocess.run(
        [str(pip), "install", "-q", "-r", str(BACKEND / "requirements.txt")],
        check=True,
    )
    ok("All Python packages installed")
    return str(venv / ("Scripts" if platform.system() == "Windows" else "bin") / "python")


def install_node_deps():
    header("Step 4 — Node.js Dependencies")
    nm = FRONTEND / "node_modules"
    if nm.exists():
        ok("node_modules already installed")
        return
    info("Installing frontend packages (this takes ~30 seconds)…")
    npm = find_bin("npm")
    subprocess.run([npm, "install", "--prefix", str(FRONTEND), "--silent"], check=True)
    ok("All Node packages installed")


# ── databases ─────────────────────────────────────────────────────────────────

def start_databases():
    header("Step 5 — Databases (Postgres + Redis)")
    result = subprocess.run(
        ["docker", "compose", "up", "postgres", "redis", "-d", "--wait"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        ok("PostgreSQL running on port 5432")
        ok("Redis running on port 6379")
        return True
    # Fallback for older docker-compose
    result2 = subprocess.run(
        ["docker-compose", "up", "postgres", "redis", "-d"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if result2.returncode == 0:
        ok("PostgreSQL + Redis started")
        return True
    fail("Could not start databases")
    print(red(result.stderr[-500:] if result.stderr else ""))
    print(dim("  Make sure Docker Desktop is open and try again."))
    return False


# ── data ingestion ────────────────────────────────────────────────────────────

def run_ingestion(python_bin: str):
    header("Step 6 — Load Data")

    print()
    print("  What data do you want to load right now?")
    print()
    print("  1. Quick test — one MLB team + its minor league affiliates  (~3 min)")
    print("  2. Full MLB rosters + stats (all 30 teams)                  (~20 min)")
    print("  3. Full MLB + all minor league levels                       (~75 min)")
    print("  4. Skip for now — I'll run ingest manually later")
    print()
    choice = input("  Enter 1 / 2 / 3 / 4: ").strip()

    if choice == "4":
        info("Skipping. Run ingest manually later:")
        print(dim("    cd backend && source .venv/bin/activate"))
        print(dim("    python -m scripts.ingest --season 2024"))
        print(dim("    python -m scripts.ingest_minors --season 2024"))
        return

    team = None
    if choice == "1":
        team = input("  Enter MLB team abbreviation (e.g. NYY, LAD, BOS): ").strip().upper()
        if not team:
            team = "NYY"

    # MLB ingest
    mlb_cmd = [python_bin, "-m", "scripts.ingest", "--season", "2024"]
    if choice == "1" and team:
        mlb_cmd += ["--team", team]

    info(f"Running MLB ingest{' for ' + team if team else ''}…")
    subprocess.run(mlb_cmd, cwd=str(BACKEND))

    # MiLB ingest
    if choice in ("1", "3"):
        mil_cmd = [python_bin, "-m", "scripts.ingest_minors", "--season", "2024"]
        if choice == "1" and team:
            mil_cmd += ["--affiliate", team]
        info(f"Running MiLB ingest{' for ' + team + ' affiliates' if team else ''}…")
        subprocess.run(mil_cmd, cwd=str(BACKEND))

    ok("Data loaded!")


# ── print run instructions ────────────────────────────────────────────────────

def print_launch_instructions():
    header("You're ready!")
    print()
    print(bold("  Open TWO terminal tabs/windows:\n"))

    print(bold("  Tab 1 — Backend API"))
    print(dim("  ─────────────────────────────────────"))
    if platform.system() == "Windows":
        print(f"    cd {BACKEND}")
        print(f"    .venv\\Scripts\\activate")
    else:
        print(f"    cd {BACKEND}")
        print(f"    source .venv/bin/activate")
    print(f"    uvicorn app.main:app --reload")
    print()

    print(bold("  Tab 2 — Frontend"))
    print(dim("  ─────────────────────────────────────"))
    print(f"    cd {FRONTEND}")
    print(f"    npm run dev")
    print()

    print(bold("  Then open your browser:"))
    print(f"    {green('http://localhost:3000')}          ← the app")
    print(f"    {green('http://localhost:8000/docs')}     ← API docs")
    print()
    print(bold("  To load more data later:"))
    print(dim("    python -m scripts.ingest --season 2024"))
    print(dim("    python -m scripts.ingest_minors --season 2024"))
    print(dim("    python -m scripts.ingest_minors --affiliate LAD --season 2024"))
    print()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print(bold("  ⚾  MLB Analytics Platform — Setup"))
    print(dim("  Run from the mlb-analytics/ folder\n"))

    # ── Step 1: prerequisites
    header("Step 1 — Prerequisites")
    py_ok     = check_python()
    node_ok   = check_node()
    npm_ok    = check_npm()
    docker_ok = check_docker()
    check_git()

    if not py_ok:
        print(red("\n  Python 3.11+ is required. Install it and re-run this script."))
        sys.exit(1)

    if not node_ok or not npm_ok:
        print(red("\n  Node.js 18+ is required. Install it and re-run this script."))
        print(dim("  Download: https://nodejs.org"))
        sys.exit(1)

    if not docker_ok:
        print(yellow("\n  Docker is required for the database."))
        print(dim("  Download Docker Desktop: https://docker.com/products/docker-desktop"))
        print(dim("  Open Docker Desktop, wait for it to start, then re-run this script."))
        sys.exit(1)

    # ── Step 2: API keys
    keys_ready = setup_env()
    if not keys_ready:
        info("Continuing with missing keys — AI scouting reports and Sportradar data won't work until keys are added.")

    # ── Steps 3 & 4: install deps
    python_bin = install_python_deps()
    install_node_deps()

    # ── Step 5: databases
    db_ok = start_databases()
    if not db_ok:
        print(yellow("\n  Skipping data load — fix Docker and re-run."))
        print_launch_instructions()
        sys.exit(1)

    # ── Step 6: ingest
    run_ingestion(python_bin)

    # ── Done
    print_launch_instructions()


if __name__ == "__main__":
    main()

