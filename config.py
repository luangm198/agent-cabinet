"""
A.I agent team configuration.

- Each agent's personality: a standard Claude Code sub-agent file in .claude/agents/<key>.md
  (YAML frontmatter: name/description/model/color + body = system prompt).
- This file holds the display fields (name/role/emoji/color) + general config + tool config.

Runs via your existing Claude login (Max plan) — no API key needed.
"""

import os

# Default brain (if an agent's frontmatter has no model). "opus" = claude-opus-4-8, 1M context.
MODEL = "opus"

# How hard it "thinks" per turn: low | medium | high | xhigh | max
EFFORT = "medium"

# ============================================================
#  TOOLS FOR THE SUB-AGENTS
# ============================================================
# Enable so agents can use tools (web search, read files, MCP). Off = talk only.
ENABLE_TOOLS = True

# Block tools that could MODIFY/DELETE the machine, for safety — agents can still READ & SEARCH.
# (Ignored if FULL_CONTROL = True below.)
DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "KillShell"]

# Where agents are allowed to READ.
#   "ALL"  = full access to EVERY drive on the machine (read anywhere).
#   or a list of specific folders, e.g.: DOCS_DIRS = [r"C:\Users\<you>\Documents"]
DOCS_DIRS = "ALL"

# ⚠️ DANGEROUS: let agents MODIFY / DELETE / RUN COMMANDS on the machine (unblocks Bash/Write/Edit).
# Default False = read & search only (recommended). Set True ONLY if you truly want to grant
# the agents full control of your machine.
FULL_CONTROL = False

# Let agents use any configured MCP servers (Notion, Drive, Gmail, Calendar...).
# ⚠️ Some MCP tools can SEND/CREATE (send mail, create pages). Set False to disable MCP entirely.
ALLOW_MCP = True

# Let agents use Claude Code skills (invoked as /skill-name). When off, the CLI is launched
# with --disable-slash-commands, which disables all skills for that agent.
ALLOW_SKILLS = False

# Global DEFAULT capabilities. Each agent may OVERRIDE these per-agent via the "👥 Team" UI
# (stored in agents.json as "caps"). An agent without its own "caps" falls back to these.
DEFAULT_CAPS = {
    "tools":  ENABLE_TOOLS,   # master switch: web search, read files
    "mcp":    ALLOW_MCP,      # MCP servers
    "skills": ALLOW_SKILLS,   # Claude Code skills (experimental)
    "full":   FULL_CONTROL,   # 🔴 write/edit/delete & run commands
}

# ============================================================
#  PER-AGENT MEMORY (persists across meetings)
# ============================================================
# Each agent has a memory/<key>.md file, recalled in later meetings.
MEMORY_ENABLED = True
# The team's SHARED memory (memory/_team.md) — facts the whole team knows, loaded into EVERY agent.
MEMORY_TEAM_ENABLED = True
# Above this number of "facts" -> auto-CONSOLIDATE memory (merge dups, drop stale/contradictory, keep newest).
MEMORY_MAX_FACTS = 40
# Max characters of memory loaded into the "brain" each turn (saves tokens; prefers the most recent).
MEMORY_INJECT_MAX_CHARS = 4000

# ============================================================
#  AUTO-RELAY BETWEEN AGENTS (toggled in the UI)
# ============================================================
# When ON: after an agent speaks, if it @mentions another (enabled) agent, that agent takes the next turn.
# Capped so it does NOT run forever / burn quota.
AUTO_RELAY_MAX_HOPS = 4        # max relay hops per Host message
AUTO_RELAY_MAX_PER_AGENT = 2   # max times one agent speaks within a single relay chain

# ============================================================

# DEFAULT (seed) LIST — only used the first time to create .claude/agents/agents.json.
# After that the team is managed DYNAMICALLY via the "👥 Team" UI (roster.py). Editing here only
# matters when agents.json doesn't exist yet. key must match the .claude/agents/<key>.md file name.
AGENTS = [
    {"key": "linh", "name": "Linh", "role": "CEO / Founder",      "emoji": "👑", "color": "#E07A5F"},
    {"key": "khoa", "name": "Khoa", "role": "CTO / Engineering",  "emoji": "🛠️", "color": "#3D9970"},
    {"key": "mai",  "name": "Mai",  "role": "Product Manager",    "emoji": "📋", "color": "#0074D9"},
    {"key": "tung", "name": "Tung", "role": "Designer (UX/UI)",   "emoji": "🎨", "color": "#B10DC9"},
    {"key": "ha",   "name": "Ha",   "role": "Marketing / Growth", "emoji": "📈", "color": "#FF851B"},
]
