"""
Ascent Terminal — desktop client.

A lightweight native window wrapping the hosted terminal at
https://ascentterminal.com (override with the ASCENT_URL env var,
e.g. http://localhost:8000 for local development).

Build to .exe with:  python build_desktop.py   (see that file)
Requires:            pip install pywebview
"""
import os
import sys

APP_NAME = "Ascent Terminal"
DEFAULT_URL = "https://ascentterminal.com/app"
MIN_W, MIN_H = 1100, 720


def fatal(msg: str) -> None:
    """Show a native error box (no console needed) and exit."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg, APP_NAME, 0x10)
    except Exception:
        print(msg, file=sys.stderr)
    sys.exit(1)


def main() -> None:
    url = os.environ.get("ASCENT_URL", DEFAULT_URL).strip() or DEFAULT_URL

    try:
        import webview
    except ImportError:
        fatal(
            "The desktop runtime is missing.\n\n"
            "If you are running from source:  pip install pywebview\n"
            "If you installed the app, please reinstall it."
        )
        return

    window = webview.create_window(
        APP_NAME,
        url,
        width=1440,
        height=900,
        min_size=(MIN_W, MIN_H),
        background_color="#070707",
        confirm_close=False,
        text_select=True,
        zoomable=True,
    )

    # private_mode=False -> cookies/localStorage persist between launches,
    # so the access key and indicator settings survive restarts.
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
