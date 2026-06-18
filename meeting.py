"""
Meeting engine — runs through the logged-in Claude CLI (Max plan), NO API key needed.

Idea:
- Each agent has its own persona (passed via --system-prompt -> swaps the "brain" into a character).
- There is a shared transcript (self.log) recording who said what.
- Each turn, the agent is given the ENTIRE meeting so far as its own context,
  then speaks in character. Each agent works independently from its own viewpoint.
- Stream each token outward (read text_delta from the CLI's stream-json output).
"""

import os
import re
import glob
import json
import base64
import asyncio
import tempfile
import mimetypes
import subprocess


def _kill_proc_tree(proc):
    """Forcefully terminate a running claude.exe AND its child processes.
    On Windows `claude.exe` spawns helper children, so proc.kill() alone would
    leave orphans burning quota — use `taskkill /T` to kill the whole tree."""
    if proc is None or proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
            )
        else:
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

import string

from config import (
    MODEL, EFFORT,
    ENABLE_TOOLS, DISALLOWED_TOOLS, DOCS_DIRS, ALLOW_MCP, FULL_CONTROL,
    MEMORY_ENABLED, MEMORY_TEAM_ENABLED, MEMORY_MAX_FACTS, MEMORY_INJECT_MAX_CHARS,
)
import store
import roster


def access_dirs() -> list[str]:
    """List of folders the agent is allowed to read."""
    if DOCS_DIRS == "ALL":
        # every drive present on the machine (C:\, D:\, ...)
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    if isinstance(DOCS_DIRS, str):
        return [DOCS_DIRS]
    return list(DOCS_DIRS or [])


def tool_args(caps: dict) -> list:
    """Build the claude CLI tool/permission flags for ONE agent's capabilities.
    Pure function (no side effects) so it can be unit-tested without spawning a process.

    caps = {"tools": bool, "mcp": bool, "skills": bool, "full": bool}
    """
    if not caps.get("tools"):
        return ["--tools", ""]                  # no tools at all -> talk only
    # tools on: run without a per-action approval prompt (web app, no human in the loop)
    args = ["--permission-mode", "bypassPermissions"]
    dirs = access_dirs()
    if dirs:
        args += ["--add-dir", *dirs]            # allow reading these locations on the machine
    if not caps.get("mcp"):
        args += ["--strict-mcp-config"]         # disable pre-configured MCP
    if not caps.get("skills"):
        args += ["--disable-slash-commands"]    # disables all Claude Code skills (/skill-name)
    blocked = [] if caps.get("full") else list(DISALLOWED_TOOLS)  # full control -> block nothing
    if blocked:
        # this variadic arg must come LAST (commander swallows the rest)
        args += ["--disallowedTools", *blocked]
    return args


def caps_note(caps: dict) -> str:
    """A per-agent block telling the agent what it ACTUALLY can and cannot do this turn,
    so it won't pretend to use tools it doesn't have. Kept in sync with tool_args()."""
    if not caps.get("tools"):
        return (
            "YOUR TOOLS THIS MEETING: you have NO tools — you can only reason and talk from "
            "your own knowledge. Do NOT claim to search the web, read files, access the computer, "
            "or run anything; nothing will actually happen. If a task needs that, say plainly that "
            "you can't, and hand it to a teammate who can or ask the Host."
        )
    lines = [
        "YOUR TOOLS & PERMISSIONS THIS MEETING (do not claim abilities beyond these):",
        "- You CAN search the web and read files/images (read-only).",
    ]
    if caps.get("mcp"):
        lines.append("- You CAN use connected MCP servers (Notion, Drive, Gmail, Calendar…) to fetch real data. Don't send/create/delete unless the Host explicitly asks.")
    else:
        lines.append("- MCP is OFF — do not try to use Notion/Drive/Gmail/etc.")
    if caps.get("skills"):
        lines.append("- You MAY use Claude Code skills (/skill-name) if helpful.")
    else:
        lines.append("- Skills are OFF — don't rely on /skill-name commands.")
    if caps.get("full"):
        lines.append("- You HAVE FULL CONTROL: you may create/edit/delete files and run commands to actually BUILD things (e.g. write an HTML mockup to disk).")
    else:
        lines.append("- You CANNOT modify the machine: no writing/editing/deleting files and no running commands. If a task needs building or running, describe exactly what to build (specs/code in your message) and hand it to a teammate who can — do NOT pretend you did it.")
    return "\n".join(lines)


# Syntax the agent uses to attach an image/file to the meeting: [[ATTACH: <path>]]
# and to save to its own memory: [[REMEMBER: <thing to remember>]]
ATTACH_RE = re.compile(r"\[\[ATTACH:\s*(.+?)\]\]")
# REMEMBER_TEAM must come BEFORE REMEMBER in the alternation to match the longer one.
MARKER_RE = re.compile(r"\[\[(ATTACH|REMEMBER_TEAM|REMEMBER):\s*(.+?)\]\]",
                       re.IGNORECASE | re.DOTALL)

MEMORY_HEADER = (
    "YOUR OWN MEMORY (accumulated by you across previous meetings — use it as context, "
    "do NOT read it back mechanically to the Host):"
)
TEAM_HEADER = (
    "THE TEAM'S SHARED MEMORY (facts the whole team agreed on in earlier sessions — everyone knows them):"
)


def image_data_url(path: str):
    """Read one image file -> (data_url, filename). Returns None if invalid/too large."""
    for cand in (path, os.path.normpath(path), path.replace("/", "\\")):
        try:
            if cand and os.path.isfile(cand):
                if os.path.getsize(cand) > 20 * 1024 * 1024:   # > 20MB -> skip
                    return None
                mime, _ = mimetypes.guess_type(cand)
                if not mime:
                    mime = "image/png"
                with open(cand, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                return (f"data:{mime};base64,{b64}", os.path.basename(cand))
        except OSError:
            continue
    return None


def find_claude_exe() -> str:
    """Find the claude.exe of Claude Desktop (already logged in)."""
    override = os.environ.get("CLAUDE_CLI")
    if override and os.path.exists(override):
        return override

    local = os.environ.get("LOCALAPPDATA", "")
    pattern = os.path.join(
        local, "Packages", "Claude_*", "LocalCache", "Roaming",
        "Claude", "claude-code", "*", "claude.exe",
    )
    matches = glob.glob(pattern)
    if matches:
        # latest version (sort by version folder name)
        matches.sort()
        return matches[-1]

    # fallback: claude on PATH
    return "claude"


CLAUDE_EXE = find_claude_exe()

# Sub-agent in the standard Claude Code format: .claude/agents/<key>.md (YAML frontmatter + body)
SUBAGENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".claude", "agents")


def parse_frontmatter(text: str):
    """Split the YAML frontmatter (--- ... ---) from the body. Returns (meta dict, body)."""
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end]
            body = text[end + 4:]
            for line in fm.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
    return meta, body.strip()


def load_agent_file(key: str):
    """Read sub-agent .claude/agents/<key>.md -> (meta, persona body)."""
    path = os.path.join(SUBAGENTS_DIR, f"{key}.md")
    try:
        with open(path, encoding="utf-8") as f:
            return parse_frontmatter(f.read())
    except FileNotFoundError:
        return {}, ""


MEETING_RULES = """
Context: This is a REAL product-team meeting. The "Host (human)" is the founder / chair sitting in the meeting with the whole team.

How to speak:
- Speak naturally in English, exactly as if you were in the meeting in person. (If the Host is clearly writing in another language, you may reply in that language.)
- Stay in your role and bring your own professional perspective.
- BE BRIEF, like talking out loud: usually 2–6 sentences. If you have nothing to add, say so in one line or defer.
- You may agree, push back, refer to teammates, and ask the Host or a teammate a direct question.
- Don't repeat what someone just said — add new value.
- Don't write document-style text with headings/markdown. Talk naturally.
- Return ONLY your actual spoken line, with no preamble like "As the …".

Handing the turn to a teammate (IMPORTANT):
- This is a live meeting where teammates can take the next turn automatically. To make a specific teammate actually respond and act next, you MUST put "@" before their name (e.g. @khoa, @mai, @tung). Just mentioning a name ("Khoa's right", "as Mai said") is only a reference — it will NOT bring that person in.
- Use "@name" only when you genuinely want that person to take the next turn — assigning them a task, asking them a direct question, or handing off work. Don't @ the whole room out of habit; @ exactly the people you need so you don't pull in everyone and waste turns.
- Example (assigning work): "@khoa stand up the storefront template this week; @tung start the mobile hero; @mai set up conversion tracking." Each @name there is pulled in to respond.
- The teammate keys you can @ are exactly the participants listed in this meeting. Use their key/first name after @ (lowercase), e.g. @khoa.

Tools (VERY IMPORTANT):
- When you need real-world / recent / possibly-changed information (new tools, prices, figures, this year's trends, competitors...), you MUST use web search to verify BEFORE speaking. Never make things up or rely on stale memory.
- When talking about specific figures/prices/products, prefer citing the source you just found.
- If the Host asks for a document on the machine, use the file-reading tool to open it and summarize its content for the team.
- ATTACH AN IMAGE TO THE MEETING: when the Host wants to VIEW an image directly (not just hear it described), after you've confirmed the correct file path, write on a SEPARATE LINE the exact syntax:
  [[ATTACH: C:\\absolute-path\\image-name.png]]
  The system will display that image right in the chat for the whole team. You may add a short caption before/after. One [[ATTACH: ...]] line per image. Only attach a file that actually exists and that you just verified.
- If a relevant MCP is available (Notion, Drive, Calendar...), use it to fetch real data. Do NOT send mail / create / edit / delete anything unless the Host explicitly asks.
- DOCUMENTS/IMAGES THE HOST UPLOADS TO THE MEETING: when the Host attaches a file, the transcript will have a 📎 label line with the document content (or the image path). READ it and base your remarks on that exact content; don't guess. For IMAGES (path only), use the image-reading tool (Read) on the path to view it directly. If the document content was truncated ("TRUNCATED"), use the file-reading tool on the path to see it in full when needed.

MEMORY (own & shared):
- Above you may see "THE TEAM'S SHARED MEMORY" (everyone knows it) and "YOUR OWN MEMORY" (your private view) — use them as context, don't recite them to the Host.
- When you need to save something (the Host says "remember ...", or you're asked to save memory), write it on a SEPARATE LINE, one item per line:
  • Something relevant ONLY to your role/viewpoint → [[REMEMBER: ... brief, 1 sentence]]
  • A fact the WHOLE TEAM needs (project name/positioning, decisions made, constraints, deadlines, agreed terminology) → [[REMEMBER_TEAM: ... brief, 1 sentence]]
  If the Host says "remember for everyone" / "the whole team should remember" → use [[REMEMBER_TEAM: ...]]. The system saves it automatically (the marker is hidden from your spoken line).
- ONLY remember things useful long-term. DON'T remember trivia, exclamations, or things true for just one turn. Don't duplicate something already in memory.
""".strip()


HOME_DIR = os.path.expanduser("~")


def _drives() -> list[str]:
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def _detect_folders():
    """Detect the REAL paths of commonly-used folders (even when moved into OneDrive)."""
    home = HOME_DIR
    one = os.path.join(home, "OneDrive")
    spec = [
        # (label, words the Host might use, possible folder names)
        ("Downloads", ["downloads", "download"],            ["Downloads"]),
        ("Documents", ["documents", "docs"],                ["Documents"]),
        ("Desktop",   ["desktop"],                          ["Desktop"]),
        ("Pictures",  ["pictures", "photos", "images"],     ["Pictures"]),
        ("Music",     ["music"],                            ["Music"]),
        ("Videos",    ["videos", "movies"],                 ["Videos"]),
    ]
    found = []
    for label, terms, names in spec:
        path = None
        for base in (home, one):
            for n in names:
                cand = os.path.join(base, n)
                if os.path.isdir(cand):
                    path = cand
                    break
            if path:
                break
        if path:
            found.append((terms, path))
    return found


def build_machine_info() -> str:
    lines = [
        "HOST'S MACHINE INFO — USE THIS TO UNDERSTAND WHERE THE HOST WANTS TO GO AND RESOLVE THE RIGHT PATH:",
        f"- User home folder: {HOME_DIR}",
        f"- Available drives: {', '.join(_drives())}",
        "- When the Host says any of the words below (case-insensitive), "
        "read it as the matching folder and ALWAYS use the ABSOLUTE PATH:",
    ]
    for terms, path in _detect_folders():
        joined = " / ".join(f'"{t}"' for t in terms)
        lines.append(f"    • {joined}  →  {path}")
    lines.append(
        "- Never use relative paths (like just 'Downloads'). "
        "Always scan subfolders too. If you don't find it, re-check the correct absolute path above "
        "BEFORE concluding — don't rush to say 'not there' or 'can't access' before scanning the right place."
    )
    return "\n".join(lines)


MACHINE_INFO = build_machine_info()


def tool_label(name: str) -> str:
    """Label shown while an agent is using a tool."""
    n = (name or "").lower()
    if "search" in n:
        return "🔎 searching the web…"
    if "fetch" in n:
        return "🌐 reading a web page…"
    if n in ("read", "glob", "grep") or n.startswith(("read", "glob", "grep")):
        return "📂 reading documents…"
    if n.startswith("mcp__") or "mcp" in n:
        return "🔌 using an MCP tool…"
    return f"🛠️ using {name}…"


def _parse_bullets(text: str) -> list:
    """Extract a list of 'facts' from a memory-consolidation result (prefer bullet lines), dedup."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    bulleted = [ln.lstrip("-•*").strip() for ln in lines if ln[:1] in "-•*"]
    chosen = bulleted if bulleted else lines
    seen, out = set(), []
    for f in chosen:
        f = f.lstrip("-•* ").strip()
        k = f.lower()
        if f and k not in seen:
            seen.add(k)
            out.append(f)
    return out


class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.key = cfg["key"]
        self.name = cfg["name"]
        self.role = cfg["role"]
        persona = roster.read_persona(self.key)        # body of .claude/agents/<key>.md
        if not persona:
            persona = f"You are {self.name}, the {self.role} on the team."
        # model from the roster (in sync with the frontmatter); fallback to MODEL in config
        self.model = cfg.get("model") or MODEL
        # per-agent capabilities (own caps merged over global DEFAULT_CAPS)
        self.caps = roster.effective_caps(cfg)
        self.system = f"{persona}\n\n{MEETING_RULES}\n\n{MACHINE_INFO}"


class Meeting:
    """One meeting session: has an id, title, participating agents, and a transcript."""

    def __init__(self, mid, title, agent_keys, created_at, log=None, project_id=None):
        team = roster.load()
        sel = set(agent_keys)
        # keep the roster order; if empty, take all
        self.agent_keys = [a["key"] for a in team if a["key"] in sel] or [a["key"] for a in team]
        keys = set(self.agent_keys)
        self.id = mid
        self.title = title
        self.created_at = created_at
        self.project_id = project_id or store.DEFAULT_PROJECT_ID
        self.agents = [Agent(c) for c in team if c["key"] in keys]
        self.log = log or []  # [{"speaker": str, "text": str}, ...]
        # key -> the live claude.exe subprocess for that agent (so the Host can STOP it).
        self.active_procs = {}
        # key -> True when the Host pressed STOP (the read loop bails out instead of waiting
        # for an EOF that — on Windows/ProactorEventLoop — never comes after taskkill).
        self.stop_flags = {}
        # key -> the in-flight stdout read task, so STOP can cancel a hung read directly.
        self.read_tasks = {}

    def stop_agent(self, key: str) -> bool:
        """Kill the running claude.exe of one agent. Returns True if one was running."""
        # Raise the flag + cancel the pending read FIRST, so _attempt's read loop unblocks
        # even though a taskkill'd process never signals EOF on its stdout pipe (Windows quirk).
        self.stop_flags[key] = True
        rt = self.read_tasks.get(key)
        if rt is not None and not rt.done():
            rt.cancel()
        proc = self.active_procs.pop(key, None)
        if proc is None:
            return False
        _kill_proc_tree(proc)
        return True

    def stop_all(self) -> list:
        """Kill every running agent. Returns the list of keys that were running."""
        running = list(self.active_procs.keys())
        for k in running:
            self.stop_agent(k)
        return running

    @classmethod
    def from_dict(cls, d):
        keys = d.get("agent_keys") or roster.keys()
        return cls(d["id"], d.get("title", ""), keys, d.get("created_at", ""),
                   d.get("log", []), d.get("project_id"))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "agent_keys": self.agent_keys,
            "log": self.log,
        }

    def add_human(self, text: str):
        self.log.append({"speaker": "Host (human)", "text": text, "ts": store.now_iso()})

    def _transcript(self) -> str:
        return "\n".join(f"{e['speaker']}: {e['text']}" for e in self.log)

    def _prompt_for(self, agent: Agent) -> str:
        return (
            "The meeting so far:\n\n"
            f"{self._transcript()}\n\n"
            "----------\n"
            f"Now it's YOUR turn ({agent.name} – {agent.role}) to speak next. "
            "Speak naturally, briefly, in character. Reply with only your spoken line."
        )

    # Temporary errors on Anthropic's servers -> retry instead of failing immediately.
    RETRYABLE_HINTS = ("529", "overloaded", "overload", "rate limit",
                       "rate_limit", "503", "502", "504", "timeout", "timed out")
    MAX_ATTEMPTS = 4   # total attempts (1 first + 3 retries)

    async def stream_agent(self, agent: Agent, prompt: str = None):
        """Have one agent speak; yield each text chunk.

        Wraps _attempt() in a loop: if a run fails due to a TEMPORARY error
        (529/overload...) and the agent hasn't produced any text yet, wait (backoff) and
        retry — so one server hiccup doesn't make the agent go silent.
        """
        for attempt in range(self.MAX_ATTEMPTS):
            produced = False          # have we streamed real text to the UI yet
            full = ""
            error_text = None

            async for kind, data in self._attempt(agent, prompt):
                if kind == "__done__":
                    full = data["text"]
                    error_text = data["error"]
                    break
                if kind == "remember":
                    # Host said "remember ..." mid-conversation -> save to own memory
                    if store.append_memory(self.project_id, agent.key, data):
                        yield ("sys", f"🧠 {agent.name} remembered: {data}")
                    continue
                if kind == "remember_team":
                    # SHARED memory for the whole team
                    if store.append_memory(self.project_id, store.TEAM_KEY, data):
                        yield ("sys", f"🏛️ Shared memory (team): {data}")
                    continue
                if kind == "text":
                    produced = True
                yield (kind, data)

            # Got real content -> done.
            if full.strip():
                self.log.append({"speaker": agent.name, "text": full, "ts": store.now_iso()})
                return

            # No text: decide whether to retry.
            retryable = bool(error_text) and any(
                h in error_text.lower() for h in self.RETRYABLE_HINTS
            )
            if retryable and not produced and attempt < self.MAX_ATTEMPTS - 1:
                wait = 2 ** attempt          # 1s, 2s, 4s...
                yield ("tool", f"⏳ server overloaded, retrying in {wait}s…")
                await asyncio.sleep(wait)
                continue

            # Out of retries / unrecoverable error -> report it.
            if error_text:
                msg = f"[error: {error_text}]"
                yield ("text", msg)
                full = msg
            self.log.append({"speaker": agent.name, "text": full, "ts": store.now_iso()})
            return

    async def _attempt(self, agent: Agent, prompt: str = None):
        """Run claude.exe ONCE; yield ('text'|'tool'|'image'|'remember', data) while streaming,
        and finish with ('__done__', {'text': full, 'error': error_text})."""
        if prompt is None:
            prompt = self._prompt_for(agent)

        # Load MEMORY (read fresh each turn, char-capped to save tokens):
        # the team's SHARED memory (every agent sees it) + this agent's OWN memory.
        # Live per-agent capabilities: re-read each turn so toggling them in the UI takes
        # effect on the NEXT turn (no new meeting needed), and so the note below always
        # matches the actual tool flags.
        live = roster.by_key(agent.key)
        caps = roster.effective_caps(live) if live else agent.caps
        # Tell the agent what it ACTUALLY can/cannot do, so it won't pretend to use
        # tools it doesn't have (auto-derived from caps — not hand-written in the persona).
        system = agent.system + "\n\n" + caps_note(caps)
        if MEMORY_ENABLED:
            parts = []
            if MEMORY_TEAM_ENABLED:
                team = store.memory_for_prompt(self.project_id, store.TEAM_KEY, MEMORY_INJECT_MAX_CHARS)
                if team:
                    parts.append(f"{TEAM_HEADER}\n{team}")
            mine = store.memory_for_prompt(self.project_id, agent.key, MEMORY_INJECT_MAX_CHARS)
            if mine:
                parts.append(f"{MEMORY_HEADER}\n{mine}")
            if parts:
                system = system + "\n\n" + "\n\n".join(parts)

        args = [
            CLAUDE_EXE,
            "-p",
            "--model", agent.model,
            "--effort", EFFORT,
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--system-prompt", system,
        ]
        # per-agent capabilities -> tool/permission flags (uses the live caps read above)
        args += tool_args(caps)

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=HOME_DIR,                       # sit in the Host's home folder -> correct paths
            limit=2 ** 22,                      # widen the buffer (4MB)
        )
        # register so the Host can STOP this agent mid-run (see Meeting.stop_agent)
        self.active_procs[agent.key] = proc
        self.stop_flags[agent.key] = False     # fresh turn -> not stopped yet

        # send the prompt via stdin (avoids command-line length limits for long meetings)
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        full = ""
        error_text = None
        buf = b""
        pending = ""   # text buffer to catch [[ATTACH:...]] syntax split across chunks

        # Read by CHUNK then split lines manually — tolerates arbitrarily long JSON lines
        # (e.g. when the agent reads a large file/image). Don't use readline (64KB limit -> crash).
        while True:
            if self.stop_flags.get(agent.key):     # Host pressed STOP between chunks
                break
            # Read in a cancellable task: STOP cancels it directly, so a taskkill'd process
            # (whose stdout never EOFs on Windows) can't wedge this loop forever.
            read_task = asyncio.ensure_future(proc.stdout.read(65536))
            self.read_tasks[agent.key] = read_task
            try:
                chunk = await read_task
            except asyncio.CancelledError:
                break                              # STOP cancelled the read
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                # skip large unrelated lines early (message echo, image tool results...)
                if '"stream_event"' not in line and '"result"' not in line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = ev.get("type")
                if etype == "stream_event":
                    inner = ev.get("event", {})
                    itype = inner.get("type")
                    if itype == "content_block_start":
                        cb = inner.get("content_block", {}) or {}
                        if "tool_use" in (cb.get("type") or ""):
                            yield ("tool", tool_label(cb.get("name", "")))
                    elif itype == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            c = delta.get("text", "")
                            if c:
                                pending += c
                                # pull out any complete [[ATTACH:...]] / [[REMEMBER:...]] markers
                                while True:
                                    mm = MARKER_RE.search(pending)
                                    if not mm:
                                        break
                                    before = pending[:mm.start()]
                                    if before:
                                        full += before
                                        yield ("text", before)
                                    kind_marker = mm.group(1).upper()
                                    val = mm.group(2).strip().strip('"').strip("'").strip("`").strip()
                                    if kind_marker == "ATTACH":
                                        full += f"[image sent: {os.path.basename(val)}]"
                                        yield ("image", val)
                                    elif kind_marker == "REMEMBER_TEAM":
                                        yield ("remember_team", val)   # hidden from the spoken line/transcript
                                    else:   # REMEMBER (own) -> also hidden
                                        yield ("remember", val)
                                    pending = pending[mm.end():]
                                # flush the safe part, keep a tail that might be a partial marker
                                cut = pending.rfind("[[")
                                if cut != -1:
                                    safe, pending = pending[:cut], pending[cut:]
                                elif pending.endswith("["):
                                    safe, pending = pending[:-1], "["
                                else:
                                    safe, pending = pending, ""
                                if safe:
                                    full += safe
                                    yield ("text", safe)
                elif etype == "result":
                    if ev.get("is_error"):
                        error_text = ev.get("result") or "Unknown error from Claude."

        if pending:                       # flush the remaining buffer
            full += pending
            yield ("text", pending)

        # Reap the process. After a STOP the proc is already killed; don't let a hung
        # proc.wait() (same Windows quirk) block forever — cap it.
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
        # Close the pipes so an abandoned (cancelled) read transport doesn't leak / warn.
        try:
            proc._transport.close()
        except Exception:
            pass
        self.active_procs.pop(agent.key, None)   # no longer stoppable once finished
        self.read_tasks.pop(agent.key, None)

        # Report back to stream_agent: streamed content + error (if any) to decide on retry.
        yield ("__done__", {"text": full, "error": error_text})

    # ---------- MEMORY: end-of-meeting distillation + auto-consolidate when bloated ----------

    def _memory_distill_prompt(self, agent: Agent) -> str:
        return (
            "The meeting so far:\n\n"
            f"{self._transcript()}\n\n"
            "----------\n"
            f"THE MEETING IS PAUSED TO SAVE MEMORY. As {agent.name} – {agent.role}, "
            "distill the 1–5 MOST IMPORTANT things you should remember for FUTURE meetings "
            "(decisions made, the Host's direction/preferences, core facts about the project). "
            "Write each one BRIEFLY on its own line, in this exact syntax:\n"
            "[[REMEMBER: ...]]\n"
            "Say nothing else beyond those lines. If there's nothing new worth remembering, write nothing."
        )

    def _team_distill_prompt(self, agent: Agent) -> str:
        return (
            "The meeting so far:\n\n"
            f"{self._transcript()}\n\n"
            "----------\n"
            "THE MEETING IS PAUSED TO SAVE THE TEAM'S SHARED MEMORY. As the meeting SECRETARY, "
            "distill 1–6 SHARED FACTS the WHOLE TEAM needs for later sessions "
            "(project name/positioning, decisions made, constraints, deadlines, agreed terminology). "
            "Do NOT record personal opinions/feelings, only objective facts that were agreed. "
            "Write each one BRIEFLY on its own line, in this exact syntax:\n"
            "[[REMEMBER_TEAM: ...]]\n"
            "Say nothing else. If there's nothing new worth remembering for the team, write nothing."
        )

    def _consolidate_prompt(self, owner: str, current: str) -> str:
        return (
            f"This is ALL of the current memory ({owner}), which may have duplicates, "
            "contradictions, or stale items:\n\n"
            f"{current}\n\n"
            "----------\n"
            "REWRITE it into a tidy list: merge duplicates, REMOVE old items superseded by newer "
            "ones (keep the MOST RECENT by the date in parentheses), drop trivia/no-longer-useful items. "
            "Return ONLY a bullet list (one item per line starting with '- '), "
            "NO preamble, NO explanation, NO [[...]] markers."
        )

    async def _consolidate(self, agent: Agent, key: str, owner: str):
        """Use `agent` to run claude and cleanly rewrite the memory at `key`. Yields ('sys', msg)."""
        try:
            text = ""
            async for kind, data in self._attempt(agent, self._consolidate_prompt(owner, store.read_memory(self.project_id, key))):
                if kind == "text":
                    text += data
                elif kind == "__done__":
                    text = data["text"] or text
            facts = _parse_bullets(text)
            if facts:
                n = store.write_memory(self.project_id, key, facts)
                yield ("sys", f"🧹 Cleaned up {owner}'s memory: {n} tidy items left.")
        except Exception as e:
            yield ("sys", f"[error cleaning up {owner}'s memory: {e}]")

    async def run_memory_save(self, agent: Agent):
        """End of meeting: the agent distills -> saves memory; if bloated, auto-CONSOLIDATE.
        Yields ('sys', message) for the server to show. Does NOT touch the transcript (self.log)."""
        if not MEMORY_ENABLED:
            return
        # 1) Distill the meeting into things to remember
        saved = 0
        try:
            async for kind, data in self._attempt(agent, self._memory_distill_prompt(agent)):
                if kind == "remember" and store.append_memory(self.project_id, agent.key, data):
                    saved += 1
                    yield ("sys", f"🧠 {agent.name} remembered: {data}")
        except Exception as e:
            yield ("sys", f"[error saving {agent.name}'s memory: {e}]")
            return
        if saved == 0:
            yield ("sys", f"🧠 {agent.name}: nothing new worth remembering.")

        # 2) If memory grew past the threshold -> auto-CONSOLIDATE (merge dups, drop contradictions/stale)
        if store.memory_fact_count(self.project_id, agent.key) > MEMORY_MAX_FACTS:
            yield ("sys", f"🧹 {agent.name}'s memory is getting full — tidying up…")
            async for ev in self._consolidate(agent, agent.key, agent.name):
                yield ev

    async def run_team_memory_save(self, agent: Agent):
        """End of meeting: distill the team's SHARED FACTS -> memory/_team.md (agent acts as secretary).
        Yields ('sys', message). Does NOT touch the transcript."""
        if not (MEMORY_ENABLED and MEMORY_TEAM_ENABLED):
            return
        saved = 0
        try:
            async for kind, data in self._attempt(agent, self._team_distill_prompt(agent)):
                if kind == "remember_team" and store.append_memory(self.project_id, store.TEAM_KEY, data):
                    saved += 1
                    yield ("sys", f"🏛️ Shared memory (team): {data}")
        except Exception as e:
            yield ("sys", f"[error saving shared memory: {e}]")
            return
        if saved == 0:
            yield ("sys", "🏛️ Shared memory: nothing new to remember.")
        if store.memory_fact_count(self.project_id, store.TEAM_KEY) > MEMORY_MAX_FACTS:
            yield ("sys", "🧹 Shared memory is getting full — tidying up…")
            async for ev in self._consolidate(agent, store.TEAM_KEY, "Whole team"):
                yield ev
