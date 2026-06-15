"""
roster.py — DYNAMIC sub-agent TEAM management (so the UI can add/edit/delete the team).

Source of truth:
- .claude/agents/agents.json : the ORDERED list of agents,
  each entry { key, name, role, emoji, color, model }.
- .claude/agents/<key>.md   : persona (body) + standard Claude Code frontmatter.
  Regenerated/synced whenever you SAVE via the UI -> keeps the "standard sub-agent format".

First run: if agents.json doesn't exist -> seed it from config.AGENTS (the default list),
taking the model from the existing .md frontmatter. Does NOT overwrite .md on seed (keeps the original persona).
"""

import os
import re
import json

from config import AGENTS as DEFAULT_AGENTS, MODEL, DEFAULT_CAPS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_DIR = os.path.join(BASE_DIR, ".claude", "agents")
ROSTER_FILE = os.path.join(AGENTS_DIR, "agents.json")

# the key is the file name + the reference in meetings/memory -> a safe constraint, IMMUTABLE after creation.
VALID_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]{0,30}$")

META_FIELDS = ("key", "name", "role", "emoji", "color", "model")

CAPS_KEYS = ("tools", "mcp", "skills", "full")


def norm_caps(raw):
    """Coerce a caps dict to {tools,mcp,skills,full: bool}, or None if not a dict."""
    if not isinstance(raw, dict):
        return None
    return {k: bool(raw.get(k)) for k in CAPS_KEYS}


def effective_caps(entry: dict) -> dict:
    """The agent's effective capabilities: its own caps merged over the global DEFAULT_CAPS.
    An agent with no "caps" field falls back to the global defaults (current behavior)."""
    caps = dict(DEFAULT_CAPS)
    own = entry.get("caps")
    if isinstance(own, dict):
        for k in CAPS_KEYS:
            if k in own:
                caps[k] = bool(own[k])
    return caps


def _ensure_dir():
    os.makedirs(AGENTS_DIR, exist_ok=True)


def persona_path(key: str) -> str:
    return os.path.join(AGENTS_DIR, f"{key}.md")


def parse_frontmatter(text: str):
    """Split the YAML frontmatter (--- ... ---) from the body. Returns (meta dict, body)."""
    meta, body = {}, text
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


def read_persona(key: str) -> str:
    """Read the body (system prompt/persona) in .claude/agents/<key>.md."""
    p = persona_path(key)
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            _, body = parse_frontmatter(f.read())
        return body
    return ""


def _write_md(entry: dict, persona: str):
    """Write the standard Claude Code sub-agent file: frontmatter + persona body."""
    _ensure_dir()
    key = entry["key"]
    fm = (
        "---\n"
        f"name: {key}\n"
        f"description: {entry.get('name', key)} — {entry.get('role', '')}\n"
        f"model: {entry.get('model', MODEL)}\n"
        f"color: {entry.get('color', '')}\n"
        "---\n\n"
    )
    with open(persona_path(key), "w", encoding="utf-8") as f:
        f.write(fm + (persona or "").strip() + "\n")


def _save_raw(items: list):
    _ensure_dir()
    with open(ROSTER_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _seed() -> list:
    """Create agents.json the first time from the default list + model from any existing .md."""
    items = []
    for a in DEFAULT_AGENTS:
        key = a["key"]
        model = MODEL
        p = persona_path(key)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                meta, _ = parse_frontmatter(f.read())
            model = meta.get("model", MODEL)
        items.append({
            "key": key, "name": a["name"], "role": a["role"],
            "emoji": a["emoji"], "color": a["color"], "model": model,
        })
    _save_raw(items)
    return items


def load() -> list:
    """The current (ordered) list of agents. Auto-seeds if missing."""
    _ensure_dir()
    if not os.path.isfile(ROSTER_FILE):
        return _seed()
    try:
        with open(ROSTER_FILE, encoding="utf-8") as f:
            items = json.load(f)
        if isinstance(items, list) and items:
            return items
    except Exception:
        pass
    return _seed()


def keys() -> list:
    return [a["key"] for a in load()]


def by_key(key: str):
    return next((a for a in load() if a["key"] == key), None)


def name_of(key: str) -> str:
    a = by_key(key)
    return a["name"] if a else key


def public() -> list:
    """The display fields (for the roster/picker), preserving order."""
    return [{k: a.get(k) for k in ("key", "name", "role", "emoji", "color")} for a in load()]


def upsert(entry: dict, persona=None) -> dict:
    """Add or update one agent. `persona=None` -> keep the old persona.
    Always re-syncs the standard .md file. Returns the saved entry."""
    items = load()
    key = entry["key"]
    merged = None
    clean = {k: v for k, v in entry.items() if k in META_FIELDS and v is not None}
    caps = norm_caps(entry.get("caps"))
    if caps is not None:
        clean["caps"] = caps
    for i, a in enumerate(items):
        if a["key"] == key:
            merged = {**a, **clean}
            items[i] = merged
            break
    if merged is None:
        merged = {"model": MODEL, **clean}
        items.append(merged)
    _save_raw(items)
    body = persona if persona is not None else read_persona(key)
    _write_md(merged, body)
    return merged


def delete(key: str) -> bool:
    """Remove one agent from the roster + its .md file. Won't delete the last one."""
    items = load()
    if len(items) <= 1 or not any(a["key"] == key for a in items):
        return False
    _save_raw([a for a in items if a["key"] != key])
    p = persona_path(key)
    if os.path.isfile(p):
        os.remove(p)
    return True
