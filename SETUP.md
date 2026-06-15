# Setup — Moving the project to another machine

**App:** "Meeting with the A.I Team" (Python / FastAPI)

> **Prerequisite:** Requires an active **Claude Code Max** subscription (5x or 20x). The app uses your Claude Code login (`claude.exe`) — there is **NO API key** and no separate cost.

**GOAL:** copy this entire project folder to a new machine (using the same Claude Max account) and run it EXACTLY the same way WITHOUT changing any application logic.

---

## 0) Requirements on the new machine

- Windows, with Claude Desktop (Claude Code) installed and LOGGED IN using a Max account.
- Python 3.10+ installed (3.12/3.13 recommended).
- Bring the ENTIRE project folder, including:
  - `memory/`     → private + shared memory (so the team still "remembers")
  - `meetings/`   → meeting history
  - `.claude/agents/` → the 5 personas (Linh/Khoa/Mai/Tung/Ha)

---

## A) Fastest way — "ZERO file edits" (recommended)

Open PowerShell/CMD right INSIDE the project folder on the new machine, then type:

```
pip install -r requirements.txt
python -m uvicorn server:app --port 8000
```

Then open your browser at: http://localhost:8000

→ No need to change a single line. The app detects `claude.exe` automatically (`find_claude_exe`).
   (The `RUN-APP.bat` file is just a double-click convenience; this method skips it.)

If it reports "Not logged in": run `claude auth login` (Max account), then try again.
Check the login:                run `claude auth status` (must show `loggedIn: true`).

---

## B) Letting Claude Code do it for you

1. Open a Terminal/PowerShell INSIDE the project folder → type: `claude`
   (it will read CLAUDE.md to understand the project)
2. Paste the block below for it:

---

**[ COMMAND TO PASTE FOR CLAUDE CODE ]**

This is the "Meeting with the A.I Team" web app (Python/FastAPI). I just copied this
entire folder from another machine, using the same Claude Max account. Please help me
run it EXACTLY the same way WITHOUT changing any application logic (keep server.py,
meeting.py, store.py, config.py, documents.py, static/index.html, and the memory/ +
meetings/ folders intact). Read CLAUDE.md in the folder to understand how to run it.
Work step by step and report back:

1. Check Python; install the libraries: `pip install -r requirements.txt`
2. Check the login: run `claude auth status`. If not logged in, tell me to run
   `claude auth login` (Max account) — don't do it for me.
3. Confirm that `find_claude_exe()` can find `claude.exe` on this machine. If it CANNOT,
   do NOT change the code — instead set the `CLAUDE_CLI` environment variable pointing
   to the correct `claude.exe`.
4. You may ONLY edit the paths in the 2 launcher files `RUN-APP.bat` and `LOGIN.bat`
   (and recreate the Desktop shortcut) to match this machine's username + folder location —
   these are environment files, NOT app logic.
5. Start it: `python -m uvicorn server:app --port 8000`, open http://localhost:8000,
   and confirm that the 5 sub-agents (Linh/Khoa/Mai/Tung/Ha) respond.

Absolutely do not touch the .py and .html files.

---

## C) Technical notes

- `claude.exe` is detected DYNAMICALLY, not hardcoded in the code. To force it manually:
  ```
  PowerShell:  $env:CLAUDE_CLI = "C:\path\to\claude.exe"
  ```
  then run uvicorn in that same window.
- The 2 `.bat` files (`RUN-APP.bat`, `LOGIN.bat`) hardcode the old machine's paths
  (username, folder location, claude version). You only need to edit them if you want to
  double-click; if you run via the uvicorn command, you do NOT need to edit them.
- Default port is 8000. If it's busy, change it: `--port 8001` (then open localhost:8001).
- Stop the app: close the window running uvicorn (or press Ctrl+C).

---

## D) For absolute safety regarding permissions

In `config.py`:
- `FULL_CONTROL = False` (the default) → agents can only READ & SEARCH (safer). Set it to
  `True` to opt in and grant agents full machine control (create/modify/delete/run commands).
- `ALLOW_MCP = True/False` → turn the MCPs on/off (Notion, Drive, Gmail, Calendar...).

(These are configuration options, not required when moving machines.)

---

Done. Enjoy a smooth machine transfer!
