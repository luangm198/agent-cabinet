# 🗣️ Meeting with the A.I Team

A web app that simulates a meeting between **you (the human / host)** and **5 A.I sub-agents**,
following the model: one chairperson ↔ many specialist agents.

> **Prerequisite:** Requires an active **Claude Code Max** subscription (5x or 20x). The app uses your Claude Code login (`claude.exe`) — there is **NO API key** and no separate cost.

## Features

- **Runs on your Claude account (Max plan) — NO API key required, no extra charges.**
  The app "borrows" the Claude Code login (`claude auth login`) that is already saved.
- **5 sub-agents following the Claude Code/Anthropic standard.** Defined in `.claude/agents/*.md`
  with YAML frontmatter (`name`, `description`, `model`, `color`) + a body that serves as the system prompt.
- **Each agent is its own Opus brain** (`model: opus` in the frontmatter), with an independent context.
- **Independent context.** On each turn, an agent receives the entire flow of the meeting as its own context
  and speaks in character — processing independently from its own perspective.
- **Real-time streaming** over WebSocket: the text appears gradually, as if being spoken.

## Sub-agent structure (Anthropic standard)

Each agent is a single file at `.claude/agents/<key>.md`:

```markdown
---
name: linh-ceo
description: Linh — CEO/Founder...
model: opus
color: orange
---

You are Linh, the founder...   <- the body = the agent's system prompt
```

The app reads these files: it splits off the frontmatter to get `model`, and uses the body as the "personality brain".

## Default team (edit in `config.py`)

| Agent | Role |
|-------|------|
| 👑 Linh | CEO / Founder |
| 🛠️ Khoa | CTO / Engineering |
| 📋 Mai | Product Manager |
| 🎨 Tung | Designer (UX/UI) |
| 📈 Ha | Marketing / Growth |

## Running the app

**Easiest way:** double-click **`RUN-APP.bat`** → the browser opens automatically.

**Or via the command line:**
```bash
pip install -r requirements.txt   # only needed the first time
python -m uvicorn server:app --port 8000
# then open http://localhost:8000
```

> You only log in once (the `LOGIN.bat` file). After that, it keeps working.
> Whenever you hit "Not logged in", just run `LOGIN.bat` again.

## How to use

- Type a topic / question → **the whole team speaks in turn**.
- To call just one person: type `@khoa`, `@mai`, `@linh`, `@tung`, `@ha`
  (e.g. *"@khoa how long will this take to build?"*).
- Each page reload = a brand-new meeting room, with a clean context.

### 🔄 Auto-relay between agents
- Click the **🔄 Auto-relay** button on the toolbar to turn it ON/OFF (default: OFF).
- When ON: if an agent finishes speaking and **@mentions** another (enabled) agent, that agent **automatically speaks next** — like a team discussing among themselves while you just sit back and watch.
- Safe: a maximum of **4 relays per message you send**, and each agent speaks at most **2 times** (adjust `AUTO_RELAY_MAX_*` in `config.py`) → it never runs forever and never burns through your quota. Typing a single line interrupts it immediately.

### 🧠 Memory (per-agent + shared team memory)
- **Private memory** (`memory/<key>.md`): each agent's own perspective. **Shared memory** (`memory/_team.md`): facts the whole team knows — loaded into EVERY agent → so everyone stays consistent.
- **Remembering:** *"@khoa remember: ..."* → goes into Khoa's private memory; *"team remember: ..."* → goes into shared memory. Or, at the end of a meeting, click **💾 Save memory** → each agent distills its own private notes + one secretary distills the shared notes.
- **View/delete:** click **🧠 Memory** → view/delete both the shared memory and each individual's memory.
- Auto-anti-bloat: when it exceeds `MEMORY_MAX_FACTS` (default 40) → the agent automatically **cleans up** (merging duplicates, dropping outdated/conflicting items). Each turn loads at most `MEMORY_INJECT_MAX_CHARS` to save tokens (adjust in `config.py`).

### 📎 Attach documents to the meeting
- Click the **📎** button next to the input box, or **drag and drop a file** onto the page.
- Supported: **PDF, Word (.docx), Excel (.xlsx), TXT, CSV, MD, JSON** (the server extracts the content)
  and **PNG/JPG/… images** (agents use the Read tool to "view" them directly).
- The document content is inserted into the transcript → **the whole team can read it in the next message**.
- Files are stored at `meetings/uploads/<id>/`; up to 25MB per file. Long documents are automatically truncated
  (agents can still open the full version on disk via the tool if needed).

## Customization

- **Change one agent's personality:** edit the body of `.claude/agents/<key>.md`. Reload the page and you're done.
- **Change each agent's individual brain:** edit `model:` in that file's frontmatter (`opus`/`sonnet`/`haiku`).
- **Add a new agent:** create `.claude/agents/<key>.md` (with correct frontmatter) + add one line to `AGENTS` in `config.py` (the key must match the file name).
- **Change the overall thinking depth:** `EFFORT` in `config.py` (`low`/`medium`/`high`/`xhigh`/`max`).

## Agent tools (web search / read files / MCP)

All 5 agents are granted tools so they can **verify things for real** instead of speaking from memory. Adjust in `config.py`:

| Setting | Meaning |
|---|---|
| `ENABLE_TOOLS = True` | Turn all agent tools on/off |
| `FULL_CONTROL` | **Defaults to `False`** → agents can only READ & SEARCH. Set to `True` to opt in and grant full machine control. |
| `DISALLOWED_TOOLS` | Blocked tools (by default blocks `Bash/Write/Edit/...` → agents **cannot modify the machine**) |
| `DOCS_DIRS` | Folders the agent is allowed to **read documents** from (default: the entire machine) |
| `ALLOW_MCP = True` | Allow MCP (Notion, Drive, Gmail, Calendar...) |

- By default (`FULL_CONTROL = False`), agents **read & search** freely, but **cannot** run commands that modify/delete things on the machine (Bash/Write/Edit are blocked).
- Setting `FULL_CONTROL = True` is an **opt-in** that grants the agents **full control of the machine** (create/modify/delete files, run commands). Use it only when you really want to hand over that level of control.
- ⚠️ When `ALLOW_MCP = True`, some MCP tools can take *actions* (send mail, create pages). The system prompt already instructs them "do not send/create/delete on your own unless the Host asks", but for absolute safety set `ALLOW_MCP = False`.
- While an agent is looking something up, the UI shows the status "🔎 searching the web…".

## Note

- Each message you send makes all 5 agents speak = 5 Opus calls, counted against your
  Max plan limit (capped over a 5-hour window). Use `@name` to call one person to save quota.
