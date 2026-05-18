#!/usr/bin/env python3
"""
Local server for Claude Local v2 — wraps claude-agent-sdk behind a browser UI.

Endpoints:
  GET  /                  -> index.html
  GET  /api/config        -> { baseUrl, hasToken }
  POST /api/config        -> save baseUrl / token to ~/.claude-web/config.json
  POST /api/session       -> { session_id }, spins up a ClaudeSDKClient
  POST /api/session/new   -> reset session (new chat)
  POST /api/messages      -> SSE stream of typed events for one turn
  POST /api/permission    -> { request_id, decision } resolves a pending tool prompt
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    UserMessage,
    SystemMessage,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ToolUseBlock,
    ToolResultBlock,
    PermissionResultAllow,
    PermissionResultDeny,
)

# ---------- Configuration ----------

PORT = int(os.environ.get("CLAUDE_WEB_PORT", "8765"))
HERE = Path(__file__).resolve().parent
CONFIG_FILE = Path.home() / ".claude-web" / "config.json"
SESSION_TTL_SECONDS = 30 * 60     # idle eviction
PERMISSION_TIMEOUT = 10 * 60      # max time to wait for the user to click a button
HEARTBEAT_GRACE_SECONDS = 60      # shut down N seconds after the last heartbeat
HEARTBEAT_STARTUP_GRACE = 30      # don't auto-shutdown for the first N seconds after boot

# Tracks the most recent browser activity (heartbeat or message). When this
# is older than HEARTBEAT_GRACE_SECONDS the server self-terminates.
_last_activity: float = 0.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("claude-local")


# ---------- Persistent config (token + base URL) ----------

def load_config() -> dict:
    cfg: dict = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
        except json.JSONDecodeError:
            cfg = {}
    if not cfg.get("baseUrl") and os.environ.get("ANTHROPIC_BASE_URL"):
        cfg["baseUrl"] = os.environ["ANTHROPIC_BASE_URL"]
    if not cfg.get("token") and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        cfg["token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def export_auth_env() -> bool:
    """Push baseUrl/token from the persisted config into os.environ so the
    bundled Claude Code CLI subprocess inherits them."""
    cfg = load_config()
    if cfg.get("baseUrl"):
        os.environ["ANTHROPIC_BASE_URL"] = cfg["baseUrl"]
    if cfg.get("token"):
        os.environ["ANTHROPIC_AUTH_TOKEN"] = cfg["token"]
    return bool(cfg.get("baseUrl") and cfg.get("token"))


# ---------- Session ----------

class Session:
    """One ClaudeSDKClient per browser tab. Holds approval state."""

    def __init__(self, sid: str):
        self.sid = sid
        self.client: ClaudeSDKClient | None = None
        self.always_allow: set[str] = set()
        self.pending: dict[str, asyncio.Future] = {}
        self.current_queue: asyncio.Queue | None = None
        self.last_activity = time.monotonic()
        self.lock = asyncio.Lock()  # serialize turns

    async def start(self) -> None:
        async def can_use_tool(tool_name: str, input_data: dict, context) -> Any:
            if tool_name in self.always_allow:
                log.info("auto-allow [%s] %s", tool_name, _summarize(tool_name, input_data))
                return PermissionResultAllow(updated_input=input_data)

            req_id = uuid.uuid4().hex
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            self.pending[req_id] = fut
            await self.broadcast({
                "type": "permission_request",
                "id": req_id,
                "tool": tool_name,
                "input": input_data,
                "summary": _summarize(tool_name, input_data),
            })
            try:
                decision = await asyncio.wait_for(fut, timeout=PERMISSION_TIMEOUT)
            except asyncio.TimeoutError:
                self.pending.pop(req_id, None)
                log.warning("permission timeout [%s]", tool_name)
                return PermissionResultDeny(
                    message="The user did not respond to the approval prompt in time."
                )
            if decision == "always":
                self.always_allow.add(tool_name)
            if decision in ("allow", "always"):
                return PermissionResultAllow(updated_input=input_data)
            return PermissionResultDeny(
                message=f"The user denied the {tool_name} call in the browser."
            )

        opts = ClaudeAgentOptions(
            permission_mode="default",
            setting_sources=["user", "project"],
            cwd=os.path.expanduser("~"),
            can_use_tool=can_use_tool,
            include_partial_messages=True,
        )
        self.client = ClaudeSDKClient(options=opts)
        await self.client.connect()
        log.info("session %s connected", self.sid[:8])

    async def close(self) -> None:
        # Resolve any pending approvals as denials so we don't leak futures.
        for req_id, fut in list(self.pending.items()):
            if not fut.done():
                fut.set_result("deny")
            self.pending.pop(req_id, None)
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception as e:
                log.warning("session %s disconnect error: %s", self.sid[:8], e)
            self.client = None

    async def broadcast(self, evt: dict) -> None:
        """Send a typed event to the current SSE stream, if any."""
        if self.current_queue is not None:
            try:
                await self.current_queue.put(json.dumps(evt))
            except Exception as e:
                log.warning("broadcast failed: %s", e)


# Global session registry
sessions: dict[str, Session] = {}


def _summarize(tool: str, input_data: dict) -> str:
    """One-line human-readable summary of a tool call for the approval card."""
    try:
        if tool == "Bash":
            return str(input_data.get("command", ""))[:240]
        if tool in ("Read", "Glob", "Grep"):
            return str(input_data.get("file_path") or input_data.get("path") or
                       input_data.get("pattern") or "")
        if tool == "Edit":
            f = input_data.get("file_path", "")
            return f"{f}"
        if tool == "Write":
            return str(input_data.get("file_path", ""))
        if tool == "WebFetch":
            return str(input_data.get("url", ""))
        if tool == "Agent":
            return str(input_data.get("description") or input_data.get("subagent_type", ""))
        return json.dumps(input_data)[:240]
    except Exception:
        return tool


# ---------- HTTP handlers ----------

async def get_config(req: web.Request) -> web.Response:
    cfg = load_config()
    return web.json_response({
        "baseUrl": cfg.get("baseUrl", ""),
        "hasToken": bool(cfg.get("token")),
    })


async def post_config(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    cfg = load_config()
    for k in ("baseUrl", "token"):
        v = body.get(k)
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()
    save_config(cfg)
    export_auth_env()
    return web.json_response({"ok": True})


async def post_session(req: web.Request) -> web.Response:
    if not export_auth_env():
        return web.json_response(
            {"error": "Auth not configured. Open Settings and paste a token."},
            status=400,
        )
    sid = uuid.uuid4().hex
    s = Session(sid)
    try:
        await s.start()
    except Exception as e:
        log.exception("session start failed")
        return web.json_response({"error": f"Could not start session: {e}"}, status=500)
    sessions[sid] = s
    log.info("new session %s (total: %d)", sid[:8], len(sessions))
    return web.json_response({"session_id": sid})


async def get_session(req: web.Request) -> web.Response:
    """Cheap ping to check if a session_id is still alive on this server."""
    sid = req.match_info["sid"]
    if sid in sessions:
        return web.json_response({"ok": True})
    return web.json_response({"error": "session not found"}, status=404)


async def post_session_new(req: web.Request) -> web.Response:
    sid = req.match_info["sid"]
    old = sessions.pop(sid, None)
    if old is not None:
        await old.close()
    if not export_auth_env():
        return web.json_response(
            {"error": "Auth not configured."},
            status=400,
        )
    new_sid = uuid.uuid4().hex
    s = Session(new_sid)
    try:
        await s.start()
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    sessions[new_sid] = s
    return web.json_response({"session_id": new_sid})


async def post_messages(req: web.Request) -> web.StreamResponse:
    sid = req.headers.get("X-Session-Id") or req.query.get("session_id", "")
    s = sessions.get(sid)
    if s is None:
        return web.json_response(
            {"error": "Unknown or expired session_id. Reload the page."},
            status=400,
        )

    try:
        body = await req.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    user_text = body.get("message") or body.get("prompt") or ""
    if not user_text.strip():
        return web.json_response({"error": "empty message"}, status=400)

    global _last_activity
    s.last_activity = time.monotonic()
    _last_activity = s.last_activity

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
    await resp.prepare(req)

    queue: asyncio.Queue = asyncio.Queue()

    # Pump events from the queue to the SSE response.
    async def pump():
        while True:
            data = await queue.get()
            if data is None:
                break
            try:
                await resp.write(f"data: {data}\n\n".encode("utf-8"))
            except (ConnectionResetError, asyncio.CancelledError):
                break
        try:
            await resp.write_eof()
        except Exception:
            pass

    pump_task = asyncio.create_task(pump())

    # Only one turn per session at a time.
    if s.lock.locked():
        await queue.put(json.dumps({
            "type": "error",
            "message": "Another message is in progress in this session.",
        }))
        await queue.put(None)
        await pump_task
        return resp

    async with s.lock:
        s.current_queue = queue
        try:
            assert s.client is not None
            await s.client.query(user_text)
            async for msg in s.client.receive_response():
                await _emit(s, msg)
            await s.broadcast({"type": "done"})
        except asyncio.CancelledError:
            log.info("session %s turn cancelled", s.sid[:8])
            raise
        except Exception as e:
            log.exception("turn error")
            await s.broadcast({"type": "error", "message": str(e)})
        finally:
            s.current_queue = None
            await queue.put(None)
            try:
                await pump_task
            except Exception:
                pass

    return resp


async def _emit(s: Session, msg: Any) -> None:
    """Translate one SDK message into typed SSE events for the browser."""
    if isinstance(msg, AssistantMessage):
        for blk in msg.content:
            if isinstance(blk, TextBlock):
                # Final text — sent in addition to the per-token deltas (see
                # StreamEvent below) so the browser can collapse incomplete
                # streamed text into the canonical version on turn end.
                await s.broadcast({"type": "text_block", "text": blk.text})
            elif isinstance(blk, ToolUseBlock):
                await s.broadcast({
                    "type": "tool_use",
                    "id": blk.id,
                    "name": blk.name,
                    "input": blk.input,
                })
            elif isinstance(blk, ToolResultBlock):
                await s.broadcast({
                    "type": "tool_result",
                    "tool_use_id": blk.tool_use_id,
                    "content": _coerce_tool_content(blk.content),
                    "is_error": bool(getattr(blk, "is_error", False)),
                })
    elif isinstance(msg, UserMessage):
        # Tool results come back as UserMessage(content=[ToolResultBlock(...)])
        for blk in (msg.content if isinstance(msg.content, list) else []):
            if isinstance(blk, ToolResultBlock):
                await s.broadcast({
                    "type": "tool_result",
                    "tool_use_id": blk.tool_use_id,
                    "content": _coerce_tool_content(blk.content),
                    "is_error": bool(getattr(blk, "is_error", False)),
                })
    elif isinstance(msg, StreamEvent):
        # Token-level streaming. Pass the raw Anthropic SSE event straight through.
        await s.broadcast({"type": "stream_event", "event": msg.event})
    elif isinstance(msg, ResultMessage):
        usage = getattr(msg, "usage", None)
        await s.broadcast({
            "type": "turn_result",
            "subtype": getattr(msg, "subtype", None),
            "usage": usage if isinstance(usage, dict) else None,
        })
    # SystemMessage and other lifecycle messages: not surfaced to the browser.


def _coerce_tool_content(content: Any) -> str:
    """Tool result content can be a string, a list of blocks, or arbitrary —
    flatten to a string for the browser to render."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


async def post_heartbeat(req: web.Request) -> web.Response:
    """Browser pings this every 15s while the page is open. Updates the
    global activity clock so the auto-shutdown task knows there's a live tab.
    Also accepts a `goodbye=true` flag from beforeunload sendBeacon — that
    just means "I'm closing, don't stay up on my account" (no immediate
    shutdown; the timer takes over).
    """
    global _last_activity
    body = {}
    if req.body_exists:
        try:
            body = await req.json()
        except json.JSONDecodeError:
            body = {}
    if body.get("goodbye"):
        # Backdate so the grace period expires sooner if no other tab pings in.
        _last_activity = time.monotonic() - max(0, HEARTBEAT_GRACE_SECONDS - 5)
    else:
        _last_activity = time.monotonic()
    sid = body.get("session_id") or req.headers.get("X-Session-Id", "")
    if sid and sid in sessions:
        sessions[sid].last_activity = _last_activity
    return web.json_response({"ok": True})


async def post_permission(req: web.Request) -> web.Response:
    try:
        body = await req.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON"}, status=400)
    sid = body.get("session_id") or req.headers.get("X-Session-Id", "")
    s = sessions.get(sid)
    if s is None:
        return web.json_response({"error": "unknown session"}, status=400)
    req_id = body.get("request_id")
    decision = body.get("decision")
    if decision not in ("allow", "always", "deny"):
        return web.json_response({"error": "invalid decision"}, status=400)
    fut = s.pending.pop(req_id, None)
    if fut is None or fut.done():
        return web.json_response({"error": "no pending request with that id"}, status=400)
    fut.set_result(decision)
    return web.json_response({"ok": True})


async def get_root(req: web.Request) -> web.Response:
    p = HERE / "index.html"
    if not p.exists():
        return web.Response(status=404, text="index.html missing")
    return web.Response(body=p.read_bytes(), content_type="text/html")


# ---------- Background eviction ----------

async def evict_idle_sessions(app: web.Application) -> None:
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        stale = [sid for sid, s in sessions.items()
                 if (now - s.last_activity) > SESSION_TTL_SECONDS]
        for sid in stale:
            log.info("evicting idle session %s", sid[:8])
            s = sessions.pop(sid, None)
            if s is not None:
                await s.close()


async def auto_shutdown_watcher(app: web.Application) -> None:
    """Self-terminate the server when no browser tab has heartbeated in
    HEARTBEAT_GRACE_SECONDS — i.e. the user closed the last tab.

    We give a startup grace so we don't shut down before the browser has
    had a chance to connect. We also skip shutdown while a turn is in
    flight (any session has an active SSE queue) so the model can finish
    its response uninterrupted.
    """
    global _last_activity
    booted = time.monotonic()
    log.info("auto-shutdown watchdog started (startup_grace=%ds, idle_grace=%ds)",
             HEARTBEAT_STARTUP_GRACE, HEARTBEAT_GRACE_SECONDS)
    while True:
        await asyncio.sleep(10)
        now = time.monotonic()
        if (now - booted) < HEARTBEAT_STARTUP_GRACE:
            continue
        if any(s.current_queue is not None for s in sessions.values()):
            _last_activity = now
            continue
        idle_for = now - _last_activity
        if idle_for > HEARTBEAT_GRACE_SECONDS:
            log.info("no heartbeat for %.0fs — shutting down", idle_for)
            os.kill(os.getpid(), signal.SIGTERM)
            return


async def on_startup(app: web.Application) -> None:
    global _last_activity
    _last_activity = time.monotonic()
    app["evictor"] = asyncio.create_task(evict_idle_sessions(app))
    app["watchdog"] = asyncio.create_task(auto_shutdown_watcher(app))


async def on_cleanup(app: web.Application) -> None:
    app["evictor"].cancel()
    app["watchdog"].cancel()
    for sid in list(sessions.keys()):
        s = sessions.pop(sid, None)
        if s is not None:
            await s.close()


# ---------- App factory & main ----------

def make_app() -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app.router.add_get("/", get_root)
    app.router.add_get("/api/config", get_config)
    app.router.add_post("/api/config", post_config)
    app.router.add_post("/api/session", post_session)
    app.router.add_get("/api/session/{sid}", get_session)
    app.router.add_post("/api/session/{sid}/new", post_session_new)
    app.router.add_post("/api/messages", post_messages)
    app.router.add_post("/api/permission", post_permission)
    app.router.add_post("/api/heartbeat", post_heartbeat)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    has_auth = export_auth_env()
    url = f"http://localhost:{PORT}/"
    log.info("Claude Local v2 running at %s", url)
    if has_auth:
        log.info("Auth ready (baseUrl=%s)", os.environ.get("ANTHROPIC_BASE_URL"))
    else:
        log.warning("Token not configured — Settings dialog will prompt the user")
    if "--no-open" not in sys.argv:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    web.run_app(
        make_app(),
        host="127.0.0.1",
        port=PORT,
        access_log=None,
        print=lambda *a, **k: None,  # silence aiohttp's banner
    )


if __name__ == "__main__":
    main()
