"""ascent_desktop.py — Desktop client for Ascent Terminal.

Opens a native window (via pywebview) pointed at the configured Ascent
Terminal server URL.  The URL and API key can be set via environment
variables or a local config file.

Usage:
    python ascent_desktop.py [--url https://ascentterminal.com] [--api-key AT-xxx]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import webview  # type: ignore
except ImportError:
    print("pywebview is required: pip install pywebview", file=sys.stderr)
    sys.exit(1)

CONFIG_FILE = Path.home() / ".ascent" / "config.json"

DEFAULT_URL = "https://ascentterminal.com"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ascent Terminal Desktop")
    parser.add_argument("--url", default=None, help="Server URL")
    parser.add_argument("--api-key", default=None, help="API key")
    args = parser.parse_args()

    cfg = _load_config()

    url = (
        args.url
        or os.getenv("ASCENT_URL")
        or cfg.get("url")
        or DEFAULT_URL
    )
    api_key = args.api_key or os.getenv("ASCENT_API_KEY") or cfg.get("api_key", "")

    # Persist for next launch
    cfg.update({"url": url})
    if api_key:
        cfg["api_key"] = api_key
    _save_config(cfg)

    # Append API key as query param so the web app can auto-authenticate
    if api_key and "?" not in url:
        url = f"{url}?api_key={api_key}"

    webview.create_window(
        title="Ascent Terminal",
        url=url,
        width=1400,
        height=900,
        resizable=True,
        min_size=(800, 600),
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
