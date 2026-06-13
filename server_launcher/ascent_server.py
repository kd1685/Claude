"""
Ascent Terminal — local server launcher (replaces run_local.bat).

Owner tool: starts the FastAPI server on your machine and opens the
browser. No batch files, so nothing for antivirus to complain about.

Usage (from the AscentTerminal root folder):

    python server_launcher/ascent_server.py            # start
    python server_launcher/ascent_server.py --setup    # install/upgrade deps first
    python server_launcher/ascent_server.py --port 8080

Can also be built into AscentServer.exe with build_server.py, but for
a tool only you run, plain `python ascent_server.py` is simplest and
never triggers AV heuristics at all.
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PLATFORM = os.path.join(ROOT, "platform")


def find_platform() -> str:
    """Locate the platform/ folder whether we run from source or a frozen exe."""
    candidates = [
        PLATFORM,
        os.path.join(os.getcwd(), "platform"),
        os.getcwd() if os.path.exists(os.path.join(os.getcwd(), "app.py")) else None,
    ]
    for c in candidates:
        if c and os.path.exists(os.path.join(c, "app.py")):
            return c
    sys.exit(
        "Could not find platform/app.py.\n"
        "Run this from inside your AscentTerminal folder."
    )


def setup(platform_dir: str) -> None:
    req = os.path.join(platform_dir, "requirements.txt")
    print("Installing / upgrading dependencies...")
    cmds = []
    if os.path.exists(req):
        cmds.append([sys.executable, "-m", "pip", "install", "-r", req])
    cmds.append([sys.executable, "-m", "pip", "install", "--upgrade", "ccxt", "yfinance"])
    for cmd in cmds:
        if subprocess.run(cmd).returncode != 0:
            sys.exit("pip failed — fix the error above and retry.")
    print("Dependencies OK.\n")


def open_browser_later(url: str, delay: float = 2.5) -> None:
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Ascent Terminal locally.")
    ap.add_argument("--setup", action="store_true", help="install/upgrade dependencies first")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    platform_dir = find_platform()
    os.chdir(platform_dir)

    if args.setup:
        setup(platform_dir)

    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("uvicorn is not installed — running setup first.\n")
        setup(platform_dir)
        import uvicorn  # noqa: F401

    url = f"http://localhost:{args.port}"
    print("=" * 56)
    print("  ASCENT TERMINAL — local server")
    print(f"  {url}   (Ctrl+C to stop)")
    print("=" * 56)

    if not args.no_browser:
        open_browser_later(url)

    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
