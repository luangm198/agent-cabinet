# MEMORY.md — Project notebook for "Meeting with the A.I Team"

> This file is the **project's memory**: goals, important decisions, known limitations, and the idea queue. Just add new ideas to the "Ideas / Roadmap" section.

---

## 🎯 Goal
Create the feeling of a REAL meeting with an A.I team: the Host (human) chairs, 5 specialist agents speak in character, do real lookups, read/attach documents on the machine, and save the transcript.

## ✅ Done so far (as of now)
- A streaming chat web app (FastAPI + WebSocket), with 5 standard Claude Code sub-agents (`.claude/agents/*.md`).
- Runs on **Claude Max login** via `claude.exe` — no API key needed.
- Each agent has its own context; reloaded with the entire transcript every turn.
- Tools: **web search, reading files on any drive, MCP**; machine modify/delete actions are blocked (safe).
- Understands natural language about folders ("download", "images", "documents"… → absolute paths).
- **Attaching real images** to the meeting (`[[ATTACH: …]]`).
- Calling by name (`@name` / "Name,"); **enabling/disabling individual agents** (disabled = absolutely silent).
- **Persistence + history** of meetings; **creating a new meeting with selected agents**; **exporting the transcript to Word (.docx)**.
- Auto-saves every turn → a dropped connection / F5 doesn't lose the context.

## 🧠 Important technical decisions (don't break)
- Auth = the `claude auth login` CLI, NOT an API key.
- The prompt is passed via STDIN; stdout is read by chunk (to avoid crashing on long lines).
- `cwd = HOME_DIR` so paths resolve correctly and the project's CLAUDE.md isn't loaded into the persona.
- Tools run with `--permission-mode bypassPermissions` (no human approver in a web app).

---

## ⚠️ Known limitations / observations
1. **Agents have no memory across meetings.** Each meeting is a fresh context; an agent doesn't remember decisions, doesn't remember the Host, and doesn't remember what was discussed in a previous meeting.
2. **At the start of a meeting, agents don't yet "know" who their teammates are.** An agent only learns who is on the team WHEN that person speaks in the transcript. If you ask "who's on our team?" right at the start, the agent may not know all 5 people. → this is what the Host meant by "the agents don't know each other".
3. Reopening an old meeting: the agent re-reads the transcript so it "remembers" within the scope of that meeting, but it still can't relate to a different meeting.

---

## 💡 Ideas / Roadmap (queue)

### 1. Tell agents about their teammates from the start — *(quick win, do early)*
Add a "team member list" to each agent's system prompt (the names + roles of the other 4 people). Edit in `meeting.py` (build_system) — assemble the roster from `meeting.agent_keys`. Once done, asking "who's on the team?" gets an immediate answer, with each person's role known.

### 2. Long-term memory for EACH agent — *(the Host's big idea)*
Goal: each agent **remembers across meetings** — past decisions, the Host's preferences, relationships with teammates.
- Proposal: each agent has its own memory file, e.g. `.claude/agents/<key>.memory.md` (or a `memory/<key>.md` folder).
- At the end of each meeting (or when the Host clicks "save memory"): have the agent summarize "what's worth remembering" → write it to its memory file.
- At the start of the next meeting: load that memory content into the system prompt → the agent "remembers".
- Consider: shared team memory (common events) vs. private memory (each person's perspective).

### 3. (space reserved for the Host's next idea)
- …

---

## 📌 Notes when adding features
- Edit `.py` → restart uvicorn. Edit `.claude/agents/*.md` → just reload the page.
- Test with a `websockets` script, then delete it.
- Update both `CLAUDE.md` (technical description) and this file (ideas/decisions) when there's a major change.
