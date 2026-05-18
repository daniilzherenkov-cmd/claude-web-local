# claude-web-local (v2 — SDK build)

A browser UI for **Claude Code** running locally on your machine. Same model,
same skills, same MCP servers, same tools as Claude Code in your terminal —
just in a Chrome tab.

> Audience: anyone who already uses Claude Code (developers, data folks,
> technical PMs). Every Bash / Write / Edit goes through a browser-rendered
> approval card — same trust model as Claude Code's TUI prompts.
>
> The chat-only build for non-tech colleagues lives at the **`v1-chat-only`**
> tag and stays available unchanged.

## First-time setup

```sh
git clone https://github.com/daniilzherenkov-cmd/claude-web-local.git
cd claude-web-local
./build_venv.sh        # ~245 MB, takes a minute. One-time.
```

## Run it

**Double-click `ClaudeLocal.app`** in Finder. The browser opens to your
chat. To stop, right-click the Dock icon → Quit (or Cmd+Q while the icon
has focus).

That's the whole experience. No Terminal window, no commands.

### Gatekeeper, the first time only

macOS Gatekeeper blocks unsigned apps downloaded from the internet. To
bypass it the first time, **right-click `ClaudeLocal.app` → Open**, then
click "Open" in the security dialog. After that, double-click works
normally.

### Power-user alternatives

- **`launch.command`** — same thing, but opens a Terminal window so you
  can see server logs in real time. Useful for debugging.
- **`./ClaudeLocal.app/Contents/Resources/venv/bin/python server.py`** —
  fully manual, no `.app` involved.

## Auth

If your shell already has `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`
exported (Claude Code users do), you're ready immediately. The launcher
sources `~/.zshrc` and inherits them.

Otherwise the page opens a Settings dialog asking for:
- **LiteLLM base URL** — get this from the dp-devinfra Slack channel
- **API token** — same place

Saved to `~/.claude-web/config.json` (mode 0600). Never sent anywhere
except your own LiteLLM proxy.

## What you can ask

The model has **the full Claude Code toolset** — Read, Write, Edit, Bash,
Glob, Grep, WebFetch, Agent, Task, plus your installed skills (`data-analyst`,
`slides-from-data`, `frontend-design`, etc.) and MCP servers (Slack, gws, …).

Examples:
- *"What's in my `~/dev` folder?"* → `Bash` tool call → approval card → `ls -la ~/dev` runs
- *"Edit `~/notes.md` and add today's date"* → `Edit` tool call → approval card → diff applied
- *"Run my data-analyst skill on table X"* → skill loads, multiple tools may run
- *"Search Slack for messages about Y"* → Slack MCP tool

When the model wants to use a tool, you'll see an inline card with:
- The exact tool and inputs
- **Allow** (just this once), **Allow always** (auto-approve this tool for the rest of the chat), **Deny**

## Files

| File | Purpose |
|---|---|
| **`ClaudeLocal.app`** | Double-clickable macOS app. Recommended. |
| `launch.command` | Same as the app but with visible Terminal output (debugging). |
| `server.py` | aiohttp + asyncio server wrapping `claude-agent-sdk`. |
| `index.html` | Single-file UI (CSS, JS, `marked.js` all inlined). |
| `pyproject.toml` | Python deps: `claude-agent-sdk`, `aiohttp`. |
| `build_venv.sh` | Creates the bundled venv inside the `.app`. Run once after cloning. |
| `rebuild_app.sh` | Resyncs `server.py` + `index.html` + icon into the `.app` after edits. |
| `make_icon.py` | Regenerates the app icon from the DH favicon. |
| `~/.claude-web/config.json` | Persistent token + base URL. |
| `~/Library/Logs/ClaudeLocal.log` | Where the `.app` writes server logs. |

## How it actually works

`server.py` is an aiohttp app on `localhost:8765`. For each browser tab it
creates one `ClaudeSDKClient` (long-lived), which subprocesses the bundled
Claude Code CLI binary. User messages flow through `POST /api/messages`,
the SDK streams back typed events (text deltas, tool_use blocks, tool
results), and the server forwards them to the browser as SSE.

When the model wants to use a tool, the SDK calls our `can_use_tool`
callback. The callback puts a `permission_request` event on the SSE stream
and `await`s an `asyncio.Future`. The browser renders an Allow / Deny
card; clicking POSTs `/api/permission`, which resolves the future and
unblocks the SDK.

## Troubleshooting

- **"Claude Local's bundled Python environment is missing"** — run
  `./build_venv.sh`. The venv is git-ignored and must be built locally.
- **"Could not load config from local server"** — the server isn't running.
  Re-run `ClaudeLocal.app` or `launch.command`.
- **"Server returned 401"** — token expired or wrong. Open Settings (gear
  icon, top right) and paste a fresh one.
- **`API Error: 400 ExceededBudget`** — your LiteLLM monthly budget is up.
  Wait for reset or ping dp-devinfra.
- **"Unknown or expired session_id"** — server restarted while your tab
  was open. Reload the page to start a fresh session.
- **Port 8765 already in use** — `CLAUDE_WEB_PORT=9000 ./launch.command`.

