# CLAUDE.md — Meeting with the A.I Team

Guidance for Claude Code (and maintainers) when working on this project.

## What the project is
A web app that simulates a **real meeting** between a **Host (human)** and **5 A.I sub-agents** (CEO, CTO, PM, Designer, Marketing). Each agent is its own "brain", speaks in character, and can search the web / read files on the machine / attach images to the meeting. The interface is a real-time streaming chat.

## ⚠️ Authentication — NO API key
The app does **not** call the Anthropic API with a key. Instead it calls the **`claude.exe` CLI** from Claude Desktop (logged in with the user's **Claude Max** plan via `claude auth login`).
- The path to `claude.exe` is detected dynamically in `meeting.py` → `find_claude_exe()` (by default located at `…\Packages\Claude_*\…\claude-code\<ver>\claude.exe`). It can be overridden with the `CLAUDE_CLI` environment variable.
- If it reports **"Not logged in"** → run `LOGIN.bat` again (which calls `claude auth login`).
- Check with: `claude auth status` (must show `loggedIn: true`).

## How to run
- **Easiest:** double-click `RUN-APP.bat` (opens the browser at http://localhost:8000).
- **Command:** `python -m uvicorn server:app --port 8000`
- Python: 3.13 (Windows). Install libraries: `pip install -r requirements.txt`.
- In a fresh shell you may need to reload PATH from the registry to find `python`/`claude`.

## Architecture / files
| File | Role |
|---|---|
| `config.py` | General configuration: `MODEL`, `EFFORT`, tool config (`ENABLE_TOOLS`, `DISALLOWED_TOOLS`, `DOCS_DIRS`, `FULL_CONTROL`, `ALLOW_MCP`). `FULL_CONTROL` defaults to `False` (agents can READ & SEARCH but cannot modify/delete/run commands); setting it to `True` is an opt-in that grants full machine control. `AGENTS` here is now only a **SEED list** (used the first time to create `agents.json`); the real team is managed dynamically via `roster.py`. |
| `roster.py` | **Dynamic TEAM management** (for the "👥 Team" UI). Source of truth: `.claude/agents/agents.json` (an ordered list of {key,name,role,emoji,color,model}) + the persona in `.claude/agents/<key>.md`. CRUD: `load/keys/by_key/name_of/public/upsert/delete`; `read_persona` reads the .md body. When SAVING via the UI → it rewrites a standard .md (frontmatter + body). `key` is IMMUTABLE once created. |
| `.claude/agents/<key>.md` | **Standard Claude Code sub-agent definition** (frontmatter + body = persona). `agents.json` holds the metadata + ordering. |
| `meeting.py` | Core: detects `claude.exe`, builds the system prompt (persona via `roster.read_persona` + `MEETING_RULES` + `MACHINE_INFO`), runs `claude -p` streaming, captures tools & images, the `Agent`/`Meeting` classes. `Meeting` has a `project_id`; every memory call passes `project_id`. |
| `server.py` | FastAPI: HTTP (`/`, `/agents`, `/roster` CRUD, `/projects` CRUD, `/meetings?project=`, `/memory?project=`, `/meetings/{id}/export`) + WebSocket `/ws` (protocol `init`/`chat`; `init` receives a `project_id` and returns a `project_id`). |
| `store.py` | Stores meetings as JSON (`meetings/`, with a `project_id` field), **PROJECTS** (`projects/<pid>.json`), **per-project memory** (`memory/<project_id>/<key>.md`), and exports `.docx`. `ensure_seed()` migrates old data into `prj_default` (runs once, idempotent). |
| `static/index.html` | The entire UI: streaming chat, roster toggles, New/History/Memory modals, **Project + Team management + agent form modals**, the Export to Word button. |
| `projects/` | Each project = one `<pid>.json` file ({id,name,created_at,updated_at}). |
| `meetings/` | Each meeting = one `<id>.json` file (with `project_id`) (+ `.docx` when exported). |
| `memory/<project_id>/` | Memory ISOLATED per project: each agent's `<key>.md` + `_team.md`. |
| `RUN-APP.bat` / `LOGIN.bat` | Run the app / log in to Claude. |

## How an agent speaks
`meeting.py → Meeting.stream_agent()` calls:
```
claude -p --model <model> --effort <EFFORT>
  --system-prompt "<persona + MEETING_RULES + MACHINE_INFO>"
  --output-format stream-json --include-partial-messages --verbose
  [--permission-mode bypassPermissions --add-dir <drives> --disallowedTools <...>]
```
- **The prompt (the entire meeting transcript) is passed via STDIN** (to avoid command-line length limits).
- `cwd = HOME_DIR` (the user's home folder) → relative paths like "Downloads" resolve correctly. (Note: because cwd is home rather than the project folder, this CLAUDE.md is NOT loaded into the agents' personas.)
- stdout is read by **chunk + manual line splitting** (NOT readline — a JSON line for a large image/file exceeding 64KB would crash readline).
- Each agent keeps its own context = it is reloaded with the entire transcript on every turn (no shared object).

## Important conventions
- **Sub-agents**: to change personality → edit the body of `.claude/agents/<key>.md`; to change the individual brain → edit `model:` in the frontmatter. Changes to `.md` take effect on **page reload** (each connection creates a new `Meeting` that re-reads the files). Changes to `.py` require a **uvicorn restart**.
- **Calling by name**: `@key` / `@name`, or the name at the start of a sentence ("Tung, …"). If no one is called → only the enabled agents speak.
- **Enable/disable agents**: the client sends `enabled: [keys]`; a disabled agent **absolutely does not speak** (even if @mentioned). Logic lives in `server.py`.
- **Attaching images to the meeting**: an agent writes a line `[[ATTACH: <absolute path>]]` → `server.py` reads the file (`image_data_url`) → sends the base64 image to the UI. The marker is hidden from the text.
- **Tools**: enabled via `--permission-mode bypassPermissions` (a web app has no per-call approver). Machine-modifying/deleting actions are blocked by `DISALLOWED_TOOLS` (Bash/Write/Edit…). By default `FULL_CONTROL = False` keeps agents read-and-search only; `FULL_CONTROL = True` unlocks everything (dangerous).
- **Persistence**: every chat turn is saved to `meetings/<id>.json`. Reconnecting = reopening the exact same meeting (no context lost).

## WebSocket protocol
- Client → `{type:"init", meeting_id?|title?|agents?}` → server returns `{type:"meeting", id,title,agents,log}`.
- Client → `{type:"chat", text, enabled:[keys]}` → server streams: `agent_start{key,name,task}` → `token`/`tool`/`image{key,...}` → `agent_done{key}` (or `sys`). **There is no more `round_done`.**

## Auto-relay between agents
- The UI toggle `btnRelay` → sends `relay:true/false` with each `chat`. Default OFF (only the Host starts a turn).
- When ON: `run_one_task` accumulates what was `spoken`, then calls `maybe_relay()` which scans for `@key`/`@name` of OTHER (enabled) agents in what was just said → queues a `("chat", ...)` turn for that agent.
- **Caps against loops/quota burn** (`config.py`): `AUTO_RELAY_MAX_HOPS=4` (per Host message) + `AUTO_RELAY_MAX_PER_AGENT=2`. The budget (`state["hops_left"]`, `chain_counts`) resets per Host message; it is deducted IMMEDIATELY when a turn is queued (synchronous, safe with asyncio). The Host can interrupt at any time (the input box is never locked).

## Running in PARALLEL (each agent gets its own "laptop")
- `server.py → ws()`: each agent has a **work queue (`agent_queues[key]`) + 1 worker (`agent_workers[key]`)** running independently. Tasks for the SAME agent run sequentially; **DIFFERENT agents run concurrently**.
- Every outgoing event goes through **a single `out_queue` + a single `sender()`** (so multiple workers don't overwrite each other's frames on the same socket).
- Assigning work (`chat`) only **pushes to the queue and returns to listen again** → the input box is NOT locked; the Host can assign work to someone else while a previous person is still working.
- "Memory" is unchanged: each agent still receives the ENTIRE `meeting.log` at the moment it starts (it just doesn't yet see work others are doing IN PROGRESS at the same time — once done, that goes into the log).
- Client (`index.html`): `bubbles{key→bubble}` for multiple agents streaming in parallel; a yellow `.working` caption shows `⏳ working on: «task» — <tool>`.

## Documents uploaded by the Host (upload)
- `documents.py`: extracts text from pdf/docx/xlsx/txt… (for images, the agent uses Read to view). `POST /meetings/{id}/upload` saves into `meetings/uploads/{id}/`, inserts the content into the `log` (an entry with an `upload` field); `GET /meetings/{id}/file/{name}` serves the file back.
- `ws()` syncs `meeting.log` from disk at the start of each chat turn to catch documents just uploaded via HTTP.

## Memory (HYBRID: per-agent + shared team)
- Files: `memory/<key>.md` for each agent + `memory/_team.md` (`store.TEAM_KEY`) for SHARED memory. One idea per line, with a date. Configured in `config.py`: `MEMORY_ENABLED`, `MEMORY_TEAM_ENABLED`, `MEMORY_MAX_FACTS` (exceeded → auto-cleanup), `MEMORY_INJECT_MAX_CHARS`.
- **Reading:** `_attempt()` loads into the `--system-prompt` each turn: the **SHARED memory** (`TEAM_HEADER`, loaded into EVERY agent) + that agent's **PRIVATE memory** (`MEMORY_HEADER`). `store.memory_for_prompt` takes only the "idea" lines, trimming to the most recent ideas if over budget.
- **Markers:** `[[REMEMBER: ...]]` → private to the agent; `[[REMEMBER_TEAM: ...]]` → shared with the team (MARKER_RE in `_attempt`, both hidden from speech). The 💾 button (`save_memory`) runs `run_memory_save` (private) for each agent + picks one secretary agent (prefers `linh`) to run `run_team_memory_save` (shared). Cleanup uses the shared helper `_consolidate(agent, key, owner)`.
- **Writing (3 problems already handled):**
  - *Who writes:* the SERVER writes (via the `[[REMEMBER: ...]]` marker the agent emits; `MARKER_RE` in `_attempt` catches both ATTACH and REMEMBER, and the REMEMBER marker is hidden from speech/transcript). `store.append_memory` prevents duplicates.
  - *When:* only when the Host says "remember…" (inline, `stream_agent` catches a `remember` event) OR via the **💾 Save memory** button (`{type:"save_memory"}` → `Meeting.run_memory_save` distills). It does NOT write every turn.
  - *Bloat & conflicts:* exceeding `MEMORY_MAX_FACTS` → `run_memory_save` auto-**cleans up** (consolidate prompt → `_parse_bullets` → `store.write_memory` overwrites with a clean list, keeping the most recent ideas).
- View/delete: `GET /memory`, `DELETE /memory/{key}`; the UI has a **🧠 Memory** modal. Save/cleanup events are reported to the UI via the `sys` event.

## Projects & Team management — 2 extension features
- **A project = an isolated workspace:** each project has its own meetings (`meetings/*.json` filtered by `project_id`), its own memory (`memory/<project_id>/`), and its own documents (per meeting). SHARED memory (`_team`) is also per project. UI: the **📁 Project** button (create/switch/delete; the currently open project is remembered in `localStorage`). Deleting a project deletes its meetings + memory too.
- **Migration:** the first time you run the new build, `store.ensure_seed()` creates `prj_default` ("General project"), moves `memory/*.md` (the old root level) → `memory/prj_default/`, and assigns `project_id=prj_default` to every old meeting. Safe, no data loss, harmless to re-run.
- **Dynamic team management:** the **👥 Team** UI button → add/edit/duplicate/delete sub-agents (name, role, emoji, color, model, persona) via `/roster` (GET/POST/PUT/DELETE). `roster.py` writes `agents.json` + syncs a standard `.md` file. **`key` cannot be changed after creation** (it is the file name + the reference used in meetings/memory). Team changes take effect in a NEW meeting (each `Meeting` re-reads the roster on creation).
- **Gotcha:** `config.AGENTS` is only a seed — editing it does NOT change the team if `agents.json` already exists; change the team via the UI, or delete `agents.json` to re-seed.

## How to test (no browser needed)
Use `websockets` (Python): connect to `ws://localhost:8000/ws`, send `init` then `chat`, and read the events. You can also check HTTP `/meetings`, `/meetings/{id}/export`. (The `_wstest*.py` scripts are temporary — delete them after testing.)

## Common pitfalls
- Editing `.py` without restarting the server → no effect.
- "Not logged in" → `LOGIN.bat`.
- Don't re-introduce `--tools ""` if you want agents to still be able to use tools.
- Large images/files: keep reading stdout by chunk (don't go back to `async for line`).
