# 🗣️ Meeting with the A.I Team

A web app that drops you into a live meeting with **your own team of A.I agents** — a CEO, a CTO, a lawyer, anyone you want. You chair the room; they reply in character, in real time, and can even debate each other.

> **Prerequisite:** an active **Claude Pro or Max** subscription. The app reuses your existing Claude login (`claude.exe`) — there is **NO API key** and **no extra cost**.

---

## ✨ Why it's different

- **Build an UNLIMITED team.** Add as many sub-agents as you want from the **👥 Team** panel — name, role, emoji, color, brain, and personality. The default team is just a starting point.
- **Each agent is its own brain.** Pick the model per agent (`opus` / `sonnet` / `haiku`), each with an independent context, speaking in character from its own perspective.
- **Real tools, not just talk.** Agents can **search the web, read files, use MCP servers** (Notion, Gmail, Drive, Calendar…), run **Claude Code skills**, and — if you allow it — **control your computer**.
- **They work in parallel.** Every agent runs on its own "laptop" — different agents answer concurrently while you keep typing.
- **They debate each other.** Turn on **🔄 Auto-relay** and agents @mention one another and discuss among themselves, with safety caps so it never loops or burns your quota.
- **Persistent memory.** Per-agent private memory + a shared team memory, isolated per project.
- **No API key. No extra charge.** It "borrows" your saved Claude login (Pro or Max).

---

## 🚀 Quick start

```bash
pip install -r requirements.txt   # first time only
python -m uvicorn server:app --port 8000
# then open http://localhost:8000
```

**Even easier (Windows):** double-click **`RUN-APP.bat`** → the browser opens automatically.

> Log in once via **`LOGIN.bat`** (it runs `claude auth login` with your Pro/Max account).
> Whenever you see *"Not logged in"*, just run `LOGIN.bat` again. Check status with `claude auth status`.

---

## 👥 Default team (fully editable in the UI)

| Agent | Role |
|-------|------|
| 👑 Linh | CEO / Founder |
| 🛠️ Khoa | CTO / Engineering |
| 📋 Mai | Product Manager |
| 🎨 Tung | Designer (UX/UI) |
| 📈 Ha | Marketing / Growth |
| ⚖️ Quang | General Counsel / Legal |

This is only a **seed**. Use the **👥 Team** button to add / edit / duplicate / delete agents — there's **no hard limit** on team size.

---

## 🧠 How to use

- Type a topic → **the whole team weighs in** (each enabled agent answers).
- Call just one person with `@key` / `@name`, e.g. *"@khoa how long to build this?"* or *"@quang are we allowed to scrape this data?"*.
- Toggle a name in the roster to **enable/disable** an agent (a disabled agent never speaks, even if @mentioned).
- **Stop** any single agent mid-answer, or **Stop all** at once.
- Each page reload = a brand-new meeting room with a clean context.

### 🔄 Auto-relay between agents
Turn it ON (toolbar) and agents that @mention another enabled agent **hand the turn over automatically** — like a team discussing while you watch. Capped at **4 relays per message** and **2 turns per agent** (`AUTO_RELAY_MAX_*` in `config.py`) so it can't run forever. Type anything to interrupt instantly.

### 📎 Attach documents
Click **📎** or drag-and-drop a file onto the page. Supports **PDF, Word (.docx), Excel (.xlsx), TXT, CSV, MD, JSON** and **images (PNG/JPG/…)**. The content is dropped into the transcript so the whole team can read it next turn.

### 🧠 Memory (per-agent + shared)
- **Private** memory per agent + a **shared team** memory loaded into everyone (so the team stays consistent).
- Say *"@khoa remember: …"* (private) or *"team remember: …"* (shared), or click **💾 Save memory** at the end of a meeting to distill notes automatically.
- View/delete anytime via the **🧠 Memory** modal. Auto-consolidates when it grows too large.

### 📁 Projects & 📄 Export
- **Projects** keep workspaces isolated — each project has its own meetings, memory, and documents (📁 Project button).
- **Export any meeting to Word (.docx)** with one click.

---

## 🔧 Sub-agent structure (Claude Code / Anthropic standard)

Each agent is a single file at `.claude/agents/<key>.md` (the **👥 Team** UI writes these for you):

```markdown
---
name: quang
description: Quang — General Counsel / Legal
model: opus
color: #6b3d99
---

You are Quang, the General Counsel…   ← the body = the agent's system prompt
```

`.claude/agents/agents.json` holds the ordered roster + per-agent metadata and capabilities. Changes take effect in a **new meeting** (reload the page).

---

## 🛡️ Agent capabilities & safety

Each agent's powers are configurable (global defaults in `config.py`, override per agent in the UI):

| Capability | Meaning |
|---|---|
| `tools` | Web search + read files |
| `mcp` | MCP servers (Notion, Drive, Gmail, Calendar…) |
| `skills` | Claude Code skills (`/skill-name`) |
| `full` | 🔴 **Full machine control** — create/modify/delete files & run commands |

- **Safe by default:** `full = false` → agents can **read & search** but **cannot** modify or delete anything (Bash/Write/Edit are blocked).
- Setting **`full = true`** is an explicit opt-in that hands an agent **full control of your machine** — use it deliberately.
- ⚠️ With MCP on, some tools can take *actions* (send mail, create pages). The system prompt tells agents not to send/create/delete unless you ask; for maximum safety, disable MCP.

---

## ⚙️ Customization

- **Personality:** edit the body of `.claude/agents/<key>.md` (or the 👥 Team form) → reload.
- **Brain:** set `model:` per agent (`opus` / `sonnet` / `haiku`).
- **Thinking depth:** `EFFORT` in `config.py` (`low` / `medium` / `high` / `xhigh` / `max`).
- **New agent:** just use the **👥 Team** UI (it creates the `.md` + roster entry). The `key` is permanent once created.

---

## 📝 Note on quota

Every message you send makes **each enabled agent** answer — so a 6-agent team = 6 model calls, counted against your **Claude Pro/Max** limit (over a rolling window). Call one person with `@name`, or disable agents you don't need, to save quota.

---

## 📦 Requirements

- **Claude Pro or Max** subscription, logged in via Claude Code (`claude auth login`).
- **Python 3.10+** (3.12/3.13 recommended), Windows.
- Install deps: `pip install -r requirements.txt`.

---

Made for anyone who wishes they had a whole expert team on call. ⭐ the repo if it's useful!
