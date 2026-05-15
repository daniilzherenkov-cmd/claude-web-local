# claude-web-local

A tiny browser chat UI for Delivery Hero's LiteLLM Claude proxy. No login,
no install beyond Python (already on macOS), no data leaves your machine.

## Run it

**Double-click `ClaudeLocal.app`** in Finder. The browser opens to your
chat. To stop, right-click the Dock icon → Quit (or press Cmd+Q while
the icon is focused).

That's the whole experience. No Terminal window, no commands.

### First time only

macOS Gatekeeper blocks unsigned apps downloaded from the internet. To
bypass it the first time, **right-click `ClaudeLocal.app` → Open**, then
click "Open" in the security dialog. After that, double-click works
normally.

### Power-user alternatives

- **`launch.command`** — same thing, but opens a Terminal window so you
  can see server logs in real time. Useful for debugging.
- **`python3 server.py`** from a terminal in this folder — fully manual.

## First-time setup

If your shell already has `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`
exported (Claude Code users do), the chat is ready immediately.

Otherwise the page opens a Settings dialog asking for:
- **LiteLLM base URL** — get this from the dp-devinfra Slack channel
- **API token** — same place

Saved to `~/.claude-web/config.json` (mode 0600). Never sent anywhere
except your own LiteLLM proxy.

## Files

| File | Purpose |
|---|---|
| **`ClaudeLocal.app`** | Double-clickable macOS app. No Terminal. Recommended for non-tech users. |
| `launch.command` | Same as the app but opens a visible Terminal — useful for debugging. |
| `server.py` | ~180-line local proxy. Stdlib only, no `pip install`. Holds the token, streams the response. |
| `index.html` | Self-contained UI — HTML, CSS, JS, and `marked.js` all inlined. |
| `rebuild_app.sh` | Resyncs `server.py` + `index.html` into the `.app` bundle after edits. |
| `~/.claude-web/config.json` | Persistent token + base URL + last-used model. |
| `~/Library/Logs/ClaudeLocal.log` | Where the `.app` writes its server logs (since it has no Terminal). |

## Why a server (and not just an HTML file)?

The DH LiteLLM proxy sits behind Cloudflare, which blocks browser CORS
preflights (`OPTIONS /v1/messages` returns 403). A pure-`file://` page
can't reach it. The Python proxy is a thin shim that adds the auth
header on the server side, so the browser only ever talks to
`localhost:8765`.

Opening `index.html` directly via `file://` shows a red banner telling
you to use the launcher.

## Troubleshooting

- **"Could not load config from local server"** — the Python server
  isn't running. Re-run `launch.command`.
- **"Server returned 401"** — token expired or wrong. Open Settings
  (gear icon, top right) and paste a fresh one.
- **"Server returned 400: team not allowed to access model"** — your
  team doesn't have access to that model in LiteLLM. Pick another from
  the dropdown.
- **Port 8765 already in use** — set a different one:
  `CLAUDE_WEB_PORT=9000 ./launch.command`.

## Sharing with non-tech colleagues

Two options:

1. **Just the `.app`** — drag `ClaudeLocal.app` to a Slack DM or Drive
   folder. They drop it into `/Applications` (or anywhere), right-click
   → Open the first time, done. Self-contained: `server.py` and
   `index.html` live inside the bundle.
2. **The whole folder** — send `claude-web-local/` zipped. Gives them
   the README, the `.app`, and the editable source if they want to
   tinker.

After editing `server.py` or `index.html`, run `./rebuild_app.sh` to
sync those changes into the `.app` bundle before re-sharing.
