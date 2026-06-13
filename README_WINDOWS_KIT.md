# Ascent Terminal — Windows kit

What's in this folder and how to run everything on Windows.

---

## Files

| File | Purpose |
|---|---|
| `UPDATE.bat` | Pull latest code + restart the server |
| `organise.bat` | Tidy the repo: move stray files to the right folders |
| `brain/RUN_EDGE_LAB.bat` | Launch the signal-research / walk-forward tool |

---

## Quick start (first time)

1. Install **Python 3.10+** from python.org — tick "Add to PATH".
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in `ACCESS_KEY` and
   `ANTHROPIC_API_KEY`.
4. Start the server:
   ```
   uvicorn platform.main:app --reload
   ```
5. Open `http://localhost:8000` in your browser.

---

## UPDATE.bat

Double-click to:
- Pull the latest commits from GitHub
- Install any new Python dependencies
- Restart the server (kills the old uvicorn process first)

The window stays open so you can see any errors.  Close it when
the server says `Application startup complete`.

---

## organise.bat

If you have stray `.py`, `.bat`, `.md`, or `.txt` files sitting in
the root that belong in `bots/` or `brain/`, double-click this to
move them automatically.  It logs every action to
`organise_log.txt`.

Safe to re-run — it only moves files it recognises by name.

---

## brain/RUN_EDGE_LAB.bat

Launches `brain/edge_lab.py` in an interactive terminal window.
Edge Lab lets you:
- Run walk-forward signal research on any MEXC futures pair
- Backtest the EMA30 trend rule with configurable parameters
- Export results to CSV

Requires the same Python environment as the main server.

---

## Notes

- All scripts assume Python is on your PATH.
- If you see `'python' is not recognised`, use `python3` instead,
  or reinstall Python with "Add to PATH" ticked.
- The server must be running for the browser UI to work.
