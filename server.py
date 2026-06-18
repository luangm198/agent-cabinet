"""
Web server for the AI team meeting.

Run:  uvicorn server:app --port 8000
Open: http://localhost:8000
"""

import os
import re
import asyncio
import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Body
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from config import AUTO_RELAY_MAX_HOPS, AUTO_RELAY_MAX_PER_AGENT
from meeting import Meeting, image_data_url
import store
import roster
import documents

MAX_UPLOAD_MB = 25

app = FastAPI(title="AI Team Meeting")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


def all_keys():
    return roster.keys()


def agent_public(keys):
    s = set(keys)
    return [
        {k: a[k] for k in ("key", "name", "role", "emoji", "color")}
        for a in roster.load() if a["key"] in s
    ]


def default_title() -> str:
    return "Meeting " + datetime.datetime.now().strftime("%H:%M %d/%m")


# ---------- HTTP ----------

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/agents")
async def list_agents():
    return agent_public(all_keys())


@app.get("/meetings")
async def meetings(project: str = None):
    """List of meetings; filter by ?project=<pid> if provided."""
    return store.list_all(project)


@app.get("/memory")
async def get_memory(project: str = store.DEFAULT_PROJECT_ID):
    """Memory of one PROJECT: {key: content} for each agent + '_team' for shared memory."""
    mem = store.all_memories(project)
    mem[store.TEAM_KEY] = store.read_memory(project, store.TEAM_KEY)
    return mem


@app.delete("/memory/{key}")
async def clear_agent_memory(key: str, project: str = store.DEFAULT_PROJECT_ID):
    store.clear_memory(project, key)
    return {"ok": True}


# ---------- PROJECTS ----------

@app.get("/projects")
async def get_projects():
    projs = store.list_projects()
    if not projs:                                   # always have at least 1 project
        store.ensure_default()
        projs = store.list_projects()
    return projs


@app.post("/projects")
async def create_project(payload: dict = Body(default={})):
    name = (payload.get("name") or "").strip() or "New project"
    return store.create_project(name)


@app.patch("/projects/{pid}")
async def rename_project(pid: str, payload: dict = Body(default={})):
    d = store.load_project(pid)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    name = (payload.get("name") or "").strip()
    if name:
        d["name"] = name
        store.save_project(d)
    return d


@app.delete("/projects/{pid}")
async def remove_project(pid: str):
    store.delete_project(pid)
    return {"ok": True}


# ---------- TEAM MANAGEMENT (sub-agent roster) ----------

@app.get("/roster")
async def get_roster():
    """All agents with their persona + effective capabilities (for the team-management UI)."""
    return [{**a, "persona": roster.read_persona(a["key"]),
             "caps": roster.effective_caps(a)} for a in roster.load()]


def _agent_payload(payload: dict, key: str) -> dict:
    return {
        "key": key,
        "name": (payload.get("name") or "").strip() or key,
        "role": (payload.get("role") or "").strip(),
        "emoji": (payload.get("emoji") or "🤖").strip(),
        "color": (payload.get("color") or "#8b93a7").strip(),
        "model": (payload.get("model") or "opus").strip(),
        "caps": payload.get("caps"),     # normalized in roster.upsert; None -> keep existing
    }


@app.post("/roster")
async def create_agent(payload: dict = Body(...)):
    key = (payload.get("key") or "").strip().lower()
    if not roster.VALID_KEY.match(key):
        return JSONResponse(
            {"error": "invalid key (only a-z, 0-9, _ , -; must start with a letter/number)."},
            status_code=400)
    if roster.by_key(key):
        return JSONResponse({"error": f"Agent '{key}' already exists."}, status_code=400)
    entry = roster.upsert(_agent_payload(payload, key), payload.get("persona") or "")
    return {"ok": True, "agent": entry}


@app.put("/roster/{key}")
async def update_agent(key: str, payload: dict = Body(...)):
    if not roster.by_key(key):
        return JSONResponse({"error": "not found"}, status_code=404)
    entry = roster.upsert(_agent_payload(payload, key), payload.get("persona"))
    return {"ok": True, "agent": entry}


@app.delete("/roster/{key}")
async def delete_agent(key: str):
    if not roster.delete(key):
        return JSONResponse(
            {"error": "Cannot delete (at least 1 agent must remain)."}, status_code=400)
    return {"ok": True}


@app.delete("/meetings/{mid}")
async def delete_meeting(mid: str):
    store.delete(mid)
    return {"ok": True}


@app.post("/meetings/{mid}/upload")
async def upload_doc(mid: str, file: UploadFile = File(...)):
    """Host uploads a document/image to the meeting. Save the file, extract its content,
    then insert it into the log so the sub-agents can read it on the next turn."""
    d = store.load(mid)
    if not d:
        return JSONResponse({"error": "Meeting not found."}, status_code=404)

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        return JSONResponse(
            {"error": f"File too large (>{MAX_UPLOAD_MB}MB)."}, status_code=400
        )

    saved_path, safe_name = store.save_upload(mid, file.filename, raw)
    is_img = documents.is_image(safe_name)

    if is_img:
        text = (
            f"📎 [Image attached by Host: {safe_name}] — path: {saved_path}\n"
            "The Host just added this image to the meeting. When you need to VIEW the image "
            "content directly, use the image-reading tool (Read) to open the path above."
        )
    else:
        content = documents.extract_text(saved_path)
        text = (
            f"📎 [Document attached by Host: {safe_name}] — path: {saved_path}\n"
            f"DOCUMENT CONTENT:\n{content}"
        )

    upload_meta = {
        "name": safe_name,
        "url": f"/meetings/{mid}/file/{safe_name}",
        "is_image": is_img,
    }
    entry = {"speaker": "Host (human)", "text": text, "upload": upload_meta, "ts": store.now_iso()}
    d.setdefault("log", []).append(entry)
    store.save(d)
    return {"ok": True, "upload": upload_meta}


@app.get("/meetings/{mid}/file/{name}")
async def meeting_file(mid: str, name: str):
    """Serve an uploaded file (for the UI to show images / re-download)."""
    path = store.upload_path(mid, name)
    if not os.path.isfile(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/meetings/{mid}/export")
async def export_meeting(mid: str):
    d = store.load(mid)
    if not d:
        return JSONResponse({"error": "not found"}, status_code=404)
    path = store.export_docx(d)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", (d.get("title") or "meeting")).strip() or "meeting"
    return FileResponse(
        path,
        filename=f"{safe}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------- WebSocket ----------

@app.websocket("/ws")
async def ws(websocket: WebSocket):
    """Each agent = its own 'laptop': it has a work queue + an independently-running worker.
    Work for the same agent runs sequentially; different agents run IN PARALLEL."""
    await websocket.accept()

    state = {
        "meeting": None,
        "auto_relay": False,       # ON/OFF auto-relay (per the UI toggle)
        "hops_left": 0,            # remaining relay budget for the Host's current message
        "chain_counts": {},        # key -> how many times this agent spoke in the current relay chain
        "enabled_agents": [],      # the agents enabled at the moment the Host sent the message
        "stopped_keys": set(),     # agents the Host just STOPPED -> suppress their auto-relay handoff
    }
    out_queue: asyncio.Queue = asyncio.Queue()   # every outgoing event goes through here (single sender)
    agent_queues: dict = {}                       # key -> work queue assigned to the agent
    agent_workers: dict = {}                      # key -> the agent's worker task (laptop)
    save_lock = asyncio.Lock()

    async def send(obj):
        await out_queue.put(obj)

    async def sender():
        # A single send loop -> avoids multiple workers clobbering frames on the same socket.
        while True:
            obj = await out_queue.get()
            if obj is None:
                break
            try:
                await websocket.send_json(obj)
            except Exception:
                break

    sender_task = asyncio.create_task(sender())

    async def save_meeting():
        m = state["meeting"]
        if m is not None:
            async with save_lock:
                store.save(m.to_dict())

    def maybe_relay(speaker, spoken):
        """If auto-relay is ON: scan @name in `speaker`'s message, queue a turn for each
        mentioned agent (if enabled), within the caps. Returns (handoffs, dropped) where
        `dropped` is a list of (agent, reason) for mentions skipped because a cap was hit —
        so the caller can tell the Host why that teammate didn't get pulled in (instead of
        the relay silently going nowhere)."""
        if not state["auto_relay"]:
            return [], []
        low = (spoken or "").lower()
        handoffs, dropped = [], []
        for a in state["enabled_agents"]:
            if a.key == speaker.key:
                continue
            if f"@{a.key}" not in low and f"@{a.name.lower()}" not in low:
                continue
            # mentioned, but a cap may block it -> record WHY so the Host gets told
            if state["chain_counts"].get(a.key, 0) >= AUTO_RELAY_MAX_PER_AGENT:
                dropped.append((a, "per_agent"))
                continue
            if state["hops_left"] <= 0:
                dropped.append((a, "hops"))
                continue
            state["hops_left"] -= 1                       # deduct the budget IMMEDIATELY (synchronously)
            state["chain_counts"][a.key] = state["chain_counts"].get(a.key, 0) + 1
            handoffs.append(a)
        return handoffs, dropped

    async def run_one_task(agent, task_text):
        """One turn of an agent working & speaking; stream the result to the UI."""
        await send({"type": "agent_start", "key": agent.key,
                    "name": agent.name, "task": task_text})
        spoken = ""
        try:
            async for kind, payload in state["meeting"].stream_agent(agent):
                if kind == "text":
                    spoken += payload
                    await send({"type": "token", "key": agent.key, "text": payload})
                elif kind == "tool":
                    await send({"type": "tool", "key": agent.key, "text": payload})
                elif kind == "sys":
                    await send({"type": "sys", "text": payload})        # e.g. "🧠 saved to memory…"
                elif kind == "image":
                    img = image_data_url(payload)
                    if img:
                        await send({"type": "image", "key": agent.key,
                                    "src": img[0], "name": img[1]})
                    else:
                        await send({"type": "token", "key": agent.key,
                                    "text": f"[could not open image: {payload}]"})
        except Exception as e:
            await send({"type": "token", "key": agent.key,
                        "text": f"[error while {agent.name} was speaking: {e}]"})
        await send({"type": "agent_done", "key": agent.key})
        await save_meeting()

        # If the Host STOPPED this agent, don't auto-relay off its (partial) words.
        if agent.key in state["stopped_keys"]:
            state["stopped_keys"].discard(agent.key)
            return

        # AUTO-RELAY: if the speaker @mentioned someone (enabled) -> queue a turn for them.
        # If a mention was dropped because a cap was hit, tell the Host why so it doesn't
        # look like the relay silently broke.
        handoffs, dropped = maybe_relay(agent, spoken)
        for nxt in handoffs:
            await send({"type": "sys", "text": f"🔄 {agent.name} hands off to {nxt.name}…"})
            ensure_worker(nxt)
            await agent_queues[nxt.key].put(("chat", f"{agent.name} just mentioned you"))
        for nxt, reason in dropped:
            if reason == "hops":
                why = f"the relay limit ({AUTO_RELAY_MAX_HOPS} hops per message) was reached"
            else:
                why = f"they already spoke {AUTO_RELAY_MAX_PER_AGENT}× in this relay chain"
            await send({"type": "sys",
                        "text": f"⏸️ @{nxt.name} wasn't pulled in — {why}. "
                                f"Send a message (e.g. \"@{nxt.key} …\") to continue."})

    async def run_memory_task(agent):
        """End of meeting: the agent distills & saves its OWN memory (runs in background, sys only)."""
        try:
            async for kind, payload in state["meeting"].run_memory_save(agent):
                if kind == "sys":
                    await send({"type": "sys", "text": payload})
        except Exception as e:
            await send({"type": "sys", "text": f"[error saving {agent.name}'s memory: {e}]"})

    async def run_team_task(agent):
        """End of meeting: distill & save the team's SHARED memory (the agent acts as secretary)."""
        try:
            async for kind, payload in state["meeting"].run_team_memory_save(agent):
                if kind == "sys":
                    await send({"type": "sys", "text": payload})
        except Exception as e:
            await send({"type": "sys", "text": f"[error saving shared memory: {e}]"})

    async def agent_worker(agent):
        q = agent_queues[agent.key]
        try:
            while True:
                item = await q.get()
                if item is None:
                    break
                kind, payload = item
                if kind == "save":
                    await run_memory_task(agent)
                elif kind == "save_team":
                    await run_team_task(agent)
                else:                       # "chat"
                    await run_one_task(agent, payload)
        except asyncio.CancelledError:
            pass

    def reset_workers():
        for t in agent_workers.values():
            t.cancel()
        agent_workers.clear()
        agent_queues.clear()

    def ensure_worker(agent):
        if agent.key not in agent_workers:
            agent_queues[agent.key] = asyncio.Queue()
            agent_workers[agent.key] = asyncio.create_task(agent_worker(agent))

    def drain_queue(q):
        """Drop all not-yet-started tasks from a worker's queue."""
        if q is None:
            return
        try:
            while True:
                q.get_nowait()
        except asyncio.QueueEmpty:
            pass

    try:
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")

            # ----- open/create a meeting -----
            if mtype == "init":
                reset_workers()                       # clear the old meeting's laptops
                meeting = None
                mid = data.get("meeting_id")
                if mid:
                    d = store.load(mid)
                    if d:
                        meeting = Meeting.from_dict(d)
                if meeting is None:
                    pid = data.get("project_id")
                    if not pid or not store.load_project(pid):
                        pid = store.ensure_default()  # always attach to a valid project
                    title = (data.get("title") or "").strip() or default_title()
                    keys_all = all_keys()
                    sel = data.get("agents") or keys_all
                    keys = [k for k in keys_all if k in set(sel)] or keys_all
                    meeting = Meeting(store.new_id(), title, keys, store.now_iso(), project_id=pid)
                    store.save(meeting.to_dict())
                state["meeting"] = meeting

                await send({
                    "type": "meeting",
                    "id": meeting.id,
                    "title": meeting.title,
                    "project_id": meeting.project_id,
                    "agents": agent_public(meeting.agent_keys),
                    "log": meeting.log,
                })
                continue

            # ----- assign work (does not lock the input; whoever is assigned does the work) -----
            if mtype == "chat":
                meeting = state["meeting"]
                if meeting is None:
                    continue
                text = (data.get("text") or "").strip()
                if not text:
                    continue

                # sync the log from disk: catch documents the Host just uploaded (via HTTP)
                fresh = store.load(meeting.id)
                if fresh:
                    meeting.log = fresh.get("log", meeting.log)

                meeting.add_human(text)
                await save_meeting()                  # save the Host message immediately so every agent sees it
                low = text.lower()

                # currently ENABLED agents (disabled = never receives work)
                enabled_keys = data.get("enabled")
                if enabled_keys is None:
                    enabled = list(meeting.agents)
                else:
                    s = set(enabled_keys)
                    enabled = [a for a in meeting.agents if a.key in s]

                # configure "auto-relay" for this message (reset the budget per Host message)
                state["auto_relay"] = bool(data.get("relay"))
                state["enabled_agents"] = enabled
                state["hops_left"] = AUTO_RELAY_MAX_HOPS
                state["chain_counts"] = {}

                # address someone by name among the enabled ones
                targeted = []
                for a in enabled:
                    nm = a.name.lower()
                    if (f"@{a.key}" in low or f"@{nm}" in low
                            or low.strip() == nm
                            or re.match(rf"^\s*{re.escape(nm)}\s*[,:.\-！?!]", low)):
                        targeted.append(a)

                speakers = targeted if targeted else enabled

                if not speakers:
                    await send({
                        "type": "sys",
                        "text": "(No agents are enabled — click a name above to re-enable.)",
                    })
                    continue

                # assign work to each agent's queue -> workers run IN PARALLEL
                for agent in speakers:
                    ensure_worker(agent)
                    await agent_queues[agent.key].put(("chat", text))
                continue

            # ----- STOP a running agent (key given) or ALL of them (no key) -----
            if mtype == "stop":
                meeting = state["meeting"]
                if meeting is None:
                    continue
                key = data.get("key")
                if key:
                    drain_queue(agent_queues.get(key))     # drop this agent's pending turns
                    state["stopped_keys"].add(key)         # suppress its relay handoff
                    if meeting.stop_agent(key):
                        await send({"type": "sys",
                                    "text": f"⏹ Stopped {roster.name_of(key) or key}."})
                else:
                    state["hops_left"] = 0                  # block auto-relay from spawning more
                    for q in agent_queues.values():
                        drain_queue(q)
                    running = meeting.stop_all()
                    state["stopped_keys"].update(running)
                    await send({"type": "sys",
                                "text": "⏹ Stopped all agents."
                                        if running else "(Nothing is running.)"})
                continue

            # ----- end-of-meeting memory save: each enabled agent distills on its own -----
            if mtype == "save_memory":
                meeting = state["meeting"]
                if meeting is None:
                    continue
                fresh = store.load(meeting.id)
                if fresh:
                    meeting.log = fresh.get("log", meeting.log)
                enabled_keys = data.get("enabled")
                if enabled_keys is None:
                    targets = list(meeting.agents)
                else:
                    s = set(enabled_keys)
                    targets = [a for a in meeting.agents if a.key in s]
                if not targets:
                    await send({"type": "sys", "text": "(No agents enabled to save memory.)"})
                    continue
                await send({"type": "sys", "text": "💾 Saving memory for the team…"})
                for agent in targets:
                    ensure_worker(agent)
                    await agent_queues[agent.key].put(("save", None))
                # SHARED memory: one agent acts as secretary (prefer CEO 'linh' if enabled)
                sec = next((a for a in targets if a.key == "linh"), targets[0])
                await agent_queues[sec.key].put(("save_team", None))
                continue

    except WebSocketDisconnect:
        pass
    finally:
        reset_workers()
        await out_queue.put(None)
        try:
            await asyncio.wait_for(sender_task, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            sender_task.cancel()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
